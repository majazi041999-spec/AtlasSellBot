"""Representative API routes — ``/api/rep/v1/*``.

A representative pastes an API key into their own bot/panel; that software then
sells on our infrastructure: it creates services, renews them, revokes links and
reads usage, spending the rep's wallet balance. The credential/limit layer is
``core/rep_api.py`` — read its docstring first.

Design rules this file must keep:

* **Never mount under ``/{WEB_SECRET_PATH}/``.** The base URL is handed to third
  parties; putting the admin panel's secret prefix in it would publish the panel
  address. Same reasoning as ``core/client_app.py``.
* **Every query is scoped to ``ctx["user"]["id"]``.** A key identifies a
  representative; there is no path here that reads or writes another account's
  rows, and none may ever be added.
* **Money paths reuse the platform engine, not a copy of it.** Prices come from
  ``core.pricing``, provisioning from ``core.multi_subscription``. A second
  pricing implementation would drift from the bot and silently over/undercharge.
* **No Telegram messages on API actions.** A reseller's bot creating 40 services
  must not put 40 messages in the rep's own chat — their bot already has the
  result in the HTTP response. Everything is still recorded as a normal order,
  so the admin panel and the rep report show it.
* **The response body is the receipt.** If provisioning half-fails we refund the
  difference in the same request and report exactly what was created; the caller
  never has to reconcile a partial charge.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from core import rep_api
from core import rep_sandbox as sandbox
from core.client_app import client_ip
from core.database import (
    add_user_balance,
    count_rep_test_today,
    add_rep_test_account,
    create_custom_order,
    get_package,
    get_packages,
    get_rep_financials,
    get_setting,
    get_subscription_nodes,
    get_subscription_profile,
    get_user_balance,
    get_user_orders_full,
    get_user_pricing,
    get_user_subscription_profiles,
    get_user_total_topups,
    get_wallet_transactions,
    update_order,
    update_subscription_profile,
)
from core.multi_subscription import (
    create_profile_for_order,
    create_test_subscription,
    delete_subscription_profile_remote,
    renew_subscription_profile,
    rotate_subscription_link,
    set_nodes_enabled,
    subscription_url,
    subscription_error_message,
)
from core.pricing import compute_package_price, is_unlimited_package

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rep")

API_VERSION = "1.0"
GB = 1024 ** 3

# One request may provision at most this many services. Each unit writes a
# client to EVERY node, so a batch of 10 is already dozens of x-ui round trips
# inside one HTTP request; larger batches would time out and hammer the panels.
MAX_BATCH = 10

# The API's own sort/filter vocabulary. Deliberately NOT shared with the panel's
# SUB_SORTS: this is a published contract for third-party code, so it changes
# only when we decide to change it, never as a side effect of a panel tweak.
SERVICE_SORTS = ("newest", "oldest", "name_az", "expiry_soon", "usage_desc")
SERVICE_FILTERS = ("all", "active", "inactive", "expired", "expiring", "near_limit", "unlimited")


# ═══════════════════════════════ plumbing ════════════════════════════════════
def _json(data: Dict, status: int = 200, ctx: Optional[Dict] = None) -> JSONResponse:
    headers = {
        # Every response is account-specific; an intermediate cache would serve
        # one representative's services to another.
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "X-Api-Version": API_VERSION,
    }
    if ctx and ctx.get("rate"):
        limit, remaining, reset_in = ctx["rate"]
        headers["X-RateLimit-Limit"] = str(limit)
        headers["X-RateLimit-Remaining"] = str(remaining)
        headers["X-RateLimit-Reset"] = str(reset_in)
    return JSONResponse(data, status_code=status, headers=headers)


def _err_body(code: str, message: str, **extra) -> Dict:
    """Errors are machine-first (``error``) with a Persian ``message`` a rep can
    show their own customer without translating."""
    body = {"ok": False, "error": code, "message": message}
    if extra:
        body.update(extra)
    return body


def _err(code: str, message: str, status: int = 400, ctx: Optional[Dict] = None, **extra) -> JSONResponse:
    return _json(_err_body(code, message, **extra), status, ctx)


def _bearer(request: Request) -> str:
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.headers.get("x-api-key") or "").strip()


async def _api_enabled() -> bool:
    return str(await get_setting("rep_api_enabled", "1") or "1").strip() not in ("0", "false", "off")


async def authorize(request: Request, scope: str = "read") -> Tuple[Optional[Dict], Optional[JSONResponse]]:
    """Authenticate + authorise one call. Returns ``(ctx, error_response)``.

    Order matters: the cheap in-memory checks come last on purpose — a caller
    must not be able to tell a valid key from an invalid one by which limit
    they hit first.
    """
    if not await _api_enabled():
        return None, _err("api_disabled", "سرویس API موقتاً غیرفعال است.", 503)

    token = _bearer(request)
    if not token:
        return None, _err("missing_key", "کلید API ارسال نشده است. هدر Authorization: Bearer <key> را بفرست.", 401)

    auth = await rep_api.authenticate(token)
    if not auth:
        return None, _err("invalid_key", "کلید API نامعتبر یا لغو شده است.", 401)

    user, key = auth["user"], auth["key"]
    if not int(user.get("is_wholesale") or 0):
        return None, _err("not_a_representative", "این حساب دیگر نماینده نیست.", 403)
    if int(user.get("is_blocked") or 0):
        return None, _err("account_blocked", "حساب شما مسدود است. با پشتیبانی تماس بگیرید.", 403)

    ip = client_ip(request)
    if not rep_api.ip_allowed(key.get("ip_allowlist") or "", ip):
        return None, _err("ip_not_allowed", "این IP در لیست مجاز کلید شما نیست.", 403)

    if scope not in str(key.get("scopes") or "").split(","):
        return None, _err("insufficient_scope",
                          f"کلید شما دسترسی «{scope}» ندارد.", 403, required_scope=scope)

    limit = int(key.get("rate_per_min") or rep_api.DEFAULT_RATE_PER_MIN)
    allowed, remaining, reset_in = rep_api.rate_check(int(key["id"]), limit)
    ctx = {"user": user, "key": key, "ip": ip, "rate": (limit, remaining, reset_in)}
    if not allowed:
        resp = _err("rate_limited", f"تعداد درخواست‌ها بیش از حد مجاز ({limit} در دقیقه) است.",
                    429, ctx, retry_after=reset_in)
        resp.headers["Retry-After"] = str(reset_in)
        return None, resp

    await rep_api.touch(int(key["id"]), ip)
    return ctx, None


async def _body(request: Request) -> Dict:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _clean_name(value, limit: int = 40) -> str:
    """Persian-friendly service name. Same character class the mini-app uses so
    a name created here looks identical to one created in the app."""
    return re.sub(r"[^\w \-]+", "", str(value or ""), flags=re.UNICODE).strip()[:limit]


def _as_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ═══════════════════════════════ serialisers ═════════════════════════════════
def _service_status(p: Dict, now_ms: int) -> str:
    total = int(float(p.get("traffic_gb") or 0) * GB)
    used = int(p.get("used_bytes") or 0)
    expire_ms = int(p.get("expire_timestamp") or 0)
    expired = 0 < expire_ms <= now_ms
    depleted = total > 0 and used >= total
    if not int(p.get("is_active") or 0):
        return "expired" if expired else ("depleted" if depleted else "disabled")
    if int(p.get("starts_on_first_use") or 0) and int(p.get("first_use_at") or 0) <= 0:
        return "pending"
    return "active"


def _service_payload(p: Dict, sub_url: str, now_ms: int, nodes: Optional[List[Dict]] = None) -> Dict:
    total = int(float(p.get("traffic_gb") or 0) * GB)
    used = int(p.get("used_bytes") or 0)
    expire_ms = int(p.get("expire_timestamp") or 0)
    out = {
        "id": int(p["id"]),
        "name": p.get("name") or p.get("email") or "",
        "email": p.get("email") or "",
        "status": _service_status(p, now_ms),
        "is_active": bool(int(p.get("is_active") or 0)),
        "unlimited": total <= 0,
        # 0 GB means unlimited volume — never render it as "zero traffic left".
        "traffic_gb": float(p.get("traffic_gb") or 0),
        "used_bytes": used,
        "remaining_bytes": max(0, total - used) if total > 0 else None,
        "usage_percent": round(min(100.0, used / total * 100), 2) if total > 0 else None,
        "expires_at": expire_ms,
        "days_left": max(0, int((expire_ms - now_ms) / 86_400_000)) if expire_ms > 0 else None,
        "starts_on_first_use": bool(int(p.get("starts_on_first_use") or 0)),
        "first_use_at": int(p.get("first_use_at") or 0),
        "duration_days": int(p.get("duration_days") or 0),
        "created_at": p.get("created_at") or "",
        "subscription_url": sub_url,
    }
    if nodes is not None:
        out["nodes"] = [{
            "label": n.get("node_label") or n.get("server_name") or "",
            "is_active": bool(int(n.get("is_active") or 0)),
            "link": (n.get("link") or "").strip() if int(n.get("is_active") or 0) else "",
        } for n in nodes]
    return out


def _package_payload(pkg: Dict, priced: Dict) -> Dict:
    return {
        "id": int(pkg["id"]),
        "name": pkg.get("name") or "",
        "traffic_gb": float(pkg.get("traffic_gb") or 0),
        "duration_days": int(pkg.get("duration_days") or 0),
        "unlimited": is_unlimited_package(pkg),
        "price": int(priced["final"]),
        "description": pkg.get("description") or "",
    }


async def _profile_or_error(profile_id: int, ctx: Dict) -> Tuple[Optional[Dict], Optional[JSONResponse]]:
    """Load a service and prove it belongs to the calling representative.

    A wrong owner returns 404, not 403: telling a caller that id 812 exists but
    is someone else's is an enumeration oracle over the whole customer base.
    """
    profile = await get_subscription_profile(int(profile_id or 0))
    if not profile or int(profile.get("user_id") or 0) != int(ctx["user"]["id"]):
        return None, _err("service_not_found", "سرویسی با این شناسه برای شما یافت نشد.", 404, ctx)
    return profile, None


# ═══════════════════════════════ pricing ═════════════════════════════════════
async def _resolve_plan(body: Dict, user: Dict) -> Dict:
    """Turn a request body into ``{traffic_gb, duration_days, unit_price, ...}``.

    Two shapes are accepted: a ``package_id`` (priced by ``core.pricing``, the
    same numbers the bot shows the rep), or a custom ``traffic_gb`` +
    ``duration_days`` priced off the rep's own per-GB / unlimited rate.

    When the rep has no custom rate we refuse rather than inventing one. The
    bot's bulk flow falls back to a hard-coded 10,000/GB; charging that through
    an API — where nobody reads a confirmation screen — would be a silent
    mispricing, so the caller is told to use a package instead.
    """
    pricing = await get_user_pricing(user["id"])
    pkg_id = _as_int(body.get("package_id"), 0)
    if pkg_id > 0:
        pkg = await get_package(pkg_id)
        if not pkg or not int(pkg.get("is_active") or 0):
            return {"error": "package_unavailable", "message": "پکیج انتخابی موجود یا فعال نیست."}
        priced = compute_package_price(pricing, pkg)
        return {
            "package": pkg,
            # The package's own traffic_gb is provisioned VERBATIM, including for
            # an "unlimited" plan where that number is the fair-use threshold —
            # `is_unlimited` changes how the plan is PRICED, not how much volume
            # the client gets. Zeroing it here would quietly hand API buyers
            # unlimited traffic while bot buyers got the threshold.
            "traffic_gb": float(pkg.get("traffic_gb") or 0),
            "duration_days": int(pkg.get("duration_days") or 0),
            "unit_price": int(priced["final"]),
            "label": pkg.get("name") or f"پکیج #{pkg_id}",
        }

    if "traffic_gb" not in body and "duration_days" not in body:
        return {"error": "invalid_request",
                "message": "یکی از دو حالت را بفرست: package_id، یا traffic_gb + duration_days."}

    traffic_gb = max(0.0, round(_as_float(body.get("traffic_gb"), 0.0), 3))
    duration_days = _as_int(body.get("duration_days"), 0)
    if duration_days < 1 or duration_days > 3650:
        return {"error": "invalid_request", "message": "duration_days باید بین ۱ تا ۳۶۵۰ روز باشد."}
    if traffic_gb > 10000:
        return {"error": "invalid_request", "message": "traffic_gb بیش از حد مجاز است."}

    discount = max(0.0, min(100.0, float(pricing.get("discount_percent") or 0)))
    if traffic_gb <= 0:
        base = int(pricing.get("unlimited_price") or 0)
        if base <= 0:
            return {"error": "custom_pricing_unavailable",
                    "message": "قیمت «نامحدود» برای حساب شما تنظیم نشده است. از package_id استفاده کن یا با پشتیبانی هماهنگ کن."}
    else:
        ppg = int(pricing.get("price_per_gb") or 0)
        if ppg <= 0:
            return {"error": "custom_pricing_unavailable",
                    "message": "تعرفه‌ی هر گیگ برای حساب شما تنظیم نشده است. از package_id استفاده کن یا با پشتیبانی هماهنگ کن."}
        base = int(traffic_gb * ppg)
    return {
        "package": None,
        "traffic_gb": traffic_gb,
        "duration_days": duration_days,
        "unit_price": max(0, int(base * (100 - discount) / 100)),
        "label": ("نامحدود" if traffic_gb <= 0 else f"{traffic_gb:g}GB") + f" / {duration_days} روز",
    }


async def _topup_gate(ctx: Dict) -> Optional[JSONResponse]:
    """The same minimum-topup rule the bot enforces before a rep may sell.

    Re-implemented against the same setting rather than shared with the bot's
    callback-shaped helper; if the rule changes, both must change.
    """
    user = ctx["user"]
    if not int(user.get("rep_topup_required") or 0):
        return None
    try:
        minimum = max(0, int(await get_setting("rep_min_topup", "500000") or 0))
    except (TypeError, ValueError):
        minimum = 0
    if minimum <= 0:
        return None
    total_in = await get_user_total_topups(user["id"])
    if total_in >= minimum:
        return None
    return _err("topup_required",
                f"برای شروع فروش باید حداقل {minimum:,} تومان شارژ کرده باشی (تا الان: {total_in:,} تومان).",
                403, ctx, required=minimum, deposited=total_in)


# ═══════════════════════════════ idempotency ═════════════════════════════════
async def _idem_start(request: Request, ctx: Dict, endpoint: str, body: Dict):
    """Returns ``(idem_key, replay_response)``. ``idem_key`` may be ''."""
    idem_key = (request.headers.get("idempotency-key") or "").strip()[:120]
    if not idem_key:
        return "", None
    fingerprint = rep_api.request_fingerprint(endpoint, body)
    state = await rep_api.idem_begin(int(ctx["user"]["id"]), idem_key, endpoint, fingerprint)
    if state["state"] == "replay":
        payload = dict(state["body"])
        payload["idempotent_replay"] = True
        return idem_key, _json(payload, int(state["status"]), ctx)
    if state["state"] == "in_flight":
        return idem_key, _err("request_in_flight",
                              "درخواست قبلی با همین Idempotency-Key هنوز در حال پردازش است.", 409, ctx)
    if state["state"] == "conflict":
        return idem_key, _err("idempotency_conflict",
                              "این Idempotency-Key قبلاً با محتوای متفاوتی استفاده شده است.", 409, ctx)
    return idem_key, None


async def _idem_done(ctx: Dict, idem_key: str, response: JSONResponse, payload: Dict) -> JSONResponse:
    if idem_key:
        await rep_api.idem_finish(int(ctx["user"]["id"]), idem_key, response.status_code, payload)
    return response


# ═══════════════════════════════ sandbox ═════════════════════════════════════
# A key whose prefix is atlas_test_ never reaches a wallet or a panel. Every
# endpoint below diverts it to core/rep_sandbox.py, AFTER the same
# authentication, scope and rate-limit checks a live key faces — an integrator
# has to be able to provoke 401, 403 and 429 too, or the sandbox is only half a
# rehearsal. See core/rep_sandbox.py for what is deliberately real.

def _is_sandbox(ctx: Dict) -> bool:
    return bool(int((ctx.get("key") or {}).get("is_sandbox") or 0))


def _sandbox_note(payload: Dict) -> Dict:
    payload = dict(payload)
    payload["sandbox"] = True
    return payload


# ═══════════════════════════════ endpoints ═══════════════════════════════════
@router.get("/v1/ping")
async def rep_ping(request: Request):
    """Cheapest possible "is my key alive" probe."""
    ctx, err = await authorize(request, "read")
    if err:
        return err
    return _json({"ok": True, "api_version": API_VERSION, "server_time": int(time.time()),
                  "representative_id": int(ctx["user"]["id"])}, 200, ctx)


@router.get("/v1/me")
async def rep_me(request: Request):
    """Account snapshot: wallet, brand, tariffs, allowances, key metadata."""
    ctx, err = await authorize(request, "read")
    if err:
        return err
    user, key = ctx["user"], ctx["key"]
    pricing = await get_user_pricing(user["id"])
    stats = await get_rep_financials(user["id"])
    try:
        trial_limit = max(0, int(await get_setting("rep_test_daily_limit", "0") or 0))
    except (TypeError, ValueError):
        trial_limit = 0
    return _json({
        "ok": True,
        "representative": {
            "id": int(user["id"]),
            "telegram_id": int(user.get("telegram_id") or 0),
            "brand_name": (user.get("rep_brand_name") or "").strip(),
            "brand_hidden": bool(int(user.get("hide_brand") or 0)),
            "balance": (await sandbox.balance(int(key["id"]))
                        if _is_sandbox(ctx) else await get_user_balance(user["id"])),
        },
        "pricing": {
            "price_per_gb": int(pricing.get("price_per_gb") or 0),
            "unlimited_price": int(pricing.get("unlimited_price") or 0),
            "discount_percent": float(pricing.get("discount_percent") or 0),
        },
        "stats": stats,
        "limits": {
            "max_batch": MAX_BATCH,
            "rate_per_min": int(key.get("rate_per_min") or rep_api.DEFAULT_RATE_PER_MIN),
            "trial_daily_limit": trial_limit,
            "trial_used_today": await count_rep_test_today(user["id"]) if trial_limit else 0,
        },
        "key": {
            "id": int(key["id"]),
            "name": key.get("name") or "",
            "prefix": key.get("prefix") or "",
            "scopes": [s for s in str(key.get("scopes") or "").split(",") if s],
            "created_at": int(key.get("created_at") or 0),
            "sandbox": _is_sandbox(ctx),
        },
        "sandbox": _is_sandbox(ctx),
    }, 200, ctx)


@router.get("/v1/packages")
async def rep_packages(request: Request):
    """Sellable plans with THIS representative's price already applied."""
    ctx, err = await authorize(request, "read")
    if err:
        return err
    pricing = await get_user_pricing(ctx["user"]["id"])
    packages = [_package_payload(p, compute_package_price(pricing, p))
                for p in await get_packages(active_only=True)]
    return _json({"ok": True, "packages": packages}, 200, ctx)


