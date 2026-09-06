"""The reseller volume ladder: how many active services buy which unlimited price.

A reseller's price for the unlimited plan steps down as their book of active
services grows. The ladder is advertised in the recruitment post, so the number a
reseller reads there has to be the number they are actually charged — which is why
it is applied in exactly one place (``core.database.get_user_pricing``) and read
back from exactly one place (this module).

Who is on it
------------
Only resellers who joined after the ladder existed. Everyone we were already
working with keeps the price they were promised when they signed up, whatever it
was: ``users.rep_tier_exempt`` is backfilled to 1 for every reseller alive at the
migration, and nothing ever sets it back to 0. A reseller who is switched off and
on again therefore stays grandfathered — being toggled in the panel is not the
same thing as being a new arrival.

An explicit per-reseller price (``users.unlimited_price``) still wins over the
ladder, so the admin can always overrule it for one person.

Storage
-------
The setting ``rep_unlimited_tiers`` holds a JSON list of ``[min_active, price]``
pairs, so the owner can move the rungs without a deploy. An empty list turns the
ladder off and pricing falls back to the single global reseller price.
"""
import json
from typing import List, Optional, Tuple

SETTING = "rep_unlimited_tiers"

# Seeded from the recruitment post: توماني، ماهانه، پلن نامحدود ۵ کاربره.
DEFAULT: List[Tuple[int, int]] = [(0, 179_000), (10, 169_000), (30, 139_000)]


def _clean(raw) -> List[Tuple[int, int]]:
    """Coerce whatever is in the setting into a sorted, sane ladder.

    Anything malformed is dropped rather than raised on: a typo in a settings
    field must not be able to stop a reseller from buying.
    """
    out: List[Tuple[int, int]] = []
    for item in raw or []:
        try:
            floor, price = int(item[0]), int(item[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if floor < 0 or price <= 0:
            continue
        out.append((floor, price))
    out.sort(key=lambda t: t[0])
    return out


async def ladder() -> List[Tuple[int, int]]:
    from core.database import get_setting
    try:
        raw = json.loads(await get_setting(SETTING, "") or "[]")
    except (ValueError, TypeError):
        raw = []
    rungs = _clean(raw)
    return rungs if rungs else list(DEFAULT)


async def save(rungs: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    from core.database import set_setting
    clean = _clean(rungs)
    await set_setting(SETTING, json.dumps([[a, b] for a, b in clean]))
    return clean


def price_for(rungs: List[Tuple[int, int]], active: int) -> int:
    """Price at ``active`` services: the last rung whose floor has been reached.

    Returns 0 when no rung applies, which the caller reads as "ladder says
    nothing" and falls back to the flat reseller price.
    """
    price = 0
    for floor, value in rungs:
        if active >= floor:
            price = value
        else:
            break
    return price


def rung_floor(rungs: List[Tuple[int, int]], active: int) -> int:
    """Floor of the rung they are standing on — which one to point at in the panel.

    Matching on the floor rather than on the price, because two rungs are allowed
    to charge the same and pointing at both would read as a bug.
    """
    floor = 0
    for start, _ in rungs:
        if active >= start:
            floor = start
        else:
            break
    return floor


def next_rung(rungs: List[Tuple[int, int]], active: int) -> Optional[Tuple[int, int]]:
    """The next step down: (how many more active services, price there).

    None once they are on the bottom rung — there is nothing left to promise.
    """
    current = price_for(rungs, active)
    for floor, value in rungs:
        if floor > active and (not current or value < current):
            return floor - active, value
    return None


async def status(user_id: int) -> dict:
    """Where one reseller stands on the ladder, for the panel and the API."""
    from core.database import count_active_services
    rungs = await ladder()
    active = await count_active_services(user_id)
    step = next_rung(rungs, active)
    return {
        "active": active,
        "price": price_for(rungs, active),
        "at": rung_floor(rungs, active),
        "rungs": [{"from": a, "price": b} for a, b in rungs],
        "next": {"in": step[0], "price": step[1]} if step else None,
    }
