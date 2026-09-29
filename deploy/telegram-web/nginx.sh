#!/usr/bin/env bash
# Wire the panel's Telegram Web into nginx on the bot server (port 2083 vhost).
# Idempotent; restores the previous config if `nginx -t` fails. See docs/telegram-web.md.
#
#   bash deploy/telegram-web/nginx.sh
set -euo pipefail

BOT_DIR=/opt/AtlasSellBot
SITE=/etc/nginx/conf.d/atlas.conf
SNIPPET=/etc/nginx/snippets/atlas-tgweb.conf
MAPCONF=/etc/nginx/conf.d/atlas-tgweb-map.conf

# The panel's secret prefix, asked from the bot itself so it is read exactly the way
# the panel reads it (parsing .env by hand here once produced a wrong path).
S="$(cd "$BOT_DIR" && "$BOT_DIR/.venv/bin/python" -c 'from core.config import WEB_SECRET_PATH as s; print(s)')"
if [ -z "$S" ] || [[ "$S" == */* ]]; then
    echo "could not read WEB_SECRET_PATH from core.config" >&2
    exit 1
fi

backup_dir="/root/nginx-bak-tgweb-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir"
cp -a "$SITE" "$backup_dir/"
[ -f "$SNIPPET" ] && cp -a "$SNIPPET" "$backup_dir/"
[ -f "$MAPCONF" ] && cp -a "$MAPCONF" "$backup_dir/"

cat > "$MAPCONF" <<'EOF'
# Telegram Web relay: websocket upgrades get "Connection: upgrade", plain HTTP keeps alive.
map $http_upgrade $atlas_tg_connection {
    default upgrade;
    ''      '';
}
# The app shell must revalidate; hashed bundles and emoji images never change.
map $uri $atlas_tg_cache {
    ~/tg/(index\.html)?$  "no-cache";
    default               "public, max-age=604800";
}
EOF

umask 027
cat > "$SNIPPET" <<EOF
# Telegram Web A inside the admin panel (AtlasSellBot docs/telegram-web.md).
# Static app under /<secret>/tg/, MTProto relay under /<secret>/tgws/. Both require
# a logged-in admin: nginx asks the bot (/api/tg/auth) before serving either.
location = /$S/tg { return 301 /$S/tg/; }

location = /$S/tg/atlas-config.js {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
}

# Plain prefix (not ^~) so the regex just below can carve out the public files.
location /$S/tg/ {
    auth_request /$S/api/tg/auth;
    # Panel session expired (it lasts JWT_EXPIRE_HOURS): log in, then the panel's
    # #/telegram route sends the owner straight back here.
    error_page 401 = @atlas_tg_login;
    alias /opt/atlas-tgweb/current/;
    index index.html;
    add_header Cache-Control \$atlas_tg_cache always;
}

# Browsers fetch these WITHOUT cookies (service worker script, web manifest, icons),
# so behind the login they were redirected: the service worker failed to register and
# the app could not be installed. They are stock Telegram Web files, nothing secret.
location ~ ^/$S/tg/((?:service\.worker-[A-Za-z0-9_-]+\.js)|(?:site(?:_dev)?\.webmanifest)|(?:favicon[A-Za-z0-9._-]*)|(?:(?:apple-touch-)?icon[A-Za-z0-9._-]*\.png)|(?:browserconfig\.xml))\$ {
    alias /opt/atlas-tgweb/current/\$1;
    add_header Cache-Control "no-cache" always;
}

location @atlas_tg_login {
    return 302 /$S/#/telegram;
}

# Only Telegram's five web DCs (and their -1 media twins) — never an open proxy.
location ~ ^/$S/tgws/(zws[1-5](?:-1)?)/((?:apiws|apiw1)(?:_test)?(?:_premium)?)\$ {
    set \$tg_host \$1.web.telegram.org;
    set \$tg_path \$2;
    auth_request /$S/api/tg/auth;
    resolver 1.1.1.1 8.8.8.8 valid=300s ipv6=off;
    proxy_pass https://\$tg_host/\$tg_path;
    proxy_http_version 1.1;
    proxy_set_header Host \$tg_host;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection \$atlas_tg_connection;
    proxy_set_header X-Forwarded-For "";
    proxy_ssl_server_name on;
    proxy_ssl_name \$tg_host;
    proxy_buffering off;
    proxy_request_buffering off;
    proxy_read_timeout 1h;
    proxy_send_timeout 1h;
    client_max_body_size 64m;
}

location = /$S/api/tg/auth {
    internal;
    proxy_pass http://127.0.0.1:8000;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-Proto https;
}
EOF
chown root:www-data "$SNIPPET" 2>/dev/null || true

# Include the snippet inside the 2083 server block, once, just before its catch-all.
if ! grep -q "include $SNIPPET;" "$SITE"; then
    python3 - "$SITE" "$SNIPPET" <<'PY'
import re, sys
site, snippet = sys.argv[1], sys.argv[2]
s = open(site).read()
m = re.search(r"listen 2083 ssl[^\n]*\n", s)
if not m:
    sys.exit("2083 server block not found")
i = s.index("    location / {", m.end())
s = s[:i] + f"    include {snippet};\n\n" + s[i:]
open(site, "w").write(s)
PY
fi

if nginx -t 2>/dev/null; then
    systemctl reload nginx
    echo "nginx: telegram web wired (backup in $backup_dir)"
else
    nginx -t || true
    cp -a "$backup_dir/atlas.conf" "$SITE"
    rm -f "$SNIPPET" "$MAPCONF"
    [ -f "$backup_dir/atlas-tgweb.conf" ] && cp -a "$backup_dir/atlas-tgweb.conf" "$SNIPPET"
    [ -f "$backup_dir/atlas-tgweb-map.conf" ] && cp -a "$backup_dir/atlas-tgweb-map.conf" "$MAPCONF"
    echo "nginx -t failed; previous config restored" >&2
    exit 1
fi