@router.get("/v1/packages/table")
async def rep_packages_table(request: Request):
    """The buy screen, rendered — with THIS representative's prices.

    The same table our own bot shows, so a reseller does not have to rebuild it
    to look as good. Three renderings come back and the caller picks:

      html        send with parse_mode="HTML"      (custom emoji when premium=1)
      html_plain  send with parse_mode="HTML"      (identical, plain glyphs)
      markdown    send with sendRichMessage        (real table, no custom emoji)

    ABOUT `premium`. Telegram only lets a bot use custom emoji if it bought a
    Fragment username, or if the bot's OWNER has Telegram Premium. That is a
    property of the SENDING bot, not of the emoji — a reseller whose owner has
    no Premium cannot use them however valid the ids are. So `premium=0` (the
    default here, because we cannot know about someone else's bot) renders the
    identical table with plain glyphs. Pass `premium=1` only if that bot is
    allowed to; if it is not, Telegram drops the emoji and the layout survives
    regardless.

    Everything a reseller sells under their own name is theirs to set: `title`,
    `intro`, `note`, the three `columns`, and `caption`.
    """
    ctx, err = await authorize(request, "read")
    if err:
        return err
    from core import package_view as pv

    q = request.query_params
    pricing = await get_user_pricing(ctx["user"]["id"])
    pkgs = await get_packages(active_only=True)
    for p in pkgs:
        p["display_price"] = int(compute_package_price(pricing, p)["final"])

    # THE MARGIN. Without this the table could only print what the reseller pays
    # us — useless to show a customer, and a number they would rather that
    # customer never saw. `prices` is an outright override per package id; the
    # percentage and the flat amount build on their cost instead.
    def num(name: str, default: float = 0.0) -> float:
        try:
            return float(q.get(name) or default)
        except (TypeError, ValueError):
            return default

    overrides = {}
    for part in (q.get("prices") or "").split(","):
        if ":" in part:
            pid, _, val = part.partition(":")
            try:
                overrides[int(pid.strip())] = max(0, int(float(val.strip())))
            except (TypeError, ValueError):
                continue

    pv.apply_markup(
        pkgs,
        percent=max(-100.0, min(1000.0, num("markup_percent"))),
        amount=max(-10_000_000, min(100_000_000, int(num("markup_amount")))),
        overrides=overrides,
        round_to=max(0, min(1_000_000, int(num("round_to", 1000)))),
    )

    def txt(name: str, default: str, limit: int = 120) -> str:
        return (q.get(name) or default)[:limit]

    cols = [c for c in (q.get("columns") or "").split("|") if c.strip()][:3]
    headers = cols if len(cols) == 3 else None
    caption = txt("caption", pv.DEFAULT_CAPTION)
    title = txt("title", "🛒 پکیج‌ها و قیمت‌ها", 80)
    intro = txt("intro", "", 300)
    note = txt("note", "", 300)
    premium = (q.get("premium") or "0").strip() in ("1", "true", "yes")

    def render(with_emoji: bool) -> str:
        return pv.screen_html(pkgs, premium=with_emoji, title=title, intro=intro,
                              note=note, headers=headers, caption=caption)

    # BOTH renderings come back every time, not just the one `premium` selected.
    # Whether a bot may use custom emoji is a question about that bot, and the
    # only way to answer it is to try — so the caller can send one, see what
    # arrives, and switch to the other without changing their request.
    return _json({
        "ok": True,
        "premium_emoji": premium,
        "html": render(premium),
        "html_premium": render(True),
        "html_plain": render(False),
        "markdown": pv.table_markdown(pkgs, headers=headers, caption=caption),
        # The rows behind the rendering, for anyone who would rather lay it out
        # themselves than accept ours. `price` is what WE charge them, and
        # `sell_price` is what the table prints — the two are different numbers
        # on purpose and confusing them is how a reseller sells at cost.
        "packages": [
            dict(_package_payload(p, compute_package_price(pricing, p)),
                 sell_price=int(p.get("sell_price") or 0),
                 below_cost=bool(p.get("below_cost")))
            for p in pkgs
        ],
    }, 200, ctx)


