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
    b.row(KeyboardButton(text="👥 کاربران"), KeyboardButton(text="🔍 جستجوی کاربر"))
    b.row(KeyboardButton(text="📣 پیام همگانی"), KeyboardButton(text="✉️ پیام خصوصی"))
    b.row(KeyboardButton(text="🌐 پنل مدیریت"))
    b.row(KeyboardButton(text="🔄 شروع مجدد"))
    return b.as_markup(resize_keyboard=True)


def user_menu(include_wholesale: bool = True) -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    # Free trial is the top of the funnel — make it the first, full-width button
    # (biggest tap target) so newcomers try before they weigh buying.
    b.row(KeyboardButton(text="🧪 تست رایگان"))
    b.row(KeyboardButton(text="📡 وضعیت سرویس"), KeyboardButton(text="🛒 خرید سرویس"))
    b.row(KeyboardButton(text="🔄 انتقال سرور"), KeyboardButton(text="📋 سفارش‌های من"))
    b.row(KeyboardButton(text="🔄 شروع مجدد"))
    b.row(KeyboardButton(text="💳 کیف پول"), KeyboardButton(text="🎁 دعوت دوستان"))
    b.row(KeyboardButton(text="📞 پشتیبانی"), KeyboardButton(text="🕊️ پیام ناشناس"))
    # Always show the representative entry: reps get their panel, everyone else
    # gets the "apply to become a representative" flow. (Previously hidden from
    # non-reps, so people who saw the ad couldn't find the button.)
    b.row(KeyboardButton(text="🏢 پنل نمایندگی"))
    b.row(KeyboardButton(text="🔗 افزودن سرویس قبلی"))
    return b.as_markup(resize_keyboard=True)


