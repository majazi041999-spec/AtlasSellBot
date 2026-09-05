"""A visible "working on it" for the operations that are not instant.

Some things this bot does take real time — creating a trial on a panel, syncing
usage off an X-UI server, building a subscription. A customer who taps and sees
nothing assumes it is broken and taps again, which is how one order becomes two.

Two levels, because they cost different things:

  * `typing()` is free and leaves nothing behind — the "typing…" line at the top
    of the chat. Right for anything under a couple of seconds. It expires after
    five seconds on its own.
  * `hold()` posts an actual message for the longer jobs, and the caller then
    EDITS it into the result. Editing rather than delete-then-send is deliberate:
    no flicker, no gap where the chat is empty, and the answer lands exactly
    where the customer was already looking.
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import Message

log = logging.getLogger(__name__)

# Animated, from the owner's own packs, so the wait looks like the rest of the
# bot rather than a system glyph.
_SPINNER_ROLE = "🔄"


async def typing(bot: Bot, chat_id: int) -> None:
    """Show "typing…" — for waits short enough that a message would be noise."""
    try:
        await bot.send_chat_action(chat_id, "typing")
    except Exception as exc:  # noqa: BLE001
        log.debug("chat action skipped: %s", exc)


async def hold(bot: Bot, chat_id: int, text: str = "کمی صبر کن…") -> Optional[Message]:
    """Post a placeholder for a slow job. Returns it, or None if it failed.

    None is a normal outcome, not an error: the caller must work whether or not
    the placeholder exists, because a wait indicator is never worth failing an
    operation over.
    """
    from bot.rich_message import GLYPH_PREMIUM
    spinner = GLYPH_PREMIUM.get(_SPINNER_ROLE, "")
    mark = (f'<tg-emoji emoji-id="{spinner}">{_SPINNER_ROLE}</tg-emoji>'
            if spinner else _SPINNER_ROLE)
    try:
        await typing(bot, chat_id)
        return await bot.send_message(chat_id, f"{mark} {text}", parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001
        log.debug("progress placeholder skipped: %s", exc)
        return None


async def done(placeholder: Optional[Message], text: str, reply_markup=None,
               parse_mode: Optional[str] = "HTML") -> bool:
    """Turn the placeholder into the result. False if there was nothing to turn."""
    if placeholder is None:
        return False
    try:
        await placeholder.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return True
    except Exception as exc:  # noqa: BLE001
        log.debug("progress edit failed: %s", exc)
        return False


async def clear(placeholder: Optional[Message]) -> None:
    """Remove the placeholder — for when the result cannot be an edit of it,
    because it is a photo, several messages, or a rich message."""
    if placeholder is None:
        return
    try:
        await placeholder.delete()
    except Exception as exc:  # noqa: BLE001
        log.debug("progress delete failed: %s", exc)
