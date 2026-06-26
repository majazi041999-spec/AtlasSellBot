import aiosqlite
import secrets
import string
import time
from datetime import datetime, date
from typing import Optional, List, Dict
from core.config import DB_PATH
from core.jalali import jalali_date_key, jalali_display, tehran_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    username TEXT NOT NULL,
    password TEXT NOT NULL,
    api_token TEXT DEFAULT '',
    sub_path TEXT DEFAULT '',
    inbound_id INTEGER DEFAULT 1,
    inbound_ids TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1,
    note TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    full_name TEXT,
    is_admin INTEGER DEFAULT 0,
    is_blocked INTEGER DEFAULT 0,
    referral_code TEXT UNIQUE,
    referred_by INTEGER,
    referral_bonus_gb REAL DEFAULT 0,
    admin_role TEXT DEFAULT 'none',
    balance_toman INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    traffic_gb REAL NOT NULL,
    duration_days INTEGER NOT NULL,
    price INTEGER NOT NULL,
    description TEXT DEFAULT '',
    inbound_id INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    sort_order INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    package_id INTEGER NOT NULL,
    server_id INTEGER,
    status TEXT DEFAULT 'pending',
    receipt_file_id TEXT,
    config_uuid TEXT,
    config_email TEXT,
    inbound_id INTEGER,
    referral_bonus_applied INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    approved_at TEXT,
    notes TEXT,
    custom_config_name TEXT DEFAULT '',
    renew_config_id INTEGER DEFAULT 0,
    renew_sub_profile_id INTEGER DEFAULT 0,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(package_id) REFERENCES packages(id)
);

CREATE TABLE IF NOT EXISTS configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    server_id INTEGER NOT NULL,
    uuid TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    inbound_id INTEGER NOT NULL,
    traffic_gb REAL NOT NULL,
    duration_days INTEGER NOT NULL,
    expire_timestamp INTEGER DEFAULT 0,
    starts_on_first_use INTEGER DEFAULT 0,
    first_use_at TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1,
    migration_count INTEGER DEFAULT 0,
    last_migration_date TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(server_id) REFERENCES servers(id)
);


CREATE TABLE IF NOT EXISTS wallet_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    balance_after INTEGER DEFAULT 0,
    kind TEXT DEFAULT 'manual',
    note TEXT DEFAULT '',
    actor_telegram_id INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS topup_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    receipt_file_id TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    reviewer_telegram_id INTEGER DEFAULT 0,
    admin_note TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    reviewed_at TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS legacy_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    telegram_id INTEGER NOT NULL,
    config_link TEXT NOT NULL,
    config_key TEXT NOT NULL UNIQUE,
    email TEXT DEFAULT '',
    uuid TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    admin_note TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    reviewed_at TEXT,
    reviewer_id INTEGER DEFAULT 0,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS config_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id INTEGER NOT NULL,
    alert_type TEXT NOT NULL,
    threshold TEXT NOT NULL,
    sent_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(config_id, alert_type, threshold),
    FOREIGN KEY(config_id) REFERENCES configs(id)
);

CREATE TABLE IF NOT EXISTS review_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_type TEXT NOT NULL,
    tx_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(tx_type, tx_id, chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS test_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    config_id INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(config_id) REFERENCES configs(id)
);

CREATE TABLE IF NOT EXISTS daily_reports (
    jalali_date TEXT PRIMARY KEY,
    gregorian_date TEXT NOT NULL,
    jalali_display TEXT NOT NULL,
    sales_amount INTEGER DEFAULT 0,
    orders_approved INTEGER DEFAULT 0,
    renewals INTEGER DEFAULT 0,
    new_configs INTEGER DEFAULT 0,
    active_configs INTEGER DEFAULT 0,
    expired_configs INTEGER DEFAULT 0,
    new_users INTEGER DEFAULT 0,
    wallet_topups INTEGER DEFAULT 0,
    wallet_topup_amount INTEGER DEFAULT 0,
    pending_orders INTEGER DEFAULT 0,
    total_revenue INTEGER DEFAULT 0,
    total_approved_orders INTEGER DEFAULT 0,
    total_users INTEGER DEFAULT 0,
    total_configs INTEGER DEFAULT 0,
    sent_to_admins INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS subscription_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    order_id INTEGER DEFAULT 0,
    token TEXT UNIQUE NOT NULL,
    email TEXT NOT NULL,
    name TEXT DEFAULT '',
    traffic_gb REAL NOT NULL,
    duration_days INTEGER NOT NULL,
    expire_timestamp INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    used_bytes INTEGER DEFAULT 0,
    expired_at INTEGER DEFAULT 0,
    expiry_notified INTEGER DEFAULT 0,
    prewarn_sent INTEGER DEFAULT 0,
    starts_on_first_use INTEGER DEFAULT 0,
    first_use_at INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS subscription_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    server_id INTEGER NOT NULL,
    inbound_id INTEGER NOT NULL,
    uuid TEXT NOT NULL,
    email TEXT NOT NULL,
    link TEXT DEFAULT '',
    last_used_bytes INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY(profile_id) REFERENCES subscription_profiles(id),
    FOREIGN KEY(server_id) REFERENCES servers(id)
);

CREATE TABLE IF NOT EXISTS subscription_node_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id INTEGER NOT NULL,
    inbound_id INTEGER NOT NULL,
    label TEXT DEFAULT '',
    priority INTEGER DEFAULT 100,
    max_active_profiles INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(server_id, inbound_id),
    FOREIGN KEY(server_id) REFERENCES servers(id)
);

CREATE TABLE IF NOT EXISTS discount_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    kind TEXT DEFAULT 'percent',          -- 'percent' | 'fixed'
    value REAL DEFAULT 0,                 -- percent (0-100) or toman amount
    max_uses INTEGER DEFAULT 0,           -- 0 = unlimited (total)
    per_user_limit INTEGER DEFAULT 1,     -- 0 = unlimited per user
    used_count INTEGER DEFAULT 0,
    min_amount INTEGER DEFAULT 0,         -- min order price to qualify
    package_id INTEGER DEFAULT 0,         -- 0 = all packages
    expires_at INTEGER DEFAULT 0,         -- epoch ms, 0 = never
    is_active INTEGER DEFAULT 1,
    note TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS discount_redemptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    order_id INTEGER DEFAULT 0,
    amount INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY(code_id) REFERENCES discount_codes(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS referral_tiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrals_needed INTEGER NOT NULL,
    reward_kind TEXT DEFAULT 'gb',        -- 'gb' | 'service'
    reward_gb REAL DEFAULT 0,             -- for 'gb', or service traffic for 'service'
    duration_days INTEGER DEFAULT 0,      -- for 'service'
    is_unlimited INTEGER DEFAULT 0,       -- service with unlimited volume
    label TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1,
    sort_order INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS referral_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    tier_id INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',        -- 'pending' | 'approved' | 'rejected'
    referrals_at_claim INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    reviewed_at TEXT DEFAULT '',
    UNIQUE(user_id, tier_id),
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(tier_id) REFERENCES referral_tiers(id)
);

INSERT OR IGNORE INTO settings VALUES
    ('welcome_message','به Atlas Account خوش آمدید! 🌐\nبهترین سرویس VPN با سرعت بالا.'),
    ('support_username',''),
    ('maintenance_mode','0'),
    ('owner_admin_id','0');
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        for stmt in SCHEMA.strip().split(';'):
            s = stmt.strip()
            if s:
                await db.execute(s)
        await _ensure_columns(db)
        await db.execute("UPDATE orders SET status='receipt_submitted', approved_at=NULL WHERE status='processing'")
        await db.commit()




