"""Install analytics and push messaging for the Atlas Android client.

SECURITY MODEL — this module breaks a rule that ``core/client_app.py`` states,
so read this before touching it.

``client_app`` says the ``/client/v1`` endpoints are **read-only**. This module
adds the first endpoint that *writes*, and that difference is the whole reason
this file exists separately rather than being bolted onto that one. Everything
below is shaped around one question: what can an anonymous attacker do to the
database by calling an endpoint whose URL is printed inside every APK?

The answers, and what they cost:

1. **Insert junk rows.** Mitigated three ways: the install id must be a
   syntactically valid UUID (a random string is rejected before it reaches
   SQLite), every text field is truncated to a hard cap, and [MAX_INSTALLS]
   stops new rows entirely once the table reaches a size the owner would
   notice. Existing rows keep updating past that point, so a flood degrades
   analytics rather than breaking the app for real users.

2. **Read other users' data.** There is nothing to read. The response carries
   only push messages the owner explicitly published — the same broadcast every
   install receives. No counts, no other installs, no subscription data. An
   attacker who calls this a million times learns what a customer learns.

3. **Correlate a person to their traffic.** The single most important rule
   here: **no IP address is ever stored, and neither is anything the phone did
   not volunteer about itself.** This is a VPN used in Iran. An install id is a
   random UUID the app generates for itself — not ANDROID_ID, not the IMEI, not
   an advertising id — so it cannot be joined to any other dataset, and it dies
   when the user clears app data. Device model and Android version are kept
   because the owner needs them to decide what to support; nothing here can
   place a person, and nothing here can be tied to a Telegram account or an
   order.

Uninstalls, honestly
--------------------
There is no uninstall signal for a sideloaded APK — Play Console can report one
because Google owns the install, and Telegram does not. What this module offers
instead is silence: an install that has not phoned home in 30 days is reported
as *dormant*, which covers "uninstalled", "phone in a drawer" and "app disabled
by a battery optimiser" without pretending to tell them apart. The panel is
worded to match; do not relabel it as an uninstall count.
"""
from __future__ import annotations

import re
import time
from typing import Dict, List, Optional

import aiosqlite

from core.config import DB_PATH

# ── Limits ────────────────────────────────────────────────────────────────────
# Above this the table stops accepting *new* install ids. Chosen to be far above
# any plausible real customer base and far below a size that would trouble
# SQLite or the VPS disk, so crossing it is a signal that something is wrong.
MAX_INSTALLS = 2_000_000

_MAX_TEXT = 64
_MAX_NOTES = 400

# A permissive UUID shape: any 8-4-4-4-12 hex string. Deliberately not strict
# about the version nibble — the point is to reject arbitrary attacker-chosen
# strings and cap the key space, not to police UUID versions.
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                      r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

DAY = 86_400


def valid_install_id(value) -> bool:
    return bool(_UUID_RE.match(str(value or "").strip()))


