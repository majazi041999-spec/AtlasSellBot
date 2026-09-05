"""The home screen: the bot's main actions as coloured buttons IN the chat.

Everything here used to live only on the reply keyboard — the panel that slides
up over the phone's own keyboard. That panel is invisible until you look for it,
and people who press Start and see a wall of text simply stop. So the same
actions are now buttons inside the welcome message, where they cannot be missed.

The reply keyboard stays as well. It is the persistent navigation for everyone
who already knows it, and removing it would take that away to fix a problem they
never had.

HOW THE BUTTONS REACH THE FLOWS. Each one calls the SAME handler the reply
keyboard calls — there is no second implementation of "buy" or "free trial" to
drift out of sync. A callback's `message.from_user` is the BOT, not the person
who tapped, so the handler is given a copy of the message with the real user
patched in. Passing the raw one would run every flow against the bot's own
account.
"""
from __future__ import annotations

import logging
from typing import List, Tuple

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

log = logging.getLogger(__name__)
router = Router()

# key, label, colour, the handler it shares with the reply keyboard.
#
# Colour carries meaning rather than decoration, because Telegram only gives
# three: green starts something free, red is the one that costs money and should
# stand out, blue is everything else.
# key, label, colour, handler shared with the reply keyboard, premium-emoji role.
#
# LABELS MUST BE SHORT AND ONE LINE. A newline does NOT make the button taller:
# Telegram folds it into a single line and TRUNCATES the overflow, which ate the
# first words of two of these ("تست رایگان بگیر…" arrived as "رایگان بگیر…").
# Width — how many buttons share a row — is the only size control there is.
#
# The plain emoji is left OUT of any label that has a premium icon: the icon
# already fills that slot, and printing both shows the same idea twice.
ACTIONS: List[Tuple[str, str, str, str, str]] = [
    ("trial", "تست رایگان", "success", "test_account", "trial"),
    ("buy", "خرید سرویس", "danger", "buy_service", "cart"),
    ("status", "سرویس‌های من", "primary", "user_status", "services"),
    ("ai", "دستیار هوشمند", "success", "", "assistant"),
    ("support", "پشتیبانی", "primary", "support", "support"),
    ("wallet", "💳 کیف پول", "primary", "wallet_home", ""),
    ("orders", "سفارش‌های من", "primary", "my_orders", "orders"),
    ("invite", "دعوت دوستان", "primary", "referral_menu", "invite"),
    ("rep", "🏢 پنل نمایندگی", "primary", "representative_start", ""),
]

# The two a newcomer came for get a full row each — the biggest tap target the
# API allows. Everything after that pairs up, which reads as a tidy grid instead
# of a column of near-empty bars.
_LAYOUT = [1, 1, 2, 2, 2, 1]


def home_kb() -> InlineKeyboardMarkup:
    from bot.keyboards import _button
    from bot.rich_message import emoji_id
    b = InlineKeyboardBuilder()
    for key, label, style, _fn, role in ACTIONS:
        _button(b, text=label, callback_data=f"home:{key}", style=style,
                icon_custom_emoji_id=emoji_id(role) if role else None)
    b.adjust(*_LAYOUT)
    return b.as_markup()


def _as_user(cb: CallbackQuery, bot: Bot, edit: bool = False) -> Message:
    """The tapped message, re-attributed to the person who tapped it.

    `cb.message.from_user` is the BOT. Every flow downstream reads from_user.id
    to decide whose wallet, whose services and whose orders it is looking at, so
    handing over the unmodified message would run all of them against the bot's
    own account. The copy leaves the original untouched.

    IT DOES NOT EDIT IN PLACE, and that was tried. Wrapping the message so a
    flow's first reply edited the menu looked right and was wrong: a flow's first
    reply is usually a preamble, not the screen. "اکانت تست شما قبلاً ساخته شده
    است:" would replace the whole menu, the real content then arrived below it,
    and the customer was left on a dead end with no way back. Editing has to be
    something a screen opts into knowing it is a screen — not something done to
    every flow from the outside.
    """
    return cb.message.model_copy(update={"from_user": cb.from_user}).as_(bot)


