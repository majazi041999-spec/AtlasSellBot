"""The message a brand-new arrival gets: a discount code and the free trial.

WHY IT IS ITS OWN THING. The bot had campaigns for a trial that did not convert,
for a customer who drifted away, and for an abandoned cart — every stage except
the first one. Somebody who found the bot and pressed Start got a menu and
nothing else, at the single moment they are most willing to try something.

EXACTLY ONCE, AND ONLY FOR NEW PEOPLE. `welcome_gift_sent` on the user row is
the guard. It has to be a marker rather than "was this row just created",
because MenuRefreshMiddleware runs BEFORE the /start handler and creates the row
first — by the time the handler looks, everybody is an old user. Existing
customers were backfilled to 1 when the column appeared, so the gift can only
reach people who arrive after it was switched on.

OFF UNTIL A CODE EXISTS. `campaign_welcome_code` is empty by default and nothing
is sent while it is: a message promising a discount that the checkout then
rejects is worse than no message. The owner sets the code, and only then does
anyone hear about it.
"""
from __future__ import annotations

import logging

from core.database import get_setting, update_user

log = logging.getLogger(__name__)

SETTINGS = {
    "campaign_welcome_enabled": "1",
    "campaign_welcome_code": "",          # empty = feature is dormant
    "campaign_welcome_percent": "",       # shown in the text; blank hides the number
}


async def _cfg() -> dict:
    out = {}
    for k, default in SETTINGS.items():
        out[k] = (await get_setting(k, default) or "").strip()
    return out


async def build(user: dict) -> tuple:
    """Return (html, keyboard) for the welcome gift, or (None, None) to skip."""
    cfg = await _cfg()
    if cfg["campaign_welcome_enabled"] != "1" or not cfg["campaign_welcome_code"]:
        return None, None
    if int(user.get("welcome_gift_sent") or 0):
        return None, None

    from bot.rich_message import emoji as tg_emoji
    from bot.keyboards import _button
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    code = cfg["campaign_welcome_code"]
    pct = cfg["campaign_welcome_percent"]
    name = (user.get("full_name") or "").strip()[:20]

    trial_line = ""
    if await get_setting("test_account_enabled", "1") == "1":
        gb = await get_setting("test_account_traffic_gb", "1")
        days = await get_setting("test_account_duration_days", "1")
        trial_line = (
            f'\n{tg_emoji("trial", "🆓")} <b>اول رایگان امتحان کن</b>\n'
            f"یک اکانت تست {gb} گیگ برای {days} روز، همین حالا و بدون پرداخت. "
            "دکمه‌ی زیر را بزن.\n"
        )

    off = f" <b>{pct}٪ تخفیف</b>" if pct else " <b>تخفیف</b>"
    html = (
        f'{tg_emoji("brand", "🌐")} <b>خوش آمدی{" " + name if name else ""}!</b>\n'
        "━━━━━━━━━━━━━━\n"
        + trial_line +
        f'\n{tg_emoji("cart", "🛒")} <b>هدیه‌ی خوش‌آمد</b>\n'
        f"برای اولین خریدت{off} داری. موقع پرداخت این کد را بزن:\n"
        f"<code>{code}</code>\n"
        "\n<i>روی کد بزن تا کپی شود.</i>"
    )

    b = InlineKeyboardBuilder()
    if trial_line:
        _button(b, text="🆓 دریافت تست رایگان", callback_data="home:trial", style="success")
    _button(b, text="🛒 دیدن پکیج‌ها و قیمت‌ها", callback_data="home:buy", style="danger")
    b.adjust(1)
    return html, b.as_markup()


async def send(bot, chat_id: int, user: dict) -> bool:
    """Send it once. Marks the user BEFORE sending, so a failure cannot turn
    into the same person being welcomed on every /start they ever press."""
    html, kb = await build(user)
    if not html:
        return False
    await update_user(int(user["id"]), welcome_gift_sent=1)
    try:
        await bot.send_message(chat_id, html, parse_mode="HTML", reply_markup=kb)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("welcome gift not delivered to %s: %s", chat_id, exc)
        return False
