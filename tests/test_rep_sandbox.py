"""The reseller API's sandbox — can somebody build against it and then switch?

Plain `python tests/test_rep_sandbox.py`.

WHAT IS BEING PROTECTED. The sandbox has exactly one promise: write your code
against a test key, swap in the live key, change nothing else. Every way that
promise can break is silent — a field that only exists in production, an error
code that differs, a status string spelled differently — and the integrator
finds out when their first real customer gets a broken response.

So the central test is not "does the sandbox work", it is **does the sandbox
answer with the same SHAPE as production**. Section 3 compares the two field by
field against the real `_service_payload`.

The other half is the opposite promise: that a test key can never touch
anything real. Section 2 walks the whole surface with a sandbox key and asserts
no wallet moved and no panel was called — the failure there would be a reseller
running their test suite against live customers.
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(tempfile.mkdtemp(prefix="atlas-sandbox-"))
os.environ.setdefault("WEB_SECRET_PATH", "SandboxTest")
os.environ.setdefault("BOT_TOKEN", "")

from starlette.testclient import TestClient  # noqa: E402

from core.database import init_db, set_setting  # noqa: E402
import core.rep_api as rep_api  # noqa: E402
import core.rep_sandbox as sandbox  # noqa: E402

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


PANEL_CALLS = []


async def setup():
    import aiosqlite
    from core.config import DB_PATH
    await init_db()
    await set_setting("rep_api_enabled", "1")
    await set_setting("rep_min_topup", "500000")      # a gate the sandbox must ignore
    await set_setting("test_account_enabled", "1")
    await set_setting("rep_test_daily_limit", "0")    # trials OFF for live keys
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO users (telegram_id, full_name, is_wholesale, price_per_gb,
                                  unlimited_price, rep_topup_required)
               VALUES (4242,'a reseller',1,10000,199000,1)""")
        await db.commit()
        async with db.execute("SELECT id FROM users WHERE telegram_id=4242") as c:
            uid = (await c.fetchone())[0]
    live = await rep_api.create_key(uid, "prod")
    test = await rep_api.create_key(uid, "test", sandbox=True)
    return uid, live["key"], test["key"]


