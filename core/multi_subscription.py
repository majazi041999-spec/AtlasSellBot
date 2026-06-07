import base64
import binascii
import json
import logging
import secrets
import time
import uuid
from datetime import datetime
from typing import Dict, List
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from core.config import WEB_PORT
from core.database import (
    add_subscription_node,
    create_subscription_profile,
    delete_subscription_profile,
    get_active_subscription_profiles,
    count_active_server_load,
    count_active_subscription_nodes_by_target,
    get_available_subscription_node_configs,
    get_subscription_node_configs,
    get_setting,
    get_subscription_nodes,
    get_subscription_profile_by_token,
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
    return str(client.get("id") or client.get("uuid") or client.get("password") or client.get("auth") or fallback or "")


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
        encoded = base64.urlsafe_b64encode(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()).decode().rstrip("=")
        return f"vmess://{encoded}"

    try:
        parts = urlsplit(link)
        if not parts.scheme:
            return link
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, quote(label, safe="")))
    except Exception:
        return link


def _fake_vmess_info_link(label: str, index: int = 1) -> str:
    label = (label or "").strip()
    if not label:
        return ""
    suffix = max(1, min(9999, int(index or 1)))
    cfg = {
        "v": "2",
        "ps": label[:180],
        "add": "127.0.0.1",
        "port": "1",
        "id": f"00000000-0000-0000-0000-{suffix:012d}",
        "aid": "0",
        "scy": "auto",
        "net": "tcp",
        "type": "none",
        "host": "",
        "path": "",
        "tls": "",
    }
    encoded = base64.b64encode(json.dumps(cfg, ensure_ascii=False, separators=(",", ":")).encode()).decode()
    return f"vmess://{encoded}"


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
    brand_template = await get_setting("sub_brand_template", "📣 {brand}")
    labels = _format_info_template(template, values) + _format_info_template(brand_template, values)
    return [_fake_vmess_info_link(label, i + 1) for i, label in enumerate(labels) if label]


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
    expire_ms = expiry_ms_from_days(duration_days)
    profile_id = await create_subscription_profile(user["id"], order["id"], token, email, traffic_gb, duration_days, expire_ms)
    created_remote: list[tuple[Dict, int, str, str]] = []
    failures: list[str] = []

    try:
        for node in nodes:
            inbound_id = int(node.get("inbound_id") or 1)
            client_uuid = str(uuid.uuid4())
            node_email = f"{email}_n{node['id']}"
            cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
            try:
                ok = await cli.add_client(inbound_id, client_uuid, node_email, traffic_gb, duration_days, starts_on_first_use=False)
                if not ok:
                    failures.append(f"{node.get('server_name') or node['server_id']}#{inbound_id}:add_failed")
                    continue
                link = await cli.get_client_link(inbound_id, node_email) or ""
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
    profile_id = await create_subscription_profile(user["id"], 0, token, email, remaining_gb, remaining_days, expire_ms)
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
                link = await cli.get_client_link(inbound_id, node_email) or ""
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


async def render_subscription(token: str) -> tuple[str, Dict[str, int]] | None:
    profile = await get_subscription_profile_by_token(token)
    if not profile or not int(profile.get("is_active") or 0):
        return None
    if await get_setting("sub_info_sync_on_render", "1") == "1":
        try:
            await sync_profile_usage(profile)
            profile = await get_subscription_profile_by_token(token) or profile
            if not int(profile.get("is_active") or 0):
                return None
        except Exception:
            pass
    await ensure_subscription_profile_nodes(profile)
    nodes = await get_subscription_nodes(profile["id"])
    links = []
    active_count = 0
    for n in nodes:
        if not int(n.get("is_active") or 0) or not n.get("link"):
            continue
        active_count += 1
        label = n.get("node_label") or f"{n.get('server_name') or 'Node'} #{n.get('inbound_id') or ''}"
        links.append(_label_subscription_link(n.get("link") or "", label))
    used = int(profile.get("used_bytes") or 0)
    total = total_bytes(profile.get("traffic_gb") or 0)
    expire = int(int(profile.get("expire_timestamp") or 0) / 1000) if int(profile.get("expire_timestamp") or 0) > 0 else 0
    info_links = await _subscription_info_links(profile, used, total, active_count)
    links = info_links + links
    body = base64.b64encode("\n".join(links).encode()).decode()
    return body, {"upload": 0, "download": used, "total": total, "expire": expire}


