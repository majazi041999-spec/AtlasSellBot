"""«وضعیت سرورها» — a customer taps a button and sees how busy each server is
right now, as a PERCENTAGE ONLY.

A TAP NEVER REACHES A SERVER. The figures are the online counts that
`_online_poll_worker` (main.py) already stores on every `servers` row each
`online_poll_seconds`. This screen only reads them, through one shared in-memory
snapshot rebuilt at most every SNAPSHOT_TTL seconds — so however many people
press the button, and however fast, the VPN panels see exactly the traffic they
would see if nobody had. A crowd cannot take a server down through this.

What a crowd CAN reach is the bot itself, so the bot is protected in layers:
  1. per user — a cooldown between views and a daily cap (admins exempt);
  2. globally — a token bucket on renders, so a coordinated group cannot spend
     the Telegram send budget that buying and support share;
  3. refresh edits the same message in place rather than sending new ones.

Customers never see how many people are online — that is business information.
Admins also see the count behind each figure, to calibrate
`server_load_capacity` (concurrent users that read as 100% on a server whose
`load_weight` is 1).

Ships OFF for customers (`server_load_public`): the owner previews it from the
"📊 آمار کلی" screen and switches it on with one tap. Covered by
tests/test_server_load.py.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from typing import Dict, Optional

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards import _button
from bot.rich_message import GLYPH_PREMIUM, premiumize
from core.database import (
    get_segment_users,
    get_setting,
    get_subscription_node_configs,
    set_setting,
)
from core.jalali import tehran_now

log = logging.getLogger(__name__)
router = Router()

DEFAULTS = {
    "server_load_public": "0",      # customers see the home button
    "server_load_capacity": "100",  # concurrent users that read as 100% (load_weight 1)
    "server_load_cooldown": "30",   # seconds between two views, per customer
    "server_load_daily": "40",      # views per customer per Tehran day
    "server_load_promo_sent": "",   # set once the announcement has been broadcast
}

SNAPSHOT_TTL = 20.0   # seconds one snapshot serves every viewer
GLOBAL_RATE = 8.0     # renders per second, all customers together, sustained
GLOBAL_BURST = 25.0   # …and how far a burst may run ahead of that
_MAX_TRACKED = 20000  # rate-limit rows kept in memory before the oldest go

_FLAG_RE = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}")
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _fa(n) -> str:
    return str(n).translate(_FA_DIGITS)


def _pe(glyph: str) -> str:
    """A glyph as the owner's premium emoji (or the plain glyph)."""
    eid = GLYPH_PREMIUM.get(glyph)
    return f'<tg-emoji emoji-id="{eid}">{glyph}</tg-emoji>' if eid else glyph


def _is_admin(uid: int) -> bool:
    # Imported here, not at module level, so this module stays importable (and
    # testable) without pulling in the whole admin handler.
    from bot.handlers.admin import is_admin
    return is_admin(uid)


async def _cfg_int(key: str, lo: int, hi: int) -> int:
    raw = await get_setting(key, DEFAULTS[key])
    try:
        value = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        value = int(DEFAULTS[key])
    return max(lo, min(hi, value))


# ─── the shared snapshot ─────────────────────────────────────────────────────

_SNAP: Dict = {"at": 0.0, "data": None}
_SNAP_LOCK = asyncio.Lock()


def invalidate() -> None:
    """Make the next view rebuild — after an admin changes a setting."""
    _SNAP["at"] = 0.0


