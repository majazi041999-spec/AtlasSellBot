import aiosqlite
import re
import secrets
import string
import time
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict
from core.config import DB_PATH
from core.jalali import jalali_date_key, jalali_display, tehran_now
from core.sorting import fa_collation

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

CREATE TABLE IF NOT EXISTS rep_test_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    profile_id INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY(user_id) REFERENCES users(id)
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

CREATE TABLE IF NOT EXISTS campaign_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign TEXT NOT NULL,               -- 'trial2paid' | 'winback' | 'renewal' | 'referral' | ...
    kind TEXT DEFAULT 'sent',             -- 'sent' | 'converted'
    user_id INTEGER DEFAULT 0,
    order_id INTEGER DEFAULT 0,
    amount INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS discount_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    kind TEXT DEFAULT 'percent',          -- 'percent' | 'fixed'
    campaign TEXT DEFAULT '',             -- groups a code under a sales campaign
    value REAL DEFAULT 0,                 -- percent (0-100) or toman amount
    max_uses INTEGER DEFAULT 0,           -- 0 = unlimited (total)
    per_user_limit INTEGER DEFAULT 1,     -- 0 = unlimited per user
    used_count INTEGER DEFAULT 0,
    min_amount INTEGER DEFAULT 0,         -- min order price to qualify
    package_id INTEGER DEFAULT 0,         -- 0 = all packages
    expires_at INTEGER DEFAULT 0,         -- epoch ms, 0 = never
    is_active INTEGER DEFAULT 1,
    targeted INTEGER DEFAULT 0,           -- 1 = only users targeted by the campaign may redeem
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
    reward_kind TEXT DEFAULT 'wallet',    -- 'wallet' | 'service' | 'gb' (legacy)
    reward_amount INTEGER DEFAULT 0,      -- toman credited to wallet (for 'wallet')
    reward_gb REAL DEFAULT 0,             -- service traffic ('service') or legacy 'gb'
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

CREATE TABLE IF NOT EXISTS custom_campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,            -- joins campaign_events + discount_codes.campaign
    title TEXT NOT NULL,
    emoji TEXT DEFAULT '🎯',
    segment TEXT DEFAULT 'all',           -- key in CUSTOM_SEGMENTS
    message TEXT DEFAULT '',              -- placeholders: {name} {code} {brand}
    photo TEXT DEFAULT '',                -- data-URI image attached to the DM
    code TEXT DEFAULT '',                 -- discount code substituted for {code}
    image_prompt TEXT DEFAULT '',         -- AI image-generation prompt (copyable in panel)
    notes TEXT DEFAULT '',                -- strategy notes shown to the admin
    status TEXT DEFAULT 'draft',          -- 'draft' | 'sent'
    sent_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    sent_at TEXT DEFAULT ''
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
            # Live load, refreshed by the auto-node poller.
            ("online_count", "INTEGER DEFAULT 0"),       # newest raw sample (what the panel shows)
            ("online_avg", "REAL DEFAULT 0"),            # smoothed sample; what routing decisions use
            ("online_ok", "INTEGER DEFAULT 0"),          # 0 = last poll failed → count unknown, not zero
            ("online_checked_at", "INTEGER DEFAULT 0"),  # epoch ms
            ("load_weight", "REAL DEFAULT 1"),           # capacity multiplier; higher = can take more users
        ],
        "users": [
            ("discount_percent", "REAL DEFAULT 0"),
            ("price_per_gb", "INTEGER DEFAULT 0"),
            ("unlimited_price", "INTEGER DEFAULT 0"),
            ("is_wholesale", "INTEGER DEFAULT 0"),
            ("wholesale_request_pending", "INTEGER DEFAULT 0"),
            ("hide_brand", "INTEGER DEFAULT 0"),
            ("rep_brand_name", "TEXT DEFAULT ''"),
            ("rep_topup_required", "INTEGER DEFAULT 0"),
            ("rep_logo", "TEXT DEFAULT ''"),
            ("admin_role", "TEXT DEFAULT 'none'"),
            ("balance_toman", "INTEGER DEFAULT 0"),
            ("referral_reminder_sent", "INTEGER DEFAULT 0"),
            ("trial_followup_sent", "INTEGER DEFAULT 0"),
            ("winback_sent", "INTEGER DEFAULT 0"),
        ],
        "discount_codes": [
            ("campaign", "TEXT DEFAULT ''"),
            ("targeted", "INTEGER DEFAULT 0"),
        ],
        "configs": [
            ("starts_on_first_use", "INTEGER DEFAULT 0"),
            ("first_use_at", "TEXT DEFAULT ''"),
        ],
        "packages": [
            ("inbound_id", "INTEGER DEFAULT 0"),
            ("is_unlimited", "INTEGER DEFAULT 0"),
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
            ("base_price", "INTEGER DEFAULT 0"),
            ("cart_reminder_stage", "INTEGER DEFAULT 0"),
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
            ("connect_host", "TEXT DEFAULT ''"),
            # Auto node ("نود خودکار"): one entry in the user's subscription that
            # always points at whichever server currently has the fewest online
            # users. Its own server_id/inbound_id are placeholders (see
            # add_auto_subscription_node_config); the real target is resolved per
            # profile at provisioning time.
            ("is_auto", "INTEGER DEFAULT 0"),
            ("auto_pool", "TEXT DEFAULT ''"),        # csv of candidate node-config ids; '' = every active node
            ("auto_show_server", "INTEGER DEFAULT 0"),  # append the current server name to the label
        ],
        "subscription_nodes": [
            # Which node CONFIG this client belongs to. Previously derived from the
            # `_n{config_id}` email suffix, which cannot work for an auto node
            # (its server/inbound differ per profile, so a server+inbound join
            # would attach the wrong config).
            ("config_id", "INTEGER DEFAULT 0"),
            # Epoch ms of the last auto-node reassignment; feeds the move cooldown
            # so a subscription can't be bounced between servers repeatedly.
            ("moved_at", "INTEGER DEFAULT 0"),
            # Traffic this node used BEFORE its client was moved to another
            # server. A moved client starts from zero on the new panel, and
            # profile usage is the SUM over nodes — without carrying the old
            # figure forward, every move would hand the customer back the quota
            # they had already spent.
            ("carried_bytes", "INTEGER DEFAULT 0"),
        ],
        "test_accounts": [
            ("profile_id", "INTEGER DEFAULT 0"),
        ],
        "referral_tiers": [
            ("reward_amount", "INTEGER DEFAULT 0"),
        ],
    }
    for table, cols in migrations.items():
        async with db.execute(f"PRAGMA table_info({table})") as c:
            existing = {r[1] for r in await c.fetchall()}
        for col, ddl in cols:
            if col not in existing:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

    # Backfill subscription_nodes.config_id from the historical `_n{config_id}`
    # email suffix so existing subscriptions keep their node identity now that we
    # join on config_id instead of (server_id, inbound_id). Same trailing-suffix
    # regex the orphan cleanup uses — done in Python because a legacy profile
    # email may itself contain "_n", and only the LAST match is the config id.
    async with db.execute(
        "SELECT id, email FROM subscription_nodes WHERE config_id=0 AND email LIKE '%\\_n%' ESCAPE '\\'"
    ) as c:
        rows = await c.fetchall()
    updates = []
    for row in rows:
        m = re.search(r"_n(\d+)$", str(row[1] or ""))
        if m:
            updates.append((int(m.group(1)), int(row[0])))
    if updates:
        await db.executemany("UPDATE subscription_nodes SET config_id=? WHERE id=?", updates)

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


# An auto node has no server of its own — the LEFT JOIN below keeps it in the
# list anyway, and its real target is resolved per subscription at provisioning
# time by core.autonode.
_NODE_CONFIG_SELECT = """SELECT nc.*, s.name AS server_name, s.url AS server_url, s.username AS srv_user,
                   s.password AS srv_pass, s.api_token AS srv_api_token, s.sub_path,
                   COALESCE(s.is_active, 0) AS server_active, s.max_active_configs
            FROM subscription_node_configs nc
            LEFT JOIN servers s ON s.id=nc.server_id"""


