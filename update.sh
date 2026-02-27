#!/usr/bin/env bash
set -euo pipefail

# Update repo from GitHub and restart systemd service
# Usage:
#   sudo ./update.sh                  # fast-forward pull (auto-stash local edits)
#   sudo ./update.sh pull             # same as default
#   sudo ./update.sh hard             # reset --hard to origin/main (drops local changes)
#   sudo ./update.sh pull-no-stash    # strict pull; fail if tree is dirty

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRANCH="${BRANCH:-main}"
SERVICE="${SERVICE:-atlas-bot}"
MODE="${1:-pull}"   # pull | hard | pull-no-stash

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "❌ '$1' نصب نیست"; exit 1; }; }
need_cmd git
need_cmd systemctl

cd "$REPO_DIR"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "❌ اینجا git repo نیست"; exit 1; }

SERVICE_STOPPED=0
STASHED=0
STASH_REF=""
STAMP="$(date +%Y%m%d-%H%M%S)"
PATCH_FILE="$REPO_DIR/update-local-changes-$STAMP.patch"

cleanup_on_error() {
  local exit_code=$?
  if [[ "$exit_code" -ne 0 ]]; then
    echo "❌ آپدیت ناموفق بود (code=$exit_code)."

    if [[ "$STASHED" -eq 1 ]]; then
      echo "ℹ️ تلاش برای بازگردانی تغییرات stash شده ..."
      if git stash pop --index -q "$STASH_REF"; then
        echo "✅ تغییرات لوکال بازگردانی شدند."
      else
        echo "⚠️ بازگردانی خودکار stash کامل نشد."
        echo "   برای بررسی دستی: git stash list"
      fi
      STASHED=0
    fi

    if [[ "$SERVICE_STOPPED" -eq 1 ]]; then
      echo "ℹ️ Start سرویس $SERVICE برای جلوگیری از downtime ..."
      systemctl start "$SERVICE" || true
    fi
  fi
}
trap cleanup_on_error EXIT

echo "ℹ️ Fetch از origin/$BRANCH ..."
git fetch origin "$BRANCH" --prune

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"

if [[ "$LOCAL" == "$REMOTE" ]]; then
  echo "✅ کد آپدیت است"
  systemctl restart "$SERVICE"
  trap - EXIT
  exit 0
fi

if [[ "$MODE" == "pull" || "$MODE" == "pull-no-stash" ]]; then
  if [[ -n "$(git status --porcelain)" ]]; then
    if [[ "$MODE" == "pull-no-stash" ]]; then
      echo "❌ ورک‌تری تمیز نیست و pull-no-stash انتخاب شده."
      echo "   یا commit/stash کنید یا از حالت پیش‌فرض pull استفاده کنید."
      exit 3
    fi

    echo "⚠️ تغییرات لوکال شناسایی شد؛ قبل از آپدیت stash می‌شوند."
    git diff > "$PATCH_FILE" || true
    echo "ℹ️ بکاپ diff: $PATCH_FILE"

    git stash push -u -m "atlas-auto-stash-$STAMP" >/dev/null
    STASH_REF="stash@{0}"
    STASHED=1
  fi
fi

echo "ℹ️ Stop سرویس $SERVICE ..."
systemctl stop "$SERVICE" || true
SERVICE_STOPPED=1

case "$MODE" in
  pull|pull-no-stash)
    echo "ℹ️ git pull --ff-only ..."
    git pull --ff-only origin "$BRANCH"
    ;;
  hard)
    echo "⚠️ git reset --hard origin/$BRANCH ..."
    git reset --hard "origin/$BRANCH"
    ;;
  *)
    echo "Usage: $0 [pull|hard|pull-no-stash]"
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
SERVICE_STOPPED=0

if [[ "$STASHED" -eq 1 ]]; then
  echo "ℹ️ بازگردانی تغییرات لوکال بعد از آپدیت ..."
  if git stash pop --index -q "$STASH_REF"; then
    echo "✅ تغییرات لوکال با موفقیت برگشتند."
  else
    echo "⚠️ بازگردانی stash با conflict همراه شد."
    echo "   stash نگه داشته شد؛ با 'git stash list' بررسی کنید."
  fi
  STASHED=0
fi

echo "✅ done"
trap - EXIT
