# AtlasSellBot

AtlasSellBot is a Telegram sales bot + web admin panel for VPN/service provisioning, with a terminal manager similar to `x-ui`.

## Highlights

- Telegram bot for ordering and account actions.
- FastAPI web admin panel for servers, packages, orders, configs, users, settings.
- Multi-inbound support per server (`inbound_ids`) with package-level inbound override (`packages.inbound_id`).
- Interactive terminal manager command: `atlas`.
- One-line bootstrap install/update commands.
- Safe updater with auto-stash support.

---

## Quick install (one line)

```bash
bash <(curl -Ls https://raw.githubusercontent.com/majazi041999-spec/AtlasSellBot/main/bootstrap.sh)
```

This will:
1. Clone/update repo in `/opt/AtlasSellBot`.
2. Run installer.
3. Configure/start `atlas-bot` service.
4. Install `/usr/local/bin/atlas` manager command.

## Quick update

```bash
bash <(curl -Ls https://raw.githubusercontent.com/majazi041999-spec/AtlasSellBot/main/bootstrap.sh) update
```

## Configure required bot credentials only

```bash
bash <(curl -Ls https://raw.githubusercontent.com/majazi041999-spec/AtlasSellBot/main/bootstrap.sh) configure
```

---

## `atlas` manager (x-ui style)

After install:

```bash
atlas
```

This opens a persistent interactive menu and stays open until you choose **Exit**.

Also supports command mode:

```bash
atlas status
atlas update
atlas restart
atlas configure
```

---

## Manual install

```bash
git clone https://github.com/majazi041999-spec/AtlasSellBot.git
cd AtlasSellBot
bash install.sh
```

Configure only (no full reinstall):

```bash
bash install.sh --configure-only
```

---

## Required `.env` values

At minimum:

```env
BOT_TOKEN=...
ADMIN_IDS=123456789
WEB_ADMIN_PASSWORD=...
WEB_SECRET_PATH=AtlasPanel2024
WEB_PORT=8000
JWT_SECRET=...
```

The installer now prompts for required values even if `.env` already exists (unless `FORCE_PROMPT=0` is used), including bot token, admin ID, web panel username/password, and panel port.

---

## Service commands

```bash
systemctl status atlas-bot
systemctl restart atlas-bot
journalctl -u atlas-bot -f
```

---

## Script overview

- `bootstrap.sh`: one-line install/update/configure/status/restart/uninstall entrypoint.
- `install.sh`: dependencies, venv, packages, env config, service setup, atlas command install.
- `atlas_menu.sh`: interactive manager and command dispatcher.
- `update.sh`: safe updater (`pull`, `pull-no-stash`, `hard`) with service + stash handling.
- `uninstall.sh`: remove service/runtime files.

---

## Multi-inbound behavior

- Server keeps:
  - `inbound_id` (default)
  - `inbound_ids` (allowed list, e.g. `1,2,3`)
- Package can set:
  - `inbound_id = 0` => use server default
  - `inbound_id > 0` => use package inbound when available on chosen server

If package inbound is not available on the selected server, the system falls back to server default inbound.

---

## Troubleshooting

### `atlas: command not found`

Run:

```bash
bash install.sh --configure-only
```

or run bootstrap install again.

### Update blocked by local changes

Use:

```bash
atlas update
```

or:

```bash
bash update.sh pull
```

### Non-interactive setup needs explicit values

If running without TTY, make sure `.env` already contains required values (`BOT_TOKEN`, `ADMIN_IDS`, `WEB_ADMIN_PASSWORD`, `JWT_SECRET`).

---

## License

Private/internal use unless repository owner specifies otherwise.
