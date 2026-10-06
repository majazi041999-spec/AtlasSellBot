# Private Netherlands Instagram egress trial

Public Instagram HTML returned `PolarisSiteData.country_code=IR` over the
existing origins, despite independent GeoIP services reporting the servers'
actual countries. Tests included both address families and uncached requests.
This is evidence of Meta's country classification, not proof of the
authenticated music-library policy decision.

A private Netherlands panel inbound uses WebSocket/TLS behind an exact Nginx
location. Its inbound tag alone matches an additional SOCKS outbound to the
official WARP client's loopback proxy. Existing inbound settings, clients and
published USA New/Germany WS links were checked and preserved. The bot node
configuration was initially disabled. One separate canary identity has a
3 GiB quota and seven-day expiry. Following explicit publication authorization,
customer identities are provisioned individually with their existing quotas and
expiries; the test identity is never shared with customers. The node carries an
Instagram test label pending the affected customer's music-picker result.

The `tls_frontend` node configuration records the public TLS port and server
name for this loopback WS transport. Subscription rendering replaces its
internal/plaintext endpoint with the TLS frontend, preserving each customer's
UUID and WS path. Invalid frontend metadata omits the link; default metadata
leaves all existing nodes unchanged. Protected USA New/Germany WS targets are
excluded. Both browser copies and client subscriptions use the same renderer.

WARP runs in local proxy mode, not system-wide mode. The main route table and
resolver file matched their pre-installation snapshots. Cloudflare trace
reported `warp=on`, `loc=NL`, and Meta reported `NL` over the complete test
node, including tests from the operator laptop. Bounded 1 MiB download and
256 KiB upload transfers completed; the laptop's upload was slow. This trial
does not establish music availability or production throughput. The affected
iPhone/account must verify the same music picker before any public rollout.

Registration, client identity, trial URI/path, complete configuration snapshots
and rollback receipts remain in private operator artifacts outside Git.
Disable the trial inbound, remove its exact Nginx include and scoped routing
rule/outbound, and stop WARP after testing if it is not adopted. Never restore
a whole panel/database snapshot over customers created since the backup.

Primary references: [WARP Linux setup](https://developers.cloudflare.com/warp-client/get-started/linux/),
[local proxy mode](https://developers.cloudflare.com/warp-client/warp-modes/),
[Xray SOCKS outbound](https://xtls.github.io/en/config/outbounds/socks.html),
[Instagram music availability](https://www.facebook.com/help/instagram/402084904469945).
