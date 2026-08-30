# راهنمای API نمایندگان

> این همان متنی است که صفحه‌ی `https://<دامنه‌ی-شما>/api/rep/docs` نمایش می‌دهد.
> آن صفحه آدرس واقعی سرور شما را داخل نمونه‌ها می‌گذارد، پس برای دادن به نماینده
> **لینک همان صفحه بهتر است**. این فایل نسخه‌ی متنی و قابل فوروارد آن است.
>
> **برای توسعه‌دهنده:** اگر endpoint‌ای اضافه یا عوض شد، این فایل و
> `web/rep_api_docs.py` باید با هم به‌روز شوند. مستنداتی که دروغ می‌گوید از
> نداشتن مستندات بدتر است.

---

## این API چیست

نماینده می‌تواند **ربات یا پنل خودش** را به سامانه وصل کند و به‌صورت خودکار:

- سرویس بسازد (تکی یا گروهی)
- تمدید کند
- مصرف و انقضا را بخواند
- سرویس را قطع/وصل کند
- لینک لو‌رفته را باطل کند و لینک تازه بگیرد
- اکانت تست بسازد
- موجودی و سفارش‌هایش را ببیند

هزینه‌ی هر سرویس **از کیف پول نمایندگی خودِ او** کم می‌شود، با همان تعرفه‌ای که
در ربات می‌بیند.

---

## ۱. گرفتن کلید

نماینده خودش کلید را می‌سازد؛ نیازی به ادمین نیست:

1. در ربات → **پنل نمایندگی**
2. دکمه‌ی **«🔌 اتصال ربات (API)»**
3. **«🔑 ساخت کلید جدید»**

کلید **فقط یک بار** نمایش داده می‌شود (ما فقط hash آن را نگه می‌داریم و بازیابی
ممکن نیست). هر نماینده تا **۳ کلید فعال** هم‌زمان می‌تواند داشته باشد و هر کدام
را از همان صفحه لغو کند.

آدرس پایه:

```
https://<دامنه>/api/rep/v1
```

تست:

```bash
curl -H "Authorization: Bearer atlas_rep_XXXX" https://<دامنه>/api/rep/v1/ping
```

---

## ۲. احراز هویت

هدر:

```http
Authorization: Bearer atlas_rep_XXXXXXXXXXXXXXXXXXXX
```

یا معادلش: `X-API-Key: atlas_rep_XXXX`

| موضوع | توضیح |
|---|---|
| Scope | `read` (خواندن) و `write` (ساخت/تغییر). کلید ساخته‌شده از ربات هر دو را دارد. |
| محدودیت IP | اختیاری، برای کلیدهایی که ادمین به IP مشخص محدود کرده. |
| لغو فوری | اگر نمایندگی لغو یا حساب مسدود شود، **همه‌ی کلیدها همان لحظه از کار می‌افتند** (بدون نیاز به لغو دستی). |
| کلید خاموش | ادمین می‌تواند با تنظیم `rep_api_enabled=0` کل API را موقتاً ببندد. |

---

## ۳. قواعد عمومی

- درخواست و پاسخ **JSON** است (`Content-Type: application/json`).
- موفق: `"ok": true` — ناموفق: `"ok": false` + `error` (کد ماشینی) + `message` (متن فارسی).
- مبالغ به **تومان** و عدد صحیح.
- زمان‌ها **epoch میلی‌ثانیه**‌اند. `0` یعنی «بدون انقضا / هنوز شروع نشده».
- `traffic_gb: 0` یعنی **نامحدود** — آن را «صفر گیگ» تفسیر نکنید.
- محدودیت نرخ: پیش‌فرض **۱۲۰ درخواست در دقیقه** برای هر کلید. هدرهای
  `X-RateLimit-Limit` / `X-RateLimit-Remaining` / `X-RateLimit-Reset` در هر پاسخ می‌آیند.
