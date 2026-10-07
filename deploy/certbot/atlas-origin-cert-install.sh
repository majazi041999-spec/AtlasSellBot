#!/bin/sh
# Install as a root-only Certbot deploy hook on the Netherlands origin.
set -eu
lineage=/etc/letsencrypt/live/atbot.anacotig.com
[ "${RENEWED_LINEAGE:-$lineage}" = "$lineage" ] || exit 0
target=/etc/ssl/atlas/atbot.anacotig.com
install -m 0600 "$lineage/fullchain.pem" "$target/fullchain.cer.new"
install -m 0600 "$lineage/privkey.pem" "$target/atbot.anacotig.com.key.new"
mv -f "$target/fullchain.cer.new" "$target/fullchain.cer"
mv -f "$target/atbot.anacotig.com.key.new" "$target/atbot.anacotig.com.key"
/usr/sbin/nginx -t
/bin/systemctl reload nginx
