"""Brute-force defence for the admin login.

THE SHAPE OF THIS, AND WHY.

The owner asked for something like reCAPTCHA v3 — invisible, nothing to type.
A true v3 equivalent is not buildable here and pretending otherwise would be
dishonest: that score comes from Google having seen the same browser across
millions of other sites, plus a model trained on labelled bot traffic at a scale
this panel will never generate. We have one site and a handful of logins a day.

What IS buildable, and fits the actual threat, is a layered check that is
invisible until something looks wrong:

  1. **A signed, single-use challenge.** You cannot POST the login cold; you
     must have fetched a challenge first. Kills the simplest scripts outright.
  2. **Proof of work.** The browser must find a nonce whose SHA-256 has N
     leading zero bits. Measured: ~1.1s in a browser at 16 bits, spent in the
     background while the admin is still typing their password, so the cost to
     them is zero. This is NOT a strong barrier on its own — a Python attacker
     hashes ~30× faster than `crypto.subtle` and clears 16 bits in 0.04s. Its
     real job is that it requires JavaScript to have run at all, which is what
     most credential-stuffing traffic cannot do.
  3. **A honeypot field and a minimum fill time.** A form returned in 80ms was
     not typed by a person, and a hidden input that only a parser would find
     should always be empty.
  4. **Rate limiting and progressive lockout.** THIS is the security boundary.
     Everything above is a filter; this is the wall. It caps an attacker at a
     couple of dozen attempts an hour regardless of how much CPU they own or
     how good their captcha solver is.
  5. **An image captcha, but only as escalation.** Shown after a few failures
     from that IP, not on every login. The owner never sees it in normal use;
     an attacker sees it immediately and permanently.

STATE IS IN PROCESS, ON PURPOSE. The app is a single process (bot + FastAPI in
one asyncio loop), so a dict is the correct amount of machinery here and it
resets on restart — which is the right failure mode: a restart should not keep
the owner locked out. If this is ever scaled to more than one worker, every
store below has to move to the database or the limits become per-worker and the
lockout becomes trivially bypassable.

ONE THING THIS DOES NOT FIX. The panel's "unguessable" URL prefix is published
by `GET /` and friends, which redirect anyone straight to it. That is a
deliberate convenience, but it means the secret path is not an access control —
which is exactly why the login itself needs the layers above.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from typing import Dict, Optional, Tuple

from core.captcha import LENGTH as CAPTCHA_LENGTH, new_code, normalize, render_png

logger = logging.getLogger(__name__)

# ── Tunables ─────────────────────────────────────────────────────────────────
CHALLENGE_TTL = 300           # seconds a challenge stays usable
POW_BITS = 16                 # ~1.1s in a browser, in the background
# Deliberately LOW. The proof-of-work is already a time floor and a
# cryptographic one; this only catches a client that replays a challenge with no
# round trip at all. Set anywhere near a human's fill time and it starts
# rejecting PASSWORD MANAGERS, which autofill and submit in one motion — an
# owner locked out of their own panel is a far worse outcome than an attacker
# saving 300ms.
MIN_FILL_MS = 350

CAPTCHA_AFTER = 3             # failures from an IP before the image appears
LOCK_AFTER = 8                # failures before the IP is locked out
LOCK_STEPS = (300, 900, 3600)  # 5min, 15min, then 1h for every lock after that

WINDOW = 900                  # failure-counting window, seconds
GLOBAL_LIMIT = 60             # failed logins from ALL IPs per window, then
GLOBAL_WINDOW = 300           # everyone gets the captcha — blunts a botnet

_MAX_TRACKED = 10_000         # hard cap so a spoofed-IP flood cannot eat memory


# ── Stores ───────────────────────────────────────────────────────────────────
# challenge id -> (issued_at, pow_prefix, captcha_code or "", issuing_ip)
# The IP is stored so a challenge minted for one caller cannot be spent by
# another, and so escalation can be re-evaluated when it is USED rather than
# trusted from when it was issued.
_CHALLENGES: Dict[str, Tuple[float, str, str, str]] = {}
# ip -> (failures, first_failure_at, locked_until, lock_count)
_FAILURES: Dict[str, Tuple[int, float, float, int]] = {}
_GLOBAL: Tuple[int, float] = (0, 0.0)


def _sweep(now: float) -> None:
    for cid in [k for k, v in _CHALLENGES.items() if now - v[0] > CHALLENGE_TTL]:
        _CHALLENGES.pop(cid, None)
    if len(_CHALLENGES) > _MAX_TRACKED:
        # Evict the OLDEST, never clear the table. Clearing it let a flood wipe
        # the challenge the real admin was holding, whose login then failed as
        # "challenge_missing" and counted against their own lockout — an
        # attacker could lock the owner out without guessing a single password.
        for cid, _ in sorted(_CHALLENGES.items(), key=lambda kv: kv[1][0])[: len(_CHALLENGES) - _MAX_TRACKED]:
            _CHALLENGES.pop(cid, None)
    for ip in [k for k, v in _FAILURES.items() if now - v[1] > WINDOW and now > v[2]]:
        _FAILURES.pop(ip, None)
    if len(_FAILURES) > _MAX_TRACKED:
        # Evict oldest-first, and NEVER an entry still serving a lock — clearing
        # the table would let an attacker launder their own lockout away.
        evictable = sorted(((k, v) for k, v in _FAILURES.items() if now > v[2]),
                           key=lambda kv: kv[1][1])
        for k, _ in evictable[: len(_FAILURES) - _MAX_TRACKED]:
            _FAILURES.pop(k, None)


def _state(ip: str, now: float) -> Tuple[int, float, float, int]:
    fails, first, locked_until, lock_count = _FAILURES.get(ip, (0, now, 0.0, 0))
    if now - first > WINDOW and now > locked_until:
        return 0, now, 0.0, lock_count
    return fails, first, locked_until, lock_count


def _global_hot(now: float) -> bool:
    count, started = _GLOBAL
    return count >= GLOBAL_LIMIT and now - started < GLOBAL_WINDOW


def lock_remaining(ip: str) -> int:
    """Seconds this IP must wait, or 0."""
    now = time.time()
    _, _, locked_until, _ = _state(ip, now)
    return max(0, int(locked_until - now))


def captcha_required(ip: str, force: bool = False) -> bool:
    """`force` is the owner's "always ask" switch from the panel."""
    if force:
        return True
    now = time.time()
    fails, _, _, _ = _state(ip, now)
    return fails >= CAPTCHA_AFTER or _global_hot(now)


