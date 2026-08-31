"""Admin login hardening — the invariants a screenshot cannot show.

Plain `python tests/test_login_guard.py` — no test framework, because the
project has none and this needs to stay runnable on the server.

What is being protected here. Before this, `POST /{S}/api/login` had no rate
limit, no lockout, no logging, and compared both credentials with `==`. The
defence added on top is layered, and every layer has a way of being silently
useless that no amount of clicking around would reveal:

  * **A challenge that can be replayed** turns one solved proof-of-work into
    unlimited password guesses. The single-use rule is the whole point.
  * **A wrong captcha that is not counted as a failure** lets an attacker
    grind the 1.4M-entry answer space for free while the failure counter
    sleeps.
  * **A lockout that a fresh challenge resets** is not a lockout.
  * **A cookie that logout cannot clear** (path/attribute mismatch) leaves the
    session alive while the UI says you signed out.
  * **A token that survives a password change** means an attacker who already
    has one keeps it after you react to them.

Each of those is asserted below against the real app.
"""
import asyncio
import hashlib
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_WORKDIR = tempfile.mkdtemp(prefix="atlas-login-")
os.chdir(_WORKDIR)
os.environ["WEB_SECRET_PATH"] = "TestPanel"
os.environ["WEB_ADMIN_USERNAME"] = "atlas_admin"
os.environ["WEB_ADMIN_PASSWORD"] = "s3cret-for-tests"
os.environ["JWT_SECRET"] = "a-real-secret-long-enough-for-the-guard-to-accept"
os.environ.setdefault("BOT_TOKEN", "")

from fastapi.testclient import TestClient  # noqa: E402

from core import captcha as captcha_mod  # noqa: E402
from core import login_guard as lg  # noqa: E402
from web.app import app  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

S = "TestPanel"
USER, PASS = "atlas_admin", "s3cret-for-tests"
FAILED = []


def check(label, got, want):
    ok = got == want
    print(f"   {'✓' if ok else '✗'} {label}: {got!r}" + ("" if ok else f"  (expected {want!r})"))
    if not ok:
        FAILED.append(label)


def check_true(label, got):
    check(label, bool(got), True)


def solve(prefix, bits):
    """The same proof-of-work the browser does, in Python."""
    n = 0
    while True:
        d = hashlib.sha256(f"{prefix}:{n}".encode()).digest()
        seen = 0
        for b in d:
            if b == 0:
                seen += 8
                continue
            x = b
            while x < 128:
                x <<= 1
                seen += 1
            break
        if seen >= bits:
            return str(n)
        n += 1