def _text(value, limit: int = _MAX_TEXT) -> str:
    return str(value or "").strip()[:limit]


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ── Schema ────────────────────────────────────────────────────────────────────
# Kept here rather than in database.SCHEMA so the analytics feature is one file
# to read, one file to remove. init_db() calls ensure_schema() below.
SCHEMA = """
CREATE TABLE IF NOT EXISTS app_installs (
    install_id      TEXT PRIMARY KEY,
    first_seen      INTEGER NOT NULL,
    last_seen       INTEGER NOT NULL,
    ping_count      INTEGER DEFAULT 1,
    version_code    INTEGER DEFAULT 0,
    version_name    TEXT DEFAULT '',
    sdk_int         INTEGER DEFAULT 0,
    android_release TEXT DEFAULT '',
    manufacturer    TEXT DEFAULT '',
    model           TEXT DEFAULT '',
    abi             TEXT DEFAULT '',
    language        TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_app_installs_last_seen  ON app_installs(last_seen);
CREATE INDEX IF NOT EXISTS idx_app_installs_first_seen ON app_installs(first_seen);

CREATE TABLE IF NOT EXISTS app_push (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT NOT NULL,
    body             TEXT DEFAULT '',
    url              TEXT DEFAULT '',
    created_at       INTEGER NOT NULL,
    expires_at       INTEGER DEFAULT 0,
    active           INTEGER DEFAULT 1,
    min_version_code INTEGER DEFAULT 0,
    max_version_code INTEGER DEFAULT 0,
    min_sdk          INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS app_push_receipts (
    push_id      INTEGER NOT NULL,
    install_id   TEXT NOT NULL,
    delivered_at INTEGER DEFAULT 0,
    opened_at    INTEGER DEFAULT 0,
    PRIMARY KEY (push_id, install_id)
);

CREATE INDEX IF NOT EXISTS idx_app_receipts_push ON app_push_receipts(push_id);

CREATE TABLE IF NOT EXISTS app_diag (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    install_id   TEXT NOT NULL,
    at           INTEGER NOT NULL,
    received     INTEGER NOT NULL,
    kind         TEXT NOT NULL,
    server       TEXT DEFAULT '',
    transport    TEXT DEFAULT '',
    preset       TEXT DEFAULT '',
    net          TEXT DEFAULT '',
    carrier      TEXT DEFAULT '',
    model        TEXT DEFAULT '',
    version_code INTEGER DEFAULT 0,
    sdk_int      INTEGER DEFAULT 0,
    ok           INTEGER DEFAULT -1,
    ms           INTEGER DEFAULT -1,
    dur          INTEGER DEFAULT -1,
    down_bps     INTEGER DEFAULT -1,
    up_bps       INTEGER DEFAULT -1,
    bytes        INTEGER DEFAULT -1,
    stage        TEXT DEFAULT '',
    why          TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_app_diag_at     ON app_diag(at);
CREATE INDEX IF NOT EXISTS idx_app_diag_kind   ON app_diag(kind);
CREATE INDEX IF NOT EXISTS idx_app_diag_server ON app_diag(server);
"""


async def ensure_schema(db) -> None:
    """Create the analytics tables on an existing connection."""
    for stmt in SCHEMA.strip().split(";"):
        s = stmt.strip()
        if s:
            await db.execute(s)


# Payload key → (column, coercer). Anything not listed here cannot reach the
# database, so an unexpected field in a crafted request is inert rather than a
# column name the caller gets to choose.
_PING_FIELDS = (
    ("versionCode", "version_code", lambda v: max(0, _int(v))),
    ("versionName", "version_name", lambda v: _text(v, 32)),
    ("sdk", "sdk_int", lambda v: max(0, _int(v))),
    ("release", "android_release", lambda v: _text(v, 16)),
    ("manufacturer", "manufacturer", lambda v: _text(v, 40)),
    ("model", "model", lambda v: _text(v, 60)),
    ("abi", "abi", lambda v: _text(v, 20)),
    ("lang", "language", lambda v: _text(v, 8)),
)


