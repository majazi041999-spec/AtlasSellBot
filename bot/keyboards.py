from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from typing import List, Dict
import time

try:
    from aiogram.types import CopyTextButton
except Exception:
    CopyTextButton = None


def _button(builder: InlineKeyboardBuilder, text: str, style: str | None = None, **kwargs):
    if style:
        try:
            builder.button(text=text, style=style, **kwargs)
            return
        except Exception:
            pass
    builder.button(text=text, **kwargs)


def _inline_button(text: str, style: str | None = None, **kwargs) -> InlineKeyboardButton:
    if style:
        try:
            return InlineKeyboardButton(text=text, style=style, **kwargs)
        except Exception:
            pass
    return InlineKeyboardButton(text=text, **kwargs)


def _copy_text_button(text: str, value: str, style: str | None = None) -> InlineKeyboardButton | None:
    if not value or CopyTextButton is None:
        return None
    try:
        return _inline_button(text=text, copy_text=CopyTextButton(text=value), style=style)
    except Exception:
        return None


def admin_menu(finance_only: bool = False) -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    if finance_only:
        b.row(KeyboardButton(text="💰 سفارش‌های در انتظار"))
        b.row(KeyboardButton(text="🔄 شروع مجدد"))
        return b.as_markup(resize_keyboard=True)

    b.row(KeyboardButton(text="📊 آمار کلی"), KeyboardButton(text="📈 گزارش روزانه"))
    b.row(KeyboardButton(text="💰 سفارش‌های در انتظار"))
    b.row(KeyboardButton(text="🔑 مدیریت کانفیگ"), KeyboardButton(text="📦 پکیج‌ها"))
    b.row(KeyboardButton(text="👥 کاربران"), KeyboardButton(text="📣 پیام همگانی"))
    b.row(KeyboardButton(text="✉️ پیام خصوصی"), KeyboardButton(text="🌐 پنل مدیریت"))
    b.row(KeyboardButton(text="🔄 شروع مجدد"))
    return b.as_markup(resize_keyboard=True)


def user_menu(include_wholesale: bool = True) -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="📡 وضعیت سرویس"), KeyboardButton(text="🛒 خرید سرویس"))
    b.row(KeyboardButton(text="🧪 دریافت اکانت تست"))
    b.row(KeyboardButton(text="🔄 انتقال سرور"), KeyboardButton(text="📋 سفارش‌های من"))
    b.row(KeyboardButton(text="🔄 شروع مجدد"))
    b.row(KeyboardButton(text="💳 کیف پول"), KeyboardButton(text="🎁 دعوت دوستان"))
    b.row(KeyboardButton(text="📞 پشتیبانی"))
    if include_wholesale:
        b.row(KeyboardButton(text="🏷️ خرید عمده"))
    b.row(KeyboardButton(text="🔗 سینک کانفیگ قبلی"))
    return b.as_markup(resize_keyboard=True)


def broadcast_target_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="👥 همه کاربران", callback_data="bc_target:all", style="primary")
    _button(b, text="🏷️ فقط کاربران عمده", callback_data="bc_target:wholesale", style="primary")
    b.adjust(1)
    return b.as_markup()


def wholesale_request_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="📝 ارسال درخواست همکاری عمده", callback_data="wh_req", style="success")
    b.adjust(1)
    return b.as_markup()


def wholesale_request_admin_kb(user_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="✅ تایید همکاری عمده", callback_data=f"wh_appr:{user_id}", style="success")
    _button(b, text="❌ رد درخواست", callback_data=f"wh_rej:{user_id}", style="danger")
    b.adjust(1)
    return b.as_markup()


