#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Atlas — MTProto (Telegram) proxy installer/manager.
#
# Uses alexbers/mtprotoproxy: fake-TLS (`ee` secrets) AND the promoted-channel
# ad tag, in one implementation.
#
# WHY NOT mtg, WHICH THIS USED TO INSTALL. Two dead ends, found the hard way:
#
#   • mtg v1 hard-checks that a client's TLS ClientHello record is exactly 512
#     bytes. That was true of Telegram clients in 2022. Today they send about
#     1700-1800 (the post-quantum key share is large), so v1 rejects EVERY real
#     client with "failed first bytes of tls handshake" — while the server looks
#     perfectly healthy: service active, port listening, Telegram reachable. Our
#     Turkey proxy turned away 3891 connections over ten days and carried not
#     one. Nothing short of a packet capture explains it.
#   • mtg v2 fixes that and drops ad-tag support entirely, which is the one
#     feature the proxy exists for here.
#
# The ad tag needs middle-proxy mode, which mtprotoproxy enables on its own once
# AD_TAG is exactly 16 bytes. Confirm it is really on by checking that outbound
# connections go to Telegram on port 8888 rather than 443.
#
# THE MASK HOST IS NOT DECORATION. It is what an active prober is relayed to
# when it connects without the secret, and the certificate the proxy imitates is
# read from it. It should be a name that resolves to THIS server and serves real
# TLS 1.3 with a valid certificate for that name, so the SNI a client presents,
# the certificate it is shown, and the address the packet went to all agree.
# TLS 1.3 specifically: on 1.2 mtprotoproxy never records the real certificate
# length and its own ServerHello stops matching the host it is imitating.
#
# Subcommands:
#   install     fetch the proxy, write config + unit, open firewall, start, verify
#   apply       rewrite config + unit (after a port/secret/tag change) and restart
#   status      print service state + listening + live connection count
#   test        verify service active + port listening + local TCP connect
#   logs        recent service log
#   uninstall   stop + remove service (keeps the checkout)
#
# Config comes from env: MTPROXY_PORT, MTPROXY_SECRET, MTPROXY_TAG.
# MTPROXY_SECRET may be the full `ee<key><domain-hex>` form — the base key and
# the mask domain are split back out of it, so callers can keep passing the same
# string the panel shows the customer.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO="https://github.com/alexbers/mtprotoproxy.git"
APP_DIR="/opt/mtprotoproxy"
UNIT="/etc/systemd/system/mtproxy.service"
CMD="${1:-status}"

PORT="${MTPROXY_PORT:-443}"
SECRET="${MTPROXY_SECRET:-}"
TAG="${MTPROXY_TAG:-}"
MASK_DOMAIN="${MTPROXY_DOMAIN:-}"

say(){ echo -e "$1"; }
die(){ echo -e "❌ $1" >&2; exit 1; }

