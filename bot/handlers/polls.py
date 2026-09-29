"""In-bot polls (نظرسنجی), driven entirely from the admin menu — no slash command.

Flow: the admin taps "📊 نظرسنجی" (a coloured reply-keyboard button) → an inline
menu to CREATE a poll or view RESULTS. Creating is conversational (FSM): the
question, then options one per message. Each message is captured as HTML via
aiogram's `Message.html_text`, so ANY text and the admin's own PREMIUM (custom)
emoji are preserved verbatim and re-rendered on the poll — nothing is parsed,
whitelisted or stripped.

The poll body is sent as HTML: static chrome (📊, 👇, the coloured circles) is
turned into the owner's premium emoji, while the admin's question/options are
passed through exactly as they typed them. Option BUTTONS carry a real colour
(InlineKeyboardButton.style) and a premium coloured-circle icon; their label is
the plain text, because button labels can't hold custom-emoji entities.

Kept as its own router so the whole feature is one file to read or remove. The
vote handler (`pv:`) has NO admin guard — any user may vote — while every other
action is owner/full-admin only. Every callback_data has a handler here, so no
button leaves a user staring at a spinner (PROJECT_MAP §13).
"""
import asyncio
import logging
import re

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.handlers.admin import is_admin
from bot.keyboards import (
    POLL_CIRCLES,
    poll_admin_kb,
    poll_cancel_kb,
    poll_creating_kb,
    poll_list_kb,
    poll_menu_kb,
    poll_vote_kb,
)
from bot.rich_message import GLYPH_PREMIUM
from bot.states import PollCreate
from core.database import (
    bump_poll_sent,
    create_poll,
    get_poll,
    get_poll_results,
    get_segment_users,
    list_polls,
    record_poll_vote,
    set_poll_active,
)

logger = logging.getLogger(__name__)
router = Router()

_MAX_OPTIONS = 10


# ─── helpers ─────────────────────────────────────────────────────────────────

def _pe(glyph: str) -> str:
    """A static chrome glyph as the owner's premium emoji (or the plain glyph)."""
    eid = GLYPH_PREMIUM.get(glyph)
    return f'<tg-emoji emoji-id="{eid}">{glyph}</tg-emoji>' if eid else glyph


def _circle(i: int) -> str:
    return _pe(POLL_CIRCLES[i % len(POLL_CIRCLES)])


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _msg_html(msg: Message) -> str:
    """The message's text WITH its entities as HTML (custom emoji → <tg-emoji>)."""
    try:
        return (msg.html_text or "").strip()
    except Exception:
        return (msg.text or "").strip()


def _poll_html(poll: dict) -> str:
    opts = poll.get("options") or []
    parts = [f"{_pe('📊')} <b>نظرسنجی</b>", "", (poll.get("question") or ""), ""]
    for i, opt in enumerate(opts):
        parts.append(f"{_circle(i)} {opt.get('h') or opt.get('t') or ''}")
    parts += ["", f"{_pe('👇')} گزینه‌ی خودت را با دکمه‌های زیر انتخاب کن:"]
    return "\n".join(parts)


def _poll_fallback(poll: dict) -> str:
    opts = poll.get("options") or []
    lines = ["📊 نظرسنجی", "", _strip_html(poll.get("question") or ""), ""]
    for i, opt in enumerate(opts):
        lines.append(f"{POLL_CIRCLES[i % len(POLL_CIRCLES)]} {opt.get('t') or ''}")
    lines += ["", "👇 گزینه‌ی خودت را با دکمه‌های زیر انتخاب کن:"]
    return "\n".join(lines)


async def deliver_poll(bot: Bot, chat_id: int, poll: dict) -> bool:
    """Send the polished poll to one chat, degrading to plain text on any error.
    Shared by send-to-self, broadcast and one-off delivery so they can't drift."""
    kb = poll_vote_kb(poll["id"], poll.get("options") or [])
    try:
        await bot.send_message(chat_id, _poll_html(poll), parse_mode="HTML", reply_markup=kb)
        return True
    except Exception:
        try:
            await bot.send_message(chat_id, _poll_fallback(poll), parse_mode=None, reply_markup=kb)
            return True
        except Exception:
            return False


