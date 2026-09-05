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
# A newline inside the label makes the button TALLER as well as wide, which is
# the only size control Telegram gives: height follows the line count and width
# follows how many buttons share the row. The ones that matter most get both.
#
# The plain emoji is left OUT of any label that has a premium icon — the icon
# already fills that slot, and printing both shows the same idea twice.
ACTIONS: List[Tuple[str, str, str, str, str]] = [
    ("trial", "تست رایگان بگیر\nیک اکانت آزمایشی، همین حالا", "success", "test_account", "trial"),
    ("buy", "خرید سرویس\nدیدن پکیج‌ها و قیمت‌ها", "danger", "buy_service", "cart"),
    ("status", "سرویس‌های من", "primary", "user_status", "services"),
    ("ai", "دستیار هوشمند\nسوالت را بپرس، همین‌جا جواب بگیر", "success", "", "assistant"),
    ("support", "پشتیبانی", "primary", "support", "support"),
    ("wallet", "💳 کیف پول", "primary", "wallet_home", ""),
    ("orders", "سفارش‌های من", "primary", "my_orders", "orders"),
    ("invite", "دعوت دوستان", "primary", "referral_menu", "invite"),
    ("rep", "🏢 پنل نمایندگی", "primary", "representative_start", ""),
]

# Everything a newcomer actually needs gets the full width. Only the last three —
# orders, invites and the reseller panel — share rows, because someone opening
# the bot for the first time is not looking for those.
_LAYOUT = [1, 1, 1, 1, 2, 2, 1]


def home_kb() -> InlineKeyboardMarkup:
    from bot.keyboards import _button
    from bot.rich_message import emoji_id
    b = InlineKeyboardBuilder()
    for key, label, style, _fn, role in ACTIONS:
        _button(b, text=label, callback_data=f"home:{key}", style=style,
                icon_custom_emoji_id=emoji_id(role) if role else None)
    b.adjust(*_LAYOUT)
    return b.as_markup()


def _as_user(cb: CallbackQuery, bot: Bot) -> Message:
    """The tapped message, re-attributed to the person who tapped it.

    `cb.message.from_user` is the bot itself. Every downstream flow reads
    `from_user.id` to decide whose wallet, whose services and whose orders it is
    looking at, so handing it the unmodified message would act on the bot's own
    account. The copy leaves the original untouched.
    """
    return cb.message.model_copy(update={"from_user": cb.from_user}).as_(bot)


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
