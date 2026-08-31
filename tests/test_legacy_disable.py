"""Bulk-disabling legacy configs — the rules that keep it from taking customers down.

Plain `python tests/test_legacy_disable.py` — no test framework, because the
project has none and this needs to stay runnable on the server.

What is being protected here. This sweep switches off hundreds of clients on
live panels, and legacy configs share inbounds with subscription nodes. Three
mistakes would each be an outage rather than a bug report:

  * **Touching a subscription client.** Selection is by email, and on the live
    database one legacy row carries an email in the subscription namespace
    (`…_n2`) on a shared inbound. Disabling it would cut off a paying
    subscriber. Every such email must be filtered out BEFORE the panel call.
  * **One write per client.** 3x-ui reloads xray on every client write, which
    drops every live connection on that server. 200 clients disabled one at a
    time is 200 reloads and a fleet-wide stutter; the whole point of
    `bulkDisable` is one read-modify-write per inbound. The test counts calls.
  * **Marking a row inactive that is still enabled on the panel.** A config we
    failed to disable must stay flagged active so the next run retries it —
    otherwise it vanishes from the list while still passing traffic.
"""
import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_WORKDIR = tempfile.mkdtemp(prefix="atlas-legacy-")
os.chdir(_WORKDIR)
os.environ.setdefault("WEB_SECRET_PATH", "TestPanel")
os.environ.setdefault("BOT_TOKEN", "")

import core.legacy_configs as lc  # noqa: E402
from core.database import (  # noqa: E402
    add_server, add_subscription_node, create_subscription_profile,
    get_or_create_user, init_db, save_config, update_config,
)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAILED = []
NOW = int(time.time() * 1000)
DAY = 86_400_000


