import base64
import binascii
import json
import logging
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
    count_active_server_load,
    count_active_subscription_nodes_by_target,
    get_available_subscription_node_configs,
    get_setting,
    get_subscription_nodes,
    get_subscription_profile_by_token,
    update_subscription_node,
    update_subscription_profile,
)
from core.xui_api import XUIClient, expiry_ms_from_days


logger = logging.getLogger(__name__)


def total_bytes(traffic_gb: float) -> int:
    return int(float(traffic_gb or 0) * 1024 ** 3)


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
        return bool(obj and obj.get("add") and obj.get("port") and obj.get("id"))
    if scheme in {"vless", "trojan"}:
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


async def _ensure_node_link(node: Dict) -> str:
    link = (node.get("link") or "").strip()
    if _subscription_link_is_complete(link):
        return link

    cli = XUIClient(
        node["server_url"],
        node["srv_user"],
        node["srv_pass"],
        node.get("sub_path") or "",
        node.get("srv_api_token", ""),
    )
    try:
        refreshed = await cli.get_client_link(int(node.get("inbound_id") or 0), node.get("email") or "")
        refreshed = (refreshed or "").strip()
        if _subscription_link_is_complete(refreshed):
            await update_subscription_node(node["id"], link=refreshed)
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


async def render_subscription(token: str) -> tuple[str, Dict[str, int]] | None:
    profile = await get_subscription_profile_by_token(token)
    if not profile or not int(profile.get("is_active") or 0):
        return None
    if await get_setting("sub_info_sync_on_render", "1") == "1":
        try:
            await sync_profile_usage(profile)
            profile = await get_subscription_profile_by_token(token) or profile
        except Exception:
            pass
    nodes = await get_subscription_nodes(profile["id"])
    links = []
    active_count = 0
    for n in nodes:
        if not int(n.get("is_active") or 0):
            continue
        raw_link = await _ensure_node_link(n)
        if not raw_link:
            continue
        label = n.get("node_label") or f"{n.get('server_name') or 'Node'} #{n.get('inbound_id') or ''}"
        link = _label_subscription_link(raw_link, label)
        if _subscription_link_is_complete(link):
            active_count += 1
            links.append(link)
    used = int(profile.get("used_bytes") or 0)
    total = total_bytes(profile.get("traffic_gb") or 0)
    expire = int(int(profile.get("expire_timestamp") or 0) / 1000) if int(profile.get("expire_timestamp") or 0) > 0 else 0
    info_links = await _subscription_info_links(profile, used, total, active_count)
    links = _dedupe_complete_links(info_links + links)
    body = base64.b64encode("\n".join(links).encode()).decode()
    return body, {"upload": 0, "download": used, "total": total, "expire": expire}


async def sync_profile_usage(profile: Dict) -> Dict:
    nodes = await get_subscription_nodes(profile["id"])
    used_total = 0
    total_limit = total_bytes(profile.get("traffic_gb") or 0)
    now_ms = int(time.time() * 1000)
    expired = int(profile.get("expire_timestamp") or 0) > 0 and int(profile.get("expire_timestamp") or 0) <= now_ms

    for node in nodes:
        cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
        try:
            traffic = await cli.get_client_traffic(node["email"])
            used = int((traffic or {}).get("down") or 0) + int((traffic or {}).get("up") or 0)
            used_total += used
            await update_subscription_node(node["id"], last_used_bytes=used)
        finally:
            await cli.close()

    should_disable = expired or (total_limit > 0 and used_total >= total_limit)
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
            await cli.update_client(node["inbound_id"], node["uuid"], node["email"], traffic_gb, expire_ms, bool(enabled))
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
        await sync_profile_usage(profile)
        checked += 1
    return checked
