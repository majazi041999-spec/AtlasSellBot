from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext

from core.config import ADMIN_IDS, WEB_SECRET_PATH, WEB_PORT, REFERRAL_BONUS_GB
from core.database import get_or_create_user, get_user_by_referral_code, update_user, get_setting
from core.texts import get_text
from bot.middlewares.channel_required import ChannelRequiredMiddleware

router = Router()


BRAND = "اطلس اکانت"
# What owner-written text may call us. Every spelling gets the same treatment so
# the brand looks identical wherever it appears, without anyone having to
# remember to type the emoji into a settings field.
_BRAND_ALIASES = (BRAND, "Atlas Account", "AtlasAccount", "اطلس‌اکانت")


def _brandify(escaped_html: str) -> str:
    """Put the brand emoji and bold on the brand name inside ALREADY-ESCAPED html.

    Runs after escaping on purpose: it inserts markup, so anything it added would
    be escaped away if the order were reversed.
    """
    from bot.rich_message import emoji as tg_emoji
    mark = f'{tg_emoji("brand", "🌐")} <b>{BRAND}</b>'
    out = escaped_html
    for alias in _BRAND_ALIASES:
        if alias in out:
            out = out.replace(alias, mark)
            break          # one spelling per text; replacing them all double-marks
    return out


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

    await send_home(msg, user, role)


async def send_home(msg: Message, user: dict, role: str):
    """The welcome message and the menus, in one place.

    /start, the restart button and the fallback for an unrecognised message all
    land here, so a customer sees the same screen however they got back to it.
    """
    import html as _html
    from bot.keyboards import admin_menu, user_menu
    from bot.rich_message import emoji as tg_emoji

    welcome = await get_text("welcome_message")
    if role != "none":
        head = "🔐 <b>پنل مدیریت</b>"
    else:
        head = f'{tg_emoji("brand", "🌐")} <b>{BRAND}</b>'
    # HTML, not Markdown: a custom emoji has no Markdown syntax. Escaped with
    # html.escape rather than rich_message.esc, because that one collapses
    # whitespace and the welcome text is written across two lines.
    text = f"{head}\n\n{_brandify(_html.escape(welcome, quote=False))}"

    kb = (admin_menu(finance_only=(role == "finance")) if role != "none"
          else user_menu(include_wholesale=bool(user.get("is_wholesale", 0))))
    await msg.answer(text, reply_markup=kb, parse_mode="HTML")

    # The reply keyboard above is invisible until someone thinks to open it, and
    # newcomers who press Start and see only text simply stop. The same actions
    # go into the chat as coloured buttons, where they cannot be missed.
    if role == "none":
        from bot.home import home_kb
        await msg.answer("👇 از این‌جا شروع کن:", reply_markup=home_kb())




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
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    role = await _admin_role(cb.from_user.id, user)
    await cb.answer()
    if role != "none":
        from bot.keyboards import admin_menu
        await cb.message.answer("منوی اصلی",
                                reply_markup=admin_menu(finance_only=(role == "finance")))
        return
    # Replace the screen the customer is leaving with the menu, rather than
    # stacking a third message under two dead ones.
    from bot.home import home_kb
    try:
        await cb.message.edit_text("👇 از این‌جا ادامه بده:", reply_markup=home_kb())
    except Exception:
        await cb.message.answer("👇 از این‌جا ادامه بده:", reply_markup=home_kb())




@router.message(F.text == "🔄 شروع مجدد")
async def restart_menu(msg: Message, state: FSMContext):
    # Identical to /start, deliberately: this button is the way back for someone
    # who is lost, and a "menu reloaded" line without the menu itself was not it.
    await state.clear()
    user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
    await send_home(msg, user, await _admin_role(msg.from_user.id, user))

@router.message(F.text == "🌐 پنل مدیریت")
async def panel_url(msg: Message):
    user = await get_or_create_user(msg.from_user.id)
    role = await _admin_role(msg.from_user.id, user)
    if role not in ("owner", "full"):
        return
    panel_help = await get_text("panel_url_help", port=WEB_PORT, secret=WEB_SECRET_PATH)
    await msg.answer(panel_help, parse_mode="Markdown")


@router.callback_query(F.data == "check_channel_join")
async def check_channel_join(cb: CallbackQuery):
    """The "بررسی عضویت" button.

    THIS HANDLER MUST EXIST, even though ChannelRequiredMiddleware answers the
    button itself and this body usually never runs. aiogram 3 draws a hard line
    between OUTER middleware, which runs for every update, and INNER middleware,
    which runs only after a handler has been MATCHED by filters. main.py
    registers ChannelRequiredMiddleware with `.middleware()` — inner. So with no
    handler bound to this callback data the router matched nothing, the
    middleware never ran, and the button was answered by nobody: the user saw a
    spinner and silence, and had to send /start again (a command that DOES have
    a handler) before the bot noticed they had joined. That was the bug.

    When the channel requirement is ON, the middleware intercepts first and this
    body is unreachable. It runs only when the requirement has since been turned
    off and someone presses a stale button — so it answers instead of leaving
    them on the same spinner.
    """
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    required, channel_username = await ChannelRequiredMiddleware.is_required()
    if required and not await ChannelRequiredMiddleware.can_access(cb.bot, cb.from_user.id, channel_username):
        await cb.answer("❌ هنوز عضو کانال نشده‌اید.", show_alert=True)
        return
    await ChannelRequiredMiddleware._render_join_success(cb, user)


# ─────────────────────────── the last-resort fallback ────────────────────────
# Registered at the very end of the LAST router, so it only ever sees a message
# no other handler wanted.
@router.message(F.text)
async def unrecognised_text(msg: Message, state: FSMContext):
    """Someone typed something the bot has no answer for — show them the menu.

    People genuinely write "سلام" or "کمک" or a stray word at a bot and then get
    silence, which reads as broken. Sending them home costs nothing and is what
    they were looking for.

    THE GUARD MATTERS MORE THAN THE FEATURE: if the person is mid-flow — typing
    an amount, naming a service, waiting to send a receipt — their message is
    part of that step, and answering with a welcome screen would throw the step
    away. So this only fires when there is NO active state.
    """
    if await state.get_state() is not None:
        return
    user = await get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.full_name)
    await send_home(msg, user, await _admin_role(msg.from_user.id, user))
