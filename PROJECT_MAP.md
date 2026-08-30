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
  app.py           (5049)   FastAPI: admin JSON API + legacy Jinja pages + subscription serving (/sub) + mini-app API (/app/api) + proxy + logo + update. Secret-prefixed routes: /{S}/... where S=WEB_SECRET_PATH.
  rep_api.py       (959)    the `/api/rep/v1/*` routes a representative's own bot calls (§8c).
  rep_api_docs.py  (373)    the Persian RTL reference page served at `/api/rep/docs`.
  admin/src/       React admin panel (see §9). pages/*.jsx, components/{Shell,ui}.jsx, api.js, router.js.
  miniapp/src/App.jsx  Telegram mini-app (single file).
  templates/*.html Legacy Jinja panel (fallback at /{S}/dashboard; most pages migrated to React).
docs/REP_API.md    forwardable copy of the reseller API reference — keep in step with web/rep_api_docs.py.
setup_mtproxy.sh   MTProto proxy installer (mtg v1.0.11). atlas_menu.sh, install.sh, update.sh, setup_*.sh.
```

## 4. Web serving model (important)
- Secret path prefix: every panel route is `/{S}/...` where `S = WEB_SECRET_PATH` (default `AtlasPanel2024`).
- **React is the MAIN panel**, served at root `/{S}/`. Assets at `/{S}/assets` (bundle uses relative base). `/{S}/v2` → redirects to root. Legacy Jinja dashboard stays at `/{S}/dashboard` as fallback (also used if React build missing).
- SPA served by `admin_root_index` / `_serve_admin_spa()` which injects `window.__PANEL_BASE__="/{S}"` and the favicon (admin logo).
- Mini-app served at `/app` (+ `/app/api/*`), assets `/app/assets`.
- **Reseller API at a plain `/api/rep/v1` prefix** (never under `/{S}`) + public docs at `/api/rep/docs`. See §8c.
- Subscription links served at `/sub/{token}` → base64 config list for VPN clients; browser page = `_render_sub_status_html` (branded per owner, rep-safe).
- Auth: JWT cookie; `_auth(request)` for Jinja routes, `_api_guard(request)` for `/{S}/api/*`. Bot admin = ADMIN_IDS / owner_admin_id / users.is_admin.

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
- Worker: `_auto_node_worker` in main.py — polls every `autonode_poll_seconds`, rebalances every 3rd poll. Panel: `/{S}/subs/autonode/{refresh,rebalance,settings}`, rebalance streams to the "nodeops" job log.
- `XUIClient.get_online_count()` returns `Optional[int]` — **None means unknown**; never coerce it to 0. It tries `/panel/api/clients/onlines` (3x-ui v3.1+), `/panel/api/inbounds/onlines` (v2), `/panel/inbound/onlines` (legacy web route), remembers which worked, and normalizes both `[email]` and `[{email}]` shapes. v3 CSRF-protects `/login` itself, so `_login` retries once with a token from `/csrf-token`.

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
- Docs live in TWO places that must move together: `web/rep_api_docs.py` (served at `/api/rep/docs`, public, fills in this install's real base URL) and `docs/REP_API.md` (the forwardable copy).

## 9. React admin panel (`web/admin/src`)
- `api.js`: `BASE = window.__PANEL_BASE__` (secret). `api.get/post` (JSON), `api.form(path,obj)` (FormData; used for endpoints that read `request.form()` and/or redirect — treats redirect/HTML as success). Long-running ops poll job-log endpoints.
- `router.js`: hash router; `App.jsx` routes by first path segment. `Shell.jsx`: sidebar NAV + legacy deep-links + fetches `/api/branding` (logo).
- Pages (native React): Dashboard(+Analytics), Users, UserDetail, Reps, Orders, Subscriptions (nodes, real-time ops + inbound editor + domain), SubProfiles, Servers, Packages, Proxy, Discounts, Campaigns, Referrals, Settings, Update. Legacy Jinja still: configs, miniapp settings.
- **Endpoint pattern:** JSON GET `/{S}/api/<thing>` for data; actions reuse existing form/JSON endpoints. add/edit for servers/packages/discounts use `api.form` → existing Jinja form endpoints (redirect=success). Node add/edit accept BOTH form and JSON.
- **Settings pattern:** `_settings_snapshot()` builds the full settings dict (shared by Jinja + `/api/settings`). React Settings submits the COMPLETE snapshot (partial submit resets omitted fields!). SSL/domain still done on legacy page.
- Job logs (`_read_job_log`/`_run_logged_job`/`_run_python_job`, `_JOB_LOG_PATHS`): "sync","nodeops","proxy","cert","update","miniapp_cert". Poll `/.../log` while running.

## 10. Mini-app (`web/miniapp/src/App.jsx`)
Telegram WebApp; auth via `X-Telegram-Init-Data` header → `validate_init_data`. `/app/api/{bootstrap,services,packages,wallet,referral,buy,receipt,wallet/pay,services/rename,services/renew}`. Rep section (tab "نمایندگی") shows financials + per-server link copy; `bootstrap` returns `is_rep`+`rep`+financials.

## 11. Logo/branding system
- Admin logo: setting `ui.logo_data` (data-URI). Shows in panel sidebar, favicon (injected into SPA), subscription browser page. Upload: `POST /{S}/api/logo` (+ `/api/logo/clear`), Settings page.
- Rep logo: `users.rep_logo`; bot `rep:logo` flow (send photo → `process_logo_bytes`).
- `_resolve_sub_logo(profile)`: rep's logo for rep subs, else admin logo — never leaks ours to a rep.

## 12. Settings keys (get_setting/set_setting; defaults in panel_content.SETTINGS_DEFAULTS)
Brand/UI: `ui.brand_name`, `ui.logo_data`, `ui.panel_subtitle`, `ui.custom_css/js`. Subs: `public_base_url`, `sub_info_enabled`, `sub_info_template`, `sub_brand_template`, `sub_auto_sync_*`, `sub_info_sync_on_render` (kick a sync when a client fetches the sub), `sub_render_sync_min_seconds` (floor between those syncs per token — default 900; lowering it multiplies panel load, see §6), `multi_sub_node_count/min_nodes` (LEGACY/unused — caps removed). Test: `test_account_enabled/traffic_gb/duration_days`, `rep_test_daily_limit`. Rep: `rep_min_topup`, `rep_price_per_gb` (global rep per-GB default), `rep_api_enabled` (kill switch for §8c; edited via `/{S}/api/rep-api/enabled`, NOT part of `_settings_snapshot`). Channel: `force_channel`, `channel_username`. Card: `card_number/holder/bank`. Campaigns: `campaign_trial_*`, `campaign_winback_*`. Referral: `referral_*`. Proxy: `proxy_port/secret/domain/tag/host`. Cert: `panel_domain`, `cert_email`, `atlas_tls_https_port`. Miniapp: `miniapp_enabled/domain/title/logo`. Auto node: `autonode_enabled`, `autonode_poll_seconds`, `autonode_stale_seconds`, `autonode_margin`, `autonode_min_delta`, `autonode_cooldown_minutes`, `autonode_max_moves`, `autonode_poll_concurrency` (defaults live in `core.autonode.DEFAULTS`, edited on the Subscriptions page — NOT part of `_settings_snapshot`).

## 13. Conventions & gotchas
- **RTL trap:** logical `inset-inline-end` = physical LEFT in RTL. Mobile sidebar drawer must use physical `right:0` + `translateX(105%)`. `html/body { overflow-x: clip }` prevents drawer-induced horizontal scroll (clip, not hidden, to keep sticky working).
- Bash tool = Git Bash (POSIX); don't use PowerShell heredoc there. For multi-line git messages use a heredoc via `git commit -F -`.
- Node email `_n{config_id}` suffix is load-bearing.
- **`init_db` splits the `SCHEMA` string on `;`** (`for stmt in SCHEMA.split(';')`), so a `;` inside a SQL comment silently truncates that `CREATE TABLE` → `OperationalError: incomplete input`. Never put a semicolon in a SCHEMA comment.
- `packages_kb` is defined twice in keyboards.py; the SECOND (l.581) wins.
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
- New admin page → web/app.py `/{S}/api/<x>` JSON + `web/admin/src/pages/<X>.jsx` + wire in App.jsx + Shell.jsx nav, then `npm --prefix web/admin run build`.
- Bot keyboards/menus → bot/keyboards.py. Bot flows/FSM → bot/handlers/user.py + bot/states.py.
- A new sort/filter option → see §5 "Sorting & filtering": add the key to the Python key set (`USER_SORTS`,
  `SUB_SORTS`, `SERVICE_SORTS`, …) AND the matching label list in the JSX page — the two must stay in sync.
- x-ui API behavior → core/xui_api.py (XUIClient). Anything that reads state for MANY clients at once → `get_all_client_traffics()` + `PanelSessions`, never a per-node loop (§6).
```
