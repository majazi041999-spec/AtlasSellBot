"""Telegram rich messages (Bot API 10.1+) with a guaranteed plain fallback.

A rich message renders real tables, headings and lists inside the client instead
of the ASCII art we used to fake them with. `sendRichMessage` is a NEW method
though, so it can fail where a plain `sendMessage` never would — a local Bot API
server that hasn't been updated, a chat type that rejects it, a field Telegram
renames later.

A customer pressing "buy" must never get an error instead of the price list, so
every helper here takes the exact message we would have sent before and falls
back to it on ANY failure. The rich version is an upgrade, never a dependency.
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram.types import InlineKeyboardMarkup, Message

log = logging.getLogger(__name__)

# Tri-state: None = not tried yet, True = the API took it, False = rich messages
# are unavailable here. Only a "no such method" answer (or an aiogram too old to
# name the method at all) flips it to False — a timeout or a one-off 400 must not
# disable the feature for the life of the process.
_supported: Optional[bool] = None

# aiogram gained these in 3.31, with the Bot API 10.1 release. An older install
# must degrade to the plain messages the bot sent before, NOT fail to import and
# take the whole bot down with it.
try:
    from aiogram.methods import EditMessageText, SendRichMessage
    from aiogram.types import InputRichMessage
except ImportError:  # pragma: no cover - depends on the installed aiogram
    EditMessageText = SendRichMessage = InputRichMessage = None  # type: ignore[assignment]
    _supported = False
    log.warning("aiogram is too old for rich messages; tables fall back to plain text")

_UNSUPPORTED_HINTS = ("method not found", "unknown method", "not found: method")


def _note_failure(exc: Exception) -> None:
    global _supported
    text = str(exc).lower()
    if any(hint in text for hint in _UNSUPPORTED_HINTS):
        _supported = False
        log.warning("rich messages unsupported by this Bot API server, disabling: %s", exc)
    else:
        log.warning("rich message send failed, fell back to plain text: %s", exc)


def table(header: list[str], rows: list[list[str]], align: Optional[list[str]] = None) -> str:
    """Build a GitHub-flavoured Markdown table, which is what rich Markdown parses.

    `align` takes "left" / "center" / "right" per column and defaults to left.
    Cells are collapsed to a single line and their pipes escaped: those are the
    only two characters that can break the table structure itself.
    """
    bar = {"left": ":---", "center": ":---:", "right": "---:"}
    align = align or ["left"] * len(header)

    def cell(value: object) -> str:
        return " ".join(str(value or "").split()).replace("|", "\\|")

    out = ["| " + " | ".join(cell(h) for h in header) + " |",
           "|" + "|".join(bar.get(a, ":---") for a in align) + "|"]
    for row in rows:
        out.append("| " + " | ".join(cell(c) for c in row) + " |")
    return "\n".join(out)


async def answer_rich(
    message: Message,
    markdown: str,
    fallback: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    rtl: bool = True,
) -> bool:
    """Send `markdown` as a rich message, or `fallback` as a plain one if that
    fails for any reason. Returns True when the rich version was delivered.
    """
    if _supported is not False:
        try:
            await message.bot(SendRichMessage(
                chat_id=message.chat.id,
                rich_message=InputRichMessage(markdown=markdown, is_rtl=rtl),
                reply_markup=reply_markup,
            ))
            globals()["_supported"] = True
            return True
        except Exception as exc:  # noqa: BLE001 — the fallback below is the point
            _note_failure(exc)
    await message.answer(fallback, reply_markup=reply_markup, parse_mode="Markdown")
    return False


async def edit_rich(
    message: Message,
    markdown: str,
    fallback: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    rtl: bool = True,
) -> bool:
    """`answer_rich` for a message we are editing in place (a callback screen)."""
    if _supported is not False:
        try:
            await message.bot(EditMessageText(
                chat_id=message.chat.id,
                message_id=message.message_id,
                rich_message=InputRichMessage(markdown=markdown, is_rtl=rtl),
                reply_markup=reply_markup,
            ))
            globals()["_supported"] = True
            return True
        except Exception as exc:  # noqa: BLE001
            _note_failure(exc)
    await message.edit_text(fallback, reply_markup=reply_markup, parse_mode="Markdown")
    return False
