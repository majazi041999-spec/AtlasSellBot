import uuid as _uuid
import time
import json
import base64
import binascii
import aiosqlite
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime, timedelta, date

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext

from core.config import ADMIN_IDS, CARD_NUMBER, CARD_HOLDER, CARD_BANK, MAX_DAILY_MIGRATIONS, REFERRAL_BONUS_GB
from core.database import (
    get_or_create_user,
    get_packages,
    get_package,
    create_order,
    get_order,
    update_order,
    get_user_orders,
    get_user_configs,
    get_config,
    update_config,
    save_config,
    get_servers,
    get_server,
    get_migration_count_today,
    get_user_migration_count_today,
    get_setting,
    get_referral_stats,
    update_user,
    DB_PATH,
    get_user_pricing,
    create_custom_order,
    get_available_servers,
    get_legacy_claim_by_key,
    get_legacy_claim_by_identity,
    update_legacy_claim,
    create_legacy_claim,
    get_user_balance,
    create_topup_request,
    add_user_balance,
    get_all_admin_telegram_ids,
    add_review_message,
)
from core.xui_api import XUIClient, fmt_bytes, days_left, expiry_ms_from_days
from core.texts import get_text
from core.qr import build_qr_image

from bot.keyboards import (
    user_menu,
    packages_kb,
    payment_kb,
    config_detail_kb,
    config_links_kb,
    configs_kb,
    servers_kb,
    wholesale_request_kb,
    wholesale_request_admin_kb,
    legacy_claim_admin_kb,
    wallet_kb,
    flow_cancel_kb,
)
from bot.states import BuyService, WholesaleBuy, LegacySync, WalletTopup

router = Router()


async def _blocked(uid: int) -> bool:
    u = await get_or_create_user(uid)
    return bool(u.get("is_blocked", 0))


def _channel_join_kb(channel_username: str):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    ch = channel_username.strip().lstrip("@")
    b = InlineKeyboardBuilder()
    b.button(text="📢 عضویت در کانال", url=f"https://t.me/{ch}")
    return b.as_markup()


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
    text = f"❌ قبل از استفاده از امکانات ربات باید عضو کانال شوید.\n\nکانال: {ch}\n\nبعد از عضویت دوباره تلاش کنید."
    if isinstance(msg_or_cb, Message):
        await msg_or_cb.answer(text, reply_markup=_channel_join_kb(channel_username))
    else:
        await msg_or_cb.answer("❌ ابتدا باید در کانال عضو شوید.", show_alert=True)
        await msg_or_cb.message.answer(text, reply_markup=_channel_join_kb(channel_username))
    return False


def _fmt_toman(amount: int) -> str:
    return f"{int(amount or 0):,}".replace(",", "،")


def _qr_input_file(link: str, footer_text: str) -> BufferedInputFile:
    qr = build_qr_image(link, footer_text=footer_text)
    return BufferedInputFile(qr.getvalue(), filename="atlas-qr.png")


async def _get_card_info():
    """✅ کارت بانکی را از Settings DB بخوان (fallback: .env)"""
    card_bank = await get_setting("card_bank", CARD_BANK)
    card_number = await get_setting("card_number", CARD_NUMBER)
    card_holder = await get_setting("card_holder", CARD_HOLDER)
    return card_bank, card_number, card_holder


def _safe_user_config_name(value: str) -> str:
    cleaned = "".join(ch for ch in (value or "").strip() if ch.isalnum() or ch in ("_", "-", "."))
    return cleaned[:24]


async def _calc_renew_price(user_id: int, traffic_gb: float, duration_days: int) -> int:
    for pkg in await get_packages(active_only=True):
        if abs(float(pkg.get("traffic_gb") or 0) - float(traffic_gb or 0)) < 0.001 and int(pkg.get("duration_days") or 0) == int(duration_days or 0):
            return int(pkg.get("price") or 0)
    pricing = await get_user_pricing(user_id)
    base = int(float(traffic_gb or 0) * int(pricing.get("price_per_gb") or 0))
    if base <= 0:
        base = int(float(traffic_gb or 0) * 10000)
    discount = float(pricing.get("discount_percent") or 0)
    return int(base * (100 - discount) / 100)


async def _calc_package_price_for_user(user_id: int, pkg: dict) -> tuple[int, int, float, int]:
    pricing = await get_user_pricing(user_id)
    base_price = int(pkg.get("price") or 0)
    price_per_gb = int(pricing.get("price_per_gb") or 0)
    if price_per_gb > 0:
        base_price = int(float(pkg.get("traffic_gb") or 0) * price_per_gb)
    discount = max(0.0, min(100.0, float(pricing.get("discount_percent") or 0)))
    final_price = int(base_price * (100 - discount) / 100)
    return max(0, final_price), max(0, base_price), discount, price_per_gb


async def _payment_text(oid: int, title: str, traffic_gb: float, duration_days: int, price: int) -> str:
    card_bank, card_number, card_holder = await _get_card_info()
    return (
        f" *سفارش شما — #{oid}*\n"
        f"━━━━━━━━━━━━━━\n"
        f" {title}\n"
        f" {traffic_gb} GB | {duration_days} روز\n"
        f" مبلغ: *{_fmt_toman(price)} تومان*\n\n"
        f"━━━━━━━━━━━━━━\n"
        f" *پرداخت کارت به کارت:*\n\n"
        f" {card_bank}\n"
        f" `{card_number}`\n"
        f" به نام: {card_holder}\n\n"
        f" *مراحل:*\n"
        f"1. مبلغ را به کارت بالا واریز کن\n"
        f"2. روی «ارسال فیش» بزن و عکس فیش را بفرست\n"
        f"3. پس از تأیید، سرویس فعال/تمدید می‌شود\n\n"
        f"⏰ مهلت پرداخت: ۳۰ دقیقه"
    )



@router.message(F.text == "💳 کیف پول")
async def wallet_home(msg: Message):
    if not await _ensure_channel_membership(msg):
        return
    if await _blocked(msg.from_user.id):
        await msg.answer(await get_text("blocked_message"))
        return
    user = await get_or_create_user(msg.from_user.id)
    bal = await get_user_balance(user["id"])
    await msg.answer(
        f"💳 *کیف پول شما*\n\nموجودی فعلی: *{_fmt_toman(bal)} تومان*",
        reply_markup=wallet_kb(),
        parse_mode="Markdown",
    )


