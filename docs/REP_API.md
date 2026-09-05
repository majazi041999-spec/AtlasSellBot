# راهنمای API نمایندگان

> **این نسخه‌ی متنی است.** نسخه‌ی اصلی و همیشه‌به‌روز، صفحه‌ی
> `https://<دامنه‌ی-شما>/api/rep/docs` است که آدرس واقعی سرور تو را داخل
> نمونه‌کدها می‌گذارد و تب PHP / Python / Node.js دارد — **برای دادن به نماینده
> همان لینک را بفرست.**
>
> **برای توسعه‌دهنده:** اگر endpointای اضافه یا عوض شد، این فایل و
> `web/rep_api_docs.py` باید با هم به‌روز شوند. مستنداتی که دروغ می‌گوید از
> نداشتن مستندات بدتر است.

---

## این API چیست

نماینده می‌تواند **ربات یا سایت خودش** را به سامانه وصل کند و خودکار:

- سرویس بسازد (تکی یا گروهی)
- تمدید کند
- مصرف و انقضا را بخواند
- سرویس را قطع/وصل کند
- لینک لو‌رفته را باطل کند و لینک تازه بگیرد
- اکانت تست بسازد
- موجودی و سفارش‌هایش را ببیند

هزینه از **کیف پول نمایندگی خودش** کم می‌شود، با همان تعرفه‌ای که در ربات می‌بیند.

---

## ۱. گرفتن کلید

نماینده خودش کلید را می‌سازد؛ نیازی به ادمین نیست:

1. در ربات → **پنل نمایندگی**
2. دکمه‌ی **«🔌 اتصال ربات (API)»**
3. **«🔑 ساخت کلید جدید»**

کلید **فقط یک بار** نمایش داده می‌شود (ما فقط hash آن را نگه می‌داریم و بازیابی
ممکن نیست). هر نماینده تا **۳ کلید فعال** هم‌زمان، و هر کدام را از همان صفحه
می‌تواند لغو کند.

آدرس پایه:

```
https://<دامنه>/api/rep/v1
```

---

## ۲. تابع پایه — یک بار کپی کن

همه‌ی مثال‌های این راهنما فقط همین تابع `atlas()` را صدا می‌زنند.

### PHP

```php
<?php
// ---------- تنظیمات ----------
define('ATLAS_BASE', 'https://<دامنه>/api/rep/v1');
define('ATLAS_KEY',  'atlas_rep_کلید_خودت');

// یک درخواست به API می‌زند.
// $idem فقط برای «ساخت» و «تمدید» لازم است (جلوگیری از خرید تکراری).
// خروجی: ['status' => کد HTTP, 'data' => آرایه‌ی پاسخ]
function atlas($method, $path, $body = null, $idem = null) {
    $headers = [
        'Authorization: Bearer ' . ATLAS_KEY,
        'Content-Type: application/json',
    ];
    if ($idem) {
        $headers[] = 'Idempotency-Key: ' . $idem;
    }

    $ch = curl_init(ATLAS_BASE . $path);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CUSTOMREQUEST  => $method,
        CURLOPT_HTTPHEADER     => $headers,
        CURLOPT_TIMEOUT        => 100,
    ]);
    if ($body !== null) {
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($body, JSON_UNESCAPED_UNICODE));
    }

    $raw    = curl_exec($ch);
    $status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    return ['status' => $status, 'data' => json_decode($raw, true)];
}
```

### Python

```python
# نصب:  pip install requests
import requests

# ---------- تنظیمات ----------
BASE = "https://<دامنه>/api/rep/v1"
KEY  = "atlas_rep_کلید_خودت"

# یک درخواست به API می‌زند.
# idem فقط برای «ساخت» و «تمدید» لازم است (جلوگیری از خرید تکراری).
# خروجی: (کد HTTP، دیکشنری پاسخ)
def atlas(method, path, body=None, idem=None):
    headers = {"Authorization": "Bearer " + KEY}
    if idem:
        headers["Idempotency-Key"] = idem

    r = requests.request(method, BASE + path, json=body,
                         headers=headers, timeout=100)
    return r.status_code, r.json()
```

### Node.js (نسخه ۱۸ به بالا)

