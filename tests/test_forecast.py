"""Revenue forecasting — does it actually beat the line it replaced?

Plain `python tests/test_forecast.py` — no test framework, because the project
has none and this needs to stay runnable on the server.

What is being protected here. "Better forecast" is the kind of claim that decays
silently: someone tunes a constant, the number still looks plausible on the
dashboard, and nobody notices it got worse. So the central test is not that the
output is pretty — it is a rolling-origin backtest on data carrying the same
three pathologies as the real business, asserting the model beats an ordinary
least-squares line by a wide margin.

The pathologies, all measured from the live database:
  * a regime change inside the history (launch week ~8.5M/day decaying to ~1.3M)
  * heavy right skew from bulk reseller orders (median 1.39M, max 12.99M)
  * real weekly seasonality (Sat x1.31, Tue x0.83)

The other tests cover the ways this can be wrong while still returning numbers:
claiming accuracy it has not measured, inventing a weekday pattern from one
observation, letting a single 13M order set every future day's price, and
dividing by zero on a business that has not sold anything yet.
"""
import os
import random
import statistics as st
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.forecast import (  # noqa: E402
    MIN_HISTORY, WINDOW, _trimmed_basket, _weekday_factors, compare_to_line, forecast,
)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAILED = []


def check(label, got, want):
    ok = got == want
    print(f"   {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f"  (expected {want!r})"))
    if not ok:
        FAILED.append(label)


def check_true(label, got):
    check(label, bool(got), True)


def synth(n=95, seed=7):
    """Revenue with the live data's three pathologies, so the comparison means
    something. Deterministic, so a regression is a real regression."""
    rnd = random.Random(seed)
    # Sat/Sun busy (Iranian work week), Tue quiet — matches the measured factors.
    dow = {0: .89, 1: .83, 2: 1.14, 3: .92, 4: .87, 5: 1.31, 6: 1.18}
    start = date(2026, 5, 28)
    rev, cnt, days = [], [], []
    for i in range(n):
        d = start + timedelta(days=i)
        # Launch spike decaying over the first ~3 weeks, then a flat baseline.
        level = 7.0 * (0.82 ** i) + 7.0
        c = max(0, int(rnd.gauss(level * dow[d.weekday()], 2)))
        basket = 165_000
        r = c * basket * rnd.uniform(.7, 1.3)
        if rnd.random() < 0.04:            # a bulk reseller order lands
            r += rnd.uniform(4e6, 1.1e7)
            c += rnd.randint(1, 3)
        rev.append(round(r)); cnt.append(c); days.append(d)
    return rev, cnt, days


def main():
    print("1. it beats the ordinary least-squares line it replaced")
    rev, cnt, days = synth()
    for horizon in (7, 30):
        cmp = compare_to_line(rev, cnt, days, horizon)
        check_true(f"{horizon}-day comparison was computable", cmp is not None)
        print(f"      {horizon}d: line {cmp['linear_smape']}%  ->  model "
              f"{cmp['this_model_smape']}%   ({cmp['error_reduction_pct']}% less error, "
              f"{cmp['folds']} folds)")
        check_true(f"{horizon}-day error is at least 25% lower than the line",
                   cmp["error_reduction_pct"] >= 25)
        check_true(f"{horizon}-day model beats the line outright",
                   cmp["this_model_smape"] < cmp["linear_smape"])

    print("\n2. it reports the accuracy it actually measured")
    f = forecast(rev, cnt, days, 7)
    check_true("forecast succeeded", f["ok"])
    check_true("accuracy is reported", f["accuracy"] is not None)
    check_true("measured over real folds", f["accuracy"]["folds"] >= 8)
    check_true("sMAPE is a plausible percentage", 0 < f["accuracy"]["smape"] < 200)
    check("one point per day of horizon", len(f["points"]), 7)
    check("total matches the points", f["total"],
          sum(p["revenue"] for p in f["points"]))
    check_true("the band brackets the point forecast",
               f["band"]["low"] <= f["total"] <= f["band"]["high"])

    print("\n3. short history refuses to pretend")
    # The failure mode this blocks: three days of data yielding a confident
    # monthly projection that an owner then plans around.
    short = forecast(rev[:5], cnt[:5], days[:5], 7)
    check("flagged as not a forecast", short["ok"], False)
    check("…with the reason", short["reason"], "not_enough_history")
    check("no accuracy is claimed", short["accuracy"], None)
    check("no band is claimed", short["band"], None)
    check_true("but it still answers with something usable", len(short["points"]) == 7)
    check_true("and says how much history it needs", short["needed_days"] == MIN_HISTORY)

    print("\n4. a brand-new business does not divide by zero")
    zeros = [0.0] * 40
    zc = [0] * 40
    zd = [date(2026, 1, 1) + timedelta(days=i) for i in range(40)]
    z = forecast(zeros, zc, zd, 7)
    check("total is zero, not a crash", z["total"], 0)
    check_true("every point is zero", all(p["revenue"] == 0 for p in z["points"]))

    print("\n5. weekday factors are learned, not invented")
    factors = _weekday_factors(cnt, days)
    check("one factor per weekday", len(factors), 7)
    avg = sum(factors.values()) / 7
    check_true("they average ~1.0 so they only reshape, never inflate", 0.95 <= avg <= 1.05)
    check_true("Saturday is busier than Tuesday", factors[5] > factors[1])
    # A weekday seen once must not become a pattern.
    two_weeks = days[:9]
    thin = _weekday_factors(cnt[:9], two_weeks)
    seen_once = [i for i in range(7) if sum(1 for d in two_weeks if d.weekday() == i) < 2]
    check_true("a weekday with a single observation stays neutral",
               all(thin[i] == 1.0 for i in seen_once))

    print("\n6. one bulk order does not reprice every future day")
    base_rev = [1_000_000.0] * 30
    base_cnt = [10.0] * 30
    normal = _trimmed_basket(base_rev, base_cnt)
    spiked = list(base_rev)
    spiked[15] = 13_000_000.0            # the reseller order the live data has
    with_spike = _trimmed_basket(spiked, base_cnt)
    check("basket without the spike", int(normal), 100_000)
    check("the spike is trimmed away entirely", int(with_spike), 100_000)
    # And prove the mean would NOT have survived it, which is why it is trimmed.
    mean_basket = st.mean([r / c for r, c in zip(spiked, base_cnt)])
    check_true("a plain mean would have been dragged up", mean_basket > normal * 1.3)

    print("\n7. no trend term — measured, not assumed")
    # Both trend models scored WORSE than a flat level in backtest (Theil-Sen
    # 63.2% vs 27.5%). A steadily rising history must NOT produce a runaway
    # projection; it should stay near the recent level.
    rising = [float(500_000 + 30_000 * i) for i in range(60)]
    rc = [5.0] * 60
    rd = [date(2026, 1, 1) + timedelta(days=i) for i in range(60)]
    fr = forecast(rising, rc, rd, 30)
    recent_daily = st.median(rising[-WINDOW:])
    projected_daily = fr["total"] / 30
    check_true("the projection stays anchored to the recent level, not extrapolated",
               projected_daily <= recent_daily * 1.25)

    print("\n8. gaps must be zero-filled by the caller, and zeros are handled")
    # A missing day is a real zero-revenue day. If the caller dropped it instead,
    # the weekday factors would silently shift. Zeros must therefore be safe.
    gappy_rev = list(rev)
    gappy_cnt = list(cnt)
    for i in range(0, len(gappy_rev), 9):
        gappy_rev[i] = 0.0
        gappy_cnt[i] = 0
    g = forecast(gappy_rev, gappy_cnt, days, 7)
    check_true("still forecasts with many zero days", g["ok"])
    check_true("and stays non-negative", all(p["revenue"] >= 0 for p in g["points"]))

    print("\n9. the drivers are exposed so the number can be explained")
    d = f["drivers"]
    check_true("orders per day is reported", d["orders_per_day"] > 0)
    check_true("average basket is reported", d["avg_basket"] > 0)
    check("weekday factors are exposed", len(d["weekday_factors"]), 7)
    check("the window is the measured 28 days", d["window_days"], WINDOW)

    print("\n" + ("ALL PASSED" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}"))
    return 1 if FAILED else 0


sys.exit(main())
