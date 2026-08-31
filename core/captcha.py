"""Image CAPTCHA for the admin login — rendered from stroke data, not a font.

WHY NOT A TTF. Pillow is available, but the FONT is not: `core/qr.py` already
has to try three paths and fall back to `ImageFont.load_default()`, which is a
10px bitmap face. A captcha rendered in it would be unreadable, and we would
only find out from an owner locked out of their own panel. So the glyphs are
polylines defined here. Every server renders identically, there is nothing to
install, and the distortion is ours to control.

WHAT THIS IS AND IS NOT. It raises the cost of an automated login attempt; it
does not make one impossible. The alphabet is small and fixed, so someone who
decides to write a template matcher for THIS captcha specifically will
eventually beat it. That is fine, because the captcha is not the security
boundary — the rate limiter and lockout in `core/login_guard.py` are, and they
cap an attacker at a couple of dozen attempts an hour no matter how good their
solver is. The captcha's job is to stop the cheap, high-volume case and to make
the expensive case not worth building.

LEGIBILITY IS A SECURITY PROPERTY HERE. There is exactly one person who has to
read this thing, every day, on a phone. A captcha they fail twice is worse than
no captcha at all, because it trains them to weaken the setting. The distortion
below was tuned down twice for that reason, and the ambiguous glyphs (0/O, 1/I,
2/Z, 5/S, 8/B, and the loop digits 6/9 which close into a blob at this stroke
width) are simply not in the alphabet.
"""
from __future__ import annotations

import math
import random
from io import BytesIO
from typing import Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFilter

# Glyphs as polylines on a 0..1 × 0..1 grid, y pointing down. Chosen so no two
# survive distortion looking like each other.
_GLYPHS: Dict[str, List[List[Tuple[float, float]]]] = {
    "3": [[(.15, .15), (.8, .15), (.45, .45), (.85, .62), (.5, .9), (.15, .82)]],
    "4": [[(.68, .95), (.68, .05), (.12, .62), (.9, .62)]],
    "7": [[(.12, .12), (.85, .12), (.42, .95)], [(.3, .55), (.7, .55)]],
    "A": [[(.1, .95), (.5, .08), (.9, .95)], [(.26, .62), (.74, .62)]],
    "C": [[(.85, .2), (.55, .08), (.22, .28), (.18, .7), (.5, .93), (.85, .8)]],
    "E": [[(.85, .1), (.2, .1), (.2, .95), (.85, .95)], [(.2, .52), (.68, .52)]],
    "F": [[(.85, .1), (.22, .1), (.22, .95)], [(.22, .5), (.7, .5)]],
    "H": [[(.15, .08), (.15, .95)], [(.85, .08), (.85, .95)], [(.15, .52), (.85, .52)]],
    "J": [[(.75, .08), (.75, .72), (.5, .93), (.22, .78)]],
    "K": [[(.18, .08), (.18, .95)], [(.85, .08), (.18, .55), (.88, .95)]],
    "L": [[(.22, .08), (.22, .93), (.85, .93)]],
    "N": [[(.15, .95), (.15, .08), (.85, .95), (.85, .08)]],
    "P": [[(.2, .95), (.2, .1), (.68, .12), (.82, .34), (.62, .54), (.2, .55)]],
    "T": [[(.1, .12), (.9, .12)], [(.5, .12), (.5, .95)]],
    "U": [[(.15, .08), (.16, .7), (.5, .93), (.84, .7), (.85, .08)]],
    "X": [[(.14, .08), (.86, .95)], [(.86, .08), (.14, .95)]],
    "Y": [[(.14, .08), (.5, .5), (.86, .08)], [(.5, .5), (.5, .95)]],
}

ALPHABET = "".join(_GLYPHS)
LENGTH = 5                     # 17**5 ≈ 1.42M — far past what the limiter allows
_BG = (18, 22, 38)             # matches the panel's --panel-solid
_INK = [(233, 238, 255), (167, 139, 250), (125, 211, 252), (110, 231, 183)]