- **Timeout سمت خودتان را کوتاه نگذارید.** ساخت هر سرویس روی همه‌ی سرورها انجام
  می‌شود و ممکن است تا حدود یک دقیقه طول بکشد. مقدار پیشنهادی: **۱۲۰ ثانیه**.

---

## ۴. جلوگیری از خرید تکراری (Idempotency)

اگر درخواست ساخت/تمدید به‌خاطر قطعی timeout شد، ارسال دوباره‌ی آن **نباید** دو بار
پول کم کند. روی `POST /services` و `POST /services/{id}/renew` این هدر را بفرستید:

```http
Idempotency-Key: order-4471
```

| حالت | نتیجه |
|---|---|
| همان کلید + همان بدنه | پاسخ اول عیناً برمی‌گردد، با `idempotent_replay: true`. پول دوباره کم نمی‌شود. |
| همان کلید + بدنه‌ی متفاوت | `409 idempotency_conflict` |
| درخواست قبلی هنوز در حال اجرا | `409 request_in_flight` — چند ثانیه بعد دوباره تلاش کنید |

کلیدها ۲۴ ساعت نگه‌داری می‌شوند. برای هر سفارش مشتری یک شناسه‌ی یکتا بسازید.

---

## ۵. کدهای خطا

| `error` | HTTP | معنی |
|---|---|---|
| `missing_key` | 401 | هدر کلید فرستاده نشده |
| `invalid_key` | 401 | کلید اشتباه یا لغو شده |
| `not_a_representative` | 403 | حساب دیگر نماینده نیست |
| `account_blocked` | 403 | حساب مسدود است |
| `ip_not_allowed` | 403 | IP در لیست مجاز کلید نیست |
| `insufficient_scope` | 403 | کلید دسترسی `write` ندارد |
| `topup_required` | 403 | حداقل شارژ اولیه‌ی نمایندگی انجام نشده |
| `rate_limited` | 429 | تعداد درخواست بیش از حد (`Retry-After` را ببینید) |
| `invalid_request` | 400 | پارامتر ناقص یا نامعتبر |
| `package_unavailable` | 400 | پکیج وجود ندارد یا غیرفعال است |
| `custom_pricing_unavailable` | 400 | تعرفه‌ی اختصاصی برای حجم دلخواه تنظیم نشده — از `package_id` استفاده کنید |
| `insufficient_balance` | 402 | موجودی کیف پول کافی نیست |
| `service_not_found` | 404 | سرویس پیدا نشد یا متعلق به شما نیست |
| `confirmation_required` | 400 | حذف بدون `confirm: true` |
| `provisioning_failed` | 502 | ساخت روی سرورها ناموفق — **مبلغ برگشت خورد** |
| `renew_failed` | 502 | تمدید ناموفق — **مبلغ برگشت خورد** |
| `revoke_failed` | 409/502 | تعویض لینک انجام نشد |
| `trial_disabled` | 403 | اکانت تست غیرفعال است |
| `trial_limit_reached` | 429 | سهمیه‌ی تست امروز پر شده |
| `api_disabled` | 503 | API توسط ادمین خاموش شده |

---

## ۶. Endpointها

همه با `https://<دامنه>/api/rep/v1` شروع می‌شوند.

### `GET /ping`
تست سلامت کلید.

```json
{ "ok": true, "api_version": "1.0", "server_time": 1756500000, "representative_id": 12 }
```

### `GET /me`
اطلاعات حساب: موجودی، برند، تعرفه، سهمیه‌ی تست، آمار.

```json
{
  "ok": true,
  "representative": { "id": 12, "brand_name": "MyVPN", "balance": 4200000 },
  "pricing": { "price_per_gb": 3500, "unlimited_price": 180000, "discount_percent": 0 },
  "stats": { "total_services": 380, "active_services": 291, "total_spent": 62150000 },
  "limits": { "max_batch": 10, "rate_per_min": 120, "trial_daily_limit": 5, "trial_used_today": 1 }
}
```

### `GET /packages`
پکیج‌های فعال با **قیمت نمایندگی خودتان** (`price`) در کنار قیمت عمومی (`list_price`).

