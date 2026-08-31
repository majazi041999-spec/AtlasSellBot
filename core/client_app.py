"""Public API for the Atlas Android client (`/client/v1/*`).

SECURITY MODEL — read before adding anything here.

Whatever this module returns is effectively public. The Android APK is
distributed to customers, so its API base URL, and any key baked beside it, can
be extracted with `apktool` in minutes. There is no such thing as a secret in a
client app.

Three rules follow, and they are not negotiable:

1. **Never mount under ``/{WEB_SECRET_PATH}/``.** The admin panel's protection
   is that unguessable prefix. If the client ever called a URL containing it,
   decompiling the APK would hand an attacker the admin panel's address. These
   routes live under a plain ``/client`` prefix for exactly that reason.

2. **Read-only, and no user data — ever.** No tokens, no subscriptions, no
   balances, no counts, not even aggregate ones. Everything served here is
   content the owner chose to publish: a promo banner, contact handles, and the
   latest app version. An attacker who scrapes every byte of it learns nothing
   they could not learn by installing the app.

3. **Treat ``clientapp_api_key`` as a speed bump, never as authorisation.** It
   filters casual scrapers and nothing more, so it must never gate anything
   whose exposure would matter.

No download URL is published. The client only learns that a newer version
exists and opens the seller's Telegram channel to fetch it, which keeps
REQUEST_INSTALL_PACKAGES out of the APK — the single strongest Play Protect
heuristic a sideloaded VPN can trip.
"""
from __future__ import annotations

import hashlib
import ipaddress
import time
from typing import Dict, Tuple

from core.database import get_setting, set_setting

# ── Settings keys ─────────────────────────────────────────────────────────────
# Deliberately NOT part of _settings_snapshot(): the React Settings page posts
# the whole snapshot back, so a key that lives there but has no form field gets
# silently blanked on every save. These are edited through their own endpoint,
# the same way the auto-node knobs are.
DEFAULTS: Dict[str, str] = {
    # Promo banner shown inside the app
    "clientapp_promo_enabled": "0",
    "clientapp_promo_id": "",          # change to re-show a banner a user dismissed
    "clientapp_promo_title": "",
    "clientapp_promo_text": "",
    "clientapp_promo_button": "",
    "clientapp_promo_url": "",
    "clientapp_promo_image_url": "",
    # In-app update manifest
    "clientapp_version_code": "0",
    "clientapp_version_name": "",
    "clientapp_version_notes": "",
    "clientapp_version_mandatory": "0",
    # Optional anti-scraper token (NOT authorisation — see module docstring)
    "clientapp_api_key": "",
}

# Only these may ever be written through the admin endpoint. An explicit
# allowlist means a typo or a crafted request cannot reach an unrelated setting.
EDITABLE = tuple(DEFAULTS.keys())


async def _get(key: str) -> str:
    return str(await get_setting(key, DEFAULTS.get(key, "")) or "").strip()


def _flag(value: str) -> bool:
    return str(value).strip() in ("1", "true", "True", "on", "yes")


# ── Rate limiting ─────────────────────────────────────────────────────────────
# A tiny fixed-window counter. These endpoints are unauthenticated and every
# installed app polls them, so an open endpoint is a free amplifier for anyone
# who wants to burn the VPS's bandwidth. Kept in-process because the app is a
# single process; if it is ever scaled out, move this to the database.
_RATE: Dict[str, Tuple[int, float]] = {}
_RATE_LIMIT = 60          # requests ...
_RATE_WINDOW = 60.0       # ... per this many seconds, per IP
_RATE_MAX_TRACKED = 20000  # hard cap so a spoofed-IP flood cannot exhaust memory


def rate_limited(ip: str) -> bool:
    """True when this IP has exceeded its budget for the current window."""
    now = time.time()
    count, started = _RATE.get(ip, (0, now))
    if now - started >= _RATE_WINDOW:
        count, started = 0, now
    count += 1
    if len(_RATE) > _RATE_MAX_TRACKED:
        # Drop the whole table rather than walking it: this only happens under
        # attack, and a cleared window is far cheaper than an O(n) sweep.
        _RATE.clear()
    _RATE[ip] = (count, started)
    return count > _RATE_LIMIT


# Networks whose forwarded-for headers we believe. Anything arriving from
# outside these is treated as a direct hit and its headers are ignored.
#
# Loopback/private cover the normal deployment (nginx or Cloudflare Tunnel on
# the same box); the public ranges are Cloudflare's own published edges, for
# installs where the app is exposed straight to Cloudflare.
_TRUSTED_PROXIES = tuple(ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7",
    # Cloudflare IPv4 — https://www.cloudflare.com/ips/
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
    # Cloudflare IPv6
    "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32",
    "2405:8100::/32", "2a06:98c0::/29", "2c0f:f248::/32",
))


def _from_trusted_proxy(peer: str) -> bool:
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(addr in net for net in _TRUSTED_PROXIES)


