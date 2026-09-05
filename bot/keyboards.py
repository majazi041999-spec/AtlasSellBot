from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from typing import List, Dict
import time

from core.sorting import fa_sort_key
from core.pricing import is_unlimited_package
from bot.rich_message import emoji as tg_emoji, esc as rich_esc, table as rich_table

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


# ── channel post composer ────────────────────────────────────────────────────
# Telegram really does colour inline buttons: InlineKeyboardButton.style takes
# 'success' (green), 'primary' (blue) or 'danger' (red), and omitting it leaves
# the client's own default. Older clients ignore the field, so a coloured button
# degrades to a normal one rather than failing to send — which is why _button()
# has always passed it optimistically.
POST_STYLES = (
    ("success", "🟢 سبز"),
    ("primary", "🔵 آبی"),
    ("danger", "🔴 قرمز"),
    ("", "⚪️ پیش‌فرض"),
)
_STYLE_LABEL = dict(POST_STYLES)


def post_style_label(style: str) -> str:
    return _STYLE_LABEL.get(style or "", "⚪️ پیش‌فرض")


def post_buttons_kb(specs: list) -> InlineKeyboardMarkup | None:
    """The keyboard as it will appear on the channel post.

    `specs` is [{"text","url","style","row"}]. Buttons sharing a row number sit
    side by side, which is how the admin typed them.
    """
    if not specs:
        return None
    rows: dict = {}
    for s in specs:
        rows.setdefault(int(s.get("row") or 0), []).append(
            _inline_button(text=s["text"], url=s["url"], style=s.get("style") or None))
    return InlineKeyboardMarkup(inline_keyboard=[rows[k] for k in sorted(rows)])


def post_color_pick_kb(index: int, total: int) -> InlineKeyboardMarkup:
    """Colour choice for one button, shown one button at a time."""
    b = InlineKeyboardBuilder()
    for style, label in POST_STYLES:
        # The choice is previewed in its own colour, so the admin sees the real
        # thing rather than reading the word "green".
        _button(b, text=label, callback_data=f"post_color:{index}:{style or 'none'}",
                style=style or None)
    b.adjust(2, 2)
    _button(b, text="❌ لغو", callback_data="post_cancel", style="danger")
    return b.as_markup()


def post_confirm_kb(target: str = "") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if target:
        _button(b, text=f"✅ ارسال به {target}", callback_data="post_send", style="success")
    _button(b, text="🎨 تغییر رنگ‌ها", callback_data="post_recolor", style="primary")
    _button(b, text="📍 تغییر مقصد", callback_data="post_retarget", style="primary")
    _button(b, text="❌ لغو", callback_data="post_cancel", style="danger")
    b.adjust(1)
    return b.as_markup()


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
    b.row(KeyboardButton(text="📮 پست کانال"))
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


def parse_button_specs(text: str) -> list:
    """Admin-typed buttons -> [{"text","url","row"}], before colours are chosen.

    Shares its grammar with parse_custom_buttons — one row per line, `|` to put
    two side by side, ` - ` between label and destination — but returns the raw
    specs so a colour can be attached to each before the keyboard is built.
    """
    raw = (text or "").strip()
    if not raw:
        return []
    out: list = []
    for row_index, line in enumerate(raw.splitlines()):
        line = line.strip()
        if not line:
            continue
        for cell in line.split("|"):
            cell = cell.strip()
            if not cell:
                continue
            if " - " in cell:
                label, _, url = cell.partition(" - ")
            elif "-" in cell:
                label, _, url = cell.partition("-")
            else:
                continue
            label, url = label.strip(), url.strip()
            if not label or not url:
                continue
            low = url.lower()
            if low.startswith(("http://", "https://", "tg://")):
                pass
            elif low.startswith("@"):
                url = "https://t.me/" + url.lstrip("@")
            elif "t.me/" in low:
                url = "https://" + url.split("//")[-1]
            else:
                url = "https://" + url
            out.append({"text": label[:64], "url": url, "row": row_index, "style": ""})
    return out


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
    _button(b, text="🔌 اتصال ربات (API)", callback_data="rep:api", style="primary")
    _button(b, text="ℹ️ راهنمای نماینده", callback_data="rep:help")
    b.adjust(2, 2, 2, 1, 1)
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


