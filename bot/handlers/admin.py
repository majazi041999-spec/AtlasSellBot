import asyncio
import logging
import re
import uuid
import time
import json
import base64
import binascii
import sqlite3
from datetime import datetime, timedelta, date
from urllib.parse import urlparse, parse_qs, unquote
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from core.config import ADMIN_IDS, WEB_SECRET_PATH, WEB_PORT
from core.database import (
    get_stats, get_all_configs, get_config, update_config,
    get_packages, get_package, add_package, update_package, delete_package,
    get_pending_orders, get_order, update_order,
    get_all_users, count_users, get_server, get_servers,
    save_config, get_user_by_telegram, get_setting, set_setting,
    get_user_by_id, server_has_capacity, count_active_configs_by_server, get_least_loaded_server, update_user,
    get_legacy_claim, update_legacy_claim, get_config_by_email, get_config_by_uuid,
    get_topup_request, get_pending_topup_requests, update_topup_request, add_user_balance,
    claim_order_for_approval,
    release_order_processing,
    clear_config_alerts,
    add_review_message,
    snapshot_daily_report,
    get_recent_daily_reports,
    format_daily_report,
    get_subscription_profile,
    get_subscription_profile_by_token,
    get_subscription_node_by_uuid,
    get_subscription_nodes,
    update_subscription_profile,
    find_user,
    get_user_configs,
    get_user_subscription_profiles,
)
from core.renewal import find_and_renew_config
from core.xui_api import XUIClient, fmt_bytes, days_left, expiry_ms_from_days
from core.qr import build_qr_image
from core.multi_subscription import (
    create_profile_for_order,
    create_profile_from_config,
    multi_sub_enabled_for_single_purchase,
    subscription_error_message,
    renew_subscription_profile,
    edit_subscription_profile,
    subscription_url,
    set_nodes_enabled,
    delete_subscription_profile_remote,
)
from bot.keyboards import (
    admin_menu, order_review_kb, order_server_select_kb,
    admin_configs_kb, adm_config_detail_kb, confirm_kb, packages_kb, servers_kb,
    broadcast_target_kb, legacy_claim_admin_kb, flow_cancel_kb, topup_review_kb,
    config_links_kb, parse_custom_buttons,
    adm_user_card_kb, adm_user_services_kb, adm_sub_panel_kb,
)
from bot.states import (
    AddPackage, CreateConfig, BulkConfig, EditConfig, EditSubProfile, Broadcast, PrivateMessage,
    AdminUserSearch, AdminBalance,
)

router = Router()
logger = logging.getLogger(__name__)


def _qr_input_file(link: str, footer_text: str) -> BufferedInputFile:
    qr = build_qr_image(link, footer_text=footer_text)
    return BufferedInputFile(qr.getvalue(), filename="atlas-qr.png")


def _fmt_toman(amount: int) -> str:
    return f"{int(amount or 0):,}".replace(",", "،")


def _extract_config_identity_from_text(text: str) -> tuple[str, str]:
    def decode_b64_text(value: str) -> str:
        raw = (value or "").strip()
        raw += "=" * (-len(raw) % 4)
        for decoder in (base64.urlsafe_b64decode, base64.b64decode):
            try:
                return decoder(raw.encode()).decode("utf-8", "ignore")
            except (binascii.Error, UnicodeDecodeError, ValueError):
                continue
        return ""

    raw = (text or "").strip()
    token = ""
    for part in raw.replace("\n", " ").split():
        clean = part.strip().strip("`'\"")
        if "://" in clean:
            token = clean
            break
    if not token:
        token = raw.strip().strip("`'\"")

    try:
        if token.lower().startswith("vmess://"):
            payload = token[8:].split("#", 1)[0].split("?", 1)[0]
            try:
                obj = json.loads(decode_b64_text(payload))
            except Exception:
                obj = {}
            return (obj.get("ps") or obj.get("remark") or obj.get("email") or "").strip(), (obj.get("id") or "").strip()

        p = urlparse(token)
        if p.scheme not in ("vless", "vmess", "trojan", "ss", "hysteria", "hysteria2", "hy2"):
            return "", ""
        email = unquote((p.fragment or "").strip())
        client_uuid = unquote((p.username or "").strip())
        q = parse_qs(p.query or "")
        if not email and q.get("remark"):
            email = unquote(q["remark"][0])
        if not email and q.get("email"):
            email = unquote(q["email"][0])
        return email, client_uuid
    except Exception:
        return "", ""


# Small TTL cache so we don't open a synchronous sqlite connection on every
# single message (this function is also evaluated inside message filters).
_role_cache: dict[int, tuple[str, float]] = {}
_ROLE_TTL = 30.0


def _db_admin_role(uid: int) -> str:
    cached = _role_cache.get(uid)
    if cached and cached[1] > time.monotonic():
        return cached[0]
    role = "none"
    try:
        conn = sqlite3.connect("atlas.db")
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key='owner_admin_id'")
        own = cur.fetchone()
        owner_id = int((own[0] if own else "0") or 0)
        if uid in ADMIN_IDS or (owner_id and uid == owner_id):
            role = "owner"
        else:
            cur.execute("SELECT is_admin, admin_role FROM users WHERE telegram_id=?", (uid,))
            row = cur.fetchone()
            if row and int(row[0] or 0) == 1:
                r = str(row[1] or "full").strip().lower()
                role = r if r in {"full", "finance"} else "full"
        conn.close()
    except Exception:
        return "none"
    _role_cache[uid] = (role, time.monotonic() + _ROLE_TTL)
    return role


def is_admin(uid: int) -> bool:
    return _db_admin_role(uid) in ("owner", "full")


def can_review_payments(uid: int) -> bool:
    return _db_admin_role(uid) in ("owner", "full", "finance")