async def get_subscription_node_configs(active_only: bool = True) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        where = ""
        if active_only:
            where = "WHERE nc.is_active=1 AND (nc.is_auto=1 OR s.is_active=1)"
        async with db.execute(
            f"""{_NODE_CONFIG_SELECT}
                {where}
                ORDER BY nc.priority ASC, nc.id ASC"""
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_subscription_node_config(node_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(f"{_NODE_CONFIG_SELECT} WHERE nc.id=?", (int(node_id),)) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def add_subscription_node_config(server_id: int, inbound_id: int, label: str = "",
                                       priority: int = 100, max_active_profiles: int = 0,
                                       connect_host: str = "") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM subscription_node_configs WHERE server_id=? AND inbound_id=?",
            (int(server_id), int(inbound_id)),
        ) as c:
            existing = await c.fetchone()
        if existing:
            await db.execute(
                """UPDATE subscription_node_configs
                   SET label=?, priority=?, max_active_profiles=?, connect_host=?, is_active=1
                   WHERE id=?""",
                (label or "", int(priority or 100), int(max_active_profiles or 0),
                 (connect_host or "").strip(), int(existing[0])),
            )
            await db.commit()
            return int(existing[0])
        cur = await db.execute(
            """INSERT INTO subscription_node_configs(server_id,inbound_id,label,priority,max_active_profiles,connect_host)
               VALUES(?,?,?,?,?,?)""",
            (int(server_id), int(inbound_id), label or "", int(priority or 100),
             int(max_active_profiles or 0), (connect_host or "").strip()),
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
    if not node or not int(node.get("is_active") or 0):
        return False
    if int(node.get("is_auto") or 0):
        return bool(await get_auto_node_candidates(node))
    if not int(node.get("server_active") or 0):
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

    # An auto node is usable as long as its pool still has at least one usable
    # member — it owns no server itself.
    if int(node.get("is_auto") or 0):
        candidates = await get_auto_node_candidates(node)
        if not candidates:
            return {"usable": False, "reason": "auto_pool_empty",
                    "label": "هیچ نود قابل استفاده‌ای در استخر خودکار نیست"}
        return {"usable": True, "reason": "ok", "label": f"قابل استفاده ({len(candidates)} سرور در استخر)"}

    if not int(node.get("server_active") or 0):
        return {"usable": False, "reason": "server_disabled", "label": "سرور این نود غیرفعال است"}

    used = await count_active_subscription_nodes_by_target(int(node["server_id"]), int(node["inbound_id"]))
    cap = int(node.get("max_active_profiles") or 0)
    if cap > 0 and used >= cap:
        return {"usable": False, "reason": "node_capacity_full", "label": f"ظرفیت نود پر است ({used}/{cap})"}
    return {"usable": True, "reason": "ok", "label": "قابل استفاده"}


# ══════════════════ AUTO NODE (نود خودکار) ══════════════════

def parse_auto_pool(raw) -> List[int]:
    """Parse the csv of candidate node-config ids. Empty = every active node."""
    out = []
    for part in str(raw or "").replace(" ", "").split(","):
        if part.isdigit() and int(part) > 0 and int(part) not in out:
            out.append(int(part))
    return out


async def add_auto_subscription_node_config(label: str = "", priority: int = 1,
                                            auto_pool: str = "", auto_show_server: int = 0,
                                            connect_host: str = "") -> int:
    """Create an auto node.

    It has no real server, but `subscription_node_configs` has a UNIQUE
    (server_id, inbound_id) and other code joins on it, so we park auto rows at
    server_id=0 with a NEGATIVE inbound_id — a value no real inbound can take,
    which keeps the constraint satisfied for several auto nodes side by side.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT MIN(inbound_id) FROM subscription_node_configs WHERE server_id=0 AND is_auto=1"
        ) as c:
            lowest = (await c.fetchone())[0]
        slot = min(-1, int(lowest or 0) - 1)
        cur = await db.execute(
            """INSERT INTO subscription_node_configs
                   (server_id,inbound_id,label,priority,max_active_profiles,connect_host,
                    is_auto,auto_pool,auto_show_server)
               VALUES(0,?,?,?,0,?,1,?,?)""",
            (slot, label or "", int(priority or 1), (connect_host or "").strip(),
             ",".join(str(i) for i in parse_auto_pool(auto_pool)), 1 if auto_show_server else 0),
        )
        await db.commit()
        return int(cur.lastrowid)


async def get_auto_node_candidates(node: Dict) -> List[Dict]:
    """Usable node configs an auto node is allowed to route users to.

    An empty pool means "every active node"; a configured pool is filtered to the
    ids that are still usable, so deleting a pool member degrades gracefully.
    """
    pool = parse_auto_pool(node.get("auto_pool"))
    out = []
    for cand in await get_subscription_node_configs(active_only=True):
        if int(cand.get("is_auto") or 0):
            continue                      # an auto node never routes to another auto node
        if pool and int(cand["id"]) not in pool:
            continue
        if await subscription_node_config_has_capacity(cand):
            out.append(cand)
    return out


async def get_auto_node_configs(active_only: bool = True) -> List[Dict]:
    return [n for n in await get_subscription_node_configs(active_only=active_only)
            if int(n.get("is_auto") or 0)]


# A client counts as "online" only if it moved bytes during the panel's last
# stats tick, so any single reading understates a server that has idle-but-
# connected users, and readings jump around between ticks. Routing on a
# smoothed value instead of the raw sample stops that noise from bouncing
# customers between servers. 0.4 keeps roughly the last three polls in view.
ONLINE_SMOOTHING = 0.4


async def set_server_online_stats(server_id: int, count: Optional[int], checked_at_ms: int) -> None:
    """Persist a server's live online count. `None` = the poll failed.

    A failed poll leaves the previous numbers untouched and only clears
    `online_ok`, so readers can tell "we don't know" from "nobody is online".
    """
    async with aiosqlite.connect(DB_PATH) as db:
        if count is None:
            await db.execute(
                "UPDATE servers SET online_ok=0, online_checked_at=? WHERE id=?",
                (int(checked_at_ms), int(server_id)),
            )
        else:
            sample = max(0, int(count))
            async with db.execute(
                "SELECT online_avg, online_ok FROM servers WHERE id=?", (int(server_id),)
            ) as c:
                row = await c.fetchone()
            # Seed the average from the first usable reading rather than easing up
            # from zero, which would make a fresh server look empty for minutes.
            if not row or not int(row[1] or 0):
                average = float(sample)
            else:
                average = ONLINE_SMOOTHING * sample + (1 - ONLINE_SMOOTHING) * float(row[0] or 0)
            await db.execute(
                """UPDATE servers SET online_count=?, online_avg=?, online_ok=1, online_checked_at=?
                   WHERE id=?""",
                (sample, round(average, 3), int(checked_at_ms), int(server_id)),
            )
        await db.commit()


async def get_profiles_with_node_config(config_id: int, limit: int = 5000) -> List[Dict]:
    """Active profiles that currently hold a client for this node config."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT p.* FROM subscription_profiles p
               JOIN subscription_nodes n ON n.profile_id=p.id
               WHERE n.config_id=? AND p.is_active=1
               GROUP BY p.id
               ORDER BY p.id
               LIMIT ?""",
            (int(config_id), max(1, int(limit))),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_auto_node_rows(config_id: int, limit: int = 5000) -> List[Dict]:
    """Active profiles already provisioned on this auto node, with their target.

    Profile columns come first so the `node_*` aliases can never be shadowed by a
    same-named column on subscription_profiles.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT p.*, n.id AS node_row_id, n.server_id AS node_server_id,
                      n.inbound_id AS node_inbound_id, n.moved_at AS node_moved_at,
                      n.is_active AS node_row_active
               FROM subscription_nodes n
               JOIN subscription_profiles p ON p.id=n.profile_id
               WHERE n.config_id=? AND p.is_active=1
               ORDER BY p.id
               LIMIT ?""",
            (int(config_id), max(1, int(limit))),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def count_auto_assignments_by_target(config_id: int) -> Dict[int, int]:
    """How many active profiles each server currently holds for this auto node."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT n.server_id, COUNT(*)
               FROM subscription_nodes n
               JOIN subscription_profiles p ON p.id=n.profile_id
               WHERE n.config_id=? AND n.is_active=1 AND p.is_active=1
               GROUP BY n.server_id""",
            (int(config_id),),
        ) as c:
            return {int(r[0]): int(r[1]) for r in await c.fetchall()}


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


# ── users: search + filter + sort (one query, stats included) ────────────────
# Sort keys are ORDER BY fragments over the aliases selected in _USER_STATS_SQL.
# Every one ends with a stable tiebreaker so paging can't drop/repeat a row.
USER_SORTS = {
    "newest":        "u.created_at DESC, u.id DESC",
    "oldest":        "u.created_at ASC, u.id ASC",
    # {coll} = the Persian collation when we can register it, NOCASE otherwise.
    "name_az":       "sort_name COLLATE {coll} ASC, u.id DESC",
    "name_za":       "sort_name COLLATE {coll} DESC, u.id DESC",
    "balance_desc":  "COALESCE(u.balance_toman,0) DESC, u.id DESC",
    "balance_asc":   "COALESCE(u.balance_toman,0) ASC, u.id DESC",
    "orders_desc":   "approved_orders DESC, u.id DESC",
    "spent_desc":    "total_spent DESC, u.id DESC",
    "services_desc": "active_services DESC, u.id DESC",
    "recent_buy":    "last_order_at DESC, u.id DESC",
}
DEFAULT_USER_SORT = "newest"

# Filter key → WHERE fragment (no params).
USER_FILTERS = {
    "all":          "",
    "rep":          "COALESCE(u.is_wholesale,0)=1",
    "rep_pending":  "COALESCE(u.wholesale_request_pending,0)=1 AND COALESCE(u.is_wholesale,0)=0",
    "admin":        "(COALESCE(u.is_admin,0)=1 OR COALESCE(u.admin_role,'none') NOT IN ('none',''))",
    "blocked":      "COALESCE(u.is_blocked,0)=1",
    "active":       "COALESCE(u.is_blocked,0)=0",
    "custom_price": ("(COALESCE(u.price_per_gb,0)>0 OR COALESCE(u.unlimited_price,0)>0 "
                     "OR COALESCE(u.discount_percent,0)>0)"),
    "has_balance":  "COALESCE(u.balance_toman,0)>0",
    "buyers":       "(SELECT COUNT(*) FROM orders o WHERE o.user_id=u.id AND o.status='approved')>0",
    "no_orders":    "(SELECT COUNT(*) FROM orders o WHERE o.user_id=u.id AND o.status='approved')=0",
}

# Registration-date window → WHERE fragment. `created_at` is 'YYYY-MM-DD HH:MM:SS'
# local time, so plain string comparison against date()/datetime() is correct.
USER_PERIODS = {
    "all":   "",
    "today": "u.created_at >= date('now','localtime')",
    "week":  "u.created_at >= date('now','localtime','-7 days')",
    "month": "u.created_at >= date('now','localtime','-30 days')",
    "year":  "u.created_at >= date('now','localtime','-365 days')",
}

# Per-user aggregates, computed inline so a page costs ONE query instead of
# get_user_business_stats() × page_size. Aliases double as sort keys.
_USER_STATS_SQL = """
    COALESCE(NULLIF(TRIM(u.full_name),''), NULLIF(TRIM(u.username),''),
             CAST(u.telegram_id AS TEXT)) AS sort_name,
    (SELECT COUNT(*) FROM orders o WHERE o.user_id=u.id AND o.status='approved') AS approved_orders,
    (SELECT COUNT(*) FROM orders o WHERE o.user_id=u.id AND o.status='pending') AS pending_orders,
    (SELECT COALESCE(SUM(COALESCE(NULLIF(o.custom_price,0), p.price, 0)),0)
       FROM orders o LEFT JOIN packages p ON p.id=o.package_id
      WHERE o.user_id=u.id AND o.status='approved') AS total_spent,
    (SELECT MAX(o.created_at) FROM orders o
      WHERE o.user_id=u.id AND o.status='approved') AS last_order_at,
    (SELECT COUNT(*) FROM configs c WHERE c.user_id=u.id) AS total_configs,
    (SELECT COUNT(*) FROM configs c WHERE c.user_id=u.id AND c.is_active=1) AS active_configs,
    (SELECT COUNT(*) FROM subscription_profiles sp WHERE sp.user_id=u.id) AS total_subs,
    (SELECT COUNT(*) FROM subscription_profiles sp
      WHERE sp.user_id=u.id AND sp.is_active=1
        AND (sp.expire_timestamp=0 OR sp.expire_timestamp > :now_ms)) AS active_subs,
    (SELECT COUNT(*) FROM configs c WHERE c.user_id=u.id AND c.is_active=1)
    + (SELECT COUNT(*) FROM subscription_profiles sp
        WHERE sp.user_id=u.id AND sp.is_active=1
          AND (sp.expire_timestamp=0 OR sp.expire_timestamp > :now_ms)) AS active_services
"""


def _user_list_where(q: str, filt: str, period: str) -> tuple[str, dict]:
    """Build the shared WHERE for list_users/count_users_filtered."""
    clauses: List[str] = []
    params: Dict = {}

    q = (q or "").strip().lstrip("@")
    if q:
        digits = q.replace(" ", "")
        if digits.isdigit():
            clauses.append("(CAST(u.telegram_id AS TEXT) LIKE :qlike OR u.id = :qid)")
            params["qlike"] = f"%{digits}%"
            params["qid"] = int(digits)
        else:
            clauses.append("(lower(COALESCE(u.username,'')) LIKE :qlike "
                           "OR lower(COALESCE(u.full_name,'')) LIKE :qlike "
                           "OR lower(COALESCE(u.rep_brand_name,'')) LIKE :qlike)")
            params["qlike"] = f"%{q.lower()}%"

    frag = USER_FILTERS.get(filt or "all", "")
    if frag:
        clauses.append(frag)
    frag = USER_PERIODS.get(period or "all", "")
    if frag:
        clauses.append(frag)

    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


async def _register_fa_collation(db) -> str:
    """Register the Persian collation on this connection so name sorts order
    the way a Persian reader expects. aiosqlite has no public wrapper for
    create_collation, so reach the raw sqlite3 connection through its executor;
    if that ever stops working we degrade to NOCASE rather than breaking the
    page. Returns the collation name to use in ORDER BY.
    """
    try:
        await db._execute(db._conn.create_collation, "FA", fa_collation)
        return "FA"
    except Exception:
        return "NOCASE"


async def list_users(q: str = "", filt: str = "all", sort: str = DEFAULT_USER_SORT,
                     period: str = "all", offset: int = 0, limit: int = 40) -> tuple[List[Dict], int]:
    """Paged user list with search/filter/sort. Returns (rows, total_matching).

    Each row carries the per-user aggregates (approved_orders, active_services,
    total_spent, …) so callers don't need get_user_business_stats() per user.
    """
    where, params = _user_list_where(q, filt, period)
    order = USER_SORTS.get(sort or "", USER_SORTS[DEFAULT_USER_SORT])
    params["now_ms"] = int(time.time() * 1000)
    params["limit"] = max(1, int(limit or 40))
    params["offset"] = max(0, int(offset or 0))

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Only name sorts carry the {coll} placeholder; format() is a no-op
        # for the rest, so registering is skipped unless it's actually needed.
        if "{coll}" in order:
            order = order.format(coll=await _register_fa_collation(db))
        async with db.execute(f"SELECT COUNT(*) FROM users u{where}", params) as c:
            total = (await c.fetchone())[0]
        async with db.execute(
            f"SELECT u.*, {_USER_STATS_SQL} FROM users u{where} "
            f"ORDER BY {order} LIMIT :limit OFFSET :offset", params
        ) as c:
            rows = [dict(r) for r in await c.fetchall()]
    return rows, total


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


async def get_user_total_topups(user_id: int) -> int:
    """Sum of all wallet credits (money the user has put in). Used to enforce a
    representative's minimum initial top-up (anti-abuse)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM wallet_transactions WHERE user_id=? AND amount>0",
            (int(user_id),),
        ) as c:
            row = await c.fetchone()
            return int((row[0] if row else 0) or 0)


async def get_wallet_transactions(user_id: int, limit: int = 12) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT amount, kind, note, created_at FROM wallet_transactions WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (int(user_id), max(1, int(limit or 12))),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


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


async def count_active_subscription_profiles() -> int:
    now_ms = int(time.time() * 1000)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM subscription_profiles WHERE is_active=1 "
            "AND (expire_timestamp=0 OR expire_timestamp>?)",
            (now_ms,),
        ) as c:
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


