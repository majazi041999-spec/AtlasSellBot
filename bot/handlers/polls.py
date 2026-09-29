"""In-bot polls (نظرسنجی): an admin creates a poll, sends it to themselves for a
test or broadcasts it to all users, and reads the tallies server-side.

Kept as its own router so the whole feature is one file to read or remove.
The vote handler (`pv:`) has NO admin guard — any user may vote — while creating,
sending, reading and closing a poll are owner/full-admin only.

Everything is sent with parse_mode=None on purpose: poll questions/options are
free user text and must never be run through the bot's default Markdown parser
(an underscore or asterisk would break the send). Every callback_data has a
handler here, so no button ever leaves a user staring at a spinner (the aiogram
inner-middleware trap documented in PROJECT_MAP §13).
"""
import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.handlers.admin import is_admin
from bot.keyboards import poll_admin_kb, poll_vote_kb
from core.database import (
    bump_poll_sent,
    create_poll,
    get_poll,
    get_poll_results,
    get_segment_users,
    record_poll_vote,
    set_poll_active,
)

logger = logging.getLogger(__name__)
router = Router()

_HELP = (
    "📊 ساخت نظرسنجی\n\n"
    "دستور را با سؤال در خط اول و هر گزینه در یک خط جدا بفرست (حداقل ۲، حداکثر ۱۰ گزینه):\n\n"
    "/newpoll\n"
    "سؤال نظرسنجی؟\n"
    "گزینه اول\n"
    "گزینه دوم\n"
    "گزینه سوم\n\n"
    "بعد از ساخت، دکمه‌ی «ارسال به خودم (تست)» را بزن تا اول خودت ببینیش."
)


def _poll_message(poll: dict) -> str:
    return f"📊 نظرسنجی\n\n{poll.get('question') or ''}\n\n👇 یکی از گزینه‌ها را انتخاب کن:"


def _results_text(res: dict, poll_id: int) -> str:
    total = int(res.get("total") or 0)
    lines = [f"📊 نتایج نظرسنجی #{poll_id}", "", res.get("question") or "", ""]
    opts = res.get("options") or []
    counts = res.get("counts") or []
    for i, opt in enumerate(opts):
        n = counts[i] if i < len(counts) else 0
        pct = (n * 100 // total) if total else 0
        filled = pct // 10
        bar = "█" * filled + "░" * (10 - filled)
        lines.append(f"{opt}\n{bar}  {n} رأی ({pct}%)")
    lines.append("")
    lines.append(f"مجموع: {total} رأی")
    return "\n".join(lines)


@router.message(Command("newpoll"))
async def new_poll(msg: Message, command: CommandObject):
    if not is_admin(msg.from_user.id):
        return
    body = (command.args or "").strip()
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if len(lines) < 3:
        await msg.answer(_HELP, parse_mode=None)
        return
    question, options = lines[0], lines[1:11]  # cap at 10 options
    if len(options) < 2:
        await msg.answer("حداقل ۲ گزینه لازم است.", parse_mode=None)
        return
    poll_id = await create_poll(question, options, is_anonymous=1, created_by=msg.from_user.id)
    preview = (
        f"✅ نظرسنجی #{poll_id} ساخته شد.\n\n"
        f"📊 {question}\n\nگزینه‌ها:\n" + "\n".join(f"• {o}" for o in options)
    )
    await msg.answer(preview, parse_mode=None, reply_markup=poll_admin_kb(poll_id, is_active=True))


@router.callback_query(F.data.startswith("psend_self:"))
async def poll_send_self(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer()
        return
    poll_id = int(cb.data.split(":")[1])
    poll = await get_poll(poll_id)
    if not poll:
        await cb.answer("نظرسنجی پیدا نشد", show_alert=True)
        return
    await cb.message.answer(
        _poll_message(poll), parse_mode=None,
        reply_markup=poll_vote_kb(poll_id, poll.get("options") or []),
    )
    await cb.answer("ارسال شد — همین‌جا تستش کن ✅")


@router.callback_query(F.data.startswith("psend_all:"))
async def poll_send_all_confirm(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer()
        return
    poll_id = int(cb.data.split(":")[1])
    b = InlineKeyboardBuilder()
    b.button(text="✅ بله، به همه ارسال کن", callback_data=f"psend_all2:{poll_id}")
    b.button(text="❌ انصراف", callback_data="pnoop")
    b.adjust(1)
    await cb.message.answer(
        "⚠️ این نظرسنجی برای همه‌ی کاربران ارسال می‌شود. مطمئنی؟",
        parse_mode=None, reply_markup=b.as_markup(),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("psend_all2:"))
async def poll_send_all(cb: CallbackQuery, bot: Bot):
    if not is_admin(cb.from_user.id):
        await cb.answer()
        return
    poll_id = int(cb.data.split(":")[1])
    poll = await get_poll(poll_id)
    if not poll:
        await cb.answer("نظرسنجی پیدا نشد", show_alert=True)
        return
    await cb.answer("در حال ارسال…")
    text = _poll_message(poll)
    kb = poll_vote_kb(poll_id, poll.get("options") or [])
    sent = 0
    for u in await get_segment_users("all", include_reps=True):
        tid = int(u.get("telegram_id") or 0)
        if not tid:
            continue
        try:
            await bot.send_message(tid, text, parse_mode=None, reply_markup=kb)
            sent += 1
            await asyncio.sleep(0.08)
        except Exception:
            # Blocked the bot / deleted account — skip silently.
            pass
    await bump_poll_sent(poll_id, sent)
    await cb.message.answer(f"✅ نظرسنجی برای {sent} کاربر ارسال شد.", parse_mode=None)


@router.callback_query(F.data.startswith("pres:"))
async def poll_results(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer()
        return
    poll_id = int(cb.data.split(":")[1])
    res = await get_poll_results(poll_id)
    await cb.message.answer(_results_text(res, poll_id), parse_mode=None)
    await cb.answer()


@router.callback_query(F.data.startswith("pclose:"))
async def poll_close(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer()
        return
    poll_id = int(cb.data.split(":")[1])
    await set_poll_active(poll_id, 0)
    await cb.answer("نظرسنجی بسته شد 🔒", show_alert=True)


@router.callback_query(F.data == "pnoop")
async def poll_noop(cb: CallbackQuery):
    await cb.answer("لغو شد")


@router.callback_query(F.data.startswith("pv:"))
async def poll_vote(cb: CallbackQuery):
    parts = cb.data.split(":")
    if len(parts) != 3:
        await cb.answer()
        return
    try:
        poll_id, idx = int(parts[1]), int(parts[2])
    except ValueError:
        await cb.answer()
        return
    poll = await get_poll(poll_id)
    if not poll:
        await cb.answer("نظرسنجی پیدا نشد", show_alert=True)
        return
    if not int(poll.get("is_active") or 0):
        await cb.answer("این نظرسنجی بسته شده است.", show_alert=True)
        return
    opts = poll.get("options") or []
    if not (0 <= idx < len(opts)):
        await cb.answer()
        return
    await record_poll_vote(poll_id, cb.from_user.id, idx)
    await cb.answer(f"رأی شما ثبت شد ✅\n«{opts[idx]}»")
