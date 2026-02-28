import asyncio
import uuid
import time
import json
import sqlite3
from datetime import datetime, timedelta, date
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from core.config import ADMIN_IDS, WEB_SECRET_PATH, WEB_PORT
from core.database import (
    get_stats, get_all_configs, get_config, update_config,
    get_packages, get_package, add_package, update_package, delete_package,
    get_pending_orders, get_order, update_order,
    get_all_users, count_users, get_server, get_servers,
    save_config, get_user_by_telegram, get_setting, set_setting,
    get_user_by_id, server_has_capacity, count_active_configs_by_server, update_user,
    get_legacy_claim, update_legacy_claim, get_config_by_email, get_config_by_uuid,
    get_topup_request, update_topup_request, add_user_balance
)
from core.xui_api import XUIClient, fmt_bytes, days_left
from core.qr import build_qr_image
from bot.keyboards import (
    admin_menu, order_review_kb, order_server_select_kb,
    admin_configs_kb, adm_config_detail_kb, confirm_kb, packages_kb, servers_kb,
    broadcast_target_kb, legacy_claim_admin_kb, flow_cancel_kb
)
from bot.states import AddPackage, CreateConfig, BulkConfig, EditConfig, Broadcast, PrivateMessage

router = Router()


def _fmt_toman(amount: int) -> str:
    return f"{int(amount or 0):,}".replace(",", "،")


def _db_admin_role(uid: int) -> str:
    try:
        conn = sqlite3.connect("atlas.db")
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key='owner_admin_id'")
        own = cur.fetchone()
        owner_id = int((own[0] if own else "0") or 0)
        if uid in ADMIN_IDS or (owner_id and uid == owner_id):
            conn.close()
            return "owner"
        cur.execute("SELECT is_admin, admin_role FROM users WHERE telegram_id=?", (uid,))
        row = cur.fetchone()
        conn.close()
    except Exception:
        return "none"
    if not row or int(row[0] or 0) != 1:
        return "none"
    role = str(row[1] or "full").strip().lower()
    return role if role in {"full", "finance"} else "full"


def is_admin(uid: int) -> bool:
    return _db_admin_role(uid) in ("owner", "full")


def can_review_payments(uid: int) -> bool:
    return _db_admin_role(uid) in ("owner", "full", "finance")


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


# ─── PENDING ORDERS ───────────────────────────────────────────────