def parse_custom_buttons(text: str) -> InlineKeyboardMarkup | None:
    """Parse admin-typed buttons into an inline keyboard.

    Format (one row per line, buttons in a row separated by |):
        عنوان دکمه - https://example.com
        کانال - https://t.me/ch | سایت - https://site.com
    Separator between label and URL can be ' - ' or ' | ' inside a button via '-'.
    Returns None if nothing valid was parsed.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    b = InlineKeyboardBuilder()
    rows: list[int] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        count = 0
        for cell in line.split("|"):
            cell = cell.strip()
            if not cell:
                continue
            # Prefer the explicit " - " separator so labels may contain dashes.
            if " - " in cell:
                label, _, url = cell.partition(" - ")
            elif "-" in cell:
                label, _, url = cell.partition("-")
            else:
                continue
            label = label.strip()
            url = url.strip()
            if not label or not url:
                continue
            # Telegram requires a scheme; add tg/http handling
            low = url.lower()
            if low.startswith(("http://", "https://", "tg://")):
                pass
            elif low.startswith("@") or "t.me/" in low:
                url = "https://t.me/" + url.lstrip("@").split("t.me/")[-1]
            else:
                url = "https://" + url
            try:
                b.button(text=label[:60], url=url)
                count += 1
            except Exception:
                continue
        if count:
            rows.append(count)
    if not rows:
        return None
    b.adjust(*rows)
    return b.as_markup()


def broadcast_target_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="👥 همه کاربران", callback_data="bc_target:all", style="primary")
    _button(b, text="🏷️ فقط کاربران عمده", callback_data="bc_target:wholesale", style="primary")
    b.adjust(1)
    return b.as_markup()


def wholesale_request_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="📝 درخواست نمایندگی", callback_data="wh_terms", style="success")
    b.adjust(1)
    return b.as_markup()


def rep_buy_choice_kb() -> InlineKeyboardMarkup:
    """Representatives can create either a single service or a bulk batch."""
    b = InlineKeyboardBuilder()
    _button(b, text="🛍 خرید تکی (یک سرویس)", callback_data="rep:buy_single", style="primary")
    _button(b, text="📦 خرید گروهی (چند سرویس)", callback_data="rep:buy_bulk", style="success")
    _button(b, text="⬅️ بازگشت", callback_data="rep:home")
    b.adjust(1)
    return b.as_markup()


def wholesale_terms_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="✅ قوانین را می‌پذیرم و درخواست می‌دهم", callback_data="wh_req", style="success")
    _button(b, text="❌ انصراف", callback_data="wh_cancel", style="danger")
    b.adjust(1)
    return b.as_markup()


def wholesale_request_admin_kb(user_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="✅ تایید نمایندگی", callback_data=f"wh_appr:{user_id}", style="success")
    _button(b, text="❌ رد درخواست", callback_data=f"wh_rej:{user_id}", style="danger")
    b.adjust(1)
    return b.as_markup()


def representative_panel_kb() -> InlineKeyboardMarkup:
    """Main inline menu of the representative (reseller) panel."""
    b = InlineKeyboardBuilder()
    _button(b, text="🏷️ برند من", callback_data="rep:brand", style="primary")
    _button(b, text="🛒 ساخت سرویس", callback_data="rep:buy", style="success")
    _button(b, text="👥 مشتریان من", callback_data="rep:customers", style="primary")
    _button(b, text="📈 گزارش مالی", callback_data="rep:report")
    _button(b, text="💳 کیف پول من", callback_data="rep:wallet")
    _button(b, text="💰 قیمت‌های من", callback_data="rep:pricing")
    _button(b, text="ℹ️ راهنمای نماینده", callback_data="rep:help")
    b.adjust(2, 2, 2, 1)
    return b.as_markup()


def rep_brand_kb(has_brand: bool, hidden: bool) -> InlineKeyboardMarkup:
    """Brand management for a representative: set name + show/hide brand line."""
    b = InlineKeyboardBuilder()
    _button(b, text=("✏️ تغییر نام برند" if has_brand else "➕ انتخاب نام برند"),
            callback_data="rep:brand_set", style="primary")
    if has_brand:
        _button(b, text="🗑 حذف برند من", callback_data="rep:brand_clear", style="danger")
    _button(b, text="🖼 لوگوی من", callback_data="rep:logo", style="primary")
    _button(b, text=("👁 نمایش برند در لینک" if hidden else "🙈 مخفی‌کردن برند در لینک"),
            callback_data="rep:brand_toggle")
    _button(b, text="⬅️ بازگشت به پنل نمایندگی", callback_data="rep:home")
    b.adjust(1)
    return b.as_markup()


def rep_back_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="⬅️ بازگشت به پنل نمایندگی", callback_data="rep:home")
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


def _service_days_label(expire_ms: int) -> str:
    expire_ms = int(expire_ms or 0)
    if expire_ms <= 0:
        return "نامحدود"
    diff = expire_ms - int(time.time() * 1000)
    if diff <= 0:
        return "منقضی"
    days = max(1, int((diff + 86_399_999) // 86_400_000))
    return f"{days}روز"


def _service_button_text(kind: str, item: Dict) -> tuple[str, str]:
    now_ms = int(time.time() * 1000)
    is_active = bool(int(item.get("is_active") or 0))
    expire_ms = int(item.get("expire_timestamp") or 0)
    expired = expire_ms > 0 and expire_ms <= now_ms
    state_icon = "🟢" if is_active and not expired else "🔴"
    kind_icon = "🧬" if kind == "sub" else "🔑"
    name = str((item.get("name") if kind == "sub" else "") or item.get("email") or item.get("id") or "-")
    if len(name) > 30:
        name = name[:27] + "..."
    try:
        gb_label = f"{float(item.get('traffic_gb') or 0):g}GB"
    except Exception:
        gb_label = "GB?"
    text = f"{state_icon} {kind_icon} {name} | {gb_label} | {_service_days_label(expire_ms)}"
    callback = f"sub_show:{item['id']}" if kind == "sub" else f"cfg:{item['id']}"
    return text, callback


def user_services_kb(configs: List[Dict], profiles: List[Dict], page: int = 0, per_page: int = 8) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    items = [("sub", p) for p in profiles] + [("cfg", c) for c in configs]
    items.sort(key=lambda pair: (int(pair[1].get("is_active") or 0), int(pair[1].get("id") or 0)), reverse=True)

    total = len(items)
    page = max(0, int(page or 0))
    max_page = max(0, (total - 1) // max(1, per_page))
    page = min(page, max_page)
    for kind, item in items[page * per_page: page * per_page + per_page]:
        text, callback = _service_button_text(kind, item)
        _button(b, text=text, callback_data=callback, style="primary")
    b.adjust(1)

    nav = []
    if page > 0:
        nav.append(_inline_button(text="◀️ قبلی", callback_data=f"svc_pg:{page-1}", style="primary"))
    if page < max_page:
        nav.append(_inline_button(text="بعدی ▶️", callback_data=f"svc_pg:{page+1}", style="primary"))
    if nav:
        b.row(*nav)
    return b.as_markup()


def config_detail_kb(cid: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="🔗 دریافت لینک اتصال", callback_data=f"cfg_link:{cid}", style="primary")
    _button(b, text="♻️ تمدید سرویس", callback_data=f"cfg_renew:{cid}", style="success")
    _button(b, text="🧬 تبدیل به لینک ساب", callback_data=f"cfg_to_sub:{cid}", style="success")
    _button(b, text="🔄 انتقال به سرور دیگر", callback_data=f"mig_start:{cid}", style="primary")
    _button(b, text="🔄 بروزرسانی سرویس", callback_data=f"cfg_refresh:{cid}", style="primary")
    _button(b, text="📡 لینک سابسکریپشن", callback_data=f"cfg_sub:{cid}", style="primary")
    _button(b, text="🧾 QR Code", callback_data=f"cfg_qr:{cid}", style="primary")
    _button(b, text="🗑️ حذف سرویس", callback_data=f"cfg_del:{cid}", style="danger")
    _button(b, text="🔙 بازگشت", callback_data="back_configs", style="primary")
    b.adjust(1)
    return b.as_markup()


def config_to_sub_confirm_kb(cid: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="✅ بله، تبدیل شود", callback_data=f"cfg_to_sub_do:{cid}", style="success")
    _button(b, text="❌ منصرف شدم", callback_data=f"cfg:{cid}", style="primary")
    b.adjust(1)
    return b.as_markup()


def config_delete_confirm_kb(cid: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="✅ بله، حذف شود", callback_data=f"cfg_del_do:{cid}", style="danger")
    _button(b, text="❌ منصرف شدم", callback_data=f"cfg:{cid}", style="primary")
    b.adjust(1)
    return b.as_markup()


def _renew_pkg_label(pkg: Dict) -> str:
    gb = float(pkg.get("traffic_gb") or 0)
    days = int(pkg.get("duration_days") or 0)
    gb_txt = "نامحدود" if gb <= 0 else f"{gb:g}GB"
    days_txt = "نامحدود" if days <= 0 else f"{days} روز"
    price = int(pkg.get("display_price", pkg.get("price") or 0) or 0)
    return f"{pkg.get('name') or 'پکیج'} — {gb_txt}/{days_txt} · {price:,} ت"


def renew_packages_kb(target_type: str, target_id: int, packages: List[Dict], back_cb: str) -> InlineKeyboardMarkup:
    """Renewal is plan-based: the user picks one of our active packages."""
    b = InlineKeyboardBuilder()
    for pkg in packages:
        _button(
            b,
            text=_renew_pkg_label(pkg),
            callback_data=f"rnwpkg:{target_type}:{target_id}:{pkg['id']}",
            style="primary",
        )
    _button(b, text="🔙 بازگشت", callback_data=back_cb, style="primary")
    b.adjust(1)
    return b.as_markup()


def _node_remark(node: Dict, index: int) -> str:
    return str(
        node.get("node_label")
        or node.get("server_name")
        or f"سرور {index}"
    ).strip()[:48]


def subscription_detail_kb(profile_id: int, sub_url: str = "", nodes: List[Dict] | None = None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    rows = []
    copy_btn = _copy_text_button("📋 کپی لینک ساب", sub_url, style="primary")
    if copy_btn:
        b.row(copy_btn)
        rows.append(1)

    # Per-node connection links shown as buttons — EVERY active server gets a
    # button. Telegram caps copy_text at 256 chars, so for shorter links we use
    # a one-tap copy button; for longer links (e.g. reality) we fall back to a
    # callback that sends the link as a copyable message.
    idx = 0
    for node in (nodes or []):
        if not int(node.get("is_active") or 0):
            continue
        link = (node.get("link") or "").strip()
        if not link:
            continue
        idx += 1
        label = f"📍 {_node_remark(node, idx)}"
        btn = None
        if len(link) <= 256:
            btn = _copy_text_button(label, link, style="success")
        if btn is None:
            btn = _inline_button(f"{label} — نمایش لینک", callback_data=f"subnode:{int(node.get('id') or 0)}", style="success")
        b.row(btn)

    _button(b, text="✏️ تغییر نام سرویس", callback_data=f"sub_rename:{profile_id}", style="primary")
    _button(b, text="♻️ تمدید ساب", callback_data=f"sub_renew:{profile_id}", style="success")
    _button(b, text="🗑️ حذف ساب", callback_data=f"sub_del:{profile_id}", style="danger")
    _button(b, text="🔙 برگشت به سرویس‌ها", callback_data="back_configs", style="primary")
    b.adjust(1)
    return b.as_markup()


def single_to_sub_nudge_kb(config_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="🧬 همین حالا تبدیل به لینک ساب", callback_data=f"cfg_to_sub:{config_id}", style="success")
    b.adjust(1)
    return b.as_markup()


def subscription_delete_confirm_kb(profile_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="✅ بله، حذف شود", callback_data=f"sub_del_do:{profile_id}", style="danger")
    _button(b, text="❌ منصرف شدم", callback_data=f"sub_show:{profile_id}", style="primary")
    b.adjust(1)
    return b.as_markup()


def servers_kb(servers: List[Dict], cb_prefix: str, extra_data: str = "", with_back: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for s in servers:
        cb = f"{cb_prefix}:{s['id']}" + (f":{extra_data}" if extra_data else "")
        _button(b, text=f"🖥️ {s['name']}", callback_data=cb, style="primary")
    if with_back:
        _button(b, text="⬅️ برگشت", callback_data="flow_back", style="primary")
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


def custom_name_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="✅ ادامه با نام پیش‌فرض", callback_data="buy_name_default", style="success")
    _button(b, text="⬅️ برگشت", callback_data="flow_back", style="primary")
    _button(b, text="❌ کنسل", callback_data="cancel", style="danger")
    b.adjust(1)
    return b.as_markup()


def discount_skip_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="بدون کد تخفیف ➡️", callback_data="buy_disc_skip", style="primary")
    _button(b, text="❌ کنسل", callback_data="cancel", style="danger")
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


def adm_config_detail_kb(cid: int, active: bool, can_convert: bool = True) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="🔴 غیرفعال" if active else "🟢 فعال", callback_data=f"toggle_cfg:{cid}", style="danger" if active else "success")
    _button(b, text="♻️ تمدید سریع", callback_data=f"adm_cfg_renew:{cid}", style="success")
    _button(b, text="📊 تغییر حجم", callback_data=f"edit_gb:{cid}", style="primary")
    _button(b, text="📅 تمدید تاریخ", callback_data=f"edit_exp:{cid}", style="success")
    _button(b, text="🔗 دریافت لینک اتصال", callback_data=f"adm_cfg_link:{cid}", style="primary")
    if can_convert:
        _button(b, text="🧬 تبدیل به ساب و ارسال به کاربر", callback_data=f"adm_cfg2sub:{cid}", style="success")
    _button(b, text="✉️ پیام به مالک", callback_data=f"adm_cfg_msg:{cid}", style="primary")
    _button(b, text="🗑️ حذف", callback_data=f"del_cfg:{cid}", style="danger")
    _button(b, text="🔙 بازگشت", callback_data="adm_cfg_list", style="primary")
    b.adjust(2, 2, 1, 1, 1, 2)
    return b.as_markup()


def adm_user_card_kb(uid: int, is_blocked: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="📡 سرویس‌های کاربر", callback_data=f"adm_usr_svcs:{uid}", style="primary")
    _button(b, text="💰 تنظیم موجودی", callback_data=f"adm_usr_bal:{uid}", style="success")
    _button(b, text="✉️ پیام به کاربر", callback_data=f"adm_usr_msg:{uid}", style="primary")
    _button(b, text="🔓 آنبلاک" if is_blocked else "🔒 بلاک", callback_data=f"toggle_block:{uid}", style="success" if is_blocked else "danger")
    _button(b, text="🔙 بازگشت", callback_data="usr_back", style="primary")
    b.adjust(1, 2, 1, 1)
    return b.as_markup()


def adm_user_services_kb(uid: int, configs: List[Dict], profiles: List[Dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in profiles:
        icon = "🟢" if int(p.get("is_active") or 0) else "🔴"
        name = p.get("name") or p.get("email") or f"ساب #{p.get('id')}"
        _button(b, text=f"📡 {icon} {str(name)[:34]}", callback_data=f"adm_sub:{p['id']}", style="primary")
    for c in configs:
        icon = "🟢" if int(c.get("is_active") or 0) else "🔴"
        _button(b, text=f"🔑 {icon} {str(c.get('email') or c.get('id'))[:34]}", callback_data=f"adm_cfg:{c['id']}", style="primary")
    if not configs and not profiles:
        _button(b, text="— سرویسی ندارد —", callback_data=f"usr:{uid}", style="primary")
    _button(b, text="🔙 بازگشت به کارت کاربر", callback_data=f"usr:{uid}", style="primary")
    b.adjust(1)
    return b.as_markup()


def adm_sub_panel_kb(pid: int, is_active: bool, owner_uid: int = 0) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="🔴 غیرفعال کردن" if is_active else "🟢 فعال کردن", callback_data=f"adm_sub_toggle:{pid}", style="danger" if is_active else "success")
    _button(b, text="♻️ تمدید (همان پلن)", callback_data=f"adm_sub_renew:{pid}", style="success")
    _button(b, text="✏️ ویرایش (حجم/مدت)", callback_data=f"adm_sub_edit:{pid}", style="primary")
    _button(b, text="📤 ارسال لینک به کاربر", callback_data=f"adm_sub_send:{pid}", style="primary")
    _button(b, text="✉️ پیام به مالک", callback_data=f"adm_sub_msg:{pid}", style="primary")
    _button(b, text="🗑️ حذف کامل ساب", callback_data=f"adm_sub_del:{pid}", style="danger")
    if owner_uid:
        _button(b, text="🔙 سرویس‌های کاربر", callback_data=f"adm_usr_svcs:{owner_uid}", style="primary")
    b.adjust(2, 1, 2, 1, 1)
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
        # Show the price THIS user actually pays (rep/custom price), not the
        # package default. Callers enrich pkgs with `display_price`.
        pnum = int(p.get("display_price", p["price"]) or 0)
        price = f"{pnum:,}".replace(",", "،")
        tier = "🥉" if pnum < 100000 else "🥈" if pnum < 200000 else "🥇"
        _button(
            b,
            text=f"{tier} {p['name']} | {gb}GB | {p['duration_days']} روز | {price} تومان",
            callback_data=f"buy:{p['id']}",
            style="primary",
        )
    b.adjust(1)
    return b.as_markup()
