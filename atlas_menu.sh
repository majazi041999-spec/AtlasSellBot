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

pause(){ read -r -p "\nبرای ادامه Enter بزنید..." _; }

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
  reinstall-service Recreate systemd service file
  install           Run installer
  configure         Configure .env (token/admin/password)
  uninstall         Run uninstall script
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
  echo -e "${BLUE}          Atlas Account Bot Manager${NC}"
  echo -e "${BLUE}════════════════════════════════════════════════${NC}"
  echo -e "Service: ${YELLOW}${SERVICE}${NC}"
  echo -e "Path:    ${YELLOW}${DIR}${NC}"
  echo ""
  echo " 1) وضعیت سرویس"
  echo " 2) شروع سرویس"
  echo " 3) توقف سرویس"
  echo " 4) ری‌استارت سرویس"
  echo " 5) لاگ زنده سرویس"
  echo " 6) آپدیت امن (pull)"
  echo " 7) آپدیت اجباری (hard)"
  echo " 8) نصب/بازسازی سرویس systemd"
  echo " 9) اجرای نصب مجدد (install.sh)"
  echo "10) تنظیم .env (توکن/ادمین/پسورد)"
  echo "11) حذف (uninstall.sh)"
  echo " 0) خروج"
  echo ""
}

if [[ "${1:-}" != "" ]]; then
  run_action "$1"
  exit $?
fi

while true; do
  show_menu
  read -r -p "انتخاب شما: " choice
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
    0) ok "Bye"; exit 0 ;;
    *) warn "گزینه نامعتبر"; pause ;;
  esac
done