```js
// ---------- تنظیمات ----------
const BASE = "https://<دامنه>/api/rep/v1";
const KEY  = "atlas_rep_کلید_خودت";

// یک درخواست به API می‌زند.
// idem فقط برای «ساخت» و «تمدید» لازم است (جلوگیری از خرید تکراری).
// خروجی: { status: کد HTTP, data: پاسخ }
async function atlas(method, path, body = null, idem = null) {
  const headers = {
    "Authorization": "Bearer " + KEY,
    "Content-Type": "application/json",
  };
  if (idem) headers["Idempotency-Key"] = idem;

  const res = await fetch(BASE + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(100000),
  });

  return { status: res.status, data: await res.json() };
}
```

تست کلید:

```php
$r = atlas('GET', '/ping');   print_r($r['data']);
```
```python
status, data = atlas("GET", "/ping");   print(data)
```
```js
const r = await atlas("GET", "/ping");   console.log(r.data);
```

پاسخ: `{ "ok": true, "api_version": "1.0", "representative_id": 12 }`

---

## ۳. قواعد عمومی

- درخواست و پاسخ **JSON** است.
- موفق: `"ok": true` — ناموفق: `"ok": false` + `error` (کد انگلیسی برای برنامه) + `message` (متن فارسی برای مشتری).
- مبالغ به **تومان** و عدد صحیح.
- زمان‌ها **epoch میلی‌ثانیه**. `0` یعنی «بدون انقضا / هنوز شروع نشده».
- `traffic_gb: 0` یعنی **نامحدود** — «صفر گیگ» نیست.
- محدودیت نرخ: **۱۲۰ درخواست در دقیقه** برای هر کلید (`X-RateLimit-Remaining` در پاسخ).

### ⏱ زمان پاسخ و خطای 524 (مهم)

ساخت هر سرویس روی **همه‌ی سرورها** انجام می‌شود و می‌تواند تا حدود یک دقیقه طول
بکشد. اگر سامانه پشت **Cloudflare** باشد، Cloudflare بعد از حدود **۱۰۰ ثانیه**
ارتباط را می‌بندد و `524` می‌دهد — **ولی سرور کارش را تمام می‌کند و سرویس ساخته
می‌شود.** پس:

- در هر درخواست حداکثر **۳ تا ۵ سرویس** بساز (`count`)، نه ۱۰ تا.
- حتماً `Idempotency-Key` بفرست (بخش بعد).
- `timeout` سمت خودت را روی ~۱۰۰ ثانیه بگذار.

---

## ۴. جلوگیری از خرید تکراری (Idempotency)

روی `POST /services` و `POST /services/{id}/renew` یک **شناسه‌ی یکتا** بفرست —
مثلاً شماره‌ی سفارش مشتری در ربات خودت:

```http
Idempotency-Key: order-1001
```

| اگر… | نتیجه |
|---|---|
| همان شناسه + همان بدنه | پاسخ اول عیناً برمی‌گردد (`idempotent_replay: true`). **پول دوباره کم نمی‌شود.** |
| درخواست قبلی هنوز در حال انجام | `409 request_in_flight` — چند ثانیه صبر و دوباره بپرس |
| همان شناسه + بدنه‌ی متفاوت | `409 idempotency_conflict` — برای سفارش جدید شناسه‌ی جدید بساز |

**وقتی timeout یا 524 گرفتی:** سفارش را از صفر نساز. همان درخواست را با **همان
شناسه** بفرست؛ اگر `409 request_in_flight` گرفتی، چند ثانیه صبر کن و دوباره
بفرست تا پاسخ واقعی را بگیری. هرگز دو بار پول کم نمی‌شود. (کد آماده در بخش ۷.)

شناسه‌ها ۲۴ ساعت نگه داشته می‌شوند.

---

## ۵. دستورها

همه با `https://<دامنه>/api/rep/v1` شروع می‌شوند.

### `GET /me` — حساب من

```php
$r = atlas('GET', '/me');
echo $r['data']['representative']['balance'];
```
```python
status, data = atlas("GET", "/me")
print(data["representative"]["balance"])
```
```js
const r = await atlas("GET", "/me");
console.log(r.data.representative.balance);
```

```json
{
  "ok": true,
  "representative": { "id": 12, "brand_name": "MyVPN", "balance": 4200000 },
  "pricing": { "price_per_gb": 3500, "unlimited_price": 180000, "discount_percent": 0 },
  "stats": { "total_services": 380, "active_services": 291, "total_spent": 62150000 },
  "limits": { "max_batch": 10, "rate_per_min": 120, "trial_daily_limit": 5, "trial_used_today": 1 }
}
```

