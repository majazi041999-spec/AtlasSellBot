"""The AI analyst's failure paths — the only part of it an owner ever debugs.

Plain `python tests/test_ai_analyst.py`.

WHAT IS BEING PROTECTED. When the analysis works, nobody needs help. When it
does not, the message on screen is the entire support experience, and the
default was actively misleading: a 404 came back as "سرویس هوش مصنوعی خطا داد
(404)", which reads as "the service is broken" and sends the owner off to
re-check an API key that was never the problem.

For Gemini a 404 means exactly one thing — this project has no model by that
name. Model ids belong to Google and get renamed and retired on their schedule,
so any name hard-coded in this repo is a future 404 waiting to happen. The only
answer that keeps working is to ask the key which models it actually has, which
is what these tests pin down.
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(tempfile.mkdtemp(prefix="atlas-ai-"))

import httpx  # noqa: E402

from core.database import init_db, set_setting  # noqa: E402
import core.ai_analyst as ai  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAILED = []


def check(label, got, want):
    ok = got == want
    print(f"   {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f"  (expected {want!r})"))
    if not ok:
        FAILED.append(label)


MODELS = {"models": [
    {"name": "models/gemini-3-pro", "displayName": "Gemini 3 Pro",
     "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3-flash", "displayName": "Gemini 3 Flash",
     "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/text-embedding-004", "displayName": "Embeddings",
     "supportedGenerationMethods": ["embedContent"]},
]}

STATS = {"today": "2026-08-31", "revenue_series_long": [], "forecast": {}, "totals": {}}


class Resp:
    def __init__(self, status, data):
        self.status_code, self._d = status, data

    def json(self):
        return self._d

    @property
    def text(self):
        return str(self._d)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=self)


def client(post_status=404, get_status=200):
    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, **k):
            return Resp(post_status, {"error": {"message": "x"}})
        async def get(self, url, **k):
            return Resp(get_status, MODELS if get_status == 200 else {})
    return C


async def main():
    await init_db()
    for k, v in (("ai_enabled", "1"), ("ai_provider", "gemini"),
                 ("ai_api_key", "AIza-not-a-real-key"),
                 # With the "models/" prefix, because that is how Google's own
                 # console displays an id and therefore how people paste it.
                 ("ai_model", "models/gemini-2.5-flash")):
        await set_setting(k, v)

    print("1. the model list only offers models that can answer")
    ai.httpx.AsyncClient = client()
    lm = await ai.list_models()
    check("the list is readable", lm["ok"], True)
    # An embedding model is in the same list and would fail at run time with a
    # 400, which is a worse error than the one being fixed.
    check("embedding models are excluded", [m["id"] for m in lm["models"]],
          ["gemini-3-flash", "gemini-3-pro"])
    check("a flash-class model is offered first", lm["models"][0]["id"], "gemini-3-flash")
    check("the pasted models/ prefix is stripped", lm["current"], "gemini-2.5-flash")

    print("\n2. a 404 names the models that DO exist")
    r = await ai.analyze(STATS)
    check("it is not reported as a bare transport error", r["error"], "model_not_found")
    check("the message names a model they can actually use",
          "gemini-3-flash" in r["message"], True)
    # The point is not that the word "key" never appears — the message says the
    # model is missing ON this key, which is accurate. The point is that it
    # names the failing model and sends them to the model setting, rather than
    # sending them off to re-issue a key that was never wrong.
    check("it names the model that failed",
          "gemini-2.5-flash" in r["message"], True)
    check("and points at the settings, not at re-issuing a key",
          "تنظیمات" in r["message"], True)
    check("the list is machine-readable too, for the settings page",
          [m["id"] for m in r.get("models", [])], ["gemini-3-flash", "gemini-3-pro"])

    print("\n3. when the list cannot be read, it does not invent one")
    ai.httpx.AsyncClient = client(get_status=403)
    r = await ai.analyze(STATS)
    check("still identified as a model problem", r["error"], "model_not_found")
    check("but no models are claimed", "models" in r, False)

    print("\n4. auth and quota keep their own, more useful messages")
    ai.httpx.AsyncClient = client(post_status=403)
    r = await ai.analyze(STATS)
    check("403 is auth-or-region, not a missing model", r["error"], "auth_or_region")
    # Gemini is blocked from Iran, so 403 is very often geography rather than a
    # bad key — telling someone to re-check a correct key wastes their day.
    check("...and says so", "مسدود" in r["message"], True)
    ai.httpx.AsyncClient = client(post_status=429)
    check("429 is quota", (await ai.analyze(STATS))["error"], "quota")

    print("\n5. an openai-compatible 404 blames the base URL, which is what it is")
    await set_setting("ai_provider", "openai")
    await set_setting("ai_base_url", "https://openrouter.ai/api")   # missing /v1
    ai.httpx.AsyncClient = client(get_status=403)
    r = await ai.analyze(STATS)
    check("it points at the address, not the model", "/v1" in r["message"], True)

    print("\n" + ("ALL PASSED" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