### `POST /services`
ساخت سرویس و کسر از کیف پول.

| فیلد | نوع | توضیح |
|---|---|---|
| `package_id` | int | حالت اول: خرید بر اساس پکیج |
| `traffic_gb` | number | حالت دوم: حجم دلخواه. `0` = نامحدود |
| `duration_days` | int | همراه حالت دوم، الزامی |
| `name` | string | نام نمایشی سرویس |
| `names` | string[] | نام مجزا برای هر سرویس در خرید گروهی |
| `count` | int | تعداد، ۱ تا ۱۰ (پیش‌فرض ۱) |
| `note` | string | یادداشت داخلی روی سفارش |

> حالت «حجم دلخواه» فقط وقتی کار می‌کند که ادمین برای شما تعرفه‌ی هر گیگ (یا
> قیمت نامحدود) ثبت کرده باشد؛ در غیر این‌صورت `custom_pricing_unavailable`
> می‌گیرید و باید از `package_id` استفاده کنید.

```json
POST /services   (Idempotency-Key: cust-8891)
{ "package_id": 3, "name": "ali-mobile", "count": 2 }
```

```json
201
{
  "ok": true, "order_id": 9134, "requested": 2, "created": 2,
  "charged": 210000, "refunded": 0, "balance": 3990000,
  "services": [
    { "id": 4471, "name": "ali-mobile-1", "status": "pending", "unlimited": false,
      "traffic_gb": 30, "used_bytes": 0, "remaining_bytes": 32212254720,
      "usage_percent": 0, "expires_at": 0, "days_left": null,
      "starts_on_first_use": true,
      "subscription_url": "https://<دامنه>/sub/AbCdEf..." }
  ]
}
```

**موفقیت نسبی:** اگر بخشی از سرویس‌ها ساخته نشود، کد `207` برمی‌گردد،
`partial: true` می‌آید و **پول سرویس‌های ساخته‌نشده همان لحظه برگشت می‌خورد**
(`refunded`). هیچ‌وقت لازم نیست خودتان مغایرت‌گیری کنید.

مقادیر `status`:

| مقدار | معنی |
|---|---|
| `active` | فعال |
| `pending` | ساخته شده، هنوز اولین اتصال انجام نشده (زمان شروع نشده) |
| `disabled` | دستی قطع شده |
| `expired` | زمانش تمام شده |
| `depleted` | حجمش تمام شده |

### `GET /services`
پارامترها:

- `page`، `per_page` (حداکثر ۱۰۰)
- `q` — جستجو در نام
- `sort` = `newest` \| `oldest` \| `name_az` \| `expiry_soon` \| `usage_desc`
- `filter` = `all` \| `active` \| `inactive` \| `expired` \| `expiring` \| `near_limit` \| `unlimited`

```json
{ "ok": true, "services": [ ... ],
  "pagination": { "page": 1, "per_page": 50, "total": 128, "pages": 3 } }
```

### `GET /services/{id}`
جزئیات یک سرویس + آرایه‌ی `nodes` (لینک تک‌تک سرورها)، برای وقتی مشتری فقط یک
کانفیگ می‌خواهد.

### `POST /services/{id}/renew`
بدنه دقیقاً مثل ساخت (`package_id` یا `traffic_gb` + `duration_days`).

```json
{ "ok": true, "order_id": 9140, "charged": 105000, "balance": 3885000,
  "nodes_renewed": 6, "carried_over": true, "service": { ... } }
```

`carried_over: true` یعنی سرویس هنوز حجم و زمان داشت و باقی‌مانده‌اش به بسته‌ی
جدید اضافه شد.

### `POST /services/{id}/rename`
```json
{ "name": "ali-laptop" }
```

### `POST /services/{id}/disable` و `POST /services/{id}/enable`
قطع/وصل روی **همه‌ی سرورها**. برگشت‌پذیر، بدون بازگشت وجه. بدنه لازم ندارد.

