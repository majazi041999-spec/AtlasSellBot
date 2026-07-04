import asyncio
import base64
import binascii
import json
import logging
import re
import secrets
import time
import uuid
from datetime import datetime
from typing import Dict, List
from urllib.parse import quote, urlsplit, urlunsplit

from core.config import WEB_PORT
from core.database import (
    add_subscription_node,
    create_subscription_profile,
    delete_subscription_profile,
    get_active_subscription_profiles,
    get_expired_subscription_profiles,
    count_active_server_load,
    count_active_subscription_nodes_by_target,
    delete_subscription_node,
    get_available_subscription_node_configs,
    get_subscription_node_configs,
    get_setting,
    get_subscription_nodes,
    get_subscription_profile,
    get_subscription_profile_by_token,
    get_user_by_id,
    update_config,
    update_subscription_node,
    update_subscription_profile,
)
from core.xui_api import XUIClient, expiry_ms_from_days

logger = logging.getLogger(__name__)


def total_bytes(traffic_gb: float) -> int:
    return int(float(traffic_gb or 0) * 1024 ** 3)


def _as_int(value, default: int = 0) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return default


def _first_positive_int(*values) -> int:
    for value in values:
        parsed = _as_int(value)
        if parsed > 0:
            return parsed
    return 0


def _epoch_ms(value) -> int:
    parsed = _as_int(value)
    if 0 < parsed < 10_000_000_000:
        return parsed * 1000
    return parsed


def _parse_datetime_ms(value: str) -> int:
    raw = str(value or "").strip()
    if not raw:
        return 0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return int(datetime.strptime(raw[:26], fmt).timestamp() * 1000)
        except ValueError:
            pass
    return 0


def _derived_expire_from_duration(obj: Dict, now_ms: int, used_bytes: int = 0) -> int:
    duration_days = _as_int(obj.get("duration_days"))
    if duration_days <= 0:
        return 0
    if _as_int(obj.get("starts_on_first_use")) and used_bytes <= 0:
        return now_ms + duration_days * 86400000
    base_ms = _parse_datetime_ms(obj.get("first_use_at") or obj.get("created_at") or "")
    if base_ms <= 0:
        base_ms = now_ms
    return base_ms + duration_days * 86400000


def _resolve_expire_ms(obj: Dict, traffic: Dict | None = None, client: Dict | None = None,
                       now_ms: int | None = None, used_bytes: int = 0) -> int:
    traffic = traffic or {}
    client = client or {}
    expire_ms = _first_positive_int(
        traffic.get("expiryTime"),
        traffic.get("expiry_time"),
        traffic.get("expire"),
        traffic.get("expires"),
        client.get("expiryTime"),
        client.get("expiry_time"),
        client.get("expire"),
        client.get("expires"),
        obj.get("expire_timestamp"),
    )
    if expire_ms > 0:
        return _epoch_ms(expire_ms)
    return _derived_expire_from_duration(obj, now_ms or int(time.time() * 1000), used_bytes)


def _days_remaining(expire_ms: int, now_ms: int | None = None) -> int:
    expire_ms = _as_int(expire_ms)
    if expire_ms <= 0:
        return 0
    diff = expire_ms - (now_ms or int(time.time() * 1000))
    if diff <= 0:
        return 0
    return max(1, int((diff + 86399999) // 86400000))


def _remote_client_uuid(client: Dict, fallback: str = "") -> str:
    for key in ("id", "uuid"):
        raw = str(client.get(key) or "").strip()
        if raw:
            try:
                return str(uuid.UUID(raw))
            except Exception:
                pass
    for key in ("password", "auth"):
        raw = str(client.get(key) or "").strip()
        if raw:
            return raw
    raw = str(fallback or "").strip()
    if raw:
        try:
            return str(uuid.UUID(raw))
        except Exception:
            return raw
    return ""


def _uuid_from_link(link: str) -> str:
    raw = str(link or "").strip()
    lower = raw.lower()
    if lower.startswith("vless://"):
        value = raw[8:].split("@", 1)[0].strip()
        try:
            return str(uuid.UUID(value))
        except Exception:
            return ""
    if lower.startswith("vmess://"):
        payload = raw[8:].split("#", 1)[0].split("?", 1)[0]
        payload += "=" * (-len(payload) % 4)
        try:
            decoded = base64.urlsafe_b64decode(payload.encode()).decode("utf-8", "ignore")
        except Exception:
            try:
                decoded = base64.b64decode(payload.encode()).decode("utf-8", "ignore")
            except Exception:
                return ""
        try:
            value = json.loads(decoded).get("id")
            return str(uuid.UUID(str(value or "")))
        except Exception:
            return ""
    return ""


async def _remote_identity_and_link(cli: XUIClient, inbound_id: int, email: str, fallback_uuid: str) -> tuple[int, str, str]:
    found = await cli.find_client(email=email)
    remote_client = (found or {}).get("client") or {}
    remote_uuid = _remote_client_uuid(remote_client, fallback_uuid)
    remote_inbound = int((found or {}).get("inbound_id") or inbound_id)
    link = await cli.get_client_link(remote_inbound, email) or ""
    link_uuid = _uuid_from_link(link)
    if link_uuid:
        remote_uuid = link_uuid
    elif not remote_uuid:
        remote_uuid = _remote_client_uuid({}, fallback_uuid)
    return remote_inbound, remote_uuid, link


def public_base_url() -> str:
    raw = ""
    # This is async in settings, so callers use public_base_url_async when possible.
    return raw


async def public_base_url_async() -> str:
    base = (await get_setting("public_base_url", "")).strip().rstrip("/")
    if base:
        return base
    domain = (await get_setting("panel_domain", "")).strip().strip("/").lower()
    if domain:
        return f"https://{domain}"
    return f"http://YOUR_SERVER_IP:{WEB_PORT}"


async def subscription_url(token: str) -> str:
    return f"{await public_base_url_async()}/sub/{token}"


async def multi_sub_enabled_for_single_purchase(bulk_count: int = 1, is_renewal: bool = False) -> bool:
    if await get_setting("multi_sub_enabled", "0") != "1":
        return False
    if is_renewal or int(bulk_count or 1) != 1:
        return False
    return True


def subscription_error_message(error: str) -> str:
    raw = str(error or "").strip()
    if raw == "public_base_url_not_configured":
        return "آدرس عمومی ساب تنظیم نشده است. در پنل سابسکریپشن، public_base_url را تنظیم کنید."
    if raw == "no_subscription_nodes_configured":
        return "هیچ نود قابل استفاده‌ای برای سابسکریپشن تعریف نشده است."
    if raw.startswith("not_enough_subscription_nodes:"):
        return f"تعداد نودهای قابل استفاده سابسکریپشن کافی نیست ({raw.split(':', 1)[1]})."
    if raw.startswith("created_nodes_below_minimum:"):
        return f"تعداد نودهای ساخته‌شده به حداقل لازم نرسید: {raw}"
    if raw == "config_expiry_unknown":
        return "تاریخ انقضای کانفیگ قبلی قابل تشخیص نبود؛ برای جلوگیری از ساخت سرویس نامحدود اشتباه، تبدیل انجام نشد. لطفاً اول تاریخ سرویس قبلی را در پنل اصلاح کنید."
    return raw or "خطای نامشخص در ساخت سابسکریپشن"


def subscription_error_message(error: str) -> str:
    raw = str(error or "").strip()
    if raw == "public_base_url_not_configured":
        return "آدرس عمومی ساب تنظیم نشده است. در پنل سابسکریپشن، public_base_url را تنظیم کنید."
    if raw == "no_subscription_nodes_configured":
        return "هیچ نود قابل استفاده‌ای برای سابسکریپشن تعریف نشده است."
    if raw.startswith("not_enough_subscription_nodes:"):
        return f"تعداد نودهای قابل استفاده سابسکریپشن کافی نیست ({raw.split(':', 1)[1]})."
    if raw.startswith("created_nodes_below_minimum:"):
        return f"تعداد نودهای ساخته‌شده به حداقل لازم نرسید: {raw}"
    if raw == "old_config_disable_failed":
        return "ساب جدید ساخته شد، اما خاموش‌کردن یا حذف کانفیگ قبلی روی سرور قدیمی ناموفق بود. لطفاً اتصال سرور قدیمی یا دسترسی API آن را بررسی کنید."
    if raw == "config_not_active":
        return "این کانفیگ فعال نیست یا قبلاً تبدیل/غیرفعال شده است."
    if raw == "no_remaining_traffic":
        return "حجم باقی‌مانده این کانفیگ تمام شده است."
    if raw == "config_expired":
        return "زمان این کانفیگ منقضی شده است."
    if raw == "config_expiry_unknown":
        return "تاریخ انقضای کانفیگ قبلی قابل تشخیص نبود؛ برای جلوگیری از ساخت سرویس نامحدود اشتباه، تبدیل انجام نشد. لطفاً اول تاریخ سرویس قبلی را در پنل اصلاح کنید."
    return raw or "خطای نامشخص در ساخت سابسکریپشن"


def _label_subscription_link(link: str, label: str) -> str:
    link = (link or "").strip()
    label = (label or "").strip()
    if not link or not label:
        return link
    if link.lower().startswith("vmess://"):
        payload = link[8:].split("#", 1)[0].split("?", 1)[0]
        payload += "=" * (-len(payload) % 4)
        try:
            decoded = base64.urlsafe_b64decode(payload.encode()).decode("utf-8", "ignore")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            try:
                decoded = base64.b64decode(payload.encode()).decode("utf-8", "ignore")
            except (binascii.Error, UnicodeDecodeError, ValueError):
                return link
        try:
            obj = json.loads(decoded)
        except Exception:
            return link
        obj["ps"] = label
        encoded = base64.b64encode(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()).decode()
        return f"vmess://{encoded}"

    try:
        parts = urlsplit(link)
        if not parts.scheme:
            return link
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, quote(label, safe="")))
    except Exception:
        return link


