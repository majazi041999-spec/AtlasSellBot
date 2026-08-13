"""Date-filtered purchase reports for representatives (نماینده), and their Excel export.

Shared by the admin panel and the mini-app so both always show the same numbers.

Everything here is anchored to Tehran time. The date columns in the database are
the server's local wall clock (SQLite `datetime('now','localtime')`), so a Jalali
range chosen by the user is converted the whole way — Jalali → Tehran → the
server's own local frame — before it ever reaches SQL. That is what makes a
report titled «از ۱ مرداد تا ۳۱ مرداد» actually contain those days, even on a
VPS running UTC.
"""

from datetime import timedelta
from typing import Dict, List

from core.database import get_rep_purchases
from core.jalali import (
    JALALI_MONTHS,
    jalali_add_months,
    jalali_datetime_display,
    jalali_parts,
    jalali_to_tehran,
    parse_jalali,
    tehran_now,
    tehran_to_db_string,
)
from core.xlsx import build_xlsx

# Presets offered in the UI. `months`/`days` count back from today; None = no lower bound.
PRESETS: Dict[str, Dict] = {
    "week":     {"label": "۷ روز اخیر", "days": 7},
    "month":    {"label": "۱ ماه اخیر", "months": 1},
    "3months":  {"label": "۳ ماه اخیر", "months": 3},
    "6months":  {"label": "۶ ماه اخیر", "months": 6},
    "year":     {"label": "۱ سال اخیر", "months": 12},
    "all":      {"label": "همه", "months": None, "days": None},
}
DEFAULT_PRESET = "month"


def _jalali_label(jy: int, jm: int, jd: int) -> str:
    return f"{jd} {JALALI_MONTHS[jm - 1]} {jy}"


def resolve_range(preset: str = DEFAULT_PRESET, date_from: str = "", date_to: str = "") -> Dict:
    """Turn a preset (or a pair of Jalali dates) into DB bounds plus display labels.

    An explicit `date_from`/`date_to` always wins over the preset. The end bound
    covers the whole chosen day (…23:59:59) so «تا ۳۱ مرداد» includes the 31st.
    """
    parsed_from = parse_jalali(date_from)
    parsed_to = parse_jalali(date_to)

    if parsed_from or parsed_to:
        used_preset = "custom"
        start = jalali_to_tehran(*parsed_from) if parsed_from else None
        end = (jalali_to_tehran(*parsed_to, hour=23, minute=59, second=59)
               if parsed_to else tehran_now())
        # Tolerate a reversed range instead of silently returning nothing.
        if start and end and start > end:
            start, end = (end.replace(hour=0, minute=0, second=0),
                          start.replace(hour=23, minute=59, second=59))
            parsed_from, parsed_to = parsed_to, parsed_from
    else:
        used_preset = preset if preset in PRESETS else DEFAULT_PRESET
        spec = PRESETS[used_preset]
        end = tehran_now()
        jy, jm, jd = jalali_parts(end)
        if spec.get("months"):
            start = jalali_to_tehran(*jalali_add_months(jy, jm, jd, -int(spec["months"])))
        elif spec.get("days"):
            start = (end - timedelta(days=int(spec["days"]) - 1)).replace(
                hour=0, minute=0, second=0, microsecond=0)
        else:
            start = None
        if start:
            parsed_from = jalali_parts(start)
        parsed_to = jalali_parts(end)

    return {
        "preset": used_preset,
        "since": tehran_to_db_string(start) if start else None,
        "until": tehran_to_db_string(end) if end else None,
        "from_jalali": "%04d/%02d/%02d" % parsed_from if parsed_from else "",
        "to_jalali": "%04d/%02d/%02d" % parsed_to if parsed_to else "",
        "from_label": _jalali_label(*parsed_from) if parsed_from else "ابتدا",
        "to_label": _jalali_label(*parsed_to) if parsed_to else "اکنون",
    }


def _status_label(item: Dict) -> str:
    if not int(item.get("is_active") or 0):
        return "غیرفعال"
    expires = int(item.get("expires_at") or 0)
    if expires <= 0:
        return "فعال"
    now_ms = int(tehran_now().timestamp() * 1000)
    return "منقضی" if expires <= now_ms else "فعال"


def _traffic_label(item: Dict) -> str:
    if item.get("is_unlimited"):
        return "نامحدود"
    value = float(item.get("traffic_gb") or 0)
    return f"{value:g}"


def _start_label(item: Dict) -> str:
    started = int(item.get("started_at") or 0)
    if started > 0:
        return jalali_datetime_display(started)
    # A "starts on first use" service has no start date until the customer
    # actually connects — say so rather than printing a misleading date.
    return "شروع نشده"


