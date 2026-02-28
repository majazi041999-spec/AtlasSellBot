from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.config import ADMIN_IDS
from core.database import get_or_create_user, get_setting


class ChannelRequiredMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        force = await get_setting("force_channel", "0")
        channel_username = (await get_setting("channel_username", "")).strip()
        if force != "1" or not channel_username:
            return await handler(event, data)

        uid = event.from_user.id if event.from_user else 0
        if uid in ADMIN_IDS:
            return await handler(event, data)

        user = await get_or_create_user(uid)
        owner_id = int(await get_setting("owner_admin_id", "0") or 0)
        if user.get("is_admin", 0) or (owner_id and uid == owner_id):
            return await handler(event, data)

        ch = channel_username if channel_username.startswith("@") else f"@{channel_username}"

        try:
            member = await event.bot.get_chat_member(ch, uid)
            if member.status in ("member", "administrator", "creator"):
                return await handler(event, data)
        except Exception:
            pass

        kb = self._join_kb(channel_username)
        text = f"⚠️ شما در کانال عضو نیستید.\n\nبرای استفاده از امکانات ربات اول باید عضو شوید:\n{ch}"

        if isinstance(event, Message):
            await event.answer(text, reply_markup=kb)
        else:
            await event.answer("⚠️ ابتدا در کانال عضو شوید.", show_alert=True)
            if event.message:
                await event.message.answer(text, reply_markup=kb)
        return None

    @staticmethod
    def _join_kb(channel_username: str):
        ch = channel_username.strip().lstrip("@")
        b = InlineKeyboardBuilder()
        b.button(text="📢 عضویت در کانال", url=f"https://t.me/{ch}")
        return b.as_markup()
