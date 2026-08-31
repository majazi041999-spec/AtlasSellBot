# AtlasSellBot — Project Map (AI quick-context)

> Read this FIRST when working on this repo. It's a dense index so you can jump
> straight to the right file/function without grepping. Persian-facing product
> (RTL). Keep this file updated when architecture changes.

## 1. What it is
Telegram bot + web admin panel + Telegram mini-app for **selling VPN
subscriptions** (V2Ray/x-ui). Sells time+traffic "subscription" links that fan a
user out across many x-ui servers ("nodes"). Has wallet, discounts, referrals,
campaigns, and a **representative (reseller / "نماینده")** system with white-label
branding, plus a keyed **reseller API** so a rep can drive the platform from
their own bot (§8c). Single-process app (bot + FastAPI) backed by **SQLite** (aiosqlite).

Stack: Python 3.13, aiogram 3.x (bot), FastAPI + uvicorn (web), aiosqlite,
React 18 + Vite (admin panel & mini-app, committed `dist/`), httpx (x-ui calls),
Pillow (via `qrcode[pil]`).

## 2. Run / build / deploy
- Entry: `python main.py` (runs bot + web concurrently). Port from `WEB_PORT` env (default 8000).
- **Local dev:** `pip install aiogram uvicorn fastapi jinja2 python-jose[cryptography] passlib[bcrypt] python-multipart aiofiles "qrcode[pil]"` makes `web/app.py` importable and lets you actually boot the API for testing (`uvicorn` on any port with `WEB_SECRET_PATH`/`WEB_ADMIN_*`/`BOT_TOKEN` set, run from a scratch dir so it creates its own `atlas.db`). Without those, `python -m py_compile` + `python -m pyflakes` are the fallback; `core/*` is import-testable either way.
- **Tests:** `tests/` holds plain runnable scripts (no pytest — the server has none). `python tests/test_autonode.py`. `tests/test_rep_api.py` boots the real FastAPI app against a throwaway DB (needs the local-dev deps above). Add regression guards here rather than claiming coverage in this file.
- React builds (committed dist so server needs no Node):
  - `npm --prefix web/admin run build` → `web/admin/dist/`
  - `npm --prefix web/miniapp run build` → `web/miniapp/dist/`
  - Dev servers in `.claude/launch.json`: admin(5173), miniapp(5174), backend(8000).
- Server ops via `atlas_menu.sh` (`atlas` CLI): status/start/stop/restart/update/logs, and `panel-link` (shows panel URL with secret + IPv4).
- Update flow: `/update/check|apply|log` endpoints + `update.sh` (git pull + restart). React "Update" page drives it.
- **Git push needs the user's GitHub login** (creds were erased once; user logs in themselves). Commit freely; end messages with the Co-Authored-By trailer. Don't push unless asked / user handles auth.