### `GET /packages` — پکیج‌ها با قیمت نمایندگی من

```php
$r = atlas('GET', '/packages');
foreach ($r['data']['packages'] as $p) {
    echo $p['id'] . ' - ' . $p['name'] . ' - ' . number_format($p['price']) . " تومان\n";
}
```
```python
status, data = atlas("GET", "/packages")
for p in data["packages"]:
    print(p["id"], p["name"], f"{p['price']:,} تومان")
```
```js
const r = await atlas("GET", "/packages");
for (const p of r.data.packages) console.log(p.id, p.name, p.price);
```

`price` = قیمت اختصاصی تو؛ همان مبلغی که از کیف پولت کم می‌شود.

### `GET /packages/table` — جدول آماده‌ی ارسال

همان جدول تمیزی که ربات خودمان نشان می‌دهد، با **قیمت‌های خودت** و **متن‌های خودت**.

> ⚠️ **درباره‌ی اموجی پرمیوم**
>
> تلگرام اجازه‌ی استفاده از اموجی پرمیوم را فقط به رباتی می‌دهد که روی
> **Fragment یوزرنیم خریده** باشد، یا **مالکِ رباتش Telegram Premium داشته
> باشد**. این محدودیت روی **رباتِ فرستنده** است، نه روی خودِ اموجی — اگر مالک
> ربات تو پرمیوم نیست، تلگرام اموجی‌ها را حذف می‌کند.
>
> برای همین هر دو نسخه همیشه برمی‌گردد. یک بار بفرست، ببین کدام درست نمایش
> داده می‌شود، و همان را استفاده کن. **جدول در هر دو حالت یکی است.**

| پارامتر | پیش‌فرض | توضیح |
|---|---|---|
| `premium` | `0` | `1` = فیلد `html` با اموجی پرمیوم ساخته شود |
| `title` | 🛒 پکیج‌ها و قیمت‌ها | تیتر بالای جدول |
| `intro` | — | یک خط توضیح، بالای جدول |
| `note` | — | یک خط، پایین جدول |
| `columns` | `📦 پکیج\|⏱ مدت\|💰 قیمت` | سه سرستون، با `\|` جدا شده |
| `caption` | قیمت‌ها به تومان | زیرنویس جدول |

| فیلد خروجی | چطور بفرستی |
|---|---|
| `html_premium` | `parse_mode="HTML"` — با اموجی پرمیوم |
| `html_plain` | `parse_mode="HTML"` — با اموجی عادی |
| `html` | هرکدام که با `premium` انتخاب کردی |
| `markdown` | `sendRichMessage` — جدول واقعی، بدون نیاز به پرمیوم |
| `packages` | داده‌ی خام، اگر خودت می‌خواهی بچینی |

```python
status, data = atlas("GET", "/packages/table", params={
    "premium": 0,
    "title": "🛒 لیست قیمت من",
    "columns": "📦 حجم|⏱ مدت|💰 قیمت",
    "note": "برای خرید پیام بده",
})
await bot.send_message(chat_id, data["html_plain"], parse_mode="HTML")
```

قیمت‌های داخل جدول **خودکار** با تعرفه‌ی نمایندگی تو حساب می‌شوند.

### `POST /services` — ساخت سرویس

| فیلد | نوع | توضیح |
|---|---|---|
| `package_id` | عدد | **روش اول:** خرید بر اساس پکیج |
| `traffic_gb` | عدد | **روش دوم:** حجم دلخواه. `0` = نامحدود |
| `duration_days` | عدد | همراه روش دوم، الزامی |
| `name` | متن | نام سرویس (اسم مشتری) |
| `names` | لیست متن | نام جدا برای هر سرویس در خرید گروهی |
| `count` | عدد | تعداد، ۱ تا ۱۰ (پیش‌فرض ۱). پشت Cloudflare بیشتر از ۵ نگذار. |
| `note` | متن | یادداشت داخلی روی سفارش |

> روش دوم فقط وقتی کار می‌کند که ادمین برایت تعرفه‌ی هر گیگ (یا قیمت نامحدود)
> ثبت کرده باشد؛ وگرنه `custom_pricing_unavailable` می‌گیری و باید از
> `package_id` استفاده کنی.

