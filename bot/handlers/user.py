import uuid as _uuid
import time
import aiosqlite
from datetime import datetime, timedelta, date
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from core.config import ADMIN_IDS, CARD_NUMBER, CARD_HOLDER, CARD_BANK, MAX_DAILY_MIGRATIONS, REFERRAL_BONUS_GB
from core.database import (
    get_or_create_user, get_packages, get_package,
    create_order, get_order, update_order, get_user_orders,
    get_user_configs, get_config, update_config, save_config,
    get_servers, get_server, get_migration_count_today,
    get_setting, get_referral_stats, update_user, DB_PATH,
    get_user_pricing, create_custom_order, get_available_servers
)
from core.xui_api import XUIClient, fmt_bytes, days_left
from core.texts import get_text
from core.qr import build_qr_image
from bot.keyboards import (
    user_menu, packages_kb, payment_kb, config_detail_kb,
    configs_kb, servers_kb
)
from bot.states import BuyService, WholesaleBuy

router = Router()


async def _blocked(uid: int) -> bool:
    u = await get_or_create_user(uid)
    return bool(u.get("is_blocked", 0))


async def _is_channel_member(msg_or_cb) -> bool:
    force = await get_setting("force_channel", "0")
    channel_username = await get_setting("channel_username", "")
    if force != "1" or not channel_username:
        return True
    bot = msg_or_cb.bot
    uid = msg_or_cb.from_user.id
    ch = channel_username if channel_username.startswith("@") else f"@{channel_username}"
    try:
        m = await bot.get_chat_member(ch, uid)
        return m.status in ("member", "administrator", "creator")
    except Exception:
        return False


async def _ensure_channel_membership(msg_or_cb) -> bool:
    if await _is_channel_member(msg_or_cb):
        return True
    channel_username = await get_setting("channel_username", "")
    ch = channel_username if channel_username.startswith("@") else f"@{channel_username}"
    text = f"🚫 برای استفاده از ربات باید عضو کانال شوید:\n{ch}\n\nبعد از عضویت دوباره تلاش کنید."
    if isinstance(msg_or_cb, Message):
        await msg_or_cb.answer(text)
    else:
        await msg_or_cb.answer("ابتدا در کانال عضو شوید.", show_alert=True)
        await msg_or_cb.message.answer(text)
    return False


# ─── STATUS ──────────────────────────────────────────────────────

@router.message(F.text == "📡 وضعیت سرویس")
async def user_status(msg: Message):
    if not await _ensure_channel_membership(msg):
        return
    if await _blocked(msg.from_user.id):
        await msg.answer(await get_text("blocked_message"))
        return
    user = await get_or_create_user(msg.from_user.id)
    configs = await get_user_configs(user["id"])
    if not configs:
        await msg.answer(await get_text("no_active_service"), parse_mode="Markdown")
        return
    if len(configs) == 1:
        await _send_config_status(msg, configs[0]["id"])
    else:
        await msg.answer(
            f"🔑 *سرویس‌های شما* ({len(configs)} سرویس)\n\nکدام سرویس را می‌خواهید؟",
            reply_markup=configs_kb(configs), parse_mode="Markdown"
        )


@router.callback_query(F.data.startswith("cfg:"))
async def cfg_selected(cb: CallbackQuery):
    cid = int(cb.data.split(":")[1])
    await _send_config_status(cb, cid)


@router.callback_query(F.data == "back_configs")
async def back_configs(cb: CallbackQuery):
    user = await get_or_create_user(cb.from_user.id)
    configs = await get_user_configs(user["id"])
    if not configs:
        await cb.message.edit_text("📭 سرویسی ندارید.")
        return
    await cb.message.edit_text(
        "🔑 *سرویس‌های شما:*",
        reply_markup=configs_kb(configs), parse_mode="Markdown"
    )


