"""Post-approval rewards: discount-code redemption + referral incentives.

Called from BOTH order-approval paths (the bot admin handler and the web
panel) so the logic stays identical. Referral has two layers:

  * a configurable fixed GB bonus credited to the inviter the first time an
    invited user makes an approved purchase, and
  * milestone tiers (e.g. 5 paying referrals -> 10GB, 10 -> 1-month unlimited)
    that, once reached, raise an admin-approval claim. The admin approves the
    claim from the bot, which then actually grants the GB/service.
"""
import logging
from datetime import datetime
from typing import Dict, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core.config import ADMIN_IDS, REFERRAL_BONUS_GB
from core.database import (
    add_user_balance,
    count_converted_referrals,
    count_user_code_redemptions,
    create_referral_claim,
    get_discount_code_by_code,
    get_referral_claim,
    get_referral_tiers,
    get_setting,
    get_user_by_id,
    get_user_referral_claim,
    record_discount_redemption,
    update_user,
)

logger = logging.getLogger(__name__)


def _fmt_toman(n: int) -> str:
    return f"{int(n or 0):,}"


async def referral_per_referral_amount() -> int:
    """Toman credited to the inviter's WALLET per first-time converted referral."""
    try:
        return max(0, int(float(await get_setting("referral_per_referral_amount", "0"))))
    except (TypeError, ValueError):
        return 0


async def referral_per_referral_gb() -> float:
    """Legacy GB-per-referral (kept for back-compat; defaults to 0/off)."""
    try:
        return max(0.0, float(await get_setting("referral_per_referral_gb", "0")))
    except (TypeError, ValueError):
        return 0.0


async def _admin_targets() -> list[int]:
    ids = set(int(a) for a in (ADMIN_IDS or []))
    try:
        owner = int(await get_setting("owner_admin_id", "0") or 0)
        if owner:
            ids.add(owner)
    except (TypeError, ValueError):
        pass
    return list(ids)


def referral_tier_reward_text(tier: Dict) -> str:
    """Human label of what a tier grants."""
    kind = str(tier.get("reward_kind"))
    if kind == "service":
        if int(tier.get("is_unlimited") or 0) or float(tier.get("reward_gb") or 0) <= 0:
            vol = "نامحدود"
        else:
            vol = f"{float(tier.get('reward_gb') or 0):g}GB"
        days = int(tier.get("duration_days") or 0)
        days_txt = f"{days} روزه" if days > 0 else "بدون محدودیت زمان"
        return f"سرویس هدیه ({vol} / {days_txt})"
    if kind == "gb":
        return f"{float(tier.get('reward_gb') or 0):g}GB حجم هدیه"
    return f"{_fmt_toman(int(tier.get('reward_amount') or 0))} تومان به کیف پول"


