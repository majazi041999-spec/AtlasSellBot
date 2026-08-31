"""Optional AI business analyst for the admin panel.

THE ONE RULE: THE MODEL NEVER PRODUCES A NUMBER.

Every figure — revenue, the forecast, growth, churn — is computed in
`core/forecast.py` and `core/database.py` and handed to the model already
finished. The model's job is the part it is actually good at: reading those
figures and saying what changed, what is at risk and what to do about it this
week. Ask a language model to forecast revenue and it will return a confident,
plausible, wrong number, and the owner will plan around it. So the prompt states
the figures are authoritative, the schema has no field for a new number, and the
panel renders its charts from the deterministic series regardless of what comes
back.

WHAT IS SENT. Aggregates only: daily revenue and order counts, the forecast, and
a handful of ratios. Never a customer row, a telegram id, a subscription token, a
username, a phone number or a card number. `build_payload` is the ONLY place that
decides this, and it builds an allowlist rather than filtering a larger object —
a filter forgets a field the day someone adds one.

BEFORE THE OWNER TURNS THIS ON. It sends their real revenue figures to a third
party. On free tiers that is usually the WORSE deal: providers commonly reserve
the right to use free-tier traffic to improve their models, where paid traffic is
excluded. The panel says so at the point of enabling it, and the feature ships
switched off.

PROVIDERS. Gemini's free tier (Flash models, no card) is the default target, but
it is blocked in Iran under US sanctions — which matters for an Iranian operator
whose server may or may not be abroad. So there is a second provider that speaks
the OpenAI-compatible `/chat/completions` shape, which lets any gateway
(OpenRouter, Groq, a self-hosted proxy) be pointed at it with a base URL and key.
Neither is required: with no key configured the panel simply shows the
deterministic analysis, which is the part that carries the numbers anyway.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional

import httpx

from core.database import get_setting

logger = logging.getLogger(__name__)

TIMEOUT = 45.0
# Room for the answer AND for whatever the model thinks first.
#
# 2048 was the original figure and it was the cause of a silent failure: from
# Gemini 2.5 onward the model reasons before answering and those reasoning
# tokens are charged against this same budget. The model spent the allowance
# thinking, hit the ceiling mid-sentence, and returned truncated JSON — which
# arrived here as "bad_output", a message that blames the model's manners
# rather than our budget. Thinking is switched off below where the model
# supports it, and this is the headroom for the models where it cannot be.
MAX_OUTPUT_TOKENS = 8192

# Free-tier defaults. Flash is the right tier here: this runs a few times a day
# on a page of numbers, so the reasoning tiers would buy nothing but latency.
DEFAULTS = {
    "ai_enabled": "0",
    "ai_provider": "gemini",          # gemini | openai
    "ai_model": "gemini-2.5-flash",
    "ai_base_url": "",                # only for the openai-compatible provider
    "ai_api_key": "",
}

SYSTEM_PROMPT = """تو یک تحلیل‌گر ارشد کسب‌وکار هستی که برای صاحب یک سرویس فروش اشتراک VPN در ایران کار می‌کنی.

قوانینی که هرگز نباید بشکنی:
۱. همه‌ی اعداد در داده‌ی ورودی، قطعی و محاسبه‌شده‌اند. آن‌ها را عیناً به کار ببر.
۲. هیچ عدد جدیدی نساز. پیش‌بینی نکن، برآورد نکن، درصد از خودت در نیاور.
   اگر عددی در داده نیست، بگو «در داده نیست» — حدس نزن.
۳. اگر داده برای یک نتیجه‌گیری کافی نیست، همین را بگو. نتیجه‌گیریِ ضعیف بدتر از سکوت است.
۴. فارسی بنویس، کوتاه و عملیاتی. صاحب کسب‌وکار وقت ندارد؛ او باید بداند
   «چه چیزی عوض شد» و «این هفته چه کار کنم».
۵. هر پیشنهاد باید مشخص و قابل انجام باشد، نه توصیه‌ی کلی. «کیفیت را بالا ببر» بی‌فایده است؛
   «۵۵ اشتراکی که تا ۷ روز دیگر منقضی می‌شوند را با کد تخفیف هدف بگیر» مفید است.

