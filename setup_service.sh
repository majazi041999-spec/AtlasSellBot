#!/bin/bash
set -e
DIR=$(pwd)
NAME="atlas-bot"
PYTHON_BIN="/usr/bin/python3"

if [ -x "${DIR}/.venv/bin/python" ]; then
  PYTHON_BIN="${DIR}/.venv/bin/python"
fi

cat > /etc/systemd/system/${NAME}.service <<EOF
[Unit]
Description=Atlas Account VPN Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${DIR}
ExecStart=${PYTHON_BIN} main.py
Restart=always
RestartSec=5
StandardOutput=append:${DIR}/atlas.log
StandardError=append:${DIR}/atlas.log
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ${NAME}
systemctl restart ${NAME}
echo "✅ Service ${NAME} is up and running!"
echo ""
echo "systemctl start ${NAME}     # start"
echo "systemctl stop ${NAME}      # stop"
echo "systemctl status ${NAME}    # status"
echo "systemctl restart ${NAME}   # restart"
echo "journalctl -u ${NAME} -f    # live logs"
