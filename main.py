"""
Atlas Account Bot — Main Entry Point
Runs Telegram bot and web admin panel concurrently.
"""
import asyncio
import logging
import os
import sys
import time
import subprocess
from datetime import datetime, timedelta


def _setup_logging():
    fmt = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    handlers = [logging.StreamHandler(sys.stdout)]
    log_candidates = [
        os.getenv("ATLAS_LOG_PATH", "").strip(),
        os.path.join(os.getcwd(), "atlas.log"),
        "/tmp/atlas-bot.log",
    ]
    for path in log_candidates:
        if not path:
            continue
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            handlers.append(logging.FileHandler(path, encoding="utf-8"))
            break
        except OSError:
            continue
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


_setup_logging()
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
    from core.update_notes import DEFAULT_UPDATE_BROADCAST_TEXT

    return DEFAULT_UPDATE_BROADCAST_TEXT


async def _broadcast_update(bot, build: str) -> int:
    from core.database import count_users, get_all_users, set_setting
    from core.update_notes import get_update_broadcast_text

    total = await count_users()
    page = 0
    sent = 0
    text = await get_update_broadcast_text()
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
    await set_setting("pending_update_text", "")
    await set_setting("pending_update_text_build", "")
    await set_setting("update_broadcast_approved_build", "")
    await set_setting("skipped_update_build", "")
    logger.info(f"📣 update broadcast sent to {sent} users | build={build}")
    return sent


async def _notify_update(bot):
    from core.database import get_setting, set_setting

    build = _current_build()
    last = await get_setting("last_update_broadcast", "")
    skipped = await get_setting("skipped_update_build", "")
    if not build or build == "unknown" or build == last or build == skipped:
        return

    approved_build = await get_setting("update_broadcast_approved_build", "")
    if approved_build == build:
        await _broadcast_update(bot, build)
        return

    await set_setting("pending_update_build", build)
    if await get_setting("pending_update_text_build", "") != build:
        await set_setting("pending_update_text", _update_text())
        await set_setting("pending_update_text_build", build)
    logger.info(f"⏸ update broadcast pending admin approval | build={build}")


