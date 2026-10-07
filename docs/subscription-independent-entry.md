# Iran entry for unchanged subscription URLs

Activated October 8, 2026 with the owner's approval. The existing
`atbot.anacotig.com` A record now points to the approved Iran entry
`193.39.9.182`, DNS only, TTL 120. Both HTTPS ports 443 and 2083 remain available.
Subscription tokens, paths, application URL settings and new-purchase URLs are
unchanged. No active VPN node used this hostname as its endpoint or TLS frontend
at cutover. USA New and Germany WS URIs matched the saved baseline.

## Request path

Client -> Iran nginx -> Germany nginx:8444 -> Netherlands nginx:19444 -> bot:8000.

Iran cannot reliably reach the Netherlands origin directly. The HTTPS path
through Germany returned complete subscription content and browser HTML. This
adds Germany as a dependency; there is no automatic failover. The previous
German recovery vhost on port 8444 remains separate and unchanged.

The three nginx examples under `deploy/nginx/subscription-iran-*` describe the
deployed route. Render their IP, hostname, certificate and secret placeholders
before use. Keep rendered files root-owned, mode 0600; never commit credentials.
Use independent 256-bit keys for the entry/relay and relay/origin hops.
HTTPS certificates are verified on both upstream hops.

The relay accepts only the Iran entry and its secret header. The private origin
requires both the German peer address and its separate secret. Source address
alone is insufficient because Germany also carries VPN customers' traffic.
Iran overwrites forwarded client headers; the private origin trusts only the
relay. Forged X-Forwarded-For, X-Real-IP, CF-Connecting-IP and private client-IP
headers were tested and did not replace the actual client address.

For the private origin only, copy `/etc/nginx/snippets/atlas-tgweb.conf` to
`atlas-sub-entry-tgweb.conf`. In **every** proxy location, add empty
`X-Atlas-Origin-Key` and `X-Atlas-Entry-Key` proxy headers. Existing locations
define their own proxy headers, so server-level inheritance is insufficient.
This prevents leaking credentials to Telegram's external hosts. The original
public nginx vhost and snippet remain unchanged.

No subscription response is cached at the entry. Access logging is disabled to
avoid recording customer tokens. The 32 MiB body limit, HTTP/WebSocket upgrades,
and fixed forwarded host/protocol support existing browser/admin routes.

## Certificates

Iran uses its own Certbot certificate in
`/etc/letsencrypt/live/atbot.anacotig.com/`, with webroot
`/var/www/atlas-sub-acme`. It was successfully issued after cutover, expires
January 5, 2027, and replaced the temporary copied certificate/key. The copied
origin key was removed. Enable `certbot.timer` and install the nginx
validation/reload hook from `deploy/certbot`.

Port 80 serves local HTTP-01 challenges first. Missing challenges pass through
the authenticated HTTPS relay to the origin's existing HTTP webroot
`/var/www/atlas-acme`. The relay strips **all** request headers on that final
plain-HTTP hop. Other HTTP requests redirect to the existing HTTPS hostname and
port 2083. The origin also uses independent Certbot renewal; its deploy hook
copies renewed files to the existing nginx certificate paths.

## Validation and known limitation

From the operator's Iranian connection with explicit proxy bypass, both ports
returned HTTP 200, a decoded subscription, and complete browser HTML. Observed
subscription times were approximately 0.5-0.7 seconds. Certificate verification
was enabled. This does not establish coverage of every Iranian ISP. Information
entries in a subscription are not usable VPN nodes.

From three foreign servers, the entry completed TLS but subsequent responses
timed out. The existing unrelated HTTPS console showed the same behavior. Small
HTTP requests succeeded. Offload, MTU, TCP timestamp/window scaling, TLS version
and alternate SNI probes did not fix the foreign path; temporary settings were
restored. The upstream cause is unconfirmed and must not be presented as a
proven provider firewall fault.

The owner explicitly accepted this limitation and authorized cutover with the
instruction to **disable VPN before updating subscriptions**. Foreign visitors
and users updating through a VPN may fail to reach this hostname. DNS affects
the entire hostname, including browser/admin access. Existing VPN nodes are not
moved. This route does not prevent future IP/domain filtering.

The reverse SSH attempt failed during key exchange and was abandoned. Its
service, restricted account/key, temporary listeners and diagnostic endpoints
were removed; HAProxy is disabled. No bot or Xray restart was required.

## Rollback and deployment

Restore the same A record to Netherlands `185.117.0.47`, enable Cloudflare
proxying and set TTL Auto. Do not point DNS-only at that origin: the owner
reports it blocked on most access networks. Preserve both serving paths while
caches expire. Old proxied DNS/AAAA answers may persist for five minutes or
longer, despite the new record's 120-second TTL.
The operator's router DNS continued advertising the old Cloudflare A/AAAA
answers with roughly eight hours remaining; public 1.1.1.1 and 8.8.8.8 returned
the new A record. Do not promise universal propagation within two minutes.

Before later cutovers, fetch a real private subscription and HTML view on both
ports with certificate verification; check active node dependencies and
protected-link hashes. Keep tokens and receipts outside Git. Validate nginx on
all three hosts before reload. Recheck unauthorized relay rejection and
certificate renewal routing when editing these configs.

Deploy repository changes with a fast-forward merge after checking unrelated
local modifications. The bot repository has separate ongoing changes; do not
stash/reset them or run a broad update script. These infrastructure changes do
not require restarting the bot or VPN inbounds.
