"""The reseller volume ladder — who is on it, and what it charges.

Plain `python tests/test_rep_tiers.py`, like the other tests here: no framework,
so it stays runnable on the server.

What is being protected: the ladder is advertised in the recruitment post, and
two of its properties are promises to real people that no reading of the code
makes obvious.

  * **Existing resellers must not be re-priced.** They agreed to a flat price.
    The ladder arriving in a deploy must not silently move any of them, not even
    to a cheaper rung — their price is a commercial agreement, not a default.
  * **A new reseller must land exactly on the advertised rung** for the number of
    active services their own panel shows them, or the post is a false quote.
"""
import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_WORKDIR = tempfile.mkdtemp(prefix="atlas-reptiers-")
os.chdir(_WORKDIR)
os.environ.setdefault("BOT_TOKEN", "")

from core import rep_tiers  # noqa: E402
from core.database import (  # noqa: E402
    create_subscription_profile,
    get_or_create_user,
    get_user_pricing,
    init_db,
    set_setting,
    update_user,
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


_SEQ = [0]


async def _services(user_id, n):
    """Give a reseller n live services, the way the panel counts them."""
    future = int((time.time() + 30 * 86400) * 1000)
    for _ in range(n):
        _SEQ[0] += 1
        i = _SEQ[0]
        await create_subscription_profile(
            user_id, 0, f"tok{i}", f"e{i}@atlas",
            traffic_gb=0, duration_days=30, expire_timestamp=future)


async def unlimited(user_id):
    return int((await get_user_pricing(user_id))["unlimited_price"])


async def main():
    await init_db()
    # A flat price exists, as it does in production — every assertion below is
    # about the ladder winning or losing against THIS number, not against zero.
    await set_setting("rep_price_per_gb", "3500")
    await set_setting("rep_unlimited_price", "195000")

    print("\nladder arithmetic")
    rungs = await rep_tiers.ladder()
    check("default ladder", rungs, [(0, 179000), (10, 169000), (30, 139000)])
    for active, want in [(0, 179000), (9, 179000), (10, 169000),
                         (29, 169000), (30, 139000), (400, 139000)]:
        check(f"price at {active} services", rep_tiers.price_for(rungs, active), want)
    check("next rung from 0", rep_tiers.next_rung(rungs, 0), (10, 169000))
    check("next rung from 25", rep_tiers.next_rung(rungs, 25), (5, 139000))
    check("next rung from 30", rep_tiers.next_rung(rungs, 30), None)

    print("\ngrandfathering")
    # An existing reseller: is_wholesale is set BEFORE the migration runs, which
    # is what the backfill keys off.
    old = await get_or_create_user(1001, "old", "Old Rep")
    await update_user(old["id"], is_wholesale=1)
    await set_setting("rep_tier_backfilled", "")   # let the guard re-arm
    import aiosqlite
    from core.database import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM settings WHERE key='rep_tier_backfilled'")
        await db.commit()
    await init_db()                                 # the deploy that adds the ladder
    fresh = await get_or_create_user(1001)
    check("existing reseller is exempt", int(fresh["rep_tier_exempt"]), 1)
    check("existing reseller keeps the flat price", await unlimited(old["id"]), 195000)
    await _services(old["id"], 40)
    check("...even at 40 services", await unlimited(old["id"]), 195000)

    print("\na reseller who joins after the ladder")
    new = await get_or_create_user(1002, "new", "New Rep")
    await update_user(new["id"], is_wholesale=1)
    fresh = await get_or_create_user(1002)
    check("new reseller is not exempt", int(fresh["rep_tier_exempt"]), 0)
    check("0 services", await unlimited(new["id"]), 179000)
    await _services(new["id"], 10)
    check("10 services", await unlimited(new["id"]), 169000)
    await _services(new["id"], 19)
    check("29 services", await unlimited(new["id"]), 169000)
    await _services(new["id"], 1)
    check("30 services", await unlimited(new["id"]), 139000)
    st = (await get_user_pricing(new["id"])).get("unlimited_tier") or {}
    check("pricing reports the rung", (st.get("active"), st.get("next")), (30, None))

    print("\nthe admin can still overrule one person")
    await update_user(new["id"], unlimited_price=125000)
    check("explicit price beats the ladder", await unlimited(new["id"]), 125000)
    await update_user(new["id"], unlimited_price=0)
    check("clearing it returns to the ladder", await unlimited(new["id"]), 139000)

    print("\nturning the ladder off")
    await rep_tiers.save([])
    check("empty ladder falls back to default", await rep_tiers.ladder(),
          [(0, 179000), (10, 169000), (30, 139000)])
    await set_setting("rep_unlimited_tiers", '[[0, 200000]]')
    check("owner can move the rungs", await unlimited(new["id"]), 200000)

    print("\nordinary customers are untouched")
    cust = await get_or_create_user(1003, "cust", "Customer")
    await _services(cust["id"], 50)
    check("no reseller flag, no ladder", await unlimited(cust["id"]), 0)

    print("\n" + ("ALL PASSED" if not FAILED else f"FAILED: {FAILED}"))
    return 1 if FAILED else 0


sys.exit(asyncio.run(main()))
