#!/usr/bin/env bash
# Installs the systemd service and timer. Run with sudo: sudo deploy/pi/install.sh <linux-user>
set -euo pipefail
USER_NAME="${1:?usage: sudo deploy/pi/install.sh <linux-user>}"
PROJECT="$(cd "$(dirname "$0")/../.." && pwd)"
sed -e "s|__USER__|$USER_NAME|g" -e "s|__PROJECT__|$PROJECT|g" \
  "$PROJECT/deploy/pi/mia.service" > /etc/systemd/system/mia.service
cp "$PROJECT/deploy/pi/mia.timer" /etc/systemd/system/mia.timer
systemctl daemon-reload
systemctl enable --now mia.timer
echo "installed; follow logs with: journalctl -u mia.service -f"