@router.message(F.text == "💰 سفارش‌های در انتظار")
async def pending_orders_list(msg: Message):
    if not can_review_payments(msg.from_user.id):
        return
    orders = await get_pending_orders()
    if not orders:
        await msg.answer("✅ هیچ سفارش در انتظاری وجود ندارد.")
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    for o in orders:
        b.button(
            text=f"📤 #{o['id']} — {o['full_name'] or 'کاربر'} — {o['pkg_name']}",
            callback_data=f"view_order:{o['id']}"
        )
    b.adjust(1)
    await msg.answer(
        f"💰 *سفارش‌های در انتظار بررسی* ({len(orders)} مورد)",
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
        await cb.message.answer_photo(
            order["receipt_file_id"],
            caption=text + "\n\n📸 *فیش پرداخت ارسال شده*",
            reply_markup=order_review_kb(oid), parse_mode="Markdown"
        )
    else:
        await cb.message.edit_text(
            text + "\n\n⏳ هنوز فیش ارسال نشده",
            reply_markup=order_review_kb(oid), parse_mode="Markdown"
        )


@router.callback_query(F.data.startswith("approve:"))
async def approve_order_start(cb: CallbackQuery):
    if not can_review_payments(cb.from_user.id):
        return
    oid = int(cb.data.split(":")[1])
    servers = [sv for sv in await get_servers() if await server_has_capacity(sv["id"])]
    if not servers:
        await cb.answer("❌ هیچ سروری فعال نیست!", show_alert=True)
        return

    # اگر سرور پیش‌فرض تنظیم شده باشد، اولویت با همان است.
    default_sid_raw = await get_setting("default_server_id", "0")
    try:
        default_sid = int(default_sid_raw or 0)
    except (TypeError, ValueError):
        default_sid = 0

    if default_sid:
        preferred = next((sv for sv in servers if sv["id"] == default_sid), None)
        if preferred:
            await _do_approve(cb, oid, preferred["id"])
            return

    if len(servers) == 1:
        await _do_approve(cb, oid, servers[0]["id"])
        return

    try:
        await cb.message.edit_text(
            "🖥️ *انتخاب سرور برای کانفیگ:*",
            reply_markup=order_server_select_kb(servers, oid),
            parse_mode="Markdown"
        )
    except Exception:
        # روی پیام فیش (photo) edit_text ممکن است fail شود؛ منو را به‌صورت پیام جدید بفرست.
        await cb.message.answer(
            "🖥️ *انتخاب سرور برای کانفیگ:*",
            reply_markup=order_server_select_kb(servers, oid),
            parse_mode="Markdown"
        )


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

async def _build_config_name(order, idx: int = 0) -> str:
    prefix = await get_setting("cfg_name_prefix", "u")
    postfix = await get_setting("cfg_name_postfix", "")
    rand_len = int(await get_setting("cfg_name_rand_len", "6") or 6)
    random_part = uuid.uuid4().hex[:max(2, min(16, rand_len))]
    idx_part = f"_{idx:02d}" if idx > 0 else ""
    return f"{prefix}{order['telegram_id']}{idx_part}_{random_part}{postfix}".replace(" ", "_")


async def _do_approve(cb: CallbackQuery, oid: int, sid: int):
    order = await get_order(oid)
    if not order:
        return
    if not await server_has_capacity(sid):
        await cb.message.answer("⛔ ظرفیت این سرور تکمیل شده است. سرور دیگری انتخاب کنید.")
        return

    await cb.answer("⏳ در حال ساخت کانفیگ...")
    server = await get_server(sid)
    client = XUIClient(server["url"], server["username"], server["password"], server["sub_path"])

    bulk_count = int(order.get("bulk_count") or 1)
    each_gb = float(order.get("bulk_each_gb") or order["traffic_gb"])
    duration = int(order["duration_days"])

    user = await get_user_by_telegram(order["telegram_id"])
    if not user:
        await cb.message.answer("❌ کاربر در دیتابیس یافت نشد!")
        await client.close()
        return

    created = []
    remaining_cap = (server.get("max_active_configs") or 0)
    if remaining_cap:
        used = await count_active_configs_by_server(sid)
        remaining_cap = max(0, remaining_cap - used)
        bulk_count = min(bulk_count, remaining_cap)

    custom_prefix = ""
    custom_start = 1
    try:
        if order.get("notes"):
            n = json.loads(order["notes"])
            custom_prefix = str(n.get("bulk_name_prefix", "")).strip()
            custom_start = int(n.get("bulk_start_number", 1) or 1)
    except Exception:
        pass

    available_inbounds = _server_inbound_choices(server)
    package_iid = int(order.get("package_inbound_id") or 0)
    target_inbound = package_iid if package_iid in available_inbounds else int(server["inbound_id"])

    for i in range(1, max(1, bulk_count) + 1):
        if bulk_count > 1 and custom_prefix:
            seq = custom_start + i - 1
            email = f"{custom_prefix}-{seq} -{int(each_gb)}GB"
        else:
            email = await _build_config_name(order, i if bulk_count > 1 else 0)
        cuuid = str(uuid.uuid4())
        ok = await client.add_client(target_inbound, cuuid, email, each_gb, duration, starts_on_first_use=True)
        if not ok:
            continue
        expire_ms = 0 if duration > 0 else 0
        link = await client.get_client_link(target_inbound, email)
        sub = await client.get_subscription_link(target_inbound, email)
        await save_config(user["id"], sid, cuuid, email, target_inbound, each_gb, duration, expire_ms, starts_on_first_use=1 if duration > 0 else 0)
        created.append({"email": email, "link": link, "sub": sub})

    await client.close()
    if not created:
        await cb.message.answer("❌ خطا در ساخت کانفیگ روی سرور! اتصال/ظرفیت سرور را بررسی کنید.")
        return

    await update_order(oid, status="approved", server_id=sid,
                       config_email=created[0]["email"], inbound_id=target_inbound,
                       approved_at=datetime.now().isoformat())

    # referral: only first successful paid order
    from core.database import has_previous_purchase
    from core.config import REFERRAL_BONUS_GB
    if not await has_previous_purchase(user["id"]) and order.get("referred_by"):
        referrer = await get_user_by_id(order["referred_by"])
        if referrer:
            new_bonus = referrer.get("referral_bonus_gb", 0) + REFERRAL_BONUS_GB
            await update_user(referrer["id"], referral_bonus_gb=new_bonus)

    head = (
        f"🎉 *سرویس شما فعال شد!*\n"
        f"━━━━━━━━━━━━━━\n"
        f"📦 سفارش: {order['pkg_name']}\n"
        f"🖥️ سرور: {server['name']}\n"
        f"📦 تعداد کانفیگ: `{len(created)}`\n"
        f"📊 حجم هر کانفیگ: `{each_gb} GB`\n"
        f"📅 مدت: `{duration}` روز\n"
    )
    try:
        await cb.bot.send_message(order["telegram_id"], head, parse_mode="Markdown")
        for item in created[:20]:
            txt = f"📧 `{item['email']}`\n"
            if item['link']:
                txt += f"🔗 `{item['link']}`\n"
            if item['sub']:
                txt += f"📡 سابسکریپشن:\n`{item['sub']}`\n"
            await cb.bot.send_message(order["telegram_id"], txt, parse_mode="Markdown")
            if item['link']:
                try:
                    ch = await get_setting("channel_username", "AtlasChannel")
                    qr = build_qr_image(item['link'], footer_text=ch)
                    await cb.bot.send_photo(order["telegram_id"], qr, caption=f"🎨 QR: {item['email']}")
                except Exception:
                    pass
    except Exception:
        pass

    await cb.message.answer(f"✅ {len(created)} کانفیگ ساخته و برای کاربر ارسال شد.", parse_mode="Markdown")
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
    await cb.message.edit_text("📦 نام پکیج را وارد کنید:\n_مثال: پکیج نقره‌ای_", parse_mode="Markdown")


@router.message(AddPackage.name)
async def pkg_name(msg: Message, state: FSMContext):
    await state.update_data(name=msg.text.strip())
    await state.set_state(AddPackage.traffic)
    await msg.answer("📊 حجم ترافیک (GB):\n_مثال: 20_", parse_mode="Markdown")


@router.message(AddPackage.traffic)
async def pkg_traffic(msg: Message, state: FSMContext):
    try:
        v = float(msg.text.strip())
    except ValueError:
        await msg.answer("❌ یک عدد وارد کنید!")
        return
    await state.update_data(traffic_gb=v)
    await state.set_state(AddPackage.duration)
    await msg.answer("📅 مدت زمان (روز):\n_مثال: 30_", parse_mode="Markdown")


@router.message(AddPackage.duration)
async def pkg_duration(msg: Message, state: FSMContext):
    try:
        v = int(msg.text.strip())
    except ValueError:
        await msg.answer("❌ عدد صحیح وارد کنید!")
        return
    await state.update_data(duration_days=v)
    await state.set_state(AddPackage.price)
    await msg.answer("💰 قیمت (تومن):\n_مثال: 100000_", parse_mode="Markdown")


@router.message(AddPackage.price)
async def pkg_price(msg: Message, state: FSMContext):
    try:
        v = int(msg.text.strip().replace(",", "").replace("،", ""))
    except ValueError:
        await msg.answer("❌ عدد وارد کنید!")
        return
    await state.update_data(price=v)
    await state.set_state(AddPackage.description)
    await msg.answer("📝 توضیحات پکیج (اختیاری — برای رد کردن `-` بزن):", parse_mode="Markdown")


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


@router.callback_query(F.data.startswith("adm_cfg:"))
async def adm_cfg_detail(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    cid = int(cb.data.split(":")[1])
    cfg = await get_config(cid)
    if not cfg:
        await cb.answer("یافت نشد!", show_alert=True)
        return
    dl = days_left(cfg["expire_timestamp"] or 0)
    dl_text = f"{dl} روز" if dl >= 0 else "نامحدود"
    status = "🟢 فعال" if cfg["is_active"] else "🔴 غیرفعال"
    await cb.message.edit_text(
        f"🔑 *{cfg['email']}*\n"
        f"🖥️ سرور: `{cfg['server_name']}`\n"
        f"📊 حجم: `{cfg['traffic_gb']} GB`\n"
        f"📅 باقی‌مانده: `{dl_text}`\n"
        f"📡 وضعیت: {status}",
        reply_markup=adm_config_detail_kb(cid, bool(cfg["is_active"])),
        parse_mode="Markdown"
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
    cli = XUIClient(server["url"], server["username"], server["password"], server["sub_path"])
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
    await cb.message.edit_text("📊 حجم جدید را به GB وارد کنید:\n_مثال: 30_", parse_mode="Markdown")


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
    cli = XUIClient(server["url"], server["username"], server["password"], server["sub_path"])
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
    await cb.message.edit_text("📅 تعداد روز از امروز وارد کنید:\n_مثال: 30_", parse_mode="Markdown")


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
    cli = XUIClient(server["url"], server["username"], server["password"], server["sub_path"])
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
        cli = XUIClient(server["url"], server["username"], server["password"], server["sub_path"])
        await cli.delete_client(cfg["inbound_id"], cfg["uuid"])
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
        parse_mode="Markdown"
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
    await msg.answer("🖥️ سرور را انتخاب کنید:", reply_markup=servers_kb(servers, "single_srv"))


@router.callback_query(F.data.startswith("single_srv:"), CreateConfig.server)
async def single_server(cb: CallbackQuery, state: FSMContext):
    sid = int(cb.data.split(":")[1])
    data = await state.get_data()
    await state.clear()
    server = await get_server(sid)
    await cb.message.edit_text("⏳ در حال ساخت کانفیگ...")

    cli = XUIClient(server["url"], server["username"], server["password"], server["sub_path"])
    cuuid = str(uuid.uuid4())
    ok = await cli.add_client(server["inbound_id"], cuuid, data["email"],
                               data["traffic_gb"], data["duration_days"], starts_on_first_use=True)
    if not ok:
        await cli.close()
        await cb.message.edit_text("❌ خطا در ساخت کانفیگ روی سرور!")
        return
    expire_ms = 0 if data["duration_days"] > 0 else 0
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
    await cb.message.edit_text(text, parse_mode="Markdown")
    if link:
        try:
            ch = await get_setting("channel_username", "AtlasChannel")
            qr = build_qr_image(link, footer_text=ch)
            await cb.message.answer_photo(qr, caption=f"🎨 QR: {data['email']}")
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
        parse_mode="Markdown"
    )


@router.message(BulkConfig.prefix)
async def bulk_prefix(msg: Message, state: FSMContext):
    await state.update_data(prefix=msg.text.strip().replace(" ", "_"))
    await state.set_state(BulkConfig.count)
    await msg.answer("🔢 تعداد کانفیگ (حداکثر ۵۰):")


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
    await msg.answer("🖥️ سرور را انتخاب کنید:", reply_markup=servers_kb(servers, "bulk_srv"))


@router.callback_query(F.data.startswith("bulk_srv:"), BulkConfig.server)
async def bulk_server(cb: CallbackQuery, state: FSMContext):
    sid = int(cb.data.split(":")[1])
    data = await state.get_data()
    await state.clear()
    server = await get_server(sid)
    await cb.message.edit_text(f"⏳ در حال ساخت {data['count']} کانفیگ...")

    cli = XUIClient(server["url"], server["username"], server["password"], server["sub_path"])
    expire_ms = 0 if data["duration_days"] > 0 else 0
    results = []

    for i in range(1, data["count"] + 1):
        email = f"{data['prefix']}_{i:03d}"
        cuuid = str(uuid.uuid4())
        ok = await cli.add_client(server["inbound_id"], cuuid, email,
                                   data["traffic_gb"], data["duration_days"], starts_on_first_use=True)
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


@router.callback_query(F.data.startswith("usr:"))
async def user_detail(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    uid = int(cb.data.split(":")[1])
    u = await get_user_by_id(uid)
    if not u:
        await cb.answer("یافت نشد!", show_alert=True)
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="🔓 آنبلاک" if u["is_blocked"] else "🔒 بلاک", callback_data=f"toggle_block:{uid}")
    b.button(text="🔙 بازگشت", callback_data="usr_back")
    b.adjust(2)
    status = "🔴 بلاک" if u["is_blocked"] else "🟢 فعال"
    await cb.message.edit_text(
        f"👤 *{u['full_name'] or '—'}*\n"
        f"🆔 `{u['telegram_id']}`\n"
        f"📡 وضعیت: {status}\n"
        f"📅 عضویت: {u['created_at'][:10]}",
        reply_markup=b.as_markup(), parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("toggle_block:"))
async def toggle_block(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    uid = int(cb.data.split(":")[1])
    u = await get_user_by_id(uid)
    from core.database import update_user
    await update_user(uid, is_blocked=0 if u["is_blocked"] else 1)
    await cb.answer("✅ تغییر کرد")
    await user_detail(cb)


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
            "✅ درخواست همکاری عمده شما تایید شد.\nاز این لحظه منوی خرید عمده برای شما فعال است.",
            reply_markup=user_menu(include_wholesale=True),
        )
    except Exception:
        pass
    await cb.message.edit_text("✅ کاربر برای خرید عمده تایید شد.")


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
        await cb.bot.send_message(u["telegram_id"], "❌ درخواست همکاری عمده شما فعلاً تایید نشد. برای بررسی دوباره با پشتیبانی در ارتباط باشید.")
    except Exception:
        pass
    await cb.message.edit_text("❌ درخواست همکاری عمده رد شد.")


async def _find_remote_legacy_client(email: str, client_uuid: str) -> dict | None:
    """Search all active servers/inbounds and return matching client meta for legacy claim import."""
    servers = await get_servers(active_only=True)
    for srv in servers:
        xui = XUIClient(srv["url"], srv["username"], srv["password"], srv.get("sub_path") or "")
        try:
            inbounds = await xui.get_inbounds()
            for inbound in inbounds:
                try:
                    settings = json.loads(inbound.get("settings") or "{}")
                except Exception:
                    continue

                clients = settings.get("clients") or []
                for c in clients:
                    c_email = (c.get("email") or "").strip()
                    c_uuid = (c.get("id") or c.get("password") or "").strip()
                    if email and c_email != email:
                        continue
                    if client_uuid and c_uuid != client_uuid and (not email):
                        continue

                    total_bytes = int(c.get("totalGB") or 0)
                    traffic_gb = round(total_bytes / (1024 ** 3), 2) if total_bytes > 0 else 0
                    expire_ts = int((c.get("expiryTime") or 0) / 1000) if (c.get("expiryTime") or 0) > 0 else 0
                    if expire_ts > 0:
                        duration_days = max(1, int((expire_ts - int(time.time())) / 86400))
                    else:
                        duration_days = 0

                    return {
                        "server_id": srv["id"],
                        "inbound_id": int(inbound.get("id") or srv.get("inbound_id") or 1),
                        "uuid": c_uuid,
                        "email": c_email or email,
                        "traffic_gb": traffic_gb,
                        "duration_days": duration_days,
                        "expire_ts": expire_ts,
                        "is_active": 1 if c.get("enable", True) else 0,
                    }
        finally:
            await xui.close()

    return None


@router.callback_query(F.data.startswith("lg_appr:"))
async def legacy_claim_approve(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    cid = int(cb.data.split(":")[1])
    claim = await get_legacy_claim(cid)
    if not claim or claim.get("status") != "pending":
        await cb.answer("این درخواست قبلاً بررسی شده.", show_alert=True)
        return

    email = (claim.get("email") or "").strip()
    if not email:
        await update_legacy_claim(cid, status="rejected", reviewer_id=cb.from_user.id, reviewed_at=datetime.now().isoformat(), admin_note="missing_email")
        await cb.message.edit_text("❌ ایمیل کانفیگ در لینک پیدا نشد؛ درخواست رد شد.")
        return

    cfg = await get_config_by_email(email) if email else None
    if not cfg and (claim.get("uuid") or "").strip():
        cfg = await get_config_by_uuid(claim["uuid"].strip())

    # اگر داخل DB نبود، مستقیم از همه سرورها/اینباندها جستجو و ایمپورت می‌کنیم.
    if not cfg:
        remote = await _find_remote_legacy_client(email, (claim.get("uuid") or "").strip())
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
                    remote["expire_ts"],
                )
                cfg = await get_config(cfg_id)
            except Exception:
                cfg = await get_config_by_email(remote["email"])

    if cfg:
        await update_config(cfg["id"], user_id=claim["user_id"], is_active=1)
        await update_legacy_claim(cid, status="approved", reviewer_id=cb.from_user.id, reviewed_at=datetime.now().isoformat())
        try:
            await cb.bot.send_message(claim["telegram_id"], f"✅ کانفیگ `{cfg.get('email') or email}` به حساب شما متصل شد.", parse_mode="Markdown")
        except Exception:
            pass
        await cb.message.edit_text(f"✅ کانفیگ {cfg.get('email') or email} به کاربر تخصیص یافت.")
        return

    await update_legacy_claim(cid, status="rejected", reviewer_id=cb.from_user.id, reviewed_at=datetime.now().isoformat(), admin_note="email_not_found")
    await cb.message.edit_text("❌ کانفیگ با این ایمیل/UUID پیدا نشد. بررسی شد روی دیتابیس و همه سرورها.")


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
    await cb.message.edit_text("✍️ متن پیام را بنویسید:\nبرای لغو /cancel بزنید.")


@router.message(Broadcast.text)
async def broadcast_preview(msg: Message, state: FSMContext):
    await state.update_data(text=msg.text)
    await state.set_state(Broadcast.confirm)
    data = await state.get_data()
    all_users = await get_all_users(0, 100000)
    target = data.get("target", "all")
    if target == "wholesale":
        total = sum(1 for u in all_users if u.get("is_wholesale", 0) and not u.get("is_blocked", 0))
        target_text = "کاربران عمده"
    else:
        total = sum(1 for u in all_users if not u.get("is_blocked", 0))
        target_text = "همه کاربران"
    await msg.answer(
        f"👀 *پیش‌نمایش:*\n\n{msg.text}\n\n🎯 مخاطب: *{target_text}*\n📤 برای *{total}* کاربر ارسال می‌شود.",
        reply_markup=confirm_kb("broadcast_do", "broadcast_cancel"),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "broadcast_do", Broadcast.confirm)
async def broadcast_do(cb: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    users = await get_all_users(0, 100000)
    target = data.get("target", "all")
    sent = failed = 0
    await cb.message.edit_text("⏳ در حال ارسال...")
    for u in users:
        if u["is_blocked"]:
            continue
        if target == "wholesale" and not u.get("is_wholesale", 0):
            continue
        try:
            await bot.send_message(u["telegram_id"], data["text"])
            sent += 1
            await asyncio.sleep(0.04)
        except Exception:
            failed += 1
    await cb.message.answer(f"✅ ارسال کامل شد!\n✅ موفق: {sent} | ❌ ناموفق: {failed}")


@router.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("❌ ارسال لغو شد.")


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
async def private_msg_send(msg: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    uid = data.get('uid')
    try:
        await msg.bot.send_message(uid, msg.text or '')
        await msg.answer("✅ پیام خصوصی ارسال شد.")
    except Exception:
        await msg.answer("❌ ارسال ناموفق بود. آیدی یا وضعیت چت کاربر را بررسی کنید.")


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
    await cb.message.edit_caption((cb.message.caption or "") + "\n\n✅ تایید شد")
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
    await cb.message.edit_caption((cb.message.caption or "") + "\n\n❌ رد شد")
    await cb.answer("رد شد")
