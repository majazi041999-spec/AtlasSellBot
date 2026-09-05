"""Representative API — auth, money safety and idempotency.

Plain `python tests/test_rep_api.py` — no test framework, because the project
has none and this needs to stay runnable on the server.

What is being protected here: this is the first endpoint a THIRD PARTY calls,
with a credential that spends a representative's wallet. Three failure modes
would each cost real money, and none of them are visible by reading the code:

  * **A charge that isn't refunded when provisioning fails.** The panels go down;
    if the wallet keeps the money the rep is silently robbed. Every failure path
    below asserts the balance is byte-for-byte what it was before the call.
  * **A retry that charges twice.** Reseller bots retry on timeout. Without
    Idempotency-Key support, one network hiccup sells the same service twice.
  * **A key that outlives its authorisation.** Losing rep status or being
    blocked must kill every key immediately, without a revocation step.

Provisioning itself is not exercised — it needs live x-ui panels. With no nodes
configured the engine fails fast, which is exactly the path the refund logic
lives on, so the money assertions are the real ones.
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The DB path is relative, so the whole test runs inside a throwaway directory
# and never touches a real atlas.db. Must happen before the app is imported.
_WORKDIR = tempfile.mkdtemp(prefix="atlas-repapi-")
os.chdir(_WORKDIR)
os.environ.setdefault("WEB_SECRET_PATH", "TestPanel")
os.environ.setdefault("BOT_TOKEN", "")

from fastapi.testclient import TestClient  # noqa: E402

from core import rep_api  # noqa: E402
from core.database import (  # noqa: E402
    add_package,
    add_user_balance,
    create_subscription_profile,
    get_or_create_user,
    get_user_balance,
    get_user_by_id,
    set_setting,
    update_user,
)
from web.app import app  # noqa: E402

# The report contains tick marks and Persian payloads; a Windows console
# defaults to cp1252 and would crash on the first one.
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


def check_true(label, got):
    check(label, bool(got), True)


async def main():
    # Peer set to loopback so this mirrors the real deployment (a proxy on the
    # same box). client_ip() only honours forwarded headers from a trusted
    # peer, and TestClient otherwise reports the literal "testclient".
    client = TestClient(app, client=("127.0.0.1", 40000))
    with client:  # triggers startup → init_db() → creates the schema
        print("1. seed a representative with a wallet and a tariff")
        rep = await get_or_create_user(700100, "reseller", "Reza Reseller")
        await update_user(rep["id"], is_wholesale=1, price_per_gb=3000, unlimited_price=0,
                          discount_percent=0, rep_topup_required=0)
        await add_user_balance(rep["id"], 500_000, kind="manual", note="test seed")
        pkg_id = await add_package("۱۰ گیگ یک‌ماهه", 10, 30, 200_000, "test package")
        # A second account proves cross-tenant isolation later.
        other = await get_or_create_user(700200, "other", "Other Rep")
        await update_user(other["id"], is_wholesale=1)
        other_pid = await create_subscription_profile(
            other["id"], 0, "tok-other", "sub_other", 10, 30, 0)
        check("rep balance", await get_user_balance(rep["id"]), 500_000)

        made = await rep_api.create_key(rep["id"], name="test bot")
        check_true("key issued", made.get("ok"))
        KEY = made["key"]
        check_true("key carries its prefix", KEY.startswith(rep_api.KEY_PREFIX))
        H = {"Authorization": f"Bearer {KEY}"}

        print("\n2. the key itself is never stored — only its hash")
        rows = await rep_api.list_keys(rep["id"])
        check("one active key", len(rows), 1)
        check_true("plaintext absent from the row", KEY not in str(dict(rows[0])))
        check("prefix is a prefix of the key", KEY.startswith(rows[0]["prefix"]), True)

        print("\n3. authentication")
        check("no key → 401", client.get("/api/rep/v1/ping").status_code, 401)
        check("no key → missing_key", client.get("/api/rep/v1/ping").json()["error"], "missing_key")
        bad = client.get("/api/rep/v1/ping", headers={"Authorization": "Bearer atlas_rep_totally_wrong_key_x"})
        check("wrong key → 401", bad.status_code, 401)
        check("wrong key → invalid_key", bad.json()["error"], "invalid_key")
        ok = client.get("/api/rep/v1/ping", headers=H)
        check("valid key → 200", ok.status_code, 200)
        check("identifies the representative", ok.json()["representative_id"], rep["id"])
        check_true("rate headers are present", "X-RateLimit-Remaining" in ok.headers)
        check("responses are never cached", ok.headers.get("Cache-Control"), "no-store")
        check("X-API-Key header also works",
              client.get("/api/rep/v1/ping", headers={"X-API-Key": KEY}).status_code, 200)

        print("\n4. /me and /packages carry THIS rep's numbers")
        me = client.get("/api/rep/v1/me", headers=H).json()
        check("balance", me["representative"]["balance"], 500_000)
        check("per-GB tariff", me["pricing"]["price_per_gb"], 3000)
        pkgs = client.get("/api/rep/v1/packages", headers=H).json()["packages"]
        check("one package", len(pkgs), 1)
        # 10 GB × 3000 = 30,000 — the rep price, not the 200,000 list price.
        check("priced at the rep tariff", pkgs[0]["price"], 30_000)
        # Our retail price is deliberately NOT exposed: a rep sets their own
        # prices, and their customers must never see ours next to theirs.
        check("our retail price is not exposed", "list_price" in pkgs[0], False)

        print("\n5. authorisation is re-read from the user row on every call")
        await update_user(rep["id"], is_wholesale=0)
        lost = client.get("/api/rep/v1/ping", headers=H)
        check("losing rep status kills the key instantly", lost.json()["error"], "not_a_representative")
        check("…with 403", lost.status_code, 403)
        await update_user(rep["id"], is_wholesale=1, is_blocked=1)
        check("a blocked account is refused",
              client.get("/api/rep/v1/ping", headers=H).json()["error"], "account_blocked")
        await update_user(rep["id"], is_blocked=0)
        check("restoring access works", client.get("/api/rep/v1/ping", headers=H).status_code, 200)

        print("\n6. scopes")
        ro = await rep_api.create_key(rep["id"], name="read only", scopes="read")
        RH = {"Authorization": f"Bearer {ro['key']}"}
        check("read key can read", client.get("/api/rep/v1/services", headers=RH).status_code, 200)
        w = client.post("/api/rep/v1/services", headers=RH, json={"package_id": pkg_id})
        check("read key cannot write", w.status_code, 403)
        check("…with insufficient_scope", w.json()["error"], "insufficient_scope")
        await rep_api.revoke_key(int(ro["id"]), rep["id"])
        check("a revoked key stops working",
              client.get("/api/rep/v1/ping", headers=RH).json()["error"], "invalid_key")

        print("\n7. a bad request never touches the wallet")
        before = await get_user_balance(rep["id"])
        r = client.post("/api/rep/v1/services", headers=H, json={})
        check("empty body → 400", r.status_code, 400)
        check("…invalid_request", r.json()["error"], "invalid_request")
        r = client.post("/api/rep/v1/services", headers=H, json={"package_id": 9999})
        check("unknown package → package_unavailable", r.json()["error"], "package_unavailable")
        r = client.post("/api/rep/v1/services", headers=H, json={"traffic_gb": 0, "duration_days": 30})
        check("unlimited with no tariff → custom_pricing_unavailable",
              r.json()["error"], "custom_pricing_unavailable")
        check("balance untouched by rejected requests", await get_user_balance(rep["id"]), before)

        print("\n8. insufficient balance is refused BEFORE any charge")
        # Drain the wallet rather than inflating the order — the assertion is
        # about the balance check firing before any debit, not about the price.
        await add_user_balance(rep["id"], -(await get_user_balance(rep["id"])) + 5_000,
                               kind="manual", note="drain")
        broke = await get_user_balance(rep["id"])
        r = client.post("/api/rep/v1/services", headers=H, json={"package_id": pkg_id})
        check("→ 402", r.status_code, 402)
        check("…insufficient_balance", r.json()["error"], "insufficient_balance")
        check("the shortfall is reported", r.json()["required"], 30_000)
        check("balance untouched", await get_user_balance(rep["id"]), broke)

        print("\n9. provisioning failure refunds every rial")
        # No subscription nodes are configured in this throwaway DB, so the
        # engine fails immediately — the exact path the refund lives on.
        await add_user_balance(rep["id"], 200_000, kind="manual", note="refill")
        before = await get_user_balance(rep["id"])
        r = client.post("/api/rep/v1/services", headers=H, json={"package_id": pkg_id, "count": 2})
        check("→ 502", r.status_code, 502)
        check("…provisioning_failed", r.json()["error"], "provisioning_failed")
        check("FULL refund, to the rial", await get_user_balance(rep["id"]), before)
        check("the refund is reported back", r.json()["balance"], before)
        orders = client.get("/api/rep/v1/orders", headers=H).json()["orders"]
        check("the failed order is recorded, not approved", orders[0]["status"], "rejected")

        print("\n10. Idempotency-Key: a retry is a replay, not a second charge")
        before = await get_user_balance(rep["id"])
        body = {"package_id": pkg_id, "name": "ali"}
        idem = {"Idempotency-Key": "order-4471", **H}
        first = client.post("/api/rep/v1/services", headers=idem, json=body)
        second = client.post("/api/rep/v1/services", headers=idem, json=body)
        check("same status on retry", second.status_code, first.status_code)
        check("marked as a replay", second.json().get("idempotent_replay"), True)
        check("same error payload", second.json()["error"], first.json()["error"])
        check("balance unchanged by the retry", await get_user_balance(rep["id"]), before)
        conflict = client.post("/api/rep/v1/services", headers=idem,
                               json={"package_id": pkg_id, "name": "SOMEONE ELSE"})
        check("same key + different body → 409", conflict.status_code, 409)
        check("…idempotency_conflict", conflict.json()["error"], "idempotency_conflict")

        print("\n11. one representative can never see another's services")
        r = client.get(f"/api/rep/v1/services/{other_pid}", headers=H)
        check("someone else's service → 404, not 403", r.status_code, 404)
        check("…service_not_found", r.json()["error"], "service_not_found")
        check("renewing it is refused too",
              client.post(f"/api/rep/v1/services/{other_pid}/renew", headers=H,
                          json={"package_id": pkg_id}).status_code, 404)
        check("so is deleting it",
              client.post(f"/api/rep/v1/services/{other_pid}/delete", headers=H,
                          json={"confirm": True}).status_code, 404)
        check("other rep's balance never moved", await get_user_balance(other["id"]), 0)

        print("\n12. destructive actions need an explicit confirmation")
        own_pid = await create_subscription_profile(rep["id"], 0, "tok-mine", "sub_mine", 10, 30, 0)
        r = client.post(f"/api/rep/v1/services/{own_pid}/delete", headers=H, json={})
        check("delete without confirm → 400", r.status_code, 400)
        check("…confirmation_required", r.json()["error"], "confirmation_required")

        print("\n13. listing, paging and renaming")
        lst = client.get("/api/rep/v1/services?per_page=1", headers=H).json()
        check("only this rep's services", lst["pagination"]["total"], 1)
        check("page size honoured", len(lst["services"]), 1)
        check("unlimited is not reported as zero traffic", lst["services"][0]["unlimited"], False)
        r = client.post(f"/api/rep/v1/services/{own_pid}/rename", headers=H, json={"name": "ali-laptop"})
        check("rename works", r.json()["name"], "ali-laptop")
        r = client.post(f"/api/rep/v1/services/{own_pid}/rename", headers=H,
                        json={"name": "<script>alert(1)</script>"})
        check("markup is stripped from names", "<" in r.json()["name"], False)
        srt = client.get("/api/rep/v1/services?sort=nonsense&filter=nonsense", headers=H)
        check("a junk sort/filter cannot 500 the list", srt.status_code, 200)

        print("\n14. IP allowlist")
        pinned = await rep_api.create_key(rep["id"], name="pinned", ip_allowlist="203.0.113.7")
        PH = {"Authorization": f"Bearer {pinned['key']}"}
        r = client.get("/api/rep/v1/ping", headers=PH)
        check("wrong IP → 403", r.status_code, 403)
        check("…ip_not_allowed", r.json()["error"], "ip_not_allowed")
        r = client.get("/api/rep/v1/ping", headers={**PH, "CF-Connecting-IP": "203.0.113.7"})
        check("allowed IP passes", r.status_code, 200)
        # The allowlist is only worth anything if the IP cannot be self-declared.
        # A forwarded header is honoured ONLY from a trusted peer — see
        # core/client_app.py:client_ip. Without that, a rep could walk straight
        # past their own pin by adding one header.
        from core.client_app import client_ip as _cip

        class _Direct:
            client = type("C", (), {"host": "198.51.100.4"})()
            headers = {"cf-connecting-ip": "203.0.113.7"}

        check("a direct caller cannot self-declare the allowed IP",
              _cip(_Direct()), "198.51.100.4")
        check("a malformed allowlist entry is dropped, not trusted",
              rep_api.normalize_allowlist("1.2.3.4, not-an-ip, 10.0.0.0/8"), "1.2.3.4,10.0.0.0/8")
        check("an empty allowlist means 'any'", rep_api.ip_allowed("", "8.8.8.8"), True)
        await rep_api.revoke_key(int(pinned["id"]), rep["id"])

        print("\n15. rate limiting")
        fast = await rep_api.create_key(rep["id"], name="ratelimited", rate_per_min=10)
        FH = {"Authorization": f"Bearer {fast['key']}"}
        codes = [client.get("/api/rep/v1/ping", headers=FH).status_code for _ in range(13)]
        check("the first 10 pass", codes[:10], [200] * 10)
        check("the 11th is throttled", codes[10], 429)
        limited = client.get("/api/rep/v1/ping", headers=FH)
        check("…rate_limited", limited.json()["error"], "rate_limited")
        check_true("Retry-After is set", limited.headers.get("Retry-After"))
        await rep_api.revoke_key(int(fast["id"]), rep["id"])

        print("\n16. the owner's kill switch turns the whole API off")
        await set_setting("rep_api_enabled", "0")
        r = client.get("/api/rep/v1/ping", headers=H)
        check("→ 503", r.status_code, 503)
        check("…api_disabled", r.json()["error"], "api_disabled")
        await set_setting("rep_api_enabled", "1")
        check("and back on", client.get("/api/rep/v1/ping", headers=H).status_code, 200)

        print("\n17. the docs page is public and self-describing")
        await set_setting("public_base_url", "https://vpn.example.com")
        d = client.get("/api/rep/docs")
        check("served without a key", d.status_code, 200)
        check_true("shows this install's base URL", "https://vpn.example.com/api/rep/v1" in d.text)
        check_true("documents the idempotency header", "Idempotency-Key" in d.text)
        check_true("never leaks the admin secret path", os.environ["WEB_SECRET_PATH"] not in d.text)
        check_true("all three languages are offered",
                   all(t in d.text for t in (">PHP<", ">Python<", ">Node.js<")))
        # An un-replaced placeholder would ship a literal "__BASE__" to every
        # representative — the samples are meant to be copy-pasted as-is.
        check("no unreplaced placeholders", "__BASE__" in d.text or "__BRAND__" in d.text, False)
        check_true("warns about the Cloudflare 100s cutoff", "524" in d.text)

        print("\n18. the minimum-topup rule applies to the API too")
        await update_user(rep["id"], rep_topup_required=1)
        # The rule counts EVERY wallet credit, refunds included, so the bar has
        # to be set above what this account has already been credited.
        from core.database import get_user_total_topups
        await set_setting("rep_min_topup", str(await get_user_total_topups(rep["id"]) + 1))
        r = client.post("/api/rep/v1/services", headers=H, json={"package_id": pkg_id})
        check("selling is gated → 403", r.status_code, 403)
        check("…topup_required", r.json()["error"], "topup_required")
        check("reads are still allowed", client.get("/api/rep/v1/me", headers=H).status_code, 200)
        await update_user(rep["id"], rep_topup_required=0)

        print("\n19. an 'unlimited' plan is priced as unlimited but provisioned verbatim")
        # traffic_gb on an unlimited plan is the FAIR-USE THRESHOLD, not a volume.
        # Pricing must ignore it; provisioning must not. Getting this backwards
        # would hand API buyers genuinely unlimited traffic while bot buyers got 100 GB.
        await update_user(rep["id"], unlimited_price=180_000)
        unl_id = await add_package("نامحدود ماهانه", 100, 30, 900_000, "", 0, 1)
        pkgs = {p["id"]: p for p in client.get("/api/rep/v1/packages", headers=H).json()["packages"]}
        check("flagged as unlimited", pkgs[unl_id]["unlimited"], True)
        check("priced from the rep's unlimited rate, not 100 × per-GB",
              pkgs[unl_id]["price"], 180_000)
        from web.rep_api import _resolve_plan
        plan = await _resolve_plan({"package_id": unl_id}, await get_user_by_id(rep["id"]))
        check("the fair-use threshold is what gets provisioned", plan["traffic_gb"], 100.0)
        check("…at the unlimited price", plan["unit_price"], 180_000)

        print("\n20. an unexpected crash after the debit still refunds")
        # The engine returning ok:False is the easy case (section 9). This is the
        # hard one: something between the debit and the response blows up. If the
        # guard is ever removed, the rep is charged for nothing and there is no
        # order row to reconcile it against.
        import web.rep_api as _api

        def _boom(*a, **kw):
            raise RuntimeError("panel exploded mid-provision")

        real_create, _api.create_profile_for_order = _api.create_profile_for_order, _boom
        try:
            before = await get_user_balance(rep["id"])
            r = client.post("/api/rep/v1/services", headers=H, json={"package_id": pkg_id})
            check("→ 500", r.status_code, 500)
            check("…internal_error", r.json()["error"], "internal_error")
            check("the wallet is made whole anyway", await get_user_balance(rep["id"]), before)
        finally:
            _api.create_profile_for_order = real_create

        print("\n21. a crashed attempt does not poison its idempotency key")
        # idem_abort releases the claim, so the caller's retry is a real attempt
        # rather than a permanent 'request_in_flight'.
        _api.create_profile_for_order = _boom
        try:
            hdrs = {"Idempotency-Key": "retry-me", **H}
            client.post("/api/rep/v1/services", headers=hdrs, json={"package_id": pkg_id})
        finally:
            _api.create_profile_for_order = real_create
        again = client.post("/api/rep/v1/services", headers={"Idempotency-Key": "retry-me", **H},
                            json={"package_id": pkg_id})
        check("the same key is usable again", again.json()["error"], "provisioning_failed")
        check("…not stuck in flight", again.status_code, 502)

    print("\n" + ("ALL PASSED" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}"))
    return 1 if FAILED else 0


sys.exit(asyncio.run(main()))
