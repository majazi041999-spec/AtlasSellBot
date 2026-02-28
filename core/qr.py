from io import BytesIO
import math

import qrcode
from PIL import Image, ImageDraw, ImageFilter, ImageFont


def _load_font(size: int, bold: bool = False):
    candidates = [
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _gradient_background(width: int, height: int) -> Image.Image:
    bg = Image.new("RGB", (width, height), "#0f1226")
    draw = ImageDraw.Draw(bg)

    top = (98, 82, 255)
    mid = (22, 170, 220)
    bottom = (14, 20, 45)

    for y in range(height):
        t = y / max(1, height - 1)
        if t < 0.6:
            k = t / 0.6
            r = int(top[0] + (mid[0] - top[0]) * k)
            g = int(top[1] + (mid[1] - top[1]) * k)
            b = int(top[2] + (mid[2] - top[2]) * k)
        else:
            k = (t - 0.6) / 0.4
            r = int(mid[0] + (bottom[0] - mid[0]) * k)
            g = int(mid[1] + (bottom[1] - mid[1]) * k)
            b = int(mid[2] + (bottom[2] - mid[2]) * k)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse((-120, -70, width // 2, height // 2), fill=(255, 255, 255, 34))
    gdraw.ellipse((width // 2 - 20, height // 2 - 60, width + 80, height + 60), fill=(255, 105, 180, 28))
    gdraw.ellipse((width // 2 - 200, height - 200, width // 2 + 180, height + 120), fill=(60, 255, 220, 35))
    glow = glow.filter(ImageFilter.GaussianBlur(22))

    return Image.alpha_composite(bg.convert("RGBA"), glow).convert("RGB")


def build_qr_image(data: str, footer_text: str = "@AtlasChannel") -> BytesIO:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=14,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#1e1465", back_color="white").convert("RGB")

    qrw, qrh = qr_img.size
    card_w = qrw + 190
    card_h = qrh + 280

    canvas = _gradient_background(card_w, card_h)
    draw = ImageDraw.Draw(canvas)

    # glass card shadow
    shadow = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    glass_rect = (42, 64, card_w - 42, card_h - 74)
    sdraw.rounded_rectangle((glass_rect[0] + 5, glass_rect[1] + 12, glass_rect[2] + 5, glass_rect[3] + 12), radius=34, fill=(0, 0, 0, 60))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), shadow)
    draw = ImageDraw.Draw(canvas)

    draw.rounded_rectangle(glass_rect, radius=34, fill=(255, 255, 255, 28), outline=(255, 255, 255, 80), width=2)

    qr_panel = (82, 132, 82 + qrw + 24, 132 + qrh + 24)
    draw.rounded_rectangle(qr_panel, radius=24, fill="#ffffff")
    canvas.paste(qr_img, (qr_panel[0] + 12, qr_panel[1] + 12))

    title_font = _load_font(40, bold=True)
    sub_font = _load_font(24, bold=False)
    footer_font = _load_font(22, bold=False)

    draw.text((80, 76), "Atlas VPN", fill="#ffffff", font=title_font)
    draw.text((80, 110), "Scan to import config", fill="#dbe4ff", font=sub_font)

    footer = (footer_text or "").strip()
    if footer and not footer.startswith("@"):
        footer = "@" + footer
    footer = footer or "@AtlasChannel"
    draw.text((80, card_h - 118), footer, fill="#eff3ff", font=footer_font)

    # Decorative tiny stars
    for i in range(12):
        x = int(30 + (card_w - 60) * (i / 11))
        y = int(26 + 10 * math.sin(i * 0.75))
        draw.ellipse((x, y, x + 3, y + 3), fill=(255, 255, 255, 170))

    out = BytesIO()
    canvas.convert("RGB").save(out, format="PNG")
    out.seek(0)
    return out
