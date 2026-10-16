"""One validated image contract for the editor, previews and Telegram delivery."""
import base64
import binascii
from io import BytesIO

from PIL import Image, UnidentifiedImageError


def campaign_photo_bytes(value: str) -> bytes:
    if not value:
        return b""
    try:
        header, encoded = value.split(",", 1)
        if not header.startswith("data:image/") or not header.endswith(";base64") or len(value) > 3_000_000:
            raise ValueError
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError
        with Image.open(BytesIO(raw)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"} or image.width * image.height > 20_000_000:
                raise ValueError
            image.load()
            image = image.convert("RGB")
            image.thumbnail((1600, 1600))
            # Extremely thin images violate Telegram's photo aspect-ratio limit.
            if max(image.size) > 20 * min(image.size):
                raise ValueError
            out = BytesIO()
            image.save(out, "JPEG", quality=90, optimize=True)
            return out.getvalue()
    except (ValueError, binascii.Error, OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError("عکس نامعتبر است؛ یک تصویر PNG، JPEG یا WebP زیر ۲ مگابایت انتخاب کن.") from exc


async def send_campaign_message(bot, chat_id: int, text: str, photo: bytes = b"", **kwargs):
    if not photo:
        return await bot.send_message(chat_id, text, parse_mode=None, **kwargs)
    from aiogram.types import BufferedInputFile
    image = BufferedInputFile(photo, filename="atlas-campaign.jpg")
    if len(text.encode("utf-16-le")) // 2 <= 1024:
        return await bot.send_photo(chat_id, image, caption=text, parse_mode=None, **kwargs)
    # Send media before text; a media failure must not silently become text-only.
    await bot.send_photo(chat_id, image)
    return await bot.send_message(chat_id, text, parse_mode=None, **kwargs)
