"""Persian-aware sorting helpers.

SQLite's built-in collations (BINARY / NOCASE) order text by UTF-8 bytes. For
Persian that is wrong: پ چ ژ ک گ ی live in a later Unicode range than the rest
of the Arabic block, so names starting with them all pile up at the end of an
A→Z list. Anything that offers "sort by name" to a Persian user goes through
here instead.
"""

# Persian alphabet in dictionary order.
FA_ALPHABET = "آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی"
_FA_INDEX = {ch: i for i, ch in enumerate(FA_ALPHABET)}

# Arabic look-alikes users type interchangeably — fold them onto the Persian
# letter so "علي" and "علی" sort together instead of landing far apart.
_FA_NORMALIZE = str.maketrans({
    "ي": "ی", "ى": "ی", "ئ": "ی",
    "ك": "ک",
    "ة": "ه", "ۀ": "ه",
    "أ": "ا", "إ": "ا", "ٱ": "ا",
    "ؤ": "و",
    "‌": " ",   # ZWNJ (نیم‌فاصله) — treat as a space
    "ً": "", "ٌ": "", "ٍ": "",   # tanvin
    "َ": "", "ُ": "", "ِ": "",   # harakat
    "ّ": "", "ْ": "",
})

# Persian letters sort after ASCII (digits, then Latin) — a predictable,
# stable grouping rather than an accident of code points.
_FA_OFFSET = 0x10000


def fa_sort_key(value) -> list:
    """Sort key that orders Persian text alphabetically, ASCII first."""
    text = str(value or "").translate(_FA_NORMALIZE).strip().lower()
    return [_FA_INDEX[ch] + _FA_OFFSET if ch in _FA_INDEX else ord(ch) for ch in text]


def fa_collation(a, b) -> int:
    """SQLite collation callback: -1 / 0 / 1."""
    ka, kb = fa_sort_key(a), fa_sort_key(b)
    return (ka > kb) - (ka < kb)