def _clean_display_part(value: str, max_len: int = 32) -> str:
    value = " ".join(str(value or "").replace("_", " ").split())
    if len(value) <= max_len:
        return value
    return value[: max(1, max_len - 1)].rstrip() + "…"


async def _subscription_node_display_label(profile: Dict, node: Dict, index: int) -> str:
    custom_name = _clean_display_part(profile.get("name") or "", 30)
    node_name = _clean_display_part(
        node.get("node_label") or node.get("server_name") or f"Node {index}",
        28,
    )
    # The remark per server must stay short: lead with the user's chosen name
    # (so it's the first thing they see in v2rayNG's server list), then the
    # server name to tell servers apart. The brand never goes here — it lives
    # only in the dedicated info config so remarks don't get long/cluttered.
    if custom_name:
        return f"{custom_name} | {node_name}"[:90]
    return node_name[:90]


def _decode_b64_json(value: str) -> Dict | None:
    raw = (value or "").strip().split("#", 1)[0].split("?", 1)[0]
    if not raw:
        return None
    raw += "=" * (-len(raw) % 4)
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            decoded = decoder(raw.encode()).decode("utf-8", "ignore")
            obj = json.loads(decoded)
            return obj if isinstance(obj, dict) else None
        except Exception:
            continue
    return None


def _subscription_link_is_complete(link: str) -> bool:
    raw = (link or "").strip()
    if not raw or "://" not in raw:
        return False
    scheme = raw.split("://", 1)[0].lower()
    if scheme == "vmess":
        obj = _decode_b64_json(raw[8:])
        return bool(obj and obj.get("add") and obj.get("port") and _uuid_from_link(raw))
    if scheme == "vless":
        try:
            parts = urlsplit(raw)
            port = parts.port
        except Exception:
            return False
        return bool(parts.hostname and port and _uuid_from_link(raw))
    if scheme == "trojan":
        try:
            parts = urlsplit(raw)
            port = parts.port
        except Exception:
            return False
        return bool(parts.hostname and port and parts.username)
    if scheme == "ss":
        try:
            parts = urlsplit(raw)
            port = parts.port
        except Exception:
            return False
        return bool(parts.hostname and port and parts.netloc)
    return False


def _link_dedupe_key(link: str) -> str:
    raw = (link or "").strip()
    scheme = raw.split("://", 1)[0].lower() if "://" in raw else ""
    if scheme == "vmess":
        obj = _decode_b64_json(raw[8:]) or {}
        return f"vmess:{obj.get('id') or ''}:{obj.get('add') or ''}:{obj.get('port') or ''}"
    try:
        parts = urlsplit(raw)
        port = parts.port or ""
        username = parts.username or ""
        return f"{parts.scheme.lower()}:{username}@{(parts.hostname or '').lower()}:{port}:{parts.path}"
    except Exception:
        return raw.split("#", 1)[0]


def _dedupe_complete_links(links: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for link in links:
        link = (link or "").strip()
        if not _subscription_link_is_complete(link):
            if link:
                logger.warning("Skipping incomplete subscription link")
            continue
        key = _link_dedupe_key(link)
        if key in seen:
            logger.warning("Skipping duplicate subscription link")
            continue
        seen.add(key)
        out.append(link)
    return out


async def _ensure_node_link(node: Dict, force_refresh: bool | None = None) -> str:
    link = (node.get("link") or "").strip()
    if force_refresh is None:
        force_refresh = await get_setting("sub_force_local_links_on_render", "1") == "1"
    if _subscription_link_is_complete(link) and not force_refresh:
        return link

    cli = XUIClient(
        node["server_url"],
        node["srv_user"],
        node["srv_pass"],
        node.get("sub_path") or "",
        node.get("srv_api_token", ""),
    )
    try:
        inbound_id, remote_uuid, refreshed = await _remote_identity_and_link(
            cli,
            int(node.get("inbound_id") or 0),
            node.get("email") or "",
            node.get("uuid") or "",
        )
        refreshed = (refreshed or "").strip()
        if _subscription_link_is_complete(refreshed):
            await update_subscription_node(node["id"], inbound_id=inbound_id, uuid=remote_uuid, link=refreshed)
            logger.info("Repaired subscription node link id=%s", node.get("id"))
            return refreshed
        logger.warning("Could not repair incomplete subscription node link id=%s", node.get("id"))
    except Exception as e:
        logger.warning("Subscription node link repair failed id=%s: %s", node.get("id"), e)
    finally:
        await cli.close()
    return ""


def _fake_info_link(label: str, index: int = 1) -> str:
    label = (label or "").strip()
    if not label:
        return ""
    fake_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"atlas-sub-info:{index}:{label}"))
    return (
        f"vless://{fake_uuid}@127.0.0.1:1"
        f"?encryption=none&type=tcp&security=none#{quote(label[:180], safe='')}"
    )


def _parse_db_datetime(value: str) -> datetime | None:
    raw = (value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw[:26], fmt)
        except Exception:
            pass
    return None


def _format_info_template(template: str, values: Dict[str, str]) -> list[str]:
    lines = []
    for raw_line in (template or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            line = line.format(**values)
        except Exception:
            pass
        if line:
            lines.append(line)
    return lines


async def _subscription_info_links(profile: Dict, used: int, total: int, active_node_count: int) -> list[str]:
    if await get_setting("sub_info_enabled", "1") != "1":
        return []
    if await get_setting("sub_info_render_as_links", "1") != "1":
        return []

    now_ms = int(time.time() * 1000)
    expire_ms = int(profile.get("expire_timestamp") or 0)
    days_left = max(0, int((expire_ms - now_ms) / 86400000)) if expire_ms > 0 else 0
    created = _parse_db_datetime(profile.get("created_at") or "")
    days_elapsed = max(0, (datetime.now() - created).days) if created else 0
    expire_date = datetime.fromtimestamp(expire_ms / 1000).strftime("%Y-%m-%d") if expire_ms > 0 else "نامحدود"
    remaining = max(0, total - used) if total > 0 else 0
    percent = min(100, int(used / total * 100)) if total > 0 else 0
    brand = await get_setting("ui.brand_name", "Atlas Account")

    values = {
        "brand": brand,
        "traffic_gb": f"{float(profile.get('traffic_gb') or 0):g}",
        "duration_days": str(int(profile.get("duration_days") or 0)),
        "used": _fmt_bytes_short(used),
        "remaining": _fmt_bytes_short(remaining),
        "total": _fmt_bytes_short(total),
        "percent": str(percent),
        "days_left": str(days_left),
        "days_elapsed": str(days_elapsed),
        "expire_date": expire_date,
        "nodes": str(active_node_count),
        "status": "فعال" if int(profile.get("is_active") or 0) else "غیرفعال",
    }

    template = await get_setting(
        "sub_info_template",
        "📊 حجم کل: {traffic_gb}GB | مصرف: {used} | باقی: {remaining}\n📅 باقی‌مانده: {days_left} روز | سپری‌شده: {days_elapsed} روز",
    )
    labels = _format_info_template(template, values)
    # Wholesale customers can opt to hide our brand from their subscription link,
    # so they can resell it under their own name. Skip the brand line entirely
    # when the owning user has that flag set.
    if not await _user_hide_brand(profile):
        brand_template = await get_setting("sub_brand_template", "📣 {brand}")
        labels = labels + _format_info_template(brand_template, values)
    return [_fake_info_link(label, i + 1) for i, label in enumerate(labels) if label]


async def _user_hide_brand(profile: Dict) -> bool:
    """True when the subscription's owner asked to hide our brand from their link."""
    uid = profile.get("user_id")
    if not uid:
        return False
    try:
        u = await get_user_by_id(int(uid))
    except Exception:
        return False
    return bool(u and int(u.get("hide_brand") or 0))


async def _subscription_expired_notice_links(profile: Dict) -> list[str]:
    """Fake info configs shown INSTEAD of real servers once a sub is finished.

    A finished sub must never keep leftover servers in the user's app; we replace
    the whole list with a clear 'expired — renew from the bot' notice so people
    know what happened and how to fix it (and don't think the service is broken).
    """
    brand = await get_setting("ui.brand_name", "Atlas Account")
    now_ms = int(time.time() * 1000)
    expire_ms = int(profile.get("expire_timestamp") or 0)
    total = total_bytes(profile.get("traffic_gb") or 0)
    used = int(profile.get("used_bytes") or 0)
    out_of_quota = total > 0 and used >= total
    out_of_time = expire_ms > 0 and expire_ms <= now_ms
    if out_of_quota and not out_of_time:
        reason = "حجم سرویس شما تمام شد"
    elif out_of_time and not out_of_quota:
        reason = "زمان سرویس شما تمام شد"
    else:
        reason = "سرویس شما به پایان رسید"
    template = await get_setting(
        "sub_expired_link_template",
        "⛔️ {reason} — برای ادامه از ربات «تمدید» کنید 🤖",
    )
    values = {"brand": brand, "reason": reason}
    labels = _format_info_template(template, values) or [f"⛔️ {reason} — از ربات تمدید کنید"]
    return [_fake_info_link(label, i + 1) for i, label in enumerate(labels) if label]


def _fmt_bytes_short(value: int) -> str:
    value = int(value or 0)
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(value)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    if idx == 0:
        return f"{int(size)}{units[idx]}"
    return f"{size:.1f}{units[idx]}"


async def pick_subscription_nodes(count: int) -> List[Dict]:
    nodes = await get_available_subscription_node_configs()
    ranked = []
    for node in nodes:
        server_used = await count_active_server_load(node["server_id"])
        node_used = await count_active_subscription_nodes_by_target(node["server_id"], node["inbound_id"])
        node_cap = int(node.get("max_active_profiles") or 0)
        ratio = (node_used / node_cap) if node_cap > 0 else 0
        ranked.append((int(node.get("priority") or 100), node_used, ratio, server_used, int(node["id"]), node))
    ranked.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4]))
    return [item[5] for item in ranked[: max(1, int(count or 1))]]