def rep_api_kb(keys: List[Dict], docs_url: str = "") -> InlineKeyboardMarkup:
    """API-key management for a representative, self-service.

    One revoke button per key, labelled by its visible prefix — the full key is
    never recoverable (only its hash is stored), so the prefix is the only way a
    rep can tell two keys apart.
    """
    b = InlineKeyboardBuilder()
    _button(b, text="🔑 ساخت کلید اصلی", callback_data="rep:api_new", style="success")
    # A test key is a separate button rather than an option on the same one:
    # the difference between spending money and not spending money should never
    # be a setting somebody can miss.
    if not any(int(k.get("is_sandbox") or 0) for k in keys):
        _button(b, text="🧪 ساخت کلید تستی (بدون هزینه)", callback_data="rep:api_new_test",
                style="primary")
    for k in keys:
        tag = "🧪 " if int(k.get("is_sandbox") or 0) else ""
        _button(b, text=f"🗑 لغو کلید {tag}{k.get('prefix') or k.get('id')}…",
                callback_data=f"rep:api_del:{int(k['id'])}", style="danger")
    if docs_url:
        b.button(text="📄 مستندات API", url=docs_url)
    _button(b, text="⬅️ بازگشت به پنل نمایندگی", callback_data="rep:home")
    b.adjust(1)
    return b.as_markup()


def rep_api_key_kb(key: str, docs_url: str = "") -> InlineKeyboardMarkup:
    """Shown once, with the plaintext key. The copy button matters here: a key
    is 53 characters and selecting it by hand on a phone is how it gets
    truncated and then reported as 'the API is broken'."""
    b = InlineKeyboardBuilder()
    copy_btn = _copy_text_button("📋 کپی کلید", key, style="primary")
    if copy_btn:
        b.row(copy_btn)
    if docs_url:
        b.row(_inline_button(text="📄 مستندات و نمونه کد", url=docs_url))
    b.row(_inline_button(text="⬅️ بازگشت", callback_data="rep:api"))
    return b.as_markup()


def rep_back_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="⬅️ بازگشت به پنل نمایندگی", callback_data="rep:home")
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


# ── service list: sort & filter ──────────────────────────────────────────────
# Codes are single letters / short words because they ride inside callback_data
# (`svc:{page}:{sort}:{filter}`), which Telegram caps at 64 bytes.
SERVICE_SORTS = [
    ("n", "🕒 جدیدترین"),
    ("o", "🕒 قدیمی‌ترین"),
    ("a", "🔤 نام (الف → ی)"),
    ("z", "🔤 نام (ی → الف)"),
    ("e", "⏳ نزدیک‌ترین انقضا"),
    ("x", "⏳ دورترین انقضا"),
    ("g", "💾 بیشترین حجم"),
]
SERVICE_FILTERS = [
    ("all", "📋 همه"),
    ("on", "🟢 فعال"),
    ("soon", "⏰ رو به انقضا"),
    ("off", "🔴 منقضی / غیرفعال"),
]
SERVICE_SORT_LABELS = dict(SERVICE_SORTS)
SERVICE_FILTER_LABELS = dict(SERVICE_FILTERS)
DEFAULT_SERVICE_SORT = "n"
DEFAULT_SERVICE_FILTER = "all"


def normalize_service_view(sort: str | None, filt: str | None) -> tuple[str, str]:
    """Clamp callback-supplied codes to known values."""
    sort = sort if sort in SERVICE_SORT_LABELS else DEFAULT_SERVICE_SORT
    filt = filt if filt in SERVICE_FILTER_LABELS else DEFAULT_SERVICE_FILTER
    return sort, filt


def _service_name_key(item: Dict) -> list:
    return fa_sort_key(item.get("name") or item.get("email") or "")