async def _open_screen(cb: CallbackQuery, key: str) -> None:
    """Render a single-screen destination INTO the message the customer tapped.

    Both of these already knew how to edit — `_send_services_list` has taken a
    CallbackQuery since long before this menu existed — so this is wiring, not a
    new rendering path.
    """
    from bot.handlers.user import _send_services_list, _user_service_lists, _fmt_toman
    from bot.keyboards import wallet_kb
    from core.database import get_or_create_user, get_user_balance

    user = await get_or_create_user(cb.from_user.id, cb.from_user.username,
                                    cb.from_user.full_name)
    if key == "wallet":
        bal = await get_user_balance(user["id"])
        text = f"💳 <b>کیف پول شما</b>\n\nموجودی فعلی: <b>{_fmt_toman(bal)} تومان</b>"
        try:
            await cb.message.edit_text(text, reply_markup=wallet_kb(), parse_mode="HTML")
        except Exception:
            await cb.message.answer(text, reply_markup=wallet_kb(), parse_mode="HTML")
        return

    configs, profiles = await _user_service_lists(user["id"])
    if not configs and not profiles:
        from core.texts import get_text
        text = await get_text("no_active_service")
        kb = InlineKeyboardBuilder()
        from bot.keyboards import _button
        _button(kb, text="🏠 منوی اصلی", callback_data="back_to_menu", style="primary")
        try:
            await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode=None)
        except Exception:
            await cb.message.answer(text, reply_markup=kb.as_markup(), parse_mode=None)
        return
    # Always the LIST, even for one service. Opening the single service straight
    # away saved a tap but landed the customer on a detail card with no list to
    # go back to; from the list, every service is one tap either way.
    await _send_services_list(cb, user["id"], page=0,
                              is_rep=bool(user.get("is_wholesale", 0)))


@router.callback_query(F.data == "home:restart")
async def home_restart(cb: CallbackQuery, state: FSMContext, bot: Bot):
    """A button that genuinely restarts the bot for the person who taps it.

    A t.me/<bot>?start=… link does NOT do this. Telegram shows a real Start
    button only to somebody who has never opened the chat; for everyone else the
    link just brings the chat forward and nothing runs — which is why the button
    attached to past broadcasts looked dead. A callback button does run, because
    the message carrying it came from this bot.
    """
    from bot.handlers.common import send_home, _admin_role
    from core.database import get_or_create_user
    await state.clear()
    await cb.answer("منو دوباره بارگذاری شد")
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username,
                                    cb.from_user.full_name)
    await send_home(_as_user(cb, bot), user, await _admin_role(cb.from_user.id, user))


@router.callback_query(F.data.startswith("home:"))
async def home_action(cb: CallbackQuery, state: FSMContext, bot: Bot):
    key = cb.data.split(":", 1)[1]
    entry = next((a for a in ACTIONS if a[0] == key), None)
    if not entry:
        await cb.answer()
        return
    await cb.answer()
    await state.clear()
    msg = _as_user(cb, bot)

    if key == "ai":
        from bot.handlers.agent import agent_start
        await agent_start(msg, state)
        return

    # ── the two destinations that ARE single screens ────────────────────────
    # These render in place, replacing the menu, and each carries "🏠 منوی اصلی"
    # so the customer can come back. Nothing else opts in: a flow that sends a
    # preamble, a QR or a sequence of steps is not a screen, and pretending
    # otherwise is what broke navigation the first time this was tried.
    if key in ("status", "wallet"):
        await _open_screen(cb, key)
        return

    from bot.handlers import user as user_handlers
    fn = getattr(user_handlers, entry[3], None) if entry[3] else None
    if not fn:
        log.warning("home action %r has no handler %r", key, entry[3])
        return
    try:
        # A couple of these flows need the FSM context; the rest take the
        # message alone. Ask the function rather than keeping a second list that
        # would go stale the first time a signature changes.
        import inspect
        if "state" in inspect.signature(fn).parameters:
            await fn(msg, state)
        else:
            await fn(msg)
    except Exception:
        log.exception("home action %r failed", key)
        await cb.message.answer("مشکلی پیش آمد. دوباره امتحان کن.")