# ── Client-facing ─────────────────────────────────────────────────────────────
async def record_ping(payload: Dict) -> Optional[Dict]:
    """Record one heartbeat and return the messages this install has not seen.

    Returns ``None`` when the payload is not usable, which the route turns into
    a 400. A malformed ping is never a reason to write anything.
    """
    install_id = str(payload.get("installId") or "").strip()
    if not valid_install_id(install_id):
        return None

    now = int(time.time())

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cur = await db.execute(
            "SELECT * FROM app_installs WHERE install_id=?", (install_id,)
        )
        known = await cur.fetchone()

        # Only columns the payload actually carries are written. Overwriting
        # everything unconditionally meant a lightweight ping — one that just
        # acknowledges a delivered message — silently blanked the device facts,
        # dropping that install into the "unknown" bucket of every breakdown and
        # out of every version-targeted push.
        updates = {}
        for key, column, coerce in _PING_FIELDS:
            if key in payload:
                updates[column] = coerce(payload.get(key))

        if known:
            # What the phone reports wins: someone who upgrades Android or
            # sideloads a newer APK should move between buckets rather than
            # linger in the one they were first seen in.
            if updates:
                assignments = ", ".join(f"{col}=?" for col in updates)
                await db.execute(
                    f"""UPDATE app_installs
                           SET last_seen=?, ping_count=ping_count+1, {assignments}
                         WHERE install_id=?""",
                    (now, *updates.values(), install_id),
                )
            else:
                await db.execute(
                    """UPDATE app_installs SET last_seen=?, ping_count=ping_count+1
                        WHERE install_id=?""",
                    (now, install_id),
                )
            version_code = int(updates.get("version_code", known["version_code"]) or 0)
            sdk_int = int(updates.get("sdk_int", known["sdk_int"]) or 0)
        else:
            version_code = int(updates.get("version_code", 0) or 0)
            sdk_int = int(updates.get("sdk_int", 0) or 0)

            cur = await db.execute("SELECT COUNT(*) AS n FROM app_installs")
            total = (await cur.fetchone())["n"]
            if total >= MAX_INSTALLS:
                # Refuse the new row but still serve messages, so a flood
                # degrades the owner's analytics without breaking the product
                # for anyone already installed.
                return {"messages": await _pending(db, install_id, version_code, sdk_int)}

            columns = ["install_id", "first_seen", "last_seen", "ping_count", *updates]
            placeholders = ",".join("?" * len(columns))
            await db.execute(
                f"INSERT INTO app_installs ({','.join(columns)}) VALUES ({placeholders})",
                (install_id, now, now, 1, *updates.values()),
            )

        await _record_receipts(db, install_id, payload, now)
        messages = await _pending(db, install_id, version_code, sdk_int)
        await db.commit()

    return {"messages": messages}


async def _record_receipts(db, install_id: str, payload: Dict, now: int) -> None:
    """Fold in the delivery/open acknowledgements the app piggybacked."""
    delivered = payload.get("delivered")
    opened = payload.get("opened")

    for raw in (delivered if isinstance(delivered, list) else [])[:50]:
        push_id = _int(raw, -1)
        if push_id < 0:
            continue
        await db.execute(
            """INSERT INTO app_push_receipts (push_id, install_id, delivered_at)
               VALUES (?,?,?)
               ON CONFLICT(push_id, install_id)
               DO UPDATE SET delivered_at=COALESCE(NULLIF(delivered_at,0), ?)""",
            (push_id, install_id, now, now),
        )

    for raw in (opened if isinstance(opened, list) else [])[:50]:
        push_id = _int(raw, -1)
        if push_id < 0:
            continue
        # A tap implies delivery, so the row is created either way — an app that
        # is killed before it can report delivery still counts correctly.
        await db.execute(
            """INSERT INTO app_push_receipts (push_id, install_id, delivered_at, opened_at)
               VALUES (?,?,?,?)
               ON CONFLICT(push_id, install_id)
               DO UPDATE SET delivered_at=COALESCE(NULLIF(delivered_at,0), ?),
                             opened_at=COALESCE(NULLIF(opened_at,0), ?)""",
            (push_id, install_id, now, now, now, now),
        )


async def _pending(db, install_id: str, version_code: int, sdk_int: int) -> List[Dict]:
    """Live messages this install matches and has not already been handed."""
    now = int(time.time())
    cur = await db.execute(
        """SELECT p.id, p.title, p.body, p.url
             FROM app_push p
             LEFT JOIN app_push_receipts r
                    ON r.push_id = p.id AND r.install_id = ?
            WHERE p.active = 1
              AND (p.expires_at = 0 OR p.expires_at > ?)
              AND (p.min_version_code = 0 OR ? >= p.min_version_code)
              AND (p.max_version_code = 0 OR ? <= p.max_version_code)
              AND (p.min_sdk = 0 OR ? >= p.min_sdk)
              AND r.delivered_at IS NULL
            ORDER BY p.id ASC
            LIMIT 5""",
        (install_id, now, version_code, version_code, sdk_int),
    )
    return [
        {"id": r["id"], "title": r["title"], "body": r["body"], "url": r["url"]}
        for r in await cur.fetchall()
    ]


