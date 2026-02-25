#!/bin/bash
# حذف کامل Atlas Account Bot
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info(){ echo -e "${BLUE}ℹ${NC} $1"; }
ok(){ echo -e "${GREEN}✓${NC} $1"; }
warn(){ echo -e "${YELLOW}⚠${NC} $1"; }
err(){ echo -e "${RED}✗${NC} $1"; }

DIR=$(pwd)
SERVICE_NAME="atlas-bot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

PURGE_SELF=0
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --purge-self) PURGE_SELF=1 ;;
    --force) FORCE=1 ;;
  esac
done

echo -e "\n${RED}══════════════════════════════════════${NC}"
echo -e "${RED}      Atlas Account Bot — حذف کامل${NC}"
echo -e "${RED}══════════════════════════════════════${NC}\n"

if [ "$FORCE" -ne 1 ]; then
  warn "این عملیات سرویس، دیتابیس، لاگ و فایل‌های تنظیمات را حذف می‌کند."
  read -p "ادامه می‌دهید؟ (yes/no): " ANS
  if [ "$ANS" != "yes" ]; then
    info "لغو شد."
    exit 0
  fi
fi

# stop/disable service safely
if command -v systemctl &>/dev/null; then
  if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
    info "توقف سرویس ${SERVICE_NAME}..."
    systemctl stop "${SERVICE_NAME}" || true
    systemctl disable "${SERVICE_NAME}" || true
    ok "سرویس متوقف و غیرفعال شد"
  fi

  if [ -f "$SERVICE_FILE" ]; then
    info "حذف فایل سرویس systemd..."
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload || true
    ok "فایل سرویس حذف شد"
  fi
fi

# remove local runtime files
info "حذف فایل‌های محلی ربات..."
rm -rf "$DIR/.venv" \
       "$DIR/atlas.db" \
       "$DIR/atlas.log" \
       "$DIR/.env" \
       "$DIR/__pycache__" \
       "$DIR/bot/__pycache__" \
       "$DIR/bot/handlers/__pycache__" \
       "$DIR/core/__pycache__" \
       "$DIR/web/__pycache__"
ok "فایل‌های اجرایی و داده محلی حذف شدند"

if [ "$PURGE_SELF" -eq 1 ]; then
  PARENT_DIR=$(dirname "$DIR")
  BASENAME_DIR=$(basename "$DIR")
  info "حذف کامل پوشه پروژه: ${DIR}"
  (cd "$PARENT_DIR" && rm -rf "$BASENAME_DIR")
  ok "کل پوشه پروژه حذف شد"
else
  warn "پوشه سورس حفظ شد. برای حذف کامل پوشه پروژه از این دستور استفاده کنید:"
  echo "  bash uninstall.sh --purge-self --force"
fi

echo ""
ok "حذف کامل انجام شد ✅"
