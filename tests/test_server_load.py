"""«شلوغی سرورها» — what customers see, and the limits that keep it cheap.

Plain `python tests/test_server_load.py` — no test framework, because the project
has none and these need to stay runnable on the server.

What is being protected here:
  * a tap must never reach a VPN panel — the screen reads stored counts through
    one shared snapshot, so N viewers inside the TTL cost ONE rebuild (§6);
  * customers see percentages only, never how many people are online (§2);
  * an unreadable server is "unknown", never 0% — 0% would read as "empty, go
    here" and send everyone to the one server we know nothing about (§1);
  * a customer can look several times a day but cannot hammer it (§3), and a
    group together cannot spend the bot's send budget (§4);
  * with the feature off, the customer home menu is exactly what it was (§5).
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.autonode as an  # noqa: E402
import bot.handlers.server_load as sl  # noqa: E402

NOW = int(time.time() * 1000)
SETTINGS = {"server_load_capacity": "100", "server_load_public": "0",
            "server_load_cooldown": "30", "server_load_daily": "3"}


async def _fake_get_setting(key, default=None):
    return SETTINGS.get(key, default)


SERVERS = [
    # 8.0 online now, smoothed 9.28 -> 9%
    {"id": 1, "name": "سرور ترکیه ۱ ", "is_active": 1, "online": 8, "online_avg": 9.28,
     "checked_at": NOW, "load_weight": 1.0},
    # panel did not answer: `online` is None -> unknown, even though avg is set
    {"id": 2, "name": "سرور هلند ۱", "is_active": 1, "online": None, "online_avg": 30.0,
     "checked_at": NOW - 2_000_000, "load_weight": 1.0},
    # over capacity -> clamped to 100
    {"id": 4, "name": "سرور آلمان ۲", "is_active": 1, "online": 150, "online_avg": 150.0,
     "checked_at": NOW, "load_weight": 1.0},
    # double weight doubles capacity: 40 / 200 -> 20%
    {"id": 5, "name": "فنلاند", "is_active": 1, "online": 40, "online_avg": 40.0,
     "checked_at": NOW, "load_weight": 2.0},
    {"id": 6, "name": "سرور آمریکا", "is_active": 0, "online": 10, "online_avg": 10.0,
     "checked_at": NOW, "load_weight": 1.0},   # inactive -> hidden
    {"id": 7, "name": "سرور بدون نود", "is_active": 1, "online": 5, "online_avg": 5.0,
     "checked_at": NOW, "load_weight": 1.0},   # no node config -> hidden
    {"id": 8, "name": "سرور فقط اتو", "is_active": 1, "online": 5, "online_avg": 5.0,
     "checked_at": NOW, "load_weight": 1.0},   # only an auto node -> hidden
]
NODES = [
    {"server_id": 1, "label": "🇹🇷 Turkey s1 - NEW", "is_auto": 0},
    {"server_id": 2, "label": "🇳🇱 Netherland WS 🛡️", "is_auto": 0},
    {"server_id": 4, "label": "🇩🇪 Germany New 🗽", "is_auto": 0},
    {"server_id": 5, "label": "Finland without a flag", "is_auto": 0},
    {"server_id": 6, "label": "🇺🇸 USA", "is_auto": 0},
    {"server_id": 8, "label": "auto", "is_auto": 1},
]


async def _fake_snapshot():
    return [dict(s) for s in SERVERS]


async def _fake_nodes(active_only=True):
    return [dict(n) for n in NODES]


sl.get_setting = _fake_get_setting
sl.get_subscription_node_configs = _fake_nodes
an.server_load_snapshot = _fake_snapshot


def section(n, title):
    print(f"§{n} {title}")


async def main():
    # ── §1 which servers, which numbers ─────────────────────────────────────
    section(1, "build: filtering, flags, names, percentages, unknown stays unknown")
    data = await sl._build()
    rows = data["rows"]
    names = [r["name"] for r in rows]
    assert names == ["ترکیه ۱", "فنلاند", "آلمان ۲", "هلند ۱"], names
    by = {r["name"]: r for r in rows}
    assert by["ترکیه ۱"]["pct"] == 9 and by["ترکیه ۱"]["flag"] == "🇹🇷"
    assert by["فنلاند"]["pct"] == 20 and by["فنلاند"]["cap"] == 200 and by["فنلاند"]["flag"] == ""
    assert by["آلمان ۲"]["pct"] == 100, "over capacity must clamp to 100"
    assert by["هلند ۱"]["pct"] is None, "a silent panel is unknown, never 0%"
    assert rows[-1]["pct"] is None, "unknown sorts last, never above a real reading"
    assert data["public"] is False and data["cooldown"] == 30 and data["daily"] == 3

    # ── §2 customers see percentages only ───────────────────────────────────
    section(2, "render: no online counts for customers, counts for admins")
    customer = sl._render(data, admin=False)
    admin = sl._render(data, admin=True)
    assert "۹٪" in customer and "۱۰۰٪" in customer and "نامشخص" in customer
    assert "۱۵۰" not in customer, "a customer must never see how many are online"
    assert "از" not in customer.split("به‌روزرسانی")[0], "no 'N از M' for customers"
    assert "(۱۵۰ از ۱۰۰)" in admin and "خاموش" in admin
    kb_customer = [b.callback_data for row in sl._kb(data, False).inline_keyboard for b in row]
    kb_admin = [b.callback_data for row in sl._kb(data, True).inline_keyboard for b in row]
    assert "sload:pub" not in kb_customer and not any(c.startswith("sload:cap") for c in kb_customer)
    assert "sload:pub" in kb_admin and "sload:cap:10" in kb_admin

    # ── §3 per-customer limits ──────────────────────────────────────────────
    section(3, "per user: cooldown between views and a daily cap")
    clock = [1000.0]
    real_monotonic = time.monotonic
    time.monotonic = lambda: clock[0]
    try:
        sl._USERS.clear()
        assert sl._user_block(7, 30, 3) is None
        sl._user_commit(7)
        clock[0] = 1010.0
        block = sl._user_block(7, 30, 3)
        assert block and block.startswith("wait:") and int(block.split(":")[1]) == 21, block
        assert sl._user_block(8, 30, 3) is None, "one customer's limit never touches another"
        clock[0] = 1031.0
        assert sl._user_block(7, 30, 3) is None
        sl._user_commit(7)
        clock[0] = 1062.0
        sl._user_commit(7)
        clock[0] = 1500.0
        assert sl._user_block(7, 30, 3) == "daily", "the 4th view of the day is refused"

        # ── §4 everyone together ────────────────────────────────────────────
        section(4, "global bucket: a burst drains it, time refills it")
        sl._BUCKET.update(tokens=sl.GLOBAL_BURST, ts=clock[0])
        taken = sum(1 for _ in range(int(sl.GLOBAL_BURST)) if sl._take_global())
        assert taken == int(sl.GLOBAL_BURST)
        assert sl._take_global() is False, "past the burst, renders are refused"
        clock[0] += 1.0
        refilled = sum(1 for _ in range(50) if sl._take_global())
        assert refilled == int(sl.GLOBAL_RATE), refilled
    finally:
        time.monotonic = real_monotonic

    # ── §5 the customer home menu ───────────────────────────────────────────
    section(5, "home menu: unchanged while off, beside «سرویس‌های من» when on")
    from bot import home
    home.set_load_public(False)
    off = home.home_kb().inline_keyboard
    off_data = [b.callback_data for row in off for b in row]
    assert "home:load" not in off_data and len(off_data) == 9
    assert [len(r) for r in off] == [1, 1, 2, 2, 2, 1], "layout must not move while off"
    home.set_load_public(True)
    on = home.home_kb().inline_keyboard
    assert [b.callback_data for b in on[2]] == ["home:status", "home:load"]
    assert [len(r) for r in on] == [1, 1, 2, 2, 2, 2]
    home.set_load_public(False)

    # ── §6 a crowd costs one rebuild ────────────────────────────────────────
    section(6, "snapshot: many viewers inside the TTL share one rebuild")
    calls = [0]

    async def _counting_build():
        calls[0] += 1
        return {"rows": [], "checked_at": 0, "capacity": 100,
                "cooldown": 30, "daily": 40, "public": True}

    real_build = sl._build
    sl._build = _counting_build
    try:
        sl._SNAP.update(at=0.0, data=None)
        await asyncio.gather(*(sl.snapshot() for _ in range(200)))
        assert calls[0] == 1, f"200 viewers rebuilt {calls[0]} times"
        sl.invalidate()
        await sl.snapshot()
        assert calls[0] == 2, "an admin change must force the next rebuild"
    finally:
        sl._build = real_build

    print("ALL OK")


asyncio.run(main())
