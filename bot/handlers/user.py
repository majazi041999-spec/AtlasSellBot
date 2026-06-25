import asyncio
import uuid as _uuid
import time
import json
import base64
import binascii
import aiosqlite
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime, timedelta, date

from aiogram import Router, F, Bot
from aiogram.filters import StateFilter
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
    get_referral_tiers,
    count_converted_referrals,
    update_user,
    DB_PATH,
    get_user_pricing,
    create_custom_order,
    get_available_servers,
    get_legacy_claim_by_key,
    get_legacy_claim_by_identity,
    update_legacy_claim,
    create_legacy_claim,
    get_config_by_email,
    get_config_by_uuid,
    get_user_balance,
    create_topup_request,
    add_user_balance,
    get_all_admin_telegram_ids,
    add_review_message,
    get_user_test_account,
    add_user_test_account,
    get_least_loaded_server,
    delete_config_by_id,
    get_user_subscription_profiles,
    get_subscription_profile_by_token,
    get_subscription_nodes,
    get_subscription_node,
    get_subscription_profile,
    update_subscription_profile,
    validate_discount_code,
)
from core.xui_api import XUIClient, fmt_bytes, days_left, expiry_ms_from_days
from core.texts import get_text
from core.qr import build_qr_image
from core.multi_subscription import (
    subscription_url,
    sync_profile_usage,
    delete_subscription_profile_remote,
    create_profile_from_config,
    create_test_subscription,
    subscription_error_message,
)
from bot.middlewares.channel_required import ChannelRequiredMiddleware

from bot.keyboards import (
    user_menu,
    packages_kb,
    payment_kb,
    config_detail_kb,
    config_to_sub_confirm_kb,
    config_delete_confirm_kb,
    renew_options_kb,
    config_links_kb,
    user_services_kb,
    subscription_detail_kb,
    subscription_delete_confirm_kb,
    servers_kb,
    custom_name_kb,
    discount_skip_kb,
    wholesale_request_kb,
    wholesale_request_admin_kb,
    legacy_claim_admin_kb,
    wallet_kb,
    flow_cancel_kb,
)
from bot.states import AnonymousFeedback, BuyService, RenewService, WholesaleBuy, LegacySync, WalletTopup, RenameSub, BuyDiscount

router = Router()
RENEWAL_MIN_DAYS = 30


async def _blocked(uid: int) -> bool:
    u = await get_or_create_user(uid)
    return bool(u.get("is_blocked", 0))


def _channel_join_kb(channel_username: str):
    return ChannelRequiredMiddleware.join_kb(channel_username)


