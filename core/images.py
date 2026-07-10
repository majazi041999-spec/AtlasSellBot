"""Small image helpers shared by the web panel and the bot (logo processing)."""
import base64
import logging

logger = logging.getLogger(__name__)


def process_logo_bytes(data: bytes, size: int = 256) -> str | None:
    """Resize an uploaded image to a <=size square PNG and return a data: URI.

    One upload then works everywhere (subscription browser page, panel, favicon).
    Falls back to the raw bytes (capped) if Pillow isn't available."""
    if not data:
        return None
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(data))
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA")
        im.thumbnail((size, size))
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        logger.warning("logo resize failed, storing raw: %s", e)
        if len(data) <= 250_000:
            head = data[:12]
            mime = "image/png"
            if head[:3] == b"\xff\xd8\xff":
                mime = "image/jpeg"
            elif head[:6] in (b"GIF87a", b"GIF89a"):
                mime = "image/gif"
            elif head[:4] == b"RIFF" and data[8:12] == b"WEBP":
                mime = "image/webp"
            return f"data:{mime};base64," + base64.b64encode(data).decode()
    return None
