"""
Atlas Account Bot — Main Entry Point
Runs Telegram bot and web admin panel concurrently.
"""
import asyncio
import logging
import os
import sys

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
