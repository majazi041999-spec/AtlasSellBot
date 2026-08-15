"""Diagnostic event ingest, rollups and export.

Plain `python tests/test_app_diag.py` — no test framework, matching the other
tests here, so these stay runnable on the server itself.

What is being protected, in order of how badly it would hurt:

1. **This endpoint is unauthenticated and its URL ships inside every APK.** A
   crafted upload must not be able to invent event categories that then pollute
   every breakdown, exceed the batch cap, or write a field the schema did not
   plan for.
2. **The rollups have to answer the question they claim to answer.** The whole
   point of the feature is "which server, on which carrier, is failing" — if the
   grouping is wrong the owner draws the wrong conclusion and moves the wrong
   server, so the arithmetic is checked against hand-counted fixtures.
3. **Retention has to actually delete.** A diagnostics table that never prunes
   is one that eventually gets copied somewhere it should not be.
"""
import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB = os.path.join(tempfile.mkdtemp(), "diag.db")

import core.config as config
config.DB_PATH = DB

import core.app_analytics as an
an.DB_PATH = DB

import aiosqlite

FAILED = []
A = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
B = "9c858901-8a57-4791-81fe-4c455b099bc9"


def check(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + f"{label}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(label)


def batch(install, carrier, events, **extra):
    payload = {
        "installId": install,
        "versionCode": 1,
        "sdk": 33,
        "model": "Xiaomi 22081212UG",
        "carrier": carrier,
        "events": events,
    }
    payload.update(extra)
    return payload


def ev(kind, **fields):
    out = {"kind": kind, "at": int(time.time())}
    out.update(fields)
    return out


async def main():
    async with aiosqlite.connect(DB) as db:
        await an.ensure_schema(db)
        await db.commit()
    print("schema created")

    print("\n1. rejects what it should reject")
    check("bad install id", await an.record_diag(batch("nope", "MCI", [ev("probe")])), None)
    check("no events", await an.record_diag(batch(A, "MCI", [])), 0)
    check("non-dict event", await an.record_diag(batch(A, "MCI", ["oops"])), 0)
    check("unknown kind dropped",
          await an.record_diag(batch(A, "MCI", [ev("exfiltrate", server="x")])), 0)

    print("\n2. a batch is stored")
    stored = await an.record_diag(batch(A, "MCI", [
        ev("probe", server="Germany WS", transport="ws+tls", ok=True, ms=120),
        ev("probe", server="Finland s1", transport="tcp+none", ok=False,
           why="context deadline exceeded"),
        ev("connected", server="Germany WS", transport="ws+tls",
           preset="iran_default", ok=True, dur=2400, ms=120),
    ]))
    check("three events stored", stored, 3)

    print("\n3. a second device, a second carrier")
    await an.record_diag(batch(B, "Irancell", [
        ev("probe", server="Germany WS", transport="ws+tls", ok=False, why="i/o timeout"),
        ev("probe", server="Finland s1", transport="tcp+none", ok=True, ms=310),
        ev("failed", server="Germany WS", preset="gaming", stage="connect",
           why="i/o timeout", ok=False),
        ev("session", server="Finland s1", transport="tcp+none", preset="gaming",
           dur=600000, down=1500000, up=90000, bytes=45000000),
    ]))

    s = await an.diag_summary(7)
    check("event count", s["events"], 7)
    check("distinct devices", s["devices"], 2)

    print("\n4. the per-server rollup answers 'which server is failing'")
    servers = {r["key"]: r for r in s["servers"]}
    check("Germany reachable", servers["Germany WS"]["reachable"], 1)
    check("Germany unreachable", servers["Germany WS"]["unreachable"], 1)
    check("Germany connects", servers["Germany WS"]["connects"], 1)
    check("Germany failures", servers["Germany WS"]["failures"], 1)
    check("Germany avg ping (only successful probes)", servers["Germany WS"]["avg_ms"], 120)
    check("Finland avg ping", servers["Finland s1"]["avg_ms"], 310)

    print("\n5. the per-carrier rollup separates the networks")
    carriers = {r["key"]: r for r in s["carriers"]}
    check("MCI installs", carriers["MCI"]["installs"], 1)
    check("MCI reachable", carriers["MCI"]["reachable"], 1)
    check("Irancell unreachable", carriers["Irancell"]["unreachable"], 1)
    check("Irancell avg ping", carriers["Irancell"]["avg_ms"], 310)

    print("\n6. presets are comparable")
    presets = {r["key"]: r for r in s["presets"]}
    check("iran_default connects", presets["iran_default"]["connects"], 1)
    check("iran_default avg connect ms", presets["iran_default"]["avg_connect_ms"], 2400)
    check("gaming failures", presets["gaming"]["failures"], 1)
    check("gaming avg peak down", presets["gaming"]["avg_peak_down"], 1500000)

    print("\n7. failure reasons are grouped")
    reasons = {r["key"]: r["count"] for r in s["reasons"]}
    check("timeout seen twice", reasons.get("i/o timeout"), 2)
    check("deadline seen once", reasons.get("context deadline exceeded"), 1)

    print("\n8. transports are comparable")
    transports = {r["key"]: r for r in s["transports"]}
    check("ws+tls reachable", transports["ws+tls"]["reachable"], 1)
    check("ws+tls unreachable", transports["ws+tls"]["unreachable"], 1)

    print("\n9. the batch cap holds")
    huge = [ev("probe", server="S", ok=True, ms=1) for _ in range(an.MAX_EVENTS_PER_BATCH + 50)]
    check("capped", await an.record_diag(batch(A, "MCI", huge)), an.MAX_EVENTS_PER_BATCH)

    print("\n10. export returns rows and is bounded")
    rows = await an.diag_export(7)
    check("export non-empty", len(rows) > 0, True)
    check("export has the columns the CSV names",
          all(k in rows[0] for k in ("at", "kind", "server", "carrier", "why")), True)
    check("export respects its limit", len(await an.diag_export(7, limit=5)), 5)

    print("\n11. retention deletes old rows on the next write")
    async with aiosqlite.connect(DB) as db:
        old = int(time.time()) - (an.DIAG_RETENTION_DAYS + 5) * an.DAY
        await db.execute(
            "INSERT INTO app_diag (install_id, at, received, kind) VALUES (?,?,?,?)",
            (A, old, old, "probe"),
        )
        await db.commit()
        cur = await db.execute("SELECT COUNT(*) FROM app_diag WHERE received = ?", (old,))
        check("stale row present before", (await cur.fetchone())[0], 1)

    await an.record_diag(batch(A, "MCI", [ev("probe", server="S", ok=True, ms=1)]))
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT COUNT(*) FROM app_diag WHERE received = ?", (old,))
        check("stale row pruned after", (await cur.fetchone())[0], 0)

    print("\n12. purge empties the table")
    await an.diag_purge()
    check("nothing left", len(await an.diag_export(30)), 0)

    print("\n" + ("ALL PASSED" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}"))
    return 1 if FAILED else 0


sys.exit(asyncio.run(main()))
