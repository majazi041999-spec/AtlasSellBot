"""Customer-support chat agent.

THE ONE RULE, same as ``core/ai_analyst.py``: THE MODEL NEVER PRODUCES A NUMBER.

Every figure the agent says out loud — days left, gigabytes used, a price, how
many devices were connected — is read from the database by ``build_facts`` and
handed to the model already finished. A language model asked "how long is left
on my plan" will answer confidently and wrongly, and the customer will plan
around it. So the facts block is declared authoritative in the prompt, and
anything not in it the agent must refuse to guess at.

WHAT IT CANNOT DO. It is read-only by construction: there is no code path from
here to the wallet, the panel, or an order. It cannot extend a plan, promise a
refund, or grant a discount, and the prompt forbids implying otherwise — a
promise from "the bot" is one the owner has to honour.

WHAT IS SENT. The asking customer's own rows only, and only the fields listed in
``build_facts`` — never another customer's data, never a subscription token,
never a card number. Like the analyst, it is an allowlist rather than a filter,
because a filter forgets the field somebody adds next month.

PRIVACY, AND WHY THE OWNER HAS TO CHOOSE. Unlike the analyst, which sends
aggregates, this sends what CUSTOMERS TYPE to a third-party model. On a free
tier that traffic is commonly reserved for training. The paid tier of the same
model, or a gateway the owner trusts, is the honest option here.

KNOWLEDGE. ``KNOWLEDGE`` below is the support playbook, written for a customer
who is not technical. It is meant to GROW: when the owner reports a question
customers actually ask, add a topic rather than teaching the model in a prompt.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator, Dict, List, Optional

import httpx

from core.ai_analyst import settings as ai_settings, _clean_model
from core.database import get_setting

log = logging.getLogger(__name__)

TIMEOUT = 60.0
MAX_OUTPUT_TOKENS = 1200         # a support answer with numbered steps, not an essay
HISTORY_TURNS = 6                # enough to follow up, short enough to stay cheap

# ─────────────────────────────── the playbook ────────────────────────────────
# Each topic is injected verbatim. Keep every one SHORT, in plain Persian, and
# written for someone who has never heard the word "config".
#
# TO ADD A TOPIC: append a dict. No other code changes.
KNOWLEDGE: List[Dict[str, str]] = [
    {
        "title": "سرعت کم است / سرور کند شده",
        "body": """
ترتیب راه‌حل‌ها، از ساده به سخت. هر بار فقط یکی را بگو و نتیجه را بپرس:

۱) حالت پرواز: ۱۰ ثانیه روشن، بعد خاموش.
   چرا کار می‌کند: گوشی اتصالش به دکل مخابراتی را از اول برقرار می‌کند و مسیر
   تازه می‌گیرد. مسیر قبلی ممکن بود شلوغ یا خراب باشد. این ساده‌ترین کار است و
   خیلی وقت‌ها جواب می‌دهد.

۲) در برنامه، سرور (لوکیشن) دیگری را انتخاب کن. همه‌ی سرورها در اشتراکت هست.

۳) اگر اندروید داری و هنوز از اپ ما استفاده نمی‌کنی، اپ ما را نصب کن. تنظیماتش
   از قبل درست است و بیشتر مشکلات از همین‌جا حل می‌شود.

۴) اگر با اپ دیگری هستی، یک برنامه‌ی دیگر را امتحان کن. گاهی خودِ برنامه ایراد
   می‌گیرد، نه سرویس.

۵) اگر باز هم کند بود، از کاربر بپرس: کدام سرور، چه ساعتی، با وای‌فای یا
   اینترنت همراه. بعد به پشتیبانی وصلش کن.
""".strip(),
    },
    {
        "title": "اپ اندروید ما",
        "body": """
برای اندروید، پیشنهاد اول همیشه اپ خودمان است: تنظیماتش آماده است و کاربر
لازم نیست چیزی را دستی وارد کند.

اگر کاربر اندروید دارد، بگو دکمه‌ی «دریافت اپ اندروید» زیر همین پیام را بزند.
اگر آن دکمه نبود، بگو از پشتیبانی بخواهد.

