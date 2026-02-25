#!/usr/bin/env bash
set -euo pipefail

# مسیر پروژه (همون جایی که این اسکریپت قرار داره)
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRANCH="${BRANCH:-main}"
SERVICE="${SERVICE:-atlas-bot}"

cd "$REPO_DIR"

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "❌ '$1' نصب نیست"; exit 1; }; }
need_cmd git
need_cmd systemctl

# مطمئن شو داخل git repo هستیم
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "❌ اینجا git repo نیست"; exit 1; }

echo "ℹ️ Fetch از origin/$BRANCH ..."
git fetch origin "$BRANCH" --prune

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"

if [[ "$LOCAL" == "$REMOTE" ]]; then
  echo "✅ کد آپدیت است (HEAD = $LOCAL)"
  echo "ℹ️ فقط ریستارت سرویس برای اعمال دوباره..."
  systemctl restart "$SERVICE"
  exit 0
fi

echo "ℹ️ آپدیت موجود است:"
echo "   LOCAL : $LOCAL"
echo "   REMOTE: $REMOTE"

# اگر تغییرات محلی داری، حالت hard امن‌تره. پیش‌فرض: pull (ff-only)
MODE="${1:-pull}"   # pull | hard

echo "ℹ️ Stop سرویس $SERVICE ..."
systemctl stop "$SERVICE" || true

case "$MODE" in
  pull)
    echo "ℹ️ git pull --ff-only ..."
    git pull --ff-only origin "$BRANCH"
    ;;
  hard)
    echo "⚠️ git reset --hard origin/$BRANCH (همه تغییرات محلی پاک میشه) ..."
    git reset --hard "origin/$BRANCH"
    ;;
  *)
    echo "Usage: $0 [pull|hard]"
    exit 2
    ;;
esac

# آپدیت وابستگی‌های پایتون داخل venv
if [[ -x "$REPO_DIR/.venv/bin/pip" ]]; then
  echo "ℹ️ نصب/آپدیت requirements داخل .venv ..."
  "$REPO_DIR/.venv/bin/pip" install -r "$REPO_DIR/requirements.txt" --upgrade
else
  echo "⚠️ .venv پیدا نشد؛ ساخت venv و نصب requirements ..."
  need_cmd python3
  python3 -m venv "$REPO_DIR/.venv"
  "$REPO_DIR/.venv/bin/pip" install --upgrade pip setuptools wheel
  "$REPO_DIR/.venv/bin/pip" install -r "$REPO_DIR/requirements.txt"
fi

# اگر setup_service.sh وجود داره، بهتره همونو اجرا کنیم تا اگر venv/مسیر عوض شد سرویس درست ست بشه
if [[ -f "$REPO_DIR/setup_service.sh" ]]; then
  echo "ℹ️ اجرای setup_service.sh (بازنویسی unit + restart) ..."
  bash "$REPO_DIR/setup_service.sh"
else
  echo "ℹ️ Start سرویس $SERVICE ..."
  systemctl start "$SERVICE"
fi

echo "✅ done"
systemctl --no-pager --full status "$SERVICE" || true
