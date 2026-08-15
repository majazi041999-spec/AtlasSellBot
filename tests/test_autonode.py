"""Auto-node routing safety rules.

Plain `python tests/test_autonode.py` — no test framework, because the project
has none and these need to stay runnable on the server.

What is being protected here: a rebalance relocates a PAYING customer. The move
deletes their client from the old panel, so every copy of the subscription
already cached in their app points at a server that no longer knows them, and
that entry stops responding until they refresh it by hand. So a move must only
ever happen on evidence we can actually see. Reading a server's load as
"unknown" is not such evidence — the onlines endpoint moved between 3x-ui
versions and the probe is best-effort, so a silent panel usually means an old
panel, not a dead server. Treating unknown as a reason to move once drained
whole servers of customers and was reported as "the configs stop pinging and
only one server still connects".
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.autonode as an  # noqa: E402

SETTINGS = {
    "autonode_margin": "0.25",
    "autonode_min_delta": "3",
    "autonode_cooldown_minutes": "60",
}


async def _fake_get_setting(key, default=None):
    return SETTINGS.get(key, default)


an.get_setting = _fake_get_setting

NOW = int(time.time() * 1000)
AUTO = {"id": 99, "is_auto": 1, "label": "auto", "connect_host": ""}


def _server(sid, online=None):
    """`online=None` models a panel that did not answer the onlines probe."""
    if online is None:
        return {"id": sid, "online_ok": 0, "online_checked_at": NOW,
                "online_count": 0, "online_avg": 0, "load_weight": 1}
    return {"id": sid, "online_ok": 1, "online_checked_at": NOW,
            "online_count": online, "online_avg": online, "load_weight": 1}


def _candidate(cid, sid):
    return {"id": cid, "server_id": sid, "inbound_id": 1, "priority": 100,
            "label": f"srv{sid}", "server_name": f"srv{sid}"}


async def _decide(servers, assignments, on_server, moved_ago_min=999):
    """Which server the auto node picks for a sub currently on `on_server`."""
    view = an.LoadView(servers, assignments, 900_000, NOW)
    target = await an.resolve_auto_target(
        AUTO,
        existing={"server_id": on_server, "inbound_id": 1,
                  "moved_at": NOW - moved_ago_min * 60_000},
        view=view,
        candidates=[_candidate(i + 1, s["id"]) for i, s in enumerate(servers)],
        allow_move=True,
    )
    return int(target["server_id"])


async def main() -> int:
    failures = []

    async def case(name, servers, assignments, on_server, expected, **kw):
        got = await _decide(servers, assignments, on_server, **kw)
        ok = got == expected
        if not ok:
            failures.append(name)
        print(f"  [{'ok  ' if ok else 'FAIL'}] {name} → srv{got} (expected srv{expected})")

    print("unknown load never causes a move:")
    await case("silent current panel does not evacuate its customers",
               [_server(1, None), _server(2, 2)], {1: 40, 2: 5}, 1, 1)
    await case("silent destination panel does not attract customers",
               [_server(1, 40), _server(2, None)], {1: 40, 2: 0}, 1, 1)
    await case("whole fleet silent moves nobody",
               [_server(1, None), _server(2, None)], {1: 40, 2: 1}, 1, 1)

    print("real, visible imbalance still balances:")
    await case("40 online vs 2 online relocates",
               [_server(1, 40), _server(2, 2)], {1: 40, 2: 2}, 1, 2)
    await case("9 vs 8 is noise, not imbalance",
               [_server(1, 9), _server(2, 8)], {1: 9, 2: 8}, 1, 1)
    await case("cooldown outranks a real imbalance",
               [_server(1, 40), _server(2, 2)], {1: 40, 2: 2}, 1, 1, moved_ago_min=5)

    print()
    if failures:
        print("FAILED: " + ", ".join(failures))
        return 1
    print("all auto-node routing rules hold")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
