import httpx
import json
import math
import secrets
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from urllib.parse import urlparse, quote
import base64

logger = logging.getLogger(__name__)


class XUIClient:
    def __init__(self, base_url: str, username: str, password: str, sub_path: str = "", api_token: str = ""):
        self.base_url = base_url.rstrip("/")
        sub = sub_path.strip("/")
        self.panel_url = f"{self.base_url}/{sub}" if sub else self.base_url
        self.username = username
        self.password = password
        self.api_token = (api_token or "").strip()
        self._cookie: Optional[str] = None
        self._csrf_token: Optional[str] = None
        self.last_error: str = ""
        self._http = httpx.AsyncClient(verify=False, timeout=20.0)

    async def _login(self) -> bool:
        try:
            r = await self._http.post(
                f"{self.panel_url}/login",
                data={"username": self.username, "password": self.password}
            )
            if r.status_code == 200 and r.json().get("success"):
                self._cookie = "; ".join(f"{k}={v}" for k, v in r.cookies.items())
                await self._load_csrf_token()
                return True
        except Exception as e:
            logger.error(f"XUI login error: {e}")
        return False

    async def _load_csrf_token(self) -> None:
        try:
            r = await self._http.get(
                f"{self.panel_url}/csrf-token",
                headers={"Cookie": self._cookie or ""},
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("success"):
                    self._csrf_token = data.get("obj") or data.get("token")
        except Exception:
            self._csrf_token = None

    def _headers(self, extra: Optional[Dict[str, str]] = None, unsafe: bool = False) -> Dict[str, str]:
        headers = dict(extra or {})
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        elif self._cookie:
            headers["Cookie"] = self._cookie
            if unsafe and self._csrf_token:
                headers["X-CSRF-Token"] = self._csrf_token
        return headers

    async def _req(self, method: str, path: str, **kw) -> Optional[Dict]:
        unsafe = method.upper() not in {"GET", "HEAD", "OPTIONS", "TRACE"}
        if not self.api_token and not self._cookie:
            if not await self._login():
                return None
        try:
            headers = self._headers(kw.pop("headers", None), unsafe=unsafe)
            r = await self._http.request(
                method, f"{self.panel_url}{path}",
                headers=headers, **kw
            )
            if r.status_code in (401, 403) and not self.api_token:
                self._cookie = None
                self._csrf_token = None
                if not await self._login():
                    return None
                headers = self._headers(unsafe=unsafe)
                r = await self._http.request(
                    method, f"{self.panel_url}{path}",
                    headers=headers, **kw
                )
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and not data.get("success", True):
                    self.last_error = str(data.get("msg") or data.get("error") or data)[:500]
                return data
            self.last_error = f"HTTP {r.status_code}: {r.text[:300]}"
        except Exception as e:
            self.last_error = str(e)[:500]
            logger.error(f"XUI request error {path}: {e}")
        return None

    async def test_connection(self) -> bool:
        if self.api_token:
            r = await self._req("GET", "/panel/api/inbounds/options")
            return bool(r and r.get("success"))
        return await self._login()

    async def get_inbounds(self) -> List[Dict]:
        r = await self._req("GET", "/panel/api/inbounds/list")
        return r.get("obj", []) if r and r.get("success") else []

    async def get_inbound(self, iid: int) -> Optional[Dict]:
        r = await self._req("GET", f"/panel/api/inbounds/get/{iid}")
        return r.get("obj") if r and r.get("success") else None

    async def get_client_traffic(self, email: str) -> Optional[Dict]:
        enc = quote(email, safe="")
        r = await self._req("GET", f"/panel/api/clients/traffic/{enc}")
        if r and r.get("success"):
            return r.get("obj")
        r = await self._req("GET", f"/panel/api/inbounds/getClientTraffics/{enc}")
        return r.get("obj") if r and r.get("success") else None

    async def get_client(self, email: str) -> Optional[Dict]:
        enc = quote(email, safe="")
        r = await self._req("GET", f"/panel/api/clients/get/{enc}")
        if r and r.get("success"):
            obj = r.get("obj")
            if isinstance(obj, dict) and isinstance(obj.get("client"), dict):
                client = obj["client"]
                client["inboundIds"] = obj.get("inboundIds") or []
                return client
            return obj if isinstance(obj, dict) else None
        return None

    async def find_client(self, email: str = "", client_uuid: str = "") -> Optional[Dict]:
        email = (email or "").strip()
        client_uuid = (client_uuid or "").strip()

        api_client = None
        if email:
            api_client = await self.get_client(email)
            if api_client:
                inbound_ids = api_client.get("inboundIds") or api_client.get("inbound_ids") or []
                inbound_id = 0
                if isinstance(inbound_ids, list) and inbound_ids:
                    try:
                        inbound_id = int(inbound_ids[0])
                    except Exception:
                        inbound_id = 0
                if inbound_id:
                    return {"client": api_client, "inbound_id": inbound_id, "inbound": None}

        for inbound in await self.get_inbounds():
            settings = self._json_obj(inbound.get("settings"), {})
            for client in settings.get("clients", []) or []:
                ident = client.get("id") or client.get("password") or client.get("auth") or ""
                if (email and client.get("email") == email) or (client_uuid and ident == client_uuid):
                    return {
                        "client": client,
                        "inbound_id": int(inbound.get("id") or 0),
                        "inbound": inbound,
                    }
        if api_client:
            return {"client": api_client, "inbound_id": 0, "inbound": None}
        return None

    def _json_obj(self, value: Any, default: Optional[Any] = None) -> Any:
        if default is None:
            default = {}
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return json.loads(value)
            except Exception:
                return default
        return default

    def _client_payload(self, protocol: str, client_uuid: str, email: str, traffic_bytes: int,
                        expire_ms: int, enable: bool = True, existing: Optional[Dict] = None) -> Dict:
        existing = dict(existing or {})
        sub_id = existing.get("subId") or secrets.token_hex(8)
        base = {
            "email": email,
            "totalGB": traffic_bytes,
            "expiryTime": expire_ms,
            "enable": enable,
            "tgId": existing.get("tgId", 0) or 0,
            "subId": sub_id,
            "limitIp": existing.get("limitIp", 0) or 0,
            "reset": existing.get("reset", 0) or 0,
            "comment": existing.get("comment", "") or "",
        }
        if existing.get("group"):
            base["group"] = existing.get("group")

        if protocol == "trojan":
            base["password"] = existing.get("password") or client_uuid
        elif protocol == "shadowsocks":
            base["password"] = existing.get("password") or client_uuid.replace("-", "")
            if existing.get("method"):
                base["method"] = existing.get("method")
        elif protocol == "hysteria":
            base["auth"] = existing.get("auth") or client_uuid.replace("-", "")
        else:
            base["id"] = existing.get("id") or existing.get("uuid") or client_uuid
            base["flow"] = existing.get("flow", "") or ""
            if existing.get("security"):
                base["security"] = existing.get("security")
        return base

    async def add_client(self, inbound_id: int, client_uuid: str, email: str,
                          traffic_gb: float, expire_days: int, starts_on_first_use: bool = False) -> bool:
        inbound = await self.get_inbound(inbound_id)
        protocol = inbound.get("protocol", "vless") if inbound else "vless"
        traffic_bytes = int(traffic_gb * 1024 ** 3)
        expire_ms = expiry_ms_from_days(expire_days)

        client = self._client_payload(protocol, client_uuid, email, traffic_bytes, expire_ms, True)

        payload = {"client": client, "inboundIds": [int(inbound_id)]}
        r = await self._req("POST", "/panel/api/clients/add", json=payload)
        if r and r.get("success"):
            return True

        payload = {"id": inbound_id, "settings": json.dumps({"clients": [client]})}
        r = await self._req("POST", "/panel/api/inbounds/addClient", json=payload)
        if r and r.get("success"):
            return True
        return False

    async def update_client(self, inbound_id: int, client_uuid: str, email: str,
                             traffic_gb: float, expire_ms: int, enable: bool = True,
                             new_email: Optional[str] = None) -> bool:
        inbound = await self.get_inbound(inbound_id)
        protocol = inbound.get("protocol", "vless") if inbound else "vless"
        traffic_bytes = int(traffic_gb * 1024 ** 3)
        payload_email = (new_email or email or "").strip()

        existing = await self.get_client(email)
        if not existing and payload_email != email:
            existing = await self.get_client(payload_email)
        client = self._client_payload(protocol, client_uuid, payload_email, traffic_bytes, expire_ms, enable, existing)

        r = await self._req("POST", f"/panel/api/clients/update/{quote(email, safe='')}", json=client)
        if r and r.get("success"):
            return True

        payload = {"id": inbound_id, "settings": json.dumps({"clients": [client]})}
        r = await self._req("POST", f"/panel/api/inbounds/updateClient/{client_uuid}", json=payload)
        if r and r.get("success"):
            return True
        return False

    async def reset_client_traffic(self, inbound_id: int, email: str) -> bool:
        enc = quote(email, safe="")
        r = await self._req("POST", f"/panel/api/inbounds/{int(inbound_id)}/resetClientTraffic/{enc}")
        if r and r.get("success"):
            return True
        r = await self._req("POST", f"/panel/api/clients/resetTraffic/{enc}")
        return bool(r and r.get("success"))

    async def delete_client(self, inbound_id: int, client_uuid: str, email: str = "") -> bool:
        if not email:
            inbound = await self.get_inbound(inbound_id)
            if inbound:
                settings = self._json_obj(inbound.get("settings"), {})
                for c in settings.get("clients", []) or []:
                    ident = c.get("id") or c.get("password") or c.get("auth") or c.get("email")
                    if ident == client_uuid:
                        email = c.get("email", "")
                        break
        if email:
            r = await self._req("POST", f"/panel/api/clients/del/{quote(email, safe='')}")
            if r and r.get("success"):
                return True
        r = await self._req("POST", f"/panel/api/inbounds/{inbound_id}/delClient/{client_uuid}")
        return bool(r and r.get("success"))

    async def get_client_link(self, inbound_id: int, email: str) -> Optional[str]:
        try:
            r = await self._req("GET", f"/panel/api/clients/links/{quote(email, safe='')}")
            if r and r.get("success"):
                obj = r.get("obj")
                if isinstance(obj, list) and obj:
                    return str(obj[0])
                if isinstance(obj, str) and obj:
                    return obj

            inbound = await self.get_inbound(inbound_id)
            if not inbound:
                return None
            protocol = inbound.get("protocol", "vless")
            settings = self._json_obj(inbound.get("settings"), {})
            stream = self._json_obj(inbound.get("streamSettings"), {})
            clients = settings.get("clients", [])
            client = next((c for c in clients if c.get("email") == email), None)
            if not client:
                client = await self.get_client(email)
            if not client:
                return None

            parsed = urlparse(self.base_url)
            host = parsed.hostname or "example.com"
            port = inbound.get("port", 443)
            network = stream.get("network", "tcp")
            security = stream.get("security", "none")

            if protocol == "vless":
                cid = client.get("id", "")
                # برای سازگاری با کلاینت‌ها، encryption را صراحتاً ارسال می‌کنیم.
                params = [f"type={network}", "encryption=none", f"security={security}"]
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
                    params.append(f"path={quote(ws.get('path', '/'), safe='')}")
                    ws_host = ws.get("host", "")
                    if ws_host:
                        params.append(f"host={ws_host}")
                elif network == "tcp":
                    # در TCP اگر header از نوع http باشد، path/host را به لینک اضافه می‌کنیم.
                    tcp = stream.get("tcpSettings", {})
                    header = tcp.get("header", {}) if isinstance(tcp, dict) else {}
                    h_type = header.get("type", "none")
                    params.append(f"headerType={h_type}")
                    if h_type == "http":
                        req = header.get("request", {}) if isinstance(header, dict) else {}
                        path = req.get("path", "/")
                        if isinstance(path, list):
                            path = path[0] if path else "/"
                        host_list = req.get("headers", {}).get("Host", [])
                        host_header = host_list[0] if isinstance(host_list, list) and host_list else ""
                        params.append(f"path={quote(path or '/', safe='')}")
                        if host_header:
                            params.append(f"host={host_header}")
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



    async def get_subscription_link(self, inbound_id: int, email: str) -> Optional[str]:
        try:
            inbound = await self.get_inbound(inbound_id)
            if not inbound:
                return None
            settings = self._json_obj(inbound.get("settings"), {})
            clients = settings.get("clients", [])
            client = next((c for c in clients if c.get("email") == email), None)
            if not client:
                client = await self.get_client(email)
            if not client:
                return None
            sub_id = client.get("subId", "")
            if not sub_id:
                return None
            parsed = urlparse(self.base_url)
            host = parsed.hostname or "example.com"
            port = parsed.port
            scheme = parsed.scheme or "https"
            base = f"{scheme}://{host}" + (f":{port}" if port else "")
            return f"{base}/sub/{sub_id}"
        except Exception as e:
            logger.error(f"get_subscription_link error: {e}")
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
    if diff <= 0:
        return 0
    return max(1, int(math.ceil(diff / 86_400_000)))

def used_pct(total: int, down: int, up: int) -> int:
    if total <= 0:
        return 0
    return min(100, int((down + up) / total * 100))

def expiry_ms_from_days(days: int) -> int:
    days = int(days or 0)
    if days <= 0:
        return 0
    return int((datetime.now() + timedelta(days=days)).timestamp() * 1000)
