#!/bin/bash
# Restart NCL Brain via launchctl
echo "=== Restarting NCL Brain ==="

LABEL="com.resonanceenergy.ncl-brain"
UID_NUM=$(id -u)

# Check if loaded
if launchctl print "gui/$UID_NUM/$LABEL" &>/dev/null; then
    echo "LaunchAgent is loaded — kickstarting..."
    launchctl kickstart -k "gui/$UID_NUM/$LABEL"
else
    echo "LaunchAgent not loaded — loading..."
    launchctl load "$HOME/Library/LaunchAgents/$LABEL.plist" 2>/dev/null
    launchctl kickstart "gui/$UID_NUM/$LABEL"
fi

echo "Waiting 5 seconds for Brain to start..."
sleep 5

# Test health
HEALTH=$(curl -s --connect-timeout 3 http://localhost:8800/health 2>/dev/null)
if [ -n "$HEALTH" ]; then
    echo "✅ Brain is healthy on localhost:8800"
    echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"
else
    echo "❌ Brain not responding on localhost:8800"
    echo "Checking process..."
    lsof -ti :8800 2>/dev/null && echo "Something is on port 8800" || echo "Nothing on port 8800"
    echo ""
    echo "Check logs: tail -50 ~/dev/NCL/logs/ncl-brain-stderr.log"
fi

# Test Tailscale IP
TS_IP="100.72.223.123"
echo ""
echo "Testing Tailscale IP ($TS_IP:8800)..."
HEALTH_TS=$(curl -s --connect-timeout 5 "http://$TS_IP:8800/health" 2>/dev/null)
if [ -n "$HEALTH_TS" ]; then
    echo "✅ Brain reachable via Tailscale!"
else
    echo "❌ Brain NOT reachable via Tailscale"
    echo "Checking Tailscale interface..."
    ifconfig | grep -A2 "utun" | grep "inet " 2>/dev/null || echo "No utun interfaces with inet"
fi

echo ""
echo "Press Enter to close..."
read
