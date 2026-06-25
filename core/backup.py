"""Backup of all registered X-UI panels (plus the bot's own DB) into one zip.

For every registered server we try to grab the raw `x-ui.db` (the panel backup
file); regardless, we always export the full inbounds JSON via the API so the
data is captured even if the raw DB download isn't available. The bot's own
`atlas.db` is included too. Used by the scheduled backup worker and the panel.
"""
import asyncio
import json
import logging
import os
import re
import sqlite3
import tempfile
from datetime import datetime
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

from core.config import DB_PATH
from core.database import get_servers
from core.xui_api import XUIClient

logger = logging.getLogger(__name__)

_PER_SERVER_TIMEOUT = 60


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name or "")).strip("_") or "x"


def _atlas_db_snapshot() -> bytes | None:
    db_path = DB_PATH if os.path.isabs(DB_PATH) else os.path.join(os.getcwd(), DB_PATH)
    if not os.path.exists(db_path):
        return None
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    try:
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(tmp.name)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        with open(tmp.name, "rb") as f:
            return f.read()
    except Exception as e:
        logger.warning("atlas.db snapshot failed: %s", e)
        return None
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


async def _backup_one_server(srv: dict) -> dict:
    """Fetch a single server's backup data. Returns a dict with bytes/json."""
    out = {
        "id": srv.get("id"),
        "name": srv.get("name") or srv.get("url"),
        "url": srv.get("url"),
        "ok": False,
        "db_bytes": None,
        "inbounds": None,
        "inbound_count": 0,
        "client_count": 0,
        "error": "",
    }
    cli = XUIClient(srv["url"], srv["username"], srv["password"], srv.get("sub_path") or "", srv.get("api_token", ""))
    try:
        try:
            out["db_bytes"] = await asyncio.wait_for(cli.download_db(), timeout=_PER_SERVER_TIMEOUT)
        except Exception as e:
            logger.info("raw db download unavailable for server %s: %s", out["name"], e)
        try:
            inbounds = await asyncio.wait_for(cli.get_inbounds(), timeout=_PER_SERVER_TIMEOUT)
        except Exception as e:
            inbounds = []
            out["error"] = f"inbounds: {e}"
        out["inbounds"] = inbounds or []
        out["inbound_count"] = len(out["inbounds"])
        clients = 0
        for ib in out["inbounds"]:
            try:
                settings = ib.get("settings")
                if isinstance(settings, str):
                    settings = json.loads(settings)
                clients += len(settings.get("clients", []) or [])
            except Exception:
                pass
        out["client_count"] = clients
        out["ok"] = bool(out["db_bytes"]) or out["inbound_count"] > 0
    except Exception as e:
        out["error"] = str(e)[:200]
    finally:
        await cli.close()
    return out


async def build_servers_backup() -> tuple[str, bytes]:
    """Build a single zip containing every panel's data + the bot DB.

    Returns (filename, zip_bytes).
    """
    servers = await get_servers(active_only=False)
    results = await asyncio.gather(*(_backup_one_server(s) for s in servers), return_exceptions=True)

    manifest = {
        "app": "AtlasSellBot",
        "kind": "servers-backup",
        "created_at": datetime.now().isoformat(),
        "server_total": len(servers),
        "servers": [],
    }
    buf = BytesIO()
    ok_count = 0
    with ZipFile(buf, "w", compression=ZIP_DEFLATED) as z:
        for res in results:
            if isinstance(res, Exception):
                manifest["servers"].append({"ok": False, "error": str(res)[:200]})
                continue
            folder = f"server_{res['id']}_{_safe(res['name'])}"
            if res.get("db_bytes"):
                z.writestr(f"{folder}/x-ui.db", res["db_bytes"])
            if res.get("inbounds") is not None:
                z.writestr(f"{folder}/inbounds.json", json.dumps(res["inbounds"], ensure_ascii=False, indent=2))
            manifest["servers"].append({
                "id": res["id"],
                "name": res["name"],
                "url": res["url"],
                "ok": res["ok"],
                "raw_db": bool(res.get("db_bytes")),
                "inbounds": res["inbound_count"],
                "clients": res["client_count"],
                "error": res.get("error") or "",
            })
            if res["ok"]:
                ok_count += 1

        atlas = _atlas_db_snapshot()
        if atlas:
            z.writestr("atlas-bot/atlas.db", atlas)
            manifest["atlas_db"] = True

        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    buf.seek(0)
    fname = f"atlas-servers-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    return fname, buf.getvalue()