def main():
    client = TestClient(app)
    with client:
        def challenge():
            return client.get(f"/{S}/api/login/challenge").json()

        def login(user=USER, pw=PASS, *, chal=None, nonce=None, captcha="",
                  honeypot="", wait=True, cid=None):
            c = chal if chal is not None else challenge()
            if wait:
                time.sleep(lg.MIN_FILL_MS / 1000 + 0.05)
            body = {
                "username": user, "password": pw,
                "challenge_id": cid if cid is not None else c.get("id"),
                "pow_nonce": nonce if nonce is not None else solve(c["pow"]["prefix"], c["pow"]["bits"]),
                "captcha": captcha, "website": honeypot,
            }
            return client.post(f"/{S}/api/login", json=body)

        print("1. the happy path is invisible — no captcha, no puzzle")
        lg.reset_all()
        c = challenge()
        check_true("a challenge is issued", bool(c.get("id")))
        check("no captcha on a clean IP", c.get("captcha"), None)
        check("proof-of-work is always required", c["pow"]["bits"], lg.POW_BITS)
        r = login(chal=c)
        check("correct credentials → 200", r.status_code, 200)
        check_true("session cookie set", "_atlas_t" in r.cookies or "_atlas_t" in client.cookies)
        check("authenticated", client.get(f"/{S}/api/me").status_code, 200)

        print("\n2. logout actually clears the session")
        client.post(f"/{S}/api/logout")
        check("no longer authenticated", client.get(f"/{S}/api/me").status_code, 401)

        print("\n3. you cannot POST the login cold")
        lg.reset_all()
        r = client.post(f"/{S}/api/login", json={"username": USER, "password": PASS})
        check("no challenge → rejected", r.status_code, 400)
        check("…challenge_missing", r.json()["error"], "challenge_missing")
        check("not authenticated", client.get(f"/{S}/api/me").status_code, 401)

        print("\n4. a solved challenge is single-use — no replay")
        lg.reset_all()
        c = challenge()
        nonce = solve(c["pow"]["prefix"], c["pow"]["bits"])
        r1 = login(pw="wrong", chal=c, nonce=nonce)
        check("first use is consumed (wrong password)", r1.status_code, 401)
        r2 = login(chal=c, nonce=nonce)          # same id + nonce, right password
        check("replay of the SAME challenge is refused", r2.status_code, 400)
        check("…challenge_missing", r2.json()["error"], "challenge_missing")
        check("replay did not authenticate", client.get(f"/{S}/api/me").status_code, 401)

        print("\n5. proof-of-work must actually be done")
        lg.reset_all()
        r = login(nonce="0")
        check("a bogus nonce is rejected", r.json()["error"], "pow_failed")
        check("…as a 400", r.status_code, 400)

        print("\n6. the honeypot")
        lg.reset_all()
        r = login(honeypot="http://spam.example")
        check("a filled hidden field is rejected", r.json()["error"], "honeypot")
        check("even with the RIGHT password", r.status_code, 400)

        print("\n7. instant submission is rejected")
        lg.reset_all()
        r = login(wait=False)
        check("submitted with no dwell time", r.json()["error"], "too_fast")

        print("\n8. the captcha escalates, and only after real failures")
        lg.reset_all()
        seen = []
        for i in range(lg.CAPTCHA_AFTER):
            c = challenge()
            seen.append(c.get("captcha") is not None)
            login(pw=f"wrong{i}", chal=c)
        check(f"no captcha for the first {lg.CAPTCHA_AFTER} attempts", seen, [False] * lg.CAPTCHA_AFTER)
        c = challenge()
        check_true(f"captcha appears after {lg.CAPTCHA_AFTER} failures", c.get("captcha") is not None)
        check_true("it is a PNG data-URI", c["captcha"]["image"].startswith("data:image/png;base64,"))
        check("of the advertised length", c["captcha"]["length"], captcha_mod.LENGTH)

        print("\n9. a wrong captcha COUNTS as a failed attempt")
        # Otherwise the answer space can be ground down for free.
        before = lg._state("testclient", time.time())[0]
        login(pw="wrong", captcha="ZZZZZ")
        after = lg._state("testclient", time.time())[0]
        check("failure counter advanced", after > before, True)

        print("\n10. the right password is still refused without the captcha")
        lg.reset_all()
        for i in range(lg.CAPTCHA_AFTER):
            login(pw=f"wrong{i}")
        r = login(captcha="")            # correct credentials, no captcha answer
        check("blocked at the captcha gate", r.json()["error"], "captcha_wrong")
        check("did not authenticate", client.get(f"/{S}/api/me").status_code, 401)

        print("\n11. lockout, and a fresh challenge does not reset it")
        lg.reset_all()
        locked_at = None
        for i in range(lg.LOCK_AFTER + 2):
            r = login(pw=f"wrong{i}", captcha="ZZZZZ")
            if r.status_code == 429:
                locked_at = i
                break
        check_true(f"locked out within {lg.LOCK_AFTER + 2} attempts", locked_at is not None)
        check_true("lockout reports a wait", lg.lock_remaining("testclient") > 0)
        c = challenge()
        check_true("a new challenge still reports the lock", c["locked_for"] > 0)
        r = login(chal=c)                 # CORRECT credentials while locked
        check("correct password is refused while locked", r.status_code, 429)
        check("…with error 'locked'", r.json()["error"], "locked")
        check("still not authenticated", client.get(f"/{S}/api/me").status_code, 401)

        print("\n12. a successful login clears the IP's record")
        lg.reset_all()
        login(pw="wrong")
        check_true("a failure was recorded", lg._state("testclient", time.time())[0] > 0)
        login()
        check("counter reset on success", lg._state("testclient", time.time())[0], 0)
        client.post(f"/{S}/api/logout")

        print("\n13. a session does not survive a credential change")
        lg.reset_all()
        login()
        check("signed in", client.get(f"/{S}/api/me").status_code, 200)
        import web.app as wa
        original = wa._CRED_VERSION
        wa._CRED_VERSION = "changed-password"      # what rotating the password does
        check("old session is rejected", client.get(f"/{S}/api/me").status_code, 401)
        wa._CRED_VERSION = original
        client.post(f"/{S}/api/logout")

        print("\n14. /health does not publish the secret panel path")
        h = client.get("/health").json()
        check("health is minimal", h, {"ok": True})
        check_true("secret path absent", S not in str(h))

        print("\n15. the captcha renderer itself")
        code = captcha_mod.new_code()
        check("code length", len(code), captcha_mod.LENGTH)
        check_true("only unambiguous glyphs", all(ch in captcha_mod.ALPHABET for ch in code))
        check_true("no look-alike characters in the alphabet",
                   not (set("01OIl2Z5S8B69") & set(captcha_mod.ALPHABET)))
        png = captcha_mod.render_png(code)
        check_true("renders a real PNG", png.startswith(b"\x89PNG\r\n\x1a\n"))
        check_true("without needing a system font", len(png) > 1000)
        # A Persian keyboard and a phone's autocapitalise must not fail a login.
        check("persian digits fold to ASCII", captcha_mod.normalize("۳۴۷ac"), "347AC")
        check("whitespace is ignored", captcha_mod.normalize(" a c 3 "), "AC3")

        print("\n16. proof-of-work verification agrees with the client")
        prefix = "unit-test-prefix"
        n = solve(prefix, 12)
        check_true("a solved nonce verifies", lg._pow_ok(prefix, n, 12))
        check("an unsolved one does not", lg._pow_ok(prefix, str(int(n) + 1), 24), False)

        print("\n17. a forged CF-Connecting-IP cannot rotate the lockout key")
        # The attack this closes: the origin is reachable directly on its public
        # IP:PORT, so an attacker who skips Cloudflare can send any
        # CF-Connecting-IP they like. A fresh one per request used to land every
        # guess in a new bucket, so the lockout never fired at all.
        from core.client_app import client_ip, _from_trusted_proxy

        class FakeReq:
            def __init__(self, peer, headers):
                self.client = type("C", (), {"host": peer})()
                self.headers = headers

        spoof = {"cf-connecting-ip": "1.2.3.4", "x-forwarded-for": "5.6.7.8"}
        check("header ignored from a direct public peer",
              client_ip(FakeReq("203.0.113.9", spoof)), "203.0.113.9")
        check("header honoured from localhost (nginx in front)",
              client_ip(FakeReq("127.0.0.1", spoof)), "1.2.3.4")
        check("header honoured from a Cloudflare edge",
              client_ip(FakeReq("162.158.1.1", spoof)), "1.2.3.4")
        check("x-forwarded-for used when cf header is absent",
              client_ip(FakeReq("10.0.0.5", {"x-forwarded-for": "9.9.9.9, 8.8.8.8"})), "9.9.9.9")
        check("no headers → the socket peer", client_ip(FakeReq("198.51.100.7", {})), "198.51.100.7")
        check_true("cloudflare range recognised", _from_trusted_proxy("104.16.0.1"))
        check("a random public IP is not a trusted proxy", _from_trusted_proxy("8.8.8.8"), False)

        print("\n18. a lost challenge does NOT count against the admin")
        # Otherwise flooding the challenge table locks the owner out for free.
        lg.reset_all()
        before = lg._state("testclient", time.time())[0]
        r = login(cid="no-such-challenge")
        check("rejected", r.json()["error"], "challenge_missing")
        check("but the failure counter did NOT move",
              lg._state("testclient", time.time())[0], before)

        print("\n19. the challenge table evicts the oldest, never everything")
        lg.reset_all()
        mine = challenge()["id"]
        # Push the table past its cap with newer entries.
        for _ in range(lg._MAX_TRACKED + 50):
            lg._CHALLENGES[f"filler-{_}"] = (time.time() + 1, "p", "", False)
        lg._sweep(time.time())
        check_true("the table was trimmed, not cleared", len(lg._CHALLENGES) > 0)
        check("it is held at the cap", len(lg._CHALLENGES) <= lg._MAX_TRACKED, True)

        print("\n20. issuing challenges is itself rate-limited")
        lg.reset_all()
        codes = [client.get(f"/{S}/api/login/challenge").status_code
                 for _ in range(lg.ISSUE_LIMIT + 4)]
        check(f"the first {lg.ISSUE_LIMIT} are served", codes[:lg.ISSUE_LIMIT], [200] * lg.ISSUE_LIMIT)
        check("then it throttles", codes[lg.ISSUE_LIMIT], 429)

        print("\n21. exhausting the render budget does not disable the captcha")
        # Degrading to "no captcha required" under load would hand an attacker a
        # switch to turn the escalation off.
        lg.reset_all()
        for i in range(lg.CAPTCHA_AFTER):
            login(pw=f"wrong{i}")
        lg._RENDERS = (lg.RENDER_CEILING + 1, time.time())   # budget spent
        c = lg.issue("testclient")
        check("no image is drawn", c["captcha"], None)
        check("but the request is marked busy", c["busy"], True)
        check_true("and the captcha is still demanded", lg.captcha_required("testclient"))

        print("\n22. the owner can demand the captcha on EVERY login")
        lg.reset_all()
        from core.database import set_setting as _set
        # TestClient runs the app's loop on its own thread, so a fresh
        # asyncio.run() here is safe for these direct DB writes.
        asyncio.run(_set("login_captcha_always", "1"))
        c = challenge()
        check_true("captcha appears on a clean IP when forced", c.get("captcha") is not None)
        r = login(chal=c, captcha="")      # right password, no captcha answer
        check("right password still needs the code", r.json()["error"], "captcha_wrong")
        check("did not authenticate", client.get(f"/{S}/api/me").status_code, 401)
        asyncio.run(_set("login_captcha_always", "0"))
        lg.reset_all()
        check("switching it off restores the invisible path", challenge().get("captcha"), None)

        print("\n23. failed-login alerts are throttled, but a lockout always speaks")
        lg.reset_all()
        check_true("first failure from an IP alerts", lg.should_alert("9.9.9.9", False))
        check("a second one within the cooldown stays quiet", lg.should_alert("9.9.9.9", False), False)
        check_true("a DIFFERENT ip still alerts", lg.should_alert("9.9.9.8", False))
        check_true("a lockout ignores the cooldown", lg.should_alert("9.9.9.9", True))
        lg.record_success("9.9.9.9")
        check_true("a successful login clears the alert memory", lg.should_alert("9.9.9.9", False))

        print("\n24. challenges cannot be pre-farmed to dodge the captcha")
        # The bug this guards: escalation used to be decided when the challenge
        # was ISSUED and frozen into it. An attacker could pull a handful while
        # their record was clean and then spend them captcha-free afterwards.
        lg.reset_all()
        farmed = [challenge() for _ in range(4)]
        check("all farmed while clean, so none carry an image",
              [c.get("captcha") for c in farmed], [None] * 4)
        for i in range(lg.CAPTCHA_AFTER):          # now earn the captcha
            login(pw=f"wrong{i}")
        r = login(chal=farmed[0])                  # correct password, stale challenge
        check("a pre-farmed challenge no longer skips the captcha",
              r.json()["error"], "need_captcha")
        check("did not authenticate", client.get(f"/{S}/api/me").status_code, 401)

        print("\n25. a challenge belongs to the IP that asked for it")
        lg.reset_all()
        c = challenge()
        stolen = lg.check("203.0.113.77", {
            "challenge_id": c["id"], "pow_nonce": solve(c["pow"]["prefix"], c["pow"]["bits"]),
        })
        check("spent from another address → refused", stolen, "challenge_missing")

        print("\n26. the failure window slides — no free pacing forever")
        # Anchored to the FIRST failure, an attacker could sit at LOCK_AFTER-1
        # guesses per window indefinitely: never locked, never alerted.
        lg.reset_all()
        now = time.time()
        for _ in range(lg.LOCK_AFTER - 1):
            lg.record_failure("5.5.5.5")
        fails, first, _, _ = lg._state("5.5.5.5", now)
        check("counter is just under the lock", fails, lg.LOCK_AFTER - 1)
        check_true("the window anchor moved to the latest failure", first >= now - 1)
        st = lg.record_failure("5.5.5.5")
        check_true("one more locks it", st["locked_for"] > 0)

        print("\n27. an expired lock does not hand back free captcha-less tries")
        # record_failure used to zero the counter on lock, and captcha_required
        # reads that counter — so every lock that expired granted CAPTCHA_AFTER
        # more attempts with no image.
        check_true("captcha still demanded straight after a lock",
                   lg.captcha_required("5.5.5.5"))
        lg._FAILURES["5.5.5.5"] = (lg._FAILURES["5.5.5.5"][0], time.time(), 0.0, 1)  # lock elapsed
        check_true("…and still demanded once the lock elapses",
                   lg.captcha_required("5.5.5.5"))

        print("\n28. a live lockout survives table pressure")
        lg.reset_all()
        for _ in range(lg.LOCK_AFTER):
            lg.record_failure("7.7.7.7")
        check_true("locked", lg.lock_remaining("7.7.7.7") > 0)
        for i in range(lg._MAX_TRACKED + 100):     # flood the table
            lg._FAILURES[f"f{i}"] = (1, time.time(), 0.0, 0)
        lg._sweep(time.time())
        check_true("the attacker's own lock was NOT laundered away",
                   lg.lock_remaining("7.7.7.7") > 0)

        print("\n29. solving the captcha correctly still logs you in")
        # The path that matters most once escalation fires: if this breaks, the
        # owner is locked out of their own panel by their own defence.
        lg.reset_all()
        for i in range(lg.CAPTCHA_AFTER):
            login(pw=f"wrong{i}")
        c = challenge()
        check_true("an image was issued", c.get("captcha") is not None)
        answer = lg._CHALLENGES[c["id"]][2]        # what the picture says
        r = login(chal=c, captcha=answer)
        check("right password + right code → 200", r.status_code, 200)
        check("authenticated", client.get(f"/{S}/api/me").status_code, 200)
        check("and the IP's record is cleared", lg._state("testclient", time.time())[0], 0)
        check("so the next login is invisible again", challenge().get("captcha"), None)
        client.post(f"/{S}/api/logout")

        print("\n30. the captcha answer tolerates how a Persian keyboard types it")
        lg.reset_all()
        for i in range(lg.CAPTCHA_AFTER):
            login(pw=f"wrong{i}")
        c = challenge()
        answer = lg._CHALLENGES[c["id"]][2]
        typed = answer.lower().replace("3", "۳").replace("4", "۴").replace("7", "۷")
        r = login(chal=c, captcha=" " + typed + " ")
        check("lowercase + Persian digits + stray spaces still works", r.status_code, 200)
        client.post(f"/{S}/api/logout")

    print("\n" + ("ALL PASSED" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}"))
    return 1 if FAILED else 0


sys.exit(main())
