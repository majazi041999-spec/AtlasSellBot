"""
Atlas Account Bot — Main Entry Point
Runs Telegram bot and web admin panel concurrently.
"""
import asyncio
import logging
import os
import sys
import subprocess

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("atlas.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("atlas")

# Reduce noise from libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("aiogram").setLevel(logging.WARNING)


def _current_build() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def _update_text() -> str:
    return (
        "🔔 *ربات آپدیت شد!*\n\n"
        "لطفاً یک بار ربات را استارت کنید: /start\n\n"
        "اپ‌های پیشنهادی:\n"
        "[📱 V2rayNG (اندروید)](https://github.com/2dust/v2rayNG/releases/latest)\n"
        "[🍎 Streisand (iOS)](https://apps.apple.com/us/app/streisand/id6450534064)\n"
        "[🪟 v2rayN (ویندوز)](https://github.com/2dust/v2rayN/releases/latest)"
    )


async def _broadcast_update(bot, build: str) -> int:
    from core.database import count_users, get_all_users, set_setting

    total = await count_users()
    page = 0
    sent = 0
    text = _update_text()
    while page * 200 < total:
        users = await get_all_users(page * 200, 200)
        if not users:
            break
        for u in users:
            try:
                await bot.send_message(u["telegram_id"], text, disable_web_page_preview=True)
                sent += 1
            except Exception:
                pass
        page += 1

    await set_setting("last_update_broadcast", build)
    await set_setting("pending_update_build", "")
    await set_setting("update_broadcast_approved_build", "")
    logger.info(f"📣 update broadcast sent to {sent} users | build={build}")
    return sent


async def _notify_update(bot):
    from core.database import get_setting, set_setting

    build = _current_build()
    last = await get_setting("last_update_broadcast", "")
    if not build or build == "unknown" or build == last:
        return

    approved_build = await get_setting("update_broadcast_approved_build", "")
    if approved_build == build:
        await _broadcast_update(bot, build)
        return

    await set_setting("pending_update_build", build)
    logger.info(f"⏸ update broadcast pending admin approval | build={build}")



async def run_bot():
    from aiogram import Bot, Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    from core.config import BOT_TOKEN, ADMIN_IDS
    from core.database import init_db
    from bot.handlers import common, admin, user

    if not BOT_TOKEN or len(BOT_TOKEN) < 20:
        logger.error("❌ BOT_TOKEN در فایل .env تنظیم نشده!")
        return

    await init_db()
    logger.info("✅ دیتابیس آماده")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    dp = Dispatcher(storage=MemoryStorage())

    # ترتیب اهمیت دارد: common باید آخر باشه
    dp.include_router(admin.router)
    dp.include_router(user.router)
    dp.include_router(common.router)

    bot_info = await bot.get_me()
    logger.info(f"🤖 ربات @{bot_info.username} آماده | ادمین‌ها: {ADMIN_IDS}")

    await _notify_update(bot)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


async def run_web():
    import uvicorn
    from core.config import WEB_PORT, WEB_SECRET_PATH
    from core.database import init_db
    from web.app import app

    await init_db()

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=WEB_PORT,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    logger.info(f"🌐 پنل وب روی پورت {WEB_PORT} | مسیر: /{WEB_SECRET_PATH}/")
    await server.serve()


async def main():
    logger.info("🚀 Atlas Account Bot در حال راه‌اندازی...")
    await asyncio.gather(
        run_bot(),
        run_web(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 ربات متوقف شد")