async def _send_config_status(target, config_id: int):
    cfg = await get_config(config_id)
    if not cfg:
        return
    # get_config already JOINs server data → use cfg aliases directly
    cli = XUIClient(cfg["server_url"], cfg["srv_user"], cfg["srv_pass"], cfg["sub_path"])
    traffic = await cli.get_client_traffic(cfg["email"])
    await cli.close()

    if traffic:
        total = traffic.get("total", 0)
        down = traffic.get("down", 0)
        up = traffic.get("up", 0)
        used = down + up
        remaining = max(0, total - used)
        expire_ms = traffic.get("expiryTime", cfg["expire_timestamp"] or 0)
        enabled = traffic.get("enable", True)
    else:
        total = int(cfg["traffic_gb"] * 1024 ** 3)
        used = 0
        remaining = total
        expire_ms = cfg["expire_timestamp"] or 0
        enabled = cfg["is_active"]

    dl = days_left(expire_ms)
    dl_text = f"{dl} روز" if dl > 0 else ("نامحدود ♾️" if dl < 0 else "⚠️ منقضی شده!")

    if total > 0:
        pct = min(100, int(used / total * 100))
        bar_filled = int(pct / 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        # رنگ بر اساس مصرف
        pct_icon = "🟢" if pct < 50 else ("🟡" if pct < 80 else "🔴")
        traffic_text = (
            f"📊 مصرف: `{fmt_bytes(used)}` از `{fmt_bytes(total)}`\n"
            f"💾 باقی‌مانده: `{fmt_bytes(remaining)}`\n"
            f"{pct_icon} `[{bar}]` {pct}%"
        )
    else:
        traffic_text = "📊 حجم: نامحدود ♾️"

    status = "🟢 فعال" if enabled else "🔴 غیرفعال"
    text = (
        f"🔑 *{cfg['email']}*\n"
        f"━━━━━━━━━━━━━━\n"
        f"{traffic_text}\n"
        f"📅 روز باقی‌مانده: `{dl_text}`\n"
        f"🖥️ سرور: `{cfg['server_name']}`\n"
        f"📡 وضعیت: {status}"
    )

    kb = config_detail_kb(config_id)
    if isinstance(target, Message):
        await target.answer(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await target.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data.startswith("cfg_link:"))
async def send_config_link(cb: CallbackQuery):
    if not await _ensure_channel_membership(cb):
        return
    cid = int(cb.data.split(":")[1])
    cfg = await get_config(cid)
    if not cfg:
        await cb.answer("سرویس یافت نشد", show_alert=True)
        return
    cli = XUIClient(cfg["server_url"], cfg["srv_user"], cfg["srv_pass"], cfg["sub_path"])
    link = await cli.get_client_link(cfg["inbound_id"], cfg["email"])
    sub = await cli.get_subscription_link(cfg["inbound_id"], cfg["email"])
    await cli.close()

    if link:
        body = f"🔗 *لینک اتصال شما:*\n\n`{link}`\n"
        if sub:
            body += f"\n📡 *لینک سابسکریپشن:*\n`{sub}`\n"
        body += "\n📱 این لینک را کپی کن و در اپلیکیشن وارد کن.\n\n_اپ‌های پیشنهادی: V2rayNG (اندروید) | Streisand (iOS) | Hiddify (ویندوز)_"
        await cb.message.answer(body, parse_mode="Markdown")
        try:
            qr = build_qr_image(link)
            await cb.message.answer_photo(qr, caption="🧩 QR Code کانفیگ شما")
        except Exception:
            pass
        await cb.answer()
    else:
        await cb.answer("❌ خطا در دریافت لینک. سرور را بررسی کنید.", show_alert=True)


@router.callback_query(F.data.startswith("cfg_refresh:"))
async def cfg_refresh(cb: CallbackQuery):
    if not await _ensure_channel_membership(cb):
        return
    cid = int(cb.data.split(":")[1])
    await _send_config_status(cb, cid)
    await cb.answer("بروزرسانی شد")


@router.callback_query(F.data.startswith("cfg_sub:"))
async def cfg_sub(cb: CallbackQuery):
    if not await _ensure_channel_membership(cb):
        return
    cid = int(cb.data.split(":")[1])
    cfg = await get_config(cid)
    if not cfg:
        await cb.answer("یافت نشد", show_alert=True)
        return
    cli = XUIClient(cfg["server_url"], cfg["srv_user"], cfg["srv_pass"], cfg["sub_path"])
    sub = await cli.get_subscription_link(cfg["inbound_id"], cfg["email"])
    await cli.close()
    if sub:
        await cb.message.answer(f"📡 *لینک سابسکریپشن:*\n`{sub}`", parse_mode="Markdown")
        await cb.answer()
    else:
        await cb.answer("لینک ساب پیدا نشد", show_alert=True)

# ─── BUY ─────────────────────────────────────────────────────────

@router.message(F.text == "🛒 خرید سرویس")
async def buy_service(msg: Message):
    if not await _ensure_channel_membership(msg):
        return
    if await _blocked(msg.from_user.id):
        await msg.answer(await get_text("blocked_message"))
        return
    pkgs = await get_packages(active_only=True)
    if not pkgs:
        await msg.answer("😔 در حال حاضر پکیجی برای فروش وجود ندارد.\nلطفاً بعداً تلاش کنید.")
        return
    if not await get_available_servers():
        await msg.answer("⛔ فعلاً هیچ سروری ظرفیت خالی برای فروش ندارد.")
        return
    text = "🛒 *پکیج مورد نظر را انتخاب کنید:*\n\n"
    for p in pkgs:
        price = f"{p['price']:,}".replace(",", "،")
        text += f"• *{p['name']}* — {p['traffic_gb']}GB / {p['duration_days']} روز / {price} تومن\n"
        if p["description"]:
            text += f"  _{p['description']}_\n"
        text += "\n"
    await msg.answer(text.strip(), reply_markup=packages_kb(pkgs), parse_mode="Markdown")


@router.callback_query(F.data.startswith("buy:"))
async def buy_pkg_selected(cb: CallbackQuery):
    pid = int(cb.data.split(":")[1])
    pkg = await get_package(pid)
    if not pkg or not pkg["is_active"]:
        await cb.answer("❌ این پکیج در دسترس نیست.", show_alert=True)
        return
    user = await get_or_create_user(cb.from_user.id)
    oid = await create_order(user["id"], pid)

    price = f"{pkg['price']:,}".replace(",", "،")
    text = (
        f"🧾 *سفارش شما — #{oid}*\n"
        f"━━━━━━━━━━━━━━\n"
        f"📦 {pkg['name']}\n"
        f"📊 {pkg['traffic_gb']} GB | 📅 {pkg['duration_days']} روز\n"
        f"💰 مبلغ: *{price} تومن*\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"💳 *پرداخت کارت به کارت:*\n\n"
        f"🏦 {CARD_BANK}\n"
        f"💳 `{CARD_NUMBER}`\n"
        f"👤 به نام: {CARD_HOLDER}\n\n"
        f"📌 *مراحل:*\n"
        f"۱. مبلغ را به کارت بالا واریز کن\n"
        f"۲. روی «ارسال فیش» بزن و عکس فیش را بفرست\n"
        f"۳. پس از تأیید، لینک کانفیگ ارسال می‌شه ⚡\n\n"
        f"⏰ مهلت پرداخت: ۳۰ دقیقه"
    )
    await cb.message.edit_text(text, reply_markup=payment_kb(oid), parse_mode="Markdown")


@router.callback_query(F.data.startswith("receipt:"))
async def prompt_receipt(cb: CallbackQuery, state: FSMContext):
    oid = int(cb.data.split(":")[1])
    await state.set_state(BuyService.waiting_receipt)
    await state.update_data(order_id=oid)
    await update_order(oid, status="pending_receipt")
    await cb.message.edit_text(
        "📸 *ارسال فیش پرداخت*\n\n"
        "تصویر فیش واریزی را ارسال کنید 👇",
        parse_mode="Markdown"
    )


@router.message(BuyService.waiting_receipt, F.photo)
async def receive_receipt(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    oid = data["order_id"]
    await state.clear()

    photo_id = msg.photo[-1].file_id
    await update_order(oid, status="receipt_submitted", receipt_file_id=photo_id)
    order = await get_order(oid)

    await msg.answer(
        "✅ *فیش دریافت شد!*\n\n"
        "⏱ معمولاً ظرف ۳۰ دقیقه سرویس شما فعال می‌شه.\n"
        "پس از تأیید، لینک کانفیگ برایتان ارسال می‌شود. 🚀",
        parse_mode="Markdown"
    )

    # اطلاع به ادمین‌ها
    caption = (
        f"🔔 *فیش جدید!*\n"
        f"━━━━━━━━━━━━━━\n"
        f"📋 سفارش: #{oid}\n"
        f"👤 {msg.from_user.full_name} (@{msg.from_user.username or '—'})\n"
        f"📦 {order['pkg_name']}\n"
        f"💰 {order['price']:,} تومن"
    )
    from bot.keyboards import order_review_kb
    for aid in ADMIN_IDS:
        try:
            await bot.send_photo(aid, photo_id, caption=caption,
                                 reply_markup=order_review_kb(oid), parse_mode="Markdown")
        except Exception:
            pass


@router.message(BuyService.waiting_receipt)
async def wrong_receipt_format(msg: Message):
    await msg.answer("📸 لطفاً *تصویر* (عکس) فیش را ارسال کنید.", parse_mode="Markdown")


@router.callback_query(F.data.startswith("cancel_order:"))
async def cancel_order(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    oid = int(cb.data.split(":")[1])
    await update_order(oid, status="cancelled")
    await cb.message.edit_text("❌ سفارش لغو شد.")




@router.message(F.text == "🏷️ خرید عمده")
async def wholesale_start(msg: Message, state: FSMContext):
    if not await _ensure_channel_membership(msg):
        return
    if await _blocked(msg.from_user.id):
        await msg.answer(await get_text("blocked_message"))
        return
    await state.set_state(WholesaleBuy.count)
    await msg.answer("🏷️ خرید عمده\n\nتعداد کانفیگ موردنیاز را وارد کنید (مثال: 20)")


@router.message(WholesaleBuy.count)
async def wholesale_count(msg: Message, state: FSMContext):
    try:
        count = max(1, min(100, int(msg.text.strip())))
    except ValueError:
        await msg.answer("❌ عدد معتبر وارد کنید")
        return
    await state.update_data(count=count)
    await state.set_state(WholesaleBuy.traffic)
    await msg.answer("📊 حجم هر کانفیگ (GB) را وارد کنید")


@router.message(WholesaleBuy.traffic)
async def wholesale_traffic(msg: Message, state: FSMContext):
    try:
        gb = float(msg.text.strip())
    except ValueError:
        await msg.answer("❌ عدد معتبر وارد کنید")
        return
    await state.update_data(traffic=gb)
    await state.set_state(WholesaleBuy.duration)
    await msg.answer("📅 مدت هر کانفیگ (روز) را وارد کنید")


@router.message(WholesaleBuy.duration)
async def wholesale_duration(msg: Message, state: FSMContext):
    try:
        days = int(msg.text.strip())
    except ValueError:
        await msg.answer("❌ عدد معتبر وارد کنید")
        return
    data = await state.get_data()
    await state.clear()

    user = await get_or_create_user(msg.from_user.id)
    pricing = await get_user_pricing(user["id"])
    total_gb = data["count"] * data["traffic"]
    base_price = int(total_gb * (pricing["price_per_gb"] or 0))
    if base_price <= 0:
        base_price = int(total_gb * 10000)
    discount = pricing["discount_percent"] or 0
    final_price = int(base_price * (100 - discount) / 100)

    if not await get_available_servers():
        await msg.answer("⛔ فعلاً سرور خالی برای فعالسازی سفارش عمده وجود ندارد.")
        return

    oid = await create_custom_order(
        user["id"],
        name=f"عمده {data['count']}x{data['traffic']}GB",
        total_traffic_gb=total_gb,
        duration_days=days,
        price=final_price,
        bulk_count=data["count"],
        bulk_each_gb=data["traffic"],
    )

    text = (
        f"🧾 *سفارش عمده #{oid}*\n"
        f"تعداد: `{data['count']}` کانفیگ\n"
        f"حجم هر کانفیگ: `{data['traffic']} GB`\n"
        f"مدت: `{days}` روز\n"
        f"قیمت هر GB: `{pricing['price_per_gb'] or 10000:,}` تومان\n"
        f"تخفیف شما: `{discount}%`\n"
        f"💰 مبلغ نهایی: *{final_price:,} تومان*\n\n"
        f"🏦 {CARD_BANK}\n💳 `{CARD_NUMBER}`\n👤 {CARD_HOLDER}\n\n"
        f"برای ثبت پرداخت روی «ارسال فیش» بزنید."
    )
    await msg.answer(text, reply_markup=payment_kb(oid), parse_mode="Markdown")


# ─── MY ORDERS ───────────────────────────────────────────────────

@router.message(F.text == "📋 سفارش‌های من")
async def my_orders(msg: Message):
    if not await _ensure_channel_membership(msg):
        return
    user = await get_or_create_user(msg.from_user.id)
    orders = await get_user_orders(user["id"])
    if not orders:
        await msg.answer("📭 هنوز سفارشی ثبت نکرده‌اید.")
        return

    STATUS = {
        "pending_payment": "⏳ انتظار پرداخت",
        "pending_receipt":  "⏳ انتظار فیش",
        "receipt_submitted": "📤 در انتظار تأیید",
        "approved":          "✅ فعال شده",
        "rejected":          "❌ رد شده",
        "cancelled":         "🚫 لغو شده",
    }
    text = "📋 *سفارش‌های اخیر شما:*\n\n"
    for o in orders:
        st = STATUS.get(o["status"], o["status"])
        text += f"📦 {o['pkg_name']} — {st}\n"
        text += f"💰 {o['price']:,} تومن | {o['created_at'][:10]}\n\n"
    await msg.answer(text.strip(), parse_mode="Markdown")


# ─── MIGRATE ─────────────────────────────────────────────────────

@router.message(F.text == "🔄 انتقال سرور")
async def migrate_menu(msg: Message):
    if not await _ensure_channel_membership(msg):
        return
    user = await get_or_create_user(msg.from_user.id)
    configs = await get_user_configs(user["id"])
    if not configs:
        await msg.answer("📭 سرویس فعالی برای انتقال ندارید.")
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    for c in configs:
        b.button(text=f"🔑 {c['email']} — {c['server_name']}", callback_data=f"mig_start:{c['id']}")
    b.adjust(1)
    await msg.answer(
        f"🔄 *انتقال سرور*\n\n"
        f"کدام سرویس را می‌خواهید منتقل کنید؟\n"
        f"⚠️ محدودیت: {MAX_DAILY_MIGRATIONS} بار در روز",
        reply_markup=b.as_markup(), parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("mig_start:"))
async def mig_start(cb: CallbackQuery):
    cid = int(cb.data.split(":")[1])
    cfg = await get_config(cid)
    user = await get_or_create_user(cb.from_user.id)

    if cfg["user_id"] != user["id"]:
        await cb.answer("❌ این سرویس متعلق به شما نیست!", show_alert=True)
        return

    today_cnt = await get_migration_count_today(cid)
    if today_cnt >= MAX_DAILY_MIGRATIONS:
        await cb.answer(f"⛔ امروز {MAX_DAILY_MIGRATIONS} بار انتقال انجام دادید!\nفردا دوباره امتحان کنید.", show_alert=True)
        return

    all_servers = await get_servers()
    others = [s for s in all_servers if s["id"] != cfg["server_id"]]
    if not others:
        await cb.answer("❌ سرور دیگری برای انتقال موجود نیست!", show_alert=True)
        return

    remaining = MAX_DAILY_MIGRATIONS - today_cnt
    await cb.message.edit_text(
        f"🔄 *انتقال سرویس*\n\n"
        f"📌 سرویس: `{cfg['email']}`\n"
        f"🖥️ سرور فعلی: `{cfg['server_name']}`\n"
        f"🔢 انتقال باقی‌مانده امروز: `{remaining}`\n\n"
        "سرور مقصد را انتخاب کنید:",
        reply_markup=servers_kb(others, "mig_confirm", str(cid)),
        parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("mig_confirm:"))
async def mig_confirm(cb: CallbackQuery):
    parts = cb.data.split(":")
    dst_sid = int(parts[1])
    src_cid = int(parts[2])

    cfg = await get_config(src_cid)
    user = await get_or_create_user(cb.from_user.id)

    if cfg["user_id"] != user["id"]:
        await cb.answer("❌ دسترسی مجاز نیست!", show_alert=True)
        return

    today_cnt = await get_migration_count_today(src_cid)
    if today_cnt >= MAX_DAILY_MIGRATIONS:
        await cb.answer("⛔ محدودیت روزانه پر شده!", show_alert=True)
        return

    await cb.message.edit_text("⏳ در حال انتقال سرویس...")

    # دریافت آمار واقعی
    src_srv = await get_server(cfg["server_id"])
    src_cli = XUIClient(src_srv["url"], src_srv["username"], src_srv["password"], src_srv["sub_path"])
    traffic = await src_cli.get_client_traffic(cfg["email"])

    if traffic:
        total_b = traffic.get("total", int(cfg["traffic_gb"] * 1024 ** 3))
        used_b = traffic.get("down", 0) + traffic.get("up", 0)
        rem_b = max(0, total_b - used_b)
        expire_ms = traffic.get("expiryTime", cfg["expire_timestamp"] or 0)
    else:
        rem_b = int(cfg["traffic_gb"] * 1024 ** 3)
        expire_ms = cfg["expire_timestamp"] or 0

    rem_gb = rem_b / (1024 ** 3)
    dl = days_left(expire_ms)
    new_days = dl if dl > 0 else 36500

    # ساخت کانفیگ جدید
    dst_srv = await get_server(dst_sid)
    dst_cli = XUIClient(dst_srv["url"], dst_srv["username"], dst_srv["password"], dst_srv["sub_path"])

    new_uuid = str(_uuid.uuid4())
    new_email = f"{cfg['email'].split('_m')[0]}_m{int(time.time())}"

    ok = await dst_cli.add_client(dst_srv["inbound_id"], new_uuid, new_email, rem_gb, new_days)
    if not ok:
        await src_cli.close()
        await dst_cli.close()
        await cb.message.edit_text("❌ خطا در ساخت کانفیگ روی سرور مقصد!")
        return

    # غیرفعال کردن کانفیگ قدیمی
    await src_cli.update_client(
        cfg["inbound_id"], cfg["uuid"], cfg["email"],
        cfg["traffic_gb"], cfg["expire_timestamp"] or 0, False
    )

    new_link = await dst_cli.get_client_link(dst_srv["inbound_id"], new_email)
    await src_cli.close()
    await dst_cli.close()

    # ذخیره کانفیگ جدید و غیرفعال کردن قدیمی
    await update_config(src_cid, is_active=0)
    new_exp_ms = int((datetime.now() + timedelta(days=new_days)).timestamp() * 1000)
    await save_config(user["id"], dst_sid, new_uuid, new_email,
                      dst_srv["inbound_id"], rem_gb, new_days, new_exp_ms)

    # آپدیت شمارنده انتقال
    today = date.today().isoformat()
    new_cnt = today_cnt + 1
    await update_config(src_cid, migration_count=new_cnt, last_migration_date=today)

    text = (
        f"✅ *انتقال موفق!*\n"
        f"━━━━━━━━━━━━━━\n"
        f"🖥️ سرور جدید: `{dst_srv['name']}`\n"
        f"📊 حجم منتقل‌شده: `{rem_gb:.2f} GB`\n"
        f"📅 روزهای باقی: `{dl if dl > 0 else 'نامحدود'}`\n\n"
        f"⚠️ لینک قدیمی غیرفعال شد."
    )
    if new_link:
        text += f"\n\n🔗 *لینک جدید:*\n`{new_link}`"

    await cb.message.edit_text(text, parse_mode="Markdown")


# ─── REFERRAL ────────────────────────────────────────────────────

@router.message(F.text == "🎁 دعوت دوستان")
async def referral_menu(msg: Message):
    if not await _ensure_channel_membership(msg):
        return
    user = await get_or_create_user(msg.from_user.id)
    stats = await get_referral_stats(user["id"])
    code = user.get("referral_code", "—")
    bot_info = await msg.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={code}"

    intro = await get_text("referral_intro", bonus_gb=int(REFERRAL_BONUS_GB))
    text = (
        f"{intro}\n\n"
        f"🔗 *لینک اختصاصی شما:*\n`{ref_link}`\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"📊 *آمار شما:*\n"
        f"👥 دعوت‌شدگان: `{stats['invited']}` نفر\n"
        f"✅ خریداران: `{stats['converted']}` نفر\n"
        f"🎁 هدیه کسب‌شده: `{stats['bonus_gb']} GB`\n\n"
        f"💡 برای استفاده از هدیه با پشتیبانی در تماس باشید."
    )
    await msg.answer(text, parse_mode="Markdown")


# ─── SUPPORT ─────────────────────────────────────────────────────

@router.message(F.text == "📞 پشتیبانی")
async def support(msg: Message):
    if not await _ensure_channel_membership(msg):
        return
    sup = await get_setting("support_username", "")
    brand = await get_setting("ui.brand_name", "Atlas Account")
    text = (await get_text("support_header", brand=brand)) + "\n\n"
    if sup:
        text += f"💬 تماس مستقیم: @{sup}\n"
    text += await get_text("support_body")
    await msg.answer(text, parse_mode="Markdown")
