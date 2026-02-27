from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from typing import List, Dict


def admin_menu(finance_only: bool = False) -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    if finance_only:
        b.row(KeyboardButton(text="💰 سفارش‌های در انتظار"))
        b.row(KeyboardButton(text="🔄 شروع مجدد"))
        return b.as_markup(resize_keyboard=True)

    b.row(KeyboardButton(text="📊 آمار کلی"), KeyboardButton(text="💰 سفارش‌های در انتظار"))
    b.row(KeyboardButton(text="🔑 مدیریت کانفیگ"), KeyboardButton(text="📦 پکیج‌ها"))
    b.row(KeyboardButton(text="👥 کاربران"), KeyboardButton(text="📣 پیام همگانی"))
    b.row(KeyboardButton(text="✉️ پیام خصوصی"), KeyboardButton(text="🌐 پنل مدیریت"))
    b.row(KeyboardButton(text="🔄 شروع مجدد"))
    return b.as_markup(resize_keyboard=True)


def user_menu(include_wholesale: bool = True) -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="📡 وضعیت سرویس"), KeyboardButton(text="🛒 خرید سرویس"))
    b.row(KeyboardButton(text="🔄 انتقال سرور"), KeyboardButton(text="📋 سفارش‌های من"))
    b.row(KeyboardButton(text="🔄 شروع مجدد"))
    b.row(KeyboardButton(text="🎁 دعوت دوستان"), KeyboardButton(text="📞 پشتیبانی"))
    if include_wholesale:
        b.row(KeyboardButton(text="🏷️ خرید عمده"))
    b.row(KeyboardButton(text="🔗 سینک کانفیگ قبلی"))
    return b.as_markup(resize_keyboard=True)


def broadcast_target_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="👥 همه کاربران", callback_data="bc_target:all")
    b.button(text="🏷️ فقط کاربران عمده", callback_data="bc_target:wholesale")
    b.adjust(1)
    return b.as_markup()


def wholesale_request_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📝 ارسال درخواست همکاری عمده", callback_data="wh_req")
    b.adjust(1)
    return b.as_markup()


def wholesale_request_admin_kb(user_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ تایید همکاری عمده", callback_data=f"wh_appr:{user_id}")
    b.button(text="❌ رد درخواست", callback_data=f"wh_rej:{user_id}")
    b.adjust(1)
    return b.as_markup()


def packages_kb(pkgs: List[Dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in pkgs:
        gb = int(p['traffic_gb']) if p['traffic_gb'] == int(p['traffic_gb']) else p['traffic_gb']
        price = f"{p['price']:,}".replace(",", "،")
        b.button(
            text=f"{'🥉' if p['price'] < 100000 else '🥈' if p['price'] < 200000 else '🥇'} {p['name']}  |  {gb}GB  |  {p['duration_days']}روز  |  {price}T",
            callback_data=f"buy:{p['id']}"
        )
    b.adjust(1)
    return b.as_markup()


def configs_kb(configs: List[Dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for c in configs:
        b.button(text=f"🔑 {c['email']}", callback_data=f"cfg:{c['id']}")
    b.adjust(1)
    return b.as_markup()


def config_detail_kb(cid: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔗 دریافت لینک اتصال", callback_data=f"cfg_link:{cid}")
    b.button(text="🔄 انتقال به سرور دیگر", callback_data=f"mig_start:{cid}")
    b.button(text="🔄 بروزرسانی سرویس", callback_data=f"cfg_refresh:{cid}")
    b.button(text="📡 لینک سابسکریپشن", callback_data=f"cfg_sub:{cid}")
    b.button(text="🔙 بازگشت", callback_data="back_configs")
    b.adjust(1)
    return b.as_markup()


def servers_kb(servers: List[Dict], cb_prefix: str, extra_data: str = "") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for s in servers:
        cb = f"{cb_prefix}:{s['id']}" + (f":{extra_data}" if extra_data else "")
        b.button(text=f"🖥️ {s['name']}", callback_data=cb)
    b.button(text="❌ لغو", callback_data="cancel")
    b.adjust(1)
    return b.as_markup()


def payment_kb(order_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📸 ارسال فیش پرداخت", callback_data=f"receipt:{order_id}")
    b.button(text="❌ انصراف از خرید", callback_data=f"cancel_order:{order_id}")
    b.adjust(1)
    return b.as_markup()


def order_review_kb(order_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ تأیید و ارسال کانفیگ", callback_data=f"approve:{order_id}")
    b.button(text="❌ رد کردن", callback_data=f"reject:{order_id}")
    b.adjust(2)
    return b.as_markup()


def order_server_select_kb(servers: List[Dict], order_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for s in servers:
        b.button(text=f"🖥️ {s['name']}", callback_data=f"assign:{order_id}:{s['id']}")
    b.adjust(1)
    return b.as_markup()


def confirm_kb(yes_cb: str, no_cb: str = "cancel") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ بله", callback_data=yes_cb)
    b.button(text="❌ خیر", callback_data=no_cb)
    b.adjust(2)
    return b.as_markup()


def admin_configs_kb(configs: List[Dict], page: int = 0) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    chunk = configs[page * 10: page * 10 + 10]
    for c in chunk:
        icon = "🟢" if c['is_active'] else "🔴"
        b.button(text=f"{icon} {c['email']}", callback_data=f"adm_cfg:{c['id']}")
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_cfg_pg:{page-1}"))
    if (page + 1) * 10 < len(configs):
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_cfg_pg:{page+1}"))
    b.adjust(1)
    if nav:
        b.row(*nav)
    return b.as_markup()


def adm_config_detail_kb(cid: int, active: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔴 غیرفعال" if active else "🟢 فعال", callback_data=f"toggle_cfg:{cid}")
    b.button(text="📊 تغییر حجم", callback_data=f"edit_gb:{cid}")
    b.button(text="📅 تمدید تاریخ", callback_data=f"edit_exp:{cid}")
    b.button(text="🗑️ حذف", callback_data=f"del_cfg:{cid}")
    b.button(text="🔙 بازگشت", callback_data="adm_cfg_list")
    b.adjust(2, 2, 1)
    return b.as_markup()


def legacy_claim_admin_kb(claim_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ تایید اتصال", callback_data=f"lg_appr:{claim_id}")
    b.button(text="❌ رد درخواست", callback_data=f"lg_rej:{claim_id}")
    b.adjust(1)
    return b.as_markup()