async def ensure_subscription_profile_nodes(profile: Dict) -> Dict:
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
    missing_nodes = []
    refresh_nodes = []
    for node in configured_nodes:
        node_email = f"{profile['email']}_n{node['id']}"[:120]
        existing = existing_by_email.get(node_email)
        if not existing:
            missing_nodes.append(node)
        elif not existing.get("link") or not int(existing.get("is_active") or 0):
            refresh_nodes.append((node, existing))
    if not missing_nodes and not refresh_nodes:
        return {"created": 0, "refreshed": 0, "skipped": 0, "failed": 0}

    used = int(profile.get("used_bytes") or 0)
    total = total_bytes(profile.get("traffic_gb") or 0)
    remaining = max(0, total - used) if total > 0 else total
    if total > 0 and remaining <= 0:
        await update_subscription_profile(profile["id"], is_active=0)
        await set_nodes_enabled(profile["id"], False)
        return {"created": 0, "refreshed": 0, "skipped": len(missing_nodes) + len(refresh_nodes), "failed": 0}

    traffic_gb = float(profile.get("traffic_gb") or 0)
    if total > 0:
        traffic_gb = max(0.1, remaining / (1024 ** 3))
    if traffic_gb <= 0:
        return {"created": 0, "refreshed": 0, "skipped": len(missing_nodes) + len(refresh_nodes), "failed": 0}

    duration_days = _days_remaining(expire_ms, now_ms)
    created = refreshed = failed = 0
    for node, existing in refresh_nodes:
        cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
        try:
            ok = await cli.update_client(
                existing["inbound_id"],
                existing["uuid"],
                existing["email"],
                traffic_gb,
                expire_ms,
                True,
            )
            link = await cli.get_client_link(existing["inbound_id"], existing["email"]) or existing.get("link", "")
            if ok or link:
                await update_subscription_node(existing["id"], link=link, is_active=1)
                refreshed += 1
            else:
                failed += 1
                logger.warning("subscription node refresh failed profile=%s node=%s/%s email=%s", profile.get("id"), node.get("server_id"), node.get("inbound_id"), existing.get("email"))
        except Exception as e:
            failed += 1
            logger.warning("subscription node refresh error profile=%s node=%s/%s: %s", profile.get("id"), node.get("server_id"), node.get("inbound_id"), e)
        finally:
            await cli.close()

    for node in missing_nodes:
        inbound_id = int(node.get("inbound_id") or 1)
        client_uuid = str(uuid.uuid4())
        node_email = f"{profile['email']}_n{node['id']}"[:120]
        cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
        try:
            ok = await cli.add_client(inbound_id, client_uuid, node_email, traffic_gb, duration_days, starts_on_first_use=False)
            if ok and expire_ms > 0:
                ok = await cli.update_client(inbound_id, client_uuid, node_email, traffic_gb, expire_ms, True)
            if not ok:
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
                logger.warning("subscription missing node add failed profile=%s node=%s/%s email=%s", profile.get("id"), node.get("server_id"), inbound_id, node_email)
                continue
            link = await cli.get_client_link(inbound_id, node_email) or ""
            if not link:
                failed += 1
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
            logger.warning("subscription missing node add error profile=%s node=%s/%s: %s", profile.get("id"), node.get("server_id"), inbound_id, e)
        finally:
            await cli.close()
    if created or refreshed or failed:
        logger.info(
            "subscription node ensure profile=%s created=%s refreshed=%s failed=%s missing=%s refresh=%s",
            profile.get("id"),
            created,
            refreshed,
            failed,
            len(missing_nodes),
            len(refresh_nodes),
        )
    return {"created": created, "refreshed": refreshed, "skipped": 0, "failed": failed}