def packages_kb(pkgs: List[Dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in pkgs:
        gb = int(p['traffic_gb']) if p['traffic_gb'] == int(p['traffic_gb']) else p['traffic_gb']
        price = f"{p['price']:,}".replace(",", "،")
        tier = '🥉' if p['price'] < 100000 else '🥈' if p['price'] < 200000 else '🥇'
        _button(b, text=f"{tier} {p['name']} | {gb}GB | {p['duration_days']}روز | {price}تومان", callback_data=f"buy:{p['id']}", style="primary")
    b.adjust(1)
    return b.as_markup()


def configs_kb(configs: List[Dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    now_ms = int(time.time() * 1000)
    for c in configs:
        expire_ms = int(c.get("expire_timestamp") or 0)
        expired = expire_ms > 0 and expire_ms <= now_ms
        icon = "🔴" if not c.get("is_active", 1) or expired else "🟢"
        suffix = " | منقضی" if expired else ""
        _button(b, text=f"{icon} {c['email']}{suffix}", callback_data=f"cfg:{c['id']}", style="danger" if expired else "primary")
    b.adjust(1)
    return b.as_markup()


def config_detail_kb(cid: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="🔗 دریافت لینک اتصال", callback_data=f"cfg_link:{cid}", style="primary")
    _button(b, text="♻️ تمدید سرویس", callback_data=f"cfg_renew:{cid}", style="success")
    _button(b, text="🔄 انتقال به سرور دیگر", callback_data=f"mig_start:{cid}", style="primary")
    _button(b, text="🔄 بروزرسانی سرویس", callback_data=f"cfg_refresh:{cid}", style="primary")
    _button(b, text="📡 لینک سابسکریپشن", callback_data=f"cfg_sub:{cid}", style="primary")
    _button(b, text="🧾 QR Code", callback_data=f"cfg_qr:{cid}", style="primary")
    _button(b, text="🔙 بازگشت", callback_data="back_configs", style="primary")
    b.adjust(1)
    return b.as_markup()


def servers_kb(servers: List[Dict], cb_prefix: str, extra_data: str = "") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for s in servers:
        cb = f"{cb_prefix}:{s['id']}" + (f":{extra_data}" if extra_data else "")
        _button(b, text=f"🖥️ {s['name']}", callback_data=cb, style="primary")
    _button(b, text="❌ لغو", callback_data="cancel", style="danger")
    b.adjust(1)
    return b.as_markup()


def payment_kb(order_id: int, allow_wallet: bool = True) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="📸 ارسال فیش پرداخت", callback_data=f"receipt:{order_id}", style="primary")
    if allow_wallet:
        _button(b, text="💳 پرداخت از کیف پول", callback_data=f"pay_wallet:{order_id}", style="success")
    _button(b, text="❌ انصراف از خرید", callback_data=f"cancel_order:{order_id}", style="danger")
    b.adjust(1)
    return b.as_markup()


def order_review_kb(order_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="✅ تأیید و ارسال کانفیگ", callback_data=f"approve:{order_id}", style="success")
    _button(b, text="❌ رد کردن", callback_data=f"reject:{order_id}", style="danger")
    b.adjust(2)
    return b.as_markup()


def order_server_select_kb(servers: List[Dict], order_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for s in servers:
        _button(b, text=f"🖥️ {s['name']}", callback_data=f"assign:{order_id}:{s['id']}", style="primary")
    b.adjust(1)
    return b.as_markup()


def confirm_kb(yes_cb: str, no_cb: str = "cancel") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="✅ بله", callback_data=yes_cb, style="success")
    _button(b, text="❌ خیر", callback_data=no_cb, style="danger")
    b.adjust(2)
    return b.as_markup()


def admin_configs_kb(configs: List[Dict], page: int = 0) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    chunk = configs[page * 10: page * 10 + 10]
    for c in chunk:
        icon = "🟢" if c['is_active'] else "🔴"
        _button(b, text=f"{icon} {c['email']}", callback_data=f"adm_cfg:{c['id']}", style="success" if c['is_active'] else "danger")
    nav = []
    if page > 0:
        nav.append(_inline_button(text="◀️", callback_data=f"adm_cfg_pg:{page-1}", style="primary"))
    if (page + 1) * 10 < len(configs):
        nav.append(_inline_button(text="▶️", callback_data=f"adm_cfg_pg:{page+1}", style="primary"))
    b.adjust(1)
    if nav:
        b.row(*nav)
    return b.as_markup()


def adm_config_detail_kb(cid: int, active: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="🔴 غیرفعال" if active else "🟢 فعال", callback_data=f"toggle_cfg:{cid}", style="danger" if active else "success")
    _button(b, text="📊 تغییر حجم", callback_data=f"edit_gb:{cid}", style="primary")
    _button(b, text="📅 تمدید تاریخ", callback_data=f"edit_exp:{cid}", style="success")
    _button(b, text="🗑️ حذف", callback_data=f"del_cfg:{cid}", style="danger")
    _button(b, text="🔙 بازگشت", callback_data="adm_cfg_list", style="primary")
    b.adjust(2, 2, 1)
    return b.as_markup()


def legacy_claim_admin_kb(claim_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="✅ تایید اتصال", callback_data=f"lg_appr:{claim_id}", style="success")
    _button(b, text="❌ رد درخواست", callback_data=f"lg_rej:{claim_id}", style="danger")
    b.adjust(1)
    return b.as_markup()


def wallet_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="➕ افزایش اعتبار", callback_data="wallet_topup", style="success")
    b.adjust(1)
    return b.as_markup()


def topup_review_kb(req_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="✅ تایید افزایش اعتبار", callback_data=f"tp_appr:{req_id}", style="success")
    _button(b, text="❌ رد درخواست", callback_data=f"tp_rej:{req_id}", style="danger")
    b.adjust(1)
    return b.as_markup()


def flow_cancel_kb(show_back: bool = True) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if show_back:
        _button(b, text="⬅️ برگشت", callback_data="flow_back", style="primary")
    _button(b, text="❌ کنسل", callback_data="cancel", style="danger")
    _button(b, text="🏠 شروع مجدد", callback_data="back_to_menu", style="primary")
    b.adjust(3 if show_back else 2)
    return b.as_markup()


def config_links_kb(link: str = "", sub: str = "") -> InlineKeyboardMarkup | None:
    rows = []
    link_btn = _copy_text_button("📋 کپی لینک اتصال", link, style="success")
    sub_btn = _copy_text_button("📋 کپی لینک سابسکریپشن", sub, style="primary")
    if link_btn:
        rows.append([link_btn])
    if sub_btn:
        rows.append([sub_btn])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def packages_kb(pkgs: List[Dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in pkgs:
        gb = int(p["traffic_gb"]) if p["traffic_gb"] == int(p["traffic_gb"]) else p["traffic_gb"]
        price = f"{int(p['price']):,}".replace(",", "،")
        tier = "🥉" if p["price"] < 100000 else "🥈" if p["price"] < 200000 else "🥇"
        _button(
            b,
            text=f"{tier} {p['name']} | {gb}GB | {p['duration_days']} روز | {price} تومان",
            callback_data=f"buy:{p['id']}",
            style="primary",
        )
    b.adjust(1)
    return b.as_markup()