async def _build() -> Dict:
    from core.autonode import server_load_snapshot

    capacity = await _cfg_int("server_load_capacity", 1, 100000)
    cooldown = await _cfg_int("server_load_cooldown", 0, 3600)
    daily = await _cfg_int("server_load_daily", 1, 10000)
    public = (await get_setting("server_load_public", DEFAULTS["server_load_public"])) == "1"

    # Only servers a customer can actually be on: an active, non-auto node
    # config points at them. The flag comes from that node's label, which is
    # where customers already see it.
    flags: Dict[int, str] = {}
    usable = set()
    for nc in await get_subscription_node_configs(active_only=True):
        if int(nc.get("is_auto") or 0):
            continue
        sid = int(nc.get("server_id") or 0)
        if not sid:
            continue
        usable.add(sid)
        if sid not in flags:
            match = _FLAG_RE.search(str(nc.get("label") or ""))
            if match:
                flags[sid] = match.group(0)

    rows, newest = [], 0
    for s in await server_load_snapshot():
        sid = int(s["id"])
        if not int(s.get("is_active") or 0) or sid not in usable:
            continue
        raw_name = str(s.get("name") or f"#{sid}").strip()
        name = re.sub(r"^سرور\s*", "", raw_name).strip() or raw_name
        try:
            weight = float(s.get("load_weight") or 1) or 1.0
        except (TypeError, ValueError):
            weight = 1.0
        cap = max(1.0, capacity * weight)
        pct = basis = None
        # `online` is None when the panel did not answer or the reading is stale.
        # Unknown is shown as unknown — never as 0%, which would read as "empty".
        if s.get("online") is not None:
            basis = float(s.get("online_avg") or 0) or float(s.get("online") or 0)
            pct = max(0, min(100, round(basis / cap * 100)))
        newest = max(newest, int(s.get("checked_at") or 0))
        rows.append({"flag": flags.get(sid, ""), "name": name, "pct": pct,
                     "online": None if basis is None else round(basis), "cap": round(cap)})
    # Least busy first: the answer to "where should I connect" is the top line.
    rows.sort(key=lambda r: (r["pct"] is None, r["pct"] if r["pct"] is not None else 0))
    return {"rows": rows, "checked_at": newest, "capacity": capacity,
            "cooldown": cooldown, "daily": daily, "public": public}


async def snapshot() -> Dict:
    if _SNAP["data"] is not None and time.monotonic() - _SNAP["at"] < SNAPSHOT_TTL:
        return _SNAP["data"]
    async with _SNAP_LOCK:
        # Re-check inside the lock: everyone who queued behind the first viewer
        # is served what that viewer just built, not a rebuild each.
        if _SNAP["data"] is not None and time.monotonic() - _SNAP["at"] < SNAPSHOT_TTL:
            return _SNAP["data"]
        data = await _build()
        _SNAP["data"], _SNAP["at"] = data, time.monotonic()
        return data


# ─── rate limiting ───────────────────────────────────────────────────────────

# uid -> [monotonic time of the last view, Tehran day, views that day]
_USERS: Dict[int, list] = {}
_BUCKET = {"tokens": GLOBAL_BURST, "ts": time.monotonic()}


def _today() -> str:
    return tehran_now().strftime("%Y%m%d")


def _user_block(uid: int, cooldown: int, daily: int) -> Optional[str]:
    """None if this customer may view now, else "daily" or "wait:<seconds>"."""
    rec = _USERS.get(uid)
    if not rec:
        return None
    if rec[1] == _today() and rec[2] >= daily:
        return "daily"
    wait = cooldown - (time.monotonic() - rec[0])
    if wait > 0:
        return f"wait:{int(wait) + 1}"
    return None


