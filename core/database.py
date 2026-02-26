import aiosqlite
import secrets
import string
import time
from datetime import datetime, date
from typing import Optional, List, Dict
from core.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    username TEXT NOT NULL,
    password TEXT NOT NULL,
    sub_path TEXT DEFAULT '',
    inbound_id INTEGER DEFAULT 1,
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
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    traffic_gb REAL NOT NULL,
    duration_days INTEGER NOT NULL,
    price INTEGER NOT NULL,
    description TEXT DEFAULT '',
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
    is_active INTEGER DEFAULT 1,
    migration_count INTEGER DEFAULT 0,
    last_migration_date TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(server_id) REFERENCES servers(id)
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

INSERT OR IGNORE INTO settings VALUES
    ('welcome_message','به Atlas Account خوش آمدید! 🌐\nبهترین سرویس VPN با سرعت بالا.'),
    ('support_username',''),
    ('maintenance_mode','0');
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        for stmt in SCHEMA.strip().split(';'):
            s = stmt.strip()
            if s:
                await db.execute(s)
        await _ensure_columns(db)
        await db.commit()




async def _ensure_columns(db):
    migrations = {
        "servers": [
            ("max_active_configs", "INTEGER DEFAULT 0"),
        ],
        "users": [
            ("discount_percent", "REAL DEFAULT 0"),
            ("price_per_gb", "INTEGER DEFAULT 0"),
            ("is_wholesale", "INTEGER DEFAULT 0"),
            ("wholesale_request_pending", "INTEGER DEFAULT 0"),
        ],
        "orders": [
            ("custom_name", "TEXT DEFAULT ''"),
            ("custom_traffic_gb", "REAL DEFAULT 0"),
            ("custom_duration_days", "INTEGER DEFAULT 0"),
            ("custom_price", "INTEGER DEFAULT 0"),
            ("bulk_count", "INTEGER DEFAULT 1"),
            ("bulk_each_gb", "REAL DEFAULT 0"),
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

async def add_server(name, url, username, password, sub_path, inbound_id, note='') -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            "INSERT INTO servers(name,url,username,password,sub_path,inbound_id,note) VALUES(?,?,?,?,?,?,?)",
            (name, url, username, password, sub_path, inbound_id, note)
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


async def server_has_capacity(server_id: int) -> bool:
    srv = await get_server(server_id)
    if not srv:
        return False
    cap = int(srv.get("max_active_configs") or 0)
    if cap <= 0:
        return True
    return (await count_active_configs_by_server(server_id)) < cap


async def get_available_servers() -> List[Dict]:
    servers = await get_servers(active_only=True)
    out = []
    for s in servers:
        if await server_has_capacity(s["id"]):
            out.append(s)
    return out
# ══════════════════ USERS ══════════════════

async def get_or_create_user(telegram_id: int, username=None, full_name=None) -> Dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)) as c:
            row = await c.fetchone()
        if row:
            await db.execute("UPDATE users SET username=?,full_name=? WHERE telegram_id=?",
                             (username, full_name, telegram_id))
            await db.commit()
            return dict(row)
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

async def add_package(name, traffic_gb, duration_days, price, description='') -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            "INSERT INTO packages(name,traffic_gb,duration_days,price,description) VALUES(?,?,?,?,?)",
            (name, traffic_gb, duration_days, price, description)
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
async def create_order(user_id: int, package_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            "INSERT INTO orders(user_id,package_id,status) VALUES(?,?,'pending_payment')",
            (user_id, package_id)
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
                   COALESCE(NULLIF(o.custom_price,0), p.price) as price
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

async def get_pending_orders() -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT o.*,u.telegram_id,u.username,u.full_name,
                   COALESCE(NULLIF(o.custom_name,''), p.name) as pkg_name,
                   COALESCE(NULLIF(o.custom_traffic_gb,0), p.traffic_gb) as traffic_gb,
                   COALESCE(NULLIF(o.custom_duration_days,0), p.duration_days) as duration_days,
                   COALESCE(NULLIF(o.custom_price,0), p.price) as price
            FROM orders o
            JOIN users u ON o.user_id=u.id
            JOIN packages p ON o.package_id=p.id
            WHERE o.status IN ('receipt_submitted')
            ORDER BY o.created_at DESC
        """) as c:
            return [dict(r) for r in await c.fetchall()]

async def get_all_orders(limit=100) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT o.*,u.telegram_id,u.username,u.full_name,
                   COALESCE(NULLIF(o.custom_name,''), p.name) as pkg_name,
                   COALESCE(NULLIF(o.custom_price,0), p.price) as price
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

async def has_previous_purchase(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM orders WHERE user_id=? AND status='approved' LIMIT 1", (user_id,)
        ) as c:
            return await c.fetchone() is not None


# ══════════════════ CONFIGS ══════════════════

async def save_config(user_id, server_id, uuid, email, inbound_id, traffic_gb, duration_days, expire_ts) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute("""
            INSERT INTO configs(user_id,server_id,uuid,email,inbound_id,traffic_gb,duration_days,expire_timestamp)
            VALUES(?,?,?,?,?,?,?,?)
        """, (user_id, server_id, uuid, email, inbound_id, traffic_gb, duration_days, expire_ts))
        await db.commit()
        return c.lastrowid

async def get_config(cid: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.*,s.name as server_name,s.url as server_url,
                   s.username as srv_user,s.password as srv_pass,
                   s.sub_path,s.inbound_id as srv_inbound
            FROM configs c JOIN servers s ON c.server_id=s.id WHERE c.id=?
        """, (cid,)) as cu:
            r = await cu.fetchone()
            return dict(r) if r else None

async def get_user_configs(user_id: int) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.*,s.name as server_name
            FROM configs c JOIN servers s ON c.server_id=s.id
            WHERE c.user_id=? AND c.is_active=1
            ORDER BY c.created_at DESC
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
            'total_revenue': await q("SELECT COALESCE(SUM(p.price),0) FROM orders o JOIN packages p ON o.package_id=p.id WHERE o.status='approved'"),
            'active_servers': await q("SELECT COUNT(*) FROM servers WHERE is_active=1"),
            'total_servers': await q("SELECT COUNT(*) FROM servers"),
            'today_orders': await q("SELECT COUNT(*) FROM orders WHERE status='approved' AND date(approved_at)=date('now','localtime')"),
        }


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
