#!/bin/bash
DIR=$(pwd)
NAME="atlas-bot"
cat > /etc/systemd/system/${NAME}.service <<EOF
[Unit]
Description=Atlas Account VPN Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${DIR}
ExecStart=/usr/bin/python3 main.py
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
systemctl start ${NAME}
echo "✅ سرویس ${NAME} راه‌اندازی شد!"
echo ""
echo "systemctl status ${NAME}    # وضعیت"
echo "systemctl restart ${NAME}   # ریستارت"
echo "journalctl -u ${NAME} -f    # لاگ زنده"