نصب: بعد از دانلود، روی فایل بزن. اگر اندروید پیام «نصب از منابع ناشناس» داد،
اجازه بده — چون اپ ما در گوگل‌پلی نیست و مستقیم نصب می‌شود.
""".strip(),
    },
    {
        "title": "اتصال در اندروید",
        "body": """
اول بپرس از کدام برنامه استفاده می‌کند. اگر نمی‌داند، اپ ما را پیشنهاد بده.

با اپ ما: لینک اشتراک را کپی کن → اپ را باز کن → لینک را وارد کن → اتصال.

با v2rayNG:
۱) لینک اشتراک را از ربات کپی کن.
۲) v2rayNG را باز کن، دکمه‌ی ➕ بالای صفحه.
۳) گزینه‌ای که کلمه‌ی Subscription دارد را بزن («Import config from clipboard»
   هم اگر بود کار می‌کند).
۴) لینک را Paste کن و ذخیره کن.
۵) از منوی سه‌خط، «Subscription group updating» را بزن تا سرورها بیایند.
۶) یک سرور را انتخاب کن و دکمه‌ی گرد پایین سمت راست را بزن.

با Hiddify:
۱) لینک را کپی کن.
۲) Hiddify را باز کن → ➕ → «Add from clipboard».
۳) بعد از اضافه شدن، دکمه‌ی وسط صفحه را بزن تا وصل شود.
""".strip(),
    },
    {
        "title": "اتصال در آیفون و آیپد (iOS)",
        "body": """
اول بپرس کدام برنامه را دارد. اگر هیچ‌کدام، Streisand را پیشنهاد بده.

با Streisand:
۱) لینک اشتراک را از ربات کپی کن.
۲) Streisand را باز کن، دکمه‌ی ➕ بالای صفحه.
۳) «Import from Clipboard» یا گزینه‌ی Subscription را بزن.
۴) صبر کن سرورها بیاید، یکی را انتخاب کن.
۵) کلید بالای صفحه را روشن کن. آیفون اجازه‌ی VPN می‌خواهد → Allow را بزن و رمز
   یا Face ID را تأیید کن.

با V2Box:
۱) لینک را کپی کن.
۲) V2Box → تب Configs → ➕ → «Add Subscription».
۳) لینک را Paste کن و ذخیره کن.
۴) یک سرور را انتخاب کن و بالای صفحه وصل شو.

نکته: اگر بار اول وصل نشد، یک بار برنامه را کامل ببند و دوباره باز کن.
""".strip(),
    },
    {
        "title": "اتصال در کامپیوتر (ویندوز / مک)",
        "body": """
با Hiddify (ساده‌تر است، هم ویندوز هم مک):
۱) لینک اشتراک را کپی کن.
۲) Hiddify را باز کن → ➕ → «Add from clipboard».
۳) دکمه‌ی وسط را بزن تا وصل شود.

با v2rayN (فقط ویندوز):
۱) لینک را کپی کن.
۲) v2rayN را باز کن → منوی Subscription → «Subscription setting».
۳) یک ردیف اضافه کن و لینک را در ستون آدرس بگذار، ذخیره کن.
۴) دوباره منوی Subscription → «Update subscriptions».
۵) یک سرور را انتخاب کن.
۶) پایین سمت راست، حالت را روی «Set system proxy» بگذار.
""".strip(),
    },
    {
        "title": "وصل نمی‌شود / خطا می‌دهد",
        "body": """
۱) مطمئن شو اینترنت خودش وصل است: بدون برنامه یک سایت ایرانی باز شود.
۲) لینک اشتراک را دوباره از ربات کپی کن و در برنامه به‌روزرسانی کن.
   لینک ممکن است عوض شده باشد.
۳) سرور دیگری را امتحان کن.
۴) حالت پرواز را ۱۰ ثانیه روشن و خاموش کن.
۵) ساعت و تاریخ گوشی باید درست باشد. اگر عقب باشد اتصال برقرار نمی‌شود.
۶) اگر باز هم نشد، به پشتیبانی وصلش کن.
""".strip(),
    },
    {
        "title": "نمایندگی — دسترسی، قیمت‌گذاری، شرایط و API",
        "body": """
