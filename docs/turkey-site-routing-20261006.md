# Turkey: scoped workaround for outgoing SNI interference

On 2026-10-06, HTTPS requests from the Turkey host to `www.pornhub.com`
failed during TLS with a connection reset. The same destination IP returned
HTTP 200 from Germany and Netherlands. A normal Internet control from Turkey
returned HTTP 204. Turkey's local OUTPUT chain accepted traffic and its Xray
routing did not explicitly block the affected site.

On Turkey, the normal SNI handshake failed repeatedly, while a handshake without
SNI followed by the same HTTP Host header returned 200 twice. The test verified
the certificate chain and the expected certificate hostname. These observations
strongly indicate outgoing SNI-based interference; they do not identify the
specific upstream device injecting the reset.

## Installed configuration

Only Turkey received this change. Its persisted 3x-ui `xrayTemplateConfig` now
contains the `atlas-tr-site-fragment` Freedom outbound:

```json
{"fragment":{"packets":"tlshello","length":"5","interval":"0"}}
```

A rule appended after the existing blocking rules matches TCP destination ports
80 and 443 for `pornhub.com`, `pornhub.org`, `phncdn.com`, and `phprcdn.com`,
including their subdomains. Other traffic keeps the original direct outbound.
The active local inbounds use HTTP/TLS sniffing with `routeOnly: true` so that
domain rules also work when the client supplies a resolved destination IP. This
does not replace that destination or change subscription addresses, credentials,
TLS certificates, ports, or transport settings. Enabling sniffing also lets
existing domain-block rules recognize domains in IP-addressed requests.

Fragmentation changes the initial TLS records only. With interval zero, the core
adds no deliberate delay between records. The egress remains Turkey; no second
VPN server or new public proxy was introduced. This is an outgoing workaround on
Turkey, separate from fragmentation on the user's Iranian access network.

## Validation

- A separate loopback-only trial core reproduced failure with the original
  direct outbound. Larger record sizes were ineffective or intermittent.
- The selected setting passed four initial requests and six staged requests,
  with both domain-addressed and IP-addressed SOCKS requests.
- Three JavaScript resources returned 200. The unrelated HTTP 204 control used
  the direct outbound, confirmed by its routing tag.
- Xray validated the complete production candidate before changes were applied.
- After deployment, all three published Turkey variants each passed three
  homepage requests, a JavaScript download, and the HTTP 204 control through
  their actual subscription links. These probes ran from Netherlands and verify
  the complete VPN/server path, not every customer's Iranian access network.
- USA New and Germany WS independently passed the HTTP 204 control; their
  servers and subscription definitions were not changed.
- Persisted client records, inbound assignments, quotas, expiry, credentials,
  ports, and transport settings were compared and remained unchanged.

An initial strict comparison of the generated config's client arrays triggered
rollback. 3x-ui updates clients through its live API without always rewriting
`config.json`; a restart regenerates those arrays from the database. The final
guard compares persisted client/assignment records and every other runtime
field, rather than treating a stale generated array as authoritative.

These checks establish homepage and static-resource access. Video playback was
not separately measured, and future upstream filtering can require retesting.

## Apply or roll back

`tools/turkey-site-routing.py` uses the existing operator SSH alias `atlas`.
Without arguments it checks the proposed or installed configuration. Installation
is idempotent and takes a private SQLite backup before stopping 3x-ui briefly:

```powershell
python tools/turkey-site-routing.py
python tools/turkey-site-routing.py --apply
```

The successful deployment backup is
`/root/atlas-backups/turkey-site-routing-20261006-155322` on Turkey. It contains
private configuration and credentials and must never be committed or published.
Rollback restores only the template and sniffing fields, preserving current
customer records and traffic counters. It refuses to overwrite settings changed
since this deployment:

```powershell
python tools/turkey-site-routing.py --rollback /root/atlas-backups/turkey-site-routing-20261006-155322
```

References: [Project X Freedom](https://xtls.github.io/en/config/outbounds/freedom.html),
[Project X routing](https://xtls.github.io/en/config/routing.html), and
[OONI measurement interpretation](https://ooni.org/support/interpreting-ooni-data/).
