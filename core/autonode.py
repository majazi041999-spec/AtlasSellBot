"""Auto node (نود خودکار) — keep every subscription on the least-busy server.

The admin adds ONE auto node in the panel. It appears as a single extra entry in
every customer's subscription and always points at whichever server currently
has the fewest users online. Two pieces make that work:

  • a poller that asks each server's 3x-ui panel how many clients are online
    right now, and
  • a rebalancer that migrates subscriptions — gradually, and only when the
    imbalance is real — off crowded servers onto quiet ones.

Why online users and not assigned users: a server's speed is dictated by who is
actually pushing traffic through it this minute, not by how many dormant configs
point at it. 3x-ui derives its onlines list from xray's stats tick (a client is
online when it moved bytes in the last ~10s), which is exactly that measure.

Three things keep the balancing from making matters worse:

  1. Unknown ≠ empty. A panel we could not reach reports *no* count, never zero —
     otherwise a server that just went down would look like the emptiest one and
     attract every user. Nor is unknown a reason to move: not knowing a server's
     load says nothing about whether it is overloaded, and the probe failing is
     not the same as the server failing. Unknown means "take on nobody new",
     never "evacuate".
  2. Hysteresis. A subscription only moves when the gap is both relatively large
     (`margin`) and absolutely meaningful (`min_delta`), and never twice inside
     the cooldown window. Without this, two near-equal servers trade users
     forever.
  3. Projected load. Within one rebalancing pass, every move we decide is added
     to the destination's tally straightaway, so a batch of users spreads out
     instead of stampeding onto the single server that looked quietest at the
     start of the pass.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional

from core.database import (
    count_auto_assignments_by_target,
    get_auto_node_candidates,
    get_auto_node_configs,
    get_auto_node_rows,
    get_servers,
    get_setting,
    set_server_online_stats,
)
from core.xui_api import XUIClient

logger = logging.getLogger(__name__)


DEFAULTS = {
    # Off unless the admin turns it on. Balancing relocates PAYING customers, and
    # each relocation costs them a dead cached config until their app refreshes,
    # so it is not something an install should start doing on its own.
    "autonode_enabled": "0",
    "autonode_poll_seconds": "120",       # how often to re-read every panel's onlines
    "autonode_stale_seconds": "900",      # a count older than this is no longer trusted
    "autonode_margin": "0.25",            # move only if current load exceeds best by 25%
    "autonode_min_delta": "3",            # …and by at least 3 online users
    "autonode_cooldown_minutes": "60",    # never move the same subscription again within an hour
    # Per rebalance pass. Kept small on purpose: a move writes a client to the
    # destination panel and deletes one from the source, and 3x-ui reloads xray
    # on each of those — which briefly drops EVERY live connection on that
    # server, not just the customer being moved. A big batch turns a load tweak
    # into a fleet-wide outage.
    "autonode_max_moves": "5",
    "autonode_poll_concurrency": "6",
}


async def _setting_float(key: str, minimum: float = 0.0) -> float:
    raw = await get_setting(key, DEFAULTS.get(key, "0"))
    try:
        return max(minimum, float(str(raw).strip()))
    except (TypeError, ValueError):
        return max(minimum, float(DEFAULTS.get(key, "0") or 0))


async def _setting_int(key: str, minimum: int = 0) -> int:
    return int(await _setting_float(key, float(minimum)))


async def is_enabled() -> bool:
    return str(await get_setting("autonode_enabled", DEFAULTS["autonode_enabled"])).strip() == "1"


# ── live online counts ──────────────────────────────────────────────────────

async def refresh_server_online_counts(servers: Optional[List[Dict]] = None) -> Dict[int, Optional[int]]:
    """Ask every active panel how many clients are online and store the answer.

    Returns {server_id: count or None}. `None` means the panel did not answer —
    the caller must treat that as *unknown*, never as zero.
    """
    servers = servers if servers is not None else await get_servers(active_only=True)
    if not servers:
        return {}

    limit = asyncio.Semaphore(max(1, await _setting_int("autonode_poll_concurrency", 1)))
    now_ms = int(time.time() * 1000)
    results: Dict[int, Optional[int]] = {}

    async def probe(server: Dict) -> None:
        sid = int(server["id"])
        count: Optional[int] = None
        async with limit:
            cli = XUIClient(
                server["url"], server["username"], server["password"],
                server.get("sub_path") or "", server.get("api_token", "") or "",
            )
            try:
                count = await asyncio.wait_for(cli.get_online_count(), timeout=15)
            except asyncio.TimeoutError:
                logger.warning("autonode: onlines timed out for server %s", server.get("name") or sid)
            except Exception as e:
                logger.warning("autonode: onlines failed for server %s: %s", server.get("name") or sid, e)
            else:
                if count is None:
                    logger.warning(
                        "autonode: server %s gave no onlines (%s)",
                        server.get("name") or sid, getattr(cli, "last_error", "") or "unknown",
                    )
            finally:
                await cli.close()
        results[sid] = count
        await set_server_online_stats(sid, count, now_ms)

    await asyncio.gather(*(probe(s) for s in servers), return_exceptions=True)
    invalidate_load_views()   # the numbers just changed; don't decide on the old ones
    return results


def _fresh_online_count(server: Dict, stale_ms: int, now_ms: int,
                        smoothed: bool = False) -> Optional[float]:
    """This server's trusted online count, or None if missing/failed/stale.

    `smoothed=True` returns the rolling average used for routing decisions;
    the default returns the raw last reading, which is what the admin sees.
    """
    if not int(server.get("online_ok") or 0):
        return None
    checked = int(server.get("online_checked_at") or 0)
    if checked <= 0 or (stale_ms > 0 and now_ms - checked > stale_ms):
        return None
    if smoothed:
        return max(0.0, float(server.get("online_avg") or server.get("online_count") or 0))
    return max(0, int(server.get("online_count") or 0))


# ── choosing a target ───────────────────────────────────────────────────────

class LoadView:
    """A snapshot of how busy each server is, plus the moves decided so far.

    Built once per rebalancing pass so that every decision inside the pass sees
    the effect of the previous ones (see "projected load" in the module docs).
    """

    def __init__(self, servers: List[Dict], assignments: Dict[int, int],
                 stale_ms: int, now_ms: int):
        self.weight: Dict[int, float] = {}
        self.online: Dict[int, Optional[int]] = {}          # raw, for display
        self.smoothed: Dict[int, Optional[float]] = {}      # rolling average, for decisions
        self.assigned: Dict[int, int] = dict(assignments)
        self.pending: Dict[int, int] = {}
        for server in servers:
            sid = int(server["id"])
            try:
                weight = float(server.get("load_weight") or 1)
            except (TypeError, ValueError):
                weight = 1.0
            self.weight[sid] = weight if weight > 0 else 1.0
            self.online[sid] = _fresh_online_count(server, stale_ms, now_ms)
            self.smoothed[sid] = _fresh_online_count(server, stale_ms, now_ms, smoothed=True)

    def known(self, server_id: int) -> bool:
        return self.smoothed.get(int(server_id)) is not None

    def score(self, server_id: int) -> float:
        """Lower is better: users per unit of capacity.

        When the live count is unknown we fall back to how many subscriptions are
        already assigned there, plus a penalty, so an unreachable server is
        ranked last without being banned outright (if every panel is unreachable
        we still have to put the user somewhere).
        """
        sid = int(server_id)
        pending = self.pending.get(sid, 0)
        live = self.smoothed.get(sid)
        if live is None:
            base = self.assigned.get(sid, 0) + pending
            return (base / self.weight.get(sid, 1.0)) + 1_000.0
        return (live + pending) / self.weight.get(sid, 1.0)

    def reserve(self, server_id: int) -> None:
        sid = int(server_id)
        self.pending[sid] = self.pending.get(sid, 0) + 1


# Concurrent placements must share one view, or each would independently pick
# whichever server looked quietest and they would all land on it. This happens
# for real: adding an auto node provisions it onto every existing subscription
# at once, and a sales burst can create many subscriptions between two polls.
# Sharing the view means each decision's `reserve()` is visible to the next.
_VIEW_TTL_SECONDS = 20.0
_view_cache: Dict[int, tuple] = {}
_view_lock = asyncio.Lock()


def invalidate_load_views() -> None:
    """Drop cached views — call after re-polling so decisions use fresh counts."""
    _view_cache.clear()


async def build_load_view(auto_node: Dict, shared: bool = True) -> LoadView:
    key = int(auto_node["id"])
    now = time.monotonic()
    if shared:
        cached = _view_cache.get(key)
        if cached and (now - cached[0]) < _VIEW_TTL_SECONDS:
            return cached[1]
    async with _view_lock:
        if shared:
            cached = _view_cache.get(key)
            if cached and (time.monotonic() - cached[0]) < _VIEW_TTL_SECONDS:
                return cached[1]
        now_ms = int(time.time() * 1000)
        stale_ms = await _setting_int("autonode_stale_seconds", 0) * 1000
        servers = await get_servers(active_only=False)
        assignments = await count_auto_assignments_by_target(key)
        view = LoadView(servers, assignments, stale_ms, now_ms)
        if shared:
            _view_cache[key] = (time.monotonic(), view)
        return view


def _merge_target(auto_node: Dict, candidate: Dict) -> Dict:
    """The auto node's identity + the chosen candidate's physical connection.

    The result is a node-config dict the provisioning code can use as-is: it
    keeps the auto node's `id` (which owns the `_n{id}` email suffix, the label
    and the pool settings) while pointing at the candidate's server and inbound.
    """
    merged = dict(auto_node)
    for key in ("server_id", "inbound_id", "server_name", "server_url", "srv_user",
                "srv_pass", "srv_api_token", "sub_path", "server_active",
                "max_active_configs"):
        merged[key] = candidate.get(key)
    # The physical node's own domain override wins unless the auto node sets one.
    if not str(auto_node.get("connect_host") or "").strip():
        merged["connect_host"] = candidate.get("connect_host") or ""
    merged["auto_target_config_id"] = int(candidate["id"])
    merged["auto_target_label"] = candidate.get("label") or candidate.get("server_name") or ""
    merged["auto_resolved"] = True   # already points at a real server; don't resolve again
    return merged


async def resolve_auto_target(auto_node: Dict, existing: Optional[Dict] = None,
                              view: Optional[LoadView] = None,
                              candidates: Optional[List[Dict]] = None,
                              allow_move: bool = True) -> Optional[Dict]:
    """Where this subscription's auto node should live right now.

    `existing` is the subscription's current row for this auto node, if any. When
    it already sits on a usable server we keep it there unless the imbalance
    clears the hysteresis thresholds — staying put is free, moving costs the
    customer a reconnect.

    Returns a node-config dict ready for provisioning, or None when the pool has
    no usable member.
    """
    candidates = candidates if candidates is not None else await get_auto_node_candidates(auto_node)
    if not candidates:
        return None
    view = view or await build_load_view(auto_node)

    # Ties are broken by how many subscriptions each server already holds, so a
    # burst of signups arriving between two polls still fans out instead of all
    # landing on whichever equally-quiet server sorts first.
    ranked = sorted(candidates, key=lambda c: (view.score(c["server_id"]),
                                               view.assigned.get(int(c["server_id"]), 0),
                                               int(c.get("priority") or 100),
                                               int(c["id"])))
    best = ranked[0]

    current = None
    if existing:
        cur_server = int(existing.get("server_id") or 0)
        cur_inbound = int(existing.get("inbound_id") or 0)
        current = next(
            (c for c in candidates
             if int(c["server_id"]) == cur_server and int(c["inbound_id"]) == cur_inbound),
            None,
        )

    if current is None:
        view.reserve(best["server_id"])
        return _merge_target(auto_node, best)

    if not allow_move or int(current["id"]) == int(best["id"]):
        return _merge_target(auto_node, current)

    # Never bounce the same subscription twice in a row.
    cooldown_ms = await _setting_int("autonode_cooldown_minutes", 0) * 60_000
    moved_at = int((existing or {}).get("moved_at") or 0)
    if cooldown_ms > 0 and moved_at > 0 and (int(time.time() * 1000) - moved_at) < cooldown_ms:
        return _merge_target(auto_node, current)

    # An unknown load is not evidence of overload, and moving on a guess is not
    # free: it deletes the client off the old panel, so every copy of the
    # subscription already cached in a customer's app keeps pointing at a server
    # that no longer knows them, and that entry simply stops responding until
    # they refresh it by hand.
    #
    # Both sides therefore have to be visible before we relocate anyone. A panel
    # that does not answer the onlines query is not a server that is down — the
    # endpoint moved between 3x-ui versions and the probe is best-effort — so
    # treating "unknown" as "move them off" drains whole panels of customers on
    # no evidence at all, and `score()`'s +1000 makes it worse by ranking every
    # unknown server last, which points all of those moves at the same handful of
    # destinations. Unknown servers are already excluded from attracting NEW
    # placements by that same ranking; that is the whole of the safe response. A
    # genuinely dead server is taken out of `candidates` (deactivated in the
    # panel, or out of capacity), and that path already relocates its customers
    # above, where `current` comes back None.
    if not view.known(current["server_id"]) or not view.known(best["server_id"]):
        return _merge_target(auto_node, current)

    # Only act on an imbalance that is both proportionally and absolutely real.
    current_score = view.score(current["server_id"])
    best_score = view.score(best["server_id"])
    margin = await _setting_float("autonode_margin", 0)
    min_delta = await _setting_float("autonode_min_delta", 0)
    weight = view.weight.get(int(current["server_id"]), 1.0)
    if current_score - best_score < (min_delta / weight if weight else min_delta):
        return _merge_target(auto_node, current)
    if current_score < best_score * (1 + margin) + 1e-9:
        return _merge_target(auto_node, current)

    view.reserve(best["server_id"])
    return _merge_target(auto_node, best)


async def expand_node_configs(nodes: List[Dict], existing_by_config: Optional[Dict[int, Dict]] = None,
                              allow_move: bool = True) -> List[Dict]:
    """Replace every auto node in `nodes` with its resolved physical target.

    Node configs that are not auto pass through untouched, so callers can hand us
    the whole list and stay oblivious to the distinction. An auto node whose pool
    has no usable member is dropped.
    """
    existing_by_config = existing_by_config or {}
    out: List[Dict] = []
    for node in nodes:
        if not int(node.get("is_auto") or 0) or node.get("auto_resolved"):
            out.append(node)
            continue
        target = await resolve_auto_target(
            node,
            existing=existing_by_config.get(int(node["id"])),
            allow_move=allow_move,
        )
        if target:
            out.append(target)
        else:
            logger.warning("autonode: node %s has no usable candidate; skipping", node.get("id"))
    return out


# ── rebalancing ─────────────────────────────────────────────────────────────

async def rebalance_auto_node(auto_node: Dict, log=None, limit: int = 5000,
                              concurrency: int = 6, per_profile_timeout: int = 120) -> Dict:
    """Move subscriptions off crowded servers for ONE auto node.

    Deciding and acting are deliberately split. Every decision is made first, in
    one sequential pass over a shared load view — that is what lets each chosen
    destination be counted immediately, so a batch of moves spreads across the
    quiet servers instead of piling onto whichever one happened to be emptiest.
    Only then are the moves executed, concurrently.
    """
    from core.multi_subscription import ensure_subscription_profile_nodes  # deferred: avoids an import cycle

    log = log or (lambda _line: None)
    node_id = int(auto_node["id"])
    label = auto_node.get("label") or f"#{node_id}"
    stats = {"considered": 0, "moved": 0, "failed": 0, "kept": 0}

    candidates = await get_auto_node_candidates(auto_node)
    if not candidates:
        log(f"⚠️ نود خودکار «{label}»: هیچ سرور قابل استفاده‌ای در استخر نیست.")
        return stats

    rows = await get_auto_node_rows(node_id, limit=limit)
    if not rows:
        log(f"ℹ️ نود خودکار «{label}»: هنوز روی هیچ اشتراکی ساخته نشده.")
        return stats

    # A private view: this pass reasons about the whole fleet at once and must
    # not inherit reservations made by unrelated placements. Its own decisions
    # are published by invalidating the shared cache when the pass finishes.
    view = await build_load_view(auto_node, shared=False)
    max_moves = await _setting_int("autonode_max_moves", 1)
    log(f"⚖️ نود خودکار «{label}» | {len(rows)} اشتراک | {len(candidates)} سرور در استخر | سقف جابه‌جایی: {max_moves}")
    for cand in sorted(candidates, key=lambda c: view.score(c["server_id"])):
        online = view.online.get(int(cand["server_id"]))
        shown = "نامشخص" if online is None else str(online)
        log(f"    • {cand.get('server_name') or cand['server_id']}: آنلاین={shown}")

    pending: list[tuple[Dict, Dict]] = []
    for row in rows:
        stats["considered"] += 1
        existing = {
            "server_id": int(row.get("node_server_id") or 0),
            "inbound_id": int(row.get("node_inbound_id") or 0),
            "moved_at": int(row.get("node_moved_at") or 0),
        }
        allow_move = len(pending) < max_moves
        target = await resolve_auto_target(
            auto_node, existing=existing, view=view,
            candidates=candidates, allow_move=allow_move,
        )
        if not target:
            continue
        if (int(target["server_id"]) == existing["server_id"]
                and int(target["inbound_id"]) == existing["inbound_id"]):
            stats["kept"] += 1
            continue
        pending.append((row, target))

    if not pending:
        log(f"✅ نود خودکار «{label}»: توزیع متعادل است؛ جابه‌جایی لازم نشد.")
        return stats

    log(f"🔀 {len(pending)} اشتراک باید جابه‌جا شود…")
    sem = asyncio.Semaphore(max(1, int(concurrency)))
    done = {"n": 0}

    async def worker(profile: Dict, target: Dict) -> None:
        async with sem:
            name = str(profile.get("email") or f"#{profile.get('id')}")[-28:]
            dest = target.get("auto_target_label") or target.get("server_name") or target["server_id"]
            try:
                r = await asyncio.wait_for(
                    ensure_subscription_profile_nodes(
                        profile, only_config_ids={node_id}, auto_targets={node_id: target},
                    ),
                    timeout=per_profile_timeout,
                )
                moved = int(r.get("moved") or 0)
                stats["moved"] += moved
                stats["failed"] += int(r.get("failed") or 0)
                done["n"] += 1
                icon = "✅" if moved else "⚠️"
                log(f"[{done['n']}/{len(pending)}] {icon} {name} → {dest}")
                for err in (r.get("errors") or [])[:1]:
                    log(f"    ↳ {err}")
            except asyncio.TimeoutError:
                stats["failed"] += 1
                done["n"] += 1
                log(f"[{done['n']}/{len(pending)}] ⌛️ {name}: طول کشید و رد شد")
            except Exception as e:
                stats["failed"] += 1
                done["n"] += 1
                log(f"[{done['n']}/{len(pending)}] ❌ {name}: {str(e)[:140]}")

    await asyncio.gather(*(worker(p, t) for p, t in pending))
    # New placements must now reason from the assignments this pass created.
    invalidate_load_views()
    log(f"📊 «{label}» — جابه‌جا شد: {stats['moved']} | بدون تغییر: {stats['kept']} | خطا: {stats['failed']}")
    return stats


async def rebalance_all_auto_nodes(log=None, refresh: bool = True, **kw) -> Dict:
    """Refresh every panel's online count, then rebalance each auto node."""
    log = log or (lambda _line: None)
    agg = {"considered": 0, "moved": 0, "failed": 0, "kept": 0, "nodes": 0}
    autos = [n for n in await get_auto_node_configs(active_only=True)]
    if not autos:
        log("هیچ نود خودکاری تعریف نشده است.")
        return agg
    if refresh:
        log("📡 در حال خواندن تعداد کاربران آنلاین از همه سرورها…")
        counts = await refresh_server_online_counts()
        unknown = [sid for sid, c in counts.items() if c is None]
        log(f"    {len(counts) - len(unknown)} سرور پاسخ داد، {len(unknown)} سرور نامشخص.")
    for auto in autos:
        agg["nodes"] += 1
        stats = await rebalance_auto_node(auto, log=log, **kw)
        for key in ("considered", "moved", "failed", "kept"):
            agg[key] += int(stats.get(key) or 0)
    return agg


