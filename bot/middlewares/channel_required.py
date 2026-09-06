import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.config import ADMIN_IDS
from core.database import get_or_create_user, get_setting

_POSITIVE_TTL = 900
_STALE_TTL = 3600
_MEMBERSHIP_CACHE: dict[tuple[str, int], float] = {}

# Where a blocked /start was trying to go, held until the person gets in.
#
# A deeplink like ?start=rep is the only kind of button a channel post may carry,
# and the reader it is aimed at has neither used the bot nor joined our channel.
# The gate below stops that first message, and by the time they have joined, the
# message carrying the payload is gone — so without this they land on the retail
# menu and the post's promise ("tap here to apply") quietly breaks for exactly
# the audience it was written for.
#
# In memory on purpose: this is worth seconds of a stranger's journey, not a
# column. A restart in that window costs them one tap.
_PENDING_START: dict[int, str] = {}


class ChannelRequiredMiddleware(BaseMiddleware):
    @staticmethod
    def _clean_channel(raw: str) -> str:
        raw = (raw or "").strip()
        if not raw:
            return ""
        # Accept values like "@channel | https://t.me/channel" and use the first
        # verifiable token as chat reference.
        for sep in ("|", ",", "\n"):
            if sep in raw:
                raw = raw.split(sep, 1)[0].strip()
        return raw

    @staticmethod
    def _channel_ref(raw: str) -> str:
        raw = ChannelRequiredMiddleware._clean_channel(raw)
        raw = (raw or "").strip()
        if raw.startswith("https://t.me/") or raw.startswith("http://t.me/"):
            tail = raw.rstrip("/").rsplit("/", 1)[-1].strip()
            return f"@{tail}" if tail and not tail.startswith("+") else ""
        if raw.startswith("t.me/"):
            tail = raw.rstrip("/").rsplit("/", 1)[-1].strip()
            return f"@{tail}" if tail and not tail.startswith("+") else ""
        if raw.startswith("-100") or raw.startswith("@"):
            return raw
        return f"@{raw}"

    @staticmethod
    def _channel_url(raw: str) -> str:
        raw = (raw or "").strip()
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        if "|" in raw:
            for part in [p.strip() for p in raw.split("|")]:
                if part.startswith("http://") or part.startswith("https://"):
                    return part
        if raw.startswith("-100"):
            return ""
        return f"https://t.me/{raw.lstrip('@')}"

    @staticmethod
    def _status_value(status) -> str:
        return str(getattr(status, "value", status) or "").lower()

    @staticmethod
    async def is_exempt(uid: int) -> bool:
        if uid in ADMIN_IDS:
            return True
        owner_id = int(await get_setting("owner_admin_id", "0") or 0)
        if owner_id and uid == owner_id:
            return True
        user = await get_or_create_user(uid)
        return bool(user.get("is_admin", 0))

    @staticmethod
    async def is_member(bot, uid: int, channel_username: str, *, use_cache: bool = True) -> bool:
        if not uid:
            return False
        ch = ChannelRequiredMiddleware._channel_ref(channel_username)
        if not ch:
            # The setting is an invite link or otherwise unverifiable by Telegram.
            # Do not falsely block real members because verification is impossible.
            return True
        key = (ch.lower(), int(uid))
        now = time.time()
        if use_cache and _MEMBERSHIP_CACHE.get(key, 0) > now:
            return True
        try:
            member = await bot.get_chat_member(ch, uid)
            status = ChannelRequiredMiddleware._status_value(member.status)
            ok = status in {"member", "administrator", "creator"} or (status == "restricted" and bool(getattr(member, "is_member", False)))
            if ok:
                _MEMBERSHIP_CACHE[key] = now + _POSITIVE_TTL
            else:
                _MEMBERSHIP_CACHE.pop(key, None)
            return ok
        except (TelegramNetworkError, TelegramRetryAfter):
            # Temporary Telegram/API trouble: trust a recent positive check.
            return _MEMBERSHIP_CACHE.get(key, 0) > now - _STALE_TTL
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            text = str(e).lower()
            if any(mark in text for mark in ("user not found", "participant_id_invalid")):
                _MEMBERSHIP_CACHE.pop(key, None)
                return False
            if any(mark in text for mark in ("chat_admin_required", "chat not found", "bot was kicked", "not enough rights")):
                return True
            return _MEMBERSHIP_CACHE.get(key, 0) > now - _STALE_TTL
        except Exception:
            return _MEMBERSHIP_CACHE.get(key, 0) > now - _STALE_TTL

    @staticmethod
    async def can_access(bot, uid: int, channel_username: str) -> bool:
        if await ChannelRequiredMiddleware.is_exempt(uid):
            return True
        return await ChannelRequiredMiddleware.is_member(bot, uid, channel_username)

    @staticmethod
    async def is_required() -> tuple[bool, str]:
        force = await get_setting("force_channel", "0")
        channel_username = (await get_setting("channel_username", "")).strip()
        return force == "1" and bool(channel_username), channel_username

    @staticmethod
    def is_join_check(event: Message | CallbackQuery) -> bool:
        return isinstance(event, CallbackQuery) and event.data == "check_channel_join"

    @staticmethod
    def remember_start(uid: int, event: Message) -> None:
        """Hold the destination of a /start that the gate is about to refuse."""
        from bot.handlers.common import START_DESTINATIONS
        parts = (event.text or "").split()
        if (len(parts) > 1 and parts[0].split("@")[0] == "/start"
                and parts[1] in START_DESTINATIONS and uid):
            _PENDING_START[int(uid)] = parts[1]

    @staticmethod
    async def _resume_start(event: CallbackQuery, user: dict, state) -> None:
        """Open whatever the refused /start was aimed at, now that they are in."""
        uid = int(event.from_user.id) if event.from_user else 0
        dest = _PENDING_START.pop(uid, None)
        if dest != "rep" or user.get("is_admin", 0) or state is None:
            return
        from bot.handlers.user import representative_start
        from bot.home import _as_user
        try:
            await representative_start(_as_user(event, event.bot), state)
        except Exception:
            pass          # the menu is already up; a missed screen is not worth an error

    @staticmethod
    async def _render_join_success(event: CallbackQuery, user: dict, state=None) -> None:
        """Membership just confirmed: pop the toast, DELETE the join prompt, and
        open the bot menu with a success message."""
        await event.answer("✅ عضویت شما تایید شد!", show_alert=False)
        if not event.message:
            return
        from bot.keyboards import admin_menu, user_menu
        # Remove the "you must join" prompt so the chat is clean.
        try:
            await event.message.delete()
        except Exception:
            pass
        kb = admin_menu() if user.get("is_admin", 0) else user_menu(include_wholesale=bool(user.get("is_wholesale", 0)))
        await event.message.answer(
            "🎉 عضویت شما تایید شد!\nحالا می‌توانید از همه‌ی امکانات ربات استفاده کنید. منوی ربات فعال شد 👇",
            reply_markup=kb,
        )
        await ChannelRequiredMiddleware._resume_start(event, user, state)

    @staticmethod
    async def verify_join_callback(event: CallbackQuery, user: dict, channel_username: str) -> bool:
        uid = event.from_user.id if event.from_user else 0
        if not await ChannelRequiredMiddleware.is_member(event.bot, uid, channel_username, use_cache=False):
            return False
        await ChannelRequiredMiddleware._render_join_success(event, user)
        return True

    @staticmethod
    def join_kb(channel_username: str):
        b = InlineKeyboardBuilder()
        url = ChannelRequiredMiddleware._channel_url(channel_username)
        if url:
            b.button(text="عضویت در کانال", url=url)
        b.button(text="بررسی عضویت", callback_data="check_channel_join")
        b.adjust(1)
        return b.as_markup()

    @staticmethod
    def join_text(channel_username: str) -> str:
        ch = ChannelRequiredMiddleware._channel_ref(channel_username)
        channel_label = ch or "لینک عضویت"
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
        required, channel_username = await self.is_required()
        if not required:
            return await handler(event, data)

        uid = event.from_user.id if event.from_user else 0
        user = await get_or_create_user(uid)
        if await self.is_exempt(uid):
            return await handler(event, data)

        # The "بررسی عضویت" button gets its own handling: a FRESH check (no cache)
        # and a clear outcome either way — success cleans up + opens the menu,
        # failure just tells them they're not a member yet (no duplicate prompt).
        if self.is_join_check(event):
            if await self.is_member(event.bot, uid, channel_username, use_cache=False):
                await self._render_join_success(event, user, data.get("state"))
            else:
                await event.answer(
                    "❌ هنوز عضو کانال نشده‌اید.\nاول در کانال عضو شوید، بعد دوباره «بررسی عضویت» را بزنید.",
                    show_alert=True,
                )
            return None

        if await self.is_member(event.bot, uid, channel_username):
            return await handler(event, data)

        text = self.join_text(channel_username)
        kb = self.join_kb(channel_username)
        if isinstance(event, Message):
            self.remember_start(uid, event)
            await event.answer(text, reply_markup=kb, parse_mode=None)
        else:
            await event.answer("ابتدا باید عضو کانال شوید.", show_alert=True)
            if event.message:
                await event.message.answer(text, reply_markup=kb, parse_mode=None)
        return None