def check(label, got, want):
    ok = got == want
    print(f"   {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f"  (expected {want!r})"))
    if not ok:
        FAILED.append(label)


class FakeXUI:
    """Records what the sweep asked the panel to do."""
    calls = []          # every bulk call: (emails, enabled)
    per_client = []     # every single-client write
    mode = "ok"         # ok | old_panel | error
    not_found = set()   # emails the panel reports as missing
    refuse = set()      # emails the panel refuses to change

    def __init__(self, url, user, pw, sub_path="", token=""):
        self.url = url
        self.last_error = ""

    async def bulk_set_clients_enabled(self, emails, enabled):
        FakeXUI.calls.append((list(emails), enabled))
        if FakeXUI.mode == "old_panel":
            self.last_error = "HTTP 404: page not found"
            return None
        if FakeXUI.mode == "error":
            self.last_error = "HTTP 401: unauthorized"
            return None
        skipped = []
        changed = 0
        for e in emails:
            if e in FakeXUI.not_found:
                skipped.append({"email": e, "reason": "client not found"})
            elif e in FakeXUI.refuse:
                skipped.append({"email": e, "reason": "inbound is locked"})
            else:
                changed += 1
        return {"changed": changed, "skipped": skipped}

    async def update_client(self, inbound_id, uuid, email, traffic_gb, expire_ms, enable=True):
        FakeXUI.per_client.append((email, enable))
        return email not in FakeXUI.refuse

    async def close(self):
        pass

    @classmethod
    def reset(cls, mode="ok"):
        cls.calls, cls.per_client = [], []
        cls.mode, cls.not_found, cls.refuse = mode, set(), set()


lc.XUIClient = FakeXUI


async def db_active():
    import aiosqlite
    async with aiosqlite.connect("atlas.db") as db:
        async with db.execute("SELECT id FROM configs WHERE is_active=1 ORDER BY id") as c:
            return [r[0] for r in await c.fetchall()]


async def reactivate_all():
    import aiosqlite
    async with aiosqlite.connect("atlas.db") as db:
        await db.execute("UPDATE configs SET is_active=1")
        await db.commit()


async def main():
    await init_db()

    print("1. seed: expired + live legacy configs, an orphan, and a booby trap")
    user = await get_or_create_user(900001, "cust", "Customer")
    s1 = await add_server("سرور یک", "http://127.0.0.1:1", "u", "p", "sub", 1)
    s2 = await add_server("سرور دو", "http://127.0.0.1:2", "u", "p", "sub", 1)

    expired = NOW - 30 * DAY
    future = NOW + 30 * DAY
    c_exp1 = await save_config(user["id"], s1, "uuid-1", "old_ali", 1, 10, 30, expired)
    c_exp2 = await save_config(user["id"], s1, "uuid-2", "old_reza", 1, 10, 30, expired)
    c_exp3 = await save_config(user["id"], s2, "uuid-3", "old_sara", 3, 10, 30, expired)
    c_live = await save_config(user["id"], s1, "uuid-4", "old_active", 1, 10, 30, future)

    # A legacy row whose email belongs to the subscription namespace, on a
    # shared inbound. This shape exists on the live database.
    c_trap = await save_config(user["id"], s2, "uuid-5", "sub_u1_aa_1780_bb_n2", 3, 10, 30, expired)
    # …and one that IS a live subscription node, by email.
    profile = await create_subscription_profile(user["id"], 0, "tok1", "sub_u1_cc", 10, 30, future)
    await add_subscription_node(profile, s2, 3, "uuid-6", "sub_u1_cc_n7", "vless://x", config_id=7)
    c_trap2 = await save_config(user["id"], s2, "uuid-7", "sub_u1_cc_n7", 3, 10, 30, expired)

    # A config on a server row that no longer exists.
    c_orphan = await save_config(user["id"], 999, "uuid-8", "old_orphan", 1, 10, 30, expired)

    check("all seeded configs are active", len(await db_active()), 7)

    print("\n2. preview: what would happen, before touching anything")
    FakeXUI.reset()
    p = await lc.preview("expired")
    check("no panel call during preview", len(FakeXUI.calls), 0)
    check("expired candidates", p["total"], 6)          # everything but c_live
    check("reachable on panels", p["on_panels"], 3)     # old_ali, old_reza, old_sara
    check("orphaned", p["orphaned"], 1)
    check("protected from the sweep", p["protected"], 2)
    reasons = {x["reason"] for x in p["protected_samples"]}
    check("both protection reasons fire", reasons,
          {"belongs_to_a_subscription", "looks_like_a_subscription_node"})

    print("\n3. the sweep never sends a subscription email to a panel")
    FakeXUI.reset()
    res = await lc.disable_all("expired")
    sent = [e for call, _ in FakeXUI.calls for e in call]
    check("subscription-node email never sent", "sub_u1_cc_n7" in sent, False)
    check("look-alike email never sent", "sub_u1_aa_1780_bb_n2" in sent, False)
    check("the live config was never sent", "old_active" in sent, False)
    check("exactly the expired legacy ones were sent", sorted(sent),
          ["old_ali", "old_reza", "old_sara"])

    print("\n4. one call per server, not one per client")
    check("bulk calls", len(FakeXUI.calls), 2)          # server 1 and server 2
    check("no per-client writes on a modern panel", len(FakeXUI.per_client), 0)

    print("\n5. local flags now match the panel")
    left = await db_active()
    check("disabled count", res["disabled"], 4)         # 3 on panels + 1 orphan
    check("orphan reported", res["orphaned"], 1)
    check("protected reported", res["protected"], 2)
    check("still active = live one + the two protected", sorted(left),
          sorted([c_live, c_trap, c_trap2]))
    check("orphan was corrected locally", c_orphan in left, False)

    print("\n6. a client the panel refuses stays active, so the next run retries")
    await reactivate_all()
    FakeXUI.reset()
    FakeXUI.refuse = {"old_reza"}
    res = await lc.disable_all("expired")
    left = await db_active()
    check("refused client still flagged active", c_exp2 in left, True)
    check("its neighbours were still disabled", c_exp1 in left, False)
    check("failure is reported", res["failed"], 1)

    print("\n7. a client already gone from the panel is treated as done")
    await reactivate_all()
    FakeXUI.reset()
    FakeXUI.not_found = {"old_ali"}
    res = await lc.disable_all("expired")
    left = await db_active()
    check("missing client's row corrected", c_exp1 in left, False)
    check("not counted as a failure", res["failed"], 0)

    print("\n8. an old panel falls back to per-client writes")
    await reactivate_all()
    FakeXUI.reset(mode="old_panel")
    res = await lc.disable_all("expired")
    check("fell back", len(FakeXUI.per_client) > 0, True)
    check("fallback disabled, never enabled", {en for _, en in FakeXUI.per_client}, {False})
    check("fallback still skipped protected emails",
          {e for e, _ in FakeXUI.per_client} & {"sub_u1_cc_n7", "sub_u1_aa_1780_bb_n2"}, set())
    check("all three disabled via fallback", res["disabled"], 4)

    print("\n9. a panel error does NOT degrade into N failing writes")
    await reactivate_all()
    FakeXUI.reset(mode="error")
    res = await lc.disable_all("expired")
    check("no per-client storm", len(FakeXUI.per_client), 0)
    check("nothing marked disabled on those servers", res["disabled"], 1)  # orphan only
    check("failures reported", res["failed"], 3)
    left = await db_active()
    check("panel configs stay active for a retry", c_exp1 in left and c_exp3 in left, True)

    print("\n10. scope=all also targets the still-valid config")
    await reactivate_all()
    FakeXUI.reset()
    p = await lc.preview("all")
    check("all-scope candidates", p["total"], 7)
    res = await lc.disable_all("all")
    sent = [e for call, _ in FakeXUI.calls for e in call]
    check("the live one is included now", "old_active" in sent, True)
    check("but protected emails still are not",
          bool({"sub_u1_cc_n7", "sub_u1_aa_1780_bb_n2"} & set(sent)), False)

    print("\n11. protection helper, directly")
    check("plain legacy email is fine", lc._is_protected("old_ali", set()), None)
    check("subscription suffix is refused", lc._is_protected("x_n12", set()),
          "looks_like_a_subscription_node")
    check("known node email is refused", lc._is_protected("what", {"what"}),
          "belongs_to_a_subscription")
    check("empty email is refused", lc._is_protected("", set()), "no_email")
    check("a name merely containing _n is fine", lc._is_protected("ali_north", set()), None)

    print("\n" + ("ALL PASSED" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}"))
    return 1 if FAILED else 0


sys.exit(asyncio.run(main()))
