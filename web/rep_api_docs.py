"""The Persian reference page served at ``/api/rep/docs``.

Kept apart from ``web/rep_api.py`` so the routes stay readable: this file is one
long template and nothing else. It is filled with ``.replace()`` rather than an
f-string because the page is mostly JSON examples — every ``{`` in them would
otherwise have to be doubled, and one missed brace silently corrupts a sample a
representative is going to copy verbatim.

Whoever changes a route MUST change the matching block here and in
``docs/REP_API.md``. A partner API whose docs lie is worse than one with no docs.
"""
from __future__ import annotations

_PAGE = r"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>مستندات API نمایندگان — __BRAND__</title>
<style>
  :root{
    --bg:#f6f7fb; --card:#fff; --ink:#12172b; --muted:#5b6480; --line:#e3e7f0;
    --brand:#3b5bfd; --brand-soft:#eef2ff; --code:#0f1424; --code-ink:#e6ebff;
    --ok:#0f9d58; --warn:#e8a33d; --danger:#e04b4b;
  }
  @media (prefers-color-scheme: dark){
    :root{ --bg:#0d1019; --card:#151a28; --ink:#eaeefb; --muted:#96a0bd; --line:#242c42;
           --brand:#7d92ff; --brand-soft:#1b2440; --code:#0a0e1a; --code-ink:#dfe6ff; }
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:15px/1.9 "Vazirmatn","Segoe UI",Tahoma,system-ui,sans-serif}
  a{color:var(--brand);text-decoration:none} a:hover{text-decoration:underline}
  .wrap{max-width:1060px;margin:0 auto;padding:24px 18px 80px}
  header.hero{background:linear-gradient(135deg,var(--brand),#8b5cf6);color:#fff;
       border-radius:20px;padding:30px 26px;margin-bottom:22px}
  header.hero h1{margin:0 0 8px;font-size:26px}
  header.hero p{margin:0;opacity:.94}
  .base{display:inline-block;margin-top:14px;background:rgba(255,255,255,.18);
       border:1px solid rgba(255,255,255,.35);border-radius:10px;padding:7px 12px;
       font-family:ui-monospace,Menlo,Consolas,monospace;direction:ltr}
  nav.toc{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 18px;margin-bottom:22px}
  nav.toc b{display:block;margin-bottom:8px}
  nav.toc a{display:inline-block;margin:3px 0 3px 14px;font-size:14px}
  section{background:var(--card);border:1px solid var(--line);border-radius:16px;
       padding:20px 22px;margin-bottom:18px}
  h2{margin:0 0 12px;font-size:20px;border-inline-start:4px solid var(--brand);padding-inline-start:10px}
  h3{margin:22px 0 8px;font-size:16px}
  p,li{color:var(--ink)} .muted{color:var(--muted)}
  code{background:var(--brand-soft);color:var(--brand);border-radius:6px;padding:1px 6px;
       font-family:ui-monospace,Menlo,Consolas,monospace;direction:ltr;display:inline-block}
  pre{background:var(--code);color:var(--code-ink);border-radius:12px;padding:14px 16px;
      overflow-x:auto;direction:ltr;text-align:left;font-size:13.5px;line-height:1.7}
  pre code{background:none;color:inherit;padding:0}
  table{width:100%;border-collapse:collapse;margin:10px 0;font-size:14px}
  th,td{border:1px solid var(--line);padding:8px 10px;text-align:right;vertical-align:top}
  th{background:var(--brand-soft)}
  td.ltr,th.ltr{direction:ltr;text-align:left;font-family:ui-monospace,Menlo,Consolas,monospace}
  .ep{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:26px 0 8px;
      padding-top:16px;border-top:1px dashed var(--line)}
  .ep:first-of-type{border-top:0;padding-top:0;margin-top:8px}
  .m{font:600 12px/1 ui-monospace,monospace;padding:5px 9px;border-radius:6px;color:#fff}
  .m.get{background:#0f9d58} .m.post{background:#3b5bfd}
  .path{font-family:ui-monospace,Menlo,Consolas,monospace;direction:ltr;font-size:14.5px}
  .note{background:var(--brand-soft);border-inline-start:4px solid var(--brand);
        border-radius:0 10px 10px 0;padding:10px 14px;margin:12px 0}
  .warn{background:rgba(232,163,61,.14);border-inline-start:4px solid var(--warn);
        border-radius:0 10px 10px 0;padding:10px 14px;margin:12px 0}
  .danger{background:rgba(224,75,75,.13);border-inline-start:4px solid var(--danger);
        border-radius:0 10px 10px 0;padding:10px 14px;margin:12px 0}
  footer{text-align:center;color:var(--muted);font-size:13px;margin-top:30px}
</style>
</head>
<body>
<div class="wrap">

<header class="hero">
  <h1>🔌 API نمایندگان — __BRAND__</h1>
  <p>با این API می‌توانی ربات یا پنل خودت را به سامانه‌ی ما وصل کنی و خودکار سرویس بسازی، تمدید کنی و مدیریت کنی.</p>
  <div class="base">Base URL: __BASE__/api/rep/v1</div>
</header>

<nav class="toc">
  <b>فهرست</b>
  <a href="#start">شروع سریع</a>
  <a href="#auth">احراز هویت</a>
  <a href="#rules">قواعد عمومی</a>
  <a href="#idem">جلوگیری از خرید تکراری</a>
  <a href="#errors">خطاها</a>
  <a href="#endpoints">لیست Endpointها</a>
  <a href="#samples">نمونه کد</a>
  <a href="#security">امنیت</a>
</nav>

<section id="start">
  <h2>شروع سریع</h2>
  <ol>
    <li>در ربات ما وارد <b>پنل نمایندگی</b> شو.</li>
    <li>روی <b>«🔌 اتصال ربات (API)»</b> بزن و یک کلید بساز.</li>
    <li>کلید <b>فقط یک بار</b> نمایش داده می‌شود؛ همان‌جا ذخیره‌اش کن.</li>
    <li>تست کن:</li>
  </ol>
<pre><code>curl -H "Authorization: Bearer atlas_rep_XXXX" \
     __BASE__/api/rep/v1/ping</code></pre>
  <p class="muted">پاسخ موفق: <code>{"ok":true,"api_version":"1.0",...}</code></p>
  <div class="note">هزینه‌ی هر سرویسی که از طریق API می‌سازی، از <b>کیف پول نمایندگی تو</b> کم می‌شود؛ پس کیف پول را شارژ نگه دار.</div>
</section>

<section id="auth">
  <h2>احراز هویت</h2>
  <p>کلید را در هدر بفرست:</p>
<pre><code>Authorization: Bearer atlas_rep_XXXXXXXXXXXXXXXXXXXX</code></pre>
  <p>یا (معادل آن):</p>
<pre><code>X-API-Key: atlas_rep_XXXXXXXXXXXXXXXXXXXX</code></pre>
  <table>
    <tr><th>موضوع</th><th>توضیح</th></tr>
    <tr><td>Scope</td><td><code>read</code> فقط خواندن، <code>write</code> ساخت و تغییر. کلید پیش‌فرض هر دو را دارد.</td></tr>
    <tr><td>محدودیت IP</td><td>اختیاری. اگر برای کلیدت IP ثبت شده باشد، فقط از همان IPها کار می‌کند.</td></tr>
    <tr><td>لغو کلید</td><td>هر زمان از داخل ربات. اگر نمایندگی‌ات لغو یا حسابت مسدود شود، همه‌ی کلیدها بلافاصله از کار می‌افتند.</td></tr>
    <tr><td>تعداد کلید</td><td>حداکثر ۳ کلید فعال هم‌زمان.</td></tr>
  </table>
</section>

<section id="rules">
  <h2>قواعد عمومی</h2>
  <ul>
    <li>همه‌ی درخواست‌ها و پاسخ‌ها <b>JSON</b> هستند (<code>Content-Type: application/json</code>).</li>
    <li>پاسخ موفق همیشه <code>"ok": true</code> دارد؛ پاسخ ناموفق <code>"ok": false</code> به‌همراه <code>error</code> (کد ماشینی) و <code>message</code> (متن فارسی).</li>
    <li>مبالغ همه به <b>تومان</b> و عدد صحیح‌اند.</li>
    <li>زمان‌ها <b>epoch میلی‌ثانیه</b> هستند (مثلاً <code>expires_at</code>). عدد <code>0</code> یعنی «بدون انقضا / هنوز شروع نشده».</li>
    <li><code>traffic_gb: 0</code> یعنی <b>نامحدود</b> — آن را «صفر گیگ» تفسیر نکن.</li>
    <li>محدودیت نرخ: به‌صورت پیش‌فرض <b>۱۲۰ درخواست در دقیقه</b> برای هر کلید. هدرهای <code>X-RateLimit-Limit</code>، <code>X-RateLimit-Remaining</code> و <code>X-RateLimit-Reset</code> در هر پاسخ برمی‌گردند.</li>
  </ul>
</section>

<section id="idem">
  <h2>جلوگیری از خرید تکراری (Idempotency)</h2>
  <p>اگر درخواست ساخت یا تمدید به‌خاطر قطعی شبکه timeout شد، <b>دوباره فرستادن آن نباید دو بار پول کم کند</b>. برای این کار روی درخواست‌های <code>POST /services</code> و <code>POST /services/{id}/renew</code> این هدر را بفرست:</p>
<pre><code>Idempotency-Key: order-4471-attempt-1</code></pre>
  <ul>
    <li>اگر همان کلید با <b>همان بدنه</b> دوباره بیاید، پاسخ اولیه عیناً برگردانده می‌شود (<code>idempotent_replay: true</code>) و پول دوباره کم نمی‌شود.</li>
    <li>اگر همان کلید با <b>بدنه‌ی متفاوت</b> بیاید → خطای <code>409 idempotency_conflict</code>.</li>
    <li>اگر درخواست قبلی هنوز در حال پردازش باشد → <code>409 request_in_flight</code>؛ چند ثانیه بعد دوباره امتحان کن.</li>
    <li>کلیدها ۲۴ ساعت نگه داشته می‌شوند. برای هر خرید یک کلید یکتا بساز.</li>
  </ul>
  <div class="warn">توصیه‌ی جدی: برای هر سفارش مشتری در ربات خودت یک شناسه‌ی یکتا بساز و همان را به‌عنوان <code>Idempotency-Key</code> بفرست.</div>
</section>

<section id="errors">
  <h2>خطاها</h2>
  <table>
    <tr><th class="ltr">error</th><th>HTTP</th><th>معنی</th></tr>
    <tr><td class="ltr">missing_key</td><td>401</td><td>هدر کلید فرستاده نشده.</td></tr>
    <tr><td class="ltr">invalid_key</td><td>401</td><td>کلید اشتباه یا لغو شده.</td></tr>
    <tr><td class="ltr">not_a_representative</td><td>403</td><td>حساب دیگر نماینده نیست.</td></tr>
    <tr><td class="ltr">account_blocked</td><td>403</td><td>حساب مسدود است.</td></tr>
    <tr><td class="ltr">ip_not_allowed</td><td>403</td><td>IP در لیست مجاز کلید نیست.</td></tr>
    <tr><td class="ltr">insufficient_scope</td><td>403</td><td>کلید دسترسی نوشتن ندارد.</td></tr>
    <tr><td class="ltr">topup_required</td><td>403</td><td>حداقل شارژ اولیه‌ی نمایندگی انجام نشده.</td></tr>
    <tr><td class="ltr">rate_limited</td><td>429</td><td>تعداد درخواست بیش از حد. <code>Retry-After</code> را ببین.</td></tr>
    <tr><td class="ltr">invalid_request</td><td>400</td><td>پارامترها ناقص یا نامعتبر.</td></tr>
    <tr><td class="ltr">package_unavailable</td><td>400</td><td>پکیج وجود ندارد یا غیرفعال است.</td></tr>
    <tr><td class="ltr">custom_pricing_unavailable</td><td>400</td><td>تعرفه‌ی اختصاصی برای حجم دلخواه تنظیم نشده؛ از <code>package_id</code> استفاده کن.</td></tr>
    <tr><td class="ltr">insufficient_balance</td><td>402</td><td>موجودی کیف پول کافی نیست.</td></tr>
    <tr><td class="ltr">service_not_found</td><td>404</td><td>سرویس پیدا نشد یا مال تو نیست.</td></tr>
    <tr><td class="ltr">provisioning_failed</td><td>502</td><td>ساخت روی سرورها ناموفق بود؛ <b>مبلغ برگشت خورد</b>.</td></tr>
    <tr><td class="ltr">renew_failed</td><td>502</td><td>تمدید ناموفق بود؛ <b>مبلغ برگشت خورد</b>.</td></tr>
    <tr><td class="ltr">trial_disabled / trial_limit_reached</td><td>403 / 429</td><td>تست غیرفعال است یا سهمیه‌ی امروز پر شده.</td></tr>
    <tr><td class="ltr">api_disabled</td><td>503</td><td>API موقتاً توسط ادمین خاموش شده.</td></tr>
  </table>
</section>

<section id="endpoints">
  <h2>لیست Endpointها</h2>
  <p class="muted">همه‌ی آدرس‌ها با <code>__BASE__/api/rep/v1</code> شروع می‌شوند.</p>

  <div class="ep"><span class="m get">GET</span><span class="path">/ping</span></div>
  <p>تست سلامت کلید.</p>

  <div class="ep"><span class="m get">GET</span><span class="path">/me</span></div>
  <p>اطلاعات حساب: موجودی، برند، تعرفه‌ها، سهمیه‌ی تست، آمار فروش.</p>
<pre><code>{
  "ok": true,
  "representative": { "id": 12, "brand_name": "MyVPN", "balance": 4200000 },
  "pricing": { "price_per_gb": 3500, "unlimited_price": 180000, "discount_percent": 0 },
  "stats": { "total_services": 380, "active_services": 291, "total_spent": 62150000 },
  "limits": { "max_batch": 10, "rate_per_min": 120, "trial_daily_limit": 5, "trial_used_today": 1 }
}</code></pre>

  <div class="ep"><span class="m get">GET</span><span class="path">/packages</span></div>
  <p>پکیج‌های قابل فروش، با <b>قیمت نمایندگی خودت</b>.</p>
<pre><code>{
  "ok": true,
  "packages": [
    { "id": 3, "name": "۳۰ گیگ یک‌ماهه", "traffic_gb": 30, "duration_days": 30,
      "unlimited": false, "price": 105000, "list_price": 180000 }
  ]
}</code></pre>

  <div class="ep"><span class="m post">POST</span><span class="path">/services</span></div>
  <p>ساخت سرویس برای مشتری و کسر هزینه از کیف پول.</p>
  <table>
    <tr><th>فیلد</th><th>نوع</th><th>توضیح</th></tr>
    <tr><td class="ltr">package_id</td><td>int</td><td>حالت اول: خرید بر اساس پکیج.</td></tr>
    <tr><td class="ltr">traffic_gb</td><td>number</td><td>حالت دوم: حجم دلخواه. <code>0</code> = نامحدود.</td></tr>
    <tr><td class="ltr">duration_days</td><td>int</td><td>همراه حالت دوم، الزامی.</td></tr>
    <tr><td class="ltr">name</td><td>string</td><td>نام نمایشی سرویس (اختیاری).</td></tr>
    <tr><td class="ltr">names</td><td>string[]</td><td>نام مجزا برای هر سرویس در خرید گروهی.</td></tr>
    <tr><td class="ltr">count</td><td>int</td><td>تعداد (۱ تا ۱۰، پیش‌فرض ۱).</td></tr>
    <tr><td class="ltr">note</td><td>string</td><td>یادداشت داخلی روی سفارش.</td></tr>
  </table>
<pre><code>POST /api/rep/v1/services
Idempotency-Key: cust-8891

{ "package_id": 3, "name": "ali-mobile", "count": 2 }

→ 201
{
  "ok": true, "order_id": 9134, "requested": 2, "created": 2,
  "charged": 210000, "refunded": 0, "balance": 3990000,
  "services": [
    { "id": 4471, "name": "ali-mobile-1", "status": "pending", "unlimited": false,
      "traffic_gb": 30, "used_bytes": 0, "expires_at": 0, "days_left": null,
      "starts_on_first_use": true,
      "subscription_url": "__BASE__/sub/AbCdEf..." }
  ]
}</code></pre>
  <div class="note">اگر بخشی از سرویس‌ها ساخته نشود، کد <code>207</code> برمی‌گردد، <code>partial: true</code> ست می‌شود و <b>پول سرویس‌های ساخته‌نشده همان لحظه برگشت می‌خورد</b> (<code>refunded</code>).</div>
  <p class="muted"><code>status</code> می‌تواند باشد: <code>active</code> (فعال)، <code>pending</code> (ساخته شده، هنوز اولین اتصال انجام نشده و زمان شروع نشده)، <code>disabled</code>، <code>expired</code>، <code>depleted</code> (حجم تمام شده).</p>

  <div class="ep"><span class="m get">GET</span><span class="path">/services</span></div>
  <p>لیست سرویس‌ها. پارامترها: <code>page</code>، <code>per_page</code> (حداکثر ۱۰۰)، <code>q</code> (جستجو در نام)،
     <code>sort</code> = <code>newest|oldest|name_az|expiry_soon|usage_desc</code>،
     <code>filter</code> = <code>all|active|inactive|expired|expiring|near_limit|unlimited</code>.</p>
<pre><code>GET /api/rep/v1/services?filter=expiring&sort=expiry_soon&per_page=50

{ "ok": true, "services": [ ... ],
  "pagination": { "page": 1, "per_page": 50, "total": 128, "pages": 3 } }</code></pre>

  <div class="ep"><span class="m get">GET</span><span class="path">/services/{id}</span></div>
  <p>جزئیات یک سرویس + لینک تک‌تک سرورها (<code>nodes</code>) برای وقتی مشتری فقط یک کانفیگ می‌خواهد.</p>

  <div class="ep"><span class="m post">POST</span><span class="path">/services/{id}/renew</span></div>
  <p>تمدید. بدنه دقیقاً مثل ساخت است (<code>package_id</code> یا <code>traffic_gb</code>+<code>duration_days</code>).</p>
<pre><code>{ "package_id": 3 }

→ { "ok": true, "order_id": 9140, "charged": 105000, "balance": 3885000,
    "nodes_renewed": 6, "carried_over": true, "service": { ... } }</code></pre>
  <p class="muted"><code>carried_over: true</code> یعنی سرویس هنوز حجم و زمان داشت و باقی‌مانده‌اش به بسته‌ی جدید اضافه شد.</p>

  <div class="ep"><span class="m post">POST</span><span class="path">/services/{id}/rename</span></div>
<pre><code>{ "name": "ali-laptop" }</code></pre>

  <div class="ep"><span class="m post">POST</span><span class="path">/services/{id}/disable</span> · <span class="path">/services/{id}/enable</span></div>
  <p>قطع/وصل سرویس روی <b>همه‌ی سرورها</b>. برگشت‌پذیر است و پولی برنمی‌گردد. بدنه لازم ندارد.</p>

  <div class="ep"><span class="m post">POST</span><span class="path">/services/{id}/revoke</span></div>
  <p>وقتی مشتری لینکش را با دیگران به اشتراک گذاشته: لینک قدیمی <b>کاملاً</b> از کار می‌افتد و لینک جدید می‌گیری. حجم، انقضا و مصرف حفظ می‌شود (این تمدید نیست). فقط روی سرویس <b>فعال</b> کار می‌کند.</p>
<pre><code>→ { "ok": true, "subscription_url": "__BASE__/sub/NEW...", "rotated_nodes": 6, "failed_nodes": 0 }</code></pre>

  <div class="ep"><span class="m post">POST</span><span class="path">/services/{id}/delete</span></div>
  <p>حذف دائمی از همه‌ی سرورها.</p>
<pre><code>{ "confirm": true }</code></pre>
  <div class="danger"><b>برگشت‌ناپذیر است و هیچ مبلغی برنمی‌گردد.</b> بدون <code>confirm: true</code> رد می‌شود. برای قطع موقت از <code>/disable</code> استفاده کن.</div>

  <div class="ep"><span class="m post">POST</span><span class="path">/services/trial</span></div>
  <p>ساخت اکانت تست رایگان از سهمیه‌ی روزانه‌ی نمایندگی (اگر ادمین فعال کرده باشد).</p>
<pre><code>{ "name": "test-ali" }

→ { "ok": true, "trial_used_today": 2, "trial_daily_limit": 5, "service": { ... } }</code></pre>

  <div class="ep"><span class="m get">GET</span><span class="path">/wallet</span></div>
  <p>موجودی و آخرین تراکنش‌ها. پارامتر <code>limit</code> (پیش‌فرض ۲۰).</p>

  <div class="ep"><span class="m get">GET</span><span class="path">/orders</span></div>
  <p>سفارش‌های اخیر — سند حسابداری هر کسر از کیف پول. پارامتر <code>limit</code> (پیش‌فرض ۲۵).</p>
</section>

<section id="samples">
  <h2>نمونه کد</h2>

  <h3>cURL — ساخت یک سرویس</h3>
<pre><code>curl -X POST __BASE__/api/rep/v1/services \
  -H "Authorization: Bearer $ATLAS_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: order-1001" \
  -d '{"package_id": 3, "name": "ali", "count": 1}'</code></pre>

  <h3>Python (httpx) — کلاس آماده</h3>
<pre><code>import httpx, uuid

BASE = "__BASE__/api/rep/v1"

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
        r = await self.c.post(f"/services/{service_id}/renew",
                              json={"package_id": package_id},
                              headers={"Idempotency-Key": str(uuid.uuid4())})
        return r.json()</code></pre>

  <h3>Node.js (fetch)</h3>
<pre><code>const BASE = "__BASE__/api/rep/v1";

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
}</code></pre>

  <div class="note"><b>Timeout را کوتاه نگذار.</b> ساخت هر سرویس روی همه‌ی سرورها انجام می‌شود و ممکن است تا یک دقیقه طول بکشد. مقدار پیشنهادی: ۱۲۰ ثانیه، به‌همراه <code>Idempotency-Key</code> برای تلاش مجدد امن.</div>
</section>

<section id="security">
  <h2>امنیت — این‌ها را رعایت کن</h2>
  <ul>
    <li>کلید را <b>فقط روی سرور خودت</b> نگه دار. هرگز داخل اپلیکیشن موبایل، جاوااسکریپت مرورگر یا مخزن گیت عمومی نگذار — قابل استخراج است.</li>
    <li>کلید = دسترسی به کیف پول تو. هرکس آن را داشته باشد می‌تواند سرویس بسازد و پولت را خرج کند.</li>
    <li>اگر کلید لو رفت، همان لحظه از ربات <b>لغوش کن</b> و یکی جدید بساز.</li>
    <li>حتماً از <b>HTTPS</b> استفاده کن.</li>
    <li>اگر سرورت IP ثابت دارد، از ادمین بخواه کلیدت را به همان IP محدود کند.</li>
    <li>برای ربات‌هایی که فقط گزارش می‌گیرند، کلید با دسترسی <code>read</code> بگیر.</li>
  </ul>
</section>

<footer>__BRAND__ · API نمایندگان نسخه ۱٫۰</footer>
</div>
</body>
</html>
"""


def docs_html(base_url: str, brand: str) -> str:
    """Render the reference page for this installation.

    ``base_url`` is whatever the owner published as ``public_base_url`` — the
    same host that serves ``/sub/{token}`` — so every example on the page is
    copy-pasteable rather than a placeholder the reader has to substitute.
    """
    base = (base_url or "").rstrip("/") or "https://your-domain.com"
    safe_brand = (brand or "Atlas").replace("<", "&lt;").replace(">", "&gt;")[:60]
    return _PAGE.replace("__BASE__", base.replace("<", "&lt;")).replace("__BRAND__", safe_brand)