def client_ip(request) -> str:
    """Real client IP — but only believing forwarded headers we can vouch for.

    THIS FUNCTION IS A SECURITY BOUNDARY. Everything keyed on it (the client
    rate limiter, the representative API's per-key limits, and the admin login's
    lockout) is only as trustworthy as the value it returns.

    The previous version trusted ``CF-Connecting-IP`` unconditionally, on the
    reasoning that Cloudflare sets it and a client cannot spoof it *past
    Cloudflare*. That is true — and irrelevant, because the origin is also
    reachable directly on its public IP:PORT (the startup banner prints exactly
    that URL). An attacker who skips Cloudflare can therefore send any
    ``CF-Connecting-IP`` they like: a fresh random one per request lands every
    guess in a brand-new bucket so the login lockout never fires, and the
    victim's own IP locks the owner out of their panel on demand.

    So the header is honoured only when the CONNECTION came from a network we
    trust to set it. A direct hit falls back to the socket peer, which cannot be
    forged over TCP.
    """
    peer = (getattr(request.client, "host", "") or "").strip()
    if not _from_trusted_proxy(peer):
        return (peer or "unknown")[:64]

    headers = request.headers
    cf = (headers.get("cf-connecting-ip") or "").strip()
    if cf:
        return cf[:64]
    xff = (headers.get("x-forwarded-for") or "").strip()
    if xff:
        return xff.split(",")[0].strip()[:64]
    return (peer or "unknown")[:64]


async def api_key_ok(request) -> bool:
    """Soft check. Passes when no key is configured — the key is optional."""
    expected = await _get("clientapp_api_key")
    if not expected:
        return True
    return (request.headers.get("x-atlas-key") or "").strip() == expected


# ── Payload builders ──────────────────────────────────────────────────────────
async def version_payload() -> Dict:
    """The in-app update manifest.

    ``code`` of 0 means "no update published"; the client treats that as
    up-to-date rather than as an error, so the owner can leave it unset.
    """
    try:
        code = int(await _get("clientapp_version_code") or 0)
    except ValueError:
        code = 0
    return {
        "versionCode": code,
        "versionName": await _get("clientapp_version_name"),
        "notes": await _get("clientapp_version_notes"),
        "mandatory": _flag(await _get("clientapp_version_mandatory")),
    }


async def config_payload() -> Dict:
    """Everything the app fetches on launch, in one round trip."""
    promo_enabled = _flag(await _get("clientapp_promo_enabled"))
    promo = None
    if promo_enabled:
        title = await _get("clientapp_promo_title")
        text = await _get("clientapp_promo_text")
        # A banner with neither a title nor body is not worth a UI slot.
        if title or text:
            # The client remembers dismissed banners by id, so the fallback must
            # be stable across restarts. Python's hash() is salted per process
            # and would resurrect a dismissed banner on every service restart.
            auto_id = hashlib.sha256(f"{title}\n{text}".encode()).hexdigest()[:12]
            promo = {
                "id": (await _get("clientapp_promo_id")) or auto_id,
                "title": title,
                "text": text,
                "button": await _get("clientapp_promo_button"),
                "url": await _get("clientapp_promo_url"),
                "imageUrl": await _get("clientapp_promo_image_url"),
            }

    # Contact handles are served rather than only compiled into the app so the
    # owner can move a bot or channel without shipping a new APK.
    return {
        "brand": await get_setting("ui.brand_name", "Atlas Account"),
        "telegram": {
            "bot": str(await get_setting("clientapp_bot_username", "") or "").strip(),
            "channel": str(await get_setting("channel_username", "") or "").strip().lstrip("@"),
        },
        "promo": promo,
        "version": await version_payload(),
    }


async def admin_payload() -> Dict:
    """Current values for the admin editor, plus why the banner is/isn't live.

    The reason is computed here rather than re-derived in the panel so the two
    can never disagree: this is the same code path that decides what the app
    actually receives.
    """
    data = {key: await _get(key) for key in EDITABLE}
    enabled = _flag(data.get("clientapp_promo_enabled", "0"))
    has_body = bool(data.get("clientapp_promo_title") or data.get("clientapp_promo_text"))
    if not enabled:
        data["_promo_status"] = "disabled"
    elif not has_body:
        data["_promo_status"] = "empty"
    else:
        data["_promo_status"] = "live"
    return data


async def save_admin(data: Dict) -> Dict:
    """Persist only allowlisted keys, normalising the ones with a fixed shape."""
    for key in EDITABLE:
        if key not in data:
            continue
        raw = str(data.get(key) or "").strip()
        if key in ("clientapp_promo_enabled", "clientapp_version_mandatory"):
            raw = "1" if _flag(raw) else "0"
        elif key == "clientapp_version_code":
            try:
                raw = str(max(0, int(raw or 0)))
            except ValueError:
                continue
        elif key in ("clientapp_promo_url", "clientapp_promo_image_url"):
            # Refuse anything that is not plain HTTPS. These become a tap target
            # and a download source inside the app, so a javascript:/http:/
            # intent: URL here would be an injection vector against every user.
            if raw and not raw.lower().startswith("https://"):
                continue
        await set_setting(key, raw)
    return await admin_payload()
