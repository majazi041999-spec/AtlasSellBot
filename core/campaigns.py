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
    get_abandoned_carts,
    get_lapsed_users_for_winback,
    get_segment_users,
    get_setting,
    get_trial_followups,
    log_campaign_event,
    mark_cart_reminder,
    mark_custom_campaign_sent,
    mark_trial_followup_sent,
    mark_winback_sent,
    user_has_campaign_event,
)
from core.panel_content import SETTINGS_DEFAULTS

logger = logging.getLogger(__name__)


def _fmt_toman(v) -> str:
    try:
        return f"{int(float(v)):,}"
    except (TypeError, ValueError):
        return str(v)

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


async def run_custom_campaign(bot, camp: dict) -> dict:
    """Send a targeted (panel-authored) campaign to its segment.

    Each user gets the campaign at most once ever (campaign_events guards
    re-sends), so re-running after adding users to a segment is safe. A photo is
    sent as the DM image; Telegram caps captions at 1024 chars, so longer
    messages go as a follow-up text bubble."""
    import base64

    from aiogram.types import BufferedInputFile

    slug = str(camp.get("slug") or "").strip()
    template = str(camp.get("message") or "")
    if not slug or not template.strip():
        return {"sent": 0, "skipped": 0}
    brand = await get_setting("ui.brand_name", "Atlas Account")
    code = str(camp.get("code") or "").strip()

    photo_bytes = b""
    photo = str(camp.get("photo") or "")
    if photo.startswith("data:") and "," in photo:
        try:
            photo_bytes = base64.b64decode(photo.split(",", 1)[1])
        except Exception:
            photo_bytes = b""

    sent = skipped = 0
    include_reps = bool(int(camp.get("include_reps") or 0))
    for u in await get_segment_users(str(camp.get("segment") or "all"), include_reps=include_reps):
        uid = int(u.get("id") or 0)
        tid = int(u.get("telegram_id") or 0)
        if not tid or await user_has_campaign_event(slug, uid):
            skipped += 1
            continue
        values = {"brand": brand, "code": code,
                  "name": (u.get("full_name") or "").strip()[:20] or "دوست عزیز"}
        try:
            text = template.format(**values)
        except Exception:
            text = template
        try:
            if photo_bytes:
                img = BufferedInputFile(photo_bytes, filename="campaign.jpg")
                if len(text) <= 1024:
                    await bot.send_photo(tid, img, caption=text, parse_mode=None)
                else:
                    await bot.send_photo(tid, img)
                    await bot.send_message(tid, text, parse_mode=None)
            else:
                await bot.send_message(tid, text, parse_mode=None)
            sent += 1
            await log_campaign_event(slug, "sent", uid)
            await asyncio.sleep(0.08)
        except Exception:
            # Blocked the bot / deleted account — skip silently, don't mark.
            skipped += 1
    if camp.get("id"):
        await mark_custom_campaign_sent(int(camp["id"]), sent)
    logger.info("custom campaign %s sent=%s skipped=%s", slug, sent, skipped)
    return {"sent": sent, "skipped": skipped}


async def _cart_card_footer() -> str:
    """Card-to-card details appended to a recovery DM so it's self-contained."""
    card = (await get_setting("card_number", "")).strip()
    if not card:
        return ""
    bank = (await get_setting("card_bank", "")).strip()
    holder = (await get_setting("card_holder", "")).strip()
    lines = ["", "──────────", "💳 کارت واریز:"]
    if bank:
        lines.append(f"🏦 {bank}")
    lines.append(card)
    if holder:
        lines.append(f"👤 {holder}")
    return "\n".join(lines)


async def _send_cart_stage(bot, stage: int, template_key: str, min_age: str,
                           max_age: str, card_footer: str, limit: int = 200) -> int:
    """Send one recovery touch (stage 1 or 2) to everyone whose latest cart
    qualifies, then bump their stage so they aren't nudged for it again."""
    from bot.keyboards import payment_kb

    template = await get_setting(template_key, SETTINGS_DEFAULTS.get(template_key, ""))
    sent = 0
    for o in await get_abandoned_carts(stage, min_age, max_age, limit):
        tid = int(o.get("telegram_id") or 0)
        values = {
            "pkg": str(o.get("pkg_name") or "سرویس"),
            "price": _fmt_toman(o.get("price") or 0),
            "name": (o.get("full_name") or "").strip()[:20] or "دوست عزیز",
        }
        try:
            text = template.format(**values)
        except Exception:
            text = template
        text += card_footer
        if tid:
            try:
                await bot.send_message(tid, text, parse_mode=None,
                                       reply_markup=payment_kb(int(o["id"])))
                sent += 1
                await asyncio.sleep(0.1)
            except Exception:
                pass
        await mark_cart_reminder(int(o["user_id"]), stage)
        await log_campaign_event("cart_recovery", "sent", int(o["user_id"]))
    return sent


async def run_cart_recovery(bot) -> dict:
    """Recover abandoned carts: users who created an order but never paid.

    Two touches — a gentle reminder after ``delay1`` minutes, then a stronger one
    after ``delay2`` hours. Each unpaid order is nudged at most once per stage,
    and carts older than ``max_age`` are left alone (don't nag stale intent)."""
    if await get_setting("cart_recovery_enabled", "1") != "1":
        return {"sent": 0}
    try:
        delay1_min = max(1, int(await get_setting("cart_recovery_delay1_min", "30") or 30))
    except (TypeError, ValueError):
        delay1_min = 30
    try:
        delay2_hours = max(1, int(await get_setting("cart_recovery_delay2_hours", "6") or 6))
    except (TypeError, ValueError):
        delay2_hours = 6
    try:
        max_age_hours = max(1, int(await get_setting("cart_recovery_max_age_hours", "48") or 48))
    except (TypeError, ValueError):
        max_age_hours = 48

    now = datetime.now()
    fmt = "%Y-%m-%d %H:%M:%S"
    max_age = (now - timedelta(hours=max_age_hours)).strftime(fmt)
    stage1_cutoff = (now - timedelta(minutes=delay1_min)).strftime(fmt)
    stage2_cutoff = (now - timedelta(hours=delay2_hours)).strftime(fmt)
    card_footer = await _cart_card_footer()

    # Stage 2 first: a cart already past the second delay jumps straight to the
    # stronger message (and is then marked done), skipping a redundant stage-1 DM.
    sent2 = await _send_cart_stage(bot, 2, "cart_recovery_template2", stage2_cutoff, max_age, card_footer)
    sent1 = await _send_cart_stage(bot, 1, "cart_recovery_template1", stage1_cutoff, max_age, card_footer)
    total = sent1 + sent2
    if total:
        logger.info("cart recovery sent=%s (stage1=%s stage2=%s)", total, sent1, sent2)
    return {"sent": total}