@router.callback_query(F.data == "wallet_topup")
async def wallet_topup_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(WalletTopup.waiting_amount)
    await cb.message.answer("💵 مبلغ افزایش اعتبار را به تومان وارد کنید.\nمثال: `250000`", parse_mode="Markdown", reply_markup=flow_cancel_kb())
    await cb.answer()


@router.message(WalletTopup.waiting_amount)
async def wallet_topup_amount(msg: Message, state: FSMContext):
    raw = (msg.text or "").replace("،", "").replace(",", "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        await msg.answer("❌ مبلغ نامعتبر است. فقط عدد تومان بفرستید.")
        return
    amount = int(raw)
    await state.update_data(topup_amount=amount)
    await state.set_state(WalletTopup.waiting_receipt)
    card_bank, card_number, card_holder = await _get_card_info()
    await msg.answer(
        f"✅ مبلغ: *{_fmt_toman(amount)} تومان*\n\n"
        f"لطفاً واریز را انجام دهید و تصویر فیش را ارسال کنید.\n\n"
        f"🏦 {card_bank}\n`{card_number}`\n👤 {card_holder}",
        parse_mode="Markdown",
        reply_markup=flow_cancel_kb(),
    )


@router.message(WalletTopup.waiting_receipt, F.photo)
async def wallet_topup_receipt(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    amount = int(data.get("topup_amount", 0) or 0)
    if amount <= 0:
        await msg.answer("❌ خطا در مبلغ. دوباره از کیف پول تلاش کنید.")
        return
    user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
    photo_id = msg.photo[-1].file_id
    req_id = await create_topup_request(user["id"], amount, photo_id)

    await msg.answer(
        f"✅ درخواست افزایش اعتبار ثبت شد.\nمبلغ: *{_fmt_toman(amount)} تومان*\nپس از تایید ادمین، موجودی شما افزایش می‌یابد.",
        parse_mode="Markdown",
    )

    from bot.keyboards import topup_review_kb
    cap = (
        f"💳 *درخواست افزایش اعتبار*\n"
        f"#Topup_{req_id}\n"
        f"👤 {user.get('full_name') or 'کاربر'} (@{user.get('username') or '—'})\n"
        f"🆔 `{msg.from_user.id}`\n"
        f"💵 مبلغ: *{_fmt_toman(amount)} تومان*"
    )
    admin_targets = list(dict.fromkeys(list(ADMIN_IDS) + await get_all_admin_telegram_ids()))
    for aid in admin_targets:
        try:
            sent = await bot.send_photo(aid, photo_id, caption=cap, reply_markup=topup_review_kb(req_id), parse_mode=None)
            await add_review_message("topup", req_id, sent.chat.id, sent.message_id)
        except Exception:
            try:
                sent = await bot.send_message(aid, cap, reply_markup=topup_review_kb(req_id), parse_mode=None)
                await add_review_message("topup", req_id, sent.chat.id, sent.message_id)
            except Exception:
                pass


@router.message(WalletTopup.waiting_receipt)
async def wallet_topup_receipt_wrong(msg: Message):
    await msg.answer("❌ لطفاً تصویر فیش را ارسال کنید.", reply_markup=flow_cancel_kb())

# ─── STATUS ──────────────────────────────────────────────────────


@router.callback_query(F.data == "flow_back")
async def flow_back_user(cb: CallbackQuery, state: FSMContext):
    cur = await state.get_state()
    if not cur:
        await cb.answer("مرحله‌ای برای برگشت وجود ندارد.", show_alert=True)
        return

    if cur.endswith("WalletTopup:waiting_receipt"):
        await state.set_state(WalletTopup.waiting_amount)
        await cb.message.edit_text("💵 مبلغ افزایش اعتبار را به تومان وارد کنید.\nمثال: `250000`", parse_mode="Markdown", reply_markup=flow_cancel_kb())
    elif cur.endswith("WholesaleBuy:traffic"):
        await state.set_state(WholesaleBuy.count)
        await cb.message.edit_text("🔢 تعداد کانفیگ موردنیاز را وارد کنید (مثلاً 5):", reply_markup=flow_cancel_kb())
    elif cur.endswith("WholesaleBuy:duration"):
        await state.set_state(WholesaleBuy.traffic)
        await cb.message.edit_text("📊 حجم *هر کانفیگ* را به GB وارد کنید (مثلاً 20):", parse_mode="Markdown", reply_markup=flow_cancel_kb())
    elif cur.endswith("WholesaleBuy:naming_prefix"):
        await state.set_state(WholesaleBuy.duration)
        await cb.message.edit_text("📅 مدت *هر کانفیگ* را به روز وارد کنید (مثلاً 30):", parse_mode="Markdown", reply_markup=flow_cancel_kb())
    elif cur.endswith("WholesaleBuy:naming_start"):
        await state.set_state(WholesaleBuy.naming_prefix)
        await cb.message.edit_text("✍️ یک پیشوند نام وارد کنید (مثلاً `vip`):", parse_mode="Markdown", reply_markup=flow_cancel_kb())
    elif cur.endswith("BuyService:waiting_receipt"):
        data = await state.get_data()
        oid = int(data.get("order_id") or 0)
        await state.clear()
        if oid:
            await update_order(oid, status="pending_payment")
            await cb.message.edit_text("⬅️ برگشتید به مرحله پرداخت.", reply_markup=payment_kb(oid), parse_mode="Markdown")
        else:
            await cb.message.edit_text("⬅️ برگشتید.")
    elif cur.endswith("BuyService:custom_name"):
        await state.clear()
        pkgs = await get_packages(active_only=True)
        await cb.message.edit_text(
            "🛒 *پکیج مورد نظر را انتخاب کنید:*",
            reply_markup=packages_kb(pkgs),
            parse_mode="Markdown",
        )
    elif cur.endswith("LegacySync:waiting_link"):
        await state.clear()
        user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
        await cb.message.edit_text("⬅️ برگشتید به منو.")
        await cb.message.answer("منوی اصلی", reply_markup=user_menu(include_wholesale=bool(user.get("is_wholesale", 0))))
    else:
        await cb.answer("برای این مرحله برگشت مستقیم تعریف نشده است.", show_alert=True)
        return
    await cb.answer()


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
            f" *سرویس‌های شما* ({len(configs)} سرویس)\n\nکدام سرویس را می‌خواهید؟",
            reply_markup=configs_kb(configs),
            parse_mode="Markdown",
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
        await cb.message.edit_text(" سرویسی ندارید.")
        return
    await cb.message.edit_text(" *سرویس‌های شما:*", reply_markup=configs_kb(configs), parse_mode="Markdown")


async def _send_config_status(target, config_id: int):
    cfg = await get_config(config_id)
    if not cfg:
        return

    # get_config already JOINs server data → use cfg aliases directly
    cli = XUIClient(cfg["server_url"], cfg["srv_user"], cfg["srv_pass"], cfg["sub_path"], cfg.get("srv_api_token", ""))
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

        # اگر شروع زمان از اولین اتصال باشد، بعد از اولین مصرف زمان را فعال کن
        if cfg.get("starts_on_first_use", 0) and used > 0 and (cfg.get("duration_days", 0) or 0) > 0:
            new_expire_ms = int((datetime.now() + timedelta(days=int(cfg.get("duration_days", 0) or 0))).timestamp() * 1000)
            cli2 = XUIClient(cfg["server_url"], cfg["srv_user"], cfg["srv_pass"], cfg["sub_path"], cfg.get("srv_api_token", ""))
            ok = await cli2.update_client(
                cfg["inbound_id"],
                cfg["uuid"],
                cfg["email"],
                cfg["traffic_gb"],
                new_expire_ms,
                bool(enabled),
            )
            await cli2.close()
            if ok:
                await update_config(
                    config_id,
                    expire_timestamp=new_expire_ms,
                    starts_on_first_use=0,
                    first_use_at=datetime.now().isoformat(),
                )
                expire_ms = new_expire_ms
    else:
        total = int(cfg["traffic_gb"] * 1024**3)
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
        pct_icon = "" if pct < 50 else ("" if pct < 80 else "")
        traffic_text = (
            f" مصرف: `{fmt_bytes(used)}` از `{fmt_bytes(total)}`\n"
            f" باقی‌مانده: `{fmt_bytes(remaining)}`\n"
            f"{pct_icon} `[{bar}]` {pct}%"
        )
    else:
        traffic_text = " حجم: نامحدود ♾️"

    status = " فعال" if enabled else " غیرفعال"
    text = (
        f" *{cfg['email']}*\n"
        f"━━━━━━━━━━━━━━\n"
        f"{traffic_text}\n"
        f" روز باقی‌مانده: `{dl_text}`\n"
        f"️ سرور: `{cfg['server_name']}`\n"
        f" وضعیت: {status}"
    )
    kb = config_detail_kb(config_id)

    if isinstance(target, Message):
        await target.answer(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await target.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data.startswith("cfg_renew:"))
async def renew_config_start(cb: CallbackQuery):
    if not await _ensure_channel_membership(cb):
        return
    cid = int(cb.data.split(":")[1])
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    cfg = await get_config(cid)
    if not cfg or int(cfg.get("user_id") or 0) != int(user["id"]):
        await cb.answer("این سرویس برای شما پیدا نشد.", show_alert=True)
        return

    traffic_gb = float(cfg.get("traffic_gb") or 0)
    duration_days = int(cfg.get("duration_days") or 0)
    if traffic_gb <= 0 or duration_days <= 0:
        await cb.answer("این سرویس برای تمدید خودکار قابل محاسبه نیست. با پشتیبانی هماهنگ کنید.", show_alert=True)
        return

    price = await _calc_renew_price(user["id"], traffic_gb, duration_days)
    oid = await create_custom_order(
        user["id"],
        f"تمدید {cfg['email']}",
        traffic_gb,
        duration_days,
        price,
        notes=f"renew_config:{cid}",
    )
    await update_order(oid, renew_config_id=cid)
    text = await _payment_text(oid, f"تمدید سرویس {cfg['email']}", traffic_gb, duration_days, price)
    text += "\n\nبعد از تأیید، همین کانفیگ تمدید می‌شود و حجم مصرفی آن ریست می‌شود."
    await cb.message.answer(text, reply_markup=payment_kb(oid), parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data.startswith("cfg_link:"))
async def send_config_link(cb: CallbackQuery):
    if not await _ensure_channel_membership(cb):
        return
    cid = int(cb.data.split(":")[1])
    cfg = await get_config(cid)
    if not cfg:
        await cb.answer("سرویس یافت نشد", show_alert=True)
        return

    cli = XUIClient(cfg["server_url"], cfg["srv_user"], cfg["srv_pass"], cfg["sub_path"], cfg.get("srv_api_token", ""))
    link = await cli.get_client_link(cfg["inbound_id"], cfg["email"])
    sub = await cli.get_subscription_link(cfg["inbound_id"], cfg["email"])
    await cli.close()

    if link:
        body = f" *لینک اتصال شما:*\n\n`{link}`\n"
        if sub:
            body += f"\n *لینک سابسکریپشن:*\n`{sub}`\n"
        body += (
            "\n این لینک را کپی کن و در اپلیکیشن وارد کن.\n\n"
            "اپ‌های پیشنهادی:\n"
            "[📱 V2rayNG (اندروید)](https://github.com/2dust/v2rayNG/releases/latest) | "
            "[🍎 Streisand (iOS)](https://apps.apple.com/us/app/streisand/id6450534064) | "
            "[🪟 v2rayN (ویندوز)](https://github.com/2dust/v2rayN/releases/latest)"
        )
        await cb.message.answer(body, parse_mode="Markdown", reply_markup=config_links_kb(link, sub or ""))
        try:
            ch = await get_setting("channel_username", "AtlasChannel")
            await cb.message.answer_photo(_qr_input_file(link, ch), caption="QR Code کانفیگ شما", parse_mode=None)
        except Exception:
            pass
        await cb.answer()
    else:
        await cb.answer("❌ خطا در دریافت لینک.\nسرور را بررسی کنید.", show_alert=True)


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

    cli = XUIClient(cfg["server_url"], cfg["srv_user"], cfg["srv_pass"], cfg["sub_path"], cfg.get("srv_api_token", ""))
    sub = await cli.get_subscription_link(cfg["inbound_id"], cfg["email"])
    await cli.close()

    if sub:
        await cb.message.answer(f" *لینک سابسکریپشن:*\n`{sub}`", parse_mode="Markdown", reply_markup=config_links_kb("", sub))
        await cb.answer()
    else:
        await cb.answer("لینک ساب پیدا نشد", show_alert=True)


# ─── BUY ─────────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("cfg_qr:"))
async def cfg_qr(cb: CallbackQuery):
    if not await _ensure_channel_membership(cb):
        return
    cid = int(cb.data.split(":")[1])
    cfg = await get_config(cid)
    if not cfg:
        await cb.answer("یافت نشد", show_alert=True)
        return

    cli = XUIClient(cfg["server_url"], cfg["srv_user"], cfg["srv_pass"], cfg["sub_path"], cfg.get("srv_api_token", ""))
    link = await cli.get_client_link(cfg["inbound_id"], cfg["email"])
    await cli.close()
    if not link:
        await cb.answer("❌ لینک کانفیگ یافت نشد", show_alert=True)
        return

    try:
        ch = await get_setting("channel_username", "AtlasChannel")
        await cb.message.answer_photo(_qr_input_file(link, ch), caption=f"QR Code سرویس {cfg['email']}", parse_mode=None)
        await cb.answer()
    except Exception:
        await cb.answer("❌ ارسال QR Code ناموفق بود.", show_alert=True)


@router.message(F.text == "🛒 خرید سرویس")
async def buy_service(msg: Message):
    if not await _ensure_channel_membership(msg):
        return
    if await _blocked(msg.from_user.id):
        await msg.answer(await get_text("blocked_message"))
        return

    pkgs = await get_packages(active_only=True)
    if not pkgs:
        await msg.answer(" در حال حاضر پکیجی برای فروش وجود ندارد.\nلطفاً بعداً تلاش کنید.")
        return
    if not await get_available_servers():
        await msg.answer("⛔ فعلاً هیچ سروری ظرفیت خالی برای فروش ندارد.")
        return

    await msg.answer(
        "🛒 *پکیج مورد نظر را انتخاب کنید:*\n\nروی هر بخش از کارت پکیج بزنید تا همان پکیج انتخاب شود.",
        reply_markup=packages_kb(pkgs),
        parse_mode="Markdown",
    )


@router.callback_query(F.data.startswith("buy:"))
async def buy_pkg_selected(cb: CallbackQuery, state: FSMContext):
    pid = int(cb.data.split(":")[1])
    pkg = await get_package(pid)
    if not pkg or not pkg["is_active"]:
        await cb.answer("❌ این پکیج در دسترس نیست.", show_alert=True)
        return

    await state.set_state(BuyService.custom_name)
    await state.update_data(package_id=pid)
    await cb.message.edit_text(
        "✍️ اگر می‌خواهید انتهای اسم کانفیگ یک نام دلخواه اضافه شود، همینجا بفرستید.\n\n"
        "مثال: `mobile` یا `ali`\n"
        "اگر نمی‌خواهید، `-` را بفرستید.\n\n"
        "اسم اصلی ربات حفظ می‌شود و نام دلخواه شما بعد از آن می‌آید.",
        parse_mode="Markdown",
        reply_markup=flow_cancel_kb(),
    )
    await cb.answer()


@router.message(BuyService.custom_name)
async def buy_custom_name(msg: Message, state: FSMContext):
    data = await state.get_data()
    pid = int(data.get("package_id") or 0)
    pkg = await get_package(pid)
    if not pkg or not pkg["is_active"]:
        await state.clear()
        await msg.answer("❌ این پکیج دیگر در دسترس نیست.")
        return

    raw_name = (msg.text or "").strip()
    cmd = raw_name.split()[0].split("@", 1)[0].lower() if raw_name else ""
    if cmd == "/cancel":
        await state.clear()
        user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
        await msg.answer("❌ عملیات لغو شد.", reply_markup=user_menu(include_wholesale=bool(user.get("is_wholesale", 0))))
        return
    custom_name = "" if raw_name == "-" else _safe_user_config_name(raw_name)
    if raw_name != "-" and not custom_name:
        await msg.answer("❌ نام فقط می‌تواند شامل حرف، عدد، خط تیره و آندرلاین باشد. دوباره بفرستید یا `-` را بفرستید.", parse_mode="Markdown")
        return

    user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
    final_price, base_price, discount, price_per_gb = await _calc_package_price_for_user(user["id"], pkg)
    oid = await create_order(user["id"], pid, custom_config_name=custom_name, custom_price=final_price)

    text = await _payment_text(oid, pkg["name"], pkg["traffic_gb"], pkg["duration_days"], final_price)
    if price_per_gb > 0 or discount > 0:
        text += f"\n\nقیمت پایه: `{_fmt_toman(base_price)}` تومان"
        if price_per_gb > 0:
            text += f"\nقیمت اختصاصی هر GB: `{_fmt_toman(price_per_gb)}` تومان"
        if discount > 0:
            text += f"\nتخفیف شما: `{discount:g}%`"
    if custom_name:
        text += f"\n\nنام دلخواه انتهای کانفیگ: `{custom_name}`"
    await state.clear()
    await msg.answer(text, reply_markup=payment_kb(oid), parse_mode="Markdown")




@router.callback_query(F.data.startswith("pay_wallet:"))
async def pay_with_wallet(cb: CallbackQuery):
    if not await _ensure_channel_membership(cb):
        return
    if await _blocked(cb.from_user.id):
        await cb.answer("حساب شما مسدود است", show_alert=True)
        return
    oid = int(cb.data.split(":")[1])
    order = await get_order(oid)
    if not order:
        await cb.answer("سفارش یافت نشد", show_alert=True)
        return
    user = await get_or_create_user(cb.from_user.id)
    if order.get("user_id") != user.get("id"):
        await cb.answer("این سفارش متعلق به شما نیست", show_alert=True)
        return
    if str(order.get("status")) not in ("pending_payment", "pending_receipt"):
        await cb.answer("این سفارش قابل پرداخت نیست", show_alert=True)
        return

    balance = await get_user_balance(user["id"])
    price = int(order.get("price") or 0)
    if balance < price:
        await cb.answer(f"موجودی کافی نیست. موجودی: {_fmt_toman(balance)} تومان", show_alert=True)
        return

    await add_user_balance(user["id"], -price, kind="purchase", note=f"order:{oid}", actor_telegram_id=cb.from_user.id)
    await update_order(oid, status="receipt_submitted", notes=((order.get("notes") or "") + "\nwallet_payment=1").strip())
    await cb.answer("✅ پرداخت از کیف پول انجام شد. سفارش در حال پردازش است...", show_alert=True)
    await _notify_admins_plain(
        cb.bot,
        "💳 خرید با کیف پول\n\n"
        f"کاربر: {order.get('full_name') or cb.from_user.full_name or '-'} (@{order.get('username') or cb.from_user.username or '-'})\n"
        f"Telegram ID: {cb.from_user.id}\n"
        f"سفارش: #{oid} | {order.get('pkg_name') or '-'}\n"
        f"حجم: {order.get('traffic_gb')} GB | مدت: {order.get('duration_days')} روز\n"
        f"مبلغ: {_fmt_toman(price)} تومان",
    )

    if int(order.get("renew_config_id") or 0) > 0:
        cfg = await get_config(int(order["renew_config_id"]))
        if not cfg:
            await add_user_balance(user["id"], price, kind="refund", note=f"renew_failed:{oid}", actor_telegram_id=0)
            await update_order(oid, status="pending_payment")
            await cb.message.answer("سرویس برای تمدید پیدا نشد و مبلغ به کیف پول شما برگشت داده شد.")
            return
        server_id = int(cfg["server_id"])
    else:
        servers = [sv for sv in await get_available_servers()]
        if not servers:
            await cb.message.answer("پرداخت انجام شد، اما سرور فعالی برای ساخت کانفیگ پیدا نشد. سفارش برای بررسی ادمین ارسال شد.")
            return

        default_sid_raw = await get_setting("default_server_id", "0")
        try:
            default_sid = int(default_sid_raw or 0)
        except (TypeError, ValueError):
            default_sid = 0
        server = next((sv for sv in servers if sv["id"] == default_sid), servers[0])
        server_id = int(server["id"])

    from bot.handlers.admin import _do_approve
    ok = await _do_approve(cb, oid, server_id)
    if not ok:
        await add_user_balance(user["id"], price, kind="refund", note=f"order_failed:{oid}", actor_telegram_id=0)
        await update_order(oid, status="pending_payment")
        await cb.message.answer("ساخت کانفیگ ناموفق بود و مبلغ به کیف پول شما برگشت داده شد. لطفاً با پشتیبانی هماهنگ کنید.")


@router.callback_query(F.data.startswith("receipt:"))
async def prompt_receipt(cb: CallbackQuery, state: FSMContext):
    oid = int(cb.data.split(":")[1])
    await state.set_state(BuyService.waiting_receipt)
    await state.update_data(order_id=oid)
    await update_order(oid, status="pending_receipt")
    await cb.message.edit_text(" *ارسال فیش پرداخت*\n\nتصویر فیش واریزی را ارسال کنید ", parse_mode="Markdown", reply_markup=flow_cancel_kb())


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
        "پس از تأیید، لینک کانفیگ برایتان ارسال می‌شود.\n",
        parse_mode="Markdown",
    )

    # اطلاع به ادمین‌ها
    caption = (
        f" *فیش جدید!*\n"
        f"━━━━━━━━━━━━━━\n"
        f" سفارش: #{oid}\n"
        f" {msg.from_user.full_name} (@{msg.from_user.username or '—'})\n"
        f" {order['pkg_name']}\n"
        f" {_fmt_toman(order['price'])} تومان"
    )
    from bot.keyboards import order_review_kb

    admin_targets = list(dict.fromkeys(list(ADMIN_IDS) + await get_all_admin_telegram_ids()))
    for aid in admin_targets:
        try:
            sent = await bot.send_photo(aid, photo_id, caption=caption, reply_markup=order_review_kb(oid), parse_mode=None)
            await add_review_message("order", oid, sent.chat.id, sent.message_id)
        except Exception:
            try:
                sent = await bot.send_message(aid, caption, reply_markup=order_review_kb(oid), parse_mode=None)
                await add_review_message("order", oid, sent.chat.id, sent.message_id)
            except Exception:
                pass


@router.message(BuyService.waiting_receipt)
async def wrong_receipt_format(msg: Message):
    await msg.answer(" لطفاً *تصویر* (عکس) فیش را ارسال کنید.", parse_mode="Markdown", reply_markup=flow_cancel_kb())


@router.callback_query(F.data.startswith("cancel_order:"))
async def cancel_order(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    oid = int(cb.data.split(":")[1])
    await update_order(oid, status="cancelled")
    await cb.message.edit_text("❌ سفارش لغو شد.")


# ─── WHOLESALE ────────────────────────────────────────────────────
@router.message(F.text == "🏷️ خرید عمده")
async def wholesale_start(msg: Message, state: FSMContext):
    if not await _ensure_channel_membership(msg):
        return
    if await _blocked(msg.from_user.id):
        await msg.answer(await get_text("blocked_message"))
        return
    user = await get_or_create_user(msg.from_user.id)
    if not user.get("is_wholesale", 0):
        if user.get("wholesale_request_pending", 0):
            await msg.answer("⏳ درخواست همکاری عمده شما قبلاً ثبت شده و منتظر بررسی ادمین است.")
        else:
            await msg.answer(
                "🏷️ *خرید عمده فقط برای همکاران تاییدشده فعال است.*\n\n"
                "اگر فروشنده/همکار هستید، درخواست همکاری ارسال کنید تا ادمین بررسی کند.",
                reply_markup=wholesale_request_kb(),
                parse_mode="Markdown",
            )
        return

    await state.set_state(WholesaleBuy.count)
    await msg.answer("️ خرید عمده\n\nتعداد کانفیگ موردنیاز را وارد کنید (مثال: 20)", reply_markup=flow_cancel_kb())




@router.callback_query(F.data == "wh_req")
async def wholesale_request_submit(cb: CallbackQuery):
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    if user.get("is_wholesale", 0):
        await cb.answer("شما قبلاً تایید شده‌اید ✅", show_alert=True)
        return
    if user.get("wholesale_request_pending", 0):
        await cb.answer("درخواست شما قبلاً ثبت شده و در حال بررسی است.", show_alert=True)
        return

    await update_user(user["id"], wholesale_request_pending=1)
    for aid in ADMIN_IDS:
        try:
            await cb.bot.send_message(
                aid,
                f"🧾 *درخواست همکاری عمده جدید*\n\n"
                f"👤 {cb.from_user.full_name or '—'} (@{cb.from_user.username or '—'})\n"
                f"🆔 `{cb.from_user.id}`",
                reply_markup=wholesale_request_admin_kb(user["id"]),
                parse_mode="Markdown",
            )
        except Exception:
            pass

    await cb.message.answer("✅ درخواست شما ثبت شد. پس از تایید ادمین، منوی خرید عمده برای شما فعال می‌شود.")
    await cb.answer()

@router.message(WholesaleBuy.count)
async def wholesale_count(msg: Message, state: FSMContext):
    try:
        count = max(1, min(100, int(msg.text.strip())))
    except ValueError:
        await msg.answer("❌ عدد معتبر وارد کنید")
        return
    await state.update_data(count=count)
    await state.set_state(WholesaleBuy.traffic)
    await msg.answer(" حجم هر کانفیگ (GB) را وارد کنید", reply_markup=flow_cancel_kb())


@router.message(WholesaleBuy.traffic)
async def wholesale_traffic(msg: Message, state: FSMContext):
    try:
        gb = float(msg.text.strip())
    except ValueError:
        await msg.answer("❌ عدد معتبر وارد کنید")
        return
    await state.update_data(traffic=gb)
    await state.set_state(WholesaleBuy.duration)
    await msg.answer(" مدت هر کانفیگ (روز) را وارد کنید", reply_markup=flow_cancel_kb())


@router.message(WholesaleBuy.duration)
async def wholesale_duration(msg: Message, state: FSMContext):
    try:
        days = int(msg.text.strip())
    except ValueError:
        await msg.answer("❌ عدد معتبر وارد کنید")
        return

    await state.update_data(duration=days)
    await state.set_state(WholesaleBuy.naming_prefix)
    await msg.answer(
        "📝 الگوی اسم کانفیگ‌ها را وارد کنید (مثال: `Mobile110 📱`)\n"
        "اگر نمی‌خواهید شخصی‌سازی شود، `-` بفرستید.",
        parse_mode="Markdown",
        reply_markup=flow_cancel_kb(),
    )


@router.message(WholesaleBuy.naming_prefix)
async def wholesale_naming_prefix(msg: Message, state: FSMContext):
    prefix = msg.text.strip()
    await state.update_data(naming_prefix="" if prefix == "-" else prefix)
    await state.set_state(WholesaleBuy.naming_start)
    await msg.answer("🔢 شماره شروع را وارد کنید (مثال: 151)", reply_markup=flow_cancel_kb())


@router.message(WholesaleBuy.naming_start)
async def wholesale_naming_start(msg: Message, state: FSMContext):
    try:
        start_no = int(msg.text.strip())
    except ValueError:
        await msg.answer("❌ شماره معتبر وارد کنید")
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

    notes = ""
    if data.get("naming_prefix"):
        notes = json.dumps({"bulk_name_prefix": data["naming_prefix"], "bulk_start_number": start_no}, ensure_ascii=False)

    oid = await create_custom_order(
        user["id"],
        name=f"عمده {data['count']}x{data['traffic']}GB",
        total_traffic_gb=total_gb,
        duration_days=int(data["duration"]),
        price=final_price,
        bulk_count=data["count"],
        bulk_each_gb=data["traffic"],
        notes=notes,
    )

    card_bank, card_number, card_holder = await _get_card_info()
    naming_line = ""
    if data.get("naming_prefix"):
        naming_line = f"\n🏷️ الگوی نام: `{data['naming_prefix']}-{start_no} -{int(data['traffic'])}GB`"

    text = (
        f" *سفارش عمده #{oid}*\n"
        f"تعداد: `{data['count']}` کانفیگ\n"
        f"حجم هر کانفیگ: `{data['traffic']} GB`\n"
        f"مدت: `{int(data['duration'])}` روز{naming_line}\n"
        f"قیمت هر GB: `{pricing['price_per_gb'] or 10000:,}` تومان\n"
        f"تخفیف شما: `{discount}%`\n"
        f" مبلغ نهایی: *{_fmt_toman(final_price)} تومان*\n\n"
        f" {card_bank}\n `{card_number}`\n {card_holder}\n\n"
        f"برای ثبت پرداخت روی «ارسال فیش» بزنید."
    )
    await msg.answer(text, reply_markup=payment_kb(oid), parse_mode="Markdown")
    await _notify_admins_plain(
        msg.bot,
        "🏷️ سفارش عمده جدید\n\n"
        f"کاربر: {msg.from_user.full_name or '-'} (@{msg.from_user.username or '-'})\n"
        f"Telegram ID: {msg.from_user.id}\n"
        f"سفارش: #{oid}\n"
        f"تعداد: {data['count']} کانفیگ\n"
        f"حجم هر کانفیگ: {data['traffic']} GB | مدت: {int(data['duration'])} روز\n"
        f"مبلغ: {_fmt_toman(final_price)} تومان\n"
        f"الگوی نام: {data.get('naming_prefix') or '-'}",
    )


def _extract_config_identity(link: str):
    def decode_b64_text(value: str) -> str:
        raw = (value or "").strip()
        raw += "=" * (-len(raw) % 4)
        for decoder in (base64.urlsafe_b64decode, base64.b64decode):
            try:
                return decoder(raw.encode()).decode("utf-8", "ignore")
            except (binascii.Error, UnicodeDecodeError, ValueError):
                continue
        return ""

    try:
        raw_link = link.strip()
        if raw_link.lower().startswith("vmess://"):
            payload = raw_link[8:].split("#", 1)[0].split("?", 1)[0]
            decoded = decode_b64_text(payload)
            try:
                obj = json.loads(decoded)
            except Exception:
                obj = {}
            raw_uuid = (obj.get("id") or "").strip()
            email = (obj.get("ps") or obj.get("remark") or obj.get("email") or "").strip()
            if not raw_uuid and not email:
                return None, None, None
            key_part = raw_uuid or email
            return f"vmess|{key_part}".lower(), email, raw_uuid

        p = urlparse(raw_link)
        if p.scheme not in ("vless", "vmess", "trojan", "ss", "hysteria", "hysteria2", "hy2"):
            return None, None, None
        email = unquote((p.fragment or "").strip())
        raw_uuid = unquote((p.username or "").strip())
        q = parse_qs(p.query or "")
        if not email and "remark" in q and q["remark"]:
            email = unquote(q["remark"][0])
        if not email and "email" in q and q["email"]:
            email = unquote(q["email"][0])
        key_part = raw_uuid or email or p.netloc or raw_link
        key = f"{p.scheme}|{key_part}".strip().lower()
        return key, email, raw_uuid
    except Exception:
        return None, None, None


async def _notify_legacy_claim_admins(bot: Bot, claim_id: int, from_user, email: str):
    targets = list(dict.fromkeys([*ADMIN_IDS, *(await get_all_admin_telegram_ids())]))
    for aid in targets:
        try:
            await bot.send_message(
                aid,
                "🧾 درخواست سینک کانفیگ قدیمی\n\n"
                f"کاربر: {from_user.full_name or '-'} (@{from_user.username or '-'})\n"
                f"Telegram ID: {from_user.id}\n"
                f"email: {email or '-'}\n"
                f"claim: #{claim_id}",
                reply_markup=legacy_claim_admin_kb(claim_id),
            )
        except Exception:
            pass


async def _admin_targets() -> list[int]:
    return list(dict.fromkeys([*ADMIN_IDS, *(await get_all_admin_telegram_ids())]))


async def _notify_admins_plain(bot: Bot, text: str):
    for aid in await _admin_targets():
        try:
            await bot.send_message(aid, text, parse_mode=None)
        except Exception:
            pass


@router.message(F.text == "🔗 سینک کانفیگ قبلی")
async def legacy_sync_start(msg: Message, state: FSMContext):
    if not await _ensure_channel_membership(msg):
        return
    if await _blocked(msg.from_user.id):
        await msg.answer(await get_text("blocked_message"))
        return

    enabled = await get_setting("legacy_sync_enabled", "1")
    if enabled != "1":
        await msg.answer("⛔ این بخش فعلاً غیرفعال شده است.")
        return

    await state.set_state(LegacySync.waiting_link)
    await msg.answer(
        "🔗 لینک کانفیگ قبلی خود را ارسال کنید تا برای اتصال به حساب شما بررسی شود.\n\n"
        "پس از تایید ادمین، سرویس به اکانت شما متصل می‌شود.\n"
        "برای لغو: /cancel"
    , reply_markup=flow_cancel_kb())


@router.message(LegacySync.waiting_link)
async def legacy_sync_submit(msg: Message, state: FSMContext):
    link = (msg.text or "").strip()
    cmd = link.split()[0].split("@", 1)[0].lower() if link else ""
    if cmd == "/cancel":
        await state.clear()
        user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
        from bot.keyboards import user_menu
        await msg.answer("❌ عملیات لغو شد.", reply_markup=user_menu(include_wholesale=bool(user.get("is_wholesale", 0))))
        return
    key, email, raw_uuid = _extract_config_identity(link)
    if not key:
        await msg.answer("❌ لینک معتبر نیست. لطفاً لینک کامل کانفیگ را ارسال کنید.")
        return

    dup = await get_legacy_claim_by_key(key) or await get_legacy_claim_by_identity(email=email, uuid=raw_uuid)
    if dup:
        status = dup.get("status", "pending")
        if status == "approved":
            await msg.answer("⚠️ این کانفیگ قبلاً تایید و ثبت شده است و درخواست تکراری پذیرفته نمی‌شود.")
        elif status == "pending":
            await msg.answer("⏳ برای این کانفیگ قبلاً درخواست ثبت شده و در حال بررسی است.")
        else:
            user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
            await update_legacy_claim(
                dup["id"],
                user_id=user["id"],
                telegram_id=msg.from_user.id,
                config_link=link,
                config_key=key,
                email=email,
                uuid=raw_uuid,
                status="pending",
                admin_note="retry_by_user",
                reviewed_at=None,
                reviewer_id=0,
            )
            await _notify_legacy_claim_admins(msg.bot, dup["id"], msg.from_user, email)
            await state.clear()
            await msg.answer("✅ درخواست قبلی دوباره برای بررسی ادمین ارسال شد.")
        return

    user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
    claim_id = await create_legacy_claim(user["id"], msg.from_user.id, link, key, email=email, uuid=raw_uuid)

    await _notify_legacy_claim_admins(msg.bot, claim_id, msg.from_user, email)

    await state.clear()
    await msg.answer("✅ درخواست شما ثبت شد. پس از تایید ادمین، سرویس به حساب شما متصل می‌شود.")


# ─── MY ORDERS ───────────────────────────────────────────────────
@router.message(F.text == "📋 سفارش‌های من")
async def my_orders(msg: Message):
    if not await _ensure_channel_membership(msg):
        return
    user = await get_or_create_user(msg.from_user.id)
    orders = await get_user_orders(user["id"])
    if not orders:
        await msg.answer(" هنوز سفارشی ثبت نکرده‌اید.")
        return

    STATUS = {
        "pending_payment": "⏳ انتظار پرداخت",
        "pending_receipt": "⏳ انتظار فیش",
        "receipt_submitted": " در انتظار تأیید",
        "approved": "✅ فعال شده",
        "rejected": "❌ رد شده",
        "cancelled": " لغو شده",
    }

    text = " *سفارش‌های اخیر شما:*\n\n"
    for o in orders:
        st = STATUS.get(o["status"], o["status"])
        text += f" {o['pkg_name']} — {st}\n"
        text += f" {o['price']:,} تومن | {o['created_at'][:10]}\n\n"

    await msg.answer(text.strip(), parse_mode="Markdown")


# ─── MIGRATE ─────────────────────────────────────────────────────
@router.message(F.text == "🔄 انتقال سرور")
async def migrate_menu(msg: Message):
    if not await _ensure_channel_membership(msg):
        return

    user = await get_or_create_user(msg.from_user.id)
    configs = await get_user_configs(user["id"])
    if not configs:
        await msg.answer(" سرویس فعالی برای انتقال ندارید.")
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    b = InlineKeyboardBuilder()
    for c in configs:
        b.button(text=f" {c['email']} — {c['server_name']}", callback_data=f"mig_start:{c['id']}")
    b.adjust(1)

    await msg.answer(
        f" *انتقال سرور*\n\n"
        f"کدام سرویس را می‌خواهید منتقل کنید؟\n"
        f"⚠️ محدودیت: {MAX_DAILY_MIGRATIONS} بار در روز",
        reply_markup=b.as_markup(),
        parse_mode="Markdown",
    )


@router.callback_query(F.data.startswith("mig_start:"))
async def mig_start(cb: CallbackQuery):
    cid = int(cb.data.split(":")[1])
    cfg = await get_config(cid)
    user = await get_or_create_user(cb.from_user.id)

    if cfg["user_id"] != user["id"]:
        await cb.answer("❌ این سرویس متعلق به شما نیست!", show_alert=True)
        return

    today_cnt = await get_user_migration_count_today(user["id"])
    if today_cnt >= MAX_DAILY_MIGRATIONS:
        await cb.answer(
            f"⛔ امروز {MAX_DAILY_MIGRATIONS} بار انتقال انجام دادید!\nفردا دوباره امتحان کنید.",
            show_alert=True,
        )
        return

    all_servers = await get_servers()
    others = [s for s in all_servers if s["id"] != cfg["server_id"]]
    if not others:
        await cb.answer("❌ سرور دیگری برای انتقال موجود نیست!", show_alert=True)
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from core.database import count_active_configs_by_server
    kb = InlineKeyboardBuilder()
    for s in others:
        cap = int(s.get("max_active_configs") or 0)
        label = f"🖥️ {s['name']}"
        if cap > 0:
            used = await count_active_configs_by_server(s["id"])
            if used >= cap:
                label += " — ⛔ ظرفیت پر شده"
        kb.button(text=label, callback_data=f"mig_confirm:{s['id']}:{cid}")
    kb.adjust(1)

    remaining = MAX_DAILY_MIGRATIONS - today_cnt
    await cb.message.edit_text(
        f" *انتقال سرویس*\n\n"
        f" سرویس: `{cfg['email']}`\n"
        f"️ سرور فعلی: `{cfg['server_name']}`\n"
        f" انتقال باقی‌مانده امروز: `{remaining}`\n\n"
        "سرور مقصد را انتخاب کنید:",
        reply_markup=kb.as_markup(),
        parse_mode="Markdown",
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

    today_cnt = await get_user_migration_count_today(user["id"])
    if today_cnt >= MAX_DAILY_MIGRATIONS:
        await cb.answer("⛔ محدودیت روزانه پر شده!", show_alert=True)
        return

    await cb.message.edit_text("⏳ در حال انتقال سرویس...")

    # دریافت آمار واقعی
    src_srv = await get_server(cfg["server_id"])
    src_cli = XUIClient(src_srv["url"], src_srv["username"], src_srv["password"], src_srv["sub_path"], src_srv.get("api_token", ""))
    traffic = await src_cli.get_client_traffic(cfg["email"])
    if traffic:
        total_b = traffic.get("total", int(cfg["traffic_gb"] * 1024**3))
        used_b = traffic.get("down", 0) + traffic.get("up", 0)
        rem_b = max(0, total_b - used_b)
        expire_ms = traffic.get("expiryTime", cfg["expire_timestamp"] or 0)
    else:
        rem_b = int(cfg["traffic_gb"] * 1024**3)
        expire_ms = cfg["expire_timestamp"] or 0

    rem_gb = rem_b / (1024**3)
    dl = days_left(expire_ms)
    new_days = dl if dl > 0 else 36500

    # ساخت کانفیگ جدید
    dst_srv = await get_server(dst_sid)
    cap = int(dst_srv.get("max_active_configs") or 0)
    if cap > 0:
        from core.database import count_active_configs_by_server
        used = await count_active_configs_by_server(dst_sid)
        if used >= cap:
            await cb.answer("⛔ ظرفیت این سرور پر شده است", show_alert=True)
            return
    dst_cli = XUIClient(dst_srv["url"], dst_srv["username"], dst_srv["password"], dst_srv["sub_path"], dst_srv.get("api_token", ""))

    new_uuid = str(_uuid.uuid4())
    new_email = f"{cfg['email'].split('_m')[0]}_m{int(time.time())}"

    ok = await dst_cli.add_client(dst_srv["inbound_id"], new_uuid, new_email, rem_gb, new_days, starts_on_first_use=False)
    if not ok:
        await src_cli.close()
        await dst_cli.close()
        await cb.message.edit_text("❌ خطا در ساخت کانفیگ روی سرور مقصد!")
        return

    # غیرفعال کردن کانفیگ قدیمی
    await src_cli.update_client(cfg["inbound_id"], cfg["uuid"], cfg["email"], cfg["traffic_gb"], cfg["expire_timestamp"] or 0, False)
    new_link = await dst_cli.get_client_link(dst_srv["inbound_id"], new_email)

    await src_cli.close()
    await dst_cli.close()

    # ذخیره کانفیگ جدید و غیرفعال کردن قدیمی
    await update_config(src_cid, is_active=0)
    new_exp_ms = expiry_ms_from_days(new_days)
    await save_config(user["id"], dst_sid, new_uuid, new_email, dst_srv["inbound_id"], rem_gb, new_days, new_exp_ms, starts_on_first_use=0)

    # آپدیت شمارنده انتقال
    today = date.today().isoformat()
    new_cnt = today_cnt + 1
    await update_config(src_cid, migration_count=new_cnt, last_migration_date=today)

    text = (
        f"✅ *انتقال موفق!*\n"
        f"━━━━━━━━━━━━━━\n"
        f"️ سرور جدید: `{dst_srv['name']}`\n"
        f" حجم منتقل‌شده: `{rem_gb:.2f} GB`\n"
        f" روزهای باقی: `{dl if dl > 0 else 'نامحدود'}`\n\n"
        f"⚠️ لینک قدیمی غیرفعال شد."
    )
    if new_link:
        text += f"\n\n *لینک جدید:*\n`{new_link}`"
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=config_links_kb(new_link or "", ""))
    if new_link:
        try:
            ch = await get_setting("channel_username", "AtlasChannel")
            await cb.message.answer_photo(_qr_input_file(new_link, ch), caption="QR Code لینک جدید شما", parse_mode=None)
        except Exception:
            pass


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
        f" *لینک اختصاصی شما:*\n`{ref_link}`\n\n"
        f"━━━━━━━━━━━━━━\n"
        f" *آمار شما:*\n"
        f" دعوت‌شدگان: `{stats['invited']}` نفر\n"
        f"✅ خریداران: `{stats['converted']}` نفر\n"
        f" هدیه کسب‌شده: `{stats['bonus_gb']} GB`\n\n"
        f" برای استفاده از هدیه با پشتیبانی در تماس باشید."
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
        text += f" تماس مستقیم: @{sup}\n"
    text += await get_text("support_body")

    await msg.answer(text, parse_mode="Markdown")
