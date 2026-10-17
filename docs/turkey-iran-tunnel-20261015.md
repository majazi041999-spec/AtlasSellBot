# Turkey through the Iran entry

The Iran entry moved to `193.39.9.214` on 2026-10-17; the published hostname and
port stayed the same. See the [migration notes](iran-entry-migration-20261017.md)
for shared-host isolation and the network performance limitation observed then.

The additional `🇹🇷 Turkey Nitro` variant uses the existing Turkey WS customer's UUID,
email, quota and expiry. It does not add a client, subscription node row, or
second entitlement. Existing and future subscriptions get it when rendered;
browser copy/import and raw subscription responses share that renderer.
If legacy imports left several active parent rows for one target, only the
newest valid row supplies this variant. Existing identities and counters
are retained; the variant is not repeated for every historical row.

## Route

Client → `nitro.anacotig.com:2053` in Iran → dedicated HAProxy TCP process →
Turkey HTTPS port 443 → exact nginx WebSocket route → existing Turkey WS
inbound on loopback:2096 → destination. Each connection has its own TCP stream;
there is no shared SSH/multiplexed transport or dependency on cross-border UDP.
`nitro` has its own DNS-only A record pointing to the Iran entry, TTL 120;
neither the bot hostname nor an existing Turkey DNS record is repointed.

HAProxy passes encrypted bytes unchanged. Clients verify
`atlasapp.anacotig.com`; TLS terminates in Turkey. Turkey's local upstream
certificate must be verified against **`atlas.anacotig.com`**, the actual name
on that inbound's certificate. Its WS Host remains `trws.anacotig.com` and its
upstream path remains `/perfix/`. These different names are deliberate.
Do not disable certificate verification to make the names agree.

The source WS port 2096 timed out from Iran. Port 443 completed TLS and the new
exact WS route passed real VLESS transfers. Existing Turkey listeners, clients,
and web locations are retained. Iran's subscription listeners 443/2083 and the
Finland subscription relay are separate from this dedicated port and service.
No default routes or system-wide networking parameters are changed.

Render `deploy/haproxy/turkey-tunnel.cfg.example` with the owned Turkey IP and
install it as `/etc/atlas-turkey-tunnel/haproxy.cfg`. Use the dedicated service
under `deploy/systemd`. The service runs without root privileges, has bounded
connections and file descriptors, and cannot select arbitrary destinations.
Do not replace the host's general HAProxy configuration/service.

Render the nginx location example with the exact WS path and the two origin
names, then include it inside Turkey's existing `atlasapp` HTTPS server. Save
the prior vhost, validate nginx, and reload. The path is routing, not a secret;
the original Xray inbound authenticates every subscriber. Non-upgrade requests
to that exact path return 404. Both inactive connection timeouts are explicit.

## Subscription and panel controls

`subscription_ws_relays` is a JSON map keyed by `server_id:inbound_id`. Each
entry contains `address`, integer `port`, `server_name`, exact `path`, and an
optional customer-facing `label` (production: `🇹🇷 Turkey Nitro`).
Production uses the existing Turkey target `1:3` only. The renderer requires
an existing VLESS WS/TLS parent and validated endpoint fields. It removes CDN
ECH, early data and insecure flags from this additional route, while preserving
identity and encryption. Other variants remain unchanged.

The admin subscriptions page shows **🇹🇷 Turkey Nitro** under Turkey WS, with its own
switch. Its switch is stored as `relay` in
`subscription_ws_disabled_variants`; turning it off hides this route on the
next subscription fetch. The parent server/node switches and pending renewal
reset protections still take precedence. Protected USA New and Germany WS
targets never acquire this variant, even if configured accidentally.

The Iran entry is infrastructure, not another quota-bearing server in the bot.
To disable only this route, use its Nitro switch. Existing cached links remain
usable while the relay and underlying account are enabled; for immediate route
shutdown stop `atlas-turkey-tunnel` as well. Expiring/disabling the underlying
Turkey account blocks both its direct and relay access.

## Validation and limits

- Valid identity and actual Turkey egress verified with an owned, temporary
  authenticated transfer endpoint. Invalid UUID was rejected.
- Three laptop transfers of 8 MiB down and 2 MiB up all passed; downloads were
  21.75–27.56 Mbit/s and uploads 3.91–4.04 Mbit/s. Four simultaneous additional
  downloads completed. Upload byte counts and SHA-256 digests matched.
- Two probes originating on the Iran server measured 59.10–67.57 Mbit/s down
  and 34.92–35.70 Mbit/s up through Turkey to the owned benchmark destination.
  These are observations at test time, not capacity guarantees or ISP coverage.
- Uplink/downlink bytes appeared under the disposable client's original Turkey
  counter. An expired test client was disabled and subsequent traffic rejected.
- A 2 MiB test quota was exceeded by a 4 MiB transfer; the panel subsequently
  disabled that client and rejected new connections. Enforcement follows the
  existing panel's polling cadence, **not** a byte-exact immediate cutoff. The
  relay does not change this existing behavior or count the counter twice.
- Automated checks cover panel toggling, disabled parent/server, pending renewal
  reset, shared identity and metadata, invalid settings and protected nodes.
- An authenticated connection survived 70 seconds idle and then carried another
  successful request on the same connection.

The dedicated nginx upstream now binds `127.0.0.2`, allowing online-user
attribution to Nitro without cloning quota-bearing accounts. See
[connection attribution](finland-iran-frost-20261015.md#dashboard-attribution).
All customer source addresses appear as relay/loopback addresses at the origin.
UUID volume accounting remains intact, but source-IP based user limits and
online-IP displays are less informative on this route. No PROXY headers are
injected into existing listeners. Connection limits are aggregate, not strict
per-IP limits that would reject unrelated mobile customers sharing NAT.

No tunnel can guarantee that this Iran IP will remain internationally reachable
or unfiltered. Foreign inbound HTTPS impairment was already recorded before
this work. This design initiates the cross-border connection from Iran and
does not rely on Turkey opening a reverse connection to Iran. It still depends
on that outgoing path and return traffic. Keep the existing subscription route
separate, retain provider console access, and avoid claims of zero packet loss
or universal operator availability. See the linked [research](iran-turkey-tunnel-research-20261015.md).

## Rollback

Hide `relay` for `1:3` in the existing variant switches, then stop/disable only
`atlas-turkey-tunnel` on Iran. Remove only this operation's nginx include and
snippet on Turkey, validate and reload. Preserve the existing inbound and
customer counters. Restore saved source files/commit only if code rollback is
needed; never restore the full customer database over later purchases/usage.
Private backups and test receipts reside outside Git.
