"""Switching off the legacy single-server configs, safely.

Every config sold before the subscription engine lives in the `configs` table
and has one client on one x-ui panel. Those sales stopped; what is left is a
tail of rows that are still flagged active locally AND still enabled on the
panels, long after they expired. This module turns them off.

WHY THIS IS NOT A FOR-LOOP OVER update_client — read before changing anything.

1. **One client write = one xray reload = every live connection on that server
   drops.** That is 3x-ui's behaviour, and it is why `multi_subscription.py`
   goes to such lengths to avoid redundant writes (see PROJECT_MAP §6). Turning
   off 200 legacy clients one at a time would reload xray 200 times and take
   every OTHER customer on those servers down with it — including subscription
   customers who have nothing to do with this. So the sweep uses 3x-ui's
   `bulkDisable` (v3.7+), which groups the emails by inbound and does a single
   read-modify-write per inbound. Per-client is the FALLBACK for old panels, and
   the log says so out loud when it happens.

2. **Legacy configs and subscription nodes share inbounds.** On the reference
   deployment two inbounds hold a handful of legacy clients next to hundreds of
   subscription clients. `bulkDisable` selects purely by email, so this module
   subtracts every subscription-node email BEFORE calling it, and also refuses
   any email shaped like a subscription node (`…_n<digits>`) even when the
   matching node row has since been deleted. A legacy row can carry such an
   email — one does on the live database — and disabling it would cut off a
   subscription customer whose node row was cleaned up.

3. **A config whose server row was deleted can only be fixed locally.** It is
   unreachable by definition; the sweep marks it inactive in our database and
   reports it separately rather than pretending it was switched off on a panel.

4. **Disabling is close to one-way.** 3x-ui had a bug (MHSanaei/3x-ui#4705)
   where a manually-disabled client could not be re-enabled and had to be
   recreated. The UI wording must not promise a clean undo.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Callable, Dict, List, Optional

from core.database import (
    get_legacy_configs_for_disable,
    get_subscription_node_emails,
    set_configs_inactive,
)
from core.xui_api import XUIClient

logger = logging.getLogger(__name__)

# The subscription engine names its clients `{profile_email}_n{config_id}` —
# that suffix is load-bearing (PROJECT_MAP §6). Anything wearing it belongs to
# the subscription namespace and is never ours to switch off.
SUB_EMAIL_SUFFIX = re.compile(r"_n\d+$")

# How many emails go in one bulkDisable call. The panel holds the whole batch in
# memory and rewrites each affected inbound once, so a huge batch is a long
# single request; a few hundred keeps each call quick without giving up the
# one-reload-per-inbound win.
CHUNK = 200

SCOPES = ("expired", "all")


def _is_protected(email: str, sub_emails: set) -> Optional[str]:
    """Reason this email must not be touched, or None if it is safe."""
    e = (email or "").strip()
    if not e:
        return "no_email"
    if e in sub_emails:
        return "belongs_to_a_subscription"
    if SUB_EMAIL_SUFFIX.search(e):
        # Its subscription-node row is gone but the client on the panel may not
        # be — refusing costs us one stale row, guessing costs a live customer.
        return "looks_like_a_subscription_node"
    return None


async def _classify(scope: str) -> Dict:
    """Split the candidate rows into what we can do with each."""
    only_expired = scope != "all"
    rows = await get_legacy_configs_for_disable(only_expired, int(time.time() * 1000))
    sub_emails = await get_subscription_node_emails()

    reachable: Dict[int, Dict] = {}   # server_id -> {server, configs}
    orphans: List[Dict] = []
    protected: List[Dict] = []

    for row in rows:
        reason = _is_protected(row.get("email") or "", sub_emails)
        if reason:
            protected.append({"id": int(row["id"]), "email": row.get("email") or "", "reason": reason})
            continue
        if not (row.get("server_url") or "").strip():
            orphans.append(row)
            continue
        sid = int(row["server_id"])
        bucket = reachable.setdefault(sid, {"server": row, "configs": []})
        bucket["configs"].append(row)

    return {"reachable": reachable, "orphans": orphans, "protected": protected, "total": len(rows)}


async def preview(scope: str = "expired") -> Dict:
    """What a sweep would do, without doing any of it."""
    c = await _classify(scope)
    return {
        "scope": scope if scope in SCOPES else "expired",
        "total": c["total"],
        "on_panels": sum(len(b["configs"]) for b in c["reachable"].values()),
        "orphaned": len(c["orphans"]),
        "protected": len(c["protected"]),
        "protected_samples": c["protected"][:5],
        "servers": [{
            "id": sid,
            "name": b["server"].get("server_name") or f"#{sid}",
            "count": len(b["configs"]),
            "inbounds": sorted({int(x.get("inbound_id") or 0) for x in b["configs"]}),
        } for sid, b in sorted(c["reachable"].items())],
    }


async def disable_all(scope: str = "expired", log: Optional[Callable[[str], None]] = None) -> Dict:
    """Switch off every targeted legacy config, one server at a time.

    Local rows are only marked inactive for clients the panel actually confirmed
    (plus orphans, which have no panel). A client we failed to disable stays
    flagged active so the next run retries it, rather than disappearing from the
    list while still passing traffic.
    """
    say = log or (lambda _m: None)
    scope = scope if scope in SCOPES else "expired"
    c = await _classify(scope)

    say(f"شروع — دامنه: {'همه کانفیگ‌های فعال' if scope == 'all' else 'فقط منقضی‌شده‌ها'}")
    say(f"کل نامزدها: {c['total']}")
    if c["protected"]:
        say(f"⛔ {len(c['protected'])} مورد کنار گذاشته شد چون به سابسکریپشن تعلق دارند:")
        for p in c["protected"][:10]:
            say(f"   • {p['email']} — {p['reason']}")

    disabled_ids: List[int] = []
    failed = 0
    reload_warned = False

    for sid, bucket in sorted(c["reachable"].items()):
        server = bucket["server"]
        configs = bucket["configs"]
        name = server.get("server_name") or f"#{sid}"
        emails = [r["email"] for r in configs]
        by_email = {r["email"]: r for r in configs}
        say(f"\n🖥 {name} — {len(emails)} کانفیگ")

        cli = XUIClient(server["server_url"], server["srv_user"], server["srv_pass"],
                        server.get("sub_path") or "", server.get("srv_api_token") or "")
        try:
            ok_emails: List[str] = []
            # "bulk" = the fast path worked · "old_panel" = no such endpoint, use
            # the per-client fallback · "error" = the panel refused for some other
            # reason, so stop rather than repeat the same failure N times.
            outcome = "bulk"
            for i in range(0, len(emails), CHUNK):
                chunk = emails[i:i + CHUNK]
                result = await cli.bulk_set_clients_enabled(chunk, enabled=False)
                if result is None:
                    err = (cli.last_error or "").lower()
                    outcome = "old_panel" if ("404" in err or "not found" in err) else "error"
                    if outcome == "error":
                        say(f"   ❌ bulkDisable رد شد: {cli.last_error}")
                    break
                skipped = {str(s.get("email")): str(s.get("reason") or "") for s in result.get("skipped") or []}
                for e in chunk:
                    if e in skipped:
                        # "client not found" means it is already gone from the
                        # panel — nothing left to switch off, so the local row is
                        # simply out of date and safe to correct.
                        if "not found" in skipped[e].lower():
                            ok_emails.append(e)
                        else:
                            say(f"   ⚠️ {e}: {skipped[e]}")
                    else:
                        ok_emails.append(e)
                say(f"   دسته {i // CHUNK + 1}: {result.get('changed', 0)} تغییر، {len(skipped)} رد شد")

            if outcome == "old_panel":
                if not reload_warned:
                    say("   ℹ️ این پنل bulkDisable ندارد (نسخه قدیمی‌تر از 3.7).")
                    say("      برمی‌گردیم به حالت تک‌به‌تک — کندتر است و برای هر کلاینت")
                    say("      یک بار xray ری‌استارت می‌شود. ممکن است اتصال‌های زنده لحظه‌ای قطع شوند.")
                    reload_warned = True
                ok_emails = []
                for row in configs:
                    try:
                        done = await cli.update_client(
                            int(row["inbound_id"]), row["uuid"], row["email"],
                            float(row.get("traffic_gb") or 0),
                            int(row.get("expire_timestamp") or 0),
                            enable=False,
                        )
                    except Exception as e:
                        done = False
                        say(f"   ⚠️ {row['email']}: {e}")
                    if done:
                        ok_emails.append(row["email"])
                    else:
                        failed += 1
                    # Breathe between writes so the panel is not hammered while
                    # it is reloading xray for the previous one.
                    await asyncio.sleep(0.3)

            confirmed = [int(by_email[e]["id"]) for e in ok_emails if e in by_email]
            if outcome != "old_panel":
                # The per-client fallback counts its own failures as it goes;
                # the other two paths account for the whole server here.
                failed += len(emails) - len(confirmed)
            disabled_ids.extend(confirmed)
            say(f"   ✅ {len(confirmed)} از {len(emails)} روی پنل غیرفعال شد")
        except Exception as e:
            logger.exception("legacy disable failed on server %s: %s", sid, e)
            say(f"   ❌ خطا روی این سرور: {e}")
            failed += len(emails)
        finally:
            await cli.close()

    if c["orphans"]:
        say(f"\n🗃 {len(c['orphans'])} کانفیگ روی سروری هستند که دیگر وجود ندارد —")
        say("   روی پنل قابل دسترسی نیستند؛ فقط در دیتابیس غیرفعال می‌شوند.")
        disabled_ids.extend(int(r["id"]) for r in c["orphans"])

    updated = await set_configs_inactive(disabled_ids)
    say(f"\n🏁 پایان — {updated} کانفیگ غیرفعال شد"
        + (f"، {failed} ناموفق (در اجرای بعدی دوباره تلاش می‌شود)" if failed else ""))
    return {
        "ok": True,
        "scope": scope,
        "disabled": updated,
        "failed": failed,
        "orphaned": len(c["orphans"]),
        "protected": len(c["protected"]),
    }


async def sweep_expired(limit: int = 300) -> Dict:
    """Background pass: keep expired legacy configs from sitting flagged active.

    Nothing used to switch these off — the alert worker only warned about them —
    so the local `is_active` flag drifted until "active services" on the
    dashboard counted hundreds of long-dead configs. Runs quietly and is a no-op
    once the tail is cleared.
    """
    c = await _classify("expired")
    pending = sum(len(b["configs"]) for b in c["reachable"].values()) + len(c["orphans"])
    if not pending:
        return {"ok": True, "disabled": 0}
    if pending > limit:
        # Leave the big first clean-up to the admin, who gets a preview and a
        # progress log; a background task should not quietly rewrite inbounds
        # across the whole fleet.
        logger.info("legacy sweep: %s expired configs pending — left for the panel action", pending)
        return {"ok": True, "disabled": 0, "deferred": pending}
    return await disable_all("expired")
