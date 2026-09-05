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
    # brand and menu
    "brand": "5895520960894733929",       # beside "اطلس اکانت", wherever it appears
    "bank": "5789532541102855208",        # beside the card number on a payment screen
    "trial": "5406756500108501710",       # base glyph 🆓 — chosen for the free trial
    "services": "5271604874419647061",
    "assistant": "5352899869369446268",
    "orders": "5980808493018387732",
    "support": "6010260496811299512",   # owner picked this one by eye
    "invite": "5274074880046802038",
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


# ─────────────── every plain emoji that HAS a premium counterpart ────────────
# Built by reading the sticker sets the owner's own emoji come from, then
# matching each set entry's base glyph against the emoji already in this
# codebase. 89 of the 131 distinct glyphs we use are covered; the rest have no
# counterpart in those sets and stay plain.
#
# Used two ways: `_button` swaps a button's leading glyph for the real thing
# automatically, and `premiumize()` does the same inside an HTML message body.
#
# To change one, edit the id here — every button and message follows.
GLYPH_PREMIUM = {
    "❌": "5895714560840568825",   # x139  CenterOfEmoji22890889
    "✅": "5895572268574051666",   # x114  CenterOfEmoji22890889
    "📊": "5282734530547951466",   # x24  AR_PREMIUM
    "💰": "5318912792428814144",   # x22  Decoration_Pack2
    "💳": "5213403875670765022",   # x21  DecorationEmojiPack
    "🛒": "5316650495715057696",   # x20  Decoration_Pack2
    "🟢": "5818812952362356039",   # x20  iconemoji1
    "🎁": "5895347444215975839",   # x20  CenterOfEmoji22890889
    "🔴": "5818717642743090785",   # x19  iconemoji1
    "🌐": "5895665559558689321",   # x18  CenterOfEmoji22890889
    "📦": "5987792582288086421",   # x17  CenterOfEmoji61682288
    "⛔": "5017122105011995219",   # x17  VariousAnimations9
    "🗑": "5979070714890686650",   # x16  iconemoji1
    "🚀": "5895497153891011900",   # x14  CenterOfEmoji22890889
    "🔑": "5978854270013804830",   # x13  iconemoji1
    "🔗": "5990023031819341856",   # x13  CenterOfEmoji99428805
    "👤": "5818715087237549366",   # x13  iconemoji1
    "➕": "5818651538901437748",   # x12  iconemoji1
    "🔄": "5865956613642259750",   # x11  iconemoji1
    "👥": "5985335113670464151",   # x11  CenterOfEmoji61682288
    "🔎": "5895564043711680203",   # x11  CenterOfEmoji22890889
    "🖥": "5316891065423241127",   # x10  Decoration_Pack2
    "📱": "5819099456745770209",   # x10  iconemoji1
    "👋": "5316961099159968983",   # x9  Decoration_Pack2
    "👇": "5470124868500465804",   # x9  neon_td
    "🧬": "5215621964286142449",   # x8  DecorationEmojiPack
    "🎉": "5316778159322963296",   # x8  Decoration_Pack2
    "🆔": "5818885490065017876",   # x8  iconemoji1
    "📣": "5988015508270615551",   # x7  CenterOfEmoji61682288
    "⚡": "5895638385300606573",   # x7  CenterOfEmoji22890889
    "📍": "5821128296217185461",   # x6  iconemoji1
    "🕊": "5895661346195771163",   # x6  CenterOfEmoji22890889
    "♾": "5895324105363689572",   # x6  CenterOfEmoji22890889
    "🎨": "5866017524868452229",   # x5  iconemoji1
    "📈": "5084922505991291559",   # x5  EmojiTechPack2
    "🔍": "5319230516929502602",   # x5  Decoration_Pack2
    "📝": "5082613952479757015",   # x5  EmojiTechPack2
    "👁": "5886667040432853038",   # x5  iconemoji1
    "🙈": "5294363352070367389",   # x5  vector_icons_by_fStikBot
    "📄": "5987635334945444280",   # x5  CenterOfEmoji61682288
    "📤": "5992519984071315160",   # x5  CenterOfEmoji99428805
    "🔥": "5317058732356542197",   # x5  Decoration_Pack2
    "💵": "5215239948420003628",   # x5  DecorationEmojiPack
    "🔘": "5888489858913014264",   # x5  iconemoji1
    "🌟": "5895312513246956764",   # x5  CenterOfEmoji22890889
    "📞": "5895730568183681309",   # x4  CenterOfEmoji22890889
    "🛍": "5213348870024605308",   # x4  DecorationEmojiPack
    "📶": "5821276292200271408",   # x4  iconemoji1
    "🔐": "5895685239098838464",   # x4  CenterOfEmoji22890889
    "🏠": "5897974332113554932",   # x4  CenterOfEmoji22890889
    "📧": "5992200618893119382",   # x4  CenterOfEmoji99428805
    "🎯": "5274266216544871353",   # x4  AR_PREMIUM
    "🤖": "5314391089514291948",   # x4  Decoration_Pack2
    "👑": "5895227687642861193",   # x4  CenterOfEmoji22890889
    "💼": "5980808493018387732",   # x4  iconemoji1
    "🔌": "5080569852989538868",   # x3  EmojiTechPack2
    "🖼": "5987725052517290172",   # x3  CenterOfEmoji61682288
    "🔤": "5285137865397773116",   # x3  AR_PREMIUM
    "🔃": "5888469298904567505",   # x3  iconemoji1
    "🔒": "5985555183499743416",   # x3  CenterOfEmoji61682288
    "💎": "6244241334320762892",   # x3  Statusvideobytaraxd
    "💡": "5314737096374624681",   # x3  Decoration_Pack2
    "🏆": "5316979941181496594",   # x3  Decoration_Pack2
    "🔧": "5258023599419171861",   # x3  vector_icons_by_fStikBot
    "📚": "5987936747160342935",   # x3  CenterOfEmoji61682288
    "🔵": "5895304150945633173",   # x2  CenterOfEmoji22890889
    "😕": "5456667726644780828",   # x2  MemeEmoji
    "📸": "5818849313555483639",   # x2  iconemoji1
    "💬": "5818984364507139347",   # x2  iconemoji1
    "🚪": "5988038228647612587",   # x2  CenterOfEmoji61682288
    "🔓": "5981075141767990672",   # x2  iconemoji1
    "🌱": "5895281744101247904",   # x2  CenterOfEmoji71658928
    "🆓": "5082873029202019100",   # x2  EmojiTechPack2
    "🍎": "5895717395518984341",   # x2  CenterOfEmoji22890889
    "💸": "5895325492638125139",   # x2  CenterOfEmoji22890889
    "⭐": "5895651600914975891",   # x2  CenterOfEmoji22890889
    "🕐": "5992184495585889960",   # x2  CenterOfEmoji99428805
    "🙏": "5319240910750359759",   # x2  Decoration_Pack2
    "🛠": "5213214428958306222",   # x2  DecorationEmojiPack
    "🟡": "5895443668663275064",   # x2  CenterOfEmoji22890889
    "👈": "5469755973759413789",   # x2  neon_td
    "👀": "5818845400840277279",   # x2  iconemoji1
    "❓": "5215320603610852113",   # x2  DecorationEmojiPack
    "📎": "5305265301917549162",   # x2  NewsEmoji
    "🔁": "5472012979073456920",   # x2  TgDuckX
    "😉": "5168337651417219882",   # x2  Mememojiszzz
    "😎": "6298597328022407025",   # x2  Statusvideobytaraxd
    "🛡": "5895576786879647172",   # x2  CenterOfEmoji22890889
    "📲": "5316994054444033034",   # x2  Decoration_Pack2
    "✨": "5895512031657725404",   # x2  CenterOfEmoji22890889
    "📉": "5084657308940632650",   # x2  EmojiTechPack2
    "👆": "5469891106315446822",   # x1  neon_td
}

