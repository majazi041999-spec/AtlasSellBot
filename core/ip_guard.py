"""Per-subscription concurrent-IP limit, with a graduated penalty.

WHAT THIS DOES. A subscription is one link that fans out to ~12 nodes across
every server. This counts how many DISTINCT PLACES are connected to that one
subscription right now, warns the customer when it goes over their allowance,
and — if they keep going — switches their clients off for 1 minute, then 10,
then an hour, then restores them.

WHY IT COSTS ALMOST NOTHING, which was the owner's first requirement.

3x-ui v3.7 already runs `CheckClientIpJob` every 10 seconds on a default
install. Since that version the job no longer tails xray's access log — that
path was deleted — it asks the running core's online-stats gRPC API for the
live connection table (email plus source IPs) and records what it saw in its
own `node_client_ip` table. Crucially, the recording step runs BEFORE the
enforcement gate, so it happens whether or not any client carries 3x-ui's own
`limitIp` and whether or not fail2ban is installed. The panel is therefore
already computing exactly what we need, for its own reasons, at no cost we can
avoid or influence.

`POST /panel/api/clients/clientIpsByGuid` hands that whole table over in ONE
request. So the entire detection budget is:

    one HTTP request per server per cycle — five, on this fleet — and no writes

There is no per-client polling anywhere in here. Asking each of the 3117 nodes
for its own IPs would be 3117 requests a minute and is the reason
`XUIClient.get_client_ips_bulk()` exists.

WHY WE DO NOT USE 3x-ui's OWN `limitIp`. Three disqualifying reasons, all read
out of the v3.7.0 source rather than assumed:
  * Its enforcement is gated on fail2ban being installed (`resolveEnforce`), and
    a start-up migration (`resetIpLimitsWithoutFail2ban`) ZEROES every client's
    limitIp when fail2ban is absent. We would be setting a field the panel
    quietly erases.
  * Its ban duration is fail2ban's `bantime`, settable only from the `x-ui`
    shell menu. There is no panel setting and no API for it, so a 1/10/60-minute
    ladder cannot be expressed.
  * It counts per CLIENT. Our unit is the subscription — twelve clients that
    must be counted together, or a customer on four servers looks like four
    separate small users and never trips anything.

HOW THE CUT ITSELF IS SAFE. `bulk_set_clients_enabled` posts to
`/panel/api/clients/bulkDisable`, and on v3.7 that path pushes the change
through xray's gRPC HandlerService (`RemoveUser` / `AddUser`) rather than
rewriting the config and reloading. Only the named emails' connections drop.
Verified in `client_bulk.go::bulkSetEnableInboundClients`, which sets
`needRestart` only when that API call FAILS. PROJECT_MAP §6's warning — one
client write reloads xray and drops every live connection — is still the right
instinct for `update_client` and for older panels, and it is why nothing here
ever loops per client. But on this fleet the bulk enable/disable pair is
surgical, and that is what makes a feature like this safe to run at all.

THE FALSE POSITIVE IS THE ONLY FAILURE THAT MATTERS. Cutting off a paying
customer who did nothing wrong is far worse than missing someone who shared
their link. Iranian mobile carriers hand out changing addresses, a phone moving
between Wi-Fi and 4G is briefly visible on both, and one VPN client opens
several parallel connections. Three things guard against that, and they are all
deliberately conservative:
  * Addresses are counted by NETWORK, not by address — /24 for IPv4 and /64 for
    IPv6 by default — so a device rotating inside one pool, or an IPv6 host
    cycling privacy addresses inside its own /64, stays one place.
  * An address only counts while it is FRESH. The panel keeps an address for 30
    minutes, which is far too coarse for "at the same time", but it re-stamps
    the timestamp on every 10-second scan for as long as the connection is live.
    So "seen in the last 90 seconds" really does mean "connected now", and a
    handover artefact ages out in about a minute.
  * A single reading never acts. The count must exceed the allowance on several
    consecutive cycles before anything happens, so a transient overlap is
    invisible and only sustained parallel use is caught.

And the feature ships OFF, with a warn-only mode that is ON when it is first
switched on, so the owner can read the log for a few days and see who it WOULD
have cut before it is allowed to cut anyone.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from core.database import (
    get_setting,
    get_servers,
    get_ip_guard_states,
    save_ip_guard_state,
    clear_ip_guard_state,
    add_ip_guard_event,
    save_ip_guard_states_bulk,
    add_ip_guard_events_bulk,
    prune_ip_guard_events,
    get_ip_guard_profile_nodes,
    get_cut_profile_ids,
)
from core.xui_api import XUIClient

logger = logging.getLogger(__name__)

# Defaults. Every one of these is a settings key so the owner can tune it
# without a deploy — see DEFAULTS below for what each one means.
DEFAULTS: Dict[str, str] = {
    # Ships off. This switches paying customers off, so it must never arrive
    # switched on because someone upgraded.
    "ip_limit_enabled": "0",
    # Observe and notify, but never actually cut. On by default so the first
    # thing the owner sees is a week of evidence rather than angry customers.
    "ip_limit_warn_only": "1",
    "ip_limit_default": "5",
    # How often we look. The panel refreshes its own view every 10s, so there is
    # nothing to gain below ~30s and it only costs requests.
    "ip_limit_poll_seconds": "60",
    # How recently an address must have been seen to count as connected NOW.
    # Two missed panel scans of headroom over the poll interval.
    "ip_limit_fresh_seconds": "90",
    # Consecutive over-limit cycles before anything happens to the customer.
    # At the default 60s poll this is four minutes of sustained overage.
    "ip_limit_strikes": "4",
    # An address counts as really in use if xray dispatched something on it this
    # recently. Matches 3x-ui's own notion of live (partitionLiveIps, 120s).
    # This is what separates a Wi-Fi-to-mobile handover — whose old address sits
    # in the online map with a FROZEN timestamp until xray reaps it, up to
    # connIdle=300s later — from a second person actually using the link.
    "ip_limit_active_seconds": "120",
    # Prefix lengths the count groups by. 32 = the exact address.
    #
    # IPv4 stays at 32 on purpose. Grouping to /24 LOOKS like it protects mobile
    # customers and mostly does not: MCI and Irancell announce their CGNAT pools
    # predominantly as /20s, so a reassignment inside one pool crosses a /24
    # boundary all the time and only rarely a /16. It would blunt real sharing
    # detection while buying almost nothing. The churn defence here is the
    # last-seen check (see confirm_active), not address arithmetic. The setting
    # remains so the owner can widen it if their own log says otherwise.
    "ip_limit_ipv4_bits": "32",
    # /64 IS correct: an IPv6 host cycles privacy addresses inside its own /64,
    # so counting addresses there would manufacture violations out of one device.
    "ip_limit_ipv6_bits": "64",
    # The ladder, in seconds. The owner asked for 1 minute, 10 minutes, 1 hour.
    "ip_limit_steps": "60,600,3600",
    # Clean time after which the ladder drops back a rung.
    "ip_limit_decay_hours": "24",
    # Floor between two WARNING messages to the same customer, for the case
    # where they keep crossing back and forth over the allowance. Escalation
    # does not consult it — see decide().
    "ip_limit_warn_cooldown": "3600",
    # How long after a cut we still expect to SEE the customer's addresses
    # before concluding the cut did not take. Disabling a client stops new
    # handshakes but does not kill established connections, and xray only reaps
    # a half-open one after connIdle (300s by default) — so addresses linger for
    # a few minutes after a perfectly successful cut. Re-issuing the disable
    # during that window would be one wasted write per server per cycle for
    # nothing. After it, still seeing them means something really did switch
    # the customer back on.
    "ip_limit_reassert_after": "300",
    # How long the warning stands before the first cut. They asked to be told
    # first and only cut if it continues, so this is that grace.
    "ip_limit_grace_seconds": "300",
    # Keep the audit log bounded.
    "ip_limit_event_keep_days": "30",
}

# Public so the settings page and the tests read the same list.
SETTING_KEYS = tuple(DEFAULTS)


async def _cfg() -> Dict[str, str]:
    out = {}
    for key, default in DEFAULTS.items():
        try:
            out[key] = (await get_setting(key, default) or default)
        except Exception:
            out[key] = default
    return out


def _int(cfg: Dict[str, str], key: str, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(float(str(cfg.get(key, DEFAULTS[key]))))))
    except (TypeError, ValueError):
        return int(DEFAULTS[key])


def parse_steps(raw: str) -> List[int]:
    """The penalty ladder, in seconds, from a comma-separated setting.

    A malformed setting must not disable the feature silently, and must not
    produce a zero-length cut that reads as "restored immediately" — fall back
    to the documented ladder instead.
    """
    out: List[int] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            v = int(float(part))
        except (TypeError, ValueError):
            continue
        if v > 0:
            out.append(min(v, 86400))
    return out or [60, 600, 3600]


def group_key(ip: str, v4_bits: int = 32, v6_bits: int = 64) -> Optional[str]:
    """The network an address belongs to, or None if it is not one we count.

    IPv6 defaults to /64 because that is genuinely one host: a phone cycles
    privacy addresses inside its own /64 all day, and counting those separately
    would manufacture a violation out of one device.

    IPv4 defaults to /32 — the exact address — on purpose. Widening it to /24
    looks like it protects mobile customers and mostly does not, because the
    Iranian carriers announce their CGNAT pools as /20s, so a reassignment
    crosses a /24 boundary routinely. It would blunt real detection for almost
    no gain. The churn defence lives in the last-seen check, not here. The
    setting stays because the owner's own log may say otherwise.
    """
    raw = str(ip or "").strip()
    if not raw:
        return None
    # The panel can hand back "1.2.3.4:5678" or a bracketed v6 literal.
    if raw.startswith("["):
        raw = raw[1:].split("]", 1)[0]
    elif raw.count(":") == 1 and "." in raw:
        raw = raw.split(":", 1)[0]
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return None
    # Loopback and private addresses are the panel talking to itself, or a
    # local probe. They are not a customer and must never fill the allowance.
    if addr.is_loopback or addr.is_private or addr.is_link_local or addr.is_unspecified:
        return None
    if addr.version == 4:
        bits = max(8, min(32, int(v4_bits)))
    else:
        bits = max(16, min(128, int(v6_bits)))
    try:
        return str(ipaddress.ip_network(f"{addr}/{bits}", strict=False))
    except ValueError:
        return None


def count_concurrent(ip_maps: Iterable[Dict[str, int]], now: int, fresh_seconds: int,
                     v4_bits: int = 32, v6_bits: int = 64) -> Tuple[int, List[str]]:
    """How many distinct places are connected to this subscription right now.

    `ip_maps` is one {ip: last_seen_epoch_s} per node of the subscription. They
    are unioned, because the customer holds ONE link and we do not care which
    of their twelve nodes a device picked.
    """
    cutoff = now - max(10, int(fresh_seconds))
    groups: Dict[str, int] = {}
    for m in ip_maps:
        for ip, ts in (m or {}).items():
            if int(ts or 0) < cutoff:
                continue
            key = group_key(ip, v4_bits, v6_bits)
            if key and int(ts or 0) > groups.get(key, 0):
                groups[key] = int(ts or 0)
    ordered = sorted(groups, key=lambda k: -groups[k])
    return len(ordered), ordered


# ---------------------------------------------------------------- the decision

# What one cycle decides to do about one subscription.
ACT_NONE = "none"
ACT_WARN = "warn"
ACT_CUT = "cut"
ACT_RESTORE = "restore"
ACT_REASSERT = "reassert"


def decide(state: Dict, count: int, limit: int, now: int, *,
           strikes_needed: int, steps: Sequence[int], decay_seconds: int,
           warn_cooldown: int, grace_seconds: int,
           reassert_after: int = 300) -> Dict:
    """Pure state machine: what should happen to this subscription, and why.

    Kept free of I/O so the whole ladder — including the parts that only happen
    after an hour — can be tested in a loop in milliseconds. `state` is the
    stored row (or an empty dict) and the return carries the NEW state, so the
    caller never has to reproduce the arithmetic.
    """
    level = int(state.get("level") or 0)
    strikes = int(state.get("strikes") or 0)
    over_since = int(state.get("over_since") or 0)
    penalty_until = int(state.get("penalty_until") or 0)
    last_violation = int(state.get("last_violation_at") or 0)
    last_warned = int(state.get("last_warned_at") or 0)
    peak = max(int(state.get("peak_ip_count") or 0), int(count))

    new = {
        "level": level, "strikes": strikes, "over_since": over_since,
        "penalty_until": penalty_until, "last_violation_at": last_violation,
        "last_warned_at": last_warned, "last_ip_count": int(count),
        "peak_ip_count": peak,
    }

    # Already serving a penalty.
    if penalty_until > now:
        # Still connecting long after the cut means it did not take — the panel
        # rejected it, or another code path switched the clients back on. Only
        # after the drain window, though: a successful cut leaves established
        # connections alive until xray reaps them, so seeing addresses in the
        # first few minutes is normal and re-issuing then would be a wasted
        # write per server every cycle.
        cut_at = int(state.get("cut_at") or 0)
        if count > 0 and cut_at and (now - cut_at) >= max(30, reassert_after):
            return dict(new, action=ACT_REASSERT,
                        reason="still connecting well after the cut")
        return dict(new, action=ACT_NONE, reason="serving penalty")

    # The penalty just ran out.
    if penalty_until > 0:
        new["penalty_until"] = 0
        new["strikes"] = 0
        new["over_since"] = 0
        return dict(new, action=ACT_RESTORE, reason="penalty served")

    # Not cut. Has the ladder gone cold?
    if level > 0 and last_violation and (now - last_violation) >= decay_seconds:
        # One rung per clean decay window, rather than all the way to zero, so a
        # repeat offender who behaves for a day does not get a full amnesty.
        level = max(0, level - 1)
        new["level"] = level
        new["last_violation_at"] = now if level > 0 else 0
        if level == 0:
            new["peak_ip_count"] = 0
            new["last_warned_at"] = 0

    if count <= limit:
        new["strikes"] = 0
        new["over_since"] = 0
        # Coming back inside the allowance closes the episode, so the next one
        # starts with a warning again rather than an immediate cut. This is also
        # what stops a standing warning from blocking escalation forever.
        new["last_warned_at"] = 0
        return dict(new, action=ACT_NONE, reason="within the allowance")

    # Over the allowance.
    strikes += 1
    new["strikes"] = strikes
    if not over_since:
        over_since = now
        new["over_since"] = over_since

    if strikes < strikes_needed:
        return dict(new, action=ACT_NONE,
                    reason=f"over by {count - limit}, {strikes}/{strikes_needed} readings")

    # Confirmed: sustained, not a blip.
    new["last_violation_at"] = now

    # They asked to be TOLD first and only cut if it carries on. So the first
    # confirmation of an episode warns, and the cut waits for the grace period
    # to elapse with the customer STILL over.
    #
    # `last_warned_at` is an outstanding warning, not a rate limiter. It is
    # cleared the moment they come back inside the allowance, and never
    # re-issued while they stay over — otherwise a customer who ignored the
    # warning would simply be warned again an hour later, with the grace timer
    # reset, and would escalate to a cut on no schedule at all.
    if not last_warned:
        new["last_warned_at"] = now
        return dict(new, action=ACT_WARN,
                    reason=f"{count} places connected, allowance {limit}")

    if (now - last_warned) < grace_seconds:
        return dict(new, action=ACT_NONE, reason="warned, inside the grace period")

    seconds = int(steps[min(level, len(steps) - 1)])
    new["level"] = level + 1
    new["penalty_until"] = now + seconds
    new["cut_at"] = now
    new["strikes"] = 0
    new["over_since"] = 0
    new["last_warned_at"] = now
    return dict(new, action=ACT_CUT, seconds=seconds,
                reason=f"{count} places connected, allowance {limit}")


# ---------------------------------------------------------------- the messages

def warn_text(count: int, limit: int, brand: str = "") -> str:
    return (
        "⚠️ اتصال هم‌زمان بیش از حد مجاز\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"روی اشتراک شما همین حالا از {count} مکان مختلف به‌طور هم‌زمان اتصال برقرار است، "
        f"در حالی که سقف مجاز {limit} اتصال هم‌زمان است.\n\n"
        "لطفاً دستگاه‌های اضافه را قطع کنید. اگر لینک اشتراکتان را به کسی داده‌اید، "
        "از بخش «تغییر لینک اشتراک» می‌توانید لینک را عوض کنید تا فقط در اختیار خودتان باشد.\n\n"
        "اگر ادامه پیدا کند، اتصال شما به‌صورت موقت قطع خواهد شد "
        "(بار اول ۱ دقیقه، سپس ۱۰ دقیقه و ۱ ساعت).\n\n"
        "ℹ️ اگر با اینترنت همراه هستید و فقط یک دستگاه دارید، نگران نباشید — "
        "تغییر آی‌پی سیم‌کارت به‌عنوان اتصال جدید شمرده نمی‌شود."
    )


def cut_text(seconds: int, count: int, limit: int) -> str:
    if seconds >= 3600:
        span = f"{seconds // 3600} ساعت"
    elif seconds >= 60:
        span = f"{seconds // 60} دقیقه"
    else:
        span = f"{seconds} ثانیه"
    return (
        "⛔️ اتصال شما موقتاً قطع شد\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"با وجود هشدار، هم‌زمان از {count} مکان به اشتراک شما متصل بود "
        f"(سقف مجاز: {limit}).\n\n"
        f"اشتراک شما به مدت {span} غیرفعال شد و پس از آن خودکار برمی‌گردد.\n"
        "زمان و حجم اشتراکتان از بین نمی‌رود.\n\n"
        "برای اینکه دوباره تکرار نشود، دستگاه‌های اضافه را قطع کنید."
    )


def restore_text() -> str:
    return (
        "✅ اشتراک شما دوباره فعال شد\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "اگر برنامه‌تان وصل نشد، یک بار قطع و دوباره وصل کنید.\n"
        "لطفاً سقف اتصال هم‌زمان را رعایت کنید تا قطعی تکرار نشود."
    )


# ---------------------------------------------------------------- the cycle

# What "cut" actually buys, so nobody is surprised later. Disabling a client
# removes it from xray's validator, which is consulted at HANDSHAKE. Xray does
# not walk live sockets and kill them (verified in
# proxy/vless/inbound/inbound.go::RemoveUser — it deletes two sync.Map entries
# and returns). So a cut stops NEW connections immediately and lets established
# ones drain. In practice browsing breaks within seconds, because every new
# destination is a new dispatch, but a client using mux can keep one tunnel
# alive for a while longer. The 1-minute rung is therefore mostly a warning
# shot with teeth, and the 10-minute and 1-hour rungs are the real deterrent.

# A server whose panel answers but reports no addresses at all, while clients
# ARE online there, cannot be policed. That happens when xray sits behind nginx
# or HAProxy without PROXY protocol (the core drops 127.0.0.1 from its online
# map), or when `statsUserOnline` is missing from the policy level. Silently
# never enforcing would be the worst outcome, so it is counted and surfaced.
_BLIND_STREAK_ALERT = 5


async def _fetch_server_ips(server: Dict, timeout: float = 20.0) -> Tuple[int, Optional[Dict[str, Dict[str, int]]], int]:
    """(server_id, {email: {ip: ts}} or None, online_email_count).

    One login and two cheap requests per server per cycle. The online count is
    read from the same session purely to tell "nobody is connected" apart from
    "we cannot see anybody", which is the difference between a quiet night and a
    misconfigured server.
    """
    sid = int(server["id"])
    cli = XUIClient(
        server["url"], server["username"], server["password"],
        server.get("sub_path") or "", server.get("api_token", "") or "",
    )
    try:
        ips = await asyncio.wait_for(cli.get_client_ips_bulk(), timeout=timeout)
        online = 0
        if ips is not None:
            try:
                emails, ok = await asyncio.wait_for(cli.get_onlines_checked(), timeout=timeout)
                online = len(emails) if ok else 0
            except (asyncio.TimeoutError, Exception):
                online = 0
        return sid, ips, online
    except asyncio.TimeoutError:
        logger.warning("ip guard: %s timed out", server.get("name") or sid)
        return sid, None, 0
    except Exception as e:
        logger.warning("ip guard: %s failed: %s", server.get("name") or sid, e)
        return sid, None, 0
    finally:
        await cli.close()


async def _apply_enabled(servers_by_id: Dict[int, Dict], per_server: Dict[int, List[str]],
                         enabled: bool) -> Dict[int, bool]:
    """Switch a batch of node clients on or off, ONE request per server.

    Emails from every affected subscription are pooled per server first, so
    cutting five customers in the same cycle still costs five requests, not
    twenty-five. Never loops per client — see the module docstring.
    """
    out: Dict[int, bool] = {}

    async def one(sid: int, emails: List[str]) -> None:
        server = servers_by_id.get(sid)
        if not server or not emails:
            out[sid] = False
            return
        cli = XUIClient(
            server["url"], server["username"], server["password"],
            server.get("sub_path") or "", server.get("api_token", "") or "",
        )
        try:
            r = await asyncio.wait_for(
                cli.bulk_set_clients_enabled(sorted(set(emails)), enabled), timeout=30)
            out[sid] = r is not None
            if r is None:
                logger.warning("ip guard: bulk %s failed on %s: %s",
                               "enable" if enabled else "disable",
                               server.get("name") or sid, cli.last_error or "unknown")
        except Exception as e:
            logger.warning("ip guard: bulk %s errored on %s: %s",
                           "enable" if enabled else "disable", server.get("name") or sid, e)
            out[sid] = False
        finally:
            await cli.close()

    await asyncio.gather(*(one(sid, em) for sid, em in per_server.items()),
                         return_exceptions=True)
    return out


async def _notify(bot, telegram_id: int, text: str) -> None:
    if not bot or not telegram_id:
        return
    try:
        await bot.send_message(int(telegram_id), text, parse_mode=None,
                               disable_web_page_preview=True)
    except Exception as e:
        # A customer who blocked the bot must not stop the cycle for everyone else.
        logger.debug("ip guard: could not message %s: %s", telegram_id, e)


async def confirm_active(servers_by_id: Dict[int, Dict], nodes: Sequence[Tuple[int, str]],
                         suspect_emails_by_server: Dict[int, List[str]], now: int,
                         active_seconds: int, v4_bits: int, v6_bits: int,
                         timeout: float = 15.0) -> Tuple[int, List[str]]:
    """Second look at ONE subscription, using the honest timestamps.

    The bulk endpoint re-stamps every address with the time of the scan, so it
    can say "these addresses are in the online map" but not "these addresses are
    carrying traffic". That distinction is the entire difference between a
    commuter and a sharer, so before anyone is warned or cut we ask the per-email
    endpoint, which keeps xray's real lastSeen, and drop anything that has gone
    quiet.

    This costs one request per suspect client — a handful — and only runs on the
    cycle that is about to act on somebody. It is never part of the scan.
    """
    by_email_server: Dict[str, int] = {email: sid for sid, email in nodes}
    groups: Dict[str, int] = {}
    unknown = False

    async def one(sid: int, emails: List[str]) -> None:
        nonlocal unknown
        server = servers_by_id.get(sid)
        if not server:
            return
        cli = XUIClient(
            server["url"], server["username"], server["password"],
            server.get("sub_path") or "", server.get("api_token", "") or "",
        )
        try:
            for email in emails:
                try:
                    m = await asyncio.wait_for(cli.get_client_ips(email), timeout=timeout)
                except Exception:
                    m = None
                if m is None:
                    # The panel would not say. Refusing to count it is the safe
                    # direction: we under-count and nobody is cut by accident.
                    unknown = True
                    continue
                for ip, ts in m.items():
                    if int(ts or 0) < now - max(30, int(active_seconds)):
                        continue
                    key = group_key(ip, v4_bits, v6_bits)
                    if key and int(ts or 0) > groups.get(key, 0):
                        groups[key] = int(ts or 0)
        finally:
            await cli.close()

    await asyncio.gather(*(one(sid, em) for sid, em in suspect_emails_by_server.items()),
                         return_exceptions=True)
    ordered = sorted(groups, key=lambda k: -groups[k])
    if unknown and not ordered:
        # Nothing came back at all — say "unknown" rather than "zero", or a
        # flapping panel would read as a clean customer and reset their ladder.
        return -1, []
    return len(ordered), ordered


async def restore_all(reason: str = "") -> int:
    """Switch every currently-cut subscription back on and forget the ladder.

    Called when the feature is switched off, so turning the toggle off in the
    panel is a real undo and never strands a customer mid-penalty.
    """
    from core.database import get_cut_profiles
    cut = await get_cut_profiles()
    if not cut:
        return 0
    servers = {int(s["id"]): s for s in await get_servers(active_only=False)}
    rows = {r["profile_id"]: r for r in await get_ip_guard_profile_nodes()}
    per_server: Dict[int, List[str]] = {}
    for state in cut:
        pid = int(state["profile_id"])
        for sid, email in (rows.get(pid) or {}).get("nodes", []):
            per_server.setdefault(sid, []).append(email)
    if per_server:
        await _apply_enabled(servers, per_server, True)
    for state in cut:
        pid = int(state["profile_id"])
        await clear_ip_guard_state(pid)
        await add_ip_guard_event(pid, "restored", detail=reason or "guard switched off")
    logger.info("ip guard: restored %s subscriptions (%s)", len(cut), reason or "off")
    return len(cut)


async def run_cycle(bot=None) -> Dict:
    """One pass. Returns a summary the worker logs and the panel can show.

    Cost on this fleet: 5 logins and 10 requests for the whole base of 244
    subscriptions, plus one request per affected server only when somebody is
    actually being cut or restored. Two SQLite queries to load, and a write only
    for subscriptions whose state changed.
    """
    cfg = await _cfg()
    now = int(time.time())

    if cfg["ip_limit_enabled"] != "1":
        restored = await restore_all("feature is switched off")
        return {"enabled": False, "restored": restored}

    warn_only = cfg["ip_limit_warn_only"] == "1"
    default_limit = _int(cfg, "ip_limit_default", 1, 1000)
    fresh = _int(cfg, "ip_limit_fresh_seconds", 20, 1800)
    strikes_needed = _int(cfg, "ip_limit_strikes", 1, 20)
    v4_bits = _int(cfg, "ip_limit_ipv4_bits", 8, 32)
    v6_bits = _int(cfg, "ip_limit_ipv6_bits", 16, 128)
    steps = parse_steps(cfg["ip_limit_steps"])
    decay = _int(cfg, "ip_limit_decay_hours", 1, 8760) * 3600
    warn_cooldown = _int(cfg, "ip_limit_warn_cooldown", 60, 86400)
    grace = _int(cfg, "ip_limit_grace_seconds", 30, 86400)
    active_seconds = _int(cfg, "ip_limit_active_seconds", 30, 1800)
    reassert_after = _int(cfg, "ip_limit_reassert_after", 30, 7200)

    profiles = await get_ip_guard_profile_nodes()
    states = await get_ip_guard_states()
    servers = await get_servers(active_only=True)
    servers_by_id = {int(s["id"]): s for s in servers}
    if not profiles or not servers:
        return {"enabled": True, "profiles": len(profiles), "servers": len(servers)}

    # --- observe: one login + two requests per server, all servers at once
    results = await asyncio.gather(*(_fetch_server_ips(s) for s in servers),
                                   return_exceptions=True)
    by_email: Dict[str, Dict[str, int]] = {}
    by_server_email: Dict[int, Dict[str, Dict[str, int]]] = {}
    answered = blind = 0
    blind_names: List[str] = []
    for r in results:
        if isinstance(r, BaseException) or not isinstance(r, tuple):
            continue
        sid, ips, online = r
        if ips is None:
            continue
        answered += 1
        fresh_emails = 0
        by_server_email[sid] = ips
        for email, m in ips.items():
            bucket = by_email.setdefault(email, {})
            for ip, ts in m.items():
                if ts > bucket.get(ip, 0):
                    bucket[ip] = ts
            if any(ts >= now - fresh for ts in m.values()):
                fresh_emails += 1
        # Clients are connected here and yet not one address came back: this
        # server cannot be policed, and saying nothing would look like consent.
        if online > 0 and fresh_emails == 0:
            blind += 1
            blind_names.append(str(servers_by_id.get(sid, {}).get("name") or sid))

    if answered == 0:
        # Every panel is unreachable. Do nothing at all — deciding on an empty
        # observation would restore everyone's penalty early and, worse, would
        # read "nobody is connected" as good behaviour.
        logger.warning("ip guard: no panel answered, skipping this cycle")
        return {"enabled": True, "answered": 0, "skipped": True}

    # --- decide
    cut_now: Dict[int, List[str]] = {}
    restore_now: Dict[int, List[str]] = {}
    reassert: Dict[int, List[str]] = {}
    acted: List[Dict] = []
    # Accumulated and flushed in ONE transaction at the end. Writing per
    # subscription costs one fsync each — measured 666 ms for 244 rows against
    # 2.6 ms batched — and SQLite has a single writer, so that time is taken
    # away from the bot too.
    pending_state: List[tuple] = []
    pending_events: List[Dict] = []

    for row in profiles:
        pid = row["profile_id"]
        limit = int(row.get("ip_limit") or 0) or default_limit
        maps = [by_email.get(email, {}) for _, email in row["nodes"]]
        count, groups = count_concurrent(maps, now, fresh, v4_bits, v6_bits)
        state = states.get(pid) or {}

        # Stage two. The scan above can only say "these addresses are in the
        # online map"; it cannot tell a busy address from a half-open one,
        # because the bulk endpoint re-stamps every timestamp. So on the one
        # reading that would actually do something to this customer, ask the
        # per-email endpoint — which keeps xray's real lastSeen — and act on
        # that instead. A handful of requests, and only for a suspect.
        if count > limit and int(state.get("strikes") or 0) + 1 >= strikes_needed:
            suspects: Dict[int, List[str]] = {}
            for sid, email in row["nodes"]:
                m = (by_server_email.get(sid) or {}).get(email)
                if m and any(int(ts or 0) >= now - fresh for ts in m.values()):
                    suspects.setdefault(sid, []).append(email)
            if suspects:
                confirmed, confirmed_groups = await confirm_active(
                    servers_by_id, row["nodes"], suspects, now,
                    active_seconds, v4_bits, v6_bits)
                if confirmed < 0:
                    # Could not confirm. Leave the state exactly as it was and
                    # try again next cycle rather than guessing in either
                    # direction — a wrong guess here either cuts an innocent
                    # customer or wipes a real offender's strike count.
                    continue
                count, groups = confirmed, confirmed_groups

        d = decide(state, count, limit, now,
                   strikes_needed=strikes_needed, steps=steps, decay_seconds=decay,
                   warn_cooldown=warn_cooldown, grace_seconds=grace,
                   reassert_after=reassert_after)
        action = d["action"]

        if action == ACT_NONE:
            # Only write when something actually moved, so a quiet base of 244
            # subscriptions does not produce 244 writes a minute.
            if (int(state.get("last_ip_count") or 0) != count
                    or int(state.get("strikes") or 0) != d["strikes"]
                    or int(state.get("level") or 0) != d["level"]):
                pending_state.append((pid, d))
            continue

        if action == ACT_WARN:
            pending_state.append((pid, d))
            pending_events.append({"profile_id": pid, "kind": "warned", "level": d["level"],
                                   "ip_count": count, "limit_used": limit,
                                   "detail": ", ".join(groups[:8])})
            # A customer flapping either side of the allowance would otherwise
            # be messaged every few minutes. The warning still STANDS — the
            # escalation clock is unaffected — we just do not say it twice.
            prev = int(state.get("last_violation_at") or 0)
            if not prev or (now - prev) >= warn_cooldown:
                await _notify(bot, row["telegram_id"], warn_text(count, limit))
            acted.append({"profile_id": pid, "action": "warned", "count": count})
            continue

        if action == ACT_CUT:
            if warn_only:
                # Dry run: record what would have happened and tell nobody's
                # connection to stop. The ladder does NOT advance, so the log
                # reads as "this is what arming it would have done".
                pending_events.append({"profile_id": pid, "kind": "would_cut",
                                       "level": int(state.get("level") or 0),
                                       "ip_count": count, "limit_used": limit,
                                       "detail": f"{d.get('seconds')}s — " + ", ".join(groups[:8])})
                keep = dict(d)
                keep["penalty_until"] = 0
                keep["level"] = int(state.get("level") or 0)
                pending_state.append((pid, keep))
                acted.append({"profile_id": pid, "action": "would_cut", "count": count})
                continue
            for sid, email in row["nodes"]:
                cut_now.setdefault(sid, []).append(email)
            pending_state.append((pid, d))
            pending_events.append({"profile_id": pid, "kind": "cut", "level": d["level"],
                                   "ip_count": count, "limit_used": limit,
                                   "detail": f"{d.get('seconds')}s — " + ", ".join(groups[:8])})
            await _notify(bot, row["telegram_id"], cut_text(int(d.get("seconds") or 0), count, limit))
            acted.append({"profile_id": pid, "action": "cut", "count": count,
                          "seconds": d.get("seconds")})
            continue

        if action == ACT_RESTORE:
            for sid, email in row["nodes"]:
                restore_now.setdefault(sid, []).append(email)
            pending_state.append((pid, d))
            pending_events.append({"profile_id": pid, "kind": "restored", "level": d["level"],
                                   "ip_count": count, "limit_used": limit})
            await _notify(bot, row["telegram_id"], restore_text())
            acted.append({"profile_id": pid, "action": "restored"})
            continue

        if action == ACT_REASSERT:
            # The cut did not take. Re-issue it, but only because we can SEE
            # them still connecting — never on a timer.
            for sid, email in row["nodes"]:
                reassert.setdefault(sid, []).append(email)
            pending_state.append((pid, {**{k: v for k, v in d.items()
                                          if k not in ("action", "reason", "seconds")},
                                       "restore_fails": int(state.get("restore_fails") or 0) + 1}))
            acted.append({"profile_id": pid, "action": "reasserted", "count": count})

    # --- persist FIRST, in one transaction each. Before the panel writes on
    # purpose: if a panel hangs, the decision is already durable and the next
    # cycle re-asserts it, rather than the customer's ladder silently resetting.
    if pending_state:
        await save_ip_guard_states_bulk(pending_state)
    if pending_events:
        await add_ip_guard_events_bulk(pending_events)

    # --- apply, batched per server
    if cut_now or reassert:
        merged: Dict[int, List[str]] = {}
        for src in (cut_now, reassert):
            for sid, emails in src.items():
                merged.setdefault(sid, []).extend(emails)
        await _apply_enabled(servers_by_id, merged, False)
    if restore_now:
        await _apply_enabled(servers_by_id, restore_now, True)

    if blind:
        logger.warning("ip guard: %s server(s) report clients online but no addresses "
                       "(%s) — xray may be behind a proxy without PROXY protocol, or "
                       "statsUserOnline is off", blind, ", ".join(blind_names))

    # Housekeeping, cheap and rare.
    if now % 3600 < _int(cfg, "ip_limit_poll_seconds", 15, 3600):
        await prune_ip_guard_events(_int(cfg, "ip_limit_event_keep_days", 1, 3650))

    return {
        "enabled": True, "warn_only": warn_only, "profiles": len(profiles),
        "answered": answered, "blind": blind, "blind_servers": blind_names,
        "acted": acted, "watched_emails": len(by_email),
    }
