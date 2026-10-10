#!/usr/bin/env bash
# Installs the launchd agent for the current user. Usage: deploy/macos/install.sh [uninstall]
set -euo pipefail
PROJECT="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL="com.mia-san-miete.run"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

if [ "${1:-}" = "uninstall" ]; then
  launchctl bootout "$DOMAIN" "$DEST" 2>/dev/null || true
  rm -f "$DEST"
  echo "removed $LABEL"
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs/mia" "$HOME/.config/mia"
sed -e "s|__PROJECT__|$PROJECT|g" -e "s|__HOME__|$HOME|g" \
  "$PROJECT/deploy/macos/$LABEL.plist.template" > "$DEST"
launchctl bootout "$DOMAIN" "$DEST" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$DEST"
echo "installed $LABEL (every 5 min while the Mac is awake); log: ~/Library/Logs/mia/run.log"
