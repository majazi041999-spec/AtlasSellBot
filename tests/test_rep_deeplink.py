"""The recruitment post's button: ?start=rep must survive the channel gate.

Plain `python tests/test_rep_deeplink.py`.

What is being protected: the post is published to channels and can only carry a
URL button, so the deeplink IS the call to action. Its reader has typically never
opened the bot and is not in our channel — which means the very first thing that
happens to them is the join gate swallowing the message that carried the payload.
If the destination is not held across that gate, the button silently degrades to
"open the retail menu" for the entire audience the post was written for, and
nothing anywhere would report it as broken.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("BOT_TOKEN", "")

from bot.handlers.common import START_DESTINATIONS  # noqa: E402
from bot.middlewares import channel_required as cr  # noqa: E402

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


class FakeMessage:
    """Only the attribute remember_start reads. A real aiogram Message needs a
    chat, a date and a bot session; none of that is part of what is under test."""

    def __init__(self, text):
        self.text = text


def remembered(uid, text):
    cr._PENDING_START.pop(uid, None)
    cr.ChannelRequiredMiddleware.remember_start(uid, FakeMessage(text))
    return cr._PENDING_START.get(uid)


print("\nwhat the gate holds on to")
check("the post's deeplink", remembered(1, "/start rep"), "rep")
check("with the bot's @name", remembered(1, "/start@atlas_account_bot rep"), "rep")
check("a referral code is NOT a destination", remembered(1, "/start A1B2C3D4"), None)
check("a bare /start", remembered(1, "/start"), None)
check("an unknown payload", remembered(1, "/start giveaway"), None)
check("not a start command at all", remembered(1, "rep"), None)
check("no text (a photo, a sticker)", remembered(1, None), None)
check("no user id", remembered(0, "/start rep"), None)

print("\nit is consumed once")
cr._PENDING_START.clear()
cr.ChannelRequiredMiddleware.remember_start(7, FakeMessage("/start rep"))
check("stored", cr._PENDING_START.get(7), "rep")
check("popped by the resume", cr._PENDING_START.pop(7, None), "rep")
check("nothing left behind", cr._PENDING_START.get(7), None)

print("\nthe two ends agree")
check("rep is a known destination", "rep" in START_DESTINATIONS, True)

print("\n" + ("ALL PASSED" if not FAILED else f"FAILED: {FAILED}"))
sys.exit(1 if FAILED else 0)
