#!/bin/bash
# Restart NCL Brain with latest Intelligence Engine code
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PYTHON=/opt/homebrew/bin/python3
if [ ! -x "$PYTHON" ]; then
    PYTHON=$(which python3 2>/dev/null || echo "python3")
fi

NCL_DIR="$HOME/dev/NCL"
LOGS="$NCL_DIR/logs"
mkdir -p "$LOGS"

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  NCL Brain — Restart with Intelligence Engine${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# Kill existing brain on port 8800 (aggressive — kill parent reloader too)
echo -e "${YELLOW}Stopping existing brain on :8800...${NC}"
for pid in $(lsof -ti :8800 2>/dev/null); do
    echo -e "  ${YELLOW}Killing PID $pid${NC}"
    kill -9 $pid 2>/dev/null || true
done
sleep 3
# Second pass — catch any reloader respawns
for pid in $(lsof -ti :8800 2>/dev/null); do
    echo -e "  ${YELLOW}Killing respawned PID $pid${NC}"
    kill -9 $pid 2>/dev/null || true
done
sleep 2

# Install new deps
echo -e "${YELLOW}Installing intelligence engine deps...${NC}"
$PYTHON -m pip install httpx pytrends --break-system-packages -q 2>/dev/null || true

# Start brain
echo -e "${YELLOW}Starting NCL Brain...${NC}"
cd "$NCL_DIR"
PYTHONPATH="$NCL_DIR" nohup $PYTHON -m uvicorn runtime.api.routes:app \
    --host 0.0.0.0 --port 8800 --reload \
    > "$LOGS/brain-stdout.log" 2> "$LOGS/brain-stderr.log" &

# Wait for it
for i in $(seq 1 15); do
    if curl -s http://localhost:8800/health >/dev/null 2>&1; then
        echo -e "${GREEN}✓ NCL Brain online (:8800)${NC}"
        break
    fi
    sleep 1
    echo -e "  Waiting... ($i/15)"
done

# Test intelligence endpoint
echo ""
echo -e "${YELLOW}Testing intelligence endpoints...${NC}"

HEALTH=$(curl -s http://localhost:8800/health 2>/dev/null)
if [ ! -z "$HEALTH" ]; then
    echo -e "${GREEN}✓ /health responding${NC}"
else
    echo -e "${RED}✗ /health not responding${NC}"
fi

SHORTCUTS=$(curl -s http://localhost:8800/shortcuts/config 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'✓ {d[\"total_shortcuts\"]} shortcuts available')" 2>/dev/null)
if [ ! -z "$SHORTCUTS" ]; then
    echo -e "${GREEN}$SHORTCUTS${NC}"
else
    echo -e "${YELLOW}⚠ Shortcuts endpoint not ready yet (may need a moment)${NC}"
fi

INTEL=$(curl -s http://localhost:8800/intelligence/stats 2>/dev/null)
if [ ! -z "$INTEL" ]; then
    echo -e "${GREEN}✓ Intelligence engine active${NC}"
else
    echo -e "${YELLOW}⚠ Intelligence engine not ready yet${NC}"
fi

echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${GREEN}  Brain restarted with Intelligence Engine${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# Get LAN IP for iPhone access
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "localhost")

echo -e "${GREEN}⚡ COMMAND CENTER:  ${CYAN}http://${LAN_IP}:8800/app${NC}"
echo ""
echo -e "Dashboard:      ${CYAN}http://localhost:8800/dashboard/ui${NC}"
echo -e "Shortcuts:      ${CYAN}http://localhost:8800/shortcuts/config${NC}"
echo -e "Intel:          ${CYAN}http://localhost:8800/intelligence/latest${NC}"
echo ""
echo -e "${YELLOW}📱 Open on ANY device:${NC}"
echo -e "${GREEN}  http://${LAN_IP}:8800/app${NC}"
echo -e "  (Add to Home Screen for app-like experience)"
echo ""
echo "Press Enter to close..."
read
