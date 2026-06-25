"""Atlas Account — Web Admin Panel (FastAPI)

All CSS/JS is embedded directly in HTML templates.
"""

import logging
import base64
import os
import re
import shlex
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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
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
    search_users,
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
    edit_subscription_profile,
    sync_subscription_nodes_for_all,
    sync_subscription_nodes_streamed,
)
from core.database import get_subscription_profile_by_token as _get_sub_profile_by_token
from core.database import get_subscription_nodes as _get_sub_nodes

logger = logging.getLogger(__name__)

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

_dir = os.path.dirname(os.path.abspath(__file__))
_repo_dir = os.path.dirname(_dir)
_db_path = DB_PATH if os.path.isabs(DB_PATH) else os.path.join(_repo_dir, DB_PATH)
_env_path = os.path.join(_repo_dir, ".env")
_backup_dir = os.path.join(_repo_dir, "backups")
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


async def _render_sub_status_html(token: str, profile: dict) -> str:
    import html as _html

    brand = await get_setting("ui.brand_name", "Atlas Account")
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
    <div class="logo">🌐</div>
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
    brand = await get_setting("ui.brand_name", "Atlas Account")
    title = (info.get("title") or "").strip() or brand
    title_b64 = base64.b64encode(str(title or "Atlas Account").encode("utf-8")).decode()
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


def _build_backup_zip() -> bytes:
    meta = {
        "app": "AtlasSellBot",
        "created_at": datetime.now().isoformat(),
        "contains": ["atlas.db"] + ([".env"] if os.path.exists(_env_path) else []),
    }
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("metadata.json", json.dumps(meta, ensure_ascii=False, indent=2))
        z.writestr("atlas.db", _sqlite_snapshot_bytes())
        if os.path.exists(_env_path):
            z.write(_env_path, ".env")
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


def _extract_restore_payload(upload_path: str, workdir: str) -> tuple[str, str | None]:
    db_out = os.path.join(workdir, "restore-atlas.db")
    env_out = os.path.join(workdir, "restore.env")
    env_found: str | None = None

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
    else:
        shutil.copyfile(upload_path, db_out)

    _validate_sqlite_db(db_out)
    return db_out, env_found


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
# ═════════════════════════════ BACKUP / RESTORE ═════════════════════════════
@app.get(f"/{S}/backups", response_class=HTMLResponse)
async def backups_page(request: Request):
    if not _auth(request):
        return _redir_login()
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
    backup_settings = {
        "server_backup_enabled": await get_setting("server_backup_enabled", SETTINGS_DEFAULTS["server_backup_enabled"]),
        "server_backup_interval_hours": await get_setting("server_backup_interval_hours", SETTINGS_DEFAULTS["server_backup_interval_hours"]),
    }
    return _templates.TemplateResponse(
        "backups.html",
        await _ctx_ui(
            request,
            active="backups",
            result=request.query_params.get("result", ""),
            pre=request.query_params.get("pre", ""),
            backups=backups,
            settings=backup_settings,
        ),
    )


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
    return RedirectResponse(f"/{S}/backups", status_code=302)


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
async def backup_restore(request: Request, backup_file: UploadFile = File(...), restore_env: str = Form("0")):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    with tempfile.TemporaryDirectory() as tmpdir:
        upload_path = os.path.join(tmpdir, "uploaded-backup")
        with open(upload_path, "wb") as f:
            shutil.copyfileobj(backup_file.file, f)

        try:
            db_restore, env_restore = _extract_restore_payload(upload_path, tmpdir)
            pre_name = _save_pre_restore_backup()
            os.replace(db_restore, _db_path)
            if restore_env == "1" and env_restore:
                os.replace(env_restore, _env_path)
            await init_db()
            return RedirectResponse(f"/{S}/backups?result=restored&pre={pre_name}", status_code=302)
        except Exception as e:
            logger.exception("backup restore failed: %s", e)
            return RedirectResponse(f"/{S}/backups?result=restore_error", status_code=302)


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
        "sub_auto_sync_enabled": await get_setting("sub_auto_sync_enabled", SETTINGS_DEFAULTS["sub_auto_sync_enabled"]),
        "sub_auto_sync_interval_hours": await get_setting("sub_auto_sync_interval_hours", SETTINGS_DEFAULTS["sub_auto_sync_interval_hours"]),
        "public_base_url": await get_setting("public_base_url", ""),
        "sub_info_enabled": await get_setting("sub_info_enabled", SETTINGS_DEFAULTS["sub_info_enabled"]),
        "sub_info_sync_on_render": await get_setting("sub_info_sync_on_render", SETTINGS_DEFAULTS["sub_info_sync_on_render"]),
        "sub_info_template": await get_setting("sub_info_template", SETTINGS_DEFAULTS["sub_info_template"]),
        "sub_brand_template": await get_setting("sub_brand_template", SETTINGS_DEFAULTS["sub_brand_template"]),
        "sub_start_on_first_use": await get_setting("sub_start_on_first_use", SETTINGS_DEFAULTS["sub_start_on_first_use"]),
        "convert_single_on_renew": await get_setting("convert_single_on_renew", "0"),
        "single_to_sub_nudge_enabled": await get_setting("single_to_sub_nudge_enabled", SETTINGS_DEFAULTS["single_to_sub_nudge_enabled"]),
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
        return RedirectResponse(f"/{S}/subs/profiles?saved=not_found", status_code=302)

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
        return RedirectResponse(f"/{S}/subs/profiles?saved=edit_error", status_code=302)
    return RedirectResponse(f"/{S}/subs/profiles?saved=edited", status_code=302)


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
    single_to_sub_nudge_enabled: str = Form("0"),
):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    node_count = max(2, min(8, int(multi_sub_node_count or 4)))
    min_nodes = max(2, min(node_count, int(multi_sub_min_nodes or 2)))
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
    await set_setting("single_to_sub_nudge_enabled", "1" if single_to_sub_nudge_enabled == "1" else "0")
    return RedirectResponse(f"/{S}/subs?saved=1", status_code=302)


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
        return RedirectResponse(f"/{S}/orders", status_code=302)

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
    if order.get("referred_by") and not await has_previous_purchase(user["id"]):
        referrer = await get_user_by_id(order["referred_by"])
        if referrer:
            await update_user(referrer["id"], referral_bonus_gb=float(referrer.get("referral_bonus_gb") or 0) + REFERRAL_BONUS_GB)
    await _clear_review_buttons("order", oid)
    if BOT_TOKEN and len(BOT_TOKEN) > 20:
        bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
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