# -- Diagnostics ---------------------------------------------------------------
# Retained for a fixed window and then deleted. Nothing here identifies a person
# -- see the client's Diagnostics module for exactly what is and is not sent --
# but a dataset that is never pruned is one that eventually gets copied somewhere
# it should not be, so it expires on its own rather than on a promise.
DIAG_RETENTION_DAYS = 30
MAX_EVENTS_PER_BATCH = 200

_DIAG_KINDS = ("connect", "probe", "connected", "failed", "session")


async def record_diag(payload: Dict) -> Optional[int]:
    """Stores one uploaded batch. Returns how many events were kept."""
    install_id = str(payload.get("installId") or "").strip()
    if not valid_install_id(install_id):
        return None

    events = payload.get("events")
    if not isinstance(events, list) or not events:
        return 0

    now = int(time.time())
    # Batch-level carrier is a fallback only. It is recorded per event now,
    # because one batch can span a Wi-Fi session and a mobile one and a single
    # value for both would file the Wi-Fi results under an operator.
    batch_carrier = _text(payload.get("carrier"), 40)
    model = _text(payload.get("model"), 60)
    version_code = max(0, _int(payload.get("versionCode")))
    sdk_int = max(0, _int(payload.get("sdk")))

    rows = []
    for raw in events[:MAX_EVENTS_PER_BATCH]:
        if not isinstance(raw, dict):
            continue
        kind = _text(raw.get("kind"), 16)
        # An unrecognised kind is dropped rather than stored: the columns only
        # mean anything for the shapes the client actually sends, and accepting
        # arbitrary strings would let a crafted upload invent categories that
        # then appear in every breakdown.
        if kind not in _DIAG_KINDS:
            continue
        ok = raw.get("ok")
        rows.append((
            install_id,
            max(0, _int(raw.get("at"), now)),
            now,
            kind,
            _text(raw.get("server"), 40),
            _text(raw.get("transport"), 24),
            _text(raw.get("preset"), 24),
            _text(raw.get("net"), 12),
            _text(raw.get("carrier"), 40) or batch_carrier,
            model,
            version_code,
            sdk_int,
            1 if ok is True else (0 if ok is False else -1),
            _int(raw.get("ms"), -1),
            _int(raw.get("dur"), -1),
            _int(raw.get("down"), -1),
            _int(raw.get("up"), -1),
            _int(raw.get("bytes"), -1),
            _text(raw.get("stage"), 24),
            # Already redacted on the device. Truncated again here, on the
            # principle that the server does not trust the client's limits.
            _text(raw.get("why"), 140),
        ))

    if not rows:
        return 0

    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            "INSERT INTO app_diag "
            "(install_id, at, received, kind, server, transport, preset, net, "
            " carrier, model, version_code, sdk_int, ok, ms, dur, "
            " down_bps, up_bps, bytes, stage, why) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        await db.execute(
            "DELETE FROM app_diag WHERE received < ?",
            (now - DIAG_RETENTION_DAYS * DAY,),
        )
        await db.commit()

    return len(rows)


async def diag_export(days: int = 7, limit: int = 100000) -> List[Dict]:
    """Every stored event in a window, newest first -- the downloadable file."""
    since = int(time.time()) - max(1, min(DIAG_RETENTION_DAYS, days)) * DAY
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM app_diag WHERE at >= ? ORDER BY at DESC LIMIT ?",
            (since, max(1, min(500000, limit))),
        )
        return [dict(r) for r in await cur.fetchall()]


