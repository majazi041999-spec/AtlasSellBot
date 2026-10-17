# Turkey Nitro / Finland Frost cutover to arvanir — 2026-10-17

The owner explicitly authorized moving both existing relay variants to
`arvanir` (`94.101.187.57`), preserving their names and links and protecting all
other nodes and existing connections. This supersedes the published entry in
[the earlier migration](iran-entry-migration-20261017.md), following
[staging validation](arvanir-relay-test-20261017.md).

## Current routes

| Published address | Current DNS-only A | Origin path |
| --- | --- | --- |
| `nitro.anacotig.com:2053` | `94.101.187.57`, TTL 120 | Arvan dedicated HAProxy → existing Turkey HTTPS/WS route |
| `frost.anacotig.com:2054` | `94.101.187.57`, TTL 120 | Arvan dedicated HAProxy → restricted IPv4 SSH link → existing Finland receiver |

Only those two existing A records were patched. Their names, TTL, proxy state
and the subscription variant settings were retained. No other DNS record,
subscription URL, node label, UUID, quota, expiry, or parent inbound changed.
The existing bot/subscription web ingress was not migrated by this operation.

Arvan uses the dedicated `atlas-turkey-tunnel` and `atlas-finland-tunnel`
services, plus four independent `atlas-frost-link@21441` through `21444` units.
The Finland backend balances two IPv4 links and two IPv6 links. The IPv6
destination is selected in scoped instance drop-ins for 21443/21444; local
listeners remain IPv4 loopback, so clients do not need IPv6. All host keys are
pinned and each new path passed certificate-verified TLS readiness checks.
The original 21441 link was not restarted while adding capacity.
The origins retain the existing attribution markers (`127.0.0.2` for Nitro,
`127.0.0.3` for Frost) and original quota-bearing accounts. No client is cloned
and no second traffic allowance is created.

## Compatibility for cached DNS and existing sessions

The dedicated TCP 2053/2054 HAProxy services on **both** prior Iran entries,
`193.39.9.182` and `193.39.9.214`, now forward directly to `94.101.187.57` on the
same respective ports. There is no new-entry → old-entry loop or unnecessary
chain between the old hosts. The new entry itself forwards to the foreign
origins, not back to an old Iran host.

Both complete HAProxy candidates were validated before replacement and graceful
reload. Established sessions can continue on the old workers until they close;
the origins and old forwarding links were not restarted or disabled. Do not
stop an old origin SSH link while old HAProxy workers might still use it.

The unrelated services on the shared host retained their original PIDs and
configuration hashes: UseBot/Eitaa, its outbound tunnel, MenuCraft, x-ui, Xray
and PostgreSQL. The old entry's general nginx/Xray services were also preserved.
General HAProxy, public subscription/web listeners, firewall policy, and system
routes were not modified. Only the two dedicated relay services were reloaded.

**Stale DNS is still a limitation.** Cloudflare/Google returned the new IP with
TTL 120, while this laptop's modem still returned `193.39.9.182` with hours left
in its cache. The compatibility route established authenticated connections,
but transfers through that old entry remained slow and hit the short test
deadline. It is a continuity path, not a claim that the old IP's network quality
is fixed. Clients need a refreshed DNS answer to get the new entry's direct
performance; changing authoritative TTL does not evict an existing cache.
Keep the old entries available while relying on these compatibility routes.

## Verification

- Before cutover, real direct-to-Arvan tests passed complete 4 MiB downloads and
  1 MiB uploads for each route, including upload SHA-256 validation. Main
  downloads measured 16.09 Mbit/s (Turkey) and 16.51 Mbit/s (Finland) from the
  current Iran laptop. Correct foreign origin addresses were observed.
- The diagnostic subscription's 12 exported links were compared before/after
  and remained identical, as did the serialized relay settings. No bot restart
  was required for this DNS/infrastructure change.
- USA New and Germany WS each passed two real HTTP 204 connectivity checks
  through their unchanged links from the laptop.
- One early post-cutover Finland 8 MiB download exceeded the 18-second deadline.
  A direct origin control completed at 143 Mbit/s, while the original shared
  SSH connection showed retransmissions and substantial packet reordering. The
  pool was expanded without stopping that connection. This is evidence for a
  transport-path limitation, not proof of a single causal mechanism.
- After expanding the pool, two complete 8 MiB download / 2 MiB upload pairs
  per route passed through the actual published domain names from Netherlands,
  whose normal resolver returned the new Arvan address. Download samples were
  24.13–30.23 Mbit/s for Turkey and 6.52–22.88 Mbit/s for Finland; uploads were
  6.18–6.38 and 1.97–5.10 Mbit/s respectively. Upload SHA-256 digests matched.
  These foreign-source tests are not Iranian operator speed guarantees.
- Cached-modem deadline failures are retained separately; do not present them
  as successful high-speed tests. A temporary alternate-DNS client probe also
  failed and was not used to claim a working local DNS fix. No system DNS
  setting was changed on the laptop.
- Original origin-side counters recorded both upload and download traffic.
  Disposable test identities were deleted and the temporary authenticated
  benchmark was stopped after verification.

These are bounded observations, not all-operator, capacity, uninterrupted-session
or zero-packet-loss guarantees. Graceful reload avoids deliberately terminating
existing connections but cannot prevent unrelated network failures.

## Recovery

Private snapshots and receipts live outside Git under
`atlas-arvanir-cutover-20261017` locally and
`/root/atlas-arvanir-cutover-20261017` on the relevant hosts.
Each old host has `bridge-originals.json` and an idempotent
`bridge-applied.json` receipt. DNS before/after snapshots are private locally.

If rollback is needed, first verify the intended previous route. Restoring DNS
alone is insufficient because old entries now forward to Arvan. Restore only
the saved dedicated relay configurations, validate and gracefully reload them,
then restore only the two saved DNS records as appropriate. Never restore a full
customer database or overwrite another application's configuration.
