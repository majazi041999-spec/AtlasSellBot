# Repeatable QR and campaign media — 2026-10-16

## Behavior

- Every multi-server subscription card in Telegram offers `sub_qr:<profile_id>`.
  The handler checks membership, owner and blocked state, fetches the current
  subscription token, and generates the QR without querying Xray panels.
- Mini-app service cards open a QR sheet. Each open makes an authenticated
  `POST /app/api/services/qr`; ownership is checked server-side. Image and current
  URL return with `Cache-Control: private, no-store`. Old links after rotation
  are not retained in a cross-service QR cache.
- The editor previews persisted campaign media, handles explicit image removal,
  waits while a selected file is being read, and saves the edited text/photo
  before invoking delivery. Creating a new campaign opens the editor correctly.
- Automatic trial/winback followups have their own editable image settings and
  use the same media delivery contract as custom campaigns. Failed delivery no
  longer marks an automatic reminder sent.
- Images are validated as real PNG/JPEG/WebP, constrained for size/dimensions,
  and converted to Telegram-compatible JPEG. Invalid configured media fails
  explicitly instead of degrading into text-only delivery. Long captions are
  sent as image plus text; failures are reported separately from dedup skips.
- Referral templates support `{referral_rewards}` and `{referral_link}`. Reward
  amounts and active milestones are resolved from current settings at preview
  and delivery time; personalized invite links use each recipient's own code.
  Referral rules, rewards, discount codes and historical send markers do not
  change when preparing campaigns.

## Prepared content

`tools/prepare_campaigns_20261016.py` is dry-run by default. `--apply` fills only
missing campaign pictures, preserves the owner's existing photo, updates the
referral campaign to the dynamic template, initializes automatic photos once,
and adds two draft-only campaigns for active retail subscribers:

1. **ابزارهای سرویس همیشه در دسترس** — QR access in bot/mini-app and tutorials.
2. **انتخاب مسیر مناسب اینترنتت** — Frost/Nitro and the server-status tool.

No messages are sent by preparation. Previously sent campaigns retain their
deduplication history. Neither new draft is scheduled automatically.

## Artwork

Nine distinct assets were generated with the built-in image generation tool,
using the existing Atlas logo as visual reference. Final JPEGs, hashes and
mapping live in `assets/campaigns/manifest.json`; prompts in `PROMPTS.md`.
The reference brand is `web/subscription_assets/atlas-logo.webp`. No numeric
reward terms, discounts or changing dates are baked into the new artwork.

## Verification

Initially `test_campaign_media` failed because automated winback never called
`send_photo`; `test_service_qr` failed because the subscription keyboard had no
QR callback. Both pass after the changes.

Coverage includes real PNG generation, current-link rotation, owner/auth/blocked
checks, invalid media rejection, long emoji captions, automatic delivery failure,
and live referral reward changes. A local OpenCV decode also read the generated
styled QR back into the exact test subscription URL.

Playwright CLI workflows in `tools/qa` use intercepted local API responses. They
exercise actual React screens, saved-photo previews, file selection, save-before-
send ordering, new campaign creation and repeated QR opening on a mobile-sized
viewport. The workflows never send to real Telegram recipients.

## Deployment and rollback

Back up live dirty source and the database privately before deployment. Commit
only this task's changes, preserving prior uncommitted edits. Use the normal
`update.sh pull` flow after confirming that the live dirty patch restores cleanly.
Do not use hard reset. Retain old hashed frontend assets during rollout for
already-open pages. After updating, validate both new endpoints and existing
subscription rendering; then run the preparation script with `--apply`.

Rollback should restore only changed source/build and these campaign fields
from the private snapshot. Never restore the entire customer database over
later purchases, renewals or consumption. No transport/node configuration is
part of this release.