# Glyphs the owner picked BY HAND for a specific slot. Without this the same
# emoji could render two ways: their chosen cart on the buy button, and whatever
# a sticker set happened to offer on every other 🛒 in the bot.
GLYPH_PREMIUM.update({
    "🛒": PREMIUM_EMOJI["cart"],
    "🏦": PREMIUM_EMOJI["bank"],
    "🎁": PREMIUM_EMOJI["invite"],
    "📞": PREMIUM_EMOJI["support"],
    "🤖": PREMIUM_EMOJI["assistant"],
})


def premiumize(html_text: str) -> str:
    """Swap plain emoji for their premium versions inside HTML message text.

    ONLY safe on text that is already valid HTML and will be sent with
    parse_mode="HTML" — a custom emoji has no Markdown syntax, so running this
    over a Markdown message would put raw tags in front of the customer.
    """
    out = html_text
    for glyph, eid in GLYPH_PREMIUM.items():
        if glyph in out:
            out = out.replace(glyph, f'<tg-emoji emoji-id="{eid}">{glyph}</tg-emoji>')
    return out


def split_leading_emoji(text: str) -> tuple:
    """("🛒 خرید", ...) -> ("🛒", "خرید") when the glyph has a premium version.

    Only the FIRST character is considered: a button icon sits before the label,
    so an emoji in the middle of one has no slot to move into.
    """
    stripped = text.lstrip()
    if stripped and stripped[0] in GLYPH_PREMIUM:
        return stripped[0], stripped[1:].lstrip()
    return "", text


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