async def create_profile_for_order(user: Dict, order: Dict, traffic_gb: float, duration_days: int) -> Dict:
    node_count = max(2, min(8, int(await get_setting("multi_sub_node_count", "4") or 4)))
    nodes = await pick_subscription_nodes(node_count)
    min_nodes = max(2, min(node_count, int(await get_setting("multi_sub_min_nodes", "2") or 2)))
    if not nodes:
        return {"ok": False, "error": "no_subscription_nodes_configured"}
    if len(nodes) < min_nodes:
        return {"ok": False, "error": f"not_enough_subscription_nodes:{len(nodes)}/{min_nodes}"}

    token = secrets.token_urlsafe(24)
    sub_url = await subscription_url(token)
    if "YOUR_SERVER_IP" in sub_url:
        return {"ok": False, "error": "public_base_url_not_configured"}
    email = f"sub_{user['telegram_id']}_{int(time.time())}_{secrets.token_hex(3)}"
    display_name = str((order or {}).get("custom_config_name") or "").strip()

    # Count duration from first use? Then create with no time-expiry yet; the
    # timer is armed on the first subscription fetch (see render_subscription).
    first_use = await get_setting("sub_start_on_first_use", "1") == "1"
    if first_use:
        expire_ms = 0
        node_expire_days = 0  # unlimited time until first use; traffic still capped
    else:
        expire_ms = expiry_ms_from_days(duration_days)
        node_expire_days = duration_days

    profile_id = await create_subscription_profile(
        user["id"], order["id"], token, email, traffic_gb, duration_days, expire_ms,
        name=display_name, starts_on_first_use=1 if first_use else 0,
    )
    created_remote: list[tuple[Dict, int, str, str]] = []
    failures: list[str] = []

    try:
        for node in nodes:
            inbound_id = int(node.get("inbound_id") or 1)
            client_uuid = str(uuid.uuid4())
            node_email = f"{email}_n{node['id']}"
            cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
            try:
                ok = await cli.add_client(inbound_id, client_uuid, node_email, traffic_gb, node_expire_days, starts_on_first_use=False)
                if not ok:
                    failures.append(f"{node.get('server_name') or node['server_id']}#{inbound_id}:add_failed")
                    continue
                inbound_id, client_uuid, link = await _remote_identity_and_link(cli, inbound_id, node_email, client_uuid)
                if not _subscription_link_is_complete(link):
                    failures.append(f"{node.get('server_name') or node['server_id']}#{inbound_id}:link_failed")
                    try:
                        await cli.delete_client(inbound_id, client_uuid, node_email)
                    except Exception:
                        pass
                    continue
                await add_subscription_node(profile_id, node["server_id"], inbound_id, client_uuid, node_email, link)
                created_remote.append((node, inbound_id, client_uuid, node_email))
            except Exception as e:
                failures.append(f"{node.get('server_name') or node['server_id']}#{inbound_id}:{e}")
            finally:
                await cli.close()

        if len(created_remote) < min_nodes:
            detail = ",".join(failures[:6])
            raise RuntimeError(f"created_nodes_below_minimum:{len(created_remote)}/{min_nodes}" + (f";{detail}" if detail else ""))

        return {
            "ok": True,
            "profile_id": profile_id,
            "token": token,
            "email": email,
            "url": sub_url,
            "nodes": len(created_remote),
            "expire_ms": expire_ms,
        }
    except Exception as e:
        for node, inbound_id, client_uuid, node_email in created_remote:
            cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
            try:
                await cli.delete_client(inbound_id, client_uuid, node_email)
            except Exception:
                pass
            finally:
                await cli.close()
        await delete_subscription_profile(profile_id)
        return {"ok": False, "error": str(e)}


async def create_test_subscription(user: Dict, traffic_gb: float, duration_days: int, name: str = "اکانت تست") -> Dict:
    """Provision a free trial as a multi-server subscription (no single server).

    Reuses the standard order-provisioning path with a synthetic order so trials
    behave exactly like paid subs (first-use timer, node failover, lifecycle)."""
    fake_order = {"id": 0, "custom_config_name": name}
    return await create_profile_for_order(user, fake_order, traffic_gb, duration_days)


async def create_profile_from_config(user: Dict, cfg: Dict) -> Dict:
    """Convert one active legacy config to a managed subscription profile."""
    if not cfg or not int(cfg.get("is_active") or 0):
        return {"ok": False, "error": "config_not_active"}

    old_cli = XUIClient(cfg["server_url"], cfg["srv_user"], cfg["srv_pass"], cfg.get("sub_path") or "", cfg.get("srv_api_token", ""))
    try:
        traffic = await old_cli.get_client_traffic(cfg["email"])
        found = await old_cli.find_client(cfg.get("email", ""), cfg.get("uuid", ""))
        remote_client = (found or {}).get("client") or {}
    finally:
        await old_cli.close()

    total = _first_positive_int(
        (traffic or {}).get("total"),
        (traffic or {}).get("totalGB"),
        remote_client.get("totalGB"),
        int(float(cfg.get("traffic_gb") or 0) * 1024 ** 3),
    )
    used = int((traffic or {}).get("down") or 0) + int((traffic or {}).get("up") or 0)
    remaining_bytes = max(0, total - used)
    remaining_gb = remaining_bytes / (1024 ** 3)
    if total > 0 and remaining_bytes <= 0:
        return {"ok": False, "error": "no_remaining_traffic"}

    now_ms = int(time.time() * 1000)
    expire_ms = _resolve_expire_ms(cfg, traffic, remote_client, now_ms, used)
    if expire_ms > 0 and expire_ms <= now_ms:
        return {"ok": False, "error": "config_expired"}
    if expire_ms <= 0:
        return {"ok": False, "error": "config_expiry_unknown"}
    remaining_days = _days_remaining(expire_ms, now_ms)

    node_count = max(2, min(8, int(await get_setting("multi_sub_node_count", "4") or 4)))
    nodes = await pick_subscription_nodes(node_count)
    min_nodes = max(2, min(node_count, int(await get_setting("multi_sub_min_nodes", "2") or 2)))
    if not nodes:
        return {"ok": False, "error": "no_subscription_nodes_configured"}
    if len(nodes) < min_nodes:
        return {"ok": False, "error": f"not_enough_subscription_nodes:{len(nodes)}/{min_nodes}"}

    token = secrets.token_urlsafe(24)
    sub_url = await subscription_url(token)
    if "YOUR_SERVER_IP" in sub_url:
        return {"ok": False, "error": "public_base_url_not_configured"}

    base_email = str(cfg.get("email") or f"legacy_{user['telegram_id']}").replace(" ", "_")
    email = f"sub_{base_email}_{int(time.time())}_{secrets.token_hex(3)}"[:96]
    display_name = str(cfg.get("email") or "").strip()
    profile_id = await create_subscription_profile(
        user["id"], 0, token, email, remaining_gb, remaining_days, expire_ms, name=display_name,
    )
    created_remote: list[tuple[Dict, int, str, str]] = []
    failures: list[str] = []

    try:
        for node in nodes:
            inbound_id = int(node.get("inbound_id") or 1)
            client_uuid = str(uuid.uuid4())
            node_email = f"{email}_n{node['id']}"[:120]
            cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
            try:
                ok = await cli.add_client(inbound_id, client_uuid, node_email, remaining_gb, remaining_days, starts_on_first_use=False)
                if ok and expire_ms > 0:
                    ok = await cli.update_client(inbound_id, client_uuid, node_email, remaining_gb, expire_ms, True)
                if not ok:
                    failures.append(f"{node.get('server_name') or node['server_id']}#{inbound_id}:add_failed")
                    continue
                inbound_id, client_uuid, link = await _remote_identity_and_link(cli, inbound_id, node_email, client_uuid)
                if not _subscription_link_is_complete(link):
                    failures.append(f"{node.get('server_name') or node['server_id']}#{inbound_id}:link_failed")
                    try:
                        await cli.delete_client(inbound_id, client_uuid, node_email)
                    except Exception:
                        pass
                    continue
                await add_subscription_node(profile_id, node["server_id"], inbound_id, client_uuid, node_email, link)
                created_remote.append((node, inbound_id, client_uuid, node_email))
            except Exception as e:
                failures.append(f"{node.get('server_name') or node['server_id']}#{inbound_id}:{e}")
            finally:
                await cli.close()

        if len(created_remote) < min_nodes:
            detail = ",".join(failures[:6])
            raise RuntimeError(f"created_nodes_below_minimum:{len(created_remote)}/{min_nodes}" + (f";{detail}" if detail else ""))

        old_cli = XUIClient(cfg["server_url"], cfg["srv_user"], cfg["srv_pass"], cfg.get("sub_path") or "", cfg.get("srv_api_token", ""))
        try:
            disabled = await old_cli.update_client(cfg["inbound_id"], cfg["uuid"], cfg["email"], float(cfg.get("traffic_gb") or 0), expire_ms, False)
            old_action = "disabled"
            if not disabled:
                disabled = await old_cli.delete_client(cfg["inbound_id"], cfg["uuid"], cfg.get("email", ""))
                old_action = "deleted" if disabled else "failed"
        finally:
            await old_cli.close()
        if not disabled:
            raise RuntimeError("old_config_disable_failed")

        await update_config(int(cfg["id"]), is_active=0, expire_timestamp=expire_ms)
        return {
            "ok": True,
            "profile_id": profile_id,
            "token": token,
            "email": email,
            "url": sub_url,
            "nodes": len(created_remote),
            "traffic_gb": remaining_gb,
            "duration_days": remaining_days,
            "expire_ms": expire_ms,
            "used_bytes": used,
            "remaining_bytes": remaining_bytes,
            "old_config_action": old_action,
        }
    except Exception as e:
        for node, inbound_id, client_uuid, node_email in created_remote:
            cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
            try:
                await cli.delete_client(inbound_id, client_uuid, node_email)
            except Exception:
                pass
            finally:
                await cli.close()
        await delete_subscription_profile(profile_id)
        return {"ok": False, "error": str(e)}


