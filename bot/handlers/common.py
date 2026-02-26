from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.config import ADMIN_IDS, WEB_SECRET_PATH, WEB_PORT
from core.database import get_or_create_user, get_user_by_referral_code, update_user, get_setting
from core.texts import get_text

router = Router()


def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


async def _menus(msg: Message):
    from bot.keyboards import admin_menu, user_menu
    user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
    is_adm = _is_admin(msg.from_user.id) or user.get("is_admin", 0)
    return user, is_adm


def _channel_join_kb(channel_username: str):
    ch = channel_username.strip().lstrip("@")
    b = InlineKeyboardBuilder()
    b.button(text="📢 عضویت در کانال", url=f"https://t.me/{ch}")
    return b.as_markup()


@router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    from bot.keyboards import admin_menu, user_menu

    args = msg.text.split()
    ref_code = args[1] if len(args) > 1 else None

    user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
    is_adm = _is_admin(msg.from_user.id) or user.get("is_admin", 0)

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
                    f"هنگامی که اولین خریدش را انجام دهد، شما {5} GB هدیه دریافت می‌کنید 🎁",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    maintenance = await get_setting("maintenance_mode", "0")
    if maintenance == "1" and not is_adm:
        await msg.answer(await get_text("maintenance_message"))
        return

    welcome = await get_text("welcome_message")
    text = f"{'🔐 *پنل مدیریت*' if is_adm else '🌐 *Atlas Account*'}\n\n{welcome}"

    kb = admin_menu() if is_adm else user_menu(include_wholesale=bool(user.get("is_wholesale", 0)))
    await msg.answer(text, reply_markup=kb, parse_mode="Markdown")


@router.message(F.text.regexp(r"^/"))
async def block_non_member_commands(msg: Message):
    """Prevent using any slash command (except /start*) when force_channel is enabled."""
    if not msg.text:
        return

    cmd = msg.text.strip().split()[0].split("@", 1)[0].lower()
    if cmd.startswith("/start"):
        return
    force = await get_setting("force_channel", "0")
    channel_username = await get_setting("channel_username", "")
    if force != "1" or not channel_username:
        return

    ch = channel_username if channel_username.startswith("@") else f"@{channel_username}"
    try:
        member = await msg.bot.get_chat_member(ch, msg.from_user.id)
        if member.status in ("member", "administrator", "creator"):
            return
    except Exception:
        pass

    await msg.answer(
        f"❌ برای استفاده از ربات باید حتما عضو کانال باشید.\n\nکانال: {ch}",
        reply_markup=_channel_join_kb(channel_username),
    )


@router.callback_query(F.data == "cancel")
async def cancel_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("❌ عملیات لغو شد.")
    await cb.answer()


@router.callback_query(F.data == "back_to_menu")
async def back_menu_cb(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    await cb.message.delete()


@router.message(F.text == "🌐 پنل مدیریت")
async def panel_url(msg: Message):
    user = await get_or_create_user(msg.from_user.id)
    if not (_is_admin(msg.from_user.id) or user.get("is_admin")):
        return
    panel_help = await get_text("panel_url_help", port=WEB_PORT, secret=WEB_SECRET_PATH)
    await msg.answer(panel_help, parse_mode="Markdown")
