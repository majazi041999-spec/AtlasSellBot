# Cloudflare scanning and VPN egress

The reported incident on 2026-10-04 consists of sequential TCP connections
to Cloudflare addresses in `173.245.48.0/20`, all on port 443. The local
WinCFScan log starts scanning that same subnet at 16:04:21 Tehran time;
the provider report starts at 12:34:22 UTC (16:04:22 Tehran). This is strong
evidence that the local scan traversed the VPN. Historical Xray access
logging was disabled, so the authenticated account cannot be independently
attributed from the server log. This observation does not prove or rule out
unrelated compromise.

Scan clean edge candidates only with the VPN and system proxy turned off,
on the operator connection whose reachability is being measured. Sending
a scan through a server measures that server's connectivity and attributes
the scan to its public IP.

On Windows, use `tools/start-cfscanner-safely.ps1 -ScannerPath <path>`.
It refuses to launch with an enabled Windows proxy/PAC or a recognizable
active VPN/TUN adapter. If either appears during a run, it stops only its
own scanner process. `-CheckOnly` verifies the current environment without
launching a scan. Detection errors fail closed. This is a local safeguard,
not a security boundary: launching the executable directly bypasses it,
and it cannot detect upstream/router VPNs or every third-party tunnel.

Do not block HTTPS or all Cloudflare networks to address this incident.
A global connection rate limit also cannot reliably distinguish a slow
scan from ordinary traffic from multiple VPN users. An inbound firewall
does not prevent scan connections made by authenticated VPN clients.
For recurrence by another user, bounded access logging and account-level
investigation are needed before selective account suspension; indiscriminate
shared-server blocking risks breaking normal browsing.

References:
- https://docs.hetzner.com/de/robot/dedicated-server/troubleshooting/guideline-in-case-of-server-locking/
- https://xtls.github.io/en/config/log.html
