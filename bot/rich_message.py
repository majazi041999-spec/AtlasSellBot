"""Telegram rich messages (Bot API 10.1+) with a guaranteed plain fallback.

A rich message renders real tables, headings and lists inside the client instead
of the ASCII art we used to fake them with. `sendRichMessage` is a NEW method
though, so it can fail where a plain `sendMessage` never would — a local Bot API
server that hasn't been updated, a chat type that rejects it, a field Telegram
renames later.

A customer pressing "buy" must never get an error instead of the price list, so
every helper here takes the exact message we would have sent before and falls
back to it on ANY failure. The rich version is an upgrade, never a dependency.

Content is built as HTML rather than Markdown because only the HTML flavour can
reach the table attributes we want — `bordered striped compact` and `<caption>`.
Rich Markdown tables are plain GFM and have no syntax for them.
"""
from __future__ import annotations

import html as _html
import logging
from typing import Optional, Sequence

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


def esc(value: object) -> str:
    """Escape a value for use as rich-message HTML text.

    Cells and paragraphs carry package names an admin typed by hand, so an
    unlucky `&` or `<` must not be able to break the markup around it.
    """
    return _html.escape(" ".join(str(value if value is not None else "").split()), quote=False)


def table(
    header: Sequence[str],
    rows: Sequence[Sequence[object]],
    align: Optional[Sequence[str]] = None,
    caption: str = "",
    bordered: bool = True,
    striped: bool = True,
    compact: bool = True,
) -> str:
    """Build a rich-message HTML table.

    `bordered`/`striped`/`compact` are Telegram's own table attributes: rules
    between the cells, alternating row shading, and tighter padding. Striping is
    what makes a price list scannable on a phone — the eye keeps its row while
    crossing from the package to its price.

    Cell VALUES may contain inline markup (a `<b>` price, say) and are passed
    through as-is; escape them with `esc()` at the call site if they came from
    user input. Header text is escaped here because it is always ours.
    """
    flags = "".join(f" {name}" for name, on in
                    (("bordered", bordered), ("striped", striped), ("compact", compact)) if on)
    align = list(align or ["left"] * len(header))

    out = [f"<table{flags}>"]
    if caption:
        out.append(f"<caption>{esc(caption)}</caption>")
    out.append("<tr>" + "".join(
        f'<th align="{align[i] if i < len(align) else "left"}">{esc(h)}</th>'
        for i, h in enumerate(header)
    ) + "</tr>")
    for row in rows:
        out.append("<tr>" + "".join(
            f'<td align="{align[i] if i < len(align) else "left"}">{c}</td>'
            for i, c in enumerate(row)
        ) + "</tr>")
    out.append("</table>")
    return "".join(out)


async def answer_rich(
    message: Message,
    html: str,
    fallback: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    rtl: bool = True,
) -> bool:
    """Send `html` as a rich message, or `fallback` as a plain one if that fails
    for any reason. Returns True when the rich version was delivered.
    """
    if _supported is not False:
        try:
            await message.bot(SendRichMessage(
                chat_id=message.chat.id,
                rich_message=InputRichMessage(html=html, is_rtl=rtl),
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
    html: str,
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
                rich_message=InputRichMessage(html=html, is_rtl=rtl),
                reply_markup=reply_markup,
            ))
            globals()["_supported"] = True
            return True
        except Exception as exc:  # noqa: BLE001
            _note_failure(exc)
    await message.edit_text(fallback, reply_markup=reply_markup, parse_mode="Markdown")
    return False
