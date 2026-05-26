#!/bin/bash
# ============================================================
# NCL START-ALL — Bring every dashboard service online
# ============================================================
# Pillar services retired 2026-05-23:
#   - NCC Relay (8787), NCC Master (8765): NCC repo removed from this machine
#   - AAC Monitor (8080): pillar retired
#   - BRS Dashboard (8000): pillar retired (never shipped)
# Service Paperclip (3100) retired 2026-05-25 (Wave 14G P13): never deployed,
# cost tracking is owned by runtime/cost_tracker.py inside the Brain.
# Active services below = NCL Brain + Ollama.
# One-Drop (8123) is documented as a manual-start dependency — left in place
# but not auto-started here.
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
echo -e "${CYAN}  NCL — Start All Services${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# Install shared deps (uses active venv — do NOT use --break-system-packages)
echo -e "${YELLOW}Installing dependencies...${NC}"
if [ -d ".venv" ]; then
    # shellcheck source=/dev/null
    source .venv/bin/activate
fi
$PYTHON -m pip install -r requirements.txt -q 2>/dev/null || true
echo -e "${GREEN}  ✓ Dependencies OK${NC}"
echo ""

# Helper: kill anything on a port
clear_port() {
    local port=$1
    for pid in $(lsof -ti :$port 2>/dev/null); do
        echo -e "  ${YELLOW}Killing PID $pid on :$port${NC}"
        kill -9 $pid 2>/dev/null || true
    done
}

# Helper: wait for a port to respond
wait_for_port() {
    local port=$1
    local name=$2
    local max=10
    for i in $(seq 1 $max); do
        if curl -s http://localhost:$port/health >/dev/null 2>&1; then
            echo -e "  ${GREEN}✓ $name online (:$port)${NC}"
            return 0
        fi
        sleep 1
    done
    echo -e "  ${RED}✗ $name failed to start on :$port${NC}"
    return 1
}

# Only use --reload in development mode
RELOAD_FLAG=""
if [ "$NCL_ENV" = "development" ]; then
    RELOAD_FLAG="--reload"
fi

# ─── 1. NCL Brain (:8800) ───────────────────────────────────
echo -e "${YELLOW}[1/4] NCL Brain (:8800)${NC}"
if curl -s http://localhost:8800/health >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓ Already running${NC}"
else
    clear_port 8800
    sleep 1
    cd "$NCL_DIR"
    PYTHONPATH="$NCL_DIR" nohup $PYTHON -m uvicorn runtime.api.routes:versioned_app \
        --host 0.0.0.0 --port 8800 $RELOAD_FLAG \
        > "$LOGS/brain-stdout.log" 2> "$LOGS/brain-stderr.log" &
    wait_for_port 8800 "NCL Brain"
fi

# ─── 2. One-Drop (:8123) ────────────────────────────────────
echo -e "${YELLOW}[2/4] One-Drop (:8123)${NC}"
if curl -s http://localhost:8123/health >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓ Already running${NC}"
else
    echo -e "  ${YELLOW}⚠ One-Drop not auto-started (no longer co-located with NCC). Start manually if needed.${NC}"
fi

# ─── 3. Ollama (:11434) ─────────────────────────────────────
echo -e "${YELLOW}[3/3] Ollama (:11434)${NC}"
if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓ Already running${NC}"
else
    # Try to start ollama serve
    if command -v ollama >/dev/null 2>&1; then
        nohup ollama serve > "$LOGS/ollama-stdout.log" 2> "$LOGS/ollama-stderr.log" &
        sleep 3
        if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
            echo -e "  ${GREEN}✓ Ollama online (:11434)${NC}"
        else
            echo -e "  ${YELLOW}⚠ Ollama starting...${NC}"
        fi
    else
        echo -e "  ${RED}✗ Ollama not installed${NC}"
    fi
fi

# ─── Summary ────────────────────────────────────────────────
echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  Service Status Summary${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

ONLINE=0
TOTAL=3
check() {
    local name=$1 port=$2 path=${3:-/health} proto=${4:-http}
    if curl -sk "${proto}://localhost:${port}${path}" >/dev/null 2>&1; then
        echo -e "  ${GREEN}●${NC} $name :$port"
        ONLINE=$((ONLINE + 1))
    else
        echo -e "  ${RED}●${NC} $name :$port"
    fi
}

check "NCL Brain"     8800 /health
check "One-Drop"      8123 /health
check "Ollama"        11434 /api/tags

echo ""
echo -e "${CYAN}  $ONLINE/$TOTAL services online${NC}"
echo -e "${CYAN}  Dashboard: http://localhost:8800/dashboard/ui${NC}"
echo ""
read -p "Press Enter to close..."
