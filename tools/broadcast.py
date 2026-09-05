"""Resumable broadcast. Run it twice and nobody is messaged twice.

WHY THIS EXISTS. The first announcement went out from a throwaway script over an
SSH session, and the laptop died mid-run. The messages were delivered — but the
only record of HOW MANY was the terminal output, which died with the connection.
There was then no safe way to finish the job: re-running would have double-
messaged everyone who had already received it.

So delivery is recorded per user, in the database, as it happens. A run that is
killed at message 90 of 232 resumes at 91. A run that already finished sends
nothing and says so.

    python tools/broadcast.py <campaign-id> --dry-run
    python tools/broadcast.py <campaign-id>

The campaign id is any short string; reusing one means "continue that send",
and a new one means "a new announcement".
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
# Run from anywhere: the project root has to be importable, and the database
# path below is relative to it.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from aiogram import Bot
from aiogram.exceptions import (TelegramBadRequest, TelegramForbiddenError,
                                TelegramRetryAfter)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards import _button
from bot.rich_message import emoji as tg_emoji
from core.config import BOT_TOKEN

DB = "atlas.db"
# 0.06s is ~16/second. Telegram's broadcast ceiling is higher, but the bot is
# serving customers on the same token while this runs, and their requests matter
# more than finishing thirty seconds sooner.
DELAY = 0.06


def announcement() -> str:
    return (
        tg_emoji("brand", "🌐") + " <b>اطلس اکانت — بازطراحی کامل</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "سلام 👋\n\n"
        + tg_emoji("services", "📱") + " <b>مینی‌اپ نو شد</b> — ظاهرش کامل بازطراحی شد و "
        "حالا خیلی سریع‌تر بالا می‌آید.\n\n"
        + tg_emoji("cart", "🛒") + " <b>منوی تازه</b> — همه‌چیز روی صفحه‌ی اول، بدون گشتن در زیرمنوها.\n\n"
        + tg_emoji("trial", "🆓") + " <b>۵ کاربر هم‌زمان</b> روی همه‌ی پکیج‌ها.\n\n"
        + tg_emoji("assistant", "🤖") + " <b>دستیار هوشمند</b> — هر سوالی داری همین‌جا بپرس. "
        "«چطور وصل شم؟»، «چقدر حجم دارم؟» و هر چیز دیگر؛ همان لحظه جواب می‌گیری."
    )


def announcement_kb():
    b = InlineKeyboardBuilder()
    _button(b, text="🔄 شروع مجدد ربات", callback_data="home:restart", style="success")
    b.adjust(1)
    return b.as_markup()


def _ensure_table(db: sqlite3.Connection) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS broadcast_log ("
        "  campaign TEXT NOT NULL,"
        "  telegram_id INTEGER NOT NULL,"
        "  status TEXT NOT NULL,"          # sent | blocked | failed
        "  at INTEGER NOT NULL,"
        "  PRIMARY KEY (campaign, telegram_id))"
    )
    db.commit()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only-active", action="store_true",
                    help="only customers with a live subscription")
    args = ap.parse_args()

    db = sqlite3.connect(DB, timeout=20)
    _ensure_table(db)

    if args.only_active:
        rows = db.execute(
            "SELECT DISTINCT u.telegram_id FROM users u "
            "JOIN subscription_profiles p ON p.user_id = u.id AND p.is_active = 1 "
            "WHERE u.telegram_id IS NOT NULL")
    else:
        rows = db.execute("SELECT telegram_id FROM users WHERE telegram_id IS NOT NULL")
    everyone = [r[0] for r in rows]

    done = {r[0] for r in db.execute(
        "SELECT telegram_id FROM broadcast_log WHERE campaign=?", (args.campaign,))}
    todo = [u for u in everyone if u not in done]

    print(f"campaign      : {args.campaign}")
    print(f"audience      : {len(everyone)}")
    print(f"already sent  : {len(done)}")
    print(f"to send now   : {len(todo)}")
    if args.dry_run:
        print("\n(dry run — nothing sent)")
        return
    if not todo:
        print("\nnothing to do; this campaign is already complete.")
        return

    bot = Bot(token=BOT_TOKEN)
    body, markup = announcement(), announcement_kb()
    counts = {"sent": 0, "blocked": 0, "failed": 0}
    t0 = time.monotonic()
    try:
        for i, uid in enumerate(todo, 1):
            status = "failed"
            for attempt in range(3):
                try:
                    await bot.send_message(uid, body, parse_mode="HTML", reply_markup=markup)
                    status = "sent"
                    break
                except TelegramRetryAfter as e:
                    # Telegram states exactly how long to wait. Obeying it is
                    # what keeps the bot's own traffic from being throttled too.
                    await asyncio.sleep(e.retry_after + 1)
                except TelegramForbiddenError:
                    status = "blocked"
                    break
                except TelegramBadRequest:
                    break
                except Exception:
                    if attempt < 2:
                        await asyncio.sleep(1)
            counts[status] += 1
            # Written per message, not at the end: the whole point is that a run
            # killed halfway leaves a usable record behind.
            db.execute("INSERT OR REPLACE INTO broadcast_log VALUES (?,?,?,?)",
                       (args.campaign, uid, status, int(time.time())))
            db.commit()
            await asyncio.sleep(DELAY)
            if i % 50 == 0:
                print(f"  ...{i}/{len(todo)}")
    finally:
        await bot.session.close()
        db.close()

    print()
    print(f"delivered      : {counts['sent']}")
    print(f"blocked the bot: {counts['blocked']}")
    print(f"other failures : {counts['failed']}")
    print(f"elapsed        : {round(time.monotonic() - t0, 1)}s")


asyncio.run(main())
