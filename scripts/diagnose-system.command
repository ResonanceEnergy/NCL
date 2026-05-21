#!/bin/bash
# Full System Diagnostic — Tailscale, Brain, Network, Devices
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'
REPORT="$HOME/dev/NCL/logs/system-diagnostic.txt"
mkdir -p "$HOME/dev/NCL/logs"

echo -e "${CYAN}================================================${NC}"
echo -e "${CYAN}  NATRIX Full System Diagnostic${NC}"
echo -e "${CYAN}================================================${NC}"
echo ""

# Write to both screen and file
exec > >(tee "$REPORT") 2>&1

echo "=== SYSTEM DIAGNOSTIC === $(date)"
echo ""

# 1. Tailscale
echo "--- TAILSCALE STATUS ---"
if command -v tailscale &>/dev/null; then
    TS_STATUS=$(tailscale status 2>&1)
    echo "$TS_STATUS"
    echo ""
    TS_IP=$(tailscale ip -4 2>/dev/null)
    echo "Tailscale IPv4: $TS_IP"
else
    # Try /Applications path
    if [ -f "/Applications/Tailscale.app/Contents/MacOS/Tailscale" ]; then
        echo "Tailscale app found but CLI not in PATH"
    else
        echo "Tailscale NOT FOUND"
    fi
fi
echo ""

# 2. Brain process
echo "--- NCL BRAIN (port 8800) ---"
BRAIN_PIDS=$(lsof -ti :8800 2>/dev/null)
if [ -z "$BRAIN_PIDS" ]; then
    echo "BRAIN NOT RUNNING — nothing on port 8800"
else
    echo "Brain PIDs on 8800: $BRAIN_PIDS"
    for pid in $BRAIN_PIDS; do
        ps -p "$pid" -o pid,ppid,stat,command 2>/dev/null
    done
fi
echo ""

# 3. Brain health check
echo "--- BRAIN HEALTH CHECK ---"
HEALTH=$(curl -s --connect-timeout 3 http://localhost:8800/health 2>&1)
if [ -z "$HEALTH" ]; then
    echo "localhost:8800/health — NO RESPONSE"
else
    echo "localhost:8800/health — $HEALTH"
fi

HEALTH_TS=$(curl -s --connect-timeout 3 http://100.72.223.123:8800/health 2>&1)
if [ -z "$HEALTH_TS" ]; then
    echo "100.72.223.123:8800/health — NO RESPONSE"
else
    echo "100.72.223.123:8800/health — $HEALTH_TS"
fi
echo ""

# 4. Relay (port 8787)
echo "--- RELAY SERVER (port 8787) ---"
RELAY_PIDS=$(lsof -ti :8787 2>/dev/null)
if [ -z "$RELAY_PIDS" ]; then
    echo "Relay NOT RUNNING — nothing on port 8787"
else
    echo "Relay PIDs on 8787: $RELAY_PIDS"
fi
echo ""

# 5. LaunchAgent status
echo "--- LAUNCHAGENT STATUS ---"
LABEL="com.resonanceenergy.ncl-brain"
if launchctl print "gui/$(id -u)/$LABEL" &>/dev/null; then
    echo "LaunchAgent LOADED: $LABEL"
    launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | grep -E "state|pid|last exit"
else
    echo "LaunchAgent NOT LOADED: $LABEL"
fi
echo ""

# 6. Network interfaces
echo "--- NETWORK ---"
echo "LAN IP (en0): $(ipconfig getifaddr en0 2>/dev/null || echo 'none')"
echo "LAN IP (en1): $(ipconfig getifaddr en1 2>/dev/null || echo 'none')"
echo "Tailscale IP: $(ipconfig getifaddr utun* 2>/dev/null || echo 'checking...')"
# Check if Tailscale interface exists
ifconfig | grep -A2 "utun" | grep "inet " 2>/dev/null || echo "No utun interfaces with inet found"
echo ""

# 7. Ollama
echo "--- OLLAMA ---"
if curl -s --connect-timeout 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "Ollama: RUNNING"
else
    echo "Ollama: NOT RUNNING"
fi
echo ""

# 8. Brain logs (last 20 lines of stderr)
echo "--- BRAIN STDERR LOG (last 20 lines) ---"
if [ -f "$HOME/dev/NCL/logs/brain-stderr.log" ]; then
    tail -20 "$HOME/dev/NCL/logs/brain-stderr.log"
elif [ -f "$HOME/dev/NCL/logs/ncl-brain-stderr.log" ]; then
    tail -20 "$HOME/dev/NCL/logs/ncl-brain-stderr.log"
else
    echo "No brain stderr log found"
fi
echo ""

# 9. Firewall
echo "--- FIREWALL ---"
/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null || echo "Could not check firewall"
echo ""

# 10. Summary
echo "================================================"
echo "  DIAGNOSTIC COMPLETE — saved to $REPORT"
echo "================================================"
echo ""
echo "Press Enter to close..."
read