# Issuing is unauthenticated and, once a captcha is due, does real image work.
# Without its own budget it is a free CPU amplifier against the single event
# loop that also runs the Telegram bot.
ISSUE_LIMIT = 12              # challenges per IP per minute
ISSUE_WINDOW = 60.0
RENDER_CEILING = 40           # captcha images rendered per minute, ALL callers
_ISSUE: Dict[str, Tuple[int, float]] = {}
_RENDERS: Tuple[int, float] = (0, 0.0)


def issue_allowed(ip: str) -> bool:
    now = time.time()
    if len(_ISSUE) > _MAX_TRACKED:
        _ISSUE.clear()
    count, started = _ISSUE.get(ip, (0, now))
    if now - started >= ISSUE_WINDOW:
        count, started = 0, now
    count += 1
    _ISSUE[ip] = (count, started)
    return count <= ISSUE_LIMIT


def _render_budget() -> bool:
    """Global ceiling on image renders, so tripping the captcha for everyone
    cannot be turned into a CPU flood."""
    global _RENDERS
    now = time.time()
    count, started = _RENDERS
    if now - started >= 60.0:
        count, started = 0, now
    count += 1
    _RENDERS = (count, started)
    return count <= RENDER_CEILING


# ── Challenge lifecycle ──────────────────────────────────────────────────────
def issue(ip: str, force_captcha: bool = False) -> Dict:
    """Mint a challenge for a login attempt.

    The captcha image is only generated when this IP has earned one (or the
    owner switched "always ask" on), so the normal path costs nothing and the
    owner never sees a puzzle.
    """
    now = time.time()
    _sweep(now)
    cid = secrets.token_urlsafe(18)
    prefix = secrets.token_urlsafe(12)
    # If the render budget is spent, still DEMAND a captcha — just do not draw a
    # new one. Degrading to "no captcha needed" under load would hand an attacker
    # a way to switch the escalation off.
    want_captcha = captcha_required(ip, force_captcha)
    can_draw = _render_budget() if want_captcha else False
    code = new_code() if (want_captcha and can_draw) else ""
    _CHALLENGES[cid] = (now, prefix, code, ip)

    out = {
        "id": cid,
        "pow": {"prefix": prefix, "bits": POW_BITS},
        "captcha": None,
        "min_fill_ms": MIN_FILL_MS,
        "locked_for": lock_remaining(ip),
        "busy": bool(want_captcha and not can_draw),
    }
    if code:
        import base64
        png = render_png(code)
        out["captcha"] = {
            "image": "data:image/png;base64," + base64.b64encode(png).decode(),
            "length": CAPTCHA_LENGTH,
        }
    return out


def _pow_ok(prefix: str, nonce: str, bits: int = POW_BITS) -> bool:
    digest = hashlib.sha256(f"{prefix}:{nonce}".encode("utf-8")).digest()
    seen = 0
    for byte in digest:
        if byte == 0:
            seen += 8
            continue
        b = byte
        while b < 128:
            b <<= 1
            seen += 1
        break
    return seen >= bits