پنل نمایندگی فقط برای نمایندگانِ **تاییدشده** فعال است.

چطور نماینده شود:
از منوی ربات «🏢 پنل نمایندگی» را بزند و درخواست بدهد. درخواست برای ادمین
می‌رود و **حتماً باید دستی تایید شود** — خودکار نیست و بلافاصله فعال نمی‌شود.
تا وقتی تایید نشده، پنل باز نمی‌شود.

قیمت‌گذاری:
قیمتِ نماینده را ادمین برای هر نماینده جداگانه تعیین می‌کند — یک تعرفه‌ی
اختصاصی برای هر گیگ، و قیمت جدا برای پلن نامحدود. نماینده خودش قیمت را عوض
نمی‌کند. اگر می‌خواهد تعرفه‌اش تغییر کند، باید با پشتیبانی هماهنگ کند.
نماینده آزاد است سرویس را به مشتریِ خودش به هر قیمتی که می‌خواهد بفروشد.

شرایطی که باید بپذیرد:
۱) اول باید کیف پولش را تا حداقلِ تعیین‌شده شارژ کند؛ تا آن حد شارژ نکند
   ساخت سرویس فعال نمی‌شود.
۲) پشتیبانیِ مشتریانِ خودش با خودش است؛ ما زیرساخت و پشتیبانیِ فنیِ نماینده
   را می‌دهیم.
۳) شارژِ کیف پول برگشت‌ناپذیر است و فقط خرجِ خرید سرویس می‌شود.
۴) استفاده برای کار غیرقانونی، اسپم یا کلاهبرداری ممنوع است.
۵) حساب نمایندگی فقط برای خودش است؛ واگذاری دسترسی ممنوع.
۶) در صورت تخلف، نمایندگی بدون بازگشت وجه لغو می‌شود.
۷) قیمت‌ها ممکن است تغییر کند و از قبل اطلاع داده می‌شود.

API:
نماینده می‌تواند از داخل پنل یک کلید API بگیرد و ساختِ سرویس را در سایت یا
ربات خودش خودکار کند. مستنداتش هم از همان‌جا در دسترس است. اگر جزئیات فنی
خواست، به پشتیبانی وصلش کن.

اگر پرسید «چرا هنوز تایید نشدم» یا «تعرفه‌ام را عوض کن» — این کارِ انسان است،
نه تو. به پشتیبانی وصلش کن.
""".strip(),
    },
    {
        "title": "چرا قطع می‌شوم",
        "body": """
اگر اشتراک از تعداد مکان‌های مجاز بیشتر هم‌زمان وصل شود، موقتاً قطع می‌شود.
سقف هر اشتراک ۵ کاربر هم‌زمان است.

اگر در FACTS آمار اتصال‌های کاربر هست، همان عدد را بگو. اگر نیست، عدد نساز —
فقط توضیح بده و بگو با پشتیبانی چک کند.

