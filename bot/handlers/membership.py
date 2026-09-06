"""Record when somebody blocks the bot, and when they come back.

Telegram sends a `my_chat_member` update the moment a user blocks or unblocks a
bot. That is the only exact source: inferring it from a send that failed only
ever finds the people we happened to message, misses everyone we did not, and
tells us hours or days late.

Nothing is backfilled. Anybody who blocked the bot before this existed stays
invisible, because counting them as active would be a lie every chart repeats.
"""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import ChatMemberUpdated

from core.database import get_or_create_user, update_user

log = logging.getLogger(__name__)
router = Router()


@router.my_chat_member()
async def bot_membership_changed(event: ChatMemberUpdated):
    # Private chats only: a bot removed from a group is a different event with
    # different meaning, and mixing the two would make the churn number wrong.
    if event.chat.type != "private":
        return
    status = event.new_chat_member.status
    if status not in ("kicked", "member"):
        return

    user = await get_or_create_user(event.from_user.id, event.from_user.username,
                                    event.from_user.full_name)
    now = event.date.strftime("%Y-%m-%d %H:%M:%S") if event.date else ""
    if status == "kicked":
        await update_user(int(user["id"]), bot_blocked_at=now)
        log.info("user %s blocked the bot", event.from_user.id)
    else:
        # Returning clears the block mark, so "currently blocked" stays a
        # question about now rather than about whether it ever happened. The
        # date they left is kept in bot_unblocked_at for the churn history.
        await update_user(int(user["id"]), bot_blocked_at="", bot_unblocked_at=now)
        log.info("user %s unblocked the bot", event.from_user.id)
