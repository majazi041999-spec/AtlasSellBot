// Jalali (Shamsi) date helpers — the exact counterpart of core/jalali.py.
//
// Same integer day-count algorithm as the backend, so a date shown here and a
// date parsed there can never disagree. Everything is anchored to Asia/Tehran
// rather than the viewer's timezone: an admin abroad must still see the day the
// business is actually in.

export const MONTHS = [
  'فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
  'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند',
]

export const WEEKDAYS = ['شنبه', 'یک‌شنبه', 'دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنج‌شنبه', 'جمعه']

export function toJalali(gy, gm, gd) {
  const gDaysInMonth = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
  const gy2 = gm > 2 ? gy + 1 : gy
  let days = 355666 + 365 * gy + Math.floor((gy2 + 3) / 4) - Math.floor((gy2 + 99) / 100)
    + Math.floor((gy2 + 399) / 400) + gd + gDaysInMonth[gm - 1]
  let jy = -1595 + 33 * Math.floor(days / 12053)
  days %= 12053
  jy += 4 * Math.floor(days / 1461)
  days %= 1461
  if (days > 365) {
    jy += Math.floor((days - 1) / 365)
    days = (days - 1) % 365
  }
  const jm = days < 186 ? 1 + Math.floor(days / 31) : 7 + Math.floor((days - 186) / 30)
  const jd = days < 186 ? 1 + (days % 31) : 1 + ((days - 186) % 30)
  return [jy, jm, jd]
}

export function toGregorian(jy, jm, jd) {
  jy += 1595
  let days = -355668 + 365 * jy + Math.floor(jy / 33) * 8 + Math.floor(((jy % 33) + 3) / 4) + jd
  days += jm < 7 ? (jm - 1) * 31 : (jm - 7) * 30 + 186
  let gy = 400 * Math.floor(days / 146097)
  days %= 146097
  if (days > 36524) {
    days -= 1
    gy += 100 * Math.floor(days / 36524)
    days %= 36524
    if (days >= 365) days += 1
  }
  gy += 4 * Math.floor(days / 1461)
  days %= 1461
  if (days > 365) {
    gy += Math.floor((days - 1) / 365)
    days = (days - 1) % 365
  }
  let gd = days + 1
  const leap = (gy % 4 === 0 && gy % 100 !== 0) || gy % 400 === 0
  const monthDays = [0, 31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
  let gm = 0
  while (gm < 13 && gd > monthDays[gm]) {
    gd -= monthDays[gm]
    gm += 1
  }
  return [gy, gm, gd]
}

// Leap years are decided by round-tripping 30 Esfand rather than by a separate
// formula, so this can never disagree with the conversions above.
export function isLeap(jy) {
  const [gy, gm, gd] = toGregorian(jy, 12, 30)
  const back = toJalali(gy, gm, gd)
  return back[0] === jy && back[1] === 12 && back[2] === 30
}

export function monthDays(jy, jm) {
  if (jm <= 6) return 31
  if (jm <= 11) return 30
  return isLeap(jy) ? 30 : 29
}

/** Today in Tehran, as [jy, jm, jd] — independent of the viewer's timezone. */
export function today() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tehran', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date()).split('-').map(Number)
  return toJalali(parts[0], parts[1], parts[2])
}

export function addMonths([jy, jm, jd], delta) {
  const total = jy * 12 + (jm - 1) + delta
  const ny = Math.floor(total / 12)
  const nm = (total % 12) + 1
  return [ny, nm, Math.min(jd, monthDays(ny, nm))]
}

export function addDays([jy, jm, jd], delta) {
  const [gy, gm, gd] = toGregorian(jy, jm, jd)
  const d = new Date(Date.UTC(gy, gm - 1, gd))
  d.setUTCDate(d.getUTCDate() + delta)
  return toJalali(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate())
}

const pad = (n) => String(n).padStart(2, '0')

/** '1404/05/22' — the wire format the backend parses. */
export function format(parts) {
  return parts ? `${parts[0]}/${pad(parts[1])}/${pad(parts[2])}` : ''
}

/** '۲۲ مرداد ۱۴۰۴' — for labels. */
export function formatLong(parts) {
  return parts ? `${parts[2]} ${MONTHS[parts[1] - 1]} ${parts[0]}` : ''
}

/** Parse '1404/05/22' (Persian digits welcome) → [jy, jm, jd], or null. */
export function parse(value) {
  const raw = String(value || '')
    .replace(/[۰-۹]/g, (c) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(c)))
    .replace(/[٠-٩]/g, (c) => String('٠١٢٣٤٥٦٧٨٩'.indexOf(c)))
    .trim()
  const m = raw.match(/^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})$/)
  if (!m) return null
  const [jy, jm, jd] = [Number(m[1]), Number(m[2]), Number(m[3])]
  if (jm < 1 || jm > 12 || jd < 1 || jd > monthDays(jy, jm)) return null
  return [jy, jm, jd]
}

/** Weekday index of the 1st of a month, 0 = Saturday — for laying out a calendar grid. */
export function firstWeekdayOfMonth(jy, jm) {
  const [gy, gm, gd] = toGregorian(jy, jm, 1)
  // JS: 0 = Sunday. Jalali weeks start on Saturday, so shift by one.
  return (new Date(Date.UTC(gy, gm - 1, gd)).getUTCDay() + 1) % 7
}
