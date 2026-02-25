import httpx
import json
import math
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from urllib.parse import urlparse
import base64

logger = logging.getLogger(__name__)


class XUIClient:
    def __init__(self, base_url: str, username: str, password: str, sub_path: str = ""):
        self.base_url = base_url.rstrip("/")
        sub = sub_path.strip("/")
        self.panel_url = f"{self.base_url}/{sub}" if sub else self.base_url
        self.username = username
        self.password = password
        self._cookie: Optional[str] = None
        self._http = httpx.AsyncClient(verify=False, timeout=20.0)

    async def _login(self) -> bool:
        try:
            r = await self._http.post(
                f"{self.panel_url}/login",
                data={"username": self.username, "password": self.password}
            )
            if r.status_code == 200 and r.json().get("success"):
                self._cookie = "; ".join(f"{k}={v}" for k, v in r.cookies.items())
                return True
        except Exception as e:
            logger.error(f"XUI login error: {e}")
        return False

    async def _req(self, method: str, path: str, **kw) -> Optional[Dict]:
        if not self._cookie:
            if not await self._login():
                return None
        try:
            r = await self._http.request(
                method, f"{self.panel_url}{path}",
                headers={"Cookie": self._cookie}, **kw
            )
            if r.status_code == 401:
                self._cookie = None
                if not await self._login():
                    return None
                r = await self._http.request(
                    method, f"{self.panel_url}{path}",
                    headers={"Cookie": self._cookie}, **kw
                )
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            logger.error(f"XUI request error {path}: {e}")
        return None

    async def test_connection(self) -> bool:
        return await self._login()

    async def get_inbounds(self) -> List[Dict]:
        r = await self._req("GET", "/panel/api/inbounds/list")
        return r.get("obj", []) if r and r.get("success") else []

    async def get_inbound(self, iid: int) -> Optional[Dict]:
        r = await self._req("GET", f"/panel/api/inbounds/get/{iid}")
        return r.get("obj") if r and r.get("success") else None

    async def get_client_traffic(self, email: str) -> Optional[Dict]:
        r = await self._req("GET", f"/panel/api/inbounds/getClientTraffics/{email}")
        return r.get("obj") if r and r.get("success") else None

    async def add_client(self, inbound_id: int, client_uuid: str, email: str,
                          traffic_gb: float, expire_days: int) -> bool:
        inbound = await self.get_inbound(inbound_id)
        protocol = inbound.get("protocol", "vless") if inbound else "vless"
        traffic_bytes = int(traffic_gb * 1024 ** 3)
        expire_ms = int((datetime.now() + timedelta(days=expire_days)).timestamp() * 1000) if expire_days > 0 else 0

        if protocol == "trojan":
            client = {"password": client_uuid, "email": email, "totalGB": traffic_bytes,
                      "expiryTime": expire_ms, "enable": True, "tgId": "", "subId": "", "limitIp": 0}
        else:
            client = {"id": client_uuid, "email": email, "totalGB": traffic_bytes,
                      "expiryTime": expire_ms, "enable": True, "tgId": "", "subId": "",
                      "limitIp": 0, "flow": ""}

        payload = {"id": inbound_id, "settings": json.dumps({"clients": [client]})}
        r = await self._req("POST", "/panel/api/inbounds/addClient", json=payload)
        return bool(r and r.get("success"))

    async def update_client(self, inbound_id: int, client_uuid: str, email: str,
                             traffic_gb: float, expire_ms: int, enable: bool = True) -> bool:
        inbound = await self.get_inbound(inbound_id)
        protocol = inbound.get("protocol", "vless") if inbound else "vless"
        traffic_bytes = int(traffic_gb * 1024 ** 3)

        if protocol == "trojan":
            client = {"password": client_uuid, "email": email, "totalGB": traffic_bytes,
                      "expiryTime": expire_ms, "enable": enable, "tgId": "", "subId": "", "limitIp": 0}
        else:
            client = {"id": client_uuid, "email": email, "totalGB": traffic_bytes,
                      "expiryTime": expire_ms, "enable": enable, "tgId": "", "subId": "",
                      "limitIp": 0, "flow": ""}

        payload = {"id": inbound_id, "settings": json.dumps({"clients": [client]})}
        r = await self._req("POST", f"/panel/api/inbounds/updateClient/{client_uuid}", json=payload)
        return bool(r and r.get("success"))

    async def delete_client(self, inbound_id: int, client_uuid: str) -> bool:
        r = await self._req("POST", f"/panel/api/inbounds/{inbound_id}/delClient/{client_uuid}")
        return bool(r and r.get("success"))

    async def get_client_link(self, inbound_id: int, email: str) -> Optional[str]:
        try:
            inbound = await self.get_inbound(inbound_id)
            if not inbound:
                return None
            protocol = inbound.get("protocol", "vless")
            settings = json.loads(inbound.get("settings", "{}"))
            stream = json.loads(inbound.get("streamSettings", "{}"))
            clients = settings.get("clients", [])
            client = next((c for c in clients if c.get("email") == email), None)
            if not client:
                return None

            parsed = urlparse(self.base_url)
            host = parsed.hostname or "example.com"
            port = inbound.get("port", 443)
            network = stream.get("network", "tcp")
            security = stream.get("security", "none")

            if protocol == "vless":
                cid = client.get("id", "")
                params = [f"type={network}", f"security={security}"]
                if security == "reality":
                    rs = stream.get("realitySettings", {})
                    names = rs.get("serverNames", [""])
                    pk = rs.get("settings", {}).get("publicKey", "")
                    sid_val = (rs.get("shortIds", [""]) or [""])[0]
                    fp = rs.get("settings", {}).get("fingerprint", "chrome")
                    if names: params.append(f"sni={names[0]}")
                    if pk: params.append(f"pbk={pk}")
                    if sid_val: params.append(f"sid={sid_val}")
                    params.append(f"fp={fp}")
                elif security == "tls":
                    tls = stream.get("tlsSettings", {})
                    sni = tls.get("serverName", host)
                    if sni: params.append(f"sni={sni}")
                if network == "ws":
                    ws = stream.get("wsSettings", {})
                    params.append(f"path={ws.get('path','/')}")
                elif network == "grpc":
                    grpc = stream.get("grpcSettings", {})
                    params.append(f"serviceName={grpc.get('serviceName','')}")
                    params.append("mode=gun")
                flow = client.get("flow", "")
                if flow: params.append(f"flow={flow}")
                return f"vless://{cid}@{host}:{port}?{'&'.join(params)}#{email}"

            elif protocol == "vmess":
                cid = client.get("id", "")
                cfg = {"v": "2", "ps": email, "add": host, "port": str(port), "id": cid,
                       "aid": str(client.get("alterId", 0)), "scy": "auto", "net": network,
                       "type": "none", "host": "", "path": "", "tls": security if security != "none" else ""}
                if network == "ws":
                    ws = stream.get("wsSettings", {})
                    cfg["path"] = ws.get("path", "/")
                encoded = base64.urlsafe_b64encode(json.dumps(cfg).encode()).decode()
                return f"vmess://{encoded}"

            elif protocol == "trojan":
                pw = client.get("password", "")
                params = [f"type={network}", f"security={security}"]
                if security in ("tls", "reality"):
                    tls = stream.get("tlsSettings", stream.get("realitySettings", {}))
                    sni = tls.get("serverName", host)
                    if sni: params.append(f"sni={sni}")
                return f"trojan://{pw}@{host}:{port}?{'&'.join(params)}#{email}"

            elif protocol == "shadowsocks":
                method = settings.get("method", "chacha20-poly1305")
                password = settings.get("password", "")
                userinfo = base64.urlsafe_b64encode(f"{method}:{password}".encode()).decode().rstrip("=")
                return f"ss://{userinfo}@{host}:{port}#{email}"

        except Exception as e:
            logger.error(f"get_client_link error: {e}")
        return None

    async def close(self):
        await self._http.aclose()


# ── Utility functions ──

def fmt_bytes(b: int) -> str:
    if b <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = min(int(math.floor(math.log(max(b, 1), 1024))), 4)
    return f"{b / (1024 ** i):.2f} {units[i]}"

def days_left(expire_ms: int) -> int:
    """Returns days left. -1 = unlimited, 0 = expired"""
    if expire_ms <= 0:
        return -1
    diff = expire_ms - int(time.time() * 1000)
    return max(0, int(diff / 86_400_000))

def used_pct(total: int, down: int, up: int) -> int:
    if total <= 0:
        return 0
    return min(100, int((down + up) / total * 100))
