"""A working, disposable copy of the reseller API for people building against it.

WHY THIS EXISTS. Integrating against a selling API means, on the first attempt,
buying things. A reseller writing their bot has to create services to see what a
service looks like, get the renewal wrong twice, and discover the shape of an
error by causing one. Doing that against production costs them real money,
provisions real clients on real panels, and leaves the owner with a fleet of
half-finished test accounts nobody dares delete.

So a sandbox key gets the same endpoints, the same request bodies, the same
response shapes and the same error codes — backed by a scratch dataset that
touches no panel and no wallet. When their code works, they swap the key and
nothing else changes. That last property is the whole point, so anything that
would make the sandbox behave differently from production is a bug here, not a
simplification.

WHAT IS DELIBERATELY REAL:
  * Pricing, quotas and the wallet. A sandbox wallet starts with play money and
    is really debited, so `insufficient_funds` is reachable — it is one of the
    two errors integrators most need to handle and the hardest to trigger on
    purpose in production.
  * Traffic. `used_bytes` climbs with elapsed time instead of sitting at zero
    forever, so usage bars, quota warnings and "nearly finished" logic can be
    exercised without waiting a month.
  * Expiry, including first-use activation.

WHAT IS DELIBERATELY FAKE, and says so:
  * Subscription URLs point at `sandbox.invalid`, a reserved TLD that can never
    resolve. Nobody can mistake one for a working config, and no VPN client will
    quietly hold onto it.
  * Nothing is provisioned. There are no nodes on any server, so nothing here
    can disturb a paying customer.

The data lives in its own tables keyed by API key, so two of a reseller's keys
do not see each other's experiments, and `POST /v1/sandbox/reset` wipes one key
back to a fresh wallet.
"""
from __future__ import annotations

import secrets
import time
from typing import Dict, List, Optional, Tuple

import aiosqlite

from core.config import DB_PATH

GB = 1024 ** 3

# Play money. Large enough to build against for days, small enough that a loop
# with a bug still finds the bottom and shows them `insufficient_funds`.
STARTING_BALANCE = 50_000_000

# Reserved by RFC 6761 — guaranteed never to resolve.
FAKE_HOST = "sandbox.invalid"

SCHEMA = """
CREATE TABLE IF NOT EXISTS rep_sandbox_wallet (
    key_id       INTEGER PRIMARY KEY,
    balance      INTEGER DEFAULT 0,
    created_at   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rep_sandbox_services (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id              INTEGER NOT NULL,
    name                TEXT DEFAULT '',
    email               TEXT DEFAULT '',
    token               TEXT NOT NULL,
    traffic_gb          REAL DEFAULT 0,
    duration_days       INTEGER DEFAULT 0,
    expire_timestamp    INTEGER DEFAULT 0,   -- epoch ms, to match production
    is_active           INTEGER DEFAULT 1,
    starts_on_first_use INTEGER DEFAULT 0,
    first_use_at        INTEGER DEFAULT 0,
    price               INTEGER DEFAULT 0,
    package_id          INTEGER DEFAULT 0,
    is_trial            INTEGER DEFAULT 0,
    deleted             INTEGER DEFAULT 0,
    created_at          INTEGER DEFAULT 0,
    burn_bytes_per_sec  INTEGER DEFAULT 0    -- makes used_bytes climb believably
);

CREATE TABLE IF NOT EXISTS rep_sandbox_orders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id       INTEGER NOT NULL,
    service_id   INTEGER DEFAULT 0,
    kind         TEXT DEFAULT '',
    amount       INTEGER DEFAULT 0,
    balance_after INTEGER DEFAULT 0,
    detail       TEXT DEFAULT '',
    created_at   INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sandbox_services_key ON rep_sandbox_services(key_id, deleted);
CREATE INDEX IF NOT EXISTS idx_sandbox_orders_key ON rep_sandbox_orders(key_id, created_at DESC);
"""


async def ensure_schema(db) -> None:
    for stmt in SCHEMA.split(";"):
        if stmt.strip():
            await db.execute(stmt)


# ─────────────────────────────────────────────────────────────── wallet