```php
$r = atlas('POST', '/services', [
    'package_id' => 3,
    'name'       => 'ali-mobile',
    'count'      => 1,
], 'order-1001');

if (!empty($r['data']['ok'])) {
    echo "لینک مشتری: " . $r['data']['services'][0]['subscription_url'];
} else {
    echo "خطا: " . $r['data']['message'];
}
```
```python
status, data = atlas("POST", "/services", {
    "package_id": 3, "name": "ali-mobile", "count": 1,
}, "order-1001")

if data.get("ok"):
    print("لینک مشتری:", data["services"][0]["subscription_url"])
else:
    print("خطا:", data["message"])
```
```js
const r = await atlas("POST", "/services",
  { package_id: 3, name: "ali-mobile", count: 1 }, "order-1001");

if (r.data.ok) console.log("لینک مشتری:", r.data.services[0].subscription_url);
else console.log("خطا:", r.data.message);
```

```json
{
  "ok": true, "order_id": 9134, "requested": 1, "created": 1,
  "charged": 105000, "refunded": 0, "balance": 3990000,
  "services": [{
    "id": 4471, "name": "ali-mobile", "status": "pending",
    "unlimited": false, "traffic_gb": 30, "used_bytes": 0,
    "expires_at": 0, "days_left": null, "starts_on_first_use": true,
    "subscription_url": "https://<دامنه>/sub/AbCdEf..."
  }]
}
```

**معنی `status`:**

| مقدار | معنی |
|---|---|
| `active` | فعال و در حال استفاده |
| `pending` | ساخته شده، هنوز مشتری وصل نشده — زمان از اولین اتصال شروع می‌شود |
| `disabled` | خودت قطعش کرده‌ای |
| `expired` | زمانش تمام شده |
| `depleted` | حجمش تمام شده |

**موفقیت نسبی:** اگر بخشی از سرویس‌ها ساخته نشود، کد `207` می‌گیری،
`partial: true` می‌آید و **پول سرویس‌های ساخته‌نشده همان لحظه برمی‌گردد**
(`refunded`). لازم نیست خودت حساب‌وکتاب کنی.

### `GET /services` — لیست سرویس‌ها

| پارامتر | مقدارها |
|---|---|
| `page` / `per_page` | شماره‌ی صفحه و تعداد در صفحه (حداکثر ۱۰۰) |
| `q` | جستجو در نام سرویس |
| `filter` | `all` · `active` · `inactive` · `expired` · `expiring` · `near_limit` · `unlimited` |
| `sort` | `newest` · `oldest` · `name_az` · `expiry_soon` · `usage_desc` |

```php
// سرویس‌هایی که نزدیک انقضا هستند — برای یادآوری تمدید به مشتری
$r = atlas('GET', '/services?filter=expiring&sort=expiry_soon&per_page=50');
foreach ($r['data']['services'] as $s) {
    echo $s['name'] . ' - ' . $s['days_left'] . " روز مانده\n";
}
```
```python
# سرویس‌هایی که نزدیک انقضا هستند — برای یادآوری تمدید به مشتری
status, data = atlas("GET", "/services?filter=expiring&sort=expiry_soon&per_page=50")
for s in data["services"]:
    print(s["name"], s["days_left"], "روز مانده")
```
```js
// سرویس‌هایی که نزدیک انقضا هستند — برای یادآوری تمدید به مشتری
const r = await atlas("GET", "/services?filter=expiring&sort=expiry_soon&per_page=50");
for (const s of r.data.services) console.log(s.name, s.days_left);
```

### `GET /services/{id}` — جزئیات + لینک تک‌تک سرورها

```php
$s = atlas('GET', '/services/4471')['data']['service'];
foreach ($s['nodes'] as $n) { echo $n['label'] . ': ' . $n['link'] . "\n"; }
```
```python
status, data = atlas("GET", "/services/4471")
for n in data["service"]["nodes"]:
    print(n["label"], n["link"])
```
```js
const r = await atlas("GET", "/services/4471");
for (const n of r.data.service.nodes) console.log(n.label, n.link);
```

### `POST /services/{id}/renew` — تمدید

بدنه دقیقاً مثل ساخت.