def _user_commit(uid: int) -> None:
    day = _today()
    rec = _USERS.get(uid)
    count = rec[2] + 1 if rec and rec[1] == day else 1
    _USERS[uid] = [time.monotonic(), day, count]
    if len(_USERS) > _MAX_TRACKED:
        # Drop the oldest half by last view. Never .clear(): that would hand every
        # limited customer a fresh allowance at the same moment.
        oldest = sorted(_USERS.items(), key=lambda kv: kv[1][0])[: len(_USERS) // 2]
        for uid_old, _ in oldest:
            _USERS.pop(uid_old, None)


def _take_global() -> bool:
    now = time.monotonic()
    _BUCKET["tokens"] = min(GLOBAL_BURST, _BUCKET["tokens"] + (now - _BUCKET["ts"]) * GLOBAL_RATE)
    _BUCKET["ts"] = now
    if _BUCKET["tokens"] >= 1.0:
        _BUCKET["tokens"] -= 1.0
        return True
    return False


async def _admit(cb: CallbackQuery, data: Dict, admin: bool) -> bool:
    """True if this view may render. Otherwise answers the callback itself."""
    if admin:
        return True
    uid = cb.from_user.id
    block = _user_block(uid, data["cooldown"], data["daily"])
    if block == "daily":
        await cb.answer("امروز به سقفِ دفعاتِ مشاهده رسیدی؛ فردا دوباره سر بزن 🙏", show_alert=True)
        return False
    if block:
        secs = block.split(":", 1)[1]
        await cb.answer(f"⏳ {_fa(secs)} ثانیه‌ی دیگه دوباره بزن.\n"
                        "آمار هر چند دقیقه یک بار به‌روز می‌شه.", show_alert=True)
        return False
    # Global check AFTER the personal one, so a customer who is already limited
    # never spends a token the others could have used.
    if not _take_global():
        await cb.answer("الان درخواست زیاده؛ چند ثانیه‌ی دیگه دوباره بزن.", show_alert=True)
        return False
    _user_commit(uid)
    return True


# ─── rendering ───────────────────────────────────────────────────────────────

def _ago(checked_ms: int) -> str:
    if not checked_ms:
        return ""
    secs = max(0, int(time.time() - checked_ms / 1000))
    if secs < 60:
        return "همین الان"
    mins = secs // 60
    if mins < 60:
        return f"{_fa(mins)} دقیقه پیش"
    return f"{_fa(mins // 60)} ساعت پیش"


def _render(data: Dict, admin: bool) -> str:
    lines = [f"{_pe('📶')} <b>وضعیت سرورها</b>", ""]
    if not data["rows"]:
        lines.append("فعلاً اطلاعاتی در دسترس نیست؛ کمی بعد دوباره سر بزن.")
    for r in data["rows"]:
        flag = f"{_pe(r['flag'])} " if r["flag"] else ""
        pct = f"{_fa(r['pct'])}٪" if r["pct"] is not None else "نامشخص"
        line = f"{flag}{html.escape(r['name'])} — <b>{pct}</b>"
        if admin and r["online"] is not None:
            line += f"  <i>({_fa(r['online'])} از {_fa(r['cap'])})</i>"
        lines.append(line)
    ago = _ago(data["checked_at"])
    if ago:
        lines += ["", f"<i>به‌روزرسانی: {ago}</i>"]
    if admin:
        lines += ["", f"<i>فقط ادمین — ظرفیتِ ۱۰۰٪: {_fa(data['capacity'])} کاربرِ همزمان • "
                      f"برای مشتری‌ها: {'روشن' if data['public'] else 'خاموش'}</i>"]
    return "\n".join(lines)


def _kb(data: Dict, admin: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    sizes = [1]
    _button(b, text="🔄 به‌روزرسانی", callback_data="sload:r", style="primary")
    if admin:
        _button(b, text=("⛔️ خاموش کن برای مشتری‌ها" if data["public"] else "✅ روشن کن برای مشتری‌ها"),
                callback_data="sload:pub", style=("danger" if data["public"] else "success"))
        for step in (-50, -10, 10, 50):
            _button(b, text=f"{'−' if step < 0 else '+'}{_fa(abs(step))}",
                    callback_data=f"sload:cap:{step}")
        sizes += [1, 4]
    _button(b, text="🏠 منوی اصلی", callback_data="back_to_menu")
    sizes.append(1)
    b.adjust(*sizes)
    return b.as_markup()


async def _show(cb: CallbackQuery, edit: bool, toast: str = "") -> None:
    try:
        data = await snapshot()
    except Exception:
        log.exception("server load snapshot failed")
        await cb.answer("الان در دسترس نیست؛ کمی بعد دوباره امتحان کن.", show_alert=True)
        return
    admin = _is_admin(cb.from_user.id)
    if not admin and not data["public"]:
        await cb.answer("این بخش به‌زودی فعال می‌شه 🙂", show_alert=True)
        return
    if not await _admit(cb, data, admin):
        return
    text, kb = _render(data, admin), _kb(data, admin)
    if edit:
        try:
            await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            await cb.answer(toast)
            return
        except Exception as exc:
            if "not modified" in str(exc).lower():
                await cb.answer(toast or "✅ اطلاعات تازه‌ست")
                return
            # Not editable (too old, or a different kind of message): send fresh.
    await cb.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer(toast)


# ─── entry points ────────────────────────────────────────────────────────────

async def open_from_home(cb: CallbackQuery) -> None:
    """The home-menu button. Replaces the menu in place, like the wallet screen."""
    await _show(cb, edit=True)


async def load_public_flag() -> None:
    """Startup: tell the home menu whether customers get the button."""
    from bot.home import set_load_public
    set_load_public((await get_setting("server_load_public", DEFAULTS["server_load_public"])) == "1")


@router.callback_query(F.data == "sload:r")
async def refresh(cb: CallbackQuery):
    await _show(cb, edit=True)


@router.callback_query(F.data == "sload:open")
async def admin_open(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer()
        return
    # A new message, so the stats screen it was opened from stays put.
    await _show(cb, edit=False)


@router.callback_query(F.data == "sload:pub")
async def toggle_public(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer()
        return
    on = (await get_setting("server_load_public", DEFAULTS["server_load_public"])) != "1"
    await set_setting("server_load_public", "1" if on else "0")
    from bot.home import set_load_public
    set_load_public(on)
    invalidate()
    await _show(cb, edit=True, toast=("✅ برای مشتری‌ها روشن شد" if on else "⛔️ برای مشتری‌ها خاموش شد"))


@router.callback_query(F.data.startswith("sload:cap:"))
async def adjust_capacity(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer()
        return
    try:
        step = int(cb.data.rsplit(":", 1)[1])
    except ValueError:
        await cb.answer()
        return
    current = await _cfg_int("server_load_capacity", 1, 100000)
    new = max(10, min(100000, current + step))
    await set_setting("server_load_capacity", str(new))
    invalidate()
    await _show(cb, edit=True, toast=f"ظرفیت: {_fa(new)}")


# ─── the update announcement (owner approves, then it goes to everyone) ───────

# Short, Telegram-style, premium emoji. premiumize() swaps the plain glyphs for
# the owner's custom emoji; the text is plain (no existing <tg-emoji>) so there is
# no double-wrap.
_PROMO_HTML = (
    "🚀 <b>قابلیت جدید: وضعیت سرورها</b>\n\n"
    "حالا قبل از اتصال می‌تونی ببینی هر سرور چقدر شلوغه و <b>خلوت‌ترین</b> رو انتخاب کنی. ⚡\n\n"
    "📶 کافیه از منوی اصلی ربات، «وضعیت سرورها» رو بزنی 👇"
)


def _promo_text() -> str:
    return premiumize(_PROMO_HTML)


def _promo_preview_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="✅ تأیید و ارسال به همه", callback_data="sload:promo_ok", style="success")
    _button(b, text="❌ فعلاً نه", callback_data="sload:promo_no", style="danger")
    b.adjust(1)
    return b.as_markup()


async def send_promo_preview(bot: Bot, chat_id: int) -> None:
    """Show the owner exactly what customers will get, with approve / cancel."""
    await bot.send_message(chat_id, "👀 پیش‌نمایشِ اعلانِ آپدیت (همینی که برای مشتری‌ها می‌ره):",
                           parse_mode=None)
    await bot.send_message(chat_id, _promo_text(), parse_mode="HTML",
                           disable_web_page_preview=True, reply_markup=_promo_preview_kb())


async def _run_announce(bot: Bot, owner_id: int) -> None:
    text = _promo_text()
    sent = 0
    for u in await get_segment_users("all", include_reps=True):
        tid = int(u.get("telegram_id") or 0)
        if not tid:
            continue
        try:
            await bot.send_message(tid, text, parse_mode="HTML", disable_web_page_preview=True)
            sent += 1
            await asyncio.sleep(0.08)
        except Exception:
            pass
    try:
        await bot.send_message(owner_id, f"📣 اعلانِ «وضعیت سرورها» برای {_fa(sent)} کاربر ارسال شد.",
                               parse_mode=None)
    except Exception:
        pass


@router.callback_query(F.data == "sload:promo_ok")
async def promo_ok(cb: CallbackQuery, bot: Bot):
    if not _is_admin(cb.from_user.id):
        await cb.answer()
        return
    # Guard: a second tap must not broadcast again. Set the flag BEFORE the task.
    if (await get_setting("server_load_promo_sent", "")).strip():
        await cb.answer("این اعلان قبلاً ارسال شده.", show_alert=True)
        return
    await set_setting("server_load_promo_sent", tehran_now().strftime("%Y-%m-%d %H:%M"))
    await set_setting("server_load_public", "1")
    from bot.home import set_load_public
    set_load_public(True)
    invalidate()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cb.answer("✅ روشن شد؛ ارسال به همه شروع شد")
    asyncio.create_task(_run_announce(bot, cb.from_user.id))


@router.callback_query(F.data == "sload:promo_no")
async def promo_no(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer()
        return
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cb.answer("باشه، فعلاً ارسال نشد.")