# Tokens with an in-flight background sync, to avoid piling up duplicate work
# when a client polls the subscription URL frequently.
_inflight_render_sync: set[str] = set()


async def _background_render_sync(token: str) -> None:
    """Heavy reconciliation (usage sync + node ensure) done OFF the request path.

    Rendering the subscription must stay fast; this keeps usage/links fresh in
    the background so the next fetch already has up-to-date data."""
    if token in _inflight_render_sync:
        return
    _inflight_render_sync.add(token)
    try:
        profile = await get_subscription_profile_by_token(token)
        if not profile:
            return
        await sync_profile_usage(profile)
        fresh = await get_subscription_profile_by_token(token)
        if fresh and int(fresh.get("is_active") or 0):
            await ensure_subscription_profile_nodes(fresh, force_refresh=False)
    except Exception as e:
        logger.warning("background subscription sync failed: %s", e)
    finally:
        _inflight_render_sync.discard(token)


async def render_subscription(token: str) -> tuple[str, Dict[str, int]] | None:
    """Serve the subscription body FAST.

    Heavy X-UI reconciliation is intentionally NOT done inline here — it caused
    request timeouts (every client poll triggered writes to every node on every
    server). Instead we serve cached links from the DB, do a cheap DB-only
    expiry/quota check, and kick off the heavy sync in the background.
    """
    profile = await get_subscription_profile_by_token(token)
    if not profile:
        return None

    now_ms = int(time.time() * 1000)

    # First-use start: the very first fetch arms the timer. We set the expiry in
    # the DB immediately (fast) and let the background sync push it to the nodes.
    if int(profile.get("starts_on_first_use") or 0) and int(profile.get("first_use_at") or 0) <= 0:
        duration_days = _as_int(profile.get("duration_days"))
        new_expire = now_ms + duration_days * 86400000 if duration_days > 0 else 0
        await update_subscription_profile(
            profile["id"], first_use_at=now_ms, expire_timestamp=new_expire,
        )
        profile["first_use_at"] = now_ms
        profile["expire_timestamp"] = new_expire
        asyncio.create_task(_background_render_sync(token))

    expire_ms = int(profile.get("expire_timestamp") or 0)
    used = int(profile.get("used_bytes") or 0)
    total = total_bytes(profile.get("traffic_gb") or 0)
    db_expired = (expire_ms > 0 and expire_ms <= now_ms) or (total > 0 and used >= total)

    if not int(profile.get("is_active") or 0) or db_expired:
        # Out of quota/time (or disabled): do NOT serve any real servers. Instead
        # of returning an empty list — which makes apps keep showing the last
        # cached servers, so some stay "alive" with no explanation — we serve a
        # single clear "expired, renew from the bot" notice that replaces the
        # whole list. Reconcile (disable remote nodes) in the background.
        if db_expired and int(profile.get("is_active") or 0):
            asyncio.create_task(_background_render_sync(token))
        notice = _dedupe_complete_links(await _subscription_expired_notice_links(profile))
        if not notice:
            return None
        body = base64.b64encode("\n".join(notice).encode()).decode()
        expire = int(expire_ms / 1000) if expire_ms > 0 else 0
        title = str(profile.get("name") or "").strip()
        return body, {"upload": 0, "download": used, "total": total, "expire": expire, "title": title}

    nodes = await get_subscription_nodes(profile["id"])
    links = []
    active_count = 0
    for n in nodes:
        if not int(n.get("is_active") or 0):
            continue
        raw_link = (n.get("link") or "").strip()
        if not _subscription_link_is_complete(raw_link):
            # Only broken/missing cached links are repaired inline, and only
            # with a tight timeout so one slow/down server can't stall the page.
            try:
                raw_link = await asyncio.wait_for(_ensure_node_link(n, force_refresh=False), timeout=8)
            except Exception:
                raw_link = ""
        if not raw_link:
            continue
        label = await _subscription_node_display_label(profile, n, active_count + 1)
        link = _label_subscription_link(raw_link, label)
        if _subscription_link_is_complete(link):
            active_count += 1
            links.append(link)

    expire = int(expire_ms / 1000) if expire_ms > 0 else 0
    info_links = await _subscription_info_links(profile, used, total, active_count)
    # Info/brand lines go FIRST so the usage + remaining-days summary sits at the
    # top of the user's server list instead of being buried under the servers.
    links = _dedupe_complete_links(info_links + links)
    body = base64.b64encode("\n".join(links).encode()).decode()

    # Keep data fresh without blocking the response.
    if await get_setting("sub_info_sync_on_render", "1") == "1":
        asyncio.create_task(_background_render_sync(token))

    title = str(profile.get("name") or "").strip()
    return body, {"upload": 0, "download": used, "total": total, "expire": expire, "title": title}