async def grant_referral_claim(claim_id: int, bot=None, reviewer_id: int = 0) -> Dict:
    """Grant a pending referral-tier claim (wallet / gb / gift service) and notify
    the user. Shared by the bot admin handler and the panel."""
    from core.database import get_referral_claim, update_referral_claim, get_user_by_id
    claim = await get_referral_claim(claim_id)
    if not claim or str(claim.get("status")) != "pending":
        return {"ok": False, "error": "already_reviewed"}
    user = await get_user_by_id(int(claim["user_id"]))
    if not user:
        return {"ok": False, "error": "user_not_found"}
    reward = referral_tier_reward_text(claim)
    kind = str(claim.get("reward_kind"))
    now_iso = datetime.now().isoformat()

    if kind == "service":
        from core.multi_subscription import create_profile_for_order
        traffic_gb = 0.0 if int(claim.get("is_unlimited") or 0) else float(claim.get("reward_gb") or 0)
        days = int(claim.get("duration_days") or 0)
        res = await create_profile_for_order(user, {"id": 0, "custom_config_name": "🎁 هدیه معرفی"}, traffic_gb, days)
        if not res.get("ok"):
            return {"ok": False, "error": "service_failed:" + str(res.get("error"))}
        await update_referral_claim(claim_id, status="approved", reviewed_at=now_iso)
        if bot:
            try:
                await bot.send_message(user["telegram_id"], f"🎁 هدیهٔ معرفی شما فعال شد!\n{reward}\n\nلینک اشتراک:\n{res['url']}", parse_mode=None)
            except Exception:
                pass
        return {"ok": True, "reward": reward, "url": res.get("url")}

    if kind == "wallet":
        amount = int(claim.get("reward_amount") or 0)
        new_bal = await add_user_balance(user["id"], amount, kind="referral", note=f"referral_tier:{claim_id}", actor_telegram_id=reviewer_id)
        await update_referral_claim(claim_id, status="approved", reviewed_at=now_iso)
        if bot:
            try:
                await bot.send_message(user["telegram_id"], f"🎉 جایزهٔ معرفی شما اعطا شد!\n💰 {_fmt_toman(amount)} تومان به کیف پولت اضافه شد.\nموجودی فعلی: {_fmt_toman(int(new_bal or 0))} تومان", parse_mode=None)
            except Exception:
                pass
        return {"ok": True, "reward": reward}

    gb = float(claim.get("reward_gb") or 0)
    await update_user(user["id"], referral_bonus_gb=float(user.get("referral_bonus_gb") or 0) + gb)
    await update_referral_claim(claim_id, status="approved", reviewed_at=now_iso)
    if bot:
        try:
            await bot.send_message(user["telegram_id"], f"🎁 هدیهٔ معرفی شما اعطا شد: {gb:g}GB به اعتبار هدیه‌تان اضافه شد.", parse_mode=None)
        except Exception:
            pass
    return {"ok": True, "reward": reward}


async def reject_referral_claim(claim_id: int, bot=None) -> Dict:
    from core.database import get_referral_claim, update_referral_claim, get_user_by_id
    claim = await get_referral_claim(claim_id)
    if not claim or str(claim.get("status")) != "pending":
        return {"ok": False, "error": "already_reviewed"}
    await update_referral_claim(claim_id, status="rejected", reviewed_at=datetime.now().isoformat())
    return {"ok": True}


async def record_order_discount(order: Dict) -> None:
    """Record a discount-code redemption for an approved order (idempotent-ish)."""
    code = (order.get("discount_code") or "").strip()
    amount = int(order.get("discount_amount") or 0)
    if not code or amount <= 0:
        return
    row = await get_discount_code_by_code(code)
    if not row:
        return
    try:
        await record_discount_redemption(int(row["id"]), int(order["user_id"]), int(order.get("id") or 0), amount)
    except Exception as e:
        logger.warning("discount redemption record failed order=%s code=%s: %s", order.get("id"), code, e)


async def _notify_admins_new_claim(bot, claim_id: int) -> None:
    claim = await get_referral_claim(claim_id)
    if not claim:
        return
    reward = referral_tier_reward_text(claim)
    name = (claim.get("full_name") or "").strip() or "—"
    uname = claim.get("username")
    uname_txt = f"@{uname}" if uname else "—"
    text = (
        "🎯 درخواست جدید هدیهٔ معرفی\n"
        "━━━━━━━━━━━━━━\n"
        f"کاربر: {name} ({uname_txt})\n"
        f"تعداد معرفی موفق: {int(claim.get('referrals_at_claim') or 0)}\n"
        f"پله: {int(claim.get('referrals_needed') or 0)} معرفی\n"
        f"هدیه: {reward}\n\n"
        "برای اعطا یا رد، یکی از دکمه‌ها را بزنید."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ اعطای هدیه", callback_data=f"refclaim_ok:{claim_id}"),
        InlineKeyboardButton(text="❌ رد", callback_data=f"refclaim_no:{claim_id}"),
    ]])
    for admin_id in await _admin_targets():
        try:
            await bot.send_message(admin_id, text, reply_markup=markup, parse_mode=None)
        except Exception:
            pass


