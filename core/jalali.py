from datetime import datetime
from zoneinfo import ZoneInfo


TEHRAN_TZ = ZoneInfo("Asia/Tehran")


def tehran_now() -> datetime:
    return datetime.now(TEHRAN_TZ)


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_days_in_month = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666
        + (365 * gy)
        + ((gy2 + 3) // 4)
        - ((gy2 + 99) // 100)
        + ((gy2 + 399) // 400)
        + gd
        + g_days_in_month[gm - 1]
    )
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def jalali_parts(dt: datetime | None = None) -> tuple[int, int, int]:
    dt = dt or tehran_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TEHRAN_TZ)
    dt = dt.astimezone(TEHRAN_TZ)
    return gregorian_to_jalali(dt.year, dt.month, dt.day)


def jalali_date_key(dt: datetime | None = None) -> str:
    jy, jm, jd = jalali_parts(dt)
    return f"{jy:04d}-{jm:02d}-{jd:02d}"


def jalali_display(dt: datetime | None = None) -> str:
    jy, jm, jd = jalali_parts(dt)
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


# ── Jalali → Gregorian, and the calendar arithmetic the reports need ─────────

JALALI_MONTHS = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)

# Persian and Arabic-Indic digits → ASCII, so a date typed on a Persian keyboard
# parses the same as one typed on an English keyboard.
_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    """Exact inverse of gregorian_to_jalali (same day-count algorithm)."""
    jy += 1595
    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd
    if jm < 7:
        days += (jm - 1) * 31
    else:
        days += ((jm - 7) * 30) + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)
    month_days = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > month_days[gm]:
        gd -= month_days[gm]
        gm += 1
    return gy, gm, gd


def jalali_is_leap(jy: int) -> bool:
    """True when Esfand of `jy` has 30 days.

    Decided by round-tripping 30 Esfand through the conversion pair rather than
    by a separate leap formula, so the answer can never disagree with the dates
    the rest of this module produces.
    """
    return gregorian_to_jalali(*jalali_to_gregorian(jy, 12, 30)) == (jy, 12, 30)


def jalali_month_days(jy: int, jm: int) -> int:
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    return 30 if jalali_is_leap(jy) else 29


def jalali_add_months(jy: int, jm: int, jd: int, months: int) -> tuple[int, int, int]:
    """Shift a Jalali date by whole months, clamping the day to month length.

    "One month ago" has to mean the same day of the previous Jalali month — not
    30 days — or a report labelled «۱ ماه اخیر» would silently cover the wrong
    window near the 31-day/30-day boundary.
    """
    total = (jy * 12 + (jm - 1)) + months
    ny, nm = divmod(total, 12)
    nm += 1
    return ny, nm, min(jd, jalali_month_days(ny, nm))


def jalali_to_tehran(jy: int, jm: int, jd: int, hour: int = 0, minute: int = 0,
                     second: int = 0) -> datetime:
    gy, gm, gd = jalali_to_gregorian(int(jy), int(jm), int(jd))
    return datetime(gy, gm, gd, hour, minute, second, tzinfo=TEHRAN_TZ)


def parse_jalali(value: str) -> tuple[int, int, int] | None:
    """Parse '1404/05/22', '1404-5-22' or '14040522' → (jy, jm, jd)."""
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = raw.translate(_FA_DIGITS)
    digits = [p for p in raw.replace("-", "/").replace(".", "/").split("/") if p]
    if len(digits) == 1 and len(digits[0]) == 8 and digits[0].isdigit():
        digits = [digits[0][:4], digits[0][4:6], digits[0][6:]]
    if len(digits) != 3 or not all(p.isdigit() for p in digits):
        return None
    jy, jm, jd = (int(p) for p in digits)
    if not (1 <= jm <= 12) or jy < 1 or jd < 1 or jd > jalali_month_days(jy, jm):
        return None
    return jy, jm, jd


# ── Reading timestamps back out of the database ─────────────────────────────

def db_datetime_to_tehran(value) -> datetime | None:
    """Turn a stored timestamp into an exact Tehran-local datetime.

    Two storage shapes exist in this schema and they need opposite treatment:

      • TEXT columns written by SQLite's `datetime('now','localtime')` hold the
        SERVER's wall clock with no offset. A naive datetime is interpreted by
        `.astimezone()` as system-local, which is precisely what those strings
        are — so the conversion is exact even on a UTC VPS.
      • INTEGER columns (expire_timestamp, first_use_at) hold epoch
        milliseconds, which are absolute and need no such assumption.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
        return (dt if dt.tzinfo else dt.astimezone()).astimezone(TEHRAN_TZ)
    if isinstance(value, (int, float)) or str(value).strip().lstrip("-").isdigit():
        ms = int(float(value))
        if ms <= 0:
            return None
        # Values this large can only be milliseconds; smaller ones are seconds.
        if ms > 10_000_000_000:
            ms //= 1000
        return datetime.fromtimestamp(ms, TEHRAN_TZ)
    raw = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[: len(fmt) + 6], fmt).astimezone(TEHRAN_TZ)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw).astimezone(TEHRAN_TZ)
    except ValueError:
        return None


def tehran_to_db_string(dt: datetime) -> str:
    """The naive server-local string SQLite would have written for this instant.

    Used to compare a Tehran date range against `datetime('now','localtime')`
    columns without converting every row.
    """
    return dt.astimezone().replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def jalali_datetime_display(value, with_time: bool = True) -> str:
    """'1404/05/22 14:30' — empty string when the timestamp is missing."""
    dt = db_datetime_to_tehran(value)
    if not dt:
        return ""
    jy, jm, jd = jalali_parts(dt)
    stamp = f"{jy:04d}/{jm:02d}/{jd:02d}"
    return f"{stamp} {dt:%H:%M}" if with_time else stamp


def jalali_long_display(value) -> str:
    """'۲۲ مرداد ۱۴۰۴' style, for report headers."""
    dt = db_datetime_to_tehran(value)
    if not dt:
        return ""
    jy, jm, jd = jalali_parts(dt)
    return f"{jd} {JALALI_MONTHS[jm - 1]} {jy}"