# ── ثبت مسیرهای «برگشت» ادمین در سیستم ناوبری یکپارچه (bot/nav.py) ──
def _register_admin_back_steps():
    from bot import nav

    # افزودن پکیج
    nav.register(AddPackage.traffic, nav.static(AddPackage.name, "✍️ نام پکیج را وارد کنید:"))
    nav.register(AddPackage.duration, nav.static(AddPackage.traffic, "📊 حجم (GB):"))
    nav.register(AddPackage.price, nav.static(AddPackage.duration, "📅 مدت (روز):"))
    nav.register(AddPackage.description, nav.static(AddPackage.price, "💰 قیمت (تومان):"))
    nav.register(AddPackage.name, nav.go_home)

    # ساخت کانفیگ تکی
    nav.register(CreateConfig.traffic, nav.static(CreateConfig.email, "📧 شناسه (ایمیل) کانفیگ را وارد کنید:\n_مثال: ali_vip_30d_", "Markdown"))
    nav.register(CreateConfig.duration, nav.static(CreateConfig.traffic, "📊 حجم ترافیک (GB):"))
    nav.register(CreateConfig.server, nav.static(CreateConfig.duration, "📅 مدت (روز):"))
    nav.register(CreateConfig.email, nav.go_home)

    # ساخت گروهی
    nav.register(BulkConfig.count, nav.static(BulkConfig.prefix, "📋 *ساخت گروهی*\n\nپیشوند نام کانفیگ‌ها:\n_مثال: vip_user_", "Markdown"))
    nav.register(BulkConfig.traffic, nav.static(BulkConfig.count, "🔢 تعداد کانفیگ (حداکثر ۵۰):"))
    nav.register(BulkConfig.duration, nav.static(BulkConfig.traffic, "📊 حجم هر کانفیگ (GB):"))
    nav.register(BulkConfig.server, nav.static(BulkConfig.duration, "📅 مدت (روز):"))
    nav.register(BulkConfig.prefix, nav.go_home)

    # پیام خصوصی
    nav.register(PrivateMessage.text, nav.static(PrivateMessage.user_id, "🆔 آیدی عددی کاربر را ارسال کنید:"))
    nav.register(PrivateMessage.user_id, nav.go_home)

    async def _pm_buttons_back(cb: CallbackQuery, state: FSMContext):
        await state.set_state(PrivateMessage.text)
        await cb.message.edit_text("✍️ متن پیام خصوصی را ارسال کنید:", reply_markup=flow_cancel_kb())
    nav.register(PrivateMessage.buttons, _pm_buttons_back)

    # پیام همگانی
    async def _bc_text_back(cb: CallbackQuery, state: FSMContext):
        await state.set_state(Broadcast.target)
        await cb.message.edit_text("📣 مخاطب پیام را انتخاب کنید:", reply_markup=broadcast_target_kb())
    nav.register(Broadcast.text, _bc_text_back)

    async def _bc_buttons_back(cb: CallbackQuery, state: FSMContext):
        await state.set_state(Broadcast.text)
        await cb.message.edit_text("✍️ متن پیام را بنویسید:", reply_markup=flow_cancel_kb())
    nav.register(Broadcast.buttons, _bc_buttons_back)
    nav.register(Broadcast.target, nav.go_home)

    # ویرایش حجم/تاریخ کانفیگ → برگشت به جزئیات همان کانفیگ
    async def _edit_cfg_back(cb: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        cid = int(data.get("cid") or 0)
        await state.clear()
        if cid:
            await _render_cfg_detail(cb.message, cid)
        else:
            await nav.go_home(cb, state)
    nav.register(EditConfig.traffic, _edit_cfg_back)
    nav.register(EditConfig.expire, _edit_cfg_back)


_register_admin_back_steps()


@router.message(StateFilter(None), lambda msg: bool(msg.text and any(_extract_config_identity_from_text(msg.text)) and _db_admin_role(msg.from_user.id) in ("owner", "full")))
async def owner_config_link_lookup(msg: Message):
    email, client_uuid = _extract_config_identity_from_text(msg.text or "")

    # Fast path: a config we manage in the DB → show the full admin panel with
    # owner info + action buttons (toggle, edit, convert-to-sub, message owner…).
    cfg = await get_config_by_email(email) if email else None
    if not cfg and client_uuid:
        cfg = await get_config_by_uuid(client_uuid)
    if cfg:
        sent = await msg.answer("🔎 کانفیگ پیدا شد. در حال بارگذاری پنل مدیریت...", parse_mode=None)
        await _render_cfg_detail(sent, int(cfg["id"]))
        return

    # The link may belong to a multi-server subscription node (UUID is the key):
    # open the sub management panel so it can be edited/renewed/toggled.
    sub_node = await get_subscription_node_by_uuid(client_uuid) if client_uuid else None
    if sub_node and int(sub_node.get("profile_id") or 0):
        sent = await msg.answer("🔎 این لینک متعلق به یک سابسکریپشن است. در حال بارگذاری پنل ساب...", parse_mode=None)
        await _render_sub_panel(sent, int(sub_node["profile_id"]))
        return

    # Slow path: search every registered server (for foreign/legacy configs).
    status = await msg.answer("⏳ دارم داخل همه سرورهای ثبت‌شده می‌گردم...", parse_mode=None)
    try:
        info = await asyncio.wait_for(_lookup_remote_config_status(email, client_uuid), timeout=90)
    except asyncio.TimeoutError:
        try:
            await status.edit_text("⌛️ جستجو طول کشید و متوقف شد. ممکن است یکی از سرورها در دسترس نباشد. دوباره تلاش کنید.", parse_mode=None)
        except Exception:
            await msg.answer("⌛️ جستجو طول کشید و متوقف شد. ممکن است یکی از سرورها در دسترس نباشد. دوباره تلاش کنید.", parse_mode=None)
        return
    except Exception as e:
        logger.exception("owner config lookup failed: %s", e)
        try:
            await status.edit_text(f"❌ خطا در جستجوی کانفیگ:\n{str(e)[:300]}", parse_mode=None)
        except Exception:
            await msg.answer(f"❌ خطا در جستجوی کانفیگ:\n{str(e)[:300]}", parse_mode=None)
        return

    if not info:
        text = (
            "❌ این کانفیگ با ایمیل/UUID داخل لینک، روی سرورهای ثبت‌شده پیدا نشد.\n\n"
            f"🔎 ایمیل: {email or '—'}\n"
            f"🔑 UUID: {client_uuid or '—'}"
        )
    else:
        text = _format_remote_config_status(info)
    try:
        await status.edit_text(text, parse_mode=None)
    except Exception:
        await msg.answer(text, parse_mode=None)


# ─── STATS ───────────────────────────────────────────────────────

@router.message(F.text == "📊 آمار کلی")
async def show_stats(msg: Message):
    if not is_admin(msg.from_user.id):
        return
    s = await get_stats()
    servers = await get_servers(active_only=False)
    srv_lines = "\n".join(f"  {'🟢' if sv['is_active'] else '🔴'} {sv['name']}" for sv in servers) or "  هنوز سروری ثبت نشده"
    today_rev = s.get('today_orders', 0)

    await msg.answer(
        f"📊 *آمار کلی — Atlas Account*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 کل کاربران: `{s['total_users']}`\n"
        f"🔑 کانفیگ فعال: `{s['active_configs']}`\n\n"
        f"💰 *فروش*\n"
        f"✅ تأیید شده: `{s['total_orders']}`\n"
        f"⏳ در انتظار: `{s['pending_orders']}`\n"
        f"📅 امروز: `{today_rev}` سفارش\n"
        f"💵 کل درآمد: `{s['total_revenue']:,}` تومن\n\n"
        f"🖥️ *سرورها* ({s['active_servers']}/{s['total_servers']} فعال)\n"
        f"{srv_lines}",
        parse_mode="Markdown"
    )


@router.message(F.text == "📈 گزارش روزانه")
async def show_daily_report(msg: Message):
    if not is_admin(msg.from_user.id):
        return
    today = await snapshot_daily_report()
    recent = await get_recent_daily_reports(7)
    lines = [format_daily_report(today)]
    if recent:
        lines.append("\n۷ گزارش آخر:")
        for r in recent[:7]:
            lines.append(
                f"{r.get('jalali_display')}: فروش {int(r.get('sales_amount') or 0):,} تومان | "
                f"{int(r.get('orders_approved') or 0)} سفارش | {int(r.get('new_configs') or 0)} کانفیگ"
            )
    await msg.answer("\n".join(lines), parse_mode=None)


# ─── PENDING ORDERS ───────────────────────────────────────────────

@router.message(F.text == "💰 سفارش‌های در انتظار")
async def pending_orders_list(msg: Message):
    if not can_review_payments(msg.from_user.id):
        return
    orders = await get_pending_orders()
    topups = await get_pending_topup_requests(100)
    if not orders and not topups:
        await msg.answer("✅ هیچ سفارش در انتظاری وجود ندارد.")
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    for o in orders:
        b.button(
            text=f"📤 #{o['id']} — {o['full_name'] or 'کاربر'} — {o['pkg_name']}",
            callback_data=f"view_order:{o['id']}"
        )
    for t in topups:
        b.button(
            text=f"💳 شارژ #{t['id']} — {t['full_name'] or 'کاربر'} — {_fmt_toman(t['amount'])} تومان",
            callback_data=f"view_topup:{t['id']}",
        )
    b.adjust(1)
    await msg.answer(
        f"💰 *در انتظار بررسی* | خرید: {len(orders)} | شارژ کیف پول: {len(topups)}",
        reply_markup=b.as_markup(), parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("view_order:"))
async def view_order(cb: CallbackQuery):
    if not can_review_payments(cb.from_user.id):
        return
    oid = int(cb.data.split(":")[1])
    order = await get_order(oid)
    if not order:
        await cb.answer("سفارش یافت نشد!", show_alert=True)
        return

    text = (
        f"📋 *سفارش #{oid}*\n"
        f"━━━━━━━━━━━━━━\n"
        f"👤 کاربر: {order['full_name']} (@{order['username'] or '—'})\n"
        f"📦 پکیج: {order['pkg_name']}\n"
        f"📊 حجم: {order['traffic_gb']} GB | 📅 {order['duration_days']} روز\n"
        f"💰 مبلغ: {_fmt_toman(order['price'])} تومان\n"
        f"🕐 ثبت: {order['created_at'][:16]}"
    )

    if order.get("receipt_file_id"):
        sent = await cb.message.answer_photo(
            order["receipt_file_id"],
            caption=text + "\n\nفیش پرداخت ارسال شده",
            reply_markup=order_review_kb(oid), parse_mode=None
        )
        await add_review_message("order", oid, sent.chat.id, sent.message_id)
    else:
        await cb.message.edit_text(
            text + "\n\n⏳ هنوز فیش ارسال نشده",
            reply_markup=order_review_kb(oid), parse_mode="Markdown"
        )


@router.callback_query(F.data.startswith("view_topup:"))
async def view_topup(cb: CallbackQuery):
    if not can_review_payments(cb.from_user.id):
        return
    rid = int(cb.data.split(":")[1])
    req = await get_topup_request(rid)
    if not req:
        await cb.answer("درخواست یافت نشد", show_alert=True)
        return
    text = (
        f"درخواست افزایش اعتبار #{rid}\n"
        f"کاربر: {req.get('full_name') or '—'} (@{req.get('username') or '—'})\n"
        f"آیدی: {req.get('telegram_id')}\n"
        f"مبلغ: {_fmt_toman(req.get('amount') or 0)} تومان\n"
        f"وضعیت: {req.get('status')}"
    )
    if req.get("receipt_file_id"):
        sent = await cb.message.answer_photo(
            req["receipt_file_id"],
            caption=text,
            reply_markup=topup_review_kb(rid),
            parse_mode=None,
        )
        await add_review_message("topup", rid, sent.chat.id, sent.message_id)
    else:
        sent = await cb.message.answer(text, reply_markup=topup_review_kb(rid), parse_mode=None)
        await add_review_message("topup", rid, sent.chat.id, sent.message_id)
    await cb.answer()


@router.callback_query(F.data.startswith("approve:"))
async def approve_order_start(cb: CallbackQuery):
    if not can_review_payments(cb.from_user.id):
        return
    oid = int(cb.data.split(":")[1])
    order = await get_order(oid)
    if not order:
        await cb.answer("سفارش یافت نشد", show_alert=True)
        return
    if int(order.get("renew_config_id") or 0) > 0:
        cfg = await get_config(int(order["renew_config_id"]))
        if not cfg:
            await cb.answer("سرویس تمدیدی پیدا نشد", show_alert=True)
            return
        await _do_approve(cb, oid, int(cfg["server_id"]))
        return
    if int(order.get("renew_sub_profile_id") or 0) > 0:
        await _do_approve(cb, oid, 0)
        return

    # Purchases are multi-server subscriptions now — there is no single server to
    # choose. Approve straight away; the sub is built from the configured nodes.
    await _do_approve(cb, oid, 0)


@router.callback_query(F.data.startswith("assign:"))
async def assign_server(cb: CallbackQuery):
    if not can_review_payments(cb.from_user.id):
        return
    _, oid, sid = cb.data.split(":")
    await _do_approve(cb, int(oid), int(sid))




def _server_inbound_choices(server: dict) -> list[int]:
    raw = str(server.get("inbound_ids") or "").replace(" ", "")
    out: list[int] = []
    for tok in raw.split(","):
        if not tok:
            continue
        try:
            val = int(tok)
        except ValueError:
            continue
        if val > 0 and val not in out:
            out.append(val)
    default_iid = int(server.get("inbound_id") or 1)
    if default_iid not in out:
        out.append(default_iid)
    return out


def _safe_config_suffix(value: str) -> str:
    cleaned = "".join(ch for ch in (value or "").strip() if ch.isalnum() or ch in ("_", "-", "."))
    return cleaned[:24]


async def _build_config_name(order, idx: int = 0) -> str:
    prefix = await get_setting("cfg_name_prefix", "u")
    postfix = await get_setting("cfg_name_postfix", "")
    rand_len = int(await get_setting("cfg_name_rand_len", "6") or 6)
    random_part = uuid.uuid4().hex[:max(2, min(16, rand_len))]
    idx_part = f"_{idx:02d}" if idx > 0 else ""
    base = f"{prefix}{order['telegram_id']}{idx_part}_{random_part}{postfix}".replace(" ", "_")
    suffix = _safe_config_suffix(order.get("custom_config_name") or "")
    return f"{base}_{suffix}" if suffix else base


async def _do_renew(cb: CallbackQuery, order: dict) -> bool:
    from core.renewal import find_and_renew_config

    cid = int(order.get("renew_config_id") or 0)
    cfg = await get_config(cid)
    if not cfg:
        await update_order(order["id"], status="receipt_submitted")
        await cb.message.answer("❌ سرویس برای تمدید پیدا نشد.")
        return False

    # Trust the order's plan values (0 = unlimited); falling back to the config's
    # old volume/duration would silently break unlimited-plan renewals.
    duration = int(order.get("duration_days") or 0)
    traffic_gb = float(order.get("traffic_gb") or 0)
    result = await find_and_renew_config(cfg, traffic_gb, duration)
    if not result.get("ok"):
        await update_order(order["id"], status="receipt_submitted")
        await cb.message.answer(
            "❌ تمدید انجام نشد. کانفیگ روی هیچ‌کدام از سرورهای ثبت‌شده پیدا نشد یا آپدیت نشد.\n"
            f"جزئیات: {result.get('error') or '-'}",
            parse_mode=None,
        )
        return False
    server = result["server"]
    link = result.get("link")
    sub = result.get("sub")
    await update_order(
        order["id"],
        status="approved",
        server_id=server["id"],
        config_email=cfg["email"],
        inbound_id=result.get("inbound_id") or cfg["inbound_id"],
        approved_at=datetime.now().isoformat(),
    )

    # Optionally convert the renewed single config into a multi-server sub link.
    if (
        await get_setting("convert_single_on_renew", "0") == "1"
        and await get_setting("multi_sub_enabled", "0") == "1"
    ):
        try:
            fresh_cfg = await get_config(cid) or cfg
            renew_user = await get_user_by_telegram(order["telegram_id"])
            if renew_user:
                conv = await create_profile_from_config(renew_user, fresh_cfg)
                if conv.get("ok"):
                    sub_url = conv["url"]
                    try:
                        await cb.bot.send_message(
                            order["telegram_id"],
                            "✅ سرویس شما تمدید و به لینک ساب چندسروره تبدیل شد.\n\n"
                            f"حجم: {float(conv.get('traffic_gb') or traffic_gb):g} GB\n"
                            f"نودهای فعال: {int(conv.get('nodes') or 0)}\n\n"
                            f"لینک ساب:\n{sub_url}",
                            parse_mode=None,
                            reply_markup=config_links_kb("", sub_url),
                        )
                        await cb.bot.send_photo(order["telegram_id"], _qr_input_file(sub_url, conv.get("email") or "Subscription"), caption="QR سابسکریپشن", parse_mode=None)
                    except Exception:
                        pass
                    try:
                        if cb.message.photo:
                            cap = cb.message.caption or ""
                            await cb.message.edit_caption(cap + ("" if "تمدید" in cap else "\n\n✅ تمدید و تبدیل به ساب شد"), reply_markup=None, parse_mode=None)
                    except Exception:
                        pass
                    return True
        except Exception as e:
            logger.warning("convert-on-renew failed for order %s: %s", order.get("id"), e)

    try:
        text = (
            "✅ سرویس شما تمدید شد.\n\n"
            f"کانفیگ: {cfg['email']}\n"
            f"سرور: {server['name']}\n"
            f"حجم جدید: {traffic_gb} GB\n"
            f"مدت تمدید: {duration} روز\n"
        )
        if link:
            text += f"\nلینک اتصال:\n{link}\n"
        if sub:
            text += f"\nلینک سابسکریپشن:\n{sub}\n"
        await cb.bot.send_message(order["telegram_id"], text, parse_mode=None, reply_markup=config_links_kb(link or "", sub or ""))
        if link:
            try:
                ch = await get_setting("channel_username", "AtlasChannel")
                await cb.bot.send_photo(order["telegram_id"], _qr_input_file(link, ch), caption=f"QR: {cfg['email']}", parse_mode=None)
            except Exception:
                pass
    except Exception:
        pass

    try:
        if cb.message.photo:
            caption = cb.message.caption or ""
            await cb.message.edit_caption(caption + ("" if "تمدید شد" in caption else "\n\n✅ تمدید شد"), reply_markup=None, parse_mode=None)
        else:
            await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cb.message.answer("✅ سرویس تمدید شد و به کاربر اطلاع داده شد.", parse_mode=None)
    return True


async def _do_renew_subscription(cb: CallbackQuery, order: dict) -> bool:
    profile_id = int(order.get("renew_sub_profile_id") or 0)
    profile = await get_subscription_profile(profile_id)
    if not profile:
        await update_order(order["id"], status="receipt_submitted")
        await cb.message.answer("❌ سابسکریپشن برای تمدید پیدا نشد.", parse_mode=None)
        return False

    # Trust the order's plan values (0 = unlimited) rather than the sub's old ones.
    duration = int(order.get("duration_days") or 0)
    traffic_gb = float(order.get("traffic_gb") or 0)
    result = await renew_subscription_profile(profile, traffic_gb, duration)
    if not result.get("ok"):
        await update_order(order["id"], status="receipt_submitted")
        await cb.message.answer(f"❌ تمدید ساب انجام نشد.\nجزئیات: {result.get('error') or '-'}", parse_mode=None)
        return False

    sub_url = await subscription_url(profile["token"])
    await update_order(
        order["id"],
        status="approved",
        server_id=0,
        config_email=profile.get("email") or f"sub:{profile_id}",
        inbound_id=0,
        approved_at=datetime.now().isoformat(),
    )
    try:
        await cb.bot.send_message(
            order["telegram_id"],
            "✅ سابسکریپشن شما تمدید شد.\n\n"
            f"حجم جدید: {traffic_gb} GB\n"
            f"مدت تمدید: {duration} روز\n"
            f"نودهای تمدیدشده: {result.get('nodes', 0)}\n\n"
            f"لینک ساب:\n{sub_url}",
            parse_mode=None,
            reply_markup=config_links_kb("", sub_url),
        )
    except Exception:
        pass
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cb.message.answer("✅ سابسکریپشن تمدید شد و به کاربر اطلاع داده شد.", parse_mode=None)
    return True


async def _do_approve(cb: CallbackQuery, oid: int, sid: int):
    try:
        return await _do_approve_impl(cb, oid, sid)
    except Exception as e:
        await release_order_processing(oid)
        try:
            await cb.message.answer(f"❌ تایید سفارش کامل نشد و سفارش دوباره به صف بررسی برگشت.\nجزئیات: {e}", parse_mode=None)
        except Exception:
            pass
        return False


async def _do_approve_impl(cb: CallbackQuery, oid: int, sid: int):
    order = await get_order(oid)
    if not order:
        return False
    if order.get("status") == "approved":
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await cb.answer("این سفارش قبلاً تایید شده است.", show_alert=True)
        return False
    if order.get("status") != "receipt_submitted":
        await cb.answer("این سفارش آماده تایید نیست یا قبلاً بررسی شده.", show_alert=True)
        return False
    if not await claim_order_for_approval(oid):
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await cb.answer("این سفارش همین الان توسط ادمین دیگری در حال پردازش است یا قبلاً بررسی شده.", show_alert=True)
        return False
    if int(order.get("renew_config_id") or 0) > 0:
        await cb.answer("⏳ در حال تمدید سرویس...")
        return await _do_renew(cb, order)
    if int(order.get("renew_sub_profile_id") or 0) > 0:
        await cb.answer("⏳ در حال تمدید سابسکریپشن...")
        return await _do_renew_subscription(cb, order)

    await cb.answer("⏳ در حال ساخت سرویس...")

    bulk_count = int(order.get("bulk_count") or 1)
    each_gb = float(order.get("bulk_each_gb") or order["traffic_gb"])
    duration = int(order["duration_days"])

    user = await get_user_by_telegram(order["telegram_id"])
    if not user:
        await cb.message.answer("❌ کاربر در دیتابیس یافت نشد!")
        await update_order(oid, status="receipt_submitted")
        return False

    # Subscriptions are the only fulfilment model now (single-server retired).
    # Every purchased unit — including bulk/reseller orders — becomes its own
    # multi-server subscription built from the configured nodes.
    units = max(1, bulk_count)

    # The buyer's accrued referral-bonus GB (if any) is added to the first unit.
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
        err_text = subscription_error_message(last_error)
        notes = ((order.get("notes") or "") + f"\nsub_create_error={last_error}").strip()
        await update_order(oid, status="receipt_submitted", notes=notes)
        await cb.message.answer(
            "❌ ساخت سابسکریپشن ناموفق بود و سفارش تایید نشد.\n\n"
            f"علت: {err_text}\n\n"
            "حداقل یک نود ساب فعال و دارای ظرفیت لازم است؛ وضعیت نودها را در پنل بررسی کنید.",
            parse_mode=None,
        )
        return False

    # Capture BEFORE flipping to approved so "first purchase" is accurate.
    from core.database import has_previous_purchase
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

    # Discount redemption + referral incentives (per-referral GB + milestone tiers).
    from core.rewards import apply_post_approval_rewards
    await apply_post_approval_rewards(cb.bot, user, order, first_purchase)

    head = (
        "🎉 سرویس شما فعال شد!\n"
        "━━━━━━━━━━━━━━\n"
        f"📦 سفارش: {order.get('pkg_name') or '—'}\n"
        f"🧬 تعداد سابسکریپشن: {len(created_subs)}\n"
        f"📊 حجم هر سرویس: {each_gb} GB\n"
        f"📅 مدت: {duration} روز\n"
    )
    if bonus_gb > 0:
        head += f"🎁 هدیه رفرال: {bonus_gb:g} GB روی سرویس اول اعمال شد\n"
    try:
        await cb.bot.send_message(order["telegram_id"], head, parse_mode=None)
        for item in created_subs[:20]:
            sub_url = item["url"]
            await cb.bot.send_message(
                order["telegram_id"],
                f"📡 لینک سابسکریپشن ({item.get('nodes', 0)} سرور):\n{sub_url}",
                parse_mode=None,
                reply_markup=config_links_kb("", sub_url),
            )
            try:
                qr_label = item.get("email") or "Subscription"
                await cb.bot.send_photo(order["telegram_id"], _qr_input_file(sub_url, qr_label), caption="QR سابسکریپشن", parse_mode=None)
            except Exception:
                pass
    except Exception:
        pass

    try:
        if cb.message.photo:
            caption = cb.message.caption or ""
            suffix = "\n\n✅ تایید شد"
            await cb.message.edit_caption(caption + ("" if "تایید شد" in caption else suffix), reply_markup=None, parse_mode=None)
        else:
            await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cb.message.answer(f"✅ {len(created_subs)} سابسکریپشن ساخته و برای کاربر ارسال شد.", parse_mode=None)
    try:
        uname = order.get("username") or ""
        display = ("@" + uname) if uname else (order.get("full_name") or "دوست عزیز")
        support = await get_setting("support_username", "")
        sup = f"@{support.lstrip('@')}" if support else "پشتیبانی"
        await cb.bot.send_message(
            order["telegram_id"],
            f"🎉 {display} عزیز، خریدت با موفقیت انجام شد و سرویس برات فعال شد.\n\n"
            f"🙏 ممنونیم از خریدت.\n"
            f"اگر مشکلی داشتی با {sup} در ارتباط باش.",
        )
    except Exception:
        pass
    return True


@router.callback_query(F.data.startswith("reject:"))
async def reject_order(cb: CallbackQuery):
    if not can_review_payments(cb.from_user.id):
        return
    oid = int(cb.data.split(":")[1])
    order = await get_order(oid)
    await update_order(oid, status="rejected")
    try:
        await cb.bot.send_message(
            order["telegram_id"],
            "❌ *سفارش شما تأیید نشد.*\n\nلطفاً با پشتیبانی در تماس باشید.",
            parse_mode="Markdown"
        )
    except Exception:
        pass
    await cb.message.answer(f"✅ سفارش #{oid} رد شد.")


# ─── PACKAGES ────────────────────────────────────────────────────

@router.message(F.text == "📦 پکیج‌ها")
async def manage_packages(msg: Message):
    if not is_admin(msg.from_user.id):
        return
    pkgs = await get_packages(active_only=False)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    for p in pkgs:
        icon = "🟢" if p["is_active"] else "🔴"
        b.button(text=f"{icon} {p['name']} | {p['traffic_gb']}GB | {p['price']:,}T",
                 callback_data=f"pkg:{p['id']}")
    b.button(text="➕ پکیج جدید", callback_data="add_pkg")
    b.adjust(1)
    await msg.answer("📦 *مدیریت پکیج‌ها*", reply_markup=b.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data == "add_pkg")
async def start_add_pkg(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(AddPackage.name)
    await cb.message.edit_text("📦 نام پکیج را وارد کنید:\n_مثال: پکیج نقره‌ای_", parse_mode="Markdown", reply_markup=flow_cancel_kb())


@router.message(AddPackage.name)
async def pkg_name(msg: Message, state: FSMContext):
    await state.update_data(name=msg.text.strip())
    await state.set_state(AddPackage.traffic)
    await msg.answer("📊 حجم ترافیک (GB):\n_مثال: 20_", parse_mode="Markdown", reply_markup=flow_cancel_kb())


@router.message(AddPackage.traffic)
async def pkg_traffic(msg: Message, state: FSMContext):
    try:
        v = float(msg.text.strip())
    except ValueError:
        await msg.answer("❌ یک عدد وارد کنید!")
        return
    await state.update_data(traffic_gb=v)
    await state.set_state(AddPackage.duration)
    await msg.answer("📅 مدت زمان (روز):\n_مثال: 30_", parse_mode="Markdown", reply_markup=flow_cancel_kb())


@router.message(AddPackage.duration)
async def pkg_duration(msg: Message, state: FSMContext):
    try:
        v = int(msg.text.strip())
    except ValueError:
        await msg.answer("❌ عدد صحیح وارد کنید!")
        return
    await state.update_data(duration_days=v)
    await state.set_state(AddPackage.price)
    await msg.answer("💰 قیمت (تومن):\n_مثال: 100000_", parse_mode="Markdown", reply_markup=flow_cancel_kb())


@router.message(AddPackage.price)
async def pkg_price(msg: Message, state: FSMContext):
    try:
        v = int(msg.text.strip().replace(",", "").replace("،", ""))
    except ValueError:
        await msg.answer("❌ عدد وارد کنید!")
        return
    await state.update_data(price=v)
    await state.set_state(AddPackage.description)
    await msg.answer("📝 توضیحات پکیج (اختیاری — برای رد کردن `-` بزن):", parse_mode="Markdown", reply_markup=flow_cancel_kb())


@router.message(AddPackage.description)
async def pkg_desc(msg: Message, state: FSMContext):
    desc = "" if msg.text.strip() == "-" else msg.text.strip()
    data = await state.get_data()
    await state.clear()
    pid = await add_package(data["name"], data["traffic_gb"], data["duration_days"], data["price"], desc)
    await msg.answer(
        f"✅ *پکیج اضافه شد!*\n\n"
        f"📦 {data['name']} | {data['traffic_gb']}GB | {data['duration_days']} روز | {data['price']:,} تومن",
        parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("pkg:"))
async def pkg_detail(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    pid = int(cb.data.split(":")[1])
    p = await get_package(pid)
    if not p:
        await cb.answer("یافت نشد!", show_alert=True)
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="🔴 غیرفعال" if p["is_active"] else "🟢 فعال", callback_data=f"toggle_pkg:{pid}")
    b.button(text="🗑️ حذف", callback_data=f"del_pkg_confirm:{pid}")
    b.button(text="🔙 بازگشت", callback_data="pkg_list_back")
    b.adjust(2, 1)
    icon = "🟢" if p["is_active"] else "🔴"
    await cb.message.edit_text(
        f"📦 *{p['name']}* {icon}\n"
        f"📊 حجم: `{p['traffic_gb']} GB`\n"
        f"📅 مدت: `{p['duration_days']} روز`\n"
        f"💰 قیمت: `{p['price']:,} تومن`\n"
        f"📝 توضیحات: {p['description'] or '—'}",
        reply_markup=b.as_markup(), parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("toggle_pkg:"))
async def toggle_pkg(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    pid = int(cb.data.split(":")[1])
    p = await get_package(pid)
    await update_package(pid, is_active=0 if p["is_active"] else 1)
    await cb.answer("✅ وضعیت تغییر کرد")
    await pkg_detail(cb)


@router.callback_query(F.data.startswith("del_pkg_confirm:"))
async def del_pkg_confirm(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    pid = cb.data.split(":")[1]
    await cb.message.edit_text(
        "⚠️ پکیج حذف می‌شود. مطمئنید؟",
        reply_markup=confirm_kb(f"del_pkg:{pid}", "pkg_list_back")
    )


@router.callback_query(F.data.startswith("del_pkg:"))
async def del_pkg(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    pid = int(cb.data.split(":")[1])
    await delete_package(pid)
    await cb.answer("✅ پکیج حذف شد")
    await _pkg_list(cb)


@router.callback_query(F.data == "pkg_list_back")
async def pkg_list_cb(cb: CallbackQuery):
    await _pkg_list(cb)


async def _pkg_list(cb: CallbackQuery):
    pkgs = await get_packages(active_only=False)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    for p in pkgs:
        icon = "🟢" if p["is_active"] else "🔴"
        b.button(text=f"{icon} {p['name']} | {p['traffic_gb']}GB", callback_data=f"pkg:{p['id']}")
    b.button(text="➕ پکیج جدید", callback_data="add_pkg")
    b.adjust(1)
    await cb.message.edit_text("📦 *مدیریت پکیج‌ها*", reply_markup=b.as_markup(), parse_mode="Markdown")


# ─── CONFIG MANAGEMENT ──────────────────────────────────────────

@router.message(F.text == "🔑 مدیریت کانفیگ")
async def manage_configs(msg: Message):
    if not is_admin(msg.from_user.id):
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="➕ ساخت کانفیگ تکی", callback_data="create_single")
    b.button(text="📋 ساخت گروهی", callback_data="create_bulk")
    b.button(text="📜 لیست همه کانفیگ‌ها", callback_data="adm_cfg_list")
    b.adjust(2, 1)
    await msg.answer("🔑 *مدیریت کانفیگ‌ها*", reply_markup=b.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data == "adm_cfg_list")
async def adm_cfg_list(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    configs = await get_all_configs()
    if not configs:
        await cb.message.edit_text("📭 هیچ کانفیگی وجود ندارد.")
        return
    await cb.message.edit_text(
        f"📜 *لیست کانفیگ‌ها* ({len(configs)} مورد)",
        reply_markup=admin_configs_kb(configs, 0), parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("adm_cfg_pg:"))
async def adm_cfg_page(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    page = int(cb.data.split(":")[1])
    configs = await get_all_configs()
    await cb.message.edit_text(
        f"📜 *لیست کانفیگ‌ها* ({len(configs)} مورد) — صفحه {page+1}",
        reply_markup=admin_configs_kb(configs, page), parse_mode="Markdown"
    )


async def _render_cfg_detail(message, cid: int):
    cfg = await get_config(cid)
    if not cfg:
        await message.edit_text("یافت نشد!")
        return
    dl = days_left(cfg["expire_timestamp"] or 0)
    dl_text = f"{dl} روز" if dl >= 0 else "نامحدود"
    status = "🟢 فعال" if cfg["is_active"] else "🔴 غیرفعال"
    owner_name = cfg.get("owner_name") or "—"
    owner_tid = cfg.get("owner_telegram_id") or "—"
    owner_un = cfg.get("owner_username")
    owner_line = f"👤 مالک: {owner_name}" + (f" (@{owner_un})" if owner_un else "") + f"\n🆔 آیدی: `{owner_tid}`"
    can_convert = bool(cfg["is_active"]) and (await get_setting("multi_sub_enabled", "0") == "1")
    await message.edit_text(
        f"🔑 *{cfg['email']}*\n"
        f"{owner_line}\n"
        f"🖥️ سرور: `{cfg['server_name']}`\n"
        f"📊 حجم: `{cfg['traffic_gb']} GB`\n"
        f"📅 باقی‌مانده: `{dl_text}`\n"
        f"📡 وضعیت: {status}",
        reply_markup=adm_config_detail_kb(cid, bool(cfg["is_active"]), can_convert=can_convert),
        parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("adm_cfg:"))
async def adm_cfg_detail(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    cid = int(cb.data.split(":")[1])
    await _render_cfg_detail(cb.message, cid)
    try:
        await cb.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("adm_cfg_link:"))
async def adm_cfg_link(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    cid = int(cb.data.split(":")[1])
    cfg = await get_config(cid)
    if not cfg:
        await cb.answer("یافت نشد", show_alert=True)
        return
    await cb.answer("در حال دریافت لینک...")
    cli = XUIClient(cfg["server_url"], cfg["srv_user"], cfg["srv_pass"], cfg.get("sub_path") or "", cfg.get("srv_api_token", ""))
    try:
        link = await asyncio.wait_for(cli.get_client_link(cfg["inbound_id"], cfg["email"]), timeout=15)
    except Exception:
        link = None
    finally:
        await cli.close()
    if not link:
        await cb.message.answer("❌ لینک اتصال به‌دست نیامد (سرور کند یا کانفیگ روی سرور نیست).", parse_mode=None)
        return
    await cb.message.answer(f"🔗 لینک اتصال «{cfg['email']}»:\n\n`{link}`", parse_mode="Markdown", reply_markup=config_links_kb(link, ""))


@router.callback_query(F.data.startswith("adm_cfg2sub:"))
async def adm_cfg2sub_confirm(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    cid = int(cb.data.split(":")[1])
    cfg = await get_config(cid)
    if not cfg or not int(cfg.get("is_active") or 0):
        await cb.answer("این کانفیگ فعال نیست.", show_alert=True)
        return
    owner = cfg.get("owner_name") or cfg.get("owner_telegram_id") or "کاربر"
    await cb.message.answer(
        "🧬 تبدیل کانفیگ تکی به لینک ساب چندسروره\n\n"
        f"کانفیگ: {cfg.get('email')}\n"
        f"مالک: {owner}\n\n"
        "با تایید: باقی‌ماندهٔ حجم/زمان به ساب جدید منتقل، کانفیگ قبلی غیرفعال، "
        "و لینک ساب مستقیماً برای خود کاربر ارسال می‌شود.",
        reply_markup=confirm_kb(f"adm_cfg2sub_do:{cid}", f"adm_cfg:{cid}"),
        parse_mode=None,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm_cfg2sub_do:"))
async def adm_cfg2sub_do(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    cid = int(cb.data.split(":")[1])
    cfg = await get_config(cid)
    if not cfg or not int(cfg.get("is_active") or 0):
        await cb.answer("این کانفیگ فعال نیست یا قبلاً تبدیل شده.", show_alert=True)
        return
    owner_user = await get_user_by_id(int(cfg.get("user_id") or 0))
    if not owner_user:
        await cb.answer("مالک این کانفیگ پیدا نشد.", show_alert=True)
        return
    await cb.answer("⏳ در حال تبدیل...")
    try:
        await cb.message.edit_text("⏳ در حال تبدیل به ساب و ارسال به کاربر...", parse_mode=None)
    except Exception:
        pass
    result = await create_profile_from_config(owner_user, cfg)
    if not result.get("ok"):
        await cb.message.answer(
            "❌ تبدیل ناموفق بود.\nعلت: " + subscription_error_message(str(result.get("error") or "")),
            parse_mode=None,
        )
        return

    sub_url = result["url"]
    # Deliver the sub link straight to the user.
    delivered = False
    try:
        await cb.bot.send_message(
            owner_user["telegram_id"],
            "🎉 سرویس شما به لینک ساب چندسروره ارتقا یافت.\n\n"
            f"حجم باقی‌مانده: {fmt_bytes(int(result.get('remaining_bytes') or 0))}\n"
            f"روز باقی‌مانده: {int(result.get('duration_days') or 0)} روز\n"
            f"نودهای فعال: {int(result.get('nodes') or 0)}\n\n"
            f"لینک ساب شما:\n{sub_url}",
            parse_mode=None,
            reply_markup=config_links_kb("", sub_url),
        )
        try:
            await cb.bot.send_photo(owner_user["telegram_id"], _qr_input_file(sub_url, result.get("email") or "Subscription"), caption="QR سابسکریپشن", parse_mode=None)
        except Exception:
            pass
        delivered = True
    except Exception:
        delivered = False

    await cb.message.answer(
        ("✅ تبدیل انجام شد و لینک ساب برای کاربر ارسال شد.\n" if delivered
         else "✅ تبدیل انجام شد، اما ارسال پیام به کاربر ناموفق بود (شاید ربات را بلاک کرده).\n")
        + f"نودهای فعال: {int(result.get('nodes') or 0)}\n\nلینک ساب:\n{sub_url}",
        parse_mode=None,
        reply_markup=config_links_kb("", sub_url),
    )


@router.callback_query(F.data.startswith("adm_cfg_msg:"))
async def adm_cfg_msg_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    cid = int(cb.data.split(":")[1])
    cfg = await get_config(cid)
    if not cfg or not cfg.get("owner_telegram_id"):
        await cb.answer("مالک این کانفیگ پیدا نشد.", show_alert=True)
        return
    await state.set_state(PrivateMessage.text)
    await state.update_data(uid=int(cfg["owner_telegram_id"]))
    await cb.message.answer(
        f"✍️ متن پیام به مالک «{cfg.get('email')}» را ارسال کنید:",
        reply_markup=flow_cancel_kb(),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm_cfg_renew:"))
async def adm_cfg_renew(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    cid = int(cb.data.split(":")[1])
    cfg = await get_config(cid)
    if not cfg:
        await cb.answer("یافت نشد", show_alert=True)
        return
    await cb.answer("⏳ در حال تمدید...")
    traffic_gb = float(cfg.get("traffic_gb") or 0)
    duration = int(cfg.get("duration_days") or 0) or 30
    result = await find_and_renew_config(cfg, traffic_gb, duration)
    if result.get("ok"):
        owner_tid = cfg.get("owner_telegram_id")
        if owner_tid:
            try:
                await cb.bot.send_message(
                    int(owner_tid),
                    f"✅ سرویس «{cfg.get('email')}» شما تمدید شد.\n"
                    f"مدت اضافه‌شده: {duration} روز | حجم: {traffic_gb:g} GB (ریست شد).",
                    parse_mode=None,
                )
            except Exception:
                pass
        await cb.message.answer(f"✅ تمدید شد: +{duration} روز | حجم {traffic_gb:g}GB ریست شد.", parse_mode=None)
        await _render_cfg_detail(cb.message, cid)
    else:
        await cb.message.answer("❌ تمدید ناموفق بود: " + str(result.get("error") or "-"), parse_mode=None)


# ─── ADMIN SUBSCRIPTION PANEL (send sub link → full control) ──────

def _extract_sub_token_from_text(text: str) -> str:
    raw = (text or "").strip()
    m = re.search(r"/sub/([A-Za-z0-9_\-]{8,})", raw)
    if m:
        return m.group(1)
    return ""


async def _render_sub_panel(message, pid: int):
    profile = await get_subscription_profile(pid)
    if not profile:
        await message.edit_text("ساب یافت نشد.", parse_mode=None)
        return
    owner = await get_user_by_id(int(profile.get("user_id") or 0))
    nodes = await get_subscription_nodes(pid)
    active_nodes = [n for n in nodes if int(n.get("is_active") or 0)]
    used = int(profile.get("used_bytes") or 0)
    total = int(float(profile.get("traffic_gb") or 0) * 1024 ** 3)
    remaining = max(0, total - used) if total > 0 else 0
    not_started = int(profile.get("starts_on_first_use") or 0) and int(profile.get("first_use_at") or 0) <= 0
    dl = days_left(int(profile.get("expire_timestamp") or 0))
    if not_started:
        dur = int(profile.get("duration_days") or 0)
        dl_text = f"از اولین اتصال ({dur} روز)"
    else:
        dl_text = f"{dl} روز" if dl > 0 else ("نامحدود" if dl < 0 else "منقضی")
    sub_url = await subscription_url(profile["token"])
    is_active = bool(int(profile.get("is_active") or 0))
    owner_name = (owner or {}).get("full_name") or "—"
    owner_tid = (owner or {}).get("telegram_id") or "—"
    text = (
        "📡 پنل مدیریت ساب\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"نام: {profile.get('name') or profile.get('email') or pid}\n"
        f"👤 مالک: {owner_name} | 🆔 {owner_tid}\n"
        f"وضعیت: {'🟢 فعال' if is_active else '🔴 غیرفعال'}\n"
        f"حجم: {fmt_bytes(used)} از {fmt_bytes(total) if total>0 else 'نامحدود'} (باقی {fmt_bytes(remaining) if total>0 else '∞'})\n"
        f"زمان باقی‌مانده: {dl_text}\n"
        f"نودهای فعال: {len(active_nodes)} از {len(nodes)}\n\n"
        f"لینک ساب:\n{sub_url}"
    )
    await message.edit_text(text, reply_markup=adm_sub_panel_kb(pid, is_active, int(profile.get("user_id") or 0)), parse_mode=None)


@router.message(StateFilter(None), lambda msg: bool(msg.text and _extract_sub_token_from_text(msg.text) and _db_admin_role(msg.from_user.id) in ("owner", "full")))
async def admin_sub_link_lookup(msg: Message):
    token = _extract_sub_token_from_text(msg.text or "")
    profile = await get_subscription_profile_by_token(token)
    if not profile:
        await msg.answer("❌ این لینک ساب در دیتابیس پیدا نشد.", parse_mode=None)
        return
    sent = await msg.answer("🔎 ساب پیدا شد. در حال بارگذاری پنل...", parse_mode=None)
    await _render_sub_panel(sent, int(profile["id"]))


@router.callback_query(F.data.startswith("adm_sub:"))
async def adm_sub_open(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    await _render_sub_panel(cb.message, int(cb.data.split(":")[1]))
    try:
        await cb.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("adm_sub_toggle:"))
async def adm_sub_toggle(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    pid = int(cb.data.split(":")[1])
    profile = await get_subscription_profile(pid)
    if not profile:
        await cb.answer("یافت نشد", show_alert=True)
        return
    new_active = not bool(int(profile.get("is_active") or 0))
    await cb.answer("⏳ در حال اعمال...")
    await update_subscription_profile(pid, is_active=1 if new_active else 0)
    try:
        await set_nodes_enabled(pid, new_active)
    except Exception:
        pass
    await _render_sub_panel(cb.message, pid)


@router.callback_query(F.data.startswith("adm_sub_renew:"))
async def adm_sub_renew(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    pid = int(cb.data.split(":")[1])
    profile = await get_subscription_profile(pid)
    if not profile:
        await cb.answer("یافت نشد", show_alert=True)
        return
    await cb.answer("⏳ در حال تمدید...")
    traffic_gb = float(profile.get("traffic_gb") or 0)
    duration = int(profile.get("duration_days") or 0) or 30
    result = await renew_subscription_profile(profile, traffic_gb, duration)
    if result.get("ok"):
        owner = await get_user_by_id(int(profile.get("user_id") or 0))
        if owner:
            try:
                await cb.bot.send_message(owner["telegram_id"], f"✅ لینک ساب شما تمدید شد (+{duration} روز، حجم {traffic_gb:g}GB).", parse_mode=None)
            except Exception:
                pass
        await cb.message.answer(f"✅ ساب تمدید شد (+{duration} روز).", parse_mode=None)
        await _render_sub_panel(cb.message, pid)
    else:
        await cb.message.answer("❌ تمدید ناموفق: " + str(result.get("error") or "-"), parse_mode=None)


@router.callback_query(F.data.startswith("adm_sub_edit:"))
async def adm_sub_edit_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    pid = int(cb.data.split(":")[1])
    profile = await get_subscription_profile(pid)
    if not profile:
        await cb.answer("یافت نشد", show_alert=True)
        return
    await state.set_state(EditSubProfile.traffic)
    await state.update_data(pid=pid)
    cur_gb = float(profile.get("traffic_gb") or 0)
    cur_days = days_left(int(profile.get("expire_timestamp") or 0))
    cur_days_txt = "نامحدود" if cur_days < 0 else f"{cur_days} روز"
    await cb.message.answer(
        "✏️ ویرایش ساب\n\n"
        f"حجم فعلی: {cur_gb:g} GB | زمان باقی‌مانده: {cur_days_txt}\n\n"
        "حجم کل جدید را به گیگابایت بفرست (عدد). برای نامحدود ۰ بفرست.",
        parse_mode=None,
        reply_markup=flow_cancel_kb(),
    )
    await cb.answer()


@router.message(EditSubProfile.traffic)
async def adm_sub_edit_traffic(msg: Message, state: FSMContext):
    raw = (msg.text or "").strip().replace(",", ".")
    try:
        traffic_gb = max(0.0, float(raw))
    except ValueError:
        await msg.answer("عدد معتبر بفرست (مثلاً 50). برای نامحدود ۰.", parse_mode=None)
        return
    await state.update_data(traffic_gb=traffic_gb)
    await state.set_state(EditSubProfile.duration)
    await msg.answer(
        "📅 مدت جدید را به روز بفرست (از همین الان محاسبه می‌شود). برای نامحدود ۰ بفرست.",
        parse_mode=None,
        reply_markup=flow_cancel_kb(),
    )


@router.message(EditSubProfile.duration)
async def adm_sub_edit_duration(msg: Message, state: FSMContext):
    raw = (msg.text or "").strip()
    try:
        duration_days = max(0, int(float(raw)))
    except ValueError:
        await msg.answer("عدد معتبر بفرست (مثلاً 30). برای نامحدود ۰.", parse_mode=None)
        return
    data = await state.get_data()
    await state.clear()
    pid = int(data.get("pid") or 0)
    traffic_gb = float(data.get("traffic_gb") or 0)
    profile = await get_subscription_profile(pid)
    if not profile:
        await msg.answer("❌ ساب پیدا نشد.", parse_mode=None)
        return
    expire_ms = int(time.time() * 1000) + duration_days * 86400000 if duration_days > 0 else 0
    await msg.answer("⏳ در حال اعمال تغییرات روی همهٔ نودها...", parse_mode=None)
    result = await edit_subscription_profile(profile, profile.get("email") or f"sub_{pid}", traffic_gb, expire_ms, is_active=True)
    if not result.get("ok"):
        await msg.answer("❌ ویرایش ناموفق: " + str(result.get("error") or "-"), parse_mode=None)
        return
    owner = await get_user_by_id(int(profile.get("user_id") or 0))
    if owner:
        gb_txt = "نامحدود" if traffic_gb <= 0 else f"{traffic_gb:g}GB"
        days_txt = "نامحدود" if duration_days <= 0 else f"{duration_days} روز"
        try:
            await msg.bot.send_message(owner["telegram_id"], f"🛠 سرویس شما به‌روزرسانی شد.\nحجم: {gb_txt} | مدت: {days_txt}", parse_mode=None)
        except Exception:
            pass
    sent = await msg.answer("✅ ساب ویرایش شد. در حال بارگذاری پنل...", parse_mode=None)
    await _render_sub_panel(sent, pid)


@router.callback_query(F.data.startswith("adm_sub_send:"))
async def adm_sub_send(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    pid = int(cb.data.split(":")[1])
    profile = await get_subscription_profile(pid)
    if not profile:
        await cb.answer("یافت نشد", show_alert=True)
        return
    owner = await get_user_by_id(int(profile.get("user_id") or 0))
    if not owner:
        await cb.answer("مالک پیدا نشد", show_alert=True)
        return
    sub_url = await subscription_url(profile["token"])
    try:
        await cb.bot.send_message(
            owner["telegram_id"],
            f"📡 لینک ساب شما:\n{sub_url}",
            parse_mode=None,
            reply_markup=config_links_kb("", sub_url),
        )
        try:
            await cb.bot.send_photo(owner["telegram_id"], _qr_input_file(sub_url, profile.get("name") or profile.get("email") or "Subscription"), caption="QR سابسکریپشن", parse_mode=None)
        except Exception:
            pass
        await cb.answer("✅ برای کاربر ارسال شد", show_alert=True)
    except Exception:
        await cb.answer("❌ ارسال ناموفق (شاید ربات بلاک شده)", show_alert=True)


@router.callback_query(F.data.startswith("adm_sub_msg:"))
async def adm_sub_msg_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    pid = int(cb.data.split(":")[1])
    profile = await get_subscription_profile(pid)
    owner = await get_user_by_id(int((profile or {}).get("user_id") or 0)) if profile else None
    if not owner:
        await cb.answer("مالک پیدا نشد", show_alert=True)
        return
    await state.set_state(PrivateMessage.text)
    await state.update_data(uid=int(owner["telegram_id"]))
    await cb.message.answer("✍️ متن پیام به مالک این ساب را ارسال کنید:", reply_markup=flow_cancel_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("adm_sub_del:"))
async def adm_sub_del_confirm(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    pid = int(cb.data.split(":")[1])
    await cb.message.answer(
        "🗑️ حذف کامل این ساب؟ همهٔ نودهای آن از سرورها و رکورد محلی حذف می‌شود.",
        reply_markup=confirm_kb(f"adm_sub_del_do:{pid}", f"adm_sub:{pid}"),
        parse_mode=None,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm_sub_del_do:"))
async def adm_sub_del_do(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    pid = int(cb.data.split(":")[1])
    await cb.answer("⏳ در حال حذف...")
    result = await delete_subscription_profile_remote(pid)
    await cb.message.answer(
        f"✅ ساب حذف شد. نودهای حذف‌شده: {result.get('deleted', 0)} | خطا: {result.get('failed', 0)}",
        parse_mode=None,
    )


@router.callback_query(F.data.startswith("toggle_cfg:"))
async def toggle_cfg(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    cid = int(cb.data.split(":")[1])
    cfg = await get_config(cid)
    server = await get_server(cfg["server_id"])
    new_status = not cfg["is_active"]
    traffic_bytes = int(cfg["traffic_gb"] * 1024 ** 3)
    cli = XUIClient(server["url"], server["username"], server["password"], server["sub_path"], server.get("api_token", ""))
    ok = await cli.update_client(cfg["inbound_id"], cfg["uuid"], cfg["email"],
                                  cfg["traffic_gb"], cfg["expire_timestamp"] or 0, new_status)
    await cli.close()
    if ok:
        await update_config(cid, is_active=1 if new_status else 0)
        await cb.answer("✅ وضعیت تغییر کرد")
    else:
        await cb.answer("❌ خطا در اتصال به سرور", show_alert=True)
    await adm_cfg_detail(cb)


@router.callback_query(F.data.startswith("edit_gb:"))
async def edit_gb_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    cid = int(cb.data.split(":")[1])
    await state.set_state(EditConfig.traffic)
    await state.update_data(cid=cid)
    await cb.message.edit_text("📊 حجم جدید را به GB وارد کنید:\n_مثال: 30_", parse_mode="Markdown", reply_markup=flow_cancel_kb())


@router.message(EditConfig.traffic)
async def edit_gb_apply(msg: Message, state: FSMContext):
    try:
        new_gb = float(msg.text.strip())
    except ValueError:
        await msg.answer("❌ عدد وارد کنید!")
        return
    data = await state.get_data()
    await state.clear()
    cid = data["cid"]
    cfg = await get_config(cid)
    server = await get_server(cfg["server_id"])
    cli = XUIClient(server["url"], server["username"], server["password"], server["sub_path"], server.get("api_token", ""))
    ok = await cli.update_client(cfg["inbound_id"], cfg["uuid"], cfg["email"],
                                  new_gb, cfg["expire_timestamp"] or 0, bool(cfg["is_active"]))
    await cli.close()
    if ok:
        await update_config(cid, traffic_gb=new_gb)
        await msg.answer(f"✅ حجم کانفیگ به *{new_gb} GB* تغییر کرد.", parse_mode="Markdown")
    else:
        await msg.answer("❌ خطا در تغییر حجم روی سرور")


@router.callback_query(F.data.startswith("edit_exp:"))
async def edit_exp_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    cid = int(cb.data.split(":")[1])
    await state.set_state(EditConfig.expire)
    await state.update_data(cid=cid)
    await cb.message.edit_text("📅 تعداد روز از امروز وارد کنید:\n_مثال: 30_", parse_mode="Markdown", reply_markup=flow_cancel_kb())


@router.message(EditConfig.expire)
async def edit_exp_apply(msg: Message, state: FSMContext):
    try:
        days = int(msg.text.strip())
    except ValueError:
        await msg.answer("❌ عدد صحیح وارد کنید!")
        return
    data = await state.get_data()
    await state.clear()
    cid = data["cid"]
    cfg = await get_config(cid)
    server = await get_server(cfg["server_id"])
    new_exp_ms = int((datetime.now() + timedelta(days=days)).timestamp() * 1000)
    cli = XUIClient(server["url"], server["username"], server["password"], server["sub_path"], server.get("api_token", ""))
    ok = await cli.update_client(cfg["inbound_id"], cfg["uuid"], cfg["email"],
                                  cfg["traffic_gb"], new_exp_ms, bool(cfg["is_active"]))
    await cli.close()
    if ok:
        await update_config(cid, expire_timestamp=new_exp_ms, duration_days=days)
        await msg.answer(f"✅ تاریخ انقضا به *{days} روز* از امروز تنظیم شد.", parse_mode="Markdown")
    else:
        await msg.answer("❌ خطا در تغییر تاریخ روی سرور")


@router.callback_query(F.data.startswith("del_cfg:"))
async def del_cfg_confirm(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    cid = cb.data.split(":")[1]
    await cb.message.edit_text(
        "⚠️ کانفیگ از سرور *و* دیتابیس حذف می‌شود. مطمئنید؟",
        reply_markup=confirm_kb(f"del_cfg_do:{cid}", "adm_cfg_list"),
        parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("del_cfg_do:"))
async def del_cfg_do(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    cid = int(cb.data.split(":")[1])
    cfg = await get_config(cid)
    if cfg:
        server = await get_server(cfg["server_id"])
        cli = XUIClient(server["url"], server["username"], server["password"], server["sub_path"], server.get("api_token", ""))
        await cli.delete_client(cfg["inbound_id"], cfg["uuid"], cfg.get("email", ""))
        await cli.close()
        await update_config(cid, is_active=0)
    await cb.answer("✅ حذف شد")
    await adm_cfg_list(cb)


# ─── SINGLE CONFIG ───────────────────────────────────────────────

@router.callback_query(F.data == "create_single")
async def create_single_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(CreateConfig.email)
    await cb.message.edit_text(
        "📧 شناسه (ایمیل) کانفیگ را وارد کنید:\n_مثال: ali_vip_30d_",
        parse_mode="Markdown",
        reply_markup=flow_cancel_kb(),
    )


@router.message(CreateConfig.email)
async def single_email(msg: Message, state: FSMContext):
    await state.update_data(email=msg.text.strip().replace(" ", "_"))
    await state.set_state(CreateConfig.traffic)
    await msg.answer("📊 حجم ترافیک (GB):", reply_markup=flow_cancel_kb())


@router.message(CreateConfig.traffic)
async def single_traffic(msg: Message, state: FSMContext):
    try:
        v = float(msg.text.strip())
    except ValueError:
        await msg.answer("❌ عدد وارد کنید!")
        return
    await state.update_data(traffic_gb=v)
    await state.set_state(CreateConfig.duration)
    await msg.answer("📅 مدت (روز):", reply_markup=flow_cancel_kb())


@router.message(CreateConfig.duration)
async def single_duration(msg: Message, state: FSMContext):
    try:
        v = int(msg.text.strip())
    except ValueError:
        await msg.answer("❌ عدد صحیح وارد کنید!")
        return
    await state.update_data(duration_days=v)
    await state.set_state(CreateConfig.server)
    servers = await get_servers()
    await msg.answer("🖥️ سرور را انتخاب کنید:", reply_markup=servers_kb(servers, "single_srv", with_back=True))


@router.callback_query(F.data.startswith("single_srv:"), CreateConfig.server)
async def single_server(cb: CallbackQuery, state: FSMContext):
    sid = int(cb.data.split(":")[1])
    data = await state.get_data()
    await state.clear()
    server = await get_server(sid)
    await cb.message.edit_text("⏳ در حال ساخت کانفیگ...")

    cli = XUIClient(server["url"], server["username"], server["password"], server["sub_path"], server.get("api_token", ""))
    cuuid = str(uuid.uuid4())
    ok = await cli.add_client(server["inbound_id"], cuuid, data["email"],
                               data["traffic_gb"], data["duration_days"], starts_on_first_use=False)
    if not ok:
        await cli.close()
        await cb.message.edit_text("❌ خطا در ساخت کانفیگ روی سرور!")
        return
    expire_ms = expiry_ms_from_days(data["duration_days"])
    link = await cli.get_client_link(server["inbound_id"], data["email"])
    await cli.close()

    text = (
        f"✅ *کانفیگ ساخته شد!*\n"
        f"📧 `{data['email']}`\n"
        f"📊 {data['traffic_gb']} GB | 📅 {data['duration_days']} روز\n"
        f"🖥️ {server['name']}"
    )
    if link:
        text += f"\n\n🔗 *لینک:*\n`{link}`"
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=config_links_kb(link or "", ""))
    if link:
        try:
            ch = await get_setting("channel_username", "AtlasChannel")
            await cb.message.answer_photo(_qr_input_file(link, ch), caption=f"QR: {data['email']}", parse_mode=None)
        except Exception:
            pass


# ─── BULK CONFIG ─────────────────────────────────────────────────

@router.callback_query(F.data == "create_bulk")
async def create_bulk_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(BulkConfig.prefix)
    await cb.message.edit_text(
        "📋 *ساخت گروهی*\n\nپیشوند نام کانفیگ‌ها:\n_مثال: vip_user_",
        parse_mode="Markdown",
        reply_markup=flow_cancel_kb(),
    )


@router.message(BulkConfig.prefix)
async def bulk_prefix(msg: Message, state: FSMContext):
    await state.update_data(prefix=msg.text.strip().replace(" ", "_"))
    await state.set_state(BulkConfig.count)
    await msg.answer("🔢 تعداد کانفیگ (حداکثر ۵۰):", reply_markup=flow_cancel_kb())


@router.message(BulkConfig.count)
async def bulk_count(msg: Message, state: FSMContext):
    try:
        n = min(50, max(1, int(msg.text.strip())))
    except ValueError:
        await msg.answer("❌ عدد وارد کنید!")
        return
    await state.update_data(count=n)
    await state.set_state(BulkConfig.traffic)
    await msg.answer("📊 حجم هر کانفیگ (GB):", reply_markup=flow_cancel_kb())


@router.message(BulkConfig.traffic)
async def bulk_traffic(msg: Message, state: FSMContext):
    try:
        v = float(msg.text.strip())
    except ValueError:
        await msg.answer("❌ عدد وارد کنید!")
        return
    await state.update_data(traffic_gb=v)
    await state.set_state(BulkConfig.duration)
    await msg.answer("📅 مدت (روز):", reply_markup=flow_cancel_kb())


@router.message(BulkConfig.duration)
async def bulk_duration(msg: Message, state: FSMContext):
    try:
        v = int(msg.text.strip())
    except ValueError:
        await msg.answer("❌ عدد وارد کنید!")
        return
    await state.update_data(duration_days=v)
    await state.set_state(BulkConfig.server)
    servers = await get_servers()
    await msg.answer("🖥️ سرور را انتخاب کنید:", reply_markup=servers_kb(servers, "bulk_srv", with_back=True))


@router.callback_query(F.data.startswith("bulk_srv:"), BulkConfig.server)
async def bulk_server(cb: CallbackQuery, state: FSMContext):
    sid = int(cb.data.split(":")[1])
    data = await state.get_data()
    await state.clear()
    server = await get_server(sid)
    await cb.message.edit_text(f"⏳ در حال ساخت {data['count']} کانفیگ...")

    cli = XUIClient(server["url"], server["username"], server["password"], server["sub_path"], server.get("api_token", ""))
    expire_ms = expiry_ms_from_days(data["duration_days"])
    results = []

    for i in range(1, data["count"] + 1):
        email = f"{data['prefix']}_{i:03d}"
        cuuid = str(uuid.uuid4())
        ok = await cli.add_client(server["inbound_id"], cuuid, email,
                                   data["traffic_gb"], data["duration_days"], starts_on_first_use=False)
        if ok:
            link = await cli.get_client_link(server["inbound_id"], email)
            results.append(f"✅ `{email}`\n`{link or '—'}`")
        else:
            results.append(f"❌ `{email}` — خطا")
        await asyncio.sleep(0.2)

    await cli.close()
    success = sum(1 for r in results if r.startswith("✅"))
    header = f"📋 *نتیجه ساخت گروهی*\n✅ موفق: {success} | ❌ ناموفق: {data['count']-success}\n\n"
    preview = "\n\n".join(results[:8])
    more = f"\n\n... و {len(results)-8} مورد دیگر" if len(results) > 8 else ""
    await cb.message.edit_text(header + preview + more, parse_mode="Markdown")


# ─── USERS ───────────────────────────────────────────────────────

@router.message(F.text == "👥 کاربران")
async def manage_users(msg: Message):
    if not is_admin(msg.from_user.id):
        return
    total = await count_users()
    users = await get_all_users(0, 10)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    for u in users:
        icon = "🔴" if u["is_blocked"] else "🟢"
        name = u["full_name"] or u["username"] or str(u["telegram_id"])
        b.button(text=f"{icon} {name}", callback_data=f"usr:{u['id']}")
    b.button(text="▶️ صفحه بعد", callback_data="usr_pg:1")
    b.adjust(1)
    await msg.answer(
        f"👥 *مدیریت کاربران* — {total} نفر",
        reply_markup=b.as_markup(), parse_mode="Markdown"
    )


async def _render_user_card(message, uid: int):
    u = await get_user_by_id(uid)
    if not u:
        await message.edit_text("کاربر یافت نشد!", parse_mode=None)
        return
    configs = await get_user_configs(uid)
    profiles = await get_user_subscription_profiles(uid)
    active_cfg = sum(1 for c in configs if int(c.get("is_active") or 0))
    active_sub = sum(1 for p in profiles if int(p.get("is_active") or 0))
    status = "🔴 بلاک" if u["is_blocked"] else "🟢 فعال"
    role_bits = []
    if int(u.get("is_admin") or 0):
        role_bits.append("ادمین")
    if int(u.get("is_wholesale") or 0):
        role_bits.append("نماینده")
    role_line = (" | ".join(role_bits)) or "کاربر عادی"
    bal = int(u.get("balance_toman") or 0)
    name = u.get("full_name") or "—"
    un = u.get("username")
    created = str(u.get("created_at") or "")[:10]
    text = (
        f"👤 {name}" + (f" (@{un})" if un else "") + "\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🆔 آیدی: {u['telegram_id']}\n"
        f"📡 وضعیت: {status} | نقش: {role_line}\n"
        f"💰 موجودی کیف پول: {_fmt_toman(bal)} تومان\n"
        f"🔑 کانفیگ‌ها: {active_cfg} فعال از {len(configs)}\n"
        f"📡 ساب‌ها: {active_sub} فعال از {len(profiles)}\n"
        f"📅 عضویت: {created}"
    )
    await message.edit_text(text, reply_markup=adm_user_card_kb(uid, bool(u["is_blocked"])), parse_mode=None)


@router.callback_query(F.data.startswith("usr:"))
async def user_detail(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    uid = int(cb.data.split(":")[1])
    await _render_user_card(cb.message, uid)
    try:
        await cb.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("toggle_block:"))
async def toggle_block(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    uid = int(cb.data.split(":")[1])
    u = await get_user_by_id(uid)
    await update_user(uid, is_blocked=0 if u["is_blocked"] else 1)
    await cb.answer("✅ تغییر کرد")
    await _render_user_card(cb.message, uid)


@router.message(F.text == "🔍 جستجوی کاربر")
async def admin_user_search_start(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return
    await state.set_state(AdminUserSearch.query)
    await msg.answer(
        "🔍 آیدی عددی، یوزرنیم (با یا بدون @) یا بخشی از نام کاربر را بفرستید:",
        reply_markup=flow_cancel_kb(show_back=False),
    )


@router.message(AdminUserSearch.query)
async def admin_user_search_do(msg: Message, state: FSMContext):
    await state.clear()
    u = await find_user(msg.text or "")
    if not u:
        await msg.answer("❌ کاربری پیدا نشد. دوباره از «🔍 جستجوی کاربر» امتحان کنید.", parse_mode=None)
        return
    sent = await msg.answer("🔎 کاربر پیدا شد...", parse_mode=None)
    await _render_user_card(sent, int(u["id"]))


@router.callback_query(F.data.startswith("adm_usr_svcs:"))
async def adm_usr_services(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    uid = int(cb.data.split(":")[1])
    configs = await get_user_configs(uid)
    profiles = await get_user_subscription_profiles(uid)
    await cb.message.edit_text(
        f"📡 سرویس‌های کاربر — {len(profiles)} ساب | {len(configs)} کانفیگ\nیکی را برای مدیریت انتخاب کنید:",
        reply_markup=adm_user_services_kb(uid, configs, profiles),
        parse_mode=None,
    )
    try:
        await cb.answer()
    except Exception:
        pass


@router.callback_query(F.data.startswith("adm_usr_msg:"))
async def adm_usr_msg_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    uid = int(cb.data.split(":")[1])
    u = await get_user_by_id(uid)
    if not u:
        await cb.answer("یافت نشد", show_alert=True)
        return
    await state.set_state(PrivateMessage.text)
    await state.update_data(uid=int(u["telegram_id"]))
    await cb.message.answer("✍️ متن پیام به این کاربر را ارسال کنید:", reply_markup=flow_cancel_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("adm_usr_bal:"))
async def adm_usr_bal_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    uid = int(cb.data.split(":")[1])
    u = await get_user_by_id(uid)
    if not u:
        await cb.answer("یافت نشد", show_alert=True)
        return
    await state.set_state(AdminBalance.amount)
    await state.update_data(uid=uid)
    await cb.message.answer(
        f"💰 موجودی فعلی: {_fmt_toman(int(u.get('balance_toman') or 0))} تومان\n\n"
        "مبلغ تغییر را بفرستید (تومان). برای کم‌کردن، عدد منفی بدهید.\nمثال: `50000` یا `-20000`",
        reply_markup=flow_cancel_kb(show_back=False),
        parse_mode="Markdown",
    )
    await cb.answer()


@router.message(AdminBalance.amount)
async def adm_usr_bal_apply(msg: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    uid = int(data.get("uid") or 0)
    raw = (msg.text or "").strip().replace(",", "").replace("،", "")
    try:
        amount = int(float(raw))
    except ValueError:
        await msg.answer("❌ عدد معتبر نیست.", parse_mode=None)
        return
    u = await get_user_by_id(uid)
    if not u:
        await msg.answer("❌ کاربر یافت نشد.", parse_mode=None)
        return
    new_balance = await add_user_balance(uid, amount, kind="admin", note="admin_manual", actor_telegram_id=msg.from_user.id)
    sign = "اضافه" if amount >= 0 else "کسر"
    await msg.answer(f"✅ {abs(amount):,} تومان {sign} شد.\nموجودی جدید: {_fmt_toman(int(new_balance or 0))} تومان", parse_mode=None)
    try:
        await msg.bot.send_message(
            u["telegram_id"],
            ("💰 موجودی کیف پول شما به‌روزرسانی شد.\n" + (f"➕ {amount:,} تومان افزوده شد." if amount >= 0 else f"➖ {abs(amount):,} تومان کسر شد.")),
            parse_mode=None,
        )
    except Exception:
        pass
    sent = await msg.answer("بازگشت به کارت کاربر...", parse_mode=None)
    await _render_user_card(sent, uid)


@router.callback_query(F.data.startswith("wh_appr:"))
async def wholesale_approve(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    uid = int(cb.data.split(":")[1])
    u = await get_user_by_id(uid)
    if not u:
        await cb.answer("یافت نشد", show_alert=True)
        return
    await update_user(uid, is_wholesale=1, wholesale_request_pending=0)
    try:
        from bot.keyboards import user_menu
        await cb.bot.send_message(
            u["telegram_id"],
            "✅ درخواست نمایندگی شما تایید شد.\nاز این لحظه «🏢 پنل نمایندگی» برای شما فعال است.",
            reply_markup=user_menu(include_wholesale=True),
        )
    except Exception:
        pass
    await cb.message.edit_text("✅ کاربر به‌عنوان نماینده تایید شد.")


@router.callback_query(F.data.startswith("wh_rej:"))
async def wholesale_reject(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    uid = int(cb.data.split(":")[1])
    u = await get_user_by_id(uid)
    if not u:
        await cb.answer("یافت نشد", show_alert=True)
        return
    await update_user(uid, wholesale_request_pending=0)
    try:
        await cb.bot.send_message(u["telegram_id"], "❌ درخواست نمایندگی شما فعلاً تایید نشد. برای بررسی دوباره با پشتیبانی در ارتباط باشید.")
    except Exception:
        pass
    await cb.message.edit_text("❌ درخواست نمایندگی رد شد.")


def _json_obj(value, default=None):
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


async def _lookup_remote_config_status(email: str, client_uuid: str) -> dict | None:
    email = (email or "").strip()
    client_uuid = (client_uuid or "").strip()
    if not email and not client_uuid:
        return None

    for srv in await get_servers(active_only=True):
        xui = XUIClient(srv["url"], srv["username"], srv["password"], srv.get("sub_path") or "", srv.get("api_token", ""))
        try:
            inbounds = await xui.get_inbounds()
            for inbound in inbounds:
                settings = _json_obj(inbound.get("settings"), {})
                for c in settings.get("clients", []) or []:
                    c_email = (c.get("email") or "").strip()
                    c_uuid = (c.get("id") or c.get("password") or c.get("auth") or "").strip()
                    if email and c_email == email:
                        matched = True
                    elif client_uuid and c_uuid == client_uuid:
                        matched = True
                    else:
                        matched = False
                    if not matched:
                        continue

                    traffic = await xui.get_client_traffic(c_email) if c_email else None
                    total = int((traffic or {}).get("total") or c.get("totalGB") or 0)
                    down = int((traffic or {}).get("down") or c.get("down") or 0)
                    up = int((traffic or {}).get("up") or c.get("up") or 0)
                    expire_ms = int((traffic or {}).get("expiryTime") or c.get("expiryTime") or 0)
                    enabled = bool((traffic or {}).get("enable", c.get("enable", True)))
                    return {
                        "server_name": srv.get("name") or srv.get("url"),
                        "server_id": srv.get("id"),
                        "inbound_id": int(inbound.get("id") or srv.get("inbound_id") or 1),
                        "protocol": inbound.get("protocol") or "-",
                        "email": c_email or email,
                        "uuid": c_uuid or client_uuid,
                        "total": total,
                        "used": down + up,
                        "down": down,
                        "up": up,
                        "remaining": max(0, total - down - up) if total > 0 else 0,
                        "expire_ms": expire_ms,
                        "enabled": enabled,
                    }
        except Exception as e:
            logger.warning("config lookup skipped server %s: %s", srv.get("name") or srv.get("url"), e)
        finally:
            await xui.close()
    return None


def _format_remote_config_status(info: dict) -> str:
    total = int(info.get("total") or 0)
    used = int(info.get("used") or 0)
    remaining = int(info.get("remaining") or 0)
    expire_ms = int(info.get("expire_ms") or 0)
    dl = days_left(expire_ms)
    if dl < 0:
        dl_text = "نامحدود"
    elif dl == 0:
        dl_text = "منقضی یا کمتر از یک روز"
    else:
        dl_text = f"{dl} روز"
    if total > 0:
        traffic = (
            f"مصرف شده: {fmt_bytes(used)}\n"
            f"باقی‌مانده: {fmt_bytes(remaining)}\n"
            f"حجم کل: {fmt_bytes(total)}"
        )
    else:
        traffic = "حجم کل: نامحدود"
    status = "فعال" if info.get("enabled", True) else "غیرفعال"
    return (
        "🔎 اطلاعات کانفیگ\n\n"
        f"ایمیل: {info.get('email') or '-'}\n"
        f"UUID/Auth: {info.get('uuid') or '-'}\n"
        f"سرور: {info.get('server_name') or '-'}\n"
        f"Inbound: {info.get('inbound_id') or '-'} | Protocol: {info.get('protocol') or '-'}\n"
        f"وضعیت: {status}\n\n"
        f"{traffic}\n"
        f"زمان باقی‌مانده: {dl_text}"
    )


def _remaining_duration_days(expire_ms: int) -> int:
    if int(expire_ms or 0) <= 0:
        return 0
    remaining = int(expire_ms) - int(time.time() * 1000)
    if remaining <= 0:
        return 0
    day_ms = 86400000
    return max(1, (remaining + day_ms - 1) // day_ms)


async def _find_remote_legacy_client(email: str, client_uuid: str) -> dict | None:
    """Search every registered 3x-ui server/inbound and return matching client meta for import."""
    email = (email or "").strip()
    client_uuid = (client_uuid or "").strip()
    if not email and not client_uuid:
        return None

    for srv in await get_servers(active_only=False):
        xui = XUIClient(srv["url"], srv["username"], srv["password"], srv.get("sub_path") or "", srv.get("api_token", ""))
        try:
            found = await xui.find_client(email=email, client_uuid=client_uuid)
            if not found:
                continue

            client = found.get("client") or {}
            inbound = found.get("inbound") or {}
            remote_email = (client.get("email") or email).strip()
            remote_uuid = (
                client.get("id")
                or client.get("password")
                or client.get("auth")
                or client_uuid
                or remote_email
            )
            remote_uuid = str(remote_uuid).strip()
            if email and remote_email and remote_email != email and not client_uuid:
                continue

            inbound_id = int(found.get("inbound_id") or inbound.get("id") or srv.get("inbound_id") or 1)
            traffic = await xui.get_client_traffic(remote_email) if remote_email else None
            traffic = traffic if isinstance(traffic, dict) else {}
            total_bytes = int(traffic.get("total") or client.get("totalGB") or client.get("total") or 0)
            up = int(traffic.get("up") or client.get("up") or 0)
            down = int(traffic.get("down") or client.get("down") or 0)
            expire_ms = int(traffic.get("expiryTime") or client.get("expiryTime") or 0)
            enabled = bool(traffic.get("enable", client.get("enable", True)))
            link = await xui.get_client_link(inbound_id, remote_email) if remote_email else None
            sub = await xui.get_subscription_link(inbound_id, remote_email) if remote_email else None

            return {
                "server_id": srv["id"],
                "server_name": srv.get("name") or srv.get("url"),
                "inbound_id": inbound_id,
                "protocol": inbound.get("protocol") or "-",
                "uuid": remote_uuid,
                "email": remote_email or email,
                "traffic_gb": round(total_bytes / (1024 ** 3), 2) if total_bytes > 0 else 0,
                "duration_days": _remaining_duration_days(expire_ms),
                "expire_ms": expire_ms,
                "used": up + down,
                "is_active": 1 if enabled else 0,
                "link": link,
                "sub": sub,
            }
        except Exception as e:
            logger.exception("legacy sync search failed on server %s: %s", srv.get("name") or srv.get("id"), e)
            continue
        finally:
            await xui.close()

    return None


async def _send_synced_config_to_user(cb: CallbackQuery, claim: dict, cfg: dict, remote: dict | None = None):
    text = (
        "✅ کانفیگ قبلی شما به حساب ربات متصل شد.\n\n"
        f"ایمیل: `{cfg.get('email') or claim.get('email') or '-'}`\n"
        f"سرور: `{cfg.get('server_name') or (remote or {}).get('server_name') or cfg.get('server_id') or '-'}`\n"
        f"حجم ثبت‌شده: `{cfg.get('traffic_gb') or 0} GB`\n"
        f"مدت باقی‌مانده: `{cfg.get('duration_days') or 0} روز`"
    )
    link = (remote or {}).get("link") or ""
    sub = (remote or {}).get("sub") or ""
    if link:
        text += f"\n\nلینک اتصال:\n`{link}`"
    if sub:
        text += f"\n\nلینک سابسکریپشن:\n`{sub}`"
    await cb.bot.send_message(
        claim["telegram_id"],
        text,
        parse_mode="Markdown",
        reply_markup=config_links_kb(link, sub) if (link or sub) else None,
    )
    if link:
        try:
            ch = await get_setting("channel_username", "AtlasChannel")
            await cb.bot.send_photo(claim["telegram_id"], _qr_input_file(link, ch), caption=f"QR: {cfg.get('email') or claim.get('email') or ''}", parse_mode=None)
        except Exception:
            pass


@router.callback_query(F.data.startswith("lg_appr:"))
async def legacy_claim_approve(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    cid = int(cb.data.split(":")[1])
    try:
        await cb.answer("⏳ در حال جستجو و اتصال کانفیگ...")
    except Exception:
        pass
    try:
        await _legacy_claim_approve_impl(cb, cid)
    except Exception as e:
        logger.exception("legacy claim approve failed cid=%s: %s", cid, e)
        try:
            await update_legacy_claim(
                cid,
                admin_note=f"approve_error:{type(e).__name__}",
                reviewer_id=cb.from_user.id,
                reviewed_at=datetime.now().isoformat(),
            )
        except Exception:
            pass
        try:
            await cb.message.answer(
                "⚠️ تایید سینک خطا خورد، اما درخواست pending مانده و نسوخت.\n"
                "بعد از بررسی اتصال سرورها دوباره همین دکمه تایید را بزنید."
            )
        except Exception:
            pass


async def _legacy_claim_approve_impl(cb: CallbackQuery, cid: int):
    claim = await get_legacy_claim(cid)
    if not claim:
        await cb.answer("درخواست پیدا نشد.", show_alert=True)
        return

    email = (claim.get("email") or "").strip()
    claim_uuid = (claim.get("uuid") or "").strip()
    if not email and not claim_uuid:
        await update_legacy_claim(cid, status="rejected", reviewer_id=cb.from_user.id, reviewed_at=datetime.now().isoformat(), admin_note="missing_identity")
        await cb.message.edit_text("❌ ایمیل یا UUID کانفیگ در لینک پیدا نشد؛ درخواست رد شد.")
        return

    claim_status = claim.get("status") or "pending"
    if claim_status != "pending":
        existing = None
        if claim_status == "approved":
            existing = await get_config_by_email(email) if email else None
            if not existing and claim_uuid:
                existing = await get_config_by_uuid(claim_uuid)
        if existing:
            await cb.answer("این درخواست قبلاً تایید و ثبت شده است.", show_alert=True)
            return
        if claim_status == "approved":
            await update_legacy_claim(
                cid,
                status="pending",
                admin_note="retry_after_missing_config_by_admin",
                reviewer_id=0,
                reviewed_at=None,
            )
        else:
            await cb.answer("این درخواست قبلاً بررسی شده است. کاربر باید دوباره درخواست سینک بفرستد.", show_alert=True)
            return

    cfg = await get_config_by_email(email) if email else None
    if not cfg and claim_uuid:
        cfg = await get_config_by_uuid(claim_uuid)

    # اگر داخل DB نبود، مستقیم از همه سرورها/اینباندها جستجو و ایمپورت می‌کنیم.
    remote = None
    if not cfg:
        remote = await _find_remote_legacy_client(email, claim_uuid)
        if remote and remote.get("email") and remote.get("uuid"):
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
        elif remote is None:
            await update_legacy_claim(
                cid,
                admin_note=f"not_found:{datetime.now().isoformat()}",
                reviewer_id=cb.from_user.id,
                reviewed_at=datetime.now().isoformat(),
            )
            await cb.answer("کانفیگ پیدا نشد؛ درخواست pending ماند تا دوباره قابل بررسی باشد.", show_alert=True)
            await cb.message.answer(
                "❌ کانفیگ با این ایمیل/UUID روی دیتابیس یا سرورهای ثبت‌شده پیدا نشد.\n"
                "درخواست رد نشد و هنوز pending است؛ بعد از اصلاح اطلاعات سرور می‌توانید دوباره تایید بزنید."
            )
            return

    if cfg:
        if not remote:
            try:
                remote = await _find_remote_legacy_client(email or cfg.get("email", ""), claim_uuid or cfg.get("uuid", ""))
            except Exception:
                remote = None
        update_fields = {"user_id": claim["user_id"], "is_active": int((remote or {}).get("is_active", 1))}
        if remote:
            update_fields.update(
                server_id=remote["server_id"],
                inbound_id=remote["inbound_id"],
                uuid=remote["uuid"],
                traffic_gb=remote["traffic_gb"],
                duration_days=remote["duration_days"],
                expire_timestamp=remote["expire_ms"],
            )
        await update_config(cfg["id"], **update_fields)
        cfg = await get_config(cfg["id"]) or cfg
        await update_legacy_claim(cid, status="approved", reviewer_id=cb.from_user.id, reviewed_at=datetime.now().isoformat())
        try:
            await _send_synced_config_to_user(cb, claim, cfg, remote)
        except Exception:
            pass
        await cb.message.edit_text(f"✅ کانفیگ {cfg.get('email') or email} به کاربر تخصیص یافت.")
        return

    await update_legacy_claim(
        cid,
        admin_note=f"not_found:{datetime.now().isoformat()}",
        reviewer_id=cb.from_user.id,
        reviewed_at=datetime.now().isoformat(),
    )
    await cb.answer("کانفیگ پیدا نشد؛ درخواست pending ماند.", show_alert=True)
    await cb.message.answer("❌ کانفیگ با این ایمیل/UUID پیدا نشد. درخواست هنوز pending است و می‌توانید دوباره بررسی کنید.")


@router.callback_query(F.data.startswith("lg_rej:"))
async def legacy_claim_reject(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    cid = int(cb.data.split(":")[1])
    claim = await get_legacy_claim(cid)
    if not claim or claim.get("status") != "pending":
        await cb.answer("این درخواست قبلاً بررسی شده.", show_alert=True)
        return
    await update_legacy_claim(cid, status="rejected", reviewer_id=cb.from_user.id, reviewed_at=datetime.now().isoformat())
    try:
        await cb.bot.send_message(claim["telegram_id"], "❌ درخواست سینک کانفیگ شما رد شد. در صورت نیاز با پشتیبانی هماهنگ کنید.")
    except Exception:
        pass
    await cb.message.edit_text("❌ درخواست رد شد.")


# ─── BROADCAST ───────────────────────────────────────────────────

@router.message(F.text == "📣 پیام همگانی")
async def broadcast_start(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return
    await state.set_state(Broadcast.target)
    await msg.answer("📣 مخاطب پیام را انتخاب کنید:", reply_markup=broadcast_target_kb())


@router.callback_query(F.data.startswith("bc_target:"), Broadcast.target)
async def broadcast_pick_target(cb: CallbackQuery, state: FSMContext):
    target = cb.data.split(":", 1)[1]
    await state.update_data(target=target)
    await state.set_state(Broadcast.text)
    await cb.message.edit_text(
        "✍️ پیام همگانی را ارسال کنید.\n\n"
        "می‌تواند متن، عکس با کپشن، لینک، بولد یا هر پیام قابل کپی دیگری باشد.",
        reply_markup=flow_cancel_kb(),
    )


@router.message(Broadcast.text)
async def broadcast_get_text(msg: Message, state: FSMContext):
    fallback_text = (
        getattr(msg, "html_text", None)
        or getattr(msg, "html_caption", None)
        or msg.text
        or msg.caption
        or ""
    )
    await state.update_data(
        text=msg.text or msg.caption or "",
        fallback_text=fallback_text,
        source_chat_id=msg.chat.id,
        source_message_id=msg.message_id,
    )
    await state.set_state(Broadcast.buttons)
    await msg.answer(
        "🔘 می‌خواهید زیر پیام دکمه شیشه‌ای اضافه شود؟\n\n"
        "اگر بله، دکمه‌ها را به این صورت بفرستید (هر خط یک ردیف):\n"
        "`عنوان دکمه - https://example.com`\n"
        "`کانال - https://t.me/yourchannel | سایت - https://site.com`\n\n"
        "🚀 برای افزودن دکمهٔ آمادهٔ «شروع ربات» روی /startbtn بزنید.\n"
        "اگر دکمه نمی‌خواهید، روی /skip بزنید.",
        parse_mode="Markdown",
        reply_markup=flow_cancel_kb(),
    )


async def _copy_broadcast_message(bot: Bot, chat_id: int, data: dict, markup=None):
    source_chat_id = data.get("source_chat_id")
    source_message_id = data.get("source_message_id")
    if source_chat_id and source_message_id:
        kwargs = {
            "chat_id": chat_id,
            "from_chat_id": source_chat_id,
            "message_id": source_message_id,
        }
        if markup is not None:
            kwargs["reply_markup"] = markup
        return await bot.copy_message(**kwargs)

    fallback = data.get("fallback_text") or data.get("text") or ""
    if not fallback:
        raise ValueError("broadcast source message is missing")
    return await bot.send_message(chat_id, fallback, reply_markup=markup, parse_mode="HTML")


async def _broadcast_show_preview(msg: Message, state: FSMContext):
    await state.set_state(Broadcast.confirm)
    data = await state.get_data()
    all_users = await get_all_users(0, 100000)
    target = data.get("target", "all")
    if target == "wholesale":
        total = sum(1 for u in all_users if u.get("is_wholesale", 0) and not u.get("is_blocked", 0))
        target_text = "نمایندگان"
    else:
        total = sum(1 for u in all_users if not u.get("is_blocked", 0))
        target_text = "همه کاربران"
    btn_note = "✅ دارد" if data.get("buttons_raw") else "—"
    markup = parse_custom_buttons(data.get("buttons_raw") or "")
    await msg.answer(
        f"👀 *پیش‌نمایش پیام:*",
        parse_mode="Markdown",
    )
    try:
        await _copy_broadcast_message(msg.bot, msg.chat.id, data, markup)
    except Exception:
        fallback = data.get("fallback_text") or data.get("text") or "پیش‌نمایش این پیام قابل نمایش نبود، اما هنگام ارسال با روش کپی تلاش می‌شود."
        await msg.answer(fallback, reply_markup=markup, parse_mode="HTML")
    await msg.answer(
        f"🎯 مخاطب: *{target_text}*\n🔘 دکمه: {btn_note}\n📤 برای *{total}* کاربر ارسال می‌شود.",
        reply_markup=confirm_kb("broadcast_do", "broadcast_cancel"),
        parse_mode="Markdown",
    )


@router.message(Broadcast.buttons, F.text == "/skip")
async def broadcast_skip_buttons(msg: Message, state: FSMContext):
    await state.update_data(buttons_raw="")
    await _broadcast_show_preview(msg, state)


@router.message(Broadcast.buttons, F.text == "/startbtn")
async def broadcast_add_start_button(msg: Message, state: FSMContext):
    """Attach a ready-made 'Start bot' deep-link button to the broadcast post."""
    try:
        me = await msg.bot.get_me()
        username = me.username
    except Exception:
        username = None
    if not username:
        await msg.answer("⚠️ نام کاربری ربات در دسترس نیست. لینک را دستی بفرستید.")
        return
    data = await state.get_data()
    existing = (data.get("buttons_raw") or "").strip()
    start_line = f"🚀 شروع ربات - https://t.me/{username}?start"
    buttons_raw = f"{existing}\n{start_line}" if existing else start_line
    await state.update_data(buttons_raw=buttons_raw)
    await _broadcast_show_preview(msg, state)


@router.message(Broadcast.buttons)
async def broadcast_get_buttons(msg: Message, state: FSMContext):
    raw = msg.text or ""
    markup = parse_custom_buttons(raw)
    if markup is None:
        await msg.answer(
            "⚠️ هیچ دکمه معتبری پیدا نشد. قالب درست:\n"
            "`عنوان - https://example.com`\n\n"
            "دوباره بفرستید یا برای رد شدن /skip بزنید.",
            parse_mode="Markdown",
        )
        return
    await state.update_data(buttons_raw=raw)
    await _broadcast_show_preview(msg, state)


@router.callback_query(F.data == "broadcast_do", Broadcast.confirm)
async def broadcast_do(cb: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    users = await get_all_users(0, 100000)
    target = data.get("target", "all")
    markup = parse_custom_buttons(data.get("buttons_raw") or "")
    sent = failed = 0
    await cb.message.edit_text("⏳ در حال ارسال...")
    for u in users:
        if u["is_blocked"]:
            continue
        if target == "wholesale" and not u.get("is_wholesale", 0):
            continue
        try:
            await _copy_broadcast_message(bot, u["telegram_id"], data, markup)
            sent += 1
            await asyncio.sleep(0.04)
        except Exception:
            failed += 1
    await cb.message.answer(f"✅ ارسال کامل شد!\n✅ موفق: {sent} | ❌ ناموفق: {failed}")


@router.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("❌ ارسال لغو شد.")


# ─── REFERRAL TIER CLAIMS (admin approval) ───────────────────────
@router.callback_query(F.data.startswith("refclaim_ok:"))
async def referral_claim_approve(cb: CallbackQuery, bot: Bot):
    if not is_admin(cb.from_user.id):
        await cb.answer("اجازه ندارید.", show_alert=True)
        return
    from core.rewards import grant_referral_claim
    claim_id = int(cb.data.split(":")[1])
    res = await grant_referral_claim(claim_id, bot=bot, reviewer_id=cb.from_user.id)
    if not res.get("ok"):
        err = str(res.get("error") or "")
        if err == "already_reviewed":
            await cb.answer("این درخواست قبلاً بررسی شده است.", show_alert=True)
        elif err.startswith("service_failed"):
            await cb.answer("ساخت سرویس هدیه ناموفق بود: " + subscription_error_message(err.split(":", 1)[-1]), show_alert=True)
        else:
            await cb.answer("خطا در اعطای هدیه.", show_alert=True)
        return
    try:
        await cb.message.edit_text((cb.message.text or "") + "\n\n✅ اعطا شد.", parse_mode=None)
    except Exception:
        pass
    await cb.answer("هدیه اعطا شد.")


@router.callback_query(F.data.startswith("refclaim_no:"))
async def referral_claim_reject(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("اجازه ندارید.", show_alert=True)
        return
    from core.rewards import reject_referral_claim
    claim_id = int(cb.data.split(":")[1])
    res = await reject_referral_claim(claim_id)
    if not res.get("ok"):
        await cb.answer("این درخواست قبلاً بررسی شده است.", show_alert=True)
        return
    try:
        await cb.message.edit_text((cb.message.text or "") + "\n\n❌ رد شد.", parse_mode=None)
    except Exception:
        pass
    await cb.answer("رد شد.")


@router.message(F.text == "✉️ پیام خصوصی")
async def private_msg_start(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return
    await state.set_state(PrivateMessage.user_id)
    await msg.answer("🆔 آیدی عددی کاربر را ارسال کنید:", reply_markup=flow_cancel_kb())


@router.message(PrivateMessage.user_id)
async def private_msg_user(msg: Message, state: FSMContext):
    try:
        uid = int((msg.text or '').strip())
    except ValueError:
        await msg.answer("❌ آیدی معتبر نیست.")
        return
    await state.update_data(uid=uid)
    await state.set_state(PrivateMessage.text)
    await msg.answer("✍️ متن پیام خصوصی را ارسال کنید:", reply_markup=flow_cancel_kb())


@router.message(PrivateMessage.text)
async def private_msg_get_text(msg: Message, state: FSMContext):
    await state.update_data(text=msg.text or "")
    await state.set_state(PrivateMessage.buttons)
    await msg.answer(
        "🔘 می‌خواهید زیر پیام دکمه شیشه‌ای اضافه شود؟\n\n"
        "اگر بله، دکمه‌ها را به این صورت بفرستید (هر خط یک ردیف):\n"
        "`عنوان دکمه - https://example.com`\n"
        "`کانال - https://t.me/yourchannel | سایت - https://site.com`\n\n"
        "اگر دکمه نمی‌خواهید، روی /skip بزنید.",
        parse_mode="Markdown",
    )


async def _private_msg_deliver(msg: Message, state: FSMContext, raw_buttons: str):
    data = await state.get_data()
    await state.clear()
    uid = data.get("uid")
    markup = parse_custom_buttons(raw_buttons or "")
    try:
        await msg.bot.send_message(uid, data.get("text") or "", reply_markup=markup)
        await msg.answer("✅ پیام خصوصی ارسال شد.")
    except Exception:
        await msg.answer("❌ ارسال ناموفق بود. آیدی یا وضعیت چت کاربر را بررسی کنید.")


@router.message(PrivateMessage.buttons, F.text == "/skip")
async def private_msg_skip_buttons(msg: Message, state: FSMContext):
    await _private_msg_deliver(msg, state, "")


@router.message(PrivateMessage.buttons)
async def private_msg_buttons(msg: Message, state: FSMContext):
    raw = msg.text or ""
    if parse_custom_buttons(raw) is None:
        await msg.answer(
            "⚠️ هیچ دکمه معتبری پیدا نشد. قالب درست:\n"
            "`عنوان - https://example.com`\n\n"
            "دوباره بفرستید یا برای رد شدن /skip بزنید.",
            parse_mode="Markdown",
        )
        return
    await _private_msg_deliver(msg, state, raw)


@router.callback_query(F.data.startswith("tp_appr:"))
async def topup_approve(cb: CallbackQuery):
    if not can_review_payments(cb.from_user.id):
        return
    rid = int(cb.data.split(":")[1])
    req = await get_topup_request(rid)
    if not req:
        await cb.answer("درخواست یافت نشد", show_alert=True)
        return
    if req.get("status") != "pending":
        await cb.answer("قبلا بررسی شده", show_alert=True)
        return

    new_balance = await add_user_balance(
        req["user_id"],
        int(req["amount"]),
        kind="topup",
        note=f"topup_request:{rid}",
        actor_telegram_id=cb.from_user.id,
    )
    await update_topup_request(
        rid,
        status="approved",
        reviewer_telegram_id=cb.from_user.id,
        reviewed_at=datetime.now().isoformat(),
    )
    try:
        await cb.bot.send_message(
            req["telegram_id"],
            f"✅ افزایش اعتبار شما تایید شد.\n💳 موجودی جدید: *{_fmt_toman(new_balance)} تومان*",
            parse_mode="Markdown",
        )
    except Exception:
        pass
    try:
        await cb.message.edit_caption((cb.message.caption or "") + "\n\n✅ تایید شد", reply_markup=None, parse_mode=None)
    except Exception:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await cb.message.answer("✅ افزایش اعتبار تایید شد.")
    await cb.answer("انجام شد")


@router.callback_query(F.data.startswith("tp_rej:"))
async def topup_reject(cb: CallbackQuery):
    if not can_review_payments(cb.from_user.id):
        return
    rid = int(cb.data.split(":")[1])
    req = await get_topup_request(rid)
    if not req:
        await cb.answer("درخواست یافت نشد", show_alert=True)
        return
    if req.get("status") != "pending":
        await cb.answer("قبلا بررسی شده", show_alert=True)
        return

    await update_topup_request(
        rid,
        status="rejected",
        reviewer_telegram_id=cb.from_user.id,
        reviewed_at=datetime.now().isoformat(),
        admin_note="rejected",
    )
    try:
        await cb.bot.send_message(req["telegram_id"], "❌ درخواست افزایش اعتبار شما رد شد. در صورت نیاز با پشتیبانی در ارتباط باشید.")
    except Exception:
        pass
    try:
        await cb.message.edit_caption((cb.message.caption or "") + "\n\n❌ رد شد", reply_markup=None, parse_mode=None)
    except Exception:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await cb.message.answer("❌ درخواست افزایش اعتبار رد شد.")
    await cb.answer("رد شد")
