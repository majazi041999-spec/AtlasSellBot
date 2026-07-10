#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Atlas — MTProto (Telegram) proxy installer/manager.
#
# Uses `mtg` v1.0.11 (9seconds/mtg): a single static Go binary that supports
# fake-TLS (secrets starting with `ee`) AND a promoted-channel ad-tag (sponsor).
# Everything here is idempotent and loudly logged so a failure is obvious.
#
# Subcommands:
#   install     download mtg, write systemd unit, open firewall, start, verify
#   apply       re-write unit (after port/tag change) and restart
#   status      print service state + listening + live connection count
#   test        verify service active + port listening + local TCP connect
#   uninstall   stop + remove service (keeps the binary)
#
# Config comes from env vars: MTPROXY_PORT, MTPROXY_SECRET, MTPROXY_TAG.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

MTG_VER="1.0.11"
MTG_BIN="/usr/local/bin/mtg"
UNIT="/etc/systemd/system/mtproxy.service"
CMD="${1:-status}"

PORT="${MTPROXY_PORT:-443}"
SECRET="${MTPROXY_SECRET:-}"
TAG="${MTPROXY_TAG:-}"

say(){ echo -e "$1"; }
die(){ echo -e "❌ $1" >&2; exit 1; }

arch_slug(){
  # Must match 9seconds/mtg release asset names (…-linux-<slug>.tar.gz).
  case "$(uname -m)" in
    x86_64|amd64) echo "amd64" ;;
    aarch64|arm64) echo "arm64" ;;
    armv7l|armv7) echo "armv7" ;;
    armv6l|armv6) echo "armv6" ;;
    i386|i686) echo "386" ;;
    *) echo "amd64" ;;
  esac
}

install_mtg(){
  if [[ -x "$MTG_BIN" ]] && "$MTG_BIN" --version 2>/dev/null | grep -q "$MTG_VER"; then
    say "✓ mtg $MTG_VER از قبل نصب است."
    return 0
  fi
  local arch; arch="$(arch_slug)"
  local name="mtg-${MTG_VER}-linux-${arch}"
  local url="https://github.com/9seconds/mtg/releases/download/v${MTG_VER}/${name}.tar.gz"
  local tmp; tmp="$(mktemp -d)"
  say "⬇️  دانلود mtg ${MTG_VER} (${arch}) ..."
  if ! curl -fsSL "$url" -o "$tmp/mtg.tgz"; then
    die "دانلود mtg ناموفق بود: $url"
  fi
  tar -xzf "$tmp/mtg.tgz" -C "$tmp" || die "استخراج آرشیو mtg ناموفق بود."
  local bin; bin="$(find "$tmp" -type f -name mtg | head -n1)"
  [[ -n "$bin" ]] || die "فایل اجرایی mtg در آرشیو پیدا نشد."
  install -m 0755 "$bin" "$MTG_BIN" || die "نصب باینری mtg ناموفق بود."
  rm -rf "$tmp"
  say "✓ mtg نصب شد: $("$MTG_BIN" --version 2>/dev/null | head -n1)"
}

write_unit(){
  [[ -n "$SECRET" ]] || die "SECRET خالی است."
  [[ "$PORT" =~ ^[0-9]+$ ]] || die "پورت نامعتبر: $PORT"
  # mtg v1: `run SECRET [ADTAG] -b BIND`. Tag is optional (sponsor channel).
  local args="run ${SECRET}"
  if [[ -n "$TAG" ]]; then args="${args} ${TAG}"; fi
  args="${args} --bind 0.0.0.0:${PORT}"
  say "📝 نوشتن سرویس systemd (پورت ${PORT}$( [[ -n "$TAG" ]] && echo '، با اسپانسر' ))"
  cat > "$UNIT" <<EOF
[Unit]
Description=Atlas MTProto Proxy (mtg)
After=network.target

[Service]
Type=simple
ExecStart=${MTG_BIN} ${args}
Restart=always
RestartSec=3
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
}

open_fw(){
  say "🔓 باز کردن پورت ${PORT} در فایروال (در صورت وجود)"
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow "${PORT}/tcp" >/dev/null 2>&1 || true
    say "  • ufw: allow ${PORT}/tcp"
  fi
  if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd --permanent --add-port="${PORT}/tcp" >/dev/null 2>&1 || true
    firewall-cmd --reload >/dev/null 2>&1 || true
    say "  • firewalld: add-port ${PORT}/tcp"
  fi
  # iptables (best effort, only if the chain doesn't already allow it)
  if command -v iptables >/dev/null 2>&1; then
    iptables -C INPUT -p tcp --dport "${PORT}" -j ACCEPT 2>/dev/null || \
      iptables -I INPUT -p tcp --dport "${PORT}" -j ACCEPT 2>/dev/null || true
  fi
}

conn_count(){
  if command -v ss >/dev/null 2>&1; then
    ss -Htn state established "( sport = :${PORT} )" 2>/dev/null | wc -l | tr -d ' '
  else
    echo "0"
  fi
}

do_status(){
  local active listen conns
  active="$(systemctl is-active mtproxy 2>/dev/null || echo inactive)"
  if ss -Hltn 2>/dev/null | grep -q ":${PORT} "; then listen="yes"; else listen="no"; fi
  conns="$(conn_count)"
  echo "STATUS active=${active} listening=${listen} port=${PORT} connections=${conns}"
}

do_test(){
  say "🧪 تست پروکسی روی پورت ${PORT} ..."
  local active listen
  active="$(systemctl is-active mtproxy 2>/dev/null || echo inactive)"
  [[ "$active" == "active" ]] || die "سرویس فعال نیست (systemctl is-active = ${active})."
  say "✓ سرویس فعال است."
  # give it a moment to bind
  for i in 1 2 3 4 5; do
    if ss -Hltn 2>/dev/null | grep -q ":${PORT} "; then break; fi
    sleep 1
  done
  ss -Hltn 2>/dev/null | grep -q ":${PORT} " || die "پورت ${PORT} در حال گوش‌دادن نیست."
  say "✓ پورت ${PORT} در حال گوش‌دادن است."
  # local TCP connect check
  if command -v timeout >/dev/null 2>&1; then
    if timeout 4 bash -c "exec 3<>/dev/tcp/127.0.0.1/${PORT}" 2>/dev/null; then
      say "✓ اتصال TCP محلی موفق بود."
    else
      die "اتصال TCP محلی به پورت ${PORT} ناموفق بود."
    fi
  fi
  say "✅ تست با موفقیت انجام شد. اتصال‌های فعلی: $(conn_count)"
}

case "$CMD" in
  install)
    [[ "$(id -u)" -eq 0 ]] || die "این عملیات به دسترسی root نیاز دارد."
    install_mtg
    write_unit
    open_fw
    systemctl enable mtproxy >/dev/null 2>&1 || true
    systemctl restart mtproxy
    sleep 2
    do_test
    say ""
    do_status
    ;;
  apply)
    [[ "$(id -u)" -eq 0 ]] || die "این عملیات به دسترسی root نیاز دارد."
    write_unit
    open_fw
    systemctl restart mtproxy
    sleep 2
    do_status
    ;;
  status) do_status ;;
  test) do_test ;;
  uninstall)
    systemctl stop mtproxy 2>/dev/null || true
    systemctl disable mtproxy 2>/dev/null || true
    rm -f "$UNIT"
    systemctl daemon-reload 2>/dev/null || true
    say "🗑 سرویس mtproxy حذف شد."
    ;;
  *) die "دستور نامعتبر: $CMD" ;;
esac
