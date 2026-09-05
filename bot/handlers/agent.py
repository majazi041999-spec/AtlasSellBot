"""The support agent's Telegram side: live drafts, a stop button, app delivery.

The answer is streamed with `sendMessageDraft`, which renders as text fading in
at the bottom of the chat. Two properties of that method shape everything here:

  * a draft is EPHEMERAL — it evaporates after about 30 seconds — so the finished
    answer must be sent again as a real message or the customer is left with an
    empty chat;
  * `messages.setTyping` and its Bot API wrappers are rate limited to 20 calls
    per 5 seconds and 40 per 30 seconds PER CHAT, and going over earns a
    FLOOD_WAIT that stalls the whole answer. So updates are throttled by time,
    not by token, however fast the model happens to be.

Gated twice on purpose: a settings flag and an admin check. It is switched off
for customers until the owner has read enough real answers to trust it.
"""
from __future__ import annotations


import logging
import time

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.states import AgentChat
from core import ai_agent
from core.ai_analyst import is_configured
from core.database import (
    get_or_create_user, get_setting, set_setting, get_packages,
    get_user_balance, get_user_subscription_profiles, get_subscription_nodes,
)
from core.pricing import package_price_for_user
from core.xui_api import days_left

log = logging.getLogger(__name__)
router = Router()

# Telegram allows 20 draft updates per 5s per chat. One every 0.8s leaves plenty
# of headroom for the other calls this handler makes on the same chat.
DRAFT_INTERVAL = 0.8
APK_SETTING = "clientapp_file_id"
APK_NAME_SETTING = "clientapp_file_name"


async def _agent_allowed(uid: int) -> bool:
    from bot.handlers.admin import is_admin
    if (await get_setting("ai_agent_enabled", "0")) != "1":
        return False
    # Customers are let in only once the owner flips this on as well; until then
    # the agent answers nobody but the people who can read its mistakes.
    if (await get_setting("ai_agent_for_customers", "0")) == "1":
        return True
    return is_admin(uid)


async def _facts_for(uid: int) -> str:
    user = await get_or_create_user(uid)
    profiles = await get_user_subscription_profiles(user["id"]) or []
    slim = []
    for p in profiles[:5]:
        nodes = await get_subscription_nodes(int(p["id"]))
        slim.append({
            "name": p.get("name") or p.get("email"),
            "used_bytes": p.get("used_bytes"),
            "traffic_gb": p.get("traffic_gb"),
            "is_active": p.get("is_active"),
            "days_left": days_left(int(p.get("expire_timestamp") or 0)),
            "active_nodes": len([n for n in nodes if int(n.get("is_active") or 0)]),
        })
    pkgs = await get_packages(active_only=True)
    for p in pkgs:
        try:
            p["display_price"] = int((await package_price_for_user(user["id"], p))["final"])
        except Exception:
            p["display_price"] = int(p.get("price") or 0)
    return await ai_agent.build_facts(
        user, slim, pkgs, await get_user_balance(user["id"]))


async def _reply_kb():
    from bot.keyboards import agent_reply_kb
    return agent_reply_kb(bool((await get_setting(APK_SETTING, "") or "").strip()),
                          (await get_setting("support_username", "") or "").strip())


@router.message(Command("ai"))
async def agent_start(msg: Message, state: FSMContext):
    if not await _agent_allowed(msg.from_user.id):
        return
    if not await is_configured():
        await msg.answer("⚠️ مدل هوش مصنوعی هنوز در پنل تنظیم نشده است.")
        return
    await state.set_state(AgentChat.talking)
    await msg.answer(
        "🤖 <b>دستیار پشتیبانی</b>\n\n"
        "سؤالت را بپرس — مثل «چرا کنده؟» یا «چطور وصل شم؟».\n"
        "برای خروج: /exit",
        parse_mode="HTML",
    )


