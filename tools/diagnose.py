"""Read-only health report for the parts that fail quietly.

Run it on the server, in the bot's directory:

    python tools/diagnose.py              # everything
    python tools/diagnose.py 123          # ...plus one subscription in detail

WHY THIS EXISTS RATHER THAN A REMOTE LOGIN. The failures this covers — an AI
model id that no longer exists, a background worker that never restarted, a
feature that is simply switched off — all look identical from the outside: the
thing does not happen and nothing says why. The fix for that is not standing
access into a production server for someone to poke around in; it is a command
that answers the question and prints something safe to paste into a chat.

So this NEVER prints a secret. API keys, panel passwords and subscription
tokens are reported as present-or-absent and by length, never by value. It only
reads, and it makes at most one login and two cheap queries per panel.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def head(t):
    print(f"\n{'=' * 62}\n{t}\n{'=' * 62}")


def row(k, v, note=""):
    print(f"  {k:.<34} {v}" + (f"   {note}" if note else ""))


def secret(v):
    """Never the value. Enough to tell 'missing' from 'probably a typo'."""
    v = (v or "").strip()
    return f"set ({len(v)} chars)" if v else "NOT SET"


def ago(ts):
    if not ts:
        return "never"
    d = int(time.time()) - int(ts)
    if d < 90:
        return f"{d}s ago"
    if d < 5400:
        return f"{d // 60}m ago"
    return f"{d // 3600}h ago"


async def main():
    from core.database import get_setting, get_servers, init_db
    await init_db()

    head("bot / process")
    row("database", os.path.abspath(getattr(__import__("core.config", fromlist=["DB_PATH"]), "DB_PATH")))
    row("public base url", await get_setting("public_base_url", "") or "NOT SET")

    head("AI analyst")
    from core import ai_analyst
    cfg = await ai_analyst.settings()
    row("enabled", "yes" if cfg["ai_enabled"] == "1" else "NO")
    row("provider", cfg["ai_provider"])
    row("model", ai_analyst._clean_model(cfg["ai_model"]) or "NOT SET")
    row("base url", cfg["ai_base_url"] or "(default)")
    row("api key", secret(cfg["ai_api_key"]))
    if cfg["ai_api_key"]:
        print("\n  asking the key which models it can use…")
        lm = await ai_analyst.list_models(cfg)
        if not lm.get("ok"):
            row("  result", f"FAILED — {lm.get('error')}", lm.get("message", "")[:80])
        else:
            names = [m["id"] for m in lm["models"]]
            row("  models available", len(names))
            for n in names[:10]:
                mark = "  <-- currently selected" if n == lm.get("current") else ""
                print(f"      {n}{mark}")
            if lm.get("current") and lm["current"] not in names:
                print(f"\n  ⚠️  '{lm['current']}' is NOT in that list — that is the 404.")

    head("connection limit (ip guard)")
    from core import ip_guard
    g = await ip_guard._cfg()
    enabled = g["ip_limit_enabled"] == "1"
    row("enabled", "yes" if enabled else "NO  <-- nothing will ever fire")
    row("warn only", "yes  <-- warns but never cuts" if g["ip_limit_warn_only"] == "1" else "no")
    row("default limit", g["ip_limit_default"])
    row("readings before acting", g["ip_limit_strikes"])
    row("poll seconds", g["ip_limit_poll_seconds"])
    row("ladder", g["ip_limit_steps"])
    last = int(float(await get_setting("ip_limit_last_run", "0") or 0))
    poll = int(float(g["ip_limit_poll_seconds"] or 60))
    alive = last and (int(time.time()) - last) < poll * 3
    row("worker last ran", ago(last),
        "" if alive else "<-- NOT RUNNING. restart the bot service.")

    head("panels")
    from core.xui_api import XUIClient
    servers = await get_servers(active_only=True)
    row("active servers", len(servers))
    for s in servers:
        cli = XUIClient(s["url"], s["username"], s["password"],
                        s.get("sub_path") or "", s.get("api_token", "") or "")
        try:
            emails, ok = await asyncio.wait_for(cli.get_onlines_checked(), timeout=20)
            ips = await asyncio.wait_for(cli.get_client_ips_bulk(), timeout=20)
            if ips is None:
                row(s["name"], "online " + (str(len(emails)) if ok else "?"),
                    "<-- clientIpsByGuid UNAVAILABLE (panel too old?)")
            else:
                fresh = sum(1 for m in ips.values() if m)
                row(s["name"], f"online {len(emails) if ok else '?'}",
                    f"clients with addresses: {fresh}")
                if ok and emails and fresh == 0:
                    print("       ⚠️  clients online but no addresses — xray behind a proxy "
                          "without PROXY protocol, or statsUserOnline off")
        except Exception as e:
            row(s["name"], "UNREACHABLE", str(e)[:60])
        finally:
            await cli.close()

    pid = 0
    for a in sys.argv[1:]:
        if a.isdigit():
            pid = int(a)
    if pid:
        head(f"subscription {pid}")
        d = await ip_guard.diagnose(pid)
        row("counted right now", d.get("counted_now"))
        row("its limit", f"{d.get('limit')} ({d.get('limit_source')})")
        row("partial reading", "yes — some panel did not answer" if d.get("partial") else "no")
        st = d.get("state")
        row("stored state", st if st else "none yet (never been over the limit)")
        row("what happens next cycle", d.get("would_do_now"))
        row("reason", d.get("because"))
        if d.get("blocked_by"):
            print(f"\n  >>> {d['blocked_by']}: {d.get('explain')}")
        else:
            print(f"\n  >>> {d.get('explain')}")

    print("\nnothing above contains a key, a password or a subscription token.\n")


if __name__ == "__main__":
    asyncio.run(main())