## 3. Repo map
```
main.py                     entry: starts bot + web, background workers, logging
core/
  config.py                 env/config: WEB_SECRET_PATH, WEB_PORT, BOT_TOKEN, ADMIN_IDS, card, JWT…
  database.py     (2663)    ALL DB access (aiosqlite). Schema (SCHEMA str) + _ensure_columns migrations + every query.
  multi_subscription.py (1993) THE subscription/node engine (see §6). Highest-risk file.
  xui_api.py       (860)    XUIClient: talks to 3x-ui panels (add/update/del client, get_inbound, update_inbound, get_onlines/get_online_count, get_client_link).
  autonode.py      (520)    "نود خودکار": online-count poller + load balancer that keeps each sub on the least-busy server (see §6b).
  rep_report.py    (215)    date-filtered representative purchase report + its Excel export (see §8b).
  rep_api.py       (419)    reseller API credentials: key issue/verify/revoke, rate limit, idempotency, per-rep lock (§8c).
  legacy_configs.py (264)   bulk-disable the legacy single-server configs, safely (§6c).
  login_guard.py    (330)   admin-login defence: challenge, PoW, honeypot, rate limit, lockout (§4b).
  captcha.py        (150)   font-free image captcha, escalation only (§4b).
  xlsx.py          (215)    dependency-free .xlsx writer (stdlib zipfile). RTL sheet, styled header, merged titles.
  pricing.py        (64)    per-user package price (rep/custom). One source of truth.
  rewards.py       (300)    referral tiers/claims reward logic.
  campaigns.py     (106)    trial→paid + winback campaigns.
  renewal.py       (104)    subscription/config renewal helpers.
  backup.py        (151)    DB backup to admins.
  images.py         (37)    process_logo_bytes(): resize upload → data-URI PNG (logo system).
  miniapp.py        (73)    validate_init_data() for Telegram WebApp auth.
  panel_content.py (140)    default settings text/templates (SETTINGS_DEFAULTS, brand, sub templates).
  sorting.py        (45)    Persian collation: fa_sort_key/fa_collation (SQLite byte order misorders پ چ ژ ک گ ی).
  qr.py, jalali.py, texts.py, update_notes.py
bot/
  handlers/user.py  (2764)  all end-user + representative bot flows (buy, test, services, wallet, rep panel).
  handlers/admin.py (2688)  admin bot commands (approve orders, wholesale approve, broadcast…).
  handlers/common.py (152)  /start, channel-join prompt.
  keyboards.py      (597)   all inline/reply keyboards (packages_kb, representative_panel_kb, join_kb…). NOTE: packages_kb is DEFINED TWICE (l.208 shadowed, l.581 effective).
  middlewares/channel_required.py  forced-channel-join gate + "بررسی عضویت" button flow.
  states.py, nav.py
web/
  app.py           (5548)   FastAPI: admin JSON API + SPA serving + subscription serving (/sub) + mini-app API (/app/api) + proxy + logo + update. Secret-prefixed routes: /{S}/... where S=WEB_SECRET_PATH.
  rep_api.py       (959)    the `/api/rep/v1/*` routes a representative's own bot calls (§8c).
  rep_api_docs.py  (857)    the Persian RTL reference page served at `/api/rep/docs` (PHP/Python/Node tabs).
  admin/src/       React admin panel (see §9). pages/*.jsx, components/{Shell,ui}.jsx, api.js, router.js.
  miniapp/src/App.jsx  Telegram mini-app (single file).
docs/REP_API.md    forwardable copy of the reseller API reference — keep in step with web/rep_api_docs.py.
setup_mtproxy.sh   MTProto proxy installer (mtg v1.0.11). atlas_menu.sh, install.sh, update.sh, setup_*.sh.
```

## 4. Web serving model (important)
- Secret path prefix: every panel route is `/{S}/...` where `S = WEB_SECRET_PATH` (default `AtlasPanel2024`).
- **React is the ONLY panel**, served at root `/{S}/`; every page is a hash route inside it. Assets at `/{S}/assets` (bundle uses relative base). The server-rendered Jinja panel was deleted (Aug 2026) — `web/templates/` and every `response_class=HTMLResponse` route are gone, along with Jinja2Templates itself.
- **A catch-all at the BOTTOM of web/app.py serves the SPA for any unmatched `/{S}/…` path**, so bookmarks of the old pages (`/{S}/dashboard`, `/{S}/users`, `/{S}/login`…) still land in the panel instead of 404ing. It must stay last — FastAPI matches in definition order — and it deliberately 404s `/{S}/api/…` as JSON so a caller bug is not disguised as HTML.
- **What survived the deletion are the POST action endpoints** (`/{S}/servers/add`, `/packages/add`, `/settings`, `/subs/profiles/{id}/edit`, …). React posts to them via `api.form`. They used to answer with a 302 back to the page that submitted them; they now all return JSON, because a redirect would land on the catch-all and make every save download the whole panel HTML. **Any new action endpoint returns JSON too.**
- If `web/admin/dist` is missing the panel serves a 503 telling you to run the build — there is no second panel to fall back to.
- SPA served by `admin_root_index` / `_serve_admin_spa()` which injects `window.__PANEL_BASE__="/{S}"` and the favicon (admin logo).
- Mini-app served at `/app` (+ `/app/api/*`), assets `/app/assets`.
- **Reseller API at a plain `/api/rep/v1` prefix** (never under `/{S}`) + public docs at `/api/rep/docs`. See §8c.
- Subscription links served at `/sub/{token}` → base64 config list for VPN clients; browser page = `_render_sub_status_html` (branded per owner, rep-safe).
- Auth: JWT cookie, hardened — see §4b before touching the login. `_api_guard(request)` for `/{S}/api/*`; `_auth(request)` for the few endpoints a browser navigates to directly (file downloads, banner preview), which bounce to `/{S}/` via `_redir_login()` so the SPA shows its own login form. Login/logout are `/{S}/api/login` + `/api/logout`. Bot admin = ADMIN_IDS / owner_admin_id / users.is_admin.

## 4b. Admin login hardening (`core/login_guard.py`, `core/captcha.py`)
`POST /{S}/api/login` had no rate limit, no lockout, no failure logging, and compared both credentials with `==`. The replacement is invisible on the happy path and escalates only under attack. Covered by `tests/test_login_guard.py` (30 sections — the security invariants are all things a screenshot cannot show).
- **There is no reCAPTCHA-v3 equivalent to build.** That score is Google's cross-site view of a browser plus a model trained on labelled bot traffic; this panel has a handful of logins a day and no such corpus. What IS buildable — and fits the real threat, which is scripted stuffing that never runs JS — is: single-use challenge → proof-of-work → honeypot → min-fill → **rate limit + progressive lockout**, with an image captcha only as escalation.
- **The rate limiter is the security boundary; everything above it is a filter.** Measured: the browser does ~84k hashes/s, CPython ~1.7M — a 16-bit PoW costs the owner ~0.8s in the background and an attacker 0.04s. PoW's real job is requiring JS to have run. Do not present it as the wall.
- **`client_ip()` is now a security boundary too** (core/client_app.py). It honours `CF-Connecting-IP`/`X-Forwarded-For` ONLY from `_TRUSTED_PROXIES` (loopback, RFC1918, Cloudflare's published ranges). It previously trusted them unconditionally — and since the origin is reachable directly on its public IP:PORT, an attacker could send a fresh forged IP per request so the lockout never fired, or send the OWNER's IP to lock them out on demand. The rep API's per-key IP allowlist had the same hole.
- **Escalation is re-evaluated when a challenge is USED, not when it is issued**, and challenges are bound to the issuing IP. Otherwise an attacker farms challenges while clean and spends them captcha-free. `record_failure` also holds the counter at `CAPTCHA_AFTER` after a lock instead of zeroing it — zeroing handed out three free captcha-less tries every time a lock expired.
- **The failure window slides with each failure.** Anchored to the first, an attacker could pace at `LOCK_AFTER-1` per window forever: never locked, never alerted.
- **Neither table is ever `.clear()`ed on overflow.** Wiping `_CHALLENGES` let a flood delete the challenge the owner was holding, whose login then failed as `challenge_missing` — which is therefore also NOT counted as a failure. Wiping `_FAILURES` would launder a live lockout; eviction is oldest-first and skips anything still locked.
- **The challenge endpoint has its own budget** (`ISSUE_LIMIT`, `RENDER_CEILING`) and the PNG renders in a worker thread — it is unauthenticated and Pillow is synchronous on the same loop as the bot. When the render budget is spent the captcha is still DEMANDED (`busy: true`); degrading to "not required" would be a switch to turn escalation off.
- **The captcha draws glyphs from polylines, not a font** (`core/captcha.py`): `core/qr.py` already has to fall back to a 10px bitmap face, which would be unreadable. Alphabet excludes every look-alike. **Be honest about its strength** — the generator ships in this repo, so an attacker can mint unlimited labelled training data; an adversarial pass measured 93.8% word accuracy from a 40-line 1-NN matcher. It is a speed bump. Distortion is tuned for the human who reads it daily, and that trade is correct.
- **Sessions**: cookie is `httponly`, `samesite=lax`, scoped to `/{S}/`, and `secure` only when the request scheme is HTTPS (the panel is genuinely served over plain HTTP by IP too). Tokens carry `_CRED_VERSION`, so changing the admin password invalidates every existing session. `_ensure_signing_secret()` generates and stores a real key rather than signing with the repo's default — it does NOT refuse to boot, because that would take a live bot down on update.
- Settings: `login_captcha_always` (owner can demand the image on every login), `login_alert_enabled` (Telegram alert on failed attempts, throttled per IP by `login_guard.should_alert`, and a lockout always sends). Both on the Settings page.
- Client: `web/admin/src/pow.js` is a hand-written SHA-256 — `crypto.subtle` is `undefined` outside a secure context (the plain-HTTP path) AND benchmarked slower here. One path, no branch.

## 5. Data model (key tables & custom columns)
`core/database.py` — `SCHEMA` creates tables; `_ensure_columns()` ALTER-adds columns idempotently (add new cols THERE).
- **users**: telegram_id, balance_toman, is_admin, admin_role, is_blocked, referral_code, referred_by. Pricing: `discount_percent`, `price_per_gb`, `unlimited_price`. Rep: `is_wholesale` (=representative), `wholesale_request_pending`, `hide_brand`, `rep_brand_name`, `rep_topup_required` (only NEW applicants gated by min-topup), `rep_logo` (data-URI).
- **packages**: traffic_gb, duration_days, price, inbound_id, `is_unlimited` (flag: price from unlimited_price not per-GB; traffic_gb then = fair-use threshold).
- **orders**: status, user_id, package_id, custom_price/custom_* , discount_*, bulk_*. Effective price = `COALESCE(NULLIF(custom_price,0), packages.price)`.
- **servers**: url, username, password, api_token, sub_path, inbound_id(s), max_active_configs.
- **subscription_node_configs**: admin-defined nodes (server_id+inbound_id) every sub is provisioned on. `label`, `priority`, `max_active_profiles`(0=∞), `is_active`, `connect_host` (per-node custom domain override).
- **subscription_profiles**: one per sold subscription. token, email, user_id, order_id, traffic_gb, used_bytes, expire_timestamp, is_active, name (customer display name), starts_on_first_use, first_use_at.
- **subscription_nodes**: per-(profile×node) x-ui client. profile_id, server_id, inbound_id, uuid, email `{profile_email}_n{config_id}`, link (cached), is_active, `remote_disabled_at` (epoch ms the PANEL confirmed the client off — `is_active` can't serve as that flag because it drops to 0 even when the remote write fails, so rendering stops immediately; see §6).
- **configs**: legacy single-server configs (mostly superseded by subscriptions).
- **test_accounts** (UNIQUE user_id → one lifetime trial) vs **rep_test_accounts** (per-day rep allowance, no unique).
- discount_codes, discount_redemptions, referral_tiers, wallet_transactions, topup_requests, campaign_events, daily_reports.
- **rep_api_keys / rep_api_idempotency**: reseller API credentials + replayed money responses. Schema lives in `core/rep_api.py` (its own `ensure_schema`, called by `init_db`), not in `SCHEMA` — same pattern as app_analytics. See §8c.
- **custom_campaigns**: panel-authored targeted blasts (Campaigns tab). `slug` is the join key to
  campaign_events (sends, once-per-user guard) AND discount_codes.campaign (attribution + targeted-code
  lock). Segments in `CUSTOM_SEGMENTS` + `get_segment_users(segment, limit, include_reps=False)` (database.py) —
  **representatives are excluded from EVERY segment by default** (a consumer blast must never reach a reseller);
  the dedicated `reps` segment still targets them, and per-campaign `custom_campaigns.include_reps` re-adds them
  (toggle in the Campaigns editor, default off). Sender =
  `run_custom_campaign` (core/campaigns.py, photo data-URI + 1024-char caption split); endpoints
  `/{S}/api/campaigns/custom[...]`. Seeded ONCE from `_SEED_CAMPAIGNS` via `seed_default_campaigns()`
  (main.py after init_db; gate setting `custom_campaigns_seeded`) — 8 designed drafts incl. image
  prompts + strategy notes; also creates codes COMEBACK30/FLASH20/RENEW15/VIP20/SCHOOL25 (FLASH20 &
  SCHOOL25 created inactive) and repairs OldFriend15 campaign 'renewal'→'winback'.

### Sorting & filtering (added for the users/services lists)
One vocabulary of keys is shared across panel, bot and mini-app — keep the lists in sync when adding one.
- **Users (server-side, SQL):** `list_users(q, filt, sort, period, offset, limit) -> (rows, total)` in database.py.
  Key sets: `USER_SORTS` / `USER_FILTERS` / `USER_PERIODS`, defaults via `DEFAULT_USER_SORT`. Unknown keys fall
  back silently, so a stale query string can't 500. Rows carry inline aggregates (`approved_orders`,
  `active_services`, `total_spent`, `last_order_at`, …) — this **replaced the get_user_business_stats() N+1**
  in `/api/users` (was ~4 queries × 40 rows per page). `/{S}/api/users?q&page&sort&filter&period`; React
  `Users.jsx` drives it with a Toolbar + filter chips + clickable `SortTh` headers (all three stay in sync).
- **Subscriptions (in-memory):** `_sort_filter_profiles()` + `SUB_SORTS`/`SUB_FILTERS` in web/app.py, behind
  `/{S}/api/subs/profiles?sort&filter`. Sorting is Python-side because usage % / days-left aren't columns.
- **Bot services list (users AND reps):** `SERVICE_SORTS`/`SERVICE_FILTERS` + `sort_filter_services()` +
  `normalize_service_view()` in keyboards.py. State rides in callback_data as **`svc:{page}:{sort}:{filter}`**
  (short codes because of Telegram's 64-byte cap); `svc_srt:`/`svc_flt:` open the picker menus, `svc_noop` is
  the page-counter label. Legacy `svc_pg:{page}` still parses (old keyboards live on in users' chats).
- **Persian name order is not the default:** SQLite's BINARY/NOCASE sort by UTF-8 bytes, which dumps پ چ ژ ک گ ی
  at the end. `core/sorting.py` fixes it. In SQL, `USER_SORTS` name entries carry a `{coll}` placeholder that
  `list_users` formats after `_register_fa_collation()` registers `FA` on the connection — aiogram/aiosqlite has
  no public `create_collation`, so it goes through `db._execute(db._conn.create_collation, …)` and **falls back to
  NOCASE if that private path ever breaks**. In JS use `localeCompare(x, "fa")`.

## 6. Subscription / node engine (`core/multi_subscription.py`) — most complex, highest risk
Concept: a sold sub = 1 `subscription_profile` + a client on EVERY active `subscription_node_config` (a `subscription_node` row per node). Link `/sub/{token}` returns all node links + info lines.
- `render_subscription(token)` → base64 body served to VPN clients. Serves cached links fast; kicks background sync. Applies per-node `connect_host` override at render time (HTTP-free, instant).
- **The render-triggered sync is rate-limited and must stay that way** (`_background_render_sync`, `sub_render_sync_min_seconds`, default 900s). One pass opens a FRESH session per node — `XUIClient` logs in per instance — so it costs a login + query per node, per poll, per customer. Clients re-fetch the sub on a timer (some on every connect), and unthrottled that is enough to saturate the panels; a saturated panel then fails the link check, which sends us down the repair path that re-adds the client and makes xray reload, dropping every live connection on that server. `force=True` bypasses the limit and is only for one-shot transitions (arming first-use, disabling an exhausted sub). Quota/expiry enforcement does NOT depend on this — the worker does it.
- `create_profile_for_order` / `create_profile_from_config`: provision on ALL usable nodes (no min/max cap anymore; min 1 works).
- `ensure_subscription_profile_nodes(profile, force_refresh, only_config_ids)`: reconcile a profile's nodes (create missing / refresh / move / orphan-cleanup). `only_config_ids` targets one node (used by real-time per-node ops). Orphan prune skipped when targeting.
- `reconcile_node_config_streamed(log, node_id, remove, force_refresh)` + `_remove_node_config_from_profile`: real-time apply of a single node action across all profiles, streamed to the "nodeops" job log. Node add/enable/disable/edit in the panel triggers this instantly.
- `set_nodes_enabled(profile_id, enabled)`: enable/disable ALL of a profile's nodes on the panels (re-creates deleted clients on re-enable).
- `rotate_subscription_link(profile_id)`: **"تغییر لینک اشتراک"** — revoke the current link and hand back a fresh one when a customer shared theirs. A shared `/sub` link makes clients cache the underlying vless configs, so token-only rotation would NOT cut off whoever imported it. So it rotates BOTH the profile token (old `/sub/{token}` 404s) AND every node's client identity (new uuid + email; delete+add because `update_client` refuses uuid changes). Same profile row → quota/expiry/name/first-use carry over; consumed traffic is banked into `carried_bytes` exactly like an auto-node move. Only rotates an ACTIVE profile (else it'd be a free renewal). Failed nodes drop their row and self-heal via the missing-node path. Bot: `subscription_detail_kb` button `sub_relink:` → `subscription_relink_confirm_kb` → `sub_relink_do:` (60s per-profile cooldown, `bot/handlers/user.py`).
- **Disabling is idempotent and must stay that way.** Every sweep re-visits inactive profiles, and this used to re-issue `update_client` for all their nodes each time — measured at 144 writes per sweep on the live fleet. A client write makes 3x-ui rewrite the inbound and reload xray, which drops every live connection on that server, so re-sending a disable the panel already applied punishes every OTHER customer there. Nodes carrying `remote_disabled_at` are skipped; unconfirmed ones keep being retried and log why. **Any new code path that writes to a panel needs the same "has this already been applied?" test.**
- Link labels: server remarks are SHORT (node name only). The user's chosen service name appears ONCE as the first info/null entry (fixed the "names too long" complaint) — see `_subscription_node_display_label` + `_subscription_info_links`.
- **Brand safety (hard rule):** our platform brand is NEVER shown on a representative's subscription — only their `rep_brand_name` (or nothing). See `_owner_brand()` → (hide, rep_brand, is_rep) and `_subscription_info_links`. Logo equivalent: `_resolve_sub_logo`/`_resolve_sub_brand` in web/app.py.
- Sync: `sync_subscription_nodes_streamed` (concurrent, time-boxed, progress log). Slowness is HTTP round-trips to x-ui, NOT SQLite — Postgres would NOT help sync speed.
- **The frequent usage pass rotates.** `sync_active_profiles(limit, usage_only=True)` (worker, every 180s) is capped far below the number of subs sold, and `get_active_subscription_profiles` is ordered — so it takes an `offset` and resumes via `_usage_pass_offset` instead of re-reading the same lowest-id customers forever while everyone past the cap waited for the hourly sweep. Any new capped pass over profiles needs the same treatment.
- **`PanelSessions` — use it for ANY sweep that touches many nodes.** Two things, both per server per sweep: one logged-in `XUIClient` (it authenticates per instance, and 3x-ui's slowest operation is the bcrypt login), and ONE bulk traffic snapshot (`XUIClient.get_all_client_traffics()` — the inbound list already carries `clientStats` with email/up/down for every client). Measured on the live fleet: a 120-node sample went from 24.5s and 240 requests to 1.6s and 5 requests; the full sweep goes from ~6.5 min and 1898 requests to ~25s and 5. Verified to return identical counters (bracketed between two snapshots taken either side of the per-client reads). Panels that don't return the list fall back to the per-client query automatically. **Do not go back to a client-per-node loop** — that is what drove panels into 15-second timeouts, which failed the link check, which sent the repair path into re-adding clients, which reloaded xray and dropped every live connection on that server.
- Gotcha: node email suffix `_n{config_id}` is the join key between subscription_nodes and node configs. `subscription_nodes.config_id` now stores it explicitly (backfilled from the suffix in `_ensure_columns`) because an auto node's server/inbound differ per profile, so a (server_id, inbound_id) join would attach the wrong config.

## 6b. Auto node — "نود خودکار" (`core/autonode.py`)
One extra entry in every subscription that always points at whichever server has the fewest users online **right now**. It is a normal `subscription_node_configs` row with `is_auto=1`, parked at `server_id=0` and a NEGATIVE `inbound_id` (a sentinel that satisfies the UNIQUE(server_id, inbound_id) constraint and allows several auto nodes). `get_subscription_node_configs` LEFT JOINs servers so those rows survive.
- **Resolution:** `expand_node_configs(nodes, existing_by_config, allow_move)` swaps each auto node for `_merge_target(auto, candidate)` — the auto node's own id/label/pool + the chosen candidate's server & inbound. Called by `create_profile_for_order`, `create_profile_from_config` and `ensure_subscription_profile_nodes`. Because the id is preserved, the `_n{id}` email suffix is stable and the EXISTING move path in `ensure_subscription_profile_nodes` performs the migration — no new provisioning code.
- **`allow_move=False` on every routine reconcile.** Only a deliberate rebalance relocates a customer; a background sync must never do it.
- **Load metric:** count of clients online on the panel (3x-ui derives it from xray's stats tick, so it is real concurrency, not assigned configs). Persisted per server: `online_count` (raw last sample), `online_avg` (EWMA α=0.4, what routing actually uses — the raw list is very noisy), `online_ok`, `online_checked_at`.
- **Safety rules** (covered by `tests/test_autonode.py` — plain `python tests/test_autonode.py`): unknown ≠ empty (an unreachable panel scores +1000, never 0); **unknown ≠ move** — a move needs BOTH the current and destination load visible, because a silent panel means an old 3x-ui, not a dead server (treating it as a reason to move drained whole servers of customers: their cached configs kept pointing at a panel that had deleted them, reported as "configs stop pinging, only one server connects"); hysteresis (`autonode_margin` 25% AND `autonode_min_delta` 3 users AND `autonode_cooldown_minutes` 60, via `subscription_nodes.moved_at`); projected load (`LoadView.reserve()` counts each decision immediately so a batch fans out instead of stampeding).
- **Defaults are deliberately timid:** `autonode_enabled` is **0** (balancing relocates paying customers — opt in), `autonode_max_moves` is 5. Each move writes a client to the destination panel and deletes one from the source, and 3x-ui reloads xray on both — which briefly drops EVERY live connection on those servers, not just the moved customer. A large batch is a fleet-wide outage. A DB row from the panel's settings form overrides these defaults.
- Workers: **`_online_poll_worker`** (main.py) refreshes every server's online count every `online_poll_seconds` (default 120) and is deliberately NOT gated on `autonode_enabled` — it used to live inside `_auto_node_worker`, so an owner who left balancing off got a dashboard whose online numbers silently froze. `_auto_node_worker` now only rebalances, reading the counts that worker stored. Panel: `/{S}/subs/autonode/{refresh,rebalance,settings}`, rebalance streams to the "nodeops" job log.
- `XUIClient.get_online_count()` returns `Optional[int]` — **None means unknown**; never coerce it to 0. It tries `/panel/api/clients/onlines` (3x-ui v3.1+), `/panel/api/inbounds/onlines` (v2), `/panel/inbound/onlines` (legacy web route), remembers which worked, and normalizes both `[email]` and `[{email}]` shapes. v3 CSRF-protects `/login` itself, so `_login` retries once with a token from `/csrf-token`.

## 6c. Retiring the legacy single-server configs (`core/legacy_configs.py`)
Everything sold before the subscription engine is a row in `configs` with one client on one panel. Nothing ever switched one off when it expired — the config alert worker only *warned* — so on the live fleet 267 of 268 rows flagged active had expired 30-90 days earlier, still enabled on the panels and still inflating "active services" on the dashboard. Two things fix that: a panel action that disables them in bulk, and `sweep_expired()` (called from `_subscription_lifecycle_worker`) so the tail cannot grow back. Covered by `tests/test_legacy_disable.py`.
- **Never loop `update_client` over many clients.** Each client write makes 3x-ui rewrite that inbound and reload xray, dropping every live connection on the server — the same rule as §6, and here it would hit hundreds of SUBSCRIPTION customers who have nothing to do with these configs. The sweep uses 3x-ui's `POST /panel/api/clients/bulkDisable` (v3.7+, `XUIClient.bulk_set_clients_enabled`), which groups the emails by inbound and does ONE read-modify-write per inbound. Per-client is the fallback for older panels and the job log says so out loud.
- **A non-404 error must NOT fall back to per-client.** Bad credentials or a dead panel would just be repeated once per client. Only a missing endpoint justifies the slow path.
- **Legacy configs share inbounds with subscription nodes.** On the live fleet two inbounds hold a few legacy clients beside ~265 subscription clients. `bulkDisable` selects purely by email, so `_is_protected()` subtracts every `subscription_nodes.email` AND refuses anything matching `_n\d+$` — a legacy row can carry a subscription-shaped email whose node row was since deleted (one does), and disabling it would cut off a live customer.
- **Rows are only marked `is_active=0` for clients the panel confirmed.** A failure stays active so the next run retries it, rather than vanishing from the list while still passing traffic. A panel reporting "client not found" counts as done — there is nothing left to switch off.
- Configs whose server row was deleted (82 on the live fleet) are unreachable by definition: corrected locally, reported separately, never presented as "disabled on the panel".
- **Disabling is close to one-way** — MHSanaei/3x-ui#4705: a manually-disabled client could not be re-enabled and had to be recreated. The UI wording must not promise a clean undo.
- Endpoints: `GET /{S}/api/configs/disable/preview?scope=expired|all` (no panel calls), `POST /{S}/api/configs/disable`, `GET …/log`. It refuses to start while the "sync" or "nodeops" jobs are running — both rewrite the same inbounds.

## 6d. Concurrent-connection limit per subscription (`core/ip_guard.py`)
Caps how many distinct places connect to ONE subscription at the same time (default 5), warns the customer in the bot, then cuts them for 1 min → 10 min → 1 hour if it continues. Ships **off**, and warn-only when first switched on. Covered by `tests/test_ip_guard.py` (20 sections, including an end-to-end cycle against a fake panel that asserts the request count).
- **Detection is free, and that is the whole reason this design was chosen.** 3x-ui v3.7 runs `CheckClientIpJob` every 10s on a default install. Since v3.7 it no longer tails xray's access log — that path was deleted — it asks the core's online-stats gRPC API for the live connection table and writes it to `node_client_ip`. The recording step runs BEFORE the enforcement gate, so it happens with no `limitIp` set and no fail2ban installed. `POST /panel/api/clients/clientIpsByGuid` returns that whole table in ONE request (`XUIClient.get_client_ips_bulk`). **Measured at fleet scale (244 subs, 3117 nodes, 5 servers): 10 reads, 0 writes, ~40 ms per cycle — 0.066% of a 60s interval.**
- **Cost scales with SERVERS, not subscriptions or nodes.** Per-email polling would be 3117 requests a minute. `tests/test_ip_guard.py` §13 asserts the request count does not move when customers are added — keep it that way.
- **Two-stage detection, and the second stage is the false-positive defence.** The bulk endpoint re-stamps every address with the scan time (`attrTs = now` in `check_client_ip_job.go`, deliberate — attribution has a 30-minute eviction rule), so it CANNOT tell a busy address from a half-open one. `POST /panel/api/clients/ips/{email}` (`XUIClient.get_client_ips`) keeps xray's real `lastSeen`, because on a panel with no limitIp `updateInboundClientIps` takes its collection-only branch and stores the raw observation. Stage two runs only on the cycle that would act, and only for the suspect's own nodes — a handful of requests.
- **Why that matters: churn produces stale timestamps, sharing produces fresh ones.** Xray refreshes `lastSeen` only on a new dispatch, and does not reap a half-open connection until `connIdle` (300s). So after a Wi-Fi→4G handover one phone really is on two addresses for up to five minutes — with the abandoned one frozen. MCI and Irancell run 5.5–6.3 subscribers per public IPv4 and announce their pools as /20s, so **/24 grouping is not the protection it looks like** and IPv4 defaults to /32. IPv6 defaults to /64, which IS correct (privacy addresses rotate inside one /64).
- **Cutting is surgical on v3.7, and this is the one place PROJECT_MAP §6's rule does not apply.** `bulkDisable`/`bulkEnable` push through xray's gRPC `RemoveUser`/`AddUser` (`client_bulk.go::bulkSetEnableInboundClients`), setting `needRestart` only when that API call FAILS. No inbound rewrite, no reload, no effect on other customers. §6 remains correct for `update_client` and older panels — nothing here ever loops per client.
- **A cut stops NEW handshakes, it does not kill established flows.** Xray's `RemoveUser` deletes two `sync.Map` entries and returns; nothing walks live sockets. Browsing breaks within seconds (every new destination is a new dispatch) but a mux client can hold one tunnel longer. The UI says so, and `ip_limit_reassert_after` (300s) stops draining connections being mistaken for a failed cut.
- **`ensure_subscription_profile_nodes` returns early for a subscription under penalty.** Every repair path there pushes `enable=True`, so without that gate the usage sweep would undo a ten-minute penalty ninety seconds in, and the two would trade panel writes for the rest of the hour.
- **All state writes are batched into one transaction per cycle** (`save_ip_guard_states_bulk`, `add_ip_guard_events_bulk`). The per-row helper opens its own connection and commits: **measured 666 ms for 244 rows against 2.6 ms batched, 256x**. SQLite has one writer, so the unbatched version steals that time from the bot too. Added `idx_subnodes_profile_active` — `subscription_nodes` had no index at all.
- **Every failure mode resolves toward NOT cutting.** No panel answered → skip the cycle entirely (never read as "nobody is connected", which would restore penalties early and reset ladders). Stage two could not confirm → leave the state untouched and retry. A server reporting online clients but no addresses is logged as un-policeable (xray behind nginx without PROXY protocol drops 127.0.0.1 from its online map, or `statsUserOnline` is off) rather than silently never enforcing. Switching the feature off releases everyone immediately.
- Tables: `ip_guard_state` (one row per subscription, sparse) and `ip_guard_events` (the evidence log the owner reads before arming it). Per-subscription override lives in `subscription_profiles.ip_limit` (0 = use the default).
- Endpoints: `GET/POST /{S}/api/ipguard`, `POST /{S}/api/ipguard/release/{profile_id}`, `POST /{S}/api/ipguard/limit/{profile_id}`. NOT part of `_settings_snapshot` — this switches customers off, and an unrelated settings save must never be able to arm it. Bot: `adm_sub_iplimit:` on the admin sub panel (`_render_sub_panel` also shows the current allowance and any live penalty).

