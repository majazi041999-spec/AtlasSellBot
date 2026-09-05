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

# Premium (custom) emoji used in bot messages, keyed by the ROLE they play — so
# swapping the artwork is a one-line change here and never a hunt through copy.
#
# Telegram renders these only where the bot may use custom emoji: a private,
# group or supergroup chat, given the bot owner has Premium. Channels are
# excluded, so a channel post falls back to the plain glyph on its own.
#
# Ids come from the /emojiid admin command. Set one to "" to drop back to the
# plain emoji without touching any of the call sites.
PREMIUM_EMOJI = {
    # buy-screen chrome
    "cart": "5258024802010026053",
    "speed": "5422609593765241366",
    "link": "5990332467033150285",
    "col_package": "5895699833397710656",
    "col_duration": "5834822129425584578",
    "col_price": "5427107837568360763",
    "infinity": "5212980778442435830",
    "bestseller": "5976567925778158529",
    # One per package tier. The table row and its BUTTON share these on purpose:
    # matching icons are what let a customer find the button that buys the row
    # they were just reading, without re-reading either.
    "tier_sm": "5983151543707242938",         # under 15 GB
    "tier_md": "5981116424993640232",         # 15-19 GB
    "tier_lg": "5981305412144599367",         # 20-24 GB
    "tier_xl": "5168180717607191003",         # 25 GB and up
    "tier_unlimited": "5168355222128427844",
}


def emoji(role: str, fallback: str) -> str:
    """A premium emoji by role, or the plain glyph when none is configured.

    `fallback` doubles as the alt text Telegram shows wherever the custom emoji
    cannot be drawn — an old client, a channel, a viewer with images off — so
    the sentence reads correctly either way. It is OUR glyph, not the sticker's
    own: the point is the slot it fills in the copy.
    """
    eid = emoji_id(role)
    return f'<tg-emoji emoji-id="{eid}">{fallback}</tg-emoji>' if eid else fallback


def emoji_id(role: str) -> str:
    """The bare custom-emoji id for a role.

    For fields that take an id instead of markup — an inline button's
    `icon_custom_emoji_id`, where there is no HTML to put a <tg-emoji> in.
    Returns "" when the role has no emoji, which every caller treats as
    "just use the plain glyph".
    """
    return (PREMIUM_EMOJI.get(role) or "").strip()


def _note_failure(exc: Exception) -> None:
    global _supported
    text = str(exc).lower()
    if any(hint in text for hint in _UNSUPPORTED_HINTS):
        _supported = False
        log.warning("rich messages unsupported by this Bot API server, disabling: %s", exc)
    else:
        log.warning("rich message send failed, fell back to plain text: %s", exc)


def date_time_entities(text: str, anchor: str, value: str, unix_time: int,
                       fmt: str = "r") -> list:
    """One `date_time` entity over `value`, where it follows `anchor` in `text`.

    Telegram renders such an entity in the READER's timezone and language, and a
    relative one ("in 12 days") keeps counting down without us resending
    anything — which is the whole point here, since a day count baked into the
    text is stale the moment it is sent.

    Attached as an entity rather than by switching the message to HTML on
    purpose: the status card carries a raw subscription URL, an admin-written
    guide and a customer's own service name, none of it escaped. Escaping all
    three to gain one date would be a poor trade.

    `anchor` is the text immediately before the value — the label — because the
    value alone ("۱۲ روز") is not unique in a card that also counts gigabytes.
    """
    if not value or not text or int(unix_time or 0) <= 0:
        return []
    at = text.find(anchor + value)
    if at < 0:
        return []
    head = text[: at + len(anchor)]
    # Telegram counts offsets in UTF-16 code units. Persian text is one unit per
    # character but a single emoji is two, so len() is not the same number.
    offset = len(head.encode("utf-16-le")) // 2
    length = len(value.encode("utf-16-le")) // 2
    # Documented cap once any format flag is set.
    if length > 31:
        return []
    try:
        from aiogram.types import MessageEntity
        return [MessageEntity(type="date_time", offset=offset, length=length,
                              unix_time=int(unix_time), date_time_format=fmt)]
    except Exception as exc:  # pragma: no cover - older aiogram
        log.warning("date_time entity unavailable, showing plain text: %s", exc)
        return []


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

    Header and cell VALUES may both contain inline markup — a `<b>` price, a
    `<tg-emoji>` icon — and are passed through as-is. Escape anything that came
    from user input with `esc()` at the call site.
    """
    flags = "".join(f" {name}" for name, on in
                    (("bordered", bordered), ("striped", striped), ("compact", compact)) if on)
    align = list(align or ["left"] * len(header))

    out = [f"<table{flags}>"]
    if caption:
        out.append(f"<caption>{esc(caption)}</caption>")
    out.append("<tr>" + "".join(
        f'<th align="{align[i] if i < len(align) else "left"}">{h}</th>'
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
