#!/usr/bin/env bash
# ══════════════════════════════════════════════════════
# Atlas Account Bot — Install & Setup (auto-run service)
# ══════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info(){ echo -e "${BLUE}ℹ${NC} $1"; }
ok(){ echo -e "${GREEN}✓${NC} $1"; }
warn(){ echo -e "${YELLOW}⚠${NC} $1"; }
err(){ echo -e "${RED}✗${NC} $1"; }

CONFIGURE_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --configure-only) CONFIGURE_ONLY=1 ;;
  esac
done

echo -e "\n${BLUE}══════════════════════════════════════${NC}"
echo -e "${BLUE} Atlas Account Bot — Install${NC}"
echo -e "${BLUE}══════════════════════════════════════${NC}\n"

# ---- helpers ----
apt_run(){
  if command -v apt-get >/dev/null 2>&1; then
    if [[ "$(id -u)" -eq 0 ]]; then
      apt-get "$@"
    elif command -v sudo >/dev/null 2>&1; then
      sudo apt-get "$@"
    else
      return 1
    fi
  else
    return 1
  fi
}

install_venv_support(){
  if ! command -v apt-get >/dev/null 2>&1; then
    err "apt-get is not available. Please install python3-venv manually and run again."
    return 1
  fi
  local py_mm
  py_mm="$(python3 - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
  info "Installing venv support packages for Python ${py_mm}..."
  apt_run update -q
  apt_run install -y python3-venv "python${py_mm}-venv" -q || apt_run install -y python3-venv -q
}

create_venv(){
  info "Creating Python virtual environment (.venv)..."
  if python3 -m venv .venv 2>/tmp/atlas_venv_err.log; then
    return 0
  fi
  if grep -qiE "ensurepip is not available|No module named ensurepip" /tmp/atlas_venv_err.log; then
    warn "ensurepip is missing; trying to install python3-venv packages..."
    if ! install_venv_support; then
      cat /tmp/atlas_venv_err.log || true
      err "Could not install required venv packages automatically."
      exit 1
    fi
    if python3 -m venv .venv 2>/tmp/atlas_venv_err_retry.log; then
      return 0
    fi
    cat /tmp/atlas_venv_err_retry.log || true
    err "Virtual environment creation failed after installing venv packages."
    exit 1
  fi
  cat /tmp/atlas_venv_err.log || true
  err "Virtual environment creation failed."
  exit 1
}

run_as_root(){
  if [[ "$(id -u)" -eq 0 ]]; then
    bash "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo bash "$@"
  else
    err "This step needs root but sudo is not available."
    exit 1
  fi
}

