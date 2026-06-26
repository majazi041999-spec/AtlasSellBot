from typing import Dict


UI_DEFAULTS: Dict[str, str] = {
    "ui.brand_name": "Atlas Account",
    "ui.panel_subtitle": "پنل مدیریت",
    "ui.topbar_note": "Atlas Account Admin",
    "ui.logo_emoji": "🌐",
}


BOT_TEXT_DEFAULTS: Dict[str, str] = {
    "text.welcome_message": "به Atlas Account خوش آمدید! 🌐\nبهترین سرویس VPN با سرعت بالا.",
    "text.maintenance_message": "🔧 ربات در حال تعمیر و به‌روزرسانی است.\nلطفاً کمی صبر کنید.",
    "text.blocked_message": "❌ حساب شما مسدود شده.\nبرای رفع مسدودی با پشتیبانی تماس بگیرید.",
    "text.no_active_service": "📭 *سرویس فعالی ندارید.*\n\nبرای خرید سرویس روی *🛒 خرید سرویس* بزنید.",
    "text.support_header": "📞 *پشتیبانی {brand}*",
    "text.support_body": "⏰ ساعات پاسخگویی: ۹ صبح تا ۱۱ شب\n\n_در صورت داشتن مشکل، شناسه کانفیگ (ایمیل) خود را ارسال کنید._",
    "text.referral_intro": "🎁 *سیستم دعوت دوستان*\n━━━━━━━━━━━━━━\nبه ازای هر دوستی که دعوت کنی و *اولین خریدش* را انجام دهد،\nشما **{bonus_gb} GB هدیه** دریافت می‌کنید! 🌟",
    "text.panel_url_help": "🌐 *پنل مدیریت وب:*\n\n`http://YOUR_SERVER_IP:{port}/{secret}/`\n\nآدرس IP سرورت را جایگزین `YOUR_SERVER_IP` کن.",
}


SETTINGS_DEFAULTS: Dict[str, str] = {
    "cfg_name_prefix": "u",
    "cfg_name_postfix": "",
    "cfg_name_rand_len": "6",
    "force_channel": "0",
    "channel_username": "",
    "auto_least_loaded_server": "0",
    "legacy_sync_enabled": "1",
    "max_daily_migrations": "5",
    "renewal_min_traffic_gb": "1",
    "multi_sub_enabled": "1",
    "multi_sub_node_count": "4",
    "multi_sub_min_nodes": "2",
    "public_base_url": "",
    "sub_auto_sync_enabled": "1",
    "sub_auto_sync_interval_hours": "1",
    "sub_info_enabled": "1",
    "sub_info_render_as_links": "1",
    "sub_info_sync_on_render": "1",
    "sub_force_local_links_on_render": "1",
    "sub_info_template": "📊 حجم کل: {traffic_gb}GB | مصرف: {used} | باقی: {remaining}\n📅 باقی‌مانده: {days_left} روز | سپری‌شده: {days_elapsed} روز",
    "sub_brand_template": "📣 {brand}",
    "sub_grace_days": "3",
    "sub_start_on_first_use": "1",
    "single_to_sub_nudge_enabled": "0",
    "server_backup_enabled": "1",
    "server_backup_interval_hours": "6",
    "sub_connection_guide": (
        "📚 راهنمای اتصال:\n"
        "۱) بهترین روش: «کپی لینک ساب» را بزنید و در برنامه (v2rayNG / NekoBox / Streisand / V2Box) از بخش افزودن از کلیپ‌بورد، آن را اضافه کنید و آپدیت بزنید.\n"
        "۲) اگر لینک ساب باز نشد: روی دکمهٔ هر سرور (📍) بزنید تا لینک همان سرور کپی شود و مستقیم در برنامه وارد کنید.\n"
        "۳) همیشه چند سرور دارید؛ اگر یکی وصل نشد، سرور دیگر را امتحان کنید."
    ),
    "sub_expiry_notice_template": (
        "⛔️ اشتراک سرویس شما به پایان رسید.\n\n"
        "سرویس: {service}\n"
        "حجم مصرف‌شده: {used} از {total}\n"
        "تاریخ انقضا: {expire_date}\n\n"
        "⏳ تا {grace_days} روز دیگر فرصت دارید سرویس را تمدید کنید.\n"
        "در غیر این صورت لینک اشتراک شما به‌طور کامل حذف می‌شود و برای استفاده مجدد باید سرویس جدید خریداری کنید."
    ),
    "sub_deleted_notice_template": (
        "🗑 لینک اشتراک سرویس شما حذف شد.\n\n"
        "سرویس: {service}\n"
        "به دلیل عدم تمدید پس از {grace_days} روز، تمام لینک‌های این اشتراک حذف شدند.\n"
        "برای استفاده مجدد لطفاً یک سرویس جدید خریداری کنید. 🌐"
    ),
    "sub_expired_link_template": "⛔️ {reason} — برای ادامه از ربات «تمدید» کنید 🤖",
    "test_account_enabled": "1",
    "test_account_traffic_gb": "1",
    "test_account_duration_days": "1",
    "test_account_server_id": "0",
    "test_account_prefix": "test",
    "discount_enabled": "1",
    "referral_enabled": "1",
    "referral_per_referral_gb": "5",
    "referral_banner_url": "",
    "referral_banner_file_id": "",
    "referral_caption": (
        "🌐 اینترنت پرسرعت و بی‌قطعی با {brand}\n\n"
        "سلام 👋 خودم از {brand} استفاده می‌کنم و راضی‌ام، گفتم به تو هم بگم:\n\n"
        "⚡️ سرعت بالا برای اینستاگرام، یوتیوب، تلگرام و بازی\n"
        "🛡 چند سرور هم‌زمان؛ اگر یکی قطع شد، بقیه وصل‌اند\n"
        "📱 نصب آسان روی موبایل و کامپیوتر\n"
        "🎁 تست رایگان قبل از خرید\n"
        "☎️ پشتیبانی همیشگی و واقعی\n\n"
        "👇 همین حالا رایگان امتحان کن:\n{link}"
    ),
}


CUSTOM_STYLE_DEFAULT = ""
CUSTOM_SCRIPT_DEFAULT = ""

