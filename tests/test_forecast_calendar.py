"""The weekly / Jalali-cycle forecast and the guards that keep its accuracy honest.

Plain `python tests/test_forecast_calendar.py`.

What is being protected:
  * The Persian-calendar pay cycle is LEARNED from the history handed in —
    never assumed — is exactly neutral when there is too little history, and
    only reshapes a month (factors average 1.0).
  * One bulk-reseller day cannot set the level (extreme days are capped).
  * A challenger cannot overrule the default on overlapping evidence: 28
    origins of a 30-day horizon are ~1 independent month. On the live data,
    letting that switch happen cost ~12 points of 30-day accuracy.
  * "accuracy_pct" is exactly 100 − WAPE, and the band is symmetric around the
    forecast, so neither can quietly flatter the model.
"""
import os
import random
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.forecast as F  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAILED = []


def check(label, got, want):
    ok = got == want
    print(("  PASS  " if ok else "  FAIL  ") + label + f"   got={got!r} want={want!r}")
    if not ok:
        FAILED.append(label)


def check_true(label, got):
    check(label, bool(got), True)


def cycle_series(n=120, seed=11, late=0.78, mid=1.2):
    """Revenue with a planted Jalali pay cycle, weekday shape and noise."""
    rnd = random.Random(seed)
    start = date(2026, 5, 30)
    dow = {0: .9, 1: .9, 2: 1.15, 3: 1.0, 4: .87, 5: 1.23, 6: .95}
    factor = {0: 1.0, 1: mid, 2: late}
    rev, cnt, days = [], [], []
    for i in range(n):
        d = start + timedelta(days=i)
        v = 1_400_000 * factor[F._month_third(d)] * dow[d.weekday()] * rnd.uniform(.85, 1.15)
        rev.append(round(v)); cnt.append(max(1, round(v / 170_000))); days.append(d)
    return rev, cnt, days


def main():
    print("\n1. Jalali month thirds are computed on the real calendar")
    check("1 Mehr 1405 (2026-09-23) is early", F._month_third(date(2026, 9, 23)), 0)
    check("15 Mehr (2026-10-07) is mid", F._month_third(date(2026, 10, 7)), 1)
    check("25 Mehr (2026-10-17) is late", F._month_third(date(2026, 10, 17)), 2)
    check("31 Shahrivar (2026-09-22) is late", F._month_third(date(2026, 9, 22)), 2)

    print("\n2. the pay cycle is learned, neutral when unknowable, and only reshapes")
    rev, cnt, days = cycle_series()
    flat = F._month_factors(rev[:20], days[:20])
    check("under four weeks of history: exactly neutral", flat, {0: 1.0, 1: 1.0, 2: 1.0})
    mf = F._month_factors(rev, days)
    check_true("a planted month-end dip is found (late < 1 < mid)", mf[2] < 1 < mf[1])
    check_true("factors average 1.0, so the month's total is untouched",
               abs(sum(mf.values()) / 3 - 1) < 1e-9)
    check_true("shrinkage keeps the learned dip milder than the planted one",
               0.78 < mf[2] < 1.0)

    print("\n3. one bulk-reseller day cannot set the level")
    steady = [1_000_000.0] * 28
    d28 = days[:28]
    base = F._weekly_level(steady, d28)
    spiked = list(steady); spiked[-3] = 60_000_000.0
    check("steady level", round(base), 1_000_000)
    check_true("a 60x day moves the level by under 1%",
               abs(F._weekly_level(spiked, d28) - base) / base < 0.01)
    check_true("the cap is a multiple of the median day, not a fixed number",
               max(F._winsorize(spiked)) == 1_000_000.0 * F.WINSOR)

    print("\n4. a challenger needs independent evidence to overrule the default")
    ev30 = F._Evaluation(rev, cnt, days, 30, 1)
    model30, why30 = ev30.select(len(rev))
    check("30-day keeps the default", model30, F.DEFAULT_MODEL)
    check("…because its folds are ~1 independent month", why30.get("reason"),
          "insufficient_independent_validation")
    ev7 = F._Evaluation(rev, cnt, days, 7, 1)
    _, why7 = ev7.select(len(rev))
    check("7-day selection is allowed to run", why7.get("reason"), "historical_validation")

    print("\n5. the future cannot leak into a 30-day decision")
    changed = F._Evaluation(rev[:90] + [1e12] * 30, cnt[:90] + [1e6] * 30, days, 30, 1)
    check("same model with a poisoned future", changed.select(90), ev30.select(90))
    check_true("same prediction with a poisoned future",
               changed.predict(90, F.DEFAULT_MODEL) == ev30.predict(90, F.DEFAULT_MODEL))

    print("\n6. the reported numbers cannot flatter the model")
    f = F.forecast(rev, cnt, days, 7, skip_days=1)
    acc = f["accuracy"]
    check("accuracy_pct is exactly 100 - WAPE", acc["accuracy_pct"], round(100 - acc["wape"], 1))
    b = f["band"]
    check("band targets 80% coverage", b["target_coverage"], 80)
    check_true("band is symmetric around the forecast (unless clipped at zero)",
               b["low"] == 0 or abs((b["high"] - f["total"]) - (f["total"] - b["low"])) <= 1)
    check_true("band coverage was measured, not assumed", b["coverage_folds"] > 0)

    print("\n7. where the cycle exists, the calendar model pays for itself")
    check_true("7-day policy beats the old fixed model on a cycling series",
               f["versus_baseline"]["error_reduction_pct"] > 0)
    f30 = F.forecast(rev, cnt, days, 30, skip_days=1)
    check_true("30-day policy beats it too", f30["versus_baseline"]["error_reduction_pct"] > 0)
    check("the learned cycle is exposed for explanation",
          sorted(f["drivers"]["month_factors"]), ["early", "late", "mid"])

    print("\n8. a business closed some weekdays is not forecast at half its revenue")
    # Median orders/day is 0 when the shop is shut four days a week. A blend
    # partner built on that median forecast 0 and halved every total (benchmark
    # "closed", 30 days: sMAPE 4 -> 67). The partner must use the MEAN.
    cd = [date(2026, 1, 1) + timedelta(days=i) for i in range(125)]
    cc = [10.0 if d.weekday() < 3 else 0.0 for d in cd]
    cr = [c * 100_000 for c in cc]
    fc = F.forecast(cr[:90], cc[:90], cd[:90], 30, skip_days=1)
    actual = sum(cr[91:121])
    check_true("30-day total within 15% of what the open days earn",
               abs(fc["total"] - actual) / actual < 0.15)

    print("")
    if FAILED:
        print(f"FAILED: {len(FAILED)} -> {FAILED}")
        sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