async def _wallet_row(db, key_id: int) -> int:
    async with db.execute("SELECT balance FROM rep_sandbox_wallet WHERE key_id=?",
                          (int(key_id),)) as c:
        row = await c.fetchone()
    if row:
        return int(row[0])
    await db.execute("INSERT INTO rep_sandbox_wallet(key_id,balance,created_at) VALUES(?,?,?)",
                     (int(key_id), STARTING_BALANCE, int(time.time())))
    return STARTING_BALANCE


async def balance(key_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        b = await _wallet_row(db, key_id)
        await db.commit()
        return b


async def _charge(db, key_id: int, amount: int, kind: str, service_id: int = 0,
                  detail: str = "") -> Tuple[bool, int]:
    """(ok, balance_after). Refuses rather than going negative, exactly as the
    real wallet does — reaching `insufficient_funds` on purpose is one of the
    things a sandbox is for."""
    bal = await _wallet_row(db, key_id)
    amount = max(0, int(amount))
    if amount > bal:
        return False, bal
    bal -= amount
    await db.execute("UPDATE rep_sandbox_wallet SET balance=? WHERE key_id=?", (bal, int(key_id)))
    await db.execute(
        """INSERT INTO rep_sandbox_orders(key_id,service_id,kind,amount,balance_after,detail,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (int(key_id), int(service_id), kind, amount, bal, detail[:200], int(time.time())))
    return True, bal


# ───────────────────────────────────────────────────────── service shaping

def _used_bytes(row: Dict, now: int) -> int:
    """Believable, monotonic, and capped at the quota.

    A sandbox where usage is always zero cannot exercise the two things every
    integrator gets wrong: rendering a usage bar, and handling a service that
    has run out. The rate is derived from the service id so it is stable across
    calls rather than jittering every poll.
    """
    started = int(row.get("first_use_at") or 0) or int(row.get("created_at") or now)
    elapsed = max(0, now - started)
    rate = int(row.get("burn_bytes_per_sec") or 0)
    used = rate * elapsed
    total = int(float(row.get("traffic_gb") or 0) * GB)
    if total > 0:
        used = min(used, total)
    return int(used)


def _status(row: Dict, now_ms: int, used: int) -> str:
    if int(row.get("deleted") or 0):
        return "deleted"
    if not int(row.get("is_active") or 0):
        return "disabled"
    total = int(float(row.get("traffic_gb") or 0) * GB)
    if total > 0 and used >= total:
        return "exhausted"
    exp = int(row.get("expire_timestamp") or 0)
    if exp > 0 and exp <= now_ms:
        return "expired"
    if int(row.get("starts_on_first_use") or 0) and not int(row.get("first_use_at") or 0):
        return "not_started"
    return "active"


def payload(row: Dict, *, with_nodes: bool = False) -> Dict:
    """The same object production returns, field for field.

    Kept deliberately in step with `web/rep_api.py::_service_payload`: an
    integrator whose code works here must not meet a missing key when they swap
    to a live key. If a field is added there, add it here.
    """
    now = int(time.time())
    now_ms = now * 1000
    used = _used_bytes(row, now)
    total = int(float(row.get("traffic_gb") or 0) * GB)
    expire_ms = int(row.get("expire_timestamp") or 0)
    out = {
        "id": int(row["id"]),
        "name": row.get("name") or row.get("email") or "",
        "email": row.get("email") or "",
        "status": _status(row, now_ms, used),
        "is_active": bool(int(row.get("is_active") or 0)),
        "unlimited": total <= 0,
        "traffic_gb": float(row.get("traffic_gb") or 0),
        "used_bytes": used,
        "remaining_bytes": max(0, total - used) if total > 0 else None,
        "usage_percent": round(min(100.0, used / total * 100), 2) if total > 0 else None,
        "expires_at": expire_ms,
        "days_left": max(0, int((expire_ms - now_ms) / 86_400_000)) if expire_ms > 0 else None,
        "starts_on_first_use": bool(int(row.get("starts_on_first_use") or 0)),
        "first_use_at": int(row.get("first_use_at") or 0),
        "duration_days": int(row.get("duration_days") or 0),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(row.get("created_at") or now))),
        "subscription_url": f"https://{FAKE_HOST}/sub/{row.get('token')}",
        # Present in every sandbox object so a response can never be mistaken
        # for a real one, in a log, a screenshot or a support ticket.
        "sandbox": True,
    }
    if with_nodes:
        # Nothing is provisioned anywhere, and saying so is more useful than
        # inventing server names an integrator might try to connect to.
        out["nodes"] = []
    return out


# ───────────────────────────────────────────────────────────── operations

async def _fetch(db, key_id: int, sid: int) -> Optional[Dict]:
    db.row_factory = aiosqlite.Row
    async with db.execute(
        "SELECT * FROM rep_sandbox_services WHERE id=? AND key_id=? AND deleted=0",
        (int(sid), int(key_id))
    ) as c:
        row = await c.fetchone()
    return dict(row) if row else None


async def list_services(key_id: int) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM rep_sandbox_services WHERE key_id=? AND deleted=0 ORDER BY id DESC",
            (int(key_id),)
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_service(key_id: int, sid: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        return await _fetch(db, key_id, sid)


async def create_service(key_id: int, *, name: str, traffic_gb: float, duration_days: int,
                         price: int, package_id: int = 0, starts_on_first_use: bool = False,
                         is_trial: bool = False) -> Dict:
    now = int(time.time())
    token = secrets.token_urlsafe(16)
    async with aiosqlite.connect(DB_PATH) as db:
        ok, bal = (True, await _wallet_row(db, key_id)) if is_trial else (None, None)
        if not is_trial:
            ok, bal = await _charge(db, key_id, price, "purchase", detail=name)
            if not ok:
                await db.commit()
                return {"ok": False, "error": "insufficient_funds", "balance": bal, "price": int(price)}
        expire_ms = 0 if starts_on_first_use or duration_days <= 0 else (now + duration_days * 86400) * 1000
        # A rate that fills the quota in roughly a third of the period, so a
        # month-long service visibly moves within a day of testing.
        span = max(1, duration_days) * 86400
        burn = int(float(traffic_gb) * GB / (span / 3)) if traffic_gb > 0 else 12_000
        cur = await db.execute(
            """INSERT INTO rep_sandbox_services
                   (key_id,name,email,token,traffic_gb,duration_days,expire_timestamp,is_active,
                    starts_on_first_use,first_use_at,price,package_id,is_trial,deleted,created_at,
                    burn_bytes_per_sec)
               VALUES(?,?,?,?,?,?,?,1,?,0,?,?,?,0,?,?)""",
            (int(key_id), name, f"sbx_{token[:10]}", token, float(traffic_gb), int(duration_days),
             int(expire_ms), 1 if starts_on_first_use else 0, int(price), int(package_id),
             1 if is_trial else 0, now, burn))
        sid = cur.lastrowid
        await db.commit()
        row = await _fetch(db, key_id, sid)
    # No `nodes` here, deliberately: production's create returns the service
    # WITHOUT them (web/rep_api.py:744) and only the detail endpoint includes
    # them. A sandbox that hands back an extra field teaches an integrator to
    # depend on something that will not be there when they switch keys.
    return {"ok": True, "service": payload(row), "charged": 0 if is_trial else int(price),
            "balance": bal}


async def renew_service(key_id: int, sid: int, *, duration_days: int, traffic_gb: float,
                        price: int) -> Dict:
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        row = await _fetch(db, key_id, sid)
        if not row:
            return {"ok": False, "error": "service_not_found"}
        ok, bal = await _charge(db, key_id, price, "renew", service_id=sid, detail=row.get("name") or "")
        if not ok:
            await db.commit()
            return {"ok": False, "error": "insufficient_funds", "balance": bal, "price": int(price)}
        # Renewing from whichever is later — now, or the current expiry — is the
        # behaviour production has, and getting it wrong is a classic bug in an
        # integrator's retry path, so the sandbox has to reproduce it exactly.
        base_ms = max(now * 1000, int(row.get("expire_timestamp") or 0))
        expire_ms = base_ms + int(duration_days) * 86_400_000
        await db.execute(
            """UPDATE rep_sandbox_services
                  SET expire_timestamp=?, duration_days=?, traffic_gb=?, is_active=1,
                      first_use_at=?, created_at=?
                WHERE id=? AND key_id=?""",
            (int(expire_ms), int(duration_days), float(traffic_gb),
             now, now, int(sid), int(key_id)))
        await db.commit()
        row = await _fetch(db, key_id, sid)
    return {"ok": True, "service": payload(row), "charged": int(price), "balance": bal}


async def update_service(key_id: int, sid: int, **fields) -> Dict:
    allowed = {"name", "is_active", "first_use_at"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return {"ok": False, "error": "nothing_to_update"}
    async with aiosqlite.connect(DB_PATH) as db:
        row = await _fetch(db, key_id, sid)
        if not row:
            return {"ok": False, "error": "service_not_found"}
        clause = ", ".join(f"{k}=?" for k in sets)
        await db.execute(f"UPDATE rep_sandbox_services SET {clause} WHERE id=? AND key_id=?",
                         (*sets.values(), int(sid), int(key_id)))
        await db.commit()
        row = await _fetch(db, key_id, sid)
    return {"ok": True, "service": payload(row)}


async def revoke_service(key_id: int, sid: int) -> Dict:
    """New link, same service — the production behaviour for a shared link."""
    async with aiosqlite.connect(DB_PATH) as db:
        row = await _fetch(db, key_id, sid)
        if not row:
            return {"ok": False, "error": "service_not_found"}
        token = secrets.token_urlsafe(16)
        await db.execute("UPDATE rep_sandbox_services SET token=? WHERE id=? AND key_id=?",
                         (token, int(sid), int(key_id)))
        await db.commit()
        row = await _fetch(db, key_id, sid)
    return {"ok": True, "service": payload(row)}


async def delete_service(key_id: int, sid: int) -> Dict:
    async with aiosqlite.connect(DB_PATH) as db:
        row = await _fetch(db, key_id, sid)
        if not row:
            return {"ok": False, "error": "service_not_found"}
        await db.execute("UPDATE rep_sandbox_services SET deleted=1 WHERE id=? AND key_id=?",
                         (int(sid), int(key_id)))
        await db.commit()
    return {"ok": True, "deleted": int(sid)}


async def orders(key_id: int, limit: int = 50) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM rep_sandbox_orders WHERE key_id=? ORDER BY id DESC LIMIT ?",
            (int(key_id), max(1, min(500, int(limit))))
        ) as c:
            return [dict(r) for r in await c.fetchall()]


def connections(service_id: int) -> Dict:
    """A plausible live-connection reading, without touching a panel.

    Derived from the service id and the clock so it is stable for a minute and
    then moves — enough to build a UI against, and it never claims to be real:
    `sandbox` is set on the object.
    """
    now = int(time.time())
    seed = (int(service_id) * 2654435761 + now // 60) % 97
    count = seed % 4
    places = [{
        "ip": f"5.{100 + (seed + i) % 60}.{(seed * (i + 3)) % 200}.···",
        "last_seen": now - (i * 7) % 40,
        "seconds_ago": (i * 7) % 40,
        "server": ["سرور ترکیه ۱", "سرور هلند ۱", "سرور آلمان ۲"][i % 3],
    } for i in range(count)]
    return {"ok": True, "service_id": int(service_id), "connections": count,
            "limit": 5, "over_limit": False, "places": places,
            "checked_at": now, "partial": False,
            "servers_answered": 3, "servers_total": 3, "sandbox": True}


async def reset(key_id: int) -> Dict:
    """Wipe this key's scratch data and hand back a full wallet."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM rep_sandbox_services WHERE key_id=?", (int(key_id),))
        await db.execute("DELETE FROM rep_sandbox_orders WHERE key_id=?", (int(key_id),))
        await db.execute("DELETE FROM rep_sandbox_wallet WHERE key_id=?", (int(key_id),))
        bal = await _wallet_row(db, key_id)
        await db.commit()
    return {"ok": True, "balance": bal, "services": 0, "sandbox": True}
