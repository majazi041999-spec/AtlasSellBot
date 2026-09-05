"""The Persian reference page served at ``/api/rep/docs``.

Kept apart from ``web/rep_api.py`` so the routes stay readable: this file is one
long template and nothing else. It is filled with ``.replace()`` rather than an
f-string because the page is mostly JSON and code samples — every ``{`` in them
would otherwise have to be doubled, and one missed brace silently corrupts a
sample a representative is going to copy verbatim.

Shape of the page, and why: every language (PHP / Python / Node.js) defines ONE
helper called ``atlas(...)`` up front, and every endpoint below is then a single
line calling it. A reseller does not want fifteen self-contained programs — they
want one function they paste once and fifteen one-liners they can read at a
glance. The language tabs swap all samples at once and remember the choice.

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
    --bg:#f5f7fb; --card:#fff; --ink:#141a2e; --muted:#606b88; --line:#e2e7f1;
    --brand:#3b5bfd; --soft:#eef2ff; --code:#0e1322; --codeInk:#e7ecff;
    --ok:#0f9d58; --warn:#c47d12; --warnBg:#fff6e6; --danger:#d94141; --dangerBg:#fdeded;
  }
  @media (prefers-color-scheme: dark){
    :root{ --bg:#0c0f18; --card:#141926; --ink:#e9edfa; --muted:#98a2c0; --line:#232b40;
           --brand:#8098ff; --soft:#1a2340; --code:#080c16; --codeInk:#dee6ff;
           --warn:#e0a740; --warnBg:#2a2313; --danger:#ff8080; --dangerBg:#2c1717; }
  }
  *{box-sizing:border-box}
  html{scroll-behavior:smooth; scroll-padding-top:110px}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:15px/1.95 "Vazirmatn","Segoe UI",Tahoma,system-ui,sans-serif}
  a{color:var(--brand);text-decoration:none}
  a:hover{text-decoration:underline}
  .wrap{max-width:960px;margin:0 auto;padding:0 16px 90px}

  /* ── sticky bar: nav + the language switch ─────────────────────────────── */
  .bar{position:sticky;top:0;z-index:20;background:var(--bg);
       border-bottom:1px solid var(--line);padding:10px 0;margin-bottom:22px}
  .bar .inner{max-width:960px;margin:0 auto;padding:0 16px;
       display:flex;gap:12px;align-items:center;flex-wrap:wrap;justify-content:space-between}
  .navlinks{display:flex;gap:4px;flex-wrap:wrap}
  .navlinks a{font-size:13.5px;color:var(--muted);padding:4px 8px;border-radius:8px}
  .navlinks a:hover{background:var(--soft);color:var(--brand);text-decoration:none}
  .langbar{display:flex;gap:6px;background:var(--soft);padding:4px;border-radius:11px}
  .langbar button{border:0;background:none;color:var(--muted);cursor:pointer;
       font:600 13px/1 inherit;padding:8px 14px;border-radius:8px}
  .langbar button.on{background:var(--brand);color:#fff}

  header.hero{background:linear-gradient(135deg,var(--brand),#8b5cf6);color:#fff;
       border-radius:20px;padding:28px 24px;margin-bottom:20px}
  header.hero h1{margin:0 0 6px;font-size:25px}
  header.hero p{margin:0;opacity:.93}
  .base{display:inline-block;margin-top:14px;background:rgba(255,255,255,.16);
       border:1px solid rgba(255,255,255,.3);border-radius:10px;padding:7px 12px;
       font-family:ui-monospace,Menlo,Consolas,monospace;direction:ltr;font-size:13.5px}

  section{background:var(--card);border:1px solid var(--line);border-radius:16px;
       padding:20px 22px;margin-bottom:16px}
  h2{margin:0 0 14px;font-size:19px;border-inline-start:4px solid var(--brand);padding-inline-start:10px}
  h3{margin:24px 0 8px;font-size:16px}
  h3:first-of-type{margin-top:6px}
  .muted{color:var(--muted)}
  ol,ul{padding-inline-start:22px}
  code{background:var(--soft);color:var(--brand);border-radius:6px;padding:1px 6px;
       font-family:ui-monospace,Menlo,Consolas,monospace;direction:ltr;display:inline-block}

  /* ── code blocks ───────────────────────────────────────────────────────── */
  .snip{position:relative;margin:10px 0}
  pre{background:var(--code);color:var(--codeInk);border-radius:12px;padding:15px 16px;
      margin:10px 0;overflow-x:auto;direction:ltr;text-align:left;
      font:13.5px/1.75 ui-monospace,Menlo,Consolas,monospace}
  pre code{background:none;color:inherit;padding:0;display:block}
  pre.res{background:var(--soft);color:var(--ink);border:1px solid var(--line)}
  /* Physical `right`, not `inset-inline-*`: in RTL the logical end flips to the
     left, which is exactly where the LTR code starts. See PROJECT_MAP §13. */
  .copy{position:absolute;top:18px;right:10px;z-index:2;
        border:0;border-radius:7px;background:rgba(255,255,255,.13);color:#cdd6f5;
        cursor:pointer;font:600 11px/1 inherit;padding:6px 9px}
  .copy:hover{background:rgba(255,255,255,.26)}
  .copy.done{background:var(--ok);color:#fff}
  body[data-lang="php"]    .snip>pre[data-l]:not([data-l="php"]),
  body[data-lang="python"] .snip>pre[data-l]:not([data-l="python"]),
  body[data-lang="node"]   .snip>pre[data-l]:not([data-l="node"]){display:none}

  table{width:100%;border-collapse:collapse;margin:10px 0;font-size:14px}
  th,td{border:1px solid var(--line);padding:8px 10px;text-align:right;vertical-align:top}
  th{background:var(--soft);font-weight:600}
  /* `anywhere` so a long error code cannot push the table wider than a phone
     screen — the page itself must never scroll sideways. */
  td.ltr,th.ltr{direction:ltr;text-align:left;font-family:ui-monospace,Menlo,Consolas,monospace;
       font-size:13px;overflow-wrap:anywhere}

  .ep{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:30px 0 6px;
      padding-top:18px;border-top:1px dashed var(--line)}
  .ep:first-of-type{border-top:0;padding-top:0;margin-top:4px}
  .m{font:700 11.5px/1 ui-monospace,monospace;padding:6px 9px;border-radius:6px;color:#fff}
  .m.get{background:#0f9d58} .m.post{background:#3b5bfd}
  .path{font-family:ui-monospace,Menlo,Consolas,monospace;direction:ltr;font-size:14.5px;font-weight:600}

  .note,.warn,.danger{border-radius:0 10px 10px 0;padding:11px 14px;margin:12px 0}
  .note{background:var(--soft);border-inline-start:4px solid var(--brand)}
  .warn{background:var(--warnBg);border-inline-start:4px solid var(--warn)}
  .danger{background:var(--dangerBg);border-inline-start:4px solid var(--danger)}
  footer{text-align:center;color:var(--muted);font-size:13px;margin-top:26px}
  @media (max-width:640px){ .navlinks{display:none} .bar .inner{justify-content:center} }
</style>
</head>
<body data-lang="php">

<div class="bar"><div class="inner">
  <nav class="navlinks">
    <a href="#start">شروع</a>
    <a href="#auth">کلید</a>
    <a href="#rules">قواعد</a>
    <a href="#sandbox">محیط تست</a>
    <a href="#idem">خرید تکراری</a>
    <a href="#endpoints">دستورها</a>
    <a href="#errors">خطاها</a>
    <a href="#full">مثال کامل</a>
    <a href="#security">امنیت</a>
  </nav>
  <div class="langbar" id="langbar">
    <button data-l="php">PHP</button>
    <button data-l="python">Python</button>
    <button data-l="node">Node.js</button>
  </div>
</div></div>

<div class="wrap">

<header class="hero">
  <h1>🔌 API نمایندگان — __BRAND__</h1>
  <p>ربات یا سایت خودت را به سامانه‌ی ما وصل کن و خودکار سرویس بساز، تمدید کن و مدیریت کن.</p>
  <div class="base">__BASE__/api/rep/v1</div>
</header>

<div class="note">
  نمونه‌کدها به سه زبان هستند. زبان دلخواهت را از نوار بالا انتخاب کن؛ همه‌ی کدهای این صفحه با هم عوض می‌شوند.
</div>

<!-- ═══════════════════════ 1 ═══════════════════════ -->
<section id="start">
  <h2>۱. شروع در سه دقیقه</h2>

  <h3>الف) کلید بگیر</h3>
  <ol>
    <li>در ربات ما وارد <b>پنل نمایندگی</b> شو.</li>
    <li>روی <b>«🔌 اتصال ربات (API)»</b> بزن.</li>
    <li><b>«🔑 ساخت کلید جدید»</b> — کلید <b>فقط همان یک بار</b> نشان داده می‌شود، کپی و ذخیره‌اش کن.</li>
  </ol>

  <h3>ب) این تابع را یک بار در پروژه‌ات بگذار</h3>
  <p class="muted">همه‌ی کدهای بقیه‌ی این صفحه فقط همین تابع <code>atlas()</code> را صدا می‌زنند. یک بار کپی کن، تمام.</p>
  <div class="snip">
<pre data-l="php"><code>&lt;?php
// ---------- تنظیمات ----------
define('ATLAS_BASE', '__BASE__/api/rep/v1');
define('ATLAS_KEY',  'atlas_rep_کلید_خودت_را_اینجا_بگذار');

/**
 * یک درخواست به API می‌زند.
 * $idem فقط برای «ساخت» و «تمدید» لازم است (جلوگیری از خرید تکراری).
 * خروجی: ['status' => کد HTTP, 'data' => آرایه‌ی پاسخ]
 */
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
        CURLOPT_RETURNTRANSFER =&gt; true,
        CURLOPT_CUSTOMREQUEST  =&gt; $method,
        CURLOPT_HTTPHEADER     =&gt; $headers,
        CURLOPT_TIMEOUT        =&gt; 100,
    ]);
    if ($body !== null) {
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($body, JSON_UNESCAPED_UNICODE));
    }

    $raw    = curl_exec($ch);
    $status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    return ['status' =&gt; $status, 'data' =&gt; json_decode($raw, true)];
}</code></pre>
<pre data-l="python"><code># نصب:  pip install requests
import requests

# ---------- تنظیمات ----------
BASE = "__BASE__/api/rep/v1"
KEY  = "atlas_rep_کلید_خودت_را_اینجا_بگذار"


# یک درخواست به API می‌زند.
# idem فقط برای «ساخت» و «تمدید» لازم است (جلوگیری از خرید تکراری).
# خروجی: (کد HTTP، دیکشنری پاسخ)
def atlas(method, path, body=None, idem=None):
    headers = {"Authorization": "Bearer " + KEY}
    if idem:
        headers["Idempotency-Key"] = idem

    r = requests.request(method, BASE + path, json=body,
                         headers=headers, timeout=100)
    return r.status_code, r.json()</code></pre>
<pre data-l="node"><code>// Node.js نسخه ۱۸ به بالا (fetch داخلی دارد، نیاز به نصب چیزی نیست)

// ---------- تنظیمات ----------
const BASE = "__BASE__/api/rep/v1";
const KEY  = "atlas_rep_کلید_خودت_را_اینجا_بگذار";

/**
 * یک درخواست به API می‌زند.
 * idem فقط برای «ساخت» و «تمدید» لازم است (جلوگیری از خرید تکراری).
 * خروجی: { status: کد HTTP, data: پاسخ }
 */
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
}</code></pre>
  </div>

  <h3>ج) اولین درخواست: تست کلید</h3>
  <div class="snip">
<pre data-l="php"><code>$r = atlas('GET', '/ping');
print_r($r['data']);</code></pre>
<pre data-l="python"><code>status, data = atlas("GET", "/ping")
print(data)</code></pre>
<pre data-l="node"><code>const r = await atlas("GET", "/ping");
console.log(r.data);</code></pre>
  </div>
  <p class="muted">پاسخ:</p>
<pre class="res"><code>{ "ok": true, "api_version": "1.0", "server_time": 1756500000, "representative_id": 12 }</code></pre>
  <p>اگر <code>ok: true</code> گرفتی، همه‌چیز آماده است ✅</p>

  <div class="note">هزینه‌ی هر سرویسی که می‌سازی از <b>کیف پول نمایندگی خودت</b> کم می‌شود، با همان تعرفه‌ای که در ربات می‌بینی. پس کیف پول را شارژ نگه دار.</div>
</section>

<!-- ═══════════════════════ 2 ═══════════════════════ -->
<section id="auth">
  <h2>۲. کلید و دسترسی</h2>
  <p>کلید در هدر <code>Authorization</code> می‌رود (تابع <code>atlas()</code> این کار را برایت می‌کند):</p>
<pre><code>Authorization: Bearer atlas_rep_XXXXXXXXXXXX</code></pre>
  <table>
    <tr><th>موضوع</th><th>توضیح</th></tr>
    <tr><td>تعداد کلید</td><td>حداکثر <b>۳ کلید فعال</b> هم‌زمان برای هر نماینده.</td></tr>
    <tr><td>سطح دسترسی</td><td><code>read</code> = فقط خواندن، <code>write</code> = ساخت و تغییر. کلیدی که از ربات می‌گیری هر دو را دارد.</td></tr>
    <tr><td>محدودیت IP</td><td>اختیاری. اگر سرورت IP ثابت دارد، از پشتیبانی بخواه کلیدت را به همان IP قفل کند.</td></tr>
    <tr><td>لغو</td><td>هر زمان از داخل ربات. اگر نمایندگی‌ات لغو یا حسابت مسدود شود، <b>همه‌ی کلیدها همان لحظه از کار می‌افتند</b>.</td></tr>
    <tr><td>بازیابی</td><td><b>ممکن نیست.</b> ما فقط اثر انگشت (hash) کلید را نگه می‌داریم. گمش کردی؟ یکی جدید بساز.</td></tr>
  </table>
</section>

<!-- ═══════════════════════ 3 ═══════════════════════ -->
<section id="rules">
  <h2>۳. قواعد عمومی</h2>
  <ul>
    <li>درخواست و پاسخ همیشه <b>JSON</b> است.</li>
    <li>موفق: <code>"ok": true</code> — ناموفق: <code>"ok": false</code> به‌همراه <code>error</code> (کد انگلیسی برای برنامه) و <code>message</code> (متن فارسی برای نمایش به کاربر).</li>
    <li>مبالغ به <b>تومان</b> و عدد صحیح‌اند.</li>
    <li>زمان‌ها <b>epoch میلی‌ثانیه</b>‌اند. <code>0</code> یعنی «بدون انقضا» یا «هنوز شروع نشده».</li>
    <li><code>traffic_gb: 0</code> یعنی <b>نامحدود</b> — آن را «صفر گیگ» حساب نکن.</li>
    <li>محدودیت سرعت: <b>۱۲۰ درخواست در دقیقه</b> برای هر کلید. باقی‌مانده در هدر <code>X-RateLimit-Remaining</code> برمی‌گردد.</li>
  </ul>

  <div class="warn">
    <b>⏱ زمان پاسخ و خطای 524.</b> ساخت هر سرویس روی <b>همه‌ی سرورها</b> انجام می‌شود و می‌تواند تا حدود یک دقیقه طول بکشد.
    سایت ما پشت Cloudflare است و Cloudflare بعد از حدود <b>۱۰۰ ثانیه</b> ارتباط را می‌بندد و خطای <code>524</code> می‌دهد —
    <b>ولی سرور کارش را تمام می‌کند و سرویس ساخته می‌شود.</b> پس:
    <ul style="margin:8px 0 0">
      <li>در هر درخواست حداکثر <b>۳ تا ۵ سرویس</b> بساز (<code>count</code>)، نه ۱۰ تا.</li>
      <li>حتماً <code>Idempotency-Key</code> بفرست تا اگر مجبور شدی دوباره بفرستی، دوباره پول کم نشود (بخش بعد).</li>
    </ul>
  </div>
</section>

<!-- ═══════════════════════ 4 ═══════════════════════ -->
<section id="sandbox">
  <h2>۳.۵ محیط تست (Sandbox) — اول اینجا</h2>
  <p>
    برای نوشتن کد لازم نیست پول خرج کنی. از بخش نمایندگان در ربات، دکمه‌ی
    <b>«🧪 ساخت کلید تستی»</b> را بزن. کلیدی می‌گیری که با
    <code dir="ltr">atlas_test_</code> شروع می‌شود.
  </p>
  <p>با کلید تستی:</p>
  <ul>
    <li><b>هیچ پولی از کیف پولت کم نمی‌شود.</b></li>
    <li><b>هیچ کانفیگی روی سرورها ساخته نمی‌شود.</b> مشتری‌های واقعی اصلاً درگیر نمی‌شوند.</li>
    <li>یک کیف پول تستی با موجودی فرضی داری که <b>واقعاً کم می‌شود</b> — تا بتوانی خطای
        <code dir="ltr">insufficient_funds</code> را هم تست کنی، که در محیط واقعی به‌عمد ایجادکردنش سخت است.</li>
    <li>حجم مصرفی به‌مرور <b>بالا می‌رود</b>، پس نوار مصرف و هشدار «نزدیک اتمام» را هم می‌توانی امتحان کنی.</li>
    <li>لینک‌های ساب به دامنه‌ی <code dir="ltr">sandbox.invalid</code> اشاره می‌کنند و
        <b>عمداً هرگز کار نمی‌کنند</b> تا با لینک واقعی اشتباه نشوند.</li>
  </ul>
  <p class="ok">
    <b>مهم‌ترین نکته:</b> پاسخ‌ها دقیقاً همان شکل محیط واقعی را دارند — همان فیلدها، همان
    کدهای خطا، همان وضعیت‌ها. وقتی کدت کار کرد، <b>فقط کلید را عوض کن</b>؛ هیچ‌چیز دیگری
    را دست نزن. هر پاسخ تستی یک فیلد اضافه‌ی <code dir="ltr">"sandbox": true</code> دارد تا در
    لاگ‌هایت هم بفهمی کدام کدام است.
  </p>

  <div class="ep"><span class="m get">GET</span><span class="path">/sandbox</span></div>
  <p>این کلید تستی است یا اصلی؟ اولین چیزی که باید بپرسی.</p>
  <div class="snip">
<pre data-l="php"><code>$r = atlas('GET', '/sandbox');
if ($r['data']['sandbox']) { echo "حالت تست — پولی کم نمی‌شود\n"; }</code></pre>
<pre data-l="python"><code>status, data = atlas("GET", "/sandbox")
if data["sandbox"]:
    print("حالت تست — پولی کم نمی‌شود")</code></pre>
<pre data-l="node"><code>const r = await atlas("GET", "/sandbox");
if (r.data.sandbox) console.log("حالت تست — پولی کم نمی‌شود");</code></pre>
  </div>
<pre class="res"><code>{
  "ok": true,
  "sandbox": true,
  "wallet": 50000000,
  "notes": ["این کلید تستی است. هیچ پولی کم نمی‌شود و هیچ کانفیگی روی سرورها ساخته نمی‌شود.", "..."]
}</code></pre>

  <div class="ep"><span class="m post">POST</span><span class="path">/sandbox/reset</span></div>
  <p>
    همه‌ی سرویس‌های تستی را پاک می‌کند و کیف پول تستی را دوباره پر می‌کند. جای خوبی است
    برای صداکردن در ابتدای تست‌های خودکارت، تا هر بار از صفر شروع کنی.
    با کلید اصلی کار نمی‌کند و خطای <code dir="ltr">403</code> می‌دهد.
  </p>
  <div class="snip">
<pre data-l="php"><code>atlas('POST', '/sandbox/reset');</code></pre>
<pre data-l="python"><code>atlas("POST", "/sandbox/reset")</code></pre>
<pre data-l="node"><code>await atlas("POST", "/sandbox/reset");</code></pre>
  </div>
</section>

<section id="idem">
  <h2>۴. جلوگیری از خرید تکراری (مهم‌ترین بخش)</h2>
  <p>هر بار که «ساخت» یا «تمدید» می‌زنی، یک <b>شناسه‌ی یکتا</b> هم بفرست — مثلاً شماره‌ی سفارش مشتری در ربات خودت:</p>
  <div class="snip">
<pre data-l="php"><code>$r = atlas('POST', '/services', ['package_id' =&gt; 3], 'order-1001');
//                                                     ↑ شناسه‌ی یکتای همین سفارش</code></pre>
<pre data-l="python"><code>status, data = atlas("POST", "/services", {"package_id": 3}, "order-1001")
#                                                             ↑ شناسه‌ی یکتای همین سفارش</code></pre>
<pre data-l="node"><code>const r = await atlas("POST", "/services", { package_id: 3 }, "order-1001");
//                                                             ↑ شناسه‌ی یکتای همین سفارش</code></pre>
  </div>

  <table>
    <tr><th>اگر…</th><th>نتیجه</th></tr>
    <tr><td>همان شناسه + همان درخواست را دوباره بفرستی</td><td>پاسخ دفعه‌ی اول عیناً برمی‌گردد (<code>idempotent_replay: true</code>). <b>پول دوباره کم نمی‌شود.</b></td></tr>
    <tr><td>درخواست قبلی هنوز در حال انجام باشد</td><td><code>409 request_in_flight</code> — چند ثانیه صبر کن و دوباره بپرس</td></tr>
    <tr><td>همان شناسه ولی درخواست متفاوت</td><td><code>409 idempotency_conflict</code> — برای سفارش جدید شناسه‌ی جدید بساز</td></tr>
  </table>

  <div class="note">
    <b>دستور کار وقتی timeout یا 524 گرفتی:</b> نترس و سفارش را دوباره از صفر نساز.
    همان درخواست را با <b>همان شناسه</b> بفرست. اگر <code>409 request_in_flight</code> گرفتی،
    ۵ ثانیه صبر کن و دوباره بفرست تا پاسخ واقعی را بگیری. هرگز دو بار پول کم نمی‌شود.
    (کد آماده‌اش در <a href="#full">بخش ۷</a> هست.)
  </div>
  <p class="muted">شناسه‌ها ۲۴ ساعت نگه داشته می‌شوند.</p>
</section>

<!-- ═══════════════════════ 5 ═══════════════════════ -->
<section id="endpoints">
  <h2>۵. دستورها</h2>

  <div class="ep"><span class="m get">GET</span><span class="path">/me</span></div>
  <p>موجودی، برند، تعرفه‌ها و آمار تو.</p>
  <div class="snip">
<pre data-l="php"><code>$r = atlas('GET', '/me');
echo $r['data']['representative']['balance'];   // موجودی به تومان</code></pre>
<pre data-l="python"><code>status, data = atlas("GET", "/me")
print(data["representative"]["balance"])   # موجودی به تومان</code></pre>
<pre data-l="node"><code>const r = await atlas("GET", "/me");
console.log(r.data.representative.balance);   // موجودی به تومان</code></pre>
  </div>
<pre class="res"><code>{
  "ok": true,
  "representative": { "id": 12, "brand_name": "MyVPN", "balance": 4200000 },
  "pricing": { "price_per_gb": 3500, "unlimited_price": 180000, "discount_percent": 0 },
  "stats": { "total_services": 380, "active_services": 291, "total_spent": 62150000 },
  "limits": { "max_batch": 10, "rate_per_min": 120, "trial_daily_limit": 5, "trial_used_today": 1 }
}</code></pre>


  <div class="ep"><span class="m get">GET</span><span class="path">/services/{id}/connections</span></div>
  <p>
    <b>همین حالا چند نفر به این سرویس وصل‌اند؟</b> ملاک، اتصال <b>هم‌زمان</b> است، نه
    تعداد آی‌پی‌هایی که در طول روز دیده شده. مشتری‌ای که با اینترنت همراه است و آی‌پی‌اش
    مدام عوض می‌شود، <b>یک</b> مکان حساب می‌شود — چون آی‌پی قبلی‌اش دیگر ترافیک ندارد و
    کنار گذاشته می‌شود. برای همین این عدد را می‌شود مبنای تصمیم گرفت.
  </p>
  <p>
    آدرس‌ها به‌صورت <b>ناقص</b> برمی‌گردند (<code dir="ltr">5.113.20.···</code>) — تعداد،
    زمان و سرور برای رسیدگی به شکایت اشتراک‌گذاری کافی است.
    اگر یکی از سرورها جواب ندهد، <code dir="ltr">partial: true</code> می‌شود و آن عدد
    <b>حداقل</b> است نه دقیق؛ در آن حالت روی آن تصمیم سخت نگیر.
  </p>
  <div class="snip">
<pre data-l="php"><code>$r = atlas('GET', '/services/1234/connections');
$d = $r['data'];
if ($d['over_limit']) {
    echo "بیش از حد مجاز: {$d['connections']} از {$d['limit']}\n";
}</code></pre>
<pre data-l="python"><code>status, data = atlas("GET", "/services/1234/connections")
if data["over_limit"]:
    print(f"بیش از حد مجاز: {data['connections']} از {data['limit']}")</code></pre>
<pre data-l="node"><code>const r = await atlas("GET", "/services/1234/connections");
if (r.data.over_limit) {
  console.log(`بیش از حد مجاز: ${r.data.connections} از ${r.data.limit}`);
}</code></pre>
  </div>
<pre class="res"><code>{
  "ok": true,
  "service_id": 1234,
  "connections": 2,
  "limit": 5,
  "over_limit": false,
  "places": [
    { "ip": "5.113.20.···", "seconds_ago": 4,   "server": "سرور هلند ۱" },
    { "ip": "91.99.4.···",  "seconds_ago": 118, "server": "سرور آلمان ۲" }
  ],
  "partial": false,
  "servers_answered": 5,
  "servers_total": 5
}</code></pre>

  <div class="ep"><span class="m get">GET</span><span class="path">/packages</span></div>
  <p>پکیج‌های قابل فروش، با <b>قیمت نمایندگی خودت</b>.</p>
  <div class="snip">
<pre data-l="php"><code>$r = atlas('GET', '/packages');
foreach ($r['data']['packages'] as $p) {
    echo $p['id'] . ' - ' . $p['name'] . ' - ' . number_format($p['price']) . " تومان\n";
}</code></pre>
<pre data-l="python"><code>status, data = atlas("GET", "/packages")
for p in data["packages"]:
    print(p["id"], p["name"], f"{p['price']:,} تومان")</code></pre>
<pre data-l="node"><code>const r = await atlas("GET", "/packages");
for (const p of r.data.packages) {
  console.log(p.id, p.name, p.price.toLocaleString() + " تومان");
}</code></pre>
  </div>
<pre class="res"><code>{
  "ok": true,
  "packages": [
    { "id": 3, "name": "۳۰ گیگ یک‌ماهه", "traffic_gb": 30, "duration_days": 30,
      "unlimited": false, "price": 105000 }
  ]
}</code></pre>
  <p class="muted"><code>price</code> = قیمت اختصاصی تو؛ همان مبلغی که از کیف پولت کم می‌شود.</p>

  <div class="ep"><span class="m get">GET</span><span class="path">/packages/table</span></div>
  <p>همان جدول تمیزی که ربات خودمان نشان می‌دهد — با <b>قیمت‌های خودت</b> و
     <b>متن‌های خودت</b>. آماده‌ی ارسال، لازم نیست چیزی بسازی.</p>

  <div class="warn">
    <b>⚠️ درباره‌ی اموجی پرمیوم — مهم</b><br>
    تلگرام اجازه‌ی استفاده از اموجی پرمیوم را فقط به رباتی می‌دهد که
    <b>روی Fragment یوزرنیم خریده</b> باشد، یا <b>مالکِ رباتش اشتراک Telegram
    Premium داشته باشد</b>. این محدودیت روی <b>رباتِ فرستنده</b> است، نه روی
    خودِ اموجی — پس اگر مالکِ ربات تو پرمیوم نیست، هرچقدر هم آیدی‌ها درست
    باشند، تلگرام آن‌ها را حذف می‌کند.<br><br>
    برای همین هر دو نسخه همیشه برمی‌گردد: یکی بار بفرست، ببین کدام درست
    نمایش داده می‌شود، و همان را استفاده کن. <b>جدول در هر دو حالت دقیقاً
    یکی است</b> — فقط اموجی‌ها فرق می‌کنند.
  </div>

  <table>
    <tr><th>پارامتر</th><th>پیش‌فرض</th><th>توضیح</th></tr>
    <tr><td class="ltr">premium</td><td class="ltr">0</td>
        <td><code>1</code> = فیلد <code>html</code> با اموجی پرمیوم ساخته شود</td></tr>
    <tr><td class="ltr">title</td><td>🛒 پکیج‌ها و قیمت‌ها</td><td>تیتر بالای جدول</td></tr>
    <tr><td class="ltr">intro</td><td>—</td><td>یک خط توضیح، بالای جدول</td></tr>
    <tr><td class="ltr">note</td><td>—</td><td>یک خط، پایین جدول (مثلاً «برای خرید پیام بده»)</td></tr>
    <tr><td class="ltr">columns</td><td>📦 پکیج|⏱ مدت|💰 قیمت</td>
        <td>سه سرستون، با <code>|</code> جدا شده</td></tr>
    <tr><td class="ltr">caption</td><td>قیمت‌ها به تومان</td><td>زیرنویس جدول</td></tr>
  </table>

  <table>
    <tr><th>فیلد خروجی</th><th>چطور بفرستی</th></tr>
    <tr><td class="ltr">html_premium</td><td><code>parse_mode="HTML"</code> — با اموجی پرمیوم</td></tr>
    <tr><td class="ltr">html_plain</td><td><code>parse_mode="HTML"</code> — با اموجی عادی</td></tr>
    <tr><td class="ltr">html</td><td>هرکدام که با <code>premium</code> انتخاب کردی</td></tr>
    <tr><td class="ltr">markdown</td><td><code>sendRichMessage</code> — جدول واقعی، بدون نیاز به پرمیوم</td></tr>
    <tr><td class="ltr">packages</td><td>داده‌ی خام، اگر خودت می‌خواهی بچینی</td></tr>
  </table>

  <div class="tabs" data-tabs>
<pre data-l="curl"><code>curl -s -H "X-API-Key: $KEY" \
  "$BASE/packages/table?premium=0&amp;title=🛒 لیست قیمت من&amp;note=برای خرید پیام بده"</code></pre>
<pre data-l="python"><code>status, data = atlas("GET", "/packages/table", params={
    "premium": 0,
    "title": "🛒 لیست قیمت من",
    "columns": "📦 حجم|⏱ مدت|💰 قیمت",
})
await bot.send_message(chat_id, data["html_plain"], parse_mode="HTML")</code></pre>
<pre data-l="node"><code>const r = await atlas("GET", "/packages/table?premium=0");
await bot.sendMessage(chatId, r.data.html_plain, { parse_mode: "HTML" });</code></pre>
  </div>
<pre class="res"><code>{
  "ok": true,
  "premium_emoji": false,
  "html": "&lt;h2&gt;🛒 پکیج‌ها…&lt;/h2&gt;&lt;table bordered striped compact&gt;…",
  "html_premium": "… &lt;tg-emoji emoji-id=\"5983…\"&gt;🌱&lt;/tg-emoji&gt; …",
  "html_plain":   "… 🌱 10 گیگ …",
  "markdown": "| 📦 پکیج | ⏱ مدت | 💰 قیمت |\n|:---|:---:|---:|\n…",
  "packages": [ … ]
}</code></pre>
  <p class="muted">قیمت‌های داخل جدول <b>خودکار</b> با تعرفه‌ی نمایندگی تو حساب می‌شوند.</p>


  <div class="ep"><span class="m post">POST</span><span class="path">/services</span></div>
  <p>ساخت سرویس برای مشتری. پول همان لحظه از کیف پولت کم می‌شود.</p>
  <table>
    <tr><th>فیلد</th><th>نوع</th><th>توضیح</th></tr>
    <tr><td class="ltr">package_id</td><td>عدد</td><td><b>روش اول:</b> خرید بر اساس پکیج آماده</td></tr>
    <tr><td class="ltr">traffic_gb</td><td>عدد</td><td><b>روش دوم:</b> حجم دلخواه. <code>0</code> = نامحدود</td></tr>
    <tr><td class="ltr">duration_days</td><td>عدد</td><td>همراه روش دوم، الزامی</td></tr>
    <tr><td class="ltr">name</td><td>متن</td><td>نام سرویس (اسم مشتری) — اختیاری</td></tr>
    <tr><td class="ltr">count</td><td>عدد</td><td>تعداد، ۱ تا ۱۰ (پیش‌فرض ۱). پشت Cloudflare بیشتر از ۵ نگذار.</td></tr>
    <tr><td class="ltr">names</td><td>لیست متن</td><td>نام جدا برای هر سرویس در خرید گروهی</td></tr>
  </table>
  <div class="snip">
<pre data-l="php"><code>$r = atlas('POST', '/services', [
    'package_id' =&gt; 3,
    'name'       =&gt; 'ali-mobile',
    'count'      =&gt; 1,
], 'order-1001');

if (!empty($r['data']['ok'])) {
    $link = $r['data']['services'][0]['subscription_url'];
    echo "لینک مشتری: $link";
} else {
    echo "خطا: " . $r['data']['message'];
}</code></pre>
<pre data-l="python"><code>status, data = atlas("POST", "/services", {
    "package_id": 3,
    "name": "ali-mobile",
    "count": 1,
}, "order-1001")

if data.get("ok"):
    link = data["services"][0]["subscription_url"]
    print("لینک مشتری:", link)
else:
    print("خطا:", data["message"])</code></pre>
<pre data-l="node"><code>const r = await atlas("POST", "/services", {
  package_id: 3,
  name: "ali-mobile",
  count: 1,
}, "order-1001");

if (r.data.ok) {
  const link = r.data.services[0].subscription_url;
  console.log("لینک مشتری:", link);
} else {
  console.log("خطا:", r.data.message);
}</code></pre>
  </div>
<pre class="res"><code>{
  "ok": true, "order_id": 9134, "requested": 1, "created": 1,
  "charged": 105000, "refunded": 0, "balance": 3990000,
  "services": [{
    "id": 4471,
    "name": "ali-mobile",
    "status": "pending",
    "unlimited": false,
    "traffic_gb": 30,
    "used_bytes": 0,
    "expires_at": 0,
    "days_left": null,
    "starts_on_first_use": true,
    "subscription_url": "__BASE__/sub/AbCdEf..."
  }]
}</code></pre>
  <p><b>معنی <code>status</code>:</b></p>
  <table>
    <tr><td class="ltr">active</td><td>فعال و در حال استفاده</td></tr>
    <tr><td class="ltr">pending</td><td>ساخته شده، هنوز مشتری وصل نشده — زمان از اولین اتصال شروع می‌شود</td></tr>
    <tr><td class="ltr">disabled</td><td>خودت قطعش کرده‌ای</td></tr>
    <tr><td class="ltr">expired</td><td>زمانش تمام شده</td></tr>
    <tr><td class="ltr">depleted</td><td>حجمش تمام شده</td></tr>
  </table>
  <div class="note">
    <b>اگر بخشی از سرویس‌ها ساخته نشود</b> (مثلاً ۴ تا از ۵ تا)، کد <code>207</code> می‌گیری،
    <code>partial: true</code> می‌آید و <b>پول سرویس‌های ساخته‌نشده همان لحظه برمی‌گردد</b> (<code>refunded</code>).
    لازم نیست خودت حساب‌وکتاب کنی.
  </div>

  <div class="ep"><span class="m get">GET</span><span class="path">/services</span></div>
  <p>لیست سرویس‌های تو، با صفحه‌بندی و فیلتر.</p>
  <div class="snip">
<pre data-l="php"><code>// سرویس‌هایی که تا ۳ روز دیگر منقضی می‌شوند (برای یادآوری تمدید به مشتری)
$r = atlas('GET', '/services?filter=expiring&amp;sort=expiry_soon&amp;per_page=50');
foreach ($r['data']['services'] as $s) {
    echo $s['name'] . ' - ' . $s['days_left'] . " روز مانده\n";
}</code></pre>
<pre data-l="python"><code># سرویس‌هایی که تا ۳ روز دیگر منقضی می‌شوند (برای یادآوری تمدید به مشتری)
status, data = atlas("GET", "/services?filter=expiring&sort=expiry_soon&per_page=50")
for s in data["services"]:
    print(s["name"], s["days_left"], "روز مانده")</code></pre>
<pre data-l="node"><code>// سرویس‌هایی که تا ۳ روز دیگر منقضی می‌شوند (برای یادآوری تمدید به مشتری)
const r = await atlas("GET", "/services?filter=expiring&sort=expiry_soon&per_page=50");
for (const s of r.data.services) {
  console.log(s.name, s.days_left, "روز مانده");
}</code></pre>
  </div>
  <table>
    <tr><th>پارامتر</th><th>مقدارها</th></tr>
    <tr><td class="ltr">page / per_page</td><td>شماره‌ی صفحه و تعداد در صفحه (حداکثر ۱۰۰)</td></tr>
    <tr><td class="ltr">q</td><td>جستجو در نام سرویس</td></tr>
    <tr><td class="ltr">filter</td><td><code>all</code> · <code>active</code> · <code>inactive</code> · <code>expired</code> · <code>expiring</code> · <code>near_limit</code> · <code>unlimited</code></td></tr>
    <tr><td class="ltr">sort</td><td><code>newest</code> · <code>oldest</code> · <code>name_az</code> · <code>expiry_soon</code> · <code>usage_desc</code></td></tr>
  </table>

  <div class="ep"><span class="m get">GET</span><span class="path">/services/{id}</span></div>
  <p>جزئیات یک سرویس، به‌همراه لینک <b>تک‌تک سرورها</b> (برای وقتی مشتری فقط یک کانفیگ می‌خواهد).</p>
  <div class="snip">
<pre data-l="php"><code>$r = atlas('GET', '/services/4471');
$s = $r['data']['service'];
echo "مصرف: " . round($s['used_bytes'] / 1073741824, 2) . " GB\n";
foreach ($s['nodes'] as $n) {
    echo $n['label'] . ': ' . $n['link'] . "\n";
}</code></pre>
<pre data-l="python"><code>status, data = atlas("GET", "/services/4471")
s = data["service"]
print("مصرف:", round(s["used_bytes"] / 1024**3, 2), "GB")
for n in s["nodes"]:
    print(n["label"], n["link"])</code></pre>
<pre data-l="node"><code>const r = await atlas("GET", "/services/4471");
const s = r.data.service;
console.log("مصرف:", (s.used_bytes / 1073741824).toFixed(2), "GB");
for (const n of s.nodes) {
  console.log(n.label, n.link);
}</code></pre>
  </div>

  <div class="ep"><span class="m post">POST</span><span class="path">/services/{id}/renew</span></div>
  <p>تمدید. بدنه دقیقاً مثل ساخت است.</p>
  <div class="snip">
<pre data-l="php"><code>$r = atlas('POST', '/services/4471/renew', ['package_id' =&gt; 3], 'renew-1001');
echo $r['data']['ok'] ? "تمدید شد" : $r['data']['message'];</code></pre>
<pre data-l="python"><code>status, data = atlas("POST", "/services/4471/renew", {"package_id": 3}, "renew-1001")
print("تمدید شد" if data.get("ok") else data["message"])</code></pre>
<pre data-l="node"><code>const r = await atlas("POST", "/services/4471/renew", { package_id: 3 }, "renew-1001");
console.log(r.data.ok ? "تمدید شد" : r.data.message);</code></pre>
  </div>
<pre class="res"><code>{ "ok": true, "order_id": 9140, "charged": 105000, "balance": 3885000,
  "nodes_renewed": 6, "carried_over": true, "service": { ... } }</code></pre>
  <p class="muted"><code>carried_over: true</code> یعنی سرویس هنوز حجم و زمان داشت و باقی‌مانده‌اش به بسته‌ی جدید <b>اضافه</b> شد.</p>

  <div class="ep"><span class="m post">POST</span><span class="path">/services/{id}/rename</span></div>
  <div class="snip">
<pre data-l="php"><code>atlas('POST', '/services/4471/rename', ['name' =&gt; 'ali-laptop']);</code></pre>
<pre data-l="python"><code>atlas("POST", "/services/4471/rename", {"name": "ali-laptop"})</code></pre>
<pre data-l="node"><code>await atlas("POST", "/services/4471/rename", { name: "ali-laptop" });</code></pre>
  </div>

  <div class="ep"><span class="m post">POST</span><span class="path">/services/{id}/disable</span> · <span class="path">/enable</span></div>
  <p>قطع و وصل سرویس روی همه‌ی سرورها. برگشت‌پذیر است و پولی برنمی‌گردد. بدنه لازم ندارد.</p>
  <div class="snip">
<pre data-l="php"><code>atlas('POST', '/services/4471/disable');   // مشتری پول نداده؟ قطعش کن
atlas('POST', '/services/4471/enable');    // پرداخت کرد؟ دوباره وصل</code></pre>
<pre data-l="python"><code>atlas("POST", "/services/4471/disable")   # مشتری پول نداده؟ قطعش کن
atlas("POST", "/services/4471/enable")    # پرداخت کرد؟ دوباره وصل</code></pre>
<pre data-l="node"><code>await atlas("POST", "/services/4471/disable");   // مشتری پول نداده؟ قطعش کن
await atlas("POST", "/services/4471/enable");    // پرداخت کرد؟ دوباره وصل</code></pre>
  </div>

  <div class="ep"><span class="m post">POST</span><span class="path">/services/{id}/revoke</span></div>
  <p>مشتری لینکش را به دوستانش داده؟ این دستور لینک قدیمی را <b>کاملاً</b> از کار می‌اندازد و لینک تازه می‌دهد.
     حجم، انقضا و مصرف حفظ می‌شود — <b>این تمدید نیست و پولی نمی‌گیرد</b>. فقط روی سرویس <b>فعال</b> کار می‌کند.</p>
  <div class="snip">
<pre data-l="php"><code>$r = atlas('POST', '/services/4471/revoke');
echo "لینک جدید: " . $r['data']['subscription_url'];</code></pre>
<pre data-l="python"><code>status, data = atlas("POST", "/services/4471/revoke")
print("لینک جدید:", data["subscription_url"])</code></pre>
<pre data-l="node"><code>const r = await atlas("POST", "/services/4471/revoke");
console.log("لینک جدید:", r.data.subscription_url);</code></pre>
  </div>

  <div class="ep"><span class="m post">POST</span><span class="path">/services/{id}/delete</span></div>
  <div class="snip">
<pre data-l="php"><code>atlas('POST', '/services/4471/delete', ['confirm' =&gt; true]);</code></pre>
<pre data-l="python"><code>atlas("POST", "/services/4471/delete", {"confirm": True})</code></pre>
<pre data-l="node"><code>await atlas("POST", "/services/4471/delete", { confirm: true });</code></pre>
  </div>
  <div class="danger"><b>برگشت‌ناپذیر است و هیچ پولی برنمی‌گردد.</b> بدون <code>confirm: true</code> رد می‌شود.
     برای قطع موقت از <code>/disable</code> استفاده کن.</div>

  <div class="ep"><span class="m post">POST</span><span class="path">/services/trial</span></div>
  <p>اکانت تست رایگان از سهمیه‌ی روزانه‌ی نمایندگی‌ات (اگر ادمین فعال کرده باشد). رایگان است.</p>
  <div class="snip">
<pre data-l="php"><code>$r = atlas('POST', '/services/trial', ['name' =&gt; 'test-ali']);
echo $r['data']['service']['subscription_url'];</code></pre>
<pre data-l="python"><code>status, data = atlas("POST", "/services/trial", {"name": "test-ali"})
print(data["service"]["subscription_url"])</code></pre>
<pre data-l="node"><code>const r = await atlas("POST", "/services/trial", { name: "test-ali" });
console.log(r.data.service.subscription_url);</code></pre>
  </div>

  <div class="ep"><span class="m get">GET</span><span class="path">/wallet</span> · <span class="path">/orders</span></div>
  <p>موجودی و تراکنش‌ها · سفارش‌های اخیر (سند حسابداری هر کسر از کیف پول). هر دو پارامتر <code>limit</code> دارند.</p>
  <div class="snip">
<pre data-l="php"><code>$w = atlas('GET', '/wallet?limit=10');
echo "موجودی: " . number_format($w['data']['balance']) . " تومان";</code></pre>
<pre data-l="python"><code>status, w = atlas("GET", "/wallet?limit=10")
print("موجودی:", f"{w['balance']:,} تومان")</code></pre>
<pre data-l="node"><code>const w = await atlas("GET", "/wallet?limit=10");
console.log("موجودی:", w.data.balance.toLocaleString(), "تومان");</code></pre>
  </div>
</section>

<!-- ═══════════════════════ 6 ═══════════════════════ -->
<section id="errors">
  <h2>۶. خطاها</h2>
  <p>هر خطا این شکل را دارد — <code>error</code> برای برنامه‌ات، <code>message</code> برای نشان‌دادن به مشتری:</p>
<pre class="res"><code>{ "ok": false, "error": "insufficient_balance",
  "message": "موجودی کیف پول کافی نیست. لازم: 105,000 تومان، موجودی: 40,000 تومان.",
  "required": 105000, "balance": 40000 }</code></pre>
  <table>
    <tr><th class="ltr">error</th><th>کد</th><th>یعنی چه و چه کار کنم</th></tr>
    <tr><td class="ltr">missing_key</td><td>401</td><td>هدر کلید را نفرستاده‌ای</td></tr>
    <tr><td class="ltr">invalid_key</td><td>401</td><td>کلید اشتباه یا لغو شده — از ربات کلید تازه بگیر</td></tr>
    <tr><td class="ltr">not_a_representative</td><td>403</td><td>حساب دیگر نماینده نیست</td></tr>
    <tr><td class="ltr">account_blocked</td><td>403</td><td>حساب مسدود است — با پشتیبانی تماس بگیر</td></tr>
    <tr><td class="ltr">insufficient_scope</td><td>403</td><td>کلیدت فقط خواندنی است</td></tr>
    <tr><td class="ltr">ip_not_allowed</td><td>403</td><td>از IP غیرمجاز درخواست زده‌ای</td></tr>
    <tr><td class="ltr">topup_required</td><td>403</td><td>هنوز حداقل شارژ اولیه‌ی نمایندگی را انجام نداده‌ای</td></tr>
    <tr><td class="ltr">rate_limited</td><td>429</td><td>خیلی سریع درخواست زده‌ای — به‌اندازه‌ی <code>Retry-After</code> ثانیه صبر کن</td></tr>
    <tr><td class="ltr">invalid_request</td><td>400</td><td>پارامترها ناقص یا اشتباه‌اند</td></tr>
    <tr><td class="ltr">package_unavailable</td><td>400</td><td>این پکیج وجود ندارد یا غیرفعال شده</td></tr>
    <tr><td class="ltr">custom_pricing_unavailable</td><td>400</td><td>برای حجم دلخواه تعرفه نداری — از <code>package_id</code> استفاده کن</td></tr>
    <tr><td class="ltr">insufficient_balance</td><td>402</td><td>کیف پولت را شارژ کن</td></tr>
    <tr><td class="ltr">service_not_found</td><td>404</td><td>این سرویس وجود ندارد یا مال تو نیست</td></tr>
    <tr><td class="ltr">confirmation_required</td><td>400</td><td>برای حذف باید <code>confirm: true</code> بفرستی</td></tr>
    <tr><td class="ltr">provisioning_failed</td><td>502</td><td>ساخت روی سرورها انجام نشد — <b>پولت برگشت خورد</b>، دوباره تلاش کن</td></tr>
    <tr><td class="ltr">renew_failed</td><td>502</td><td>تمدید انجام نشد — <b>پولت برگشت خورد</b></td></tr>
    <tr><td class="ltr">request_in_flight</td><td>409</td><td>همین درخواست در حال انجام است — چند ثانیه صبر و دوباره</td></tr>
    <tr><td class="ltr">idempotency_conflict</td><td>409</td><td>این شناسه قبلاً برای درخواست دیگری استفاده شده</td></tr>
    <tr><td class="ltr">trial_limit_reached</td><td>429</td><td>سهمیه‌ی تست امروزت پر شده</td></tr>
    <tr><td class="ltr">api_disabled</td><td>503</td><td>API موقتاً توسط ادمین خاموش شده</td></tr>
  </table>
</section>

<!-- ═══════════════════════ 7 ═══════════════════════ -->
<section id="full">
  <h2>۷. مثال کامل: فروش یک سرویس به مشتری</h2>
  <p>این همان کدی است که در ربات خودت لازم داری: سرویس را می‌سازد، در برابر timeout و 524 مقاوم است،
     و در هیچ حالتی دو بار پول کم نمی‌کند.</p>
  <div class="snip">
<pre data-l="php"><code>&lt;?php
// تابع atlas() از بخش ۱ را بالای همین فایل بگذار.

/**
 * برای یک مشتری سرویس می‌سازد و لینک اشتراک را برمی‌گرداند.
 * $orderId باید برای هر سفارش یکتا باشد (مثلاً شناسه‌ی سفارش در دیتابیس خودت).
 */
function sellService($orderId, $packageId, $customerName) {
    // حداکثر ۳ بار تلاش — برای وقتی Cloudflare وسط کار قطع می‌کند.
    for ($try = 1; $try &lt;= 3; $try++) {
        $r = atlas('POST', '/services', [
            'package_id' =&gt; $packageId,
            'name'       =&gt; $customerName,
        ], 'order-' . $orderId);          // ← همان شناسه در هر سه تلاش

        $data = $r['data'];

        // درخواست قبلی هنوز در حال انجام است: صبر کن و دوباره بپرس.
        if (isset($data['error']) &amp;&amp; $data['error'] === 'request_in_flight') {
            sleep(8);
            continue;
        }

        // پاسخ قطعی گرفتیم (موفق یا ناموفق).
        if ($data !== null) {
            if (!empty($data['ok'])) {
                return ['ok' =&gt; true, 'link' =&gt; $data['services'][0]['subscription_url']];
            }
            return ['ok' =&gt; false, 'error' =&gt; $data['message']];
        }

        // پاسخی نیامد (timeout / 524). سرور شاید کارش را تمام کرده باشد،
        // پس با همان شناسه دوباره می‌پرسیم — پول دوباره کم نمی‌شود.
        sleep(8);
    }

    return ['ok' =&gt; false, 'error' =&gt; 'پاسخی از سرور نگرفتیم. چند دقیقه بعد وضعیت سفارش را چک کن.'];
}

// ---------- استفاده ----------
$res = sellService(1001, 3, 'ali-mobile');

if ($res['ok']) {
    echo "لینک اشتراک مشتری:\n" . $res['link'];
} else {
    echo "خطا: " . $res['error'];
}</code></pre>
<pre data-l="python"><code># تابع atlas() از بخش ۱ را بالای همین فایل بگذار.
import time


# برای یک مشتری سرویس می‌سازد و لینک اشتراک را برمی‌گرداند.
# order_id باید برای هر سفارش یکتا باشد (مثلاً شناسه‌ی سفارش در دیتابیس خودت).
def sell_service(order_id, package_id, customer_name):
    # حداکثر ۳ بار تلاش — برای وقتی Cloudflare وسط کار قطع می‌کند.
    for attempt in range(3):
        try:
            status, data = atlas("POST", "/services", {
                "package_id": package_id,
                "name": customer_name,
            }, f"order-{order_id}")          # ← همان شناسه در هر سه تلاش
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

if ok:
    print("لینک اشتراک مشتری:")
    print(result)
else:
    print("خطا:", result)</code></pre>
<pre data-l="node"><code>// تابع atlas() از بخش ۱ را بالای همین فایل بگذار.

const sleep = (ms) =&gt; new Promise((r) =&gt; setTimeout(r, ms));

/**
 * برای یک مشتری سرویس می‌سازد و لینک اشتراک را برمی‌گرداند.
 * orderId باید برای هر سفارش یکتا باشد (مثلاً شناسه‌ی سفارش در دیتابیس خودت).
 */
async function sellService(orderId, packageId, customerName) {
  // حداکثر ۳ بار تلاش — برای وقتی Cloudflare وسط کار قطع می‌کند.
  for (let attempt = 0; attempt &lt; 3; attempt++) {
    let data;
    try {
      const r = await atlas("POST", "/services", {
        package_id: packageId,
        name: customerName,
      }, `order-${orderId}`);          // ← همان شناسه در هر سه تلاش
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

if (res.ok) {
  console.log("لینک اشتراک مشتری:");
  console.log(res.link);
} else {
  console.log("خطا:", res.error);
}</code></pre>
  </div>
  <div class="note">
    اگر بعد از ۳ تلاش هم جواب نگرفتی، سفارش را دوباره نساز.
    با <code>GET /orders</code> یا <code>GET /services</code> ببین ساخته شده یا نه.
  </div>
</section>

<!-- ═══════════════════════ 8 ═══════════════════════ -->
<section id="security">
  <h2>۸. امنیت — این چند نکته را جدی بگیر</h2>
  <ul>
    <li>کلید = <b>دسترسی به کیف پول تو</b>. هرکس آن را داشته باشد می‌تواند از موجودی‌ات سرویس بسازد.</li>
    <li>کلید را <b>فقط روی سرور خودت</b> نگه دار. هرگز داخل اپ موبایل، کد جاوااسکریپت مرورگر یا مخزن گیت عمومی نگذار — به‌راحتی بیرون کشیده می‌شود.</li>
    <li>کلید را در فایل تنظیمات یا متغیر محیطی بگذار، نه وسط کد.</li>
    <li>اگر کلید لو رفت: همان لحظه از داخل ربات <b>لغوش کن</b> و یکی جدید بساز.</li>
    <li>همیشه از <b>HTTPS</b> استفاده کن (همین آدرس بالا).</li>
    <li>برای بخش‌هایی که فقط گزارش می‌گیرند، از پشتیبانی کلید <code>read</code> بخواه.</li>
  </ul>
</section>

<footer>__BRAND__ · API نمایندگان · نسخه ۱٫۰</footer>
</div>

<script>
(function () {
  // ── language switch: every sample on the page follows one choice ─────────
  var bar = document.getElementById('langbar');
  function setLang(l) {
    document.body.dataset.lang = l;
    bar.querySelectorAll('button').forEach(function (b) {
      b.classList.toggle('on', b.dataset.l === l);
    });
    try { localStorage.setItem('atlas_api_lang', l); } catch (e) {}
  }
  bar.addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (b) setLang(b.dataset.l);
  });
  var saved = 'php';
  try { saved = localStorage.getItem('atlas_api_lang') || 'php'; } catch (e) {}
  setLang(saved);

  // ── copy buttons ─────────────────────────────────────────────────────────
  // Standalone <pre> blocks get wrapped so they can host a button too.
  document.querySelectorAll('pre').forEach(function (pre) {
    if (!pre.parentElement.classList.contains('snip')) {
      var wrap = document.createElement('div');
      wrap.className = 'snip';
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(pre);
    }
  });

  function copyText(text, btn) {
    var done = function () {
      btn.textContent = 'کپی شد ✓';
      btn.classList.add('done');
      setTimeout(function () { btn.textContent = 'کپی'; btn.classList.remove('done'); }, 1600);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () {});
      return;
    }
    // Older in-app browsers (Telegram's WebView included) have no clipboard
    // API, so fall back to a throwaway textarea.
    var ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); done(); } catch (e) {}
    document.body.removeChild(ta);
  }

  // ONE button per block, copying whichever language is currently on screen —
  // a button per <pre> would stack three of them at the same coordinates.
  document.querySelectorAll('.snip').forEach(function (snip) {
    var btn = document.createElement('button');
    btn.className = 'copy';
    btn.type = 'button';
    btn.textContent = 'کپی';
    btn.addEventListener('click', function () {
      var pres = snip.querySelectorAll('pre');
      var visible = null;
      pres.forEach(function (p) { if (p.offsetParent !== null && !visible) visible = p; });
      copyText((visible || pres[0]).innerText, btn);
    });
    snip.appendChild(btn);
  });
})();
</script>
</body>
</html>
"""


def docs_html(base_url: str, brand: str) -> str:
    """Render the reference page for this installation.

    ``base_url`` is whatever the owner published as ``public_base_url`` — the
    same host that serves ``/sub/{token}`` — so every sample on the page is
    copy-pasteable rather than a placeholder the reader has to substitute.
    """
    base = (base_url or "").rstrip("/") or "https://your-domain.com"
    safe_base = base.replace("<", "&lt;").replace(">", "&gt;")
    safe_brand = (brand or "Atlas").replace("<", "&lt;").replace(">", "&gt;")[:60]
    return _PAGE.replace("__BASE__", safe_base).replace("__BRAND__", safe_brand)