```php
$r = atlas('POST', '/services/4471/renew', ['package_id' => 3], 'renew-1001');
```
```python
status, data = atlas("POST", "/services/4471/renew", {"package_id": 3}, "renew-1001")
```
```js
const r = await atlas("POST", "/services/4471/renew", { package_id: 3 }, "renew-1001");
```

```json
{ "ok": true, "order_id": 9140, "charged": 105000, "balance": 3885000,
  "nodes_renewed": 6, "carried_over": true, "service": { } }
```

`carried_over: true` یعنی سرویس هنوز حجم و زمان داشت و باقی‌مانده‌اش به بسته‌ی
جدید **اضافه** شد.

### `POST /services/{id}/rename` — تغییر نام

```php
atlas('POST', '/services/4471/rename', ['name' => 'ali-laptop']);
```
```python
atlas("POST", "/services/4471/rename", {"name": "ali-laptop"})
```
```js
await atlas("POST", "/services/4471/rename", { name: "ali-laptop" });
```

### `POST /services/{id}/disable` و `/enable` — قطع و وصل

روی همه‌ی سرورها. برگشت‌پذیر، بدون بازگشت وجه. بدنه لازم ندارد.

```php
atlas('POST', '/services/4471/disable');   // مشتری پول نداده؟ قطعش کن
atlas('POST', '/services/4471/enable');    // پرداخت کرد؟ دوباره وصل
```
```python
atlas("POST", "/services/4471/disable")
atlas("POST", "/services/4471/enable")
```
```js
await atlas("POST", "/services/4471/disable");
await atlas("POST", "/services/4471/enable");
```

### `POST /services/{id}/revoke` — باطل‌کردن لینک لو‌رفته

مشتری لینکش را به دیگران داده؟ این دستور لینک قدیمی را **کاملاً** از کار
می‌اندازد (هم توکن و هم UUID روی همه‌ی سرورها عوض می‌شود) و لینک تازه می‌دهد.
حجم، انقضا و مصرف حفظ می‌شود — **تمدید نیست و پولی نمی‌گیرد**. فقط روی سرویس
**فعال** کار می‌کند.

```php
$r = atlas('POST', '/services/4471/revoke');
echo "لینک جدید: " . $r['data']['subscription_url'];
```
```python
status, data = atlas("POST", "/services/4471/revoke")
print("لینک جدید:", data["subscription_url"])
```
```js
const r = await atlas("POST", "/services/4471/revoke");
console.log("لینک جدید:", r.data.subscription_url);
```

### `POST /services/{id}/delete` — حذف دائمی

```php
atlas('POST', '/services/4471/delete', ['confirm' => true]);
```
```python
atlas("POST", "/services/4471/delete", {"confirm": True})
```
```js
await atlas("POST", "/services/4471/delete", { confirm: true });
```

> ⚠️ **برگشت‌ناپذیر و بدون بازگشت وجه.** بدون `confirm: true` رد می‌شود.
> برای قطع موقت از `/disable` استفاده کن.

### `POST /services/trial` — اکانت تست رایگان

از سهمیه‌ی روزانه‌ی نمایندگی (اگر ادمین فعال کرده باشد). رایگان است.

```php
$r = atlas('POST', '/services/trial', ['name' => 'test-ali']);
```
```python
status, data = atlas("POST", "/services/trial", {"name": "test-ali"})
```
```js
const r = await atlas("POST", "/services/trial", { name: "test-ali" });
```

### `GET /wallet` و `GET /orders`

موجودی و تراکنش‌ها · سفارش‌های اخیر (سند حسابداری هر کسر از کیف پول).
هر دو پارامتر `limit` دارند.

```php
$w = atlas('GET', '/wallet?limit=10');
echo number_format($w['data']['balance']);
```
```python
status, w = atlas("GET", "/wallet?limit=10");   print(w["balance"])
```
```js
const w = await atlas("GET", "/wallet?limit=10");   console.log(w.data.balance);
```

---

## ۶. خطاها

هر خطا این شکل را دارد — `error` برای برنامه‌ات، `message` برای نمایش به مشتری:

```json
{ "ok": false, "error": "insufficient_balance",
  "message": "موجودی کیف پول کافی نیست. لازم: 105,000 تومان، موجودی: 40,000 تومان.",
  "required": 105000, "balance": 40000 }
```