async def diag_summary(days: int = 7) -> Dict:
    """The rollups worth reading before downloading anything.

    Every figure is an answer to a question the owner actually has: which server
    fails most, which carrier struggles, whether a preset connects slower, and
    what the failures say. The raw export covers everything else.
    """
    since = int(time.time()) - max(1, min(DIAG_RETENTION_DAYS, days)) * DAY

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async def rows(sql, args=()):
            cur = await db.execute(sql, args)
            return [dict(r) for r in await cur.fetchall()]

        cur = await db.execute(
            "SELECT COUNT(*) n, COUNT(DISTINCT install_id) d FROM app_diag WHERE at >= ?",
            (since,),
        )
        head = await cur.fetchone()

        servers = await rows(
            "SELECT server AS key, "
            " SUM(kind='probe' AND ok=1) AS reachable, "
            " SUM(kind='probe' AND ok=0) AS unreachable, "
            " CAST(AVG(CASE WHEN kind='probe' AND ok=1 AND ms>=0 THEN ms END) AS INT) AS avg_ms, "
            " SUM(kind='connected') AS connects, "
            " SUM(kind='failed') AS failures "
            "FROM app_diag WHERE at >= ? AND server != '' "
            "GROUP BY server ORDER BY (reachable + connects) DESC LIMIT 40",
            (since,),
        )

        carriers = await rows(
            "SELECT carrier AS key, COUNT(DISTINCT install_id) AS installs, "
            " SUM(kind='probe' AND ok=1) AS reachable, "
            " SUM(kind='probe' AND ok=0) AS unreachable, "
            " CAST(AVG(CASE WHEN kind='probe' AND ok=1 AND ms>=0 THEN ms END) AS INT) AS avg_ms "
            "FROM app_diag WHERE at >= ? AND carrier != '' "
            "GROUP BY carrier ORDER BY installs DESC LIMIT 20",
            (since,),
        )

        transports = await rows(
            "SELECT transport AS key, "
            " SUM(kind='probe' AND ok=1) AS reachable, "
            " SUM(kind='probe' AND ok=0) AS unreachable, "
            " CAST(AVG(CASE WHEN kind='probe' AND ok=1 AND ms>=0 THEN ms END) AS INT) AS avg_ms "
            "FROM app_diag WHERE at >= ? AND transport != '' "
            "GROUP BY transport ORDER BY (reachable + unreachable) DESC LIMIT 20",
            (since,),
        )

        presets = await rows(
            "SELECT preset AS key, "
            " SUM(kind='connected') AS connects, "
            " SUM(kind='failed') AS failures, "
            " CAST(AVG(CASE WHEN kind='connected' AND dur>=0 THEN dur END) AS INT) AS avg_connect_ms, "
            " CAST(AVG(CASE WHEN kind='session' AND down_bps>=0 THEN down_bps END) AS INT) AS avg_peak_down "
            "FROM app_diag WHERE at >= ? AND preset != '' "
            "GROUP BY preset ORDER BY connects DESC LIMIT 20",
            (since,),
        )

        reasons = await rows(
            "SELECT why AS key, COUNT(*) AS count FROM app_diag "
            "WHERE at >= ? AND why != '' GROUP BY why ORDER BY count DESC LIMIT 30",
            (since,),
        )

        networks = await rows(
            "SELECT net AS key, COUNT(*) AS count, SUM(kind='failed') AS failures "
            "FROM app_diag WHERE at >= ? AND net != '' "
            "GROUP BY net ORDER BY count DESC LIMIT 10",
            (since,),
        )

    return {
        "days": days,
        "events": int(head["n"] or 0),
        "devices": int(head["d"] or 0),
        "servers": servers,
        "carriers": carriers,
        "transports": transports,
        "presets": presets,
        "reasons": reasons,
        "networks": networks,
        "retentionDays": DIAG_RETENTION_DAYS,
    }


