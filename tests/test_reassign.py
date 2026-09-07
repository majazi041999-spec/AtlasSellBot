"""Handing a subscription to a different customer.

Plain `python tests/test_reassign.py`.

What is being protected: this moves a PAID service between two real people, and
the ways it can go wrong are all silent. Handing it to an id that never opened
the bot leaves a service whose owner can never be told it exists. Touching the
token would break the link the customer already installed. And the traffic and
expiry have to survive, or the buyer quietly loses what they paid for.
"""
import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WORKDIR = tempfile.mkdtemp(prefix="atlas-reassign-")
os.chdir(_WORKDIR)
os.environ.setdefault("BOT_TOKEN", "")

from core.database import (  # noqa: E402
    create_subscription_profile,
    get_or_create_user,
    get_subscription_profile,
    init_db,
)
from core.multi_subscription import reassign_subscription  # noqa: E402

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


async def main():
    await init_db()
    buyer = await get_or_create_user(9001, "buyer", "The Buyer")
    recipient = await get_or_create_user(9002, "recip", "The Recipient")
    future = int((time.time() + 20 * 86400) * 1000)
    pid = await create_subscription_profile(
        buyer["id"], 0, "tok-assign", "sub_9001_abc@atlas",
        traffic_gb=50, duration_days=30, expire_timestamp=future, name="نامحدود")
    before = await get_subscription_profile(pid)

    print("\nrefusing what cannot work")
    r = await reassign_subscription(pid, 999999, notify=False)
    check("id that never started the bot", r["ok"], False)
    check("...and says why", bool(r.get("error")), True)
    check("owner untouched after refusal",
          (await get_subscription_profile(pid))["user_id"], buyer["id"])
    r = await reassign_subscription(999999, 9002, notify=False)
    check("unknown service", r["ok"], False)

    print("\nthe handover")
    r = await reassign_subscription(pid, 9002, notify=False)
    check("ok", r["ok"], True)
    check("reports the old owner", r["from"]["telegram_id"], 9001)
    check("reports the new owner", r["to"]["telegram_id"], 9002)
    after = await get_subscription_profile(pid)
    check("owner moved", after["user_id"], recipient["id"])

    print("\nwhat the customer already installed must not change")
    check("token identical", after["token"], before["token"])
    check("email identical", after["email"], before["email"])
    check("traffic identical", after["traffic_gb"], before["traffic_gb"])
    check("expiry identical", after["expire_timestamp"], before["expire_timestamp"])
    check("usage identical", after["used_bytes"], before["used_bytes"])
    check("still active", after["is_active"], before["is_active"])

    print("\nassigning it again to the same person")
    r = await reassign_subscription(pid, 9002, notify=False)
    check("reported as a no-op", (r["ok"], r.get("unchanged")), (True, True))
    check("owner still the recipient",
          (await get_subscription_profile(pid))["user_id"], recipient["id"])

    print("\nand it can be handed back")
    r = await reassign_subscription(pid, 9001, notify=False)
    check("ok", r["ok"], True)
    check("owner is the buyer again",
          (await get_subscription_profile(pid))["user_id"], buyer["id"])

    print("\n" + ("ALL PASSED" if not FAILED else f"FAILED: {FAILED}"))
    return 1 if FAILED else 0


sys.exit(asyncio.run(main()))
