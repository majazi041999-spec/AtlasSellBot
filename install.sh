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

# Python check
if ! command -v python3 &>/dev/null; then
  info "نصب Python3..."
  apt-get update -q && apt-get install -y python3 python3-pip -q
fi
ok "Python $(python3 --version | cut -d' ' -f2)"

# pip packages
info "نصب پکیج‌های Python..."
pip3 install -r requirements.txt -q
ok "پکیج‌ها نصب شدند"

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

  JWT_SEC=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
  sed -i "s|JWT_SECRET=.*|JWT_SECRET=$JWT_SEC|" .env
  ok "JWT Secret تولید شد"
fi

# Get web info
WEB_PORT=$(grep -m1 WEB_PORT .env | cut -d= -f2 | tr -d '\r' || echo "8000")
WEB_SECRET=$(grep -m1 WEB_SECRET_PATH .env | cut -d= -f2 | tr -d '\r' || echo "AtlasPanel2024")
SERVER_IP=$(curl -s --max-time 3 ifconfig.me 2>/dev/null || echo "YOUR_SERVER_IP")

echo ""
ok "نصب کامل شد!"
echo ""
echo -e "${GREEN}══════════════════════════════════════${NC}"
echo -e "  🌐 پنل وب: ${YELLOW}http://$SERVER_IP:$WEB_PORT/$WEB_SECRET/${NC}"
echo -e "  🤖 راه‌اندازی: ${YELLOW}python3 main.py${NC}"
echo -e "  🔧 سرویس: ${YELLOW}bash setup_service.sh${NC}"
echo -e "${GREEN}══════════════════════════════════════${NC}\n"