upsert_env(){
  local key="$1" value="$2"
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${value}|" .env
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

ensure_env_template(){
  if [[ ! -f ".env.example" ]]; then
    warn ".env.example not found; creating a default template."
    cat > .env.example <<'ENVEOF'
BOT_TOKEN=
ADMIN_IDS=0
WEB_SECRET_PATH=AtlasPanel2024
WEB_ADMIN_USERNAME=atlas_admin
WEB_ADMIN_PASSWORD=ChangeMe123!
JWT_SECRET=please_change_this_secret_key_in_production
WEB_PORT=8000

# کارت بانکی (از پنل قابل تغییر است؛ اینها فقط مقدار پیش‌فرض هستند)
CARD_NUMBER=
CARD_HOLDER=
CARD_BANK=

CHANNEL_USERNAME=
REFERRAL_BONUS_GB=5
ENVEOF
  fi

  if [[ ! -f ".env" ]]; then
    cp .env.example .env
    warn ".env was created."
  fi
}

configure_env_values(){
  local python_bin="$1"
  ensure_env_template

  local bot_token admin_ids web_pass jwt_secret current

  current="$(grep -m1 '^BOT_TOKEN=' .env | cut -d= -f2- || true)"
  if [[ -z "$current" ]]; then
    read -r -p " Telegram bot token: " bot_token
    upsert_env "BOT_TOKEN" "$bot_token"
  fi

  current="$(grep -m1 '^ADMIN_IDS=' .env | cut -d= -f2- || true)"
  if [[ -z "$current" || "$current" == "0" ]]; then
    read -r -p " Admin numeric ID (from @userinfobot): " admin_ids
    upsert_env "ADMIN_IDS" "$admin_ids"
  fi

  current="$(grep -m1 '^WEB_ADMIN_PASSWORD=' .env | cut -d= -f2- || true)"
  if [[ -z "$current" || "$current" == "ChangeMe123!" ]]; then
    read -r -s -p " Web panel password: " web_pass
    echo ""
    upsert_env "WEB_ADMIN_PASSWORD" "$web_pass"
  fi

  current="$(grep -m1 '^JWT_SECRET=' .env | cut -d= -f2- || true)"
  if [[ -z "$current" || "$current" == "please_change_this_secret_key_in_production" ]]; then
    jwt_secret="$(${python_bin} -c "import secrets; print(secrets.token_urlsafe(48))")"
    upsert_env "JWT_SECRET" "$jwt_secret"
    ok "JWT secret generated"
  fi

  ok ".env configuration checked"
}

install_atlas_command(){
  local target="/usr/local/bin/atlas"
  local tmpf atlas_dir
  tmpf="$(mktemp)"
  atlas_dir="$(pwd)"
  cat > "$tmpf" <<'EOF2'
#!/usr/bin/env bash
set -euo pipefail
ATLAS_DIR="__ATLAS_DIR__"
if [[ -f "${ATLAS_DIR}/atlas_menu.sh" ]]; then
  exec bash "${ATLAS_DIR}/atlas_menu.sh" "$@"
fi
echo "atlas_menu.sh not found in ${ATLAS_DIR}" >&2
exit 1
EOF2
  sed -i "s|__ATLAS_DIR__|${atlas_dir}|g" "$tmpf"

  if [[ "$(id -u)" -eq 0 ]]; then
    mv "$tmpf" "$target"
    chmod +x "$target"
  elif command -v sudo >/dev/null 2>&1; then
    sudo mv "$tmpf" "$target"
    sudo chmod +x "$target"
  else
    rm -f "$tmpf"
    err "Could not install $target (need root/sudo)."
    return 1
  fi
  ok "Command installed: atlas"
}

# ---- python/pip ----
if ! command -v python3 >/dev/null 2>&1; then
  info "Installing Python3..."
  apt_run update -q
  apt_run install -y python3 python3-venv python3-pip curl -q
fi

if ! python3 -m pip --version >/dev/null 2>&1; then
  info "Installing pip for python3..."
  if command -v apt-get >/dev/null 2>&1; then
    apt_run update -q
    apt_run install -y python3-pip -q
  else
    python3 -m ensurepip --upgrade || true
  fi
fi

ok "Python $(python3 --version | awk '{print $2}')"

if [[ ! -d ".venv" ]]; then
  create_venv
fi

PYTHON_BIN="$(pwd)/.venv/bin/python"
PIP_BIN="$(pwd)/.venv/bin/pip"

if [[ "$CONFIGURE_ONLY" -eq 1 ]]; then
  info "Configure-only mode"
  configure_env_values "$PYTHON_BIN"
  info "Installing command: atlas"
  install_atlas_command || true
  ok "Configuration completed"
  exit 0
fi

info "Upgrading pip inside venv..."
"$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel -q

info "Installing Python packages..."
"$PIP_BIN" install -r requirements.txt -q
ok "Packages installed"

configure_env_values "$PYTHON_BIN"

WEB_PORT="$(grep -m1 '^WEB_PORT=' .env | cut -d= -f2 | tr -d '\r' || true)"
WEB_SECRET="$(grep -m1 '^WEB_SECRET_PATH=' .env | cut -d= -f2 | tr -d '\r' || true)"
WEB_PORT="${WEB_PORT:-8000}"
WEB_SECRET="${WEB_SECRET:-AtlasPanel2024}"
SERVER_IP="$(curl -s --max-time 3 ifconfig.me 2>/dev/null || echo "YOUR_SERVER_IP")"

info "Installing & starting systemd service (atlas-bot)..."
run_as_root ./setup_service.sh
ok "Service installed + started"

info "Installing command: atlas"
install_atlas_command || true

echo ""
ok "Installation completed!"
echo ""
echo -e "${GREEN}══════════════════════════════════════${NC}"
echo -e " Web panel: ${YELLOW}http://${SERVER_IP}:${WEB_PORT}/${WEB_SECRET}/${NC}"
echo -e " Service status: ${YELLOW}systemctl status atlas-bot${NC}"
echo -e " Live logs: ${YELLOW}journalctl -u atlas-bot -f${NC}"
echo -e " Uninstall: ${YELLOW}bash uninstall.sh${NC}"
echo -e " Manager: ${YELLOW}atlas${NC}"
echo -e "${GREEN}══════════════════════════════════════${NC}\n"
