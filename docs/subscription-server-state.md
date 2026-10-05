# Server switches and subscription variants

Disabling a physical server hides all of its cached clients and generated
transport variants on the next subscription fetch. Cached client identities and
banked traffic counters remain intact. Usage reconciliation and provisioning
skip disabled servers. Orders recheck server status before a panel connection,
provision up to four nodes concurrently and bound each attempt to 15 seconds.

Re-enabling a server immediately exposes its retained active cached clients.
A background job restores missing clients for active subscriptions, targeting
only enabled node configurations on that server. It also restores current
subscription quota and expiry after renewals performed while the server was
offline. Expired or disabled subscriptions are not provisioned.

The admin subscription page lists transport variants under their owning node.
Each shares the parent's customer UUID and quota; switching a variant changes
subscription rendering without creating or deleting remote clients. Parent node
and server switches still take precedence. Existing WS tuning settings remain
supported; `subscription_ws_disabled_variants` stores independently hidden
variant IDs by `server_id:inbound_id`. USA/Germany transport tuning is protected
from these variant switches.

Regression checks:

```sh
python -m unittest discover -s tests -p 'test_subscription_*.py'
python tests/test_autonode.py
npm --prefix web/admin run build
```

Production maintenance on 2026-10-05 also added HTTPS port 443 to the existing
subscription Nginx virtual host, preserving port 2083 and its certificate.
`public_base_url` now uses the same HTTPS hostname without an explicit port.
Existing tokens and paths are unchanged. Private Android probes on raw Irancell
verified both endpoints returned valid subscriptions in approximately 0.8 seconds.
The original intermittent failure reported by other users was not reproduced;
this single-network observation does not establish availability for all users.

The NL preset retains Plus, external Backup 1 and Backup M. Other NL variants
remain visible but disabled in the panel, so they can be restored individually.
No customer rows or credentials are removed by this preset.
