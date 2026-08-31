"""Per-subscription concurrent-IP limit — does it catch sharers without cutting customers?

Plain `python tests/test_ip_guard.py` — no test framework, because the project
has none and this needs to stay runnable on the server.

WHAT IS BEING PROTECTED. This feature switches paying customers off. The failure
that matters is not "a sharer got away with it" — it is "a commuter on Irancell
lost their connection for an hour because their SIM changed IP". So the central
tests are the false-positive ones, and they are written from the mechanism, not
from a guess:

  * Xray's online map is refcounted on live connections, so it holds an address
    only while that address has an open connection. But it does NOT reap a
    half-open connection promptly — `connIdle` is 300 seconds by default. So
    after a Wi-Fi-to-mobile handover a single phone really is visible on two
    addresses for up to five minutes.
  * The discriminator is the timestamp. Xray refreshes an address's lastSeen
    only when a connection dispatches something NEW, so the abandoned address
    carries a frozen timestamp while the live one keeps advancing.
  * 3x-ui's bulk endpoint destroys that signal — it re-stamps every address with
    the scan time — which is why the guard confirms a suspicion against the
    per-email endpoint before it does anything. `test 6` is that test, and it is
    the one that would have to fail before a customer is wrongly cut.

The rest cover the ways this can be wrong while still looking like it works: a
ladder that skips a rung, a penalty that outlives a restart, a dry run that
cuts anyway, and a panel outage read as "nobody is connected".
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.ip_guard as ipg  # noqa: E402
from core.ip_guard import (  # noqa: E402
    ACT_CUT, ACT_NONE, ACT_REASSERT, ACT_RESTORE, ACT_WARN, DEFAULTS,
    count_concurrent, decide, group_key, parse_steps,
)

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


NOW = 1_800_000_000
LADDER = dict(strikes_needed=4, steps=[60, 600, 3600], decay_seconds=86400,
              warn_cooldown=3600, grace_seconds=300, reassert_after=300)


def run(state, count, limit=5, now=NOW, **over):
    return decide(state, count, limit, now, **{**LADDER, **over})




# --------------------------------------------------------------- the cycle

class FakePanel:
    """Stands in for XUIClient, and counts every request it is asked to make.

    The owner's first requirement was that this not slow anything down, so the
    request count is not an incidental detail here — it is the thing under test.
    """
    # scripted per-server: {server_url: {email: {ip: ts}}}
    IPS = {}
    ONLINE = {}
    CALLS = []          # ("bulk_ips"|"onlines"|"per_email"|"disable"|"enable", url, detail)
    FAIL_BULK = set()   # server urls whose bulk read fails

    def __init__(self, url, user, pw, sub_path="", api_token=""):
        self.url = url
        self.last_error = ""

    async def get_client_ips_bulk(self):
        """The bulk view — and it RE-STAMPS every address with the scan time.

        That is what the real panel does (`node_client_ip` is written with
        `attrTs = now`), and modelling it is the whole point: without the
        re-stamp the test would never exercise stage two, which exists purely
        because this view cannot tell a busy address from a half-open one.

        Returns the real method's contract, {email: {ip: ts}} — the guid-keyed
        unwrapping is XUIClient's job and is covered on its own in section 20.
        """
        FakePanel.CALLS.append(("bulk_ips", self.url, None))
        if self.url in FakePanel.FAIL_BULK:
            return None
        now = int(time.time())
        return {e: {ip: now for ip in m}
                for e, m in FakePanel.IPS.get(self.url, {}).items()}

    # get_client_ips (below) returns the TRUE last-seen times, unmodified.

    async def get_onlines_checked(self):
        FakePanel.CALLS.append(("onlines", self.url, None))
        return list(FakePanel.ONLINE.get(self.url, [])), True

    async def get_client_ips(self, email):
        FakePanel.CALLS.append(("per_email", self.url, email))
        return dict(FakePanel.IPS.get(self.url, {}).get(email, {}))

    async def bulk_set_clients_enabled(self, emails, enabled):
        FakePanel.CALLS.append(("enable" if enabled else "disable", self.url, tuple(sorted(emails))))
        return {"changed": len(emails), "skipped": []}

    async def close(self):
        pass

    @classmethod
    def reset(cls):
        cls.CALLS = []
        cls.FAIL_BULK = set()

    @classmethod
    def count(cls, kind):
        return sum(1 for c in cls.CALLS if c[0] == kind)


async def _seed(db_dir, profiles=1, nodes_per=3):
    """A miniature of the real shape: one server per node slot, N subscriptions."""
    import aiosqlite
    from core.database import (
        DB_PATH, init_db, add_server, get_or_create_user, set_setting,
    )
    await init_db()
    urls = [f"https://srv{i}.example.test" for i in range(nodes_per)]
    for i, u in enumerate(urls):
        await add_server(f"srv{i}", u, "user", "pass", "", 1)
    async with aiosqlite.connect(DB_PATH) as db:
        for p in range(profiles):
            uid = 1000 + p
            await db.execute(
                "INSERT OR IGNORE INTO users (telegram_id, full_name) VALUES (?,?)",
                (500000 + p, f"customer {p}"))
            await db.execute(
                """INSERT INTO subscription_profiles
                       (user_id, token, email, name, traffic_gb, duration_days,
                        expire_timestamp, is_active)
                   VALUES ((SELECT id FROM users WHERE telegram_id=?),?,?,?,?,?,?,1)""",
                (500000 + p, f"tok{p}", f"sub{p}", f"sub {p}", 50, 30,
                 int(time.time() + 86400) * 1000))
            async with db.execute("SELECT id FROM subscription_profiles WHERE token=?",
                                  (f"tok{p}",)) as c:
                pid = (await c.fetchone())[0]
            for n in range(nodes_per):
                async with db.execute("SELECT id FROM servers WHERE url=?", (urls[n],)) as c:
                    sid = (await c.fetchone())[0]
                await db.execute(
                    """INSERT INTO subscription_nodes
                           (profile_id, server_id, inbound_id, uuid, email, is_active)
                       VALUES (?,?,?,?,?,1)""",
                    (pid, sid, 1, f"uuid{p}-{n}", f"sub{p}_n{n}"))
        await db.commit()
    return urls



def parser_tests():
    """The panel's wire shape, unwrapped by XUIClient — section 20.

    A panel that fronts other nodes reports several guid subtrees and the same
    client can appear under more than one, so the union and the newest-wins rule
    are load-bearing rather than defensive.
    """
    from core.xui_api import XUIClient

    print("\n20. the panel's guid-keyed reply is unwrapped correctly")
    cli = XUIClient.__new__(XUIClient)
    cli.last_error = ""

    async def fake_req(payload):
        async def _req(method, path, **kw):
            return payload
        return _req

    async def go():
        import asyncio as _a
        cases = [
            ("a single guid", {"success": True, "obj": {
                "g1": {"sub0_n0": [{"ip": "1.2.3.4", "timestamp": 111}]}}},
             {"sub0_n0": {"1.2.3.4": 111}}),
            ("two guids, same client, newest wins", {"success": True, "obj": {
                "g1": {"a": [{"ip": "1.2.3.4", "timestamp": 100}]},
                "g2": {"a": [{"ip": "1.2.3.4", "timestamp": 200}]}}},
             {"a": {"1.2.3.4": 200}}),
            ("an empty panel", {"success": True, "obj": {}}, {}),
            ("a null obj is 'nobody', not a failure", {"success": True, "obj": None}, {}),
        ]
        for label, payload, want in cases:
            cli._req = await fake_req(payload)
            check(label, await cli.get_client_ips_bulk(), want)
        # A failure must be None — "unknown" — never an empty dict, or the guard
        # would read a dead panel as "nobody is connected" and restore penalties.
        cli._req = await fake_req({"success": False, "msg": "nope"})
        check("a rejected request is unknown, not empty", await cli.get_client_ips_bulk(), None)
        cli._req = await fake_req(None)
        check("no reply at all is unknown", await cli.get_client_ips_bulk(), None)
        cli._req = await fake_req({"success": True, "obj": ["not", "a", "dict"]})
        check("a shape we do not recognise is unknown", await cli.get_client_ips_bulk(), None)

    asyncio.run(go())


def cycle_tests():
    import importlib, os, tempfile

    work = os.path.join(tempfile.gettempdir(), "ipguard-cycle-test")
    os.makedirs(work, exist_ok=True)
    for f in ("atlas.db", "atlas.db-wal", "atlas.db-shm"):
        try:
            os.remove(os.path.join(work, f))
        except OSError:
            pass
    cwd = os.getcwd()
    os.chdir(work)
    try:
        import core.database as db
        importlib.reload(db)
        import core.ip_guard as guard
        importlib.reload(guard)
        guard.XUIClient = FakePanel

        async def cycle():
            # Production cycles are a minute apart, so the shared snapshot has
            # always expired. These run microseconds apart and re-script the
            # panel between them, so the cached reading has to be dropped or the
            # second cycle would decide on the first one's data.
            guard.reset_snapshot()
            return await guard.run_cycle(None)

        async def main_async():
            urls = await _seed(work, profiles=3, nodes_per=3)
            from core.database import set_setting, get_ip_guard_events, get_ip_guard_state

            print("\n12. switched off, it does nothing at all")
            FakePanel.reset()
            r = await cycle()
            check("reports itself off", r.get("enabled"), False)
            check("and makes no requests", len(FakePanel.CALLS), 0)

            await set_setting("ip_limit_enabled", "1")
            await set_setting("ip_limit_warn_only", "0")
            await set_setting("ip_limit_default", "5")
            await set_setting("ip_limit_strikes", "2")
            await set_setting("ip_limit_grace_seconds", "30")

            print("\n13. a quiet base costs a fixed, tiny number of requests")
            FakePanel.IPS = {u: {} for u in urls}
            FakePanel.ONLINE = {u: [] for u in urls}
            FakePanel.reset()
            await cycle()
            check("one bulk read per server", FakePanel.count("bulk_ips"), len(urls))
            check("one online check per server", FakePanel.count("onlines"), len(urls))
            check("no per-client reads", FakePanel.count("per_email"), 0)
            check("and no writes", FakePanel.count("disable") + FakePanel.count("enable"), 0)
            quiet = len(FakePanel.CALLS)

            # The claim being protected: cost is per SERVER, not per subscription.
            # If this ever becomes per-node it is 3117 requests a minute.
            FakePanel.reset()
            await cycle()
            check("adding customers does not add requests", len(FakePanel.CALLS), quiet)

            print("\n14. one busy customer is confirmed before anything happens")
            now = int(time.time())
            # sub0 looks like six places on server 0 — but three of them went
            # quiet minutes ago and are only waiting to be reaped.
            FakePanel.IPS[urls[0]] = {"sub0_n0": {
                "91.99.1.1": now, "91.99.1.2": now, "91.99.1.3": now,
                "91.99.1.4": now - 400, "91.99.1.5": now - 400, "91.99.1.6": now - 400,
            }}
            FakePanel.ONLINE[urls[0]] = ["sub0_n0"]
            FakePanel.reset()
            await cycle()   # strike 1
            check("no per-client read on a non-deciding cycle", FakePanel.count("per_email"), 0)
            FakePanel.reset()
            await cycle()   # strike 2 — the deciding one
            check("now it confirms against the honest timestamps",
                  FakePanel.count("per_email") > 0, True)
            check("and only for the suspect's own nodes", FakePanel.count("per_email"), 1)
            ev = await get_ip_guard_events(10)
            check("nobody was warned — three of the six were stale", ev, [])

            print("\n15. a genuinely shared subscription is warned, then cut")
            FakePanel.IPS[urls[0]] = {"sub0_n0": {
                f"91.99.1.{i}": now for i in range(1, 8)
            }}
            FakePanel.reset()
            await cycle()
            await cycle()
            ev = await get_ip_guard_events(10)
            kinds = [e["kind"] for e in ev]
            check("the first action is a warning", kinds[:1], ["warned"])
            check("nothing was disabled yet", FakePanel.count("disable"), 0)

            # Let the grace period lapse with them still over.
            st = await get_ip_guard_state(1)
            await db.save_ip_guard_state(1, last_warned_at=int(time.time()) - 120,
                                         strikes=int(st["strikes"] or 0))
            FakePanel.reset()
            await cycle()
            await cycle()
            ev = await get_ip_guard_events(10)
            check("then it cuts", "cut" in [e["kind"] for e in ev], True)
            check("with one disable per server the customer is on",
                  FakePanel.count("disable"), 3)
            st = await get_ip_guard_state(1)
            check("the penalty is the first rung", int(st["penalty_until"]) - int(time.time()) <= 60, True)
            check("and the rung is recorded", int(st["level"]), 1)

            print("\n16. the penalty ends by itself")
            await db.save_ip_guard_state(1, penalty_until=int(time.time()) - 1)
            FakePanel.IPS[urls[0]] = {}
            FakePanel.reset()
            await cycle()
            check("it switches the customer back on", FakePanel.count("enable"), 3)
            st = await get_ip_guard_state(1)
            check("and the cut is cleared", int(st["penalty_until"]), 0)

            print("\n17. warn-only never touches a panel")
            await set_setting("ip_limit_warn_only", "1")
            await db.clear_ip_guard_state(1)
            FakePanel.IPS[urls[0]] = {"sub0_n0": {f"91.99.2.{i}": int(time.time())
                                                  for i in range(1, 9)}}
            FakePanel.reset()
            for _ in range(6):
                await cycle()
            check("no client was ever disabled", FakePanel.count("disable"), 0)
            ev = await get_ip_guard_events(20)
            check("but the evidence is recorded",
                  "would_cut" in [e["kind"] for e in ev] or "warned" in [e["kind"] for e in ev], True)

            print("\n18. a panel outage is not read as good behaviour")
            await set_setting("ip_limit_warn_only", "0")
            FakePanel.reset()
            FakePanel.FAIL_BULK = set(urls)   # reset() clears this, so arm it after
            r = await cycle()
            check("the cycle is skipped entirely", r.get("skipped"), True)
            check("and nothing is written to any panel",
                  FakePanel.count("disable") + FakePanel.count("enable"), 0)

            print("\n21. many people asking costs one reading, not one each")
            # This is the whole reason fleet_snapshot exists. A customer button
            # in the bot, the same button in the mini-app, the owner checking a
            # config, and the reseller API all want the same fact. Without
            # sharing, twenty customers tapping it is a hundred requests.
            guard.reset_snapshot()
            now = int(time.time())
            FakePanel.IPS[urls[0]] = {"sub0_n0": {"91.99.5.1": now, "91.99.5.2": now}}
            FakePanel.reset()
            first = await guard.live_connections(1, confirm=False)
            after_one = FakePanel.count("bulk_ips")
            check("the first ask reads every server once", after_one, len(urls))
            for _ in range(20):
                await guard.live_connections(1, confirm=False)
                guard._LIVE_CACHE.clear()          # force the count, not the cache
            check("twenty more asks read nothing again",
                  FakePanel.count("bulk_ips"), after_one)
            check("and the answer is the real count", first["count"], 2)

            print("\n22. what the customer is shown is their own, and masked")
            guard.reset_snapshot(); FakePanel.reset()
            masked = await guard.live_connections(1, confirm=False)
            check("addresses are masked by default",
                  all("···" in p["ip"] for p in masked["places"]), True)
            guard.forget_live(1)
            full = await guard.live_connections(1, confirm=False, reveal=True)
            check("the owner can see the real thing",
                  any(p["ip"] == "91.99.5.1" for p in full["places"]), True)
            check("both agree on the count", masked["count"], full["count"])

            print("\n23. a half-answered fleet says so instead of undercounting")
            guard.reset_snapshot(); FakePanel.reset()
            FakePanel.FAIL_BULK = {urls[1], urls[2]}
            partial = await guard.live_connections(1, confirm=False)
            check("it reports the reading as partial", partial["partial"], True)
            check("and names how many servers answered", partial["answered"], 1)
            FakePanel.FAIL_BULK = set()

            print("\n24. the customer's own allowance comes back with the count")
            guard.reset_snapshot(); guard.forget_live(1)
            await db.set_profile_ip_limit(1, 9)
            r = await guard.live_connections(1, confirm=False)
            check("the per-subscription override is used", r["limit"], 9)
            await db.set_profile_ip_limit(1, 0)
            guard.forget_live(1)
            r = await guard.live_connections(1, confirm=False)
            check("and zero falls back to the default", r["limit"], 5)

            print("\n19. turning it off releases everyone immediately")
            FakePanel.FAIL_BULK = set()
            await db.save_ip_guard_state(1, penalty_until=int(time.time()) + 3600, level=2)
            await set_setting("ip_limit_enabled", "0")
            FakePanel.reset()
            r = await cycle()
            check("the cut customer is restored", r.get("restored"), 1)
            check("with one enable per server", FakePanel.count("enable"), 3)
            check("and their ladder is forgotten", await get_ip_guard_state(1), None)

        asyncio.run(main_async())
    finally:
        os.chdir(cwd)


def main():
    print("1. addresses are grouped the way the mechanism requires")
    check("a plain v4 address is itself", group_key("5.113.20.7"), "5.113.20.7/32")
    check("two addresses in one /24 stay distinct at /32",
          group_key("5.113.20.7") == group_key("5.113.20.9"), False)
    check("...and collapse when the owner widens it",
          group_key("5.113.20.7", 24) == group_key("5.113.20.9", 24), True)
    # An IPv6 host cycles privacy addresses inside its own /64. Counting those
    # as separate places would manufacture a violation out of one phone.
    check("v6 privacy addresses in one /64 are one place",
          group_key("2a01:4f8:1c17:abcd::1") == group_key("2a01:4f8:1c17:abcd:dead:beef::9"), True)
    check("a different /64 is a different place",
          group_key("2a01:4f8:1c17:abcd::1") == group_key("2a01:4f8:1c17:abce::1"), False)
    check("host:port is accepted", group_key("5.113.20.7:443"), "5.113.20.7/32")
    check("bracketed v6 with a port is accepted",
          group_key("[2a01:4f8:1c17:abcd::1]:443"), "2a01:4f8:1c17:abcd::/64")
    # The panel itself, a health probe, or xray behind a local proxy. None of
    # these is a customer and none may eat into the allowance.
    for bad in ("127.0.0.1", "::1", "192.168.1.5", "10.0.0.9", "172.16.4.4", "", "nonsense", "999.1.1.1"):
        check(f"not counted: {bad!r}", group_key(bad), None)

    print("\n2. the count is per SUBSCRIPTION, unioned over its nodes")
    # One customer holds one link that fans out to ~12 nodes. The same phone
    # hopping between two of them must not read as two people.
    node_a = {"5.113.20.7": NOW}
    node_b = {"5.113.20.7": NOW - 5}
    n, groups = count_concurrent([node_a, node_b], NOW, 90)
    check("the same address on two nodes is one place", n, 1)
    n, _ = count_concurrent([{"5.113.20.7": NOW}, {"91.99.1.4": NOW}], NOW, 90)
    check("two addresses are two places", n, 2)
    # Freshness: the panel keeps an address for 30 minutes, which is not
    # "at the same time" by any reading.
    n, _ = count_concurrent([{"5.113.20.7": NOW, "91.99.1.4": NOW - 600}], NOW, 90)
    check("a ten-minute-old sighting is not concurrent", n, 1)
    n, _ = count_concurrent([], NOW, 90)
    check("no nodes is zero, not a crash", n, 0)

    print("\n3. a malformed ladder cannot silently disarm the feature")
    check("the documented ladder parses", parse_steps("60,600,3600"), [60, 600, 3600])
    check("junk falls back rather than emptying", parse_steps("abc"), [60, 600, 3600])
    check("empty falls back", parse_steps(""), [60, 600, 3600])
    # A zero-length step would read as "cut, then restore immediately", which
    # would spam the customer with two messages and change nothing.
    check("zero and negative steps are dropped", parse_steps("0,-5,120"), [120])
    check("a step is capped at a day", parse_steps("999999"), [86400])

    print("\n4. one reading never acts — sustained overage does")
    state = {}
    for i in range(1, LADDER["strikes_needed"]):
        d = run(state, count=8)
        check(f"reading {i} of {LADDER['strikes_needed']} does nothing", d["action"], ACT_NONE)
        check(f"...and counts a strike", d["strikes"], i)
        state = d
    d = run(state, count=8)
    check("the deciding reading warns first, as the owner asked", d["action"], ACT_WARN)
    check("nobody is cut yet", d["penalty_until"], 0)

    print("\n5. one clean reading forgives the run")
    state = {}
    for _ in range(3):
        state = run(state, count=8)
    check("three strikes stand", state["strikes"], 3)
    state = run(state, count=5)
    check("back inside the allowance clears them", state["strikes"], 0)
    check("and nothing happens", state["action"], ACT_NONE)
    # Being AT the limit is allowed. Off-by-one here would cut every customer
    # who used exactly their allowance.
    d = run({}, count=5, limit=5)
    check("exactly at the allowance is fine", d["action"], ACT_NONE)
    d = run({}, count=6, limit=5)
    check("one over starts counting", d["strikes"], 1)

    print("\n6. THE ONE THAT MATTERS — a commuter is not a sharer")
    # A phone switches from Wi-Fi to 4G. Xray keeps the abandoned address in the
    # online map until connIdle reaps it, up to 300s later, so the bulk scan
    # shows two places. But the abandoned address stops dispatching, so its real
    # lastSeen freezes while the live one advances. Counted honestly, this is
    # one place, and the customer is never even warned.
    handover_bulk = {"5.113.20.7": NOW, "91.99.1.4": NOW}       # scan re-stamps both
    n, _ = count_concurrent([handover_bulk], NOW, 90)
    check("the bulk scan cannot tell them apart", n, 2)
    # What the per-email endpoint really holds: the old address went quiet 200s
    # ago and is merely waiting to be reaped.
    handover_true = {"5.113.20.7": NOW - 3, "91.99.1.4": NOW - 200}
    n, _ = count_concurrent([handover_true], NOW, 120)
    check("the honest timestamps say one place", n, 1)
    # Three rotations in five minutes — a commuter on a train — still one place.
    commuter = {"5.113.20.7": NOW - 2, "5.113.21.9": NOW - 140,
                "5.113.44.2": NOW - 260, "91.99.1.4": NOW - 295}
    n, _ = count_concurrent([commuter], NOW, 120)
    check("a commuter rotating four addresses is one place", n, 1)
    # Real sharing looks nothing like that: every address keeps advancing.
    sharers = {f"91.99.{i}.4": NOW - (i % 3) for i in range(1, 8)}
    n, _ = count_concurrent([sharers], NOW, 120)
    check("seven people all actively using it is seven places", n, 7)

    print("\n7. the ladder is 1 minute, then 10, then an hour")
    # Warn, let the grace period pass with the customer still over, then cut.
    state = {}
    for _ in range(LADDER["strikes_needed"]):
        state = run(state, count=9)
    check("warned", state["action"], ACT_WARN)
    t = NOW + LADDER["grace_seconds"] + 1
    seen = []
    for rung in (60, 600, 3600, 3600):
        # Keep reading until it acts, rather than assuming which reading does —
        # an off-by-one here would hide a rung being skipped entirely.
        s, guard = state, 0
        while guard < 20:
            s = run(s, count=9, now=t)
            t += 60
            guard += 1
            if s["action"] == ACT_CUT:
                break
        check(f"rung {len(seen) + 1} cuts", s["action"], ACT_CUT)
        check(f"...for {rung}s", s.get("seconds"), rung)
        seen.append(s.get("seconds"))
        # serve it out, then restore
        t = int(s["penalty_until"]) + 1
        r = run(s, count=0, now=t)
        check("the penalty ends in a restore", r["action"], ACT_RESTORE)
        check("...and clears the cut", r["penalty_until"], 0)
        state = r
        t += 60
    check("the ladder does not run off the end", seen, [60, 600, 3600, 3600])

    print("\n8. while cut, we only re-cut on evidence")
    cut = {"penalty_until": NOW + 600, "level": 2, "last_violation_at": NOW,
           "cut_at": NOW - 600}
    d = run(cut, count=0)
    check("a quiet cut subscription is left alone", d["action"], ACT_NONE)
    # Established connections survive a disable until xray reaps them, so
    # addresses linger for minutes after a perfectly good cut. Re-issuing then
    # would be a wasted write per server every single cycle.
    draining = dict(cut, cut_at=NOW - 30)
    check("draining connections are not mistaken for a failed cut",
          run(draining, count=3)["action"], ACT_NONE)
    # Still connecting while cut means the disable did not take — another code
    # path re-enabled them, or the panel refused. Re-apply, but only because we
    # can SEE it, never on a timer.
    d = run(cut, count=3)
    check("still connecting means re-apply", d["action"], ACT_REASSERT)
    check("the penalty end is untouched", d["penalty_until"], NOW + 600)

    print("\n9. the ladder decays after good behaviour")
    hot = {"level": 3, "last_violation_at": NOW, "peak_ip_count": 12}
    d = run(hot, count=1, now=NOW + 86400 + 1)
    check("a clean day drops one rung", d["level"], 2)
    check("not a full amnesty", d["level"] != 0, True)
    d2 = run({"level": 1, "last_violation_at": NOW}, count=1, now=NOW + 86400 + 1)
    check("the last rung clears the ladder", d2["level"], 0)
    check("...and forgets the peak", d2["peak_ip_count"], 0)
    d3 = run(hot, count=1, now=NOW + 3600)
    check("an hour is not enough to decay", d3["level"], 3)

    print("\n10. a restart cannot strand a cut customer")
    # The penalty lives in SQLite, not in memory, so the decision after a
    # restart is taken from the stored row alone. Rebuild it from what the
    # database would hand back and confirm it restores.
    stored = {"profile_id": 7, "level": 2, "strikes": 0, "over_since": 0,
              "penalty_until": NOW - 1, "cut_at": NOW - 601,
              "last_violation_at": NOW - 601, "last_warned_at": NOW - 601,
              "last_ip_count": 9, "peak_ip_count": 11, "restore_fails": 0}
    d = run(stored, count=0)
    check("an expired penalty restores on the next cycle", d["action"], ACT_RESTORE)
    check("...and the rung is remembered for next time", d["level"], 2)

    print("\n11. the defaults are the ones the owner asked for")
    check("five simultaneous connections", DEFAULTS["ip_limit_default"], "5")
    check("1 minute, 10 minutes, 1 hour", DEFAULTS["ip_limit_steps"], "60,600,3600")
    # Both of these are safety interlocks. If either ever flips to on by
    # default, an upgrade starts cutting customers with nobody having asked.
    check("ships switched off", DEFAULTS["ip_limit_enabled"], "0")
    check("and warn-only when first switched on", DEFAULTS["ip_limit_warn_only"], "1")
    # /24 would look protective and mostly is not — Iranian carriers announce
    # their CGNAT pools as /20s, so churn crosses /24 constantly.
    check("v4 counts exact addresses", DEFAULTS["ip_limit_ipv4_bits"], "32")
    check("v6 counts /64s", DEFAULTS["ip_limit_ipv6_bits"], "64")

    cycle_tests()
    parser_tests()

    print("\n25. A CDN EDGE IS NOT A CUSTOMER — the real one that nearly fired")
    # Taken verbatim from the owner's own report. One subscription showed 76
    # "places" and was one cycle from a sharing warning. Every address on the
    # CDN-fronted server belonged to Cloudflare: a customer's connections land
    # on dozens of edge machines, so one honest phone looked like a reseller.
    #
    # Counting these does not merely inflate a number, it inverts the feature —
    # the customers punished hardest would be the ones on the server that works
    # best in Iran.
    real = ["193.39.9.214", "2.147.235.151", "2.147.58.13",
            "5.211.152.139", "158.58.61.165"]
    cf = ["162.158.182.152", "172.71.144.49", "172.71.135.38", "172.70.248.181",
          "141.101.69.92", "104.23.239.129", "104.22.123.27", "172.69.223.146",
          "162.158.95.10", "172.71.247.85", "141.101.96.74", "172.64.0.1",
          "108.162.192.5", "173.245.48.9", "103.21.244.7", "188.114.96.3"]
    for ip in cf:
        check_true(f"{ip} is recognised as a CDN edge", ipg.is_cdn_ip(ip))
    for ip in real:
        check(f"{ip} is a real customer", ipg.is_cdn_ip(ip), False)

    m = {ip: NOW for ip in real + cf}
    n, groups = ipg.count_concurrent([m], NOW, 90)
    check("only the real customers are counted", n, len(real))
    check("and no CDN address survives into the list",
          any(ipg.is_cdn_ip(g.split("/")[0]) for g in groups), False)
    check("the hidden ones are counted up for the report",
          ipg.count_cdn([m], NOW, 90), len(cf))

    # 76 places vs the 5 that are actually people.
    check("76 places becomes 5", ipg.count_concurrent(
        [{ip: NOW for ip in real + cf * 4}], NOW, 90)[0], 5)

    print("\n26. other CDNs can be added without a deploy")
    # Iranian sellers also front configs with ArvanCloud and Derak. Rather than
    # guess at their ranges, the owner pastes what their own log shows.
    check("an unknown CDN is counted by default", ipg.is_cdn_ip("185.143.232.9"), False)
    check("...and excluded once declared",
          ipg.is_cdn_ip("185.143.232.9", "185.143.232.0/22"), True)
    check("a malformed entry does not break the list",
          ipg.is_cdn_ip("2.147.235.151", "not-a-cidr, 10.0.0.0/8"), False)
    ipg._CDN_NETS.clear()

    print("\n27. the message names WHICH subscription, and links to it")
    # A representative can hold dozens of subscriptions and an ordinary customer
    # several. "Your subscription is over the limit" is unactionable to either:
    # they cannot tell which one to go and fix.
    row = {"name": "Br-Gorbah", "package_name": "نامحدود یک ماهه"}
    w = ipg.warn_text(26, 5, row)
    check_true("the warning names the subscription", "Br-Gorbah" in w)
    check_true("...and the package it was sold under", "نامحدود یک ماهه" in w)
    check_true("...and the count", "26" in w)
    check_true("...and the allowance", "5" in w)
    c = ipg.cut_text(600, 26, 5, row)
    check_true("the cut notice names it too", "Br-Gorbah" in c)
    check_true("...and says the quota is not lost", "از بین نمی‌رود" in c)
    check_true("the restore notice names it", "Br-Gorbah" in ipg.restore_text(row))
    # An older row, or one where the join found no package, must not crash or
    # emit a dangling label.
    bare = ipg.warn_text(9, 5, {"name": "", "package_name": ""})
    check_true("a nameless subscription still produces a message", len(bare) > 80)
    check("no empty label is left behind", "اشتراک: \n" in bare, False)
    check_true("no row at all is survivable", len(ipg.warn_text(9, 5)) > 80)

    kb = ipg._view_kb(566)
    check("the button opens THAT subscription",
          kb.inline_keyboard[0][0].callback_data, "sub_show:566")

    print("\n" + ("ALL PASSED" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