async def ensure_subscription_profile_nodes(profile: Dict, force_refresh: bool = False) -> Dict:
    """Create missing clients for newly configured subscription nodes."""
    if not profile or not int(profile.get("is_active") or 0):
        return {"created": 0, "skipped": 0, "failed": 0}

    expire_ms = int(profile.get("expire_timestamp") or 0)
    now_ms = int(time.time() * 1000)
    if expire_ms > 0 and expire_ms <= now_ms:
        return {"created": 0, "skipped": 0, "failed": 0}

    existing_nodes = await get_subscription_nodes(profile["id"])
    existing_by_email = {str(node.get("email") or ""): node for node in existing_nodes}
    configured_nodes = await get_subscription_node_configs(active_only=True)

    # Orphan cleanup: a subscription node whose underlying node CONFIG was deleted
    # from the panel must be removed from the user's sub entirely (remote client +
    # local row). Each node email ends with `_n{config_id}`; if that config id no
    # longer exists, it's an orphan. Without this, a "removed" server lingers in
    # every sub link (just relabelled to its raw server name).
    #
    # SAFETY: only prune when at least one node config still exists. If the config
    # table is empty (everything deleted, or a transient read), we must NOT wipe
    # every user's servers — treat it as a misconfiguration and skip pruning.
    all_config_ids = {int(c["id"]) for c in await get_subscription_node_configs(active_only=False)}
    removed = 0
    for node in (existing_nodes if all_config_ids else []):
        email = str(node.get("email") or "")
        m = re.search(r"_n(\d+)$", email)
        cfg_id = int(m.group(1)) if m else 0
        if cfg_id and cfg_id not in all_config_ids:
            cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
            try:
                await cli.delete_client(int(node.get("inbound_id") or 0), node.get("uuid") or "", email)
            except Exception as e:
                logger.warning("orphan node remote delete failed profile=%s node=%s: %s", profile.get("id"), node.get("id"), e)
            finally:
                await cli.close()
            try:
                await delete_subscription_node(int(node["id"]))
                removed += 1
                existing_by_email.pop(email, None)
            except Exception as e:
                logger.warning("orphan node db delete failed profile=%s node=%s: %s", profile.get("id"), node.get("id"), e)

    missing_nodes = []
    refresh_nodes = []
    move_nodes = []
    for node in configured_nodes:
        node_email = f"{profile['email']}_n{node['id']}"[:120]
        existing = existing_by_email.get(node_email)
        if not existing:
            missing_nodes.append(node)
        elif int(existing.get("server_id") or 0) != int(node.get("server_id") or 0) or int(existing.get("inbound_id") or 0) != int(node.get("inbound_id") or 0):
            move_nodes.append((node, existing))
        elif force_refresh or not existing.get("link") or not int(existing.get("is_active") or 0):
            refresh_nodes.append((node, existing))
    if not missing_nodes and not refresh_nodes and not move_nodes:
        return {"created": 0, "refreshed": 0, "verified": 0, "moved": 0, "removed": removed, "skipped": 0, "failed": 0}

    used = int(profile.get("used_bytes") or 0)
    total = total_bytes(profile.get("traffic_gb") or 0)
    remaining = max(0, total - used) if total > 0 else total
    if total > 0 and remaining <= 0:
        await update_subscription_profile(profile["id"], is_active=0)
        await set_nodes_enabled(profile["id"], False)
        return {"created": 0, "refreshed": 0, "verified": 0, "moved": 0, "skipped": len(missing_nodes) + len(refresh_nodes) + len(move_nodes), "failed": 0}

    traffic_gb = float(profile.get("traffic_gb") or 0)
    if total > 0:
        traffic_gb = max(0.1, remaining / (1024 ** 3))
    if traffic_gb <= 0:
        return {"created": 0, "refreshed": 0, "verified": 0, "moved": 0, "skipped": len(missing_nodes) + len(refresh_nodes) + len(move_nodes), "failed": 0}

    duration_days = _days_remaining(expire_ms, now_ms)
    created = refreshed = verified = moved = failed = 0
    errors: list[str] = []
    for node, existing in move_nodes:
        inbound_id = int(node.get("inbound_id") or 1)
        client_uuid = str(existing.get("uuid") or uuid.uuid4())
        node_email = f"{profile['email']}_n{node['id']}"[:120]
        cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
        try:
            added = await cli.add_client(inbound_id, client_uuid, node_email, traffic_gb, duration_days, starts_on_first_use=False)
            ok = bool(added)
            if added and expire_ms > 0:
                updated = await cli.update_client(inbound_id, client_uuid, node_email, traffic_gb, expire_ms, True)
                if not updated:
                    logger.warning("subscription moved node exact-expiry update failed but add succeeded profile=%s node=%s/%s email=%s", profile.get("id"), node.get("server_id"), inbound_id, node_email)
            if not added:
                found = await cli.find_client(email=node_email)
                remote_client = (found or {}).get("client") or {}
                remote_uuid = _remote_client_uuid(remote_client, client_uuid)
                remote_inbound = int((found or {}).get("inbound_id") or inbound_id)
                if remote_client and remote_uuid:
                    client_uuid = remote_uuid
                    inbound_id = remote_inbound or inbound_id
                    ok = await cli.update_client(inbound_id, client_uuid, node_email, traffic_gb, expire_ms, True)
            if not ok:
                failed += 1
                detail = getattr(cli, "last_error", "") or "unknown"
                errors.append(f"move_failed:p{profile.get('id')}:node{node.get('server_id')}/{inbound_id}:{detail}")
                continue
            inbound_id, client_uuid, link = await _remote_identity_and_link(cli, inbound_id, node_email, client_uuid)
            if not _subscription_link_is_complete(link):
                failed += 1
                detail = getattr(cli, "last_error", "") or "link_not_found"
                errors.append(f"move_link_empty:p{profile.get('id')}:node{node.get('server_id')}/{inbound_id}:{detail}")
                continue
            await update_subscription_node(
                existing["id"],
                server_id=int(node["server_id"]),
                inbound_id=inbound_id,
                uuid=client_uuid,
                email=node_email,
                link=link,
                last_used_bytes=0,
                is_active=1,
            )
            moved += 1
            old_cli = XUIClient(existing["server_url"], existing["srv_user"], existing["srv_pass"], existing.get("sub_path") or "", existing.get("srv_api_token", ""))
            try:
                await old_cli.delete_client(existing["inbound_id"], existing["uuid"], existing.get("email", ""))
            except Exception:
                pass
            finally:
                await old_cli.close()
        except Exception as e:
            failed += 1
            errors.append(f"move_error:p{profile.get('id')}:node{node.get('server_id')}/{inbound_id}:{e}")
            logger.warning("subscription moved node error profile=%s node=%s/%s: %s", profile.get("id"), node.get("server_id"), inbound_id, e)
        finally:
            await cli.close()

    for node, existing in refresh_nodes:
        cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
        try:
            inbound_id = int(node.get("inbound_id") or existing.get("inbound_id") or 1)
            client_uuid = str(existing.get("uuid") or uuid.uuid4())
            node_email = str(existing.get("email") or f"{profile['email']}_n{node['id']}"[:120])
            link = await cli.get_client_link(inbound_id, node_email) or ""
            if not _subscription_link_is_complete(link):
                added = await cli.add_client(inbound_id, client_uuid, node_email, traffic_gb, duration_days, starts_on_first_use=False)
                if added and expire_ms > 0:
                    updated = await cli.update_client(inbound_id, client_uuid, node_email, traffic_gb, expire_ms, True)
                    if not updated:
                        logger.warning("subscription refresh exact-expiry update failed but add succeeded profile=%s node=%s/%s email=%s", profile.get("id"), node.get("server_id"), inbound_id, node_email)
                if not added:
                    found = await cli.find_client(email=node_email)
                    remote_client = (found or {}).get("client") or {}
                    remote_uuid = _remote_client_uuid(remote_client, client_uuid)
                    remote_inbound = int((found or {}).get("inbound_id") or inbound_id)
                    if remote_client and remote_uuid:
                        client_uuid = remote_uuid
                        inbound_id = remote_inbound or inbound_id
                        await cli.update_client(inbound_id, client_uuid, node_email, traffic_gb, expire_ms, True)
                inbound_id, client_uuid, link = await _remote_identity_and_link(cli, inbound_id, node_email, client_uuid)
            if _subscription_link_is_complete(link):
                inbound_id, client_uuid, fresh_link = await _remote_identity_and_link(cli, inbound_id, node_email, client_uuid)
                if _subscription_link_is_complete(fresh_link):
                    link = fresh_link
                changed = (
                    link != (existing.get("link") or "")
                    or not int(existing.get("is_active") or 0)
                    or int(existing.get("inbound_id") or 0) != inbound_id
                    or str(existing.get("uuid") or "") != client_uuid
                )
                await update_subscription_node(existing["id"], inbound_id=inbound_id, uuid=client_uuid, link=link, is_active=1)
                if changed:
                    refreshed += 1
                else:
                    verified += 1
            else:
                failed += 1
                msg = f"refresh_failed:p{profile.get('id')}:node{node.get('server_id')}/{inbound_id}:{getattr(cli, 'last_error', '') or node_email}"
                errors.append(msg)
                logger.warning("subscription node refresh failed profile=%s node=%s/%s email=%s", profile.get("id"), node.get("server_id"), inbound_id, node_email)
        except Exception as e:
            failed += 1
            errors.append(f"refresh_error:p{profile.get('id')}:node{node.get('server_id')}/{node.get('inbound_id')}:{e}")
            logger.warning("subscription node refresh error profile=%s node=%s/%s: %s", profile.get("id"), node.get("server_id"), node.get("inbound_id"), e)
        finally:
            await cli.close()

    for node in missing_nodes:
        inbound_id = int(node.get("inbound_id") or 1)
        client_uuid = str(uuid.uuid4())
        node_email = f"{profile['email']}_n{node['id']}"[:120]
        cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
        try:
            added = await cli.add_client(inbound_id, client_uuid, node_email, traffic_gb, duration_days, starts_on_first_use=False)
            ok = bool(added)
            if added and expire_ms > 0:
                updated = await cli.update_client(inbound_id, client_uuid, node_email, traffic_gb, expire_ms, True)
                if not updated:
                    logger.warning("subscription missing node exact-expiry update failed but add succeeded profile=%s node=%s/%s email=%s", profile.get("id"), node.get("server_id"), inbound_id, node_email)
            if not added:
                found = await cli.find_client(email=node_email)
                remote_client = (found or {}).get("client") or {}
                remote_uuid = _remote_client_uuid(remote_client, client_uuid)
                remote_inbound = int((found or {}).get("inbound_id") or inbound_id)
                if remote_client and remote_uuid:
                    client_uuid = remote_uuid
                    inbound_id = remote_inbound or inbound_id
                    ok = await cli.update_client(inbound_id, client_uuid, node_email, traffic_gb, expire_ms, True)
            if not ok:
                failed += 1
                detail = getattr(cli, "last_error", "") or "unknown"
                errors.append(f"add_failed:p{profile.get('id')}:node{node.get('server_id')}/{inbound_id}:{detail}")
                logger.warning("subscription missing node add failed profile=%s node=%s/%s email=%s", profile.get("id"), node.get("server_id"), inbound_id, node_email)
                continue
            inbound_id, client_uuid, link = await _remote_identity_and_link(cli, inbound_id, node_email, client_uuid)
            if not _subscription_link_is_complete(link):
                failed += 1
                detail = getattr(cli, "last_error", "") or "link_not_found"
                errors.append(f"link_empty:p{profile.get('id')}:node{node.get('server_id')}/{inbound_id}:{detail}")
                logger.warning("subscription missing node link empty profile=%s node=%s/%s email=%s", profile.get("id"), node.get("server_id"), inbound_id, node_email)
                try:
                    await cli.delete_client(inbound_id, client_uuid, node_email)
                except Exception:
                    pass
                continue
            await add_subscription_node(profile["id"], node["server_id"], inbound_id, client_uuid, node_email, link)
            created += 1
        except Exception as e:
            failed += 1
            errors.append(f"add_error:p{profile.get('id')}:node{node.get('server_id')}/{inbound_id}:{e}")
            logger.warning("subscription missing node add error profile=%s node=%s/%s: %s", profile.get("id"), node.get("server_id"), inbound_id, e)
        finally:
            await cli.close()
    if created or refreshed or verified or moved or failed:
        logger.info(
            "subscription node ensure profile=%s created=%s refreshed=%s verified=%s moved=%s failed=%s missing=%s refresh=%s move=%s",
            profile.get("id"),
            created,
            refreshed,
            verified,
            moved,
            failed,
            len(missing_nodes),
            len(refresh_nodes),
            len(move_nodes),
        )
    return {"created": created, "refreshed": refreshed, "verified": verified, "moved": moved, "removed": removed, "skipped": 0, "failed": failed, "errors": errors[:12]}


