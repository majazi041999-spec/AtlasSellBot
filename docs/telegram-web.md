# Telegram inside the admin panel

The panel's «✈️ تلگرام» menu opens a full Telegram client. It is **Telegram Web A**
([Ajaxy/telegram-tt](https://github.com/Ajaxy/telegram-tt), GPL-3.0) built by us with a small
patch and served under `/<secret>/tg/`. The owner logs in inside it exactly as on
web.telegram.org.

**How it opens.** It is not boxed inside the panel. The owner asked for it to feel like
Telegram Desktop.
- The menu item is a plain link to `/<secret>/tg/` in a named tab (`atlas-telegram`), so it
  opens full-window and repeat clicks reuse the same tab.
- Chrome's address-bar **Install** turns it into a desktop app with its own window and
  taskbar icon. The manifest is relative, so its scope is `/<secret>/tg/`.
- **Expired panel session** (`JWT_EXPIRE_HOURS` in `.env`, default 24 h; NL runs 720): nginx turns the 401 into a redirect
  to `/<secret>/#/telegram`. After the login, the panel returns to that route, which forwards
  to the app.
- **No api_id yet:** `atlas-config.js` sends the owner to `#/telegram/setup` instead.
- **Changing the api_id later:** open `#/telegram/setup` in the panel.

## Why it is built this way

`*.web.telegram.org` is filtered in Iran, and the panel is not. So the browser only ever
talks to the panel's own origin (`atbot.anacotig.com:2083`). nginx relays the client's
MTProto connections to Telegram from the bot server.

- **The relay cannot read anything.** MTProto is encrypted between the browser and
  Telegram's DC. nginx only forwards bytes.
- **The Telegram session never touches the server.** It lives in the owner's browser
  (IndexedDB), exactly as on web.telegram.org.
- **The relay is not an open proxy.** It matches only Telegram's five web DCs and their
  `-1` media twins (`zws1..5[-1].web.telegram.org`, paths `apiws`/`apiw1`).
- **Both the app and the relay require a logged-in admin.** nginx asks the bot's
  `/<secret>/api/tg/auth` (the session cookie, as `/api/me` checks it) before serving either.
- **The owner's own `api_id`/`api_hash` are used.** Telegram requires every client to have
  its own. The owner creates them once at my.telegram.org → API development tools, and
  enters them on the Telegram page.
  - They are stored in settings `tg_web_api_id` / `tg_web_api_hash`. The hash is write-only
    in the admin API.
  - They reach the client as `/<secret>/tg/atlas-config.js`, admin-only and `no-store`.
    Every web client embeds these two values; they are not a password.
- **Telegram sees the bot server's IP.** Sessions show up as the Netherlands.

## The patch (`deploy/telegram-web/atlas-telegram-web.patch`)

It was written against upstream commit `28ffcf7`, which is pinned in `build.sh`.

- **`src/lib/gramjs/extensions/atlasProxy.ts` (new).** When the app runs under `…/tg/`, it
  maps `zwsN[-1].web.telegram.org/<path>` to `wss|https://<panel>/<secret>/tgws/zwsN[-1]/<path>`.
- **`PromisedWebSockets.ts` and `HttpStream.ts`.** Both the websocket and the HTTP fallback
  go through that mapping.
- **Credentials at runtime.** `index.html` loads `./atlas-config.js`. `global/actions/api/initial.ts`
  passes `window.__ATLAS_TG__` to the worker as `apiId`/`apiHash`. `methods/client.ts`
  prefers them. `api/types/misc.ts` adds the two fields.
- **`vite.config.ts`.** `ATLAS_RUNTIME_API=1` skips the build-time credential check, and
  sourcemaps are off.

## Build and deploy (on the bot server, as root)

```bash
cd /opt/AtlasSellBot && git pull --ff-only
bash deploy/telegram-web/build.sh     # Node 24 + upstream + patch → /opt/atlas-tgweb/current
bash deploy/telegram-web/nginx.sh     # once: snippet + include in the :2083 vhost, nginx -t, reload
```

`build.sh` runs at `nice 19` / `ionice idle`, with `oom_score_adj=1000`. The box also runs
xray and the bot, so if memory runs short the kernel kills the build, not a customer-facing
service.

Each build is a new directory in `/opt/atlas-tgweb/releases/`. `current` is a symlink.
- **Roll back:** point `current` at the previous release.
- **Remove the feature:** delete the `include /etc/nginx/snippets/atlas-tgweb.conf;` line
  and reload nginx.

**Updating upstream.** Bump `TT_COMMIT` in `build.sh` and rebuild. If `git apply` fails,
redo the patch against the new tree.

## Limitations

- Passkey login is tied to web.telegram.org. Phone number, code and 2FA password work normally.
- Voice and video calls need direct UDP to Telegram's servers. They may fail from Iran.
- The upstream "switch to another web version" menu is hidden off web.telegram.org.