@router.message(StateFilter(AgentChat.talking), Command("exit"))
async def agent_exit(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("✅ از حالت دستیار خارج شدی.")


@router.message(StateFilter(AgentChat.talking), F.text)
async def agent_ask(msg: Message, state: FSMContext, bot: Bot):
    if not await _agent_allowed(msg.from_user.id):
        await state.clear()
        return
    question = (msg.text or "").strip()
    if not question:
        return
    if not ai_agent.take_slot(msg.from_user.id):
        await msg.answer("امروز سؤال‌های زیادی پرسیدی. کمی بعد دوباره امتحان کن "
                         "یا با پشتیبانی حرف بزن.")
        return

    data = await state.get_data()
    history = list(data.get("history") or [])
    history.append({"role": "user", "text": question[:2000]})

    brand = (await get_setting("ui.brand_name", "") or "").strip()
    draft_id = int(time.time() * 1000) % 2_000_000_000 or 1
    answer = ""
    last_push = 0.0

    async def push(text: str) -> None:
        """Update the live draft, never letting a draft failure kill the answer."""
        try:
            from aiogram.methods import SendMessageDraft
            await bot(SendMessageDraft(chat_id=msg.chat.id, draft_id=draft_id,
                                       text=text[:4000], can_stop=True, keep_on_stop=True))
        except Exception as exc:  # noqa: BLE001
            log.debug("draft update skipped: %s", exc)

    await push("")  # empty text renders Telegram's own "Thinking…" placeholder
    try:
        facts = await _facts_for(msg.from_user.id)
        async for piece in ai_agent.stream_answer(facts, history, brand):
            answer += piece
            now = time.monotonic()
            if now - last_push >= DRAFT_INTERVAL:
                last_push = now
                await push(answer)
    except Exception as exc:  # noqa: BLE001
        log.warning("agent stream failed: %s", exc)
        support = (await get_setting("support_username", "") or "").strip()
        await msg.answer(
            "الان نتوانستم جواب بدهم. لطفاً دوباره امتحان کن"
            + (f" یا به @{support} پیام بده." if support else "."))
        return

    answer = answer.strip()
    if not answer:
        await msg.answer("جوابی پیدا نکردم. سؤالت را کمی واضح‌تر بپرس.")
        return

    # The draft is temporary; this is the message that stays in the chat.
    await msg.answer(answer[:4000], reply_markup=await _reply_kb())
    history.append({"role": "model", "text": answer})
    await state.update_data(history=history[-ai_agent.HISTORY_TURNS * 2:])


@router.callback_query(F.data == "agent:getapp")
async def agent_send_app(cb, bot: Bot):
    file_id = (await get_setting(APK_SETTING, "") or "").strip()
    if not file_id:
        await cb.answer("فایل اپ هنوز آپلود نشده است.", show_alert=True)
        return
    await cb.answer()
    try:
        await bot.send_document(
            cb.message.chat.id, file_id,
            caption="📱 <b>اپ اندروید اطلس</b>\n\n"
                    "۱) روی فایل بزن تا نصب شود.\n"
                    "۲) اگر پیام «نصب از منابع ناشناس» آمد، اجازه بده — چون اپ ما "
                    "در گوگل‌پلی نیست و مستقیم نصب می‌شود.\n"
                    "۳) اپ را باز کن و لینک اشتراکت را وارد کن.",
            parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001
        log.warning("sending the app failed: %s", exc)
        await cb.message.answer("ارسال فایل ناموفق بود. لطفاً به پشتیبانی پیام بده.")


# ─────────────────────────── owner: store the APK ────────────────────────────
@router.message(Command("setapk"))
async def set_apk(msg: Message):
    from bot.handlers.admin import is_admin
    if not is_admin(msg.from_user.id):
        return
    doc = msg.document or (msg.reply_to_message.document if msg.reply_to_message else None)
    if not doc:
        await msg.answer(
            "📎 فایل APK اپ را بفرست و روی همان پیام <code>/setapk</code> را ریپلای کن.\n\n"
            "بعد از آن، دستیار می‌تواند همان فایل را مستقیم برای کاربر بفرستد — "
            "بدون هاست و بدون لینک.", parse_mode="HTML")
        return
    # A file_id is Telegram's own handle for a file it already stores, so the
    # bot re-sends it instantly and we host nothing ourselves.
    await set_setting(APK_SETTING, doc.file_id)
    await set_setting(APK_NAME_SETTING, doc.file_name or "atlas.apk")
    await msg.answer(f"✅ فایل اپ ذخیره شد: <code>{doc.file_name or '-'}</code>\n"
                     f"حجم: {int((doc.file_size or 0) / 1024 / 1024)} مگابایت",
                     parse_mode="HTML")
