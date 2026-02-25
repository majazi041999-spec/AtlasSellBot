"""
Atlas Account — Web Admin Panel (FastAPI)
All CSS/JS is embedded directly in HTML templates.
"""
import time
import logging
from typing import Optional

from fastapi import FastAPI, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from jose import jwt, JWTError
from datetime import datetime, timedelta
import os

from core.config import (
    WEB_SECRET_PATH, WEB_ADMIN_USERNAME, WEB_ADMIN_PASSWORD,
    JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_HOURS
)
from core.database import (
    get_servers, get_server, add_server, update_server, delete_server,
    get_packages, get_package, add_package, update_package, delete_package,
    get_all_users, count_users,
    get_pending_orders, get_all_orders, get_order, update_order,
    get_all_configs, get_config, update_config,
    get_stats, get_setting, set_setting
)
from core.xui_api import XUIClient

logger = logging.getLogger(__name__)

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

_dir = os.path.dirname(os.path.abspath(__file__))
_templates = Jinja2Templates(directory=os.path.join(_dir, "templates"))

S = WEB_SECRET_PATH  # short alias


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


# ═══════════════════════════════ AUTH ROUTES ════════════════════════

@app.get(f"/{S}/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return _templates.TemplateResponse("login.html", _ctx(request))


@app.post(f"/{S}/login")
async def login_post(request: Request,
                     username: str = Form(...), password: str = Form(...)):
    if username == WEB_ADMIN_USERNAME and password == WEB_ADMIN_PASSWORD:
        token = _make_token(username)
        r = RedirectResponse(f"/{S}/", status_code=302)
        r.set_cookie("_atlas_t", token, httponly=True,
                     max_age=JWT_EXPIRE_HOURS * 3600, samesite="lax")
        return r
    return _templates.TemplateResponse("login.html",
                                       _ctx(request, error="نام کاربری یا رمز عبور اشتباه است"))


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
    return _templates.TemplateResponse("dashboard.html",
                                       _ctx(request, stats=stats, pending=pending[:6], active="dashboard"))


# ═══════════════════════════════ SERVERS ════════════════════════════

@app.get(f"/{S}/servers", response_class=HTMLResponse)
async def servers_page(request: Request):
    if not _auth(request):
        return _redir_login()
    servers = await get_servers(active_only=False)
    return _templates.TemplateResponse("servers.html",
                                       _ctx(request, servers=servers, active="servers"))


@app.post(f"/{S}/servers/add")
async def server_add(request: Request,
                     name: str = Form(...), url: str = Form(...),
                     username: str = Form(...), password: str = Form(...),
                     sub_path: str = Form(""), inbound_id: int = Form(1),
                     note: str = Form("")):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await add_server(name, url.rstrip("/"), username, password, sub_path.strip("/"), inbound_id, note)
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
async def server_edit(request: Request, sid: int,
                      name: str = Form(...), url: str = Form(...),
                      username: str = Form(...), password: str = Form(...),
                      sub_path: str = Form(""), inbound_id: int = Form(1),
                      note: str = Form("")):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await update_server(sid, name=name, url=url.rstrip("/"), username=username,
                        password=password, sub_path=sub_path.strip("/"),
                        inbound_id=inbound_id, note=note)
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
    pkgs = await get_packages(active_only=False)
    return _templates.TemplateResponse("packages.html",
                                       _ctx(request, packages=pkgs, active="packages"))


@app.post(f"/{S}/packages/add")
async def pkg_add(request: Request,
                  name: str = Form(...), traffic_gb: float = Form(...),
                  duration_days: int = Form(...), price: int = Form(...),
                  description: str = Form("")):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await add_package(name, traffic_gb, duration_days, price, description)
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
    orders = await get_all_orders(100)
    pending = await get_pending_orders()
    return _templates.TemplateResponse("orders.html",
                                       _ctx(request, orders=orders, pending_count=len(pending), active="orders"))


# ═══════════════════════════════ CONFIGS ════════════════════════════

@app.get(f"/{S}/configs", response_class=HTMLResponse)
async def configs_page(request: Request):
    if not _auth(request):
        return _redir_login()
    configs = await get_all_configs()
    return _templates.TemplateResponse("configs.html",
                                       _ctx(request, configs=configs, active="configs"))


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
    ok = await cli.update_client(cfg["inbound_id"], cfg["uuid"], cfg["email"],
                                  cfg["traffic_gb"], cfg["expire_timestamp"] or 0, new_status)
    await cli.close()
    if ok:
        await update_config(cid, is_active=1 if new_status else 0)
    return JSONResponse({"success": ok})


# ═══════════════════════════════ USERS ══════════════════════════════

@app.get(f"/{S}/users", response_class=HTMLResponse)
async def users_page(request: Request):
    if not _auth(request):
        return _redir_login()
    users = await get_all_users(0, 200)
    total = await count_users()
    return _templates.TemplateResponse("users.html",
                                       _ctx(request, users=users, total=total, active="users"))


@app.post(f"/{S}/users/{{uid}}/toggle_block")
async def user_toggle_block(request: Request, uid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from core.database import get_user_by_id, update_user
    u = await get_user_by_id(uid)
    if not u:
        return JSONResponse({"error": "not found"}, status_code=404)
    await update_user(uid, is_blocked=0 if u["is_blocked"] else 1)
    return JSONResponse({"success": True})


# ═══════════════════════════════ SETTINGS ═══════════════════════════

@app.get(f"/{S}/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    if not _auth(request):
        return _redir_login()
    settings = {
        "welcome_message": await get_setting("welcome_message"),
        "support_username": await get_setting("support_username"),
        "maintenance_mode": await get_setting("maintenance_mode", "0"),
    }
    from core.config import CARD_NUMBER, CARD_HOLDER, CARD_BANK, REFERRAL_BONUS_GB
    settings["card_number"] = CARD_NUMBER
    settings["card_holder"] = CARD_HOLDER
    settings["card_bank"] = CARD_BANK
    settings["referral_bonus_gb"] = REFERRAL_BONUS_GB
    saved = request.query_params.get("saved")
    return _templates.TemplateResponse("settings.html",
                                       _ctx(request, settings=settings, saved=saved, active="settings"))


@app.post(f"/{S}/settings")
async def settings_save(request: Request,
                         welcome_message: str = Form(""),
                         support_username: str = Form(""),
                         maintenance_mode: str = Form("0")):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    await set_setting("welcome_message", welcome_message)
    await set_setting("support_username", support_username)
    await set_setting("maintenance_mode", maintenance_mode)
    return RedirectResponse(f"/{S}/settings?saved=1", status_code=302)


# ═══════════════════════════════ ROOT ═══════════════════════════════

@app.get("/")
async def root():
    return RedirectResponse(f"/{S}/login", status_code=302)