## 6e. Live connection view + reseller sandbox
Two things built on §6d's machinery. Covered by `tests/test_ip_guard.py` §21-24 and `tests/test_rep_sandbox.py`.

**"Who is connected to my service right now"** — `core/ip_guard.py::live_connections(profile_id)`, exposed in four places at once: the customer's bot button (`sub_conns:`), the same button in the mini-app (`POST /app/api/services/connections`), the owner's view in the bot (`adm_sub_conns:`) and in the panel (`GET /{S}/api/subs/{id}/connections`, per-service on the user page), and the reseller API (`GET /api/rep/v1/services/{id}/connections`).
- **One shared fleet snapshot serves all of them** (`fleet_snapshot`, 25s TTL, single lock with a re-check inside). Without it, a hundred customers tapping the button is five hundred requests. §21 asserts that twenty asks after the first cost zero extra reads — keep that test.
- Customer- and reseller-facing views get MASKED addresses (`5.113.20.···`); only the owner's two views pass `reveal=True`. The count, timing and server are enough to act on a sharing complaint.
- The owner's views pass `fresh=1` / call `reset_snapshot()`: they are pressed because the previous answer is being disputed, so they must not be served from a cache.
- A panel that did not answer sets `partial`, and every surface says the number is a floor. Never present a partial reading as exact.
- `render_connections()` is shared by the bot and mini-app so the wording — especially the mobile-IP caveat — cannot drift between them.

