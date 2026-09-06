"""The pre-expiry ladder — that it escalates, and that it stays quiet.

Plain `python tests/test_renewal_nudges.py`.

What is being protected: these messages go to paying customers unprompted, and
both ways of getting it wrong are invisible from the code. Sending a rung twice
turns a reminder into nagging; describing a quota problem in the language of a
calendar problem ("your service ends tomorrow" to somebody with three weeks
left) is how a customer learns to ignore the whole channel.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("BOT_TOKEN", "")

from core import renewal_nudges as n  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAILED = []


def check(label, got, want):
    ok = got == want
    print(("  PASS  " if ok else "  FAIL  ") + label + f"   got={got!r} want={want!r}")
    if not ok:
        FAILED.append(label)


print("\nrungs by days remaining (plenty of quota left)")
for days, want in [(30, 0), (8, 0), (7, 1), (4, 1), (3, 2), (2, 2), (1, 3), (0, 4)]:
    check(f"{days} days left", n.stage_for(days, 10.0)[0], want)

print("\nrungs by quota used (plenty of days left)")
for pct, want in [(10, 0), (74, 0), (75, 1), (87, 1), (88, 2), (94, 2), (95, 3), (99, 4)]:
    check(f"{pct}% used", n.stage_for(30, float(pct))[0], want)

print("\nit describes whichever one is actually biting")
check("out of days, quota fine", n.stage_for(0, 20.0)[1], "time")
check("out of quota, weeks left", n.stage_for(30, 99.5)[1], "quota")
check("no expiry set, quota driven", n.stage_for(None, 96.0)[1], "quota")
check("unlimited traffic, time driven", n.stage_for(2, None)[1], "time")

print("\nevery rung has both wordings, and they differ")
for stage in range(1, n.MAX_STAGE + 1):
    t, q = n.message_for(stage, "time"), n.message_for(stage, "quota")
    check(f"stage {stage} has both", bool(t) and bool(q), True)
    check(f"stage {stage} wordings differ", t != q, True)

print("\nno two rungs reuse the same text")
seen = [n.message_for(s, r) for s in range(1, n.MAX_STAGE + 1) for r in ("time", "quota")]
check("all texts unique", len(set(seen)), len(seen))

print("\nit never returns something unsendable")
check("unknown reason falls back", bool(n.message_for(2, "weather")), True)
check("stage 0 falls back", bool(n.message_for(0, "time")), True)

print("\nthe ladder only ever climbs")
prev = 0
ok = True
for days in range(10, -1, -1):
    s = n.stage_for(days, 0.0)[0]
    if s < prev:
        ok = False
    prev = s
check("monotonic as the days run down", ok, True)

print("\n" + ("ALL PASSED" if not FAILED else f"FAILED: {FAILED}"))
sys.exit(1 if FAILED else 0)
