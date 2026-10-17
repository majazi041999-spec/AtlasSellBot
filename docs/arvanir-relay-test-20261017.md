# Arvan Iran relay staging test — 2026-10-17

The owner supplied `arvanir` (`94.101.187.57`) for testing as a potential
replacement for the slow Iran entry. This operation prepared and tested the
server; **production DNS and subscription variant settings were not changed**.
The currently published entry remains the one documented in
[the earlier migration](iran-entry-migration-20261017.md).

## Staged services

The fresh host has one vCPU, approximately 2 GiB RAM, and configured global
IPv6 `2a07:3903:0:2::33`. Before preparation only SSH and system services were
listening. The existing dedicated relay templates were used:

- `atlas-turkey-tunnel`: public TCP 2053 → existing Turkey HTTPS/WS route.
- `atlas-finland-tunnel`: public TCP 2054 → loopback 21441.
- `atlas-frost-link@21441`: restricted SSH forwarding over IPv4 to Finland's
  existing loopback receiver on 21440. The pinned host key, original receiver,
  attribution marker and customer accounting remain unchanged.

Both HAProxy processes use one thread and `maxconn 1024`, with a 128 MiB memory
ceiling each. The SSH service has a 64 MiB ceiling and `IPQoS=none`. The package's
general HAProxy service is masked; the dedicated processes are enabled. There
were no default route, system-wide firewall or kernel tuning changes.

A new private forwarding key exists only on `arvanir`. Finland's additional
authorization permits only the owned IPv4/IPv6 source addresses, local
forwarding to `127.0.0.1:21440`, and no shell. Prior keys remain intact.

## Measured transfers

Real VLESS tests reused the existing origin inbounds with disposable identities.
Destination authentication, complete response lengths and upload SHA-256 were
checked. The test endpoint was authenticated, temporary and on an unused port.

| Test source / path | Download Mbit/s | Upload Mbit/s |
| --- | --- | --- |
| Current Iran laptop → Turkey, IPv4 origin path; two 4 MiB/1 MiB pairs | 6.15–22.78 | 1.52–3.51 |
| Current Iran laptop → Finland, IPv4 SSH path; two 4 MiB/1 MiB pairs | 15.91–19.43 | 2.19–3.84 |
| Current Iran laptop → Finland, IPv6 SSH path; two 4 MiB/1 MiB pairs | 14.32–14.92 | 3.43–4.28 |
| Netherlands → Iran entry → Turkey; 8 MiB/2 MiB | 16.89 | 7.16 |
| Netherlands → Iran entry → Finland; 8 MiB/2 MiB | 26.97 | 2.59 |

Two concurrent additional 1 MiB downloads completed on each laptop-tested path.
Origin IP checks returned the owned Turkey/Finland addresses. Original counters
recorded traffic under the two disposable accounts, which were subsequently
deleted. The temporary benchmark was stopped.

IPv6 was a separate server-to-server path; it did not require IPv6 on the
customer device. It was usable, but these samples did not establish a download
advantage over IPv4. Its temporary public port 2055, relay unit and SSH unit were
removed after comparison. The staged main routes retain IPv4.

These are limited measurements at test time, not capacity, all-operator,
long-term stability or zero packet-loss guarantees. They are materially better
than the earlier entry's recorded 0.2–0.8 Mbit/s downloads, but they are not a
simultaneous controlled comparison of every ISP. No customers were moved during
the test, and USA New / Germany WS were not modified.

Private credentials and receipts remain outside Git in the operator directory
`atlas-arvanir-20261017` locally and `/root/atlas-arvanir-20261017` on the relevant
hosts. Do not publish those receipts or copy private keys into this repository.
