#!/bin/bash
# Kill old services and restart with new code
# Note: set -e is intentionally NOT set here so test failures don't abort the restart.
# Tests are run with "|| true" to ensure the restart completes regardless.

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  STRIKE-POINT Full Restart${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# Ensure directories
mkdir -p ~/Projects/FirstStrike/logs
mkdir -p ~/dev/NCL/logs
mkdir -p ~/dev/NCL/mandate-generation/{input,processed,failed}
mkdir -p ~/dev/NCL/data
mkdir -p ~/dev/NCL/config

# Install dependencies
echo -e "${YELLOW}Checking dependencies...${NC}"
pip3 install fastapi uvicorn pydantic httpx pydantic-settings pyyaml aiofiles --break-system-packages -q 2>/dev/null || \
pip3 install fastapi uvicorn pydantic httpx pydantic-settings pyyaml aiofiles -q
echo -e "${GREEN}  ✓ Dependencies OK${NC}"

# Kill ALL old relay/brain/watcher processes
echo ""
echo -e "${YELLOW}Stopping old services...${NC}"
pkill -f "relay-pump-endpoint" 2>/dev/null && echo -e "${GREEN}  ✓ Old relay killed${NC}" || echo "  (no relay running)"
pkill -f "runtime.api.routes" 2>/dev/null && echo -e "${GREEN}  ✓ Old brain killed${NC}" || echo "  (no brain running)"
pkill -f "pump_watcher" 2>/dev/null && echo -e "${GREEN}  ✓ Old watcher killed${NC}" || echo "  (no watcher running)"
sleep 2

# Start FirstStrike Relay (port 8787)
echo ""
echo -e "${YELLOW}Starting FirstStrike Relay on :8787...${NC}"
cd ~/Projects/FirstStrike
nohup python3 relay-pump-endpoint.py > logs/relay-stdout.log 2> logs/relay-stderr.log &
RELAY_PID=$!
sleep 3
if curl -sk https://localhost:8787/health >/dev/null 2>&1; then
    echo -e "${GREEN}  ✓ Relay started (PID $RELAY_PID)${NC}"
else
    echo -e "${RED}  ✗ Relay failed — checking stderr:${NC}"
    tail -20 logs/relay-stderr.log
fi

# Start NCL Brain (port 8800)
echo ""
echo -e "${YELLOW}Starting NCL Brain on :8800...${NC}"
cd ~/dev/NCL
PYTHONPATH=~/dev/NCL nohup python3 -m runtime.api.routes > logs/ncl-brain-stdout.log 2> logs/ncl-brain-stderr.log &
BRAIN_PID=$!
sleep 3
if curl -s http://localhost:8800/health >/dev/null 2>&1; then
    echo -e "${GREEN}  ✓ Brain started (PID $BRAIN_PID)${NC}"
else
    echo -e "${YELLOW}  ⚠ Brain may need API keys — check logs/ncl-brain-stderr.log${NC}"
    tail -5 logs/ncl-brain-stderr.log 2>/dev/null
fi

# Start Pump Watcher
echo ""
echo -e "${YELLOW}Starting Pump Watcher...${NC}"
cd ~/dev/NCL
PYTHONPATH=~/dev/NCL nohup python3 -m runtime.pump_watcher > logs/pump-watcher-stdout.log 2> logs/pump-watcher-stderr.log &
WATCHER_PID=$!
echo -e "${GREEN}  ✓ Watcher started (PID $WATCHER_PID)${NC}"

# Run E2E test — failures here are logged but do NOT abort the restart
echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  Running E2E Pipeline Test${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""
sleep 2
cd ~/dev/NCL
python3 tests/test_e2e_pipeline.py || echo -e "${YELLOW}  ⚠ E2E test failed — services are still running, check output above${NC}"

echo ""
echo -e "${CYAN}Dashboard: https://localhost:8787/status${NC}"
echo -e "${CYAN}Brain API: http://localhost:8800/docs${NC}"
echo ""
read -p "Press Enter to close..."
