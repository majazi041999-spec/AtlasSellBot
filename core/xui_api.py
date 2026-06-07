import httpx
import json
import math
import secrets
import time
import logging
import uuid as uuidlib
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from urllib.parse import urlparse, quote, urlencode, parse_qsl
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
            if r.status_code != 200:
                self.last_error = f"login_failed HTTP {r.status_code}: {r.text[:300]}"
                return False
            try:
                data = r.json()
            except Exception:
                self.last_error = f"login_failed invalid_response: {r.text[:300]}"
                return False
            if data.get("success"):
                self._cookie = "; ".join(f"{k}={v}" for k, v in r.cookies.items())
                await self._load_csrf_token()
                self.last_error = ""
                return True
            self.last_error = f"login_failed: {str(data.get('msg') or data.get('error') or data)[:300]}"
        except Exception as e:
            self.last_error = f"login_failed: {str(e)[:300]}"
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

    def _allow_token_write(self, path: str) -> bool:
        if not self.api_token:
            return False
        safe_prefixes = (
            "/panel/api/clients/add",
            "/panel/api/clients/update/",
            "/panel/api/clients/del/",
            "/panel/api/clients/bulkDel",
            "/panel/api/clients/resetTraffic/",
            "/panel/api/inbounds/addClient",
            "/panel/api/inbounds/updateClient/",
        )
        if any(path.startswith(prefix) for prefix in safe_prefixes):
            return True
        if path.startswith("/panel/api/inbounds/"):
            return any(part in path for part in ("/delClient/", "/delClientByEmail/", "/resetClientTraffic/"))
        return False

    def _headers(self, extra: Optional[Dict[str, str]] = None, unsafe: bool = False,
                 token_write: bool = False) -> Dict[str, str]:
        headers = dict(extra or {})
        if self.api_token and (not unsafe or token_write):
            headers["Authorization"] = f"Bearer {self.api_token}"
        elif self._cookie:
            headers["Cookie"] = self._cookie
            if unsafe and self._csrf_token:
                headers["X-CSRF-Token"] = self._csrf_token
        return headers

    async def _req(self, method: str, path: str, **kw) -> Optional[Dict]:
        unsafe = method.upper() not in {"GET", "HEAD", "OPTIONS", "TRACE"}
        token_write_allowed = unsafe and self._allow_token_write(path)
        token_write = False
        login_error = ""
        if (unsafe or not self.api_token) and not self._cookie:
            if not await self._login():
                login_error = self.last_error or "login_failed"
                if token_write_allowed:
                    token_write = True
                else:
                    if unsafe and self.api_token:
                        self.last_error = f"{login_error}; unsafe_write_requires_panel_login"
                    elif not self.last_error:
                        self.last_error = "login_failed"
                    return None
        try:
            extra_headers = kw.pop("headers", None)
            headers = self._headers(extra_headers, unsafe=unsafe, token_write=token_write)
            r = await self._http.request(
                method, f"{self.panel_url}{path}",
                headers=headers, **kw
            )
            if r.status_code in (401, 403) and (unsafe or not self.api_token) and not token_write:
                self._cookie = None
                self._csrf_token = None
                if not await self._login():
                    login_error = self.last_error or f"HTTP {r.status_code}"
                    if token_write_allowed:
                        token_write = True
                    else:
                        if unsafe and self.api_token:
                            self.last_error = f"{login_error}; unsafe_write_requires_panel_login"
                        elif not self.last_error:
                            self.last_error = f"auth_failed HTTP {r.status_code}"
                        return None
                headers = self._headers(extra_headers, unsafe=unsafe, token_write=token_write)
                r = await self._http.request(
                    method, f"{self.panel_url}{path}",
                    headers=headers, **kw
                )
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and not data.get("success", True):
                    msg = str(data.get("msg") or data.get("error") or data)
                    if msg.strip().lower() in {"", "unknown", "none"}:
                        msg = f"{msg or 'api_error'} at {path}"
                    if token_write and login_error:
                        msg = f"{msg}; panel_login_failed: {login_error}"
                    self.last_error = msg[:500]
                else:
                    self.last_error = ""
                return data
            err = f"HTTP {r.status_code}: {r.text[:300]}"
            if token_write and login_error:
                err = f"{err}; panel_login_failed: {login_error}"
            self.last_error = err[:500]
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

        for inbound in await self.get_inbounds():
            protocol = inbound.get("protocol", "vless")
            client = self._find_inbound_client(inbound, protocol, email, client_uuid)
            if client:
                return {
                    "client": client,
                    "inbound_id": int(inbound.get("id") or 0),
                    "inbound": inbound,
                    }
        if api_client:
            protocol = str(api_client.get("protocol") or "vless")
            if not self._client_identity(protocol, api_client):
                return None
            inbound_ids = api_client.get("inboundIds") or api_client.get("inbound_ids") or []
            inbound_id = 0
            if isinstance(inbound_ids, list) and inbound_ids:
                try:
                    inbound_id = int(inbound_ids[0])
                except Exception:
                    inbound_id = 0
            return {"client": api_client, "inbound_id": inbound_id, "inbound": None}
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

    def _decode_b64_json(self, value: str) -> Optional[Dict]:
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

    def _link_is_complete(self, link: str) -> bool:
        raw = (link or "").strip()
        if not raw:
            return False
        scheme = raw.split("://", 1)[0].lower() if "://" in raw else ""
        if scheme == "vmess":
            obj = self._decode_b64_json(raw[8:])
            if not obj:
                return False
            return bool(obj.get("add") and obj.get("port") and self._normal_uuid(obj.get("id")))
        if scheme == "vless":
            try:
                parsed = urlparse(raw)
                port = parsed.port
            except Exception:
                return False
            return bool(parsed.hostname and port and self._normal_uuid(parsed.username))
        if scheme == "trojan":
            try:
                parsed = urlparse(raw)
                port = parsed.port
            except Exception:
                return False
            return bool(parsed.hostname and port and parsed.username)
        if scheme == "ss":
            try:
                parsed = urlparse(raw)
                port = parsed.port
            except Exception:
                return False
            return bool(parsed.hostname and port and parsed.netloc)
        return False

    def _first_complete_api_link(self, obj: Any) -> Optional[str]:
        links = obj if isinstance(obj, list) else [obj]
        for item in links:
            link = str(item or "").strip()
            if self._link_is_complete(link):
                return link
            if link:
                logger.warning("3x-ui returned incomplete client link; rebuilding locally")
        return None

    def _api_endpoint(self, api_link: Optional[str], scheme: str, fallback_host: str, fallback_port: Any) -> tuple[str, Any]:
        raw = (api_link or "").strip()
        if not raw.lower().startswith(f"{scheme.lower()}://") or not self._link_is_complete(raw):
            return fallback_host, fallback_port
        try:
            parsed = urlparse(raw)
            return (parsed.hostname or fallback_host).strip(), parsed.port or fallback_port
        except Exception:
            return fallback_host, fallback_port

    def _merge_api_query_params(self, params: list[tuple[str, str]], api_link: Optional[str], scheme: str) -> list[tuple[str, str]]:
        raw = (api_link or "").strip()
        if not raw.lower().startswith(f"{scheme.lower()}://"):
            return params
        existing = {str(k) for k, _ in params}
        try:
            for key, value in parse_qsl(urlparse(raw).query, keep_blank_values=True):
                if key and key not in existing:
                    params.append((key, value))
                    existing.add(key)
        except Exception:
            pass
        return params

    def _normal_uuid(self, value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            return str(uuidlib.UUID(raw))
        except Exception:
            return ""

    def _client_identity(self, protocol: str, client: Optional[Dict]) -> str:
        client = client or {}
        if protocol in ("trojan", "shadowsocks"):
            return str(client.get("password") or "")
        if protocol == "hysteria":
            return str(client.get("auth") or "")
        return self._normal_uuid(client.get("id") or client.get("uuid"))

    def _find_inbound_client(self, inbound: Optional[Dict], protocol: str, email: str = "", client_uuid: str = "") -> Optional[Dict]:
        if not inbound:
            return None
        settings = self._json_obj(inbound.get("settings"), {})
        target_uuid = self._normal_uuid(client_uuid)
        for client in settings.get("clients", []) or []:
            ident = self._client_identity(protocol, client)
            if (email and client.get("email") == email) or (target_uuid and ident == target_uuid):
                return client
        return None

    async def _client_missing_from_inbound(self, inbound_id: int, email: str = "", client_identity: str = "") -> bool:
        inbound = await self.get_inbound(int(inbound_id))
        if not inbound:
            return False
        protocol = inbound.get("protocol", "vless")
        identity = (client_identity or "").strip()
        normal_identity = self._normal_uuid(identity)
        settings = self._json_obj(inbound.get("settings"), {})
        for client in settings.get("clients", []) or []:
            if email and client.get("email") == email:
                return False
            current_identity = self._client_identity(protocol, client)
            if identity and (current_identity == identity or (normal_identity and current_identity == normal_identity)):
                return False
        return True

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
            cid = self._normal_uuid(existing.get("id") or existing.get("uuid")) or self._normal_uuid(client_uuid)
            if not cid:
                raise ValueError("invalid_uuid_for_client_payload")
            base["id"] = cid
            base["flow"] = existing.get("flow", "") or ""
            if existing.get("security"):
                base["security"] = existing.get("security")
        return base

    def _link_has_valid_identity(self, link: str) -> bool:
        raw = str(link or "").strip()
        lower = raw.lower()
        if lower.startswith("vless://"):
            userinfo = raw[8:].split("@", 1)[0].strip()
            return bool(self._normal_uuid(userinfo))
        if lower.startswith("vmess://"):
            payload = raw[8:].split("#", 1)[0].split("?", 1)[0]
            payload += "=" * (-len(payload) % 4)
            try:
                decoded = base64.urlsafe_b64decode(payload.encode()).decode("utf-8", "ignore")
            except Exception:
                try:
                    decoded = base64.b64decode(payload.encode()).decode("utf-8", "ignore")
                except Exception:
                    return False
            try:
                obj = json.loads(decoded)
            except Exception:
                return False
            return bool(self._normal_uuid(obj.get("id")))
        return bool(raw)

    async def add_client(self, inbound_id: int, client_uuid: str, email: str,
                          traffic_gb: float, expire_days: int, starts_on_first_use: bool = False) -> bool:
        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            self.last_error = "inbound_not_found"
            return False
        protocol = inbound.get("protocol", "vless")
        traffic_bytes = int(traffic_gb * 1024 ** 3)
        expire_ms = expiry_ms_from_days(expire_days)

        try:
            client = self._client_payload(protocol, client_uuid, email, traffic_bytes, expire_ms, True)
        except ValueError as e:
            self.last_error = str(e)
            return False

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
        if not inbound:
            self.last_error = "inbound_not_found"
            return False
        protocol = inbound.get("protocol", "vless")
        traffic_bytes = int(traffic_gb * 1024 ** 3)
        payload_email = (new_email or email or "").strip()

        existing = self._find_inbound_client(inbound, protocol, email, client_uuid)
        api_existing = None
        if not existing:
            api_existing = await self.get_client(email)
        if not existing and payload_email != email:
            api_existing = await self.get_client(payload_email)
        if api_existing:
            safe_identity = self._client_identity(protocol, api_existing)
            if safe_identity:
                existing = api_existing
        try:
            client = self._client_payload(protocol, client_uuid, payload_email, traffic_bytes, expire_ms, enable, existing)
        except ValueError as e:
            self.last_error = str(e)
            return False

        path_identity = self._client_identity(protocol, existing) or self._client_identity(protocol, client) or client_uuid
        payload = {"id": inbound_id, "settings": json.dumps({"clients": [client]})}
        r = await self._req("POST", f"/panel/api/inbounds/updateClient/{quote(path_identity, safe='')}", json=payload)
        if r and r.get("success"):
            return True

        r = await self._req("POST", f"/panel/api/clients/update/{quote(email, safe='')}", json=client)
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
        inbound_id = int(inbound_id)
        email = (email or "").strip()
        client_identity = (client_uuid or "").strip()

        if email:
            found = await self.find_client(email=email, client_uuid=client_uuid)
            if found:
                try:
                    inbound_id = int(found.get("inbound_id") or inbound_id)
                except Exception:
                    pass
                inbound = found.get("inbound")
                protocol = (inbound or {}).get("protocol", "vless")
                client_identity = self._client_identity(protocol, found.get("client")) or client_identity
        else:
            inbound = await self.get_inbound(inbound_id)
            if inbound:
                protocol = inbound.get("protocol", "vless")
                settings = self._json_obj(inbound.get("settings"), {})
                for c in settings.get("clients", []) or []:
                    ident = self._client_identity(protocol, c) or c.get("email", "")
                    if ident == client_uuid:
                        email = c.get("email", "")
                        client_identity = ident
                        break

        errors = []

        if client_identity:
            r = await self._req("POST", f"/panel/api/inbounds/{inbound_id}/delClient/{quote(client_identity, safe='')}")
            if r and r.get("success"):
                return True
            if await self._client_missing_from_inbound(inbound_id, email, client_identity):
                self.last_error = ""
                return True
            errors.append(f"delClient: {self.last_error or 'failed'}")

        if email:
            r = await self._req("POST", f"/panel/api/inbounds/{inbound_id}/delClientByEmail/{quote(email, safe='')}")
            if r and r.get("success"):
                return True
            if await self._client_missing_from_inbound(inbound_id, email, client_identity):
                self.last_error = ""
                return True
            errors.append(f"delClientByEmail: {self.last_error or 'failed'}")

            r = await self._req("POST", "/panel/api/clients/bulkDel", json={"emails": [email], "keepTraffic": False})
            if r and r.get("success"):
                return True
            if await self._client_missing_from_inbound(inbound_id, email, client_identity):
                self.last_error = ""
                return True
            errors.append(f"clients/bulkDel: {self.last_error or 'failed'}")

        if email:
            r = await self._req("POST", f"/panel/api/clients/del/{quote(email, safe='')}")
            if r and r.get("success"):
                return True
            if await self._client_missing_from_inbound(inbound_id, email, client_identity):
                self.last_error = ""
                return True
            errors.append(f"clients/del: {self.last_error or 'failed'}")

        if errors:
            self.last_error = " | ".join(errors)[-500:]
        return False

    async def get_client_link(self, inbound_id: int, email: str) -> Optional[str]:
        try:
            api_link = None
            r = await self._req("GET", f"/panel/api/clients/links/{quote(email, safe='')}")
            if r and r.get("success"):
                api_link = self._first_complete_api_link(r.get("obj"))

            inbound = await self.get_inbound(inbound_id)
            if not inbound:
                return api_link
            protocol = inbound.get("protocol", "vless")
            settings = self._json_obj(inbound.get("settings"), {})
            stream = self._json_obj(inbound.get("streamSettings"), {})
            clients = settings.get("clients", [])
            client = next((c for c in clients if c.get("email") == email), None)
            if not client:
                client = await self.get_client(email)
            if not client:
                return api_link

            parsed = urlparse(self.base_url)
            host = parsed.hostname or "example.com"
            port = inbound.get("port", 443)
            network = stream.get("network", "tcp")
            security = stream.get("security", "none")

            if protocol == "vless":
                cid = self._normal_uuid(client.get("id") or client.get("uuid"))
                if not cid:
                    self.last_error = "invalid_vless_uuid_for_link"
                    return api_link
                host, port = self._api_endpoint(api_link, "vless", host, port)
                # برای سازگاری با کلاینت‌ها، encryption را صراحتاً ارسال می‌کنیم.
                params = [("type", network), ("encryption", "none"), ("security", security)]
                if security == "reality":
                    rs = stream.get("realitySettings", {})
                    names = rs.get("serverNames", [""])
                    pk = rs.get("settings", {}).get("publicKey", "")
                    sid_val = (rs.get("shortIds", [""]) or [""])[0]
                    fp = rs.get("settings", {}).get("fingerprint", "chrome")
                    spx = rs.get("settings", {}).get("spiderX", "")
                    if names: params.append(("sni", names[0]))
                    if pk: params.append(("pbk", pk))
                    if sid_val: params.append(("sid", sid_val))
                    if spx: params.append(("spx", spx))
                    params.append(("fp", fp))
                elif security == "tls":
                    tls = stream.get("tlsSettings", {})
                    sni = tls.get("serverName", host)
                    if sni: params.append(("sni", sni))
                    alpn = tls.get("alpn")
                    if isinstance(alpn, list) and alpn:
                        params.append(("alpn", ",".join(str(x) for x in alpn if x)))
                    elif isinstance(alpn, str) and alpn:
                        params.append(("alpn", alpn))
                    fp = tls.get("settings", {}).get("fingerprint", "") if isinstance(tls.get("settings"), dict) else ""
                    fp = fp or tls.get("fingerprint", "")
                    if fp:
                        params.append(("fp", fp))
                if network == "ws":
                    ws = stream.get("wsSettings", {})
                    params.append(("path", ws.get("path", "/")))
                    ws_host = ws.get("host", "")
                    if ws_host:
                        params.append(("host", ws_host))
                elif network == "tcp":
                    # در TCP اگر header از نوع http باشد، path/host را به لینک اضافه می‌کنیم.
                    tcp = stream.get("tcpSettings", {})
                    header = tcp.get("header", {}) if isinstance(tcp, dict) else {}
                    h_type = header.get("type", "none")
                    params.append(("headerType", h_type))
                    if h_type == "http":
                        req = header.get("request", {}) if isinstance(header, dict) else {}
                        path = req.get("path", "/")
                        if isinstance(path, list):
                            path = path[0] if path else "/"
                        host_list = req.get("headers", {}).get("Host", [])
                        host_header = host_list[0] if isinstance(host_list, list) and host_list else ""
                        params.append(("path", path or "/"))
                        if host_header:
                            params.append(("host", host_header))
                elif network == "grpc":
                    grpc = stream.get("grpcSettings", {})
                    params.append(("serviceName", grpc.get("serviceName", "")))
                    params.append(("mode", "gun"))
                flow = client.get("flow", "")
                if flow: params.append(("flow", flow))
                params = self._merge_api_query_params(params, api_link, "vless")
                link = f"vless://{cid}@{host}:{port}?{urlencode(params)}#{quote(email, safe='')}"
                return link if self._link_is_complete(link) else api_link

            elif protocol == "vmess":
                cid = self._normal_uuid(client.get("id") or client.get("uuid"))
                if not cid:
                    self.last_error = "invalid_vmess_uuid_for_link"
                    return api_link
                cfg = {"v": "2", "ps": email, "add": host, "port": str(port), "id": cid,
                       "aid": str(client.get("alterId", 0)), "scy": "auto", "net": network,
                       "type": "none", "host": "", "path": "", "tls": security if security != "none" else ""}
                if network == "ws":
                    ws = stream.get("wsSettings", {})
                    cfg["path"] = ws.get("path", "/")
                encoded = base64.b64encode(json.dumps(cfg, ensure_ascii=False, separators=(",", ":")).encode()).decode()
                link = f"vmess://{encoded}"
                return link if self._link_is_complete(link) else api_link

            elif protocol == "trojan":
                pw = client.get("password", "")
                params = [("type", network), ("security", security)]
                if security in ("tls", "reality"):
                    tls = stream.get("tlsSettings", stream.get("realitySettings", {}))
                    sni = tls.get("serverName", host)
                    if sni: params.append(("sni", sni))
                link = f"trojan://{pw}@{host}:{port}?{urlencode(params)}#{quote(email, safe='')}"
                return link if self._link_is_complete(link) else api_link

            elif protocol == "shadowsocks":
                method = settings.get("method", "chacha20-poly1305")
                password = settings.get("password", "")
                userinfo = base64.urlsafe_b64encode(f"{method}:{password}".encode()).decode().rstrip("=")
                link = f"ss://{userinfo}@{host}:{port}#{quote(email, safe='')}"
                return link if self._link_is_complete(link) else api_link

            return api_link

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
