"""Android install analytics and push delivery.

Plain `python tests/test_app_analytics.py` — no test framework, matching
test_autonode.py, so these stay runnable on the server itself.

What is being protected here, in order of how badly it would hurt:

1. **The endpoint is unauthenticated and its URL ships inside every APK.** A
   malformed install id must never reach SQLite, a crafted payload must never
   choose a column name, and a non-https link must never become a tap target
   inside the app.
2. **A message must be delivered exactly once.** Redelivering on every
   heartbeat would turn one announcement into a notification every half hour,
   which is the fastest way to make someone uninstall a VPN.
3. **A partial ping must not erase what the app already told us.** A heartbeat
   that only acknowledges a delivered message carries no device facts; writing
   those columns anyway dropped the install into the "unknown" bucket of every
   breakdown and out of every version-targeted push. That failure is silent —
   the row still exists and still counts as active — so it is covered
   explicitly below.
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB = os.path.join(tempfile.mkdtemp(), "test.db")

import core.config as config
config.DB_PATH = DB

import core.app_analytics as an
an.DB_PATH = DB

import aiosqlite

FAILED = []


def check(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + f"{label}: got {got!r}, want {want!r}")
    if not ok:
        FAILED.append(label)


async def main():
    async with aiosqlite.connect(DB) as db:
        await an.ensure_schema(db)
        await db.commit()

    print("schema created")

    A = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
    B = "9c858901-8a57-4791-81fe-4c455b099bc9"

    print("\n1. rejects a malformed install id")
    check("bad id returns None", await an.record_ping({"installId": "not-a-uuid"}), None)
    check("missing id returns None", await an.record_ping({}), None)

    print("\n2. first ping registers the install")
    r = await an.record_ping({
        "installId": A, "versionCode": 1, "versionName": "0.1.0",
        "sdk": 33, "release": "13", "manufacturer": "Xiaomi",
        "model": "22081212UG", "abi": "arm64-v8a", "lang": "fa",
    })
    check("no messages yet", r["messages"], [])
    s = await an.stats()
    check("total installs", s["totals"]["total"], 1)
    check("active today", s["totals"]["active_1d"], 1)
    check("new today", s["totals"]["new_1d"], 1)

    print("\n3. second install, older Android")
    await an.record_ping({
        "installId": B, "versionCode": 1, "versionName": "0.1.0",
        "sdk": 24, "release": "7.0", "manufacturer": "Samsung",
        "model": "SM-J250F", "abi": "armeabi-v7a", "lang": "fa",
    })
    s = await an.stats()
    check("total installs", s["totals"]["total"], 2)
    check("two android buckets", len(s["androids"]), 2)
    check("two brands", len(s["brands"]), 2)

    print("\n4. re-ping does not create a duplicate")
    await an.record_ping({"installId": A, "versionCode": 2, "versionName": "0.2.0", "sdk": 33})
    s = await an.stats()
    check("still two installs", s["totals"]["total"], 2)
    check("version moved with the device",
          sorted(v["key"] for v in s["versions"]), ["0.1.0 (1)", "0.2.0 (2)"])

    print("\n5. push targeting")
    everyone = await an.create_push({"title": "Hello", "body": "all", "url": "https://t.me/x"})
    modern = await an.create_push({"title": "Modern", "body": "sdk 26+", "minSdk": 26})
    check("title is required", await an.create_push({"title": "  "}), None)

    r = await an.record_ping({"installId": A, "versionCode": 2, "sdk": 33})
    check("A gets both", sorted(m["id"] for m in r["messages"]),
          sorted([everyone["id"], modern["id"]]))

    r = await an.record_ping({"installId": B, "versionCode": 1, "sdk": 24})
    check("B is excluded from the sdk-gated one",
          [m["id"] for m in r["messages"]], [everyone["id"]])

    print("\n6. non-https link is dropped, not stored")
    evil = await an.create_push({"title": "Evil", "url": "javascript:alert(1)"})
    msgs = {m["id"]: m for m in (await an.record_ping({"installId": A, "sdk": 33}))["messages"]}
    check("url blanked", msgs[evil["id"]]["url"], "")

    print("\n7. delivery receipts stop redelivery")
    ids = [m["id"] for m in (await an.record_ping({"installId": A, "sdk": 33}))["messages"]]
    await an.record_ping({"installId": A, "sdk": 33, "delivered": ids})
    r = await an.record_ping({"installId": A, "sdk": 33})
    check("nothing pending after ack", r["messages"], [])

    print("\n8. open receipts are counted")
    await an.record_ping({"installId": A, "sdk": 33, "opened": [everyone["id"]]})
    rows = {p["id"]: p for p in await an.list_push()}
    check("delivered counted", rows[everyone["id"]]["delivered"], 1)
    check("opened counted", rows[everyone["id"]]["opened"], 1)

    print("\n9. an open implies delivery even without a delivered ack")
    await an.record_ping({"installId": B, "sdk": 24, "opened": [everyone["id"]]})
    rows = {p["id"]: p for p in await an.list_push()}
    check("delivered now 2", rows[everyone["id"]]["delivered"], 2)

    print("\n10. audience preview honours filters")
    check("everyone active", await an.audience({}), 2)
    check("sdk 26+ only", await an.audience({"minSdk": 26}), 1)
    check("versionCode >= 2 only", await an.audience({"minVersionCode": 2}), 1)

    print("\n11. deactivate and delete")
    await an.set_push_active(everyone["id"], False)
    r = await an.record_ping({"installId": B, "sdk": 24})
    check("inactive not served", [m["id"] for m in r["messages"]], [evil["id"]])
    await an.delete_push(evil["id"])
    check("deleted is gone", [p["id"] for p in await an.list_push() if p["id"] == evil["id"]], [])

    print("\n12. a ping carrying no device facts must not erase them")
    await an.record_ping({"installId": A, "delivered": []})
    s = await an.stats()
    check("version survived a bare ping",
          sorted(v["key"] for v in s["versions"]), ["0.1.0 (1)", "0.2.0 (2)"])
    check("brand survived a bare ping",
          sorted(b["key"] for b in s["brands"]), ["Samsung", "Xiaomi"])
    check("still reachable by version filter", await an.audience({"minVersionCode": 2}), 1)

    print("\n13. receipt acks for unknown ids are harmless")
    await an.record_ping({"installId": A, "sdk": 33, "delivered": [999999], "opened": ["x"]})
    check("still alive", (await an.stats())["totals"]["total"], 2)

    print("\n14. daily series is zero-filled to 30 points")
    s = await an.stats()
    check("30 days", len(s["daily"]), 30)
    check("today has both installs", s["daily"][-1]["count"], 2)

    print("\n" + ("ALL PASSED" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}"))
    return 1 if FAILED else 0


sys.exit(asyncio.run(main()))
