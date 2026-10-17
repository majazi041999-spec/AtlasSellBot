# Finland Frost and node connection attribution — 2026-10-15

The Iran entry moved to `193.39.9.214` on 2026-10-17. On that shared host the
current forwarding pool has one enabled link, while the original deployment
below used four. See the [migration notes](iran-entry-migration-20261017.md) for
the current configuration and measured network limitations.

## Published route

`Finland Frost` uses `frost.anacotig.com:2054`, a DNS-only A record to the owned
Iran entry. Client TLS (SNI/WS Host `mobofn.anacotig.com`, WS `/prefix/`) stays
encrypted through Iran and terminates at Finland's existing VLESS WS inbound
`5:3`. The bot hostname is not a node address. Subscription URLs are unchanged.

Iran HAProxy selects among four independent local OpenSSH forwards on ports
21441–21444. Each has its own supervised process and encrypted connection to
Finland:22, forwarding only to Finland's loopback receiver on port 21440.
That receiver passes TCP to the existing loopback:443 with a dedicated source
address for accurate online attribution. No default routes, NAT,
IP forwarding, or existing subscription recovery services are modified.
The isolated `atlas-frost` account uses a new key restricted to the Iran source,
local forwarding and one destination. Shell sessions, remote forwarding, agent
forwarding and password login are disabled. The host key is pinned from the
existing trusted management connection. No private keys are stored in Git.

The existing Finland UUID/email and counter are reused. No customer is cloned,
no separate traffic allowance is allocated, and renewal/expiry remain managed
by the existing panel. The relay has its own toggle under the parent node.

## Why this path

- Direct Finland:443 initially timed out because a separate nftables table
  `inet atlas-fiws` allowed only Cloudflare and existing management servers.
  A bounded packet capture showed incoming SYNs without replies. Adding the
  Iran source to that specific allowlist made TCP/TLS/WS handshakes pass.
  This temporary allowance was reverted after selecting the restricted SSH path.
- Actual authenticated traffic still failed across that direct Iran route,
  despite successful tests on Finland itself and from Netherlands. Changing
  client TLS fingerprints did not establish a usable path. Handshake success
  alone was therefore not treated as a working VPN.
- A temporary source-restricted UDP echo test returned only 3 of 12 packets.
  The temporary listener and firewall rule were removed. This does not prove
  all UDP protocols fail, but gave no basis to prefer a UDP tunnel here.
- The restricted SSH pool passed real authenticated traffic. Four transports
  reduce the number of sessions sharing one outer TCP connection; they do not
  eliminate TCP head-of-line blocking or guarantee zero loss. Existing TCP
  transport was selected on measured results, not claimed universal superiority.

OpenSSH documents [key restrictions](https://man.openbsd.org/sshd#AUTHORIZED_KEYS_FILE_FORMAT)
and [forwarding controls](https://man.openbsd.org/sshd_config#AllowTcpForwarding).
WireGuard's [limitations](https://www.wireguard.com/known-limitations/) explain
why a UDP-dependent option still needs an actual usable network path. Earlier
[transport research](iran-turkey-tunnel-research-20261015.md) covers alternatives.

## Validation and limits

Through the real Frost entry, a disposable 256 MiB identity exited at Finland's
owned IP. Three 8 MiB downloads measured 19.20–33.34 Mbit/s and three 2 MiB
uploads 3.35–3.73 Mbit/s from the current laptop connection. Upload byte counts
and SHA256 matched; four simultaneous 1 MiB downloads succeeded. These are
observations for that path/time, not all-operator speed guarantees.

Traffic appeared in the original Finland client counter. Invalid credentials
were rejected. After the panel's next enforcement scan, an expired identity
was disabled and new traffic rejected. A 2 MiB quota allowed the test's 4 MiB
transfer before the next scan disabled it. This is the existing polling-based
enforcement behavior, not an immediate byte-accurate cutoff. An expiry update
also allowed one immediate request before the scan: never promise instant cutoff.

No transport guarantees the Iran server will remain internationally reachable.
This design needs an outgoing Iran→Finland SSH connection and its return path.
It does not depend on Finland establishing a new incoming connection to Iran.

## Dashboard attribution

The existing per-server online sample still supplies parent-node counts by
client email suffix. Duplicate emails are counted once. Active nodes with zero
online clients are visible; stale/unreachable panels remain unknown.

For the two relays, one extra bulk IP-observation request per relevant server
identifies their distinct ingress: Turkey's nginx binds `127.0.0.2`, and Frost's
loopback receiver binds `127.0.0.3`. Finland's bulk observation API omitted
the initial exact `127.0.0.1` source even during a sustained test, so it was
replaced with the distinct receiver source before publication. These markers must stay
exclusive to the corresponding inbound/relay. Configure them in each relay's
`source_ips`. A new forwarding path must be checked before reusing a marker.

Only sightings from the last 90 seconds intersected with the current online
email sample are attributed. Aggregate route counts are stored atomically in
the same `online_nodes` JSON as parent counts; emails/IPs are not persisted.
Missing sightings display unknown or a known lower bound, never a false zero.
Users observed on both routes appear under both children but only once in the
parent total. Variants with identical credentials and ingress remain explicitly
grouped; this API cannot infer which hostname/fingerprint the client selected.

Tests cover shared-route overlap, missing/old observations, deduplication,
same-sample storage, unknown panels, inactive observed nodes, zero nodes, and
the dashboard API. The existing subscription/protected-node suite also passes.

## Rollback

Hide relay `5:3`, stop/disable `atlas-finland-tunnel` and only the four
`atlas-frost-link@2144[1-4]` units. Preserve Finland's original inbound and
customer counters. Remove only this account's SSH block/key if decommissioning.
Private receipts/backups are in `/root/atlas-finland-tunnel-20261015` on the
managed servers and the corresponding ignored local operator directory.
Never restore a full database over subsequent orders or traffic.
