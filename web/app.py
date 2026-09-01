"""Atlas Account — Web Admin Panel (FastAPI)

Serves the React admin panel (single page app, `web/admin/dist`), its JSON API,
the customer-facing subscription links, the Telegram mini-app and the
representative API. There is no server-rendered panel any more — see the
"REACT ADMIN PANEL" section below before adding an HTML route.
"""

import logging
import base64
import os
import re
import glob
import shlex
import hashlib
import secrets
import time
import subprocess
import uuid
import sqlite3
import json
import shutil
import tempfile
import zipfile
from io import BytesIO
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BufferedInputFile
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from jose import JWTError, jwt

from core.config import (
    ADMIN_IDS,
    CARD_BANK,
    CARD_HOLDER,
    CARD_NUMBER,
    JWT_ALGORITHM,
    JWT_EXPIRE_HOURS,
    JWT_SECRET,
    REFERRAL_BONUS_GB,
    BOT_TOKEN,
    DB_PATH,
    WEB_ADMIN_PASSWORD,
    WEB_ADMIN_USERNAME,
    WEB_PORT,
    WEB_SECRET_PATH,
)
from core.database import (
    add_package,
    add_server,
    count_users,
    delete_package,
    delete_server,
    add_subscription_node_config,
    delete_subscription_node_config,
    get_discount_codes,
    get_discount_code,
    add_discount_code,
    update_discount_code,
    delete_discount_code,
    get_campaign_overview,
    get_revenue_timeseries,
    reset_campaign_flag,
    CUSTOM_SEGMENTS,
    get_segment_counts,
    get_custom_campaigns,
    get_custom_campaign,
    save_custom_campaign,
    delete_custom_campaign,
    get_user_subscription_profiles,
    get_user_balance,
    get_referral_tiers,
    get_referral_tier,
    add_referral_tier,
    update_referral_tier,
    delete_referral_tier,
    get_all_configs,
    get_configs_by_base_email,
    delete_configs_by_base_email,
    get_all_orders,
    get_all_users,
    list_users,
    USER_SORTS,
    USER_FILTERS,
    USER_PERIODS,
    DEFAULT_USER_SORT,
    get_user_orders_full,
    get_rep_financials,
    get_user_configs_full,
    get_user_business_stats,
    get_recent_receipt_transactions,
    add_user_balance,
    get_pending_topup_requests,
    get_topup_request,
    update_topup_request,
    get_pending_legacy_claims,
    get_legacy_claim,
    update_legacy_claim,
    get_config_by_email,
    get_config_by_uuid,
    get_config,
    get_order,  # noqa: F401
    get_package,
    get_packages,
    get_pending_orders,
    get_available_servers,
    get_least_loaded_server,
    server_has_capacity,
    get_user_by_id,
    get_wholesale_users,
    get_user_by_telegram,
    has_previous_purchase,
    save_config,
    count_active_configs_by_server,
    get_server,
    get_servers,
    get_setting,
    get_stats,
    get_subscription_node_config,
    get_subscription_node_configs,
    get_subscription_profile,
    get_subscription_profiles_full,
    subscription_node_config_status,
    count_active_subscription_nodes_by_target,
    init_db,
    set_setting,
    update_subscription_node_config,
    update_config,
    update_order,  # noqa: F401
    update_package,
    update_server,
    update_user,
    reset_legacy_claims,
    claim_order_for_approval,
    release_order_processing,
    clear_config_alerts,
    get_review_messages,
    snapshot_daily_report,
    get_recent_daily_reports,
)
from core.panel_content import (
    BOT_TEXT_DEFAULTS,
    CUSTOM_SCRIPT_DEFAULT,
    CUSTOM_STYLE_DEFAULT,
    SETTINGS_DEFAULTS,
    UI_DEFAULTS,
)
from core.sorting import fa_sort_key
from core.xui_api import XUIClient, expiry_ms_from_days
from core.renewal import find_and_renew_config
from core.qr import build_qr_image
from bot.keyboards import config_links_kb
from core.update_notes import get_update_broadcast_text
from core.multi_subscription import render_subscription
from core.multi_subscription import (
    create_profile_for_order,
    multi_sub_enabled_for_single_purchase,
    subscription_error_message,
    renew_subscription_profile,
    subscription_url,
    delete_subscription_profile_remote,
    edit_subscription_profile,
    reset_subscription_usage,
    reset_subscription_time,
    rebuild_subscription_profile,
    sync_subscription_nodes_for_all,
    sync_subscription_nodes_streamed,
    reconcile_node_config_streamed,
)
import core.client_app as _client_app
import core.app_analytics as _app_analytics
from core.database import get_subscription_profile_by_token as _get_sub_profile_by_token
from core.database import get_subscription_nodes as _get_sub_nodes
from core.autonode import (
    DEFAULTS as AUTONODE_DEFAULTS,
    auto_node_overview,
    rebalance_all_auto_nodes,
    refresh_server_online_counts,
)
from core.database import (
    add_auto_subscription_node_config,
    count_auto_assignments_by_target,
    get_auto_node_candidates,
    parse_auto_pool,
)
from core.rep_report import (
    DEFAULT_PRESET as DEFAULT_REPORT_PRESET,
    build_rep_report,
    rep_report_filename,
    rep_report_xlsx,
)

logger = logging.getLogger(__name__)

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

_dir = os.path.dirname(os.path.abspath(__file__))
_repo_dir = os.path.dirname(_dir)
_db_path = DB_PATH if os.path.isabs(DB_PATH) else os.path.join(_repo_dir, DB_PATH)
_env_path = os.path.join(_repo_dir, ".env")
_backup_dir = os.path.join(_repo_dir, "backups")

S = WEB_SECRET_PATH  # short alias


@app.get("/")
@app.get("/panel")
@app.get("/panel/")
@app.get("/admin")
@app.get("/admin/")
async def easy_panel_entry():
    return RedirectResponse(f"/{S}/", status_code=302)


@app.get("/health")
async def health_check():
    # Deliberately does NOT include the panel path: /health is public, and
    # handing out the secret prefix to anyone who asks would undo the only thing
    # that prefix is for.
    return JSONResponse({"ok": True})


# Representative API (`/api/rep/v1/*`) — a rep's own bot connects here with an
# API key. Mounted on a plain prefix on purpose: the base URL is handed to third
# parties, so it must never contain WEB_SECRET_PATH. See web/rep_api.py.
from web.rep_api import router as _rep_api_router  # noqa: E402  (after `app` exists)

app.include_router(_rep_api_router)


_SUB_CLIENT_UAS = (
    "v2ray", "v2rayng", "nekobox", "nekoray", "sing-box", "singbox", "sagernet",
    "clash", "clashmeta", "mihomo", "stash", "streisand", "shadowrocket", "v2box",
    "hiddify", "foxray", "loon", "quantumult", "surge", "matsuri", "throne",
    "karing", "happ", "ktor-client", "go-http", "okhttp", "curl", "wget",
)


def _wants_html_sub(request: Request) -> bool:
    """True when a human browser opens the link (show a status page); False for
    VPN clients fetching the config list."""
    if request.query_params.get("config") in ("1", "true"):
        return False
    if request.query_params.get("html") in ("1", "true"):
        return True
    ua = (request.headers.get("user-agent") or "").lower()
    accept = (request.headers.get("accept") or "").lower()
    if any(tok in ua for tok in _SUB_CLIENT_UAS):
        return False
    return ("text/html" in accept) and ("mozilla" in ua)


def _fmt_bytes_web(b: int) -> str:
    b = int(b or 0)
    if b <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    f = float(b)
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{f:.2f} {units[i]}"


from core.images import process_logo_bytes


async def _admin_logo() -> str:
    return (await get_setting("ui.logo_data", "")).strip()


def _is_whitelabel_owner(u: dict) -> bool:
    """True when a subscription owner must be treated as a representative for
    white-label branding: flagged wholesale OR has configured their own brand /
    logo. Keying only on is_wholesale leaked our brand onto a rep whose flag was
    momentarily off (or set after their branding). Mirrors _owner_brand in
    core.multi_subscription — keep the two in sync."""
    return bool(int(u.get("is_wholesale") or 0)) \
        or bool((u.get("rep_brand_name") or "").strip()) \
        or bool((u.get("rep_logo") or "").strip())


async def _resolve_sub_logo(profile: dict) -> str:
    """Logo to show on a subscription's browser page: the rep's own logo for a
    rep's sub, otherwise the platform (admin) logo. Never leaks ours to a rep."""
    uid = profile.get("user_id")
    if uid:
        try:
            from core.database import get_user_by_id as _gubi
            u = await _gubi(int(uid))
        except Exception:
            u = None
        if u and _is_whitelabel_owner(u):
            return (u.get("rep_logo") or "").strip()  # empty → neutral, never ours
    return await _admin_logo()


async def _resolve_sub_brand(profile: dict) -> tuple[str, bool]:
    """(display_brand, is_representative) for a subscription's browser page/title.

    HARD RULE: for a representative's subscription this NEVER returns our platform
    brand — only their own brand (may be empty → caller shows a neutral title)."""
    uid = profile.get("user_id")
    if uid:
        try:
            from core.database import get_user_by_id as _gubi
            u = await _gubi(int(uid))
        except Exception:
            u = None
        if u and _is_whitelabel_owner(u):
            return (u.get("rep_brand_name") or "").strip(), True
    return await get_setting("ui.brand_name", "Atlas Account"), False


async def _render_sub_status_html(token: str, profile: dict) -> str:
    import html as _html

    disp_brand, is_rep = await _resolve_sub_brand(profile)
    brand = disp_brand or (str(profile.get("name") or "").strip() or "سرویس اشتراک")
    logo_uri = await _resolve_sub_logo(profile)
    logo_html = (
        f'<img src="{_html.escape(logo_uri, quote=True)}" alt="logo" '
        'style="width:54px;height:54px;border-radius:16px;object-fit:cover">'
        if logo_uri else "🌐"
    )
    sub_url = await subscription_url(token)
    nodes = await _get_sub_nodes(int(profile["id"]))
    active_nodes = [n for n in nodes if int(n.get("is_active") or 0) and (n.get("link") or "").strip()]

    now_ms = int(time.time() * 1000)
    expire_ms = int(profile.get("expire_timestamp") or 0)
    total = int(float(profile.get("traffic_gb") or 0) * 1024 ** 3)
    used = int(profile.get("used_bytes") or 0)
    remaining = max(0, total - used) if total > 0 else 0
    pct = min(100, int(used / total * 100)) if total > 0 else 0
    if expire_ms > 0:
        days_left = max(0, int((expire_ms - now_ms) / 86400000))
        expire_date = datetime.fromtimestamp(expire_ms / 1000).strftime("%Y-%m-%d")
    else:
        days_left = -1
        expire_date = "نامحدود"
    expired = (expire_ms > 0 and expire_ms <= now_ms) or (total > 0 and used >= total) or not int(profile.get("is_active") or 0)
    status_label = "منقضی / غیرفعال" if expired else "فعال"
    status_color = "#ff4c6a" if expired else "#00e5a0"
    days_text = "نامحدود" if days_left < 0 else (f"{days_left} روز" if days_left > 0 else "کمتر از یک روز / منقضی")

    node_rows = ""
    for i, n in enumerate(active_nodes, 1):
        remark = _html.escape(str(n.get("node_label") or n.get("server_name") or f"سرور {i}"))
        # The link lives in a data-attribute (no off-screen inputs) so it can be
        # copied without creating horizontal overflow / a phantom scroll area.
        link = _html.escape(n.get("link") or "", quote=True)
        node_rows += f"""
        <div class="node">
          <div class="node-name">📍 {remark}</div>
          <button class="copy-btn" type="button" data-link="{link}" onclick="copyText(this,this.dataset.link)">کپی لینک</button>
        </div>"""
    if not node_rows:
        node_rows = '<div class="muted">سروری برای نمایش موجود نیست.</div>'

    safe_brand = _html.escape(str(brand or "Atlas Account"))
    safe_sub = _html.escape(sub_url, quote=True)
    renew_banner = (
        '<div class="banner">⛔️ سرویس شما به پایان رسیده است. برای ادامه، از داخل ربات «تمدید» کنید.</div>'
        if expired else ""
    )
    return f"""<!doctype html>
<html lang="fa" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow">
<meta name="theme-color" content="#0b0f1a">
<title>{safe_brand} — وضعیت اشتراک</title>
<style>
*{{box-sizing:border-box}}
html,body{{max-width:100%;overflow-x:hidden}}
body{{margin:0;font-family:Vazirmatn,Tahoma,system-ui,-apple-system,sans-serif;
  background:radial-gradient(120% 80% at 80% -10%,rgba(124,111,255,.20),transparent 55%),
             radial-gradient(120% 80% at 0% 110%,rgba(0,229,160,.14),transparent 55%),#0b0f1a;
  color:#e8edf6;min-height:100vh;min-height:100dvh;display:flex;align-items:flex-start;justify-content:center;
  padding:max(16px,env(safe-area-inset-top)) 16px calc(28px + env(safe-area-inset-bottom))}}
.wrap{{width:100%;max-width:460px;margin:auto}}
.card{{width:100%;background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.09);
  border-radius:22px;padding:22px;box-shadow:0 30px 70px rgba(0,0,0,.5);backdrop-filter:blur(8px)}}
.head{{text-align:center;margin-bottom:16px}}
.logo{{width:54px;height:54px;border-radius:16px;display:inline-flex;align-items:center;justify-content:center;
  font-size:1.7rem;background:linear-gradient(135deg,#7c6fff,#00e5a0);box-shadow:0 10px 28px rgba(124,111,255,.4)}}
.brand{{font-size:1.2rem;font-weight:800;margin-top:10px}}
.sub-title{{color:#9aa6bd;font-size:.82rem;margin-top:2px}}
.status{{display:inline-block;margin-top:12px;padding:5px 14px;border-radius:999px;font-size:.8rem;font-weight:800;
  color:{status_color};border:1px solid {status_color};background:rgba(255,255,255,.04)}}
.banner{{margin:14px 0 2px;padding:12px 14px;border-radius:14px;font-size:.83rem;font-weight:700;line-height:1.7;
  background:rgba(255,76,106,.12);border:1px solid rgba(255,76,106,.4);color:#ffb3c0}}
.usage{{margin:18px 0 8px}}
.usage-top{{display:flex;justify-content:space-between;align-items:baseline;font-size:.84rem;margin-bottom:8px}}
.usage-top b{{font-size:1.05rem}}
.bar{{height:12px;border-radius:999px;background:rgba(255,255,255,.09);overflow:hidden}}
.bar>i{{display:block;height:100%;width:{pct}%;border-radius:999px;background:linear-gradient(90deg,#7c6fff,#00e5a0)}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:16px}}
.cell{{background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06);border-radius:14px;padding:12px}}
.cell .k{{color:#9aa6bd;font-size:.74rem}}
.cell .v{{font-weight:800;font-size:.96rem;margin-top:3px;word-break:break-word}}
.section-title{{margin:20px 0 9px;font-weight:800;font-size:.92rem;display:flex;align-items:center;gap:6px}}
.sub-box{{display:flex;gap:8px;align-items:center;background:#0a0e18;border:1px solid rgba(255,255,255,.09);
  border-radius:14px;padding:8px 8px 8px 10px;overflow:hidden}}
.sub-box input{{flex:1;background:transparent;border:none;color:#cfe;font-family:ui-monospace,Consolas,monospace;
  font-size:.72rem;direction:ltr;text-align:left;outline:none;min-width:0}}
.copy-btn{{background:#7c6fff;border:none;color:#fff;border-radius:11px;padding:9px 14px;font-size:.78rem;
  font-weight:800;cursor:pointer;white-space:nowrap;flex-shrink:0;transition:transform .1s,background .15s}}
.copy-btn:hover{{background:#6b5dff}}
.copy-btn:active{{transform:scale(.95)}}
.node{{display:flex;justify-content:space-between;align-items:center;gap:10px;background:#0a0e18;
  border:1px solid rgba(255,255,255,.06);border-radius:14px;padding:11px 12px;margin-bottom:8px}}
.node-name{{font-size:.88rem;font-weight:700;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.muted{{color:#9aa6bd;font-size:.85rem}}
.guide{{margin-top:18px;font-size:.78rem;color:#9aa6bd;line-height:2;background:rgba(255,255,255,.03);
  border:1px solid rgba(255,255,255,.05);border-radius:14px;padding:13px 15px}}
.foot{{text-align:center;color:#5d6680;font-size:.72rem;margin-top:18px}}
@media(max-width:480px){{.card{{padding:18px;border-radius:18px}}.grid{{gap:8px}}}}
</style></head>
<body><div class="wrap"><div class="card">
  <div class="head">
    <div class="logo">{logo_html}</div>
    <div class="brand">{safe_brand}</div>
    <div class="sub-title">صفحهٔ وضعیت اشتراک</div>
    <div><span class="status">{status_label}</span></div>
  </div>

  {renew_banner}

  <div class="usage">
    <div class="usage-top"><span class="muted">مصرف</span>
      <span><b>{_fmt_bytes_web(used)}</b> از {(_fmt_bytes_web(total) if total>0 else 'نامحدود')}</span></div>
    <div class="bar"><i></i></div>
  </div>

  <div class="grid">
    <div class="cell"><div class="k">باقی‌مانده</div><div class="v">{(_fmt_bytes_web(remaining) if total>0 else 'نامحدود')}</div></div>
    <div class="cell"><div class="k">زمان باقی‌مانده</div><div class="v">{days_text}</div></div>
    <div class="cell"><div class="k">تاریخ انقضا</div><div class="v">{expire_date}</div></div>
    <div class="cell"><div class="k">تعداد سرور</div><div class="v">{len(active_nodes)}</div></div>
  </div>

  <div class="section-title">🔗 لینک اشتراک</div>
  <div class="sub-box">
    <input id="suburl" value="{safe_sub}" readonly onclick="this.select()">
    <button class="copy-btn" type="button" onclick="copyText(this,document.getElementById('suburl').value)">کپی</button>
  </div>

  <div class="section-title">🖥 سرورها</div>
  {node_rows}

  <div class="guide">
    📚 راهنما: لینک اشتراک بالا را کپی کنید و در برنامه‌هایی مثل v2rayNG، NekoBox، Streisand یا V2Box از بخش «افزودن از کلیپ‌بورد» اضافه و آپدیت کنید. اگر لینک اشتراک باز نشد، لینک هر سرور را جداگانه کپی کنید.
  </div>
  <div class="foot">{safe_brand}</div>
</div></div>
<script>
function copyText(btn, text){{
  const done=()=>{{const o=btn.textContent;btn.textContent='✅ کپی شد';setTimeout(()=>btn.textContent=o,1500);}};
  if(navigator.clipboard&&window.isSecureContext){{navigator.clipboard.writeText(text).then(done).catch(()=>fallback(text,done));}}
  else fallback(text,done);
}}
function fallback(text,done){{const t=document.createElement('textarea');t.value=text;t.style.position='fixed';t.style.opacity='0';document.body.appendChild(t);t.select();try{{document.execCommand('copy');done();}}catch(e){{}}document.body.removeChild(t);}}
</script>
</body></html>"""


# ═════════════════ Android client public API (/client/v1) ═════════════════
# Deliberately NOT under /{S}/ — see core/client_app.py for why that separation
# is load-bearing. Nothing here reads or returns user data.

def _client_headers(seconds: int) -> dict:
    return {
        "Cache-Control": f"public, max-age={seconds}",
        # These are consumed by a native app, never a browser, so no site has
        # any business reading them cross-origin.
        "X-Content-Type-Options": "nosniff",
    }


async def _client_gate(request: Request):
    """Shared entry checks. Returns a JSONResponse to short-circuit, else None."""
    if _client_app.rate_limited(_client_app.client_ip(request)):
        return JSONResponse({"error": "rate_limited"}, status_code=429,
                            headers={"Retry-After": "60"})
    if not await _client_app.api_key_ok(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return None


@app.get("/client/v1/config")
async def client_app_config(request: Request):
    """Launch payload for the Android app: brand, contacts, promo, version."""
    blocked = await _client_gate(request)
    if blocked:
        return blocked
    return JSONResponse(await _client_app.config_payload(), headers=_client_headers(300))


@app.get("/client/v1/version")
async def client_app_version(request: Request):
    """Update manifest on its own, for clients that only poll for upgrades."""
    blocked = await _client_gate(request)
    if blocked:
        return blocked
    return JSONResponse(await _client_app.version_payload(), headers=_client_headers(900))


@app.post("/client/v1/ping")
async def client_app_ping(request: Request):
    """Heartbeat up, push messages down — one round trip.

    Deliberately a single endpoint rather than separate telemetry and inbox
    calls. Every extra request is a radio wake-up on a phone this app is trying
    not to drain, and the two have identical timing needs anyway.

    This is the only ``/client/v1`` route that writes. See
    ``core/app_analytics.py`` for what an anonymous caller can and cannot do to
    the database through it.
    """
    blocked = await _client_gate(request)
    if blocked:
        return blocked
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "bad_request"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "bad_request"}, status_code=400)

    result = await _app_analytics.record_ping(body)
    if result is None:
        return JSONResponse({"error": "bad_install_id"}, status_code=400)

    return JSONResponse(
        {
            "ok": True,
            # How long the client should wait before the next heartbeat. Served
            # rather than hard-coded so the owner can back it off across the
            # whole fleet without shipping an APK.
            "intervalMinutes": await _app_analytics_interval(),
            "messages": result["messages"],
        },
        # Never cached: the response is per-install and carries pending
        # messages, so an intermediate cache would deliver one install's inbox
        # to another and then stop delivering anything at all.
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


async def _app_analytics_interval() -> int:
    raw = await get_setting("clientapp_ping_minutes", "30")
    try:
        return max(15, min(1440, int(str(raw).strip() or 30)))
    except ValueError:
        return 30


@app.post("/client/v1/diag")
async def client_app_diag(request: Request):
    """Receives a batch of connection diagnostics from the app.

    What arrives here has already been stripped on the device: structured events
    with a fixed field list, and the one free-text field redacted of hosts, IPs,
    UUIDs and tokens before it ever left the phone. See the client's Diagnostics
    module for the guarantee, and core/app_analytics.record_diag for what this
    side refuses to store.

    The point of the whole path is to answer "which server, on which carrier, is
    failing" without ever learning where a user went.
    """
    blocked = await _client_gate(request)
    if blocked:
        return blocked
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "bad_request"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "bad_request"}, status_code=400)

    stored = await _app_analytics.record_diag(body)
    if stored is None:
        return JSONResponse({"error": "bad_install_id"}, status_code=400)
    return JSONResponse({"ok": True, "stored": stored}, headers={"Cache-Control": "no-store"})


