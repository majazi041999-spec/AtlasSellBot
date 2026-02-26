from io import BytesIO
import qrcode
from PIL import Image, ImageDraw, ImageFont


def build_qr_image(data: str, footer_text: str = "@AtlasChannel") -> BytesIO:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=12,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#2d1fd6", back_color="white").convert("RGB")

    w, h = qr_img.size
    card_w = w + 120
    card_h = h + 200

    canvas = Image.new("RGB", (card_w, card_h), "#0f1024")
    draw = ImageDraw.Draw(canvas)

    # gradient-like background stripes
    for i in range(card_h):
        c = 15 + int(25 * i / max(1, card_h - 1))
        draw.line([(0, i), (card_w, i)], fill=(c, c, min(255, c + 40)))

    card_x, card_y = 60, 60
    draw.rounded_rectangle([card_x - 10, card_y - 10, card_x + w + 10, card_y + h + 10], radius=22, fill="#ffffff")
    canvas.paste(qr_img, (card_x, card_y))

    try:
        title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 30)
        foot_font = ImageFont.truetype("DejaVuSans.ttf", 22)
    except Exception:
        title_font = ImageFont.load_default()
        foot_font = ImageFont.load_default()

    draw.text((60, 16), "Scan QR", fill="#d9ddff", font=title_font)
    footer = (footer_text or "").strip()
    if footer and not footer.startswith("@"):
        footer = "@" + footer
    draw.text((60, card_h - 56), footer or "@AtlasChannel", fill="#d9ddff", font=foot_font)

    buf = BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    return buf