async def get_referral_invitees(user_id: int, limit: int = 50) -> List[Dict]:
    """The people this user invited + whether each has bought yet (transparency)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT u.full_name, u.username, u.created_at,
                      EXISTS(SELECT 1 FROM orders o WHERE o.user_id=u.id AND o.status='approved') AS bought
               FROM users u WHERE u.referred_by=?
               ORDER BY u.id DESC LIMIT ?""",
            (int(user_id), max(1, int(limit or 50))),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_referral_earned_total(user_id: int) -> int:
    """Total toman this user has earned into their wallet from referrals."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM wallet_transactions WHERE user_id=? AND kind='referral' AND amount>0",
            (int(user_id),),
        ) as c:
            return int((await c.fetchone())[0] or 0)


async def get_pending_referral_reminders(before_dt: str, limit: int = 200) -> List[Dict]:
    """Invited users who joined before `before_dt` (e.g. 24h ago), haven't bought,
    and whose inviter hasn't been reminded yet. Returns the inviter's chat id +
    code so we can nudge the inviter to send a discount to that friend."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT u.id AS invitee_id, u.full_name AS invitee_name, u.username AS invitee_username,
                      ref.telegram_id AS referrer_tid, ref.referral_code AS referrer_code
               FROM users u JOIN users ref ON ref.id = u.referred_by
               WHERE COALESCE(u.referred_by,0) > 0
                 AND COALESCE(u.referral_reminder_sent,0) = 0
                 AND u.created_at <= ?
                 AND NOT EXISTS(SELECT 1 FROM orders o WHERE o.user_id=u.id AND o.status='approved')
               ORDER BY u.id LIMIT ?""",
            (str(before_dt), max(1, int(limit or 200))),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def mark_referral_reminder_sent(invitee_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET referral_reminder_sent=1 WHERE id=?", (int(invitee_id),))
        await db.commit()


async def get_pending_referral_claims(limit: int = 100) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT rc.id, rc.referrals_at_claim, rc.created_at,
                      u.full_name, u.username, u.telegram_id,
                      t.referrals_needed, t.reward_kind, t.reward_amount, t.reward_gb, t.duration_days, t.is_unlimited, t.label
               FROM referral_claims rc
               JOIN users u ON u.id = rc.user_id
               JOIN referral_tiers t ON t.id = rc.tier_id
               WHERE rc.status='pending'
               ORDER BY rc.id DESC LIMIT ?""",
            (max(1, int(limit or 100)),),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_referral_analytics(days: int = 14) -> Dict:
    """Complete referral KPIs: reach, conversion, money in vs reward out (net),
    whether referral chains are forming, and a top-referrers leaderboard."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async def scalar(q, args=()):
            async with db.execute(q, args) as c:
                r = await c.fetchone()
                return (r[0] if r else 0) or 0

        total_referred = int(await scalar("SELECT COUNT(*) FROM users WHERE COALESCE(referred_by,0)>0"))
        active_referrers = int(await scalar("SELECT COUNT(DISTINCT referred_by) FROM users WHERE COALESCE(referred_by,0)>0"))
        converted = int(await scalar(
            "SELECT COUNT(DISTINCT u.id) FROM users u JOIN orders o ON o.user_id=u.id "
            "WHERE COALESCE(u.referred_by,0)>0 AND o.status='approved'"))
        revenue = int(await scalar(
            "SELECT COALESCE(SUM(COALESCE(NULLIF(o.custom_price,0), p.price)),0) "
            "FROM orders o JOIN users u ON u.id=o.user_id LEFT JOIN packages p ON p.id=o.package_id "
            "WHERE COALESCE(u.referred_by,0)>0 AND o.status='approved'"))
        rewards_paid = int(await scalar(
            "SELECT COALESCE(SUM(amount),0) FROM wallet_transactions WHERE kind='referral' AND amount>0"))
        pending_claims = int(await scalar("SELECT COUNT(*) FROM referral_claims WHERE status='pending'"))
        approved_claims = int(await scalar("SELECT COUNT(*) FROM referral_claims WHERE status='approved'"))
        service_gifts = int(await scalar(
            "SELECT COUNT(*) FROM referral_claims rc JOIN referral_tiers t ON t.id=rc.tier_id "
            "WHERE rc.status='approved' AND t.reward_kind='service'"))
        chain_referrers = int(await scalar(
            "SELECT COUNT(DISTINCT u.id) FROM users u WHERE COALESCE(u.referred_by,0)>0 "
            "AND EXISTS(SELECT 1 FROM users c WHERE c.referred_by=u.id)"))
        try:
            max_chain = int(await scalar(
                "WITH RECURSIVE chain(id,depth) AS ("
                " SELECT id,1 FROM users WHERE COALESCE(referred_by,0)=0"
                " UNION ALL SELECT u.id,c.depth+1 FROM users u JOIN chain c ON u.referred_by=c.id WHERE c.depth<40)"
                " SELECT COALESCE(MAX(depth),1) FROM chain"))
        except Exception:
            max_chain = 1

        top = []
        async with db.execute(
            """SELECT ref.id AS id, ref.full_name AS full_name, ref.username AS username,
                      COUNT(u.id) AS invited,
                      SUM(CASE WHEN EXISTS(SELECT 1 FROM orders o WHERE o.user_id=u.id AND o.status='approved') THEN 1 ELSE 0 END) AS converted,
                      (SELECT COALESCE(SUM(amount),0) FROM wallet_transactions wt WHERE wt.user_id=ref.id AND wt.kind='referral' AND wt.amount>0) AS earned
               FROM users ref JOIN users u ON u.referred_by=ref.id
               GROUP BY ref.id ORDER BY converted DESC, invited DESC LIMIT 20"""
        ) as c:
            top = [dict(r) for r in await c.fetchall()]

        async with db.execute(
            "SELECT date(created_at) d, COUNT(*) c FROM users "
            "WHERE COALESCE(referred_by,0)>0 AND date(created_at) >= date('now', ?, 'localtime') "
            "GROUP BY date(created_at)",
            (f"-{max(1, int(days)) - 1} days",),
        ) as c:
            ts = {r["d"]: int(r["c"]) for r in await c.fetchall()}

    series = []
    today = datetime.now()
    for i in range(max(1, int(days)) - 1, -1, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        series.append({"date": d, "count": ts.get(d, 0)})

    return {
        "total_referred": total_referred,
        "active_referrers": active_referrers,
        "converted": converted,
        "conversion_rate": round(converted / total_referred * 100, 1) if total_referred else 0.0,
        "revenue": revenue,
        "rewards_paid": rewards_paid,
        "net": revenue - rewards_paid,
        "profitable": (revenue - rewards_paid) > 0,
        "pending_claims": pending_claims,
        "approved_claims": approved_claims,
        "service_gifts": service_gifts,
        "chain_referrers": chain_referrers,
        "max_chain": max_chain,
        "chain_forms": max_chain >= 3 or chain_referrers > 0,
        "top": top,
        "series": series,
    }


# ══════════════════ CAMPAIGNS / ANALYTICS ══════════════════

async def log_campaign_event(campaign: str, kind: str = "sent", user_id: int = 0, order_id: int = 0, amount: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO campaign_events(campaign,kind,user_id,order_id,amount) VALUES(?,?,?,?,?)",
            ((campaign or "").strip(), kind, int(user_id or 0), int(order_id or 0), int(amount or 0)),
        )
        await db.commit()


async def get_campaign_overview() -> List[Dict]:
    """Per-campaign performance: sends, conversions (code redemptions), revenue,
    discount given, conversion rate."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sends: Dict[str, int] = {}
        async with db.execute("SELECT campaign, COUNT(*) c FROM campaign_events WHERE kind='sent' GROUP BY campaign") as c:
            for r in await c.fetchall():
                sends[r["campaign"]] = int(r["c"])
        agg: Dict[str, Dict] = {}
        async with db.execute(
            """SELECT dc.campaign AS campaign, COUNT(dr.id) AS conv,
                      COALESCE(SUM(dr.amount),0) AS discount,
                      COALESCE(SUM(o.custom_price),0) AS revenue
               FROM discount_redemptions dr
               JOIN discount_codes dc ON dc.id = dr.code_id
               LEFT JOIN orders o ON o.id = dr.order_id AND o.status='approved'
               WHERE COALESCE(dc.campaign,'') != ''
               GROUP BY dc.campaign"""
        ) as c:
            for r in await c.fetchall():
                agg[r["campaign"]] = {"conversions": int(r["conv"]), "discount": int(r["discount"]), "revenue": int(r["revenue"])}
        out = []
        for name in sorted(set(list(sends.keys()) + list(agg.keys()))):
            a = agg.get(name, {})
            sent = sends.get(name, 0)
            conv = int(a.get("conversions", 0))
            out.append({
                "campaign": name,
                "sent": sent,
                "conversions": conv,
                "revenue": int(a.get("revenue", 0)),
                "discount": int(a.get("discount", 0)),
                "rate": round(conv / sent * 100, 1) if sent else 0.0,
            })
        out.sort(key=lambda x: x["revenue"], reverse=True)
        return out


