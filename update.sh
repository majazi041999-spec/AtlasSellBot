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

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "❌ '$1' is not installed"; exit 1; }; }
need_cmd git
need_cmd systemctl
need_cmd python3

cd "$REPO_DIR"
if ! git rev-parse --is-inside-work-tree >/dev/null 2>/tmp/atlas_git_check.err; then
  if grep -qi "dubious ownership" /tmp/atlas_git_check.err; then
    echo "⚠️ Git safe.directory issue detected; trusting $REPO_DIR for this user."
    git config --global --add safe.directory "$REPO_DIR"
  fi
fi
if ! git rev-parse --is-inside-work-tree >/dev/null 2>/tmp/atlas_git_check.err; then
  echo "❌ Current directory is not a git repository or Git cannot access it:"
  cat /tmp/atlas_git_check.err
  exit 1
fi

SERVICE_STOPPED=0
STASHED=0
STASH_REF=""
STAMP="$(date +%Y%m%d-%H%M%S)"
PATCH_FILE="$REPO_DIR/update-local-changes-$STAMP.patch"
STOP_TIMEOUT="${STOP_TIMEOUT:-20}"

stop_service_fast() {
  local service="$1"
  local timeout="$2"

  if ! systemctl is-active --quiet "$service"; then
    return 0
  fi

  systemctl stop "$service" --no-block || return 0
  for ((i=0; i<timeout; i++)); do
    if ! systemctl is-active --quiet "$service"; then
      return 0
    fi
    sleep 1
  done

  echo "⚠️ Service $service did not stop after ${timeout}s; forcing it down ..."
  systemctl kill --kill-who=all --signal=SIGKILL "$service" || true
  for _ in 1 2 3 4 5; do
    if ! systemctl is-active --quiet "$service"; then
      return 0
    fi
    sleep 1
  done
  return 0
}

cleanup_on_error() {
  local exit_code=$?
  if [[ "$exit_code" -ne 0 ]]; then
    echo "❌ Update failed (code=$exit_code)."

    if [[ "$STASHED" -eq 1 ]]; then
      echo "ℹ️ Trying to restore stashed changes..."
      if git stash pop --index -q "$STASH_REF"; then
        echo "✅ Local changes restored."
      else
        echo "⚠️ Automatic stash restore had conflicts."
        echo "   Please check manually: git stash list"
      fi
      STASHED=0
    fi

    if [[ "$SERVICE_STOPPED" -eq 1 ]]; then
      echo "ℹ️ Starting service $SERVICE to avoid downtime..."
      systemctl start "$SERVICE" || true
    fi
  fi
}
trap cleanup_on_error EXIT

echo "ℹ️ Fetching origin/$BRANCH ..."
git fetch origin "$BRANCH" --prune

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"

if [[ "$LOCAL" == "$REMOTE" ]]; then
  echo "✅ Already up to date"
  systemctl restart "$SERVICE"
  trap - EXIT
  exit 0
fi

if [[ "$MODE" == "pull" || "$MODE" == "pull-no-stash" ]]; then
  if [[ -n "$(git status --porcelain)" ]]; then
    if [[ "$MODE" == "pull-no-stash" ]]; then
      echo "❌ Working tree is dirty and pull-no-stash mode was selected."
      echo "   Please commit/stash changes or use default pull mode."
      exit 3
    fi

    echo "⚠️ Local tracked changes detected; stashing before update."
    git diff > "$PATCH_FILE" || true
    echo "ℹ️ Diff backup: $PATCH_FILE"

    git stash push -m "atlas-auto-stash-$STAMP" >/dev/null
    STASH_REF="stash@{0}"
    STASHED=1
  fi
fi

echo "ℹ️ Stopping service $SERVICE ..."
stop_service_fast "$SERVICE" "$STOP_TIMEOUT"
SERVICE_STOPPED=1

case "$MODE" in
  pull|pull-no-stash)
    echo "ℹ️ Running git pull --ff-only ..."
    git pull --ff-only origin "$BRANCH"
    ;;
  hard)
    echo "⚠️ Running git reset --hard origin/$BRANCH ..."
    git reset --hard "origin/$BRANCH"
    ;;
  *)
    echo "Usage: $0 [pull|hard|pull-no-stash]"
    exit 2
    ;;
esac

# ensure venv + update python deps
if [[ ! -x "$REPO_DIR/.venv/bin/python" ]]; then
  echo "ℹ️ .venv not found; creating virtual environment ..."
  python3 -m venv "$REPO_DIR/.venv"
fi
"$REPO_DIR/.venv/bin/python" -m pip install --upgrade pip setuptools wheel >/dev/null
"$REPO_DIR/.venv/bin/pip" install -r "$REPO_DIR/requirements.txt" --upgrade

# reload service unit (if changed) and restart
if [[ -f "$REPO_DIR/setup_service.sh" ]]; then
  bash "$REPO_DIR/setup_service.sh"
else
  systemctl start "$SERVICE"
fi
SERVICE_STOPPED=0

if [[ "$STASHED" -eq 1 ]]; then
  echo "ℹ️ Restoring local changes after update..."
  if git stash pop --index -q "$STASH_REF"; then
    echo "✅ Local changes restored successfully."
  else
    echo "⚠️ Stash restore has conflicts."
    echo "   Stash entry is kept; check with: git stash list"
  fi
  STASHED=0
fi

echo "✅ Done"
trap - EXIT
