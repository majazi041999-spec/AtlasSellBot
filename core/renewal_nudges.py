"""The pre-expiry ladder: what we say to somebody whose service is running out.

There used to be exactly one warning, at three days left or 85% of the quota
spent. One message is easy to miss — it arrives while you are doing something
else, and by the time the service stops you have forgotten it existed. So the
same period now carries four, spaced so each one lands at a moment when the
answer to "should I do something?" has actually changed.

Two things keep that from turning into spam:

  * **A stage is sent once, ever.** `subscription_profiles.prewarn_sent` holds the
    highest rung already sent and only ever climbs, so a customer sitting at 76%
    for a fortnight hears nothing more until they cross the next rung. Renewal
    resets it to 0, which is what re-arms the ladder for the new period.
  * **Every rung is written twice** — once for running out of DAYS and once for
    running out of GIGABYTES. They are genuinely different situations: telling
    somebody with three weeks left that their service "ends tomorrow" because
    they burned through the traffic is how a reminder starts getting ignored.

The wording is deliberately mid-register: not chummy, not a bank letter. Each
rung reads differently from the last so that four messages feel like four
moments rather than one message sent four times.
"""
from typing import Dict, List, Optional, Tuple

# rung, days-left at or below, percent-used at or above
# The two thresholds are ORed: whichever the customer hits first.
STAGES: List[Tuple[int, int, int]] = [
    (1, 7, 75),
    (2, 3, 88),
    (3, 1, 95),
    (4, 0, 99),
]

MAX_STAGE = STAGES[-1][0]
# Loosest rung, for the query that decides who is even worth looking at.
ENTRY_DAYS = STAGES[0][1]
ENTRY_PERCENT = STAGES[0][2]

# {stage: {"time": ..., "quota": ...}} — HTML, run through premiumize() before
# sending. Placeholders are filled by the caller's existing template formatter.
MESSAGES: Dict[int, Dict[str, str]] = {
    1: {
        "time": (
            "📊 <b>یک هفته تا پایان سرویس</b>\n\n"
            "{service}\n"
            "تا <b>{expire_date}</b> فعال است · {remaining} از {total} باقی مانده\n\n"
            "عجله‌ای نیست، فقط خواستیم بدانی. هر وقت تمدید کنی همین سرویس ادامه "
            "پیدا می‌کند و لینکت عوض نمی‌شود."
        ),
        "quota": (
            "📊 <b>سه‌چهارم حجمت مصرف شده</b>\n\n"
            "{service}\n"
            "<b>{remaining}</b> از {total} باقی مانده\n\n"
            "با این روند احتمالاً قبل از پایان دوره حجمت تمام می‌شود. "
            "اگر خواستی از قبل تمدید کنی، از همین‌جا."
        ),
    },
    2: {
        "time": (
            "⏳ <b>سه روز تا پایان</b>\n\n"
            "{service} — تا <b>{expire_date}</b>\n"
            "باقی‌مانده: {remaining}\n\n"
            "تمدید الان یعنی سرویس بدون وقفه ادامه پیدا می‌کند؛ همان لینک، "
            "همان تنظیمات، بدون کار اضافه."
        ),
        "quota": (
            "⚡ <b>حجمت رو به اتمام است</b>\n\n"
            "{service}\n"
            "فقط <b>{remaining}</b> مانده\n\n"
            "وقتی حجم تمام شود سرویس قطع می‌شود، حتی اگر روزهایش هنوز باقی باشد."
        ),
    },
    3: {
        "time": (
            "🔔 <b>فردا سرویست تمام می‌شود</b>\n\n"
            "{service} · <b>{expire_date}</b>\n\n"
            "بعد از آن اتصال قطع می‌شود و لینک فعلی جواب نمی‌دهد. "
            "یک دکمه با تمدید فاصله داری."
        ),
        "quota": (
            "🔔 <b>کمتر از ۵ درصد حجمت مانده</b>\n\n"
            "{service} — <b>{remaining}</b>\n\n"
            "با این مقدار به این زودی‌ها نمی‌رسد. بهتر است همین حالا تمدیدش کنی."
        ),
    },
    4: {
        "time": (
            "⚠️ <b>امروز آخرین روز است</b>\n\n"
            "{service} امشب تمام می‌شود و اتصال قطع خواهد شد.\n\n"
            "تمدید از همین‌جا، بدون تغییر لینک."
        ),
        "quota": (
            "⚠️ <b>حجمت تقریباً تمام شد</b>\n\n"
            "{service} — فقط <b>{remaining}</b> مانده\n\n"
            "هر لحظه ممکن است قطع شود. تمدید یک دکمه است."
        ),
    },
}


def stage_for(days_left: Optional[int], used_percent: Optional[float]) -> Tuple[int, str]:
    """The highest rung this customer has reached, and why.

    Returns (0, "") when nothing applies. `reason` is "time" or "quota" — whichever
    rung was reached by a larger margin, so a service that is both nearly out of
    days and nearly out of traffic is described by whichever is actually biting.
    """
    best = 0
    reason = ""
    for stage, day_at, pct_at in STAGES:
        by_time = days_left is not None and days_left <= day_at
        by_quota = used_percent is not None and used_percent >= pct_at
        if not (by_time or by_quota):
            continue
        if stage >= best:
            best = stage
            if by_time and by_quota:
                # Both fired: describe the one further past its threshold.
                time_margin = (day_at - days_left) / max(1, day_at + 1)
                quota_margin = (used_percent - pct_at) / max(1.0, 100.0 - pct_at)
                reason = "time" if time_margin >= quota_margin else "quota"
            else:
                reason = "time" if by_time else "quota"
    return best, reason


def message_for(stage: int, reason: str) -> str:
    """The text for one rung. Falls back to the time wording, which reads sensibly
    even when the trigger was the quota — never returns empty."""
    rung = MESSAGES.get(int(stage) or 1) or MESSAGES[1]
    return rung.get(reason) or rung.get("time") or ""
