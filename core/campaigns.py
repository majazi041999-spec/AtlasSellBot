"""Automated sales campaigns: trial→paid conversion and win-back.

Each campaign DMs a targeted group a discount code, logs a 'sent' event for the
analytics dashboard, and marks the user so they're nudged only once. Conversions
and revenue are attributed automatically from redemptions of the campaign's
discount code (see get_campaign_overview)."""
import asyncio
import logging
import time
from datetime import datetime, timedelta

from core.database import (
    get_lapsed_users_for_winback,
    get_setting,
    get_trial_followups,
    log_campaign_event,
    mark_trial_followup_sent,
    mark_winback_sent,
)

logger = logging.getLogger(__name__)

_TRIAL_DEFAULT = (
    "👋 سلام! امیدوارم از تست رایگان {brand} راضی بوده باشی.\n\n"
    "برای اولین خریدت یک هدیه برات گذاشتیم:\n"
    "🎟️ کد تخفیف: {code}\n\n"
    "همین حالا با سرعت بالا و چند سرور پشتیبان، سرویس کامل بگیر. 🚀"
)
_WINBACK_DEFAULT = (
    "سلام 👋 جای تو توی {brand} خالیه!\n\n"
    "یک کد تخفیف ویژه برای بازگشتت آماده کردیم:\n"
    "🎟️ کد: {code}\n\n"
    "با همون سرعت و کیفیت قبل، دوباره وصل شو. منتظرتیم 🌟"
)


async def run_trial_to_paid(bot, limit: int = 200) -> dict:
    """When a free trial ends without a purchase, send a first-buy discount."""
    if await get_setting("campaign_trial_enabled", "1") != "1":
        return {"sent": 0}
    code = (await get_setting("campaign_trial_code", "")).strip()
    if not code:
        return {"sent": 0}
    try:
        dur = max(1, int(await get_setting("test_account_duration_days", "1") or 1))
    except (TypeError, ValueError):
        dur = 1
    cutoff = (datetime.now() - timedelta(days=dur)).strftime("%Y-%m-%d %H:%M:%S")
    template = await get_setting("campaign_trial_template", _TRIAL_DEFAULT)
    brand = await get_setting("ui.brand_name", "Atlas Account")
    sent = 0
    for u in await get_trial_followups(cutoff, limit):
        tid = int(u.get("telegram_id") or 0)
        values = {"brand": brand, "code": code, "name": (u.get("full_name") or "").strip()[:20] or "دوست عزیز"}
        try:
            text = template.format(**values)
        except Exception:
            text = template
        if tid:
            try:
                await bot.send_message(tid, text, parse_mode=None)
                sent += 1
                await asyncio.sleep(0.1)
            except Exception:
                pass
        await mark_trial_followup_sent(int(u["id"]))
        await log_campaign_event("trial2paid", "sent", int(u["id"]))
    if sent:
        logger.info("campaign trial2paid sent=%s", sent)
    return {"sent": sent}


async def run_winback(bot, limit: int = 200) -> dict:
    """DM users whose service ended a while ago a comeback discount."""
    if await get_setting("campaign_winback_enabled", "1") != "1":
        return {"sent": 0}
    code = (await get_setting("campaign_winback_code", "")).strip()
    if not code:
        return {"sent": 0}
    try:
        days = max(1, int(await get_setting("campaign_winback_days", "14") or 14))
    except (TypeError, ValueError):
        days = 14
    cutoff_ms = int(time.time() * 1000) - days * 86400000
    template = await get_setting("campaign_winback_template", _WINBACK_DEFAULT)
    brand = await get_setting("ui.brand_name", "Atlas Account")
    sent = 0
    for u in await get_lapsed_users_for_winback(cutoff_ms, limit):
        tid = int(u.get("telegram_id") or 0)
        values = {"brand": brand, "code": code, "name": (u.get("full_name") or "").strip()[:20] or "دوست عزیز"}
        try:
            text = template.format(**values)
        except Exception:
            text = template
        if tid:
            try:
                await bot.send_message(tid, text, parse_mode=None)
                sent += 1
                await asyncio.sleep(0.1)
            except Exception:
                pass
        await mark_winback_sent(int(u["id"]))
        await log_campaign_event("winback", "sent", int(u["id"]))
    if sent:
        logger.info("campaign winback sent=%s", sent)
    return {"sent": sent}