def check(ip: str, payload: Dict, force_captcha: bool = False) -> Optional[str]:
    """Validate everything except the password. Returns an error code or None.

    A challenge is consumed the moment it is checked, pass or fail — otherwise
    one solved proof-of-work could be replayed for an unlimited number of
    password guesses, which would make the whole layer decorative.
    """
    now = time.time()
    _sweep(now)

    remaining = lock_remaining(ip)
    if remaining:
        return f"locked:{remaining}"

    cid = str(payload.get("challenge_id") or "")
    entry = _CHALLENGES.pop(cid, None)          # single use, always
    if not entry:
        # Returned WITHOUT counting a failure (see record_failure's caller): a
        # challenge goes missing when it expires or is evicted under load, which
        # happens to legitimate logins too. Counting it would let an attacker
        # who floods the challenge table drive the owner's lockout.
        return "challenge_missing"
    issued, prefix, code, owner = entry
    if now - issued > CHALLENGE_TTL:
        return "challenge_expired"
    # A challenge belongs to the caller who asked for it. Without this an
    # attacker could farm challenges from one address and spend them from
    # another to dodge that address's escalation.
    if owner and owner != ip:
        return "challenge_missing"

    # Measured against the server's own issue time — never a client-supplied
    # timestamp, which the client controls.
    if (now - issued) * 1000 < MIN_FILL_MS:
        return "too_fast"

    # Hidden field: present in the DOM, never visible, never filled by a person.
    if str(payload.get("website") or "").strip():
        return "honeypot"

    if not _pow_ok(prefix, str(payload.get("pow_nonce") or "")):
        return "pow_failed"

    if code:
        if normalize(str(payload.get("captcha") or "")) != code:
            return "captcha_wrong"
    elif captcha_required(ip, force_captcha):
        # This challenge carries no image, but by the time it was USED the caller
        # had earned one. Re-evaluating here (rather than trusting the flag from
        # issue time) is what stops an attacker pre-farming challenges while
        # clean and spending them captcha-free afterwards.
        return "need_captcha"

    return None


def record_failure(ip: str) -> Dict:
    """Count a failed login and escalate. Returns the new state for the caller."""
    global _GLOBAL
    now = time.time()
    fails, first, locked_until, lock_count = _state(ip, now)
    fails += 1

    # The window slides with each failure. Anchoring it to the FIRST failure let
    # an attacker pace themselves at LOCK_AFTER-1 guesses per window forever —
    # never locking, never alerting, and still ~28 guesses an hour.
    first = now

    if fails >= LOCK_AFTER:
        step = LOCK_STEPS[min(lock_count, len(LOCK_STEPS) - 1)]
        locked_until = now + step
        lock_count += 1
        # Deliberately NOT reset to zero: the counter is what keeps the captcha
        # on. Zeroing it handed the attacker CAPTCHA_AFTER free attempts after
        # every lock expired. Held at the captcha threshold instead.
        fails = CAPTCHA_AFTER
        logger.warning("admin login: locking %s for %ss (lock #%s)", ip, step, lock_count)

    _FAILURES[ip] = (fails, first, locked_until, lock_count)

    count, started = _GLOBAL
    _GLOBAL = (1, now) if now - started > GLOBAL_WINDOW else (count + 1, started)

    return {"failures": fails, "locked_for": max(0, int(locked_until - now)),
            "captcha_next": captcha_required(ip)}


# Telegram alerts on failed logins. The owner asked to hear about them; without
# a throttle a sustained attack would turn their chat into a firehose and they
# would mute it, which is worse than no alert at all.
ALERT_COOLDOWN = 600
_ALERTED: Dict[str, float] = {}


def should_alert(ip: str, locked: bool) -> bool:
    """True at most once per IP per cooldown — but a LOCKOUT always speaks up."""
    now = time.time()
    if len(_ALERTED) > _MAX_TRACKED:
        _ALERTED.clear()
    if locked:
        _ALERTED[ip] = now
        return True
    if now - _ALERTED.get(ip, 0.0) < ALERT_COOLDOWN:
        return False
    _ALERTED[ip] = now
    return True


def record_success(ip: str) -> None:
    _FAILURES.pop(ip, None)
    _ALERTED.pop(ip, None)


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest((a or "").encode("utf-8"), (b or "").encode("utf-8"))


def reset_all() -> None:
    """Test hook — also what a process restart does implicitly."""
    global _GLOBAL, _RENDERS
    _CHALLENGES.clear()
    _FAILURES.clear()
    _ISSUE.clear()
    _ALERTED.clear()
    _GLOBAL = (0, 0.0)
    _RENDERS = (0, 0.0)
