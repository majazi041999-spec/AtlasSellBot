# Iran entry for unchanged subscription URLs

Activated October 8, 2026 with the owner's approval. The existing
`atbot.anacotig.com` A record now points to the approved Iran entry
`193.39.9.182`, DNS only, TTL 120. Both HTTPS ports 443 and 2083 remain available.
Subscription tokens, paths, application URL settings and new-purchase URLs are
unchanged. No active VPN node used this hostname as its endpoint or TLS frontend
at cutover. USA New and Germany WS URIs matched the saved baseline.

## Request path

Current primary (October 10): client -> Iran nginx -> localhost:18443 ->
restricted SSH forward through Finland -> Netherlands nginx:19444 -> bot:8000.

Germany nginx:8444 is retained as an automatic fallback for GET/HEAD requests
when the primary returns 502, 503 or 504. Writes are never replayed against the
fallback after an uncertain upstream result. Germany remains suspended at this
deployment, so the backup becomes usable only after that server returns.
The previous German recovery vhost remains separate and unchanged.

The October 8 route depended solely on Germany. On October 10, the owner
confirmed that server had expired and been suspended. The reported subscription
returned 504 after eight seconds at the Iran entry, while the bot returned a
complete response in 75 ms locally. Germany's SSH and web ports also timed out
from the Netherlands. Moving the primary to Finland removed this dependency.

Direct Iran-to-Netherlands HTTPS/SSH and Iran-to-USA SSH probes were unsuccessful;
Finland completed SSH key exchange and carried the authenticated origin request.
The new transport opens no public port and does not change any VPN inbound.

The three nginx examples under `deploy/nginx/subscription-iran-*` describe the
deployed route. Render their IP, hostname, certificate and secret placeholders
before use. Keep rendered files root-owned, mode 0600; never commit credentials.
Use independent 256-bit keys for the entry/relay and relay/origin hops.
HTTPS certificates are verified on both upstream hops.

The German relay accepts only the Iran entry and its secret header. The private
origin requires its separate secret and an allowed peer (Germany or Finland).
Source address alone is insufficient because these hosts also carry customer
VPN traffic. Iran overwrites forwarded client headers; the private origin trusts
only those peers. The original October 8 forged-header tests passed; the primary
path retains the same fixed Host and overwritten X-Forwarded-For/X-Real-IP.

Install `deploy/systemd/atlas-sub-fallback.service.example` on Iran, substituting
`BRIDGE_IP` (Finland) and `ORIGIN_IP`. Despite the historical fallback service name,
this is now the primary transport. Use a dedicated unprivileged local account,
mode-0600 key, and a host key obtained through an existing trusted administrator
connection. StrictHostKeyChecking is mandatory. The service restarts after three
seconds and uses SSH keepalives to detect lost connections.

On Finland, install `deploy/ssh/atlas-sub-fallback.conf.example` for the dedicated
non-login account. Its authorized key must use `restrict,port-forwarding` and
`permitopen="ORIGIN_IP:19444"`. Permit only that forwarding destination: no shell,
TTY, agent, remote/streamlocal forwarding or other network destinations. Root
SSH settings and existing VPN services remain unchanged.

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
the Finland tunnel to the authenticated origin listener, which serves the
existing `/var/www/atlas-acme` webroot. The German fallback retains its old relay
to origin HTTP:80 and strips **all** headers on that final plain-HTTP hop. Other
HTTP requests redirect to the existing HTTPS hostname and port 2083. The origin
also uses independent Certbot renewal; its hook copies renewed files to the
existing nginx certificate paths.

## Validation and known limitation

After the October 10 repair, the exact reported subscription returned HTTP 200
and fully decoded content on both public ports from the operator's connection,
with explicit proxy bypass and TLS verification. Downloads took about 0.6-0.7
seconds. This does not establish coverage of every ISP. Information entries are
not usable VPN nodes.

A temporary loopback-only copy of the nginx server forced the primary to fail
and used the healthy tunnel as a fallback stand-in: GET returned the complete
subscription, HEAD preserved the origin's 405, and POST returned 504 without
replay. The canary and its logs were removed. A temporary public ACME token also
passed through Finland and was removed. Origin access without the secret still
returned 404. Germany's live fallback could not be accepted while it was down.

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

The original October 8 reverse SSH attempt from the Netherlands to Iran failed
and was removed; HAProxy remains disabled. The October 10 forward connection is
initiated from Iran to Finland and was tested successfully. No bot or Xray
restart was required for either deployment.

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
