"""Private resale notes. These never participate in pricing or wallet charging."""
import aiosqlite
from core.config import DB_PATH

MAX_SALE_PRICE = 1_000_000_000_000


async def set_sale_price(user_id: int, kind: str, order_id: int,
                         profile_id: int, sale_price):
    if kind not in ("purchase", "renewal"):
        raise ValueError("invalid_kind")
    if any(type(v) is not int or v < 0 for v in (order_id, profile_id)) or order_id == 0:
        raise ValueError("invalid_identity")
    if sale_price is not None and (type(sale_price) is not int or not 0 <= sale_price <= MAX_SALE_PRICE):
        raise ValueError("invalid_price")
    if kind == "renewal" and profile_id != 0:
        raise ValueError("invalid_identity")
    async with aiosqlite.connect(DB_PATH) as db:
        # Check purchase ownership, not a caller-supplied rep id or the current
        # owner of a service which may have been handed to the end customer.
        await db.execute("BEGIN IMMEDIATE")
        async with db.execute("""
            SELECT 1 FROM orders o JOIN users u ON u.id=o.user_id
            WHERE o.id=? AND o.user_id=? AND o.status='approved'
              AND u.is_wholesale=1 AND COALESCE(u.is_blocked,0)=0
              AND ((?='renewal' AND (o.renew_sub_profile_id>0 OR o.renew_config_id>0))
                   OR (?='purchase' AND EXISTS
                       (SELECT 1 FROM subscription_profiles sp WHERE sp.id=? AND sp.order_id=o.id)))
            """, (order_id, user_id, kind, kind, profile_id)) as c:
            if not await c.fetchone():
                return False
        if sale_price is None:
            await db.execute("DELETE FROM rep_sale_prices WHERE user_id=? AND kind=? AND order_id=? AND profile_id=?",
                             (user_id, kind, order_id, profile_id))
        else:
            await db.execute("""INSERT INTO rep_sale_prices(user_id,kind,order_id,profile_id,sale_price)
                VALUES(?,?,?,?,?) ON CONFLICT(user_id,kind,order_id,profile_id)
                DO UPDATE SET sale_price=excluded.sale_price, updated_at=datetime('now','localtime')""",
                (user_id, kind, order_id, profile_id, sale_price))
        await db.commit()
    return True


async def add_private_accounting(user_id: int, items: list, summary: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT kind,order_id,profile_id,sale_price FROM rep_sale_prices WHERE user_id=?",
                              (user_id,)) as c:
            prices = {(r[0], r[1], r[2]): r[3] for r in await c.fetchall()}
    revenue = profit = cost = priced = profit_count = 0
    for item in items:
        sale = prices.get((item["kind"], item["order_id"], item["profile_id"]))
        item["sale_price"] = sale
        item["profit"] = None if sale is None or item["price"] is None else sale - item["price"]
        if sale is not None:
            priced += 1
            revenue += sale
        if item["profit"] is not None:
            profit_count += 1
            profit += item["profit"]
            cost += item["price"]
    summary.update(total_revenue=revenue, total_profit=profit, cost_of_sales=cost,
                   sales_count=priced, profit_count=profit_count,
                   unpriced_count=len(items)-priced, unknown_sale_cost_count=priced-profit_count)
