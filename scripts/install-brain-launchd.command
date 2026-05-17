#!/usr/bin/env bash
# Double-click this file to install NCL Brain as a startup service.
# It will auto-start on every Mac login and restart if it crashes.

set -euo pipefail

LABEL="com.resonanceenergy.ncl-brain"
NCL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_SRC="$NCL_DIR/com.resonanceenergy.ncl-brain.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$NCL_DIR/logs"

echo "=== NCL Brain LaunchAgent Installer ==="
echo ""
echo "  Working dir:  $NCL_DIR"
echo "  Logs:         $LOG_DIR/"
echo ""

# Create logs directory
mkdir -p "$LOG_DIR"

# Ensure launch script is executable
chmod +x "$NCL_DIR/scripts/launch-brain.sh"

# Unload existing if already installed
if launchctl print "gui/$(id -u)/$LABEL" &>/dev/null; then
    echo "[*] Unloading existing $LABEL..."
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    sleep 1
fi

# Replace __HOME__ placeholder and install plist
echo "[*] Installing plist to ~/Library/LaunchAgents/..."
mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__HOME__|$HOME|g" "$PLIST_SRC" > "$PLIST_DST"

# Load the agent (starts immediately due to RunAtLoad)
echo "[*] Loading $LABEL..."
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"

# Verify
sleep 2
if launchctl print "gui/$(id -u)/$LABEL" &>/dev/null; then
    echo ""
    echo "=== SUCCESS — Brain is live on port 8800 ==="
    echo "  Auto-starts on login. KeepAlive restarts on crash."
    echo ""
else
    echo ""
    echo "=== Check logs: tail -f $LOG_DIR/ncl-brain-stderr.log ==="
    echo ""
fi

echo "Press any key to close..."
read -n 1
