import os
from dotenv import load_dotenv
from typing import List

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_IDS: List[int] = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "0").split(",") if x.strip().isdigit()]

WEB_SECRET_PATH: str = os.getenv("WEB_SECRET_PATH", "AtlasPanel2024")
WEB_ADMIN_USERNAME: str = os.getenv("WEB_ADMIN_USERNAME", "atlas_admin")
WEB_ADMIN_PASSWORD: str = os.getenv("WEB_ADMIN_PASSWORD", "ChangeMe123!")
JWT_SECRET: str = os.getenv("JWT_SECRET", "please_change_this_secret_key_in_production")
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_HOURS: int = 24
WEB_PORT: int = int(os.getenv("WEB_PORT", "8000"))

CARD_NUMBER: str = os.getenv("CARD_NUMBER", "")
CARD_HOLDER: str = os.getenv("CARD_HOLDER", "")
CARD_BANK: str = os.getenv("CARD_BANK", "")

CHANNEL_USERNAME: str = os.getenv("CHANNEL_USERNAME", "")
DB_PATH: str = "atlas.db"
MAX_DAILY_MIGRATIONS: int = 5
REFERRAL_BONUS_GB: float = float(os.getenv("REFERRAL_BONUS_GB", "5"))