def _sort_filter(rows: List[Dict], sort: str, filt: str, now_ms: int) -> List[Dict]:
    if filt == "active":
        rows = [r for r in rows if int(r.get("is_active") or 0)]
    elif filt == "inactive":
        rows = [r for r in rows if not int(r.get("is_active") or 0)]
    elif filt == "expired":
        rows = [r for r in rows if 0 < int(r.get("expire_timestamp") or 0) <= now_ms]
    elif filt == "expiring":
        rows = [r for r in rows
                if 0 < int(r.get("expire_timestamp") or 0) <= now_ms + 3 * 86_400_000
                and int(r.get("expire_timestamp") or 0) > now_ms]
    elif filt == "near_limit":
        rows = [r for r in rows
                if float(r.get("traffic_gb") or 0) > 0
                and int(r.get("used_bytes") or 0) >= 0.8 * float(r.get("traffic_gb") or 0) * GB]
    elif filt == "unlimited":
        rows = [r for r in rows if float(r.get("traffic_gb") or 0) <= 0]

    def usage(r):
        total = float(r.get("traffic_gb") or 0) * GB
        return int(r.get("used_bytes") or 0) / total if total > 0 else 0.0

    if sort == "oldest":
        rows.sort(key=lambda r: int(r["id"]))
    elif sort == "name_az":
        from core.sorting import fa_sort_key
        rows.sort(key=lambda r: fa_sort_key(r.get("name") or r.get("email") or ""))
    elif sort == "expiry_soon":
        # Never-expiring rows sort last rather than first — 0 is "no deadline".
        rows.sort(key=lambda r: int(r.get("expire_timestamp") or 0) or 1 << 62)
    elif sort == "usage_desc":
        rows.sort(key=usage, reverse=True)
    else:
        rows.sort(key=lambda r: int(r["id"]), reverse=True)
    return rows