def new_code(rnd: random.Random | None = None) -> str:
    r = rnd or random.SystemRandom()
    return "".join(r.choice(ALPHABET) for _ in range(LENGTH))


# A Persian keyboard produces Persian (and sometimes Arabic) digits, and phones
# love to lower-case. Those are the same answer and must not be a failed login.
_DIGIT_FOLD = str.maketrans({"۳": "3", "٣": "3", "۴": "4", "٤": "4", "۷": "7", "٧": "7"})


def normalize(answer: str) -> str:
    """Canonical form of what the admin typed.

    Deliberately only case-folds, translates Persian/Arabic digits and drops
    whitespace. It does NOT drop unrecognised characters: silently deleting a
    stray keystroke could turn a typo into a right-length wrong answer, and the
    comparison downstream is exact.
    """
    return "".join((answer or "").translate(_DIGIT_FOLD).upper().split())


def _warp(pt, cx, cy, rot, sx, sy, shear):
    x, y = (pt[0] - .5) * sx, (pt[1] - .5) * sy
    x += y * shear
    c, s = math.cos(rot), math.sin(rot)
    return (cx + (x * c - y * s), cy + (x * s + y * c))


def render_png(code: str, width: int = 260, height: int = 92, scale: int = 3) -> bytes:
    """Draw `code` distorted, as PNG bytes. Supersampled then downscaled so the
    strokes come out antialiased without needing a font renderer."""
    rnd = random.SystemRandom()
    W, H = width * scale, height * scale
    img = Image.new("RGB", (W, H), _BG)
    d = ImageDraw.Draw(img)

    # Speckle + arcs in the panel's own palette, so the widget reads as part of
    # the UI rather than a pasted-in third-party box.
    for _ in range(rnd.randint(90, 140)):
        x, y = rnd.randrange(W), rnd.randrange(H)
        r = rnd.randint(1, 3) * scale
        d.ellipse([x, y, x + r, y + r], fill=(38, 46, 78))
    for _ in range(3):
        x0 = rnd.randrange(0, W // 2)
        d.arc([x0, rnd.randrange(-H, H // 2), x0 + rnd.randrange(W // 2, W), rnd.randrange(H // 2, H * 2)],
              rnd.randrange(0, 180), rnd.randrange(180, 360), fill=(52, 60, 100), width=2 * scale)

    slot = W / (len(code) + .6)
    for i, ch in enumerate(code):
        cx = slot * (i + .8) + rnd.uniform(-.07, .07) * slot
        cy = H / 2 + rnd.uniform(-.09, .09) * H
        rot = rnd.uniform(-.26, .26)
        sx = slot * rnd.uniform(.80, .96)
        sy = H * rnd.uniform(.66, .82)
        shear = rnd.uniform(-.18, .18)
        # Per-glyph colour: a solver cannot isolate the text by hue.
        col = rnd.choice(_INK)
        w = int(scale * rnd.uniform(3.6, 4.6))
        for poly in _GLYPHS[ch]:
            pts = [_warp(p, cx, cy, rot, sx, sy, shear) for p in poly]
            d.line(pts, fill=col, width=w, joint="curve")
            for p in pts:                       # round the joints
                r = w / 2
                d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=col)

    # One thin cutting line, drawn OVER the glyphs in an ink colour so a
    # threshold pass cannot separate it from the text. Kept to one, and out of
    # the vertical middle, because two shredded the glyphs for humans too.
    pts = [(rnd.randrange(W), rnd.randrange(int(H * .2), int(H * .8))) for _ in range(4)]
    d.line(sorted(pts), fill=rnd.choice(_INK[:2]), width=int(scale * 1.2), joint="curve")

    img = img.resize((width, height), Image.LANCZOS).filter(ImageFilter.SMOOTH)
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