async def _ensure_columns(db):
    migrations = {
        "servers": [
            ("max_active_configs", "INTEGER DEFAULT 0"),
            ("inbound_ids", "TEXT DEFAULT ''"),
            ("api_token", "TEXT DEFAULT ''"),
        ],
        "users": [
            ("discount_percent", "REAL DEFAULT 0"),
            ("price_per_gb", "INTEGER DEFAULT 0"),
            ("is_wholesale", "INTEGER DEFAULT 0"),
            ("wholesale_request_pending", "INTEGER DEFAULT 0"),
            ("admin_role", "TEXT DEFAULT 'none'"),
            ("balance_toman", "INTEGER DEFAULT 0"),
        ],
        "configs": [
            ("starts_on_first_use", "INTEGER DEFAULT 0"),
            ("first_use_at", "TEXT DEFAULT ''"),
        ],
        "packages": [
            ("inbound_id", "INTEGER DEFAULT 0"),
        ],
        "orders": [
            ("custom_name", "TEXT DEFAULT ''"),
            ("custom_traffic_gb", "REAL DEFAULT 0"),
            ("custom_duration_days", "INTEGER DEFAULT 0"),
            ("custom_price", "INTEGER DEFAULT 0"),
            ("bulk_count", "INTEGER DEFAULT 1"),
            ("bulk_each_gb", "REAL DEFAULT 0"),
            ("custom_config_name", "TEXT DEFAULT ''"),
            ("renew_config_id", "INTEGER DEFAULT 0"),
            ("renew_sub_profile_id", "INTEGER DEFAULT 0"),
            ("referral_bonus_applied", "INTEGER DEFAULT 0"),
            ("discount_code", "TEXT DEFAULT ''"),
            ("discount_amount", "INTEGER DEFAULT 0"),
        ],
        "daily_reports": [
            ("renewals", "INTEGER DEFAULT 0"),
            ("sent_to_admins", "INTEGER DEFAULT 0"),
            ("total_revenue", "INTEGER DEFAULT 0"),
            ("total_approved_orders", "INTEGER DEFAULT 0"),
            ("total_users", "INTEGER DEFAULT 0"),
            ("total_configs", "INTEGER DEFAULT 0"),
        ],
        "subscription_profiles": [
            ("order_id", "INTEGER DEFAULT 0"),
            ("used_bytes", "INTEGER DEFAULT 0"),
            ("updated_at", "TEXT DEFAULT ''"),
            ("expired_at", "INTEGER DEFAULT 0"),
            ("expiry_notified", "INTEGER DEFAULT 0"),
            ("name", "TEXT DEFAULT ''"),
            ("starts_on_first_use", "INTEGER DEFAULT 0"),
            ("first_use_at", "INTEGER DEFAULT 0"),
            ("prewarn_sent", "INTEGER DEFAULT 0"),
        ],
        "subscription_node_configs": [
            ("label", "TEXT DEFAULT ''"),
            ("priority", "INTEGER DEFAULT 100"),
            ("max_active_profiles", "INTEGER DEFAULT 0"),
            ("is_active", "INTEGER DEFAULT 1"),
        ],
        "test_accounts": [
            ("profile_id", "INTEGER DEFAULT 0"),
        ],
    }
    for table, cols in migrations.items():
        async with db.execute(f"PRAGMA table_info({table})") as c:
            existing = {r[1] for r in await c.fetchall()}
        for col, ddl in cols:
            if col not in existing:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

def _gen_referral_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(8))


# ══════════════════ SERVERS ══════════════════

async def get_servers(active_only=True) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        q = "SELECT * FROM servers" + (" WHERE is_active=1" if active_only else "") + " ORDER BY id"
        async with db.execute(q) as c:
            return [dict(r) for r in await c.fetchall()]

async def get_server(sid: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM servers WHERE id=?", (sid,)) as c:
            r = await c.fetchone()
            return dict(r) if r else None

async def add_server(name, url, username, password, sub_path, inbound_id, note='', inbound_ids: str = "", api_token: str = "") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            "INSERT INTO servers(name,url,username,password,api_token,sub_path,inbound_id,note,inbound_ids) VALUES(?,?,?,?,?,?,?,?,?)",
            (name, url, username, password, api_token, sub_path, inbound_id, note, inbound_ids)
        )
        await db.commit()
        return c.lastrowid

async def update_server(sid: int, **kw):
    fields = ','.join(f"{k}=?" for k in kw)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE servers SET {fields} WHERE id=?", (*kw.values(), sid))
        await db.commit()

