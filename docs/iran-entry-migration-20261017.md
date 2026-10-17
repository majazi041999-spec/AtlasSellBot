# Iran relay migration — 2026-10-17

The owner authorized moving the existing Turkey Nitro and Finland Frost entries
from `193.39.9.182` to the shared Iran host `193.39.9.214` (`zonevpn-new`). The new
host also runs UseBot/Eitaa, another V2Ray deployment, MenuCraft and PostgreSQL.
Those applications must remain independent of the Atlas relays.

## Published endpoints

Only these DNS-only A records changed, retaining their names and TTL 120:

| Name | Port | New entry | Destination |
| --- | --- | --- | --- |
| `nitro.anacotig.com` | 2053 | `193.39.9.214` | Existing Turkey HTTPS/WS route |
| `frost.anacotig.com` | 2054 | `193.39.9.214` | Restricted SSH forward to the existing Finland receiver |

No subscription URL, UUID, quota, expiry, parent inbound, variant setting, bot
hostname, or other DNS record changed. Existing clients need to reconnect after
their DNS cache expires; the two node addresses remain the same.

The existing Iran subscription/web ingress was **not** moved by this operation.
In particular, ports 2083 and 2096 on the new host belong to its other V2Ray
deployment and must not be replaced with Atlas listeners.

## Isolation on the new host

- `atlas-turkey-tunnel.service` uses only `/etc/atlas-turkey-tunnel/haproxy.cfg`
  and public TCP 2053, forwarding encrypted bytes to Turkey:443. The existing
  Turkey WS route, upstream certificate verification and attribution marker
  `127.0.0.2` remain unchanged.
- `atlas-finland-tunnel.service` uses only
  `/etc/atlas-finland-tunnel/haproxy.cfg` and public TCP 2054. Its current backend
  is loopback 21441.
- `atlas-frost-link@21441.service` forwards only to Finland's existing loopback
  receiver on 21440. A newly generated key is held only on this Iran host. Its
  Finland authorization is restricted to source `193.39.9.214`, forwarding to
  `127.0.0.1:21440`, and no shell. The old entry's key remains authorized.
- Finland's existing receiver and attribution marker `127.0.0.3` are retained.
  Customer accounts and their traffic counters are reused, not cloned.
- Each dedicated HAProxy process uses one thread, `maxconn 512`,
  `LimitNOFILE=4096`, `MemoryMax=96M`, and CPU/IO weight 50. The SSH link has a
  32 MiB memory ceiling and `IPQoS=none`.
- Four independent SSH links were initially installed and verified. On this
  shared one-vCPU host only 21441 is currently enabled; 21442–21444 were stopped
  and disabled, and removed from the HAProxy backend. Reducing the pool did not
  eliminate the observed network slowdown, so do not describe it as a fix.
- The package's general `haproxy.service` is masked. Only the dedicated Atlas
  services run. Existing application units, firewall policy, routing, sysctls,
  default HAProxy configuration and other applications' listeners were not
  changed or restarted. No upgrade of existing packages was requested.

## Validation and observed limitations

Before the DNS change, real VLESS traffic through the new IP exited at the
expected Turkey and Finland origin IPs. Complete 1 MiB downloads and 256 KiB
uploads passed length checks; upload SHA-256 digests also matched. The original
origin-side counters recorded the disposable accounts' upload and download
traffic. Test identities have a 64 MiB cap and temporary expiry and must be
removed after verification.

**The new host's international network was slow and intermittently difficult to
reach during this operation.** Early 12/22-second bounded transfers timed out.
A later complete transfer measured approximately:

| Route | Download | Upload |
| --- | --- | --- |
| Turkey Nitro | 0.76 Mbit/s | 0.13 Mbit/s |
| Finland Frost | 0.30 Mbit/s | 0.50 Mbit/s |

These are measurements from this laptop/network at that time, not capacity or
all-operator guarantees. Origin-to-benchmark controls completed much faster:
about 64–100 Mbit/s down and 17–22 Mbit/s up. An Iran-local relay probe was also
slow, so the laptop access network alone does not explain the observation.
The server showed low CPU load and ample available RAM when management access
returned. This narrows the problem to the path involving the Iran host but does
not identify a specific provider device or establish intentional filtering.

A small, source-restricted UDP echo probe did not demonstrate a dependable
alternative; delayed/out-of-order responses were observed. No UDP tunnel was
published. Its temporary Finland listener and firewall allowance were removed.
There was no configured global IPv6 address on the new host.

Both old relay entries failed the comparison connectivity probe. DNS was moved
after the new routes completed real transfers, to restore functional access;
this is not a claim that the international speed problem has been solved.

On the shared host, pre-existing services retained their original main PIDs,
configuration hashes and V2Ray inbound definitions. UseBot and MenuCraft's local
HTTP checks returned 200 before and after installation. The diagnostic
subscription's existing links, including USA New and Germany WS, were compared
and remained identical.

## Operations and rollback

Private snapshots, test credentials and receipts are outside Git under
`/root/atlas-iran-migrate-20261017` on the managed hosts and the corresponding
private local operator directory. Do not publish those files.

Check the dedicated services without restarting the existing applications:

```sh
systemctl status atlas-turkey-tunnel atlas-finland-tunnel atlas-frost-link@21441
```

To retire only this entry, first move the two DNS records to a **verified working**
entry, then stop/disable the three units above. The old IP was not a working
rollback destination at test time. Remove only the new source-restricted Finland
key when decommissioning; retain the old key and the original Finland receiver.
Never replace a complete customer database, existing application configuration,
or the host's general firewall rules as part of this rollback.

Historical route details: [Turkey](turkey-iran-tunnel-20261015.md) and
[Finland](finland-iran-frost-20261015.md).