def _parse_db_datetime(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime((value or "")[:26], fmt)
        except Exception:
            pass
    return datetime.now()


async def _repair_missing_expiries():
    from core.database import get_configs_needing_expiry_repair, update_config
    from core.xui_api import XUIClient

    repaired = failed = 0
    for cfg in await get_configs_needing_expiry_repair():
        start = _parse_db_datetime(cfg.get("created_at", ""))
        expire_ms = int((start + timedelta(days=int(cfg.get("duration_days") or 0))).timestamp() * 1000)
        if expire_ms <= int(datetime.now().timestamp() * 1000):
            expire_ms = int((datetime.now() + timedelta(days=int(cfg.get("duration_days") or 0))).timestamp() * 1000)
        cli = XUIClient(
            cfg["server_url"],
            cfg["srv_user"],
            cfg["srv_pass"],
            cfg.get("sub_path") or "",
            cfg.get("srv_api_token") or "",
        )
        try:
            ok = await cli.update_client(
                cfg["inbound_id"],
                cfg["uuid"],
                cfg["email"],
                cfg["traffic_gb"],
                expire_ms,
                bool(cfg.get("is_active", 1)),
            )
            if ok:
                await update_config(cfg["id"], expire_timestamp=expire_ms, starts_on_first_use=0)
                repaired += 1
            else:
                failed += 1
        except Exception:
            failed += 1
        finally:
            await cli.close()
    if repaired or failed:
        logger.info(f"🛠 expiry repair done | repaired={repaired} failed={failed}")


VOLUME_ALERTS = [
    (1024 ** 3, "volume_1gb", "۱ گیگابایت"),
    (500 * 1024 ** 2, "volume_500mb", "۵۰۰ مگابایت"),
    (200 * 1024 ** 2, "volume_200mb", "۲۰۰ مگابایت"),
]
TIME_ALERTS = [
    (3, "time_3d", "۳ روز"),
    (2, "time_2d", "۲ روز"),
    (1, "time_1d", "۱ روز"),
]


def _pick_crossed_threshold(value: int, thresholds: list[tuple[int, str, str]]):
    selected = None
    crossed = []
    for limit, key, label in thresholds:
        if value <= limit:
            selected = (limit, key, label)
            crossed.append((limit, key, label))
    return selected, crossed


async def _config_alert_worker(bot):
    from core.database import (
        get_active_configs_for_alerts,
        get_config_alerts_sent,
        mark_config_alert_sent,
        get_setting,
        update_config,
    )
    from core.xui_api import XUIClient, fmt_bytes, days_left

    await asyncio.sleep(20)
    while True:
        checked = sent = 0
        try:
            configs = await get_active_configs_for_alerts(1000)
            for cfg in configs:
                checked += 1
                total = int(float(cfg.get("traffic_gb") or 0) * 1024 ** 3)
                used = 0
                expire_ms = int(cfg.get("expire_timestamp") or 0)
                cli = XUIClient(
                    cfg["server_url"],
                    cfg["srv_user"],
                    cfg["srv_pass"],
                    cfg.get("sub_path") or "",
                    cfg.get("srv_api_token") or "",
                )
                try:
                    traffic = await cli.get_client_traffic(cfg["email"])
                    if traffic:
                        total = int(traffic.get("total") or total)
                        used = int(traffic.get("down") or 0) + int(traffic.get("up") or 0)
                        remote_expire = int(traffic.get("expiryTime") or 0)
                        if remote_expire > 0:
                            expire_ms = remote_expire
                            if remote_expire != int(cfg.get("expire_timestamp") or 0):
                                await update_config(cfg["id"], expire_timestamp=remote_expire)
                finally:
                    await cli.close()

                sent_alerts = await get_config_alerts_sent(cfg["id"])
                remaining = max(0, total - used) if total > 0 else 0

                volume_selected = None
                volume_crossed = []
                if total > 0:
                    volume_selected, volume_crossed = _pick_crossed_threshold(remaining, VOLUME_ALERTS)

                time_selected = None
                time_crossed = []
                dl = days_left(expire_ms)
                if dl >= 0:
                    time_selected, time_crossed = _pick_crossed_threshold(dl, TIME_ALERTS)

                messages = []
                if volume_selected and ("volume", volume_selected[1]) not in sent_alerts:
                    for _, key, _ in volume_crossed:
                        await mark_config_alert_sent(cfg["id"], "volume", key)
                    messages.append(
                        f"حجم سرویس {cfg['email']} رو به اتمام است.\n"
                        f"باقی‌مانده: {fmt_bytes(remaining)}\n"
                        f"مصرف‌شده: {fmt_bytes(used)} از {fmt_bytes(total)}"
                    )
                if time_selected and ("time", time_selected[1]) not in sent_alerts:
                    for _, key, _ in time_crossed:
                        await mark_config_alert_sent(cfg["id"], "time", key)
                    messages.append(
                        f"زمان سرویس {cfg['email']} رو به اتمام است.\n"
                        f"زمان باقی‌مانده: حدود {time_selected[2]}"
                    )

                for text in messages:
                    try:
                        await bot.send_message(cfg["telegram_id"], "⚠️ " + text, parse_mode=None)
                        sent += 1
                        await asyncio.sleep(0.1)
                    except Exception:
                        pass
        except Exception as e:
            logger.exception("config alert worker failed: %s", e)

        if checked or sent:
            logger.info(f"config alerts checked={checked} sent={sent}")
        try:
            interval = int(await get_setting("config_alert_check_interval", "3600") or 3600)
        except Exception:
            interval = 3600
        await asyncio.sleep(max(300, interval))


async def _daily_report_worker(bot):
    from core.config import ADMIN_IDS
    from core.database import (
        snapshot_daily_report,
        mark_daily_report_sent,
        format_daily_report,
        get_all_admin_telegram_ids,
    )
    from core.jalali import tehran_now

    await asyncio.sleep(35)
    while True:
        try:
            report = await snapshot_daily_report()
            now = tehran_now()
            if now.hour >= 23 and not int(report.get("sent_to_admins") or 0):
                text = format_daily_report(report)
                targets = list(dict.fromkeys(list(ADMIN_IDS) + await get_all_admin_telegram_ids()))
                for aid in targets:
                    try:
                        await bot.send_message(aid, text, parse_mode=None)
                        await asyncio.sleep(0.1)
                    except Exception:
                        pass
                await mark_daily_report_sent(report["jalali_date"])
        except Exception as e:
            logger.exception("daily report worker failed: %s", e)
        await asyncio.sleep(1800)


async def _multi_subscription_worker():
    from core.multi_subscription import sync_active_profiles, sync_subscription_nodes_for_all
    from core.database import get_setting

    await asyncio.sleep(30)
    last_full_sync = 0.0
    while True:
        try:
            # Cheap frequent pass: enforce quota/expiry so finished subs are
            # disabled fast and the sub link starts showing the renew notice.
            checked = await sync_active_profiles(200, usage_only=True)
            if checked:
                logger.info(f"multi-sub usage checked={checked}")

            # Full node reconcile (create missing / remove orphaned / repair
            # links) on a panel-configurable cadence. This is the automatic
            # "config sync" — toggleable and defaulting to hourly.
            if await get_setting("sub_auto_sync_enabled", "1") == "1":
                try:
                    interval_h = float(await get_setting("sub_auto_sync_interval_hours", "1") or 1)
                except (TypeError, ValueError):
                    interval_h = 1.0
                interval_s = max(900, int(interval_h * 3600))
                now = time.time()
                if now - last_full_sync >= interval_s - 30:
                    last_full_sync = now
                    result = await sync_subscription_nodes_for_all(5000, force_refresh=False)
                    logger.info(
                        "auto sub node-sync: checked=%s created=%s refreshed=%s moved=%s removed=%s failed=%s",
                        result.get("checked"), result.get("created"), result.get("refreshed"),
                        result.get("moved"), result.get("removed"), result.get("failed"),
                    )
        except Exception as e:
            logger.exception("multi-sub worker failed: %s", e)
        await asyncio.sleep(180)


async def _single_to_sub_nudge_worker(bot):
    """Periodically nudge users who still have single configs to convert to a sub."""
    import time as _t
    from core.database import get_active_configs_for_alerts, get_setting, set_setting
    from bot.keyboards import single_to_sub_nudge_kb

    await asyncio.sleep(120)
    while True:
        try:
            enabled = await get_setting("single_to_sub_nudge_enabled", "0") == "1"
            multi = await get_setting("multi_sub_enabled", "0") == "1"
            if enabled and multi:
                interval_days = max(1, int(await get_setting("single_to_sub_nudge_days", "3") or 3))
                last = float(await get_setting("single_to_sub_nudge_last", "0") or 0)
                now = _t.time()
                if now - last >= interval_days * 86400 - 60:
                    text = await get_setting(
                        "single_to_sub_nudge_text",
                        "♻️ سرویس تکی شما قابل ارتقا به «لینک ساب چندسروره» است.\n"
                        "با تبدیل، اگر یک سرور قطع شد، سرورهای دیگر همچنان وصل می‌مانند و مدیریت ساده‌تر می‌شود.\n"
                        "حجم و زمان باقی‌مانده‌تان دقیقاً منتقل می‌شود.",
                    )
                    sent = 0
                    seen_users = set()
                    for cfg in await get_active_configs_for_alerts(1000):
                        try:
                            await bot.send_message(
                                cfg["telegram_id"], text,
                                reply_markup=single_to_sub_nudge_kb(int(cfg["id"])),
                                parse_mode=None,
                            )
                            sent += 1
                            seen_users.add(cfg["telegram_id"])
                            await asyncio.sleep(0.1)
                        except Exception:
                            pass
                    await set_setting("single_to_sub_nudge_last", str(now))
                    if sent:
                        logger.info(f"single→sub nudge sent={sent} users={len(seen_users)}")
        except Exception as e:
            logger.exception("single→sub nudge worker failed: %s", e)
        await asyncio.sleep(3600)


async def _owner_targets() -> list[int]:
    """Top-level admins who should receive sensitive panel backups."""
    from core.config import ADMIN_IDS
    from core.database import get_setting

    ids = list(ADMIN_IDS)
    try:
        owner_id = int(await get_setting("owner_admin_id", "0") or 0)
        if owner_id:
            ids.append(owner_id)
    except Exception:
        pass
    return list(dict.fromkeys(i for i in ids if i))


async def _send_servers_backup(bot, reason: str = "scheduled") -> bool:
    from aiogram.types import BufferedInputFile
    from core.backup import build_servers_backup
    from core.jalali import jalali_display
    from core.database import get_servers

    targets = await _owner_targets()
    if not targets:
        logger.warning("server backup: no owner targets configured")
        return False
    try:
        fname, data = await build_servers_backup()
    except Exception as e:
        logger.exception("server backup build failed: %s", e)
        for aid in targets:
            try:
                await bot.send_message(aid, f"❌ تهیهٔ بکاپ سرورها ناموفق بود:\n{str(e)[:300]}", parse_mode=None)
            except Exception:
                pass
        return False

    servers = await get_servers(active_only=False)
    size_mb = len(data) / (1024 * 1024)
    caption = (
        f"🗄 بکاپ پنل‌ها — {jalali_display()}\n"
        f"تعداد سرور: {len(servers)} | حجم: {size_mb:.2f} MB\n"
        f"شامل دیتابیس هر پنل (در صورت دسترسی) + خروجی کامل اینباندها + دیتابیس ربات."
    )
    sent = 0
    for aid in targets:
        try:
            await bot.send_document(aid, BufferedInputFile(data, filename=fname), caption=caption, parse_mode=None)
            sent += 1
            await asyncio.sleep(0.2)
        except Exception as e:
            logger.warning("server backup send to %s failed: %s", aid, e)
    logger.info("server backup (%s) sent to %s owners | %.2f MB", reason, sent, size_mb)
    return sent > 0


async def _server_backup_worker(bot):
    from core.database import get_setting

    await asyncio.sleep(90)
    while True:
        try:
            if await get_setting("server_backup_enabled", "1") == "1":
                try:
                    interval_h = float(await get_setting("server_backup_interval_hours", "6") or 6)
                except (TypeError, ValueError):
                    interval_h = 6.0
                interval_s = max(3600, int(interval_h * 3600))
                last = 0.0
                try:
                    last = float(await get_setting("server_backup_last_ts", "0") or 0)
                except (TypeError, ValueError):
                    last = 0.0
                now = time.time()
                if now - last >= interval_s - 60:
                    from core.database import set_setting
                    ok = await _send_servers_backup(bot, reason="scheduled")
                    if ok:
                        await set_setting("server_backup_last_ts", str(now))
        except Exception as e:
            logger.exception("server backup worker failed: %s", e)
        await asyncio.sleep(900)  # re-check every 15 minutes


async def _subscription_lifecycle_worker(bot):
    """Notify users about ended subscriptions and delete them after the grace period."""
    from core.database import get_setting
    from core.multi_subscription import run_subscription_lifecycle, run_subscription_expiry_warnings
    from core.rewards import run_referral_reminders
    from core.campaigns import run_trial_to_paid, run_winback

    await asyncio.sleep(60)
    while True:
        try:
            # Warn BEFORE the service ends (with a quick-renew button), then
            # handle the ones that already ended.
            await run_subscription_expiry_warnings(bot)
            await run_subscription_lifecycle(bot)
            # Smart 24h referral nudge (ask inviters to send a discount code).
            await run_referral_reminders(bot)
            # Sales campaigns: convert lapsed trials, win back churned users.
            await run_trial_to_paid(bot)
            await run_winback(bot)
        except Exception as e:
            logger.exception("subscription lifecycle worker failed: %s", e)
        try:
            interval = int(await get_setting("sub_lifecycle_check_interval", "1800") or 1800)
        except Exception:
            interval = 1800
        await asyncio.sleep(max(300, interval))



async def run_bot():
    from aiogram import Bot, Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    from core.config import BOT_TOKEN, ADMIN_IDS
    from core.database import init_db
    from bot.handlers import common, admin, user
    from bot import nav
    from bot.middlewares import ChannelRequiredMiddleware

    if not BOT_TOKEN or len(BOT_TOKEN) < 20:
        logger.error("❌ BOT_TOKEN در فایل .env تنظیم نشده!")
        return

    await init_db()
    logger.info("✅ دیتابیس آماده")
    await _repair_missing_expiries()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    dp = Dispatcher(storage=MemoryStorage())

    # عضویت اجباری کانال: روی همه پیام‌ها/کال‌بک‌ها قبل از هندلرها چک شود
    dp.message.middleware(ChannelRequiredMiddleware())
    dp.callback_query.middleware(ChannelRequiredMiddleware())

    # ترتیب اهمیت دارد: common باید آخر باشه
    # nav اول ثبت می‌شود تا تنها هندلر «برگشت» یکپارچه باشد
    dp.include_router(nav.router)
    dp.include_router(admin.router)
    dp.include_router(user.router)
    dp.include_router(common.router)

    bot_info = await bot.get_me()
    logger.info(f"🤖 ربات @{bot_info.username} آماده | ادمین‌ها: {ADMIN_IDS}")

    await _notify_update(bot)
    asyncio.create_task(_config_alert_worker(bot))
    asyncio.create_task(_daily_report_worker(bot))
    asyncio.create_task(_multi_subscription_worker())
    asyncio.create_task(_subscription_lifecycle_worker(bot))
    asyncio.create_task(_single_to_sub_nudge_worker(bot))
    asyncio.create_task(_server_backup_worker(bot))
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


async def run_web():
    import uvicorn
    from core.config import WEB_HOST, WEB_PORT, WEB_SECRET_PATH
    from core.database import init_db
    from web.app import app

    await init_db()

    config = uvicorn.Config(
        app,
        host=WEB_HOST,
        port=WEB_PORT,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    logger.info(
        f"🌐 پنل وب: http://SERVER_IP:{WEB_PORT}/panel "
        f"| مسیر مستقیم: http://SERVER_IP:{WEB_PORT}/{WEB_SECRET_PATH}/ "
        f"| bind={WEB_HOST}:{WEB_PORT}"
    )
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
