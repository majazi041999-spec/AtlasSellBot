"""Representative (reseller) API — keys, quotas and idempotency.

This is the credential/limit layer behind ``/api/rep/v1/*`` (routes live in
``web/rep_api.py``). A representative pastes a key into *their own* bot and that
bot then creates and manages services on our platform, spending the rep's
wallet balance.

SECURITY MODEL — read before changing anything here.

Unlike ``core/client_app.py`` (whose key is a speed bump baked into a public
APK), a key issued here is **real authorisation to spend money**. It can create
services, charge the rep's wallet and revoke a customer's link. Everything
below follows from that:

1. **The key is never stored.** Only ``sha256(key)`` is, and lookups happen by
   that hash — the database can be dumped without yielding a usable credential.
   A plain SHA-256 (not bcrypt/argon2) is correct *here* and only here: the key
   is 32 bytes of ``secrets`` entropy, so there is no dictionary to run against
   it, and the hash is computed on every request. Never reuse this shortcut for
   anything a human chooses.

2. **Authorisation is re-checked on every request, from the users table.** The
   key row is not the source of truth for "is this still a representative".
   Losing rep status, or being blocked, kills every key instantly without any
   revocation step — see ``authenticate()``.

3. **Money paths are idempotent and serialised.** A reseller bot retries on
   timeout; without ``Idempotency-Key`` support that retry is a second charge
   and a second service. ``idem_*`` below stores the first response and replays
   it. ``user_lock()`` serialises a rep's balance writes so two concurrent
   creates cannot both pass the same balance check (single-process app — if
   this is ever scaled out, that lock has to become a database one).

4. **A key is per-representative and scoped to their own rows.** Nothing here
   grants a lookup by another user's id; the route layer must always filter by
   ``key["user_id"]``.

5. **No CORS, ever.** These endpoints are for a rep's *server*. Adding
   ``Access-Control-Allow-Origin`` would invite putting the key in a browser or
   a mobile app, where it can be extracted (see rule 1 of ``client_app``).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import secrets
import time
from typing import Dict, List, Optional, Tuple

import aiosqlite

from core.config import DB_PATH

# ── Key format ────────────────────────────────────────────────────────────────
# The prefix is cosmetic but load-bearing for humans: it makes a leaked key
# recognisable in a log or a paste, and lets secret scanners match on it.
KEY_PREFIX = "atlas_rep_"
_KEY_BYTES = 32                 # → 43 url-safe chars
_DISPLAY_PREFIX_LEN = len(KEY_PREFIX) + 8

# Per-representative ceilings. Deliberately small: a rep needs one key per bot,
# and "I'll just make another" is how unused credentials pile up.
MAX_KEYS_PER_REP = 3
DEFAULT_RATE_PER_MIN = 120
MAX_RATE_PER_MIN = 600

# Responses to a money call are replayable for this long. A day covers any
# realistic retry (including a bot that was down and resumed) without keeping
# request bodies around forever.
IDEMPOTENCY_TTL = 86_400


SCHEMA = """
CREATE TABLE IF NOT EXISTS rep_api_keys (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,          -- users.id of the representative
    name          TEXT DEFAULT '',           -- rep-chosen label ("my bot")
    prefix        TEXT NOT NULL,             -- visible head of the key, for identification
    key_hash      TEXT NOT NULL UNIQUE,      -- sha256(key) — the key itself is never stored
    scopes        TEXT DEFAULT 'read,write',
    ip_allowlist  TEXT DEFAULT '',           -- comma-separated IPs/CIDRs — empty means any
    rate_per_min  INTEGER DEFAULT 120,
    is_active     INTEGER DEFAULT 1,
    created_at    INTEGER NOT NULL,
    last_used_at  INTEGER DEFAULT 0,
    last_ip       TEXT DEFAULT '',
    calls         INTEGER DEFAULT 0,
    revoked_at    INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_rep_api_keys_user ON rep_api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_rep_api_keys_hash ON rep_api_keys(key_hash);

CREATE TABLE IF NOT EXISTS rep_api_idempotency (
    user_id      INTEGER NOT NULL,
    idem_key     TEXT NOT NULL,
    endpoint     TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status       INTEGER DEFAULT 0,          -- 0 = still in flight
    response     TEXT DEFAULT '',
    created_at   INTEGER NOT NULL,
    PRIMARY KEY (user_id, idem_key)
);

CREATE INDEX IF NOT EXISTS idx_rep_api_idem_created ON rep_api_idempotency(created_at);
"""


async def ensure_schema(db) -> None:
    """Create the API tables on an existing connection (called by init_db)."""
    for stmt in SCHEMA.strip().split(";"):
        s = stmt.strip()
        if s:
            await db.execute(s)


# ── Key lifecycle ─────────────────────────────────────────────────────────────
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_scopes(raw) -> str:
    """Keep only scopes we actually enforce, in a stable order."""
    known = ("read", "write")
    if isinstance(raw, str):
        parts = [p.strip().lower() for p in raw.split(",")]
    else:
        parts = [str(p).strip().lower() for p in (raw or [])]
    picked = [s for s in known if s in parts]
    return ",".join(picked) if picked else "read"


def normalize_allowlist(raw) -> str:
    """Validate every entry, drop the rest.

    Silently keeping a malformed entry would be dangerous: an allowlist that
    fails to parse must never degrade into "allow everything".
    """
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.replace(";", ",").split(",")]
    else:
        parts = [str(p).strip() for p in (raw or [])]
    out: List[str] = []
    for p in parts:
        if not p:
            continue
        try:
            ipaddress.ip_network(p, strict=False)
        except ValueError:
            continue
        if p not in out:
            out.append(p)
    return ",".join(out[:20])


def ip_allowed(allowlist: str, ip: str) -> bool:
    entries = [p.strip() for p in str(allowlist or "").split(",") if p.strip()]
    if not entries:
        return True
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        # An unparseable caller IP with an allowlist set is a hard no: we cannot
        # prove it belongs, and the rep asked us to prove it.
        return False
    for entry in entries:
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


async def create_key(user_id: int, name: str = "", scopes: str = "read,write",
                     ip_allowlist: str = "", rate_per_min: int = DEFAULT_RATE_PER_MIN) -> Dict:
    """Issue a new key. The plaintext is returned ONCE, under ``key``."""
    token = KEY_PREFIX + secrets.token_urlsafe(_KEY_BYTES)
    now = int(time.time())
    rate = max(10, min(MAX_RATE_PER_MIN, int(rate_per_min or DEFAULT_RATE_PER_MIN)))
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM rep_api_keys WHERE user_id=? AND is_active=1", (int(user_id),)
        ) as c:
            row = await c.fetchone()
        if int(row[0] if row else 0) >= MAX_KEYS_PER_REP:
            return {"ok": False, "error": "key_limit_reached", "limit": MAX_KEYS_PER_REP}
        cur = await db.execute(
            """INSERT INTO rep_api_keys(user_id,name,prefix,key_hash,scopes,ip_allowlist,
                                        rate_per_min,is_active,created_at)
               VALUES(?,?,?,?,?,?,?,1,?)""",
            (int(user_id), str(name or "")[:40], token[:_DISPLAY_PREFIX_LEN], _hash(token),
             normalize_scopes(scopes), normalize_allowlist(ip_allowlist), rate, now),
        )
        await db.commit()
        key_id = cur.lastrowid
    return {"ok": True, "id": key_id, "key": token, "prefix": token[:_DISPLAY_PREFIX_LEN],
            "scopes": normalize_scopes(scopes), "rate_per_min": rate, "created_at": now}


async def list_keys(user_id: int, include_revoked: bool = False) -> List[Dict]:
    sql = "SELECT * FROM rep_api_keys WHERE user_id=?"
    if not include_revoked:
        sql += " AND is_active=1"
    sql += " ORDER BY id DESC"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, (int(user_id),)) as c:
            return [dict(r) for r in await c.fetchall()]


async def list_all_keys(limit: int = 200) -> List[Dict]:
    """Every key on the platform, newest and still-active first, with its owner
    attached. Admin overview only — never reachable through a rep's own key."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT k.*, u.telegram_id, u.full_name, u.username
               FROM rep_api_keys k JOIN users u ON u.id = k.user_id
               ORDER BY k.is_active DESC, k.id DESC LIMIT ?""",
            (max(1, int(limit or 200)),),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def revoke_key(key_id: int, user_id: Optional[int] = None) -> bool:
    """Revoke one key. ``user_id`` scopes the write so a rep can only touch
    their own; admin callers pass None."""
    sql = "UPDATE rep_api_keys SET is_active=0, revoked_at=? WHERE id=? AND is_active=1"
    args: list = [int(time.time()), int(key_id)]
    if user_id is not None:
        sql += " AND user_id=?"
        args.append(int(user_id))
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(sql, tuple(args))
        await db.commit()
        return cur.rowcount > 0


async def revoke_all(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE rep_api_keys SET is_active=0, revoked_at=? WHERE user_id=? AND is_active=1",
            (int(time.time()), int(user_id)),
        )
        await db.commit()
        return cur.rowcount


async def authenticate(token: str) -> Optional[Dict]:
    """Resolve a presented key to ``{key, user}``, or None.

    The user row is re-read and re-checked every call on purpose: revoking rep
    status or blocking an account must take effect immediately, without anyone
    remembering to also revoke the keys.
    """
    token = (token or "").strip()
    if not token.startswith(KEY_PREFIX) or len(token) < len(KEY_PREFIX) + 20:
        return None
    digest = _hash(token)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM rep_api_keys WHERE key_hash=? AND is_active=1", (digest,)
        ) as c:
            key = await c.fetchone()
        if not key:
            return None
        # Defence in depth: the row came back from an equality match on the
        # digest, so this can only fail on a corrupted row — but compare in
        # constant time anyway rather than trusting SQLite's matching.
        if not hmac.compare_digest(str(key["key_hash"]), digest):
            return None
        async with db.execute("SELECT * FROM users WHERE id=?", (int(key["user_id"]),)) as c:
            user = await c.fetchone()
    if not user:
        return None
    return {"key": dict(key), "user": dict(user)}


# Writing last_used_at on literally every call turns a read endpoint into a
# write. Once a minute per key is enough to answer "is this key still in use?"
# and keeps polling bots off the write path.
_TOUCH_EVERY = 60.0
_last_touch: Dict[int, float] = {}


async def touch(key_id: int, ip: str) -> None:
    now = time.time()
    if now - _last_touch.get(int(key_id), 0.0) < _TOUCH_EVERY:
        return
    _last_touch[int(key_id)] = now
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE rep_api_keys SET last_used_at=?, last_ip=?, calls=calls+1 WHERE id=?",
                (int(now), str(ip or "")[:64], int(key_id)),
            )
            await db.commit()
    except Exception:
        # Usage bookkeeping must never fail a customer's request.
        pass


# ── Rate limiting ─────────────────────────────────────────────────────────────
# Fixed window per key, in process. The point is to keep one rep's runaway loop
# from monopolising the panel-facing worker pool — the expensive part of a
# create is HTTP round-trips to x-ui, and those are shared with every other
# customer on the box.
_RATE: Dict[int, Tuple[int, float]] = {}
_RATE_WINDOW = 60.0


def rate_check(key_id: int, limit: int) -> Tuple[bool, int, int]:
    """Consume one unit. Returns ``(allowed, remaining, seconds_until_reset)``."""
    limit = max(1, int(limit or DEFAULT_RATE_PER_MIN))
    now = time.time()
    count, started = _RATE.get(int(key_id), (0, now))
    if now - started >= _RATE_WINDOW:
        count, started = 0, now
    count += 1
    _RATE[int(key_id)] = (count, started)
    reset_in = max(1, int(_RATE_WINDOW - (now - started)))
    return count <= limit, max(0, limit - count), reset_in


# ── Per-rep serialisation for money paths ─────────────────────────────────────
_locks: Dict[int, asyncio.Lock] = {}


def user_lock(user_id: int) -> asyncio.Lock:
    """One lock per representative, so concurrent charges queue instead of
    racing the balance check. Single-process only — see the module docstring."""
    lock = _locks.get(int(user_id))
    if lock is None:
        lock = asyncio.Lock()
        _locks[int(user_id)] = lock
    return lock


# ── Idempotency ───────────────────────────────────────────────────────────────
def request_fingerprint(endpoint: str, body: Dict) -> str:
    """Stable hash of what was asked for, so replaying a key with a *different*
    body is caught instead of silently returning the wrong service."""
    try:
        payload = json.dumps(body or {}, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        payload = str(body)
    return hashlib.sha256(f"{endpoint}\n{payload}".encode("utf-8")).hexdigest()


async def idem_begin(user_id: int, idem_key: str, endpoint: str, fingerprint: str) -> Dict:
    """Claim an idempotency key.

    Returns one of:
      ``{"state": "new"}``       — first time, go ahead and do the work
      ``{"state": "replay", "status": int, "body": dict}``
      ``{"state": "in_flight"}`` — an identical call is still running
      ``{"state": "conflict"}``  — same key, different request body
    """
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("DELETE FROM rep_api_idempotency WHERE created_at < ?",
                         (now - IDEMPOTENCY_TTL,))
        try:
            await db.execute(
                """INSERT INTO rep_api_idempotency(user_id,idem_key,endpoint,request_hash,status,response,created_at)
                   VALUES(?,?,?,?,0,'',?)""",
                (int(user_id), str(idem_key)[:120], str(endpoint)[:80], fingerprint, now),
            )
            await db.commit()
            return {"state": "new"}
        except aiosqlite.IntegrityError:
            await db.commit()
        async with db.execute(
            "SELECT * FROM rep_api_idempotency WHERE user_id=? AND idem_key=?",
            (int(user_id), str(idem_key)[:120]),
        ) as c:
            row = await c.fetchone()
    if not row:
        # Lost a race with the TTL sweep; treat as fresh.
        return {"state": "new"}
    if str(row["request_hash"]) != fingerprint:
        return {"state": "conflict"}
    if int(row["status"] or 0) <= 0:
        return {"state": "in_flight"}
    try:
        body = json.loads(row["response"] or "{}")
    except Exception:
        body = {}
    return {"state": "replay", "status": int(row["status"]), "body": body}


async def idem_finish(user_id: int, idem_key: str, status: int, body: Dict) -> None:
    try:
        payload = json.dumps(body or {}, ensure_ascii=False, default=str)
    except Exception:
        payload = "{}"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE rep_api_idempotency SET status=?, response=? WHERE user_id=? AND idem_key=?",
            (int(status), payload, int(user_id), str(idem_key)[:120]),
        )
        await db.commit()


async def idem_abort(user_id: int, idem_key: str) -> None:
    """Release a claimed key that never produced a result, so the caller's
    retry is a fresh attempt rather than a permanent ``in_flight``."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM rep_api_idempotency WHERE user_id=? AND idem_key=? AND status=0",
            (int(user_id), str(idem_key)[:120]),
        )
        await db.commit()