async def repair_subscription_profile_expiry(profile: Dict) -> Dict:
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
    nodes = await get_subscription_nodes(profile_id)
    profile = None
    for node in nodes:
        cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
        try:
            traffic_gb = 1
            expire_ms = 0
            if profile is None:
                from core.database import get_subscription_profile
                profile = await get_subscription_profile(profile_id)
            if profile:
                traffic_gb = float(profile.get("traffic_gb") or 0)
                expire_ms = int(profile.get("expire_timestamp") or 0)
            ok = await cli.update_client(node["inbound_id"], node["uuid"], node["email"], traffic_gb, expire_ms, bool(enabled))
            if ok:
                await update_subscription_node(node["id"], is_active=1 if enabled else 0)
        except Exception:
            pass
        finally:
            await cli.close()


async def renew_subscription_profile(profile: Dict, traffic_gb: float, duration_days: int) -> Dict:
    nodes = await get_subscription_nodes(profile["id"])
    now_ms = int(time.time() * 1000)
    base_expire = max(int(profile.get("expire_timestamp") or 0), now_ms)
    new_expire_ms = base_expire + int(duration_days) * 86400000 if int(duration_days) > 0 else 0
    ok_count = 0
    failures = []
    for node in nodes:
        cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
        try:
            ok = await cli.update_client(node["inbound_id"], node["uuid"], node["email"], traffic_gb, new_expire_ms, True)
            if ok:
                await cli.reset_client_traffic(node["inbound_id"], node["email"])
                await update_subscription_node(node["id"], is_active=1, last_used_bytes=0)
                ok_count += 1
            else:
                failures.append(f"{node.get('server_name') or node.get('server_id')}#{node.get('inbound_id')}")
        finally:
            await cli.close()
    if ok_count <= 0:
        return {"ok": False, "error": "no_nodes_updated:" + ",".join(failures[:6])}
    await update_subscription_profile(
        profile["id"],
        traffic_gb=float(traffic_gb),
        duration_days=int(duration_days),
        expire_timestamp=new_expire_ms,
        used_bytes=0,
        is_active=1,
    )
    return {"ok": True, "nodes": ok_count, "expire_ms": new_expire_ms}


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
            if ok:
                link = await cli.get_client_link(node["inbound_id"], new_node_email) or node.get("link", "")
                await update_subscription_node(
                    node["id"],
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
    await update_subscription_profile(
        profile["id"],
        email=email,
        traffic_gb=float(traffic_gb),
        duration_days=max(0, duration_days),
        expire_timestamp=int(expire_ms or 0),
        is_active=1 if is_active else 0,
    )
    return {"ok": True, "nodes": ok_count, "expire_ms": int(expire_ms or 0)}


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


async def sync_active_profiles(limit: int = 100) -> int:
    checked = 0
    for profile in await get_active_subscription_profiles(limit):
        result = await sync_profile_usage(profile)
        if not result.get("disabled"):
            fresh = await get_subscription_profile_by_token(profile["token"]) or profile
            await ensure_subscription_profile_nodes(fresh)
        checked += 1
    return checked


async def sync_subscription_nodes_for_all(limit: int = 1000) -> Dict:
    checked = created = refreshed = failed = skipped = disabled = 0
    for profile in await get_active_subscription_profiles(limit):
        usage = await sync_profile_usage(profile)
        checked += 1
        if usage.get("disabled"):
            disabled += 1
            continue
        fresh = await get_subscription_profile_by_token(profile["token"]) or profile
        result = await ensure_subscription_profile_nodes(fresh)
        created += int(result.get("created") or 0)
        refreshed += int(result.get("refreshed") or 0)
        failed += int(result.get("failed") or 0)
        skipped += int(result.get("skipped") or 0)
    return {
        "checked": checked,
        "created": created,
        "refreshed": refreshed,
        "failed": failed,
        "skipped": skipped,
        "disabled": disabled,
    }