def main():
    uid, live_key, test_key = asyncio.run(setup())

    # The panel client must never be reached by a sandbox call. Anything that
    # tries is recorded and fails the run.
    import core.multi_subscription as ms

    class Tripwire:
        def __init__(self, *a, **k):
            PANEL_CALLS.append("XUIClient constructed")

        def __getattr__(self, name):
            PANEL_CALLS.append(name)
            raise AssertionError(f"sandbox reached the panel: {name}")

    ms.XUIClient = Tripwire

    from web.app import app
    S = os.environ["WEB_SECRET_PATH"]

    with TestClient(app) as c:
        H = {"Authorization": f"Bearer {test_key}"}
        LIVE = {"Authorization": f"Bearer {live_key}"}
        base = "/api/rep/v1"

        print("1. the key announces itself before anything is spent")
        r = c.get(f"{base}/sandbox", headers=H)
        check("sandbox info is 200", r.status_code, 200)
        d = r.json()
        check("it says it is a sandbox", d["sandbox"], True)
        check("and shows the play wallet", d["wallet"], sandbox.STARTING_BALANCE)
        rl = c.get(f"{base}/sandbox", headers=LIVE).json()
        check("a live key is told it is live", rl["sandbox"], False)
        check("and has no play wallet", rl["wallet"], None)
        # The reset route is the one thing that must never work on a live key.
        check("a live key cannot reset anything",
              c.post(f"{base}/sandbox/reset", headers=LIVE).status_code, 403)

        print("\n2. the whole surface works without money or panels")
        check("ping", c.get(f"{base}/ping", headers=H).status_code, 200)
        me = c.get(f"{base}/me", headers=H).json()
        check("me reports the sandbox wallet", me["representative"]["balance"],
              sandbox.STARTING_BALANCE)
        check("and flags the key", me["key"]["sandbox"], True)

        # The minimum-topup rule gates real selling. A brand-new rep must still
        # be able to learn the API, so the sandbox ignores it — while the live
        # key on the same account is correctly refused.
        made = c.post(f"{base}/services", headers=H,
                      json={"traffic_gb": 20, "duration_days": 30, "name": "first"})
        check("creating a service works", made.status_code, 200)
        body = made.json()
        check("...and says it was a sandbox", body["sandbox"], True)
        check("...and made one", body["created"], 1)
        sid = body["services"][0]["id"]
        blocked = c.post(f"{base}/services", headers=LIVE,
                         json={"traffic_gb": 20, "duration_days": 30})
        check("the same call on the live key is still gated",
              blocked.json().get("error"), "topup_required")

        check("the wallet really moved",
              c.get(f"{base}/wallet", headers=H).json()["balance"] < sandbox.STARTING_BALANCE, True)
        check("listing shows it", c.get(f"{base}/services", headers=H).json()["pagination"]["total"], 1)
        check("detail works", c.get(f"{base}/services/{sid}", headers=H).status_code, 200)
        check("rename works",
              c.post(f"{base}/services/{sid}/rename", headers=H, json={"name": "renamed"})
               .json()["name"], "renamed")
        check("disable works",
              c.post(f"{base}/services/{sid}/disable", headers=H).json()["service"]["is_active"], False)
        check("enable works",
              c.post(f"{base}/services/{sid}/enable", headers=H).json()["service"]["is_active"], True)
        old_url = c.get(f"{base}/services/{sid}", headers=H).json()["service"]["subscription_url"]
        rev = c.post(f"{base}/services/{sid}/revoke", headers=H).json()
        check("revoke issues a new link", rev["subscription_url"] != old_url, True)
        ren = c.post(f"{base}/services/{sid}/renew", headers=H,
                     json={"traffic_gb": 20, "duration_days": 30})
        check("renew works", ren.status_code, 200)
        check("...and charges again", ren.json()["charged"] > 0, True)

        # Trials are switched OFF for live keys here (daily limit 0), which is
        # exactly when an integrator most needs to be able to test the call.
        tr = c.post(f"{base}/services/trial", headers=H)
        check("trial works even with the live allowance at zero", tr.status_code, 200)
        check("...and costs nothing", tr.json()["charged"], 0)
        check("the live key is still correctly refused",
              c.post(f"{base}/services/trial", headers=LIVE).json().get("error"), "trial_disabled")

        conn = c.get(f"{base}/services/{sid}/connections", headers=H)
        check("connections answers", conn.status_code, 200)
        check("...with a count", isinstance(conn.json()["connections"], int), True)
        check("...marked as sandbox", conn.json()["sandbox"], True)

        check("orders lists the charges",
              len(c.get(f"{base}/orders", headers=H).json()["orders"]) >= 2, True)
        check("delete needs confirmation",
              c.post(f"{base}/services/{sid}/delete", headers=H, json={}).json()["error"],
              "confirmation_required")
        check("delete works with it",
              c.post(f"{base}/services/{sid}/delete", headers=H, json={"confirm": True})
               .status_code, 200)
        check("and it is gone",
              c.get(f"{base}/services/{sid}", headers=H).status_code, 404)

        check("NOT ONE panel call was made", PANEL_CALLS, [])

        print("\n3. the shape matches production, field for field")
        # The promise is "swap the key and change nothing". A field that exists
        # in one and not the other breaks it silently, at the worst moment.
        from web.rep_api import _service_payload
        fake_profile = {"id": 1, "name": "x", "email": "e", "traffic_gb": 20.0,
                        "used_bytes": 5 * 1024 ** 3, "expire_timestamp": 1_800_000_000_000,
                        "is_active": 1, "starts_on_first_use": 0, "first_use_at": 0,
                        "duration_days": 30, "created_at": "2026-01-01 00:00:00"}
        prod = set(_service_payload(fake_profile, "https://x/sub/y", 1_700_000_000_000))
        made2 = c.post(f"{base}/services", headers=H,
                       json={"traffic_gb": 5, "duration_days": 7, "name": "shape"}).json()
        sbx = set(made2["services"][0])
        missing = sorted(prod - sbx)
        check("no production field is missing from a sandbox service", missing, [])
        check("the only addition is the sandbox marker", sorted(sbx - prod), ["sandbox"])
        st = made2["services"][0]["status"]
        check("status uses the production vocabulary",
              st in {"active", "disabled", "expired", "exhausted", "not_started", "deleted"}, True)

        print("\n4. a runaway test loop finds the bottom, it does not find real money")
        # insufficient_funds is one of the two errors integrators must handle and
        # the hardest to provoke deliberately in production.
        for _ in range(60):
            r = c.post(f"{base}/services", headers=H,
                       json={"traffic_gb": 100, "duration_days": 30, "count": 5})
            if r.status_code != 200:
                break
        check("it eventually refuses", r.status_code, 402)
        check("with the error a live key would give", r.json()["error"], "insufficient_funds")

        print("\n5. reset gives them a clean bench")
        rs = c.post(f"{base}/sandbox/reset", headers=H).json()
        check("the wallet is refilled", rs["balance"], sandbox.STARTING_BALANCE)
        check("and the services are gone",
              c.get(f"{base}/services", headers=H).json()["pagination"]["total"], 0)

    print("\n" + ("ALL PASSED" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