**Measured on the live fleet (2026-08-31, one reading, 5/5 panels in 1.8s):** 107 of 244 active subscriptions had at least one connection. 63 of those had exactly ONE place; the median was 1. **20 were over the default allowance of 5**, with a long tail at 28, 35, 35, 37, 40 and 58 simultaneous places — numbers mobile churn cannot produce. Also note the raw, unfiltered view showed one subscription at 647 addresses: that is the panel's 30-minute retention, and it is exactly why the freshness filter is not optional.

**The reseller sandbox** (`core/rep_sandbox.py`) — a key prefixed `atlas_test_` gets every endpoint against a scratch dataset that touches no wallet and no panel.
- Diverted AFTER authentication, scope and rate-limit checks, so 401/403/429 are still reachable — a sandbox that skipped those would only be half a rehearsal.
- **Deliberately real:** pricing, the wallet (play money, really debited, so `insufficient_funds` is reachable), usage that climbs with time, expiry and first-use.
- **Deliberately fake and labelled:** links point at `sandbox.invalid` (RFC 6761, can never resolve), nothing is provisioned, and every response carries `"sandbox": true`.
- **The one promise is "swap the key and change nothing".** `tests/test_rep_sandbox.py` §3 diffs the sandbox service object against the real `_service_payload` field for field — it already caught `create` returning a `nodes` key production does not. If you add a field to `_service_payload`, add it to `rep_sandbox.payload` too.
- A tripwire in the test replaces `XUIClient` and fails the run if a sandbox call reaches a panel.
- Sandbox keys do not count against `MAX_KEYS_PER_REP` (own ceiling of 1) — making someone revoke a working production key to get a test one would defeat the point. Issued from the bot's rep console (`rep:api_new_test`).