async def check_referral_tiers(bot, referrer_id: int) -> int:
    """Create admin-approval claims for any newly reached milestone tiers."""
    if await get_setting("referral_enabled", "1") != "1":
        return 0
    tiers = await get_referral_tiers(active_only=True)
    if not tiers:
        return 0
    converted = await count_converted_referrals(referrer_id)
    created = 0
    for tier in tiers:
        if converted < int(tier.get("referrals_needed") or 0):
            continue
        if await get_user_referral_claim(referrer_id, int(tier["id"])):
            continue  # already pending/approved/rejected
        claim_id = await create_referral_claim(referrer_id, int(tier["id"]), converted)
        if claim_id:
            created += 1
            if bot:
                await _notify_admins_new_claim(bot, claim_id)
    return created


async def run_referral_reminders(bot, limit: int = 200) -> Dict:
    """Smart 24h nudge: if an invited friend hasn't bought after a day, ask the
    inviter to send them a special discount code (encourages the conversion)."""
    import asyncio
    from datetime import datetime, timedelta
    from core.database import get_pending_referral_reminders, mark_referral_reminder_sent

    if await get_setting("referral_enabled", "1") != "1":
        return {"sent": 0}
    if await get_setting("referral_reminder_enabled", "1") != "1":
        return {"sent": 0}
    code = (await get_setting("referral_reminder_code", "")).strip()
    if not code:
        return {"sent": 0}  # nothing to offer yet — don't burn the reminder flag

    brand = await get_setting("ui.brand_name", "Atlas Account")
    template = await get_setting(
        "referral_reminder_template",
        "👋 سلام! یکی از دوستانت که با لینک تو وارد {brand} شد، هنوز خرید نکرده.\n\n"
        "این کد تخفیف ویژه رو براش بفرست تا ترغیب بشه:\n🎟️ کد: {code}\n\nلینک دعوت تو:\n{link}",
    )
    try:
        me = await bot.get_me()
        username = me.username
    except Exception:
        username = ""
    cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    sent = 0
    for row in await get_pending_referral_reminders(cutoff, limit):
        tid = int(row.get("referrer_tid") or 0)
        link = f"https://t.me/{username}?start={row.get('referrer_code') or ''}" if username else ""
        name = (row.get("invitee_name") or "").strip() or (("@" + row["invitee_username"]) if row.get("invitee_username") else "دوستت")
        values = {"brand": brand, "code": code, "link": link, "name": name[:20]}
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
        await mark_referral_reminder_sent(int(row["invitee_id"]))
    if sent:
        logger.info("referral 24h reminders sent=%s", sent)
    return {"sent": sent}


async def apply_post_approval_rewards(bot, buyer: Dict, order: Dict, first_purchase: bool) -> None:
    """Run all reward side-effects after an order is approved.

    `first_purchase` must be captured BEFORE the order is flipped to approved
    (it means: this is the buyer's first ever approved order)."""
    await record_order_discount(order)

    if not first_purchase:
        return
    referred_by = order.get("referred_by") or buyer.get("referred_by")
    if not referred_by:
        return
    referrer = await get_user_by_id(int(referred_by))
    if not referrer or int(referrer["id"]) == int(buyer["id"]):
        return

    # Primary reward model: cash into the inviter's WALLET (usable in the bot).
    amount = await referral_per_referral_amount()
    if amount > 0:
        await add_user_balance(referrer["id"], amount, kind="referral",
                               note=f"referral:{buyer.get('id')}", actor_telegram_id=0)
        if bot:
            try:
                await bot.send_message(
                    referrer["telegram_id"],
                    "🎉 یکی از دوستانی که دعوت کردی خرید کرد!\n"
                    f"💰 {_fmt_toman(amount)} تومان جایزه به کیف پولت اضافه شد.\n"
                    "می‌تونی برای خرید یا تمدید سرویس از همین موجودی استفاده کنی.",
                    parse_mode=None,
                )
            except Exception:
                pass

    # Legacy GB bonus (only if explicitly configured; off by default).
    per = await referral_per_referral_gb()
    if per > 0:
        await update_user(referrer["id"], referral_bonus_gb=float(referrer.get("referral_bonus_gb") or 0) + per)

    try:
        await check_referral_tiers(bot, int(referrer["id"]))
    except Exception as e:
        logger.warning("referral tier check failed referrer=%s: %s", referrer.get("id"), e)
