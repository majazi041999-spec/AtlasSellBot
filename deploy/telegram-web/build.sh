#!/usr/bin/env bash
# Build the panel's Telegram Web A on this server and switch /opt/atlas-tgweb/current
# to it. Run as root on the bot server. See docs/telegram-web.md.
#
#   bash deploy/telegram-web/build.sh
#
# Upstream is pinned: the patch below was written against this exact commit. To
# move to a newer Telegram Web A, bump TT_COMMIT, rebuild and re-check the patch.
set -euo pipefail

TT_COMMIT=28ffcf710b15571e5a2f7bb3bdce3fc90fc8ec80
NODE_VER=v24.21.0                       # telegram-tt requires node >= 24.15
ROOT=/opt/atlas-tgweb
PATCH="$(cd "$(dirname "$0")" && pwd)/atlas-telegram-web.patch"

mkdir -p "$ROOT/build" "$ROOT/releases"
cd "$ROOT/build"

if [ ! -x node/bin/node ] || [ "$(node/bin/node -v)" != "$NODE_VER" ]; then
    tarball="node-$NODE_VER-linux-x64.tar.xz"
    curl -fsSLO "https://nodejs.org/dist/$NODE_VER/$tarball"
    curl -fsSL "https://nodejs.org/dist/$NODE_VER/SHASUMS256.txt" | grep " $tarball\$" | sha256sum -c -
    rm -rf node && mkdir node && tar -xJf "$tarball" -C node --strip-components=1 && rm -f "$tarball"
fi
export PATH="$ROOT/build/node/bin:$PATH"

rm -rf src && mkdir src && cd src
git init -q && git remote add origin https://github.com/Ajaxy/telegram-tt.git
git fetch -q --depth 1 origin "$TT_COMMIT" && git checkout -q FETCH_HEAD
git apply "$PATCH"

# This box also runs xray and the bot. Build at the lowest priority, and if memory
# ever runs short let the kernel kill the build rather than a customer-facing service.
echo 1000 > /proc/self/oom_score_adj
export NODE_OPTIONS=--max-old-space-size=2048 ATLAS_RUNTIME_API=1
nice -n 19 ionice -c3 npm ci --no-audit --no-fund
nice -n 19 ionice -c3 npm run build:production

# Build reports and Google's site-verification file are not part of the app.
rm -f dist/build-stats.json dist/statoscope-report.html dist/google*.html
release="$ROOT/releases/${TT_COMMIT:0:7}-$(date +%Y%m%d%H%M%S)"
mv dist "$release"
chmod -R a+rX "$release"
ln -sfn "$release" "$ROOT/current"
cd "$ROOT/build" && rm -rf src
echo "telegram web: $ROOT/current -> $release ($(du -sh "$release" | cut -f1))"