async def diag_purge() -> None:
    """Deletes every stored diagnostic event."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM app_diag")
        await db.commit()


# -- Admin-facing --------------------------------------------------------------
async def stats() -> Dict:
    """Everything the panel's analytics page shows, in one round trip."""
    now = int(time.time())

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async def scalar(sql: str, args=()) -> int:
            cur = await db.execute(sql, args)
            row = await cur.fetchone()
            return int(row[0] or 0)

        async def breakdown(sql: str, args=()) -> List[Dict]:
            cur = await db.execute(sql, args)
            return [{"key": r["k"], "count": int(r["n"])} for r in await cur.fetchall()]

        total = await scalar("SELECT COUNT(*) FROM app_installs")

        totals = {
            "total": total,
            "active_1d": await scalar(
                "SELECT COUNT(*) FROM app_installs WHERE last_seen >= ?", (now - DAY,)),
            "active_7d": await scalar(
                "SELECT COUNT(*) FROM app_installs WHERE last_seen >= ?", (now - 7 * DAY,)),
            "active_30d": await scalar(
                "SELECT COUNT(*) FROM app_installs WHERE last_seen >= ?", (now - 30 * DAY,)),
            # Not "uninstalled" — see the module docstring.
            "dormant_30d": await scalar(
                "SELECT COUNT(*) FROM app_installs WHERE last_seen < ?", (now - 30 * DAY,)),
            "new_1d": await scalar(
                "SELECT COUNT(*) FROM app_installs WHERE first_seen >= ?", (now - DAY,)),
            "new_7d": await scalar(
                "SELECT COUNT(*) FROM app_installs WHERE first_seen >= ?", (now - 7 * DAY,)),
            "new_30d": await scalar(
                "SELECT COUNT(*) FROM app_installs WHERE first_seen >= ?", (now - 30 * DAY,)),
        }

        versions = await breakdown(
            """SELECT CASE WHEN version_name='' THEN CAST(version_code AS TEXT)
                           ELSE version_name || ' (' || version_code || ')' END AS k,
                      COUNT(*) AS n
                 FROM app_installs GROUP BY version_code, version_name
                 ORDER BY n DESC LIMIT 20""")

        androids = await breakdown(
            """SELECT CASE WHEN android_release='' THEN 'SDK ' || sdk_int
                           ELSE 'Android ' || android_release || ' (SDK ' || sdk_int || ')' END AS k,
                      COUNT(*) AS n
                 FROM app_installs GROUP BY sdk_int, android_release
                 ORDER BY sdk_int DESC LIMIT 20""")

        brands = await breakdown(
            """SELECT CASE WHEN manufacturer='' THEN 'نامشخص' ELSE manufacturer END AS k,
                      COUNT(*) AS n
                 FROM app_installs GROUP BY manufacturer ORDER BY n DESC LIMIT 15""")

        models = await breakdown(
            """SELECT CASE WHEN model='' THEN 'نامشخص'
                           ELSE TRIM(manufacturer || ' ' || model) END AS k,
                      COUNT(*) AS n
                 FROM app_installs GROUP BY manufacturer, model ORDER BY n DESC LIMIT 25""")

        abis = await breakdown(
            """SELECT CASE WHEN abi='' THEN 'نامشخص' ELSE abi END AS k, COUNT(*) AS n
                 FROM app_installs GROUP BY abi ORDER BY n DESC LIMIT 10""")

        # New installs per day for the last 30 days, zero-filled so the chart
        # does not silently skip quiet days and imply a shorter history.
        cur = await db.execute(
            """SELECT DATE(first_seen,'unixepoch','localtime') AS d, COUNT(*) AS n
                 FROM app_installs WHERE first_seen >= ?
                GROUP BY d ORDER BY d ASC""",
            (now - 30 * DAY,))
        seen = {r["d"]: int(r["n"]) for r in await cur.fetchall()}
        daily = []
        for back in range(29, -1, -1):
            stamp = time.strftime("%Y-%m-%d", time.localtime(now - back * DAY))
            daily.append({"date": stamp, "count": seen.get(stamp, 0)})

    return {
        "totals": totals,
        "versions": versions,
        "androids": androids,
        "brands": brands,
        "models": models,
        "abis": abis,
        "daily": daily,
        "capacity": {"max": MAX_INSTALLS, "used": total},
    }