# ── status for the admin panel ──────────────────────────────────────────────

async def server_load_snapshot() -> List[Dict]:
    """Per-server load, as shown on the Subscriptions page."""
    now_ms = int(time.time() * 1000)
    stale_ms = await _setting_int("autonode_stale_seconds", 0) * 1000
    out = []
    for server in await get_servers(active_only=False):
        live = _fresh_online_count(server, stale_ms, now_ms)
        checked = int(server.get("online_checked_at") or 0)
        try:
            weight = float(server.get("load_weight") or 1)
        except (TypeError, ValueError):
            weight = 1.0
        out.append({
            "id": int(server["id"]),
            "name": server.get("name") or f"#{server['id']}",
            "is_active": int(server.get("is_active") or 0),
            "online": live,
            "online_known": live is not None,
            "online_avg": round(float(server.get("online_avg") or 0), 1),
            "raw_online": int(server.get("online_count") or 0),
            "checked_at": checked,
            "stale": bool(checked and live is None and int(server.get("online_ok") or 0)),
            "load_weight": weight if weight > 0 else 1.0,
        })
    out.sort(key=lambda s: (s["online"] is None, s["online"] if s["online"] is not None else 0, s["id"]))
    return out


async def auto_node_overview() -> Dict:
    """Everything the panel needs to explain what the auto node is doing."""
    autos = await get_auto_node_configs(active_only=False)
    servers = await server_load_snapshot()
    by_id = {s["id"]: s for s in servers}
    nodes = []
    for auto in autos:
        candidates = await get_auto_node_candidates(auto)
        assigned = await count_auto_assignments_by_target(int(auto["id"]))
        nodes.append({
            "id": int(auto["id"]),
            "label": auto.get("label") or "",
            "is_active": int(auto.get("is_active") or 0),
            "priority": int(auto.get("priority") or 1),
            "auto_pool": auto.get("auto_pool") or "",
            "auto_show_server": int(auto.get("auto_show_server") or 0),
            "connect_host": auto.get("connect_host") or "",
            "candidates": [{
                "id": int(c["id"]),
                "label": c.get("label") or c.get("server_name") or f"#{c['id']}",
                "server_id": int(c["server_id"]),
                "server_name": c.get("server_name") or "",
                "inbound_id": int(c["inbound_id"]),
                "online": (by_id.get(int(c["server_id"])) or {}).get("online"),
                "assigned": int(assigned.get(int(c["server_id"]) or 0, 0)),
            } for c in candidates],
            "assigned_total": sum(assigned.values()),
        })
    return {
        "enabled": await is_enabled(),
        "nodes": nodes,
        "servers": servers,
        "settings": {
            "poll_seconds": await _setting_int("autonode_poll_seconds", 15),
            "stale_seconds": await _setting_int("autonode_stale_seconds", 0),
            "margin": await _setting_float("autonode_margin", 0),
            "min_delta": await _setting_int("autonode_min_delta", 0),
            "cooldown_minutes": await _setting_int("autonode_cooldown_minutes", 0),
            "max_moves": await _setting_int("autonode_max_moves", 1),
        },
    }