| `error` | کد | یعنی چه و چه کار کنم |
|---|---|---|
| `missing_key` | 401 | هدر کلید را نفرستاده‌ای |
| `invalid_key` | 401 | کلید اشتباه یا لغو شده — از ربات کلید تازه بگیر |
| `not_a_representative` | 403 | حساب دیگر نماینده نیست |
| `account_blocked` | 403 | حساب مسدود است — با پشتیبانی تماس بگیر |
| `insufficient_scope` | 403 | کلیدت فقط خواندنی است |
| `ip_not_allowed` | 403 | از IP غیرمجاز درخواست زده‌ای |
| `topup_required` | 403 | هنوز حداقل شارژ اولیه‌ی نمایندگی را انجام نداده‌ای |
| `rate_limited` | 429 | خیلی سریع درخواست زده‌ای — `Retry-After` ثانیه صبر کن |
| `invalid_request` | 400 | پارامترها ناقص یا اشتباه‌اند |
| `package_unavailable` | 400 | پکیج وجود ندارد یا غیرفعال است |
| `custom_pricing_unavailable` | 400 | برای حجم دلخواه تعرفه نداری — از `package_id` استفاده کن |
| `insufficient_balance` | 402 | کیف پولت را شارژ کن |
| `service_not_found` | 404 | این سرویس وجود ندارد یا مال تو نیست |
| `confirmation_required` | 400 | برای حذف باید `confirm: true` بفرستی |
| `provisioning_failed` | 502 | ساخت انجام نشد — **پولت برگشت خورد**، دوباره تلاش کن |
| `renew_failed` | 502 | تمدید انجام نشد — **پولت برگشت خورد** |
| `request_in_flight` | 409 | همین درخواست در حال انجام است — چند ثانیه صبر و دوباره |
| `idempotency_conflict` | 409 | این شناسه قبلاً برای درخواست دیگری استفاده شده |
| `trial_limit_reached` | 429 | سهمیه‌ی تست امروزت پر شده |
| `api_disabled` | 503 | API موقتاً توسط ادمین خاموش شده |

---

## ۷. مثال کامل: فروش یک سرویس به مشتری

مقاوم در برابر timeout و 524، و در هیچ حالتی دو بار پول کم نمی‌کند.

### PHP

```php
<?php
// تابع atlas() از بخش ۲ را بالای همین فایل بگذار.

// برای یک مشتری سرویس می‌سازد و لینک اشتراک را برمی‌گرداند.
// $orderId باید برای هر سفارش یکتا باشد (شناسه‌ی سفارش در دیتابیس خودت).
function sellService($orderId, $packageId, $customerName) {
    // حداکثر ۳ بار تلاش — برای وقتی Cloudflare وسط کار قطع می‌کند.
    for ($try = 1; $try <= 3; $try++) {
        $r = atlas('POST', '/services', [
            'package_id' => $packageId,
            'name'       => $customerName,
        ], 'order-' . $orderId);          // همان شناسه در هر سه تلاش

        $data = $r['data'];

        // درخواست قبلی هنوز در حال انجام است: صبر کن و دوباره بپرس.
        if (isset($data['error']) && $data['error'] === 'request_in_flight') {
            sleep(8);
            continue;
        }

        // پاسخ قطعی گرفتیم (موفق یا ناموفق).
        if ($data !== null) {
            if (!empty($data['ok'])) {
                return ['ok' => true, 'link' => $data['services'][0]['subscription_url']];
            }
            return ['ok' => false, 'error' => $data['message']];
        }

        // پاسخی نیامد (timeout / 524). سرور شاید کارش را تمام کرده باشد،
        // پس با همان شناسه دوباره می‌پرسیم — پول دوباره کم نمی‌شود.
        sleep(8);
    }

    return ['ok' => false, 'error' => 'پاسخی از سرور نگرفتیم. چند دقیقه بعد وضعیت سفارش را چک کن.'];
}

// ---------- استفاده ----------
$res = sellService(1001, 3, 'ali-mobile');

if ($res['ok']) {
    echo "لینک اشتراک مشتری:\n" . $res['link'];
} else {
    echo "خطا: " . $res['error'];
}
```

### Python

