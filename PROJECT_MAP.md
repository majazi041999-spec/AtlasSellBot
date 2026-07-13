# AtlasSellBot — Project Map (AI quick-context)

> Read this FIRST when working on this repo. It's a dense index so you can jump
> straight to the right file/function without grepping. Persian-facing product
> (RTL). Keep this file updated when architecture changes.

## 1. What it is
Telegram bot + web admin panel + Telegram mini-app for **selling VPN
subscriptions** (V2Ray/x-ui). Sells time+traffic "subscription" links that fan a
user out across many x-ui servers ("nodes"). Has wallet, discounts, referrals,
campaigns, and a **representative (reseller / "نماینده")** system with white-label
branding. Single-process app (bot + FastAPI) backed by **SQLite** (aiosqlite).

Stack: Python 3.13, aiogram 3.x (bot), FastAPI + uvicorn (web), aiosqlite,
React 18 + Vite (admin panel & mini-app, committed `dist/`), httpx (x-ui calls),
Pillow (via `qrcode[pil]`).

## 2. Run / build / deploy
- Entry: `python main.py` (runs bot + web concurrently). Port from `WEB_PORT` env (default 8000).
- **Local dev caveat:** `aiogram` is NOT installed in the dev sandbox, so `web/app.py`/`main.py` can't be imported here; use `python -m py_compile` to check syntax. `core/*` mostly import-testable.
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
  xui_api.py       (860)    XUIClient: talks to 3x-ui panels (add/update/del client, get_inbound, update_inbound, get_onlines, get_client_link).
  pricing.py        (64)    per-user package price (rep/custom). One source of truth.
  rewards.py       (300)    referral tiers/claims reward logic.
  campaigns.py     (106)    trial→paid + winback campaigns.
  renewal.py       (104)    subscription/config renewal helpers.
  backup.py        (151)    DB backup to admins.
  images.py         (37)    process_logo_bytes(): resize upload → data-URI PNG (logo system).
  miniapp.py        (73)    validate_init_data() for Telegram WebApp auth.
  panel_content.py (140)    default settings text/templates (SETTINGS_DEFAULTS, brand, sub templates).
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
  admin/src/       React admin panel (see §9). pages/*.jsx, components/{Shell,ui}.jsx, api.js, router.js.
  miniapp/src/App.jsx  Telegram mini-app (single file).
  templates/*.html Legacy Jinja panel (fallback at /{S}/dashboard; most pages migrated to React).
setup_mtproxy.sh   MTProto proxy installer (mtg v1.0.11). atlas_menu.sh, install.sh, update.sh, setup_*.sh.
```

## 4. Web serving model (important)
- Secret path prefix: every panel route is `/{S}/...` where `S = WEB_SECRET_PATH` (default `AtlasPanel2024`).
- **React is the MAIN panel**, served at root `/{S}/`. Assets at `/{S}/assets` (bundle uses relative base). `/{S}/v2` → redirects to root. Legacy Jinja dashboard stays at `/{S}/dashboard` as fallback (also used if React build missing).
- SPA served by `admin_root_index` / `_serve_admin_spa()` which injects `window.__PANEL_BASE__="/{S}"` and the favicon (admin logo).
- Mini-app served at `/app` (+ `/app/api/*`), assets `/app/assets`.
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
- **subscription_nodes**: per-(profile×node) x-ui client. profile_id, server_id, inbound_id, uuid, email `{profile_email}_n{config_id}`, link (cached), is_active.
- **configs**: legacy single-server configs (mostly superseded by subscriptions).
- **test_accounts** (UNIQUE user_id → one lifetime trial) vs **rep_test_accounts** (per-day rep allowance, no unique).
- discount_codes, discount_redemptions, referral_tiers, wallet_transactions, topup_requests, campaign_events, daily_reports.

## 6. Subscription / node engine (`core/multi_subscription.py`) — most complex, highest risk
Concept: a sold sub = 1 `subscription_profile` + a client on EVERY active `subscription_node_config` (a `subscription_node` row per node). Link `/sub/{token}` returns all node links + info lines.
- `render_subscription(token)` → base64 body served to VPN clients. Serves cached links fast; kicks background sync. Applies per-node `connect_host` override at render time (HTTP-free, instant).
- `create_profile_for_order` / `create_profile_from_config`: provision on ALL usable nodes (no min/max cap anymore; min 1 works).
- `ensure_subscription_profile_nodes(profile, force_refresh, only_config_ids)`: reconcile a profile's nodes (create missing / refresh / move / orphan-cleanup). `only_config_ids` targets one node (used by real-time per-node ops). Orphan prune skipped when targeting.
- `reconcile_node_config_streamed(log, node_id, remove, force_refresh)` + `_remove_node_config_from_profile`: real-time apply of a single node action across all profiles, streamed to the "nodeops" job log. Node add/enable/disable/edit in the panel triggers this instantly.
- `set_nodes_enabled(profile_id, enabled)`: enable/disable ALL of a profile's nodes on the panels (re-creates deleted clients on re-enable).
- Link labels: server remarks are SHORT (node name only). The user's chosen service name appears ONCE as the first info/null entry (fixed the "names too long" complaint) — see `_subscription_node_display_label` + `_subscription_info_links`.
- **Brand safety (hard rule):** our platform brand is NEVER shown on a representative's subscription — only their `rep_brand_name` (or nothing). See `_owner_brand()` → (hide, rep_brand, is_rep) and `_subscription_info_links`. Logo equivalent: `_resolve_sub_logo`/`_resolve_sub_brand` in web/app.py.
- Sync: `sync_subscription_nodes_streamed` (concurrent, time-boxed, progress log). Slowness is HTTP round-trips to x-ui, NOT SQLite — Postgres would NOT help sync speed.
- Gotcha: node email suffix `_n{config_id}` is the join key between subscription_nodes and node configs.

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
Brand/UI: `ui.brand_name`, `ui.logo_data`, `ui.panel_subtitle`, `ui.custom_css/js`. Subs: `public_base_url`, `sub_info_enabled`, `sub_info_template`, `sub_brand_template`, `sub_auto_sync_*`, `multi_sub_node_count/min_nodes` (LEGACY/unused — caps removed). Test: `test_account_enabled/traffic_gb/duration_days`, `rep_test_daily_limit`. Rep: `rep_min_topup`, `rep_price_per_gb` (global rep per-GB default). Channel: `force_channel`, `channel_username`. Card: `card_number/holder/bank`. Campaigns: `campaign_trial_*`, `campaign_winback_*`. Referral: `referral_*`. Proxy: `proxy_port/secret/domain/tag/host`. Cert: `panel_domain`, `cert_email`, `atlas_tls_https_port`. Miniapp: `miniapp_enabled/domain/title/logo`.

## 13. Conventions & gotchas
- **RTL trap:** logical `inset-inline-end` = physical LEFT in RTL. Mobile sidebar drawer must use physical `right:0` + `translateX(105%)`. `html/body { overflow-x: clip }` prevents drawer-induced horizontal scroll (clip, not hidden, to keep sticky working).
- Bash tool = Git Bash (POSIX); don't use PowerShell heredoc there. For multi-line git messages use a heredoc via `git commit -F -`.
- Node email `_n{config_id}` suffix is load-bearing.
- `packages_kb` is defined twice in keyboards.py; the SECOND (l.581) wins.
- Committed `dist/` — must rebuild React after src changes or the panel serves stale UI.
- Telegram MTProto proxy uses `mtg v1.0.11`; flags MUST precede positional secret (`run --bind ... SECRET [TAG]`) or bind is ignored → wrong port. Also set `MTG_BIND` env.

## 14. "Where do I change X?" index
- Subscription link contents / brand / server names → `multi_subscription.py`: `_subscription_info_links`, `_subscription_node_display_label`, `_owner_brand`, `render_subscription`.
- Node add/edit/enable/disable behavior → web/app.py `/{S}/subs/nodes/*` + `reconcile_node_config_streamed`.
- Per-node custom domain → `subscription_node_configs.connect_host` + `_apply_host_override`.
- Pricing shown/charged → `core/pricing.py` + `_priced_packages` (bot) + `/app/api/packages` (miniapp).
- Rep features → bot/handlers/user.py (`rep:*`, `wh_*`) + keyboards.py + web Users/UserDetail/Reps pages.
- A new user column → `_ensure_columns` in database.py + expose in `_slim_user`/user-detail API.
- A new setting → `SETTINGS_DEFAULTS` (panel_content) + `_settings_snapshot` + settings_save Form param + React Settings field.
- New admin page → web/app.py `/{S}/api/<x>` JSON + `web/admin/src/pages/<X>.jsx` + wire in App.jsx + Shell.jsx nav, then `npm --prefix web/admin run build`.
- Bot keyboards/menus → bot/keyboards.py. Bot flows/FSM → bot/handlers/user.py + bot/states.py.
- x-ui API behavior → core/xui_api.py (XUIClient).
```
