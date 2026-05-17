#!/usr/bin/env bash
# restart-brain.command — Restart the NCL Brain launchd service
# Double-click this file to restart the Brain with latest code changes.

set -euo pipefail

LABEL="com.resonanceenergy.ncl-brain"
UID_VAL=$(id -u)

echo "=== Restarting NCL Brain ==="
echo ""

# Check if the service is loaded
if launchctl print "gui/$UID_VAL/$LABEL" &>/dev/null; then
    echo "[1/3] Stopping current Brain process..."
    launchctl kickstart -k "gui/$UID_VAL/$LABEL"
    echo "      Done — service restarted via kickstart."
else
    echo "[1/3] Service not loaded. Loading plist..."
    PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
    if [ -f "$PLIST" ]; then
        launchctl load "$PLIST"
        echo "      Loaded from $PLIST"
    else
        echo "      ERROR: Plist not found at $PLIST"
        echo "      Run: cp ~/dev/NCL/com.resonanceenergy.ncl-brain.plist ~/Library/LaunchAgents/"
        read -p "Press Enter to close..."
        exit 1
    fi
fi

echo ""
echo "[2/3] Waiting 5 seconds for Brain to start..."
sleep 5

echo ""
echo "[3/3] Testing Brain health endpoint..."
HEALTH=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8800/health 2>/dev/null || echo "000")
if [ "$HEALTH" = "200" ]; then
    echo "      Brain is UP (HTTP 200)"
else
    echo "      Brain returned HTTP $HEALTH — check logs:"
    echo "      tail -50 ~/dev/NCL/logs/ncl-brain-stderr.log"
fi

echo ""
echo "=== Brain restart complete ==="
echo ""
read -p "Press Enter to close..."