async def reset_stats() -> Dict:
    """Wipes install analytics and every push message. Irreversible.

    ## Why all three tables go together

    Delivery is remembered per (message, install) in app_push_receipts, and that
    record is the only thing stopping a message being handed to the same phone
    again. Clearing receipts while leaving messages live would re-deliver every
    active announcement to every device on their next heartbeat — a silent mass
    re-notification, which for a VPN is how an app gets uninstalled. So messages
    and receipts are cleared as one operation, never separately.

    ## What this does not do

    It does not reset anybody's phone. Each install keeps the random id it
    generated for itself, so devices reappear here as they check in — but with
    first_seen set to whenever that happens, so their real install dates are
    gone for good and the daily chart restarts from today. The panel says so
    before asking for confirmation.

    Push ids deliberately keep counting rather than restarting at 1. A phone
    that was shown message 3 and has not yet acknowledged it would otherwise
    acknowledge a *different* new message 3, marking it delivered to someone who
    never saw it.
    """
    tables = ("app_installs", "app_push", "app_push_receipts")
    removed = {}
    async with aiosqlite.connect(DB_PATH) as db:
        for table in tables:
            cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
            removed[table] = int((await cur.fetchone())[0] or 0)
        for table in tables:
            await db.execute(f"DELETE FROM {table}")
        await db.commit()
    return {
        "installs": removed["app_installs"],
        "messages": removed["app_push"],
        "receipts": removed["app_push_receipts"],
    }


async def list_push() -> List[Dict]:
    """Every message the owner has composed, newest first, with its counts."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT p.*,
                      (SELECT COUNT(*) FROM app_push_receipts r
                        WHERE r.push_id=p.id AND r.delivered_at>0) AS delivered,
                      (SELECT COUNT(*) FROM app_push_receipts r
                        WHERE r.push_id=p.id AND r.opened_at>0) AS opened
                 FROM app_push p ORDER BY p.id DESC LIMIT 100""")
        return [dict(r) for r in await cur.fetchall()]


async def create_push(data: Dict) -> Optional[Dict]:
    """Compose a message. Returns None when there is nothing worth sending."""
    title = _text(data.get("title"), 80)
    body = _text(data.get("body"), _MAX_NOTES)
    if not title:
        return None

    url = _text(data.get("url"), 300)
    # Same rule as the promo banner: this becomes a tap target inside the app,
    # so anything that is not plain https is dropped rather than stored.
    if url and not url.lower().startswith("https://"):
        url = ""

    days = max(0, _int(data.get("expiresDays"), 0))
    now = int(time.time())

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO app_push
                   (title, body, url, created_at, expires_at, active,
                    min_version_code, max_version_code, min_sdk)
               VALUES (?,?,?,?,?,1,?,?,?)""",
            (title, body, url, now, now + days * DAY if days else 0,
             max(0, _int(data.get("minVersionCode"))),
             max(0, _int(data.get("maxVersionCode"))),
             max(0, _int(data.get("minSdk")))),
        )
        await db.commit()
        new_id = cur.lastrowid

    return {"id": new_id}


async def set_push_active(push_id: int, active: bool) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE app_push SET active=? WHERE id=?",
                         (1 if active else 0, _int(push_id)))
        await db.commit()


async def delete_push(push_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM app_push WHERE id=?", (_int(push_id),))
        await db.execute("DELETE FROM app_push_receipts WHERE push_id=?", (_int(push_id),))
        await db.commit()


async def audience(data: Dict) -> int:
    """How many installs a set of filters would reach, for the compose form.

    Counts against the 30-day active window rather than every install ever
    seen: a message cannot reach a phone that stopped calling home, and showing
    the all-time number would promise a reach that does not exist.
    """
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """SELECT COUNT(*) FROM app_installs
                WHERE last_seen >= ?
                  AND (? = 0 OR version_code >= ?)
                  AND (? = 0 OR version_code <= ?)
                  AND (? = 0 OR sdk_int >= ?)""",
            (now - 30 * DAY,
             max(0, _int(data.get("minVersionCode"))), max(0, _int(data.get("minVersionCode"))),
             max(0, _int(data.get("maxVersionCode"))), max(0, _int(data.get("maxVersionCode"))),
             max(0, _int(data.get("minSdk"))), max(0, _int(data.get("minSdk")))),
        )
        return int((await cur.fetchone())[0] or 0)
