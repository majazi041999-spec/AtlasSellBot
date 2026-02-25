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
}


CUSTOM_STYLE_DEFAULT = ""
CUSTOM_SCRIPT_DEFAULT = ""

