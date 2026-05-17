#!/usr/bin/env bash
# install-brain-launchd.sh — Install NCL Brain as a macOS LaunchAgent
# Runs automatically on login, restarts if it crashes (KeepAlive=true)
#
# Usage:
#   bash ~/dev/NCL/scripts/install-brain-launchd.sh
#
# To uninstall:
#   launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.resonanceenergy.ncl-brain.plist
#   rm ~/Library/LaunchAgents/com.resonanceenergy.ncl-brain.plist

set -euo pipefail

LABEL="com.resonanceenergy.ncl-brain"
NCL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_SRC="$NCL_DIR/com.resonanceenergy.ncl-brain.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$NCL_DIR/logs"

echo "=== NCL Brain LaunchAgent Installer ==="
echo ""
echo "  Source plist: $PLIST_SRC"
echo "  Install to:   $PLIST_DST"
echo "  Working dir:  $NCL_DIR"
echo "  Logs:         $LOG_DIR/"
echo ""

# 1. Create logs directory
mkdir -p "$LOG_DIR"

# 2. Ensure launch script is executable
chmod +x "$NCL_DIR/scripts/launch-brain.sh"

# 3. Unload existing if already installed
if launchctl print "gui/$(id -u)/$LABEL" &>/dev/null; then
    echo "[*] Unloading existing $LABEL..."
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    sleep 1
fi

# 4. Replace __HOME__ placeholder and install plist
echo "[*] Installing plist to ~/Library/LaunchAgents/..."
mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__HOME__|$HOME|g" "$PLIST_SRC" > "$PLIST_DST"

# 5. Load the agent (starts immediately due to RunAtLoad)
echo "[*] Loading $LABEL..."
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"

# 6. Verify it's running
sleep 2
if launchctl print "gui/$(id -u)/$LABEL" &>/dev/null; then
    echo ""
    echo "=== SUCCESS ==="
    echo "  NCL Brain is now running on port 8800"
    echo "  It will auto-start on every login"
    echo "  KeepAlive=true means it restarts if it crashes"
    echo ""
    echo "  Check status:  launchctl print gui/\$(id -u)/$LABEL"
    echo "  View logs:     tail -f $LOG_DIR/ncl-brain-stdout.log"
    echo "  Stop:          launchctl kickstart -k gui/\$(id -u)/$LABEL"
    echo "  Uninstall:     launchctl bootout gui/\$(id -u)/$LABEL"
    echo ""
else
    echo ""
    echo "=== WARNING ==="
    echo "  Plist installed but service may not be running yet."
    echo "  Check: launchctl print gui/\$(id -u)/$LABEL"
    echo "  Logs:  tail -f $LOG_DIR/ncl-brain-stderr.log"
    echo ""
fi
