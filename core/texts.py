from core.database import get_setting
from core.panel_content import BOT_TEXT_DEFAULTS


async def get_text(key: str, **kwargs) -> str:
    setting_key = key if key.startswith("text.") else f"text.{key}"
    default = BOT_TEXT_DEFAULTS.get(setting_key, "")
    if setting_key == "text.welcome_message":
        default = await get_setting("welcome_message", default)
    value = await get_setting(setting_key, default)
    try:
        return value.format(**kwargs)
    except Exception:
        return value