@app.get(f"/{S}/users/search")
async def users_search_api(request: Request, q: str = ""):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    q = (q or "").strip()
    if len(q) < 2:
        return JSONResponse([])
    results = await search_users(q, limit=15)
    out = []
    for u in results:
        out.append({
            "id": u["id"],
            "telegram_id": u.get("telegram_id", ""),
            "full_name": u.get("full_name") or "—",
            "username": u.get("username") or "",
            "balance_toman": u.get("balance_toman") or 0,
            "is_blocked": bool(u.get("is_blocked")),
            "is_wholesale": bool(u.get("is_wholesale")),
            "url": f"/{S}/users/{u['id']}",
        })
    return JSONResponse(out)


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
        return RedirectResponse(f"/{S}/users", status_code=302)
    await add_user_balance(uid, amount, kind="manual", note=note, actor_telegram_id=0)
    if is_ajax:
        from core.database import get_user_by_id
        u = await get_user_by_id(uid)
        return JSONResponse({"success": True, "new_balance": u.get("balance_toman", 0) if u else 0})
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
async def user_set_pricing(request: Request, uid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    ct = request.headers.get("content-type", "")
    if "application/json" in ct:
        data = await request.json()
        discount_percent = float(data.get("discount_percent", 0) or 0)
        price_per_gb = int(str(data.get("price_per_gb", 0) or 0).replace(",", ""))
        is_ajax = True
    else:
        form = await request.form()
        discount_percent = float(form.get("discount_percent", 0) or 0)
        price_per_gb = int(str(form.get("price_per_gb", 0) or 0).replace(",", ""))
        is_ajax = False
    discount_percent = max(0, min(100, discount_percent))
    price_per_gb = max(0, price_per_gb)
    from core.database import update_user
    await update_user(uid, discount_percent=discount_percent, price_per_gb=price_per_gb)
    if is_ajax:
        return JSONResponse({"success": True})
    return RedirectResponse(f"/{S}/users", status_code=302)


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


@app.get(f"/{S}/legacy-claims", response_class=HTMLResponse)
async def legacy_claims_page(request: Request):
    if not _auth(request):
        return _redir_login()
    claims = await get_pending_legacy_claims()
    return _templates.TemplateResponse(
        "legacy_claims.html",
        await _ctx_ui(request, claims=claims, active="legacy_claims", result=request.query_params.get("result", "")),
    )


@app.post(f"/{S}/legacy-claims/{{cid}}/approve")
async def legacy_claim_approve_web(request: Request, cid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    claim = await get_legacy_claim(cid)
    if not claim or claim.get("status") != "pending":
        return RedirectResponse(f"/{S}/legacy-claims?result=missing", status_code=302)

    email = (claim.get("email") or "").strip()
    claim_uuid = (claim.get("uuid") or "").strip()
    if not email and not claim_uuid:
        await update_legacy_claim(cid, status="rejected", reviewed_at=datetime.now().isoformat(), admin_note="missing_identity_web")
        return RedirectResponse(f"/{S}/legacy-claims?result=bad_identity", status_code=302)

    cfg = await get_config_by_email(email) if email else None
    if not cfg and claim_uuid:
        cfg = await get_config_by_uuid(claim_uuid)

    remote = None
    if not cfg:
        from bot.handlers.admin import _find_remote_legacy_client

        remote = await _find_remote_legacy_client(email, claim_uuid)
        if not remote or not remote.get("email") or not remote.get("uuid"):
            await update_legacy_claim(cid, admin_note=f"not_found_web:{datetime.now().isoformat()}", reviewed_at=datetime.now().isoformat())
            return RedirectResponse(f"/{S}/legacy-claims?result=not_found", status_code=302)
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
        return RedirectResponse(f"/{S}/legacy-claims?result=not_found", status_code=302)

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
    return RedirectResponse(f"/{S}/legacy-claims?result=approved", status_code=302)


@app.post(f"/{S}/legacy-claims/{{cid}}/reject")
async def legacy_claim_reject_web(request: Request, cid: int):
    if not _auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    claim = await get_legacy_claim(cid)
    if claim and claim.get("status") == "pending":
        await update_legacy_claim(cid, status="rejected", reviewed_at=datetime.now().isoformat(), admin_note="rejected_web")
        await _notify_legacy_sync_user(int(claim["telegram_id"]), "❌ درخواست سینک کانفیگ شما رد شد. برای بررسی بیشتر با پشتیبانی هماهنگ کنید.")
    return RedirectResponse(f"/{S}/legacy-claims?result=rejected", status_code=302)


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
        "sub_info_enabled": await get_setting("sub_info_enabled", SETTINGS_DEFAULTS["sub_info_enabled"]),
        "sub_info_sync_on_render": await get_setting("sub_info_sync_on_render", SETTINGS_DEFAULTS["sub_info_sync_on_render"]),
        "sub_info_template": await get_setting("sub_info_template", SETTINGS_DEFAULTS["sub_info_template"]),
        "sub_brand_template": await get_setting("sub_brand_template", SETTINGS_DEFAULTS["sub_brand_template"]),
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
    sub_info_enabled: str = Form("1"),
    sub_info_sync_on_render: str = Form("1"),
    sub_info_template: str = Form(""),
    sub_brand_template: str = Form(""),
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
    atlas_tls_https_port: int = Form(443),
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
    # Subscriptions are the only fulfilment model now; keep it pinned on.
    await set_setting("multi_sub_enabled", "1")
    await set_setting("multi_sub_node_count", str(max(2, min(8, int(multi_sub_node_count or 4)))))
    await set_setting("multi_sub_min_nodes", str(max(2, min(8, int(multi_sub_min_nodes or 2)))))
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

    # ✅ ذخیره کارت
    await set_setting("card_number", card_number.strip())
    await set_setting("card_holder", card_holder.strip())
    await set_setting("card_bank", card_bank.strip())
    await set_setting("panel_domain", panel_domain.strip().lower())
    await set_setting("cert_email", cert_email.strip().lower())
    await set_setting("atlas_tls_https_port", str(max(1, min(65535, int(atlas_tls_https_port or 443)))))

    return RedirectResponse(f"/{S}/settings?saved=1", status_code=302)


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


@app.get(f"/{S}/update", response_class=HTMLResponse)
async def update_page(request: Request):
    if not _auth(request):
        return _redir_login()
    return _templates.TemplateResponse(
        "update.html",
        await _ctx_ui(request, active="update"),
    )


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
    return RedirectResponse(f"/{S}/login", status_code=302)
