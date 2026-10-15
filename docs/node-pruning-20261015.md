# Node pruning and Finland announcement — 2026-10-15

Compared completed three-day windows October 9–11 and October 12–14 in Tehran
time, excluding the partial October 15. The evidence is Atlas Android app
diagnostics, not a complete history of concurrent users across all clients.
Daily reporting devices increased from 49–51 to 53–59 across those windows.

- Netherlands regular WS: successful connection events fell from 26 to 6
  (77%); reporting connected devices fell from 9 to 4. The route was already
  hidden, so no additional parent-node removal was warranted. Netherlands Plus
  and Backup M remained in use and were retained.
- Turkey Backup 1: successful connection events fell from 25 to 15 (40%),
  while connected devices went from 13 to 12. After being shown both figures,
  the owner explicitly requested removal of this backup too.
- Germany WS/Plus, USA New/Plus, Finland and the other Turkey routes retained
  usage. Newly published Nitro and Frost are not evaluated against old windows.

Disabled only variant `backup-0` for parent target `1:3` using the existing
`subscription_ws_disabled_variants` setting. Do not delete the parent Turkey
account/inbound: its UUID/counter is shared by the retained paths. No customer
quota, expiry or saved subscription URL changes. Old inactive node identities
remain in accounting history; they were already excluded from subscriptions.
The sample subscription lost exactly the requested backup, with its other
links preserved. Rollback removes only `backup-0` from this target's disabled
list, preserving all other switches.

The owner authorized a Telegram bot broadcast and an Atlas app notification
for Finland Frost. The message uses ordinary Unicode emoji, asks users to
update the existing subscription, and describes optimization and speed without
disclosing transport details. The bot button opens the existing services list;
its text starts with Persian letters to avoid the keyboard helper's automatic
premium icon conversion. No channel post was requested or sent.

App notification: all app versions, seven-day expiry, delivered through the
existing heartbeat notification mechanism. Queueing is not proof of delivery
to an offline phone. Telegram campaign `finland-frost-20261015` uses the existing
resumable per-user delivery ledger. Private operational receipts hold the
notification ID, aggregate results and settings backup.