def sort_filter_services(items: List[tuple], sort: str, filt: str) -> List[tuple]:
    """items = [(kind, row)]. Returns a new filtered+sorted list."""
    now_ms = int(time.time() * 1000)
    INF = float("inf")

    def expire_ms(it):
        return int(it[1].get("expire_timestamp") or 0)

    def expired(it):
        exp = expire_ms(it)
        return exp > 0 and exp <= now_ms

    def alive(it):
        return bool(int(it[1].get("is_active") or 0)) and not expired(it)

    def days_left(it):
        exp = expire_ms(it)
        return (exp - now_ms) / 86_400_000 if exp > 0 else None

    if filt == "on":
        items = [it for it in items if alive(it)]
    elif filt == "off":
        items = [it for it in items if not alive(it)]
    elif filt == "soon":
        items = [it for it in items if alive(it)
                 and days_left(it) is not None and days_left(it) <= 3]

    # Newest/oldest use the row id — subscription_profiles and configs both
    # allocate ids in purchase order.
    keys = {
        "n": (lambda it: int(it[1].get("id") or 0), True),
        "o": (lambda it: int(it[1].get("id") or 0), False),
        "a": (lambda it: _service_name_key(it[1]), False),
        "z": (lambda it: _service_name_key(it[1]), True),
        "e": (lambda it: (days_left(it) if days_left(it) is not None else INF), False),
        "x": (lambda it: (days_left(it) if days_left(it) is not None else INF), True),
        "g": (lambda it: float(it[1].get("traffic_gb") or 0), True),
    }
    key, rev = keys.get(sort, keys[DEFAULT_SERVICE_SORT])
    items = sorted(items, key=lambda it: int(it[1].get("id") or 0), reverse=True)
    return sorted(items, key=key, reverse=rev)


