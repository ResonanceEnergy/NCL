#!/bin/bash
# ============================================================
# STRIKE-POINT Pipeline Quick Start
# Starts all services and runs E2E test
# Double-click this in Finder to launch everything
# ============================================================

PYTHON=/opt/homebrew/bin/python3
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  STRIKE-POINT Pipeline Quick Start${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# Ensure directories exist
mkdir -p ~/Projects/FirstStrike/logs
mkdir -p ~/dev/NCL/logs
mkdir -p ~/dev/NCL/mandate-generation/{input,processed,failed}

# Install deps if needed
$PYTHON -c "import fastapi, uvicorn, pydantic, httpx" 2>/dev/null || {
    echo -e "${YELLOW}  Installing dependencies...${NC}"
    /opt/homebrew/bin/pip3 install fastapi uvicorn pydantic httpx pydantic-settings pyyaml aiofiles --break-system-packages -q 2>/dev/null
}

# Kill old relay if running (to pick up new code)
echo -e "${YELLOW}Restarting services with latest code...${NC}"
pkill -f "relay-pump-endpoint" 2>/dev/null || true
pkill -f "runtime.api.routes" 2>/dev/null || true
pkill -f "pump_watcher" 2>/dev/null || true
sleep 2

# Remove old TLS cert so relay regenerates with current Tailscale IP
rm -f ~/Projects/FirstStrike/certs/relay.pem ~/Projects/FirstStrike/certs/relay-key.pem 2>/dev/null
echo -e "${GREEN}  ✓ Old TLS cert cleared (will regenerate with Tailscale IP)${NC}"

# Start FirstStrike Relay (port 8787)
echo -e "${YELLOW}  Starting FirstStrike Relay on :8787...${NC}"
cd ~/Projects/FirstStrike
nohup $PYTHON relay-pump-endpoint.py > logs/relay-stdout.log 2> logs/relay-stderr.log &
sleep 3
if curl -sk https://localhost:8787/health >/dev/null 2>&1; then
    echo -e "${GREEN}  ✓ Relay started${NC}"
else
    echo -e "${RED}  ✗ Relay failed — stderr:${NC}"
    tail -5 logs/relay-stderr.log
fi

# Start NCL Brain (port 8800)
echo -e "${YELLOW}  Starting NCL Brain on :8800...${NC}"
cd ~/dev/NCL
PYTHONPATH=~/dev/NCL nohup $PYTHON -m runtime.api.routes > logs/ncl-brain-stdout.log 2> logs/ncl-brain-stderr.log &
sleep 3
if curl -s http://localhost:8800/health >/dev/null 2>&1; then
    echo -e "${GREEN}  ✓ Brain started${NC}"
else
    echo -e "${YELLOW}  ⚠ Brain starting (may need API keys in .env)${NC}"
fi

# Start Pump Watcher
echo -e "${YELLOW}  Starting Pump Watcher...${NC}"
cd ~/dev/NCL
PYTHONPATH=~/dev/NCL nohup $PYTHON -m runtime.pump_watcher > logs/pump-watcher-stdout.log 2> logs/pump-watcher-stderr.log &
echo -e "${GREEN}  ✓ Watcher started${NC}"

# Run E2E test
echo ""
echo -e "${CYAN}Running E2E pipeline test...${NC}"
echo ""
sleep 2
cd ~/dev/NCL
$PYTHON tests/test_e2e_pipeline.py

echo ""
echo -e "${CYAN}Dashboard: https://localhost:8787/status${NC}"
echo -e "${CYAN}Brain API: http://localhost:8800/docs${NC}"
echo ""
read -p "Press Enter to close..."