```python
# تابع atlas() از بخش ۲ را بالای همین فایل بگذار.
import time

# برای یک مشتری سرویس می‌سازد و لینک اشتراک را برمی‌گرداند.
# order_id باید برای هر سفارش یکتا باشد (شناسه‌ی سفارش در دیتابیس خودت).
def sell_service(order_id, package_id, customer_name):
    # حداکثر ۳ بار تلاش — برای وقتی Cloudflare وسط کار قطع می‌کند.
    for attempt in range(3):
        try:
            status, data = atlas("POST", "/services", {
                "package_id": package_id,
                "name": customer_name,
            }, f"order-{order_id}")          # همان شناسه در هر سه تلاش
        except requests.RequestException:
            # پاسخی نیامد (timeout / 524). سرور شاید کارش را تمام کرده باشد،
            # پس با همان شناسه دوباره می‌پرسیم — پول دوباره کم نمی‌شود.
            time.sleep(8)
            continue

        # درخواست قبلی هنوز در حال انجام است: صبر کن و دوباره بپرس.
        if data.get("error") == "request_in_flight":
            time.sleep(8)
            continue

        # پاسخ قطعی گرفتیم (موفق یا ناموفق).
        if data.get("ok"):
            return True, data["services"][0]["subscription_url"]
        return False, data.get("message", "خطای نامشخص")

    return False, "پاسخی از سرور نگرفتیم. چند دقیقه بعد وضعیت سفارش را چک کن."


# ---------- استفاده ----------
ok, result = sell_service(1001, 3, "ali-mobile")
print("لینک اشتراک مشتری:\n" + result if ok else "خطا: " + result)
```

### Node.js

```js
// تابع atlas() از بخش ۲ را بالای همین فایل بگذار.

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// برای یک مشتری سرویس می‌سازد و لینک اشتراک را برمی‌گرداند.
// orderId باید برای هر سفارش یکتا باشد (شناسه‌ی سفارش در دیتابیس خودت).
async function sellService(orderId, packageId, customerName) {
  // حداکثر ۳ بار تلاش — برای وقتی Cloudflare وسط کار قطع می‌کند.
  for (let attempt = 0; attempt < 3; attempt++) {
    let data;
    try {
      const r = await atlas("POST", "/services", {
        package_id: packageId,
        name: customerName,
      }, `order-${orderId}`);          // همان شناسه در هر سه تلاش
      data = r.data;
    } catch (e) {
      // پاسخی نیامد (timeout / 524). سرور شاید کارش را تمام کرده باشد،
      // پس با همان شناسه دوباره می‌پرسیم — پول دوباره کم نمی‌شود.
      await sleep(8000);
      continue;
    }

    // درخواست قبلی هنوز در حال انجام است: صبر کن و دوباره بپرس.
    if (data.error === "request_in_flight") {
      await sleep(8000);
      continue;
    }

    // پاسخ قطعی گرفتیم (موفق یا ناموفق).
    if (data.ok) return { ok: true, link: data.services[0].subscription_url };
    return { ok: false, error: data.message };
  }

  return { ok: false, error: "پاسخی از سرور نگرفتیم. چند دقیقه بعد وضعیت سفارش را چک کن." };
}

// ---------- استفاده ----------
const res = await sellService(1001, 3, "ali-mobile");
console.log(res.ok ? "لینک اشتراک مشتری:\n" + res.link : "خطا: " + res.error);
```

> اگر بعد از ۳ تلاش هم جواب نگرفتی، سفارش را دوباره نساز.
> با `GET /orders` یا `GET /services` ببین ساخته شده یا نه.

---

## ۸. امنیت

- کلید = **دسترسی به کیف پول تو**. هرکس آن را داشته باشد می‌تواند از موجودی‌ات سرویس بسازد.
- کلید را **فقط روی سرور خودت** نگه دار. هرگز داخل اپ موبایل، کد جاوااسکریپت مرورگر یا مخزن گیت عمومی نگذار — به‌راحتی بیرون کشیده می‌شود.
- کلید را در فایل تنظیمات یا متغیر محیطی بگذار، نه وسط کد.
- اگر کلید لو رفت: همان لحظه از داخل ربات **لغوش کن** و یکی جدید بساز.
- همیشه از **HTTPS** استفاده کن.
- اگر سرورت IP ثابت دارد، از ادمین بخواه کلید را به همان IP قفل کند.
- برای بخش‌هایی که فقط گزارش می‌گیرند، کلید `read` بگیر.
