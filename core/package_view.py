"""Render the package list as a table — for our bot and for a reseller's.

ONE implementation, two consumers. The bot's buy screen and the reseller API
return the same table because they call the same function; a second copy would
drift the first time somebody changed a column here and not there, and the thing
that drifts is a price list.

THE PREMIUM-EMOJI RULE, which is why `premium` is a parameter and not a
constant. Telegram: "Custom emoji entities can only be used by bots that
purchased additional usernames on Fragment or in the messages directly sent by
the bot to private, group and supergroup chats if the owner of the bot has a
Telegram Premium subscription."

The restriction is on the SENDING BOT, not on the emoji. A reseller whose bot
owner has no Premium cannot send them at all — the ids are fine, their bot is
not allowed to use them. So the table renders either way: `premium=True` wraps
each glyph in <tg-emoji>, `premium=False` emits the plain glyph and the table is
otherwise identical. Nobody has to choose between a clean table and a working
one.
"""
from __future__ import annotations

import html as _html
from typing import Dict, List, Optional, Sequence

from core.pricing import is_unlimited_package

# Per-tier glyphs, shared with the bot's buy buttons so a row and the button
# that buys it carry the same mark.
TIER_ROLES = (
    (25.0, "tier_xl", "💎"),
    (20.0, "tier_lg", "🚀"),
    (15.0, "tier_md", "⚡"),
    (0.0, "tier_sm", "🌱"),
)

DEFAULT_HEADERS = ("📦 پکیج", "⏱ مدت", "💰 قیمت")
DEFAULT_CAPTION = "قیمت‌ها به تومان"


def esc(value: object) -> str:
    return _html.escape(" ".join(str(value if value is not None else "").split()), quote=False)


def fa_num(value: int) -> str:
    return f"{int(value or 0):,}".replace(",", "،")


def tier_of(pkg: Dict) -> tuple:
    """(glyph, emoji role) for a package."""
    if is_unlimited_package(pkg):
        return "♾️", "tier_unlimited"
    gb = float(pkg.get("traffic_gb") or 0)
    for threshold, role, glyph in TIER_ROLES:
        if gb >= threshold:
            return glyph, role
    return "🌱", "tier_sm"


def traffic_text(pkg: Dict) -> str:
    """An unlimited plan is stored with a non-zero traffic_gb as a fair-use
    threshold, so the raw number must never be printed for one."""
    if is_unlimited_package(pkg):
        return "نامحدود"
    return f"{float(pkg.get('traffic_gb') or 0):g} گیگ"


def duration_text(pkg: Dict) -> str:
    days = int(pkg.get("duration_days") or 0)
    return "نامحدود" if days <= 0 else f"{days} روز"


def price_of(pkg: Dict) -> int:
    """The price THIS buyer pays. Callers stamp `display_price`; without one the
    package's own price is the honest fallback."""
    return int(pkg.get("display_price", pkg.get("price") or 0) or 0)


def _mark(role: str, glyph: str, premium: bool) -> str:
    if not premium:
        return glyph
    from bot.rich_message import emoji_id
    eid = emoji_id(role)
    return f'<tg-emoji emoji-id="{eid}">{glyph}</tg-emoji>' if eid else glyph


def _glyph_mark(glyph: str, premium: bool) -> str:
    if not premium:
        return glyph
    from bot.rich_message import GLYPH_PREMIUM
    eid = GLYPH_PREMIUM.get(glyph)
    return f'<tg-emoji emoji-id="{eid}">{glyph}</tg-emoji>' if eid else glyph


def table_html(
    pkgs: Sequence[Dict],
    premium: bool = True,
    headers: Optional[Sequence[str]] = None,
    caption: str = DEFAULT_CAPTION,
    highlight_unlimited: bool = True,
) -> str:
    """The package table as rich-message HTML.

    `headers` and `caption` are the reseller's to change — they sell under their
    own brand and their own wording, and a table they cannot label is a table
    they will rebuild by hand.
    """
    heads = list(headers or DEFAULT_HEADERS)
    cells = []
    for h in heads:
        h = str(h)
        # A header like "📦 پکیج" gets its glyph marked; a reseller's own wording
        # without one is simply escaped.
        if h and h[0] in "📦⏱💰📊🔑🌐♾️":
            cells.append(f"{_glyph_mark(h[0], premium)} {esc(h[1:])}")
        else:
            cells.append(esc(h))

    rows_html = []
    for p in pkgs:
        glyph, role = tier_of(p)
        star = highlight_unlimited and is_unlimited_package(p)
        name = f"{_mark(role, glyph, premium)} {esc(traffic_text(p))}"
        price = esc(fa_num(price_of(p)))
        rows_html.append([
            f"<mark><b>{name}</b></mark>" if star else name,
            esc(duration_text(p)),
            f"<mark><b>{price}</b></mark>" if star else f"<b>{price}</b>",
        ])

    out = ["<table bordered striped compact>"]
    if caption:
        out.append(f"<caption>{esc(caption)}</caption>")
    align = ["left", "center", "right"]
    out.append("<tr>" + "".join(
        f'<th align="{align[i] if i < 3 else "left"}">{c}</th>' for i, c in enumerate(cells)) + "</tr>")
    for r in rows_html:
        out.append("<tr>" + "".join(
            f'<td align="{align[i] if i < 3 else "left"}">{c}</td>' for i, c in enumerate(r)) + "</tr>")
    out.append("</table>")
    return "".join(out)


def table_markdown(pkgs: Sequence[Dict],
                   headers: Optional[Sequence[str]] = None,
                   caption: str = DEFAULT_CAPTION) -> str:
    """The same table as GitHub-flavoured Markdown.

    No custom emoji: Markdown has no syntax for one. This is the format for a
    bot that cannot use them at all, and it still renders as a real table.
    """
    heads = list(headers or DEFAULT_HEADERS)
    lines = []
    if caption:
        lines += [f"**{caption}**", ""]
    lines.append("| " + " | ".join(str(h).replace("|", "\\|") for h in heads) + " |")
    lines.append("|:---|:---:|---:|")
    for p in pkgs:
        glyph, _role = tier_of(p)
        lines.append("| {} {} | {} | **{}** |".format(
            glyph,
            traffic_text(p).replace("|", "\\|"),
            duration_text(p),
            fa_num(price_of(p))))
    return "\n".join(lines)


def screen_html(pkgs: Sequence[Dict], premium: bool = True,
                title: str = "🛒 پکیج‌ها و قیمت‌ها",
                intro: str = "", note: str = "",
                headers: Optional[Sequence[str]] = None,
                caption: str = DEFAULT_CAPTION) -> str:
    """A whole screen: heading, optional intro, the table, optional footer.

    `title`, `intro` and `note` are plain text from the caller and are escaped —
    a reseller writing their own copy must not be able to break their own
    message with an unlucky character, and must not be able to inject markup
    into a document we render on their behalf.
    """
    parts = [f"<h2>{_glyph_mark(title[0], premium)} {esc(title[1:])}</h2>"
             if title and title[0] not in "<abcdefghijklmnopqrstuvwxyz"
             else f"<h2>{esc(title)}</h2>"]
    if intro:
        parts.append(f"<p>{esc(intro)}</p>")
    parts.append(table_html(pkgs, premium=premium, headers=headers, caption=caption))
    if note:
        parts.append(f"<p>{esc(note)}</p>")
    return "".join(parts)
