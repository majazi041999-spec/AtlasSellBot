from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.config import ADMIN_IDS
from core.database import get_or_create_user, get_setting


class ChannelRequiredMiddleware(BaseMiddleware):
    @staticmethod
    def _channel_ref(raw: str) -> str:
        raw = (raw or "").strip()
        if raw.startswith("https://t.me/") or raw.startswith("http://t.me/"):
            tail = raw.rstrip("/").rsplit("/", 1)[-1].strip()
            return f"@{tail}" if tail and not tail.startswith("+") else raw
        if raw.startswith("t.me/"):
            tail = raw.rstrip("/").rsplit("/", 1)[-1].strip()
            return f"@{tail}" if tail and not tail.startswith("+") else f"https://{raw}"
        if raw.startswith("-100") or raw.startswith("@"):
            return raw
        return f"@{raw}"

    @staticmethod
    def _channel_url(raw: str) -> str:
        raw = (raw or "").strip()
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        return f"https://t.me/{raw.lstrip('@')}"

    @staticmethod
    async def is_member(bot, uid: int, channel_username: str) -> bool:
        if not uid:
            return False
        ch = ChannelRequiredMiddleware._channel_ref(channel_username)
        try:
            member = await bot.get_chat_member(ch, uid)
            return member.status in ("member", "administrator", "creator")
        except Exception:
            return False

    @staticmethod
    def join_kb(channel_username: str):
        b = InlineKeyboardBuilder()
        b.button(text="عضویت در کانال", url=ChannelRequiredMiddleware._channel_url(channel_username))
        b.button(text="بررسی عضویت", callback_data="check_channel_join")
        b.adjust(1)
        return b.as_markup()

    @staticmethod
    def join_text(channel_username: str) -> str:
        ch = ChannelRequiredMiddleware._channel_ref(channel_username)
        channel_label = ch if not ch.startswith("http") else "لینک عضویت"
        return (
            "برای استفاده از امکانات ربات، ابتدا باید عضو کانال شوید.\n\n"
            f"کانال: {channel_label}\n\n"
            "بعد از عضویت روی «بررسی عضویت» بزنید یا /start را دوباره ارسال کنید."
        )

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

        if await self.is_member(event.bot, uid, channel_username):
            if isinstance(event, CallbackQuery) and event.data == "check_channel_join":
                await event.answer("عضویت تایید شد.")
                if event.message:
                    from bot.keyboards import admin_menu, user_menu

                    role = "full" if user.get("is_admin", 0) else "none"
                    kb = admin_menu() if role != "none" else user_menu(include_wholesale=bool(user.get("is_wholesale", 0)))
                    await event.message.answer("عضویت شما تایید شد. منوی ربات فعال است.", reply_markup=kb)
                return None
            return await handler(event, data)

        text = self.join_text(channel_username)
        kb = self.join_kb(channel_username)
        if isinstance(event, Message):
            await event.answer(text, reply_markup=kb, parse_mode=None)
        else:
            await event.answer("ابتدا باید عضو کانال شوید.", show_alert=True)
            if event.message:
                await event.message.answer(text, reply_markup=kb, parse_mode=None)
        return None
