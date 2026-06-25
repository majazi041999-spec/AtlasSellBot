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
from typing import Dict, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core.config import ADMIN_IDS, REFERRAL_BONUS_GB
from core.database import (
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


async def referral_per_referral_gb() -> float:
    """The fixed GB credited to the inviter per first-time converted referral."""
    try:
        return max(0.0, float(await get_setting("referral_per_referral_gb", str(REFERRAL_BONUS_GB))))
    except (TypeError, ValueError):
        return float(REFERRAL_BONUS_GB)


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
    if str(tier.get("reward_kind")) == "service":
        if int(tier.get("is_unlimited") or 0) or float(tier.get("reward_gb") or 0) <= 0:
            vol = "نامحدود"
        else:
            vol = f"{float(tier.get('reward_gb') or 0):g}GB"
        days = int(tier.get("duration_days") or 0)
        days_txt = f"{days} روزه" if days > 0 else "بدون محدودیت زمان"
        return f"سرویس هدیه ({vol} / {days_txt})"
    return f"{float(tier.get('reward_gb') or 0):g}GB حجم هدیه"


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

    per = await referral_per_referral_gb()
    if per > 0:
        await update_user(referrer["id"], referral_bonus_gb=float(referrer.get("referral_bonus_gb") or 0) + per)
        if bot:
            try:
                await bot.send_message(
                    referrer["telegram_id"],
                    f"🎁 یکی از دعوت‌شده‌های شما خرید کرد!\n{per:g}GB به اعتبار هدیهٔ شما اضافه شد.",
                    parse_mode=None,
                )
            except Exception:
                pass

    try:
        await check_referral_tiers(bot, int(referrer["id"]))
    except Exception as e:
        logger.warning("referral tier check failed referrer=%s: %s", referrer.get("id"), e)
