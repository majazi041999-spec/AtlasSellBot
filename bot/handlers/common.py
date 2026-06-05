from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext

from core.config import ADMIN_IDS, WEB_SECRET_PATH, WEB_PORT, REFERRAL_BONUS_GB
from core.database import get_or_create_user, get_user_by_referral_code, update_user, get_setting
from core.texts import get_text
from bot.middlewares.channel_required import ChannelRequiredMiddleware

router = Router()


async def _admin_role(uid: int, user: dict) -> str:
    owner_id = int(await get_setting("owner_admin_id", "0") or 0)
    if uid in ADMIN_IDS or (owner_id and uid == owner_id):
        return "owner"
    if not user.get("is_admin", 0):
        return "none"
    role = (user.get("admin_role") or "full").strip().lower()
    return role if role in {"full", "finance"} else "full"


async def _menus(msg: Message):
    user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
    role = await _admin_role(msg.from_user.id, user)
    return user, role


def _channel_join_kb(channel_username: str):
    return ChannelRequiredMiddleware.join_kb(channel_username)


@router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    from bot.keyboards import admin_menu, user_menu

    args = msg.text.split()
    ref_code = args[1] if len(args) > 1 else None

    user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
    role = await _admin_role(msg.from_user.id, user)

    # رجیستر referral (اگر قبلاً کسی دعوتش نکرده)
    if ref_code and not user.get("referred_by") and ref_code != user.get("referral_code"):
        referrer = await get_user_by_referral_code(ref_code)
        if referrer and referrer["id"] != user["id"]:
            await update_user(user["id"], referred_by=referrer["id"])
            try:
                from aiogram import Bot
                await msg.bot.send_message(
                    referrer["telegram_id"],
                    f"🎉 *یک دوست جدید با لینک دعوت شما ثبت‌نام کرد!*\n\n"
                    f"👤 {msg.from_user.full_name or 'کاربر جدید'}\n\n"
                    f"هنگامی که اولین خریدش را انجام دهد، شما {REFERRAL_BONUS_GB} GB هدیه دریافت می‌کنید 🎁",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    maintenance = await get_setting("maintenance_mode", "0")
    if maintenance == "1" and role == "none":
        await msg.answer(await get_text("maintenance_message"))
        return

    welcome = await get_text("welcome_message")
    text = f"{'🔐 *پنل مدیریت*' if role != 'none' else '🌐 *Atlas Account*'}\n\n{welcome}"

    kb = admin_menu(finance_only=(role == 'finance')) if role != 'none' else user_menu(include_wholesale=bool(user.get("is_wholesale", 0)))
    await msg.answer(text, reply_markup=kb, parse_mode="Markdown")




@router.message(F.text.regexp(r"^/cancel(?:@\w+)?(?:\s|$)"))
async def cancel_cmd(msg: Message, state: FSMContext):
    await state.clear()
    user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
    role = await _admin_role(msg.from_user.id, user)
    from bot.keyboards import admin_menu, user_menu
    kb = admin_menu(finance_only=(role == "finance")) if role != "none" else user_menu(include_wholesale=bool(user.get("is_wholesale", 0)))
    await msg.answer("❌ عملیات لغو شد.", reply_markup=kb)

@router.message(F.text.regexp(r"^/"))
async def block_non_member_commands(msg: Message):
    """Prevent using any slash command (except /start*) when force_channel is enabled."""
    if not msg.text:
        return

    cmd = msg.text.strip().split()[0].split("@", 1)[0].lower()
    if cmd.startswith("/start"):
        return
    required, channel_username = await ChannelRequiredMiddleware.is_required()
    if not required:
        return

    if await ChannelRequiredMiddleware.can_access(msg.bot, msg.from_user.id, channel_username):
        return

    ch = ChannelRequiredMiddleware._channel_ref(channel_username) or "لینک عضویت"
    await msg.answer(
        f"❌ برای استفاده از ربات باید حتما عضو کانال باشید.\n\nکانال: {ch}",
        reply_markup=_channel_join_kb(channel_username),
    )


@router.callback_query(F.data == "cancel")
async def cancel_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await cb.message.edit_text("❌ عملیات لغو شد.")
    except Exception:
        await cb.message.answer("❌ عملیات لغو شد.")
    await cb.answer()


@router.callback_query(F.data == "back_to_menu")
async def back_menu_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    from bot.keyboards import admin_menu, user_menu

    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    role = await _admin_role(cb.from_user.id, user)
    kb = admin_menu(finance_only=(role == "finance")) if role != "none" else user_menu(include_wholesale=bool(user.get("is_wholesale", 0)))
    try:
        await cb.message.edit_text("🏠 برگشت به منوی اصلی")
    except Exception:
        pass
    await cb.message.answer("منوی اصلی", reply_markup=kb)
    await cb.answer()




@router.message(F.text == "🔄 شروع مجدد")
async def restart_menu(msg: Message, state: FSMContext):
    await state.clear()
    from bot.keyboards import admin_menu, user_menu
    user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
    role = await _admin_role(msg.from_user.id, user)
    kb = admin_menu(finance_only=(role == "finance")) if role != "none" else user_menu(include_wholesale=bool(user.get("is_wholesale", 0)))
    await msg.answer("✅ ربات برای شما بروزرسانی شد و منو دوباره بارگذاری شد.", reply_markup=kb)

@router.message(F.text == "🌐 پنل مدیریت")
async def panel_url(msg: Message):
    user = await get_or_create_user(msg.from_user.id)
    role = await _admin_role(msg.from_user.id, user)
    if role not in ("owner", "full"):
        return
    panel_help = await get_text("panel_url_help", port=WEB_PORT, secret=WEB_SECRET_PATH)
    await msg.answer(panel_help, parse_mode="Markdown")
