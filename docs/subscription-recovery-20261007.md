# Subscription delivery with unchanged customer URLs

Proxied DNS answers are Cloudflare edge addresses. A successful test on one
network, or one address family, does not prove another subscriber's path works.
On the attached MCI LTE phone, explicit Cloudflare IPv4 candidates timed out,
while the trial through Cloudflare IPv6 and one ECH resolver carried HTTPS and
complete authenticated download/upload requests. The original DNS address also
worked during these tests; the reported intermittent failure was not reproduced
consistently. ECH-dependent variants additionally require compatible clients.

## Current primary entry: same hostname, Iran HTTPS entry

On October 8, after explicit owner approval, the same `atbot` A record moved to
the Iran entry with DNS-only routing and TTL 120. Customer URLs and protected VPN
nodes are unchanged. The owner accepted the foreign-ingress limitation and will
instruct customers to disable VPN before updating. See the deployed
[entry design, validation and rollback](subscription-independent-entry.md).
The original Cloudflare route remains the rollback option, not the current path.

## Earlier October 8 rollback: Cloudflare restored

On October 8, the owner reported that the Netherlands origin IP is blocked on
most operators. The October 7 DNS-only change was therefore rolled back: the
same `atbot` A record is proxied again with TTL Auto. Direct DNS to the origin
is not an acceptable fix for this deployment. A successful local/foreign probe
was insufficient evidence for that cutover.

After rollback, public DNS returned Cloudflare addresses. Real subscription
downloads on ports 443 and 2083 returned HTTP 200, valid configuration content,
Cloudflare response headers and cache status DYNAMIC. The two protected VPN
URIs remained unchanged. These checks confirm restoration, not resolution of
the original intermittent reachability problem.

The owner also confirmed the subscription updated with VPN enabled but failed
without it. This led to the independent Iran entry above. Do not disable the
proxy to the blocked Netherlands origin again or change customers' URLs.

## Historical October 7 direct-DNS attempt (reverted)

On October 7, the owner explicitly required retaining existing subscription URLs
and the URLs issued for new purchases. `public_base_url` remains
`https://atbot.anacotig.com`; tokens and `/sub/<token>` paths are unchanged.
Existing URLs with port 2083 and URLs using the default HTTPS port both work.

The existing `atbot` A record still points to the Netherlands origin. Its proxy
status was changed to **DNS only**, with TTL 120 seconds, after testing direct
HTTPS with the original hostname, SNI and certificate validation. This changes
the network path for the whole `atbot` hostname, including its browser/admin
pages, rather than just `/sub/`. Other DNS records and working VPN nodes were
not changed. Before the change, no active node configuration or published node
link used `atbot` as its endpoint or TLS frontend.

This removes Cloudflare edge IP selection, challenges and caching from requests
that resolve the new DNS answer. It does not protect against blocking of the
origin IP or hostname, and it exposes the origin address without Cloudflare's
HTTP protection. No origin rotation or automatic failover was added. A single
healthy ISP test cannot establish that every affected ISP can reach the origin.

Previously cached proxied answers can remain for five minutes or longer in
client/resolver caches. Both Google and Cloudflare public DNS returned the origin
A record and no AAAA record after the change; the operator laptop initially
continued returning the older edge addresses. Do not describe propagation as
instantaneous. Reopening the client or refreshing its DNS may be needed.

Validation covered certificate-verified subscription downloads and browser HTML
on ports 443 and 2083 before switching DNS. Downloads were base64-decoded and
checked for configuration entries; synthetic information entries must not be
counted as usable nodes. The application URL setting and published USA New and
Germany WS URIs were compared before and after and remained identical. No
affected subscriber's failing path was available for an end-to-end retest.

For rollback, restore proxying on the same A record and return its TTL to Auto;
retain the hostname, origin, HTTPS listeners and application URL settings. DNS
rollback is also subject to caching. The private operator record contains the
original record ID and exact pre-change state; it is not committed to Git.

## Existing independent recovery entry

The separate recovery entry uses the existing German hostname and its valid
public certificate on HTTPS port 8444. It remains available for previously
issued recovery URLs; it does not replace the primary purchase URL. The original
Germany WS and USA New listeners, identities, transport settings and subscription
URIs remain unchanged. Recovery depends on both Germany and Netherlands being
available and does not hide the entry server's address.

Only `/sub/<token>` and the subscription logo are exposed by this additional
listener. Admin and panel paths return 404. Access logging is disabled to avoid
storing subscription tokens. Upstream TLS is verified against the system trust
store with sufficient certificate chain depth. Certificate renewals must reload
the additional nginx listener as well.

Set `subscription_backup_base_url` to the independent HTTPS origin, with no path,
credentials, query or fragment. Existing subscription URLs and tokens remain
valid. Service cards offer a separate copy button. Opening the recovery page
keeps its recovery URL in application import buttons instead of sending the
user back to the primary entry. Only the explicitly configured recovery host
can select that URL; arbitrary forwarded hosts cannot redirect imports.

## Canceled Instagram experiment

The owner canceled the experiment because music still did not load. Config 28,
the 274 associated subscription rows, the 275 isolated panel clients (including
the operator canary) and Netherlands inbound 6 on loopback port 16443 were
removed. The trial's routing rule, SOCKS outbound and nginx WebSocket locations
were removed on both entry servers. The unused experimental AAAA record was
deleted, and the dedicated WARP proxy service was stopped and disabled. Private
database/configuration backups were retained. Other Netherlands inbound
transport settings were compared before and after and remained unchanged.

Do not restore the retired trial's WebSocket location or WARP route when
reinstalling the subscription recovery listener. The example nginx configuration
intentionally contains only subscription delivery routes.

References: [Cloudflare proxy DNS](https://developers.cloudflare.com/dns/proxy-status/),
[Cloudflare ECH](https://developers.cloudflare.com/ssl/edge-certificates/ech/).
