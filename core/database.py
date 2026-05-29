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
        await db.execute("UPDATE orders SET status='receipt_submitted' WHERE status='processing'")
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
            ("referral_bonus_applied", "INTEGER DEFAULT 0"),
        ],
        "daily_reports": [
            ("renewals", "INTEGER DEFAULT 0"),
            ("sent_to_admins", "INTEGER DEFAULT 0"),
            ("total_revenue", "INTEGER DEFAULT 0"),
            ("total_approved_orders", "INTEGER DEFAULT 0"),
            ("total_users", "INTEGER DEFAULT 0"),
            ("total_configs", "INTEGER DEFAULT 0"),
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
            "UPDATE orders SET status='processing' WHERE id=? AND status='receipt_submitted'",
            (oid,),
        )
        await db.commit()
        return (c.rowcount or 0) > 0

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

async def get_config(cid: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT c.*,s.name as server_name,s.url as server_url,
                   s.username as srv_user,s.password as srv_pass,
                   s.api_token as srv_api_token,
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
            "renewals": int(await q("SELECT COUNT(*) FROM orders WHERE status='approved' AND COALESCE(renew_config_id,0)>0 AND date(approved_at)=?", gdate) or 0),
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