@app.get(f"/{S}/api/client/diag/summary")
async def admin_client_diag_summary(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        days = int(request.query_params.get("days", "7"))
    except ValueError:
        days = 7
    return JSONResponse(await _app_analytics.diag_summary(days))


@app.get(f"/{S}/api/client/diag/export")
async def admin_client_diag_export(request: Request):
    """Downloads the raw events as a file, for offline analysis."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        days = int(request.query_params.get("days", "7"))
    except ValueError:
        days = 7

    rows = await _app_analytics.diag_export(days)
    fmt = (request.query_params.get("format") or "json").lower()

    if fmt == "csv":
        import csv
        import io as _io

        buffer = _io.StringIO()
        columns = [
            "at", "kind", "server", "transport", "preset", "net", "carrier",
            "model", "version_code", "sdk_int", "ok", "ms", "dur",
            "down_bps", "up_bps", "bytes", "stage", "why", "install_id",
        ]
        writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return PlainTextResponse(
            buffer.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="atlas-diag-{days}d.csv"',
                "Cache-Control": "no-store",
            },
        )

    return JSONResponse(
        {"days": days, "count": len(rows), "events": rows},
        headers={
            "Content-Disposition": f'attachment; filename="atlas-diag-{days}d.json"',
            "Cache-Control": "no-store",
        },
    )


@app.post(f"/{S}/api/client/diag/purge")
async def admin_client_diag_purge(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await _app_analytics.diag_purge()
    return JSONResponse({"success": True})


@app.get(f"/{S}/api/client/stats")
async def admin_client_stats(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse(await _app_analytics.stats())


@app.post(f"/{S}/api/client/reset")
async def admin_client_reset(request: Request):
    """Clears install analytics and all push messages. Not undoable."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    removed = await _app_analytics.reset_stats()
    return JSONResponse({"success": True, "removed": removed})


@app.get(f"/{S}/api/client/push")
async def admin_client_push_list(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({"messages": await _app_analytics.list_push()})


@app.post(f"/{S}/api/client/push")
async def admin_client_push_create(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = dict(await request.form())
    created = await _app_analytics.create_push(body)
    if created is None:
        return JSONResponse({"error": "title_required"}, status_code=400)
    return JSONResponse({"success": True, **created})


@app.post(f"/{S}/api/client/push/audience")
async def admin_client_push_audience(request: Request):
    """Reach preview for the compose form, before anything is stored."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    return JSONResponse({"count": await _app_analytics.audience(body or {})})


@app.post(f"/{S}/api/client/push/{{push_id:int}}/active")
async def admin_client_push_active(push_id: int, request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    await _app_analytics.set_push_active(push_id, bool(body.get("active")))
    return JSONResponse({"success": True})


@app.post(f"/{S}/api/client/push/{{push_id:int}}/delete")
async def admin_client_push_delete(push_id: int, request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await _app_analytics.delete_push(push_id)
    return JSONResponse({"success": True})


@app.get(f"/{S}/api/client/config")
async def admin_client_config(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse(await _client_app.admin_payload())


@app.post(f"/{S}/api/client/config")
async def admin_client_config_save(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = dict(await request.form())
    return JSONResponse({"success": True, "config": await _client_app.save_admin(body)})


@app.get("/sub/{token}")
async def public_subscription(token: str, request: Request):
    # Human opening the link in a browser → pretty status page.
    if _wants_html_sub(request):
        profile = await _get_sub_profile_by_token(token)
        if not profile:
            return HTMLResponse(
                "<!doctype html><html lang='fa' dir='rtl'><meta charset='utf-8'>"
                "<body style='font-family:Tahoma;background:#0b0f1a;color:#e8edf6;text-align:center;padding-top:80px'>"
                "<h2>لینک اشتراک یافت نشد</h2><p style='color:#9aa6bd'>این لینک معتبر نیست یا حذف شده است.</p></body></html>",
                status_code=404,
            )
        # keep usage/links fresh in the background without blocking the page
        try:
            _asyncio.create_task(render_subscription(token))
        except Exception:
            pass
        html = await _render_sub_status_html(token, profile)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    # VPN client → base64 config list (fast, read-only).
    rendered = await render_subscription(token)
    if not rendered:
        return StreamingResponse(iter([b""]), media_type="text/plain", status_code=404)
    body, info = rendered
    # Profile-Title fallback must be brand-safe for reps (never our brand).
    _prof = await _get_sub_profile_by_token(token) or {}
    disp_brand, _is_rep = await _resolve_sub_brand(_prof)
    title = (info.get("title") or "").strip() or disp_brand or "VPN"
    title_b64 = base64.b64encode(str(title or "VPN").encode("utf-8")).decode()
    headers = {
        "Subscription-Userinfo": (
            f"upload={info['upload']}; download={info['download']}; "
            f"total={info['total']}; expire={info['expire']}"
        ),
        "Profile-Title": f"base64:{title_b64}",
        "Cache-Control": "no-store",
    }
    return StreamingResponse(iter([body.encode()]), media_type="text/plain; charset=utf-8", headers=headers)


async def _clear_review_buttons(tx_type: str, tx_id: int, status_text: str = ""):
    if not BOT_TOKEN or len(BOT_TOKEN) <= 20:
        return
    rows = await get_review_messages(tx_type, tx_id)
    if not rows:
        return
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    try:
        for row in rows:
            chat_id = int(row["chat_id"])
            message_id = int(row["message_id"])
            try:
                if status_text:
                    await bot.edit_message_caption(
                        chat_id=chat_id,
                        message_id=message_id,
                        caption=status_text,
                        reply_markup=None,
                        parse_mode=None,
                    )
                else:
                    await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
            except Exception:
                try:
                    await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
                except Exception:
                    pass
    finally:
        await bot.session.close()


@app.on_event("startup")
async def _startup_init_db():
    # تضمین ایجاد جداول حتی اگر وب مستقل اجرا شود
    await init_db()
    # Must run AFTER init_db: it reads/writes the settings table.
    await _ensure_signing_secret()
    _warn_weak_config()



# ═══════════════════════════════ AUTH ═══════════════════════════════
# The signing key actually used. Normally this IS JWT_SECRET, but see
# _ensure_signing_secret(): a deployment still carrying the committed default
# would have forgeable admin sessions, which would make the whole login —
# password, captcha and all — decorative.
_SIGNING_SECRET = JWT_SECRET
_DEFAULT_JWT_SECRET = "please_change_this_secret_key_in_production"

# Binds a token to the credentials that issued it, at zero storage cost:
# changing the admin password or username invalidates every session already out
# there, including an attacker's. Truncated because it only needs to change, not
# to be secret — it rides inside a signed token.
_CRED_VERSION = hashlib.sha256(
    f"{WEB_ADMIN_USERNAME}:{WEB_ADMIN_PASSWORD}".encode("utf-8")
).hexdigest()[:16]


def _warn_weak_config() -> None:
    """Say out loud when the install is still running on shipped defaults.

    Deliberately a log line and not an exception: refusing to boot would take a
    live bot and its paying customers down during an update, and the owner would
    discover it from customers rather than from us. The login itself is hardened
    either way — this is about the two values that hardening cannot compensate
    for, because they are what an attacker would be guessing.
    """
    if WEB_ADMIN_PASSWORD in ("", "ChangeMe123!"):
        logger.critical(
            "WEB_ADMIN_PASSWORD is still the shipped default. Anyone who has seen "
            "this project knows it. Set it in .env and restart."
        )
    if S == "AtlasPanel2024":
        logger.critical(
            "WEB_SECRET_PATH is still the shipped default, so the panel URL is "
            "guessable. Set it in .env and restart."
        )


async def _ensure_signing_secret() -> None:
    """Never sign with the default secret that ships in the repo.

    Anyone who has read this codebase knows that string, and with it can mint an
    admin cookie without ever touching the login form. Rather than refuse to
    boot — which would take a live bot and its paying customers down on an
    update — generate a real key once, keep it in settings, and use that. The
    only visible effect is that existing sessions need one fresh login.
    """
    global _SIGNING_SECRET
    if JWT_SECRET and JWT_SECRET != _DEFAULT_JWT_SECRET and len(JWT_SECRET) >= 24:
        return
    stored = (await get_setting("jwt_signing_secret", "")).strip()
    if not stored:
        stored = secrets.token_urlsafe(48)
        await set_setting("jwt_signing_secret", stored)
        logger.critical(
            "JWT_SECRET is unset or still the repo default — generated a private "
            "signing key and stored it. Set JWT_SECRET in .env to control it yourself."
        )
    else:
        logger.critical("JWT_SECRET is still the repo default — using the generated key from settings.")
    _SIGNING_SECRET = stored


def _make_token(username: str) -> str:
    exp = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    return jwt.encode({"sub": username, "exp": exp, "v": _CRED_VERSION},
                      _SIGNING_SECRET, algorithm=JWT_ALGORITHM)


def _verify_token(token: str) -> Optional[str]:
    try:
        p = jwt.decode(token, _SIGNING_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    # Reject sessions minted under different credentials. Tokens issued before
    # this field existed have no "v" and are also rejected — a one-time
    # re-login, which is the correct outcome for an upgrade that changes how
    # sessions are trusted.
    if p.get("v") != _CRED_VERSION:
        return None
    return p.get("sub")


def _session_tokens(request: Request) -> list:
    """Every `_atlas_t` value the browser sent, not just the one that won.

    A browser can legitimately hold two cookies of the same name at different
    paths — the pre-upgrade `/` one and the current `/{S}/` one — and it sends
    BOTH. Starlette collapses them into a dict, so one silently shadows the
    other. Reading the raw header means a valid session is never hidden behind a
    stale one; the login response deletes the old cookie too, but that only helps
    once the admin has managed to log in.
    """
    raw = request.headers.get("cookie") or ""
    out = []
    for part in raw.split(";"):
        name, _, value = part.strip().partition("=")
        if name == "_atlas_t" and value:
            out.append(value.strip())
    parsed = request.cookies.get("_atlas_t", "")
    if parsed and parsed not in out:
        out.append(parsed)
    return out


def _auth(request: Request) -> Optional[str]:
    for token in _session_tokens(request):
        who = _verify_token(token)
        if who:
            return who
    return None


def _redir_login():
    """Bounce an unauthenticated browser to the panel, which shows the login
    form itself. Used by the few endpoints a browser navigates to directly
    (file downloads, the banner preview) rather than fetches as JSON."""
    return RedirectResponse(f"/{S}/", status_code=302)


async def _update_broadcast_text() -> str:
    return await get_update_broadcast_text()


async def _send_update_broadcast(build: str) -> int:
    if not BOT_TOKEN or len(BOT_TOKEN) < 20:
        raise RuntimeError("BOT_TOKEN is not configured")

    text = await _update_broadcast_text()
    total = await count_users()
    page = 0
    sent = 0

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    try:
        while page * 200 < total:
            users = await get_all_users(page * 200, 200)
            if not users:
                break
            for u in users:
                try:
                    await bot.send_message(u["telegram_id"], text, disable_web_page_preview=True)
                    sent += 1
                except Exception:
                    pass
            page += 1
    finally:
        await bot.session.close()

    await set_setting("last_update_broadcast", build)
    await set_setting("pending_update_build", "")
    await set_setting("pending_update_text", "")
    await set_setting("pending_update_text_build", "")
    await set_setting("update_broadcast_approved_build", "")
    await set_setting("skipped_update_build", "")
    return sent


def _safe_backup_name(prefix: str = "atlas-backup") -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"


def _sqlite_snapshot_bytes() -> bytes:
    if not os.path.exists(_db_path):
        raise FileNotFoundError("atlas.db not found")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    try:
        src = sqlite3.connect(_db_path)
        dst = sqlite3.connect(tmp.name)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        with open(tmp.name, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


# Installed-cert + reverse-proxy locations written by the in-panel SSL setup.
_SSL_BASE = "/etc/ssl/atlas"
_NGINX_CONF_GLOB = "/etc/nginx/conf.d/atlas-*.conf"
_SYSTEMD_UNITS = ["/etc/systemd/system/atlas-bot.service", "/etc/systemd/system/atlasbot.service"]


def _system_backup_files() -> list[tuple[str, str]]:
    """Readable SSL certs + nginx vhost(s) + systemd unit, as (abspath, arcname)."""
    out: list[tuple[str, str]] = []
    try:
        if os.path.isdir(_SSL_BASE):
            for root, _dirs, files in os.walk(_SSL_BASE):
                for fn in files:
                    ap = os.path.join(root, fn)
                    rel = os.path.relpath(ap, _SSL_BASE).replace(os.sep, "/")
                    if os.access(ap, os.R_OK):
                        out.append((ap, f"ssl/atlas/{rel}"))
        for ap in glob.glob(_NGINX_CONF_GLOB):
            if os.access(ap, os.R_OK):
                out.append((ap, f"nginx/{os.path.basename(ap)}"))
        for ap in _SYSTEMD_UNITS:
            if os.path.isfile(ap) and os.access(ap, os.R_OK):
                out.append((ap, f"systemd/{os.path.basename(ap)}"))
    except Exception as e:
        logger.warning("collecting system backup files failed: %s", e)
    return out


def _system_restore_target(arc: str) -> Optional[str]:
    """Map a backup arcname back to its absolute system path (restore)."""
    if arc.startswith("ssl/atlas/"):
        tail = arc[len("ssl/atlas/"):]
        if ".." in tail.split("/"):
            return None
        return os.path.join(_SSL_BASE, *tail.split("/"))
    if arc.startswith("nginx/") and arc.endswith(".conf"):
        return os.path.join("/etc/nginx/conf.d", os.path.basename(arc))
    if arc.startswith("systemd/") and arc.endswith(".service"):
        return os.path.join("/etc/systemd/system", os.path.basename(arc))
    return None


def _build_backup_zip() -> bytes:
    sys_files = _system_backup_files()
    contains = ["atlas.db"]
    if os.path.exists(_env_path):
        contains.append(".env")
    if any(a.startswith("ssl/") for _, a in sys_files):
        contains.append("ssl")
    if any(a.startswith("nginx/") for _, a in sys_files):
        contains.append("nginx")
    meta = {
        "app": "AtlasSellBot",
        "created_at": datetime.now().isoformat(),
        "contains": contains,
    }
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("metadata.json", json.dumps(meta, ensure_ascii=False, indent=2))
        z.writestr("atlas.db", _sqlite_snapshot_bytes())
        if os.path.exists(_env_path):
            z.write(_env_path, ".env")
        for ap, arc in sys_files:
            try:
                z.write(ap, arc)
            except Exception:
                pass
    buf.seek(0)
    return buf.getvalue()


def _save_pre_restore_backup() -> str:
    os.makedirs(_backup_dir, exist_ok=True)
    name = _safe_backup_name("before-restore")
    path = os.path.join(_backup_dir, name)
    with open(path, "wb") as f:
        f.write(_build_backup_zip())
    return name


def _validate_sqlite_db(path: str):
    con = sqlite3.connect(path)
    try:
        row = con.execute("PRAGMA integrity_check").fetchone()
        if not row or str(row[0]).lower() != "ok":
            raise ValueError("sqlite integrity_check failed")
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"settings", "users", "servers", "packages", "orders", "configs"}
        if not required.issubset(tables):
            raise ValueError("uploaded database is not an Atlas panel backup")
    finally:
        con.close()


def _extract_restore_payload(upload_path: str, workdir: str) -> tuple[str, str | None, list[tuple[str, str]]]:
    db_out = os.path.join(workdir, "restore-atlas.db")
    env_out = os.path.join(workdir, "restore.env")
    env_found: str | None = None
    sys_staged: list[tuple[str, str]] = []  # (staged_path, target_abspath)

    if zipfile.is_zipfile(upload_path):
        with zipfile.ZipFile(upload_path) as z:
            names = z.namelist()
            db_name = "atlas.db" if "atlas.db" in names else next((n for n in names if n.endswith("/atlas.db") or n.endswith(".db")), "")
            if not db_name:
                raise ValueError("backup zip does not contain atlas.db")
            with z.open(db_name) as src, open(db_out, "wb") as dst:
                shutil.copyfileobj(src, dst)
            env_name = ".env" if ".env" in names else next((n for n in names if n.endswith("/.env")), "")
            if env_name:
                with z.open(env_name) as src, open(env_out, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                env_found = env_out
            # Stage SSL/nginx/systemd files for an optional system restore.
            sys_dir = os.path.join(workdir, "sys")
            for arc in names:
                target = _system_restore_target(arc)
                if not target:
                    continue
                staged = os.path.join(sys_dir, arc.replace("/", os.sep))
                os.makedirs(os.path.dirname(staged), exist_ok=True)
                with z.open(arc) as src, open(staged, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                sys_staged.append((staged, target))
    else:
        shutil.copyfile(upload_path, db_out)

    _validate_sqlite_db(db_out)
    return db_out, env_found, sys_staged


def _restore_system_files(sys_staged: list[tuple[str, str]]) -> dict:
    """Best-effort write of SSL/nginx/systemd files back to the system."""
    restored = 0
    failed = 0
    for staged, target in sys_staged:
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(staged, target)
            # Private keys should stay readable only by root.
            if target.endswith((".key", ".pem")):
                try:
                    os.chmod(target, 0o600)
                except OSError:
                    pass
            restored += 1
        except Exception as e:
            failed += 1
            logger.warning("system file restore failed %s: %s", target, e)
    if restored:
        for cmd in (["nginx", "-t"], ["nginx", "-s", "reload"]):
            try:
                subprocess.run(cmd, capture_output=True, timeout=20)
            except Exception:
                pass
    return {"restored": restored, "failed": failed}


def _clean_domain(value: str) -> str:
    domain = (value or "").strip().lower()
    domain = re.sub(r"^https?://", "", domain)
    domain = domain.split("/", 1)[0].split(":", 1)[0].strip(".")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+", domain):
        return ""
    return domain


def _atlas_tls_proxy_script(domain: str, email: str, app_port: int, https_port: int) -> str:
    q_domain = shlex.quote(domain)
    q_email = shlex.quote(email)
    q_port = shlex.quote(str(app_port))
    q_https_port = shlex.quote(str(https_port))
    q_conf = shlex.quote(f"/etc/nginx/conf.d/atlas-{domain}.conf")
    q_cert_dir = shlex.quote(f"/etc/ssl/atlas/{domain}")
    q_fullchain = shlex.quote(f"/etc/ssl/atlas/{domain}/fullchain.cer")
    q_keyfile = shlex.quote(f"/etc/ssl/atlas/{domain}/{domain}.key")
    email_arg = f" --accountemail {q_email}" if email else ""
    return f"""set -e
if [ -z "${{HOME:-}}" ]; then
  export HOME="$(getent passwd "$(id -u)" 2>/dev/null | cut -d: -f6)"
  [ -z "$HOME" ] && export HOME="/root"
fi
DOMAIN={q_domain}
APP_PORT={q_port}
HTTPS_PORT={q_https_port}
WEBROOT=/var/www/atlas-acme
CONF={q_conf}
CERT_DIR={q_cert_dir}
FULLCHAIN={q_fullchain}
KEYFILE={q_keyfile}

if ! command -v nginx >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y
    DEBIAN_FRONTEND=noninteractive apt-get install -y nginx curl socat ca-certificates
  else
    echo "nginx is not installed and apt-get is unavailable" >&2
    exit 20
  fi
fi

mkdir -p "$WEBROOT/.well-known/acme-challenge" "$CERT_DIR"
cat > "$CONF" <<NGINX_HTTP
server {{
    listen 80;
    server_name $DOMAIN;

    location ^~ /.well-known/acme-challenge/ {{
        root $WEBROOT;
        default_type text/plain;
    }}

    location / {{
        proxy_pass http://127.0.0.1:$APP_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \\$host;
        proxy_set_header X-Real-IP \\$remote_addr;
        proxy_set_header X-Forwarded-For \\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\$scheme;
    }}
}}
NGINX_HTTP

nginx -t
systemctl enable --now nginx >/dev/null 2>&1 || service nginx start >/dev/null 2>&1 || true
nginx -s reload >/dev/null 2>&1 || systemctl reload nginx >/dev/null 2>&1 || service nginx reload >/dev/null 2>&1 || true

if [ ! -d "$HOME/.acme.sh" ]; then
  curl https://get.acme.sh | sh
fi
ACME="$HOME/.acme.sh/acme.sh"
if [ ! -x "$ACME" ] && [ -x "/root/.acme.sh/acme.sh" ]; then
  ACME="/root/.acme.sh/acme.sh"
fi
"$ACME" --set-default-ca --server letsencrypt
"$ACME" --issue -d "$DOMAIN" -w "$WEBROOT" --force{email_arg}
"$ACME" --install-cert -d "$DOMAIN" --fullchain-file "$FULLCHAIN" --key-file "$KEYFILE" --force

cat > "$CONF" <<NGINX_HTTPS
server {{
    listen 80;
    server_name $DOMAIN;

    location ^~ /.well-known/acme-challenge/ {{
        root $WEBROOT;
        default_type text/plain;
    }}

    location / {{
        return 301 https://\\$host{"" if https_port == 443 else f":{https_port}"}\\$request_uri;
    }}
}}

server {{
    listen $HTTPS_PORT ssl http2;
    server_name $DOMAIN;

    ssl_certificate $FULLCHAIN;
    ssl_certificate_key $KEYFILE;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:SSL:10m;
    client_max_body_size 32m;

    location / {{
        proxy_pass http://127.0.0.1:$APP_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \\$host;
        proxy_set_header X-Real-IP \\$remote_addr;
        proxy_set_header X-Forwarded-For \\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }}
}}
NGINX_HTTPS

nginx -t
nginx -s reload >/dev/null 2>&1 || systemctl reload nginx >/dev/null 2>&1 || service nginx reload >/dev/null 2>&1
"""


# ═══════════════════════════════ AUTH ROUTES ════════════════════════






# ═══════════════════ REACT ADMIN PANEL — JSON API + SPA ═══════════════════
# React is the ONLY panel. It is served at the secret root /<secret>/ and every
# page is a hash route inside it; all data flows through JSON endpoints under
# /<secret>/api/*. The server-rendered Jinja panel it replaced is gone — what
# survives from it are the POST action endpoints (/<secret>/servers/add,
# /packages/add, /settings, …), which the React pages still post to. Do not
# re-add an HTML page route here: the catch-all at the bottom of this file sends
# every unmatched /<secret>/… path into the SPA.
_admin_dist = os.path.join(_dir, "admin", "dist")
try:
    from fastapi.staticfiles import StaticFiles as _StaticFiles
    if os.path.isdir(os.path.join(_admin_dist, "assets")):
        # Bundle uses a relative base ("./assets/…") → served at /<secret>/assets.
        app.mount(f"/{S}/assets", _StaticFiles(directory=os.path.join(_admin_dist, "assets")), name="admin_assets")
except Exception as _e:  # pragma: no cover
    logger.warning("admin static mount skipped: %s", _e)


def _admin_index_html() -> str:
    idx = os.path.join(_admin_dist, "index.html")
    if not os.path.isfile(idx):
        return ""
    with open(idx, "r", encoding="utf-8") as f:
        html = f.read()
    # Inject the secret prefix at serve time so it's never committed in the bundle.
    return html.replace("<head>", f'<head><script>window.__PANEL_BASE__="/{S}";</script>', 1)


async def _serve_admin_spa():
    html = _admin_index_html()
    if not html:
        # There is no second panel to fall back to any more, so say plainly what
        # is wrong and how to fix it rather than serving a blank page.
        return HTMLResponse(
            "<!doctype html><html lang='fa' dir='rtl'><meta charset='utf-8'>"
            "<title>پنل ساخته نشده</title>"
            "<body style=\"font-family:Tahoma,sans-serif;background:#0d1017;color:#e8ecf8;"
            "display:flex;align-items:center;justify-content:center;height:100vh;margin:0\">"
            "<div style='text-align:center;max-width:420px;padding:24px'>"
            "<h2>پنل هنوز build نشده است</h2>"
            "<p style='color:#94a0bd;line-height:2'>روی سرور این دستور را بزنید:</p>"
            "<code style='display:block;background:#151b28;padding:12px;border-radius:10px;"
            "direction:ltr'>npm --prefix web/admin run build</code>"
            "<p style='color:#94a0bd;margin-top:18px'>یا آخرین نسخه را با "
            "<code style='direction:ltr'>bash update.sh</code> بگیرید.</p>"
            "</div></body></html>",
            status_code=503,
        )
    # Inject the custom favicon (admin logo) so the browser tab shows your brand.
    logo = await _admin_logo()
    if logo:
        html = html.replace("<head>", f'<head><link rel="icon" href="{logo}">', 1)
    return HTMLResponse(html)


@app.get(f"/{S}")
async def admin_root_noslash():
    return RedirectResponse(f"/{S}/", status_code=307)


@app.get(f"/{S}/")
async def admin_root_index():
    # React SPA is the main panel. Auth is handled client-side via /api/me, so the
    # shell HTML itself is public (same as the old v2 behaviour).
    return await _serve_admin_spa()






def _api_guard(request: Request):
    return _auth(request)


@app.post(f"/{S}/api/login")
async def api_login(request: Request):
    """Authenticate an admin.

    Everything protective lives in core/login_guard.py; this endpoint's job is
    to call it in the right ORDER. The order matters: the lockout and the
    challenge are checked BEFORE the password is compared, so a locked-out or
    unchallenged caller learns nothing about credentials, and every rejection
    past the lockout gate counts as a failure — including a wrong captcha,
    without which the small captcha answer space could be brute-forced for free.
    """
    from core import login_guard
    ip = _client_app.client_ip(request)
    force_captcha = await get_setting("login_captcha_always", "0") == "1"

    # Bounded read before anything else parses attacker-controlled JSON.
    if int(request.headers.get("content-length") or 0) > 4096:
        return JSONResponse({"error": "invalid_credentials"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    problem = login_guard.check(ip, body, force_captcha)
    if problem:
        if problem.startswith("locked:"):
            wait = int(problem.split(":", 1)[1])
            logger.warning("admin login blocked (locked) ip=%s wait=%ss", ip, wait)
            return JSONResponse({"error": "locked", "retry_after": wait}, status_code=429)
        if problem in ("challenge_missing", "challenge_expired"):
            # NOT a failed attempt. A challenge goes missing when it times out or
            # is evicted under load, which happens to real logins too — counting
            # it would let anyone who floods the challenge endpoint drive the
            # owner's own lockout without guessing a single password.
            logger.info("admin login needs a fresh challenge ip=%s (%s)", ip, problem)
            return JSONResponse({"error": problem,
                                 "captcha_required": login_guard.captcha_required(ip, force_captcha),
                                 "retry_after": 0}, status_code=400)
        state = login_guard.record_failure(ip)
        logger.warning("admin login rejected ip=%s reason=%s", ip, problem)
        await _maybe_alert_admins_login(ip, state, problem, str(body.get("username") or ""))
        return JSONResponse({"error": problem, **_login_hint(state)}, status_code=400)

    username = str(body.get("username") or "")[:256]
    password = str(body.get("password") or "")[:256]
    # Both compared in constant time, and deliberately WITHOUT short-circuiting,
    # so response time never reveals whether the username alone was right.
    ok_user = login_guard.constant_time_eq(username, WEB_ADMIN_USERNAME)
    ok_pass = login_guard.constant_time_eq(password, WEB_ADMIN_PASSWORD)
    if ok_user and ok_pass:
        login_guard.record_success(ip)
        logger.info("admin login ok user=%s ip=%s", username, ip)
        token = _make_token(username)
        r = JSONResponse({"ok": True, "username": username})
        _set_session_cookie(r, request, token)
        return r

    state = login_guard.record_failure(ip)
    logger.warning("admin login failed user=%r ip=%s failures=%s", username[:64], ip, state["failures"])
    await _maybe_alert_admins_login(ip, state, "نام کاربری یا رمز اشتباه", username)
    return JSONResponse({"error": "invalid_credentials", **_login_hint(state)}, status_code=401)


def _login_hint(state: dict) -> dict:
    """What the client needs to render next — never why the attempt failed."""
    return {"captcha_required": bool(state.get("captcha_next")),
            "retry_after": int(state.get("locked_for") or 0)}


def _set_session_cookie(response, request: Request, token: str) -> None:
    """Set the admin session cookie with the tightest flags that still work here.

    `secure` is decided from the actual request scheme rather than hard-coded:
    the panel is genuinely reachable over plain http://IP:PORT (that is what
    `atlas panel-link` prints), and an unconditional `secure=True` there would
    set a cookie the browser refuses to send back — an owner locked out of their
    own panel. Behind Cloudflare the original scheme arrives in
    X-Forwarded-Proto, so HTTPS users still get the flag.
    """
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").split(",")[0].strip()
    # Kill any cookie left at the OLD root path FIRST. Before the session was
    # scoped to /{S}/, this cookie lived at "/". A browser that still holds that
    # one sends both, and RFC 6265 orders the longer path first — so the stale
    # root cookie arrives LAST and wins the dict Starlette parses them into. The
    # symptom is brutal and silent: login returns 200, the panel still says
    # unauthorised, and the admin loops forever with no error to read.
    response.delete_cookie("_atlas_t", path="/")
    response.set_cookie(
        "_atlas_t", token, httponly=True, max_age=JWT_EXPIRE_HOURS * 3600,
        samesite="lax", secure=(proto == "https"), path=f"/{S}/",
    )


async def _maybe_alert_admins_login(ip: str, state: dict, reason: str, username: str = "") -> None:
    """Tell the owner in Telegram that someone failed to log into the panel.

    Throttled per IP by `login_guard.should_alert`: a sustained attack would
    otherwise fill the owner's chat, and an alert channel someone mutes is worth
    less than no alert at all. A LOCKOUT always sends regardless of the
    cooldown — that is the message that actually needs reading.
    """
    from core import login_guard
    if not BOT_TOKEN or len(BOT_TOKEN) < 20:
        return
    if await get_setting("login_alert_enabled", "1") != "1":
        return
    locked = bool(state.get("locked_for"))
    if not login_guard.should_alert(ip, locked):
        return
    try:
        from core.database import get_all_admin_telegram_ids
        targets = list(dict.fromkeys(list(ADMIN_IDS) + await get_all_admin_telegram_ids()))
        if not targets:
            return
        from core.jalali import jalali_datetime_display
        lines = [
            "🔐 *تلاش ناموفق ورود به پنل*",
            "",
            f"IP: `{ip}`",
            f"نام کاربری واردشده: `{(username or '—')[:40]}`",
            f"علت: {reason}",
            f"تعداد تلاش ناموفق: {state.get('failures', 0)}",
            f"زمان: {jalali_datetime_display(datetime.now()) or ''}",
        ]
        if locked:
            lines += ["", f"⛔ این IP برای *{state['locked_for']} ثانیه* قفل شد."]
        if state.get("captcha_next"):
            lines.append("🖼 از این پس برای این IP کد تصویری خواسته می‌شود.")
        lines += ["", "_اگر خودت نبودی، رمز پنل را عوض کن._"]
        bot = Bot(token=BOT_TOKEN)
        try:
            for aid in targets:
                try:
                    await bot.send_message(aid, "\n".join(lines), parse_mode="Markdown")
                except Exception:
                    pass
        finally:
            await bot.session.close()
    except Exception as e:
        logger.warning("login alert failed: %s", e)


@app.get(f"/{S}/api/login/challenge")
async def api_login_challenge(request: Request):
    """Hand out a fresh single-use challenge. Public by necessity — it is what
    you need BEFORE you can log in — so it must stay cheap and leak nothing."""
    from core import login_guard
    ip = _client_app.client_ip(request)
    if not login_guard.issue_allowed(ip):
        return JSONResponse({"error": "rate_limited"}, status_code=429,
                            headers={"Retry-After": "60"})
    force = await get_setting("login_captcha_always", "0") == "1"
    # issue() draws a PNG when a captcha is due. Pillow is synchronous, and this
    # process also runs the bot on the same loop, so it goes to a worker thread.
    loop = _asyncio.get_running_loop()
    return JSONResponse(await loop.run_in_executor(None, login_guard.issue, ip, force))


@app.post(f"/{S}/api/logout")
async def api_logout(request: Request):
    r = JSONResponse({"ok": True})
    # Path and samesite MUST match _set_session_cookie — a mismatch leaves the
    # original cookie in place and makes logout a no-op.
    r.delete_cookie("_atlas_t", path=f"/{S}/", samesite="lax")
    r.delete_cookie("_atlas_t")          # also clear any pre-upgrade "/" cookie
    return r


@app.get(f"/{S}/api/me")
async def api_me(request: Request):
    user = _api_guard(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({"ok": True, "username": user})


@app.get(f"/{S}/api/dashboard")
async def api_dashboard(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.database import build_daily_report
    stats = await get_stats()
    pending = await get_pending_orders()
    try:
        report = await build_daily_report()
    except Exception:
        report = {}
    def _slim(o):
        return {
            "id": o["id"], "pkg_name": o.get("pkg_name"), "price": int(o.get("price") or 0),
            "full_name": o.get("full_name"), "username": o.get("username"), "telegram_id": o.get("telegram_id"),
            "traffic_gb": o.get("traffic_gb"), "duration_days": o.get("duration_days"),
            "created_at": o.get("created_at"),
            "is_renew": bool(int(o.get("renew_config_id") or 0) or int(o.get("renew_sub_profile_id") or 0)),
        }
    # Live online users, per server. `online` is None when that panel did not
    # answer (or its last answer went stale) — NEVER folded into the total as a
    # zero, because "we don't know" and "nobody is connected" look identical on a
    # dashboard and are opposite facts. The unanswered panels are counted
    # separately so the number can be read honestly.
    try:
        from core.autonode import server_load_snapshot
        servers_online = [s for s in await server_load_snapshot() if s.get("is_active")]
    except Exception as e:
        logger.warning("dashboard online snapshot failed: %s", e)
        servers_online = []
    known = [s for s in servers_online if s.get("online") is not None]
    newest_check = max((int(s.get("checked_at") or 0) for s in servers_online), default=0)

    return JSONResponse({
        "stats": stats,
        "online": {
            "total": sum(int(s["online"]) for s in known),
            "servers_known": len(known),
            "servers_total": len(servers_online),
            "checked_at": newest_check,
            "servers": [{
                "id": s["id"], "name": s["name"],
                "online": s["online"],            # null = unknown, not zero
                "avg": s.get("online_avg"),
                "stale": bool(s.get("stale")),
            } for s in servers_online],
        },
        "pending": [_slim(o) for o in pending[:8]],
        "pending_total": len(pending),
        "report": {
            "sales_amount": int(report.get("sales_amount") or 0),
            "orders_approved": int(report.get("orders_approved") or 0),
            "renewals": int(report.get("renewals") or 0),
            "new_users": int(report.get("new_users") or 0),
            "wallet_topup_amount": int(report.get("wallet_topup_amount") or 0),
            "jalali_display": report.get("jalali_display") or "",
        },
    })


async def _analytics_stats() -> dict:
    """Everything both the analytics page AND the AI analyst read.

    One builder so the two can never disagree: the figure the owner sees on the
    chart is the same object handed to the model, which is the whole reason the
    model is not allowed to compute its own.
    """
    from core.database import (get_new_users_timeseries, count_users,
                               count_active_subscription_profiles, count_expiring_profiles)
    from core.forecast import forecast as run_forecast, compare_to_line

    # 120 days so the backtest inside the forecaster has folds to measure with.
    rev = await get_revenue_timeseries(120)
    users_ts = await get_new_users_timeseries(30)
    days = [datetime.strptime(r["date"], "%Y-%m-%d").date() for r in rev]
    revenue = [float(r["revenue"]) for r in rev]
    counts = [float(r["orders"]) for r in rev]

    fc7 = run_forecast(revenue, counts, days, 7)
    fc30 = run_forecast(revenue, counts, days, 30)
    versus = compare_to_line(revenue, counts, days, 7)

    last30 = rev[-30:]
    prev30 = rev[-60:-30] if len(rev) >= 60 else []
    revenue_30d = int(sum(r["revenue"] for r in last30))
    revenue_prev_30d = int(sum(r["revenue"] for r in prev30))

    async def _safe(coro, default=0):
        try:
            return await coro
        except Exception:
            return default

    from core.database import get_revenue_mix
    try:
        mix = await get_revenue_mix(90)
    except Exception as e:
        logger.warning('revenue mix failed: %s', e)
        mix = {}
    return {
        "today": datetime.now().strftime("%Y-%m-%d"),
        "revenue_series": last30,
        "revenue_series_long": rev,
        "users": users_ts,
        "forecast": fc7,
        "forecast30": fc30,
        "versus_linear": versus,
        "revenue_30d": revenue_30d,
        "revenue_prev_30d": revenue_prev_30d,
        "orders_30d": int(sum(r["orders"] for r in last30)),
        "new_users_30d": int(sum(u["new_users"] for u in users_ts)),
        "total_users": await _safe(count_users()),
        "active_subs": await _safe(count_active_subscription_profiles()),
        "expiring_7d": await _safe(count_expiring_profiles(7)),
        "expiring_30d": await _safe(count_expiring_profiles(30)),
        **mix,
    }


@app.get(f"/{S}/api/analytics")
async def api_analytics(request: Request):
    """Sales analytics + the revenue forecast.

    Response keys are kept backward-compatible with the previous shape so the
    existing chart code keeps working; the forecast underneath it is now
    core/forecast.py, which reports the accuracy it actually measured.
    """
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    st = await _analytics_stats()
    fc7, fc30 = st["forecast"], st["forecast30"]

    rev_vals = [float(r["revenue"]) for r in st["revenue_series"]]
    last7, prev7 = sum(rev_vals[-7:]), sum(rev_vals[-14:-7]) if len(rev_vals) >= 14 else 0
    momentum = round((last7 - prev7) / prev7 * 100, 1) if prev7 > 0 else (100.0 if last7 else 0.0)

    return JSONResponse({
        "revenue": st["revenue_series"],
        "users": st["users"],
        "forecast": fc7["points"],
        "forecast_meta": {
            "method": fc7.get("method"),
            "ok": fc7.get("ok"),
            "reason": fc7.get("reason"),
            "history_days": fc7.get("history_days"),
            # Measured on this owner's own data, so the panel can state the
            # accuracy instead of implying one.
            "accuracy": fc7.get("accuracy"),
            "band7": fc7.get("band"),
            "band30": fc30.get("band"),
            "drivers": fc7.get("drivers"),
            "versus_linear": st.get("versus_linear"),
        },
        "mix": {
            "reseller_share_pct": st.get("reseller_share_pct"),
            "renewal_share_pct": st.get("renewal_share_pct"),
            "top_packages": st.get("top_packages") or [],
        },
        "totals": {
            "total_users": st["total_users"],
            "active_subs": st["active_subs"],
            "revenue_30d": st["revenue_30d"],
            "revenue_prev_30d": st["revenue_prev_30d"],
            "orders_30d": st["orders_30d"],
            "new_users_30d": st["new_users_30d"],
            "avg_daily_revenue": int(round(st["revenue_30d"] / max(1, len(st["revenue_series"])))),
            "momentum_pct": momentum,
            "forecast_next7": fc7["total"],
            "forecast_next30": fc30["total"],
            "near_expiry": st["expiring_7d"],
            "expiring_30d": st["expiring_30d"],
        },
    })


@app.get(f"/{S}/api/analytics/ai")
async def api_analytics_ai(request: Request):
    """Ask the configured model to interpret the numbers we computed.

    Every figure in the payload is already final — see core/ai_analyst.py for why
    the model is not permitted to produce one of its own.
    """
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core import ai_analyst
    result = await ai_analyst.analyze(await _analytics_stats())
    return JSONResponse(result, status_code=200 if result.get("ok") else 200)


@app.get(f"/{S}/api/analytics/ai/status")
async def api_analytics_ai_status(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core import ai_analyst
    cfg = await ai_analyst.settings()
    return JSONResponse({
        "enabled": cfg["ai_enabled"] == "1",
        "configured": bool(cfg["ai_api_key"]),
        "provider": cfg["ai_provider"],
        "model": cfg["ai_model"],
        "base_url": cfg["ai_base_url"],
    })


@app.get(f"/{S}/api/analytics/ai/models")
async def api_analytics_ai_models(request: Request):
    """Which models this key can actually use.

    Exists because "model not found" is the one AI misconfiguration the owner
    cannot fix by re-reading their key: model ids are Google's to rename, and
    the only durable answer is to ask the key. Lets the settings page offer a
    list to pick from instead of a text box to guess into.
    """
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core import ai_analyst
    return JSONResponse(await ai_analyst.list_models())


@app.get(f"/{S}/api/analytics/segment/{{kind}}")
async def api_analytics_segment(request: Request, kind: str):
    """Lazy-loaded user lists behind the dashboard tiles."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.database import (get_expiring_profiles, get_top_buyers,
                               get_top_active_service_users, get_online_users_by_emails)

    if kind == "expiring":
        rows = await get_expiring_profiles(3, 100)
        now_ms = int(time.time() * 1000)
        items = [{
            "telegram_id": r.get("telegram_id"), "full_name": r.get("full_name"),
            "username": r.get("username"), "title": r.get("name") or "سرویس",
            "value": f"{max(0, int((int(r.get('expire_timestamp') or 0) - now_ms) / 3600000))} ساعت",
        } for r in rows]
        return JSONResponse({"items": items, "count": len(items)})

    if kind == "top_buyers":
        rows = await get_top_buyers(30)
        items = [{
            "telegram_id": r.get("telegram_id"), "full_name": r.get("full_name"),
            "username": r.get("username"), "title": f"{int(r.get('orders') or 0)} خرید",
            "value": f"{int(r.get('spent') or 0):,} ت",
        } for r in rows]
        return JSONResponse({"items": items, "count": len(items)})

    if kind == "top_services":
        rows = await get_top_active_service_users(30)
        items = [{
            "telegram_id": r.get("telegram_id"), "full_name": r.get("full_name"),
            "username": r.get("username"), "title": "سرویس فعال",
            "value": f"{int(r.get('active_services') or 0)}",
        } for r in rows]
        return JSONResponse({"items": items, "count": len(items)})

    if kind == "online":
        servers = await get_servers(active_only=True)
        sem = _asyncio.Semaphore(8)
        all_emails: list[str] = []

        async def _probe(sv):
            async with sem:
                cli = XUIClient(sv["url"], sv["username"], sv["password"], sv.get("sub_path") or "", sv.get("api_token", ""))
                try:
                    return await _asyncio.wait_for(cli.get_onlines(), timeout=8)
                except Exception:
                    return []
                finally:
                    await cli.close()

        results = await _asyncio.gather(*(_probe(sv) for sv in servers))
        for r in results:
            all_emails.extend(r or [])
        users = await get_online_users_by_emails(all_emails)
        items = [{
            "telegram_id": u.get("telegram_id"), "full_name": u.get("full_name"),
            "username": u.get("username"), "title": "اتصال آنلاین",
            "value": f"{int(u.get('online_conns') or 0)}",
        } for u in users]
        return JSONResponse({"items": items, "count": len(items), "connections": len(all_emails)})

    return JSONResponse({"error": "unknown_kind"}, status_code=400)


# ═══════════════════════════════ MTPROTO PROXY ══════════════════════════════
_MTPROXY_SCRIPT = os.path.join(_repo_dir, "setup_mtproxy.sh")


def _mtproxy_secret(domain: str) -> str:
    """Build a fake-TLS (`ee…`) MTProto secret for the given SNI domain.

    Format: byte 0xEE + 16 random bytes + the domain bytes, hex-encoded. This is
    generated here (not via mtg) so setup never depends on a fragile CLI step."""
    domain = (domain or "www.cloudflare.com").strip().lower() or "www.cloudflare.com"
    return "ee" + secrets.token_hex(16) + domain.encode("utf-8").hex()


def _mtproxy_links(host: str, port, secret: str) -> dict:
    host = (host or "").strip()
    if not host or not secret:
        return {"tg": "", "https": ""}
    q = f"server={host}&port={port}&secret={secret}"
    return {"tg": f"tg://proxy?{q}", "https": f"https://t.me/proxy?{q}"}


async def _mtproxy_run(subcmd: str, cfg: dict, timeout: int = 25) -> str:
    """Run a read-only proxy subcommand (status/test) synchronously and capture it."""
    env = dict(os.environ,
               MTPROXY_PORT=str(cfg.get("port") or 443),
               MTPROXY_SECRET=str(cfg.get("secret") or ""),
               MTPROXY_TAG=str(cfg.get("tag") or ""))
    try:
        proc = await _asyncio.create_subprocess_exec(
            "bash", _MTPROXY_SCRIPT, subcmd,
            stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.STDOUT, env=env,
        )
        out, _ = await _asyncio.wait_for(proc.communicate(), timeout=timeout)
        return (out or b"").decode("utf-8", "replace")
    except Exception as e:
        return f"error: {e}"


async def _mtproxy_cfg() -> dict:
    return {
        "port": int(await get_setting("proxy_port", "443") or 443),
        "secret": await get_setting("proxy_secret", ""),
        "domain": await get_setting("proxy_domain", "www.cloudflare.com"),
        "tag": await get_setting("proxy_tag", ""),
        "host": await get_setting("proxy_host", ""),
    }


def _parse_proxy_status(text: str) -> dict:
    """Parse the `STATUS active=.. listening=.. port=.. connections=.. actual_ports=..`."""
    out = {"active": False, "listening": False, "connections": 0, "port": 0, "actual_ports": ""}
    for line in (text or "").splitlines():
        if line.startswith("STATUS "):
            for kv in line[7:].split():
                if "=" not in kv:
                    continue
                k, v = kv.split("=", 1)
                if k == "active":
                    out["active"] = (v == "active")
                elif k == "listening":
                    out["listening"] = (v == "yes")
                elif k == "connections":
                    out["connections"] = int(v) if v.isdigit() else 0
                elif k == "port":
                    out["port"] = int(v) if v.isdigit() else 0
                elif k == "actual_ports":
                    out["actual_ports"] = "" if v == "none" else v
    return out


@app.get(f"/{S}/api/proxy")
async def api_proxy_get(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    cfg = await _mtproxy_cfg()
    status = _parse_proxy_status(await _mtproxy_run("status", cfg, timeout=12))
    return JSONResponse({
        "config": {"port": cfg["port"], "domain": cfg["domain"], "tag": cfg["tag"],
                   "host": cfg["host"], "has_secret": bool(cfg["secret"])},
        "links": _mtproxy_links(cfg["host"], cfg["port"], cfg["secret"]),
        "status": status,
        "installing": _read_job_log("proxy").get("running", False),
    })


@app.post(f"/{S}/api/proxy/save")
async def api_proxy_save(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    d = await request.json()
    port = max(1, min(65535, int(d.get("port") or 443)))
    domain = (str(d.get("domain") or "www.cloudflare.com").strip().lower()) or "www.cloudflare.com"
    tag = "".join(ch for ch in str(d.get("tag") or "").strip() if ch in "0123456789abcdefABCDEF")
    host = str(d.get("host") or "").strip()
    await set_setting("proxy_port", str(port))
    await set_setting("proxy_domain", domain)
    await set_setting("proxy_tag", tag)
    await set_setting("proxy_host", host)
    # Generate/keep the secret. Regenerate when the domain changed or on request,
    # otherwise keep it stable so existing links don't break.
    secret = await get_setting("proxy_secret", "")
    prev_domain_hex = secret[34:] if len(secret) > 34 else ""
    want_new = bool(d.get("regenerate")) or not secret or prev_domain_hex != domain.encode("utf-8").hex()
    if want_new:
        secret = _mtproxy_secret(domain)
        await set_setting("proxy_secret", secret)
    return JSONResponse({"success": True, "links": _mtproxy_links(host, port, secret), "has_secret": bool(secret)})


@app.post(f"/{S}/api/proxy/install")
async def api_proxy_install(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if _read_job_log("proxy").get("running"):
        return JSONResponse({"error": "یک عملیات پروکسی همین الان در حال اجراست."}, status_code=409)
    cfg = await _mtproxy_cfg()
    if not cfg["secret"]:
        cfg["secret"] = _mtproxy_secret(cfg["domain"])
        await set_setting("proxy_secret", cfg["secret"])
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    subcmd = "apply" if body.get("apply") else "install"
    script = (
        f"export MTPROXY_PORT={shlex.quote(str(cfg['port']))} "
        f"MTPROXY_SECRET={shlex.quote(cfg['secret'])} "
        f"MTPROXY_TAG={shlex.quote(cfg['tag'] or '')}; "
        f"bash {shlex.quote(_MTPROXY_SCRIPT)} {subcmd}"
    )
    _asyncio.create_task(_run_logged_job("proxy", script))
    return JSONResponse({"success": True})


@app.get(f"/{S}/api/proxy/install/log")
async def api_proxy_install_log(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse(_read_job_log("proxy"))


@app.get(f"/{S}/api/proxy/test")
async def api_proxy_test(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    cfg = await _mtproxy_cfg()
    out = await _mtproxy_run("test", cfg, timeout=20)
    ok = "✅" in out and "❌" not in out
    return JSONResponse({"success": ok, "output": out.strip()[-1500:]})


@app.post(f"/{S}/api/proxy/restart")
async def api_proxy_restart(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if _read_job_log("proxy").get("running"):
        return JSONResponse({"error": "یک عملیات پروکسی در حال اجراست."}, status_code=409)
    cfg = await _mtproxy_cfg()
    script = (
        f"export MTPROXY_PORT={shlex.quote(str(cfg['port']))} "
        f"MTPROXY_SECRET={shlex.quote(cfg['secret'] or '')} "
        f"MTPROXY_TAG={shlex.quote(cfg['tag'] or '')}; "
        f"bash {shlex.quote(_MTPROXY_SCRIPT)} restart"
    )
    _asyncio.create_task(_run_logged_job("proxy", script))
    return JSONResponse({"success": True})


@app.get(f"/{S}/api/proxy/logs")
async def api_proxy_logs(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    out = await _mtproxy_run("logs", await _mtproxy_cfg(), timeout=15)
    return JSONResponse({"logs": out.strip()[-4000:]})


@app.post(f"/{S}/api/proxy/uninstall")
async def api_proxy_uninstall(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if _read_job_log("proxy").get("running"):
        return JSONResponse({"error": "یک عملیات پروکسی در حال اجراست."}, status_code=409)
    _asyncio.create_task(_run_logged_job("proxy", f"bash {shlex.quote(_MTPROXY_SCRIPT)} uninstall"))
    return JSONResponse({"success": True})


def _slim_order(o: dict) -> dict:
    return {
        "id": o["id"], "status": o.get("status"), "pkg_name": o.get("pkg_name"),
        "price": int(o.get("price") or 0), "full_name": o.get("full_name"),
        "username": o.get("username"), "telegram_id": o.get("telegram_id"),
        "created_at": o.get("created_at"), "approved_at": o.get("approved_at"),
        "is_renew": bool(int(o.get("renew_config_id") or 0) or int(o.get("renew_sub_profile_id") or 0)),
    }


@app.get(f"/{S}/api/orders")
async def api_orders(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    page = max(1, int(request.query_params.get("page", "1") or 1))
    status = (request.query_params.get("status") or "").strip()
    per_page = 30
    orders_all = await get_all_orders(1000)
    if status:
        orders_all = [o for o in orders_all if str(o.get("status")) == status]
    total = len(orders_all)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    rows = orders_all[start:start + per_page]
    pending = await get_pending_orders()
    return JSONResponse({
        "orders": [_slim_order(o) for o in rows],
        "total": total, "page": page, "total_pages": total_pages,
        "pending_count": len(pending),
    })


@app.post(f"/{S}/api/orders/{{oid}}/approve")
async def api_order_approve(request: Request, oid: int):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        res = await _fulfill_order(oid)
    except Exception as e:
        logger.exception("api order approve failed oid=%s: %s", oid, e)
        await release_order_processing(oid)
        res = {"ok": False, "error": "exception"}
    if res.get("ok"):
        return JSONResponse({"ok": True})
    return JSONResponse({"error": res.get("error") or "failed"}, status_code=400)


@app.post(f"/{S}/api/orders/{{oid}}/reject")
async def api_order_reject(request: Request, oid: int):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    order = await get_order(oid)
    if order:
        await update_order(oid, status="rejected")
        await _clear_review_buttons("order", oid)
    return JSONResponse({"ok": True})


@app.get(f"/{S}/api/users")
async def api_users(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    q = (request.query_params.get("q") or "").strip()
    page = max(1, int(request.query_params.get("page", "1") or 1))
    # Unknown keys fall back to the default inside list_users, so a stale or
    # hand-edited query string can never 500 the page.
    sort = request.query_params.get("sort") or DEFAULT_USER_SORT
    filt = request.query_params.get("filter") or "all"
    period = request.query_params.get("period") or "all"
    per_page = 40

    def _slim_user(u: dict) -> dict:
        # Stats come inline from list_users(); fall back to the per-user helper's
        # shape for callers that still attach u["business"] themselves.
        biz = u.get("business")
        if biz is None:
            biz = {
                "approved_orders": int(u.get("approved_orders") or 0),
                "pending_orders": int(u.get("pending_orders") or 0),
                "total_configs": int(u.get("total_configs") or 0),
                "active_configs": int(u.get("active_configs") or 0),
                "total_subs": int(u.get("total_subs") or 0),
                "active_subs": int(u.get("active_subs") or 0),
                "active_services": int(u.get("active_services") or 0),
                "total_spent": int(u.get("total_spent") or 0),
                "last_order_at": u.get("last_order_at"),
            }
        return {
            "id": u["id"], "telegram_id": u.get("telegram_id"), "username": u.get("username"),
            "full_name": u.get("full_name"), "is_blocked": int(u.get("is_blocked") or 0),
            "is_wholesale": int(u.get("is_wholesale") or 0),
            "wholesale_request_pending": int(u.get("wholesale_request_pending") or 0),
            "hide_brand": int(u.get("hide_brand") or 0),
            "rep_brand_name": u.get("rep_brand_name") or "",
            "admin_role": u.get("admin_role") or "none", "is_admin": int(u.get("is_admin") or 0),
            "balance_toman": int(u.get("balance_toman") or 0),
            "discount_percent": float(u.get("discount_percent") or 0),
            "price_per_gb": int(u.get("price_per_gb") or 0),
            "unlimited_price": int(u.get("unlimited_price") or 0),
            "created_at": u.get("created_at"),
            "business": biz,
        }

    users, total = await list_users(q=q, filt=filt, sort=sort, period=period,
                                    offset=(page - 1) * per_page, limit=per_page)
    total_pages = max(1, (total + per_page - 1) // per_page)
    if page > total_pages:  # filter shrank the result set under the current page
        page = total_pages
        users, total = await list_users(q=q, filt=filt, sort=sort, period=period,
                                        offset=(page - 1) * per_page, limit=per_page)

    wholesale = await get_wholesale_users(200)
    for u in wholesale:
        u["business"] = await get_user_business_stats(u["id"])
    pending_topups = await get_pending_topup_requests(200)
    return JSONResponse({
        "users": [_slim_user(u) for u in users],
        "total": total, "page": page, "total_pages": total_pages,
        "query": q, "sort": sort, "filter": filt, "period": period,
        "sorts": list(USER_SORTS.keys()), "filters": list(USER_FILTERS.keys()),
        "periods": list(USER_PERIODS.keys()),
        "wholesale": [_slim_user(u) for u in wholesale],
        "pending_topups": [{
            "id": t.get("id"), "user_id": t.get("user_id"), "amount": int(t.get("amount") or 0),
            "full_name": t.get("full_name"), "username": t.get("username"), "telegram_id": t.get("telegram_id"),
            "created_at": t.get("created_at"),
        } for t in pending_topups],
    })


@app.post(f"/{S}/api/topups/{{rid}}/approve")
async def api_topup_approve(request: Request, rid: int):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    req = await get_topup_request(rid)
    if req and req.get("status") == "pending":
        await add_user_balance(req["user_id"], int(req["amount"]), kind="topup", note=f"topup_request:{rid}", actor_telegram_id=0)
        await update_topup_request(rid, status="approved", reviewer_telegram_id=0, reviewed_at=datetime.now().isoformat())
        await _clear_review_buttons("topup", rid)
    return JSONResponse({"ok": True})


@app.post(f"/{S}/api/topups/{{rid}}/reject")
async def api_topup_reject(request: Request, rid: int):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    req = await get_topup_request(rid)
    if req and req.get("status") == "pending":
        await update_topup_request(rid, status="rejected", reviewer_telegram_id=0, reviewed_at=datetime.now().isoformat(), admin_note="rejected_web")
        await _clear_review_buttons("topup", rid)
    return JSONResponse({"ok": True})


@app.get(f"/{S}/api/reps")
async def api_reps(request: Request):
    """All representatives with sales/stats, for the admin Representatives page."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.database import get_wholesale_users
    reps = await get_wholesale_users(500)
    out = []
    total_spent = total_active = 0
    for u in reps:
        fin = await get_rep_financials(u["id"]) if int(u.get("is_wholesale") or 0) else {
            "total_spent": 0, "month_spent": 0, "orders": 0, "total_services": 0, "active_services": 0, "expired_services": 0}
        total_spent += int(fin.get("total_spent") or 0)
        total_active += int(fin.get("active_services") or 0)
        out.append({
            "id": u["id"], "telegram_id": u.get("telegram_id"), "username": u.get("username"),
            "full_name": u.get("full_name"), "is_wholesale": int(u.get("is_wholesale") or 0),
            "wholesale_request_pending": int(u.get("wholesale_request_pending") or 0),
            "rep_brand_name": u.get("rep_brand_name") or "", "balance_toman": int(u.get("balance_toman") or 0),
            "created_at": u.get("created_at"),
            "fin": fin,
        })
    out.sort(key=lambda r: r["fin"].get("total_spent") or 0, reverse=True)
    approved = [r for r in out if r["is_wholesale"]]
    return JSONResponse({
        "reps": out,
        "kpi": {"count": len(approved), "pending": sum(1 for r in out if r["wholesale_request_pending"] and not r["is_wholesale"]),
                "total_spent": total_spent, "active_services": total_active},
    })


@app.get(f"/{S}/api/users/{{uid}}")
async def api_user_detail(request: Request, uid: int):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    u = await get_user_by_id(uid)
    if not u:
        return JSONResponse({"error": "not_found"}, status_code=404)
    business = await get_user_business_stats(uid)
    orders = await get_user_orders_full(uid, 100)
    profiles = await get_subscription_profiles_full(uid, 200)
    configs = await get_user_configs_full(uid)
    now_ms = int(time.time() * 1000)

    async def _prof(p):
        try:
            url = await subscription_url(p["token"])
        except Exception:
            url = f"/sub/{p.get('token','')}"
        total_b = int(float(p.get("traffic_gb") or 0) * 1024 ** 3)
        used = int(p.get("used_bytes") or 0)
        exp = int(p.get("expire_timestamp") or 0)
        return {
            "id": p["id"], "name": p.get("name") or p.get("email"), "email": p.get("email"),
            "traffic_gb": float(p.get("traffic_gb") or 0), "used_bytes": used,
            "used_pct": (min(100, int(used / total_b * 100)) if total_b > 0 else 0),
            "expire_timestamp": exp, "days_left": (max(0, int((exp - now_ms) / 86400000)) if exp > 0 else -1),
            "is_active": int(p.get("is_active") or 0), "url": url,
        }

    fin = await get_rep_financials(uid) if int(u.get("is_wholesale") or 0) else None
    return JSONResponse({
        "user": {
            "id": u["id"], "telegram_id": u.get("telegram_id"), "username": u.get("username"),
            "full_name": u.get("full_name"), "is_blocked": int(u.get("is_blocked") or 0),
            "is_wholesale": int(u.get("is_wholesale") or 0),
            "wholesale_request_pending": int(u.get("wholesale_request_pending") or 0),
            "rep_topup_required": int(u.get("rep_topup_required") or 0),
            "hide_brand": int(u.get("hide_brand") or 0),
            "rep_brand_name": u.get("rep_brand_name") or "",
            "admin_role": u.get("admin_role") or "none", "is_admin": int(u.get("is_admin") or 0),
            "balance_toman": int(u.get("balance_toman") or 0),
            "discount_percent": float(u.get("discount_percent") or 0),
            "price_per_gb": int(u.get("price_per_gb") or 0),
            "unlimited_price": int(u.get("unlimited_price") or 0),
            "created_at": u.get("created_at"),
        },
        "business": business,
        "rep_financials": fin,
        "orders": [{
            "id": o["id"], "status": o.get("status"), "pkg_name": o.get("pkg_name"),
            "price": int(o.get("price") or 0), "traffic_gb": o.get("traffic_gb"),
            "duration_days": o.get("duration_days"), "created_at": o.get("created_at"),
            "server_name": o.get("server_name"),
        } for o in orders],
        "profiles": [await _prof(p) for p in profiles],
        "configs": [{
            "id": c["id"], "name": c.get("email") or c.get("name"), "server_name": c.get("server_name"),
            "is_active": int(c.get("is_active") or 0),
        } for c in configs],
    })


# ═══════════════════════════════ DASHBOARD (legacy fallback) ═════════════════
# Root /<secret>/ now serves the React SPA; this stays as a legacy fallback.


@app.post(f"/{S}/updates/approve_send")
async def approve_and_send_update(request: Request, update_text: str = Form("")):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    build = (await get_setting("pending_update_build", "")).strip()
    if not build:
        return JSONResponse({"error": "هیچ آپدیت منتظر تاییدی وجود ندارد."}, status_code=400)

    if update_text.strip():
        await set_setting("pending_update_text", update_text.strip())
        await set_setting("pending_update_text_build", build)
    await set_setting("update_broadcast_approved_build", build)
    try:
        sent = await _send_update_broadcast(build)
        logger.info(f"update broadcast approved and sent from panel | build={build} sent={sent}")
    except Exception as e:
        logger.exception("failed to send approved update broadcast: %s", e)
        return JSONResponse({"error": f"ارسال ناموفق بود: {e}"}, status_code=500)

    return JSONResponse({"success": True, "sent": sent, "build": build})


@app.post(f"/{S}/updates/reject")
async def reject_update_broadcast(request: Request):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    build = (await get_setting("pending_update_build", "")).strip()
    if build:
        await set_setting("skipped_update_build", build)
    await set_setting("pending_update_build", "")
    await set_setting("pending_update_text", "")
    await set_setting("pending_update_text_build", "")
    await set_setting("update_broadcast_approved_build", "")
    return JSONResponse({"success": True})


# ═══════════════════════════════ SERVERS ════════════════════════════
# ═════════════════════════════ BACKUP / RESTORE ═════════════════════════════
@app.get(f"/{S}/api/backups")
async def api_backups(request: Request):
    """Emergency snapshots on disk + the automatic server-backup schedule."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    backups = []
    if os.path.isdir(_backup_dir):
        for item in sorted(os.listdir(_backup_dir), reverse=True)[:20]:
            path = os.path.join(_backup_dir, item)
            if os.path.isfile(path):
                backups.append({
                    "name": item,
                    "size": os.path.getsize(path),
                    "created": datetime.fromtimestamp(os.path.getmtime(path)).isoformat(),
                })
    return JSONResponse({
        "backups": backups,
        "settings": {
            "server_backup_enabled": await get_setting("server_backup_enabled", SETTINGS_DEFAULTS["server_backup_enabled"]),
            "server_backup_interval_hours": await get_setting("server_backup_interval_hours", SETTINGS_DEFAULTS["server_backup_interval_hours"]),
        },
    })


_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _rep_report_for(user_id: int, request: Request):
    """Build a rep's purchase report from the query string. Returns (user, report)."""
    user = await get_user_by_id(int(user_id))
    if not user:
        return None, None
    q = request.query_params
    report = await build_rep_report(
        user,
        preset=str(q.get("preset") or DEFAULT_REPORT_PRESET),
        date_from=str(q.get("from") or ""),
        date_to=str(q.get("to") or ""),
    )
    return user, report


@app.get(f"/{S}/api/reps/{{user_id}}/purchases")
async def api_rep_purchases(request: Request, user_id: int):
    """Date-filtered purchase report for one representative."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    user, report = await _rep_report_for(user_id, request)
    if not user:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(report)


@app.get(f"/{S}/api/reps/{{user_id}}/purchases.xlsx")
async def api_rep_purchases_xlsx(request: Request, user_id: int):
    """The same report as an Excel file (Jalali dates), for record keeping."""
    if not _auth(request):
        return _redir_login()
    user, report = await _rep_report_for(user_id, request)
    if not user:
        return JSONResponse({"error": "not found"}, status_code=404)
    data = rep_report_xlsx(report)
    headers = {"Content-Disposition": f'attachment; filename="{rep_report_filename(report)}"'}
    return StreamingResponse(iter([data]), media_type=_XLSX_MEDIA_TYPE, headers=headers)


@app.get(f"/{S}/api/rep-api")
async def api_rep_api_status(request: Request):
    """Owner view of the representative API: on/off plus every issued key.

    Not part of `_settings_snapshot` on purpose — the React Settings page posts
    the whole snapshot back, so a key that lives there without a form field gets
    blanked on every save. Same treatment as the auto-node knobs.
    """
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core import rep_api as _rep_api
    rows = await _rep_api.list_all_keys(200)
    return JSONResponse({
        "enabled": await get_setting("rep_api_enabled", "1") != "0",
        "max_keys_per_rep": _rep_api.MAX_KEYS_PER_REP,
        "default_rate_per_min": _rep_api.DEFAULT_RATE_PER_MIN,
        "keys": [{
            "id": int(k["id"]), "user_id": int(k["user_id"]),
            "telegram_id": int(k.get("telegram_id") or 0),
            "owner": k.get("full_name") or k.get("username") or "",
            "name": k.get("name") or "", "prefix": k.get("prefix") or "",
            "scopes": k.get("scopes") or "", "ip_allowlist": k.get("ip_allowlist") or "",
            "rate_per_min": int(k.get("rate_per_min") or 0),
            "is_active": bool(int(k.get("is_active") or 0)),
            "created_at": int(k.get("created_at") or 0),
            "last_used_at": int(k.get("last_used_at") or 0),
            "last_ip": k.get("last_ip") or "", "calls": int(k.get("calls") or 0),
        } for k in rows],
    })


@app.post(f"/{S}/api/rep-api/enabled")
async def api_rep_api_toggle(request: Request):
    """Kill switch for the whole representative API."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    enabled = "1" if str(body.get("enabled")).lower() in ("1", "true", "on", "yes") else "0"
    await set_setting("rep_api_enabled", enabled)
    return JSONResponse({"success": True, "enabled": enabled == "1"})


@app.get(f"/{S}/api/reps/{{user_id}}/apikeys")
async def api_rep_apikeys(request: Request, user_id: int):
    """API keys issued to one representative. The key itself is unrecoverable —
    only its prefix and usage are stored, so this lists metadata only."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core import rep_api as _rep_api
    rows = await _rep_api.list_keys(user_id, include_revoked=True)
    return JSONResponse({"keys": [{
        "id": int(k["id"]), "name": k.get("name") or "", "prefix": k.get("prefix") or "",
        "scopes": k.get("scopes") or "", "ip_allowlist": k.get("ip_allowlist") or "",
        "rate_per_min": int(k.get("rate_per_min") or 0),
        "is_active": bool(int(k.get("is_active") or 0)),
        "created_at": int(k.get("created_at") or 0), "last_used_at": int(k.get("last_used_at") or 0),
        "last_ip": k.get("last_ip") or "", "calls": int(k.get("calls") or 0),
    } for k in rows]})


@app.post(f"/{S}/api/reps/{{user_id}}/apikeys/{{key_id}}/revoke")
async def api_rep_apikey_revoke(request: Request, user_id: int, key_id: int):
    """Admin kill switch for a single leaked/abused key."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core import rep_api as _rep_api
    return JSONResponse({"success": await _rep_api.revoke_key(key_id, user_id)})


@app.get(f"/{S}/backups/download")
async def backup_download(request: Request):
    if not _auth(request):
        return _redir_login()
    name = _safe_backup_name()
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    return StreamingResponse(iter([_build_backup_zip()]), media_type="application/zip", headers=headers)


@app.get(f"/{S}/backups/emergency/{{name}}")
async def backup_emergency_download(request: Request, name: str):
    if not _auth(request):
        return _redir_login()
    clean = os.path.basename(name)
    path = os.path.join(_backup_dir, clean)
    if not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, media_type="application/zip", filename=clean)


@app.get(f"/{S}/backups/servers/download")
async def backups_servers_download(request: Request):
    if not _auth(request):
        return _redir_login()
    from core.backup import build_servers_backup
    fname, data = await build_servers_backup()
    headers = {"Content-Disposition": f'attachment; filename="{fname}"'}
    return StreamingResponse(iter([data]), media_type="application/zip", headers=headers)


@app.post(f"/{S}/backups/servers/settings")
async def backups_servers_settings(
    request: Request,
    server_backup_enabled: str = Form("0"),
    server_backup_interval_hours: int = Form(6),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await set_setting("server_backup_enabled", "1" if server_backup_enabled == "1" else "0")
    await set_setting("server_backup_interval_hours", str(max(1, min(168, int(server_backup_interval_hours or 6)))))
    return JSONResponse({"success": True})


@app.post(f"/{S}/backups/servers/send")
async def backups_servers_send(request: Request):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not BOT_TOKEN or len(BOT_TOKEN) < 20:
        return JSONResponse({"error": "توکن ربات تنظیم نشده است."}, status_code=400)
    from core.backup import build_servers_backup
    from core.database import get_all_admin_telegram_ids, get_servers

    # Owner-level recipients only (backup is sensitive).
    owner_id = int(await get_setting("owner_admin_id", "0") or 0)
    targets = list(dict.fromkeys(list(ADMIN_IDS) + ([owner_id] if owner_id else [])))
    if not targets:
        return JSONResponse({"error": "هیچ ادمین کلی تنظیم نشده است."}, status_code=400)

    try:
        fname, data = await build_servers_backup()
    except Exception as e:
        return JSONResponse({"error": f"ساخت بکاپ ناموفق بود: {e}"}, status_code=500)

    servers = await get_servers(active_only=False)
    size_mb = len(data) / (1024 * 1024)
    caption = f"🗄 بکاپ پنل‌ها (دستی) — {len(servers)} سرور | {size_mb:.2f} MB"
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    sent = 0
    try:
        for aid in targets:
            try:
                await bot.send_document(aid, BufferedInputFile(data, filename=fname), caption=caption, parse_mode=None)
                sent += 1
            except Exception as e:
                logger.warning("manual server backup send to %s failed: %s", aid, e)
    finally:
        await bot.session.close()
    if not sent:
        return JSONResponse({"error": "ارسال به ادمین ناموفق بود (شاید ربات را استارت نکرده‌اید)."}, status_code=502)
    return JSONResponse({"success": True, "sent": sent, "servers": len(servers)})


@app.post(f"/{S}/backups/restore")
async def backup_restore(
    request: Request,
    backup_file: UploadFile = File(...),
    restore_env: str = Form("0"),
    restore_ssl: str = Form("0"),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    with tempfile.TemporaryDirectory() as tmpdir:
        upload_path = os.path.join(tmpdir, "uploaded-backup")
        with open(upload_path, "wb") as f:
            shutil.copyfileobj(backup_file.file, f)

        try:
            db_restore, env_restore, sys_staged = _extract_restore_payload(upload_path, tmpdir)
            pre_name = _save_pre_restore_backup()
            os.replace(db_restore, _db_path)
            if restore_env == "1" and env_restore:
                os.replace(env_restore, _env_path)
            ssl = {}
            if restore_ssl == "1" and sys_staged:
                res = _restore_system_files(sys_staged)
                ssl = {"ssl_restored": res["restored"], "ssl_failed": res["failed"]}
            await init_db()
            # `pre` is the snapshot taken of the CURRENT database before it was
            # overwritten — the caller needs its name to undo a bad restore.
            return JSONResponse({"success": True, "pre_restore_backup": pre_name, **ssl})
        except Exception as e:
            logger.exception("backup restore failed: %s", e)
            return JSONResponse({"error": f"بازیابی ناموفق بود: {e}"}, status_code=400)


@app.get(f"/{S}/api/reports")
async def api_reports(request: Request):
    """Daily snapshots. Reading the page also takes today's snapshot, which is
    what makes "today" a live row rather than yesterday's leftovers."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({
        "today": await snapshot_daily_report(),
        "reports": await get_recent_daily_reports(60),
    })




@app.post(f"/{S}/servers/add")
async def server_add(
    request: Request,
    name: str = Form(...),
    url: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    api_token: str = Form(""),
    sub_path: str = Form(""),
    inbound_id: int = Form(1),
    inbound_ids: str = Form(""),
    note: str = Form(""),
    max_active_configs: int = Form(0),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    sid = await add_server(name, url.rstrip("/"), username, password, sub_path.strip("/"), inbound_id, note, inbound_ids=inbound_ids, api_token=api_token.strip())
    await update_server(sid, max_active_configs=max_active_configs)
    return JSONResponse({"success": True})


@app.post(f"/{S}/servers/{{sid}}/toggle")
async def server_toggle(request: Request, sid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    srv = await get_server(sid)
    if not srv:
        return JSONResponse({"error": "not found"}, status_code=404)
    await update_server(sid, is_active=0 if srv["is_active"] else 1)
    return JSONResponse({"success": True, "is_active": not srv["is_active"]})


@app.post(f"/{S}/servers/{{sid}}/edit")
async def server_edit(
    request: Request,
    sid: int,
    name: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    username: Optional[str] = Form(None),
    password: str = Form(""),
    api_token: str = Form(""),
    sub_path: Optional[str] = Form(None),
    inbound_id: Optional[int] = Form(None),
    inbound_ids: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    max_active_configs: Optional[int] = Form(None),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    srv = await get_server(sid)
    if not srv:
        return JSONResponse({"error": "not found"}, status_code=404)

    updates = dict(
        name=(name if name is not None and name.strip() else srv.get("name", "")),
        url=((url if url is not None and url.strip() else srv.get("url", "")).rstrip("/")),
        username=(username if username is not None and username.strip() else srv.get("username", "")),
        password=password or srv.get("password", ""),
        sub_path=(sub_path if sub_path is not None else srv.get("sub_path", "")).strip("/"),
        inbound_id=inbound_id if inbound_id is not None else int(srv.get("inbound_id") or 1),
        note=note if note is not None else srv.get("note", ""),
        inbound_ids=inbound_ids if inbound_ids is not None else srv.get("inbound_ids", ""),
        max_active_configs=max_active_configs if max_active_configs is not None else int(srv.get("max_active_configs") or 0),
    )
    if api_token.strip():
        updates["api_token"] = api_token.strip()
    await update_server(sid, **updates)
    return JSONResponse({"success": True})


@app.post(f"/{S}/servers/{{sid}}/delete")
async def server_delete(request: Request, sid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await delete_server(sid)
    return JSONResponse({"success": True})


@app.post(f"/{S}/servers/{{sid}}/test")
async def server_test(request: Request, sid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    srv = await get_server(sid)
    if not srv:
        return JSONResponse({"success": False, "msg": "not found"})
    cli = XUIClient(srv["url"], srv["username"], srv["password"], srv["sub_path"], srv.get("api_token", ""))
    ok = await cli.test_connection()
    await cli.close()
    return JSONResponse({"success": ok})


@app.get(f"/{S}/api/servers")
async def api_servers(request: Request):
    """Server list for the React panel (secrets omitted, presence flagged)."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    servers = await get_servers(active_only=False)
    out = []
    for s in servers:
        out.append({
            "id": s["id"], "name": s.get("name"), "url": s.get("url"),
            "username": s.get("username"), "sub_path": s.get("sub_path") or "",
            "inbound_id": int(s.get("inbound_id") or 1),
            "inbound_ids": s.get("inbound_ids") or "",
            "note": s.get("note") or "",
            "max_active_configs": int(s.get("max_active_configs") or 0),
            "is_active": int(s.get("is_active") or 0),
            "has_api_token": bool((s.get("api_token") or "").strip()),
            "has_password": bool((s.get("password") or "").strip()),
            "active_configs": await count_active_configs_by_server(int(s["id"])),
        })
    return JSONResponse({"servers": out})


# ═════════════════════════════ SUBSCRIPTIONS ═══════════════════════




@app.post(f"/{S}/subs/profiles/{{profile_id}}/toggle")
async def subscription_profile_toggle(request: Request, profile_id: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    profile = await get_subscription_profile(profile_id)
    if not profile:
        return JSONResponse({"success": False, "error": "not found"}, status_code=404)
    from core.database import update_subscription_profile
    from core.multi_subscription import set_nodes_enabled
    next_active = 0 if int(profile.get("is_active") or 0) else 1
    await update_subscription_profile(profile_id, is_active=next_active)
    # Actually enable/disable every server (re-creating any client that was
    # removed after expiry) — not just flip the DB flag.
    try:
        await set_nodes_enabled(profile_id, bool(next_active))
    except Exception as e:
        logger.warning("toggle set_nodes_enabled failed pid=%s: %s", profile_id, e)
    return JSONResponse({"success": True, "is_active": bool(next_active)})


@app.post(f"/{S}/subs/profiles/{{profile_id}}/edit")
async def subscription_profile_edit(
    request: Request,
    profile_id: int,
    email: str = Form(...),
    traffic_gb: float = Form(...),
    expire_at: str = Form(""),
    is_active: str = Form("1"),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    profile = await get_subscription_profile(profile_id)
    if not profile:
        return JSONResponse({"error": "سرویس پیدا نشد."}, status_code=404)

    clean_email = re.sub(r"[^A-Za-z0-9_.@:-]+", "_", (email or "").strip())[:96] or str(profile.get("email") or f"sub_{profile_id}")
    traffic_gb = max(0.1, float(traffic_gb or 0.1))
    expire_ms = 0
    if (expire_at or "").strip():
        try:
            expire_ms = int(datetime.fromisoformat(expire_at.strip()).timestamp() * 1000)
        except ValueError:
            expire_ms = int(profile.get("expire_timestamp") or 0)

    result = await edit_subscription_profile(profile, clean_email, traffic_gb, expire_ms, is_active == "1")
    if not result.get("ok"):
        return JSONResponse({"error": "اعمال تغییرات روی سرورها ناموفق بود."}, status_code=502)
    return JSONResponse({"success": True})


@app.post(f"/{S}/subs/profiles/{{profile_id}}/reset-usage")
async def subscription_profile_reset_usage(request: Request, profile_id: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    res = await reset_subscription_usage(profile_id)
    return JSONResponse({"success": bool(res.get("ok")), **res})


@app.post(f"/{S}/subs/profiles/{{profile_id}}/reset-time")
async def subscription_profile_reset_time(request: Request, profile_id: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    res = await reset_subscription_time(profile_id)
    return JSONResponse({"success": bool(res.get("ok")), **res})


@app.post(f"/{S}/subs/profiles/{{profile_id}}/rebuild")
async def subscription_profile_rebuild(request: Request, profile_id: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    res = await rebuild_subscription_profile(profile_id)
    return JSONResponse({"success": bool(res.get("ok")), **res})


@app.post(f"/{S}/subs/profiles/{{profile_id}}/delete")
async def subscription_profile_delete(request: Request, profile_id: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    profile = await get_subscription_profile(profile_id)
    if not profile:
        return JSONResponse({"success": False, "error": "not found"}, status_code=404)
    result = await delete_subscription_profile_remote(profile_id)
    return JSONResponse({"success": True, **result})


# Sort/filter for the subscription (service) lists. Done in Python because the
# rows are already fully materialised and the derived keys (usage %, days left)
# aren't columns.
SUB_SORTS = ["newest", "oldest", "name_az", "name_za", "owner_az",
             "expiry_soon", "expiry_late", "usage_desc", "usage_asc", "traffic_desc"]
SUB_FILTERS = ["all", "active", "inactive", "expired", "expiring", "near_limit", "unlimited"]


def _profile_sort_name(p: dict) -> list:
    return fa_sort_key(p.get("name") or p.get("email") or "")


def _sort_filter_profiles(rows: list, sort: str, filt: str, now_ms: int) -> list:
    def used_pct(p):
        total_b = float(p.get("traffic_gb") or 0) * 1024 ** 3
        return (min(100.0, float(p.get("used_bytes") or 0) / total_b * 100) if total_b > 0 else 0.0)

    def expired(p):
        exp = int(p.get("expire_timestamp") or 0)
        return exp > 0 and exp <= now_ms

    def days_left(p):
        exp = int(p.get("expire_timestamp") or 0)
        return (exp - now_ms) / 86400000 if exp > 0 else None

    if filt == "active":
        rows = [p for p in rows if int(p.get("is_active") or 0) and not expired(p)]
    elif filt == "inactive":
        rows = [p for p in rows if not int(p.get("is_active") or 0)]
    elif filt == "expired":
        rows = [p for p in rows if expired(p)]
    elif filt == "expiring":  # ≤3 days left and still alive
        rows = [p for p in rows if int(p.get("is_active") or 0) and not expired(p)
                and days_left(p) is not None and days_left(p) <= 3]
    elif filt == "near_limit":
        rows = [p for p in rows if used_pct(p) >= 85]
    elif filt == "unlimited":
        rows = [p for p in rows if float(p.get("traffic_gb") or 0) <= 0]

    # No-expiry profiles sort last under "soonest", first under "latest".
    INF = float("inf")
    keys = {
        "newest":      (lambda p: int(p.get("id") or 0), True),
        "oldest":      (lambda p: int(p.get("id") or 0), False),
        "name_az":     (_profile_sort_name, False),
        "name_za":     (_profile_sort_name, True),
        "owner_az":    (lambda p: fa_sort_key(p.get("full_name") or p.get("username") or ""), False),
        "expiry_soon": (lambda p: (days_left(p) if days_left(p) is not None else INF), False),
        "expiry_late": (lambda p: (days_left(p) if days_left(p) is not None else INF), True),
        "usage_desc":  (used_pct, True),
        "usage_asc":   (used_pct, False),
        "traffic_desc": (lambda p: float(p.get("traffic_gb") or 0), True),
    }
    key, rev = keys.get(sort or "", keys["newest"])
    # Stable secondary order by id so equal keys page deterministically.
    rows = sorted(rows, key=lambda p: int(p.get("id") or 0), reverse=True)
    return sorted(rows, key=key, reverse=rev)


@app.get(f"/{S}/api/subs/profiles")
async def api_subs_profiles(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    q = (request.query_params.get("q") or "").strip().lower()
    page = max(1, int(request.query_params.get("page", "1") or 1))
    sort = request.query_params.get("sort") or "newest"
    filt = request.query_params.get("filter") or "all"
    per_page = 40
    all_p = await get_subscription_profiles_full(limit=2000)
    if q:
        all_p = [p for p in all_p if q in str(p.get("email") or "").lower()
                 or q in str(p.get("name") or "").lower()
                 or q in str(p.get("telegram_id") or "").lower()
                 or q in str(p.get("full_name") or "").lower()]

    now_ms = int(time.time() * 1000)
    all_p = _sort_filter_profiles(all_p, sort, filt, now_ms)

    total = len(all_p)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    items = []
    for p in all_p[(page - 1) * per_page: page * per_page]:
        try:
            url = await subscription_url(p["token"])
        except Exception:
            url = f"/sub/{p['token']}"
        total_b = int(float(p.get("traffic_gb") or 0) * 1024 ** 3)
        used = int(p.get("used_bytes") or 0)
        exp = int(p.get("expire_timestamp") or 0)
        items.append({
            "id": p["id"], "name": p.get("name") or "", "email": p.get("email"),
            "telegram_id": p.get("telegram_id"), "full_name": p.get("full_name"), "username": p.get("username"),
            "is_active": int(p.get("is_active") or 0), "traffic_gb": float(p.get("traffic_gb") or 0),
            "used_bytes": used, "used_pct": (min(100, int(used / total_b * 100)) if total_b > 0 else 0),
            "expire_timestamp": exp,
            "days_left": (max(0, int((exp - now_ms) / 86400000)) if exp > 0 else -1),
            "url": url,
        })
    return JSONResponse({"profiles": items, "total": total, "page": page, "total_pages": total_pages,
                         "query": q, "sort": sort, "filter": filt,
                         "sorts": SUB_SORTS, "filters": SUB_FILTERS})


@app.post(f"/{S}/subs/settings")
async def subscriptions_settings_save(
    request: Request,
    multi_sub_node_count: int = Form(4),
    multi_sub_min_nodes: int = Form(2),
    sub_auto_sync_enabled: str = Form("0"),
    sub_auto_sync_interval_hours: int = Form(1),
    public_base_url: str = Form(""),
    sub_info_enabled: str = Form("0"),
    sub_info_sync_on_render: str = Form("0"),
    sub_info_template: str = Form(""),
    sub_brand_template: str = Form(""),
    sub_start_on_first_use: str = Form("0"),
    convert_single_on_renew: str = Form("0"),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    # Min/max node caps were removed: every subscription now uses ALL usable nodes.
    # These settings are kept (no ceiling) only for backward-compat display.
    node_count = max(0, int(multi_sub_node_count or 0))
    min_nodes = max(0, int(multi_sub_min_nodes or 0))
    # Subscriptions are the only fulfilment model now, so multi_sub_enabled is kept
    # pinned on rather than exposed as a toggle that could break the store.
    await set_setting("multi_sub_enabled", "1")
    await set_setting("multi_sub_node_count", str(node_count))
    await set_setting("multi_sub_min_nodes", str(min_nodes))
    await set_setting("sub_auto_sync_enabled", "1" if sub_auto_sync_enabled == "1" else "0")
    await set_setting("sub_auto_sync_interval_hours", str(max(1, min(24, int(sub_auto_sync_interval_hours or 1)))))
    await set_setting("public_base_url", public_base_url.strip().rstrip("/"))
    await set_setting("sub_info_enabled", "1" if sub_info_enabled == "1" else "0")
    await set_setting("sub_info_sync_on_render", "1" if sub_info_sync_on_render == "1" else "0")
    await set_setting("sub_info_template", sub_info_template.strip() or SETTINGS_DEFAULTS["sub_info_template"])
    await set_setting("sub_brand_template", sub_brand_template.strip() or SETTINGS_DEFAULTS["sub_brand_template"])
    await set_setting("sub_start_on_first_use", "1" if sub_start_on_first_use == "1" else "0")
    await set_setting("convert_single_on_renew", "1" if convert_single_on_renew == "1" else "0")
    return JSONResponse({"success": True})


@app.post(f"/{S}/subs/sync-nodes")
async def subscription_sync_nodes(request: Request):
    # Legacy blocking endpoint kept for compatibility; the panel now uses the
    # streamed start/log endpoints below for a fast, observable sync.
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    result = await sync_subscription_nodes_for_all(5000, force_refresh=False)
    return JSONResponse({"success": True, **result})


@app.post(f"/{S}/subs/sync-nodes/start")
async def subscription_sync_nodes_start(request: Request):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if _read_job_log("sync").get("running"):
        return JSONResponse({"error": "یک همگام‌سازی همین الان در حال اجراست."}, status_code=409)
    form = await request.form()
    deep = str(form.get("deep") or "").lower() in ("1", "true", "on", "yes")

    async def _runner(log):
        await sync_subscription_nodes_streamed(log, limit=5000, force_refresh=deep, concurrency=6)

    _asyncio.create_task(_run_python_job("sync", _runner))
    return JSONResponse({"success": True, "deep": deep})


@app.get(f"/{S}/subs/sync-nodes/log")
async def subscription_sync_nodes_log(request: Request):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse(_read_job_log("sync"))


def _start_nodeops(node_id: int, remove: bool = False, force_refresh: bool = False) -> bool:
    """Kick off a real-time single-node reconciliation as a streamed job.

    Returns False (without starting) if a node op is already running, so callers
    can tell the user to wait rather than overlapping two writes to the panels.
    """
    if _read_job_log("nodeops").get("running"):
        return False

    async def _runner(log):
        await reconcile_node_config_streamed(
            log, int(node_id), remove=remove, force_refresh=force_refresh,
            limit=5000, concurrency=6,
        )

    _asyncio.create_task(_run_python_job("nodeops", _runner))
    return True


async def _node_form_body(request: Request) -> dict:
    """Read a node add/edit body from either JSON (React) or a form post (legacy)."""
    if "application/json" in request.headers.get("content-type", ""):
        return await request.json()
    form = await request.form()
    return dict(form)


@app.post(f"/{S}/subs/nodes/add")
async def subscription_node_add(request: Request):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    d = await _node_form_body(request)
    node_id = await add_subscription_node_config(
        int(d.get("server_id")), int(d.get("inbound_id")),
        str(d.get("label") or "").strip(), int(d.get("priority") or 100),
        int(d.get("max_active_profiles") or 0), str(d.get("connect_host") or "").strip(),
    )
    # Immediately provision this node onto every active subscription (background,
    # observable via the node-ops log). Adding a node now shows up in all links.
    started = _start_nodeops(node_id, remove=False, force_refresh=False)
    if "application/json" in request.headers.get("content-type", ""):
        return JSONResponse({"success": True, "node_id": node_id, "job_started": started})
    return JSONResponse({"success": True})


def _as_flag(value) -> int:
    """Accept a checkbox, a JSON boolean, or a string — all mean the same thing."""
    if isinstance(value, bool):
        return 1 if value else 0
    return 1 if str(value or "").strip().lower() in ("1", "true", "on", "yes") else 0


@app.post(f"/{S}/subs/nodes/add_auto")
async def subscription_auto_node_add(request: Request):
    """Create an auto node — the entry that follows the least-busy server."""
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    d = await _node_form_body(request)
    # Validate BEFORE inserting: creating the row first would leave an orphan
    # auto node behind on every rejected attempt, and a retry would add another.
    pool = parse_auto_pool(d.get("auto_pool"))
    candidates = await get_auto_node_candidates({"auto_pool": ",".join(str(i) for i in pool)})
    if not candidates:
        return JSONResponse({
            "success": False,
            "error": ("هیچ نود قابل استفاده‌ای برای استخر خودکار وجود ندارد. "
                      "اول حداقل یک نود معمولی فعال بسازید."),
        }, status_code=400)
    node_id = await add_auto_subscription_node_config(
        label=str(d.get("label") or "").strip() or "🚀 خودکار",
        priority=int(d.get("priority") or 1),
        auto_pool=str(d.get("auto_pool") or ""),
        auto_show_server=_as_flag(d.get("auto_show_server")),
        connect_host=str(d.get("connect_host") or "").strip(),
    )
    started = _start_nodeops(node_id, remove=False, force_refresh=False)
    return JSONResponse({"success": True, "node_id": node_id, "job_started": started})


@app.post(f"/{S}/subs/nodes/{{node_id}}/edit")
async def subscription_node_edit(request: Request, node_id: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    d = await _node_form_body(request)
    before = await get_subscription_node_config(node_id)

    # An auto node has no server/inbound of its own — only its label, priority
    # and pool are editable, and changing the pool never needs a panel round-trip
    # (the next rebalance picks it up).
    if before and int(before.get("is_auto") or 0):
        fields = dict(
            label=str(d.get("label") or "").strip(),
            priority=int(d.get("priority") or 1),
            auto_pool=",".join(str(i) for i in parse_auto_pool(d.get("auto_pool"))),
            auto_show_server=_as_flag(d.get("auto_show_server")),
        )
        if "connect_host" in d:
            fields["connect_host"] = str(d.get("connect_host") or "").strip()
        await update_subscription_node_config(node_id, **fields)
        # A changed label only shows up once each link is relabelled, so refresh.
        started = _start_nodeops(node_id, remove=False, force_refresh=True)
        if "application/json" in request.headers.get("content-type", ""):
            return JSONResponse({"success": True, "job_started": started})
        return JSONResponse({"success": True})

    server_id = int(d.get("server_id"))
    inbound_id = int(d.get("inbound_id"))
    update_fields = dict(
        server_id=int(server_id),
        inbound_id=int(inbound_id),
        label=str(d.get("label") or "").strip(),
        priority=int(d.get("priority") or 100),
        max_active_profiles=int(d.get("max_active_profiles") or 0),
    )
    # Only overwrite connect_host when the caller actually submitted it, so the
    # legacy edit form (which has no domain field) can't silently wipe a domain.
    if "connect_host" in d:
        update_fields["connect_host"] = str(d.get("connect_host") or "").strip()
    await update_subscription_node_config(node_id, **update_fields)
    # If the server/inbound changed, links must be rebuilt (move); a bare label or
    # connect_host change needs no panel calls (render applies host live), but a
    # force refresh is cheap-ish and guarantees consistency, so we refresh on any
    # target change.
    target_changed = bool(before) and (
        int(before.get("server_id") or 0) != int(server_id)
        or int(before.get("inbound_id") or 0) != int(inbound_id)
    )
    started = False
    if target_changed:
        started = _start_nodeops(node_id, remove=False, force_refresh=True)
    if "application/json" in request.headers.get("content-type", ""):
        return JSONResponse({"success": True, "job_started": started})
    return JSONResponse({"success": True})


@app.post(f"/{S}/subs/nodes/{{node_id}}/toggle")
async def subscription_node_toggle(request: Request, node_id: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    node = await get_subscription_node_config(node_id)
    if not node:
        return JSONResponse({"success": False, "error": "not found"}, status_code=404)
    now_active = 0 if int(node.get("is_active") or 0) else 1
    await update_subscription_node_config(node_id, is_active=now_active)
    # Real-time: disabling removes this node from every link; enabling re-creates it.
    started = _start_nodeops(node_id, remove=(now_active == 0), force_refresh=False)
    return JSONResponse({"success": True, "is_active": now_active, "job_started": started})


@app.post(f"/{S}/subs/nodes/{{node_id}}/reconcile")
async def subscription_node_reconcile(request: Request, node_id: int):
    """Force-rebuild this node's link on every subscription (apply inbound edits)."""
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    node = await get_subscription_node_config(node_id)
    if not node:
        return JSONResponse({"success": False, "error": "not found"}, status_code=404)
    started = _start_nodeops(node_id, remove=False, force_refresh=True)
    if not started:
        return JSONResponse({"success": False, "error": "یک عملیات نود همین الان در حال اجراست."}, status_code=409)
    return JSONResponse({"success": True, "job_started": True})


@app.post(f"/{S}/subs/nodes/{{node_id}}/delete")
async def subscription_node_delete(request: Request, node_id: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    # Remove from every subscription first (matches by email suffix _n{id}, so it
    # works even after the config row is gone), then delete the config.
    started = _start_nodeops(node_id, remove=True, force_refresh=False)
    await delete_subscription_node_config(node_id)
    return JSONResponse({"success": True, "job_started": started})


@app.get(f"/{S}/subs/nodes/ops/log")
async def subscription_nodeops_log(request: Request):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse(_read_job_log("nodeops"))


@app.get(f"/{S}/api/subs")
async def api_subs(request: Request):
    """Everything the React Subscriptions page needs: nodes, servers, settings."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    nodes = await get_subscription_node_configs(active_only=False)
    out_nodes = []
    for node in nodes:
        status = await subscription_node_config_status(node)
        is_auto = int(node.get("is_auto") or 0)
        if is_auto:
            # An auto node owns no server/inbound, so count the subscriptions
            # currently routed through it instead.
            active_profiles = sum((await count_auto_assignments_by_target(int(node["id"]))).values())
        else:
            active_profiles = await count_active_subscription_nodes_by_target(node["server_id"], node["inbound_id"])
        out_nodes.append({
            "id": node["id"],
            "server_id": node["server_id"],
            "server_name": node.get("server_name"),
            "server_url": node.get("server_url"),
            "server_active": int(node.get("server_active") or 0),
            "inbound_id": node["inbound_id"],
            "label": node.get("label") or "",
            "priority": int(node.get("priority") or 100),
            "max_active_profiles": int(node.get("max_active_profiles") or 0),
            "connect_host": node.get("connect_host") or "",
            "is_active": int(node.get("is_active") or 0),
            "active_profiles": active_profiles,
            "usable": status["usable"],
            "usable_label": status["label"],
            "usable_reason": status["reason"],
            "is_auto": is_auto,
            "auto_pool": node.get("auto_pool") or "",
            "auto_show_server": int(node.get("auto_show_server") or 0),
        })
    servers = await get_servers(active_only=False)
    return JSONResponse({
        "nodes": out_nodes,
        "servers": [{"id": s["id"], "name": s.get("name"), "is_active": int(s.get("is_active") or 0)} for s in servers],
        "autonode": await auto_node_overview(),
        "settings": {
            "public_base_url": await get_setting("public_base_url", ""),
            "sub_auto_sync_enabled": await get_setting("sub_auto_sync_enabled", "0"),
            "sub_auto_sync_interval_hours": await get_setting("sub_auto_sync_interval_hours", "1"),
        },
    })


@app.post(f"/{S}/subs/autonode/refresh")
async def subscription_autonode_refresh(request: Request):
    """Re-read every panel's online count right now (no subscriptions touched)."""
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    counts = await refresh_server_online_counts()
    return JSONResponse({
        "success": True,
        "polled": len(counts),
        "unknown": sum(1 for v in counts.values() if v is None),
        "autonode": await auto_node_overview(),
    })


@app.post(f"/{S}/subs/autonode/rebalance")
async def subscription_autonode_rebalance(request: Request):
    """Redistribute subscriptions across servers now, streamed to the node-ops log."""
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if _read_job_log("nodeops").get("running"):
        return JSONResponse({"success": False, "error": "یک عملیات نود همین الان در حال اجراست."}, status_code=409)

    async def _runner(log):
        await rebalance_all_auto_nodes(log=log, refresh=True, concurrency=6)

    _asyncio.create_task(_run_python_job("nodeops", _runner))
    return JSONResponse({"success": True, "job_started": True})


@app.post(f"/{S}/subs/autonode/settings")
async def subscription_autonode_settings(request: Request):
    """Save the load-balancer tuning knobs (each is validated, none are required)."""
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    d = await _node_form_body(request)
    for key in AUTONODE_DEFAULTS:
        if key not in d:
            continue
        if key == "autonode_enabled":
            await set_setting(key, "1" if _as_flag(d.get(key)) else "0")
            continue
        raw = str(d.get(key) or "").strip()
        try:
            value = float(raw)
        except ValueError:
            continue
        if value < 0:
            continue
        await set_setting(key, str(value) if key == "autonode_margin" else str(int(value)))
    return JSONResponse({"success": True, "autonode": await auto_node_overview()})


@app.get(f"/{S}/subs/nodes/{{node_id}}/inbound")
async def subscription_node_inbound_get(request: Request, node_id: int):
    """Fetch the raw inbound so it can be edited from our panel (no 3x-ui trip)."""
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    node = await get_subscription_node_config(node_id)
    if not node:
        return JSONResponse({"success": False, "error": "not found"}, status_code=404)
    cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
    try:
        inbound = await cli.get_inbound(int(node["inbound_id"]))
        if not inbound:
            return JSONResponse({"success": False, "error": cli.last_error or "inbound_not_found"}, status_code=502)

        def _as_text(v):
            # 3x-ui usually returns these as JSON strings, but some forks parse them
            # to objects. Always hand the panel a pretty JSON string to edit.
            if v is None:
                return ""
            if isinstance(v, (dict, list)):
                return json.dumps(v, ensure_ascii=False, indent=2)
            return str(v)

        return JSONResponse({"success": True, "inbound": {
            "id": inbound.get("id"),
            "remark": inbound.get("remark", ""),
            "port": inbound.get("port"),
            "protocol": inbound.get("protocol"),
            "enable": bool(inbound.get("enable", True)),
            "listen": inbound.get("listen", ""),
            "expiryTime": inbound.get("expiryTime", 0),
            "total": inbound.get("total", 0),
            "settings": _as_text(inbound.get("settings")),
            "streamSettings": _as_text(inbound.get("streamSettings")),
            "sniffing": _as_text(inbound.get("sniffing")),
        }})
    finally:
        await cli.close()


@app.post(f"/{S}/subs/nodes/{{node_id}}/inbound")
async def subscription_node_inbound_update(request: Request, node_id: int):
    """Save inbound edits back to 3x-ui, then rebuild all links for this node."""
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    node = await get_subscription_node_config(node_id)
    if not node:
        return JSONResponse({"success": False, "error": "not found"}, status_code=404)
    data = await request.json()
    cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
    try:
        current = await cli.get_inbound(int(node["inbound_id"]))
        if not current:
            return JSONResponse({"success": False, "error": cli.last_error or "inbound_not_found"}, status_code=502)
        # Start from the live inbound and overlay only the editable fields so we
        # never drop data 3x-ui expects (clientStats, tag, allocate, …).
        payload = dict(current)
        for key in ("remark", "listen", "settings", "streamSettings", "sniffing"):
            if key in data and data[key] is not None:
                payload[key] = data[key]
        if "port" in data and data["port"]:
            payload["port"] = int(data["port"])
        if "enable" in data:
            payload["enable"] = bool(data["enable"])
        if "expiryTime" in data:
            payload["expiryTime"] = int(data["expiryTime"] or 0)
        if "total" in data:
            payload["total"] = int(data["total"] or 0)
        # Validate any JSON-string fields the admin edited before pushing.
        for key in ("settings", "streamSettings", "sniffing"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                try:
                    json.loads(val)
                except Exception:
                    return JSONResponse({"success": False, "error": f"invalid JSON in {key}"}, status_code=400)
        ok = await cli.update_inbound(int(node["inbound_id"]), payload)
        if not ok:
            return JSONResponse({"success": False, "error": cli.last_error or "update_failed"}, status_code=502)
    finally:
        await cli.close()
    # Rebuild every subscription's link for this node so the inbound change lands.
    started = _start_nodeops(node_id, remove=False, force_refresh=True)
    return JSONResponse({"success": True, "job_started": started})


@app.post(f"/{S}/subs/nodes/{{node_id}}/test")
async def subscription_node_test(request: Request, node_id: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    node = await get_subscription_node_config(node_id)
    if not node:
        return JSONResponse({"success": False, "msg": "not found"})
    cli = XUIClient(node["server_url"], node["srv_user"], node["srv_pass"], node.get("sub_path") or "", node.get("srv_api_token", ""))
    try:
        inbound = await cli.get_inbound(int(node["inbound_id"]))
        if not inbound:
            return JSONResponse({"success": False, "msg": f"inbound not found: {cli.last_error or 'unknown'}"})
        settings = cli._json_obj(inbound.get("settings"), {})
        protocol = inbound.get("protocol", "vless")
        for old_client in settings.get("clients", []) or []:
            old_email = str(old_client.get("email") or "")
            if old_email.startswith("atlas_sync_probe_") and old_email.rsplit("_", 1)[-1] == str(node_id):
                old_identity = cli._client_identity(protocol, old_client)
                await cli.delete_client(int(node["inbound_id"]), old_identity, old_email)
        test_uuid = str(uuid.uuid4())
        test_email = f"atlas_sync_probe_{int(time.time())}_{node_id}"
        add_ok = await cli.add_client(int(node["inbound_id"]), test_uuid, test_email, 0.1, 1)
        if add_ok:
            del_ok = await cli.delete_client(int(node["inbound_id"]), test_uuid, test_email)
            if del_ok:
                return JSONResponse({"success": True, "msg": "write test ok"})
            return JSONResponse({"success": False, "msg": f"cleanup test client failed: {cli.last_error or 'unknown'}"})
        return JSONResponse({"success": False, "msg": f"add client failed: {cli.last_error or 'unknown'}"})
    finally:
        await cli.close()


# ═══════════════════════════════ PACKAGES ═══════════════════════════


@app.post(f"/{S}/packages/add")
async def pkg_add(
    request: Request,
    name: str = Form(...),
    traffic_gb: float = Form(...),
    duration_days: int = Form(...),
    price: int = Form(...),
    description: str = Form(""),
    inbound_id: int = Form(0),
    is_unlimited: str = Form("0"),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await add_package(name, traffic_gb, duration_days, price, description, inbound_id=inbound_id,
                      is_unlimited=1 if is_unlimited == "1" else 0)
    return JSONResponse({"success": True})


@app.post(f"/{S}/packages/{{pid}}/edit")
async def pkg_edit(
    request: Request,
    pid: int,
    name: str = Form(...),
    traffic_gb: float = Form(...),
    duration_days: int = Form(...),
    price: int = Form(...),
    description: str = Form(""),
    inbound_id: int = Form(0),
    is_unlimited: str = Form("0"),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await update_package(
        pid,
        name=name,
        traffic_gb=traffic_gb,
        duration_days=duration_days,
        price=price,
        description=description,
        inbound_id=inbound_id,
        is_unlimited=1 if is_unlimited == "1" else 0,
    )
    return JSONResponse({"success": True})


@app.post(f"/{S}/packages/{{pid}}/toggle")
async def pkg_toggle(request: Request, pid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    p = await get_package(pid)
    await update_package(pid, is_active=0 if p["is_active"] else 1)
    return JSONResponse({"success": True})


@app.post(f"/{S}/packages/{{pid}}/delete")
async def pkg_delete(request: Request, pid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await delete_package(pid)
    return JSONResponse({"success": True})


@app.get(f"/{S}/api/packages")
async def api_packages(request: Request):
    """Package list for the React panel."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    pkgs = await get_packages(active_only=False)
    return JSONResponse({"packages": [{
        "id": p["id"], "name": p.get("name"),
        "traffic_gb": float(p.get("traffic_gb") or 0),
        "duration_days": int(p.get("duration_days") or 0),
        "price": int(p.get("price") or 0),
        "description": p.get("description") or "",
        "inbound_id": int(p.get("inbound_id") or 0),
        "is_active": int(p.get("is_active") or 0),
        "is_unlimited": int(p.get("is_unlimited") or 0),
    } for p in pkgs]})


# ═══════════════════════════════ DISCOUNT CODES ═════════════════════
def _date_to_ms(s: str) -> int:
    s = (s or "").strip()
    if not s:
        return 0
    try:
        return int(datetime.strptime(s, "%Y-%m-%d").replace(hour=23, minute=59, second=59).timestamp() * 1000)
    except Exception:
        return 0


def _ms_to_date(ms) -> str:
    ms = int(ms or 0)
    if ms <= 0:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")
    except Exception:
        return ""




@app.post(f"/{S}/discounts/add")
async def discount_add(
    request: Request,
    code: str = Form(...),
    kind: str = Form("percent"),
    value: float = Form(0),
    max_uses: int = Form(0),
    per_user_limit: int = Form(1),
    min_amount: int = Form(0),
    package_id: int = Form(0),
    expires: str = Form(""),
    note: str = Form(""),
    campaign: str = Form(""),
    targeted: str = Form("0"),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    code = (code or "").strip()
    if code:
        await add_discount_code(
            code, kind, value, max_uses=max_uses, per_user_limit=per_user_limit,
            min_amount=min_amount, package_id=package_id, expires_at=_date_to_ms(expires),
            note=note, campaign=(campaign or "").strip(), targeted=1 if targeted == "1" else 0,
        )
    return JSONResponse({"success": True})


@app.post(f"/{S}/discounts/{{cid}}/edit")
async def discount_edit(
    request: Request,
    cid: int,
    code: str = Form(...),
    kind: str = Form("percent"),
    value: float = Form(0),
    max_uses: int = Form(0),
    per_user_limit: int = Form(1),
    min_amount: int = Form(0),
    package_id: int = Form(0),
    expires: str = Form(""),
    note: str = Form(""),
    campaign: str = Form(""),
    targeted: str = Form("0"),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await update_discount_code(
        cid, code=(code or "").strip(),
        kind=kind if kind in ("percent", "fixed") else "percent",
        value=float(value or 0), max_uses=int(max_uses or 0),
        per_user_limit=int(per_user_limit or 0), min_amount=int(min_amount or 0),
        package_id=int(package_id or 0), expires_at=_date_to_ms(expires),
        note=(note or "").strip(), campaign=(campaign or "").strip(),
        targeted=1 if targeted == "1" else 0,
    )
    return JSONResponse({"success": True})


@app.post(f"/{S}/discounts/{{cid}}/toggle")
async def discount_toggle(request: Request, cid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    c = await get_discount_code(cid)
    if c:
        await update_discount_code(cid, is_active=0 if int(c.get("is_active") or 0) else 1)
    return JSONResponse({"success": True})


@app.post(f"/{S}/discounts/{{cid}}/delete")
async def discount_delete(request: Request, cid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await delete_discount_code(cid)
    return JSONResponse({"success": True})


@app.get(f"/{S}/api/discounts")
async def api_discounts(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    codes = await get_discount_codes()
    packages = await get_packages(active_only=False)
    return JSONResponse({
        "codes": [{
            "id": c["id"], "code": c.get("code"), "kind": c.get("kind") or "percent",
            "value": float(c.get("value") or 0), "max_uses": int(c.get("max_uses") or 0),
            "per_user_limit": int(c.get("per_user_limit") or 0), "min_amount": int(c.get("min_amount") or 0),
            "package_id": int(c.get("package_id") or 0), "used_count": int(c.get("used_count") or 0),
            "expires": _ms_to_date(c.get("expires_at")) or "", "note": c.get("note") or "",
            "campaign": c.get("campaign") or "", "targeted": int(c.get("targeted") or 0),
            "is_active": int(c.get("is_active") or 0),
        } for c in codes],
        "packages": [{"id": p["id"], "name": p.get("name")} for p in packages],
    })


# ═══════════════════════════════ CAMPAIGNS ══════════════════════════
_CAMPAIGN_LABELS = {
    "trial2paid": "تبدیل تست به خرید",
    "winback": "بازگشت مشتری",
    "referral": "معرفی دوستان",
    "renewal": "مشوق تمدید",
    "general": "عمومی",
}




@app.post(f"/{S}/campaigns/settings")
async def campaigns_settings(
    request: Request,
    campaign_trial_enabled: str = Form("0"),
    campaign_trial_code: str = Form(""),
    campaign_trial_template: str = Form(""),
    campaign_winback_enabled: str = Form("0"),
    campaign_winback_code: str = Form(""),
    campaign_winback_days: str = Form("14"),
    campaign_winback_template: str = Form(""),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await set_setting("campaign_trial_enabled", "1" if campaign_trial_enabled == "1" else "0")
    await set_setting("campaign_trial_code", (campaign_trial_code or "").strip())
    await set_setting("campaign_trial_template", campaign_trial_template or "")
    await set_setting("campaign_winback_enabled", "1" if campaign_winback_enabled == "1" else "0")
    await set_setting("campaign_winback_code", (campaign_winback_code or "").strip())
    try:
        wd = max(1, int(float(campaign_winback_days or 14)))
    except (TypeError, ValueError):
        wd = 14
    await set_setting("campaign_winback_days", str(wd))
    await set_setting("campaign_winback_template", campaign_winback_template or "")
    return JSONResponse({"success": True})


@app.post(f"/{S}/campaigns/{{name}}/run")
async def campaigns_run(request: Request, name: str):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not BOT_TOKEN or len(BOT_TOKEN) < 20:
        return JSONResponse({"error": "توکن ربات تنظیم نشده است."}, status_code=400)
    from core.campaigns import run_trial_to_paid, run_winback
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    try:
        if name == "trial2paid":
            res = await run_trial_to_paid(bot)
        elif name == "winback":
            res = await run_winback(bot)
        else:
            return JSONResponse({"error": "campaign unknown"}, status_code=400)
    finally:
        await bot.session.close()
    return JSONResponse({"success": True, "sent": res.get("sent", 0)})


@app.post(f"/{S}/campaigns/{{name}}/reset")
async def campaigns_reset(request: Request, name: str):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    cleared = await reset_campaign_flag(name)
    return JSONResponse({"success": True, "cleared": cleared})


@app.get(f"/{S}/api/campaigns")
async def api_campaigns(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    custom = await get_custom_campaigns()
    overview = await get_campaign_overview()
    custom_labels = {c["slug"]: f"{c.get('emoji') or '🎯'} {c['title']}" for c in custom}
    for c in overview:
        c["label"] = _CAMPAIGN_LABELS.get(c["campaign"]) or custom_labels.get(c["campaign"]) or c["campaign"]
    codes = [c["code"] for c in await get_discount_codes() if int(c.get("is_active") or 0)]
    kpi = {
        "revenue": sum(c["revenue"] for c in overview),
        "conversions": sum(c["conversions"] for c in overview),
        "discount": sum(c["discount"] for c in overview),
        "sent": sum(c["sent"] for c in overview),
    }
    conv_by_slug = {c["campaign"]: c for c in overview}
    for c in custom:
        perf = conv_by_slug.get(c["slug"]) or {}
        c["conversions"] = int(perf.get("conversions") or 0)
        c["revenue"] = int(perf.get("revenue") or 0)
        c["has_photo"] = bool(c.get("photo"))
        c.pop("photo", None)  # keep the list payload small; photo is write-only here
    return JSONResponse({
        "overview": overview,
        "codes": codes,
        "kpi": kpi,
        "custom": custom,
        "segments": [{"key": k, "label": v} for k, v in CUSTOM_SEGMENTS.items()],
        "segment_counts": await get_segment_counts(),
        "segment_counts_reps": await get_segment_counts(include_reps=True),
        "settings": {
            "campaign_trial_enabled": await get_setting("campaign_trial_enabled", "1"),
            "campaign_trial_code": await get_setting("campaign_trial_code", ""),
            "campaign_trial_template": await get_setting("campaign_trial_template", ""),
            "campaign_winback_enabled": await get_setting("campaign_winback_enabled", "1"),
            "campaign_winback_code": await get_setting("campaign_winback_code", ""),
            "campaign_winback_days": await get_setting("campaign_winback_days", "14"),
            "campaign_winback_template": await get_setting("campaign_winback_template", ""),
        },
    })


@app.post(f"/{S}/api/campaigns/custom")
async def api_custom_campaign_save(request: Request):
    """Create or update a targeted campaign (JSON body; photo as data-URI)."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "bad json"}, status_code=400)
    photo = str(data.get("photo") or "")
    if photo and (not photo.startswith("data:image/") or len(photo) > 3_000_000):
        return JSONResponse({"error": "عکس نامعتبر یا بزرگ‌تر از ۲ مگابایت است."}, status_code=400)
    if not str(data.get("title") or "").strip():
        return JSONResponse({"error": "عنوان کمپین لازم است."}, status_code=400)
    cid = int(data.get("id") or 0)
    if cid:
        old = await get_custom_campaign(cid)
        if not old:
            return JSONResponse({"error": "کمپین پیدا نشد."}, status_code=404)
        if "photo" not in data:  # editor didn't touch the image → keep the stored one
            data["photo"] = old.get("photo") or ""
        if "include_reps" not in data:  # older client → keep the stored setting
            data["include_reps"] = old.get("include_reps") or 0
    new_id = await save_custom_campaign(data)
    return JSONResponse({"success": True, "id": new_id})


@app.post(f"/{S}/api/campaigns/custom/{{cid}}/delete")
async def api_custom_campaign_delete(request: Request, cid: int):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await delete_custom_campaign(int(cid))
    return JSONResponse({"success": True})


@app.post(f"/{S}/api/campaigns/custom/{{cid}}/send")
async def api_custom_campaign_send(request: Request, cid: int):
    """Blast the campaign to its segment (each user receives it at most once)."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not BOT_TOKEN or len(BOT_TOKEN) < 20:
        return JSONResponse({"error": "توکن ربات تنظیم نشده است."}, status_code=400)
    camp = await get_custom_campaign(int(cid))
    if not camp:
        return JSONResponse({"error": "کمپین پیدا نشد."}, status_code=404)
    from core.campaigns import run_custom_campaign
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    try:
        res = await run_custom_campaign(bot, camp)
    finally:
        await bot.session.close()
    return JSONResponse({"success": True, **res})


# ═══════════════════════════════ MINI APP ═══════════════════════════
_miniapp_dist = os.path.join(_dir, "miniapp", "dist")
try:
    from fastapi.staticfiles import StaticFiles
    if os.path.isdir(os.path.join(_miniapp_dist, "assets")):
        app.mount("/app/assets", StaticFiles(directory=os.path.join(_miniapp_dist, "assets")), name="miniapp_assets")
except Exception as _e:  # pragma: no cover
    logger.warning("mini app static mount skipped: %s", _e)


async def _miniapp_brand() -> dict:
    title = (await get_setting("miniapp_title", "")).strip() or await get_setting("ui.brand_name", "Atlas")
    return {"title": title, "logo": (await get_setting("miniapp_logo", "🌐")).strip() or "🌐"}


# Why each mini-app rejection happened, counted since the process started.
# Customers reported an occasional "invalid access" and there was nothing in the
# log to say whether it was a stale session, a wrong token, or an attack — every
# failure returned the same silent None.
_MINIAPP_REJECTS: dict = {}


async def _miniapp_user(request: Request):
    """Validate Telegram initData and return the matching DB user (or None)."""
    from core.miniapp import check_init_data
    from core.database import get_or_create_user
    res = check_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    if not res.get("ok"):
        reason = res.get("reason") or "unknown"
        _MINIAPP_REJECTS[reason] = _MINIAPP_REJECTS.get(reason, 0) + 1
        # An expired session is the customer's client holding an old webview,
        # which is normal and self-correcting; a bad hash is not, and should be
        # loud.
        (logger.info if reason in ("expired", "no_data") else logger.warning)(
            "miniapp rejected: %s%s (seen %s times)", reason,
            f" age={res.get('age')}s limit={res.get('limit')}s" if reason == "expired" else "",
            _MINIAPP_REJECTS[reason])
        request.state.miniapp_reject = reason
        return None
    tg = res["user"]
    name = (str(tg.get("first_name", "")) + " " + str(tg.get("last_name", ""))).strip()
    return await get_or_create_user(int(tg["id"]), tg.get("username") or "", name)


@app.get("/app")
@app.get("/app/")
async def miniapp_index():
    idx = os.path.join(_miniapp_dist, "index.html")
    if not os.path.isfile(idx):
        return HTMLResponse("<h3 style='font-family:sans-serif'>Mini app not built yet.</h3>", status_code=503)
    return FileResponse(idx, media_type="text/html")


@app.post("/app/api/bootstrap")
async def miniapp_bootstrap(request: Request):
    brand = await _miniapp_brand()
    if await get_setting("miniapp_enabled", "0") != "1":
        return JSONResponse({"enabled": False, "brand": brand})
    user = await _miniapp_user(request)
    if not user:
        return JSONResponse({"error": "invalid_init_data",
                             "reason": getattr(request.state, "miniapp_reject", "")},
                            status_code=401)
    bal = await get_user_balance(user["id"])
    profiles = await get_user_subscription_profiles(user["id"])
    active = sum(1 for p in profiles if int(p.get("is_active") or 0))
    is_rep = bool(int(user.get("is_wholesale") or 0))
    rep = None
    if is_rep:
        fin = await get_rep_financials(user["id"])
        rep = {
            "brand_name": (user.get("rep_brand_name") or "").strip(),
            "has_logo": bool((user.get("rep_logo") or "").strip()),
            "financials": fin,
        }
    return JSONResponse({
        "enabled": True,
        "brand": brand,
        "user": {"name": ((user.get("full_name") or "").split(" ")[0] if user.get("full_name") else ""), "balance": bal},
        "stats": {"active_services": active, "total_services": len(profiles)},
        "is_rep": is_rep,
        "rep": rep,
        "support": (await get_setting("support_username", "")).lstrip("@"),
    })


@app.post("/app/api/services")
async def miniapp_services(request: Request):
    if await get_setting("miniapp_enabled", "0") != "1":
        return JSONResponse({"error": "disabled"}, status_code=403)
    user = await _miniapp_user(request)
    if not user:
        return JSONResponse({"error": "invalid_init_data"}, status_code=401)
    out = []
    for p in await get_user_subscription_profiles(user["id"]):
        nodes = await _get_sub_nodes(p["id"])
        try:
            sub_url = await subscription_url(p["token"])
        except Exception:
            sub_url = ""
        out.append({
            "id": p["id"], "name": p.get("name") or p.get("email"),
            "traffic_gb": p.get("traffic_gb"), "used_bytes": p.get("used_bytes"),
            "expire_ts": int(p.get("expire_timestamp") or 0), "is_active": int(p.get("is_active") or 0),
            "sub_url": sub_url,
            "email": p.get("email") or "",
            "created_at": p.get("created_at") or "",   # lets the mini-app sort by purchase time
            "nodes": [{
                "label": n.get("node_label") or n.get("server_name"),
                "is_active": int(n.get("is_active") or 0),
                "uuid": (n.get("uuid") or "").strip(),
                "link": (n.get("link") or "").strip() if int(n.get("is_active") or 0) else "",
            } for n in nodes],
        })
    return JSONResponse({"services": out})


@app.post("/app/api/packages")
async def miniapp_packages(request: Request):
    if await get_setting("miniapp_enabled", "0") != "1":
        return JSONResponse({"error": "disabled"}, status_code=403)
    user = await _miniapp_user(request)
    if not user:
        return JSONResponse({"error": "invalid_init_data"}, status_code=401)
    from core.pricing import package_price_for_user
    pkgs = await get_packages(active_only=True)
    out = []
    for p in pkgs:
        priced = await package_price_for_user(user["id"], p)
        out.append({
            "id": p["id"], "name": p["name"], "traffic_gb": p["traffic_gb"],
            "duration_days": p["duration_days"],
            "price": priced["final"],
            "base": priced["base"] if priced["final"] != priced["base"] else 0,
        })
    return JSONResponse({"packages": out})


@app.post("/app/api/wallet")
async def miniapp_wallet(request: Request):
    if await get_setting("miniapp_enabled", "0") != "1":
        return JSONResponse({"error": "disabled"}, status_code=403)
    user = await _miniapp_user(request)
    if not user:
        return JSONResponse({"error": "invalid_init_data"}, status_code=401)
    from core.database import get_wallet_transactions
    bal = await get_user_balance(user["id"])
    txs = await get_wallet_transactions(user["id"], 12)
    return JSONResponse({"balance": bal, "transactions": [{"amount": t["amount"], "kind": t["kind"], "note": t["note"]} for t in txs]})


@app.post("/app/api/referral")
async def miniapp_referral(request: Request):
    if await get_setting("miniapp_enabled", "0") != "1":
        return JSONResponse({"error": "disabled"}, status_code=403)
    user = await _miniapp_user(request)
    if not user:
        return JSONResponse({"error": "invalid_init_data"}, status_code=401)
    from core.miniapp import get_bot_username
    from core.rewards import referral_tier_reward_text
    from core.database import get_referral_earned_total, get_referral_stats, count_converted_referrals, get_referral_tiers
    uname = await get_bot_username()
    code = user.get("referral_code", "")
    link = f"https://t.me/{uname}?start={code}" if uname else ""
    brand = await get_setting("ui.brand_name", "Atlas")
    caption = (await get_setting("referral_caption", "")).replace("{brand}", brand)
    stats = await get_referral_stats(user["id"])
    converted = await count_converted_referrals(user["id"])
    tiers = await get_referral_tiers(active_only=True)
    return JSONResponse({
        "link": link,
        "earned": await get_referral_earned_total(user["id"]),
        "invited": stats["invited"], "converted": converted,
        "caption": caption.replace("{link}", link),
        "caption_no_link": caption.replace("{link}", "").strip(),
        "tiers": [{"referrals_needed": int(t["referrals_needed"]), "reward": referral_tier_reward_text(t), "reached": converted >= int(t["referrals_needed"])} for t in tiers],
    })


@app.post("/app/api/rep/purchases")
async def miniapp_rep_purchases(request: Request):
    """A representative's own purchase report, filtered by date, inside the mini app."""
    if await get_setting("miniapp_enabled", "0") != "1":
        return JSONResponse({"error": "disabled"}, status_code=403)
    user = await _miniapp_user(request)
    if not user:
        return JSONResponse({"error": "invalid_init_data"}, status_code=401)
    if not int(user.get("is_wholesale") or 0):
        return JSONResponse({"error": "not_a_representative"}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        body = {}
    report = await build_rep_report(
        user,
        preset=str(body.get("preset") or DEFAULT_REPORT_PRESET),
        date_from=str(body.get("from") or ""),
        date_to=str(body.get("to") or ""),
    )
    return JSONResponse(report)


@app.post("/app/api/rep/purchases/excel")
async def miniapp_rep_purchases_excel(request: Request):
    """Send the rep their Excel report as a Telegram document.

    Deliberately not a browser download: Telegram's in-app WebView blocks or
    silently drops blob downloads on several platforms, whereas a document sent
    to the chat arrives everywhere and stays there for the rep to re-open.
    """
    if await get_setting("miniapp_enabled", "0") != "1":
        return JSONResponse({"error": "disabled"}, status_code=403)
    user = await _miniapp_user(request)
    if not user:
        return JSONResponse({"error": "invalid_init_data"}, status_code=401)
    if not int(user.get("is_wholesale") or 0):
        return JSONResponse({"error": "not_a_representative"}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        body = {}
    report = await build_rep_report(
        user,
        preset=str(body.get("preset") or DEFAULT_REPORT_PRESET),
        date_from=str(body.get("from") or ""),
        date_to=str(body.get("to") or ""),
    )
    data = rep_report_xlsx(report)
    rng = report["range"]
    summary = report["summary"]
    caption = (
        f"📊 گزارش خرید شما\n"
        f"بازه: از {rng['from_label']} تا {rng['to_label']}\n"
        f"سرویس: {summary['services']} | تمدید: {summary['renewals']} | "
        f"مجموع: {summary['total_spent']:,} تومان"
    )
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await bot.send_document(
            int(user["telegram_id"]),
            BufferedInputFile(data, filename=rep_report_filename(report)),
            caption=caption, parse_mode=None,
        )
    except Exception as e:
        logger.warning("rep excel send failed for %s: %s", user.get("telegram_id"), e)
        return JSONResponse(
            {"error": "send_failed", "message": "ارسال فایل ناموفق بود. لطفاً ابتدا ربات را استارت کنید."},
            status_code=502,
        )
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass
    return JSONResponse({"success": True, "rows": len(report["rows"])})


async def _miniapp_jitter(base: int) -> int:
    """Same tiny unique-amount jitter the bot applies (for card-receipt matching)."""
    base = int(base or 0)
    if base <= 0 or await get_setting("random_price_enabled", "1") != "1":
        return base
    try:
        max_off = max(0, int(await get_setting("random_price_max", "990") or 990))
    except (TypeError, ValueError):
        max_off = 990
    if max_off < 10:
        return base
    import random as _rnd
    return base + _rnd.randint(1, max_off // 10) * 10


async def _miniapp_card() -> dict:
    from core.config import CARD_NUMBER, CARD_HOLDER, CARD_BANK
    return {
        "card": await get_setting("card_number", CARD_NUMBER),
        "holder": await get_setting("card_holder", CARD_HOLDER),
        "bank": await get_setting("card_bank", CARD_BANK),
    }


async def _miniapp_price(user: dict, pkg: dict, code: str) -> dict:
    """Final price = base (user per-GB / unlimited / package) − user% − code, then jitter."""
    from core.database import validate_discount_code
    from core.pricing import package_price_for_user
    final = (await package_price_for_user(user["id"], pkg))["final"]
    code = (code or "").strip()
    code_amount = 0
    applied = ""
    if code:
        v = await validate_discount_code(code, user["id"], int(pkg["id"]), final)
        if not v.get("ok"):
            return {"error": v.get("error") or "code_invalid"}
        code_amount = int(v["discount_amount"])
        applied = v["code"]
    net = await _miniapp_jitter(max(0, final - code_amount))
    return {"base": final, "code": applied, "code_amount": code_amount, "net": net}


@app.post("/app/api/buy")
async def miniapp_buy(request: Request):
    if await get_setting("miniapp_enabled", "0") != "1":
        return JSONResponse({"error": "disabled"}, status_code=403)
    user = await _miniapp_user(request)
    if not user:
        return JSONResponse({"error": "invalid_init_data"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    pid = int(body.get("package_id") or 0)
    pkg = await get_package(pid)
    if not pkg or not int(pkg.get("is_active") or 0):
        return JSONResponse({"error": "package_unavailable"}, status_code=400)
    from core.database import create_order, update_order
    name = re.sub(r"[^A-Za-z0-9_-]+", "", str(body.get("name") or "").strip())[:24]
    priced = await _miniapp_price(user, pkg, str(body.get("discount_code") or ""))
    if priced.get("error"):
        return JSONResponse({"error": priced["error"], "code_error": True}, status_code=400)
    oid = await create_order(user["id"], pid, custom_config_name=name, custom_price=priced["net"])
    if priced["code"] and priced["code_amount"] > 0:
        await update_order(oid, discount_code=priced["code"], discount_amount=priced["code_amount"])
    return JSONResponse({
        "ok": True, "order_id": oid,
        "payment": {"amount": priced["net"], "base": priced["base"],
                    "code_amount": priced["code_amount"], **await _miniapp_card()},
    })


@app.post("/app/api/wallet/topup")
async def miniapp_wallet_topup(request: Request):
    if await get_setting("miniapp_enabled", "0") != "1":
        return JSONResponse({"error": "disabled"}, status_code=403)
    user = await _miniapp_user(request)
    if not user:
        return JSONResponse({"error": "invalid_init_data"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    amount = int(float(body.get("amount") or 0))
    if amount < 1000:
        return JSONResponse({"error": "amount_too_small"}, status_code=400)
    amount = await _miniapp_jitter(amount)
    return JSONResponse({"ok": True, "amount": amount, **await _miniapp_card()})


@app.post("/app/api/services/rename")
async def miniapp_service_rename(request: Request):
    if await get_setting("miniapp_enabled", "0") != "1":
        return JSONResponse({"error": "disabled"}, status_code=403)
    user = await _miniapp_user(request)
    if not user:
        return JSONResponse({"error": "invalid_init_data"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    from core.database import get_subscription_profile, update_subscription_profile
    profile = await get_subscription_profile(int(body.get("profile_id") or 0))
    if not profile or int(profile.get("user_id") or 0) != int(user["id"]):
        return JSONResponse({"error": "not_your_service"}, status_code=403)
    name = re.sub(r"[^\w \-]+", "", str(body.get("name") or ""), flags=re.UNICODE).strip()[:40]
    await update_subscription_profile(int(profile["id"]), name=name)
    return JSONResponse({"ok": True, "name": name})


@app.post("/app/api/services/connections")
async def miniapp_service_connections(request: Request):
    """"How many devices are on my service right now" — the mini-app's version.

    Same answer, same masking and the same shared fleet snapshot as the bot
    button, so the two can never disagree in front of the same customer.
    """
    if await get_setting("miniapp_enabled", "0") != "1":
        return JSONResponse({"error": "disabled"}, status_code=403)
    user = await _miniapp_user(request)
    if not user:
        return JSONResponse({"error": "invalid_init_data"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    from core.database import get_subscription_profile
    profile = await get_subscription_profile(int(body.get("profile_id") or 0))
    if not profile or int(profile.get("user_id") or 0) != int(user["id"]):
        return JSONResponse({"error": "not_your_service"}, status_code=403)
    from core.ip_guard import live_connections
    try:
        live = await live_connections(int(profile["id"]), confirm=True, reveal=False)
    except Exception as e:
        logger.warning("miniapp connections failed: %s", e)
        return JSONResponse({"ok": False}, status_code=502)
    return JSONResponse(live)


@app.post("/app/api/services/renew")
async def miniapp_service_renew(request: Request):
    if await get_setting("miniapp_enabled", "0") != "1":
        return JSONResponse({"error": "disabled"}, status_code=403)
    user = await _miniapp_user(request)
    if not user:
        return JSONResponse({"error": "invalid_init_data"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    from core.database import get_subscription_profile, create_custom_order, update_order, get_package
    from core.pricing import package_price_for_user
    profile = await get_subscription_profile(int(body.get("profile_id") or 0))
    if not profile or int(profile.get("user_id") or 0) != int(user["id"]):
        return JSONResponse({"error": "not_your_service"}, status_code=403)
    pkg = await get_package(int(body.get("package_id") or 0))
    if not pkg or not int(pkg.get("is_active") or 0):
        return JSONResponse({"error": "package_unavailable"}, status_code=400)
    # Renewal follows our plans, not the service's current volume.
    traffic_gb = float(pkg.get("traffic_gb") or 0)
    duration = int(pkg.get("duration_days") or 0)
    price = await _miniapp_jitter((await package_price_for_user(user["id"], pkg))["final"])
    oid = await create_custom_order(user["id"], f"تمدید {profile.get('name') or profile['id']}",
                                    traffic_gb, duration, price, notes=f"renew_sub:{profile['id']};plan:{pkg['id']}",
                                    package_id=int(pkg["id"]))
    await update_order(oid, renew_sub_profile_id=int(profile["id"]))
    return JSONResponse({"ok": True, "order_id": oid, "payment": {"amount": price, **await _miniapp_card()}})


@app.post("/app/api/wallet/pay")
async def miniapp_wallet_pay(request: Request):
    """Pay a pending order (new purchase OR renewal) from the wallet balance and
    fulfil it instantly. Mirrors the bot's `pay_wallet` flow."""
    if await get_setting("miniapp_enabled", "0") != "1":
        return JSONResponse({"error": "disabled"}, status_code=403)
    user = await _miniapp_user(request)
    if not user:
        return JSONResponse({"error": "invalid_init_data"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    from core.database import get_order, update_order
    oid = int(body.get("order_id") or 0)
    order = await get_order(oid)
    if not order or int(order.get("user_id") or 0) != int(user["id"]):
        return JSONResponse({"error": "not_your_order"}, status_code=403)
    if str(order.get("status")) not in ("pending_payment", "pending_receipt"):
        return JSONResponse({"error": "not_payable"}, status_code=400)

    # Wallet charges the FIXED clean price (base_price), not the jittered card amount.
    price = int(order.get("base_price") or 0) or int(order.get("price") or 0)
    balance = await get_user_balance(user["id"])
    if balance < price:
        return JSONResponse({"error": "insufficient_balance", "balance": balance, "price": price}, status_code=400)

    await add_user_balance(user["id"], -price, kind="purchase", note=f"order:{oid}", actor_telegram_id=int(user.get("telegram_id") or 0))
    await update_order(oid, status="receipt_submitted", notes=((order.get("notes") or "") + "\nwallet_payment=1;source=miniapp").strip())

    try:
        result = await _fulfill_order(oid)
    except Exception as e:
        logger.exception("miniapp wallet fulfilment failed oid=%s: %s", oid, e)
        result = {"ok": False, "error": "exception"}

    if not result.get("ok"):
        await add_user_balance(user["id"], price, kind="refund", note=f"order_failed:{oid}", actor_telegram_id=0)
        await update_order(oid, status="pending_payment")
        return JSONResponse({"error": "fulfilment_failed"}, status_code=502)

    await _notify_admins_wallet_purchase(user, order, price)
    return JSONResponse({"ok": True, "order_id": oid, "balance": await get_user_balance(user["id"])})


async def _notify_admins_wallet_purchase(user: dict, order: dict, price: int):
    if not BOT_TOKEN or len(BOT_TOKEN) < 20:
        return
    from core.database import get_all_admin_telegram_ids
    try:
        bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
        admin_targets = list(dict.fromkeys(list(ADMIN_IDS) + await get_all_admin_telegram_ids()))
        text = (
            "💳 خرید با کیف پول (مینی‌اپ)\n\n"
            f"کاربر: {user.get('full_name') or '-'} (@{user.get('username') or '-'})\n"
            f"Telegram ID: {user.get('telegram_id')}\n"
            f"سفارش: #{order['id']} | {order.get('pkg_name') or order.get('custom_name') or '-'}\n"
            f"مبلغ: {price:,} تومان"
        )
        try:
            for aid in admin_targets:
                try:
                    await bot.send_message(aid, text, parse_mode=None)
                except Exception:
                    pass
        finally:
            await bot.session.close()
    except Exception as e:
        logger.warning("wallet purchase admin notify failed: %s", e)


@app.post("/app/api/receipt")
async def miniapp_receipt(
    request: Request,
    photo: UploadFile = File(...),
    kind: str = Form("order"),
    id: int = Form(0),
    amount: int = Form(0),
):
    if await get_setting("miniapp_enabled", "0") != "1":
        return JSONResponse({"error": "disabled"}, status_code=403)
    user = await _miniapp_user(request)
    if not user:
        return JSONResponse({"error": "invalid_init_data"}, status_code=401)
    if not BOT_TOKEN or len(BOT_TOKEN) < 20:
        return JSONResponse({"error": "bot_unavailable"}, status_code=503)
    data = await photo.read()
    if not data or len(data) > 6 * 1024 * 1024:
        return JSONResponse({"error": "bad_image"}, status_code=400)
    if data[:3] != b"\xff\xd8\xff" and data[:8] != b"\x89PNG\r\n\x1a\n":
        return JSONResponse({"error": "not_an_image"}, status_code=400)

    from core.database import (get_order, update_order, add_review_message,
                               get_all_admin_telegram_ids, create_topup_request)
    from bot.keyboards import order_review_kb, topup_review_kb
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    admin_targets = list(dict.fromkeys(list(ADMIN_IDS) + await get_all_admin_telegram_ids()))
    uname = user.get("username") or "—"
    fname = user.get("full_name") or "کاربر"
    try:
        if kind == "order":
            order = await get_order(int(id))
            if not order or int(order.get("user_id") or 0) != int(user["id"]):
                return JSONResponse({"error": "not_your_order"}, status_code=403)
            file_id = ""
            caption = (f"🧾 فیش جدید (مینی‌اپ)\nسفارش: #{order['id']}\n{fname} (@{uname})\n"
                       f"{order.get('pkg_name') or '-'}\n{int(order.get('price') or 0):,} تومان")
            for aid in admin_targets:
                try:
                    sent = await bot.send_photo(aid, BufferedInputFile(data, "receipt.jpg"), caption=caption,
                                                reply_markup=order_review_kb(int(order["id"])), parse_mode=None)
                    file_id = file_id or (sent.photo[-1].file_id if sent.photo else "")
                    await add_review_message("order", int(order["id"]), sent.chat.id, sent.message_id)
                except Exception:
                    pass
            await update_order(int(order["id"]), status="receipt_submitted", receipt_file_id=file_id)
            return JSONResponse({"ok": True})
        elif kind == "topup":
            amt = int(amount or 0)
            if amt < 1000:
                return JSONResponse({"error": "amount_too_small"}, status_code=400)
            file_id = ""
            for aid in admin_targets:  # first send gives us a reusable file_id
                try:
                    tmp = await bot.send_photo(aid, BufferedInputFile(data, "topup.jpg"),
                                               caption="در حال ثبت…", parse_mode=None)
                    file_id = tmp.photo[-1].file_id if tmp.photo else ""
                    try:
                        await bot.delete_message(aid, tmp.message_id)
                    except Exception:
                        pass
                    break
                except Exception:
                    continue
            req_id = await create_topup_request(int(user["id"]), amt, file_id)
            caption = (f"💳 درخواست شارژ کیف پول (مینی‌اپ)\n#Topup_{req_id}\n{fname} (@{uname})\n"
                       f"🆔 {user.get('telegram_id')}\nمبلغ: {amt:,} تومان")
            for aid in admin_targets:
                try:
                    if file_id:
                        sent = await bot.send_photo(aid, file_id, caption=caption,
                                                    reply_markup=topup_review_kb(req_id), parse_mode=None)
                    else:
                        sent = await bot.send_message(aid, caption, reply_markup=topup_review_kb(req_id), parse_mode=None)
                    await add_review_message("topup", req_id, sent.chat.id, sent.message_id)
                except Exception:
                    pass
            return JSONResponse({"ok": True})
        return JSONResponse({"error": "bad_kind"}, status_code=400)
    finally:
        await bot.session.close()


# ── Mini App management (admin-only, behind the secret path) ──
@app.get(f"/{S}/api/miniapp")
async def api_miniapp(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    domain = await get_setting("miniapp_domain", "")
    return JSONResponse({
        "settings": {
            "miniapp_enabled": await get_setting("miniapp_enabled", "0"),
            "miniapp_title": await get_setting("miniapp_title", ""),
            "miniapp_logo": await get_setting("miniapp_logo", "🌐"),
            "miniapp_domain": domain,
            "cert_email": await get_setting("cert_email", ""),
        },
        # Without a build there is nothing to serve at /app, so the panel has to
        # say so rather than hand out a link that renders "not built yet".
        "built": os.path.isfile(os.path.join(_miniapp_dist, "index.html")),
        "app_url": f"https://{domain}/app" if domain else "",
    })


@app.post(f"/{S}/miniapp/settings")
async def miniapp_admin_settings(
    request: Request,
    miniapp_enabled: str = Form("0"),
    miniapp_title: str = Form(""),
    miniapp_logo: str = Form("🌐"),
    miniapp_domain: str = Form(""),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await set_setting("miniapp_enabled", "1" if miniapp_enabled == "1" else "0")
    await set_setting("miniapp_title", (miniapp_title or "").strip())
    await set_setting("miniapp_logo", (miniapp_logo or "🌐").strip() or "🌐")
    await set_setting("miniapp_domain", _clean_domain(miniapp_domain))
    return JSONResponse({"success": True})


@app.post(f"/{S}/miniapp/cert/start")
async def miniapp_cert_start(request: Request):
    """Issue an SSL cert + nginx vhost for the mini-app's OWN domain on 443,
    proxying to this same app (so https://<domain>/app serves the mini app)."""
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    form = await request.form()
    domain = _clean_domain(str(form.get("miniapp_domain") or await get_setting("miniapp_domain", "")))
    email = str(form.get("cert_email") or await get_setting("cert_email", "")).strip().lower()
    if not domain:
        return JSONResponse({"error": "دامنهٔ مینی‌اپ معتبر نیست. مثال: app.example.com"}, status_code=400)
    if _read_job_log("miniapp_cert").get("running"):
        return JSONResponse({"error": "یک عملیات گواهی مینی‌اپ در حال اجراست. صبر کنید."}, status_code=409)
    await set_setting("miniapp_domain", domain)
    if email:
        await set_setting("cert_email", email)
    script = _atlas_tls_proxy_script(domain, email, WEB_PORT, 443)
    _asyncio.create_task(_run_logged_job("miniapp_cert", script))
    return JSONResponse({"success": True, "domain": domain, "app_url": f"https://{domain}/app"})


@app.get(f"/{S}/miniapp/cert/log")
async def miniapp_cert_log(request: Request):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    data = _read_job_log("miniapp_cert")
    if data.get("status") == "ok":
        domain = _clean_domain(await get_setting("miniapp_domain", ""))
        data["app_url"] = f"https://{domain}/app" if domain else ""
    return JSONResponse(data)


# ═══════════════════════════════ REFERRALS ══════════════════════════


@app.post(f"/{S}/referrals/claims/{{cid}}/approve")
async def referral_claim_approve_web(request: Request, cid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.rewards import grant_referral_claim
    rbot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)) if (BOT_TOKEN and len(BOT_TOKEN) > 20) else None
    try:
        res = await grant_referral_claim(cid, bot=rbot, reviewer_id=0)
    finally:
        if rbot:
            await rbot.session.close()
    return JSONResponse({"success": bool(res.get("ok")), **res})


@app.post(f"/{S}/referrals/claims/{{cid}}/reject")
async def referral_claim_reject_web(request: Request, cid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.rewards import reject_referral_claim
    res = await reject_referral_claim(cid)
    return JSONResponse({"success": bool(res.get("ok")), **res})


@app.post(f"/{S}/referrals/settings")
async def referrals_settings(
    request: Request,
    referral_enabled: str = Form("1"),
    referral_per_referral_amount: str = Form("0"),
    referral_caption: str = Form(""),
    referral_reminder_enabled: str = Form("0"),
    referral_reminder_code: str = Form(""),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await set_setting("referral_enabled", "1" if referral_enabled == "1" else "0")
    try:
        amount = max(0, int(float(referral_per_referral_amount or 0)))
    except (TypeError, ValueError):
        amount = 0
    await set_setting("referral_per_referral_amount", str(amount))
    await set_setting("referral_per_referral_gb", "0")  # wallet model supersedes GB
    await set_setting("referral_caption", referral_caption or "")
    await set_setting("referral_reminder_enabled", "1" if referral_reminder_enabled == "1" else "0")
    await set_setting("referral_reminder_code", (referral_reminder_code or "").strip())
    return JSONResponse({"success": True})


@app.post(f"/{S}/referrals/tiers/add")
async def referral_tier_add(
    request: Request,
    referrals_needed: int = Form(...),
    reward_kind: str = Form("wallet"),
    reward_amount: int = Form(0),
    reward_gb: float = Form(0),
    duration_days: int = Form(0),
    is_unlimited: str = Form("0"),
    label: str = Form(""),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await add_referral_tier(
        referrals_needed, reward_kind, reward_gb=reward_gb, duration_days=duration_days,
        is_unlimited=1 if is_unlimited == "1" else 0, label=label, reward_amount=reward_amount,
    )
    return JSONResponse({"success": True})


@app.post(f"/{S}/referrals/tiers/{{tid}}/edit")
async def referral_tier_edit(
    request: Request,
    tid: int,
    referrals_needed: int = Form(...),
    reward_kind: str = Form("wallet"),
    reward_amount: int = Form(0),
    reward_gb: float = Form(0),
    duration_days: int = Form(0),
    is_unlimited: str = Form("0"),
    label: str = Form(""),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await update_referral_tier(
        tid, referrals_needed=int(referrals_needed or 0),
        reward_kind=reward_kind if reward_kind in ("wallet", "gb", "service") else "wallet",
        reward_amount=int(reward_amount or 0),
        reward_gb=float(reward_gb or 0), duration_days=int(duration_days or 0),
        is_unlimited=1 if is_unlimited == "1" else 0, label=(label or "").strip(),
    )
    return JSONResponse({"success": True})


@app.post(f"/{S}/referrals/tiers/{{tid}}/toggle")
async def referral_tier_toggle(request: Request, tid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    t = await get_referral_tier(tid)
    if t:
        await update_referral_tier(tid, is_active=0 if int(t.get("is_active") or 0) else 1)
    return JSONResponse({"success": True})


@app.post(f"/{S}/referrals/tiers/{{tid}}/delete")
async def referral_tier_delete(request: Request, tid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await delete_referral_tier(tid)
    return JSONResponse({"success": True})


@app.get(f"/{S}/api/referrals")
async def api_referrals(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.database import get_pending_referral_claims
    from core.rewards import referral_tier_reward_text
    tiers = await get_referral_tiers(active_only=False)
    pending = await get_pending_referral_claims(50)
    codes = [c["code"] for c in await get_discount_codes() if int(c.get("is_active") or 0)]
    banner_file_id = await get_setting("referral_banner_file_id", "")
    banner_url = await get_setting("referral_banner_url", "")
    return JSONResponse({
        "settings": {
            "referral_enabled": await get_setting("referral_enabled", "1"),
            "referral_per_referral_amount": await get_setting("referral_per_referral_amount", "0"),
            "referral_caption": await get_setting("referral_caption", ""),
            "referral_reminder_enabled": await get_setting("referral_reminder_enabled", "1"),
            "referral_reminder_code": await get_setting("referral_reminder_code", ""),
        },
        "tiers": [{
            "id": t["id"], "referrals_needed": int(t.get("referrals_needed") or 0),
            "reward_kind": t.get("reward_kind") or "wallet", "reward_amount": int(t.get("reward_amount") or 0),
            "reward_gb": float(t.get("reward_gb") or 0), "duration_days": int(t.get("duration_days") or 0),
            "is_unlimited": int(t.get("is_unlimited") or 0), "label": t.get("label") or "",
            "is_active": int(t.get("is_active") or 0),
        } for t in tiers],
        "claims": [{
            "id": cl["id"], "telegram_id": cl.get("telegram_id"), "full_name": cl.get("full_name"),
            "username": cl.get("username"), "reward_text": referral_tier_reward_text(cl),
        } for cl in pending],
        "codes": codes,
        "banner_set": bool((banner_file_id or "").strip() or (banner_url or "").strip()),
    })


@app.post(f"/{S}/referrals/banner")
async def referral_banner_upload(request: Request, banner: UploadFile = File(...)):
    """Upload a banner: push it to Telegram once to obtain a reusable file_id,
    then keep ONLY the file_id (the bytes never touch local disk)."""
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not BOT_TOKEN or len(BOT_TOKEN) < 20:
        return JSONResponse({"error": "توکن ربات تنظیم نشده است."}, status_code=400)
    data = await banner.read()
    if not data:
        return JSONResponse({"error": "فایل خالی است."}, status_code=400)
    owner = int(await get_setting("owner_admin_id", "0") or 0)
    targets = list(dict.fromkeys(([owner] if owner else []) + list(ADMIN_IDS)))
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    file_id = ""
    try:
        for chat_id in targets:
            if not chat_id:
                continue
            try:
                m = await bot.send_photo(
                    chat_id,
                    BufferedInputFile(data, filename="referral-banner.jpg"),
                    caption="🖼 بنر معرفی ذخیره شد (این پیام را می‌توانید پاک کنید).",
                    parse_mode=None,
                )
                if m.photo:
                    file_id = m.photo[-1].file_id
                    break
            except Exception as e:
                logger.warning("banner upload to %s failed: %s", chat_id, e)
                continue
    finally:
        await bot.session.close()
    if not file_id:
        return JSONResponse({"error": "ارسال بنر به تلگرام ناموفق بود."}, status_code=502)
    await set_setting("referral_banner_file_id", file_id)
    await set_setting("referral_banner_url", "")
    return JSONResponse({"success": True})


@app.get(f"/{S}/referrals/banner/preview")
async def referral_banner_preview(request: Request):
    """Stream the saved banner straight from Telegram (no local copy kept)."""
    if not _auth(request):
        return _redir_login()
    fid = (await get_setting("referral_banner_file_id", "")).strip()
    url = (await get_setting("referral_banner_url", "")).strip()
    if not fid and url:
        return RedirectResponse(url, status_code=302)
    if not fid or not BOT_TOKEN or len(BOT_TOKEN) < 20:
        return StreamingResponse(iter([b""]), media_type="image/png", status_code=404)
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    try:
        f = await bot.get_file(fid)
        buf = await bot.download_file(f.file_path)
        data = buf.read() if hasattr(buf, "read") else bytes(buf)
    except Exception as e:
        logger.warning("banner preview fetch failed: %s", e)
        data = b""
    finally:
        await bot.session.close()
    if not data:
        return StreamingResponse(iter([b""]), media_type="image/png", status_code=404)
    return StreamingResponse(iter([data]), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post(f"/{S}/referrals/banner/clear")
async def referral_banner_clear(request: Request):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await set_setting("referral_banner_file_id", "")
    await set_setting("referral_banner_url", "")
    return JSONResponse({"success": True})


# ═══════════════════════════════ ORDERS ═════════════════════════════


@app.post(f"/{S}/orders/{{oid}}/reject")
async def order_reject_web(request: Request, oid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    order = await get_order(oid)
    if not order:
        return JSONResponse({"error": "سفارش پیدا نشد."}, status_code=404)
    await update_order(oid, status="rejected")
    await _clear_review_buttons("order", oid)
    return JSONResponse({"success": True})


@app.post(f"/{S}/orders/{{oid}}/approve")
async def order_approve_web(request: Request, oid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        await _fulfill_order(oid)
    except Exception as e:
        logger.exception("order approve failed oid=%s: %s", oid, e)
        await release_order_processing(oid)
    return JSONResponse({"success": True})


async def _fulfill_order(oid: int, order: dict | None = None) -> dict:
    """Shared fulfilment for a *paid* order — used by both admin receipt
    approval and instant wallet payment. Performs the renew/create and notifies
    the user. Returns ``{"ok": bool, "error": str}``; on failure the order is
    left in ``receipt_submitted`` so it can be retried/refunded by the caller."""
    if order is None:
        order = await get_order(oid)
    if not order:
        return {"ok": False, "error": "order_missing"}
    if order.get("status") == "approved":
        return {"ok": True}
    if order.get("status") not in ("receipt_submitted", "processing"):
        return {"ok": False, "error": "bad_status"}
    if not await claim_order_for_approval(oid):
        return {"ok": False, "error": "claim_failed"}

    if int(order.get("renew_config_id") or 0) > 0:
        cfg = await get_config(int(order["renew_config_id"]))
        if not cfg:
            await update_order(oid, status="receipt_submitted")
            return {"ok": False, "error": "config_missing"}

        # Trust the order's plan values (0 = unlimited); don't fall back to the
        # config's old volume/duration or an unlimited renewal would be lost.
        duration = int(order.get("duration_days") or 0)
        traffic_gb = float(order.get("traffic_gb") or 0)
        result = await find_and_renew_config(cfg, traffic_gb, duration)
        if not result.get("ok"):
            await update_order(oid, status="receipt_submitted")
            return {"ok": False, "error": "renew_failed"}

        server = result["server"]
        link = result.get("link")
        sub = result.get("sub")
        await update_order(
            oid,
            status="approved",
            server_id=server["id"],
            config_email=cfg["email"],
            inbound_id=result.get("inbound_id") or cfg["inbound_id"],
            approved_at=datetime.now().isoformat(),
        )
        await _clear_review_buttons("order", oid)
        if BOT_TOKEN and len(BOT_TOKEN) > 20:
            bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
            try:
                text = f"✅ سرویس شما تمدید شد.\n\nکانفیگ: {cfg['email']}\nسرور: {server['name']}\nحجم: {traffic_gb} GB\nمدت تمدید: {duration} روز\n"
                if link:
                    text += f"\nلینک اتصال:\n{link}\n"
                if sub:
                    text += f"\nلینک سابسکریپشن:\n{sub}\n"
                await bot.send_message(order["telegram_id"], text, parse_mode=None, reply_markup=config_links_kb(link or "", sub or ""))
                if link:
                    try:
                        qr = build_qr_image(link, footer_text=await get_setting("channel_username", "AtlasChannel"))
                        await bot.send_photo(
                            order["telegram_id"],
                            BufferedInputFile(qr.getvalue(), filename="atlas-qr.png"),
                            caption=f"QR: {cfg['email']}",
                            parse_mode=None,
                        )
                    except Exception:
                        pass
            finally:
                await bot.session.close()
        return {"ok": True}

    if int(order.get("renew_sub_profile_id") or 0) > 0:
        profile = await get_subscription_profile(int(order["renew_sub_profile_id"]))
        if not profile:
            await update_order(oid, status="receipt_submitted")
            return {"ok": False, "error": "profile_missing"}
        # Trust the order's plan values (0 = unlimited) rather than the sub's old ones.
        duration = int(order.get("duration_days") or 0)
        traffic_gb = float(order.get("traffic_gb") or 0)
        result = await renew_subscription_profile(profile, traffic_gb, duration)
        if not result.get("ok"):
            await update_order(oid, status="receipt_submitted", notes=((order.get("notes") or "") + f"\nsub_renew_error={result.get('error') or ''}").strip())
            return {"ok": False, "error": "sub_renew_failed"}
        sub_url = await subscription_url(profile["token"])
        await update_order(
            oid,
            status="approved",
            server_id=0,
            config_email=profile.get("email") or f"sub:{profile['id']}",
            inbound_id=0,
            approved_at=datetime.now().isoformat(),
        )
        await _clear_review_buttons("order", oid)
        if BOT_TOKEN and len(BOT_TOKEN) > 20:
            bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
            try:
                await bot.send_message(
                    order["telegram_id"],
                    "✅ سابسکریپشن شما تمدید شد.\n\n"
                    f"حجم جدید: {traffic_gb} GB\n"
                    f"مدت تمدید: {duration} روز\n"
                    f"نودهای تمدیدشده: {result.get('nodes', 0)}\n\n"
                    f"لینک ساب:\n{sub_url}",
                    parse_mode=None,
                    reply_markup=config_links_kb("", sub_url),
                )
            finally:
                await bot.session.close()
        return {"ok": True}

    user = await get_user_by_telegram(order["telegram_id"])
    if not user:
        await update_order(oid, status="receipt_submitted")
        return {"ok": False, "error": "no_user"}

    bulk_count = int(order.get("bulk_count") or 1)
    each_gb = float(order.get("bulk_each_gb") or order["traffic_gb"])
    duration = int(order["duration_days"])
    # Subscriptions are the only fulfilment model now (single-server retired).
    # Bulk/reseller orders create one multi-server subscription per unit.
    units = max(1, bulk_count)
    bonus_gb = 0.0
    if not int(order.get("referral_bonus_applied") or 0):
        bonus_gb = max(0.0, float(user.get("referral_bonus_gb") or 0))

    created_subs = []
    last_error = ""
    for idx in range(units):
        unit_gb = each_gb + bonus_gb if (idx == 0 and bonus_gb > 0) else each_gb
        sub_result = await create_profile_for_order(user, order, unit_gb, duration)
        if sub_result.get("ok"):
            created_subs.append(sub_result)
        else:
            last_error = sub_result.get("error", "")
            break

    if not created_subs:
        notes = ((order.get("notes") or "") + f"\nsub_create_error={last_error}").strip()
        await update_order(oid, status="receipt_submitted", notes=notes)
        logger.warning("Subscription creation failed for order %s: %s", oid, subscription_error_message(last_error))
        return {"ok": False, "error": "create_failed"}

    # Capture BEFORE flipping to approved so "first purchase" is accurate.
    first_purchase = not await has_previous_purchase(user["id"])
    await update_order(
        oid,
        status="approved",
        server_id=0,
        config_email=created_subs[0]["email"],
        inbound_id=0,
        approved_at=datetime.now().isoformat(),
    )
    if bonus_gb > 0:
        await update_user(user["id"], referral_bonus_gb=0)
        await update_order(oid, referral_bonus_applied=1)
    await _clear_review_buttons("order", oid)
    reward_bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)) if (BOT_TOKEN and len(BOT_TOKEN) > 20) else None
    # Discount redemption + referral incentives (per-referral GB + milestone tiers).
    from core.rewards import apply_post_approval_rewards
    await apply_post_approval_rewards(reward_bot, user, order, first_purchase)
    if reward_bot:
        bot = reward_bot
        try:
            head = (
                "🎉 سرویس شما فعال شد!\n\n"
                f"سفارش: {order.get('pkg_name') or '—'}\n"
                f"تعداد سابسکریپشن: {len(created_subs)}\n"
                f"حجم هر سرویس: {each_gb} GB\n"
                f"مدت: {duration} روز"
            )
            if bonus_gb > 0:
                head += f"\n🎁 هدیه رفرال: {bonus_gb:g} GB روی سرویس اول"
            await bot.send_message(order["telegram_id"], head, parse_mode=None)
            for item in created_subs[:20]:
                sub_url = item["url"]
                await bot.send_message(
                    order["telegram_id"],
                    f"📡 لینک سابسکریپشن ({item.get('nodes', 0)} سرور):\n{sub_url}",
                    parse_mode=None,
                    reply_markup=config_links_kb("", sub_url),
                )
                try:
                    qr = build_qr_image(sub_url, footer_text=item.get("email") or "Subscription")
                    await bot.send_photo(order["telegram_id"], BufferedInputFile(qr.getvalue(), filename="atlas-sub.png"), caption="QR سابسکریپشن", parse_mode=None)
                except Exception:
                    pass
        finally:
            await bot.session.close()
    return {"ok": True}


# ═══════════════════════════════ CONFIGS ════════════════════════════
@app.get(f"/{S}/api/configs")
async def api_configs(request: Request):
    """Legacy single-server configs, grouped by their base email.

    A config that has been migrated between servers keeps a row per move
    (`{email}_m2`, `_m3`…). Listing those raw would show one customer three
    times, so they collapse into one entry carrying the move history, and the
    ACTIVE row wins as the representative one.
    """
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    page = max(1, int(request.query_params.get("page", "1") or 1))
    per_page = 30
    q = (request.query_params.get("q") or "").strip().lower()

    grouped: dict = {}
    for c in await get_all_configs():
        base = (c.get("email") or "").split("_m")[0]
        g = grouped.setdefault(base, {**c, "history_count": 0, "history_servers": []})
        g["history_count"] += 1
        if c.get("server_name") and c["server_name"] not in g["history_servers"]:
            g["history_servers"].append(c["server_name"])
        if c.get("is_active") and not g.get("is_active"):
            g.update(c)
    rows = list(grouped.values())
    if q:
        rows = [c for c in rows
                if q in str(c.get("email") or "").lower()
                or q in str(c.get("full_name") or "").lower()
                or q in str(c.get("username") or "").lower()
                or q in str(c.get("telegram_id") or "")]

    total = len(rows)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    window = rows[(page - 1) * per_page: page * per_page]
    return JSONResponse({
        "configs": [{
            "id": int(c["id"]),
            "email": c.get("email") or "",
            "user_id": int(c.get("user_id") or 0),
            "telegram_id": int(c.get("telegram_id") or 0),
            "full_name": c.get("full_name") or "",
            "username": c.get("username") or "",
            "server_name": c.get("server_name") or "",
            "traffic_gb": float(c.get("traffic_gb") or 0),
            "expire_timestamp": int(c.get("expire_timestamp") or 0),
            "is_active": int(c.get("is_active") or 0),
            "created_at": c.get("created_at") or "",
            "history_count": int(c.get("history_count") or 0),
            "history_servers": c.get("history_servers") or [],
        } for c in window],
        "total": total, "page": page, "total_pages": total_pages,
    })


@app.post(f"/{S}/configs/{{cid}}/toggle")
async def config_toggle(request: Request, cid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    cfg = await get_config(cid)
    if not cfg:
        return JSONResponse({"error": "not found"}, status_code=404)
    srv = await get_server(cfg["server_id"])
    cli = XUIClient(srv["url"], srv["username"], srv["password"], srv["sub_path"], srv.get("api_token", ""))
    new_status = not cfg["is_active"]
    ok = await cli.update_client(
        cfg["inbound_id"],
        cfg["uuid"],
        cfg["email"],
        cfg["traffic_gb"],
        cfg["expire_timestamp"] or 0,
        new_status,
    )
    await cli.close()
    if ok:
        await update_config(cid, is_active=1 if new_status else 0)
    return JSONResponse({"success": ok})


@app.post(f"/{S}/configs/{{cid}}/delete")
async def config_delete(request: Request, cid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    cfg = await get_config(cid)
    if not cfg:
        return JSONResponse({"success": False, "error": "not found"}, status_code=404)

    base_email = (cfg.get("email") or "").split("_m")[0]
    rows = await get_configs_by_base_email(base_email)

    deleted_remote = 0
    for item in rows:
        try:
            srv = await get_server(item["server_id"])
            if not srv:
                continue
            cli = XUIClient(srv["url"], srv["username"], srv["password"], srv["sub_path"], srv.get("api_token", ""))
            ok = await cli.delete_client(item["inbound_id"], item["uuid"], item.get("email", ""))
            await cli.close()
            if ok:
                deleted_remote += 1
        except Exception:
            continue

    deleted_local = await delete_configs_by_base_email(base_email)
    return JSONResponse({"success": True, "deleted_local": deleted_local, "deleted_remote": deleted_remote})


@app.get(f"/{S}/api/configs/disable/preview")
async def api_configs_disable_preview(request: Request):
    """What a bulk disable would touch — computed without calling any panel."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.legacy_configs import preview
    scope = request.query_params.get("scope") or "expired"
    return JSONResponse(await preview(scope))


@app.post(f"/{S}/api/configs/disable")
async def api_configs_disable(request: Request):
    """Switch off legacy single-server configs across every panel.

    Streamed as a background job because it talks to every server in turn; the
    safety rules (never touch a subscription client, one write per inbound) live
    in core/legacy_configs.py.
    """
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if _read_job_log("legacy").get("running"):
        return JSONResponse({"error": "یک عملیات غیرفعال‌سازی همین الان در حال اجراست."}, status_code=409)
    # Both rewrite clients on the same inbounds; running them together would
    # make each one's read-modify-write clobber the other's.
    for other, label in (("sync", "همگام‌سازی ساب‌ها"), ("nodeops", "عملیات نودها")):
        if _read_job_log(other).get("running"):
            return JSONResponse(
                {"error": f"«{label}» در حال اجراست. صبر کنید تا تمام شود، بعد دوباره بزنید."},
                status_code=409,
            )
    try:
        body = await request.json()
    except Exception:
        body = {}
    scope = str((body or {}).get("scope") or "expired")

    from core.legacy_configs import disable_all
    _asyncio.create_task(_run_python_job("legacy", lambda log: disable_all(scope, log)))
    return JSONResponse({"success": True, "scope": scope})


@app.get(f"/{S}/api/configs/disable/log")
async def api_configs_disable_log(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse(_read_job_log("legacy"))


# ═══════════════════════════════ USERS ══════════════════════════════








@app.post(f"/{S}/users/{{uid}}/toggle_block")
async def user_toggle_block(request: Request, uid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.database import get_user_by_id, update_user  # local import to avoid circulars

    u = await get_user_by_id(uid)
    if not u:
        return JSONResponse({"error": "not found"}, status_code=404)
    await update_user(uid, is_blocked=0 if u["is_blocked"] else 1)
    return JSONResponse({"success": True})




@app.post(f"/{S}/users/{{uid}}/toggle_wholesale")
async def user_toggle_wholesale(request: Request, uid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.database import get_user_by_id, update_user

    u = await get_user_by_id(uid)
    if not u:
        return JSONResponse({"error": "not found"}, status_code=404)
    next_status = 0 if u.get("is_wholesale", 0) else 1
    await update_user(uid, is_wholesale=next_status, wholesale_request_pending=0 if next_status else u.get("wholesale_request_pending", 0))
    return JSONResponse({"success": True, "is_wholesale": bool(next_status)})


@app.post(f"/{S}/users/{{uid}}/toggle_hide_brand")
async def user_toggle_hide_brand(request: Request, uid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.database import get_user_by_id, update_user

    u = await get_user_by_id(uid)
    if not u:
        return JSONResponse({"error": "not found"}, status_code=404)
    next_status = 0 if u.get("hide_brand", 0) else 1
    await update_user(uid, hide_brand=next_status)
    return JSONResponse({"success": True, "hide_brand": bool(next_status)})


@app.post(f"/{S}/users/{{uid}}/rep_brand")
async def user_set_rep_brand(request: Request, uid: int):
    """Admin sets/clears a representative's own brand name."""
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.database import get_user_by_id, update_user
    u = await get_user_by_id(uid)
    if not u:
        return JSONResponse({"error": "not found"}, status_code=404)
    if "application/json" in request.headers.get("content-type", ""):
        data = await request.json()
    else:
        data = dict(await request.form())
    brand = " ".join(str(data.get("brand") or "").split()).strip()[:32]
    await update_user(uid, rep_brand_name=brand)
    return JSONResponse({"success": True, "rep_brand_name": brand})


@app.post(f"/{S}/users/{{uid}}/admin_role")
async def user_set_admin_role(request: Request, uid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    ct = request.headers.get("content-type", "")
    if "application/json" in ct:
        data = await request.json()
        role = str(data.get("role", "none"))
        is_ajax = True
    else:
        form = await request.form()
        role = str(form.get("role", "none") or "none")
        is_ajax = False
    role = role.strip().lower()
    if role not in {"none", "finance", "full"}:
        role = "none"
    from core.database import update_user
    await update_user(uid, is_admin=0 if role == "none" else 1, admin_role=role)
    if is_ajax:
        return JSONResponse({"success": True, "role": role})
    return JSONResponse({"success": True})


@app.post(f"/{S}/users/transfer_owner")
async def transfer_owner(request: Request, telegram_id: int = Form(...)):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.database import get_user_by_telegram, set_setting, update_user

    user = await get_user_by_telegram(telegram_id)
    if not user:
        return JSONResponse({"error": "کاربری با این آیدی پیدا نشد."}, status_code=404)
    await update_user(user["id"], is_admin=1, admin_role="full")
    await set_setting("owner_admin_id", str(telegram_id))
    return JSONResponse({"success": True})
@app.post(f"/{S}/users/{{uid}}/balance_adjust")
async def user_balance_adjust(request: Request, uid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    ct = request.headers.get("content-type", "")
    if "application/json" in ct:
        data = await request.json()
        amount = int(str(data.get("amount", 0)).replace(",", "") or 0)
        note = str(data.get("note", "manual") or "manual")
        is_ajax = True
    else:
        form = await request.form()
        amount = int(str(form.get("amount", 0) or 0).replace(",", ""))
        note = str(form.get("note", "manual") or "manual")
        is_ajax = False
    if amount == 0:
        if is_ajax:
            return JSONResponse({"error": "مبلغ نمی‌تواند صفر باشد"}, status_code=400)
        return JSONResponse({"error": "مبلغ نمی‌تواند صفر باشد"}, status_code=400)
    await add_user_balance(uid, amount, kind="manual", note=note, actor_telegram_id=0)
    if is_ajax:
        from core.database import get_user_by_id
        u = await get_user_by_id(uid)
        return JSONResponse({"success": True, "new_balance": u.get("balance_toman", 0) if u else 0})
    return JSONResponse({"success": True})


@app.post(f"/{S}/topups/{{rid}}/approve")
async def topup_approve_web(request: Request, rid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    req = await get_topup_request(rid)
    if req and req.get("status") == "pending":
        await add_user_balance(req["user_id"], int(req["amount"]), kind="topup", note=f"topup_request:{rid}", actor_telegram_id=0)
        await update_topup_request(rid, status="approved", reviewer_telegram_id=0, reviewed_at=datetime.now().isoformat())
        await _clear_review_buttons("topup", rid)
    return JSONResponse({"success": True})


@app.post(f"/{S}/topups/{{rid}}/reject")
async def topup_reject_web(request: Request, rid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    req = await get_topup_request(rid)
    if req and req.get("status") == "pending":
        await update_topup_request(rid, status="rejected", reviewer_telegram_id=0, reviewed_at=datetime.now().isoformat(), admin_note="rejected_web")
        await _clear_review_buttons("topup", rid)
    return JSONResponse({"success": True})


@app.post(f"/{S}/users/{{uid}}/pricing")
async def user_set_pricing(request: Request, uid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    ct = request.headers.get("content-type", "")
    if "application/json" in ct:
        data = await request.json()
        discount_percent = float(data.get("discount_percent", 0) or 0)
        price_per_gb = int(str(data.get("price_per_gb", 0) or 0).replace(",", ""))
        unlimited_price = int(str(data.get("unlimited_price", 0) or 0).replace(",", ""))
        is_ajax = True
    else:
        form = await request.form()
        discount_percent = float(form.get("discount_percent", 0) or 0)
        price_per_gb = int(str(form.get("price_per_gb", 0) or 0).replace(",", ""))
        unlimited_price = int(str(form.get("unlimited_price", 0) or 0).replace(",", ""))
        is_ajax = False
    discount_percent = max(0, min(100, discount_percent))
    price_per_gb = max(0, price_per_gb)
    unlimited_price = max(0, unlimited_price)
    from core.database import update_user
    await update_user(uid, discount_percent=discount_percent, price_per_gb=price_per_gb, unlimited_price=unlimited_price)
    if is_ajax:
        return JSONResponse({"success": True})
    return JSONResponse({"success": True})


# ═══════════════════════════════ TRANSACTIONS ═══════════════════════
# ═════════════════════════════ LEGACY SYNC CLAIMS ═════════════════════════════
async def _notify_legacy_sync_user(telegram_id: int, text: str):
    if not BOT_TOKEN or len(BOT_TOKEN) < 20:
        return
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    try:
        await bot.send_message(int(telegram_id), text, parse_mode=None)
    except Exception:
        pass
    finally:
        await bot.session.close()


@app.get(f"/{S}/api/legacy-claims")
async def api_legacy_claims(request: Request):
    """Customers asking us to adopt a config they bought before this panel."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({"claims": [{
        "id": int(c["id"]),
        "telegram_id": int(c.get("telegram_id") or 0),
        "full_name": c.get("full_name") or "",
        "username": c.get("username") or "",
        "email": c.get("email") or "",
        "uuid": c.get("uuid") or "",
        "config_link": c.get("config_link") or "",
        "created_at": c.get("created_at") or "",
    } for c in await get_pending_legacy_claims()]})


@app.post(f"/{S}/legacy-claims/{{cid}}/approve")
async def legacy_claim_approve_web(request: Request, cid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    claim = await get_legacy_claim(cid)
    if not claim or claim.get("status") != "pending":
        return JSONResponse({"error": "این درخواست دیگر در انتظار بررسی نیست."}, status_code=404)

    email = (claim.get("email") or "").strip()
    claim_uuid = (claim.get("uuid") or "").strip()
    if not email and not claim_uuid:
        await update_legacy_claim(cid, status="rejected", reviewed_at=datetime.now().isoformat(), admin_note="missing_identity_web")
        return JSONResponse({"error": "لینک ارسالی نه ایمیل دارد نه UUID — قابل شناسایی نیست."}, status_code=400)

    cfg = await get_config_by_email(email) if email else None
    if not cfg and claim_uuid:
        cfg = await get_config_by_uuid(claim_uuid)

    remote = None
    if not cfg:
        from bot.handlers.admin import _find_remote_legacy_client

        remote = await _find_remote_legacy_client(email, claim_uuid)
        if not remote or not remote.get("email") or not remote.get("uuid"):
            await update_legacy_claim(cid, admin_note=f"not_found_web:{datetime.now().isoformat()}", reviewed_at=datetime.now().isoformat())
            return JSONResponse({"error": "این کانفیگ روی هیچ‌کدام از پنل‌ها پیدا نشد."}, status_code=404)
        try:
            cfg_id = await save_config(
                claim["user_id"],
                remote["server_id"],
                remote["uuid"],
                remote["email"],
                remote["inbound_id"],
                remote["traffic_gb"],
                remote["duration_days"],
                remote["expire_ms"],
            )
            cfg = await get_config(cfg_id)
        except sqlite3.IntegrityError:
            cfg = await get_config_by_email(remote["email"])
            if not cfg and remote.get("uuid"):
                cfg = await get_config_by_uuid(remote["uuid"])

    if not cfg:
        await update_legacy_claim(cid, admin_note=f"not_found_web:{datetime.now().isoformat()}", reviewed_at=datetime.now().isoformat())
        return JSONResponse({"error": "این کانفیگ روی هیچ‌کدام از پنل‌ها پیدا نشد."}, status_code=404)

    if not remote:
        try:
            from bot.handlers.admin import _find_remote_legacy_client

            remote = await _find_remote_legacy_client(email or cfg.get("email", ""), claim_uuid or cfg.get("uuid", ""))
        except Exception:
            remote = None

    updates = {"user_id": claim["user_id"], "is_active": int((remote or {}).get("is_active", 1))}
    if remote:
        updates.update(
            server_id=remote["server_id"],
            inbound_id=remote["inbound_id"],
            uuid=remote["uuid"],
            traffic_gb=remote["traffic_gb"],
            duration_days=remote["duration_days"],
            expire_timestamp=remote["expire_ms"],
        )
    await update_config(cfg["id"], **updates)
    await update_legacy_claim(cid, status="approved", reviewed_at=datetime.now().isoformat(), admin_note="approved_web")
    await _notify_legacy_sync_user(
        int(claim["telegram_id"]),
        "✅ کانفیگ قبلی شما تایید و به حساب ربات متصل شد.\n\nاز بخش «📡 وضعیت سرویس» می‌توانید آن را ببینید.",
    )
    return JSONResponse({"success": True, "config_id": int(cfg["id"])})


@app.post(f"/{S}/legacy-claims/{{cid}}/reject")
async def legacy_claim_reject_web(request: Request, cid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    claim = await get_legacy_claim(cid)
    if claim and claim.get("status") == "pending":
        await update_legacy_claim(cid, status="rejected", reviewed_at=datetime.now().isoformat(), admin_note="rejected_web")
        await _notify_legacy_sync_user(int(claim["telegram_id"]), "❌ درخواست سینک کانفیگ شما رد شد. برای بررسی بیشتر با پشتیبانی هماهنگ کنید.")
    return JSONResponse({"success": True})


@app.get(f"/{S}/api/transactions")
async def api_transactions(request: Request):
    """Every payment receipt a customer uploaded — wallet top-ups and orders in
    one stream, which is how an admin actually reviews them."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    limit = max(1, min(500, int(request.query_params.get("limit", "200") or 200)))
    return JSONResponse({"transactions": [{
        "tx_type": t.get("tx_type") or "",
        "tx_id": int(t.get("tx_id") or 0),
        "user_id": int(t.get("user_id") or 0),
        "telegram_id": int(t.get("telegram_id") or 0),
        "full_name": t.get("full_name") or "",
        "username": t.get("username") or "",
        "amount": int(t.get("amount") or 0),
        "status": t.get("status") or "",
        "created_at": t.get("created_at") or "",
        "reviewed_at": t.get("reviewed_at") or "",
        # The image itself is fetched from Telegram on demand — see
        # /receipts/{type}/{id} — so the list stays small and fast.
        "has_receipt": bool((t.get("receipt_file_id") or "").strip()),
    } for t in await get_recent_receipt_transactions(limit)]})


@app.get(f"/{S}/receipts/{'{'}tx_type{'}'}/{'{'}tx_id{'}'}")
async def receipt_image(request: Request, tx_type: str, tx_id: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    tx_type = (tx_type or "").strip().lower()
    tx = None
    for item in await get_recent_receipt_transactions(500):
        if item.get("tx_type") == tx_type and int(item.get("tx_id") or 0) == int(tx_id):
            tx = item
            break
    if not tx or not tx.get("receipt_file_id"):
        return JSONResponse({"error": "not found"}, status_code=404)

    bot = Bot(token=BOT_TOKEN)
    try:
        f = await bot.get_file(tx["receipt_file_id"])
        stream = await bot.download_file(f.file_path)
        stream.seek(0)
        return StreamingResponse(stream, media_type="image/jpeg")
    except Exception:
        return JSONResponse({"error": "receipt unavailable"}, status_code=404)
    finally:
        await bot.session.close()




# ═══════════════════════════════ SETTINGS ═══════════════════════════
async def _settings_snapshot() -> dict:
    """Current values for every field the settings form manages, keyed exactly by
    the POST /settings form param names so the React page maps 1:1 and can submit
    the complete set (partial submits would reset omitted fields to defaults)."""
    settings = {
        "welcome_message": await get_setting("text.welcome_message", BOT_TEXT_DEFAULTS["text.welcome_message"]),
        "support_username": await get_setting("support_username", ""),
        "maintenance_mode": await get_setting("maintenance_mode", "0"),
        "maintenance_message": await get_setting("text.maintenance_message", BOT_TEXT_DEFAULTS["text.maintenance_message"]),
        "blocked_message": await get_setting("text.blocked_message", BOT_TEXT_DEFAULTS["text.blocked_message"]),
        "no_active_service": await get_setting("text.no_active_service", BOT_TEXT_DEFAULTS["text.no_active_service"]),
        "support_header": await get_setting("text.support_header", BOT_TEXT_DEFAULTS["text.support_header"]),
        "support_body": await get_setting("text.support_body", BOT_TEXT_DEFAULTS["text.support_body"]),
        "referral_intro": await get_setting("text.referral_intro", BOT_TEXT_DEFAULTS["text.referral_intro"]),
        "panel_url_help": await get_setting("text.panel_url_help", BOT_TEXT_DEFAULTS["text.panel_url_help"]),
        "ui_brand_name": await get_setting("ui.brand_name", UI_DEFAULTS["ui.brand_name"]),
        "ui_panel_subtitle": await get_setting("ui.panel_subtitle", UI_DEFAULTS["ui.panel_subtitle"]),
        "ui_topbar_note": await get_setting("ui.topbar_note", UI_DEFAULTS["ui.topbar_note"]),
        "ui_logo_emoji": await get_setting("ui.logo_emoji", UI_DEFAULTS["ui.logo_emoji"]),
        "ui_custom_css": await get_setting("ui.custom_css", CUSTOM_STYLE_DEFAULT),
        "ui_custom_js": await get_setting("ui.custom_js", CUSTOM_SCRIPT_DEFAULT),
        "cfg_name_prefix": await get_setting("cfg_name_prefix", SETTINGS_DEFAULTS["cfg_name_prefix"]),
        "cfg_name_postfix": await get_setting("cfg_name_postfix", SETTINGS_DEFAULTS["cfg_name_postfix"]),
        "cfg_name_rand_len": await get_setting("cfg_name_rand_len", SETTINGS_DEFAULTS["cfg_name_rand_len"]),
        "force_channel": await get_setting("force_channel", SETTINGS_DEFAULTS["force_channel"]),
        "channel_username": await get_setting("channel_username", SETTINGS_DEFAULTS["channel_username"]),
        "default_server_id": await get_setting("default_server_id", "0"),
        "auto_least_loaded_server": await get_setting("auto_least_loaded_server", SETTINGS_DEFAULTS["auto_least_loaded_server"]),
        "legacy_sync_enabled": await get_setting("legacy_sync_enabled", SETTINGS_DEFAULTS["legacy_sync_enabled"]),
        "max_daily_migrations": await get_setting("max_daily_migrations", SETTINGS_DEFAULTS["max_daily_migrations"]),
        "renewal_min_traffic_gb": await get_setting("renewal_min_traffic_gb", SETTINGS_DEFAULTS["renewal_min_traffic_gb"]),
        "multi_sub_enabled": await get_setting("multi_sub_enabled", SETTINGS_DEFAULTS["multi_sub_enabled"]),
        "multi_sub_node_count": await get_setting("multi_sub_node_count", SETTINGS_DEFAULTS["multi_sub_node_count"]),
        "multi_sub_min_nodes": await get_setting("multi_sub_min_nodes", SETTINGS_DEFAULTS["multi_sub_min_nodes"]),
        "public_base_url": await get_setting("public_base_url", SETTINGS_DEFAULTS["public_base_url"]),
        "sub_info_enabled": await get_setting("sub_info_enabled", SETTINGS_DEFAULTS["sub_info_enabled"]),
        "sub_info_sync_on_render": await get_setting("sub_info_sync_on_render", SETTINGS_DEFAULTS["sub_info_sync_on_render"]),
        "sub_info_template": await get_setting("sub_info_template", SETTINGS_DEFAULTS["sub_info_template"]),
        "sub_brand_template": await get_setting("sub_brand_template", SETTINGS_DEFAULTS["sub_brand_template"]),
        "test_account_enabled": await get_setting("test_account_enabled", SETTINGS_DEFAULTS["test_account_enabled"]),
        "test_account_traffic_gb": await get_setting("test_account_traffic_gb", SETTINGS_DEFAULTS["test_account_traffic_gb"]),
        "test_account_duration_days": await get_setting("test_account_duration_days", SETTINGS_DEFAULTS["test_account_duration_days"]),
        "test_account_server_id": await get_setting("test_account_server_id", SETTINGS_DEFAULTS["test_account_server_id"]),
        "test_account_prefix": await get_setting("test_account_prefix", SETTINGS_DEFAULTS["test_account_prefix"]),
        "rep_test_daily_limit": await get_setting("rep_test_daily_limit", "0"),
        "panel_domain": await get_setting("panel_domain", ""),
        "cert_email": await get_setting("cert_email", ""),
        "atlas_tls_https_port": await get_setting("atlas_tls_https_port", "443"),
        "cert_status": await get_setting("cert_status", ""),
        "ai_enabled": await get_setting("ai_enabled", SETTINGS_DEFAULTS["ai_enabled"]),
        "ai_provider": await get_setting("ai_provider", SETTINGS_DEFAULTS["ai_provider"]),
        "ai_model": await get_setting("ai_model", SETTINGS_DEFAULTS["ai_model"]),
        "ai_base_url": await get_setting("ai_base_url", SETTINGS_DEFAULTS["ai_base_url"]),
        # The key itself is never sent back to the browser — only whether one exists.
        "ai_key_set": "1" if (await get_setting("ai_api_key", "")).strip() else "0",
        "login_captcha_always": await get_setting("login_captcha_always", SETTINGS_DEFAULTS["login_captcha_always"]),
        "login_alert_enabled": await get_setting("login_alert_enabled", SETTINGS_DEFAULTS["login_alert_enabled"]),
    }

    # ✅ کارت بانکی از دیتابیس Settings خوانده می‌شود (با fallback از .env)
    settings["card_number"] = await get_setting("card_number", CARD_NUMBER)
    settings["card_holder"] = await get_setting("card_holder", CARD_HOLDER)
    settings["card_bank"] = await get_setting("card_bank", CARD_BANK)

    settings["referral_bonus_gb"] = REFERRAL_BONUS_GB
    settings["rep_min_topup"] = await get_setting("rep_min_topup", "500000")
    settings["rep_price_per_gb"] = await get_setting("rep_price_per_gb", "0")
    settings["rep_unlimited_price"] = await get_setting("rep_unlimited_price", "0")
    return settings




@app.get(f"/{S}/api/settings")
async def api_settings(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    settings = await _settings_snapshot()
    servers = await get_servers(active_only=False)
    return JSONResponse({
        "settings": settings,
        "servers": [{"id": s["id"], "name": s.get("name"), "is_active": int(s.get("is_active") or 0)} for s in servers],
    })


@app.post(f"/{S}/api/rep-pricing")
async def api_rep_pricing(request: Request):
    """Global representative pricing: one per-GB / unlimited price used for every
    rep who has no per-seller custom price, plus the minimum first-top-up."""
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    d = await request.json()
    ppg = max(0, int(str(d.get("rep_price_per_gb") or 0).replace(",", "") or 0))
    unl = max(0, int(str(d.get("rep_unlimited_price") or 0).replace(",", "") or 0))
    mint = max(0, int(str(d.get("rep_min_topup") or 0).replace(",", "") or 0))
    await set_setting("rep_price_per_gb", str(ppg))
    await set_setting("rep_unlimited_price", str(unl))
    await set_setting("rep_min_topup", str(mint))
    return JSONResponse({"success": True})


@app.get(f"/{S}/api/branding")
async def api_branding(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({
        "brand_name": await get_setting("ui.brand_name", "Atlas Account"),
        "logo": await _admin_logo(),
    })


@app.post(f"/{S}/api/logo")
async def api_logo_upload(request: Request, logo: UploadFile = File(...)):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    data = await logo.read()
    uri = process_logo_bytes(data)
    if not uri:
        return JSONResponse({"success": False, "error": "تصویر نامعتبر یا خیلی بزرگ است."}, status_code=400)
    await set_setting("ui.logo_data", uri)
    return JSONResponse({"success": True, "logo": uri})


@app.post(f"/{S}/api/logo/clear")
async def api_logo_clear(request: Request):
    if not _api_guard(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await set_setting("ui.logo_data", "")
    return JSONResponse({"success": True})


@app.post(f"/{S}/settings")
async def settings_save(
    request: Request,
    welcome_message: str = Form(""),
    support_username: str = Form(""),
    maintenance_mode: str = Form("0"),
    maintenance_message: str = Form(""),
    blocked_message: str = Form(""),
    no_active_service: str = Form(""),
    support_header: str = Form(""),
    support_body: str = Form(""),
    referral_intro: str = Form(""),
    panel_url_help: str = Form(""),
    ui_brand_name: str = Form(""),
    ui_panel_subtitle: str = Form(""),
    ui_topbar_note: str = Form(""),
    ui_logo_emoji: str = Form(""),
    ui_custom_css: str = Form(""),
    ui_custom_js: str = Form(""),
    cfg_name_prefix: str = Form("u"),
    cfg_name_postfix: str = Form(""),
    cfg_name_rand_len: str = Form("6"),
    force_channel: str = Form("0"),
    channel_username: str = Form(""),
    default_server_id: str = Form("0"),
    auto_least_loaded_server: str = Form("0"),
    legacy_sync_enabled: str = Form("1"),
    max_daily_migrations: int = Form(5),
    renewal_min_traffic_gb: float = Form(1),
    multi_sub_enabled: str = Form("0"),
    multi_sub_node_count: int = Form(4),
    multi_sub_min_nodes: int = Form(2),
    public_base_url: str = Form(""),
    sub_info_enabled: str = Form("1"),
    sub_info_sync_on_render: str = Form("1"),
    sub_info_template: str = Form(""),
    sub_brand_template: str = Form(""),
    test_account_enabled: str = Form("0"),
    test_account_traffic_gb: float = Form(1),
    test_account_duration_days: int = Form(1),
    test_account_server_id: str = Form("0"),
    test_account_prefix: str = Form("test"),
    rep_test_daily_limit: str = Form("0"),
    # ✅ کارت بانکی از پنل ذخیره می‌شود
    card_number: str = Form(""),
    card_holder: str = Form(""),
    card_bank: str = Form(""),
    panel_domain: str = Form(""),
    cert_email: str = Form(""),
    atlas_tls_https_port: int = Form(443),
    rep_min_topup: str = Form("500000"),
    ai_enabled: str = Form("0"),
    ai_provider: str = Form("gemini"),
    ai_model: str = Form(""),
    ai_base_url: str = Form(""),
    ai_api_key: str = Form(""),
    login_captcha_always: str = Form("0"),
    login_alert_enabled: str = Form("1"),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        await set_setting("rep_min_topup", str(max(0, int(str(rep_min_topup or "0").replace(",", "")))))
    except (TypeError, ValueError):
        await set_setting("rep_min_topup", "500000")

    await set_setting("ai_enabled", "1" if ai_enabled == "1" else "0")
    await set_setting("ai_provider", "openai" if ai_provider == "openai" else "gemini")
    await set_setting("ai_model", (ai_model or "").strip() or SETTINGS_DEFAULTS["ai_model"])
    await set_setting("ai_base_url", (ai_base_url or "").strip())
    # A blank field means "leave the stored key alone", so saving other settings
    # cannot silently wipe a key the form never received.
    if (ai_api_key or "").strip():
        await set_setting("ai_api_key", ai_api_key.strip())

    await set_setting("login_captcha_always", "1" if login_captcha_always == "1" else "0")
    await set_setting("login_alert_enabled", "1" if login_alert_enabled == "1" else "0")

    await set_setting("text.welcome_message", welcome_message)
    await set_setting("support_username", support_username)
    await set_setting("maintenance_mode", maintenance_mode)
    await set_setting("text.maintenance_message", maintenance_message)
    await set_setting("text.blocked_message", blocked_message)
    await set_setting("text.no_active_service", no_active_service)
    await set_setting("text.support_header", support_header)
    await set_setting("text.support_body", support_body)
    await set_setting("text.referral_intro", referral_intro)
    await set_setting("text.panel_url_help", panel_url_help)

    await set_setting("ui.brand_name", ui_brand_name)
    await set_setting("ui.panel_subtitle", ui_panel_subtitle)
    await set_setting("ui.topbar_note", ui_topbar_note)
    await set_setting("ui.logo_emoji", ui_logo_emoji)
    await set_setting("ui.custom_css", ui_custom_css)
    await set_setting("ui.custom_js", ui_custom_js)

    await set_setting("cfg_name_prefix", cfg_name_prefix)
    await set_setting("cfg_name_postfix", cfg_name_postfix)
    await set_setting("cfg_name_rand_len", cfg_name_rand_len)

    await set_setting("force_channel", force_channel)
    await set_setting("channel_username", channel_username.lstrip("@"))

    valid_server_ids = {str(sv["id"]) for sv in await get_servers(active_only=False)}
    await set_setting("default_server_id", default_server_id if default_server_id in valid_server_ids else "0")
    await set_setting("auto_least_loaded_server", "1" if auto_least_loaded_server == "1" else "0")
    await set_setting("legacy_sync_enabled", "1" if legacy_sync_enabled == "1" else "0")
    await set_setting("max_daily_migrations", str(max(0, int(max_daily_migrations or 0))))
    await set_setting("renewal_min_traffic_gb", str(max(0.1, float(renewal_min_traffic_gb or 1))))
    # Subscriptions are the only fulfilment model now; keep it pinned on.
    await set_setting("multi_sub_enabled", "1")
    await set_setting("multi_sub_node_count", str(max(0, int(multi_sub_node_count or 0))))
    await set_setting("multi_sub_min_nodes", str(max(0, int(multi_sub_min_nodes or 0))))
    await set_setting("public_base_url", public_base_url.strip().rstrip("/"))
    await set_setting("sub_info_enabled", "1" if sub_info_enabled == "1" else "0")
    await set_setting("sub_info_sync_on_render", "1" if sub_info_sync_on_render == "1" else "0")
    await set_setting("sub_info_template", sub_info_template.strip() or SETTINGS_DEFAULTS["sub_info_template"])
    await set_setting("sub_brand_template", sub_brand_template.strip() or SETTINGS_DEFAULTS["sub_brand_template"])
    await set_setting("test_account_enabled", "1" if test_account_enabled == "1" else "0")
    await set_setting("test_account_traffic_gb", str(max(0.1, float(test_account_traffic_gb or 1))))
    await set_setting("test_account_duration_days", str(max(1, int(test_account_duration_days or 1))))
    await set_setting("test_account_server_id", test_account_server_id if test_account_server_id in valid_server_ids else "0")
    clean_test_prefix = "".join(ch for ch in (test_account_prefix or "test").strip() if ch.isalnum() or ch in ("_", "-"))[:16] or "test"
    await set_setting("test_account_prefix", clean_test_prefix)
    try:
        _rtdl = max(0, int(rep_test_daily_limit or 0))
    except (TypeError, ValueError):
        _rtdl = 0
    await set_setting("rep_test_daily_limit", str(_rtdl))

    # ✅ ذخیره کارت
    await set_setting("card_number", card_number.strip())
    await set_setting("card_holder", card_holder.strip())
    await set_setting("card_bank", card_bank.strip())
    await set_setting("panel_domain", panel_domain.strip().lower())
    await set_setting("cert_email", cert_email.strip().lower())
    await set_setting("atlas_tls_https_port", str(max(1, min(65535, int(atlas_tls_https_port or 443)))))

    return JSONResponse({"success": True})


def _public_url_for(domain: str, https_port: int) -> str:
    return f"https://{domain}" if int(https_port) == 443 else f"https://{domain}:{int(https_port)}"


@app.post(f"/{S}/settings/certificate/start")
async def settings_cert_start(request: Request):
    """Kick off the SSL/Nginx setup as a background streamed job (no blocking)."""
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    form = await request.form()
    domain = _clean_domain(str(form.get("panel_domain") or await get_setting("panel_domain", "")))
    email = str(form.get("cert_email") or await get_setting("cert_email", "")).strip().lower()
    try:
        https_port = int(form.get("atlas_tls_https_port") or await get_setting("atlas_tls_https_port", "443") or 443)
    except (TypeError, ValueError):
        https_port = 443
    https_port = max(1, min(65535, https_port))
    if not domain:
        return JSONResponse({"error": "دامنه معتبر نیست. مثال درست: sm.example.com"}, status_code=400)
    if https_port in {80, WEB_PORT}:
        return JSONResponse({"error": f"پورت HTTPS ({https_port}) مناسب نیست؛ با پورت 80 یا پورت داخلی ربات تداخل دارد."}, status_code=400)

    # already running?
    if _read_job_log("cert").get("running"):
        return JSONResponse({"error": "یک عملیات گواهی همین الان در حال اجراست. کمی صبر کنید."}, status_code=409)

    await set_setting("panel_domain", domain)
    await set_setting("cert_email", email)
    await set_setting("atlas_tls_https_port", str(https_port))

    script = _atlas_tls_proxy_script(domain, email, WEB_PORT, https_port)
    _asyncio.create_task(_run_logged_job("cert", script))
    return JSONResponse({
        "success": True,
        "domain": domain,
        "https_port": https_port,
        "public_url": _public_url_for(domain, https_port),
    })


@app.get(f"/{S}/settings/certificate/log")
async def settings_cert_log(request: Request):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    data = _read_job_log("cert")
    if data["status"] == "ok":
        domain = _clean_domain(await get_setting("panel_domain", ""))
        try:
            https_port = int(await get_setting("atlas_tls_https_port", "443") or 443)
        except (TypeError, ValueError):
            https_port = 443
        data["public_url"] = _public_url_for(domain, https_port) if domain else ""
        data["domain"] = domain
        data["https_port"] = https_port
    return JSONResponse(data)


@app.post(f"/{S}/settings/certificate/apply-domain")
async def settings_cert_apply_domain(request: Request):
    """Set the verified domain as the public base URL for the panel + bot sub links."""
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    form = await request.form()
    domain = _clean_domain(str(form.get("domain") or await get_setting("panel_domain", "")))
    try:
        https_port = int(form.get("https_port") or await get_setting("atlas_tls_https_port", "443") or 443)
    except (TypeError, ValueError):
        https_port = 443
    if not domain:
        return JSONResponse({"error": "دامنه نامعتبر است."}, status_code=400)
    public_url = _public_url_for(domain, https_port)
    await set_setting("public_base_url", public_url)
    await set_setting("panel_domain", domain)
    await set_setting("atlas_tls_https_port", str(https_port))
    await set_setting("cert_status", f"✅ دامنه روی پنل و ربات تنظیم شد | لینک عمومی ساب: {public_url}")
    return JSONResponse({"success": True, "public_url": public_url})




@app.post(f"/{S}/settings/legacy_sync/reset")
async def settings_reset_legacy_sync(request: Request):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    deleted = await reset_legacy_claims()
    return JSONResponse({"success": True, "deleted": deleted})


# ═══════════════════════════════ UPDATE ══════════════════════════════
import asyncio as _asyncio


# ───────── Background log-job infra (shared by SSL setup + self-update) ─────────
_JOB_LOG_PATHS = {
    "cert": os.path.join(_repo_dir, "atlas-cert.log"),
    "update": os.path.join(_repo_dir, "atlas-update.log"),
    "sync": os.path.join(_repo_dir, "atlas-sync.log"),
    "nodeops": os.path.join(_repo_dir, "atlas-nodeops.log"),
    "proxy": os.path.join(_repo_dir, "atlas-proxy.log"),
    "legacy": os.path.join(_repo_dir, "atlas-legacy.log"),
}
_JOB_DONE_OK = "__ATLAS_JOB_OK__"
_JOB_DONE_FAIL = "__ATLAS_JOB_FAIL__"


def _job_log_path(name: str) -> str:
    return _JOB_LOG_PATHS.get(name, os.path.join(_repo_dir, "atlas-job.log"))


def _read_job_log(name: str) -> dict:
    path = _job_log_path(name)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        return {"lines": [], "running": False, "status": "idle"}
    status = "running"
    if _JOB_DONE_OK in text:
        status = "ok"
    elif _JOB_DONE_FAIL in text:
        status = "error"
    lines = [ln for ln in text.splitlines() if _JOB_DONE_OK not in ln and _JOB_DONE_FAIL not in ln]
    return {"lines": lines[-500:], "running": status == "running", "status": status}


async def _run_logged_job(name: str, script: str):
    """Run a bash script in-process, streaming combined output to the job log file.

    For jobs that do NOT restart this service (e.g. SSL setup). For self-update
    use _launch_detached_job(): stopping atlas-bot would kill an in-process job.
    """
    path = _job_log_path(name)
    cmd = ["bash", "-lc", script]
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        cmd = ["sudo", "-n", "bash", "-lc", script]
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"$ شروع عملیات «{name}» — {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        proc = await _asyncio.create_subprocess_exec(
            *cmd,
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.STDOUT,
            cwd=_repo_dir,
        )
        with open(path, "a", encoding="utf-8") as f:
            while True:
                chunk = await proc.stdout.readline()
                if not chunk:
                    break
                f.write(chunk.decode("utf-8", errors="replace"))
                f.flush()
        rc = await proc.wait()
        with open(path, "a", encoding="utf-8") as f:
            if rc == 0:
                f.write(f"\n✅ عملیات با موفقیت تمام شد.\n{_JOB_DONE_OK}\n")
            else:
                f.write(f"\n❌ عملیات با کد خطای {rc} متوقف شد.\n{_JOB_DONE_FAIL}\n")
    except Exception as e:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n❌ خطای داخلی هنگام اجرا: {e}\n{_JOB_DONE_FAIL}\n")
        except Exception:
            pass


async def _run_python_job(name: str, coro_func):
    """Run an async Python routine as a streamed background job.

    `coro_func(log)` receives a synchronous `log(line)` callback that appends a
    line to the job log file (read by /.../log endpoints for live display)."""
    path = _job_log_path(name)
    try:
        f = open(path, "w", encoding="utf-8")
    except Exception:
        return
    f.write(f"$ شروع عملیات «{name}» — {datetime.now():%Y-%m-%d %H:%M:%S}\n")
    f.flush()

    def log(line: str = ""):
        try:
            f.write(str(line).rstrip("\n") + "\n")
            f.flush()
        except Exception:
            pass

    try:
        await coro_func(log)
        f.write(f"\n✅ عملیات با موفقیت تمام شد.\n{_JOB_DONE_OK}\n")
    except Exception as e:
        f.write(f"\n❌ خطای داخلی: {e}\n{_JOB_DONE_FAIL}\n")
    finally:
        try:
            f.flush()
            f.close()
        except Exception:
            pass


def _launch_detached_job(name: str, script: str) -> None:
    """Run a script fully detached from this service's cgroup so it survives a
    restart. Required for self-update (update.sh stops atlas-bot, which would
    otherwise kill the updater before the restart completes)."""
    path = _job_log_path(name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"$ شروع آپدیت — {datetime.now():%Y-%m-%d %H:%M:%S}\n")
    qpath = shlex.quote(path)
    inner = (
        f"({script}) >> {qpath} 2>&1; "
        f"if [ $? -eq 0 ]; then echo {_JOB_DONE_OK} >> {qpath}; "
        f"else echo {_JOB_DONE_FAIL} >> {qpath}; fi"
    )
    # systemd-run gives the unit a minimal env where HOME is often unset, which
    # breaks `git config --global` / acme.sh ("fatal: $HOME not set"). Pass a
    # sane HOME (and keep the current env for the fallback paths).
    home = os.environ.get("HOME") or "/root"
    sudo = [] if (hasattr(os, "geteuid") and os.geteuid() == 0) else ["sudo", "-n"]
    if shutil.which("systemd-run"):
        unit = f"atlas-selfupdate-{int(time.time())}"
        cmd = sudo + [
            "systemd-run", "--collect", "--unit", unit,
            "--property=KillMode=process",
            f"--setenv=HOME={home}",
            "bash", "-lc", inner,
        ]
    elif shutil.which("setsid"):
        cmd = sudo + ["setsid", "bash", "-lc", inner]
    else:
        cmd = sudo + ["bash", "-lc", inner]
    env = dict(os.environ)
    env["HOME"] = home
    subprocess.Popen(
        cmd, cwd=_repo_dir,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, env=env,
    )


async def _git_run(*args, cwd=None):
    try:
        proc = await _asyncio.create_subprocess_exec(
            *args,
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.PIPE,
            cwd=cwd or _repo_dir,
        )
    except FileNotFoundError:
        return "", "git_not_installed", 127
    out, err = await proc.communicate()
    return out.decode("utf-8", errors="replace").strip(), err.decode("utf-8", errors="replace").strip(), proc.returncode


async def _git(*subargs):
    """Run git against the repo, trusting it (avoids 'dubious ownership' failures)."""
    return await _git_run("git", "-C", _repo_dir, "-c", f"safe.directory={_repo_dir}", *subargs)


def _is_git_sha(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{7,40}", (value or "").strip()))


def _extract_new_changelog(local_md: str, remote_md: str) -> str:
    """Persian, user-friendly changelog: the remote CHANGELOG.md version blocks
    that are newer than the one currently installed."""
    def first_version_header(md: str) -> str:
        for line in (md or "").splitlines():
            if line.strip().startswith("## ["):
                return line.strip()
        return ""

    local_top = first_version_header(local_md)
    out_lines: list[str] = []
    capturing = False
    for line in (remote_md or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("## ["):
            if local_top and stripped == local_top:
                break  # reached the installed version; stop
            capturing = True
        if capturing:
            out_lines.append(line.rstrip())
    text = "\n".join(out_lines).strip()
    return text


async def _read_remote_changelog() -> str:
    out, _, rc = await _git("show", "origin/main:CHANGELOG.md")
    return out if rc == 0 else ""


def _run_update_bg(repo_dir: str):
    """Start the self-update DETACHED so it survives the service restart.

    update.sh stops atlas-bot; if the updater were a child of this process it
    would be killed mid-update. systemd-run (or setsid) keeps it alive."""
    update_sh = os.path.join(repo_dir, "update.sh")
    if os.path.exists(update_sh):
        script = f"bash {shlex.quote(update_sh)} hard"
    else:
        script = (
            f"cd {shlex.quote(repo_dir)} && git fetch origin main && "
            f"git reset --hard origin/main && systemctl restart atlas-bot"
        )
    _launch_detached_job("update", script)




@app.get(f"/{S}/update/check")
async def update_check(request: Request):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        # Is this even a git checkout?
        inside, _, inside_rc = await _git("rev-parse", "--is-inside-work-tree")
        if inside_rc != 0 or inside.strip() != "true":
            return JSONResponse({
                "error": "این نصب یک مخزن git نیست؛ آپدیت خودکار ممکن نیست. لطفاً از طریق SSH به‌روزرسانی کنید.",
            }, status_code=400)

        local_hash, lerr, lrc = await _git("rev-parse", "HEAD")
        if lrc != 0 or not _is_git_sha(local_hash):
            return JSONResponse({
                "error": f"خواندن نسخهٔ فعلی ناموفق بود: {lerr or 'unknown'}",
            }, status_code=500)

        # Fetch latest refs; if this fails (network/filtering), say so clearly
        # instead of comparing against stale data and always showing "update".
        fetch_out, fetch_err, fetch_rc = await _git("fetch", "--prune", "origin", "main")
        if fetch_rc != 0:
            return JSONResponse({
                "error": "اتصال به گیت‌هاب برای بررسی نسخهٔ جدید برقرار نشد (شبکه/فیلترینگ). کمی بعد دوباره امتحان کنید.",
                "local_hash": local_hash[:8],
                "detail": (fetch_err or fetch_out or "")[:300],
            }, status_code=502)

        remote_hash, rerr, rrc = await _git("rev-parse", "origin/main")
        if rrc != 0 or not _is_git_sha(remote_hash):
            return JSONResponse({
                "error": f"خواندن نسخهٔ گیت‌هاب ناموفق بود: {rerr or 'unknown'}",
                "local_hash": local_hash[:8],
            }, status_code=500)

        up_to_date = local_hash == remote_hash

        changelog = []
        changelog_md = ""
        if not up_to_date and local_hash and remote_hash:
            log_out, _, _ = await _git(
                "log", "--no-merges",
                "--pretty=format:%H|%s|%an|%ar",
                f"{local_hash}..origin/main",
            )
            for line in log_out.split("\n"):
                line = line.strip()
                if line:
                    parts = line.split("|", 3)
                    changelog.append({
                        "hash": parts[0][:8] if parts else "",
                        "message": parts[1] if len(parts) > 1 else line,
                        "author": parts[2] if len(parts) > 2 else "",
                        "time": parts[3] if len(parts) > 3 else "",
                    })

            # Persian, user-friendly changelog straight from the new CHANGELOG.md
            try:
                local_md = ""
                local_changelog_path = os.path.join(_repo_dir, "CHANGELOG.md")
                if os.path.exists(local_changelog_path):
                    with open(local_changelog_path, "r", encoding="utf-8", errors="replace") as f:
                        local_md = f.read()
                remote_md = await _read_remote_changelog()
                changelog_md = _extract_new_changelog(local_md, remote_md)
            except Exception:
                changelog_md = ""

        return JSONResponse({
            "up_to_date": up_to_date,
            "local_hash": local_hash[:8] if local_hash else "—",
            "remote_hash": remote_hash[:8] if remote_hash else "—",
            "commits_behind": len(changelog),
            "changelog": changelog,
            "changelog_md": changelog_md,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post(f"/{S}/update/apply")
async def update_apply(request: Request):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if _read_job_log("update").get("running"):
        return JSONResponse({"error": "یک آپدیت همین الان در حال اجراست."}, status_code=409)
    try:
        _run_update_bg(_repo_dir)
    except Exception as e:
        return JSONResponse({"error": f"شروع آپدیت ناموفق بود: {e}"}, status_code=500)
    return JSONResponse({"success": True, "message": "آپدیت شروع شد. پنل چند ثانیه دیگر ریستارت می‌شود..."})


@app.get(f"/{S}/update/log")
async def update_log(request: Request):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse(_read_job_log("update"))


# ═══════════════════════════════ ROOT ═══════════════════════════════
@app.get("/")
async def root():
    return RedirectResponse(f"/{S}/", status_code=302)


# ---------------------------------------------------------------- IP guard
# Per-subscription concurrent-connection limit. Deliberately NOT part of
# `_settings_snapshot`: like the auto node and the reseller API kill switch,
# this is a self-contained feature block with its own validation, and folding
# fifteen more fields into the big settings form would mean every unrelated
# save round-trips them too.

@app.get(f"/{S}/api/subs/{{profile_id}}/connections")
async def api_sub_connections(request: Request, profile_id: int):
    """Who is connected to this one subscription, right now.

    The owner's view, so addresses are NOT masked — this is the screen you open
    when a customer says "it keeps disconnecting" or when you suspect a link has
    been shared, and a partial address answers neither question.

    Cheap regardless of how often it is opened: every panel is read at most once
    every few seconds and that reading is shared with the guard worker, the bot,
    the mini-app and the reseller API. See core/ip_guard.py.
    """
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.ip_guard import live_connections, forget_live, reset_snapshot
    if request.query_params.get("fresh") == "1":
        # An explicit "check again" from the owner skips every cache, because
        # the reason they pressed it is that they do not believe the last answer.
        reset_snapshot()
    forget_live(int(profile_id))
    try:
        return JSONResponse(await live_connections(int(profile_id), confirm=True, reveal=True))
    except Exception as e:
        logger.warning("connections lookup failed for %s: %s", profile_id, e)
        return JSONResponse({"ok": False, "error": str(e)[:300]}, status_code=502)


@app.get(f"/{S}/api/ipguard")
async def api_ipguard_get(request: Request):
    """Settings, live state, and the evidence log the owner reads before arming it."""
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.ip_guard import DEFAULTS as IPG_DEFAULTS
    from core.database import get_ip_guard_events, get_cut_profiles

    settings = {}
    for key, default in IPG_DEFAULTS.items():
        settings[key] = await get_setting(key, default)
    events = await get_ip_guard_events(200)
    cut = await get_cut_profiles()
    try:
        from core.ip_guard import coverage as ipg_coverage
        cover = await ipg_coverage()
    except Exception as e:
        logger.warning("ip guard coverage failed: %s", e)
        cover = {}
    try:
        from core.database import get_gateways
        gateways = await get_gateways()
    except Exception as e:
        logger.warning("ip guard gateways failed: %s", e)
        gateways = []
    now = int(time.time())
    return JSONResponse({
        "settings": settings,
        "defaults": IPG_DEFAULTS,
        "cut_now": [{**c, "seconds_left": max(0, int(c["penalty_until"]) - now)} for c in cut],
        "events": events,
        "coverage": cover,
        "gateways": gateways,
        "now": now,
    })


@app.post(f"/{S}/api/ipguard")
async def api_ipguard_save(request: Request):
    """Save the guard's knobs. Every value is validated and clamped here as well
    as in core/ip_guard.py — a setting that reaches the worker as nonsense would
    either disarm the feature silently or cut somebody for a week."""
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.ip_guard import DEFAULTS as IPG_DEFAULTS, parse_steps

    d = await _node_form_body(request)
    flags = ("ip_limit_enabled", "ip_limit_warn_only", "ip_limit_gateways_enabled")
    bounds = {
        "ip_limit_default": (1, 1000),
        "ip_limit_poll_seconds": (15, 3600),
        "ip_limit_fresh_seconds": (20, 1800),
        "ip_limit_active_seconds": (30, 1800),
        "ip_limit_strikes": (1, 20),
        "ip_limit_ipv4_bits": (8, 32),
        "ip_limit_ipv6_bits": (16, 128),
        "ip_limit_decay_hours": (1, 8760),
        "ip_limit_warn_cooldown": (60, 86400),
        "ip_limit_grace_seconds": (30, 86400),
        "ip_limit_reassert_after": (30, 7200),
        "ip_limit_event_keep_days": (1, 3650),
        "ip_limit_gateway_bits": (8, 32),
        "ip_limit_gateway_min_users": (2, 50),
        "ip_limit_gateway_window_hours": (1, 8760),
        "ip_limit_gateway_scan_minutes": (1, 1440),
    }
    was_on = await get_setting("ip_limit_enabled", "0") == "1"

    for key in IPG_DEFAULTS:
        if key not in d:
            continue
        if key in flags:
            await set_setting(key, "1" if _as_flag(d.get(key)) else "0")
            continue
        if key == "ip_limit_steps":
            # Store the parsed form, so a typo cannot reach the worker.
            await set_setting(key, ",".join(str(v) for v in parse_steps(str(d.get(key) or ""))))
            continue
        lo, hi = bounds.get(key, (0, 10 ** 9))
        try:
            value = int(float(str(d.get(key) or "").strip()))
        except ValueError:
            continue
        await set_setting(key, str(max(lo, min(hi, value))))

    # Switching the feature off must be a real undo: release anybody serving a
    # penalty right now instead of leaving them cut until someone notices.
    released = 0
    if was_on and await get_setting("ip_limit_enabled", "0") != "1":
        from core.ip_guard import restore_all
        try:
            released = await restore_all("switched off from the panel")
        except Exception as e:
            logger.warning("ip guard: release on disable failed: %s", e)
    return JSONResponse({"success": True, "released": released})


@app.post(f"/{S}/api/ipguard/release/{{profile_id}}")
async def api_ipguard_release(request: Request, profile_id: int):
    """Let the owner overrule the guard for one customer, right now."""
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.database import (get_ip_guard_state, clear_ip_guard_state,
                               add_ip_guard_event, get_subscription_nodes)
    from core.multi_subscription import set_nodes_enabled

    state = await get_ip_guard_state(int(profile_id))
    if not state:
        return JSONResponse({"success": False, "error": "not found"}, status_code=404)
    nodes = await get_subscription_nodes(int(profile_id))
    if int(state.get("penalty_until") or 0) > int(time.time()) and nodes:
        try:
            await set_nodes_enabled(int(profile_id), True)
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)[:300]}, status_code=502)
    await clear_ip_guard_state(int(profile_id))
    await add_ip_guard_event(int(profile_id), "restored", detail="released by the admin")
    return JSONResponse({"success": True})


@app.post(f"/{S}/api/ipguard/limit/{{profile_id}}")
async def api_ipguard_set_limit(request: Request, profile_id: int):
    """Per-subscription allowance override. 0 puts them back on the default."""
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.database import set_profile_ip_limit
    d = await _node_form_body(request)
    try:
        value = int(float(str(d.get("ip_limit") or 0)))
    except ValueError:
        return JSONResponse({"success": False, "error": "bad value"}, status_code=400)
    await set_profile_ip_limit(int(profile_id), max(0, min(1000, value)))
    return JSONResponse({"success": True, "ip_limit": max(0, min(1000, value))})


# ── shared gateways ──────────────────────────────────────────────────────────
# The list of networks that put many customers behind one address. Detection
# fills it in on its own; these exist so the owner can see the evidence, add a
# network they know about, and overrule one that was learned wrongly.

@app.post(f"/{S}/api/ipguard/gateways")
async def api_ipguard_gateway_add(request: Request):
    """Add a network by hand. Validated here so an unparseable block can never
    reach the loader, where it would be skipped silently every cycle."""
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    import ipaddress
    from core.database import upsert_gateway
    from core.ip_guard import reset_gateways
    d = await _node_form_body(request)
    raw = str(d.get("block") or "").strip()
    try:
        net = ipaddress.ip_network(raw, strict=False)
    except ValueError:
        return JSONResponse({"success": False, "error": "شبکه معتبر نیست. مثال: 31.171.96.0/21"},
                            status_code=400)
    # A very wide block would quietly excuse a whole country. /16 for v4 is
    # already generous for a carrier NAT; anything wider is a mistake.
    if net.version == 4 and net.prefixlen < 16:
        return JSONResponse({"success": False, "error": "بلوک بیش از حد بزرگ است (حداقل /16)"},
                            status_code=400)
    if net.version == 6 and net.prefixlen < 32:
        return JSONResponse({"success": False, "error": "بلوک بیش از حد بزرگ است (حداقل /32)"},
                            status_code=400)
    await upsert_gateway(str(net), source="manual", note=str(d.get("note") or "").strip()[:200])
    reset_gateways()
    return JSONResponse({"success": True, "block": str(net)})


@app.post(f"/{S}/api/ipguard/gateways/toggle")
async def api_ipguard_gateway_toggle(request: Request):
    """Switch one network on or off. The block goes in the BODY, not the path —
    it contains a slash."""
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.database import set_gateway_enabled
    from core.ip_guard import reset_gateways
    d = await _node_form_body(request)
    block = str(d.get("block") or "").strip()
    if not block:
        return JSONResponse({"success": False, "error": "no block"}, status_code=400)
    await set_gateway_enabled(block, _as_flag(d.get("enabled")))
    reset_gateways()
    return JSONResponse({"success": True})


@app.post(f"/{S}/api/ipguard/gateways/delete")
async def api_ipguard_gateway_delete(request: Request):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.database import delete_gateway
    from core.ip_guard import reset_gateways
    d = await _node_form_body(request)
    block = str(d.get("block") or "").strip()
    if not block:
        return JSONResponse({"success": False, "error": "no block"}, status_code=400)
    await delete_gateway(block)
    reset_gateways()
    return JSONResponse({"success": True})


@app.post(f"/{S}/api/ipguard/gateways/scan")
async def api_ipguard_gateway_scan(request: Request):
    """Run detection right now instead of waiting for the next scheduled pass."""
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.ip_guard import detect_gateways
    found = await detect_gateways(
        int(await get_setting("ip_limit_gateway_window_hours", "24") or 24),
        int(await get_setting("ip_limit_gateway_min_users", "2") or 2),
        int(await get_setting("ip_limit_gateway_bits", "24") or 24))
    return JSONResponse({"success": True, "found": found})


# ── SPA catch-all — MUST stay the last route in this file ─────────────────────
# The panel is a hash router, so every real page is `/{S}/#/...`. This exists for
# the paths the OLD server-rendered panel owned (`/{S}/users`, `/{S}/settings`,
# …): admins have those bookmarked, and a 404 would read as "the panel is gone"
# rather than "that page moved". Anything unmatched lands in the SPA instead.
#
# Registered last because FastAPI matches in definition order — declared any
# earlier it would swallow every route defined below it.
@app.get(f"/{S}/{{path:path}}")
async def admin_spa_catch_all(path: str):
    # An unknown /api/ path is a caller bug, not a stale bookmark; answering it
    # with the SPA's HTML would turn a clear 404 into a JSON parse error.
    if path.startswith("api/"):
        return JSONResponse({"error": "not_found"}, status_code=404)
    return await _serve_admin_spa()