## 7. Pricing (`core/pricing.py`)
`package_price_for_user(user_id, pkg)` → {base, final, discount, ...}. Rules:
- Unlimited pkg (`is_unlimited` flag or traffic_gb<=0): base = user `unlimited_price` if >0 else pkg price. NEVER per-GB.
- Volume pkg: base = traffic_gb × user `price_per_gb` if >0 else pkg price. Then apply `discount_percent`.
- Set custom price to 0 = fall back to package default.
- **Display must match charge:** bot keyboards (`packages_kb`, `_renew_pkg_label`) use a `display_price` field; enrich pkgs via `_priced_packages(user_id, pkgs)` in bot/handlers/user.py before every buy/renew menu. Mini-app uses `package_price_for_user` directly.
- Wallet payments deduct the FIXED order price (`orders.price`), not a recomputed variable one.

## 8. Representative ("نماینده") system
Formerly "wholesale/عمده". `users.is_wholesale=1` = approved rep.
- **In-bot signup:** `join`/panel → `wholesale_request_kb` → `wh_terms` (rules screen) → `wh_req` (submit, sets `wholesale_request_pending=1` + `rep_topup_required=1`, notifies admins with approve/reject). Admin approves in bot (`wh_appr:`) or panel.
- Min-topup rule (`rep_min_topup` setting) gates NEW reps at buy time (`rep_topup_required`); existing reps grandfathered.
- Rep panel (bot): `representative_panel_kb` → brand (`rep:brand` + logo `rep:logo`), buy (bulk `WholesaleBuy` + single `rep_buy_single`), customers (`rep:customers`), financial report (`rep:report` via `get_rep_financials`), wallet, pricing.
- White-label: `rep_brand_name` + `rep_logo` shown on their customers' links/pages; ours never leaks (§6).
- Rep daily test allowance: `rep_test_daily_limit` setting; `count_rep_test_today`/`add_rep_test_account`.
- Admin panel: Users modal + `UserDetail.jsx` + `Reps.jsx` manage rep brand/pricing/stats. Endpoints: `/users/{id}/rep_brand`, `/users/{id}/toggle_wholesale`, `/users/{id}/pricing`, `/users/{id}/toggle_hide_brand`.