زمینه‌ی کسب‌وکار که باید در تحلیل لحاظ کنی:
- درآمد از دو کانال می‌آید: مشتری مستقیم، و نماینده‌ها (که عمده می‌خرند و سبد خریدشان بزرگ‌تر است).
- خریدهای نماینده‌ها انفجاری است؛ یک سفارش بزرگ می‌تواند یک روز را غیرعادی نشان دهد. این را با نوسان طبیعی اشتباه نگیر.
- تمدید اشتراک‌های در حال انقضا، قابل‌پیش‌بینی‌ترین منبع درآمد آینده است.
- هفته‌ی کاری از شنبه شروع می‌شود؛ الگوی هفتگی طبیعی است، نه مشکل.

فقط و فقط یک شیء JSON برگردان، بدون هیچ متن اضافه‌ای دور آن."""

# The model returns a fixed shape so the panel can render it. Note there is no
# field anywhere for a figure of the model's own — by construction.
RESPONSE_SHAPE = {
    "headline": "یک جمله: وضعیت کسب‌وکار همین حالا",
    "summary": "دو تا چهار جمله تحلیل",
    "findings": [
        {"title": "…", "detail": "…", "severity": "good | watch | risk",
         "based_on": "کدام عدد از داده این را می‌گوید"}
    ],
    "actions": [
        {"title": "…", "why": "…", "effort": "low | medium | high"}
    ],
    "confidence": "high | medium | low",
    "confidence_reason": "چرا",
}


async def settings() -> Dict[str, str]:
    out = {}
    for key, default in DEFAULTS.items():
        out[key] = (await get_setting(key, default) or "").strip()
    return out


async def is_configured() -> bool:
    s = await settings()
    return s["ai_enabled"] == "1" and bool(s["ai_api_key"])


_SAFE_TEXT = re.compile(r"[^\w\s؀-ۿ.,:%()\-/]+")


def _clean(value: str, limit: int = 60) -> str:
    """Strip anything exotic out of a free-text label before it reaches a prompt.

    Package and brand names are owner- or reseller-supplied, so they are the one
    part of this payload that someone else writes. Nothing here is trusted enough
    to carry instructions.
    """
    return _SAFE_TEXT.sub(" ", str(value or ""))[:limit].strip()


def build_payload(stats: Dict) -> Dict:
    """The exact object sent to the provider — an allowlist, built field by field.

    Deliberately NOT "take the analytics dict and delete the sensitive keys":
    that approach leaks the first time somebody adds a field upstream. If a
    number is not named here, it is not sent.
    """
    fc = stats.get("forecast") or {}
    acc = fc.get("accuracy") or {}
    band = fc.get("band") or {}
    drivers = fc.get("drivers") or {}
    return {
        "currency": "toman",
        "today": stats.get("today"),
        "revenue_daily": [
            {"date": r.get("date"), "revenue": int(r.get("revenue") or 0),
             "orders": int(r.get("orders") or 0)}
            for r in (stats.get("revenue_series") or [])[-60:]
        ],
        "totals": {
            "revenue_30d": int(stats.get("revenue_30d") or 0),
            "orders_30d": int(stats.get("orders_30d") or 0),
            "revenue_prev_30d": int(stats.get("revenue_prev_30d") or 0),
            "new_users_30d": int(stats.get("new_users_30d") or 0),
            "active_subscriptions": int(stats.get("active_subs") or 0),
        },
        "mix": {
            "reseller_revenue_share_pct": stats.get("reseller_share_pct"),
            "renewal_revenue_share_pct": stats.get("renewal_share_pct"),
        },
        "pipeline": {
            "subscriptions_expiring_7d": int(stats.get("expiring_7d") or 0),
            "subscriptions_expiring_30d": int(stats.get("expiring_30d") or 0),
            "historical_renewal_rate_pct": stats.get("renewal_rate_pct"),
        },
        "forecast": {
            "horizon_days": fc.get("horizon"),
            "total": fc.get("total"),
            "typical_range": {"low": band.get("low"), "high": band.get("high")},
            "measured_error_pct": acc.get("smape"),
            "orders_per_day": drivers.get("orders_per_day"),
            "avg_basket": drivers.get("avg_basket"),
            "method": fc.get("method"),
        },
        "top_packages": [
            {"name": _clean(p.get("name")), "orders": int(p.get("orders") or 0),
             "revenue": int(p.get("revenue") or 0)}
            for p in (stats.get("top_packages") or [])[:8]
        ],
    }


def _user_prompt(payload: Dict) -> str:
    return (
        "داده‌ی کسب‌وکار (همه‌ی اعداد قطعی و محاسبه‌شده‌اند):\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=1)
        + "\n\nبا این ساختار دقیق پاسخ بده (فقط JSON):\n"
        + json.dumps(RESPONSE_SHAPE, ensure_ascii=False, indent=1)
        + "\n\nحداکثر ۵ مورد در findings و حداکثر ۴ مورد در actions."
        + "\nهر مورد در findings باید در based_on به عددی از همین داده اشاره کند."
    )


def _extract_json(text: str) -> Optional[Dict]:
    """Models wrap JSON in prose or fences no matter how firmly you ask."""
    if not text:
        return None
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    start, end = t.find("{"), t.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(t[start:end + 1])
        except Exception:
            return None
    return None


def _clean_model(name: str) -> str:
    """Accept what people actually paste.

    Google's own console shows model ids as `models/gemini-x`, and the docs
    show them bare. Pasting the first form produced a URL with `models/` twice
    and a 404 that blamed the model rather than the paste.
    """
    m = str(name or "").strip()
    if m.lower().startswith("models/"):
        m = m[7:]
    return m.strip()


async def list_models(cfg: Optional[Dict] = None) -> Dict:
    """Which models can THIS key actually use?

    Exists because a 404 from Gemini means "no such model for this project",
    and the only honest answer to that is a list of the ones that do exist —
    Google renames and retires model ids on its own schedule, so any name
    hard-coded here is a future 404. Asking the key is the version that keeps
    working.
    """
    cfg = cfg or await settings()
    key = (cfg.get("ai_api_key") or "").strip()
    if not key:
        return {"ok": False, "error": "no_key", "message": "اول کلید API را ذخیره کن."}

    provider = cfg.get("ai_provider") or "gemini"
    if provider == "openai":
        base = (cfg.get("ai_base_url") or "https://api.openai.com/v1").rstrip("/")
        url, headers = f"{base}/models", {"Authorization": f"Bearer {key}"}
    else:
        url = "https://generativelanguage.googleapis.com/v1beta/models"
        headers = {"x-goog-api-key": key}

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        if code in (401, 403):
            return {"ok": False, "error": "auth_or_region",
                    "message": ("کلید پذیرفته نشد، یا این سرویس از کشور این سرور در "
                                "دسترس نیست (Gemini در ایران مسدود است).")}
        return {"ok": False, "error": f"http_{code}",
                "message": f"فهرست مدل‌ها خوانده نشد ({code})."}
    except Exception as e:
        logger.warning("ai model list failed: %s", e)
        return {"ok": False, "error": "network",
                "message": "ارتباط با سرویس برقرار نشد."}

    models = []
    if provider == "openai":
        for m in (data.get("data") or []):
            mid = str(m.get("id") or "").strip()
            if mid:
                models.append({"id": mid, "label": mid})
    else:
        for m in (data.get("models") or []):
            # Only the ones that can actually answer a generateContent call —
            # embedding models are in this list too and would 400 at run time.
            if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                continue
            mid = _clean_model(m.get("name") or "")
            if not mid:
                continue
            models.append({"id": mid,
                           "label": (m.get("displayName") or mid).strip()})
    # Cheapest-looking first: a flash-class model is the right default for one
    # page of numbers, and putting it at the top makes the good choice the easy one.
    models.sort(key=lambda m: (0 if "flash" in m["id"].lower() else 1, m["id"]))
    return {"ok": True, "provider": provider, "models": models,
            "current": _clean_model(cfg.get("ai_model") or "")}


async def _call_gemini(cfg: Dict, prompt: str) -> str:
    model = _clean_model(cfg["ai_model"]) or "gemini-2.5-flash"
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent")
    gen = {
        "temperature": 0.3,               # analysis, not creative writing
        "maxOutputTokens": MAX_OUTPUT_TOKENS,
        "responseMimeType": "application/json",
    }

    async def ask(with_thinking_off: bool) -> Dict:
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": dict(gen),
        }
        if with_thinking_off:
            # This job is "read twenty numbers and say what they mean". The
            # model does not need to deliberate, and on 2.5+ deliberation eats
            # the output budget until the answer is cut off mid-JSON.
            body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(url, json=body,
                                  headers={"x-goog-api-key": cfg["ai_api_key"]})
            r.raise_for_status()
            return r.json()

    try:
        data = await ask(True)
    except httpx.HTTPStatusError as e:
        # Older models reject thinkingConfig outright. Retry without it rather
        # than reporting a 400 the owner cannot act on.
        if e.response.status_code == 400 and "thinking" in (e.response.text or "").lower():
            data = await ask(False)
        else:
            raise

    cand = (data.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    # A reasoning part is marked `thought` and is NOT the answer. Concatenating
    # it produced prose in front of the JSON and, when the answer itself was
    # truncated, nothing but prose.
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    return {"text": text,
            "finish_reason": cand.get("finishReason") or "",
            "usage": data.get("usageMetadata") or {}}


async def _call_openai_compatible(cfg: Dict, prompt: str) -> str:
    base = (cfg["ai_base_url"] or "https://api.openai.com/v1").rstrip("/")
    body = {
        "model": cfg["ai_model"] or "gpt-4o-mini",
        "temperature": 0.3,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(f"{base}/chat/completions", json=body,
                              headers={"Authorization": f"Bearer {cfg['ai_api_key']}"})
        r.raise_for_status()
        data = r.json()
    return (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")


def _normalise(obj: Dict) -> Dict:
    """Coerce whatever came back into the shape the panel renders.

    A model that returns a string where a list belongs must not blank the page,
    and it must not be able to inject markup through a field either.
    """
    def txt(v, limit=400):
        return _SAFE_TEXT.sub(" ", str(v or ""))[:limit].strip()

    findings: List[Dict] = []
    for f in (obj.get("findings") or [])[:5]:
        if not isinstance(f, dict):
            f = {"title": f}
        sev = str(f.get("severity") or "watch").lower()
        findings.append({
            "title": txt(f.get("title"), 120),
            "detail": txt(f.get("detail"), 400),
            "severity": sev if sev in ("good", "watch", "risk") else "watch",
            "based_on": txt(f.get("based_on"), 160),
        })
    actions: List[Dict] = []
    for a in (obj.get("actions") or [])[:4]:
        if not isinstance(a, dict):
            a = {"title": a}
        eff = str(a.get("effort") or "medium").lower()
        actions.append({
            "title": txt(a.get("title"), 120),
            "why": txt(a.get("why"), 300),
            "effort": eff if eff in ("low", "medium", "high") else "medium",
        })
    conf = str(obj.get("confidence") or "medium").lower()
    return {
        "headline": txt(obj.get("headline"), 160),
        "summary": txt(obj.get("summary"), 900),
        "findings": findings,
        "actions": actions,
        "confidence": conf if conf in ("high", "medium", "low") else "medium",
        "confidence_reason": txt(obj.get("confidence_reason"), 200),
    }


async def analyze(stats: Dict) -> Dict:
    """Run the analysis. Never raises — the panel must survive every failure.

    Returns ``{"ok": True, "analysis": {...}, "provider": ..., "model": ...}`` or
    ``{"ok": False, "error": <code>, "message": <persian>}``.
    """
    cfg = await settings()
    if cfg["ai_enabled"] != "1":
        return {"ok": False, "error": "disabled",
                "message": "تحلیل هوش مصنوعی خاموش است. از تنظیمات روشنش کن."}
    if not cfg["ai_api_key"]:
        return {"ok": False, "error": "no_key",
                "message": "کلید API تنظیم نشده است."}

    payload = build_payload(stats)
    prompt = _user_prompt(payload)
    try:
        meta = {}
        if cfg["ai_provider"] == "openai":
            raw = await _call_openai_compatible(cfg, prompt)
        else:
            result = await _call_gemini(cfg, prompt)
            raw, meta = result["text"], result
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        if code in (401, 403):
            # 403 from Gemini is very often the sanctions geo-block rather than a
            # bad key, and telling someone to re-check a correct key wastes their
            # afternoon.
            msg = ("کلید API پذیرفته نشد. اگر کلید درست است، ممکن است سرویس از "
                   "کشور این سرور در دسترس نباشد (Gemini در ایران مسدود است) — "
                   "می‌توانی به‌جایش یک سرویس سازگار با OpenAI تنظیم کنی.")
            return {"ok": False, "error": "auth_or_region", "message": msg}
        if code == 429:
            return {"ok": False, "error": "quota",
                    "message": "سهمیه‌ی رایگان امروز تمام شده. فردا دوباره امتحان کن."}
        if code == 404:
            # For Gemini this is never the key and never the URL — it is "this
            # project has no model by that name". Google renames and retires
            # model ids on its own schedule, so the useful answer is the list of
            # ones that DO exist on this key, not a status code.
            listed = await list_models(cfg)
            if listed.get("ok") and listed.get("models"):
                names = "، ".join(m["id"] for m in listed["models"][:6])
                return {"ok": False, "error": "model_not_found",
                        "models": listed["models"],
                        "message": (f"مدل «{_clean_model(cfg['ai_model'])}» روی این کلید وجود ندارد. "
                                    f"مدل‌های در دسترس تو: {names}. "
                                    "یکی از این‌ها را در تنظیمات بگذار.")}
            if cfg["ai_provider"] == "openai":
                return {"ok": False, "error": "model_not_found",
                        "message": ("آدرس پایه یا نام مدل درست نیست. آدرس باید تا "
                                    "/v1 باشد، مثل https://openrouter.ai/api/v1")}
            return {"ok": False, "error": "model_not_found",
                    "message": (f"مدل «{_clean_model(cfg['ai_model'])}» پیدا نشد و فهرست "
                                "مدل‌ها هم خوانده نشد. نام مدل را در تنظیمات بررسی کن.")}
        logger.warning("ai analyst HTTP %s: %s", code, e.response.text[:300])
        return {"ok": False, "error": f"http_{code}",
                "message": f"سرویس هوش مصنوعی خطا داد ({code})."}
    except (httpx.TimeoutException, httpx.RequestError) as e:
        logger.warning("ai analyst network error: %s", e)
        return {"ok": False, "error": "network",
                "message": "ارتباط با سرویس هوش مصنوعی برقرار نشد."}
    except Exception as e:
        logger.exception("ai analyst failed: %s", e)
        return {"ok": False, "error": "internal", "message": "تحلیل ناموفق بود."}

    parsed = _extract_json(raw)
    if not isinstance(parsed, dict):
        finish = str(meta.get("finish_reason") or "")
        usage = meta.get("usage") or {}
        logger.warning("ai analyst unparseable output: finish=%s usage=%s raw=%s",
                       finish, usage, (raw or "")[:400])
        if finish.upper() in ("MAX_TOKENS", "LENGTH"):
            # The honest diagnosis, and one the owner can act on: the answer was
            # cut off, not malformed. Naming the model matters because the fix
            # is usually to pick one that does not reason before answering.
            return {"ok": False, "error": "truncated",
                    "message": ("پاسخ مدل نصفه ماند (سقف توکن). معمولاً یعنی مدل قبل از "
                                "جواب‌دادن «فکر» می‌کند و بودجه تمام می‌شود. یک مدل "
                                f"سبک‌تر مثل flash را امتحان کن (الان: {_clean_model(cfg['ai_model'])}).")}
        if finish.upper() in ("SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST"):
            return {"ok": False, "error": "blocked",
                    "message": f"سرویس پاسخ را مسدود کرد ({finish}). مدل دیگری را امتحان کن."}
        if not (raw or "").strip():
            return {"ok": False, "error": "empty_output",
                    "message": ("مدل هیچ متنی برنگرداند"
                                + (f" ({finish})" if finish else "")
                                + ". معمولاً با انتخاب یک مدل flash حل می‌شود.")}
        return {"ok": False, "error": "bad_output",
                "message": ("پاسخ سرویس قابل خواندن نبود"
                            + (f" ({finish})" if finish else "")
                            + ". اگر تکرار شد، مدل دیگری را امتحان کن.")}

    return {"ok": True, "analysis": _normalise(parsed),
            "provider": cfg["ai_provider"], "model": cfg["ai_model"]}
