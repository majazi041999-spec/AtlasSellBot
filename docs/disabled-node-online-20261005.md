# Disabled nodes remained usable after subscription lifecycle changes

On 2026-10-05, the bot marked Netherland Ultra Speed (config 9) disabled,
but its Netherlands inbound still accepted clients. A direct panel reading
confirmed two online config-9 clients, matching the dashboard's cached sample.
Other disabled configs also appeared in direct panel readings.

Renewal, profile editing and activation previously enabled all surviving
subscription-node rows without checking `node_config_active`. The same policy
gap existed in timer reset and subscription-link rotation. These paths now
respect the configured node and physical server switches. Activation retries
an unconfirmed disable instead of enabling that client.

Node removal now retains an inactive local row until remote deletion succeeds,
and reports failed removals. The admin toggle rejects an already-running node
job and restores the previous state if a reconciliation job cannot start.

The dashboard keeps observed disabled-node clients in its totals and marks
their node as disabled. It displays each server's sample time and describes
the count as online clients, which can include multiple nodes for one customer
and client connectivity probes. Its refresh button now polls the panels,
rather than simply rereading the stored sample. The regular poll interval is
configurable and defaults to 120 seconds; these are sampled observations,
not an exact count of unique people or established TCP sessions.

Validation: disabled-node lifecycle/removal regression tests, dashboard and
toggle-handler tests, subscription tests, renewal tests, auto-node rules,
and a production build of the admin frontend. Deployment uses
`bash update.sh pull-no-stash`.

Operational cleanup targets only panel clients whose `_n<id>` suffix belongs
to an existing disabled node config. Preserve transport settings, identities,
traffic limits, expiry dates, manual clients and enabled-node clients. Back up
the bot database and panel snapshots privately before disabling in bulk;
verify the panel state afterward. Never commit those credential-bearing
snapshots. Third-party clients still need to fetch the updated subscription;
server-side policy cannot force their local subscription cache to refresh.
