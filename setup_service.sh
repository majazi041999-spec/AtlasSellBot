#!/usr/bin/env bash
set -euo pipefail

NAME="atlas-bot"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Please run as root: sudo bash setup_service.sh"
  exit 1
fi

PYTHON_BIN="/usr/bin/python3"
if [[ -x "${DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${DIR}/.venv/bin/python"
fi

cat > "/etc/systemd/system/${NAME}.service" <<EOF
[Unit]
Description=Atlas Account Bot (Bot + Web Panel)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${DIR}
ExecStart=${PYTHON_BIN} ${DIR}/main.py
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

# اگر خواستی خروجی لاگ‌ها بیشتر بشه:
# StandardOutput=journal
# StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "${NAME}"
systemctl --no-pager --full status "${NAME}" || true
echo "OK: service enabled + started -> ${NAME}"