# ── split `ee<32 hex key><domain in hex>` into its two halves ────────────────
parse_secret(){
  local s="${SECRET,,}"
  [[ -n "$s" ]] || die "SECRET خالی است."
  if [[ "$s" == ee* && ${#s} -gt 34 ]]; then
    BASE_SECRET="${s:2:32}"
    local dom_hex="${s:34}"
    local decoded
    decoded="$(printf '%s' "$dom_hex" | xxd -r -p 2>/dev/null || true)"
    [[ -n "$decoded" ]] || die "بخش دامنه در SECRET قابل خواندن نبود."
    MASK_DOMAIN="${MASK_DOMAIN:-$decoded}"
  else
    BASE_SECRET="${s:0:32}"
    MASK_DOMAIN="${MASK_DOMAIN:-www.google.com}"
  fi
  [[ "$BASE_SECRET" =~ ^[0-9a-f]{32}$ ]] || die "کلید ۱۶ بایتی نامعتبر: $BASE_SECRET"
}

install_app(){
  command -v git >/dev/null 2>&1 || { DEBIAN_FRONTEND=noninteractive apt-get update -qq >/dev/null 2>&1; DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git >/dev/null 2>&1; }
  command -v python3 >/dev/null 2>&1 || die "python3 نصب نیست."
  mkdir -p "$APP_DIR"
  if [[ -d "$APP_DIR/.git" ]]; then
    say "⬇️  به‌روزرسانی mtprotoproxy ..."
    git -C "$APP_DIR" fetch -q origin && git -C "$APP_DIR" reset -q --hard origin/master
  else
    say "⬇️  دریافت mtprotoproxy ..."
    git clone -q "$REPO" "$APP_DIR" || die "دریافت mtprotoproxy ناموفق بود."
  fi
  [[ -f "$APP_DIR/mtprotoproxy.py" ]] || die "فایل mtprotoproxy.py پیدا نشد."
  say "✓ نسخه: $(git -C "$APP_DIR" log --oneline -1)"
}

write_config(){
  parse_secret
  [[ "$PORT" =~ ^[0-9]+$ ]] || die "پورت نامعتبر: $PORT"
  local ad_line="# AD_TAG not set — the sponsored channel is off."
  if [[ -n "$TAG" ]]; then
    if [[ "${TAG,,}" =~ ^[0-9a-f]{32}$ ]]; then
      ad_line="AD_TAG = \"${TAG,,}\""
    else
      say "⚠️  تگ اسپانسر باید ۳۲ کاراکتر hex باشد؛ نادیده گرفته شد: $TAG"
    fi
  fi
  say "📝 نوشتن config (پورت ${PORT}، ماسک ${MASK_DOMAIN}$( [[ -n "$TAG" ]] && echo '، با اسپانسر' ))"
  cat > "$APP_DIR/config.py" <<PYCONF
# Written by setup_mtproxy.sh — edit the panel, not this file.
PORT = ${PORT}

USERS = {
    "atlas": "${BASE_SECRET}",
}

# Fake-TLS only. classic/secure are trivially fingerprinted and have been dead in
# Iran for years; leaving them on only gives a client a way to fall back into
# something that cannot work.
MODES = {
    "classic": False,
    "secure": False,
    "tls": True,
}

TLS_DOMAIN = "${MASK_DOMAIN}"

${ad_line}
PYCONF
  python3 -c "import ast,io,sys; ast.parse(io.open('$APP_DIR/config.py').read())" \
    || die "config.py نامعتبر تولید شد."
}

write_unit(){
  cat > "$UNIT" <<EOF
[Unit]
Description=Atlas MTProto Proxy (mtprotoproxy)
After=network.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
ExecStart=/usr/bin/python3 ${APP_DIR}/mtprotoproxy.py
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

listen_ports(){
  # Ports the proxy process actually holds — catches a wrong bind.
  if command -v ss >/dev/null 2>&1; then
    ss -Hltnp 2>/dev/null | grep -i "mtprotoproxy\|python3" | grep -oE ':[0-9]+ ' | tr -d ': ' | sort -u | paste -sd, - 2>/dev/null
  fi
}

# Whether the ad tag is really in force: middle-proxy mode talks to Telegram on
# 8888, direct mode on 443. A tag configured but no 8888 means no sponsorship,
# and nothing else reports that.
middle_proxy_conns(){
  if command -v ss >/dev/null 2>&1; then
    ss -Htn state established 2>/dev/null | awk '{print $4}' | grep -c ':8888$' || echo 0
  else
    echo 0
  fi
}

do_status(){
  local active listen conns actual
  active="$(systemctl is-active mtproxy 2>/dev/null || echo inactive)"
  if ss -Hltn 2>/dev/null | grep -q ":${PORT} "; then listen="yes"; else listen="no"; fi
  conns="$(conn_count)"
  actual="$(listen_ports)"
  echo "STATUS active=${active} listening=${listen} port=${PORT} connections=${conns} actual_ports=${actual:-none}"
  echo "MIDDLE_PROXY connections=$(middle_proxy_conns)"
}

do_test(){
  say "🧪 تست پروکسی روی پورت ${PORT} ..."
  local active
  active="$(systemctl is-active mtproxy 2>/dev/null || echo inactive)"
  [[ "$active" == "active" ]] || die "سرویس فعال نیست (systemctl is-active = ${active})."
  say "✓ سرویس فعال است."
  for _ in 1 2 3 4 5; do
    if ss -Hltn 2>/dev/null | grep -q ":${PORT} "; then break; fi
    sleep 1
  done
  ss -Hltn 2>/dev/null | grep -q ":${PORT} " || die "پورت ${PORT} در حال گوش‌دادن نیست."
  say "✓ پورت ${PORT} در حال گوش‌دادن است."
  if command -v timeout >/dev/null 2>&1; then
    timeout 4 bash -c "exec 3<>/dev/tcp/127.0.0.1/${PORT}" 2>/dev/null \
      && say "✓ اتصال TCP محلی موفق بود." \
      || die "اتصال TCP محلی به پورت ${PORT} ناموفق بود."
  fi
  if [[ -n "$TAG" ]]; then
    local mp; mp="$(middle_proxy_conns)"
    if [[ "$mp" -gt 0 ]]; then
      say "✓ حالت middle-proxy فعال است (${mp} اتصال روی 8888) — تگ اسپانسر ارسال می‌شود."
    else
      say "⚠️  هنوز اتصالی روی پورت 8888 نیست. تا وقتی کاربری وصل نشود طبیعی است؛"
      say "   اگر با وجود کاربر فعال باز هم صفر ماند، تگ اسپانسر اعمال نمی‌شود."
    fi
  fi
  say "✅ تست انجام شد. اتصال‌های فعلی: $(conn_count)"
}

case "$CMD" in
  install)
    [[ "$(id -u)" -eq 0 ]] || die "این عملیات به دسترسی root نیاز دارد."
    install_app
    write_config
    write_unit
    open_fw
    systemctl enable mtproxy >/dev/null 2>&1 || true
    systemctl restart mtproxy
    sleep 3
    do_test
    say ""
    do_status
    ;;
  apply)
    [[ "$(id -u)" -eq 0 ]] || die "این عملیات به دسترسی root نیاز دارد."
    write_config
    write_unit
    open_fw
    systemctl restart mtproxy
    sleep 3
    do_status
    ;;
  status) do_status ;;
  test)   do_test ;;
  restart)
    systemctl restart mtproxy
    sleep 3
    do_status
    ;;
  logs)
    if command -v journalctl >/dev/null 2>&1; then
      journalctl -u mtproxy -n 80 --no-pager 2>/dev/null || echo "لاگی در دسترس نیست."
    else
      echo "journalctl در دسترس نیست."
    fi
    ;;
  uninstall)
    systemctl stop mtproxy 2>/dev/null || true
    systemctl disable mtproxy 2>/dev/null || true
    rm -f "$UNIT"
    systemctl daemon-reload 2>/dev/null || true
    say "✓ سرویس حذف شد (فایل‌های $APP_DIR دست‌نخورده ماند)."
    ;;
  *)
    die "دستور ناشناخته: $CMD (install|apply|status|test|restart|logs|uninstall)"
    ;;
esac
