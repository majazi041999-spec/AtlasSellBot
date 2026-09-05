"""Push menu changes to customers without asking them to press /start.

THE PROBLEM. A reply keyboard is not part of the bot; it is a thing Telegram
stored on the customer's phone the last time the bot sent one. Change
`user_menu()` and nobody sees the change — their phone keeps showing the old
buttons until some message arrives carrying a new keyboard. /start does that,
which is why every menu change so far has needed a broadcast asking people to
press it. Most never do, and the ones who do are annoyed.

THE FIX. MENU_VERSION is bumped whenever the menus change. Each customer's row
remembers the version they are holding. The first time someone touches the bot
after a bump, this sends them the current menu once and records the new version.
No broadcast, no instructions, and nobody is asked to do anything.

WHY A MIDDLEWARE. It has to run for every kind of interaction — a typed message,
a tapped button, a command — and before whatever they were actually trying to
do, so their action still lands on the screen they expect.

Costs one extra message per customer per menu change, and only to customers who
come back. Somebody who never opens the bot again is never messaged.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

log = logging.getLogger(__name__)

# ── BUMP THIS whenever user_menu() or the home menu changes. ──────────────────
# 1: the coloured in-chat home menu, premium emoji, "انتقال سرور" and
#    "افزودن سرویس قبلی" removed from the reply keyboard.
MENU_VERSION = 1


class MenuRefreshMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        try:
            await self._refresh(event)
        except Exception as exc:  # noqa: BLE001
            # Never let a cosmetic refresh stop the thing the customer asked for.
            log.debug("menu refresh skipped: %s", exc)
        return await handler(event, data)

    async def _refresh(self, event: TelegramObject) -> None:
        from core.database import get_or_create_user, get_setting, update_user

        if isinstance(event, Message):
            user_tg, chat_id, bot = event.from_user, event.chat.id, event.bot
        elif isinstance(event, CallbackQuery) and event.message:
            user_tg, chat_id, bot = event.from_user, event.message.chat.id, event.bot
        else:
            return
        if not user_tg or user_tg.is_bot:
            return

        user = await get_or_create_user(user_tg.id, user_tg.username, user_tg.full_name)
        if int(user.get("menu_version") or 0) >= MENU_VERSION:
            return

        # Written BEFORE the send. If the send fails — blocked bot, closed chat —
        # this must not retry on every message the person ever sends again.
        await update_user(user["id"], menu_version=MENU_VERSION)

        from bot.handlers.common import _admin_role
        from bot.keyboards import admin_menu, user_menu
        role = await _admin_role(user_tg.id, user)
        kb = (admin_menu(finance_only=(role == "finance")) if role != "none"
              else user_menu(include_wholesale=bool(user.get("is_wholesale", 0))))
        await bot.send_message(chat_id, "✨ منوی ربات به‌روز شد.", reply_markup=kb)

        if role == "none":
            from bot.home import home_kb
            await bot.send_message(chat_id, "👇 از این‌جا شروع کن:", reply_markup=home_kb())