def _results_html(res: dict, poll_id: int) -> str:
    total = int(res.get("total") or 0)
    counts = res.get("counts") or []
    parts = [f"{_pe('📊')} <b>نتایج نظرسنجی</b> #{poll_id}", "", (res.get("question") or ""), ""]
    for i, opt in enumerate(res.get("options") or []):
        n = counts[i] if i < len(counts) else 0
        pct = (n * 100 // total) if total else 0
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        parts.append(f"{_circle(i)} {opt.get('h') or opt.get('t') or ''}")
        parts.append(f"<code>{bar}</code>  {n} رأی ({pct}%)")
    parts += ["", f"مجموع: <b>{total}</b> رأی"]
    return "\n".join(parts)


def _results_fallback(res: dict, poll_id: int) -> str:
    total = int(res.get("total") or 0)
    counts = res.get("counts") or []
    lines = [f"📊 نتایج نظرسنجی #{poll_id}", "", _strip_html(res.get("question") or ""), ""]
    for i, opt in enumerate(res.get("options") or []):
        n = counts[i] if i < len(counts) else 0
        pct = (n * 100 // total) if total else 0
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        lines.append(f"{POLL_CIRCLES[i % len(POLL_CIRCLES)]} {opt.get('t') or ''}\n{bar}  {n} رأی ({pct}%)")
    lines += ["", f"مجموع: {total} رأی"]
    return "\n".join(lines)


async def _send_results(target: Message, poll_id: int) -> None:
    res = await get_poll_results(poll_id)
    try:
        await target.answer(_results_html(res, poll_id), parse_mode="HTML")
    except Exception:
        await target.answer(_results_fallback(res, poll_id), parse_mode=None)


# ─── entry: the "📊 نظرسنجی" menu button ─────────────────────────────────────

@router.message(F.text == "📊 نظرسنجی")
async def poll_menu(msg: Message):
    if not is_admin(msg.from_user.id):
        return
    await msg.answer("📊 نظرسنجی — یکی را انتخاب کن:", parse_mode=None, reply_markup=poll_menu_kb())


# ─── create (FSM) ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "pnew")
async def poll_new(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer()
        return
    await state.set_state(PollCreate.question)
    await state.update_data(poll_q="", poll_opts=[])
    await cb.message.answer(
        "📝 سؤالِ نظرسنجی را بفرست.\nمی‌تونی اموجیِ پرمیوم و هر متنی بذاری — عیناً حفظ می‌شود.",
        parse_mode=None, reply_markup=poll_cancel_kb(),
    )
    await cb.answer()


@router.message(PollCreate.question)
async def poll_got_question(msg: Message, state: FSMContext):
    q_html = _msg_html(msg)
    if not q_html:
        await msg.answer("لطفاً یک پیامِ متنی برای سؤال بفرست.", parse_mode=None, reply_markup=poll_cancel_kb())
        return
    await state.update_data(poll_q=q_html, poll_opts=[])
    await state.set_state(PollCreate.options)
    await msg.answer(
        "✅ سؤال ثبت شد.\n\nحالا گزینه‌ها را «یکی‌یکی، هر کدام در یک پیامِ جدا» بفرست.\n"
        "وقتی تمام شد «✅ پایان و ساخت» را بزن.",
        parse_mode=None, reply_markup=poll_creating_kb(),
    )


@router.message(PollCreate.options)
async def poll_got_option(msg: Message, state: FSMContext):
    plain = (msg.text or "").strip()
    if not plain:
        await msg.answer("این گزینه متن نداشت؛ یک گزینه‌ی متنی بفرست.", parse_mode=None, reply_markup=poll_creating_kb())
        return
    data = await state.get_data()
    opts = list(data.get("poll_opts") or [])
    if len(opts) >= _MAX_OPTIONS:
        await msg.answer(f"به سقفِ {_MAX_OPTIONS} گزینه رسیدی. «✅ پایان و ساخت» را بزن.",
                         parse_mode=None, reply_markup=poll_creating_kb())
        return
    opts.append({"t": plain, "h": _msg_html(msg) or plain})
    await state.update_data(poll_opts=opts)
    await msg.answer(
        f"✅ گزینه‌ی {len(opts)} ثبت شد.\nگزینه‌ی بعدی را بفرست یا «✅ پایان و ساخت».",
        parse_mode=None, reply_markup=poll_creating_kb(),
    )


@router.callback_query(F.data == "pdone")
async def poll_done(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer()
        return
    data = await state.get_data()
    q = (data.get("poll_q") or "").strip()
    opts = data.get("poll_opts") or []
    if not q or len(opts) < 2:
        await cb.answer("حداقل یک سؤال و ۲ گزینه لازم است.", show_alert=True)
        return
    poll_id = await create_poll(q, opts, is_anonymous=1, created_by=cb.from_user.id)
    await state.clear()
    await cb.message.answer(
        f"✅ نظرسنجی #{poll_id} ساخته شد.\nاول با «🧪 ارسال به خودم» ببینش، بعد برای همه بفرست:",
        parse_mode=None, reply_markup=poll_admin_kb(poll_id, is_active=True),
    )
    await cb.answer("ساخته شد ✅")


@router.callback_query(F.data == "pcancel")
async def poll_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await cb.message.answer("❌ لغو شد.", parse_mode=None)
    except Exception:
        pass
    await cb.answer("لغو شد")


# ─── list + results ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "plist")
async def poll_list(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer()
        return
    polls = await list_polls(15)
    view = [{
        "id": p["id"],
        "is_active": p.get("is_active"),
        "title": _strip_html(p.get("question") or "")[:30] or f"#{p['id']}",
    } for p in polls]
    await cb.message.answer("📋 نظرسنجی‌ها — یکی را بزن تا نتایجش را ببینی:",
                            parse_mode=None, reply_markup=poll_list_kb(view))
    await cb.answer()


@router.callback_query(F.data.startswith("pres:"))
async def poll_results(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer()
        return
    poll_id = int(cb.data.split(":")[1])
    await _send_results(cb.message, poll_id)
    await cb.answer()


# ─── send ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("psend_self:"))
async def poll_send_self(cb: CallbackQuery, bot: Bot):
    if not is_admin(cb.from_user.id):
        await cb.answer()
        return
    poll_id = int(cb.data.split(":")[1])
    poll = await get_poll(poll_id)
    if not poll:
        await cb.answer("نظرسنجی پیدا نشد", show_alert=True)
        return
    await deliver_poll(bot, cb.from_user.id, poll)
    await cb.answer("ارسال شد — همین‌جا تستش کن ✅")


@router.callback_query(F.data.startswith("psend_all:"))
async def poll_send_all_confirm(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer()
        return
    poll_id = int(cb.data.split(":")[1])
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="✅ بله، به همه ارسال کن", callback_data=f"psend_all2:{poll_id}")
    b.button(text="❌ انصراف", callback_data="pnoop")
    b.adjust(1)
    await cb.message.answer("⚠️ این نظرسنجی برای همه‌ی کاربران ارسال می‌شود. مطمئنی؟",
                            parse_mode=None, reply_markup=b.as_markup())
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
    sent = 0
    for u in await get_segment_users("all", include_reps=True):
        tid = int(u.get("telegram_id") or 0)
        if not tid:
            continue
        if await deliver_poll(bot, tid, poll):
            sent += 1
        await asyncio.sleep(0.08)
    await bump_poll_sent(poll_id, sent)
    await cb.message.answer(f"✅ نظرسنجی برای {sent} کاربر ارسال شد.", parse_mode=None)


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


# ─── any user: vote ──────────────────────────────────────────────────────────

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
    await cb.answer(f"رأی شما ثبت شد ✅\n«{opts[idx].get('t') or ''}»")
