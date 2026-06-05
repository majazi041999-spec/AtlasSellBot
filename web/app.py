"""Atlas Account — Web Admin Panel (FastAPI)

All CSS/JS is embedded directly in HTML templates.
"""

import logging
import os
import re
import shlex
import time
import subprocess
import uuid
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BufferedInputFile
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt

from core.config import (
    CARD_BANK,
    CARD_HOLDER,
    CARD_NUMBER,
    JWT_ALGORITHM,
    JWT_EXPIRE_HOURS,
    JWT_SECRET,
    REFERRAL_BONUS_GB,
    BOT_TOKEN,
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
    get_all_configs,
    get_configs_by_base_email,
    delete_configs_by_base_email,
    get_all_orders,
    get_all_users,
    find_user,
    get_user_orders_full,
    get_user_configs_full,
    get_user_business_stats,
    get_recent_receipt_transactions,
    add_user_balance,
    get_pending_topup_requests,
    get_topup_request,
    update_topup_request,
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
    get_server,
    get_servers,
    get_setting,
    get_stats,
    get_subscription_node_config,
    get_subscription_node_configs,
    get_subscription_profile,
    get_subscription_profiles_full,
    get_subscription_nodes,
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
from core.xui_api import XUIClient, expiry_ms_from_days
from core.renewal import find_and_renew_config
from core.qr import build_qr_image
from bot.keyboards import config_links_kb
from core.update_notes import DEFAULT_UPDATE_BROADCAST_TEXT, get_update_broadcast_text
from core.multi_subscription import render_subscription
from core.multi_subscription import (
    create_profile_for_order,
    multi_sub_enabled_for_single_purchase,
    subscription_error_message,
    renew_subscription_profile,
    subscription_url,
    delete_subscription_profile_remote,
)

logger = logging.getLogger(__name__)

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

_dir = os.path.dirname(os.path.abspath(__file__))
_templates = Jinja2Templates(directory=os.path.join(_dir, "templates"))

S = WEB_SECRET_PATH  # short alias


@app.get("/")
@app.get("/panel")
@app.get("/panel/")
@app.get("/admin")
@app.get("/admin/")
async def easy_panel_entry():
    return RedirectResponse(f"/{S}/login", status_code=302)


@app.get("/health")
async def health_check():
    return JSONResponse({"ok": True, "panel": f"/{S}/login"})


@app.get("/sub/{token}")
async def public_subscription(token: str):
    rendered = await render_subscription(token)
    if not rendered:
        return StreamingResponse(iter([b""]), media_type="text/plain", status_code=404)
    body, info = rendered
    headers = {
        "Subscription-Userinfo": (
            f"upload={info['upload']}; download={info['download']}; "
            f"total={info['total']}; expire={info['expire']}"
        ),
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



# ═══════════════════════════════ AUTH ═══════════════════════════════
def _make_token(username: str) -> str:
    exp = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    return jwt.encode({"sub": username, "exp": exp}, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _verify_token(token: str) -> Optional[str]:
    try:
        p = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return p.get("sub")
    except JWTError:
        return None


def _auth(request: Request) -> Optional[str]:
    return _verify_token(request.cookies.get("_atlas_t", ""))


def _redir_login():
    return RedirectResponse(f"/{S}/login", status_code=302)


def _ctx(request: Request, **kw) -> dict:
    """Build template context with common vars injected."""
    return {"request": request, "S": S, "now_ts": int(time.time()), **kw}


async def _load_ui_settings() -> dict:
    ui: dict = {}
    for key, default in UI_DEFAULTS.items():
        ui[key.split(".", 1)[1]] = await get_setting(key, default)
    ui["custom_css"] = await get_setting("ui.custom_css", CUSTOM_STYLE_DEFAULT)
    ui["custom_js"] = await get_setting("ui.custom_js", CUSTOM_SCRIPT_DEFAULT)
    return ui


async def _ctx_ui(request: Request, **kw) -> dict:
    ctx = _ctx(request, **kw)
    ctx["ui"] = await _load_ui_settings()
    return ctx


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
@app.get(f"/{S}/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return _templates.TemplateResponse("login.html", await _ctx_ui(request))


@app.post(f"/{S}/login")
async def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == WEB_ADMIN_USERNAME and password == WEB_ADMIN_PASSWORD:
        token = _make_token(username)
        r = RedirectResponse(f"/{S}/", status_code=302)
        r.set_cookie(
            "_atlas_t",
            token,
            httponly=True,
            max_age=JWT_EXPIRE_HOURS * 3600,
            samesite="lax",
        )
        return r
    return _templates.TemplateResponse(
        "login.html",
        await _ctx_ui(request, error="نام کاربری یا رمز عبور اشتباه است"),
    )


@app.get(f"/{S}/logout")
async def logout():
    r = RedirectResponse(f"/{S}/login", status_code=302)
    r.delete_cookie("_atlas_t")
    return r


# ═══════════════════════════════ DASHBOARD ══════════════════════════
@app.get(f"/{S}/", response_class=HTMLResponse)
@app.get(f"/{S}/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not _auth(request):
        return _redir_login()
    stats = await get_stats()
    pending = await get_pending_orders()
    pending_update_build = await get_setting("pending_update_build", "")
    last_update_broadcast = await get_setting("last_update_broadcast", "")
    pending_update_text = await get_setting("pending_update_text", DEFAULT_UPDATE_BROADCAST_TEXT)
    return _templates.TemplateResponse(
        "dashboard.html",
        await _ctx_ui(
            request,
            stats=stats,
            pending=pending[:6],
            active="dashboard",
            pending_update_build=pending_update_build,
            last_update_broadcast=last_update_broadcast,
            pending_update_text=pending_update_text,
        ),
    )


@app.post(f"/{S}/updates/approve_send")
async def approve_and_send_update(request: Request, update_text: str = Form("")):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    build = (await get_setting("pending_update_build", "")).strip()
    if not build:
        return RedirectResponse(f"/{S}/dashboard", status_code=302)

    if update_text.strip():
        await set_setting("pending_update_text", update_text.strip())
        await set_setting("pending_update_text_build", build)
    await set_setting("update_broadcast_approved_build", build)
    try:
        sent = await _send_update_broadcast(build)
        logger.info(f"update broadcast approved and sent from panel | build={build} sent={sent}")
    except Exception as e:
        logger.exception("failed to send approved update broadcast: %s", e)

    return RedirectResponse(f"/{S}/dashboard", status_code=302)


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
    return RedirectResponse(f"/{S}/dashboard", status_code=302)


# ═══════════════════════════════ SERVERS ════════════════════════════
@app.get(f"/{S}/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    if not _auth(request):
        return _redir_login()
    today = await snapshot_daily_report()
    reports = await get_recent_daily_reports(60)
    return _templates.TemplateResponse(
        "reports.html",
        await _ctx_ui(request, today=today, reports=reports, active="reports"),
    )


@app.get(f"/{S}/servers", response_class=HTMLResponse)
async def servers_page(request: Request):
    if not _auth(request):
        return _redir_login()
    servers = await get_servers(active_only=False)
    return _templates.TemplateResponse(
        "servers.html",
        await _ctx_ui(request, servers=servers, active="servers"),
    )


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
    return RedirectResponse(f"/{S}/servers", status_code=302)


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
    return RedirectResponse(f"/{S}/servers", status_code=302)


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


# ═════════════════════════════ SUBSCRIPTIONS ═══════════════════════
@app.get(f"/{S}/subs", response_class=HTMLResponse)
async def subscriptions_page(request: Request):
    if not _auth(request):
        return _redir_login()
    nodes = await get_subscription_node_configs(active_only=False)
    for node in nodes:
        node["active_profiles"] = await count_active_subscription_nodes_by_target(node["server_id"], node["inbound_id"])
        status = await subscription_node_config_status(node)
        node["usable"] = status["usable"]
        node["usable_label"] = status["label"]
        node["usable_reason"] = status["reason"]
    settings = {
        "multi_sub_enabled": await get_setting("multi_sub_enabled", SETTINGS_DEFAULTS["multi_sub_enabled"]),
        "multi_sub_node_count": await get_setting("multi_sub_node_count", SETTINGS_DEFAULTS["multi_sub_node_count"]),
        "multi_sub_min_nodes": await get_setting("multi_sub_min_nodes", SETTINGS_DEFAULTS["multi_sub_min_nodes"]),
        "public_base_url": await get_setting("public_base_url", ""),
        "sub_info_enabled": await get_setting("sub_info_enabled", SETTINGS_DEFAULTS["sub_info_enabled"]),
        "sub_info_sync_on_render": await get_setting("sub_info_sync_on_render", SETTINGS_DEFAULTS["sub_info_sync_on_render"]),
        "sub_info_template": await get_setting("sub_info_template", SETTINGS_DEFAULTS["sub_info_template"]),
        "sub_brand_template": await get_setting("sub_brand_template", SETTINGS_DEFAULTS["sub_brand_template"]),
    }
    return _templates.TemplateResponse(
        "subscriptions.html",
        await _ctx_ui(
            request,
            active="subs",
            nodes=nodes,
            servers=await get_servers(active_only=False),
            settings=settings,
            saved=request.query_params.get("saved", "") == "1",
        ),
    )


@app.get(f"/{S}/subs/profiles", response_class=HTMLResponse)
async def subscription_profiles_page(request: Request):
    if not _auth(request):
        return _redir_login()
    page = max(1, int(request.query_params.get("page", "1") or 1))
    per_page = 40
    profiles_all = await get_subscription_profiles_full(limit=1000)
    for profile in profiles_all:
        try:
            profile["url"] = await subscription_url(profile["token"])
        except Exception:
            profile["url"] = f"/sub/{profile['token']}"
    total = len(profiles_all)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    profiles = profiles_all[(page - 1) * per_page: page * per_page]
    return _templates.TemplateResponse(
        "subscription_profiles.html",
        await _ctx_ui(request, profiles=profiles, total=total, page=page, total_pages=total_pages, active="subs"),
    )


@app.post(f"/{S}/subs/profiles/{{profile_id}}/toggle")
async def subscription_profile_toggle(request: Request, profile_id: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    profile = await get_subscription_profile(profile_id)
    if not profile:
        return JSONResponse({"success": False, "error": "not found"}, status_code=404)
    from core.database import update_subscription_profile
    next_active = 0 if int(profile.get("is_active") or 0) else 1
    await update_subscription_profile(profile_id, is_active=next_active)
    return JSONResponse({"success": True, "is_active": bool(next_active)})


@app.post(f"/{S}/subs/profiles/{{profile_id}}/delete")
async def subscription_profile_delete(request: Request, profile_id: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    profile = await get_subscription_profile(profile_id)
    if not profile:
        return JSONResponse({"success": False, "error": "not found"}, status_code=404)
    result = await delete_subscription_profile_remote(profile_id)
    return JSONResponse({"success": True, **result})


@app.post(f"/{S}/subs/settings")
async def subscriptions_settings_save(
    request: Request,
    multi_sub_enabled: str = Form("0"),
    multi_sub_node_count: int = Form(4),
    multi_sub_min_nodes: int = Form(2),
    public_base_url: str = Form(""),
    sub_info_enabled: str = Form("0"),
    sub_info_sync_on_render: str = Form("0"),
    sub_info_template: str = Form(""),
    sub_brand_template: str = Form(""),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    node_count = max(2, min(8, int(multi_sub_node_count or 4)))
    min_nodes = max(2, min(node_count, int(multi_sub_min_nodes or 2)))
    await set_setting("multi_sub_enabled", "1" if multi_sub_enabled == "1" else "0")
    await set_setting("multi_sub_node_count", str(node_count))
    await set_setting("multi_sub_min_nodes", str(min_nodes))
    await set_setting("public_base_url", public_base_url.strip().rstrip("/"))
    await set_setting("sub_info_enabled", "1" if sub_info_enabled == "1" else "0")
    await set_setting("sub_info_sync_on_render", "1" if sub_info_sync_on_render == "1" else "0")
    await set_setting("sub_info_template", sub_info_template.strip() or SETTINGS_DEFAULTS["sub_info_template"])
    await set_setting("sub_brand_template", sub_brand_template.strip() or SETTINGS_DEFAULTS["sub_brand_template"])
    return RedirectResponse(f"/{S}/subs?saved=1", status_code=302)


@app.post(f"/{S}/subs/nodes/add")
async def subscription_node_add(
    request: Request,
    server_id: int = Form(...),
    inbound_id: int = Form(...),
    label: str = Form(""),
    priority: int = Form(100),
    max_active_profiles: int = Form(0),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await add_subscription_node_config(server_id, inbound_id, label.strip(), priority, max_active_profiles)
    return RedirectResponse(f"/{S}/subs?saved=1", status_code=302)


@app.post(f"/{S}/subs/nodes/{{node_id}}/edit")
async def subscription_node_edit(
    request: Request,
    node_id: int,
    server_id: int = Form(...),
    inbound_id: int = Form(...),
    label: str = Form(""),
    priority: int = Form(100),
    max_active_profiles: int = Form(0),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await update_subscription_node_config(
        node_id,
        server_id=int(server_id),
        inbound_id=int(inbound_id),
        label=label.strip(),
        priority=int(priority or 100),
        max_active_profiles=int(max_active_profiles or 0),
    )
    return RedirectResponse(f"/{S}/subs?saved=1", status_code=302)


@app.post(f"/{S}/subs/nodes/{{node_id}}/toggle")
async def subscription_node_toggle(request: Request, node_id: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    node = await get_subscription_node_config(node_id)
    if not node:
        return JSONResponse({"success": False, "error": "not found"}, status_code=404)
    await update_subscription_node_config(node_id, is_active=0 if int(node.get("is_active") or 0) else 1)
    return JSONResponse({"success": True})


@app.post(f"/{S}/subs/nodes/{{node_id}}/delete")
async def subscription_node_delete(request: Request, node_id: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await delete_subscription_node_config(node_id)
    return JSONResponse({"success": True})


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
        return JSONResponse({"success": bool(inbound), "msg": "ok" if inbound else "inbound not found"})
    finally:
        await cli.close()


# ═══════════════════════════════ PACKAGES ═══════════════════════════
@app.get(f"/{S}/packages", response_class=HTMLResponse)
async def packages_page(request: Request):
    if not _auth(request):
        return _redir_login()
    page = max(1, int(request.query_params.get("page", "1") or 1))
    per_page = 20
    pkgs_all = await get_packages(active_only=False)
    total = len(pkgs_all)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    pkgs = pkgs_all[start:start + per_page]
    servers = await get_servers(active_only=False)
    return _templates.TemplateResponse(
        "packages.html",
        await _ctx_ui(request, packages=pkgs, total=total, page=page, total_pages=total_pages, servers=servers, active="packages"),
    )


@app.post(f"/{S}/packages/add")
async def pkg_add(
    request: Request,
    name: str = Form(...),
    traffic_gb: float = Form(...),
    duration_days: int = Form(...),
    price: int = Form(...),
    description: str = Form(""),
    inbound_id: int = Form(0),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await add_package(name, traffic_gb, duration_days, price, description, inbound_id=inbound_id)
    return RedirectResponse(f"/{S}/packages", status_code=302)


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
    )
    return RedirectResponse(f"/{S}/packages", status_code=302)


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


# ═══════════════════════════════ ORDERS ═════════════════════════════
@app.get(f"/{S}/orders", response_class=HTMLResponse)
async def orders_page(request: Request):
    if not _auth(request):
        return _redir_login()
    page = max(1, int(request.query_params.get("page", "1") or 1))
    per_page = 30
    orders_all = await get_all_orders(1000)
    total = len(orders_all)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    orders = orders_all[start:start + per_page]
    pending = await get_pending_orders()
    return _templates.TemplateResponse(
        "orders.html",
        await _ctx_ui(request, orders=orders, total=total, page=page, total_pages=total_pages, pending_count=len(pending), active="orders"),
    )


@app.post(f"/{S}/orders/{{oid}}/reject")
async def order_reject_web(request: Request, oid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    order = await get_order(oid)
    if not order:
        return RedirectResponse(f"/{S}/orders", status_code=302)
    await update_order(oid, status="rejected")
    await _clear_review_buttons("order", oid)
    return RedirectResponse(f"/{S}/orders", status_code=302)


@app.post(f"/{S}/orders/{{oid}}/approve")
async def order_approve_web(request: Request, oid: int):
    try:
        return await _order_approve_web_impl(request, oid)
    except Exception as e:
        logger.exception("order approve failed oid=%s: %s", oid, e)
        await release_order_processing(oid)
        return RedirectResponse(f"/{S}/orders", status_code=302)


async def _order_approve_web_impl(request: Request, oid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    order = await get_order(oid)
    if not order:
        return RedirectResponse(f"/{S}/orders", status_code=302)
    if order.get("status") == "approved":
        return RedirectResponse(f"/{S}/orders", status_code=302)
    if order.get("status") not in ("receipt_submitted", "processing"):
        return RedirectResponse(f"/{S}/orders", status_code=302)
    if not await claim_order_for_approval(oid):
        return RedirectResponse(f"/{S}/orders", status_code=302)

    if int(order.get("renew_config_id") or 0) > 0:
        cfg = await get_config(int(order["renew_config_id"]))
        if not cfg:
            await update_order(oid, status="receipt_submitted")
            return RedirectResponse(f"/{S}/orders", status_code=302)

        duration = int(order.get("duration_days") or cfg.get("duration_days") or 0)
        traffic_gb = float(order.get("traffic_gb") or cfg.get("traffic_gb") or 0)
        result = await find_and_renew_config(cfg, traffic_gb, duration)
        if not result.get("ok"):
            await update_order(oid, status="receipt_submitted")
            return RedirectResponse(f"/{S}/orders", status_code=302)

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
        return RedirectResponse(f"/{S}/orders", status_code=302)

    if int(order.get("renew_sub_profile_id") or 0) > 0:
        profile = await get_subscription_profile(int(order["renew_sub_profile_id"]))
        if not profile:
            await update_order(oid, status="receipt_submitted")
            return RedirectResponse(f"/{S}/orders", status_code=302)
        duration = int(order.get("duration_days") or profile.get("duration_days") or 0)
        traffic_gb = float(order.get("traffic_gb") or profile.get("traffic_gb") or 0)
        result = await renew_subscription_profile(profile, traffic_gb, duration)
        if not result.get("ok"):
            await update_order(oid, status="receipt_submitted", notes=((order.get("notes") or "") + f"\nsub_renew_error={result.get('error') or ''}").strip())
            return RedirectResponse(f"/{S}/orders", status_code=302)
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
        return RedirectResponse(f"/{S}/orders", status_code=302)

    user = await get_user_by_telegram(order["telegram_id"])
    if not user:
        await update_order(oid, status="receipt_submitted")
        return RedirectResponse(f"/{S}/orders", status_code=302)

    bulk_count = int(order.get("bulk_count") or 1)
    each_gb = float(order.get("bulk_each_gb") or order["traffic_gb"])
    duration = int(order["duration_days"])
    if await multi_sub_enabled_for_single_purchase(bulk_count=bulk_count, is_renewal=False):
        sub_result = await create_profile_for_order(user, order, each_gb, duration)
        if sub_result.get("ok"):
            await update_order(
                oid,
                status="approved",
                server_id=0,
                config_email=sub_result["email"],
                inbound_id=0,
                approved_at=datetime.now().isoformat(),
            )
            if order.get("referred_by"):
                referrer = await get_user_by_id(order["referred_by"])
                if referrer:
                    await update_user(
                        referrer["id"],
                        referral_bonus_gb=float(referrer.get("referral_bonus_gb") or 0) + REFERRAL_BONUS_GB,
                    )
            await _clear_review_buttons("order", oid)
            if BOT_TOKEN and len(BOT_TOKEN) > 20:
                bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
                try:
                    sub_url = sub_result["url"]
                    await bot.send_message(
                        order["telegram_id"],
                        "🎉 سرویس آزمایشی چندسروره شما فعال شد.\n\n"
                        f"تعداد سرورها: {sub_result['nodes']}\n"
                        f"حجم کل مشترک: {each_gb} GB\n"
                        f"مدت: {duration} روز\n\n"
                        f"لینک سابسکریپشن:\n{sub_url}",
                        parse_mode=None,
                        reply_markup=config_links_kb("", sub_url),
                    )
                    qr = build_qr_image(sub_url, footer_text=await get_setting("channel_username", "AtlasChannel"))
                    await bot.send_photo(order["telegram_id"], BufferedInputFile(qr.getvalue(), filename="atlas-sub.png"), caption="QR سابسکریپشن چندسروره", parse_mode=None)
                finally:
                    await bot.session.close()
            return RedirectResponse(f"/{S}/orders", status_code=302)
        notes = ((order.get("notes") or "") + f"\nmulti_sub_error={sub_result.get('error', '')}").strip()
        await update_order(oid, status="receipt_submitted", notes=notes)
        logger.warning("Multi-sub creation failed for order %s: %s", oid, subscription_error_message(sub_result.get("error", "")))
        return RedirectResponse(f"/{S}/orders", status_code=302)

    servers = [sv for sv in await get_servers() if await server_has_capacity(sv["id"])]
    if not servers:
        await update_order(oid, status="receipt_submitted")
        return RedirectResponse(f"/{S}/orders", status_code=302)
    suggested = await get_least_loaded_server() if await get_setting("auto_least_loaded_server", "0") == "1" else None
    sid = int((suggested or servers[0])["id"])
    server = await get_server(sid)

    created = []
    bonus_pending = 0.0
    bonus_applied = 0.0
    if not int(order.get("referral_bonus_applied") or 0):
        bonus_pending = max(0.0, float(user.get("referral_bonus_gb") or 0))
    is_first_purchase = not await has_previous_purchase(user["id"])

    cli = XUIClient(server["url"], server["username"], server["password"], server["sub_path"], server.get("api_token", ""))
    target_inbound = int(server.get("inbound_id") or 1)
    suffix = "".join(ch for ch in (order.get("custom_config_name") or "").strip() if ch.isalnum() or ch in ("_", "-", "."))[:24]
    for i in range(1, max(1, bulk_count) + 1):
        base_email = f"u{order['telegram_id']}_{i}_{int(time.time())}" if bulk_count > 1 else f"u{order['telegram_id']}_{int(time.time())}"
        email = f"{base_email}_{suffix}" if suffix else base_email
        cuuid = str(uuid.uuid4())
        config_gb = each_gb + bonus_pending if bonus_pending > 0 else each_gb
        ok = await cli.add_client(target_inbound, cuuid, email, config_gb, duration, starts_on_first_use=False)
        if not ok:
            continue
        if bonus_pending > 0:
            bonus_applied = bonus_pending
            bonus_pending = 0.0
        link = await cli.get_client_link(target_inbound, email)
        sub = await cli.get_subscription_link(target_inbound, email)
        await save_config(user["id"], sid, cuuid, email, target_inbound, config_gb, duration, expiry_ms_from_days(duration), starts_on_first_use=0)
        created.append((email, link, sub, config_gb))
    await cli.close()

    if created:
        await update_order(oid, status="approved", server_id=sid, config_email=created[0][0], inbound_id=target_inbound, approved_at=datetime.now().isoformat())
        if bonus_applied > 0:
            await update_user(user["id"], referral_bonus_gb=0)
            await update_order(oid, referral_bonus_applied=1)
        await _clear_review_buttons("order", oid)
        if is_first_purchase and order.get("referred_by"):
            referrer = await get_user_by_id(order["referred_by"])
            if referrer:
                await update_user(
                    referrer["id"],
                    referral_bonus_gb=float(referrer.get("referral_bonus_gb") or 0) + REFERRAL_BONUS_GB,
                )
        if BOT_TOKEN and len(BOT_TOKEN) > 20:
            bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
            try:
                await bot.send_message(
                    order["telegram_id"],
                    f"🎉 *سرویس شما فعال شد!*\n\nسفارش: {order['pkg_name']}\nسرور: {server['name']}\nتعداد کانفیگ: `{len(created)}`",
                    parse_mode=None,
                )
                if bonus_applied > 0:
                    await bot.send_message(
                        order["telegram_id"],
                        f"🎁 هدیه رفرال شما اعمال شد: {bonus_applied:g} GB روی اولین کانفیگ",
                        parse_mode=None,
                    )
                for email, link, sub, _traffic_gb in created[:20]:
                    txt = f"📧 `{email}`\n"
                    if link:
                        txt += f"🔗 `{link}`\n"
                    if sub:
                        txt += f"📡 Subscription:\n`{sub}`\n"
                    await bot.send_message(
                        order["telegram_id"],
                        txt,
                        parse_mode=None,
                        reply_markup=config_links_kb(link or "", sub or ""),
                    )
                    if link:
                        try:
                            qr = build_qr_image(link, footer_text=await get_setting("channel_username", "AtlasChannel"))
                            await bot.send_photo(
                                order["telegram_id"],
                                BufferedInputFile(qr.getvalue(), filename="atlas-qr.png"),
                                caption=f"QR: {email}",
                                parse_mode=None,
                            )
                        except Exception:
                            pass
            finally:
                await bot.session.close()
    else:
        await update_order(oid, status="receipt_submitted")
    return RedirectResponse(f"/{S}/orders", status_code=302)


# ═══════════════════════════════ CONFIGS ════════════════════════════
@app.get(f"/{S}/configs", response_class=HTMLResponse)
async def configs_page(request: Request):
    if not _auth(request):
        return _redir_login()
    page = max(1, int(request.query_params.get("page", "1") or 1))
    per_page = 30
    raw = await get_all_configs()
    grouped = {}
    for c in raw:
        base = (c.get("email") or "").split("_m")[0]
        g = grouped.setdefault(base, {**c, "history_count": 0, "history_servers": []})
        g["history_count"] += 1
        if c.get("server_name") and c["server_name"] not in g["history_servers"]:
            g["history_servers"].append(c["server_name"])
        if c.get("is_active") and not g.get("is_active"):
            g.update(c)
    configs_all = list(grouped.values())
    total = len(configs_all)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    configs = configs_all[start:start + per_page]
    return _templates.TemplateResponse(
        "configs.html",
        await _ctx_ui(request, configs=configs, total=total, page=page, total_pages=total_pages, active="configs"),
    )


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


# ═══════════════════════════════ USERS ══════════════════════════════
@app.get(f"/{S}/users", response_class=HTMLResponse)
async def users_page(request: Request):
    if not _auth(request):
        return _redir_login()
    page = max(1, int(request.query_params.get("page", "1") or 1))
    per_page = 50
    total = await count_users()
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    users = await get_all_users((page - 1) * per_page, per_page)
    for u in users:
        u["business"] = await get_user_business_stats(u["id"])
    wholesale_users = await get_wholesale_users(200)
    for u in wholesale_users:
        u["business"] = await get_user_business_stats(u["id"])
    wholesale_stats = {
        "active": sum(1 for u in wholesale_users if u.get("is_wholesale")),
        "pending": sum(1 for u in wholesale_users if u.get("wholesale_request_pending")),
        "approved_orders": sum(int((u.get("business") or {}).get("approved_orders") or 0) for u in wholesale_users),
        "active_configs": sum(int((u.get("business") or {}).get("active_configs") or 0) for u in wholesale_users),
    }
    pending_topups = await get_pending_topup_requests(200)
    return _templates.TemplateResponse(
        "users.html",
        await _ctx_ui(
            request,
            users=users,
            wholesale_users=wholesale_users,
            wholesale_stats=wholesale_stats,
            pending_topups=pending_topups,
            total=total,
            page=page,
            total_pages=total_pages,
            active="users",
        ),
    )


@app.get(f"/{S}/users/find")
async def user_find_page(request: Request, q: str = ""):
    if not _auth(request):
        return _redir_login()
    user = await find_user(q)
    if user:
        return RedirectResponse(f"/{S}/users/{user['id']}", status_code=302)
    return RedirectResponse(f"/{S}/users?not_found=1", status_code=302)


@app.get(f"/{S}/users/{{uid}}", response_class=HTMLResponse)
async def user_detail_page(request: Request, uid: int):
    if not _auth(request):
        return _redir_login()
    user = await get_user_by_id(uid)
    if not user:
        return RedirectResponse(f"/{S}/users?not_found=1", status_code=302)
    orders = await get_user_orders_full(uid, 300)
    configs = await get_user_configs_full(uid)
    profiles = await get_subscription_profiles_full(uid, 300)
    for profile in profiles:
        profile["nodes"] = await get_subscription_nodes(profile["id"])
        try:
            profile["url"] = await subscription_url(profile["token"])
        except Exception:
            profile["url"] = ""
    business = await get_user_business_stats(uid)
    return _templates.TemplateResponse(
        "user_detail.html",
        await _ctx_ui(
            request,
            user=user,
            orders=orders,
            configs=configs,
            profiles=profiles,
            business=business,
            active="users",
        ),
    )


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


@app.post(f"/{S}/users/{{uid}}/admin_role")
async def user_set_admin_role(request: Request, uid: int, role: str = Form("none")):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    role = (role or "none").strip().lower()
    valid = {"none", "finance", "full"}
    if role not in valid:
        role = "none"
    from core.database import update_user
    await update_user(uid, is_admin=0 if role == "none" else 1, admin_role=role)
    return RedirectResponse(f"/{S}/users", status_code=302)


@app.post(f"/{S}/users/transfer_owner")
async def transfer_owner(request: Request, telegram_id: int = Form(...)):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.database import get_user_by_telegram, set_setting, update_user

    user = await get_user_by_telegram(telegram_id)
    if not user:
        return RedirectResponse(f"/{S}/users?owner_error=1", status_code=302)
    await update_user(user["id"], is_admin=1, admin_role="full")
    await set_setting("owner_admin_id", str(telegram_id))
    return RedirectResponse(f"/{S}/users?owner_ok=1", status_code=302)
@app.post(f"/{S}/users/{{uid}}/balance_adjust")
async def user_balance_adjust(request: Request, uid: int, amount: int = Form(...), note: str = Form("manual")):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    amount = int(amount or 0)
    if amount == 0:
        return RedirectResponse(f"/{S}/users", status_code=302)
    await add_user_balance(uid, amount, kind="manual", note=(note or "manual"), actor_telegram_id=0)
    return RedirectResponse(f"/{S}/users", status_code=302)


@app.post(f"/{S}/topups/{{rid}}/approve")
async def topup_approve_web(request: Request, rid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    req = await get_topup_request(rid)
    if req and req.get("status") == "pending":
        await add_user_balance(req["user_id"], int(req["amount"]), kind="topup", note=f"topup_request:{rid}", actor_telegram_id=0)
        await update_topup_request(rid, status="approved", reviewer_telegram_id=0, reviewed_at=datetime.now().isoformat())
        await _clear_review_buttons("topup", rid)
    return RedirectResponse(f"/{S}/users", status_code=302)


@app.post(f"/{S}/topups/{{rid}}/reject")
async def topup_reject_web(request: Request, rid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    req = await get_topup_request(rid)
    if req and req.get("status") == "pending":
        await update_topup_request(rid, status="rejected", reviewer_telegram_id=0, reviewed_at=datetime.now().isoformat(), admin_note="rejected_web")
        await _clear_review_buttons("topup", rid)
    return RedirectResponse(f"/{S}/users", status_code=302)


@app.post(f"/{S}/users/{{uid}}/pricing")
async def user_set_pricing(
    request: Request,
    uid: int,
    discount_percent: float = Form(0),
    price_per_gb: int = Form(0),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    discount_percent = max(0, min(100, float(discount_percent)))
    price_per_gb = max(0, int(price_per_gb))

    from core.database import update_user  # local import

    await update_user(uid, discount_percent=discount_percent, price_per_gb=price_per_gb)
    return RedirectResponse(f"/{S}/users", status_code=302)


# ═══════════════════════════════ TRANSACTIONS ═══════════════════════
@app.get(f"/{S}/transactions", response_class=HTMLResponse)
async def transactions_page(request: Request):
    if not _auth(request):
        return _redir_login()
    txs = await get_recent_receipt_transactions(200)
    return _templates.TemplateResponse(
        "transactions.html",
        await _ctx_ui(request, transactions=txs, active="transactions"),
    )


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
@app.get(f"/{S}/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    if not _auth(request):
        return _redir_login()

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
        "test_account_enabled": await get_setting("test_account_enabled", SETTINGS_DEFAULTS["test_account_enabled"]),
        "test_account_traffic_gb": await get_setting("test_account_traffic_gb", SETTINGS_DEFAULTS["test_account_traffic_gb"]),
        "test_account_duration_days": await get_setting("test_account_duration_days", SETTINGS_DEFAULTS["test_account_duration_days"]),
        "test_account_server_id": await get_setting("test_account_server_id", SETTINGS_DEFAULTS["test_account_server_id"]),
        "test_account_prefix": await get_setting("test_account_prefix", SETTINGS_DEFAULTS["test_account_prefix"]),
        "panel_domain": await get_setting("panel_domain", ""),
        "cert_email": await get_setting("cert_email", ""),
        "atlas_tls_https_port": await get_setting("atlas_tls_https_port", "443"),
        "cert_status": await get_setting("cert_status", ""),
    }

    # ✅ کارت بانکی از دیتابیس Settings خوانده می‌شود (با fallback از .env)
    settings["card_number"] = await get_setting("card_number", CARD_NUMBER)
    settings["card_holder"] = await get_setting("card_holder", CARD_HOLDER)
    settings["card_bank"] = await get_setting("card_bank", CARD_BANK)

    settings["referral_bonus_gb"] = REFERRAL_BONUS_GB

    servers = await get_servers(active_only=False)
    saved = request.query_params.get("saved")
    cert_result = request.query_params.get("cert")
    return _templates.TemplateResponse(
        "settings.html",
        await _ctx_ui(request, settings=settings, servers=servers, saved=saved, cert_result=cert_result, active="settings"),
    )


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
    test_account_enabled: str = Form("0"),
    test_account_traffic_gb: float = Form(1),
    test_account_duration_days: int = Form(1),
    test_account_server_id: str = Form("0"),
    test_account_prefix: str = Form("test"),
    # ✅ کارت بانکی از پنل ذخیره می‌شود
    card_number: str = Form(""),
    card_holder: str = Form(""),
    card_bank: str = Form(""),
    panel_domain: str = Form(""),
    cert_email: str = Form(""),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

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
    await set_setting("multi_sub_enabled", "1" if multi_sub_enabled == "1" else "0")
    await set_setting("multi_sub_node_count", str(max(2, min(8, int(multi_sub_node_count or 4)))))
    await set_setting("multi_sub_min_nodes", str(max(2, min(8, int(multi_sub_min_nodes or 2)))))
    await set_setting("public_base_url", public_base_url.strip().rstrip("/"))
    await set_setting("test_account_enabled", "1" if test_account_enabled == "1" else "0")
    await set_setting("test_account_traffic_gb", str(max(0.1, float(test_account_traffic_gb or 1))))
    await set_setting("test_account_duration_days", str(max(1, int(test_account_duration_days or 1))))
    await set_setting("test_account_server_id", test_account_server_id if test_account_server_id in valid_server_ids else "0")
    clean_test_prefix = "".join(ch for ch in (test_account_prefix or "test").strip() if ch.isalnum() or ch in ("_", "-"))[:16] or "test"
    await set_setting("test_account_prefix", clean_test_prefix)

    # ✅ ذخیره کارت
    await set_setting("card_number", card_number.strip())
    await set_setting("card_holder", card_holder.strip())
    await set_setting("card_bank", card_bank.strip())
    await set_setting("panel_domain", panel_domain.strip().lower())
    await set_setting("cert_email", cert_email.strip().lower())

    return RedirectResponse(f"/{S}/settings?saved=1", status_code=302)


@app.post(f"/{S}/settings/certificate/apply")
async def settings_apply_certificate(request: Request):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    form = await request.form()
    raw_domain = str(form.get("panel_domain") or form.get("public_base_url") or await get_setting("panel_domain", ""))
    domain = _clean_domain(raw_domain)
    email = str(form.get("cert_email") or await get_setting("cert_email", "")).strip().lower()
    try:
        https_port = int(form.get("atlas_tls_https_port") or await get_setting("atlas_tls_https_port", "443") or 443)
    except (TypeError, ValueError):
        https_port = 443
    https_port = max(1, min(65535, https_port))
    if https_port in {80, WEB_PORT}:
        await set_setting("cert_status", f"❌ پورت HTTPS انتخابی ({https_port}) مناسب نیست؛ با پورت 80 یا پورت داخلی ربات تداخل دارد.")
        return RedirectResponse(f"/{S}/settings?cert=error", status_code=302)
    if not domain:
        await set_setting("cert_status", "❌ دامنه معتبر نیست. مثال درست: sm.example.com")
        return RedirectResponse(f"/{S}/settings?cert=error", status_code=302)

    try:
        script = _atlas_tls_proxy_script(domain, email, WEB_PORT, https_port)
        cmd = ["bash", "-lc", script]
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            cmd = ["sudo", "-n", "bash", "-lc", script]
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=600,
        )
        await set_setting("panel_domain", domain)
        await set_setting("cert_email", email)
        await set_setting("atlas_tls_https_port", str(https_port))
        public_url = f"https://{domain}" if https_port == 443 else f"https://{domain}:{https_port}"
        await set_setting("public_base_url", public_url)
        await set_setting(
            "cert_status",
            f"✅ SSL و Nginx برای Atlas فعال شد | لینک عمومی ساب: {public_url} | پورت داخلی ربات: {WEB_PORT}",
        )
        return RedirectResponse(f"/{S}/settings?cert=ok", status_code=302)
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or str(e)).strip()[-900:]
        await set_setting(
            "cert_status",
            "❌ خطا در نصب SSL/Nginx. مطمئن شوید DNS روی IP همین سرور و حالت DNS Only است، پورت‌های 80 و 443 بازند، "
            f"و سرویس با دسترسی root اجرا می‌شود. جزئیات: {detail}",
        )
        return RedirectResponse(f"/{S}/settings?cert=error", status_code=302)
    except Exception as e:
        await set_setting("cert_status", f"❌ خطا در دریافت/اعمال گواهی Atlas: {e}")
        return RedirectResponse(f"/{S}/settings?cert=error", status_code=302)




@app.post(f"/{S}/settings/legacy_sync/reset")
async def settings_reset_legacy_sync(request: Request):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    deleted = await reset_legacy_claims()
    return JSONResponse({"success": True, "deleted": deleted})


# ═══════════════════════════════ ROOT ═══════════════════════════════
@app.get("/")
async def root():
    return RedirectResponse(f"/{S}/login", status_code=302)
