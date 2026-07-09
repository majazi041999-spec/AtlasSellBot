#!/usr/bin/env bash
set -euo pipefail

SERVICE="${SERVICE:-atlas-bot}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info(){ echo -e "${BLUE}ℹ${NC} $1"; }
ok(){ echo -e "${GREEN}✓${NC} $1"; }
warn(){ echo -e "${YELLOW}⚠${NC} $1"; }
err(){ echo -e "${RED}✗${NC} $1"; }

run_root_cmd(){
  if [[ "$(id -u)" -eq 0 ]]; then
    bash -lc "$*"
  elif command -v sudo >/dev/null 2>&1; then
    sudo bash -lc "$*"
  else
    err "This action needs root (sudo not found)."
    return 1
  fi
}

pause(){ read -r -p "\nPress Enter to continue..." _; }

# Read a KEY=value from the project's .env, stripping surrounding quotes/CR.
env_get(){
  local key="$1" file="$DIR/.env" val=""
  [[ -f "$file" ]] || return 0
  val="$(sed -n "s/^${key}=//p" "$file" | tail -n1)"
  val="${val%$'\r'}"
  val="${val%\"}"; val="${val#\"}"
  val="${val%\'}"; val="${val#\'}"
  printf '%s' "$val"
}

# Best-effort public IPv4 detection.
public_ipv4(){
  local ip=""
  ip="$(curl -s4 --max-time 6 https://api.ipify.org 2>/dev/null || true)"
  [[ -z "$ip" ]] && ip="$(curl -s4 --max-time 6 https://ifconfig.me 2>/dev/null || true)"
  [[ -z "$ip" ]] && ip="$(curl -s4 --max-time 6 https://ipv4.icanhazip.com 2>/dev/null | tr -d '\r\n' || true)"
  [[ -z "$ip" ]] && ip="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' | head -n1 || true)"
  printf '%s' "$ip"
}

show_panel_link(){
  local secret port ip
  secret="$(env_get WEB_SECRET_PATH)"; secret="${secret:-AtlasPanel2024}"
  secret="${secret#/}"; secret="${secret%/}"
  port="$(env_get WEB_PORT)"; port="${port:-8000}"
  ip="$(public_ipv4)"; ip="${ip:-<SERVER-IP>}"
  echo ""
  echo -e "${BLUE}────────────── Panel links (IPv4) ──────────────${NC}"
  ok "Main panel (React):"
  echo -e "   ${GREEN}http://${ip}:${port}/${secret}/${NC}"
  echo ""
  info "Legacy panel (classic fallback):"
  echo -e "   ${YELLOW}http://${ip}:${port}/${secret}/dashboard${NC}"
  echo -e "${BLUE}────────────────────────────────────────────────${NC}"
}

run_action(){
  local action="${1:-}"
  case "$action" in
    status)
      run_root_cmd "systemctl --no-pager --full status '$SERVICE'"
      ;;
    start)
      run_root_cmd "systemctl start '$SERVICE'"
      ok "Service started"
      ;;
    stop)
      run_root_cmd "systemctl stop '$SERVICE'"
      ok "Service stopped"
      ;;
    restart)
      run_root_cmd "systemctl restart '$SERVICE'"
      ok "Service restarted"
      ;;
    logs)
      run_root_cmd "journalctl -u '$SERVICE' -f"
      ;;
    update)
      (cd "$DIR" && bash update.sh pull)
      ;;
    update-hard)
      warn "Hard update selected: local changes will be discarded."
      (cd "$DIR" && bash update.sh hard)
      ;;
    reinstall-service)
      run_root_cmd "cd '$DIR' && bash setup_service.sh"
      ;;
    install)
      (cd "$DIR" && bash install.sh)
      ;;
    configure)
      (cd "$DIR" && bash install.sh --configure-only)
      ;;
    uninstall)
      run_root_cmd "cd '$DIR' && bash uninstall.sh"
      ;;
    uninstall-full)
      run_root_cmd "cd '$DIR' && bash uninstall.sh --purge-self --force"
      ;;
    panel-link|panel|link)
      show_panel_link
      ;;
    help|-h|--help)
      cat <<USAGE
Usage: atlas [command]
Commands:
  status            Show systemd status
  start             Start service
  stop              Stop service
  restart           Restart service
  logs              Follow service logs
  update            Safe update (pull mode)
  update-hard       Force update (hard reset)
  panel-link        Show admin panel links (new v2 + classic) with IPv4
  reinstall-service Recreate systemd service file
  install           Run installer
  configure         Configure .env (token/admin/password)
  uninstall         Run uninstall script
  uninstall-full    Full reset uninstall (remove project dir too)
  menu              Open interactive menu (default)
USAGE
      ;;
    menu|"")
      return 99
      ;;
    *)
      err "Unknown command: $action"
      return 2
      ;;
  esac
}

show_menu(){
  clear || true
  echo -e "${BLUE}════════════════════════════════════════════════${NC}"
  echo -e "${BLUE}             Atlas Bot Manager${NC}"
  echo -e "${BLUE}════════════════════════════════════════════════${NC}"
  echo -e "Service: ${YELLOW}${SERVICE}${NC}"
  echo -e "Path:    ${YELLOW}${DIR}${NC}"
  echo ""
  echo " 1) Service status"
  echo " 2) Start service"
  echo " 3) Stop service"
  echo " 4) Restart service"
  echo " 5) Live logs"
  echo " 6) Safe update (pull)"
  echo " 7) Force update (hard)"
  echo " 8) Reinstall systemd service"
  echo " 9) Run installer (install.sh)"
  echo "10) Configure .env (token/admin/password)"
  echo "11) Uninstall"
  echo "12) Full reset uninstall (remove project dir)"
  echo "13) Show panel links (new v2 + classic)"
  echo " 0) Exit"
  echo ""
}

if [[ "${1:-}" != "" ]]; then
  run_action "$1"
  exit $?
fi

while true; do
  show_menu
  read -r -p "Select an option: " choice
  case "$choice" in
    1) run_action status; pause ;;
    2) run_action start; pause ;;
    3) run_action stop; pause ;;
    4) run_action restart; pause ;;
    5) run_action logs ;;
    6) run_action update; pause ;;
    7) run_action update-hard; pause ;;
    8) run_action reinstall-service; pause ;;
    9) run_action install; pause ;;
    10) run_action configure; pause ;;
    11) run_action uninstall; pause ;;
    12) run_action uninstall-full; exit 0 ;;
    13) show_panel_link; pause ;;
    0) ok "Bye"; exit 0 ;;
    *) warn "Invalid option"; pause ;;
  esac
done