### `POST /services/{id}/revoke`
وقتی مشتری لینکش را به اشتراک گذاشته: لینک قدیمی **کاملاً** از کار می‌افتد
(هم توکن و هم UUID روی همه‌ی سرورها عوض می‌شود) و لینک تازه می‌گیرید. حجم،
انقضا و مصرف حفظ می‌شود — **این تمدید نیست**. فقط روی سرویس **فعال** کار می‌کند.

```json
{ "ok": true, "subscription_url": "https://<دامنه>/sub/NEW...",
  "rotated_nodes": 6, "failed_nodes": 0 }
```

### `POST /services/{id}/delete`
حذف دائمی از همه‌ی سرورها.

```json
{ "confirm": true }
```

> ⚠️ **برگشت‌ناپذیر و بدون بازگشت وجه.** بدون `confirm: true` رد می‌شود.
> برای قطع موقت از `/disable` استفاده کنید.

### `POST /services/trial`
اکانت تست رایگان از سهمیه‌ی روزانه‌ی نمایندگی (اگر ادمین فعال کرده باشد).

```json
{ "name": "test-ali" }
→ { "ok": true, "trial_used_today": 2, "trial_daily_limit": 5, "service": { ... } }
```

### `GET /wallet`
موجودی + آخرین تراکنش‌ها. پارامتر `limit` (پیش‌فرض ۲۰).

### `GET /orders`
سفارش‌های اخیر — سند حسابداری هر کسر از کیف پول. پارامتر `limit` (پیش‌فرض ۲۵).

---

## ۷. نمونه کد

### cURL

```bash
curl -X POST https://<دامنه>/api/rep/v1/services \
  -H "Authorization: Bearer $ATLAS_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: order-1001" \
  -d '{"package_id": 3, "name": "ali", "count": 1}'
```

### Python (httpx)

```python
import httpx, uuid

BASE = "https://<دامنه>/api/rep/v1"

class AtlasRep:
    def __init__(self, key: str):
        self.c = httpx.AsyncClient(
            base_url=BASE,
            headers={"Authorization": f"Bearer {key}"},
            timeout=120,          # ساخت سرویس روی چند سرور زمان‌بر است
        )

    async def packages(self):
        r = await self.c.get("/packages")
        r.raise_for_status()
        return r.json()["packages"]

    async def create(self, package_id: int, name: str = "", count: int = 1):
        r = await self.c.post(
            "/services",
            json={"package_id": package_id, "name": name, "count": count},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("message") or data.get("error"))
        return data["services"]

    async def renew(self, service_id: int, package_id: int):
        r = await self.c.post(
            f"/services/{service_id}/renew",
            json={"package_id": package_id},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        return r.json()
```

### Node.js

```js
const BASE = "https://<دامنه>/api/rep/v1";

async function createService(key, packageId, name) {
  const res = await fetch(`${BASE}/services`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${key}`,
      "Content-Type": "application/json",
      "Idempotency-Key": crypto.randomUUID(),
    },
    body: JSON.stringify({ package_id: packageId, name, count: 1 }),
  });
  const data = await res.json();
  if (!data.ok) throw new Error(data.message || data.error);
  return data.services[0].subscription_url;
}
```

---

## ۸. امنیت

- کلید را **فقط روی سرور خودتان** نگه دارید. هرگز داخل اپ موبایل، جاوااسکریپت
  مرورگر یا مخزن گیت عمومی نگذارید — قابل استخراج است.
- کلید = دسترسی به کیف پول شما. هرکس آن را داشته باشد می‌تواند از موجودی‌تان
  سرویس بسازد.
- اگر کلید لو رفت، همان لحظه از داخل ربات لغوش کنید و کلید تازه بسازید.
- حتماً از **HTTPS** استفاده کنید.
- اگر سرورتان IP ثابت دارد، از ادمین بخواهید کلید را به همان IP محدود کند.
- برای ربات‌هایی که فقط گزارش می‌گیرند، کلید با دسترسی `read` بگیرید.
