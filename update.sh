#!/usr/bin/env bash
set -euo pipefail

# Update repo from GitHub and restart systemd service
# Usage:
#   sudo ./update.sh            # fast-forward pull
#   sudo ./update.sh hard       # reset --hard to origin/main (drops local changes)

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRANCH="${BRANCH:-main}"
SERVICE="${SERVICE:-atlas-bot}"
MODE="${1:-pull}"   # pull | hard

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "❌ '$1' نصب نیست"; exit 1; }; }
need_cmd git
need_cmd systemctl

cd "$REPO_DIR"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "❌ اینجا git repo نیست"; exit 1; }

echo "ℹ️ Fetch از origin/$BRANCH ..."
git fetch origin "$BRANCH" --prune

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"

if [[ "$LOCAL" == "$REMOTE" ]]; then
  echo "✅ کد آپدیت است"
  systemctl restart "$SERVICE"
  exit 0
fi

echo "ℹ️ Stop سرویس $SERVICE ..."
systemctl stop "$SERVICE" || true

case "$MODE" in
  pull)
    echo "ℹ️ git pull --ff-only ..."
    git pull --ff-only origin "$BRANCH"
    ;;
  hard)
    echo "⚠️ git reset --hard origin/$BRANCH ..."
    git reset --hard "origin/$BRANCH"
    ;;
  *)
    echo "Usage: $0 [pull|hard]"
    exit 2
    ;;
esac

# update python deps
if [[ -x "$REPO_DIR/.venv/bin/pip" ]]; then
  "$REPO_DIR/.venv/bin/pip" install -r "$REPO_DIR/requirements.txt" --upgrade
fi

# reload service unit (if changed) and restart
if [[ -f "$REPO_DIR/setup_service.sh" ]]; then
  bash "$REPO_DIR/setup_service.sh"
else
  systemctl start "$SERVICE"
fi

echo "✅ done"