@router.get("/v1/services")
async def rep_services(request: Request):
    """Paged list of every service this representative has created."""
    ctx, err = await authorize(request, "read")
    if err:
        return err
    q = request.query_params
    page = max(1, _as_int(q.get("page"), 1))
    if _is_sandbox(ctx):
        rows = await sandbox.list_services(int(ctx["key"]["id"]))
        page_ = max(1, _as_int(q.get("page"), 1))
        per = max(1, min(100, _as_int(q.get("per_page"), 25)))
        window = rows[(page_ - 1) * per: page_ * per]
        return _json({"ok": True, "sandbox": True,
                      "services": [sandbox.payload(r) for r in window],
                      "pagination": {"page": page_, "per_page": per, "total": len(rows),
                                     "pages": max(1, -(-len(rows) // per))}}, 200, ctx)
    per_page = max(1, min(100, _as_int(q.get("per_page"), 25)))
    sort = q.get("sort") if q.get("sort") in SERVICE_SORTS else "newest"
    filt = q.get("filter") if q.get("filter") in SERVICE_FILTERS else "all"
    search = (q.get("q") or "").strip().lower()

    rows = await get_user_subscription_profiles(ctx["user"]["id"])
    if search:
        rows = [r for r in rows
                if search in str(r.get("name") or "").lower() or search in str(r.get("email") or "").lower()]
    now_ms = int(time.time() * 1000)
    rows = _sort_filter(rows, sort, filt, now_ms)
    total = len(rows)
    window = rows[(page - 1) * per_page: page * per_page]

    services = []
    for p in window:
        try:
            url = await subscription_url(p["token"])
        except Exception:
            url = ""
        services.append(_service_payload(p, url, now_ms))
    return _json({
        "ok": True,
        "services": services,
        "pagination": {"page": page, "per_page": per_page, "total": total,
                       "pages": max(1, -(-total // per_page))},
    }, 200, ctx)


@router.get("/v1/services/{profile_id}")
async def rep_service_detail(request: Request, profile_id: int):
    """One service, with the per-server links behind its subscription URL."""
    ctx, err = await authorize(request, "read")
    if err:
        return err
    if _is_sandbox(ctx):
        row = await sandbox.get_service(int(ctx["key"]["id"]), int(profile_id))
        if not row:
            return _err("service_not_found", "سرویسی با این شناسه پیدا نشد.", 404, ctx)
        return _json({"ok": True, "sandbox": True,
                      "service": sandbox.payload(row, with_nodes=True)}, 200, ctx)
    profile, err = await _profile_or_error(profile_id, ctx)
    if err:
        return err
    try:
        url = await subscription_url(profile["token"])
    except Exception:
        url = ""
    nodes = await get_subscription_nodes(int(profile["id"]))
    return _json({"ok": True,
                  "service": _service_payload(profile, url, int(time.time() * 1000), nodes)}, 200, ctx)


@router.post("/v1/services")
async def rep_create_service(request: Request):
    """Create 1..MAX_BATCH services and charge the representative's wallet.

    Partial success is a first-class outcome: nodes go down, and refusing to
    hand over the four subscriptions that *were* created because the fifth
    failed helps nobody. The unused units are refunded in the same request and
    the order is rewritten to what was actually delivered.
    """
    ctx, err = await authorize(request, "write")
    if err:
        return err
    if not _is_sandbox(ctx):
        # The minimum-topup rule is about real money, and a sandbox that refused
        # to let a new rep try the API until they had paid would be backwards.
        gate = await _topup_gate(ctx)
        if gate:
            return gate

    body = await _body(request)
    idem_key, replay = await _idem_start(request, ctx, "services.create", body)
    if replay:
        return replay

    if _is_sandbox(ctx):
        # Same plan resolution and the same pricing, so an integrator can hit
        # both `insufficient_funds` and a bad package id here rather than
        # discovering them with real money.
        plan = await _resolve_plan(body, ctx["user"])
        if plan.get("error"):
            fail = _err_body(plan["error"], plan["message"])
            return await _idem_done(ctx, idem_key, _json(fail, 400, ctx), fail)
        count = max(1, min(MAX_BATCH, _as_int(body.get("count"), 1)))
        names = body.get("names") if isinstance(body.get("names"), list) else []
        made, failed = [], []
        for i in range(count):
            nm = _clean_name(names[i]) if i < len(names) else _clean_name(body.get("name"))
            r = await sandbox.create_service(
                int(ctx["key"]["id"]), name=nm or f"sandbox {i + 1}",
                traffic_gb=float(plan["traffic_gb"]), duration_days=int(plan["duration_days"]),
                price=int(plan["unit_price"]), package_id=int((plan.get("package") or {}).get("id") or 0),
                starts_on_first_use=bool(body.get("starts_on_first_use")))
            if r.get("ok"):
                made.append(r["service"])
            else:
                failed.append(r)
                break
        if not made and failed:
            f = failed[0]
            fail = _err_body(f.get("error") or "sandbox_error",
                             "موجودی کیف پول تستی کافی نیست. با POST /v1/sandbox/reset شارژش کن.")
            return await _idem_done(ctx, idem_key, _json(fail, 402, ctx), fail)
        payload = {"ok": True, "sandbox": True, "services": made,
                   "created": len(made), "requested": count,
                   "charged": sum(int(s.get("price") or 0) for s in []) or
                              int(plan["unit_price"]) * len(made),
                   "balance": await sandbox.balance(int(ctx["key"]["id"]))}
        return await _idem_done(ctx, idem_key, _json(payload, 200, ctx), payload)

    try:
        plan = await _resolve_plan(body, ctx["user"])
        if plan.get("error"):
            fail = _err_body(plan["error"], plan["message"])
            return await _idem_done(ctx, idem_key, _json(fail, 400, ctx), fail)

        count = max(1, min(MAX_BATCH, _as_int(body.get("count"), 1)))
        names = body.get("names")
        if isinstance(names, list) and names:
            unit_names = [_clean_name(n) for n in names[:count]]
            unit_names += [""] * (count - len(unit_names))
        else:
            base_name = _clean_name(body.get("name"))
            unit_names = ([f"{base_name}-{i + 1}"[:40] for i in range(count)]
                          if base_name and count > 1 else [base_name] * count)

        unit_price = int(plan["unit_price"])
        total_price = unit_price * count
        user_id = int(ctx["user"]["id"])
        telegram_id = int(ctx["user"].get("telegram_id") or 0)

        # One rep at a time: two concurrent creates must not both clear the same
        # balance check and overdraw the wallet.
        async with rep_api.user_lock(user_id):
            balance = await get_user_balance(user_id)
            if balance < total_price:
                fail = _err_body("insufficient_balance",
                                 f"موجودی کیف پول کافی نیست. لازم: {total_price:,} تومان، موجودی: {balance:,} تومان.",
                                 required=total_price, balance=balance)
                return await _idem_done(ctx, idem_key, _json(fail, 402, ctx), fail)

            each_gb = float(plan["traffic_gb"])
            duration = int(plan["duration_days"])
            note = _clean_name(body.get("note"), 120)
            oid = await create_custom_order(
                user_id,
                name=f"API: {plan['label']}" + (f" ×{count}" if count > 1 else ""),
                total_traffic_gb=each_gb * count,
                duration_days=duration,
                price=total_price,
                bulk_count=count,
                bulk_each_gb=each_gb,
                notes=json.dumps({"source": "rep_api", "key_id": int(ctx["key"]["id"]),
                                  "note": note}, ensure_ascii=False),
                package_id=int(plan["package"]["id"]) if plan.get("package") else 0,
            )
            await add_user_balance(user_id, -total_price, kind="purchase",
                                   note=f"order:{oid}", actor_telegram_id=telegram_id)

            # From here on the wallet is already debited, so EVERY exit — including
            # an unexpected one — has to hand back what it did not deliver. Without
            # this guard a failing DB write between the debit and the refund would
            # keep the rep's money and leave nothing behind to reconcile it with.
            order = {"id": oid, "custom_config_name": ""}
            created, failures = [], []
            try:
                for idx in range(count):
                    unit_order = dict(order, custom_config_name=unit_names[idx])
                    result = await create_profile_for_order(ctx["user"], unit_order, each_gb, duration)
                    if result.get("ok"):
                        created.append(result)
                    else:
                        failures.append(result.get("error") or "unknown")
            except Exception:
                undelivered = total_price - unit_price * len(created)
                if undelivered > 0:
                    await add_user_balance(user_id, undelivered, kind="refund",
                                           note=f"order_error:{oid}", actor_telegram_id=0)
                raise

            charged = unit_price * len(created)
            refund = total_price - charged
            if refund > 0:
                await add_user_balance(user_id, refund, kind="refund",
                                       note=f"order_partial:{oid}", actor_telegram_id=0)

            if not created:
                await update_order(oid, status="rejected",
                                   notes=json.dumps({"source": "rep_api", "error": failures[:3]},
                                                    ensure_ascii=False))
                logger.warning("rep-api create failed rep=%s order=%s: %s", user_id, oid, failures[:3])
                fail = _err_body("provisioning_failed",
                                 "ساخت سرویس ناموفق بود و مبلغ به کیف پول شما بازگشت. علت: "
                                 + subscription_error_message(failures[0] if failures else ""),
                                 order_id=oid, balance=await get_user_balance(user_id))
                return await _idem_done(ctx, idem_key, _json(fail, 502, ctx), fail)

            await update_order(oid, status="approved", server_id=0, inbound_id=0,
                               config_email=created[0]["email"], custom_price=charged,
                               bulk_count=len(created),
                               approved_at=datetime.now().isoformat())

            now_ms = int(time.time() * 1000)
            services = []
            for item in created:
                profile = await get_subscription_profile(int(item["profile_id"]))
                if profile:
                    services.append(_service_payload(profile, item["url"], now_ms))
            payload = {
                "ok": True,
                "order_id": oid,
                "requested": count,
                "created": len(created),
                "charged": charged,
                "refunded": refund,
                "balance": await get_user_balance(user_id),
                "services": services,
            }
            if failures:
                payload["partial"] = True
                payload["message"] = subscription_error_message(failures[0])
            status = 201 if not failures else 207
            return await _idem_done(ctx, idem_key, _json(payload, status, ctx), payload)
    except Exception as e:
        logger.exception("rep-api create crashed rep=%s: %s", ctx["user"].get("id"), e)
        # Free the key so the caller's retry is a real attempt, not a permanent
        # "in flight" — the charge path above refunds anything it could not use.
        if idem_key:
            await rep_api.idem_abort(int(ctx["user"]["id"]), idem_key)
        return _err("internal_error", "خطای داخلی سرور. لطفاً دوباره تلاش کن.", 500, ctx)


@router.post("/v1/services/{profile_id}/renew")
async def rep_renew_service(request: Request, profile_id: int):
    """Extend an existing service. Leftover volume/time carry over exactly as
    they do in the bot — the engine decides, not this route."""
    ctx, err = await authorize(request, "write")
    if err:
        return err
    if not _is_sandbox(ctx):
        gate = await _topup_gate(ctx)
        if gate:
            return gate
        profile, err = await _profile_or_error(profile_id, ctx)
        if err:
            return err

    body = await _body(request)
    idem_key, replay = await _idem_start(request, ctx, f"services.renew.{profile_id}", body)
    if replay:
        return replay

    if _is_sandbox(ctx):
        plan = await _resolve_plan(body, ctx["user"])
        if plan.get("error"):
            fail = _err_body(plan["error"], plan["message"])
            return await _idem_done(ctx, idem_key, _json(fail, 400, ctx), fail)
        r = await sandbox.renew_service(
            int(ctx["key"]["id"]), int(profile_id),
            duration_days=int(plan["duration_days"]), traffic_gb=float(plan["traffic_gb"]),
            price=int(plan["unit_price"]))
        if not r.get("ok"):
            code = 404 if r.get("error") == "service_not_found" else 402
            fail = _err_body(r.get("error") or "sandbox_error",
                             "سرویس تستی پیدا نشد." if code == 404
                             else "موجودی کیف پول تستی کافی نیست.")
            return await _idem_done(ctx, idem_key, _json(fail, code, ctx), fail)
        payload = {"ok": True, "sandbox": True, "service": r["service"],
                   "charged": r["charged"], "balance": r["balance"]}
        return await _idem_done(ctx, idem_key, _json(payload, 200, ctx), payload)

    try:
        plan = await _resolve_plan(body, ctx["user"])
        if plan.get("error"):
            fail = _err_body(plan["error"], plan["message"])
            return await _idem_done(ctx, idem_key, _json(fail, 400, ctx), fail)

        price = int(plan["unit_price"])
        user_id = int(ctx["user"]["id"])
        async with rep_api.user_lock(user_id):
            balance = await get_user_balance(user_id)
            if balance < price:
                fail = _err_body("insufficient_balance",
                                 f"موجودی کافی نیست. لازم: {price:,} تومان، موجودی: {balance:,} تومان.",
                                 required=price, balance=balance)
                return await _idem_done(ctx, idem_key, _json(fail, 402, ctx), fail)

            oid = await create_custom_order(
                user_id,
                name=f"API تمدید: {profile.get('name') or profile['id']}",
                total_traffic_gb=float(plan["traffic_gb"]),
                duration_days=int(plan["duration_days"]),
                price=price,
                notes=json.dumps({"source": "rep_api", "renew_sub": int(profile["id"])}, ensure_ascii=False),
                package_id=int(plan["package"]["id"]) if plan.get("package") else 0,
            )
            await update_order(oid, renew_sub_profile_id=int(profile["id"]))
            await add_user_balance(user_id, -price, kind="purchase",
                                   note=f"order:{oid}", actor_telegram_id=int(ctx["user"].get("telegram_id") or 0))

            # Debited — so an unexpected failure has to refund too, not just the
            # engine's own "renew didn't work" answer below.
            try:
                result = await renew_subscription_profile(profile, float(plan["traffic_gb"]),
                                                          int(plan["duration_days"]))
            except Exception:
                await add_user_balance(user_id, price, kind="refund",
                                       note=f"order_error:{oid}", actor_telegram_id=0)
                raise
            if not result.get("ok"):
                await add_user_balance(user_id, price, kind="refund",
                                       note=f"order_failed:{oid}", actor_telegram_id=0)
                await update_order(oid, status="rejected")
                fail = _err_body("renew_failed",
                                 "تمدید ناموفق بود و مبلغ بازگشت داده شد: "
                                 + subscription_error_message(result.get("error") or ""),
                                 order_id=oid, balance=await get_user_balance(user_id))
                return await _idem_done(ctx, idem_key, _json(fail, 502, ctx), fail)

            await update_order(oid, status="approved", server_id=0, inbound_id=0,
                               config_email=profile.get("email") or f"sub:{profile['id']}",
                               approved_at=datetime.now().isoformat())
            fresh = await get_subscription_profile(int(profile["id"])) or profile
            payload = {
                "ok": True,
                "order_id": oid,
                "charged": price,
                "balance": await get_user_balance(user_id),
                "nodes_renewed": int(result.get("nodes") or 0),
                "carried_over": bool(result.get("carried")),
                "service": _service_payload(fresh, await subscription_url(fresh["token"]),
                                            int(time.time() * 1000)),
            }
            return await _idem_done(ctx, idem_key, _json(payload, 200, ctx), payload)
    except Exception as e:
        logger.exception("rep-api renew crashed rep=%s pid=%s: %s", ctx["user"].get("id"), profile_id, e)
        if idem_key:
            await rep_api.idem_abort(int(ctx["user"]["id"]), idem_key)
        return _err("internal_error", "خطای داخلی سرور. لطفاً دوباره تلاش کن.", 500, ctx)


@router.post("/v1/services/{profile_id}/rename")
async def rep_rename_service(request: Request, profile_id: int):
    """Rename the service. The name is what the customer sees on their link."""
    ctx, err = await authorize(request, "write")
    if err:
        return err
    name = _clean_name((await _body(request)).get("name"))
    if _is_sandbox(ctx):
        r = await sandbox.update_service(int(ctx["key"]["id"]), int(profile_id), name=name)
        if not r.get("ok"):
            return _err("service_not_found", "سرویس تستی پیدا نشد.", 404, ctx)
        return _json({"ok": True, "sandbox": True, "id": int(profile_id), "name": name}, 200, ctx)
    profile, err = await _profile_or_error(profile_id, ctx)
    if err:
        return err
    await update_subscription_profile(int(profile["id"]), name=name)
    return _json({"ok": True, "id": int(profile["id"]), "name": name}, 200, ctx)


async def _set_active(request: Request, profile_id: int, enabled: bool):
    ctx, err = await authorize(request, "write")
    if err:
        return err
    if _is_sandbox(ctx):
        r = await sandbox.update_service(int(ctx["key"]["id"]), int(profile_id),
                                         is_active=1 if enabled else 0)
        if not r.get("ok"):
            return _err("service_not_found", "سرویس تستی پیدا نشد.", 404, ctx)
        return _json({"ok": True, "sandbox": True, "service": r["service"]}, 200, ctx)
    profile, err = await _profile_or_error(profile_id, ctx)
    if err:
        return err
    await update_subscription_profile(int(profile["id"]), is_active=1 if enabled else 0)
    try:
        # Flip it on the panels too — a DB flag alone would leave the customer
        # connected (or, on enable, leave them with no client to connect to).
        await set_nodes_enabled(int(profile["id"]), enabled)
    except Exception as e:
        logger.warning("rep-api set_nodes_enabled failed pid=%s: %s", profile_id, e)
        return _err("panel_error", "وضعیت در دیتابیس تغییر کرد اما اعمال روی سرورها ناموفق بود.",
                    502, ctx, id=int(profile["id"]), is_active=enabled)
    fresh = await get_subscription_profile(int(profile["id"])) or profile
    return _json({"ok": True, "service": _service_payload(fresh, await subscription_url(fresh["token"]),
                                                          int(time.time() * 1000))}, 200, ctx)


@router.post("/v1/services/{profile_id}/disable")
async def rep_disable_service(request: Request, profile_id: int):
    """Cut the service off on every server (reversible, no refund)."""
    return await _set_active(request, profile_id, False)


@router.post("/v1/services/{profile_id}/enable")
async def rep_enable_service(request: Request, profile_id: int):
    """Turn a disabled service back on, re-creating any client the panel dropped."""
    return await _set_active(request, profile_id, True)


@router.post("/v1/services/{profile_id}/revoke")
async def rep_revoke_service(request: Request, profile_id: int):
    """Issue a brand-new link and kill the old one — for a shared subscription.

    Rotates the token AND every node's client identity, so a customer who
    already imported the old link stops connecting. Quota, expiry and consumed
    traffic carry over; this is not a renewal.
    """
    ctx, err = await authorize(request, "write")
    if err:
        return err
    if _is_sandbox(ctx):
        r = await sandbox.revoke_service(int(ctx["key"]["id"]), int(profile_id))
        if not r.get("ok"):
            return _err("service_not_found", "سرویس تستی پیدا نشد.", 404, ctx)
        return _json({"ok": True, "sandbox": True,
                      "subscription_url": r["service"]["subscription_url"],
                      "rotated_nodes": 0, "service": r["service"]}, 200, ctx)
    profile, err = await _profile_or_error(profile_id, ctx)
    if err:
        return err
    result = await rotate_subscription_link(int(profile["id"]))
    if not result.get("ok"):
        message = ("سرویس غیرفعال است؛ فقط سرویس فعال قابل تعویض لینک است."
                   if result.get("error") == "inactive"
                   else subscription_error_message(result.get("error") or ""))
        return _err("revoke_failed", message, 409 if result.get("error") == "inactive" else 502, ctx)
    fresh = await get_subscription_profile(int(profile["id"])) or profile
    return _json({"ok": True,
                  "subscription_url": result.get("url") or "",
                  "rotated_nodes": int(result.get("rotated") or 0),
                  "failed_nodes": int(result.get("failed") or 0),
                  "service": _service_payload(fresh, result.get("url") or "",
                                              int(time.time() * 1000))}, 200, ctx)


@router.post("/v1/services/{profile_id}/delete")
async def rep_delete_service(request: Request, profile_id: int):
    """Permanently remove a service from every panel. No refund, no undo.

    Deliberately a POST on an explicit path rather than ``DELETE /services/{id}``:
    a stray verb from a misconfigured HTTP client should not be able to destroy
    a paying customer's subscription.
    """
    ctx, err = await authorize(request, "write")
    if err:
        return err
    if not bool((await _body(request)).get("confirm")):
        return _err("confirmation_required",
                    "برای حذف دائمی باید در بدنه‌ی درخواست confirm=true بفرستی.", 400, ctx)
    if _is_sandbox(ctx):
        r = await sandbox.delete_service(int(ctx["key"]["id"]), int(profile_id))
        if not r.get("ok"):
            return _err("service_not_found", "سرویس تستی پیدا نشد.", 404, ctx)
        return _json({"ok": True, "sandbox": True, "id": int(profile_id),
                      "removed_nodes": 0, "failed_nodes": 0}, 200, ctx)
    profile, err = await _profile_or_error(profile_id, ctx)
    if err:
        return err
    result = await delete_subscription_profile_remote(int(profile["id"]))
    return _json({"ok": True, "id": int(profile["id"]),
                  "removed_nodes": int(result.get("deleted") or 0),
                  "failed_nodes": int(result.get("failed") or 0)}, 200, ctx)


@router.post("/v1/services/trial")
async def rep_create_trial(request: Request):
    """Free trial from the representative's daily allowance (admin-set)."""
    ctx, err = await authorize(request, "write")
    if err:
        return err
    if _is_sandbox(ctx):
        # The daily allowance is a real-money guard against giving away stock.
        # There is no stock here, so the sandbox lets them exercise the call as
        # often as they need to get their code right.
        try:
            gb = float(await get_setting("test_account_traffic_gb", "1") or 1)
            days = int(await get_setting("test_account_duration_days", "1") or 1)
        except (TypeError, ValueError):
            gb, days = 1.0, 1
        r = await sandbox.create_service(int(ctx["key"]["id"]), name="sandbox trial",
                                         traffic_gb=gb, duration_days=days, price=0,
                                         is_trial=True)
        return _json({"ok": True, "sandbox": True, "service": r["service"],
                      "charged": 0}, 200, ctx)
    if str(await get_setting("test_account_enabled", "1")) != "1":
        return _err("trial_disabled", "اکانت تست در حال حاضر غیرفعال است.", 403, ctx)
    try:
        limit = max(0, int(await get_setting("rep_test_daily_limit", "0") or 0))
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        return _err("trial_disabled", "سهمیه‌ی تست روزانه برای نمایندگان تنظیم نشده است.", 403, ctx)

    user_id = int(ctx["user"]["id"])
    async with rep_api.user_lock(user_id):
        used = await count_rep_test_today(user_id)
        if used >= limit:
            return _err("trial_limit_reached",
                        f"سقف تست روزانه ({limit} عدد) پر شده است.", 429, ctx,
                        limit=limit, used=used)
        try:
            traffic_gb = float(await get_setting("test_account_traffic_gb", "1") or 1)
        except (TypeError, ValueError):
            traffic_gb = 1.0
        try:
            duration = int(await get_setting("test_account_duration_days", "1") or 1)
        except (TypeError, ValueError):
            duration = 1
        name = _clean_name((await _body(request)).get("name")) or "اکانت تست"
        result = await create_test_subscription(ctx["user"], traffic_gb, duration, name)
        if not result.get("ok"):
            return _err("provisioning_failed",
                        subscription_error_message(result.get("error") or ""), 502, ctx)
        await add_rep_test_account(user_id, profile_id=int(result["profile_id"]))
        profile = await get_subscription_profile(int(result["profile_id"]))
        return _json({
            "ok": True,
            "trial_used_today": await count_rep_test_today(user_id),
            "trial_daily_limit": limit,
            "service": _service_payload(profile, result["url"], int(time.time() * 1000)) if profile else None,
        }, 201, ctx)


@router.get("/v1/services/{profile_id}/connections")
async def rep_service_connections(request: Request, profile_id: int):
    """How many distinct places are connected to this service RIGHT NOW.

    Simultaneous connections, not addresses-seen-today: an address counts only
    while it still has a live connection, and one confirmed against the panel's
    honest last-seen times rather than its 30-minute history. A customer on
    mobile data whose IP keeps changing is one place, not five — see
    core/ip_guard.py for why that distinction is the whole feature.

    Cheap to call: every panel is read at most once every few seconds no matter
    how many resellers (or customers, or panel pages) ask, because they all
    share one snapshot. Still rate-limited like any other endpoint.

    Addresses come back MASKED (`5.113.20.···`). The count, the timing and the
    server are what you need to act on a sharing complaint; handing a third
    party a list of end-user addresses over an API is not.
    """
    ctx, err = await authorize(request, "read")
    if err:
        return err
    if _is_sandbox(ctx):
        return _json(sandbox.connections(int(profile_id)), 200, ctx)
    profile, err = await _profile_or_error(profile_id, ctx)
    if err:
        return err
    from core.ip_guard import live_connections
    try:
        live = await live_connections(int(profile["id"]), confirm=True, reveal=False)
    except Exception as e:
        logger.warning("rep api: connections failed for %s: %s", profile_id, e)
        return _err("upstream_unavailable",
                    "الان نمی‌شود وضعیت اتصال را خواند. کمی بعد دوباره امتحان کن.", 503, ctx)
    return _json({
        "ok": True,
        "service_id": int(profile["id"]),
        "connections": live.get("count", 0),
        "limit": live.get("limit", 0),
        "over_limit": bool(live.get("limit") and live.get("count", 0) > live["limit"]),
        "places": live.get("places", []),
        "checked_at": live.get("checked_at"),
        # True when a panel did not answer, so the count is a floor rather than
        # the whole picture. Do not present it as exact when this is set.
        "partial": bool(live.get("partial")),
        "servers_answered": live.get("answered"),
        "servers_total": live.get("servers"),
    }, 200, ctx)
@router.post("/v1/sandbox/reset")
async def rep_sandbox_reset(request: Request):
    """Wipe this sandbox key's scratch data and refill its play wallet.

    Only a sandbox key may call it. A live key gets 403 rather than a quiet
    no-op, because the one thing worse than a test endpoint is a test endpoint
    someone believes they can point at production.
    """
    ctx, err = await authorize(request, "write")
    if err:
        return err
    if not _is_sandbox(ctx):
        return _err("not_a_sandbox_key",
                    "این مسیر فقط با کلید تستی (atlas_test_) کار می‌کند.", 403, ctx)
    return _json(await sandbox.reset(int(ctx["key"]["id"])), 200, ctx)


@router.get("/v1/sandbox")
async def rep_sandbox_info(request: Request):
    """What this key is, and what the sandbox does and does not do.

    Answers the first question every integrator has — "am I about to spend real
    money?" — without them having to find out empirically.
    """
    ctx, err = await authorize(request, "read")
    if err:
        return err
    on = _is_sandbox(ctx)
    return _json({
        "ok": True,
        "sandbox": on,
        "wallet": await sandbox.balance(int(ctx["key"]["id"])) if on else None,
        "notes": ([
            "این کلید تستی است. هیچ پولی کم نمی‌شود و هیچ کانفیگی روی سرورها ساخته نمی‌شود.",
            "قیمت‌ها، سهمیه‌ها و کیف پول واقعی شبیه‌سازی می‌شوند تا خطای insufficient_funds را هم بتوانی تست کنی.",
            "لینک‌های اشتراک به دامنه‌ی sandbox.invalid اشاره می‌کنند و هرگز کار نمی‌کنند.",
            "برای پاک‌کردن داده‌ها و شارژ دوباره: POST /v1/sandbox/reset",
            "وقتی کدت آماده شد، فقط کلید را با کلید اصلی عوض کن — بقیه چیزها یکی است.",
        ] if on else [
            "این کلید اصلی است و روی داده‌ی واقعی کار می‌کند.",
            "برای تست بدون هزینه، از بخش نمایندگان در ربات یک کلید تستی بگیر (atlas_test_).",
        ]),
    }, 200, ctx)


@router.get("/v1/wallet")
async def rep_wallet(request: Request):
    """Balance plus recent movements, so a rep's bot can show its own ledger."""
    ctx, err = await authorize(request, "read")
    if err:
        return err
    limit = max(1, min(100, _as_int(request.query_params.get("limit"), 20)))
    if _is_sandbox(ctx):
        kid = int(ctx["key"]["id"])
        return _json({"ok": True, "sandbox": True,
                      "balance": await sandbox.balance(kid),
                      "transactions": [{"amount": -int(o["amount"]), "kind": o["kind"],
                                        "note": o.get("detail") or "",
                                        "created_at": o["created_at"]}
                                       for o in await sandbox.orders(kid, limit)]}, 200, ctx)
    txs = await get_wallet_transactions(ctx["user"]["id"], limit)
    return _json({
        "ok": True,
        "balance": await get_user_balance(ctx["user"]["id"]),
        "transactions": [{"amount": int(t.get("amount") or 0), "kind": t.get("kind") or "",
                          "note": t.get("note") or "", "created_at": t.get("created_at") or ""}
                         for t in txs],
    }, 200, ctx)


@router.get("/v1/orders")
async def rep_orders(request: Request):
    """Recent orders — the audit trail behind every charge on the wallet."""
    ctx, err = await authorize(request, "read")
    if err:
        return err
    limit = max(1, min(100, _as_int(request.query_params.get("limit"), 25)))
    if _is_sandbox(ctx):
        return _json({"ok": True, "sandbox": True, "orders": [{
            "id": int(o["id"]), "status": "approved", "name": o.get("detail") or o["kind"],
            "price": int(o["amount"]), "traffic_gb": 0.0, "duration_days": 0,
            "count": 1, "created_at": o["created_at"], "approved_at": o["created_at"],
        } for o in await sandbox.orders(int(ctx["key"]["id"]), limit)]}, 200, ctx)
    rows = await get_user_orders_full(ctx["user"]["id"], limit)
    return _json({"ok": True, "orders": [{
        "id": int(o["id"]),
        "status": o.get("status") or "",
        "name": o.get("pkg_name") or "",
        "price": int(o.get("price") or 0),
        "traffic_gb": float(o.get("traffic_gb") or 0),
        "duration_days": int(o.get("duration_days") or 0),
        "count": int(o.get("bulk_count") or 1),
        "created_at": o.get("created_at") or "",
        "approved_at": o.get("approved_at") or "",
    } for o in rows]}, 200, ctx)


@router.get("/docs", response_class=HTMLResponse)
async def rep_api_docs():
    """Human-readable Persian reference, served from the same host as the API.

    Public on purpose: it contains no secrets, and a representative must be able
    to open it before they own a key.
    """
    from web.rep_api_docs import docs_html
    from core.multi_subscription import public_base_url_async
    base = (await public_base_url_async() or "").rstrip("/")
    brand = await get_setting("ui.brand_name", "Atlas")
    return HTMLResponse(docs_html(base, brand), headers={"Cache-Control": "public, max-age=600"})