async def repair_subscription_profile_expiry(profile: Dict) -> Dict:
    # Don't "repair" a first-use profile that hasn't started yet — its expiry is
    # intentionally 0 until the first fetch arms the timer.
    if int(profile.get("starts_on_first_use") or 0) and int(profile.get("first_use_at") or 0) <= 0:
        return profile
    if int(profile.get("expire_timestamp") or 0) > 0 or _as_int(profile.get("duration_days")) <= 0:
        return profile

    now_ms = int(time.time() * 1000)
    expire_ms = _resolve_expire_ms(profile, now_ms=now_ms, used_bytes=int(profile.get("used_bytes") or 0))
    if expire_ms <= 0:
        return profile

    fixed = dict(profile)
    fixed["expire_timestamp"] = expire_ms
    fixed["is_active"] = 0 if expire_ms <= now_ms else int(profile.get("is_active") or 0)
    await update_subscription_profile(
        profile["id"],
        expire_timestamp=expire_ms,
        is_active=fixed["is_active"],
    )
    await set_nodes_enabled(profile["id"], bool(fixed["is_active"]))
    return fixed


async def sync_profile_usage(profile: Dict) -> Dict:
    profile = await repair_subscription_profile_expiry(profile)
    if not int(profile.get("is_active") or 0):
        await set_nodes_enabled(profile["id"], False)
        return {"used": int(profile.get("used_bytes") or 0), "disabled": True, "inactive": True}
    nodes = await get_subscription_nodes(profile["id"])
    used_total = 0
    total_limit = total_bytes(profile.get("traffic_gb") or 0)
    now_ms = int(time.time() * 1000)
    expired = int(profile.get("expire_timestamp") or 0) > 0 and int(profile.get("expire_timestamp") or 0) <= now_ms
    if expired:
        await update_subscription_profile(profile["id"], is_active=0)
        await set_nodes_enabled(profile["id"], False)
        return {"used": int(profile.get("used_bytes") or 0), "disabled": True, "expired": True}

    for node in nodes:
        cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
        try:
            traffic = await cli.get_client_traffic(node["email"])
            if traffic:
                used = int((traffic or {}).get("down") or 0) + int((traffic or {}).get("up") or 0)
                await update_subscription_node(node["id"], last_used_bytes=used)
            else:
                used = int(node.get("last_used_bytes") or 0)
            used_total += used
        except Exception:
            used_total += int(node.get("last_used_bytes") or 0)
        finally:
            await cli.close()

    should_disable = total_limit > 0 and used_total >= total_limit
    await update_subscription_profile(profile["id"], used_bytes=used_total, is_active=0 if should_disable else 1)
    if should_disable:
        await set_nodes_enabled(profile["id"], False)
    return {"used": used_total, "disabled": should_disable}


async def set_nodes_enabled(profile_id: int, enabled: bool):
    """Enable/disable EVERY node of a profile on the panels — robustly.

    The hard cases this must get right:
      * Re-enable after expiry: the remote client was usually deleted on most
        servers, so a plain updateClient fails and only the few survivors come
        back. We RE-CREATE the missing client so ALL servers reactivate.
      * Disable: we must never leave a node marked active in our DB even if the
        remote write fails, and we try hard (identity re-resolve) to actually
        disable the remote client so a finished sub can't keep working.
    """
    nodes = await get_subscription_nodes(profile_id)
    from core.database import get_subscription_profile
    profile = await get_subscription_profile(profile_id)
    traffic_gb = float(profile.get("traffic_gb") or 0) if profile else 0
    expire_ms = int(profile.get("expire_timestamp") or 0) if profile else 0
    now_ms = int(time.time() * 1000)
    duration_days = _days_remaining(expire_ms, now_ms) if expire_ms > 0 else 0

    for node in nodes:
        cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
        try:
            inbound_id = int(node.get("inbound_id") or 1)
            node_uuid = node.get("uuid") or ""
            node_email = node.get("email") or ""
            ok = await cli.update_client(inbound_id, node_uuid, node_email, traffic_gb, expire_ms, bool(enabled))
            if not ok:
                # Identity drift: cached uuid/inbound may be stale → re-resolve.
                r_in, r_uuid, _ = await _remote_identity_and_link(cli, inbound_id, node_email, node_uuid)
                if r_uuid:
                    inbound_id, node_uuid = (r_in or inbound_id), r_uuid
                    ok = await cli.update_client(inbound_id, node_uuid, node_email, traffic_gb, expire_ms, bool(enabled))
            if enabled:
                if not ok:
                    # Client is genuinely gone → re-create so this server comes back.
                    new_uuid = node_uuid or str(uuid.uuid4())
                    added = await cli.add_client(inbound_id, new_uuid, node_email, traffic_gb, duration_days, starts_on_first_use=False)
                    if added:
                        node_uuid = new_uuid
                        if expire_ms > 0:
                            await cli.update_client(inbound_id, node_uuid, node_email, traffic_gb, expire_ms, True)
                        ok = True
                if ok:
                    r_in, r_uuid, link = await _remote_identity_and_link(cli, inbound_id, node_email, node_uuid)
                    upd = {"is_active": 1, "inbound_id": r_in or inbound_id, "uuid": r_uuid or node_uuid}
                    if _subscription_link_is_complete(link):
                        upd["link"] = link
                    await update_subscription_node(node["id"], **upd)
                else:
                    logger.warning("set_nodes_enabled: could not re-enable node id=%s profile=%s", node.get("id"), profile_id)
            else:
                # Disable: always drop the DB flag (render must stop serving it).
                await update_subscription_node(node["id"], is_active=0)
        except Exception as e:
            logger.warning("set_nodes_enabled node id=%s failed: %s", node.get("id"), e)
            if not enabled:
                try:
                    await update_subscription_node(node["id"], is_active=0)
                except Exception:
                    pass
        finally:
            await cli.close()


async def renew_subscription_profile(profile: Dict, traffic_gb: float, duration_days: int) -> Dict:
    """Renew a subscription.

    Rules (per product spec):
      * Consumed/used volume ALWAYS resets to zero and counting restarts.
      * If renewed *while still fully usable* — it still had BOTH remaining
        volume AND remaining time — the leftover volume and leftover time are
        CARRIED OVER and summed with the newly purchased volume/duration.
      * Otherwise (it had run out of volume OR time) it starts fresh from now.
    """
    # Freshest figures so carry-over isn't computed off stale usage.
    fresh = await get_subscription_profile(profile["id"]) or profile
    now_ms = int(time.time() * 1000)
    new_duration = int(duration_days or 0)
    new_traffic_gb = float(traffic_gb or 0)

    cur_total = total_bytes(fresh.get("traffic_gb") or 0)        # 0 = unlimited volume
    cur_used = int(fresh.get("used_bytes") or 0)
    cur_expire = int(fresh.get("expire_timestamp") or 0)         # 0 = unlimited / not armed
    not_started = bool(int(fresh.get("starts_on_first_use") or 0) and int(fresh.get("first_use_at") or 0) <= 0)

    volume_remaining = cur_total <= 0 or cur_used < cur_total
    time_remaining = cur_expire <= 0 or cur_expire > now_ms
    carry = volume_remaining and time_remaining and not not_started

    # Volume: carry leftover + new, or top-up unused, or fresh. Unlimited stays unlimited.
    if carry:
        final_traffic_gb = 0.0 if (cur_total <= 0 or new_traffic_gb <= 0) else \
            round(max(0.0, (cur_total - cur_used) / (1024 ** 3)) + new_traffic_gb, 3)
    elif not_started:
        final_traffic_gb = 0.0 if (cur_total <= 0 or new_traffic_gb <= 0) else \
            round(cur_total / (1024 ** 3) + new_traffic_gb, 3)
    else:
        final_traffic_gb = new_traffic_gb

    # Time: carry leftover + new, or fresh from now. First-use timer stays unarmed.
    if not_started:
        final_expire_ms = 0
    elif carry:
        final_expire_ms = 0 if (cur_expire <= 0 or new_duration <= 0) else cur_expire + new_duration * 86400000
    else:
        final_expire_ms = now_ms + new_duration * 86400000 if new_duration > 0 else 0

    nodes = await get_subscription_nodes(profile["id"])
    ok_count = 0
    failures = []
    for node in nodes:
        cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
        try:
            inbound_id = int(node.get("inbound_id") or 0)
            node_uuid = node.get("uuid") or ""
            node_email = node.get("email") or ""
            ok = await cli.update_client(inbound_id, node_uuid, node_email, final_traffic_gb, final_expire_ms, True)
            if not ok:
                # Identity drift recovery: the cached uuid/inbound may be stale
                # (client recreated on the panel). Re-resolve by email and retry,
                # so a renew never silently no-ops and leaves the old volume/date.
                resolved_inbound, resolved_uuid, _ = await _remote_identity_and_link(cli, inbound_id, node_email, node_uuid)
                if resolved_uuid:
                    inbound_id = resolved_inbound or inbound_id
                    node_uuid = resolved_uuid
                    ok = await cli.update_client(inbound_id, node_uuid, node_email, final_traffic_gb, final_expire_ms, True)
            if ok:
                await cli.reset_client_traffic(inbound_id, node_email)
                # Refresh the cached link/identity so the served sub immediately
                # reflects the renewed client.
                fresh_inbound, fresh_uuid, fresh_link = await _remote_identity_and_link(cli, inbound_id, node_email, node_uuid)
                update_kw = {"is_active": 1, "last_used_bytes": 0, "inbound_id": fresh_inbound or inbound_id, "uuid": fresh_uuid or node_uuid}
                if _subscription_link_is_complete(fresh_link):
                    update_kw["link"] = fresh_link
                await update_subscription_node(node["id"], **update_kw)
                ok_count += 1
            else:
                failures.append(f"{node.get('server_name') or node.get('server_id')}#{node.get('inbound_id')}")
        except Exception as e:
            failures.append(f"{node.get('server_name') or node.get('server_id')}#{node.get('inbound_id')}:{type(e).__name__}")
        finally:
            await cli.close()
    if ok_count <= 0:
        return {"ok": False, "error": "no_nodes_updated:" + ",".join(failures[:6])}
    update_kwargs = dict(
        traffic_gb=float(final_traffic_gb),
        used_bytes=0,
        is_active=1,
        expired_at=0,
        expiry_notified=0,
        prewarn_sent=0,
    )
    if not_started:
        update_kwargs.update(expire_timestamp=0, duration_days=int(new_duration))
    else:
        final_duration_days = _days_remaining(final_expire_ms, now_ms) if final_expire_ms > 0 else 0
        update_kwargs.update(
            expire_timestamp=int(final_expire_ms),
            duration_days=int(final_duration_days),
            starts_on_first_use=0,
        )
    await update_subscription_profile(profile["id"], **update_kwargs)
    return {"ok": True, "nodes": ok_count, "expire_ms": final_expire_ms, "carried": carry, "traffic_gb": final_traffic_gb}