def _expiry_label(item: Dict) -> str:
    expires = int(item.get("expires_at") or 0)
    if expires > 0:
        return jalali_datetime_display(expires)
    return "پس از اولین اتصال" if int(item.get("started_at") or 0) <= 0 else "نامحدود"


async def build_rep_report(user: Dict, preset: str = DEFAULT_PRESET,
                           date_from: str = "", date_to: str = "",
                           limit: int = 5000) -> Dict:
    """The report as both surfaces render it: rows with Jalali dates + a summary."""
    rng = resolve_range(preset, date_from, date_to)
    data = await get_rep_purchases(int(user["id"]), since=rng["since"],
                                   until=rng["until"], limit=limit)

    rows: List[Dict] = []
    for index, item in enumerate(data["items"], start=1):
        rows.append({
            "row": index,
            "kind": item["kind"],
            "kind_label": "تمدید" if item["kind"] == "renewal" else "خرید",
            "name": item["name"],
            "traffic_gb": item["traffic_gb"],
            "traffic_label": _traffic_label(item),
            "is_unlimited": bool(item["is_unlimited"]),
            "duration_days": item["duration_days"],
            "price": item["price"],
            "purchased_at": jalali_datetime_display(item["purchased_at"]),
            "started_at": _start_label(item),
            "expires_at": _expiry_label(item),
            "status": _status_label(item),
            "used_gb": round(int(item.get("used_bytes") or 0) / (1024 ** 3), 2),
            "profile_id": item["profile_id"],
            "order_id": item["order_id"],
        })

    return {
        "range": rng,
        "presets": [{"key": k, "label": v["label"]} for k, v in PRESETS.items()],
        "rows": rows,
        "summary": data["summary"],
        "rep": {
            "id": int(user["id"]),
            "telegram_id": int(user.get("telegram_id") or 0),
            "name": (str(user.get("rep_brand_name") or "").strip()
                     or str(user.get("full_name") or "").strip()
                     or str(user.get("username") or "").strip()
                     or f"#{user['id']}"),
        },
        "generated_at": jalali_datetime_display(tehran_now()),
    }


_COLUMNS = [
    {"header": "ردیف", "width": 7, "type": "int"},
    {"header": "نوع", "width": 10, "type": "text"},
    {"header": "نام انتخابی سرویس", "width": 30, "type": "text"},
    {"header": "حجم (گیگابایت)", "width": 16, "type": "float"},
    {"header": "مدت (روز)", "width": 12, "type": "int"},
    {"header": "تاریخ خرید", "width": 20, "type": "text"},
    {"header": "تاریخ شروع", "width": 20, "type": "text"},
    {"header": "تاریخ انقضا", "width": 20, "type": "text"},
    {"header": "مبلغ (تومان)", "width": 16, "type": "int"},
    {"header": "وضعیت", "width": 12, "type": "text"},
]


def rep_report_xlsx(report: Dict) -> bytes:
    """Render a built report as an .xlsx document (dates already Jalali)."""
    summary = report["summary"]
    rng = report["range"]
    rows = [[
        row["row"], row["kind_label"], row["name"],
        # Unlimited plans have no number to put here — the writer keeps this as
        # text when it is not parseable as a number.
        "نامحدود" if row["is_unlimited"] else row["traffic_gb"],
        row["duration_days"], row["purchased_at"], row["started_at"],
        row["expires_at"], row["price"], row["status"],
    ] for row in report["rows"]]

    titles = [
        f"گزارش خرید نماینده — {report['rep']['name']}",
        f"بازه: از {rng['from_label']} تا {rng['to_label']}",
        (f"تعداد سرویس: {summary['services']} | تمدید: {summary['renewals']} | "
         f"مجموع حجم: {summary['total_gb']} گیگابایت"
         + (f" (+{summary['unlimited_count']} سرویس نامحدود)" if summary["unlimited_count"] else "")
         + f" | مجموع خرید: {summary['total_spent']:,} تومان"),
        f"تاریخ تهیه گزارش: {report['generated_at']}",
    ]
    if not rows:
        titles.append("در این بازه هیچ خریدی ثبت نشده است.")
    return build_xlsx(_COLUMNS, rows, sheet_name="خرید نماینده", titles=titles)


def rep_report_filename(report: Dict) -> str:
    """ASCII-safe filename (Content-Disposition headers must stay latin-1)."""
    rng = report["range"]
    stamp = (rng["from_jalali"] or "all").replace("/", "") + "-" + (rng["to_jalali"] or "now").replace("/", "")
    return f"rep-{report['rep']['id']}-purchases-{stamp}.xlsx"