async def delete_server(sid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM servers WHERE id=?", (sid,))
        await db.commit()




async def count_active_configs_by_server(server_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM configs WHERE server_id=? AND is_active=1", (server_id,)) as c:
            return (await c.fetchone())[0]


async def count_active_subscription_nodes_by_server(server_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT COUNT(*)
               FROM subscription_nodes n
               JOIN subscription_profiles p ON p.id=n.profile_id
               WHERE n.server_id=? AND n.is_active=1 AND p.is_active=1""",
            (int(server_id),),
        ) as c:
            return int((await c.fetchone())[0] or 0)


async def count_active_subscription_nodes_by_target(server_id: int, inbound_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT COUNT(*)
               FROM subscription_nodes n
               JOIN subscription_profiles p ON p.id=n.profile_id
               WHERE n.server_id=? AND n.inbound_id=? AND n.is_active=1 AND p.is_active=1""",
            (int(server_id), int(inbound_id)),
        ) as c:
            return int((await c.fetchone())[0] or 0)


async def count_active_server_load(server_id: int) -> int:
    return await count_active_configs_by_server(server_id) + await count_active_subscription_nodes_by_server(server_id)


async def server_has_capacity(server_id: int) -> bool:
    srv = await get_server(server_id)
    if not srv:
        return False
    cap = int(srv.get("max_active_configs") or 0)
    if cap <= 0:
        return True
    return (await count_active_server_load(server_id)) < cap


async def get_available_servers() -> List[Dict]:
    servers = await get_servers(active_only=True)
    out = []
    for s in servers:
        if await server_has_capacity(s["id"]):
            out.append(s)
    return out


async def get_subscription_node_configs(active_only: bool = True) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        where = ""
        if active_only:
            where = "WHERE nc.is_active=1 AND s.is_active=1"
        async with db.execute(
            f"""SELECT nc.*, s.name AS server_name, s.url AS server_url, s.username AS srv_user,
                       s.password AS srv_pass, s.api_token AS srv_api_token, s.sub_path,
                       s.is_active AS server_active, s.max_active_configs
                FROM subscription_node_configs nc
                JOIN servers s ON s.id=nc.server_id
                {where}
                ORDER BY nc.priority ASC, nc.id ASC"""
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_subscription_node_config(node_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT nc.*, s.name AS server_name, s.url AS server_url, s.username AS srv_user,
                      s.password AS srv_pass, s.api_token AS srv_api_token, s.sub_path,
                      s.is_active AS server_active, s.max_active_configs
               FROM subscription_node_configs nc
               JOIN servers s ON s.id=nc.server_id
               WHERE nc.id=?""",
            (int(node_id),),
        ) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def add_subscription_node_config(server_id: int, inbound_id: int, label: str = "",
                                       priority: int = 100, max_active_profiles: int = 0) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM subscription_node_configs WHERE server_id=? AND inbound_id=?",
            (int(server_id), int(inbound_id)),
        ) as c:
            existing = await c.fetchone()
        if existing:
            await db.execute(
                """UPDATE subscription_node_configs
                   SET label=?, priority=?, max_active_profiles=?, is_active=1
                   WHERE id=?""",
                (label or "", int(priority or 100), int(max_active_profiles or 0), int(existing[0])),
            )
            await db.commit()
            return int(existing[0])
        cur = await db.execute(
            """INSERT INTO subscription_node_configs(server_id,inbound_id,label,priority,max_active_profiles)
               VALUES(?,?,?,?,?)""",
            (int(server_id), int(inbound_id), label or "", int(priority or 100), int(max_active_profiles or 0)),
        )
        await db.commit()
        return int(cur.lastrowid)


async def update_subscription_node_config(node_id: int, **kw):
    if not kw:
        return
    fields = ",".join(f"{k}=?" for k in kw)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE subscription_node_configs SET {fields} WHERE id=?", (*kw.values(), int(node_id)))
        await db.commit()


async def delete_subscription_node_config(node_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM subscription_node_configs WHERE id=?", (int(node_id),))
        await db.commit()


async def subscription_node_config_has_capacity(node: Dict) -> bool:
    if not node or not int(node.get("is_active") or 0) or not int(node.get("server_active") or 0):
        return False
    cap = int(node.get("max_active_profiles") or 0)
    if cap <= 0:
        return True
    used = await count_active_subscription_nodes_by_target(int(node["server_id"]), int(node["inbound_id"]))
    return used < cap


async def subscription_node_config_status(node: Dict) -> Dict:
    if not node:
        return {"usable": False, "reason": "not_found", "label": "نود پیدا نشد"}
    if not int(node.get("is_active") or 0):
        return {"usable": False, "reason": "node_disabled", "label": "خود نود غیرفعال است"}
    if not int(node.get("server_active") or 0):
        return {"usable": False, "reason": "server_disabled", "label": "سرور این نود غیرفعال است"}

    used = await count_active_subscription_nodes_by_target(int(node["server_id"]), int(node["inbound_id"]))
    cap = int(node.get("max_active_profiles") or 0)
    if cap > 0 and used >= cap:
        return {"usable": False, "reason": "node_capacity_full", "label": f"ظرفیت نود پر است ({used}/{cap})"}
    return {"usable": True, "reason": "ok", "label": "قابل استفاده"}


async def get_available_subscription_node_configs() -> List[Dict]:
    out = []
    for node in await get_subscription_node_configs(active_only=True):
        status = await subscription_node_config_status(node)
        if status["usable"]:
            out.append(node)
    return out


async def get_least_loaded_server(exclude_ids: Optional[List[int]] = None) -> Optional[Dict]:
    excluded = {int(x) for x in (exclude_ids or [])}
    candidates = []
    for server in await get_available_servers():
        sid = int(server["id"])
        if sid in excluded:
            continue
        used = await count_active_configs_by_server(sid)
        cap = int(server.get("max_active_configs") or 0)
        ratio = (used / cap) if cap > 0 else 0
        item = dict(server)
        item["active_configs"] = used
        item["load_ratio"] = ratio
        candidates.append(item)
    if not candidates:
        return None
    return sorted(candidates, key=lambda s: (int(s.get("active_configs") or 0), float(s.get("load_ratio") or 0), int(s["id"])))[0]
# ══════════════════ USERS ══════════════════

async def get_or_create_user(telegram_id: int, username=None, full_name=None) -> Dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)) as c:
            row = await c.fetchone()
        if row:
            await db.execute(
                "UPDATE users SET username=COALESCE(?, username), full_name=COALESCE(?, full_name) WHERE telegram_id=?",
                (username, full_name, telegram_id)
            )
            await db.commit()
            async with db.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)) as c2:
                return dict(await c2.fetchone())
        code = _gen_referral_code()
        await db.execute(
            "INSERT INTO users(telegram_id,username,full_name,referral_code) VALUES(?,?,?,?)",
            (telegram_id, username, full_name, code)
        )
        await db.commit()
        async with db.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)) as c:
            return dict(await c.fetchone())

async def get_user_by_telegram(telegram_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)) as c:
            r = await c.fetchone()
            return dict(r) if r else None

async def get_user_by_id(uid: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE id=?", (uid,)) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def find_user(query: str) -> Optional[Dict]:
    q = (query or "").strip().lstrip("@")
    if not q:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if q.isdigit():
            async with db.execute("SELECT * FROM users WHERE id=? OR telegram_id=? LIMIT 1", (int(q), int(q))) as c:
                r = await c.fetchone()
                return dict(r) if r else None
        async with db.execute(
            "SELECT * FROM users WHERE lower(username)=lower(?) OR full_name LIKE ? ORDER BY id DESC LIMIT 1",
            (q, f"%{q}%"),
        ) as c:
            r = await c.fetchone()
            return dict(r) if r else None

async def search_users(query: str, limit: int = 20) -> List[Dict]:
    q = (query or "").strip().lstrip("@")
    if not q:
        return []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if q.isdigit():
            async with db.execute(
                "SELECT * FROM users WHERE id=? OR telegram_id=? ORDER BY id DESC LIMIT ?",
                (int(q), int(q), limit),
            ) as c:
                return [dict(r) for r in await c.fetchall()]
        async with db.execute(
            "SELECT * FROM users WHERE lower(username) LIKE lower(?) OR full_name LIKE ? ORDER BY created_at DESC LIMIT ?",
            (f"%{q}%", f"%{q}%", limit),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_user_by_referral_code(code: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE referral_code=?", (code,)) as c:
            r = await c.fetchone()
            return dict(r) if r else None

async def update_user(uid: int, **kw):
    fields = ','.join(f"{k}=?" for k in kw)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {fields} WHERE id=?", (*kw.values(), uid))
        await db.commit()

async def get_all_users(offset=0, limit=50) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_user_business_stats(uid: int) -> Dict:
    async with aiosqlite.connect(DB_PATH) as db:
        stats = {"active_configs": 0, "total_configs": 0, "approved_orders": 0, "pending_orders": 0}
        async with db.execute("SELECT COUNT(*) FROM configs WHERE user_id=?", (uid,)) as c:
            stats["total_configs"] = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM configs WHERE user_id=? AND is_active=1", (uid,)) as c:
            stats["active_configs"] = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND status='approved'", (uid,)) as c:
            stats["approved_orders"] = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND status='pending'", (uid,)) as c:
            stats["pending_orders"] = (await c.fetchone())[0]
        return stats


async def get_wholesale_users(limit: int = 200) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM users
               WHERE is_wholesale=1 OR wholesale_request_pending=1
               ORDER BY is_wholesale DESC, wholesale_request_pending DESC, created_at DESC
               LIMIT ?""",
            (max(1, int(limit or 200)),),
        ) as c:
            return [dict(r) for r in await c.fetchall()]



async def get_user_balance(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance_toman FROM users WHERE id=?", (user_id,)) as c:
            row = await c.fetchone()
            return int((row[0] if row else 0) or 0)


async def add_user_balance(user_id: int, amount: int, kind: str = "manual", note: str = "", actor_telegram_id: int = 0) -> int:
    amount = int(amount or 0)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance_toman FROM users WHERE id=?", (user_id,)) as c:
            row = await c.fetchone()
            cur = int((row[0] if row else 0) or 0)
        new_bal = cur + amount
        await db.execute("UPDATE users SET balance_toman=? WHERE id=?", (new_bal, user_id))
        await db.execute(
            "INSERT INTO wallet_transactions(user_id,amount,balance_after,kind,note,actor_telegram_id) VALUES(?,?,?,?,?,?)",
            (user_id, amount, new_bal, kind, note, actor_telegram_id),
        )
        await db.commit()
        return new_bal


async def create_topup_request(user_id: int, amount: int, receipt_file_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            "INSERT INTO topup_requests(user_id,amount,receipt_file_id,status) VALUES(?,?,?,'pending')",
            (user_id, int(amount), receipt_file_id),
        )
        await db.commit()
        return c.lastrowid


async def get_topup_request(rid: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT t.*, u.telegram_id, u.username, u.full_name FROM topup_requests t
               JOIN users u ON t.user_id=u.id WHERE t.id=?""",
            (rid,),
        ) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def get_pending_topup_requests(limit: int = 100) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT t.*, u.telegram_id, u.username, u.full_name FROM topup_requests t
               JOIN users u ON t.user_id=u.id WHERE t.status='pending' ORDER BY t.created_at DESC LIMIT ?""",
            (limit,),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def update_topup_request(rid: int, **kw):
    fields = ','.join(f"{k}=?" for k in kw)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE topup_requests SET {fields} WHERE id=?", (*kw.values(), rid))
        await db.commit()


async def add_review_message(tx_type: str, tx_id: int, chat_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR IGNORE INTO review_messages(tx_type,tx_id,chat_id,message_id)
               VALUES(?,?,?,?)""",
            (tx_type, int(tx_id), int(chat_id), int(message_id)),
        )
        await db.commit()


async def get_review_messages(tx_type: str, tx_id: int) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM review_messages WHERE tx_type=? AND tx_id=? ORDER BY id ASC",
            (tx_type, int(tx_id)),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_recent_receipt_transactions(limit: int = 100) -> List[Dict]:
    limit = max(1, int(limit or 100))
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        q = """
            SELECT * FROM (
                SELECT
                    'topup' AS tx_type,
                    t.id AS tx_id,
                    t.user_id AS user_id,
                    u.telegram_id AS telegram_id,
                    u.username AS username,
                    u.full_name AS full_name,
                    t.amount AS amount,
                    t.status AS status,
                    t.receipt_file_id AS receipt_file_id,
                    t.created_at AS created_at,
                    t.reviewed_at AS reviewed_at
                FROM topup_requests t
                JOIN users u ON u.id=t.user_id
                WHERE COALESCE(t.receipt_file_id,'') <> ''

                UNION ALL

                SELECT
                    'order' AS tx_type,
                    o.id AS tx_id,
                    o.user_id AS user_id,
                    u.telegram_id AS telegram_id,
                    u.username AS username,
                    u.full_name AS full_name,
                    COALESCE(o.custom_price, p.price, 0) AS amount,
                    o.status AS status,
                    o.receipt_file_id AS receipt_file_id,
                    o.created_at AS created_at,
                    o.approved_at AS reviewed_at
                FROM orders o
                JOIN users u ON u.id=o.user_id
                LEFT JOIN packages p ON p.id=o.package_id
                WHERE COALESCE(o.receipt_file_id,'') <> ''
            ) z
            ORDER BY created_at DESC
            LIMIT ?
        """
        async with db.execute(q, (limit,)) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_all_admin_telegram_ids() -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT telegram_id FROM users WHERE is_admin=1") as c:
            rows = await c.fetchall()
            out = []
            for r in rows:
                try:
                    tid = int(r[0])
                except Exception:
                    continue
                if tid not in out:
                    out.append(tid)
            return out

async def count_users() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            return (await c.fetchone())[0]

async def get_referral_stats(user_id: int) -> Dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE referred_by=?", (user_id,)
        ) as c:
            count = (await c.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM orders o JOIN users u ON o.user_id=u.id WHERE u.referred_by=? AND o.status='approved'",
            (user_id,)
        ) as c:
            purchases = (await c.fetchone())[0]
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT referral_bonus_gb FROM users WHERE id=?", (user_id,)) as c:
            r = await c.fetchone()
            bonus = r['referral_bonus_gb'] if r else 0
    return {'invited': count, 'converted': purchases, 'bonus_gb': bonus}


async def count_converted_referrals(user_id: int) -> int:
    """Distinct referred users who have made at least one approved purchase.

    This is the metric the milestone referral tiers reward (real paying
    referrals, not just sign-ups or repeat orders)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT COUNT(DISTINCT u.id)
               FROM users u JOIN orders o ON o.user_id=u.id
               WHERE u.referred_by=? AND o.status='approved'""",
            (int(user_id),),
        ) as c:
            return int((await c.fetchone())[0] or 0)


# ══════════════════ DISCOUNT CODES ══════════════════

async def get_discount_codes() -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM discount_codes ORDER BY is_active DESC, id DESC") as c:
            return [dict(r) for r in await c.fetchall()]


async def get_discount_code(cid: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM discount_codes WHERE id=?", (int(cid),)) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def get_discount_code_by_code(code: str) -> Optional[Dict]:
    raw = (code or "").strip()
    if not raw:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM discount_codes WHERE code=? COLLATE NOCASE", (raw,)) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def add_discount_code(code: str, kind: str, value: float, max_uses: int = 0,
                            per_user_limit: int = 1, min_amount: int = 0, package_id: int = 0,
                            expires_at: int = 0, note: str = "") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            """INSERT INTO discount_codes(code,kind,value,max_uses,per_user_limit,min_amount,package_id,expires_at,note)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            ((code or "").strip(), kind if kind in ("percent", "fixed") else "percent",
             float(value or 0), int(max_uses or 0), int(per_user_limit or 0),
             int(min_amount or 0), int(package_id or 0), int(expires_at or 0), (note or "").strip()),
        )
        await db.commit()
        return int(c.lastrowid)


async def update_discount_code(cid: int, **kw):
    if not kw:
        return
    fields = ",".join(f"{k}=?" for k in kw)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE discount_codes SET {fields} WHERE id=?", (*kw.values(), int(cid)))
        await db.commit()


async def delete_discount_code(cid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM discount_codes WHERE id=?", (int(cid),))
        await db.commit()


async def count_user_code_redemptions(code_id: int, user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM discount_redemptions WHERE code_id=? AND user_id=?",
            (int(code_id), int(user_id)),
        ) as c:
            return int((await c.fetchone())[0] or 0)


async def record_discount_redemption(code_id: int, user_id: int, order_id: int, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO discount_redemptions(code_id,user_id,order_id,amount) VALUES(?,?,?,?)",
            (int(code_id), int(user_id), int(order_id or 0), int(amount or 0)),
        )
        await db.execute("UPDATE discount_codes SET used_count=used_count+1 WHERE id=?", (int(code_id),))
        await db.commit()


def discount_amount_for(code: Dict, amount: int) -> int:
    """Toman discount a code grants on an order of `amount` toman."""
    amount = int(amount or 0)
    if amount <= 0:
        return 0
    if str(code.get("kind")) == "fixed":
        return min(amount, int(float(code.get("value") or 0)))
    pct = max(0.0, min(100.0, float(code.get("value") or 0)))
    return int(amount * pct / 100)


async def validate_discount_code(code: str, user_id: int, package_id: int, amount: int) -> Dict:
    """Check a code for a specific user/package/amount.

    Returns {ok, error?, code_id, kind, value, discount_amount, final_amount}."""
    import time as _time
    row = await get_discount_code_by_code(code)
    if not row:
        return {"ok": False, "error": "not_found"}
    if not int(row.get("is_active") or 0):
        return {"ok": False, "error": "inactive"}
    exp = int(row.get("expires_at") or 0)
    if exp and exp <= int(_time.time() * 1000):
        return {"ok": False, "error": "expired"}
    max_uses = int(row.get("max_uses") or 0)
    if max_uses and int(row.get("used_count") or 0) >= max_uses:
        return {"ok": False, "error": "exhausted"}
    pkg = int(row.get("package_id") or 0)
    if pkg and pkg != int(package_id or 0):
        return {"ok": False, "error": "wrong_package"}
    if int(amount or 0) < int(row.get("min_amount") or 0):
        return {"ok": False, "error": "min_amount", "min_amount": int(row.get("min_amount") or 0)}
    per_user = int(row.get("per_user_limit") or 0)
    if per_user and await count_user_code_redemptions(int(row["id"]), user_id) >= per_user:
        return {"ok": False, "error": "user_limit"}
    disc = discount_amount_for(row, amount)
    if disc <= 0:
        return {"ok": False, "error": "zero_discount"}
    return {
        "ok": True,
        "code_id": int(row["id"]),
        "code": row["code"],
        "kind": row["kind"],
        "value": float(row["value"] or 0),
        "discount_amount": disc,
        "final_amount": max(0, int(amount) - disc),
    }


# ══════════════════ REFERRAL TIERS ══════════════════

async def get_referral_tiers(active_only: bool = False) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        where = " WHERE is_active=1" if active_only else ""
        async with db.execute(
            f"SELECT * FROM referral_tiers{where} ORDER BY referrals_needed ASC, id ASC"
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_referral_tier(tid: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM referral_tiers WHERE id=?", (int(tid),)) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def add_referral_tier(referrals_needed: int, reward_kind: str, reward_gb: float = 0,
                            duration_days: int = 0, is_unlimited: int = 0, label: str = "") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            """INSERT INTO referral_tiers(referrals_needed,reward_kind,reward_gb,duration_days,is_unlimited,label)
               VALUES(?,?,?,?,?,?)""",
            (int(referrals_needed or 0), reward_kind if reward_kind in ("gb", "service") else "gb",
             float(reward_gb or 0), int(duration_days or 0), 1 if int(is_unlimited or 0) else 0, (label or "").strip()),
        )
        await db.commit()
        return int(c.lastrowid)


async def update_referral_tier(tid: int, **kw):
    if not kw:
        return
    fields = ",".join(f"{k}=?" for k in kw)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE referral_tiers SET {fields} WHERE id=?", (*kw.values(), int(tid)))
        await db.commit()


async def delete_referral_tier(tid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM referral_tiers WHERE id=?", (int(tid),))
        await db.commit()


async def get_user_referral_claim(user_id: int, tier_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM referral_claims WHERE user_id=? AND tier_id=?",
            (int(user_id), int(tier_id)),
        ) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def create_referral_claim(user_id: int, tier_id: int, referrals_at_claim: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            c = await db.execute(
                "INSERT INTO referral_claims(user_id,tier_id,referrals_at_claim) VALUES(?,?,?)",
                (int(user_id), int(tier_id), int(referrals_at_claim or 0)),
            )
            await db.commit()
            return int(c.lastrowid)
        except Exception:
            return 0


async def get_referral_claim(claim_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT rc.*, u.telegram_id, u.full_name, u.username,
                      t.referrals_needed, t.reward_kind, t.reward_gb, t.duration_days, t.is_unlimited, t.label
               FROM referral_claims rc
               JOIN users u ON u.id=rc.user_id
               JOIN referral_tiers t ON t.id=rc.tier_id
               WHERE rc.id=?""",
            (int(claim_id),),
        ) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def update_referral_claim(claim_id: int, **kw):
    if not kw:
        return
    fields = ",".join(f"{k}=?" for k in kw)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE referral_claims SET {fields} WHERE id=?", (*kw.values(), int(claim_id)))
        await db.commit()


# ══════════════════ PACKAGES ══════════════════

async def get_packages(active_only=True) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        q = "SELECT * FROM packages" + (" WHERE is_active=1" if active_only else "") + " ORDER BY sort_order,price"
        async with db.execute(q) as c:
            return [dict(r) for r in await c.fetchall()]

async def get_package(pid: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM packages WHERE id=?", (pid,)) as c:
            r = await c.fetchone()
            return dict(r) if r else None

async def add_package(name, traffic_gb, duration_days, price, description='', inbound_id: int = 0) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            "INSERT INTO packages(name,traffic_gb,duration_days,price,description,inbound_id) VALUES(?,?,?,?,?,?)",
            (name, traffic_gb, duration_days, price, description, inbound_id)
        )
        await db.commit()
        return c.lastrowid

async def update_package(pid: int, **kw):
    fields = ','.join(f"{k}=?" for k in kw)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE packages SET {fields} WHERE id=?", (*kw.values(), pid))
        await db.commit()

async def delete_package(pid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM packages WHERE id=?", (pid,))
        await db.commit()


# ══════════════════ ORDERS ══════════════════



async def get_user_pricing(user_id: int) -> Dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT discount_percent, price_per_gb FROM users WHERE id=?", (user_id,)) as c:
            r = await c.fetchone()
            if not r:
                return {"discount_percent": 0, "price_per_gb": 0}
            return {"discount_percent": float(r["discount_percent"] or 0), "price_per_gb": int(r["price_per_gb"] or 0)}


async def create_custom_order(user_id: int, name: str, total_traffic_gb: float, duration_days: int,
                              price: int, bulk_count: int = 1, bulk_each_gb: float = 0, notes: str = "") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM packages ORDER BY id LIMIT 1") as c0:
            row = await c0.fetchone()
        package_id = row[0] if row else None
        if package_id is None:
            c1 = await db.execute("INSERT INTO packages(name,traffic_gb,duration_days,price,description,is_active) VALUES(?,?,?,?,?,0)",
                                  ("پکیج سیستمی", 1, 30, 0, "system"))
            package_id = c1.lastrowid
        c = await db.execute(
            """INSERT INTO orders(user_id,package_id,status,custom_name,custom_traffic_gb,custom_duration_days,custom_price,bulk_count,bulk_each_gb,notes)
               VALUES(?,?,'pending_payment',?,?,?,?,?,?,?)""",
            (user_id, package_id, name, total_traffic_gb, duration_days, price, bulk_count, bulk_each_gb, notes)
        )
        await db.commit()
        return c.lastrowid
async def create_order(user_id: int, package_id: int, custom_config_name: str = '', custom_price: int = 0) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            "INSERT INTO orders(user_id,package_id,status,custom_config_name,custom_price) VALUES(?,?,'pending_payment',?,?)",
            (user_id, package_id, custom_config_name, int(custom_price or 0))
        )
        await db.commit()
        return c.lastrowid

async def get_order(oid: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT o.*,
                   u.telegram_id,u.username,u.full_name,u.referred_by,
                   COALESCE(NULLIF(o.custom_name,''), p.name) as pkg_name,
                   COALESCE(NULLIF(o.custom_traffic_gb,0), p.traffic_gb) as traffic_gb,
                   COALESCE(NULLIF(o.custom_duration_days,0), p.duration_days) as duration_days,
                   COALESCE(NULLIF(o.custom_price,0), p.price) as price,
                   COALESCE(p.inbound_id,0) as package_inbound_id
            FROM orders o
            JOIN users u ON o.user_id=u.id
            JOIN packages p ON o.package_id=p.id
            WHERE o.id=?
        """, (oid,)) as c:
            r = await c.fetchone()
            return dict(r) if r else None

async def update_order(oid: int, **kw):
    fields = ','.join(f"{k}=?" for k in kw)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE orders SET {fields} WHERE id=?", (*kw.values(), oid))
        await db.commit()


async def claim_order_for_approval(oid: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            """UPDATE orders SET status='processing', approved_at=datetime('now','localtime')
               WHERE id=?
                 AND (
                    status='receipt_submitted'
                    OR (
                        status='processing'
                        AND (
                            approved_at IS NULL
                            OR datetime(approved_at) < datetime('now','localtime','-15 minutes')
                        )
                    )
                 )""",
            (oid,),
        )
        await db.commit()
        return (c.rowcount or 0) > 0


async def release_order_processing(oid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE orders SET status='receipt_submitted', approved_at=NULL WHERE id=? AND status='processing'",
            (oid,),
        )
        await db.commit()

async def get_pending_orders() -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT o.*,u.telegram_id,u.username,u.full_name,
                   COALESCE(NULLIF(o.custom_name,''), p.name) as pkg_name,
                   COALESCE(NULLIF(o.custom_traffic_gb,0), p.traffic_gb) as traffic_gb,
                   COALESCE(NULLIF(o.custom_duration_days,0), p.duration_days) as duration_days,
                   COALESCE(NULLIF(o.custom_price,0), p.price) as price,
                   COALESCE(p.inbound_id,0) as package_inbound_id
            FROM orders o
            JOIN users u ON o.user_id=u.id
            JOIN packages p ON o.package_id=p.id
            WHERE o.status IN ('receipt_submitted','processing')
            ORDER BY o.created_at DESC
        """) as c:
            return [dict(r) for r in await c.fetchall()]

async def get_all_orders(limit=100) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT o.*,u.telegram_id,u.username,u.full_name,
                   COALESCE(NULLIF(o.custom_name,''), p.name) as pkg_name,
                   COALESCE(NULLIF(o.custom_price,0), p.price) as price,
                   COALESCE(p.inbound_id,0) as package_inbound_id
            FROM orders o
            JOIN users u ON o.user_id=u.id
            JOIN packages p ON o.package_id=p.id
            ORDER BY o.created_at DESC LIMIT ?
        """, (limit,)) as c:
            return [dict(r) for r in await c.fetchall()]

async def get_user_orders(user_id: int) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT o.*,COALESCE(NULLIF(o.custom_name,''), p.name) as pkg_name,
                   COALESCE(NULLIF(o.custom_traffic_gb,0), p.traffic_gb) as traffic_gb,
                   COALESCE(NULLIF(o.custom_duration_days,0), p.duration_days) as duration_days,
                   COALESCE(NULLIF(o.custom_price,0), p.price) as price
            FROM orders o
            JOIN packages p ON o.package_id=p.id
            WHERE o.user_id=? ORDER BY o.created_at DESC LIMIT 10
        """, (user_id,)) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_user_orders_full(user_id: int, limit: int = 200) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT o.*, COALESCE(NULLIF(o.custom_name,''), p.name) as pkg_name,
                   COALESCE(NULLIF(o.custom_traffic_gb,0), p.traffic_gb) as traffic_gb,
                   COALESCE(NULLIF(o.custom_duration_days,0), p.duration_days) as duration_days,
                   COALESCE(NULLIF(o.custom_price,0), p.price) as price,
                   s.name AS server_name
            FROM orders o
            JOIN packages p ON p.id=o.package_id
            LEFT JOIN servers s ON s.id=o.server_id
            WHERE o.user_id=?
            ORDER BY o.created_at DESC
            LIMIT ?
        """, (int(user_id), max(1, int(limit or 200)))) as c:
            return [dict(r) for r in await c.fetchall()]

async def has_previous_purchase(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM orders WHERE user_id=? AND status='approved' LIMIT 1", (user_id,)
        ) as c:
            return await c.fetchone() is not None


# ══════════════════ CONFIGS ══════════════════

async def save_config(user_id, server_id, uuid, email, inbound_id, traffic_gb, duration_days, expire_ts, starts_on_first_use: int = 0) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute("""
            INSERT INTO configs(user_id,server_id,uuid,email,inbound_id,traffic_gb,duration_days,expire_timestamp,starts_on_first_use)
            VALUES(?,?,?,?,?,?,?,?,?)
        """, (user_id, server_id, uuid, email, inbound_id, traffic_gb, duration_days, expire_ts, starts_on_first_use))
        await db.commit()
        return c.lastrowid


async def get_user_test_account(user_id: int) -> Optional[Dict]:
    """Return the user's trial record (if any).

    Trials are subscriptions now (`profile_id`); legacy trials referenced a single
    `config_id`. Either way we return one row tagged with `kind` so callers can
    detect 'already used a trial' even if the underlying service was deleted."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM test_accounts WHERE user_id=? LIMIT 1", (int(user_id),)) as c:
            row = await c.fetchone()
        if not row:
            return None
        ta = dict(row)
        if int(ta.get("profile_id") or 0) > 0:
            async with db.execute("SELECT * FROM subscription_profiles WHERE id=?", (int(ta["profile_id"]),)) as c:
                p = await c.fetchone()
            ta["kind"] = "sub" if p else "gone"
            if p:
                ta["profile"] = dict(p)
            return ta
        cid = int(ta.get("config_id") or 0)
        if cid:
            async with db.execute(
                """SELECT email, uuid, server_id, inbound_id, traffic_gb,
                          duration_days, expire_timestamp, is_active
                   FROM configs WHERE id=?""",
                (cid,),
            ) as c:
                cfg = await c.fetchone()
            if cfg:
                ta.update(dict(cfg))
                ta["kind"] = "config"
                return ta
        ta["kind"] = "gone"
        return ta


async def add_user_test_account(user_id: int, config_id: int = 0, profile_id: int = 0) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            """INSERT INTO test_accounts(user_id,config_id,profile_id) VALUES(?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET config_id=excluded.config_id,
                   profile_id=excluded.profile_id, created_at=datetime('now','localtime')""",
            (int(user_id), int(config_id or 0), int(profile_id or 0)),
        )
        await db.commit()
        return c.lastrowid or 0

async def get_config(cid: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.*,s.name as server_name,s.url as server_url,
                   s.username as srv_user,s.password as srv_pass,
                   s.api_token as srv_api_token,
                   s.sub_path,s.inbound_id as srv_inbound,
                   u.telegram_id as owner_telegram_id, u.username as owner_username,
                   u.full_name as owner_name
            FROM configs c JOIN servers s ON c.server_id=s.id
            LEFT JOIN users u ON u.id=c.user_id
            WHERE c.id=?
        """, (cid,)) as cu:
            r = await cu.fetchone()
            return dict(r) if r else None

async def get_user_configs(user_id: int) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.*,s.name as server_name
            FROM configs c JOIN servers s ON c.server_id=s.id
            WHERE c.user_id=?
            ORDER BY c.is_active DESC, c.created_at DESC
        """, (user_id,)) as cu:
            return [dict(r) for r in await cu.fetchall()]

async def get_all_configs() -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.*,s.name as server_name,u.full_name,u.telegram_id
            FROM configs c
            JOIN servers s ON c.server_id=s.id
            JOIN users u ON c.user_id=u.id
            ORDER BY c.created_at DESC
        """) as cu:
            return [dict(r) for r in await cu.fetchall()]


async def get_active_configs_for_alerts(limit: int = 500) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.*,s.name as server_name,s.url as server_url,
                   s.username as srv_user,s.password as srv_pass,
                   s.api_token as srv_api_token,s.sub_path,
                   u.telegram_id,u.full_name
            FROM configs c
            JOIN servers s ON c.server_id=s.id
            JOIN users u ON c.user_id=u.id
            WHERE c.is_active=1 AND s.is_active=1
            ORDER BY c.id ASC
            LIMIT ?
        """, (max(1, int(limit or 500)),)) as cu:
            return [dict(r) for r in await cu.fetchall()]


async def get_config_alerts_sent(config_id: int) -> set[tuple[str, str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT alert_type, threshold FROM config_alerts WHERE config_id=?",
            (config_id,),
        ) as c:
            return {(str(r[0]), str(r[1])) for r in await c.fetchall()}


async def mark_config_alert_sent(config_id: int, alert_type: str, threshold: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO config_alerts(config_id,alert_type,threshold) VALUES(?,?,?)",
            (config_id, alert_type, threshold),
        )
        await db.commit()


async def clear_config_alerts(config_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM config_alerts WHERE config_id=?", (config_id,))
        await db.commit()


async def get_configs_needing_expiry_repair(limit: int = 500) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.*,s.name as server_name,s.url as server_url,
                   s.username as srv_user,s.password as srv_pass,
                   s.api_token as srv_api_token,s.sub_path
            FROM configs c
            JOIN servers s ON c.server_id=s.id
            WHERE c.is_active=1
              AND c.duration_days > 0
              AND (COALESCE(c.expire_timestamp,0) <= 0 OR COALESCE(c.starts_on_first_use,0)=1)
            ORDER BY c.id ASC
            LIMIT ?
        """, (max(1, int(limit or 500)),)) as cu:
            return [dict(r) for r in await cu.fetchall()]



async def get_configs_by_base_email(base_email: str) -> List[Dict]:
    base = (base_email or "").strip()
    if not base:
        return []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM configs WHERE email=? OR email LIKE ? ORDER BY id DESC",
            (base, f"{base}_m%"),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def delete_config_by_id(cid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM configs WHERE id=?", (cid,))
        await db.commit()


async def delete_configs_by_base_email(base_email: str) -> int:
    base = (base_email or "").strip()
    if not base:
        return 0
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute("DELETE FROM configs WHERE email=? OR email LIKE ?", (base, f"{base}_m%"))
        await db.commit()
        return c.rowcount

async def update_config(cid: int, **kw):
    fields = ','.join(f"{k}=?" for k in kw)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE configs SET {fields} WHERE id=?", (*kw.values(), cid))
        await db.commit()

async def get_migration_count_today(config_id: int) -> int:
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT migration_count,last_migration_date FROM configs WHERE id=?", (config_id,)
        ) as c:
            r = await c.fetchone()
            if r and r[1] == today:
                return r[0]
            return 0


async def get_user_migration_count_today(user_id: int) -> int:
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COALESCE(SUM(migration_count),0) FROM configs WHERE user_id=? AND last_migration_date=?",
            (user_id, today),
        ) as c:
            r = await c.fetchone()
            return int(r[0] or 0)


# ══════════════════ SETTINGS ══════════════════

async def get_setting(key: str, default='') -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as c:
            r = await c.fetchone()
            return r[0] if r else default

async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))
        await db.commit()


# ══════════════════ MULTI-SERVER SUBSCRIPTIONS (EXPERIMENTAL) ══════════════════

async def create_subscription_profile(user_id: int, order_id: int, token: str, email: str,
                                      traffic_gb: float, duration_days: int, expire_timestamp: int,
                                      name: str = "", starts_on_first_use: int = 0) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            """INSERT INTO subscription_profiles
                   (user_id,order_id,token,email,name,traffic_gb,duration_days,expire_timestamp,starts_on_first_use)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (int(user_id), int(order_id or 0), token, email, (name or "").strip(),
             float(traffic_gb), int(duration_days), int(expire_timestamp or 0), int(starts_on_first_use or 0)),
        )
        await db.commit()
        return c.lastrowid


async def add_subscription_node(profile_id: int, server_id: int, inbound_id: int, uuid: str, email: str, link: str = "") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            """INSERT INTO subscription_nodes(profile_id,server_id,inbound_id,uuid,email,link)
               VALUES(?,?,?,?,?,?)""",
            (int(profile_id), int(server_id), int(inbound_id), uuid, email, link or ""),
        )
        await db.commit()
        return c.lastrowid


async def get_subscription_profile_by_token(token: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM subscription_profiles WHERE token=? LIMIT 1", ((token or "").strip(),)) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def get_user_subscription_profiles(user_id: int) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM subscription_profiles WHERE user_id=? ORDER BY is_active DESC, id DESC",
            (int(user_id),),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_user_configs_full(user_id: int) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.*, s.name AS server_name, s.url AS server_url
            FROM configs c
            JOIN servers s ON s.id=c.server_id
            WHERE c.user_id=?
            ORDER BY c.is_active DESC, c.id DESC
        """, (int(user_id),)) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_subscription_profiles_full(user_id: int | None = None, limit: int = 300) -> List[Dict]:
    where = ""
    params: list = []
    if user_id is not None:
        where = "WHERE sp.user_id=?"
        params.append(int(user_id))
    params.append(max(1, int(limit or 300)))
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""SELECT sp.*, u.telegram_id, u.username, u.full_name,
                       COALESCE(NULLIF(o.custom_name,''), p.name) AS order_name,
                       COALESCE(NULLIF(o.custom_price,0), p.price, 0) AS order_price,
                       COUNT(n.id) AS node_count,
                       SUM(CASE WHEN n.is_active=1 THEN 1 ELSE 0 END) AS active_node_count
                FROM subscription_profiles sp
                JOIN users u ON u.id=sp.user_id
                LEFT JOIN orders o ON o.id=sp.order_id
                LEFT JOIN packages p ON p.id=o.package_id
                LEFT JOIN subscription_nodes n ON n.profile_id=sp.id
                {where}
                GROUP BY sp.id
                ORDER BY sp.is_active DESC, sp.id DESC
                LIMIT ?""",
            tuple(params),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_subscription_profile(pid: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM subscription_profiles WHERE id=?", (int(pid),)) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def get_subscription_nodes(profile_id: int) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT n.*, s.name AS server_name, s.url AS server_url, s.username AS srv_user,
                      s.password AS srv_pass, s.api_token AS srv_api_token, s.sub_path,
                      nc.label AS node_label, nc.priority AS node_priority
               FROM subscription_nodes n
               JOIN servers s ON s.id=n.server_id
               LEFT JOIN subscription_node_configs nc
                    ON nc.server_id=n.server_id AND nc.inbound_id=n.inbound_id
               WHERE n.profile_id=?
               ORDER BY n.id""",
            (int(profile_id),),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_subscription_node(node_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT n.*, s.name AS server_name, nc.label AS node_label
               FROM subscription_nodes n
               JOIN servers s ON s.id=n.server_id
               LEFT JOIN subscription_node_configs nc
                    ON nc.server_id=n.server_id AND nc.inbound_id=n.inbound_id
               WHERE n.id=?""",
            (int(node_id),),
        ) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def get_active_subscription_profiles(limit: int = 200) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM subscription_profiles sp
               WHERE sp.is_active=1
                  OR EXISTS (
                      SELECT 1 FROM subscription_nodes n
                      WHERE n.profile_id=sp.id AND n.is_active=1
                  )
               ORDER BY sp.is_active DESC, sp.id
               LIMIT ?""",
            (max(1, int(limit or 200)),),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_expired_subscription_profiles(now_ms: int, limit: int = 300) -> List[Dict]:
    """Profiles that are out of time or out of quota, with the owner's chat id.

    Used by the lifecycle worker to notify the user that their subscription
    ended and, after the grace period, to delete it."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT sp.*, u.telegram_id, u.full_name
               FROM subscription_profiles sp
               JOIN users u ON u.id = sp.user_id
               WHERE (sp.expire_timestamp > 0 AND sp.expire_timestamp <= ?)
                  OR (sp.traffic_gb > 0 AND sp.used_bytes >= sp.traffic_gb * 1073741824)
               ORDER BY sp.id
               LIMIT ?""",
            (int(now_ms), max(1, int(limit or 300))),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_subscription_profiles_for_prewarn(now_ms: int, within_ms: int, used_fraction: float, limit: int = 300) -> List[Dict]:
    """Active profiles that are *about to* end (not yet ended), not warned yet.

    Triggers when expiry is within `within_ms`, OR usage has crossed
    `used_fraction` of the quota (e.g. 0.85 = 85% used / 15% left)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT sp.*, u.telegram_id, u.full_name
               FROM subscription_profiles sp
               JOIN users u ON u.id = sp.user_id
               WHERE sp.is_active = 1 AND COALESCE(sp.prewarn_sent,0) = 0
                 AND (sp.expire_timestamp = 0 OR sp.expire_timestamp > ?)
                 AND (sp.traffic_gb <= 0 OR sp.used_bytes < sp.traffic_gb * 1073741824)
                 AND (
                       (sp.expire_timestamp > 0 AND sp.expire_timestamp <= ?)
                    OR (sp.traffic_gb > 0 AND sp.used_bytes >= sp.traffic_gb * 1073741824 * ?)
                 )
               ORDER BY sp.id
               LIMIT ?""",
            (int(now_ms), int(now_ms + within_ms), float(used_fraction), max(1, int(limit or 300))),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def update_subscription_profile(pid: int, **kw):
    fields = ','.join(f"{k}=?" for k in kw)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE subscription_profiles SET {fields}, updated_at=datetime('now','localtime') WHERE id=?", (*kw.values(), int(pid)))
        await db.commit()


async def update_subscription_node(nid: int, **kw):
    fields = ','.join(f"{k}=?" for k in kw)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE subscription_nodes SET {fields} WHERE id=?", (*kw.values(), int(nid)))
        await db.commit()


async def delete_subscription_node(nid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM subscription_nodes WHERE id=?", (int(nid),))
        await db.commit()


async def get_subscription_node_by_uuid(client_uuid: str) -> Optional[Dict]:
    """Find a subscription node (and its owning profile) by client UUID.

    Used to resolve a pasted config link back to the sub it belongs to."""
    raw = (client_uuid or "").strip()
    if not raw:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT n.*, p.user_id AS profile_user_id
               FROM subscription_nodes n
               JOIN subscription_profiles p ON p.id = n.profile_id
               WHERE n.uuid = ? COLLATE NOCASE
               ORDER BY p.is_active DESC, n.id DESC
               LIMIT 1""",
            (raw,),
        ) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def delete_subscription_profile(pid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM subscription_nodes WHERE profile_id=?", (int(pid),))
        await db.execute("DELETE FROM subscription_profiles WHERE id=?", (int(pid),))
        await db.commit()


# ══════════════════ STATS ══════════════════

async def get_stats() -> Dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async def q(sql, *a):
            async with db.execute(sql, a) as c:
                return (await c.fetchone())[0]
        return {
            'total_users': await q("SELECT COUNT(*) FROM users"),
            'active_configs': await q("SELECT COUNT(*) FROM configs WHERE is_active=1"),
            'total_orders': await q("SELECT COUNT(*) FROM orders WHERE status='approved'"),
            'pending_orders': await q("SELECT COUNT(*) FROM orders WHERE status='receipt_submitted'"),
            'total_revenue': await q("SELECT COALESCE(SUM(COALESCE(NULLIF(o.custom_price,0), p.price)),0) FROM orders o JOIN packages p ON o.package_id=p.id WHERE o.status='approved'"),
            'active_servers': await q("SELECT COUNT(*) FROM servers WHERE is_active=1"),
            'total_servers': await q("SELECT COUNT(*) FROM servers"),
            'today_orders': await q("SELECT COUNT(*) FROM orders WHERE status='approved' AND date(approved_at)=date('now','localtime')"),
        }


async def build_daily_report(gregorian_date: str | None = None) -> Dict:
    now = tehran_now()
    gdate = gregorian_date or now.strftime("%Y-%m-%d")
    jkey = jalali_date_key(now)
    jdisplay = jalali_display(now)
    now_ms = int(time.time() * 1000)

    async with aiosqlite.connect(DB_PATH) as db:
        async def q(sql, *args):
            async with db.execute(sql, args) as c:
                row = await c.fetchone()
                return row[0] if row else 0

        sales_amount = await q(
            """SELECT COALESCE(SUM(COALESCE(NULLIF(o.custom_price,0), p.price)),0)
               FROM orders o JOIN packages p ON o.package_id=p.id
               WHERE o.status='approved' AND date(o.approved_at)=?""",
            gdate,
        )
        report = {
            "jalali_date": jkey,
            "gregorian_date": gdate,
            "jalali_display": jdisplay,
            "sales_amount": int(sales_amount or 0),
            "orders_approved": int(await q("SELECT COUNT(*) FROM orders WHERE status='approved' AND date(approved_at)=?", gdate) or 0),
            "renewals": int(await q("SELECT COUNT(*) FROM orders WHERE status='approved' AND (COALESCE(renew_config_id,0)>0 OR COALESCE(renew_sub_profile_id,0)>0) AND date(approved_at)=?", gdate) or 0),
            "new_configs": int(await q("SELECT COUNT(*) FROM configs WHERE date(created_at)=?", gdate) or 0),
            "active_configs": int(await q("SELECT COUNT(*) FROM configs WHERE is_active=1") or 0),
            "expired_configs": int(await q("SELECT COUNT(*) FROM configs WHERE COALESCE(expire_timestamp,0)>0 AND expire_timestamp<=?", now_ms) or 0),
            "new_users": int(await q("SELECT COUNT(*) FROM users WHERE date(created_at)=?", gdate) or 0),
            "wallet_topups": int(await q("SELECT COUNT(*) FROM topup_requests WHERE status='approved' AND date(reviewed_at)=?", gdate) or 0),
            "wallet_topup_amount": int(await q("SELECT COALESCE(SUM(amount),0) FROM topup_requests WHERE status='approved' AND date(reviewed_at)=?", gdate) or 0),
            "pending_orders": int(await q("SELECT COUNT(*) FROM orders WHERE status='receipt_submitted'") or 0),
            "total_revenue": int(await q(
                """SELECT COALESCE(SUM(COALESCE(NULLIF(o.custom_price,0), p.price)),0)
                   FROM orders o JOIN packages p ON o.package_id=p.id
                   WHERE o.status='approved'"""
            ) or 0),
            "total_approved_orders": int(await q("SELECT COUNT(*) FROM orders WHERE status='approved'") or 0),
            "total_users": int(await q("SELECT COUNT(*) FROM users") or 0),
            "total_configs": int(await q("SELECT COUNT(*) FROM configs") or 0),
            "sent_to_admins": 0,
        }
        return report


async def get_daily_report(jalali_date: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM daily_reports WHERE jalali_date=?", (jalali_date,)) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def snapshot_daily_report(gregorian_date: str | None = None) -> Dict:
    report = await build_daily_report(gregorian_date)
    existing = await get_daily_report(report["jalali_date"])
    report["sent_to_admins"] = int((existing or {}).get("sent_to_admins") or 0)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO daily_reports(
                   jalali_date,gregorian_date,jalali_display,sales_amount,orders_approved,renewals,
                   new_configs,active_configs,expired_configs,new_users,wallet_topups,wallet_topup_amount,
                   pending_orders,total_revenue,total_approved_orders,total_users,total_configs,sent_to_admins,updated_at
               )
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))
               ON CONFLICT(jalali_date) DO UPDATE SET
                   gregorian_date=excluded.gregorian_date,
                   jalali_display=excluded.jalali_display,
                   sales_amount=excluded.sales_amount,
                   orders_approved=excluded.orders_approved,
                   renewals=excluded.renewals,
                   new_configs=excluded.new_configs,
                   active_configs=excluded.active_configs,
                   expired_configs=excluded.expired_configs,
                   new_users=excluded.new_users,
                   wallet_topups=excluded.wallet_topups,
                   wallet_topup_amount=excluded.wallet_topup_amount,
                   pending_orders=excluded.pending_orders,
                   total_revenue=excluded.total_revenue,
                   total_approved_orders=excluded.total_approved_orders,
                   total_users=excluded.total_users,
                   total_configs=excluded.total_configs,
                   updated_at=datetime('now','localtime')""",
            (
                report["jalali_date"],
                report["gregorian_date"],
                report["jalali_display"],
                report["sales_amount"],
                report["orders_approved"],
                report["renewals"],
                report["new_configs"],
                report["active_configs"],
                report["expired_configs"],
                report["new_users"],
                report["wallet_topups"],
                report["wallet_topup_amount"],
                report["pending_orders"],
                report["total_revenue"],
                report["total_approved_orders"],
                report["total_users"],
                report["total_configs"],
                report["sent_to_admins"],
            ),
        )
        await db.commit()
    return await get_daily_report(report["jalali_date"]) or report


async def get_recent_daily_reports(limit: int = 30) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM daily_reports ORDER BY gregorian_date DESC LIMIT ?",
            (max(1, int(limit or 30)),),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def mark_daily_report_sent(jalali_date: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE daily_reports SET sent_to_admins=1 WHERE jalali_date=?", (jalali_date,))
        await db.commit()


def format_daily_report(report: Dict) -> str:
    def toman(value) -> str:
        return f"{int(value or 0):,}".replace(",", "،")

    return (
        f"گزارش روزانه {report.get('jalali_display') or report.get('jalali_date')}\n"
        f"فروش امروز: {toman(report.get('sales_amount'))} تومان\n"
        f"سفارش تایید شده: {int(report.get('orders_approved') or 0)}\n"
        f"تمدیدها: {int(report.get('renewals') or 0)}\n"
        f"کانفیگ جدید: {int(report.get('new_configs') or 0)}\n"
        f"کاربر جدید: {int(report.get('new_users') or 0)}\n"
        f"شارژ کیف پول: {int(report.get('wallet_topups') or 0)} مورد | {toman(report.get('wallet_topup_amount'))} تومان\n"
        f"سفارش‌های در انتظار: {int(report.get('pending_orders') or 0)}\n\n"
        f"جمع کل فروش: {toman(report.get('total_revenue'))} تومان\n"
        f"کل سفارش‌های موفق: {int(report.get('total_approved_orders') or 0)}\n"
        f"کانفیگ فعال/منقضی: {int(report.get('active_configs') or 0)} / {int(report.get('expired_configs') or 0)}\n"
        f"کل کاربران: {int(report.get('total_users') or 0)}"
    )


# ══════════════════ LEGACY CONFIG CLAIMS ══════════════════

async def create_legacy_claim(user_id: int, telegram_id: int, config_link: str, config_key: str, email: str = '', uuid: str = '') -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            """INSERT INTO legacy_claims(user_id,telegram_id,config_link,config_key,email,uuid,status)
               VALUES(?,?,?,?,?,?,'pending')""",
            (user_id, telegram_id, config_link, config_key, email, uuid)
        )
        await db.commit()
        return c.lastrowid


async def get_legacy_claim_by_key(config_key: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM legacy_claims WHERE config_key=?", (config_key,)) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def get_legacy_claim_by_identity(email: str = '', uuid: str = '') -> Optional[Dict]:
    email = (email or '').strip()
    uuid = (uuid or '').strip()
    if not email and not uuid:
        return None
    clauses = []
    params = []
    if email:
        clauses.append("email=?")
        params.append(email)
    if uuid:
        clauses.append("uuid=?")
        params.append(uuid)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT * FROM legacy_claims WHERE {' OR '.join(clauses)} ORDER BY id DESC LIMIT 1",
            params,
        ) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def get_pending_legacy_claims() -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT lc.*, u.full_name, u.username
               FROM legacy_claims lc
               JOIN users u ON lc.user_id=u.id
               WHERE lc.status='pending'
               ORDER BY lc.created_at DESC"""
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_legacy_claim(cid: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM legacy_claims WHERE id=?", (cid,)) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def update_legacy_claim(cid: int, **kw):
    fields = ','.join(f"{k}=?" for k in kw)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE legacy_claims SET {fields} WHERE id=?", (*kw.values(), cid))
        await db.commit()


async def get_config_by_email(email: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM configs WHERE email=? LIMIT 1", (email,)) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def get_config_by_uuid(uuid_val: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM configs WHERE uuid=? LIMIT 1", (uuid_val,)) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def reset_legacy_claims() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute("DELETE FROM legacy_claims")
        await db.commit()
        return c.rowcount or 0