async def edit_subscription_profile(profile: Dict, email: str, traffic_gb: float, expire_ms: int, is_active: bool = True) -> Dict:
    nodes = await get_subscription_nodes(profile["id"])
    ok_count = 0
    failures = []
    old_email = str(profile.get("email") or "")
    for node in nodes:
        cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
        try:
            node_email = str(node.get("email") or "")
            suffix = ""
            if old_email and node_email.startswith(old_email):
                suffix = node_email[len(old_email):]
            if not suffix and len(nodes) > 1:
                suffix = f"_n{node.get('id')}"
            new_node_email = f"{email}{suffix}"[:120] if suffix else email[:120]
            ok = await cli.update_client(
                node["inbound_id"],
                node["uuid"],
                node_email,
                traffic_gb,
                int(expire_ms or 0),
                bool(is_active),
                new_email=new_node_email,
            )
            if not ok and is_active:
                # Client was removed on this server (typical after expiry) →
                # re-create it so reactivation restores EVERY server, not just
                # the few whose client happened to survive.
                new_uuid = node.get("uuid") or str(uuid.uuid4())
                duration = _days_remaining(int(expire_ms or 0), int(time.time() * 1000)) if int(expire_ms or 0) > 0 else 0
                added = await cli.add_client(node["inbound_id"], new_uuid, new_node_email, traffic_gb, duration, starts_on_first_use=False)
                if added and int(expire_ms or 0) > 0:
                    await cli.update_client(node["inbound_id"], new_uuid, new_node_email, traffic_gb, int(expire_ms or 0), True)
                ok = added
            if ok:
                inbound_id, client_uuid, link = await _remote_identity_and_link(
                    cli,
                    int(node.get("inbound_id") or 0),
                    new_node_email,
                    node.get("uuid") or "",
                )
                if not _subscription_link_is_complete(link):
                    failures.append(f"{node.get('server_name') or node.get('server_id')}#{node.get('inbound_id')}:link_failed")
                    continue
                await update_subscription_node(
                    node["id"],
                    inbound_id=inbound_id,
                    uuid=client_uuid,
                    email=new_node_email,
                    link=link,
                    is_active=1 if is_active else 0,
                )
                ok_count += 1
            else:
                failures.append(f"{node.get('server_name') or node.get('server_id')}#{node.get('inbound_id')}")
        finally:
            await cli.close()
    if nodes and ok_count <= 0:
        return {"ok": False, "error": "no_nodes_updated:" + ",".join(failures[:6])}

    now_ms = int(time.time() * 1000)
    duration_days = int((int(expire_ms or 0) - now_ms + 86399999) // 86400000) if int(expire_ms or 0) > 0 else 0
    reset_lifecycle = {}
    if is_active:
        reset_lifecycle = {"expired_at": 0, "expiry_notified": 0, "prewarn_sent": 0}
    await update_subscription_profile(
        profile["id"],
        email=email,
        traffic_gb=float(traffic_gb),
        duration_days=max(0, duration_days),
        expire_timestamp=int(expire_ms or 0),
        is_active=1 if is_active else 0,
        **reset_lifecycle,
    )
    return {"ok": True, "nodes": ok_count, "expire_ms": int(expire_ms or 0)}


async def reset_subscription_usage(profile_id: int) -> Dict:
    """Admin: zero the consumed volume (reset traffic counter) on every server."""
    profile = await get_subscription_profile(profile_id)
    if not profile:
        return {"ok": False, "error": "not_found"}
    nodes = await get_subscription_nodes(profile_id)
    done = 0
    for node in nodes:
        cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
        try:
            if await cli.reset_client_traffic(int(node.get("inbound_id") or 0), node.get("email") or ""):
                done += 1
            await update_subscription_node(node["id"], last_used_bytes=0)
        except Exception:
            pass
        finally:
            await cli.close()
    await update_subscription_profile(profile_id, used_bytes=0, is_active=1, expired_at=0, expiry_notified=0, prewarn_sent=0)
    await set_nodes_enabled(profile_id, True)
    return {"ok": True, "nodes": done}


async def reset_subscription_time(profile_id: int) -> Dict:
    """Admin: re-arm the timer — a fresh full duration counted from now."""
    profile = await get_subscription_profile(profile_id)
    if not profile:
        return {"ok": False, "error": "not_found"}
    duration = int(profile.get("duration_days") or 0)
    now_ms = int(time.time() * 1000)
    new_expire = now_ms + duration * 86400000 if duration > 0 else 0
    traffic_gb = float(profile.get("traffic_gb") or 0)
    for node in await get_subscription_nodes(profile_id):
        cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
        try:
            await cli.update_client(int(node.get("inbound_id") or 0), node.get("uuid") or "", node.get("email") or "", traffic_gb, new_expire, True)
        except Exception:
            pass
        finally:
            await cli.close()
    await update_subscription_profile(
        profile_id, expire_timestamp=new_expire, is_active=1,
        expired_at=0, expiry_notified=0, prewarn_sent=0,
        starts_on_first_use=0, first_use_at=now_ms,
    )
    await set_nodes_enabled(profile_id, True)
    return {"ok": True, "expire_ms": new_expire}


async def rebuild_subscription_profile(profile_id: int) -> Dict:
    """Admin: return a sub to a clean working state — re-create/enable every
    server (even ones deleted after expiry), re-arm the timer and zero usage."""
    await reset_subscription_time(profile_id)
    await reset_subscription_usage(profile_id)
    profile = await get_subscription_profile(profile_id)
    if profile and int(profile.get("is_active") or 0):
        try:
            await ensure_subscription_profile_nodes(profile, force_refresh=True)
        except Exception as e:
            logger.warning("rebuild ensure failed pid=%s: %s", profile_id, e)
    return {"ok": True}


async def delete_subscription_profile_remote(profile_id: int) -> Dict:
    nodes = await get_subscription_nodes(profile_id)
    deleted = failed = 0
    for node in nodes:
        cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
        try:
            ok = await cli.delete_client(node["inbound_id"], node["uuid"], node.get("email", ""))
            deleted += 1 if ok else 0
            failed += 0 if ok else 1
        except Exception:
            failed += 1
        finally:
            await cli.close()
    await delete_subscription_profile(profile_id)
    return {"ok": True, "deleted": deleted, "failed": failed}


async def sync_active_profiles(limit: int = 100, usage_only: bool = False) -> int:
    """Reconcile active profiles.

    `usage_only=True` does the cheap, frequent pass: just refresh usage and let
    quota/expiry disable finished subs. The full pass also reconciles nodes
    (create missing / remove orphaned / repair links) and is driven on a slower,
    panel-configurable cadence by the worker.
    """
    checked = 0
    for profile in await get_active_subscription_profiles(limit):
        result = await sync_profile_usage(profile)
        if not usage_only and not result.get("disabled"):
            fresh = await get_subscription_profile_by_token(profile["token"]) or profile
            await ensure_subscription_profile_nodes(fresh)
        checked += 1
    return checked


async def sync_subscription_nodes_for_all(limit: int = 1000, force_refresh: bool = False) -> Dict:
    checked = created = refreshed = verified = moved = removed = failed = skipped = disabled = 0
    errors: list[str] = []
    for profile in await get_active_subscription_profiles(limit):
        usage = await sync_profile_usage(profile)
        checked += 1
        if usage.get("disabled"):
            disabled += 1
            continue
        fresh = await get_subscription_profile_by_token(profile["token"]) or profile
        result = await ensure_subscription_profile_nodes(fresh, force_refresh=force_refresh)
        created += int(result.get("created") or 0)
        refreshed += int(result.get("refreshed") or 0)
        verified += int(result.get("verified") or 0)
        moved += int(result.get("moved") or 0)
        removed += int(result.get("removed") or 0)
        failed += int(result.get("failed") or 0)
        skipped += int(result.get("skipped") or 0)
        for err in result.get("errors") or []:
            if len(errors) < 20:
                errors.append(str(err))
    return {
        "checked": checked,
        "created": created,
        "refreshed": refreshed,
        "verified": verified,
        "moved": moved,
        "removed": removed,
        "failed": failed,
        "skipped": skipped,
        "disabled": disabled,
        "errors": errors,
    }


async def sync_subscription_nodes_streamed(
    log,
    limit: int = 5000,
    force_refresh: bool = False,
    concurrency: int = 6,
    per_profile_timeout: int = 120,
) -> Dict:
    """Same as sync_subscription_nodes_for_all but FAST and observable.

    - Profiles are processed concurrently (network-bound work → big speedup).
    - Each profile is time-boxed so one slow/down server can't stall everything.
    - `log(line)` is called with human-readable progress for live display.
    """
    profiles = await get_active_subscription_profiles(limit)
    total = len(profiles)
    mode = "بازسازی کامل لینک‌ها" if force_refresh else "سریع (فقط نودهای ناقص/جدید)"
    log(f"🔎 {total} ساب فعال پیدا شد | حالت: {mode} | پردازش همزمان: {concurrency}")
    agg = {"checked": 0, "created": 0, "refreshed": 0, "verified": 0,
           "moved": 0, "removed": 0, "failed": 0, "skipped": 0, "disabled": 0}
    if not total:
        log("هیچ ساب فعالی برای همگام‌سازی وجود ندارد.")
        return agg

    sem = asyncio.Semaphore(max(1, int(concurrency)))
    state = {"done": 0}

    async def worker(profile: Dict):
        async with sem:
            label = str(profile.get("email") or f"#{profile.get('id')}")[-28:]
            try:
                usage = await asyncio.wait_for(sync_profile_usage(profile), timeout=per_profile_timeout)
                agg["checked"] += 1
                if usage.get("disabled"):
                    agg["disabled"] += 1
                    state["done"] += 1
                    log(f"[{state['done']}/{total}] ⏸ {label}: غیرفعال/منقضی شد")
                    return
                fresh = await get_subscription_profile_by_token(profile["token"]) or profile
                r = await asyncio.wait_for(
                    ensure_subscription_profile_nodes(fresh, force_refresh=force_refresh),
                    timeout=per_profile_timeout,
                )
                for k in ("created", "refreshed", "verified", "moved", "removed", "failed", "skipped"):
                    agg[k] += int(r.get(k) or 0)
                state["done"] += 1
                log(
                    f"[{state['done']}/{total}] ✅ {label}: "
                    f"ساخته={r.get('created', 0)} ترمیم={r.get('refreshed', 0)} "
                    f"تایید={r.get('verified', 0)} انتقال={r.get('moved', 0)} "
                    f"حذف={r.get('removed', 0)} خطا={r.get('failed', 0)}"
                )
                for err in (r.get("errors") or [])[:2]:
                    log(f"    ↳ {err}")
            except asyncio.TimeoutError:
                agg["failed"] += 1
                state["done"] += 1
                log(f"[{state['done']}/{total}] ⌛️ {label}: طول کشید و رد شد (سرور کند یا در دسترس نیست)")
            except Exception as e:
                agg["failed"] += 1
                state["done"] += 1
                log(f"[{state['done']}/{total}] ❌ {label}: {str(e)[:140]}")

    await asyncio.gather(*(worker(p) for p in profiles))
    log("")
    log(
        f"📊 خلاصه — بررسی: {agg['checked']} | ساخته: {agg['created']} | "
        f"ترمیم: {agg['refreshed']} | تایید: {agg['verified']} | انتقال: {agg['moved']} | "
        f"حذف: {agg['removed']} | غیرفعال: {agg['disabled']} | خطا: {agg['failed']}"
    )
    return agg


def _format_lifecycle_template(template: str, values: Dict[str, str]) -> str:
    try:
        return (template or "").format(**values)
    except Exception:
        return template or ""


async def run_subscription_expiry_warnings(bot, limit: int = 300) -> Dict:
    """Pre-expiry nudge: warn users *before* their sub ends (low volume or few
    days left) and attach a one-tap renew button. Sent once per cycle; the flag
    resets on renewal so the next cycle warns again."""
    if await get_setting("sub_prewarn_enabled", "1") != "1":
        return {"warned": 0}
    from core.database import get_subscription_profiles_for_prewarn
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from core.jalali import jalali_display

    try:
        days = max(1, int(await get_setting("sub_prewarn_days", "3") or 3))
    except (TypeError, ValueError):
        days = 3
    try:
        percent = max(1, min(90, int(await get_setting("sub_prewarn_percent", "15") or 15)))
    except (TypeError, ValueError):
        percent = 15
    template = await get_setting(
        "sub_prewarn_template",
        "⏳ سرویس شما رو به اتمام است.\n\n"
        "سرویس: {service}\n"
        "حجم باقی‌مانده: {remaining} از {total}\n"
        "زمان باقی‌مانده: حدود {days_left} روز\n\n"
        "برای جلوگیری از قطعی، همین حالا تمدید کنید 👇",
    )
    brand = await get_setting("ui.brand_name", "Atlas Account")
    now_ms = int(time.time() * 1000)
    used_fraction = (100 - percent) / 100.0
    warned = 0
    for p in await get_subscription_profiles_for_prewarn(now_ms, days * 86400000, used_fraction, limit):
        pid = int(p["id"])
        telegram_id = int(p.get("telegram_id") or 0)
        total = total_bytes(p.get("traffic_gb") or 0)
        used = int(p.get("used_bytes") or 0)
        remaining = max(0, total - used) if total > 0 else 0
        expire_ms = int(p.get("expire_timestamp") or 0)
        days_left = max(0, int((expire_ms - now_ms) / 86400000)) if expire_ms > 0 else 0
        values = {
            "brand": brand,
            "service": str(p.get("name") or p.get("email") or f"#{pid}"),
            "remaining": _fmt_bytes_short(remaining),
            "total": _fmt_bytes_short(total) if total > 0 else "نامحدود",
            "days_left": str(days_left),
            "expire_date": jalali_display(datetime.fromtimestamp(expire_ms / 1000)) if expire_ms > 0 else "—",
        }
        if telegram_id:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="♻️ تمدید سریع", callback_data=f"sub_renew:{pid}")
            ]])
            try:
                await bot.send_message(telegram_id, _format_lifecycle_template(template, values), parse_mode=None, reply_markup=kb)
                warned += 1
                await asyncio.sleep(0.1)
            except Exception:
                pass
        await update_subscription_profile(pid, prewarn_sent=1)
    if warned:
        logger.info("subscription pre-expiry warnings sent=%s (days=%s percent=%s)", warned, days, percent)
    return {"warned": warned}