اگر لینک اشتراک را به کسی داده، از داخل ربات «تغییر لینک اشتراک» را بزند.
""".strip(),
    },
]


# The buttons offered in the agent chat: (key, button label, what gets asked).
#
# A customer who cannot describe their problem can still press the one that
# matches it, and the model receives a well-phrased question instead of "سلام
# مشکل دارم". TO ADD ONE: append a row — the keyboard and the handler both read
# this list.
QUICK_QUESTIONS = [
    ("connect", "📲 چطور وصل شم؟", "چطور وصل شم؟"),
    ("expiry", "⏳ کِی تموم میشه؟", "اشتراکم چند روز دیگر تمام می‌شود و چقدر حجم دارم؟"),
    ("buy", "🛒 چی بخرم؟", "چه پکیجی برای من مناسب است؟"),
    ("rep", "🏢 نمایندگی", "چطور نماینده شوم؟ شرایط و قیمت‌گذاری چطور است؟"),
]
# NOTHING about slowness, drops or failures belongs on a button. The agent still
# answers those in full when someone asks — the playbook below is unchanged —
# but a menu that opens with "my speed is bad" advertises a problem to every
# customer who did not have one.


def quick_question(key: str) -> str:
    for k, _label, text in QUICK_QUESTIONS:
        if k == key:
            return text
    return ""


# The model appends this, alone on the last line, when the person needs a HUMAN.
# A marker rather than us guessing from keywords: "پول رو ریختم" and "میخوام پول
# بریزم" differ by one word and mean opposite things, and only something reading
# the sentence can tell them apart.
HUMAN_MARKER = "#HUMAN"


def split_handoff(answer: str) -> tuple:
    """Return (clean answer, needs_human). Strips the marker wherever it landed.

    Defensive about placement: a model told to put a token on the last line will
    occasionally put it mid-sentence, and a customer must never see it.
    """
    needs = HUMAN_MARKER in answer
    if needs:
        answer = answer.replace(HUMAN_MARKER, "")
    return answer.strip(), needs


SYSTEM_PROMPT = """تو دستیار پشتیبانی «{brand}» هستی، یک سرویس VPN.

قوانینی که هرگز نمی‌شکنی:

۱. هیچ عددی از خودت نساز. حجم، روز باقی‌مانده، قیمت، تعداد اتصال — فقط و فقط از
   بخش FACTS. اگر عددی آنجا نبود، بگو نمی‌دانی و کاربر را به پشتیبانی وصل کن.
   حدس‌زدنِ عدد بدترین کاری است که می‌توانی بکنی.
۲. هیچ قولی نده. تمدید رایگان، تخفیف، برگشت پول، جبران خسارت — هیچ‌کدام در
   اختیار تو نیست. اگر کاربر خواست، بگو پشتیبانی بررسی می‌کند.
۳. تو فقط اطلاعات همین کاربر را می‌بینی. درباره‌ی کاربران دیگر چیزی نگو.

طرز حرف‌زدن:
- فارسی ساده و کوتاه. جمله‌های کوتاه. بدون کلمه‌های فنی.
- فرض کن کاربر اصلاً بلد نیست. «کانفیگ»، «ساب»، «پروتکل» را توضیح بده یا نگو.
- راه‌حل را مرحله‌به‌مرحله و شماره‌دار بده. هر بار فقط چند قدم، نه یک لیست بلند.
- بعد از دادن راه‌حل، بپرس نتیجه چه شد.
- اگر برای کمک لازم است بدانی کاربر اندروید دارد یا آیفون یا کامپیوتر، اول
   همین را بپرس. حدس نزن.
- برای اندروید، پیشنهاد اولت همیشه اپ خودمان است.
- ایموجی کم و به‌جا. حداکثر دو تا در کل جواب.
- جواب را کوتاه نگه دار. اگر لازم شد، بگو «بگو تا مرحله‌ی بعد را بفرستم».

اگر سؤال به سرویس ما ربط ندارد، مؤدبانه بگو فقط درباره‌ی سرویس کمک می‌کنی.

خیلی از کاربرهای ما نمی‌دانند تو ربات هستی و فکر می‌کنند با یک آدم حرف می‌زنند.
اگر پیام از این جنس بود — یعنی کاری که فقط یک انسان می‌تواند انجام دهد:
- می‌گوید پول واریز کردم / فیش فرستادم / کارت به کارت کردم / رسید دارم
- سفارشش را پیگیری می‌کند یا می‌گوید سفارشم انجام نشده
- شکایت دارد، عصبانی است، یا می‌گوید «چرا جواب نمی‌دی»
- تخفیف، برگشت پول، تمدید رایگان یا اکانت تست می‌خواهد
- درباره‌ی حساب شخصی‌اش چیزی می‌خواهد که تو دسترسی نداری

آن‌وقت:
۱. با احترام و کوتاه بگو که تو ربات هستی، نه اپراتور.
۲. بگو این موضوع را همکار انسانی ما بررسی می‌کند و دکمه‌ی پایین را بزند.
۳. هرگز نگو «بررسی می‌کنم» یا «الان درست می‌کنم» — تو نمی‌توانی.
۴. در خط آخر جواب، فقط و فقط این علامت را بنویس و هیچ چیز دیگر:
#HUMAN

