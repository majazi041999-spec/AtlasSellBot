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

# How long a signed initData stays acceptable. See check_init_data for why a
# day was too short and what the age check is actually protecting against.
MAX_INIT_DATA_AGE = 7 * 86400


def validate_init_data(init_data: str, max_age_sec: int | None = None) -> dict | None:
    """Verify Telegram WebApp initData. Returns {user, auth_date} or None.

    Thin wrapper kept for callers that only care whether it passed. Use
    `check_init_data` when you need to know WHY it did not.
    """
    res = check_init_data(init_data, max_age_sec)
    return res if res.get("ok") else None


def check_init_data(init_data: str, max_age_sec: int | None = None) -> dict:
    """The same check, but it says which of the five ways it failed.

    Written after customers reported an occasional "دسترسی نامعتبر است" with no
    way to tell a stale session from a broken one. Returning None for all of
    them meant the logs could not distinguish "this person left the app open
    since yesterday" — harmless and self-correcting — from "the bot token
    changed" or "someone is forging headers", which are not. The reason now
    travels to the caller so the client can say something true to the customer
    and the owner can see the difference in the log.

    `reason` is one of: no_data, no_token, malformed, no_hash, bad_hash,
    expired, no_user.
    """
    if not init_data:
        return {"ok": False, "reason": "no_data"}
    if not BOT_TOKEN or len(BOT_TOKEN) < 20:
        return {"ok": False, "reason": "no_token"}
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return {"ok": False, "reason": "malformed"}
    received = data.pop("hash", "")
    if not received:
        return {"ok": False, "reason": "no_hash"}
    check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        return {"ok": False, "reason": "bad_hash"}
    try:
        auth_date = int(data.get("auth_date", "0"))
    except ValueError:
        auth_date = 0

    # The signature already proves Telegram issued this for this user; age only
    # bounds how long a captured header could be replayed, which requires
    # already having the customer's device or traffic. A day was short enough
    # that anyone who left the app open overnight — or whose client restored a
    # cached webview, which does NOT re-issue initData — came back to a refusal
    # they could do nothing about. A week keeps the replay window sane and
    # removes the failure they were actually hitting.
    limit = MAX_INIT_DATA_AGE if max_age_sec is None else max_age_sec
    age = int(time.time()) - auth_date if auth_date else 0
    if limit and auth_date and age > limit:
        return {"ok": False, "reason": "expired", "age": age, "limit": limit}
    user = {}
    if data.get("user"):
        try:
            user = json.loads(data["user"])
        except Exception:
            user = {}
    if not user.get("id"):
        return {"ok": False, "reason": "no_user"}
    return {"ok": True, "user": user, "auth_date": auth_date, "age": age}


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
