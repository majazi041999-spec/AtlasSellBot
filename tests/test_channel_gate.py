"""The forced-channel gate — does pressing "بررسی عضویت" actually do anything?

Plain `python tests/test_channel_gate.py` — no test framework, matching the
other suites here so they stay runnable on the server.

WHAT IS BEING PROTECTED, and it is a whole class of bug, not one button.

aiogram 3 draws a hard line between OUTER middleware, which runs for every
update, and INNER middleware, which runs only after a handler has been MATCHED
by filters. `main.py` registers ChannelRequiredMiddleware with `.middleware()`,
i.e. inner. ChannelRequiredMiddleware answers the "بررسی عضویت" button itself,
so it looked complete — but no handler was ever bound to that callback data.
The router matched nothing, the inner middleware therefore never ran, and the
button was answered by NOBODY. The user joined the channel, pressed the button,
and got a spinner and silence; they had to send /start again — a command that
does have a handler — before the bot noticed.

That failure is invisible to any test that calls the middleware directly, which
is why this suite drives the REAL dispatcher with the REAL routers and asserts
on the Telegram API calls that come out the other end.
"""
import asyncio
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(tempfile.mkdtemp(prefix="atlas-channel-gate-"))

from aiogram import Dispatcher  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import CallbackQuery, Chat, Message, Update, User  # noqa: E402

from core.database import init_db, set_setting  # noqa: E402
from bot.middlewares import ChannelRequiredMiddleware  # noqa: E402
from bot.handlers import admin, common, user as user_h  # noqa: E402
from bot import nav  # noqa: E402

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


class FakeBot:
    """Records the Telegram calls the dispatcher tries to make."""
    id = 4242

    def __init__(self, status="member"):
        self.status = status
        self.calls = []

    async def get_chat_member(self, chat_id, user_id):
        self.calls.append(("get_chat_member", chat_id))
        outer = self

        class M:
            status = outer.status
            is_member = outer.status == "member"
        return M()

    async def __call__(self, method, *a, **k):
        name = type(method).__name__
        self.calls.append((name, getattr(method, "text", None)))
        return True

    @property
    def session(self):
        return None

    def kinds(self):
        return [c[0] for c in self.calls]


_DP = None


def build_dp():
    """Exactly what main.py builds, in the same order.

    Built once and reused: a Router can only ever be attached to one Dispatcher,
    and these are the real routers, not copies. That constraint is the point —
    testing against the actual wiring is what makes this catch a missing
    handler, which a hand-rolled router would not.
    """
    global _DP
    if _DP is None:
        _DP = Dispatcher(storage=MemoryStorage())
        _DP.include_router(nav.router)
        _DP.include_router(admin.router)
        _DP.include_router(user_h.router)
        _DP.include_router(common.router)
        _DP.message.middleware(ChannelRequiredMiddleware())
        _DP.callback_query.middleware(ChannelRequiredMiddleware())
    return _DP


def press_button(uid=90001):
    u = User(id=uid, is_bot=False, first_name="tester")
    c = Chat(id=uid, type="private")
    msg = Message(message_id=7, date=datetime.now(), chat=c, from_user=u, text="join prompt")
    cb = CallbackQuery(id="cb1", from_user=u, chat_instance="ci",
                       data="check_channel_join", message=msg)
    return Update(update_id=1, callback_query=cb)


async def main():
    await init_db()
    await set_setting("force_channel", "1")
    await set_setting("channel_username", "@atlaschannel")
    # The middleware exempts admins, which would skip the whole gate.
    await set_setting("owner_admin_id", "0")

    print("1. the button is answered at all")
    # The regression itself. Without a handler bound to this callback data the
    # inner middleware never runs and NOTHING comes back — the exact silence
    # the customer saw.
    dp, bot = build_dp(), FakeBot(status="member")
    await dp.feed_update(bot, press_button())
    check("the membership check actually ran", "get_chat_member" in bot.kinds(), True)
    check("the callback is answered, so the spinner stops",
          "AnswerCallbackQuery" in bot.kinds(), True)
    check("something is sent back to the user", "SendMessage" in bot.kinds(), True)

    print("\n2. a confirmed member gets the menu and a clean chat")
    check("the join prompt is removed", "DeleteMessage" in bot.kinds(), True)
    sent = [c[1] for c in bot.calls if c[0] == "SendMessage" and c[1]]
    check("the message says they are in", bool(sent and "تایید" in sent[0]), True)

    print("\n3. someone who has not joined is told so, not ignored")
    dp, bot = build_dp(), FakeBot(status="left")
    await dp.feed_update(bot, press_button(uid=90002))
    check("still answered, so the button never hangs",
          "AnswerCallbackQuery" in bot.kinds(), True)
    check("no menu is opened", "SendMessage" in bot.kinds(), False)
    check("and the prompt is left in place", "DeleteMessage" in bot.kinds(), False)

    print("\n4. the check is never served from a stale cache")
    # Someone presses the button precisely because their status just changed.
    # Answering from a cached "not a member" is the same silence with extra steps.
    dp, bot = build_dp(), FakeBot(status="left")
    await dp.feed_update(bot, press_button(uid=90003))
    before = bot.kinds().count("get_chat_member")
    bot.status = "member"
    await dp.feed_update(bot, press_button(uid=90003))
    check("Telegram is asked again on the second press",
          bot.kinds().count("get_chat_member") > before, True)
    check("and the second press lets them in", "SendMessage" in bot.kinds(), True)

    print("\n5. a stale button still answers once the requirement is lifted")
    await set_setting("force_channel", "0")
    dp, bot = build_dp(), FakeBot(status="left")
    await dp.feed_update(bot, press_button(uid=90004))
    check("the handler takes over and answers",
          "AnswerCallbackQuery" in bot.kinds(), True)
    check("and opens the menu", "SendMessage" in bot.kinds(), True)

    print("\n" + ("ALL PASSED" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
