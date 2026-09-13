"""Historical renewal rate — the metric the AI analyst was always shown as null.

Plain `python tests/test_renewal_rate.py`.

What is being protected: the rate is measured per PAID PERIOD off the orders
table, because a renewal overwrites the profile's expiry and the profile row
alone cannot tell a loyal customer from a lapsed one. The traps are all in the
windowing — a sub that expired yesterday must not be scored as churned before
its owner had a fair chance to renew, a win-back after a long gap must not be
counted as a renewal, and a multi-renewal history must contribute one decision
per period, not one per customer.
"""
import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WORKDIR = tempfile.mkdtemp(prefix="atlas-renewrate-")
os.chdir(_WORKDIR)
os.environ.setdefault("BOT_TOKEN", "")

from core.database import (  # noqa: E402
    init_db,
    get_or_create_user,
    add_package,
    create_order,
    update_order,
    create_subscription_profile,
    get_renewal_rate,
)

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


def _dt(days_ago):
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


async def _approved(uid, pkg, days_ago, duration, renew_pid=0):
    """An approved order dated `days_ago` days back, running `duration` days."""
    oid = await create_order(uid, pkg)
    await update_order(oid, status="approved", approved_at=_dt(days_ago),
                       duration_snapshot=duration, renew_sub_profile_id=renew_pid)
    return oid


async def _sub(uid, init_order_id, tok, dur):
    return await create_subscription_profile(
        uid, init_order_id, tok, f"{tok}@atlas", traffic_gb=10,
        duration_days=dur, expire_timestamp=0)


async def main():
    await init_db()
    pkg = await add_package("تست", 10, 30, 100000)
    uid = (await get_or_create_user(8001, "buyer", "Buyer"))["id"]

    print("\nempty history reads as null, not zero")
    r = await get_renewal_rate(90, 14)
    check("no matured periods -> pct is None", r["renewal_rate_pct"], None)
    check("...and decisions is 0", r["decisions"], 0)

    # A — renewed on time: period ends 30d ago, renewal 31d ago (within grace).
    a_init = await _approved(uid, pkg, 60, 30)
    a = await _sub(uid, a_init, "A", 30)
    await _approved(uid, pkg, 31, 30, renew_pid=a)   # renewal period ends ~1d ago -> not yet judged
    r = await get_renewal_rate(90, 14)
    check("A alone -> 1 decision", r["decisions"], 1)
    check("A alone -> 1 renewed", r["renewed"], 1)
    check("A alone -> 100%", r["renewal_rate_pct"], 100.0)

    # B — churned: period ends 20d ago, no renewal.
    b_init = await _approved(uid, pkg, 50, 30)
    await _sub(uid, b_init, "B", 30)
    r = await get_renewal_rate(90, 14)
    check("A+B -> 2 decisions", r["decisions"], 2)
    check("A+B -> 1 renewed", r["renewed"], 1)
    check("A+B -> 50%", r["renewal_rate_pct"], 50.0)

    # C — expired only 5 days ago: too recent to judge, must be excluded.
    c_init = await _approved(uid, pkg, 35, 30)   # ends 5d ago < grace(14)
    await _sub(uid, c_init, "C", 30)
    r = await get_renewal_rate(90, 14)
    check("recent expiry is not yet a decision", r["decisions"], 2)
    check("...renewed unchanged", r["renewed"], 1)

    # D — ended 170d ago: older than the 90+14 window, excluded.
    d_init = await _approved(uid, pkg, 200, 30)   # ends 170d ago
    await _sub(uid, d_init, "D", 30)
    r = await get_renewal_rate(90, 14)
    check("out-of-window expiry excluded", r["decisions"], 2)

    # E — two renewals then churn: three periods, first two renewed, last not.
    e_init = await _approved(uid, pkg, 120, 30)   # p1 ends 90d ago
    e = await _sub(uid, e_init, "E", 30)
    await _approved(uid, pkg, 88, 30, renew_pid=e)   # p2 ends 58d ago, renews p1
    await _approved(uid, pkg, 57, 30, renew_pid=e)   # p3 ends 27d ago, renews p2; p3 itself not renewed
    r = await get_renewal_rate(90, 14)
    check("A+B+E -> 5 decisions", r["decisions"], 5)
    check("A+B+E -> 3 renewed (E adds 2)", r["renewed"], 3)
    check("A+B+E -> 60%", r["renewal_rate_pct"], 60.0)

    print("\nwin-back after a long gap is NOT a renewal")
    # F — period ends 60d ago; the only 'later' order is 20d ago, far past grace.
    f_init = await _approved(uid, pkg, 90, 30)   # p1 ends 60d ago
    f = await _sub(uid, f_init, "F", 30)
    await _approved(uid, pkg, 20, 30, renew_pid=f)   # 40 days after p1 ended -> gap
    r = await get_renewal_rate(90, 14)
    check("F adds a decision", r["decisions"], 6)
    check("...but not a renewal (gap > grace)", r["renewed"], 3)

    print("")
    if FAILED:
        print(f"FAILED: {len(FAILED)} -> {FAILED}")
        sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    asyncio.run(main())
