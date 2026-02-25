#!/usr/bin/env bash
set -euo pipefail

# AtlasSellBot - Domain + SSL (Let's Encrypt) + Nginx reverse proxy
# Usage: sudo bash setup_domain_ssl.sh

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash setup_domain_ssl.sh"
  exit 1
fi

if [[ ! -f ".env" ]]; then
  echo "❌ .env not found. Run install.sh first."
  exit 1
fi

read -r -p "Domain (example.com): " DOMAIN
read -r -p "Email for Let's Encrypt: " EMAIL

WEB_PORT="$(grep -m1 '^WEB_PORT=' .env | cut -d= -f2 | tr -d '\r' || true)"
WEB_PORT="${WEB_PORT:-8000}"

apt-get update -y
apt-get install -y nginx certbot python3-certbot-nginx

cat > /etc/nginx/sites-available/atlas-bot.conf <<EOF
server {
  listen 80;
  server_name ${DOMAIN} www.${DOMAIN};

  location / {
    proxy_pass http://127.0.0.1:${WEB_PORT};
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
  }
}
EOF

ln -sf /etc/nginx/sites-available/atlas-bot.conf /etc/nginx/sites-enabled/atlas-bot.conf

nginx -t
systemctl reload nginx

# SSL + redirect
certbot --nginx -d "${DOMAIN}" -d "www.${DOMAIN}" \
  --agree-tos -m "${EMAIL}" --non-interactive --redirect

# enable renewal timer (usually enabled by default on ubuntu/debian)
systemctl enable --now certbot.timer || true

echo ""
echo "✅ DONE: https://${DOMAIN}/"
echo "ℹ️ Note: make sure DNS A-record points to this server and ports 80/443 are open."
