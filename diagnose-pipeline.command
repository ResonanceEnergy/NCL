#!/bin/bash
# ============================================================
# STRIKE-POINT Pipeline Diagnostics
# Checks every link in the chain: Tailscale → Relay → Brain
# Double-click in Finder to run
# ============================================================

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

PASS="${GREEN}✓ PASS${NC}"
FAIL="${RED}✗ FAIL${NC}"
WARN="${YELLOW}⚠ WARN${NC}"

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  STRIKE-POINT Pipeline Diagnostics${NC}"
echo -e "${CYAN}  $(date)${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

ISSUES=0

# ── 1. Tailscale ──────────────────────────────────
echo -e "${CYAN}[1/7] Tailscale${NC}"
TS_IP=$(/Applications/Tailscale.app/Contents/MacOS/Tailscale ip -4 2>/dev/null || echo "")
TS_STATUS=$(/Applications/Tailscale.app/Contents/MacOS/Tailscale status --self 2>/dev/null || echo "")
if [ -n "$TS_IP" ]; then
    echo -e "  $PASS  Tailscale UP — IP: $TS_IP"
    echo -e "  Status: $TS_STATUS"
else
    echo -e "  $FAIL  Tailscale NOT CONNECTED"
    echo -e "  → Open Tailscale app and connect"
    ISSUES=$((ISSUES+1))
fi
echo ""

# ── 2. Relay process ─────────────────────────────
echo -e "${CYAN}[2/7] FirstStrike Relay Process${NC}"
RELAY_PID=$(pgrep -f "relay-pump-endpoint" 2>/dev/null)
if [ -n "$RELAY_PID" ]; then
    echo -e "  $PASS  Relay running (PID: $RELAY_PID)"
    RELAY_PYTHON=$(ps -p $RELAY_PID -o command= 2>/dev/null | awk '{print $1}')
    echo -e "  Python: $RELAY_PYTHON"
    if [[ "$RELAY_PYTHON" == *"homebrew"* ]]; then
        echo -e "  $PASS  Using Homebrew Python"
    else
        echo -e "  $WARN  NOT using Homebrew Python — may be missing deps"
    fi
else
    echo -e "  $FAIL  Relay NOT RUNNING"
    echo -e "  → Double-click start-pipeline.command or install-services.command"
    ISSUES=$((ISSUES+1))
fi
echo ""

