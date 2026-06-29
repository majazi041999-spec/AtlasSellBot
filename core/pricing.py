"""Central per-user package pricing.

One source of truth for "what does this package cost *this* user", used by the
bot, the web panel and the mini app so the three never drift apart.

Rules
-----
* **Unlimited package** (``traffic_gb <= 0``): its price is NEVER derived from
  the per-GB rate (zero volume would make it free). It uses the user's own
  ``unlimited_price`` when set (> 0), otherwise the package's own ``price``.
* **Volume package**: base = ``traffic_gb * price_per_gb`` when the user has a
  custom per-GB rate (> 0), otherwise the package's own ``price``.
* The per-user ``discount_percent`` is applied on top in both cases.

Setting ``price_per_gb`` / ``unlimited_price`` back to ``0`` therefore always
falls back to the package default — there is no sticky custom price.
"""
from typing import Dict


def is_unlimited_package(pkg: Dict) -> bool:
    return float(pkg.get("traffic_gb") or 0) <= 0


def compute_package_price(pricing: Dict, pkg: Dict) -> Dict:
    """Return pricing breakdown for ``pkg`` given a user's ``pricing`` dict
    (as returned by ``get_user_pricing``).

    Keys: base, final, discount, price_per_gb, unlimited_price, is_unlimited.
    """
    traffic_gb = float(pkg.get("traffic_gb") or 0)
    pkg_price = int(pkg.get("price") or 0)
    discount = max(0.0, min(100.0, float(pricing.get("discount_percent") or 0)))
    ppg = max(0, int(pricing.get("price_per_gb") or 0))
    unlimited_price = max(0, int(pricing.get("unlimited_price") or 0))
    unlimited = traffic_gb <= 0

    if unlimited:
        base = unlimited_price if unlimited_price > 0 else pkg_price
        applied_ppg = 0
    else:
        base = int(traffic_gb * ppg) if ppg > 0 else pkg_price
        applied_ppg = ppg

    base = max(0, base)
    final = max(0, int(base * (100 - discount) / 100))
    return {
        "base": base,
        "final": final,
        "discount": discount,
        "price_per_gb": applied_ppg,
        "unlimited_price": unlimited_price if unlimited else 0,
        "is_unlimited": unlimited,
    }


async def package_price_for_user(user_id: int, pkg: Dict) -> Dict:
    """Async wrapper that loads the user's pricing then computes the price."""
    from core.database import get_user_pricing
    return compute_package_price(await get_user_pricing(user_id), pkg)
