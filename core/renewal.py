import time
import logging
from datetime import datetime
from typing import Dict, Optional

from core.database import get_server, get_servers, update_config, clear_config_alerts
from core.xui_api import XUIClient

logger = logging.getLogger(__name__)


async def find_and_renew_config(cfg: Dict, traffic_gb: float, duration_days: int) -> Dict:
    now_ms = int(time.time() * 1000)
    servers = []

    current = await get_server(int(cfg.get("server_id") or 0))
    if current:
        servers.append(current)

    for srv in await get_servers(active_only=False):
        if not any(int(s.get("id") or 0) == int(srv.get("id") or 0) for s in servers):
            servers.append(srv)

    last_error: Optional[str] = None
    for server in servers:
        client = XUIClient(
            server["url"],
            server["username"],
            server["password"],
            server.get("sub_path") or "",
            server.get("api_token", ""),
        )
        try:
            found = await client.find_client(cfg.get("email") or "", cfg.get("uuid") or "")
            if not found:
                last_error = f"not found on server {server.get('name') or server.get('id')}"
                continue

            remote = found.get("client") or {}
            inbound_id = int(found.get("inbound_id") or cfg.get("inbound_id") or server.get("inbound_id") or 1)
            remote_email = (remote.get("email") or cfg.get("email") or "").strip()
            client_uuid = (
                remote.get("id")
                or remote.get("uuid")
                or remote.get("password")
                or remote.get("auth")
                or cfg.get("uuid")
                or ""
            )
            if not client_uuid:
                last_error = "client uuid/password not found"
                continue

            if not remote_email:
                last_error = "client email not found"
                continue

            remote_expire = int(remote.get("expiryTime") or 0)
            if remote_email:
                traffic = await client.get_client_traffic(remote_email)
                if traffic:
                    remote_expire = max(remote_expire, int(traffic.get("expiryTime") or 0))

            base_expire = max(int(cfg.get("expire_timestamp") or 0), remote_expire, now_ms)
            new_expire_ms = base_expire + int(duration_days) * 86400000 if int(duration_days) > 0 else 0
            ok = await client.update_client(inbound_id, client_uuid, remote_email, traffic_gb, new_expire_ms, True)
            if not ok:
                last_error = f"update failed on server {server.get('name')}"
                continue

            await client.reset_client_traffic(inbound_id, remote_email)
            link = await client.get_client_link(inbound_id, remote_email)
            sub = await client.get_subscription_link(inbound_id, remote_email)

            await update_config(
                cfg["id"],
                server_id=server["id"],
                uuid=client_uuid,
                inbound_id=inbound_id,
                traffic_gb=traffic_gb,
                duration_days=int(duration_days),
                expire_timestamp=new_expire_ms,
                is_active=1,
                starts_on_first_use=0,
                first_use_at="",
            )
            await clear_config_alerts(cfg["id"])
            return {
                "ok": True,
                "server": server,
                "inbound_id": inbound_id,
                "uuid": client_uuid,
                "expire_ms": new_expire_ms,
                "link": link,
                "sub": sub,
                "renewed_at": datetime.now().isoformat(),
            }
        except Exception as e:
            last_error = f"{server.get('name') or server.get('id')}: {type(e).__name__}"
            logger.exception("renew search/update failed on server %s: %s", server.get("name") or server.get("id"), e)
        finally:
            await client.close()

    return {"ok": False, "error": last_error or "config not found on any registered server"}
