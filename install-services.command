#!/bin/bash
# ============================================================
# STRIKE-POINT Service Installer
# Installs all NARTIX pipeline services as launchd daemons
# ============================================================

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

LAUNCH_DIR="$HOME/Library/LaunchAgents"

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  STRIKE-POINT Service Installer${NC}"
echo -e "${CYAN}  MANDATE-2026-008${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# Create required directories
echo -e "${YELLOW}Creating directories...${NC}"
mkdir -p "$HOME/Projects/FirstStrike/logs"
mkdir -p "$HOME/dev/NCL/logs"
mkdir -p "$HOME/dev/NCL/mandate-generation/input"
mkdir -p "$HOME/dev/NCL/mandate-generation/processed"
mkdir -p "$HOME/dev/NCL/mandate-generation/failed"
mkdir -p "$HOME/dev/NCL/data"
mkdir -p "$HOME/dev/NCL/config"
mkdir -p "$LAUNCH_DIR"
echo -e "${GREEN}  ✓ Directories ready${NC}"

# Kill any old relay processes running from terminal
echo ""
echo -e "${YELLOW}Stopping old processes...${NC}"
pkill -f "relay-pump-endpoint" 2>/dev/null && echo -e "${GREEN}  ✓ Old relay killed${NC}" || true
pkill -f "runtime.api.routes" 2>/dev/null && echo -e "${GREEN}  ✓ Old brain killed${NC}" || true
pkill -f "pump_watcher" 2>/dev/null && echo -e "${GREEN}  ✓ Old watcher killed${NC}" || true
sleep 1

# Check Python dependencies (use homebrew python)
echo ""
echo -e "${YELLOW}Checking Python dependencies...${NC}"
/opt/homebrew/bin/python3 -c "import fastapi, uvicorn, pydantic, httpx" 2>/dev/null || {
    echo -e "${RED}  Missing Python packages. Installing...${NC}"
    /opt/homebrew/bin/pip3 install fastapi uvicorn pydantic httpx pydantic-settings pyyaml aiofiles --break-system-packages 2>/dev/null || \
    /opt/homebrew/bin/pip3 install fastapi uvicorn pydantic httpx pydantic-settings pyyaml aiofiles
}
echo -e "${GREEN}  ✓ Python dependencies OK${NC}"

# --- Service 1: FirstStrike Relay (port 8787) ---
echo ""
echo -e "${YELLOW}Installing FirstStrike Relay (port 8787)...${NC}"
RELAY_PLIST="com.resonanceenergy.relay"
launchctl bootout "gui/$(id -u)/$RELAY_PLIST" 2>/dev/null || true
cp "$HOME/Projects/FirstStrike/com.resonanceenergy.relay.plist" "$LAUNCH_DIR/"
launchctl bootstrap "gui/$(id -u)" "$LAUNCH_DIR/$RELAY_PLIST.plist"
echo -e "${GREEN}  ✓ FirstStrike Relay installed${NC}"

# --- Service 2: NCL Brain (port 8800) ---
echo ""
echo -e "${YELLOW}Installing NCL Brain Service (port 8800)...${NC}"
BRAIN_PLIST="com.resonanceenergy.ncl-brain"
launchctl bootout "gui/$(id -u)/$BRAIN_PLIST" 2>/dev/null || true
cp "$HOME/dev/NCL/com.resonanceenergy.ncl-brain.plist" "$LAUNCH_DIR/"
launchctl bootstrap "gui/$(id -u)" "$LAUNCH_DIR/$BRAIN_PLIST.plist"
echo -e "${GREEN}  ✓ NCL Brain Service installed${NC}"

# --- Service 3: Pump Watcher ---
echo ""
echo -e "${YELLOW}Installing Pump Watcher...${NC}"
WATCHER_PLIST="com.resonanceenergy.ncl-watcher"
launchctl bootout "gui/$(id -u)/$WATCHER_PLIST" 2>/dev/null || true
cp "$HOME/dev/NCL/com.resonanceenergy.ncl-watcher.plist" "$LAUNCH_DIR/"
launchctl bootstrap "gui/$(id -u)" "$LAUNCH_DIR/$WATCHER_PLIST.plist"
echo -e "${GREEN}  ✓ Pump Watcher installed${NC}"

# Verify
echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  Verification${NC}"
echo -e "${CYAN}============================================${NC}"

sleep 3

# Check relay
if curl -sk https://localhost:8787/health >/dev/null 2>&1; then
    echo -e "${GREEN}  ✓ FirstStrike Relay  → https://localhost:8787  RUNNING${NC}"
else
    echo -e "${RED}  ✗ FirstStrike Relay  → https://localhost:8787  NOT RESPONDING (check logs)${NC}"
fi

# Check brain
if curl -s http://localhost:8800/health >/dev/null 2>&1; then
    echo -e "${GREEN}  ✓ NCL Brain Service  → http://localhost:8800   RUNNING${NC}"
else
    echo -e "${YELLOW}  ⚠ NCL Brain Service  → http://localhost:8800   STARTING (needs API keys in .env)${NC}"
fi

# Check watcher
if pgrep -f "pump_watcher" >/dev/null 2>&1; then
    echo -e "${GREEN}  ✓ Pump Watcher       → filesystem monitor     RUNNING${NC}"
else
    echo -e "${YELLOW}  ⚠ Pump Watcher       → filesystem monitor     STARTING${NC}"
fi

# Check Tailscale
TS_IP=$(/Applications/Tailscale.app/Contents/MacOS/Tailscale ip -4 2>/dev/null || echo "")
if [ -n "$TS_IP" ]; then
    echo -e "${GREEN}  ✓ Tailscale IP       → $TS_IP${NC}"
    echo -e "${GREEN}  ✓ iPhone endpoint    → https://$TS_IP:8787${NC}"
else
    echo -e "${RED}  ✗ Tailscale          → NOT CONNECTED${NC}"
fi

echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  Pipeline Architecture${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""
echo -e "  iPhone → Grok → FirstStrike App"
echo -e "    ↓ (Tailscale VPN)"
echo -e "  FirstStrike Relay [:8787] → file write + API forward"
echo -e "    ↓"
echo -e "  NCL Brain Service [:8800] → council → mandate"
echo -e "    ↓"
echo -e "  Pump Watcher (fallback filesystem → brain)"
echo ""
echo -e "${GREEN}Done. All services installed.${NC}"
echo ""
echo -e "${YELLOW}Logs:${NC}"
echo -e "  Relay:   ~/Projects/FirstStrike/logs/relay.log"
echo -e "  Brain:   ~/dev/NCL/logs/ncl-brain-stdout.log"
echo -e "  Watcher: ~/dev/NCL/logs/pump-watcher.log"
echo ""