## 8b. Rep purchase report + Excel (`core/rep_report.py`)
Date-filtered "what did this representative buy" report, shown on their page in the admin panel and in the mini-app's rep tab, exportable to Excel.
- `resolve_range(preset, date_from, date_to)` — presets `week|month|3months|6months|year|all`, or an explicit Jalali `YYYY/MM/DD` pair which overrides the preset. "۱ ماه اخیر" is one **Jalali** month back (`jalali_add_months`, day clamped to month length), not 30 days. The end bound covers the whole chosen day.
- `get_rep_purchases(user_id, since, until)` (database.py) returns **one row per service** — a bulk order of 10 yields 10 rows, each with its own name and dates, which is what makes the export usable as proof — plus renewal orders (which create no new profile). A bulk order's price is DIVIDED across its services so rows sum to what was charged; `summary.total_spent` is summed over DISTINCT orders instead.
- Endpoints: `GET /{S}/api/reps/{id}/purchases` + `…/purchases.xlsx` (admin, cookie auth); `POST /app/api/rep/purchases` + `…/purchases/excel` (mini-app). **The mini-app one does not return a file** — it sends the .xlsx to the rep's Telegram chat via the bot, because blob downloads are unreliable in Telegram's WebView.
- Unlimited plans must never render as `0` GB — `traffic_label`/the Excel cell say «نامحدود». A not-yet-started service says «شروع نشده» / «پس از اولین اتصال» rather than a fake date.
- **Timezone (this is the accuracy-critical part):** `created_at` columns are the SERVER's local wall clock (`datetime('now','localtime')`), epoch-ms columns are absolute. `jalali.db_datetime_to_tehran` converts naive strings via `.astimezone()` (which reads them as system-local — exactly what they are) then to Tehran; `tehran_to_db_string` does the inverse so a Jalali range filters the right rows even on a UTC VPS. Verified across the +3:30 day rollover.
- `core/jalali.py` gained `jalali_to_gregorian`, `jalali_is_leap` (decided by round-trip, so it can never disagree with the conversions), `jalali_month_days`, `jalali_add_months`, `parse_jalali`, `jalali_datetime_display`. `web/{admin,miniapp}/src/jalali.js` is the **same algorithm in JS** (verified to agree day-for-day) — use it, don't add a date npm package.

