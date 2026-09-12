"""Rejecting an order: the reason flow and the atomic transition.

Plain `python tests/test_reject_order.py`.

What is being protected:
  * The reject is a SINGLE conditional UPDATE, so two admins (or an admin who
    rejects an order another admin already approved) can't both take effect —
    exactly one caller wins and an approved order can never be flipped to
    rejected underneath a fulfilment that is already running.
  * When a reason is given it reaches the buyer verbatim; «رد بدون اطلاع» sends
    the buyer nothing.
  * The approve/reject buttons are taken off EVERY admin's copy of the review
    message once the order is decided, not just the one that was pressed.
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WORKDIR = tempfile.mkdtemp(prefix="atlas-reject-")
os.chdir(_WORKDIR)
os.environ.setdefault("BOT_TOKEN", "")

from core.database import (  # noqa: E402
    init_db,
    get_or_create_user,
    add_package,
    create_order,
    update_order,
    get_order,
    reject_order_if_reviewable,
    add_review_message,
    get_review_messages,
)
from bot.handlers.admin import _finalize_rejection, _clear_order_review_kbs  # noqa: E402

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


class FakeBot:
    """Records what the handler tried to do instead of hitting Telegram."""

    def __init__(self):
        self.sent = []      # (chat_id, text)
        self.cleared = []   # (chat_id, message_id) markup removals

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))

    async def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None):
        # Telegram would reject a non-None markup here in real life; we only ever
        # pass None. Record the clear.
        assert reply_markup is None
        self.cleared.append((chat_id, message_id))


async def _make_reviewable_order(tid, pkg_id):
    """A buyer with an order sitting at the reviewable status."""
    u = await get_or_create_user(tid, f"u{tid}", f"User {tid}")
    oid = await create_order(u["id"], pkg_id)
    await update_order(oid, status="receipt_submitted")
    return u, oid


async def main():
    await init_db()
    pkg = await add_package("تست", 20, 30, 100000)

    print("\nthe atomic transition")
    _, oid = await _make_reviewable_order(7001, pkg)
    check("reviewable order rejects once", await reject_order_if_reviewable(oid, "دلیل"), True)
    o = await get_order(oid)
    check("...status is now rejected", o["status"], "rejected")
    check("...reason stored in notes", "reject: دلیل" in (o["notes"] or ""), True)
    check("second reject is refused (no double-decision)", await reject_order_if_reviewable(oid, "again"), False)

    print("\ncannot reject what was already approved")
    _, oid2 = await _make_reviewable_order(7002, pkg)
    await update_order(oid2, status="approved")
    check("approved order refuses rejection", await reject_order_if_reviewable(oid2, "nope"), False)
    check("...and stays approved", (await get_order(oid2))["status"], "approved")

    print("\ncannot reject an order still awaiting its receipt")
    _, oid3 = await _make_reviewable_order(7003, pkg)
    await update_order(oid3, status="pending_payment")
    check("pending order refuses rejection", await reject_order_if_reviewable(oid3), False)
    check("...and is untouched", (await get_order(oid3))["status"], "pending_payment")

    print("\nreason flow reaches the buyer and clears every admin copy")
    buyer, oid4 = await _make_reviewable_order(7004, pkg)
    # Two admins each hold a copy of the review message.
    await add_review_message("order", oid4, 111, 5001)
    await add_review_message("order", oid4, 222, 5002)
    bot = FakeBot()
    ok = await _finalize_rejection(bot, oid4, "کیفیت فیش نامشخص بود")
    check("finalize with reason succeeds", ok, True)
    check("...order rejected", (await get_order(oid4))["status"], "rejected")
    check("...exactly one message to the buyer", len(bot.sent), 1)
    check("...sent to the buyer's telegram id", bot.sent[0][0], 7004)
    check("...containing the reason", "کیفیت فیش نامشخص بود" in bot.sent[0][1], True)
    check("...buttons cleared on BOTH admin copies", sorted(bot.cleared), [(111, 5001), (222, 5002)])

    print("\nsilent reject notifies nobody")
    _, oid5 = await _make_reviewable_order(7005, pkg)
    await add_review_message("order", oid5, 333, 6001)
    bot2 = FakeBot()
    ok = await _finalize_rejection(bot2, oid5, None)
    check("finalize with no reason succeeds", ok, True)
    check("...order rejected", (await get_order(oid5))["status"], "rejected")
    check("...NO message sent to the buyer", len(bot2.sent), 0)
    check("...no 'reject:' note added", "reject:" in ((await get_order(oid5))["notes"] or ""), False)
    check("...buttons still cleared", bot2.cleared, [(333, 6001)])

    print("\nfinalize on an already-decided order is a no-op that reports failure")
    bot3 = FakeBot()
    ok = await _finalize_rejection(bot3, oid5, "دوباره")
    check("second finalize refused", ok, False)
    check("...and sent nothing", len(bot3.sent), 0)

    print("\n_clear_order_review_kbs tolerates a copy Telegram refuses to edit")
    _, oid6 = await _make_reviewable_order(7006, pkg)
    await add_review_message("order", oid6, 444, 7001)

    class HalfBrokenBot(FakeBot):
        async def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None):
            raise RuntimeError("message can't be edited")

    # Must not raise even when every edit fails.
    await _clear_order_review_kbs(HalfBrokenBot(), oid6)
    check("survives an un-editable review message", True, True)

    print("")
    if FAILED:
        print(f"FAILED: {len(FAILED)} -> {FAILED}")
        sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    asyncio.run(main())
