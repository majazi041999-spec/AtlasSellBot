#!/bin/bash
# Complete uninstall script for Atlas Account Bot
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info(){ echo -e "${BLUE}ℹ${NC} $1"; }
ok(){ echo -e "${GREEN}✓${NC} $1"; }
warn(){ echo -e "${YELLOW}⚠${NC} $1"; }
err(){ echo -e "${RED}✗${NC} $1"; }

DIR=$(pwd)
SERVICE_NAME="atlas-bot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
ATLAS_CMD="/usr/local/bin/atlas"
BOOTSTRAP_DIR="/opt/AtlasSellBot"

PURGE_SELF=0
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --purge-self) PURGE_SELF=1 ;;
    --force) FORCE=1 ;;
  esac
done

echo -e "\n${RED}══════════════════════════════════════${NC}"
echo -e "${RED}      Atlas Account Bot — Full Uninstall${NC}"
echo -e "${RED}══════════════════════════════════════${NC}\n"

if [ "$FORCE" -ne 1 ]; then
  warn "This will remove service, local runtime data, and global atlas command."
  read -p "Do you want to continue? (yes/no): " ANS
  if [ "$ANS" != "yes" ]; then
    info "Canceled."
    exit 0
  fi
fi

# stop/disable service safely
if command -v systemctl &>/dev/null; then
  if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
    info "Stopping service ${SERVICE_NAME}..."
    systemctl stop "${SERVICE_NAME}" || true
    systemctl disable "${SERVICE_NAME}" || true
    ok "Service stopped and disabled"
  fi

  if [ -f "$SERVICE_FILE" ]; then
    info "Removing systemd service file..."
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload || true
    ok "Service file removed"
  fi
fi

# remove global atlas command if present
if [ -f "$ATLAS_CMD" ]; then
  info "Removing global atlas command ($ATLAS_CMD)..."
  rm -f "$ATLAS_CMD"
  ok "Global atlas command removed"
fi

# remove local runtime files
info "Removing local bot files..."
rm -rf "$DIR/.venv" \
       "$DIR/atlas.db" \
       "$DIR/atlas.log" \
       "$DIR/.env" \
       "$DIR/__pycache__" \
       "$DIR/bot/__pycache__" \
       "$DIR/bot/handlers/__pycache__" \
       "$DIR/core/__pycache__" \
       "$DIR/web/__pycache__"
ok "Runtime files and local data removed"

if [ "$PURGE_SELF" -eq 1 ]; then
  PARENT_DIR=$(dirname "$DIR")
  BASENAME_DIR=$(basename "$DIR")
  info "Removing project directory completely: ${DIR}"
  (cd "$PARENT_DIR" && rm -rf "$BASENAME_DIR")
  ok "Project directory removed"
else
  warn "Source directory was kept. To remove it too, run:"
  echo "  bash uninstall.sh --purge-self --force"
fi

echo ""
ok "Uninstall completed ✅"
