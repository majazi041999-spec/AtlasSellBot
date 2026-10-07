# Independent entry for existing subscription URLs

Status: prepared, not deployed. Use only an entry server approved for Atlas.

The Netherlands origin is reported blocked on most consumer ISPs. Direct HTTPS
from the candidate Iran server also timed out on both existing ports. Keeping
the same URL therefore requires an entry reachable by subscribers and an
independent path between that entry and the origin.

Read-only preparation confirmed that the candidate has no listeners on 80, 443
or 2083, and the origin can obtain its SSH host key over port 22. The supplied
units passed `systemd-analyze verify` on the origin. This is preparation only;
it is not a successful tunnel or affected-subscriber acceptance test. The
candidate was saved under a separate service name and is absent from the Atlas
server inventory, so its owner must confirm its use before installation.

The proposed path is client HTTPS -> Iran TCP listener -> reverse SSH tunnel ->
the existing Netherlands nginx. The origin initiates the tunnel to Iran, so the
entry does not need direct outbound HTTPS access to the blocked origin IP.
Client TLS terminates at the existing origin. No customer token, subscription
content or TLS private key needs to be decrypted or stored at the entry.

The entry socket listens on both 443 and 2083 and forwards to a loopback tunnel
listener. Port 80 forwards separately for existing redirects and HTTP-01
certificate renewal. Existing hostname, paths, tokens, certificates and purchase
URL generation remain unchanged. No VPN inbound is moved or changed.

Provision a dedicated SSH account and key with only the two required loopback
remote forwards allowed; do not reuse administrator credentials. Pin the SSH
host key obtained through the existing trusted administrator connection. Keep
the private key on the origin with mode 0600. The supplied systemd examples
restart a broken tunnel and run the entry forwarders without root privileges
after systemd has bound the listening ports.

Before enabling sockets, confirm ports 80, 443 and 2083 are unused and inspect
the existing firewall. Validate unit files with `systemd-analyze verify`. Test
certificate-verified real subscription and HTML requests pinned to the entry IP
on both HTTPS ports, HTTP certificate challenge routing, and tunnel reconnection.
Test from the affected access networks; an unrelated successful connection does
not establish accessibility for every ISP. Do not switch production DNS until
the candidate is validated. Retain the previous proxied DNS record for rollback.

The entry and its origin tunnel are additional dependencies. This proposal does
not add automatic failover and does not defeat filtering of the hostname itself.