## 8c. Representative API — `/api/rep/v1/*` (reseller integration)
A representative pastes an API key into **their own bot/panel**, which then sells on our infrastructure: create/renew/disable/revoke services and read usage, spending the rep's wallet. Three files: `core/rep_api.py` (keys, rate limit, idempotency, per-rep lock), `web/rep_api.py` (routes), `web/rep_api_docs.py` (the Persian reference page). Covered by `tests/test_rep_api.py` (plain `python tests/test_rep_api.py`, boots the real app against a throwaway DB).
- **Self-service keys.** The rep makes their own key in the bot: `representative_panel_kb` → `rep:api` → `rep:api_new` / `rep:api_del:{id}` (bot/handlers/user.py, `rep_api_kb`/`rep_api_key_kb` in keyboards.py). Max 3 active keys each. Admin sees/kills any key via `/{S}/api/rep-api` (+ `/enabled` kill switch) and `/{S}/api/reps/{uid}/apikeys[...]/revoke`.
- **NEVER mount under `/{S}/`.** The base URL goes to third parties; the secret prefix would leak the panel address. Same rule as `core/client_app.py`.
- **Only a sha256 of the key is stored** — plaintext is shown once, at creation, and is unrecoverable. That shortcut is safe *only* because the key is 32 bytes of `secrets` entropy; never copy it for anything a human chooses.
- **Authorisation is re-read from `users` on every call** (`authenticate()`), so losing `is_wholesale` or getting blocked kills every key instantly with no revocation step. Add nothing that caches it.
- **Money paths must stay idempotent and serialised.** `Idempotency-Key` on `POST /services` and `/renew` stores the first response and replays it (24h TTL) — a reseller bot retries on timeout, and without this that retry is a second charge. `rep_api.user_lock(user_id)` serialises balance writes (single-process; scaling out means moving it to the DB).
- **Partial success refunds in-request.** A batch that provisions 4 of 5 returns `207`, charges for 4, and refunds the 5th before responding. Every failure path restores the balance exactly — that is what `tests/test_rep_api.py` asserts, to the rial.
- **No Telegram messages on API actions** (a rep creating 40 services must not get 40 DMs), but everything is still a normal order row, so the admin panel and the rep report (§8b) show it.
- Pricing comes from `core.pricing`, provisioning from `core.multi_subscription` — never a second implementation, or the API and the bot drift. An "unlimited" package's `traffic_gb` is the fair-use threshold: it changes **pricing** only, and is provisioned verbatim (§7).
- Custom `traffic_gb`+`duration_days` is refused (`custom_pricing_unavailable`) when the rep has no per-GB/unlimited rate. The bot's bulk flow falls back to a hard-coded 10,000/GB; doing that through an API, where nobody reads a confirmation screen, would be silent mispricing.
- `SERVICE_SORTS`/`SERVICE_FILTERS` in web/rep_api.py are a **published contract**, deliberately not shared with the panel's `SUB_SORTS` — they change only on purpose.
- Docs live in TWO places that must move together: `web/rep_api_docs.py` (served at `/api/rep/docs`, public, fills in this install's real base URL) and `docs/REP_API.md` (the forwardable copy). Both carry the SAME samples in PHP, Python and Node.js, all built on one `atlas()` helper the reader pastes once — so an endpoint change is three snippets per doc, not three programs. A `"""` inside a Python sample would close the `r"""` template, so samples use `#` comments.
- **Behind Cloudflare the docs must keep warning about 524.** CF cuts a request at ~100s while the server finishes provisioning anyway; the advice (`count` ≤ 5, always send `Idempotency-Key`, retry the same key through `request_in_flight`) is what stops a rep double-selling. `client_ip()` already reads `CF-Connecting-IP`, so rate limits and the IP allowlist are per-caller, not per-edge.

## 9. React admin panel (`web/admin/src`)
- `api.js`: `BASE = window.__PANEL_BASE__` (secret). `api.get/post` (JSON), `api.form(path,obj)` (FormData; used for endpoints that read `request.form()` and/or redirect — treats redirect/HTML as success). Long-running ops poll job-log endpoints.
- `router.js`: hash router; `App.jsx` routes by first path segment. `Shell.jsx`: sidebar NAV + legacy deep-links + fetches `/api/branding` (logo).
- Pages (all native React — nothing is server-rendered any more): Dashboard(+Analytics), Users, UserDetail, Reps, Orders, Subscriptions (nodes, real-time ops + inbound editor + domain), SubProfiles, Servers, Packages, Proxy, Discounts, Campaigns, Referrals, ClientApp, AppStats, AppDiag, Transactions, MiniApp, Reports, Configs, LegacyClaims, Backups, Settings, Update.
- `Shell.jsx` has TWO nav groups: `NAV` (day-to-day) and `TOOLS` (setup/records/maintenance — miniapp, reports, legacy configs, transfer claims, backups, settings, update). Adding a page means: route in `App.jsx`, entry in one of those lists, and a label in `TITLES`.
- **Endpoint pattern:** JSON GET `/{S}/api/<thing>` for data; actions POST to `/{S}/<thing>/<action>`. `api.form` sends FormData for endpoints that read `request.form()` (servers/packages/discounts add+edit, settings, referral tiers, backups, miniapp); `api.post` sends JSON. **Every action endpoint answers with JSON now** — see §4. Node add/edit accept BOTH form and JSON.
- **Settings pattern:** `_settings_snapshot()` builds the full settings dict (shared by Jinja + `/api/settings`). React Settings submits the COMPLETE snapshot (partial submit resets omitted fields!). SSL/domain still done on legacy page.
- Job logs (`_read_job_log`/`_run_logged_job`/`_run_python_job`, `_JOB_LOG_PATHS`): "sync","nodeops","proxy","cert","update","miniapp_cert". Poll `/.../log` while running.

## 10. Mini-app (`web/miniapp/src/App.jsx`)
Telegram WebApp; auth via `X-Telegram-Init-Data` header → `validate_init_data`. `/app/api/{bootstrap,services,packages,wallet,referral,buy,receipt,wallet/pay,services/rename,services/renew}`. Rep section (tab "نمایندگی") shows financials + per-server link copy; `bootstrap` returns `is_rep`+`rep`+financials.

## 11. Logo/branding system
- Admin logo: setting `ui.logo_data` (data-URI). Shows in panel sidebar, favicon (injected into SPA), subscription browser page. Upload: `POST /{S}/api/logo` (+ `/api/logo/clear`), Settings page.
- Rep logo: `users.rep_logo`; bot `rep:logo` flow (send photo → `process_logo_bytes`).
- `_resolve_sub_logo(profile)`: rep's logo for rep subs, else admin logo — never leaks ours to a rep.

## 11b. Revenue forecasting & the AI analyst (`core/forecast.py`, `core/ai_analyst.py`)
The dashboard's revenue forecast used to be an OLS line through daily totals. Backtested on the owner's real 95-day history (60 rolling folds), that line scored **worse than seasonal naive** — it extrapolates whatever the last few weeks did, and this business does not trend, it oscillates. The replacement decomposes the number instead of fitting it: **median orders/day (28-day window) × 20%-trimmed basket size × multiplicative weekday factors**. Measured sMAPE went 55.4% → 27.5% at 7 days and 65.6% → 17.1% at 30. Covered by `tests/test_forecast.py`, which re-runs the backtest and fails if the new model ever loses to the old line.
- **There is deliberately no trend term.** Every variant that extended a slope (OLS, Theil-Sen, damped Holt-Winters) scored worse on this data. If you add one back, prove it with `_out_of_sample_ratios()` first — the test is the argument, not the intuition.
- **Bias correction was tried and dropped** (30.0% → 33.9%). Kept as a negative result so nobody re-adds it.
- **The band is empirical, not parametric.** A normal-theory 80% interval only held 53.6% of actuals. `band7` comes from the model's own out-of-sample error quantiles, and the UI calls it "بازه‌ی معمول" (typical range), never "confidence interval".
- `forecast()` rounds each day BEFORE summing, so the headline total always equals the sum of the plotted points. `_weekday_factors()` normalises against the mean of the *observed* weekdays, so a missing weekday stays neutral at 1.0 instead of `1/mean`.
- Needs `MIN_HISTORY=14` days; below that it returns `ok:false` and the panel says so rather than printing a number it cannot stand behind.
- **A more elaborate design was built and lost.** Shrunk local-median weekday factors + a significance-tested changepoint window + capped, damped Theil-Sen drift, scored on identical folds: 39.8% vs 28.7% at 7 days, 30.5% vs 25.1% at 30. At 7 days it also lost to seasonal naive. The win here comes from *what* is modelled (orders, then price them), not from a more sophisticated level estimator — do not re-litigate this without a fold-for-fold measurement.
- **The trailing partial day is left in on purpose.** `get_revenue_timeseries()` always appends today, part-finished. That would wreck an OLS fit, but measured at 2%/25%/60%/100% of the day elapsed it moves 7-day error by ≤0.4 points and makes 30-day WORSE by ~3 (you lose a real day of history). Every estimator is a median; one low value in 28 barely moves one.
- **Do not repeat the "one 13M reseller order" story.** It was in an earlier draft of this file and it is false: the largest single order in the 95-day history is 1.0M, and the 12.99M day was 45 ordinary orders. The skew is busy DAYS, not big orders.

**AI analyst** — optional, default OFF. The split is the whole design: **the deterministic engine computes every number; the model only interprets them.** It is never asked to predict, add, or estimate anything.
- `build_payload()` is a strict allowlist — daily totals, forecast output, package names, share percentages. No customer rows, telegram IDs, tokens, sub links, or angle brackets ever reach it (asserted in the tests).
- Two providers: `gemini` (native API, genuinely free tier, no card) and `openai` (any OpenAI-compatible base URL). **Gemini is sanctions-blocked from Iran** — if the bot's server is inside Iran the Gemini path will fail, which is exactly why the OpenAI-compatible option exists. The settings card says this out loud.
- **Provider reality, checked Aug 2026.** Gemini is the only major no-card free tier, and its free-tier terms say Google trains on submissions and that human reviewers may read input and output — the settings card states this. It is also OFAC-blocked for Iran, and Google separately rejects many datacenter ASNs, so even a German VPS can return `FAILED_PRECONDITION — user location is not supported`. OpenRouter is not a way around that: its terms explicitly forbid reaching restricted models via VPN/proxy, and its training opt-out is a *separate setting for free models*. Groq's free models are the weakest Persian performers of the candidates. There is no clean answer here; the code's job is to fail honestly and say why, which is what the 403 handler does.
- `analyze()` never raises: provider errors, malformed JSON and schema drift all come back as `{ok:false, message}` for the panel to render.
- `_normalise()` clamps the model's output to the shape the UI expects; unknown severities/efforts degrade instead of blowing up the page.
- Endpoints: `GET /{S}/api/analytics/ai` (runs it) and `GET /{S}/api/analytics/ai/status` (is it configured — used to decide whether to show the panel at all). The API key is write-only: it is never returned to the browser, and an empty field on save leaves the stored key untouched.

## 12. Settings keys (get_setting/set_setting; defaults in panel_content.SETTINGS_DEFAULTS)
Brand/UI: `ui.brand_name`, `ui.logo_data`, `ui.panel_subtitle`, `ui.custom_css/js`. Subs: `public_base_url`, `sub_info_enabled`, `sub_info_template`, `sub_brand_template`, `sub_auto_sync_*`, `sub_info_sync_on_render` (kick a sync when a client fetches the sub), `sub_render_sync_min_seconds` (floor between those syncs per token — default 900; lowering it multiplies panel load, see §6), `multi_sub_node_count/min_nodes` (LEGACY/unused — caps removed). Test: `test_account_enabled/traffic_gb/duration_days`, `rep_test_daily_limit`. Rep: `rep_min_topup`, `rep_price_per_gb` (global rep per-GB default), `rep_api_enabled` (kill switch for §8c; edited via `/{S}/api/rep-api/enabled`, NOT part of `_settings_snapshot`). Channel: `force_channel`, `channel_username`. Card: `card_number/holder/bank`. Campaigns: `campaign_trial_*`, `campaign_winback_*`. Referral: `referral_*`. Proxy: `proxy_port/secret/domain/tag/host`. Cert: `panel_domain`, `cert_email`, `atlas_tls_https_port`. Miniapp: `miniapp_enabled/domain/title/logo`. Login: `login_captcha_always`, `login_alert_enabled` (§4b). IP limit (§6d): `ip_limit_enabled` (ships 0), `ip_limit_warn_only` (ships 1), `ip_limit_default`, `ip_limit_poll_seconds`, `ip_limit_fresh_seconds`, `ip_limit_active_seconds`, `ip_limit_strikes`, `ip_limit_ipv4_bits`, `ip_limit_ipv6_bits`, `ip_limit_steps`, `ip_limit_decay_hours`, `ip_limit_warn_cooldown`, `ip_limit_grace_seconds`, `ip_limit_reassert_after`, `ip_limit_event_keep_days` — edited via `/{S}/api/ipguard`, NOT part of `_settings_snapshot`. AI analyst (§11b): `ai_enabled`, `ai_provider` (`gemini`|`openai`), `ai_model`, `ai_base_url` (openai provider only), `ai_api_key` — the key is WRITE-ONLY: `_settings_snapshot` returns `ai_key_set` (0/1) instead, and saving an empty field leaves the stored key untouched. Online counts: `online_poll_seconds` (default 120; polling runs whether or not the auto node is on — §6b). Auto node: `autonode_enabled`, `autonode_poll_seconds`, `autonode_stale_seconds`, `autonode_margin`, `autonode_min_delta`, `autonode_cooldown_minutes`, `autonode_max_moves`, `autonode_poll_concurrency` (defaults live in `core.autonode.DEFAULTS`, edited on the Subscriptions page — NOT part of `_settings_snapshot`).

## 13. Conventions & gotchas
- **RTL trap:** logical `inset-inline-end` = physical LEFT in RTL. Mobile sidebar drawer must use physical `right:0` + `translateX(105%)`. `html/body { overflow-x: clip }` prevents drawer-induced horizontal scroll (clip, not hidden, to keep sticky working).
- Bash tool = Git Bash (POSIX); don't use PowerShell heredoc there. For multi-line git messages use a heredoc via `git commit -F -`.
- Node email `_n{config_id}` suffix is load-bearing.
- **`init_db` splits the `SCHEMA` string on `;`** (`for stmt in SCHEMA.split(';')`), so a `;` inside a SQL comment silently truncates that `CREATE TABLE` → `OperationalError: incomplete input`. Never put a semicolon in a SCHEMA comment.
- **aiogram inner vs outer middleware — a silent-failure trap.** `dp.callback_query.middleware()` registers an INNER middleware, which runs only after a handler has been MATCHED by filters. A callback button whose data has NO registered handler therefore never reaches the middleware at all: the router matches nothing, nobody answers, and the user sees a spinner forever with no error anywhere. This is what broke "بررسی عضویت" — ChannelRequiredMiddleware answered the button itself, so it looked complete, but nothing was bound to `check_channel_join`. Every callback_data you put on a keyboard needs a handler, even one the middleware normally intercepts. `tests/test_channel_gate.py` drives the REAL dispatcher and routers precisely because a test that calls the middleware directly cannot see this.
- `packages_kb` is defined twice in keyboards.py; the SECOND (l.581) wins.
- **`_ensure_columns` migrations is a dict literal**, so a second entry for a table silently overrides the first and its columns are never added — with no error. Add to the EXISTING block for that table, and check with `grep -c '"<table>": \[' core/database.py`.
- Committed `dist/` — must rebuild React after src changes or the panel serves stale UI.
- Telegram MTProto proxy uses `mtg v1.0.11`; flags MUST precede positional secret (`run --bind ... SECRET [TAG]`) or bind is ignored → wrong port. Also set `MTG_BIND` env.

## 14. "Where do I change X?" index
- Subscription link contents / brand / server names → `multi_subscription.py`: `_subscription_info_links`, `_subscription_node_display_label`, `_owner_brand`, `render_subscription`.
- Node add/edit/enable/disable behavior → web/app.py `/{S}/subs/nodes/*` + `reconcile_node_config_streamed`.
- Per-node custom domain → `subscription_node_configs.connect_host` + `_apply_host_override`.
- Pricing shown/charged → `core/pricing.py` + `_priced_packages` (bot) + `/app/api/packages` (miniapp).
- Rep features → bot/handlers/user.py (`rep:*`, `wh_*`) + keyboards.py + web Users/UserDetail/Reps pages.
- Change/revoke a customer's subscription link ("تغییر لینک اشتراک") → `rotate_subscription_link` (multi_subscription.py) + `sub_relink*` handlers/keyboards (bot). See §6.
- Exclude/include reps in a campaign → `get_segment_users(..., include_reps)` + `custom_campaigns.include_reps` (database.py), `run_custom_campaign` (campaigns.py), Campaigns.jsx toggle. See §5 custom_campaigns.
- Auto-node routing / load metric / hysteresis → `core/autonode.py` (`LoadView.score`, `resolve_auto_target`, `rebalance_auto_node`); its provisioning hook is `expand_node_configs` inside `ensure_subscription_profile_nodes`.
- Reseller API endpoint / error code / limit → `web/rep_api.py`; credentials & idempotency → `core/rep_api.py`; the docs → `web/rep_api_docs.py` AND `docs/REP_API.md` (both, always). See §8c.
- Rep purchase report columns or date window → `core/rep_report.py` (`_COLUMNS`, `resolve_range`) + `get_rep_purchases` in database.py.
- Anything Jalali → `core/jalali.py` AND the mirrored `web/{admin,miniapp}/src/jalali.js` (keep them in step).
- Excel output → `core/xlsx.py` (no third-party dependency — don't add openpyxl).
- A new user column → `_ensure_columns` in database.py + expose in `_slim_user`/user-detail API.
- A new setting → `SETTINGS_DEFAULTS` (panel_content) + `_settings_snapshot` + settings_save Form param + React Settings field.
- New admin page → web/app.py `/{S}/api/<x>` JSON + `web/admin/src/pages/<X>.jsx` + wire in App.jsx and Shell.jsx (`NAV` or `TOOLS`, plus `TITLES`), then `npm --prefix web/admin run build`. Never add an HTML page route — §4.
- Bot keyboards/menus → bot/keyboards.py. Bot flows/FSM → bot/handlers/user.py + bot/states.py.
- A new sort/filter option → see §5 "Sorting & filtering": add the key to the Python key set (`USER_SORTS`,
  `SUB_SORTS`, `SERVICE_SORTS`, …) AND the matching label list in the JSX page — the two must stay in sync.
- x-ui API behavior → core/xui_api.py (XUIClient). Anything that reads state for MANY clients at once → `get_all_client_traffics()` + `PanelSessions`, never a per-node loop (§6). Anything that WRITES to many clients at once → `bulk_set_clients_enabled()` (§6c).
- Turning legacy single configs off (one, or all of them) → `core/legacy_configs.py` + `/{S}/api/configs/disable*` + the danger card in `Configs.jsx`. See §6c.
- Live online counts → `_online_poll_worker` (main.py) writes them, `server_load_snapshot()` (core/autonode.py) reads them, `/{S}/api/dashboard` → `online` serves them, `OnlineNow` in Dashboard.jsx renders them. See §6b.
```
