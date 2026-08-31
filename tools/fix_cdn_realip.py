"""Make a CDN-fronted inbound report the CUSTOMER's address, not Cloudflare's.

Xray 26.7.28 has `sockopt.trustedXForwardedFor`: a list of HEADER NAMES. When a
request carries one of them, xray takes the first entry of `X-Forwarded-For` as
the peer address instead of the TCP source. Cloudflare always sets
`CF-Connecting-IP` on what it proxies, so that header is the marker.

Run with --apply to write. Without it, it only reports.
Run with --revert to remove the setting again.

Every inbound's original streamSettings is written to /root/xff-backup-*.json
before anything changes, so a revert never depends on this script being right.

WARNING, and it is why this touches one inbound at a time: 3x-ui applies an
inbound update by removing and re-adding it on the running xray, so every live
connection ON THAT INBOUND drops and has to reconnect. Clients do that by
themselves within seconds, but it is a real interruption and it is not worth
causing twice.
"""
import asyncio
import json
import sys
import time

sys.path.insert(0, "/opt/AtlasSellBot")

from core.database import get_servers          # noqa: E402
from core.xui_api import XUIClient             # noqa: E402
from core.ip_guard import is_cdn_ip            # noqa: E402

MARKER = "CF-Connecting-IP"
APPLY = "--apply" in sys.argv
REVERT = "--revert" in sys.argv
ONLY = None
for a in sys.argv[1:]:
    if a.startswith("--server="):
        ONLY = a.split("=", 1)[1]


def _obj(v, default=None):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return default if default is not None else {}
    return v if v is not None else (default if default is not None else {})


async def main():
    backup = {}
    for s in await get_servers(active_only=True):
        name = s["name"].strip()
        if ONLY and ONLY not in name:
            continue
        cli = XUIClient(s["url"], s["username"], s["password"],
                        s.get("sub_path") or "", s.get("api_token", "") or "")
        try:
            ibs = await asyncio.wait_for(cli.get_inbounds(), timeout=30)
            ips = await asyncio.wait_for(cli.get_client_ips_bulk(), timeout=30)

            # Which inbound does each observed email belong to?
            email2ib, by_id = {}, {}
            for ib in ibs or []:
                by_id[ib["id"]] = ib
                for c in (_obj(ib.get("settings")).get("clients") or []):
                    email2ib[c.get("email")] = ib["id"]

            share = {}
            for email, m in (ips or {}).items():
                ibid = email2ib.get(email)
                if ibid is None:
                    continue
                a = share.setdefault(ibid, [0, 0])
                for ip in m:
                    a[0] += 1
                    if is_cdn_ip(ip):
                        a[1] += 1

            for ibid, (tot, cdn) in sorted(share.items()):
                pct = round(cdn / max(1, tot) * 100)
                ib = by_id[ibid]
                ss = _obj(ib.get("streamSettings"))
                sock = ss.get("sockopt") or {}
                have = MARKER in (sock.get("trustedXForwardedFor") or [])

                if REVERT:
                    if not have:
                        continue
                    target = True
                elif pct <= 80:
                    continue          # not CDN-fronted: leave it completely alone
                else:
                    target = not have

                net = ss.get("network")
                print(f"{name} / inbound {ibid} (port {ib.get('port')}, {net}) "
                      f"cdn={pct}% trusted={have}")
                if REVERT:
                    sock["trustedXForwardedFor"] = [
                        h for h in (sock.get("trustedXForwardedFor") or []) if h != MARKER]
                    if not sock["trustedXForwardedFor"]:
                        sock.pop("trustedXForwardedFor", None)
                elif have:
                    print("   already set, nothing to do")
                    continue
                else:
                    sock["trustedXForwardedFor"] = sorted(
                        set((sock.get("trustedXForwardedFor") or []) + [MARKER]))

                if sock:
                    ss["sockopt"] = sock
                elif "sockopt" in ss:
                    ss.pop("sockopt")

                backup.setdefault(name, {})[ibid] = ib.get("streamSettings")
                if not APPLY:
                    print(f"   WOULD set sockopt.trustedXForwardedFor = "
                          f"{sock.get('trustedXForwardedFor')}   (dry run)")
                    continue

                payload = dict(ib)
                payload["streamSettings"] = json.dumps(ss, ensure_ascii=False)
                for k in ("settings", "sniffing", "allocate"):
                    if isinstance(payload.get(k), (dict, list)):
                        payload[k] = json.dumps(payload[k], ensure_ascii=False)
                ok = await asyncio.wait_for(cli.update_inbound(ibid, payload), timeout=60)
                print(f"   {'APPLIED' if ok else 'FAILED: ' + (cli.last_error or '?')}")
        except Exception as e:
            print(f"{name}: ERROR {str(e)[:120]}")
        finally:
            await cli.close()

    if backup and APPLY:
        path = f"/root/xff-backup-{int(time.time())}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(backup, f, ensure_ascii=False, indent=2)
        print(f"\noriginal streamSettings saved to {path}")


asyncio.run(main())
