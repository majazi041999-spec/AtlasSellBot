#!/usr/bin/env bash
set -euo pipefail

# Atlas bootstrap/manager (3x-ui style one-liner)
# Example:
#   bash <(curl -Ls https://raw.githubusercontent.com/majazi041999-spec/AtlasSellBot/main/bootstrap.sh)
#   bash <(curl -Ls https://raw.githubusercontent.com/majazi041999-spec/AtlasSellBot/main/bootstrap.sh) update

REPO_URL="${REPO_URL:-https://github.com/majazi041999-spec/AtlasSellBot.git}"
BRANCH="${BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-/opt/AtlasSellBot}"
SERVICE="${SERVICE:-atlas-bot}"
CMD="${1:-install}"

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info(){ echo -e "${BLUE}ℹ${NC} $1"; }
ok(){ echo -e "${GREEN}✓${NC} $1"; }
warn(){ echo -e "${YELLOW}⚠${NC} $1"; }
err(){ echo -e "${RED}✗${NC} $1"; }

need_cmd(){ command -v "$1" >/dev/null 2>&1 || { err "'$1' is required"; exit 1; }; }

run_root(){
  if [[ "$(id -u)" -eq 0 ]]; then
    bash -c "$*"
  elif command -v sudo >/dev/null 2>&1; then
    sudo bash -c "$*"
  else
    err "This action needs root privileges (sudo not found)."
    exit 1
  fi
}

install_deps_if_missing(){
  if command -v git >/dev/null 2>&1 && command -v curl >/dev/null 2>&1; then
    return 0
  fi

  if command -v apt-get >/dev/null 2>&1; then
    info "Installing required packages (git, curl)..."
    run_root "apt-get update -q"
    run_root "apt-get install -y git curl -q"
    return 0
  fi

  err "git/curl are missing and automatic install is only implemented for apt-based systems."
  exit 1
}

ensure_repo(){
  install_deps_if_missing
  need_cmd git

  if [[ ! -d "$INSTALL_DIR/.git" ]]; then
    info "Cloning Atlas repository into $INSTALL_DIR ..."
    run_root "mkdir -p \"$(dirname "$INSTALL_DIR")\""
    run_root "git clone --branch \"$BRANCH\" \"$REPO_URL\" \"$INSTALL_DIR\""
  else
    info "Repository already exists: $INSTALL_DIR"
  fi

  run_root "cd \"$INSTALL_DIR\" && git fetch origin \"$BRANCH\" --prune"
}

write_manager_command(){
  local manager="/usr/local/bin/atlas"
  info "Installing helper command: $manager"
  run_root "cat > '$manager' <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
INSTALL_DIR="${INSTALL_DIR:-/opt/AtlasSellBot}"
if [[ -f "${INSTALL_DIR}/atlas_menu.sh" ]]; then
  exec bash "${INSTALL_DIR}/atlas_menu.sh" "\$@"
fi
exec bash <(curl -Ls "https://raw.githubusercontent.com/majazi041999-spec/AtlasSellBot/main/bootstrap.sh") "\$@"
EOS
chmod +x '$manager'"
  ok "Command installed: atlas"
}

do_install(){
  ensure_repo
  if [[ ! -f "$INSTALL_DIR/install.sh" ]]; then
    err "install.sh not found in $INSTALL_DIR"
    exit 1
  fi

  info "Running installer..."
  run_root "cd \"$INSTALL_DIR\" && bash install.sh"
  write_manager_command

  ok "Install finished."
  echo ""
  echo "Update later with: atlas update"
  echo "Or: bash <(curl -Ls https://raw.githubusercontent.com/majazi041999-spec/AtlasSellBot/main/bootstrap.sh) update"
}

do_update(){
  ensure_repo
  if [[ ! -f "$INSTALL_DIR/update.sh" ]]; then
    err "update.sh not found in $INSTALL_DIR"
    exit 1
  fi

  info "Updating Atlas ..."
  run_root "cd \"$INSTALL_DIR\" && bash update.sh pull"
  ok "Update finished."
}

do_restart(){
  need_cmd systemctl
  info "Restarting service: $SERVICE"
  run_root "systemctl restart '$SERVICE'"
  ok "Service restarted"
}

do_status(){
  need_cmd systemctl
  run_root "systemctl --no-pager --full status '$SERVICE'"
}

do_uninstall(){
  if [[ ! -d "$INSTALL_DIR" ]]; then
    warn "Install directory not found: $INSTALL_DIR"
    exit 0
  fi
  info "Uninstalling Atlas from $INSTALL_DIR ..."
  run_root "cd \"$INSTALL_DIR\" && bash uninstall.sh --force"
  ok "Uninstalled"
}

case "$CMD" in
  install) do_install ;;
  update) do_update ;;
  restart) do_restart ;;
  status) do_status ;;
  uninstall) do_uninstall ;;
  help|-h|--help)
    cat <<USAGE
Atlas bootstrap commands:
  install    Clone (if needed) and run install.sh (default)
  update     Run update.sh pull
  restart    Restart systemd service ($SERVICE)
  status     Show systemd status
  uninstall  Run uninstall.sh --force

Environment overrides:
  REPO_URL, BRANCH, INSTALL_DIR, SERVICE
USAGE
    ;;
  *)
    err "Unknown command: $CMD"
    exit 2
    ;;
esac
