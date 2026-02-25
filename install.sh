#!/bin/bash
# ══════════════════════════════════════════════════════
#          Atlas Account Bot — Install & Setup
# ══════════════════════════════════════════════════════
set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info(){ echo -e "${BLUE}ℹ${NC} $1"; }
ok(){ echo -e "${GREEN}✓${NC} $1"; }
warn(){ echo -e "${YELLOW}⚠${NC} $1"; }
err(){ echo -e "${RED}✗${NC} $1"; }

echo -e "\n${BLUE}══════════════════════════════════════${NC}"
echo -e "${BLUE}      Atlas Account Bot — Install${NC}"
echo -e "${BLUE}══════════════════════════════════════${NC}\n"

if [ "$(id -u)" -ne 0 ]; then
  warn "Tip: run this installer as root so system dependencies can be installed automatically."
fi

apt_run(){
  if [ "$(id -u)" -eq 0 ]; then
    apt-get "$@"
  elif command -v sudo &>/dev/null; then
    sudo apt-get "$@"
  else
    return 1
  fi
}

install_venv_support(){
  if ! command -v apt-get &>/dev/null; then
    err "apt-get is not available. Please install python3-venv manually and run again."
    return 1
  fi

  PY_MM=$(python3 - <<'EOF'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
EOF
)

  info "Installing venv support packages for Python ${PY_MM}..."
  apt_run update -q
  apt_run install -y python3-venv "python${PY_MM}-venv" -q || apt_run install -y python3-venv -q
}

create_venv(){
  info "Creating Python virtual environment (.venv)..."
  if python3 -m venv .venv 2>/tmp/atlas_venv_err.log; then
    return 0
  fi

  if grep -qiE "ensurepip is not available|No module named ensurepip" /tmp/atlas_venv_err.log; then
    warn "ensurepip is missing; trying to install python3-venv packages..."
    if ! install_venv_support; then
      cat /tmp/atlas_venv_err.log
      err "Could not install required venv packages automatically."
      err "Run: apt-get install -y python3-venv"
      exit 1
    fi

    if python3 -m venv .venv 2>/tmp/atlas_venv_err_retry.log; then
      return 0
    fi

    cat /tmp/atlas_venv_err_retry.log
    err "Virtual environment creation failed after installing venv packages."
    exit 1
  fi

  cat /tmp/atlas_venv_err.log
  err "Virtual environment creation failed."
  exit 1
}


# Python + pip check
if ! command -v python3 &>/dev/null; then
  info "Installing Python3..."
  apt_run update -q && apt_run install -y python3 python3-venv python3-pip curl -q
fi

if ! python3 -m pip --version &>/dev/null; then
  info "Installing pip for python3..."
  if command -v apt-get &>/dev/null; then
    apt_run update -q && apt_run install -y python3-pip -q
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

info "Upgrading pip inside venv..."
$PYTHON_BIN -m pip install --upgrade pip setuptools wheel -q

# pip packages
info "Installing Python packages..."
$PIP_BIN install -r requirements.txt -q
ok "Packages installed"

# .env.example fallback
if [ ! -f ".env.example" ]; then
  warn ".env.example not found; creating a default template."
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
  warn ".env was created. Please fill in the following values:"
  echo ""

  read -p "  🤖 Telegram bot token: " BOT_TOKEN
  sed -i "s|BOT_TOKEN=.*|BOT_TOKEN=$BOT_TOKEN|" .env

  read -p "  👤 Admin numeric ID (from @userinfobot): " ADMIN_ID
  sed -i "s|ADMIN_IDS=.*|ADMIN_IDS=$ADMIN_ID|" .env

  read -p "  🔐 Web panel password: " WEB_PASS
  sed -i "s|WEB_ADMIN_PASSWORD=.*|WEB_ADMIN_PASSWORD=$WEB_PASS|" .env

  read -p "  💳 Card number (with dashes): " CARD_NUM
  sed -i "s|CARD_NUMBER=.*|CARD_NUMBER=$CARD_NUM|" .env

  read -p "  👤 Card holder name: " CARD_HOLDER
  sed -i "s|CARD_HOLDER=.*|CARD_HOLDER=$CARD_HOLDER|" .env

  read -p "  🏦 Bank name: " CARD_BANK
  sed -i "s|CARD_BANK=.*|CARD_BANK=$CARD_BANK|" .env

  JWT_SEC=$($PYTHON_BIN -c "import secrets; print(secrets.token_urlsafe(48))")
  sed -i "s|JWT_SECRET=.*|JWT_SECRET=$JWT_SEC|" .env
  ok "JWT secret generated"
fi

# Get web info
WEB_PORT=$(grep -m1 '^WEB_PORT=' .env | cut -d= -f2 | tr -d '\r' || true)
WEB_SECRET=$(grep -m1 '^WEB_SECRET_PATH=' .env | cut -d= -f2 | tr -d '\r' || true)
WEB_PORT=${WEB_PORT:-8000}
WEB_SECRET=${WEB_SECRET:-AtlasPanel2024}
SERVER_IP=$(curl -s --max-time 3 ifconfig.me 2>/dev/null || echo "YOUR_SERVER_IP")

echo ""
ok "Installation completed!"
echo ""
echo -e "${GREEN}══════════════════════════════════════${NC}"
echo -e "  🌐 Web panel: ${YELLOW}http://$SERVER_IP:$WEB_PORT/$WEB_SECRET/${NC}"
echo -e "  🤖 Manual start: ${YELLOW}./.venv/bin/python main.py${NC}"
echo -e "  🔧 Install/update service: ${YELLOW}bash setup_service.sh${NC}"
echo -e "  ▶️ Start service: ${YELLOW}systemctl start atlas-bot${NC}"
echo -e "  ⏹️ Stop service: ${YELLOW}systemctl stop atlas-bot${NC}"
echo -e "  🔁 Restart service: ${YELLOW}systemctl restart atlas-bot${NC}"
echo -e "  📊 Service status: ${YELLOW}systemctl status atlas-bot${NC}"
echo -e "  📜 Live logs: ${YELLOW}journalctl -u atlas-bot -f${NC}"
echo -e "  🧹 Full uninstall: ${YELLOW}bash uninstall.sh${NC}"
echo -e "${GREEN}══════════════════════════════════════${NC}\n"
