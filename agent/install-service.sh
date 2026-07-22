#!/usr/bin/env bash
#
# Install (or reload) the collector agent as a launchd LaunchAgent, with the
# plist paths filled in automatically from this script's location. Run it from
# anywhere:  ./install-service.sh
#
# This avoids hand-editing the plist (a common source of a broken service).
set -euo pipefail

AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.user.ollamahostmonitor"
TEMPLATE="$AGENT_DIR/$LABEL.plist"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
PY="$AGENT_DIR/.venv/bin/python3"
DOMAIN="gui/$(id -u)"

[ -f "$TEMPLATE" ] || { echo "error: template not found: $TEMPLATE" >&2; exit 1; }
if [ ! -x "$PY" ]; then
  echo "error: venv python not found at $PY" >&2
  echo "       create it first:  cd \"$AGENT_DIR\" && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi
if [ ! -f "$AGENT_DIR/config.toml" ]; then
  echo "warning: $AGENT_DIR/config.toml not found — copy config.example.toml and set your broker" >&2
fi

mkdir -p "$HOME/Library/LaunchAgents"

# Replace the placeholder agent path in the template with this real agent dir.
sed "s#/Users/YOU/MMM-OllamaHostMonitor/agent#$AGENT_DIR#g" "$TEMPLATE" > "$DEST"
plutil -lint "$DEST" >/dev/null
if grep -q '/Users/YOU/' "$DEST"; then
  echo "error: unresolved placeholders remain in $DEST" >&2
  exit 1
fi

# (Re)load the service.
launchctl bootout "$DOMAIN" "$DEST" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$DEST"
launchctl kickstart -p "$DOMAIN/$LABEL" || true
sleep 2

echo "Installed and loaded $LABEL"
launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E 'state = |pid = ' | head -n 2 || true
echo "Logs: /tmp/ollama-host-monitor.{out,err}.log"
echo "Verify data:  mosquitto_sub -h <broker> -t 'ollama-host/metrics/#' -v"
