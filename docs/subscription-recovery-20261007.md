# Independent subscription recovery and Instagram trial entry

Proxied DNS answers are Cloudflare edge addresses. A successful test on one
network, or one address family, does not prove another subscriber's path works.
On the attached MCI LTE phone, explicit Cloudflare IPv4 candidates timed out,
while the trial through Cloudflare IPv6 and one ECH resolver carried HTTPS and
complete authenticated download/upload requests. The original DNS address also
worked during these tests; the reported intermittent failure was not reproduced
consistently. ECH-dependent variants additionally require compatible clients.

The independent entry uses the existing German hostname and its valid public
certificate on a separate HTTPS port, 8444. The original Germany WS and USA New
listeners, identities, transport settings and subscription URIs remain unchanged.
An exact WebSocket location forwards only the Netherlands Instagram trial path
to the Netherlands origin over verified TLS. The trial's Netherlands inbound
still uses its dedicated WARP proxy; other Netherlands inbounds do not use it.
This route depends on both Germany and Netherlands being available. It is not a
Cloudflare CDN route and does not hide the entry server's address.

Only `/sub/<token>`, the subscription logo, and the exact trial WebSocket path are
exposed by the additional listener. Admin and panel paths return 404. Access
logging is disabled to avoid storing subscription tokens. Upstream TLS is
verified against the system trust store with sufficient certificate chain depth.
Certificate renewals must reload the additional nginx listener as well.

Set `subscription_backup_base_url` to the independent HTTPS origin, with no path,
credentials, query or fragment. Existing subscription URLs and tokens remain
valid. Service cards offer a separate copy button. Opening the recovery page
keeps its recovery URL in application import buttons instead of sending the
user back to the primary entry. Only the explicitly configured recovery host
can select that URL; arbitrary forwarded hosts cannot redirect imports.

Validation uses the production Atlas Android parser/config/core on the attached
MCI phone, with a Google HTTPS probe and authenticated bounded transfer tests.
Subscription tests use direct, certificate-verified HTTPS and parse the received
node list. The temporary transfer listener and its firewall rule are removed
after verification. Connection measurements do not establish that the affected
Instagram account's licensed music catalog is available; that still needs the
user's account test.

References: [Cloudflare proxy DNS](https://developers.cloudflare.com/dns/proxy-status/),
[Cloudflare ECH](https://developers.cloudflare.com/ssl/edge-certificates/ech/).