async def run_subscription_lifecycle(bot, limit: int = 300) -> Dict:
    """Notify users when their subscription ends and delete it after a grace period.

    Flow per expired profile (out of time OR out of quota):
      1) First time seen expired -> stamp expired_at.
      2) If not yet notified -> send the "subscription ended" message with usage
         stats + a warning that they have N days to renew, then mark notified
         and make sure the profile is inactive.
      3) Once the grace window passes without renewal -> delete every remote
         node + the local profile and tell the user to buy again.
    """
    from core.jalali import jalali_display

    now_ms = int(time.time() * 1000)
    try:
        grace_days = max(0, int(await get_setting("sub_grace_days", "3") or 3))
    except Exception:
        grace_days = 3
    grace_ms = grace_days * 86400000
    brand = await get_setting("ui.brand_name", "Atlas Account")
    notice_tpl = await get_setting("sub_expiry_notice_template", "")
    deleted_tpl = await get_setting("sub_deleted_notice_template", "")

    notified = deleted = 0
    for profile in await get_expired_subscription_profiles(now_ms, limit):
        try:
            pid = int(profile["id"])
            telegram_id = int(profile.get("telegram_id") or 0)
            total = total_bytes(profile.get("traffic_gb") or 0)
            used = int(profile.get("used_bytes") or 0)
            remaining = max(0, total - used) if total > 0 else 0
            expire_ms = int(profile.get("expire_timestamp") or 0)
            expire_date = jalali_display(datetime.fromtimestamp(expire_ms / 1000)) if expire_ms > 0 else "—"
            values = {
                "brand": brand,
                "service": profile.get("email") or f"#{pid}",
                "used": _fmt_bytes_short(used),
                "total": _fmt_bytes_short(total) if total > 0 else "نامحدود",
                "remaining": _fmt_bytes_short(remaining),
                "duration_days": str(int(profile.get("duration_days") or 0)),
                "expire_date": expire_date,
                "grace_days": str(grace_days),
            }

            expired_at = int(profile.get("expired_at") or 0)
            if expired_at <= 0:
                expired_at = now_ms
                await update_subscription_profile(pid, expired_at=expired_at, is_active=0)

            # Step 1: ensure the user is informed exactly once, with a one-tap
            # "quick renew" button so the user can start renewal immediately.
            if not int(profile.get("expiry_notified") or 0):
                if telegram_id and notice_tpl.strip():
                    try:
                        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
                        renew_kb = InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(text="♻️ تمدید سریع", callback_data=f"sub_renew:{pid}")
                        ]])
                        await bot.send_message(
                            telegram_id,
                            _format_lifecycle_template(notice_tpl, values),
                            parse_mode=None,
                            reply_markup=renew_kb,
                        )
                        notified += 1
                        await asyncio.sleep(0.1)
                    except Exception:
                        pass
                await update_subscription_profile(pid, expiry_notified=1, is_active=0)
                # Make sure the nodes are actually disabled on the panels.
                try:
                    await set_nodes_enabled(pid, False)
                except Exception:
                    pass

            # Step 2: delete after the grace window with no renewal.
            if grace_ms >= 0 and now_ms >= expired_at + grace_ms:
                try:
                    await delete_subscription_profile_remote(pid)
                    deleted += 1
                    if telegram_id and deleted_tpl.strip():
                        try:
                            await bot.send_message(telegram_id, _format_lifecycle_template(deleted_tpl, values), parse_mode=None)
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning("subscription lifecycle delete failed pid=%s: %s", pid, e)
        except Exception as e:
            logger.warning("subscription lifecycle error profile=%s: %s", profile.get("id"), e)

    if notified or deleted:
        logger.info("subscription lifecycle: notified=%s deleted=%s grace_days=%s", notified, deleted, grace_days)
    return {"notified": notified, "deleted": deleted}
