#!/bin/bash
# ══════════════════════════════════════════════════════
#          Atlas Account Bot — نصب و راه‌اندازی
# ══════════════════════════════════════════════════════
set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info(){ echo -e "${BLUE}ℹ${NC} $1"; }
ok(){ echo -e "${GREEN}✓${NC} $1"; }
warn(){ echo -e "${YELLOW}⚠${NC} $1"; }
err(){ echo -e "${RED}✗${NC} $1"; }

echo -e "\n${BLUE}══════════════════════════════════════${NC}"
echo -e "${BLUE}      Atlas Account Bot — نصب${NC}"
echo -e "${BLUE}══════════════════════════════════════${NC}\n"

if [ "$(id -u)" -ne 0 ]; then
  warn "پیشنهاد: اسکریپت نصب را با root اجرا کنید تا وابستگی‌های سیستمی بدون خطا نصب شوند."
fi

install_venv_support(){
  if ! command -v apt-get &>/dev/null; then
    return 1
  fi

  PY_MM=$(python3 - <<'EOF'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
EOF
)

  info "نصب پیش‌نیاز venv برای Python ${PY_MM}..."
  apt-get update -q
  apt-get install -y python3-venv "python${PY_MM}-venv" -q || apt-get install -y python3-venv -q
}

create_venv(){
  info "ساخت محیط مجازی Python (.venv)..."
  if python3 -m venv .venv 2>/tmp/atlas_venv_err.log; then
    return 0
  fi

  if grep -qiE "ensurepip is not available|No module named ensurepip" /tmp/atlas_venv_err.log; then
    warn "ماژول ensurepip در سیستم موجود نیست؛ تلاش برای نصب python3-venv..."
    install_venv_support || true
    python3 -m venv .venv
    return 0
  fi

  cat /tmp/atlas_venv_err.log
  err "ایجاد venv ناموفق بود."
  exit 1
}


# Python + pip check
if ! command -v python3 &>/dev/null; then
  info "نصب Python3..."
  apt-get update -q && apt-get install -y python3 python3-venv python3-pip curl -q
fi

if ! python3 -m pip --version &>/dev/null; then
  info "نصب pip برای python3..."
  if command -v apt-get &>/dev/null; then
    apt-get update -q && apt-get install -y python3-pip -q
  else
    python3 -m ensurepip --upgrade || true
  fi
fi

ok "Python $(python3 --version | cut -d' ' -f2)"

# venv setup
if [ ! -d ".venv" ]; then
  create_venv
fi

PYTHON_BIN="$(pwd)/.venv/bin/python"
PIP_BIN="$(pwd)/.venv/bin/pip"

info "به‌روزرسانی pip داخل venv..."
$PYTHON_BIN -m pip install --upgrade pip setuptools wheel -q

# pip packages
info "نصب پکیج‌های Python..."
$PIP_BIN install -r requirements.txt -q
ok "پکیج‌ها نصب شدند"

# .env.example fallback
if [ ! -f ".env.example" ]; then
  warn "فایل .env.example پیدا نشد؛ فایل نمونه پیش‌فرض ساخته می‌شود."
  cat > .env.example <<'EOF'
BOT_TOKEN=
ADMIN_IDS=0
WEB_SECRET_PATH=AtlasPanel2024
WEB_ADMIN_USERNAME=atlas_admin
WEB_ADMIN_PASSWORD=ChangeMe123!
JWT_SECRET=please_change_this_secret_key_in_production
WEB_PORT=8000
CARD_NUMBER=
CARD_HOLDER=
CARD_BANK=
CHANNEL_USERNAME=
REFERRAL_BONUS_GB=5
EOF
fi

# .env setup
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo ""
  warn "فایل .env ساخته شد. لطفاً مقادیر زیر را وارد کنید:"
  echo ""

  read -p "  🤖 توکن ربات تلگرام: " BOT_TOKEN
  sed -i "s|BOT_TOKEN=.*|BOT_TOKEN=$BOT_TOKEN|" .env

  read -p "  👤 آیدی عددی ادمین (از @userinfobot): " ADMIN_ID
  sed -i "s|ADMIN_IDS=.*|ADMIN_IDS=$ADMIN_ID|" .env

  read -p "  🔐 رمز پنل وب: " WEB_PASS
  sed -i "s|WEB_ADMIN_PASSWORD=.*|WEB_ADMIN_PASSWORD=$WEB_PASS|" .env

  read -p "  💳 شماره کارت (با خط تیره): " CARD_NUM
  sed -i "s|CARD_NUMBER=.*|CARD_NUMBER=$CARD_NUM|" .env

  read -p "  👤 نام صاحب کارت: " CARD_HOLDER
  sed -i "s|CARD_HOLDER=.*|CARD_HOLDER=$CARD_HOLDER|" .env

  read -p "  🏦 نام بانک: " CARD_BANK
  sed -i "s|CARD_BANK=.*|CARD_BANK=$CARD_BANK|" .env

  JWT_SEC=$($PYTHON_BIN -c "import secrets; print(secrets.token_urlsafe(48))")
  sed -i "s|JWT_SECRET=.*|JWT_SECRET=$JWT_SEC|" .env
  ok "JWT Secret تولید شد"
fi

# Get web info
WEB_PORT=$(grep -m1 '^WEB_PORT=' .env | cut -d= -f2 | tr -d '\r' || true)
WEB_SECRET=$(grep -m1 '^WEB_SECRET_PATH=' .env | cut -d= -f2 | tr -d '\r' || true)
WEB_PORT=${WEB_PORT:-8000}
WEB_SECRET=${WEB_SECRET:-AtlasPanel2024}
SERVER_IP=$(curl -s --max-time 3 ifconfig.me 2>/dev/null || echo "YOUR_SERVER_IP")

echo ""
ok "نصب کامل شد!"
echo ""
echo -e "${GREEN}══════════════════════════════════════${NC}"
echo -e "  🌐 پنل وب: ${YELLOW}http://$SERVER_IP:$WEB_PORT/$WEB_SECRET/${NC}"
echo -e "  🤖 راه‌اندازی دستی: ${YELLOW}./.venv/bin/python main.py${NC}"
echo -e "  🔧 نصب/به‌روزرسانی سرویس: ${YELLOW}bash setup_service.sh${NC}"
echo -e "  ▶️ استارت سرویس: ${YELLOW}systemctl start atlas-bot${NC}"
echo -e "  ⏹️ استاپ سرویس: ${YELLOW}systemctl stop atlas-bot${NC}"
echo -e "  🔁 ری‌استارت: ${YELLOW}systemctl restart atlas-bot${NC}"
echo -e "  📊 وضعیت: ${YELLOW}systemctl status atlas-bot${NC}"
echo -e "  📜 لاگ زنده: ${YELLOW}journalctl -u atlas-bot -f${NC}"
echo -e "  🧹 حذف کامل: ${YELLOW}bash uninstall.sh${NC}"
echo -e "${GREEN}══════════════════════════════════════${NC}\n"