def _extract_subscription_token(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    try:
        p = urlparse(raw)
    except Exception:
        return ""
    if p.scheme not in ("http", "https") or not p.netloc:
        return ""
    parts = [part for part in (p.path or "").split("/") if part]
    if len(parts) >= 2 and parts[-2].lower() == "sub":
        token = parts[-1].strip()
        if token and all(ch.isalnum() or ch in "-_" for ch in token):
            return token
    return ""


def _format_subscription_status_card(profile: dict, sub_url: str, used: int, total: int, remaining: int,
                                     pct: int, days_text: str, active_nodes: list[dict]) -> str:
    service_name = profile.get("name") or profile.get("email") or f"ساب #{profile.get('id')}"
    status_text = "فعال" if int(profile.get("is_active") or 0) else "غیرفعال"
    filled = max(0, min(10, int(round((pct / 100) * 10))))
    usage_bar = "█" * filled + "░" * (10 - filled)
    node_names = [
        str(n.get("node_label") or n.get("server_name") or f"Node #{n.get('id')}")
        for n in active_nodes[:6]
    ]
    nodes_text = "\n".join(f"• {name}" for name in node_names) if node_names else "• نودی فعال نیست"
    return (
        "📡 وضعیت سرویس سابسکریپشن\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"نام سرویس: {service_name}\n"
        f"وضعیت: {status_text}\n\n"
        "مصرف سرویس\n"
        f"{usage_bar} {pct}%\n"
        f"مصرف‌شده: {fmt_bytes(used)}\n"
        f"باقی‌مانده: {fmt_bytes(remaining)}\n"
        f"حجم کل: {fmt_bytes(total)}\n\n"
        "زمان سرویس\n"
        f"باقی‌مانده: {days_text}\n\n"
        f"نودهای فعال ({len(active_nodes)})\n"
        f"{nodes_text}\n\n"
        "لینک سابسکریپشن\n"
        f"{sub_url}"
    )


def _format_node_links_block(active_nodes: list[dict]) -> str:
    """List each server's connection link with its remark, so the user can copy
    a single server's link directly if the subscription URL has trouble."""
    rows = []
    idx = 0
    for n in active_nodes:
        link = (n.get("link") or "").strip()
        if not link:
            continue
        idx += 1
        remark = str(n.get("node_label") or n.get("server_name") or f"سرور {idx}").strip()
        rows.append(f"📍 {remark}:\n{link}")
    if not rows:
        return ""
    return "🔗 لینک مستقیم سرورها (در صورت مشکل لینک ساب):\n\n" + "\n\n".join(rows)


async def _send_subscription_status(target, profile: dict, send_qr: bool = True):
    if not profile:
        return
    # Live usage sync is best-effort and time-boxed: a slow/down X-UI server
    # must never block showing the user their cached subscription link.
    try:
        await asyncio.wait_for(sync_profile_usage(profile), timeout=12)
        profile = await get_subscription_profile_by_token(profile["token"]) or profile
    except Exception:
        pass

    sub_url = await subscription_url(profile["token"])
    nodes = await get_subscription_nodes(profile["id"])
    used = int(profile.get("used_bytes") or 0)
    total = int(float(profile.get("traffic_gb") or 0) * 1024 ** 3)
    remaining = max(0, total - used) if total > 0 else 0
    pct = min(100, int(used / total * 100)) if total > 0 else 0
    not_started = int(profile.get("starts_on_first_use") or 0) and int(profile.get("first_use_at") or 0) <= 0
    dl = days_left(int(profile.get("expire_timestamp") or 0))
    if not_started:
        dur = int(profile.get("duration_days") or 0)
        dl_text = f"از اولین اتصال شروع می‌شود ({dur} روز)" if dur > 0 else "از اولین اتصال شروع می‌شود"
    else:
        dl_text = f"{dl} روز" if dl > 0 else ("نامحدود" if dl < 0 else "منقضی شده")
    active_nodes = [n for n in nodes if int(n.get("is_active") or 0)]
    node_names = [
        str(n.get("node_label") or n.get("server_name") or f"Node #{n.get('id')}")
        for n in active_nodes[:8]
    ]
    nodes_text = "، ".join(node_names) if node_names else "-"

    text = (
        "📡 سرویس سابسکریپشن چندسروره شما\n\n"
        f"حجم کل: {profile['traffic_gb']} GB\n"
        f"مصرف ثبت‌شده: {fmt_bytes(used)} از {fmt_bytes(total)} ({pct}%)\n"
        f"باقی‌مانده: {fmt_bytes(remaining)}\n"
        f"روز باقی‌مانده: {dl_text}\n"
        f"نودهای فعال: {len(active_nodes)}\n"
        f"Remark نودها: {nodes_text}\n"
        f"وضعیت: {'فعال' if int(profile.get('is_active') or 0) else 'غیرفعال'}\n\n"
        f"لینک ساب:\n{sub_url}"
    )

    text = _format_subscription_status_card(profile, sub_url, used, total, remaining, pct, dl_text, active_nodes)

    # Node links are exposed as buttons in subscription_detail_kb. Keeping long
    # configs out of the status text makes the card readable on mobile.
    guide = (await get_setting("sub_connection_guide", "")).strip()
    if guide:
        text += "\n\n" + guide
    if len(text) > 3900:
        text = text[:3900] + "\n…"

    kb = subscription_detail_kb(int(profile["id"]), sub_url, active_nodes)
    if isinstance(target, Message):
        await target.answer(text, parse_mode=None, reply_markup=kb)
        if send_qr:
            try:
                qr_label = profile.get("name") or profile.get("email") or "Subscription"
                await target.answer_photo(_qr_input_file(sub_url, qr_label), caption=f"QR سابسکریپشن: {qr_label}", parse_mode=None)
            except Exception:
                pass
    else:
        await target.message.edit_text(text, parse_mode=None, reply_markup=kb)


async def _is_channel_member(msg_or_cb) -> bool:
    required, channel_username = await ChannelRequiredMiddleware.is_required()
    if not required:
        return True

    uid = msg_or_cb.from_user.id if msg_or_cb.from_user else 0
    return await ChannelRequiredMiddleware.can_access(msg_or_cb.bot, uid, channel_username)


async def _ensure_channel_membership(msg_or_cb) -> bool:
    if await _is_channel_member(msg_or_cb):
        return True

    _, channel_username = await ChannelRequiredMiddleware.is_required()
    ch = ChannelRequiredMiddleware._channel_ref(channel_username) or "لینک عضویت"
    text = f"❌ قبل از استفاده از امکانات ربات باید عضو کانال شوید.\n\nکانال: {ch}\n\nبعد از عضویت دوباره تلاش کنید."
    if isinstance(msg_or_cb, Message):
        await msg_or_cb.answer(text, reply_markup=_channel_join_kb(channel_username))
    else:
        await msg_or_cb.answer("❌ ابتدا باید در کانال عضو شوید.", show_alert=True)
        if msg_or_cb.message:
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
    if int(duration_days or 0) > RENEWAL_MIN_DAYS:
        base = int(base * (int(duration_days) / RENEWAL_MIN_DAYS))
    discount = float(pricing.get("discount_percent") or 0)
    return int(base * (100 - discount) / 100)


async def _renewal_min_traffic() -> float:
    raw = await get_setting("renewal_min_traffic_gb", "1")
    try:
        return max(0.1, float(raw or 1))
    except (TypeError, ValueError):
        return 1.0


async def _calc_package_price_for_user(user_id: int, pkg: dict) -> tuple[int, int, float, int]:
    pricing = await get_user_pricing(user_id)
    base_price = int(pkg.get("price") or 0)
    price_per_gb = int(pricing.get("price_per_gb") or 0)
    if price_per_gb > 0:
        base_price = int(float(pkg.get("traffic_gb") or 0) * price_per_gb)
    discount = max(0.0, min(100.0, float(pricing.get("discount_percent") or 0)))
    final_price = int(base_price * (100 - discount) / 100)
    return max(0, final_price), max(0, base_price), discount, price_per_gb


async def _migration_limit() -> int:
    raw = await get_setting("max_daily_migrations", str(MAX_DAILY_MIGRATIONS))
    try:
        return max(0, int(raw or MAX_DAILY_MIGRATIONS))
    except (TypeError, ValueError):
        return MAX_DAILY_MIGRATIONS


async def _test_account_settings() -> dict:
    def as_float(value: str, default: float) -> float:
        try:
            return max(0.1, float(value or default))
        except (TypeError, ValueError):
            return default

    def as_int(value: str, default: int) -> int:
        try:
            return max(1, int(value or default))
        except (TypeError, ValueError):
            return default

    return {
        "enabled": await get_setting("test_account_enabled", "1") == "1",
        "traffic_gb": as_float(await get_setting("test_account_traffic_gb", "1"), 1.0),
        "duration_days": as_int(await get_setting("test_account_duration_days", "1"), 1),
        "server_id": as_int(await get_setting("test_account_server_id", "0"), 0),
        "prefix": (await get_setting("test_account_prefix", "test") or "test").strip()[:16],
    }


async def _pick_test_server(preferred_id: int) -> dict | None:
    servers = await get_available_servers()
    if not servers:
        return None
    if preferred_id:
        preferred = next((s for s in servers if int(s["id"]) == int(preferred_id)), None)
        if preferred:
            return preferred
    if await get_setting("auto_least_loaded_server", "0") == "1":
        suggested = await get_least_loaded_server()
        if suggested:
            return suggested
    default_raw = await get_setting("default_server_id", "0")
    try:
        default_id = int(default_raw or 0)
    except (TypeError, ValueError):
        default_id = 0
    if default_id:
        default = next((s for s in servers if int(s["id"]) == default_id), None)
        if default:
            return default
    return servers[0]


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


# ── ثبت مسیرهای «برگشت» کاربر در سیستم ناوبری یکپارچه (bot/nav.py) ──
def _register_user_back_steps():
    from bot import nav

    # شارژ کیف پول
    nav.register(WalletTopup.waiting_receipt, nav.static(
        WalletTopup.waiting_amount,
        "💵 مبلغ افزایش اعتبار را به تومان وارد کنید.\nمثال: `250000`",
        "Markdown",
    ))
    nav.register(WalletTopup.waiting_amount, nav.go_home)

    # خرید عمده
    nav.register(WholesaleBuy.traffic, nav.static(
        WholesaleBuy.count, "🔢 تعداد کانفیگ موردنیاز را وارد کنید (مثلاً 5):"))
    nav.register(WholesaleBuy.duration, nav.static(
        WholesaleBuy.traffic, "📊 حجم *هر کانفیگ* را به GB وارد کنید (مثلاً 20):", "Markdown"))
    nav.register(WholesaleBuy.naming_prefix, nav.static(
        WholesaleBuy.duration, "📅 مدت *هر کانفیگ* را به روز وارد کنید (مثلاً 30):", "Markdown"))
    nav.register(WholesaleBuy.naming_start, nav.static(
        WholesaleBuy.naming_prefix, "✍️ یک پیشوند نام وارد کنید (مثلاً `vip`):", "Markdown"))
    nav.register(WholesaleBuy.count, nav.go_home)

    # تمدید سرویس
    async def _renew_duration_back(cb: CallbackQuery, state: FSMContext):
        min_traffic = await _renewal_min_traffic()
        await state.set_state(RenewService.traffic)
        await cb.message.edit_text(
            f"📊 حجم جدید تمدید را به GB وارد کنید.\nحداقل: `{min_traffic:g} GB`\nمثال: `20`",
            reply_markup=flow_cancel_kb(),
            parse_mode="Markdown",
        )
    nav.register(RenewService.duration, _renew_duration_back)

    async def _renew_traffic_back(cb: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        cid = int(data.get("config_id") or 0)
        await state.clear()
        if cid:
            await cb.message.edit_text("♻️ نوع تمدید را انتخاب کنید:", reply_markup=renew_options_kb(cid), parse_mode="Markdown")
        else:
            await nav.go_home(cb, state)
    nav.register(RenewService.traffic, _renew_traffic_back)

    # خرید سرویس
    async def _buy_receipt_back(cb: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        oid = int(data.get("order_id") or 0)
        await state.clear()
        if oid:
            await update_order(oid, status="pending_payment")
            await cb.message.edit_text("⬅️ برگشتید به مرحله پرداخت.", reply_markup=payment_kb(oid), parse_mode="Markdown")
        else:
            await nav.go_home(cb, state)
    nav.register(BuyService.waiting_receipt, _buy_receipt_back)

    async def _buy_name_back(cb: CallbackQuery, state: FSMContext):
        await state.clear()
        pkgs = await get_packages(active_only=True)
        await cb.message.edit_text(
            "🛒 *پکیج مورد نظر را انتخاب کنید:*",
            reply_markup=packages_kb(pkgs),
            parse_mode="Markdown",
        )
    nav.register(BuyService.custom_name, _buy_name_back)

    # سینک کانفیگ قدیمی و بازخورد ناشناس
    nav.register(LegacySync.waiting_link, nav.go_home)
    nav.register(AnonymousFeedback.text, nav.go_home)


_register_user_back_steps()


async def _user_service_lists(user_id: int) -> tuple[list[dict], list[dict]]:
    configs = await get_user_configs(user_id)
    profiles = await get_user_subscription_profiles(user_id)
    return configs, profiles


async def _send_services_list(target, user_id: int, page: int = 0):
    configs, profiles = await _user_service_lists(user_id)
    total = len(configs) + len(profiles)
    text = (
        "📡 مدیریت سرویس‌های شما\n\n"
        f"کل سرویس‌ها: {total}\n"
        f"کانفیگ عادی: {len(configs)} | لینک ساب: {len(profiles)}\n\n"
        "یکی از سرویس‌ها را انتخاب کنید:"
    )
    kb = user_services_kb(configs, profiles, page=page)
    if isinstance(target, Message):
        await target.answer(text, reply_markup=kb, parse_mode=None)
    else:
        await target.message.edit_text(text, reply_markup=kb, parse_mode=None)


@router.message(F.text == "📡 وضعیت سرویس")
async def user_status(msg: Message):
    if not await _ensure_channel_membership(msg):
        return
    if await _blocked(msg.from_user.id):
        await msg.answer(await get_text("blocked_message"))
        return

    user = await get_or_create_user(msg.from_user.id)
    configs, profiles = await _user_service_lists(user["id"])
    total = len(configs) + len(profiles)
    if total <= 0:
        await msg.answer(await get_text("no_active_service"), parse_mode="Markdown")
        return
    if total == 1 and configs:
        await _send_config_status(msg, configs[0]["id"])
        return
    if total == 1 and profiles:
        await _send_subscription_status(msg, profiles[0])
        return
    await _send_services_list(msg, user["id"], page=0)


@router.callback_query(F.data.startswith("svc_pg:"))
async def services_page(cb: CallbackQuery):
    if not await _ensure_channel_membership(cb):
        return
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    try:
        page = int(cb.data.split(":", 1)[1])
    except Exception:
        page = 0
    await _send_services_list(cb, user["id"], page=page)
    await cb.answer()


@router.callback_query(F.data.startswith("cfg:"))
async def cfg_selected(cb: CallbackQuery):
    if not await _ensure_channel_membership(cb):
        return
    cid = int(cb.data.split(":")[1])
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    if not await _owned_config_for_user(user["id"], cid):
        await cb.answer("این سرویس برای شما پیدا نشد.", show_alert=True)
        return
    await _send_config_status(cb, cid)


@router.callback_query(F.data == "back_configs")
async def back_configs(cb: CallbackQuery):
    user = await get_or_create_user(cb.from_user.id)
    configs, profiles = await _user_service_lists(user["id"])
    if not configs and not profiles:
        await cb.message.edit_text(" سرویسی ندارید.")
        await cb.answer()
        return
    await _send_services_list(cb, user["id"], page=0)
    await cb.answer()


async def _owned_config_for_user(user_id: int, config_id: int) -> dict | None:
    cfg = await get_config(config_id)
    if not cfg or int(cfg.get("user_id") or 0) != int(user_id):
        return None
    return cfg


async def _send_config_status(target, config_id: int):
    cfg = await get_config(config_id)
    if not cfg:
        return

    # get_config already JOINs server data → use cfg aliases directly.
    # Time-box the live X-UI call so a slow/down server can't freeze the bot.
    cli = XUIClient(cfg["server_url"], cfg["srv_user"], cfg["srv_pass"], cfg["sub_path"], cfg.get("srv_api_token", ""))
    try:
        traffic = await asyncio.wait_for(cli.get_client_traffic(cfg["email"]), timeout=12)
    except Exception:
        traffic = None
    finally:
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


@router.callback_query(F.data.startswith("cfg_del:"))
async def cfg_delete_confirm(cb: CallbackQuery):
    if not await _ensure_channel_membership(cb):
        return
    cid = int(cb.data.split(":")[1])
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    cfg = await _owned_config_for_user(user["id"], cid)
    if not cfg:
        await cb.answer("این سرویس برای شما پیدا نشد.", show_alert=True)
        return
    await cb.message.edit_text(
        "🗑️ *حذف سرویس*\n\n"
        f"کانفیگ: `{cfg['email']}`\n\n"
        "با تایید، سرویس از سرور و از حساب شما حذف می‌شود. این کار قابل برگشت نیست.",
        reply_markup=config_delete_confirm_kb(cid),
        parse_mode="Markdown",
    )
    await cb.answer()


@router.callback_query(F.data.startswith("cfg_to_sub:"))
async def cfg_to_sub_confirm(cb: CallbackQuery):
    if not await _ensure_channel_membership(cb):
        return
    cid = int(cb.data.split(":")[1])
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    cfg = await _owned_config_for_user(user["id"], cid)
    if not cfg or not int(cfg.get("is_active") or 0):
        await cb.answer("این سرویس فعال نیست یا برای شما پیدا نشد.", show_alert=True)
        return
    await cb.message.answer(
        "🧬 تبدیل کانفیگ قدیمی به لینک ساب\n\n"
        f"سرویس: {cfg.get('email') or cid}\n\n"
        "با تایید، ربات باقی‌مانده حجم و زمان همین سرویس را به لینک سابسکریپشن جدید منتقل می‌کند. "
        "کانفیگ قبلی روی سرور غیرفعال می‌شود و فقط لینک ساب جدید فعال می‌ماند.",
        reply_markup=config_to_sub_confirm_kb(cid),
        parse_mode=None,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("cfg_to_sub_do:"))
async def cfg_to_sub_do(cb: CallbackQuery):
    if not await _ensure_channel_membership(cb):
        return
    cid = int(cb.data.split(":")[1])
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    cfg = await _owned_config_for_user(user["id"], cid)
    if not cfg or not int(cfg.get("is_active") or 0):
        await cb.answer("این سرویس فعال نیست یا قبلاً تبدیل/غیرفعال شده است.", show_alert=True)
        return
    await cb.answer("در حال تبدیل سرویس...")
    result = await create_profile_from_config(user, cfg)
    if not result.get("ok"):
        await cb.message.answer(
            "❌ تبدیل سرویس به لینک ساب ناموفق بود.\n"
            f"علت: {subscription_error_message(str(result.get('error') or ''))}",
            parse_mode=None,
        )
        return

    sub_url = result["url"]
    qr_label = result.get("email") or cfg.get("email") or "Subscription"
    old_action = "حذف شد" if result.get("old_config_action") == "deleted" else "غیرفعال شد"
    text = (
        "✅ سرویس شما به لینک سابسکریپشن تبدیل شد.\n\n"
        f"سرویس قبلی: {cfg.get('email') or '-'}\n"
        f"حجم باقی‌مانده منتقل‌شده: {fmt_bytes(int(result.get('remaining_bytes') or 0))}\n"
        f"روز باقی‌مانده: {int(result.get('duration_days') or 0)} روز\n"
        f"نودهای فعال: {int(result.get('nodes') or 0)}\n\n"
        f"لینک ساب:\n{sub_url}\n\n"
        f"کانفیگ قبلی {old_action} و از این به بعد فقط همین لینک ساب فعال است."
    )
    await cb.message.answer(text, parse_mode=None, reply_markup=subscription_detail_kb(int(result["profile_id"]), sub_url))
    try:
        await cb.message.answer_photo(_qr_input_file(sub_url, qr_label), caption=f"QR سابسکریپشن: {qr_label}", parse_mode=None)
    except Exception:
        pass


@router.callback_query(F.data.startswith("cfg_del_do:"))
async def cfg_delete_do(cb: CallbackQuery):
    if not await _ensure_channel_membership(cb):
        return
    cid = int(cb.data.split(":")[1])
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    cfg = await _owned_config_for_user(user["id"], cid)
    if not cfg:
        await cb.answer("این سرویس برای شما پیدا نشد.", show_alert=True)
        return

    cli = XUIClient(cfg["server_url"], cfg["srv_user"], cfg["srv_pass"], cfg["sub_path"], cfg.get("srv_api_token", ""))
    try:
        ok = await cli.delete_client(cfg["inbound_id"], cfg["uuid"], cfg.get("email", ""))
    finally:
        await cli.close()

    if not ok:
        await cb.answer("حذف روی سرور ناموفق بود. لطفاً با پشتیبانی هماهنگ کنید.", show_alert=True)
        return

    await delete_config_by_id(cid)
    await cb.message.edit_text("✅ سرویس از سرور و حساب شما حذف شد.", parse_mode=None)
    await cb.answer()


async def _owned_subscription_for_user(user_id: int, profile_id: int) -> dict | None:
    profile = await get_subscription_profile(profile_id)
    if not profile or int(profile.get("user_id") or 0) != int(user_id):
        return None
    return profile


@router.callback_query(F.data.startswith("subnode:"))
async def sub_node_link(cb: CallbackQuery):
    """Send a single server's connection link (for links too long for a copy button)."""
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    try:
        nid = int(cb.data.split(":")[1])
    except (ValueError, IndexError):
        await cb.answer("نامعتبر", show_alert=True)
        return
    node = await get_subscription_node(nid)
    if not node:
        await cb.answer("سرور پیدا نشد.", show_alert=True)
        return
    profile = await get_subscription_profile(int(node.get("profile_id") or 0))
    if not profile or int(profile.get("user_id") or 0) != int(user["id"]):
        await cb.answer("این سرور برای شما نیست.", show_alert=True)
        return
    link = (node.get("link") or "").strip()
    if not link:
        await cb.answer("لینک این سرور هنوز آماده نیست.", show_alert=True)
        return
    remark = str(node.get("node_label") or node.get("server_name") or "سرور")
    await cb.message.answer(f"📍 {remark}\n\n`{link}`", parse_mode="Markdown")
    await cb.answer("لینک ارسال شد ⬇️")


@router.callback_query(F.data.startswith("sub_show:"))
async def sub_show(cb: CallbackQuery):
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    pid = int(cb.data.split(":")[1])
    profile = await _owned_subscription_for_user(user["id"], pid)
    if not profile:
        await cb.answer("این ساب برای شما پیدا نشد.", show_alert=True)
        return
    await _send_subscription_status(cb, profile)
    await cb.answer()


@router.callback_query(F.data.startswith("sub_rename:"))
async def sub_rename_start(cb: CallbackQuery, state: FSMContext):
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    pid = int(cb.data.split(":")[1])
    profile = await _owned_subscription_for_user(user["id"], pid)
    if not profile:
        await cb.answer("این ساب برای شما پیدا نشد.", show_alert=True)
        return
    await state.set_state(RenameSub.name)
    await state.update_data(pid=pid)
    cur = (profile.get("name") or "").strip() or "—"
    await cb.message.answer(
        "✏️ یک نام دلخواه برای این سرویس بفرست تا توی لیست سرویس‌ها و داخل برنامه (Remark هر سرور) نمایش داده شود.\n\n"
        f"نام فعلی: {cur}\n"
        "فقط حرف، عدد، فاصله، خط تیره و آندرلاین. برای حذف نام، `-` بفرست.",
        parse_mode="Markdown",
        reply_markup=flow_cancel_kb(),
    )
    await cb.answer()


@router.message(RenameSub.name)
async def sub_rename_apply(msg: Message, state: FSMContext):
    raw = (msg.text or "").strip()
    if raw.split()[0].split("@", 1)[0].lower() == "/cancel" if raw else False:
        await state.clear()
        await msg.answer("❌ لغو شد.")
        return
    data = await state.get_data()
    await state.clear()
    pid = int(data.get("pid") or 0)
    user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
    profile = await _owned_subscription_for_user(user["id"], pid)
    if not profile:
        await msg.answer("این ساب برای شما پیدا نشد.")
        return
    new_name = "" if raw == "-" else _safe_user_config_name(raw)
    if raw != "-" and not new_name:
        await msg.answer("❌ نام نامعتبر است. فقط حرف، عدد، فاصله، خط تیره و آندرلاین مجاز است.")
        return
    await update_subscription_profile(pid, name=new_name)
    profile["name"] = new_name
    shown = new_name or "(بدون نام)"
    await msg.answer(
        f"✅ نام سرویس به «{shown}» تغییر کرد.\n"
        "برای دیدن نام جدید، در برنامه‌ات لینک ساب را یک‌بار آپدیت کن.",
        parse_mode=None,
    )
    await _send_subscription_status(msg, profile)


@router.callback_query(F.data.startswith("sub_del:"))
async def sub_delete_confirm(cb: CallbackQuery):
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    pid = int(cb.data.split(":")[1])
    profile = await _owned_subscription_for_user(user["id"], pid)
    if not profile:
        await cb.answer("این ساب برای شما پیدا نشد.", show_alert=True)
        return
    await cb.message.answer(
        "🗑️ حذف سابسکریپشن\n\n"
        f"شناسه سرویس: {profile.get('email') or profile.get('token')}\n\n"
        "با تایید، همه نودهای این ساب از سرورها و از حساب شما حذف می‌شود.",
        reply_markup=subscription_delete_confirm_kb(pid),
        parse_mode=None,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sub_del_do:"))
async def sub_delete_do(cb: CallbackQuery):
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    pid = int(cb.data.split(":")[1])
    profile = await _owned_subscription_for_user(user["id"], pid)
    if not profile:
        await cb.answer("این ساب برای شما پیدا نشد.", show_alert=True)
        return
    result = await delete_subscription_profile_remote(pid)
    await cb.message.edit_text(
        f"✅ سابسکریپشن حذف شد.\nنودهای حذف‌شده: {result.get('deleted', 0)} | خطا: {result.get('failed', 0)}",
        parse_mode=None,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sub_renew:"))
async def sub_renew_same(cb: CallbackQuery):
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    pid = int(cb.data.split(":")[1])
    profile = await _owned_subscription_for_user(user["id"], pid)
    if not profile:
        await cb.answer("این ساب برای شما پیدا نشد.", show_alert=True)
        return
    traffic_gb = float(profile.get("traffic_gb") or 0)
    duration_days = max(int(profile.get("duration_days") or 0), RENEWAL_MIN_DAYS)
    price = await _calc_renew_price(user["id"], traffic_gb, duration_days)
    oid = await create_custom_order(
        user["id"],
        f"تمدید ساب {profile.get('email') or pid}",
        traffic_gb,
        duration_days,
        price,
        notes=f"renew_sub:{pid};renew_traffic:{traffic_gb:g};renew_days:{duration_days}",
    )
    await update_order(oid, renew_sub_profile_id=pid)
    text = await _payment_text(oid, "تمدید سابسکریپشن چندسروره", traffic_gb, duration_days, price)
    text += "\n\nبعد از تایید، همین لینک ساب با حجم و مدت جدید تمدید می‌شود و مصرف آن ریست می‌شود."
    await cb.message.answer(text, reply_markup=payment_kb(oid), parse_mode="Markdown")
    await cb.answer()


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

    await cb.message.answer(
        "♻️ *تمدید سرویس*\n\n"
        f"کانفیگ: `{cfg['email']}`\n"
        f"حجم فعلی: `{cfg.get('traffic_gb') or 0} GB`\n"
        f"مدت فعلی: `{cfg.get('duration_days') or 0} روز`\n\n"
        "می‌توانید با همین مشخصات تمدید کنید یا حجم و مدت جدید انتخاب کنید.",
        reply_markup=renew_options_kb(cid),
        parse_mode="Markdown",
    )
    await cb.answer()


async def _create_renew_order(cb_or_msg, user: dict, cfg: dict, traffic_gb: float, duration_days: int):
    min_traffic = await _renewal_min_traffic()
    if traffic_gb < min_traffic:
        if isinstance(cb_or_msg, CallbackQuery):
            await cb_or_msg.answer(f"حداقل حجم تمدید {min_traffic:g} GB است.", show_alert=True)
        else:
            await cb_or_msg.answer(f"❌ حداقل حجم تمدید `{min_traffic:g} GB` است.", parse_mode="Markdown")
        return
    if int(duration_days or 0) < RENEWAL_MIN_DAYS:
        if isinstance(cb_or_msg, CallbackQuery):
            await cb_or_msg.answer(f"حداقل مدت تمدید {RENEWAL_MIN_DAYS} روز است.", show_alert=True)
        else:
            await cb_or_msg.answer(f"❌ حداقل مدت تمدید `{RENEWAL_MIN_DAYS}` روز است.", parse_mode="Markdown")
        return

    price = await _calc_renew_price(user["id"], traffic_gb, duration_days)
    oid = await create_custom_order(
        user["id"],
        f"تمدید {cfg['email']}",
        traffic_gb,
        int(duration_days),
        price,
        notes=f"renew_config:{cfg['id']};renew_traffic:{traffic_gb:g};renew_days:{int(duration_days)}",
    )
    await update_order(oid, renew_config_id=cfg["id"])
    text = await _payment_text(oid, f"تمدید سرویس {cfg['email']}", traffic_gb, int(duration_days), price)
    text += "\n\nبعد از تأیید، همین کانفیگ با حجم و مدت انتخابی تمدید می‌شود و مصرف آن ریست می‌شود."
    if isinstance(cb_or_msg, CallbackQuery):
        await cb_or_msg.message.answer(text, reply_markup=payment_kb(oid), parse_mode="Markdown")
        await cb_or_msg.answer()
    else:
        await cb_or_msg.answer(text, reply_markup=payment_kb(oid), parse_mode="Markdown")


@router.callback_query(F.data.startswith("renew_same:"))
async def renew_same_config(cb: CallbackQuery):
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
    await _create_renew_order(cb, user, cfg, traffic_gb, max(duration_days, RENEWAL_MIN_DAYS))


@router.callback_query(F.data.startswith("renew_custom:"))
async def renew_custom_start(cb: CallbackQuery, state: FSMContext):
    if not await _ensure_channel_membership(cb):
        return
    cid = int(cb.data.split(":")[1])
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    cfg = await get_config(cid)
    if not cfg or int(cfg.get("user_id") or 0) != int(user["id"]):
        await cb.answer("این سرویس برای شما پیدا نشد.", show_alert=True)
        return
    min_traffic = await _renewal_min_traffic()
    await state.set_state(RenewService.traffic)
    await state.update_data(config_id=cid)
    await cb.message.answer(
        f"📊 حجم جدید تمدید را به GB وارد کنید.\nحداقل: `{min_traffic:g} GB`\nمثال: `20`",
        reply_markup=flow_cancel_kb(),
        parse_mode="Markdown",
    )
    await cb.answer()


@router.message(RenewService.traffic)
async def renew_custom_traffic(msg: Message, state: FSMContext):
    try:
        traffic_gb = float((msg.text or "").strip().replace(",", "."))
    except ValueError:
        await msg.answer("❌ حجم را به عدد وارد کنید. مثال: `20`", reply_markup=flow_cancel_kb(), parse_mode="Markdown")
        return
    min_traffic = await _renewal_min_traffic()
    if traffic_gb < min_traffic:
        await msg.answer(f"❌ حداقل حجم تمدید `{min_traffic:g} GB` است.", reply_markup=flow_cancel_kb(), parse_mode="Markdown")
        return
    await state.update_data(traffic_gb=traffic_gb)
    await state.set_state(RenewService.duration)
    await msg.answer(
        f"📅 مدت تمدید را به روز وارد کنید.\nحداقل: `{RENEWAL_MIN_DAYS}` روز\nمثال: `30`",
        reply_markup=flow_cancel_kb(),
        parse_mode="Markdown",
    )


@router.message(RenewService.duration)
async def renew_custom_duration(msg: Message, state: FSMContext):
    try:
        duration_days = int((msg.text or "").strip())
    except ValueError:
        await msg.answer("❌ مدت را به عدد روز وارد کنید. مثال: `30`", reply_markup=flow_cancel_kb(), parse_mode="Markdown")
        return
    if duration_days < RENEWAL_MIN_DAYS:
        await msg.answer(f"❌ حداقل مدت تمدید `{RENEWAL_MIN_DAYS}` روز است.", reply_markup=flow_cancel_kb(), parse_mode="Markdown")
        return
    data = await state.get_data()
    await state.clear()
    user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
    cfg = await get_config(int(data.get("config_id") or 0))
    if not cfg or int(cfg.get("user_id") or 0) != int(user["id"]):
        await msg.answer("❌ سرویس برای تمدید پیدا نشد.")
        return
    await _create_renew_order(msg, user, cfg, float(data.get("traffic_gb") or 0), duration_days)


@router.callback_query(F.data.startswith("cfg_link:"))
async def send_config_link(cb: CallbackQuery):
    if not await _ensure_channel_membership(cb):
        return
    cid = int(cb.data.split(":")[1])
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    if not await _owned_config_for_user(user["id"], cid):
        await cb.answer("این سرویس برای شما پیدا نشد.", show_alert=True)
        return
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
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    if not await _owned_config_for_user(user["id"], cid):
        await cb.answer("این سرویس برای شما پیدا نشد.", show_alert=True)
        return
    await _send_config_status(cb, cid)
    await cb.answer("بروزرسانی شد")


@router.callback_query(F.data.startswith("cfg_sub:"))
async def cfg_sub(cb: CallbackQuery):
    if not await _ensure_channel_membership(cb):
        return
    cid = int(cb.data.split(":")[1])
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    if not await _owned_config_for_user(user["id"], cid):
        await cb.answer("این سرویس برای شما پیدا نشد.", show_alert=True)
        return
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
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    if not await _owned_config_for_user(user["id"], cid):
        await cb.answer("این سرویس برای شما پیدا نشد.", show_alert=True)
        return
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


@router.message(F.text == "🧪 دریافت اکانت تست")
async def test_account(msg: Message):
    if not await _ensure_channel_membership(msg):
        return
    if await _blocked(msg.from_user.id):
        await msg.answer(await get_text("blocked_message"))
        return

    settings = await _test_account_settings()
    if not settings["enabled"]:
        await msg.answer("⛔ اکانت تست فعلاً غیرفعال است.")
        return

    user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
    existing = await get_user_test_account(user["id"])
    if existing:
        if existing.get("kind") == "sub" and existing.get("profile"):
            await msg.answer("🧪 اکانت تست شما قبلاً ساخته شده است:", parse_mode=None)
            await _send_subscription_status(msg, existing["profile"], send_qr=True)
            return
        # A trial was already issued before (legacy single config, or it has since
        # been removed). Don't hand out another one.
        await msg.answer(
            "🧪 شما قبلاً اکانت تست دریافت کرده‌اید.\n"
            "برای ادامه می‌توانید از بخش «🛒 خرید سرویس» یک سرویس کامل تهیه کنید.",
            parse_mode=None,
        )
        return

    result = await create_test_subscription(user, settings["traffic_gb"], settings["duration_days"])
    if not result.get("ok"):
        err = subscription_error_message(result.get("error", ""))
        await msg.answer(
            "❌ ساخت اکانت تست ناموفق بود.\n\n"
            f"علت: {err}\n\n"
            "لطفاً کمی بعد دوباره تلاش کنید یا با پشتیبانی در ارتباط باشید.",
            parse_mode=None,
        )
        return

    await add_user_test_account(user["id"], profile_id=int(result["profile_id"]))
    await msg.answer(
        "✅ اکانت تست چندسروره شما ساخته شد.\n"
        f"حجم: {settings['traffic_gb']} GB | مدت: {settings['duration_days']} روز | سرورها: {result.get('nodes', 0)}",
        parse_mode=None,
    )
    profile = await get_subscription_profile(int(result["profile_id"]))
    if profile:
        await _send_subscription_status(msg, profile, send_qr=True)


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
        reply_markup=custom_name_kb(),
    )
    await cb.answer()


async def _finalize_buy_payment(from_user, state: FSMContext):
    data = await state.get_data()
    pid = int(data.get("package_id") or 0)
    pkg = await get_package(pid)
    if not pkg or not pkg["is_active"]:
        await state.clear()
        return None, "❌ این پکیج دیگر در دسترس نیست."

    user = await get_or_create_user(from_user.id, from_user.username, from_user.full_name)
    final_price, base_price, discount, price_per_gb = await _calc_package_price_for_user(user["id"], pkg)
    custom_name = data.get("custom_name") or ""

    # Re-validate the discount code against the live price right before creating
    # the order (guards against price/limit changes mid-flow).
    code = (data.get("discount_code") or "").strip()
    code_amount = int(data.get("discount_amount") or 0)
    if code:
        v = await validate_discount_code(code, user["id"], pid, final_price)
        code_amount = int(v.get("discount_amount") or 0) if v.get("ok") else 0
        if not v.get("ok"):
            code = ""
    net_price = max(0, final_price - code_amount)

    oid = await create_order(user["id"], pid, custom_config_name=custom_name, custom_price=net_price)
    if code and code_amount > 0:
        await update_order(oid, discount_code=code, discount_amount=code_amount)

    text = await _payment_text(oid, pkg["name"], pkg["traffic_gb"], pkg["duration_days"], net_price)
    if price_per_gb > 0 or discount > 0 or code_amount > 0:
        text += f"\n\nقیمت پایه: `{_fmt_toman(base_price)}` تومان"
        if price_per_gb > 0:
            text += f"\nقیمت اختصاصی هر GB: `{_fmt_toman(price_per_gb)}` تومان"
        if discount > 0:
            text += f"\nتخفیف شما: `{discount:g}%`"
        if code_amount > 0:
            text += f"\n🎟️ کد تخفیف `{code}`: `{_fmt_toman(code_amount)}-` تومان"
            text += f"\n💳 مبلغ نهایی: *{_fmt_toman(net_price)}* تومان"
    if custom_name:
        text += f"\n\nنام دلخواه انتهای کانفیگ: `{custom_name}`"
    await state.clear()
    return (oid, text), None


@router.callback_query(StateFilter(BuyService.custom_name), F.data == "buy_name_default")
async def buy_default_name(cb: CallbackQuery, state: FSMContext):
    await _go_to_discount_step(cb.message.answer, cb.from_user, state, "")
    await cb.answer("با نام پیش‌فرض ادامه داده شد.")


@router.message(BuyService.custom_name)
async def buy_custom_name(msg: Message, state: FSMContext):
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
    await _go_to_discount_step(msg.answer, msg.from_user, state, custom_name)


async def _go_to_discount_step(send, from_user, state: FSMContext, custom_name: str):
    """After the name step, optionally ask for a discount code, else finalize."""
    await state.update_data(custom_name=custom_name, discount_code="", discount_amount=0)
    if await get_setting("discount_enabled", "1") != "1":
        await _emit_buy_payment(send, from_user, state)
        return
    await state.set_state(BuyDiscount.code)
    await send(
        "🎟️ اگر کد تخفیف دارید همینجا بفرستید.\n\nاگر ندارید، روی «بدون کد تخفیف» بزنید.",
        reply_markup=discount_skip_kb(),
    )


def _discount_error_text(v: dict) -> str:
    return {
        "not_found": "❌ کد تخفیف نامعتبر است.",
        "inactive": "❌ این کد تخفیف غیرفعال است.",
        "expired": "❌ مهلت استفاده از این کد تمام شده است.",
        "exhausted": "❌ ظرفیت استفاده از این کد پر شده است.",
        "wrong_package": "❌ این کد برای این پکیج معتبر نیست.",
        "min_amount": f"❌ این کد فقط برای سفارش‌های بالای {_fmt_toman(int(v.get('min_amount') or 0))} تومان است.",
        "user_limit": "❌ شما قبلاً از این کد استفاده کرده‌اید.",
        "zero_discount": "❌ این کد برای این سفارش تخفیفی ندارد.",
    }.get(v.get("error"), "❌ کد تخفیف معتبر نیست.")


@router.callback_query(StateFilter(BuyDiscount.code), F.data == "buy_disc_skip")
async def buy_discount_skip(cb: CallbackQuery, state: FSMContext):
    await state.update_data(discount_code="", discount_amount=0)
    await _emit_buy_payment(cb.message.answer, cb.from_user, state)
    await cb.answer()


@router.message(BuyDiscount.code)
async def buy_discount_code(msg: Message, state: FSMContext):
    raw = (msg.text or "").strip()
    low = raw.split()[0].split("@", 1)[0].lower() if raw else ""
    if low == "/cancel":
        await state.clear()
        await msg.answer("❌ عملیات لغو شد.")
        return
    if low == "/skip" or raw == "-":
        await state.update_data(discount_code="", discount_amount=0)
        await _emit_buy_payment(msg.answer, msg.from_user, state)
        return

    data = await state.get_data()
    pid = int(data.get("package_id") or 0)
    pkg = await get_package(pid)
    if not pkg or not pkg["is_active"]:
        await state.clear()
        await msg.answer("❌ این پکیج دیگر در دسترس نیست.")
        return
    user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
    final_price, *_ = await _calc_package_price_for_user(user["id"], pkg)
    v = await validate_discount_code(raw, user["id"], pid, final_price)
    if not v.get("ok"):
        await msg.answer(
            _discount_error_text(v) + "\n\nکد دیگری بفرستید یا «بدون کد تخفیف» را بزنید.",
            reply_markup=discount_skip_kb(),
        )
        return
    await state.update_data(discount_code=v["code"], discount_amount=int(v["discount_amount"]))
    await msg.answer(f"✅ کد «{v['code']}» اعمال شد — {_fmt_toman(int(v['discount_amount']))} تومان تخفیف.")
    await _emit_buy_payment(msg.answer, msg.from_user, state)


async def _emit_buy_payment(send, from_user, state: FSMContext):
    result, error = await _finalize_buy_payment(from_user, state)
    if error:
        await send(error)
        return
    oid, text = result
    await send(text, reply_markup=payment_kb(oid), parse_mode="Markdown")


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
    elif int(order.get("renew_sub_profile_id") or 0) > 0:
        profile = await get_subscription_profile(int(order["renew_sub_profile_id"]))
        if not profile:
            await add_user_balance(user["id"], price, kind="refund", note=f"sub_renew_failed:{oid}", actor_telegram_id=0)
            await update_order(oid, status="pending_payment")
            await cb.message.answer("سابسکریپشن برای تمدید پیدا نشد و مبلغ به کیف پول شما برگشت داده شد.")
            return
        server_id = 0
    else:
        servers = [sv for sv in await get_available_servers()]
        if not servers:
            await cb.message.answer("پرداخت انجام شد، اما سرور فعالی برای ساخت کانفیگ پیدا نشد. سفارش برای بررسی ادمین ارسال شد.")
            return

        server = None
        if await get_setting("auto_least_loaded_server", "0") == "1":
            server = await get_least_loaded_server()
        if not server:
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


@router.message(StateFilter(None), lambda msg: bool(msg.text and _extract_subscription_token(msg.text or "")))
async def user_subscription_link_lookup(msg: Message):
    if not await _ensure_channel_membership(msg):
        return
    if await _blocked(msg.from_user.id):
        await msg.answer(await get_text("blocked_message"))
        return

    token = _extract_subscription_token(msg.text or "")
    profile = await get_subscription_profile_by_token(token) if token else None
    user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
    if profile and int(profile.get("user_id") or 0) == int(user["id"]):
        await _send_subscription_status(msg, profile, send_qr=False)
        return

    if profile:
        await msg.answer(
            "❌ این لینک سابسکریپشن داخل حساب شما ثبت نشده است.\n"
            "اگر فکر می‌کنید اشتباه شده، با پشتیبانی پیام دهید.",
            parse_mode=None,
        )
        return

    await msg.answer("❌ این لینک سابسکریپشن داخل ربات پیدا نشد.", parse_mode=None)


@router.message(StateFilter(None), lambda msg: bool(msg.text and _extract_config_identity(msg.text or "")[0]))
async def user_config_link_lookup(msg: Message):
    if not await _ensure_channel_membership(msg):
        return
    if await _blocked(msg.from_user.id):
        await msg.answer(await get_text("blocked_message"))
        return

    _, email, raw_uuid = _extract_config_identity(msg.text or "")
    user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
    cfg = await get_config_by_email(email) if email else None
    if not cfg and raw_uuid:
        cfg = await get_config_by_uuid(raw_uuid)

    if cfg and int(cfg.get("user_id") or 0) == int(user["id"]):
        await msg.answer("🔎 کانفیگ شما پیدا شد. وضعیت سرویس:")
        await _send_config_status(msg, int(cfg["id"]))
        return

    if cfg:
        await msg.answer(
            "❌ این کانفیگ داخل حساب شما ثبت نشده است.\n"
            "اگر فکر می‌کنید اشتباه شده، با پشتیبانی پیام دهید.",
            parse_mode=None,
        )
        return

    await msg.answer(
        "❌ این کانفیگ داخل حساب شما پیدا نشد.\n\n"
        "اگر این سرویس را قبلاً خارج از ربات گرفته‌اید، از گزینه «🔗 سینک کانفیگ قبلی» استفاده کنید.",
        parse_mode=None,
    )


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
            existing = await get_config_by_email(email) if email else None
            if not existing and raw_uuid:
                existing = await get_config_by_uuid(raw_uuid)
            if existing:
                await msg.answer("⚠️ این کانفیگ قبلاً تایید و ثبت شده است و درخواست تکراری پذیرفته نمی‌شود.")
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
                    admin_note="retry_after_missing_config",
                    reviewed_at=None,
                    reviewer_id=0,
                )
                await _notify_legacy_claim_admins(msg.bot, dup["id"], msg.from_user, email)
                await state.clear()
                await msg.answer("✅ درخواست قبلی دوباره برای بررسی ادمین ارسال شد.")
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


@router.message(F.text == "🕊️ پیام ناشناس")
async def anonymous_feedback_start(msg: Message, state: FSMContext):
    if not await _ensure_channel_membership(msg):
        return
    if await _blocked(msg.from_user.id):
        await msg.answer(await get_text("blocked_message"))
        return
    await state.set_state(AnonymousFeedback.text)
    await msg.answer(
        "🕊️ متن پیشنهاد یا انتقاد خودتان را بنویسید.\n\n"
        "پیام بدون نام، یوزرنیم و آیدی شما برای مدیریت ارسال می‌شود.",
        reply_markup=flow_cancel_kb(show_back=False),
        parse_mode=None,
    )


@router.message(AnonymousFeedback.text)
async def anonymous_feedback_submit(msg: Message, state: FSMContext):
    text = (msg.text or msg.caption or "").strip()
    if not text:
        await msg.answer("❌ لطفاً متن پیام را ارسال کنید.", reply_markup=flow_cancel_kb(show_back=False))
        return
    if len(text) > 3500:
        await msg.answer("❌ متن خیلی طولانی است. لطفاً کوتاه‌تر ارسال کنید.", reply_markup=flow_cancel_kb(show_back=False))
        return

    await state.clear()
    sent = 0
    for aid in await _admin_targets():
        try:
            await msg.bot.send_message(
                aid,
                "🕊️ پیام ناشناس جدید\n\n"
                f"{text}",
                parse_mode=None,
            )
            sent += 1
        except Exception:
            pass
    if sent:
        await msg.answer("✅ پیام ناشناس شما برای مدیریت ارسال شد. ممنون از بازخوردتان.", parse_mode=None)
    else:
        await msg.answer("⚠️ ارسال پیام به مدیریت ناموفق بود. لطفاً کمی بعد دوباره تلاش کنید.", parse_mode=None)


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
    limit = await _migration_limit()

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    b = InlineKeyboardBuilder()
    for c in configs:
        b.button(text=f" {c['email']} — {c['server_name']}", callback_data=f"mig_start:{c['id']}")
    b.adjust(1)

    await msg.answer(
        f" *انتقال سرور*\n\n"
        f"کدام سرویس را می‌خواهید منتقل کنید؟\n"
        f"⚠️ محدودیت: {limit} بار در روز",
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

    limit = await _migration_limit()
    today_cnt = await get_user_migration_count_today(user["id"])
    if today_cnt >= limit:
        await cb.answer(
            f"⛔ امروز {limit} بار انتقال انجام دادید!\nفردا دوباره امتحان کنید.",
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
    suggested = None
    if await get_setting("auto_least_loaded_server", "0") == "1":
        suggested = await get_least_loaded_server(exclude_ids=[int(cfg["server_id"])])
        if suggested:
            others = sorted(others, key=lambda s: 0 if int(s["id"]) == int(suggested["id"]) else 1)
    kb = InlineKeyboardBuilder()
    for s in others:
        cap = int(s.get("max_active_configs") or 0)
        label = f"🖥️ {s['name']}"
        if suggested and int(s["id"]) == int(suggested["id"]):
            label += " — ⭐ سرور پیشنهادی"
        if cap > 0:
            used = await count_active_configs_by_server(s["id"])
            if used >= cap:
                label += " — ⛔ ظرفیت پر شده"
        kb.button(text=label, callback_data=f"mig_confirm:{s['id']}:{cid}")
    kb.adjust(1)

    remaining = limit - today_cnt
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

    limit = await _migration_limit()
    today_cnt = await get_user_migration_count_today(user["id"])
    if today_cnt >= limit:
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
    if await get_setting("referral_enabled", "1") != "1":
        await msg.answer("🎁 سیستم دعوت دوستان فعلاً غیرفعال است.")
        return

    from core.rewards import referral_tier_reward_text

    user = await get_or_create_user(msg.from_user.id)
    stats = await get_referral_stats(user["id"])
    code = user.get("referral_code", "—")
    bot_info = await msg.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={code}"
    brand = await get_setting("ui.brand_name", "Atlas Account")

    converted = await count_converted_referrals(user["id"])
    tiers = await get_referral_tiers(active_only=True)
    tier_lines = []
    for t in tiers:
        need = int(t.get("referrals_needed") or 0)
        mark = "✅" if converted >= need else f"⏳ {converted}/{need}"
        tier_lines.append(f"{mark} {need} معرفی → {referral_tier_reward_text(t)}")

    info = (
        "🎁 *دعوت دوستان*\n"
        "━━━━━━━━━━━━━━\n"
        f"👥 دعوت‌شدگان: `{stats['invited']}` | 🛒 خریداران: `{stats['converted']}`\n"
        f"💎 اعتبار هدیه: `{stats['bonus_gb']} GB`\n"
    )
    if tier_lines:
        info += "\n🏆 *پله‌های هدیه:*\n" + "\n".join(tier_lines) + "\n"
        info += "\n_هدایا پس از رسیدن به هر پله و تأیید پشتیبانی فعال می‌شوند._\n"
    info += f"\n🔗 *لینک اختصاصی شما:*\n`{ref_link}`\n\n👇 پیام زیر را برای دوستانتان فوروارد کنید:"
    await msg.answer(info, parse_mode="Markdown")

    # The forwardable banner + caption (customizable from the panel).
    caption_tpl = await get_setting(
        "referral_caption",
        "🎁 با لینک اختصاصی من به {brand} بپیوند!\n\n👇 برای شروع:\n{link}",
    )
    try:
        share_text = caption_tpl.format(brand=brand, link=ref_link)
    except Exception:
        share_text = f"{caption_tpl}\n{ref_link}"
    banner = (await get_setting("referral_banner_file_id", "")).strip() or (await get_setting("referral_banner_url", "")).strip()
    if banner:
        try:
            await msg.answer_photo(banner, caption=share_text, parse_mode=None)
            return
        except Exception:
            pass
    await msg.answer(share_text, parse_mode=None)


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