def user_services_kb(configs: List[Dict], profiles: List[Dict], page: int = 0, per_page: int = 8,
                     sort: str = DEFAULT_SERVICE_SORT, filt: str = DEFAULT_SERVICE_FILTER) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    sort, filt = normalize_service_view(sort, filt)
    items = sort_filter_services(
        [("sub", p) for p in profiles] + [("cfg", c) for c in configs], sort, filt)

    total = len(items)
    page = max(0, int(page or 0))
    max_page = max(0, (total - 1) // max(1, per_page))
    page = min(page, max_page)
    for kind, item in items[page * per_page: page * per_page + per_page]:
        text, callback = _service_button_text(kind, item)
        _button(b, text=text, callback_data=callback, style="primary")
    b.adjust(1)

    if not total:
        _button(b, text="😕 با این فیلتر سرویسی نیست", callback_data=f"svc:0:{sort}:all", style="primary")
        b.adjust(1)

    b.row(
        _inline_button(text=f"🔃 {SERVICE_SORT_LABELS[sort]}", callback_data=f"svc_srt:{page}:{sort}:{filt}"),
        _inline_button(text=f"🔎 {SERVICE_FILTER_LABELS[filt]}", callback_data=f"svc_flt:{page}:{sort}:{filt}"),
    )

    nav = []
    if page > 0:
        nav.append(_inline_button(text="◀️ قبلی", callback_data=f"svc:{page-1}:{sort}:{filt}", style="primary"))
    if max_page > 0:
        nav.append(_inline_button(text=f"{page+1}/{max_page+1}", callback_data="svc_noop", style="primary"))
    if page < max_page:
        nav.append(_inline_button(text="بعدی ▶️", callback_data=f"svc:{page+1}:{sort}:{filt}", style="primary"))
    if nav:
        b.row(*nav)
    return b.as_markup()


def service_sort_kb(page: int, sort: str, filt: str) -> InlineKeyboardMarkup:
    """Sort picker. Choosing an option jumps back to page 0 of the list."""
    b = InlineKeyboardBuilder()
    for code, label in SERVICE_SORTS:
        mark = "✅ " if code == sort else ""
        _button(b, text=f"{mark}{label}", callback_data=f"svc:0:{code}:{filt}", style="primary")
    b.adjust(1)
    b.row(_inline_button(text="🔙 بازگشت به لیست", callback_data=f"svc:{page}:{sort}:{filt}", style="primary"))
    return b.as_markup()


def service_filter_kb(page: int, sort: str, filt: str, counts: Dict[str, int] | None = None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for code, label in SERVICE_FILTERS:
        mark = "✅ " if code == filt else ""
        n = (counts or {}).get(code)
        suffix = f" ({n})" if n is not None else ""
        _button(b, text=f"{mark}{label}{suffix}", callback_data=f"svc:0:{sort}:{code}", style="primary")
    b.adjust(1)
    b.row(_inline_button(text="🔙 بازگشت به لیست", callback_data=f"svc:{page}:{sort}:{filt}", style="primary"))
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
    # Reads like the buy button on purpose — same shape, same helpers, so an
    # unlimited plan can never print its fair-use threshold ("100GB") in one
    # screen and "نامحدود" in the other.
    return f"🔄 تمدید {_pkg_traffic(pkg)} · {_pkg_duration(pkg)} — {_fa_num(_pkg_price(pkg))} تومان"


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

    _button(b, text="📶 دستگاه‌های متصل الان", callback_data=f"sub_conns:{profile_id}", style="primary")
    _button(b, text="✏️ تغییر نام سرویس", callback_data=f"sub_rename:{profile_id}", style="primary")
    _button(b, text="♻️ تمدید ساب", callback_data=f"sub_renew:{profile_id}", style="success")
    _button(b, text="🔄 تغییر لینک اشتراک", callback_data=f"sub_relink:{profile_id}", style="primary")
    _button(b, text="🗑️ حذف ساب", callback_data=f"sub_del:{profile_id}", style="danger")
    _button(b, text="🔙 برگشت به سرویس‌ها", callback_data="back_configs", style="primary")
    b.adjust(1)
    return b.as_markup()


def subscription_delete_confirm_kb(profile_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="✅ بله، حذف شود", callback_data=f"sub_del_do:{profile_id}", style="danger")
    _button(b, text="❌ منصرف شدم", callback_data=f"sub_show:{profile_id}", style="primary")
    b.adjust(1)
    return b.as_markup()


def subscription_relink_confirm_kb(profile_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, text="✅ بله، لینک جدید بده", callback_data=f"sub_relink_do:{profile_id}", style="danger")
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
    _button(b, text="📶 اتصال‌های زنده", callback_data=f"adm_sub_conns:{pid}", style="primary")
    _button(b, text="🔐 سقف اتصال هم‌زمان", callback_data=f"adm_sub_iplimit:{pid}", style="primary")
    _button(b, text="📤 ارسال لینک به کاربر", callback_data=f"adm_sub_send:{pid}", style="primary")
    _button(b, text="✉️ پیام به مالک", callback_data=f"adm_sub_msg:{pid}", style="primary")
    _button(b, text="🗑️ حذف کامل ساب", callback_data=f"adm_sub_del:{pid}", style="danger")
    if owner_uid:
        _button(b, text="🔙 سرویس‌های کاربر", callback_data=f"adm_usr_svcs:{owner_uid}", style="primary")
    b.adjust(2, 1, 2, 2, 1, 1)
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


def _pkg_traffic(pkg: Dict) -> str:
    """An unlimited plan is stored with a non-zero traffic_gb as a FAIR-USE
    threshold (ours sits at 100), so the raw number must never be printed for
    one — the customer would read "unlimited ... 100GB" and open a ticket."""
    if is_unlimited_package(pkg):
        return "نامحدود"
    gb = float(pkg.get("traffic_gb") or 0)
    return f"{gb:g} گیگ"


def _pkg_duration(pkg: Dict) -> str:
    days = int(pkg.get("duration_days") or 0)
    return "نامحدود" if days <= 0 else f"{days} روز"


def _pkg_price(pkg: Dict) -> int:
    """The price THIS user actually pays (rep/custom price), not the package
    default. Callers enrich pkgs with `display_price`."""
    return int(pkg.get("display_price", pkg.get("price") or 0) or 0)


def _fa_num(value: int) -> str:
    return f"{int(value):,}".replace(",", "،")


def _pkg_flair(pkg: Dict, biggest_gb: float) -> tuple:
    """The emoji and Telegram button style for one package.

    Telegram offers exactly three styles — "primary" (blue), "success" (green)
    and "danger" (red) — so colour has to MEAN something rather than decorate.
    Here it is a size ladder, not a value claim: at our per-GB tariff the volume
    plans all cost the same per gigabyte, so calling one of them "best value"
    would be a lie the customer can check with a calculator.

      blue   — the ordinary volume plans
      green  — the largest volume plan on offer, whatever it happens to be
      red    — the unlimited flagship. Nothing on this screen is destructive, so
               red cannot be misread as a warning; among blue buy buttons it is
               simply the one that stands out.

    The emoji follows the same ladder so the two never disagree.
    """
    if is_unlimited_package(pkg):
        return "♾️", "danger"
    gb = float(pkg.get("traffic_gb") or 0)
    style = "success" if biggest_gb > 0 and gb >= biggest_gb else "primary"
    emoji = "💎" if gb >= 25 else "🚀" if gb >= 20 else "⚡" if gb >= 15 else "🌱"
    return emoji, style


def packages_kb(pkgs: List[Dict], bestseller_id: int = 0) -> InlineKeyboardMarkup:
    """One button per package, kept SHORT and unmistakable.

    The table above carries the detail, so the button only has to answer "what
    do I get and what does it cost" — plus the verb, because a first-time
    customer has to be able to tell that pressing it IS the purchase.

    The package name is deliberately left out: it already spells out the volume
    and the duration that sit right next to it, and the doubling was what made
    the old button too long to read on a phone.
    """
    b = InlineKeyboardBuilder()
    biggest = max((float(p.get("traffic_gb") or 0)
                   for p in pkgs if not is_unlimited_package(p)), default=0.0)
    for p in pkgs:
        emoji, style = _pkg_flair(p, biggest)
        # One badge, on one button. Two would cancel each other out, and the
        # claim itself is measured — see best_selling_package_id().
        badge = " 🔥" if bestseller_id and int(p.get("id") or 0) == int(bestseller_id) else ""
        _button(
            b,
            text=f"{emoji} خرید {_pkg_traffic(p)} · {_pkg_duration(p)} — {_fa_num(_pkg_price(p))} تومان{badge}",
            callback_data=f"buy:{p['id']}",
            style=style,
        )
    b.adjust(1)
    return b.as_markup()


def packages_table_html(pkgs: List[Dict]) -> str:
    """The package list as a rich-message table (Bot API 10.1+).

    This MUST show the same numbers as `packages_kb` — the table is what the
    customer reads and the buttons are what they press, so any drift between the
    two is a price dispute waiting to happen. Both read them through the
    `_pkg_*` helpers above for exactly that reason; keep it that way.

    The row's emoji is the same one its button carries, which is what lets a
    customer match a row to the button that buys it without reading either.
    """
    biggest = max((float(p.get("traffic_gb") or 0)
                   for p in pkgs if not is_unlimited_package(p)), default=0.0)
    rows = []
    for p in pkgs:
        emoji, _ = _pkg_flair(p, biggest)
        star = is_unlimited_package(p)
        name = f"{emoji} {rich_esc(_pkg_traffic(p))}"
        price = rich_esc(_fa_num(_pkg_price(p)))
        rows.append([
            # The flagship row is highlighted rather than merely listed: <mark>
            # is Telegram's own emphasis, so it tracks the reader's theme instead
            # of us guessing at a colour.
            f"<mark><b>{name}</b></mark>" if star else name,
            rich_esc(_pkg_duration(p)),
            f"<mark><b>{price}</b></mark>" if star else f"<b>{price}</b>",
        ])
    return rich_table(
        ["📦 پکیج",
         f'{tg_emoji("duration", "⏱")} مدت',
         f'{tg_emoji("price", "💰")} قیمت'],
        rows,
        align=["left", "center", "right"],
        caption="قیمت‌ها به تومان · ۵ کاربر هم‌زمان روی همه‌ی پکیج‌ها",
    )
