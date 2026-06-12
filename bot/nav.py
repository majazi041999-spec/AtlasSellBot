"""Unified step navigation for the bot.

Previously there were two separate `flow_back` handlers (one in admin.py and
one in user.py). Because the admin router is registered first and its handler
had no admin guard, it swallowed every user's "back" press and dumped them to
the admin menu — so back navigation was broken for regular users and missing in
many flows.

This module provides ONE `flow_back` handler backed by a per-state registry, so
every flow can declare exactly where its "⬅️ برگشت" button goes. Handlers in
admin.py / user.py register their back transitions at import time.
"""
from typing import Awaitable, Callable, Dict

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery

from core.config import ADMIN_IDS
from core.database import get_or_create_user, get_setting

router = Router()

BackHandler = Callable[[CallbackQuery, FSMContext], Awaitable[None]]

# Maps an FSM state string (e.g. "CreateConfig:traffic") -> async back handler.
_BACK: Dict[str, BackHandler] = {}


def _key(state) -> str:
    return state.state if isinstance(state, State) else str(state)


def register(state, handler: BackHandler) -> None:
    """Register the back handler invoked when the user is in `state` and taps back."""
    _BACK[_key(state)] = handler


def static(target_state: State, text: str, parse_mode: str | None = None,
           markup_factory: Callable | None = None) -> BackHandler:
    """Build a back handler that returns to a previous step with a static prompt."""
    from bot.keyboards import flow_cancel_kb

    async def _handler(cb: CallbackQuery, state: FSMContext) -> None:
        await state.set_state(target_state)
        kb = markup_factory() if markup_factory else flow_cancel_kb()
        await cb.message.edit_text(text, reply_markup=kb, parse_mode=parse_mode)

    return _handler


async def _role(uid: int, user: dict) -> str:
    owner_id = int(await get_setting("owner_admin_id", "0") or 0)
    if uid in ADMIN_IDS or (owner_id and uid == owner_id):
        return "owner"
    if not user.get("is_admin", 0):
        return "none"
    role = (user.get("admin_role") or "full").strip().lower()
    return role if role in {"full", "finance"} else "full"


async def go_home(cb: CallbackQuery, state: FSMContext) -> None:
    """Clear the flow and show the correct main menu for this user."""
    from bot.keyboards import admin_menu, user_menu

    await state.clear()
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, cb.from_user.full_name)
    role = await _role(cb.from_user.id, user)
    kb = admin_menu(finance_only=(role == "finance")) if role != "none" else user_menu(
        include_wholesale=bool(user.get("is_wholesale", 0))
    )
    try:
        await cb.message.edit_text("🏠 برگشت به منوی اصلی")
    except Exception:
        pass
    await cb.message.answer("منوی اصلی", reply_markup=kb)


@router.callback_query(F.data == "flow_back")
async def flow_back(cb: CallbackQuery, state: FSMContext) -> None:
    cur = await state.get_state()
    if not cur:
        await cb.answer("مرحله‌ای برای برگشت وجود ندارد.", show_alert=True)
        return
    handler = _BACK.get(cur)
    try:
        if handler:
            await handler(cb, state)
        else:
            # Safety net: never leave the user stuck — go home.
            await go_home(cb, state)
    except Exception:
        await go_home(cb, state)
    await cb.answer()
