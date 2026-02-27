"""Atlas Account — Web Admin Panel (FastAPI)

All CSS/JS is embedded directly in HTML templates.
"""

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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
    WEB_ADMIN_PASSWORD,
    WEB_ADMIN_USERNAME,
    WEB_SECRET_PATH,
)
from core.database import (
    add_package,
    add_server,
    count_users,
    delete_package,
    delete_server,
    get_all_configs,
    get_all_orders,
    get_all_users,
    get_user_business_stats,
    get_config,
    get_order,  # noqa: F401
    get_package,
    get_packages,
    get_pending_orders,
    get_server,
    get_servers,
    get_setting,
    get_stats,
    init_db,
    set_setting,
    update_config,
    update_order,  # noqa: F401
    update_package,
    update_server,
    reset_legacy_claims,
)
from core.panel_content import (
    BOT_TEXT_DEFAULTS,
    CUSTOM_SCRIPT_DEFAULT,
    CUSTOM_STYLE_DEFAULT,
    SETTINGS_DEFAULTS,
    UI_DEFAULTS,
)
from core.xui_api import XUIClient

logger = logging.getLogger(__name__)

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

_dir = os.path.dirname(os.path.abspath(__file__))
_templates = Jinja2Templates(directory=os.path.join(_dir, "templates"))

S = WEB_SECRET_PATH  # short alias


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
    return _templates.TemplateResponse(
        "dashboard.html",
        await _ctx_ui(request, stats=stats, pending=pending[:6], active="dashboard"),
    )


# ═══════════════════════════════ SERVERS ════════════════════════════
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
    sub_path: str = Form(""),
    inbound_id: int = Form(1),
    inbound_ids: str = Form(""),
    note: str = Form(""),
    max_active_configs: int = Form(0),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    sid = await add_server(name, url.rstrip("/"), username, password, sub_path.strip("/"), inbound_id, note, inbound_ids=inbound_ids)
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
    name: str = Form(...),
    url: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    sub_path: str = Form(""),
    inbound_id: int = Form(1),
    inbound_ids: str = Form(""),
    note: str = Form(""),
    max_active_configs: int = Form(0),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await update_server(
        sid,
        name=name,
        url=url.rstrip("/"),
        username=username,
        password=password,
        sub_path=sub_path.strip("/"),
        inbound_id=inbound_id,
        note=note,
        inbound_ids=inbound_ids,
        max_active_configs=max_active_configs,
    )
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
    cli = XUIClient(srv["url"], srv["username"], srv["password"], srv["sub_path"])
    ok = await cli.test_connection()
    await cli.close()
    return JSONResponse({"success": ok})


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
    cli = XUIClient(srv["url"], srv["username"], srv["password"], srv["sub_path"])
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
    return _templates.TemplateResponse(
        "users.html",
        await _ctx_ui(request, users=users, total=total, page=page, total_pages=total_pages, active="users"),
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
        "legacy_sync_enabled": await get_setting("legacy_sync_enabled", SETTINGS_DEFAULTS["legacy_sync_enabled"]),
    }

    # ✅ کارت بانکی از دیتابیس Settings خوانده می‌شود (با fallback از .env)
    settings["card_number"] = await get_setting("card_number", CARD_NUMBER)
    settings["card_holder"] = await get_setting("card_holder", CARD_HOLDER)
    settings["card_bank"] = await get_setting("card_bank", CARD_BANK)

    settings["referral_bonus_gb"] = REFERRAL_BONUS_GB

    servers = await get_servers(active_only=False)
    saved = request.query_params.get("saved")
    return _templates.TemplateResponse(
        "settings.html",
        await _ctx_ui(request, settings=settings, servers=servers, saved=saved, active="settings"),
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
    legacy_sync_enabled: str = Form("1"),
    # ✅ کارت بانکی از پنل ذخیره می‌شود
    card_number: str = Form(""),
    card_holder: str = Form(""),
    card_bank: str = Form(""),
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
    await set_setting("legacy_sync_enabled", "1" if legacy_sync_enabled == "1" else "0")

    # ✅ ذخیره کارت
    await set_setting("card_number", card_number.strip())
    await set_setting("card_holder", card_holder.strip())
    await set_setting("card_bank", card_bank.strip())

    return RedirectResponse(f"/{S}/settings?saved=1", status_code=302)


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
