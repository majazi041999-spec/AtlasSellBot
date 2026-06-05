import base64
import secrets
import time
import uuid
from typing import Dict, List

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


async def render_subscription(token: str) -> tuple[str, Dict[str, int]] | None:
    profile = await get_subscription_profile_by_token(token)
    if not profile or not int(profile.get("is_active") or 0):
        return None
    nodes = await get_subscription_nodes(profile["id"])
    links = [n.get("link") or "" for n in nodes if int(n.get("is_active") or 0) and n.get("link")]
    used = int(profile.get("used_bytes") or 0)
    total = total_bytes(profile.get("traffic_gb") or 0)
    expire = int(int(profile.get("expire_timestamp") or 0) / 1000) if int(profile.get("expire_timestamp") or 0) > 0 else 0
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


async def sync_active_profiles(limit: int = 100) -> int:
    checked = 0
    for profile in await get_active_subscription_profiles(limit):
        await sync_profile_usage(profile)
        checked += 1
    return checked