# ── 3. Relay health (localhost) ──────────────────
echo -e "${CYAN}[3/7] Relay Health (localhost)${NC}"
RELAY_HEALTH=$(curl -sk --connect-timeout 3 https://localhost:8787/health 2>/dev/null)
if [ $? -eq 0 ] && [ -n "$RELAY_HEALTH" ]; then
    echo -e "  $PASS  https://localhost:8787/health responds"
    echo -e "  Response: $RELAY_HEALTH"
else
    echo -e "  $FAIL  Relay not responding on localhost:8787"
    ISSUES=$((ISSUES+1))
fi
echo ""

# ── 4. Relay health (Tailscale IP) ───────────────
echo -e "${CYAN}[4/7] Relay Health (Tailscale IP)${NC}"
if [ -n "$TS_IP" ]; then
    RELAY_TS=$(curl -sk --connect-timeout 5 "https://$TS_IP:8787/health" 2>/dev/null)
    if [ $? -eq 0 ] && [ -n "$RELAY_TS" ]; then
        echo -e "  $PASS  https://$TS_IP:8787/health responds"
        echo -e "  Response: $RELAY_TS"
        echo -e "  → iPhone should use: https://$TS_IP:8787"
    else
        echo -e "  $FAIL  Relay NOT reachable via Tailscale IP ($TS_IP:8787)"
        echo -e "  → Check: Is relay binding to 0.0.0.0 (not 127.0.0.1)?"
        echo -e "  → Check: macOS firewall blocking port 8787?"
        ISSUES=$((ISSUES+1))
    fi
else
    echo -e "  $WARN  Skipped — Tailscale not connected"
fi
echo ""

# ── 5. TLS Certificate ──────────────────────────
echo -e "${CYAN}[5/7] TLS Certificate${NC}"
CERT_INFO=$(echo | openssl s_client -connect localhost:8787 -servername localhost 2>/dev/null | openssl x509 -noout -subject -dates 2>/dev/null)
if [ -n "$CERT_INFO" ]; then
    echo -e "  $PASS  TLS certificate present"
    echo "$CERT_INFO" | sed 's/^/  /'
else
    echo -e "  $WARN  Could not read TLS cert info"
fi
# Check if cert files exist
CERT_DIR="$HOME/Projects/FirstStrike/certs"
if [ -f "$CERT_DIR/relay.pem" ] && [ -f "$CERT_DIR/relay-key.pem" ]; then
    echo -e "  $PASS  relay.pem and relay-key.pem exist"
    CERT_AGE=$(( ($(date +%s) - $(stat -f %m "$CERT_DIR/relay.pem")) / 86400 ))
    echo -e "  Certificate age: ${CERT_AGE} days"
    # Check if Tailscale IP is in cert SAN
    if [ -n "$TS_IP" ]; then
        if openssl x509 -in "$CERT_DIR/relay.pem" -noout -text 2>/dev/null | grep -q "$TS_IP"; then
            echo -e "  $PASS  Tailscale IP ($TS_IP) is in cert SAN"
        else
            echo -e "  $FAIL  Tailscale IP ($TS_IP) NOT in cert SAN"
            echo -e "  → Restart relay (start-pipeline.command) to regenerate cert"
            ISSUES=$((ISSUES+1))
        fi
    fi
else
    echo -e "  $WARN  No TLS cert yet — relay will generate on start"
fi
echo ""

# ── 6. NCL Brain ─────────────────────────────────
echo -e "${CYAN}[6/7] NCL Brain Service${NC}"
BRAIN_PID=$(pgrep -f "runtime.api.routes" 2>/dev/null)
if [ -n "$BRAIN_PID" ]; then
    echo -e "  $PASS  Brain running (PID: $BRAIN_PID)"
    BRAIN_PYTHON=$(ps -p $BRAIN_PID -o command= 2>/dev/null | awk '{print $1}')
    echo -e "  Python: $BRAIN_PYTHON"
    if [[ "$BRAIN_PYTHON" == *"homebrew"* ]]; then
        echo -e "  $PASS  Using Homebrew Python"
    else
        echo -e "  $FAIL  NOT using Homebrew Python — will crash on import"
        ISSUES=$((ISSUES+1))
    fi
else
    echo -e "  $FAIL  Brain NOT RUNNING"
    ISSUES=$((ISSUES+1))
fi

BRAIN_HEALTH=$(curl -s --connect-timeout 3 http://localhost:8800/health 2>/dev/null)
if [ $? -eq 0 ] && [ -n "$BRAIN_HEALTH" ]; then
    echo -e "  $PASS  http://localhost:8800/health responds"
    echo -e "  Response: $BRAIN_HEALTH"
else
    echo -e "  $FAIL  Brain not responding on localhost:8800"
    echo -e "  → Check logs: tail ~/dev/NCL/logs/ncl-brain-stderr.log"
    ISSUES=$((ISSUES+1))
fi
echo ""

# ── 7. Pump Watcher ──────────────────────────────
echo -e "${CYAN}[7/7] Pump Watcher${NC}"
WATCHER_PID=$(pgrep -f "pump_watcher" 2>/dev/null)
if [ -n "$WATCHER_PID" ]; then
    echo -e "  $PASS  Watcher running (PID: $WATCHER_PID)"
else
    echo -e "  $WARN  Watcher not running (fallback path inactive)"
fi
echo ""

# ── 8. Launchd plist check ───────────────────────
echo -e "${CYAN}[Bonus] Launchd Plist Verification${NC}"
LA_DIR="$HOME/Library/LaunchAgents"
for PLIST in com.resonanceenergy.relay com.resonanceenergy.ncl-brain com.resonanceenergy.ncl-watcher; do
    if [ -f "$LA_DIR/$PLIST.plist" ]; then
        PLIST_PYTHON=$(grep -A1 "ProgramArguments" "$LA_DIR/$PLIST.plist" | grep python | sed 's/.*<string>//' | sed 's/<\/string>.*//' | tr -d ' ')
        if [[ "$PLIST_PYTHON" == *"homebrew"* ]]; then
            echo -e "  $PASS  $PLIST → $PLIST_PYTHON"
        else
            echo -e "  $FAIL  $PLIST → $PLIST_PYTHON (WRONG — needs /opt/homebrew/bin/python3)"
            echo -e "       → Run install-services.command to fix"
            ISSUES=$((ISSUES+1))
        fi
    else
        echo -e "  $WARN  $PLIST.plist NOT installed in LaunchAgents"
        echo -e "       → Run install-services.command to install"
    fi
done
echo ""

# ── Recent relay logs ────────────────────────────
echo -e "${CYAN}[Logs] Recent Relay Activity${NC}"
RELAY_LOG="$HOME/Projects/FirstStrike/logs/relay-stdout.log"
if [ -f "$RELAY_LOG" ]; then
    echo "  Last 10 lines:"
    tail -10 "$RELAY_LOG" 2>/dev/null | sed 's/^/  /'
else
    echo "  No relay stdout log found"
fi
echo ""

RELAY_ERR="$HOME/Projects/FirstStrike/logs/relay-stderr.log"
if [ -f "$RELAY_ERR" ]; then
    echo -e "${CYAN}[Logs] Relay Errors (last 10)${NC}"
    tail -10 "$RELAY_ERR" 2>/dev/null | sed 's/^/  /'
fi
echo ""

BRAIN_ERR="$HOME/dev/NCL/logs/ncl-brain-stderr.log"
if [ -f "$BRAIN_ERR" ]; then
    echo -e "${CYAN}[Logs] Brain Errors (last 10)${NC}"
    tail -10 "$BRAIN_ERR" 2>/dev/null | sed 's/^/  /'
fi
echo ""

# ── macOS firewall ───────────────────────────────
echo -e "${CYAN}[Firewall] macOS Firewall Status${NC}"
FW=$(/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null)
echo "  $FW"
if echo "$FW" | grep -qi "enabled"; then
    echo -e "  $WARN  Firewall is ON — may block Tailscale → port 8787"
    echo -e "  → Check: System Settings → Network → Firewall → Options"
    echo -e "  → Ensure Python is allowed incoming connections"
fi
echo ""

# ── Summary ──────────────────────────────────────
echo -e "${CYAN}============================================${NC}"
if [ $ISSUES -eq 0 ]; then
    echo -e "${GREEN}  ALL CHECKS PASSED — Pipeline healthy${NC}"
    echo -e "${GREEN}  iPhone endpoint: https://$TS_IP:8787${NC}"
else
    echo -e "${RED}  $ISSUES ISSUE(S) FOUND — see above${NC}"
fi
echo -e "${CYAN}============================================${NC}"
echo ""

# ── Quick fix suggestions ────────────────────────
if [ $ISSUES -gt 0 ]; then
    echo -e "${YELLOW}Quick Fixes:${NC}"
    echo -e "  1. Double-click install-services.command (fixes plists + restarts)"
    echo -e "  2. Or run: ~/dev/NCL/start-pipeline.command (manual start)"
    echo -e "  3. Check Tailscale is connected on both Mac and iPhone"
    echo -e "  4. On iPhone, verify endpoint is https://$TS_IP:8787"
    echo ""
fi

read -p "Press Enter to close..."