async def get_revenue_timeseries(days: int = 14) -> List[Dict]:
    """Daily approved-order revenue for the last N days (gaps filled with zero)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT date(o.approved_at) AS d,
                      COALESCE(SUM(COALESCE(NULLIF(o.custom_price,0), p.price)),0) AS rev,
                      COUNT(*) AS cnt
               FROM orders o LEFT JOIN packages p ON p.id = o.package_id
               WHERE o.status='approved' AND o.approved_at IS NOT NULL
                 AND date(o.approved_at) >= date('now', ?, 'localtime')
               GROUP BY date(o.approved_at)""",
            (f"-{max(1, int(days)) - 1} days",),
        ) as c:
            rows = {r["d"]: {"rev": int(r["rev"]), "cnt": int(r["cnt"])} for r in await c.fetchall()}
    out = []
    today = datetime.now()
    for i in range(max(1, int(days)) - 1, -1, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        v = rows.get(d, {"rev": 0, "cnt": 0})
        out.append({"date": d, "revenue": v["rev"], "orders": v["cnt"]})
    return out


async def get_new_users_timeseries(days: int = 30) -> List[Dict]:
    """Daily new-user counts for the last N days (gaps filled with zero)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT date(created_at) AS d, COUNT(*) AS cnt
               FROM users
               WHERE date(created_at) >= date('now', ?, 'localtime')
               GROUP BY date(created_at)""",
            (f"-{max(1, int(days)) - 1} days",),
        ) as c:
            rows = {r["d"]: int(r["cnt"]) for r in await c.fetchall()}
    out = []
    today = datetime.now()
    for i in range(max(1, int(days)) - 1, -1, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        out.append({"date": d, "new_users": rows.get(d, 0)})
    return out


async def get_expiring_profiles(within_days: int = 3, limit: int = 100) -> List[Dict]:
    """Active subscriptions expiring within the next `within_days` days."""
    now_ms = int(time.time() * 1000)
    until_ms = now_ms + int(within_days) * 86400000
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT sp.id, sp.name, sp.expire_timestamp, sp.traffic_gb, sp.used_bytes,
                      u.telegram_id, u.username, u.full_name
               FROM subscription_profiles sp JOIN users u ON u.id=sp.user_id
               WHERE sp.is_active=1 AND sp.expire_timestamp>? AND sp.expire_timestamp<=?
               ORDER BY sp.expire_timestamp ASC LIMIT ?""",
            (now_ms, until_ms, int(limit)),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def count_expiring_profiles(within_days: int = 3) -> int:
    now_ms = int(time.time() * 1000)
    until_ms = now_ms + int(within_days) * 86400000
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM subscription_profiles WHERE is_active=1 "
            "AND expire_timestamp>? AND expire_timestamp<=?",
            (now_ms, until_ms),
        ) as c:
            return (await c.fetchone())[0]


async def get_online_users_by_emails(emails: List[str]) -> List[Dict]:
    """Map a set of currently-online client emails back to users (deduped).

    Matches both subscription node clients (subscription_nodes) and legacy single
    configs (configs). Returns one row per user with how many of their connections
    are online right now."""
    emails = [e for e in (emails or []) if e]
    if not emails:
        return []
    ph = ",".join("?" for _ in emails)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""SELECT u.id, u.telegram_id, u.username, u.full_name,
                       COUNT(DISTINCT src.email) AS online_conns
                FROM (
                    SELECT n.email AS email, sp.user_id AS user_id
                    FROM subscription_nodes n
                    JOIN subscription_profiles sp ON sp.id=n.profile_id
                    WHERE n.email IN ({ph})
                    UNION ALL
                    SELECT c.email AS email, c.user_id AS user_id
                    FROM configs c WHERE c.email IN ({ph})
                ) src
                JOIN users u ON u.id=src.user_id
                GROUP BY u.id ORDER BY online_conns DESC, u.id DESC""",
            (*emails, *emails),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_top_buyers(limit: int = 30) -> List[Dict]:
    """Users ranked by total approved spend."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT u.id, u.telegram_id, u.username, u.full_name, u.balance_toman,
                      COUNT(o.id) AS orders,
                      COALESCE(SUM(COALESCE(NULLIF(o.custom_price,0), p.price)),0) AS spent
               FROM orders o JOIN users u ON u.id=o.user_id
               LEFT JOIN packages p ON p.id=o.package_id
               WHERE o.status='approved'
               GROUP BY o.user_id ORDER BY spent DESC LIMIT ?""",
            (int(limit),),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_rep_financials(user_id: int) -> Dict:
    """Financial summary for a representative: total & monthly spend, order count,
    and service counts (active/expired). Spend = sum of approved orders."""
    now_ms = int(time.time() * 1000)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT COALESCE(SUM(COALESCE(NULLIF(o.custom_price,0), p.price, 0)),0) AS total,
                      COUNT(o.id) AS orders
               FROM orders o LEFT JOIN packages p ON p.id=o.package_id
               WHERE o.user_id=? AND o.status='approved'""",
            (user_id,),
        ) as c:
            r = await c.fetchone()
            total_spent = int(r["total"] or 0)
            orders = int(r["orders"] or 0)
        async with db.execute(
            """SELECT COALESCE(SUM(COALESCE(NULLIF(o.custom_price,0), p.price, 0)),0) AS m
               FROM orders o LEFT JOIN packages p ON p.id=o.package_id
               WHERE o.user_id=? AND o.status='approved'
                 AND o.created_at >= date('now','start of month','localtime')""",
            (user_id,),
        ) as c:
            month_spent = int((await c.fetchone())["m"] or 0)
        async with db.execute(
            "SELECT COUNT(*) AS n FROM subscription_profiles WHERE user_id=?", (user_id,),
        ) as c:
            total_services = int((await c.fetchone())["n"] or 0)
        async with db.execute(
            """SELECT COUNT(*) AS n FROM subscription_profiles
               WHERE user_id=? AND is_active=1 AND (expire_timestamp=0 OR expire_timestamp>?)""",
            (user_id, now_ms),
        ) as c:
            active_services = int((await c.fetchone())["n"] or 0)
        return {
            "total_spent": total_spent, "month_spent": month_spent, "orders": orders,
            "total_services": total_services, "active_services": active_services,
            "expired_services": max(0, total_services - active_services),
        }


async def get_rep_purchases(user_id: int, since: Optional[str] = None,
                            until: Optional[str] = None, limit: int = 5000) -> Dict:
    """Everything a representative bought in a date window, service by service.

    `since`/`until` are inclusive `'YYYY-MM-DD HH:MM:SS'` bounds in the SAME
    local-time frame the `created_at` columns are written in (build them with
    core.jalali.tehran_to_db_string so a Jalali range lands on the right rows).

    Two kinds of purchase are reported, because a rep's revenue is both:
      • new services  — one row per subscription profile, which is the unit the
        customer actually holds (a bulk order of 10 produces 10 rows, each with
        its own name and dates — that is what makes the export usable as proof);
      • renewals      — orders that topped up an existing service and so create
        no new profile of their own.

    The per-row price of a bulk order is divided by its service count, so the
    rows sum to what was actually charged instead of counting the order N times.
    """
    where = ["sp.user_id=?"]
    args: List = [int(user_id)]
    if since:
        where.append("sp.created_at>=?")
        args.append(since)
    if until:
        where.append("sp.created_at<=?")
        args.append(until)

    order_where = ["o.user_id=?", "o.status='approved'"]
    order_args: List = [int(user_id)]
    if since:
        order_where.append("o.created_at>=?")
        order_args.append(since)
    if until:
        order_where.append("o.created_at<=?")
        order_args.append(until)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            f"""SELECT sp.id, sp.name, sp.traffic_gb, sp.duration_days, sp.created_at,
                       sp.first_use_at, sp.expire_timestamp, sp.is_active, sp.used_bytes,
                       sp.order_id,
                       o.approved_at AS order_approved_at,
                       o.custom_config_name AS order_name,
                       MAX(COALESCE(NULLIF(o.bulk_count,0),1), 1) AS bulk_count,
                       COALESCE(NULLIF(o.custom_price,0), p.price, 0) AS order_price,
                       COALESCE(p.name,'') AS package_name,
                       COALESCE(p.is_unlimited,0) AS pkg_unlimited
                FROM subscription_profiles sp
                LEFT JOIN orders o ON o.id=sp.order_id
                LEFT JOIN packages p ON p.id=o.package_id
                WHERE {' AND '.join(where)}
                ORDER BY sp.created_at DESC, sp.id DESC
                LIMIT ?""",
            (*args, max(1, int(limit))),
        ) as c:
            profile_rows = [dict(r) for r in await c.fetchall()]

        async with db.execute(
            f"""SELECT o.id AS order_id, o.created_at, o.approved_at AS order_approved_at,
                       COALESCE(NULLIF(o.custom_price,0), p.price, 0) AS order_price,
                       COALESCE(NULLIF(o.custom_traffic_gb,0), p.traffic_gb, 0) AS traffic_gb,
                       COALESCE(NULLIF(o.custom_duration_days,0), p.duration_days, 0) AS duration_days,
                       COALESCE(p.is_unlimited,0) AS pkg_unlimited,
                       COALESCE(NULLIF(o.custom_config_name,''), sp.name, cfg.email, '') AS name,
                       sp.expire_timestamp, sp.first_use_at, sp.is_active
                FROM orders o
                LEFT JOIN packages p ON p.id=o.package_id
                LEFT JOIN subscription_profiles sp ON sp.id=o.renew_sub_profile_id
                LEFT JOIN configs cfg ON cfg.id=o.renew_config_id
                WHERE {' AND '.join(order_where)}
                  AND (COALESCE(o.renew_sub_profile_id,0)>0 OR COALESCE(o.renew_config_id,0)>0)
                ORDER BY o.created_at DESC
                LIMIT ?""",
            (*order_args, max(1, int(limit))),
        ) as c:
            renewal_rows = [dict(r) for r in await c.fetchall()]

        # Spend is summed over DISTINCT orders — never over the service rows, or a
        # bulk order would be counted once per service it produced.
        async with db.execute(
            f"""SELECT COUNT(*) AS n,
                       COALESCE(SUM(COALESCE(NULLIF(o.custom_price,0), p.price, 0)),0) AS total
                FROM orders o LEFT JOIN packages p ON p.id=o.package_id
                WHERE {' AND '.join(order_where)}""",
            tuple(order_args),
        ) as c:
            money = await c.fetchone()

        legacy_where = ["user_id=?"]
        legacy_args: List = [int(user_id)]
        if since:
            legacy_where.append("created_at>=?")
            legacy_args.append(since)
        if until:
            legacy_where.append("created_at<=?")
            legacy_args.append(until)
        async with db.execute(
            f"SELECT COUNT(*) FROM configs WHERE {' AND '.join(legacy_where)}", tuple(legacy_args),
        ) as c:
            legacy_configs = int((await c.fetchone())[0] or 0)

    items: List[Dict] = []
    for row in profile_rows:
        bulk = max(1, int(row.get("bulk_count") or 1))
        traffic = float(row.get("traffic_gb") or 0)
        items.append({
            "kind": "purchase",
            "profile_id": int(row["id"]),
            "order_id": int(row.get("order_id") or 0),
            "name": (str(row.get("name") or "").strip()
                     or str(row.get("order_name") or "").strip()
                     or str(row.get("package_name") or "").strip()
                     or f"سرویس #{row['id']}"),
            "traffic_gb": traffic,
            "is_unlimited": bool(int(row.get("pkg_unlimited") or 0)) or traffic <= 0,
            "duration_days": int(row.get("duration_days") or 0),
            "price": int(round(int(row.get("order_price") or 0) / bulk)),
            "bulk_count": bulk,
            "purchased_at": row.get("created_at"),
            "approved_at": row.get("order_approved_at"),
            "started_at": int(row.get("first_use_at") or 0),
            "expires_at": int(row.get("expire_timestamp") or 0),
            "used_bytes": int(row.get("used_bytes") or 0),
            "is_active": int(row.get("is_active") or 0),
        })
    for row in renewal_rows:
        traffic = float(row.get("traffic_gb") or 0)
        items.append({
            "kind": "renewal",
            "profile_id": 0,
            "order_id": int(row.get("order_id") or 0),
            "name": str(row.get("name") or "").strip() or f"تمدید سفارش #{row.get('order_id')}",
            "traffic_gb": traffic,
            "is_unlimited": bool(int(row.get("pkg_unlimited") or 0)) or traffic <= 0,
            "duration_days": int(row.get("duration_days") or 0),
            "price": int(row.get("order_price") or 0),
            "bulk_count": 1,
            "purchased_at": row.get("created_at"),
            "approved_at": row.get("order_approved_at"),
            "started_at": int(row.get("first_use_at") or 0),
            "expires_at": int(row.get("expire_timestamp") or 0),
            "used_bytes": 0,
            "is_active": int(row.get("is_active") or 0),
        })
    items.sort(key=lambda it: (str(it.get("purchased_at") or ""), it.get("order_id") or 0), reverse=True)

    measured = [it for it in items if not it["is_unlimited"]]
    return {
        "items": items,
        "summary": {
            "services": sum(1 for it in items if it["kind"] == "purchase"),
            "renewals": sum(1 for it in items if it["kind"] == "renewal"),
            "total_gb": round(sum(it["traffic_gb"] for it in measured), 2),
            "unlimited_count": len(items) - len(measured),
            "orders": int(money["n"] or 0),
            "total_spent": int(money["total"] or 0),
            "legacy_configs": legacy_configs,
        },
    }


async def get_top_active_service_users(limit: int = 30) -> List[Dict]:
    """Users ranked by number of currently-active subscriptions."""
    now_ms = int(time.time() * 1000)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT u.id, u.telegram_id, u.username, u.full_name,
                      COUNT(sp.id) AS active_services
               FROM subscription_profiles sp JOIN users u ON u.id=sp.user_id
               WHERE sp.is_active=1 AND (sp.expire_timestamp=0 OR sp.expire_timestamp>?)
               GROUP BY sp.user_id ORDER BY active_services DESC, u.id DESC LIMIT ?""",
            (now_ms, int(limit)),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_lapsed_users_for_winback(expired_before_ms: int, limit: int = 200) -> List[Dict]:
    """Users whose newest service ended before `expired_before_ms`, have nothing
    active now, and haven't been win-backed yet."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT u.id, u.telegram_id, u.full_name FROM users u
               WHERE COALESCE(u.winback_sent,0)=0 AND u.telegram_id>0 AND COALESCE(u.is_blocked,0)=0
                 AND EXISTS(SELECT 1 FROM subscription_profiles sp WHERE sp.user_id=u.id AND sp.expire_timestamp>0 AND sp.expire_timestamp<=?)
                 AND NOT EXISTS(SELECT 1 FROM subscription_profiles s2 WHERE s2.user_id=u.id AND s2.is_active=1)
               ORDER BY u.id LIMIT ?""",
            (int(expired_before_ms), max(1, int(limit or 200))),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def mark_winback_sent(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET winback_sent=1 WHERE id=?", (int(user_id),))
        await db.commit()


async def get_trial_followups(created_before: str, limit: int = 200) -> List[Dict]:
    """Users whose free trial has ended (created before cutoff), no approved
    purchase yet, not yet nudged."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT u.id, u.telegram_id, u.full_name FROM test_accounts ta
               JOIN users u ON u.id = ta.user_id
               WHERE COALESCE(u.trial_followup_sent,0)=0 AND u.telegram_id>0 AND COALESCE(u.is_blocked,0)=0
                 AND ta.created_at <= ?
                 AND NOT EXISTS(SELECT 1 FROM orders o WHERE o.user_id=u.id AND o.status='approved')
               ORDER BY u.id LIMIT ?""",
            (str(created_before), max(1, int(limit or 200))),
        ) as c:
            return [dict(r) for r in await c.fetchall()]


async def mark_trial_followup_sent(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET trial_followup_sent=1 WHERE id=?", (int(user_id),))
        await db.commit()


async def reset_campaign_flag(flag: str) -> int:
    """Admin: clear a campaign's per-user 'sent' flag to allow a fresh run."""
    col = {"winback": "winback_sent", "trial2paid": "trial_followup_sent"}.get(flag)
    if not col:
        return 0
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(f"UPDATE users SET {col}=0 WHERE {col}=1")
        await db.commit()
        return cur.rowcount or 0


# ══════════════════ CUSTOM (TARGETED) CAMPAIGNS ══════════════════
# One-shot promotional blasts managed from the panel's Campaigns tab. Each row is
# a full campaign: audience segment + message + optional photo/discount code.
# The slug ties three tables together: campaign_events (sends), discount_codes
# .campaign (attribution + targeted-code lock) and this table.

CUSTOM_SEGMENTS = {
    "all":          "همه کاربران",
    "buyers":       "خریداران (حداقل یک خرید موفق)",
    "non_buyers":   "بدون خرید (عضو شده ولی هرگز نخریده)",
    "lapsed":       "ریزش‌کرده (سرویس داشته، الان هیچ سرویس فعالی ندارد)",
    "active_subs":  "دارای اشتراک فعال",
    "expiring_7d":  "انقضای سرویس طی ۷ روز آینده",
    "trial_no_buy": "تست رایگان گرفته ولی هنوز نخریده",
    "reps":         "نمایندگان",
    "vip":          "مشتریان VIP (۱۵ خریدار برتر)",
}

_SEG_BASE = "u.telegram_id>0 AND COALESCE(u.is_blocked,0)=0"
_SEG_HAS_BOUGHT = "EXISTS(SELECT 1 FROM orders o WHERE o.user_id=u.id AND o.status='approved')"
_SEG_ACTIVE_SUB = ("EXISTS(SELECT 1 FROM subscription_profiles sp WHERE sp.user_id=u.id "
                   "AND sp.is_active=1 AND (sp.expire_timestamp=0 OR sp.expire_timestamp>{now}))")


async def get_segment_users(segment: str, limit: int = 5000) -> List[Dict]:
    """Resolve a CUSTOM_SEGMENTS key to its current audience (id, telegram_id, full_name)."""
    now_ms = int(time.time() * 1000)
    active = _SEG_ACTIVE_SUB.format(now=now_ms)
    base = f"SELECT u.id, u.telegram_id, u.full_name FROM users u WHERE {_SEG_BASE}"
    params: tuple = ()
    if segment == "vip":
        sql = f"""SELECT u.id, u.telegram_id, u.full_name,
                         SUM(COALESCE(NULLIF(o.custom_price,0), p.price, 0)) AS spent
                  FROM users u
                  JOIN orders o ON o.user_id=u.id AND o.status='approved'
                  LEFT JOIN packages p ON p.id=o.package_id
                  WHERE {_SEG_BASE}
                  GROUP BY u.id ORDER BY spent DESC LIMIT 15"""
    elif segment == "buyers":
        sql = f"{base} AND {_SEG_HAS_BOUGHT}"
    elif segment == "non_buyers":
        sql = f"{base} AND NOT {_SEG_HAS_BOUGHT}"
    elif segment == "lapsed":
        sql = (f"{base} AND EXISTS(SELECT 1 FROM subscription_profiles sp WHERE sp.user_id=u.id)"
               f" AND NOT {active}")
    elif segment == "active_subs":
        sql = f"{base} AND {active}"
    elif segment == "expiring_7d":
        sql = (f"{base} AND EXISTS(SELECT 1 FROM subscription_profiles sp WHERE sp.user_id=u.id"
               f" AND sp.is_active=1 AND sp.expire_timestamp>? AND sp.expire_timestamp<=?)")
        params = (now_ms, now_ms + 7 * 86400000)
    elif segment == "trial_no_buy":
        sql = (f"{base} AND EXISTS(SELECT 1 FROM test_accounts ta WHERE ta.user_id=u.id)"
               f" AND NOT {_SEG_HAS_BOUGHT}")
    elif segment == "reps":
        sql = f"{base} AND COALESCE(u.is_wholesale,0)=1"
    else:  # "all" and unknown keys fall back to everyone
        sql = base
    if segment != "vip":
        sql += f" ORDER BY u.id LIMIT {max(1, int(limit))}"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as c:
            return [dict(r) for r in await c.fetchall()]


async def get_segment_counts() -> Dict[str, int]:
    """Audience size per segment (shown in the panel's segment picker)."""
    out = {}
    for key in CUSTOM_SEGMENTS:
        out[key] = len(await get_segment_users(key))
    return out


async def get_custom_campaigns() -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM custom_campaigns ORDER BY status='sent', id") as c:
            return [dict(r) for r in await c.fetchall()]


async def get_custom_campaign(cid: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM custom_campaigns WHERE id=?", (int(cid),)) as c:
            r = await c.fetchone()
            return dict(r) if r else None


async def save_custom_campaign(data: Dict) -> int:
    """Insert (no id) or update (with id) a campaign. Returns the row id."""
    fields = ("title", "emoji", "segment", "message", "photo", "code", "image_prompt", "notes")
    vals = {k: str(data.get(k) or "") for k in fields}
    if vals["segment"] not in CUSTOM_SEGMENTS:
        vals["segment"] = "all"
    cid = int(data.get("id") or 0)
    async with aiosqlite.connect(DB_PATH) as db:
        if cid:
            sets = ",".join(f"{k}=?" for k in fields)
            await db.execute(f"UPDATE custom_campaigns SET {sets} WHERE id=?", (*vals.values(), cid))
        else:
            slug = (str(data.get("slug") or "").strip() or f"cc{int(time.time())}")
            cur = await db.execute(
                f"""INSERT INTO custom_campaigns(slug,{','.join(fields)}) VALUES(?,?,?,?,?,?,?,?,?)""",
                (slug, *vals.values()),
            )
            cid = int(cur.lastrowid)
        await db.commit()
        return cid


async def delete_custom_campaign(cid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM custom_campaigns WHERE id=?", (int(cid),))
        await db.commit()


async def mark_custom_campaign_sent(cid: int, sent_count: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE custom_campaigns SET status='sent', sent_count=sent_count+?,
               sent_at=datetime('now','localtime') WHERE id=?""",
            (int(sent_count), int(cid)),
        )
        await db.commit()


# Campaigns designed from the shop's own sales data (churn, trial conversion,
# package mix, buying hours). Seeded once as DRAFTS — nothing sends by itself.
_SEED_CAMPAIGNS: List[Dict] = [
    {
        "slug": "winback_blast", "emoji": "💜", "segment": "lapsed", "code": "COMEBACK30",
        "title": "بازگشت بزرگ — ۳۰٪ تخفیف ریزشی‌ها",
        "message": (
            "{name} عزیز، جای تو توی {brand} حسابی خالیه! 💜\n\n"
            "از آخرین سرویست مدتی می‌گذره و این مدت کلی بهتر شدیم:\n"
            "⚡️ سرورهای جدید با پایداری بالاتر\n"
            "🌐 یک لینک، چند سرور پشتیبان — قطعی تقریباً صفر\n"
            "📱 مینی‌اپ داخل تلگرام برای مدیریت راحت سرویس\n\n"
            "برای برگشتنت یک هدیه ویژه گذاشتیم:\n"
            "🎁 کد {code} → ۳۰٪ تخفیف خرید بعدی\n\n"
            "⏳ این کد مخصوص شماست و همیشگی نیست!\n"
            "🛒 منوی ربات → «خرید سرویس» → موقع پرداخت کد را وارد کن."
        ),
        "image_prompt": (
            "Premium Telegram promo, square 1:1 (1080x1080). A glowing violet doorway opening in a "
            "dark navy (#0d1024) scene, warm golden light spilling out, a small gift box with cyan "
            "ribbon floating mid-air toward the viewer, subtle Persian geometric pattern in the "
            "background shadows, huge glowing neon '30%' numeral above the door. Modern 3D render, "
            "cinematic rim lighting, electric violet + cyan accents, shallow depth of field, "
            "no other text anywhere."
        ),
        "notes": (
            "چرا: ۷۳ کاربر ریزشی داری و فقط ۱۶ اشتراک فعال — بزرگ‌ترین درآمد خفته همین‌جاست. "
            "کد COMEBACK30 قفل‌شده به همین کمپین است (فقط دریافت‌کننده‌ها می‌توانند استفاده کنند). "
            "بهترین زمان ارسال: ساعت ۱۵ تا ۱۹ (اوج خرید طبق داده خودت). "
            "KPI: نرخ تبدیل ۱۰٪ = حدود ۷ برگشتی؛ با میانگین سبد ~۲۱۰ هزار تومان یعنی +۱.۵ میلیون. "
            "۴۸ ساعت بعد از ارسال، به جواب‌نداده‌ها دستی پیگیری نده — کمپین winback خودکار ادامه می‌دهد."
        ),
    },
    {
        "slug": "flash_sale", "emoji": "🔥", "segment": "all", "code": "FLASH20",
        "title": "فلش‌سیل ۴۸ ساعته",
        "message": (
            "🔥 فلش‌سیل ۴۸ ساعته {brand} شروع شد!\n\n"
            "فقط ۴۸ ساعت، روی همه پلن‌ها:\n"
            "🎟 کد {code} → ۲۰٪ تخفیف\n\n"
            "♾️ پیشنهاد داغ: پلن «نامحدود یک‌ماهه» — محبوب‌ترین پلن ما — با این کد "
            "به‌صرفه‌تر از همیشه در می‌آید.\n\n"
            "⏰ تایمر روشن شد؛ بعد از ۴۸ ساعت کد می‌سوزد.\n"
            "🛒 منوی ربات → «خرید سرویس» → کد را موقع پرداخت وارد کن."
        ),
        "image_prompt": (
            "High-energy flash-sale visual, square 1:1 (1080x1080). A massive electric lightning bolt "
            "striking a glossy dark glass surface, neon shockwaves in violet and cyan, a futuristic "
            "digital countdown hourglass glowing hot orange, sparks and light particles, dark navy "
            "background (#0d1024), huge neon numeral '48' with a small 'H' beside it as the only text. "
            "Modern 3D render, cinematic lighting, dramatic contrast, premium tech aesthetic."
        ),
        "notes": (
            "چرا: فروش ماه اخیر نصف ماه قبلش بوده؛ فلش‌سیل بهترین شوک کوتاه‌مدت است. "
            "کد FLASH20 عمومی است و «غیرفعال» ساخته شده — قبل از ارسال از تب تخفیف‌ها فعالش کن "
            "و دقیقاً ۴۸ ساعت بعد خاموشش کن (اعتبار حرفت را نگه دار). "
            "همین بنر را هم‌زمان در کانال @atlas_account بگذار تا غیرعضوها هم ببینند. "
            "بهترین شروع: پنجشنبه ساعت ۱۵. هر فصل حداکثر ۲-۳ بار — زیاد تکرارش کنی، عادت می‌شود و "
            "کسی دیگر با قیمت کامل نمی‌خرد."
        ),
    },
    {
        "slug": "renewal_save", "emoji": "⏳", "segment": "expiring_7d", "code": "RENEW15",
        "title": "نجات تمدید — قبل از قطعی",
        "message": (
            "⏳ {name} عزیز، سرویس تو همین روزها تمام می‌شود!\n\n"
            "برای اینکه حتی یک لحظه هم آفلاین نشوی، همین حالا تمدید کن:\n"
            "🎟 کد {code} → ۱۵٪ تخفیف تمدید زودهنگام\n\n"
            "🔁 منوی ربات → «وضعیت سرویس» → تمدید\n"
            "یادت باشد: بعد از انقضا، این تخفیف هم می‌پرد 😉"
        ),
        "image_prompt": (
            "Urgency renewal visual, square 1:1 (1080x1080). A sleek futuristic hourglass with "
            "glowing cyan sand almost run out, wrapped by a luminous violet circular renewal arrow "
            "(refresh loop) that radiates fresh energy, dark navy background (#0d1024), floating "
            "clock shards dissolving into light particles, large neon '15%' numeral, modern 3D "
            "render, cinematic product lighting, premium tech aesthetic, no other text."
        ),
        "notes": (
            "چرا: فقط ۴٪ سفارش‌هایت «تمدید» است — مشتری منقضی می‌شود و بعد شاید برگردد، شاید نه. "
            "این کمپین را هفته‌ای یک‌بار روی سگمنت «انقضای ۷ روز آینده» اجرا کن (هر کاربر فقط یک‌بار پیام می‌گیرد). "
            "ربات پیام هشدار خودکار هم دارد؛ این پیام مکمل آن است چون «تخفیف» دارد و انگیزه می‌سازد. "
            "KPI: نرخ تمدید را از ۴٪ به ۳۰٪+ برسان — ارزش طول عمر مشتری (LTV) را چند برابر می‌کند."
        ),
    },
    {
        "slug": "trial_push", "emoji": "🧪", "segment": "non_buyers", "code": "",
        "title": "تست رایگان — بدون ریسک",
        "message": (
            "{name} عزیز 👋\n\n"
            "هنوز {brand} را امتحان نکرده‌ای؟!\n"
            "🎁 یک سرویس تست کاملاً رایگان منتظرته — بدون پرداخت، بدون شرط.\n\n"
            "⚡️ سرعت و پایداری را خودت بسنج؛ راضی بودی، بعداً خرید کن.\n"
            "بیشترِ کسانی که تست می‌گیرند، می‌مانند 😎\n\n"
            "🧪 منوی ربات → «تست رایگان» — همین حالا فعالش کن."
        ),
        "image_prompt": (
            "Friendly free-trial visual, square 1:1 (1080x1080). A translucent glass gift box "
            "opening with a soft explosion of cyan light, a glowing shield with a wifi symbol "
            "floating above it, gentle violet aurora ribbons, dark navy background (#0d1024), "
            "sparkling particles, a glowing 'FREE' tag hanging from the box as the only text, "
            "modern 3D render, soft cinematic lighting, inviting and safe mood."
        ),
        "notes": (
            "چرا: ۷۴٪ کسانی که تست گرفته‌اند خریده‌اند (۲۰ از ۲۷) — ولی فقط ۲۷ نفر تست گرفته‌اند! "
            "۵۵ کاربر عضو شده‌اند و هرگز نخریده‌اند؛ این پیام دقیقاً به آن‌ها می‌رود. "
            "پیشنهاد: حجم تست را از ۰.۲ گیگ به ۱ گیگ ببر تا کاربر واقعاً کیفیت را حس کند — "
            "با نرخ تبدیل ۷۴٪، هر تست تقریباً یک مشتری است. "
            "بعد از این کمپین، اتوماسیون «تست→خرید» (کد NewBuy20) خودش پیگیری می‌کند."
        ),
    },
    {
        "slug": "referral_push", "emoji": "🎁", "segment": "buyers", "code": "",
        "title": "احیای دعوت دوستان",
        "message": (
            "💎 {name} عزیز، با {brand} اینترنت رایگان بگیر!\n\n"
            "لینک دعوت اختصاصی‌ات توی منوی «دعوت دوستان» است.\n"
            "دوستانت که با لینک تو بیایند و بخرند:\n\n"
            "🎁 ۳ دعوت → ۳۰ هزار تومان اعتبار کیف پول\n"
            "💰 ۶ دعوت → ۸۰ هزار تومان اعتبار\n"
            "🏆 ۱۰ دعوت → یک ماه سرویس نامحدود رایگان\n"
            "👑 ۲۰ دعوت → سه ماه سرویس نامحدود رایگان\n\n"
            "لینکت را در گروه دوستانه، پیج و استوری‌ات بفرست 🚀\n"
            "🎁 منوی ربات → «دعوت دوستان»"
        ),
        "image_prompt": (
            "Referral program visual, square 1:1 (1080x1080). Three stylized glowing avatars "
            "connected by luminous threads of violet and cyan light forming a network, gift boxes "
            "and gold coins orbiting the connections, one avatar wearing a tiny golden crown, dark "
            "navy background (#0d1024) with subtle Persian star-pattern, floating sparkles, modern "
            "3D render, warm friendly lighting, no text anywhere."
        ),
        "notes": (
            "چرا: فقط ۳ کاربر با معرفی آمده‌اند — سیستم ریفرال کاملاً خوابیده در حالی که پلکان جایزه "
            "خوبی تعریف کرده‌ای. در بازار VPN ایران، دهان‌به‌دهان (گروه‌های دوستانه/خانوادگی) "
            "ارزان‌ترین کانال جذب است؛ هر مشتری راضی به‌طور طبیعی ۲-۳ نفر «هم‌نیاز» می‌شناسد. "
            "این پیام را ماهی یک‌بار به خریداران یادآوری کن. ایده تکمیلی: به معرفی‌شده هم "
            "یک هدیه کوچک بده (مثلاً ۱۰٪ اولین خرید) تا لینک‌ها راحت‌تر پخش شوند."
        ),
    },
    {
        "slug": "vip_thanks", "emoji": "👑", "segment": "vip", "code": "VIP20",
        "title": "قدردانی VIP — مشتریان طلایی",
        "message": (
            "{name} عزیز؛ شما جزو مشتریان طلایی {brand} هستید 👑\n\n"
            "بابت اعتماد و همراهی‌ات، یک هدیه اختصاصی داریم که برای همه ارسال نمی‌شود:\n"
            "🎟 کد {code} → ۲۰٪ تخفیف — تا ۳ بار قابل استفاده\n\n"
            "💼 راستی: اگر برای دوستان یا مشتری‌های خودت هم سرویس تهیه می‌کنی، "
            "پنل نمایندگی با قیمت عمده و برند اختصاصی داریم؛ "
            "از منوی ربات «پنل نمایندگی» → «درخواست نمایندگی» را بزن.\n\n"
            "مرسی که هستی 🌟"
        ),
        "image_prompt": (
            "Luxury VIP appreciation visual, square 1:1 (1080x1080). An elegant golden crown "
            "resting on a dark velvet cushion, soft god-rays from above, floating golden particles "
            "and a subtle violet-cyan aurora in the dark navy background (#0d1024), a glass star "
            "trophy softly glowing beside it, premium jewelry-advert style 3D render, rich warm "
            "gold + deep violet palette, cinematic spotlight, no text anywhere."
        ),
        "notes": (
            "چرا: ۱۵ مشتری برتر تو بخش بزرگی از کل درآمدت را می‌سازند؛ دو نفر اول عملاً «ریسلر غیررسمی» "
            "هستند (۸۷ و ۷۴ سفارش!). این پیام هم قدردانی است هم دعوت نرم به نمایندگی رسمی — "
            "نماینده شدنشان یعنی فروش باثبات‌تر و وفاداری بلندمدت. "
            "کد VIP20 قفل به همین ۱۵ نفر است و ۳ بار مصرف دارد. "
            "این کمپین را هر فصل یک‌بار (با کد جدید) تکرار کن؛ حس «دیده شدن» قوی‌ترین ابزار حفظ مشتری است."
        ),
    },
    {
        "slug": "rep_recruit", "emoji": "💼", "segment": "buyers", "code": "",
        "title": "جذب نماینده — بفروش، درآمد داشته باش",
        "message": (
            "💼 {name} عزیز، با {brand} کسب درآمد کن!\n\n"
            "اگر ادمین گروه یا کانالی یا اطرافیانت دنبال اینترنت آزادند، نماینده ما شو:\n\n"
            "✅ قیمت عمده (هرچه بیشتر بفروشی، سود بیشتر)\n"
            "✅ برند و لوگوی خودت روی سرویس‌ها — مشتری اصلاً اسم ما را نمی‌بیند\n"
            "✅ اکانت تست رایگان برای مشتری‌هایت\n"
            "✅ پنل مدیریت و گزارش مالی شفاف داخل ربات\n\n"
            "🚀 شروع: منوی ربات → «پنل نمایندگی» → «درخواست نمایندگی»"
        ),
        "image_prompt": (
            "Business partnership visual, square 1:1 (1080x1080). A sleek holographic storefront "
            "projected from a modern briefcase, a rising neon bar chart and floating coins above it, "
            "violet and cyan glow on dark navy (#0d1024), a handshake silhouette formed of light "
            "particles in the background, modern 3D render, cinematic lighting, ambitious "
            "entrepreneurial mood, premium tech aesthetic, no text anywhere."
        ),
        "notes": (
            "چرا: ۱۱ نماینده فعلی‌ات سهم بزرگی از فروش می‌سازند و وایت‌لیبل کامل، مزیت رقابتی جدی "
            "توست — اکثر رقبا این را ندارند. هر نماینده جدید یعنی یک کانال فروش که خودش رشد می‌کند. "
            "این پیام را به خریداران بفرست (به غیرخریدار نمایندگی نده). "
            "ایده تکمیلی: در کانال هم پستش کن و برای ماه اول نماینده‌های جدید، حداقل شارژ اولیه را کم کن."
        ),
    },
    {
        "slug": "school_mehr", "emoji": "🎒", "segment": "all", "code": "SCHOOL25",
        "title": "بازگشت به مدرسه (شهریور/مهر)",
        "message": (
            "🎒 مهر نزدیک است؛ اینترنت پایدار برای کلاس آنلاین، جزوه و تحقیق، واجب‌تر از همیشه!\n\n"
            "📚 کمپین «بازگشت به مدرسه» {brand}:\n"
            "🎟 کد {code} → ۲۵٪ تخفیف همه پلن‌ها، ویژه شروع سال تحصیلی\n\n"
            "⚡️ سرعت بالا، چند سرور پشتیبان، پشتیبانی واقعی.\n"
            "🛒 منوی ربات → «خرید سرویس» → کد را موقع پرداخت وارد کن."
        ),
        "image_prompt": (
            "Back-to-school promo visual, square 1:1 (1080x1080). A stylish backpack with a glowing "
            "laptop and floating books, wifi beams rising from the laptop screen like an aurora, "
            "warm autumn orange leaves drifting through a dark navy scene (#0d1024) with violet-cyan "
            "neon accents, pencils and a graduation cap floating playfully, big neon '25%' numeral, "
            "modern 3D render, cinematic lighting, energetic youthful mood, no other text."
        ),
        "notes": (
            "زمان‌بندی: نیمه دوم شهریور تا هفته اول مهر بفرست (الان پیش‌نویس بماند). "
            "کد SCHOOL25 غیرفعال ساخته شده — موقع اجرا از تب تخفیف‌ها فعالش کن. "
            "دانش‌آموز/دانشجو یعنی مصرف بالا و حساس به قیمت → پلن‌های حجمی ۱۰-۲۰ گیگ را جلو بگذار. "
            "همزمان در کانال پست بگذار و از نماینده‌ها بخواه در گروه‌هایشان بازنشر کنند."
        ),
    },
]


async def seed_default_campaigns():
    """One-time seed of the designed campaign playbook (drafts) + their discount
    codes. Never re-runs (setting flag) and never touches a non-empty table."""
    if await get_setting("custom_campaigns_seeded", "") == "1":
        return
    existing = await get_custom_campaigns()
    if not existing:
        # code, percent, per_user_limit, campaign slug, targeted, active
        seed_codes = [
            ("COMEBACK30", 30, 1, "winback_blast", 1, 1),
            ("FLASH20",    20, 1, "flash_sale",    0, 0),  # activate when the sale starts
            ("RENEW15",    15, 1, "renewal_save",  1, 1),
            ("VIP20",      20, 3, "vip_thanks",    1, 1),
            ("SCHOOL25",   25, 1, "school_mehr",   0, 0),  # activate in Shahrivar/Mehr
        ]
        for code, pct, per_user, slug, targeted, active in seed_codes:
            if not await get_discount_code_by_code(code):
                cid = await add_discount_code(code, "percent", pct, per_user_limit=per_user,
                                              note="کمپین هدفمند (ساخت خودکار)",
                                              campaign=slug, targeted=targeted)
                if not active:
                    await update_discount_code(cid, is_active=0)
        for camp in _SEED_CAMPAIGNS:
            await save_custom_campaign(dict(camp))
    # Repair: the winback automation logs 'winback' events, but its configured
    # code was created with campaign='renewal' — a string nothing ever logs, so
    # the targeted-code lock rejected every single recipient ("not_eligible").
    wb_code = (await get_setting("campaign_winback_code", "")).strip()
    if wb_code:
        row = await get_discount_code_by_code(wb_code)
        if row and int(row.get("targeted") or 0) and (row.get("campaign") or "") == "renewal":
            await update_discount_code(int(row["id"]), campaign="winback")
    await set_setting("custom_campaigns_seeded", "1")


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
                            expires_at: int = 0, note: str = "", campaign: str = "", targeted: int = 0) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            """INSERT INTO discount_codes(code,kind,value,max_uses,per_user_limit,min_amount,package_id,expires_at,note,campaign,targeted)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            ((code or "").strip(), kind if kind in ("percent", "fixed") else "percent",
             float(value or 0), int(max_uses or 0), int(per_user_limit or 0),
             int(min_amount or 0), int(package_id or 0), int(expires_at or 0), (note or "").strip(),
             (campaign or "").strip(), 1 if int(targeted or 0) else 0),
        )
        await db.commit()
        return int(c.lastrowid)


async def user_has_campaign_event(campaign: str, user_id: int, kind: str = "sent") -> bool:
    """True if the user was targeted by a campaign (e.g. received its message)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM campaign_events WHERE campaign=? AND user_id=? AND kind=? LIMIT 1",
            ((campaign or "").strip(), int(user_id), kind),
        ) as c:
            return await c.fetchone() is not None


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
    # Campaign-locked code: only the users the campaign actually targeted may use it.
    if int(row.get("targeted") or 0) and str(row.get("campaign") or "").strip():
        if not await user_has_campaign_event(str(row["campaign"]).strip(), int(user_id), "sent"):
            return {"ok": False, "error": "not_eligible"}
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
                            duration_days: int = 0, is_unlimited: int = 0, label: str = "",
                            reward_amount: int = 0) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            """INSERT INTO referral_tiers(referrals_needed,reward_kind,reward_amount,reward_gb,duration_days,is_unlimited,label)
               VALUES(?,?,?,?,?,?,?)""",
            (int(referrals_needed or 0), reward_kind if reward_kind in ("wallet", "gb", "service") else "wallet",
             int(reward_amount or 0), float(reward_gb or 0), int(duration_days or 0),
             1 if int(is_unlimited or 0) else 0, (label or "").strip()),
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
                      t.referrals_needed, t.reward_kind, t.reward_amount, t.reward_gb, t.duration_days, t.is_unlimited, t.label
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

async def add_package(name, traffic_gb, duration_days, price, description='', inbound_id: int = 0,
                       is_unlimited: int = 0) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            "INSERT INTO packages(name,traffic_gb,duration_days,price,description,inbound_id,is_unlimited) VALUES(?,?,?,?,?,?,?)",
            (name, traffic_gb, duration_days, price, description, inbound_id, 1 if int(is_unlimited or 0) else 0)
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
        async with db.execute(
            "SELECT discount_percent, price_per_gb, unlimited_price, is_wholesale FROM users WHERE id=?",
            (user_id,),
        ) as c:
            r = await c.fetchone()
    if not r:
        return {"discount_percent": 0, "price_per_gb": 0, "unlimited_price": 0}
    ppg = int(r["price_per_gb"] or 0)
    unl = int(r["unlimited_price"] or 0)
    # Representatives: a per-seller custom price ALWAYS wins; when it isn't set,
    # fall back to the single global representative price the admin configured.
    if int(r["is_wholesale"] or 0):
        if ppg <= 0:
            try:
                ppg = max(0, int(await get_setting("rep_price_per_gb", "0") or 0))
            except (TypeError, ValueError):
                ppg = 0
        if unl <= 0:
            try:
                unl = max(0, int(await get_setting("rep_unlimited_price", "0") or 0))
            except (TypeError, ValueError):
                unl = 0
    return {
        "discount_percent": float(r["discount_percent"] or 0),
        "price_per_gb": ppg,
        "unlimited_price": unl,
    }


async def create_custom_order(user_id: int, name: str, total_traffic_gb: float, duration_days: int,
                              price: int, bulk_count: int = 1, bulk_each_gb: float = 0, notes: str = "",
                              package_id: int = 0) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        # Prefer an explicit plan (so get_order's COALESCE falls back to the
        # right traffic/duration — important for unlimited plans where the
        # custom value is 0 and NULLIF would otherwise drop it).
        if package_id:
            async with db.execute("SELECT id FROM packages WHERE id=?", (int(package_id),)) as cp:
                if not await cp.fetchone():
                    package_id = 0
        if not package_id:
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
async def create_order(user_id: int, package_id: int, custom_config_name: str = '', custom_price: int = 0,
                       base_price: int = 0) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            "INSERT INTO orders(user_id,package_id,status,custom_config_name,custom_price,base_price) VALUES(?,?,'pending_payment',?,?,?)",
            (user_id, package_id, custom_config_name, int(custom_price or 0), int(base_price or 0))
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


async def get_abandoned_carts(stage: int, min_age: str, max_age: str, limit: int = 200) -> List[Dict]:
    """Orders left unpaid (no receipt) — the 'abandoned cart' funnel hole.

    Returns at most ONE order per user (their most recent unpaid one) whose
    reminder stage is below ``stage`` and whose age sits in [max_age, min_age]
    (older than the reminder delay, but not so old we nag about a stale cart).
    ``min_age``/``max_age`` are 'YYYY-MM-DD HH:MM:SS' localtime cutoffs where
    ``min_age`` is the more-recent boundary (created_at <= min_age)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT o.*, u.telegram_id, u.username, u.full_name,
                   COALESCE(NULLIF(o.custom_name,''), p.name) as pkg_name,
                   COALESCE(NULLIF(o.custom_traffic_gb,0), p.traffic_gb) as traffic_gb,
                   COALESCE(NULLIF(o.custom_duration_days,0), p.duration_days) as duration_days,
                   COALESCE(NULLIF(o.custom_price,0), p.price) as price
            FROM orders o
            JOIN users u ON o.user_id=u.id
            JOIN packages p ON o.package_id=p.id
            WHERE o.status IN ('pending_payment','pending_receipt')
              AND o.cart_reminder_stage < ?
              AND o.created_at <= ?
              AND o.created_at >= ?
              AND u.telegram_id IS NOT NULL
              AND COALESCE(u.is_blocked,0)=0
              AND o.id = (
                    SELECT o2.id FROM orders o2
                    WHERE o2.user_id=o.user_id
                      AND o2.status IN ('pending_payment','pending_receipt')
                    ORDER BY o2.created_at DESC, o2.id DESC LIMIT 1
              )
            ORDER BY o.created_at ASC
            LIMIT ?
        """, (int(stage), min_age, max_age, int(limit))) as c:
            return [dict(r) for r in await c.fetchall()]


async def mark_cart_reminder(user_id: int, stage: int):
    """Bump the reminder stage on ALL of a user's still-unpaid orders, so sibling
    carts don't re-trigger the same nudge on the next pass."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE orders SET cart_reminder_stage=?
               WHERE user_id=? AND status IN ('pending_payment','pending_receipt')
                 AND cart_reminder_stage < ?""",
            (int(stage), int(user_id), int(stage)),
        )
        await db.commit()


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

async def count_rep_test_today(user_id: int) -> int:
    """How many test accounts this representative created today (local date)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT COUNT(*) FROM rep_test_accounts
               WHERE user_id=? AND date(created_at)=date('now','localtime')""",
            (int(user_id),),
        ) as c:
            row = await c.fetchone()
            return int((row[0] if row else 0) or 0)


async def add_rep_test_account(user_id: int, profile_id: int = 0) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            "INSERT INTO rep_test_accounts(user_id,profile_id) VALUES(?,?)",
            (int(user_id), int(profile_id or 0)),
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


async def add_subscription_node(profile_id: int, server_id: int, inbound_id: int, uuid: str,
                                email: str, link: str = "", config_id: int = 0) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            """INSERT INTO subscription_nodes(profile_id,server_id,inbound_id,uuid,email,link,config_id)
               VALUES(?,?,?,?,?,?,?)""",
            (int(profile_id), int(server_id), int(inbound_id), uuid, email, link or "", int(config_id or 0)),
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
            # `own` is the node config this client belongs to (config_id); `phys`
            # is whatever config owns the server/inbound it physically sits on.
            # For a normal node they are the same row. For an AUTO node they
            # differ — the label must come from the auto node, while the connect
            # host belongs to the physical target, so each is resolved separately.
            """SELECT n.*, s.name AS server_name, s.url AS server_url, s.username AS srv_user,
                      s.password AS srv_pass, s.api_token AS srv_api_token, s.sub_path,
                      COALESCE(own.label, phys.label) AS node_label,
                      COALESCE(own.priority, phys.priority, 100) AS node_priority,
                      COALESCE(NULLIF(own.connect_host,''), phys.connect_host, '') AS connect_host,
                      COALESCE(own.is_auto, 0) AS node_is_auto,
                      COALESCE(own.auto_show_server, 0) AS node_auto_show_server
               FROM subscription_nodes n
               JOIN servers s ON s.id=n.server_id
               LEFT JOIN subscription_node_configs own ON own.id=n.config_id
               LEFT JOIN subscription_node_configs phys
                    ON phys.server_id=n.server_id AND phys.inbound_id=n.inbound_id
               WHERE n.profile_id=?
               ORDER BY COALESCE(own.priority, phys.priority, 100) ASC, n.id ASC""",
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


async def get_active_subscription_profiles(limit: int = 200, offset: int = 0) -> List[Dict]:
    """A page of profiles that still need reconciling.

    `offset` lets a caller walk the whole set across successive passes. Without
    it a capped pass re-reads the SAME lowest-id profiles every time, so those
    few get polled constantly while everyone past the cap waits for the slow
    full sweep — and each poll costs one login + query per node.
    """
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
               LIMIT ? OFFSET ?""",
            (max(1, int(limit or 200)), max(0, int(offset or 0))),
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