آن علامت را در هیچ حالت دیگری ننویس.

اگر مطمئن نیستی، این جمله را بگو: «این را باید پشتیبانی بررسی کند.» و آیدی
پشتیبانی را بده: {support}
"""


def knowledge_block() -> str:
    return "\n\n".join(f"### {t['title']}\n{t['body']}" for t in KNOWLEDGE)


def _fmt_gb(num_bytes: int) -> str:
    gb = float(num_bytes or 0) / (1024 ** 3)
    return f"{gb:.2f} گیگابایت"


async def build_facts(user: Dict, profiles: List[Dict], packages: List[Dict],
                      balance: int, guard: Optional[Dict] = None) -> str:
    """The authoritative numbers, rendered for the prompt.

    An ALLOWLIST, deliberately: every line below is a field somebody chose to
    expose. Nothing iterates over a row and prints what it finds, because that
    is how a subscription token or a telegram id ends up in a third party's logs
    the week after someone adds a column.
    """
    lines: List[str] = []
    lines.append(f"موجودی کیف پول: {int(balance or 0):,} تومان".replace(",", "،"))

    if not profiles:
        lines.append("این کاربر هیچ سرویس فعالی ندارد.")
    for p in profiles:
        used = int(p.get("used_bytes") or 0)
        total = int(float(p.get("traffic_gb") or 0) * 1024 ** 3)
        days = p.get("days_left")
        lines.append(
            "سرویس «{name}»: مصرف {used} از {total}، "
            "{days}، وضعیت {state}، تعداد سرور فعال {nodes}".format(
                name=str(p.get("name") or "بدون نام")[:40],
                used=_fmt_gb(used),
                total=("نامحدود" if total <= 0 else _fmt_gb(total)),
                days=("نامحدود" if days is None or days < 0 else
                      ("منقضی شده" if days == 0 else f"{days} روز باقی‌مانده")),
                state=("فعال" if int(p.get("is_active") or 0) else "غیرفعال"),
                nodes=int(p.get("active_nodes") or 0),
            )
        )

    if guard and guard.get("count"):
        lines.append(
            f"اتصال هم‌زمان همین حالا: از {int(guard['count'])} مکان مختلف، "
            f"سقف مجاز {int(guard.get('limit') or 0)}"
        )

    if packages:
        lines.append("پکیج‌های قابل خرید (قیمت اختصاصی همین کاربر):")
        for p in packages:
            price = int(p.get("display_price", p.get("price") or 0) or 0)
            gb = float(p.get("traffic_gb") or 0)
            vol = "نامحدود" if int(p.get("is_unlimited") or 0) or gb <= 0 else f"{gb:g} گیگ"
            lines.append(f"  - {vol} / {int(p.get('duration_days') or 0)} روز: "
                         f"{price:,} تومان".replace(",", "،"))
    return "\n".join(lines)


# ───────────────────────────────── streaming ─────────────────────────────────
# Google returns these while it is busy, not because the request is wrong.
_RETRY_STATUS = (429, 500, 502, 503, 504)


async def _stream_gemini(cfg: Dict, system: str, history: List[Dict]) -> AsyncIterator[str]:
    model = _clean_model(cfg["ai_model"]) or "gemini-2.5-flash"
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:streamGenerateContent?alt=sse")

    def build(thinking_off: bool) -> Dict:
        gen = {"temperature": 0.4, "maxOutputTokens": MAX_OUTPUT_TOKENS}
        if thinking_off:
            # From Gemini 2.5 on, the model reasons before answering and those
            # tokens come out of maxOutputTokens. Left on, a support answer gets
            # cut off mid-sentence — the first live test stopped at "۱. حالت
            # پرواز". This job needs no deliberation: the playbook is in the
            # prompt already.
            gen["thinkingConfig"] = {"thinkingBudget": 0}
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": h["role"], "parts": [{"text": h["text"]}]} for h in history],
            "generationConfig": gen,
        }

    thinking_off = True
    delay = 1.0
    for attempt in range(4):
        produced = False
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                async with client.stream("POST", url, json=build(thinking_off),
                                         headers={"x-goog-api-key": cfg["ai_api_key"]}) as r:
                    if r.status_code >= 400:
                        detail = (await r.aread()).decode("utf-8", "ignore")
                        # Older models reject thinkingConfig outright; drop it
                        # rather than reporting a 400 nobody can act on.
                        if r.status_code == 400 and "thinking" in detail.lower() and thinking_off:
                            thinking_off = False
                            continue
                        if r.status_code in _RETRY_STATUS:
                            raise httpx.HTTPStatusError(detail[:200], request=r.request, response=r)
                        r.raise_for_status()
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if not chunk or chunk == "[DONE]":
                            continue
                        try:
                            data = json.loads(chunk)
                        except ValueError:
                            continue
                        for cand in data.get("candidates") or []:
                            for part in (cand.get("content") or {}).get("parts") or []:
                                # A reasoning part is marked `thought`, not the answer.
                                if not part.get("thought") and part.get("text"):
                                    produced = True
                                    yield part["text"]
            return
        except Exception as exc:  # noqa: BLE001
            # Once text has reached the customer the answer cannot be restarted
            # without repeating itself, so only a failure BEFORE the first token
            # is retried.
            if produced or attempt == 3:
                raise
            log.warning("gemini stream retry %d after %s", attempt + 1, exc)
            await asyncio.sleep(delay)
            delay *= 2


async def _stream_openai(cfg: Dict, system: str, history: List[Dict]) -> AsyncIterator[str]:
    base = (cfg["ai_base_url"] or "https://api.openai.com/v1").rstrip("/")
    msgs = [{"role": "system", "content": system}]
    for h in history:
        msgs.append({"role": "assistant" if h["role"] == "model" else "user",
                     "content": h["text"]})
    body = {"model": cfg["ai_model"] or "gpt-4o-mini", "temperature": 0.4,
            "max_tokens": MAX_OUTPUT_TOKENS, "messages": msgs, "stream": True}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        async with client.stream("POST", f"{base}/chat/completions", json=body,
                                 headers={"Authorization": f"Bearer {cfg['ai_api_key']}"}) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if not chunk or chunk == "[DONE]":
                    continue
                try:
                    data = json.loads(chunk)
                except ValueError:
                    continue
                delta = ((data.get("choices") or [{}])[0].get("delta") or {}).get("content")
                if delta:
                    yield delta


async def stream_answer(facts: str, history: List[Dict], brand: str) -> AsyncIterator[str]:
    """Yield the answer in pieces, for a live draft.

    History is [{role: "user"|"model", text: str}, ...], oldest first, with the
    customer's newest message last.
    """
    cfg = await ai_settings()
    support = (await get_setting("support_username", "") or "").strip()
    system = (
        SYSTEM_PROMPT.format(brand=brand or "ما", support=("@" + support) if support else "پشتیبانی")
        + "\n\n=== دانش پشتیبانی ===\n" + knowledge_block()
        + "\n\n=== FACTS (تنها منبع معتبر اعداد) ===\n" + facts
    )
    streamer = _stream_gemini if cfg["ai_provider"] == "gemini" else _stream_openai
    async for piece in streamer(cfg, system, history[-HISTORY_TURNS * 2:]):
        yield piece


# ───────────────────────────── per-user throttle ─────────────────────────────
_USED: Dict[int, List[float]] = {}
RATE_LIMIT = 20          # questions
RATE_WINDOW = 3600       # per hour, per user


def take_slot(user_id: int) -> bool:
    """One question's worth of budget, or False when the user has had their hour's
    share. The model is billed per call; without this one stuck customer tapping
    "why is it slow" can run up the owner's bill on their own."""
    now = time.time()
    hits = [t for t in _USED.get(user_id, []) if now - t < RATE_WINDOW]
    if len(hits) >= RATE_LIMIT:
        _USED[user_id] = hits
        return False
    hits.append(now)
    _USED[user_id] = hits
    return True
