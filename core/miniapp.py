"""Telegram Mini App backend helpers — security + small utilities.

The ONLY trust anchor is Telegram's signed `initData`: every API call must
carry it and we verify the HMAC with the bot token (per Telegram's Web Apps
spec). Nothing the client sends (user id, etc.) is trusted unless the signature
checks out, so a user can never act as someone else.
"""
import hashlib
import hmac
import json
import logging
import time
from urllib.parse import parse_qsl

from core.config import BOT_TOKEN

logger = logging.getLogger(__name__)


def validate_init_data(init_data: str, max_age_sec: int = 86400) -> dict | None:
    """Verify Telegram WebApp initData. Returns {user, auth_date} or None."""
    if not init_data or not BOT_TOKEN or len(BOT_TOKEN) < 20:
        return None
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None
    received = data.pop("hash", "")
    if not received:
        return None
    check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        return None
    try:
        auth_date = int(data.get("auth_date", "0"))
    except ValueError:
        return None
    if max_age_sec and auth_date and (time.time() - auth_date) > max_age_sec:
        return None
    user = {}
    if data.get("user"):
        try:
            user = json.loads(data["user"])
        except Exception:
            user = {}
    if not user.get("id"):
        return None
    return {"user": user, "auth_date": auth_date}


_bot_username: str | None = None


async def get_bot_username() -> str:
    """Cached @username of the bot (for building referral deep-links)."""
    global _bot_username
    if _bot_username is not None:
        return _bot_username
    _bot_username = ""
    if BOT_TOKEN and len(BOT_TOKEN) > 20:
        try:
            from aiogram import Bot
            b = Bot(BOT_TOKEN)
            try:
                me = await b.get_me()
                _bot_username = me.username or ""
            finally:
                await b.session.close()
        except Exception as e:
            logger.warning("miniapp get_bot_username failed: %s", e)
    return _bot_username
