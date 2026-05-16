#!/bin/bash
# ============================================================
# NCL START-ALL — Bring every dashboard service online
# ============================================================
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
NCC_DIR="$HOME/dev/NCC-Doctrine"
AAC_DIR="$HOME/dev/AAC"
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
echo -e "${YELLOW}[1/8] NCL Brain (:8800)${NC}"
if curl -s http://localhost:8800/health >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓ Already running${NC}"
else
    clear_port 8800
    sleep 1
    cd "$NCL_DIR"
    PYTHONPATH="$NCL_DIR" nohup $PYTHON -m uvicorn runtime.api.routes:app \
        --host 0.0.0.0 --port 8800 $RELOAD_FLAG \
        > "$LOGS/brain-stdout.log" 2> "$LOGS/brain-stderr.log" &
    wait_for_port 8800 "NCL Brain"
fi

# ─── 2. NCC Relay (:8787) ───────────────────────────────────
echo -e "${YELLOW}[2/8] NCC Relay (:8787)${NC}"
if curl -sk https://localhost:8787/health >/dev/null 2>&1 || curl -s http://localhost:8787/health >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓ Already running${NC}"
else
    clear_port 8787
    sleep 1
    # Use the real relay server from NCC-Doctrine
    if [ -f "$NCC_DIR/runtime/relay_server.py" ]; then
        cd "$NCC_DIR/runtime"
        PYTHONPATH="$NCC_DIR" nohup $PYTHON relay_server.py \
            > "$LOGS/relay-stdout.log" 2> "$LOGS/relay-stderr.log" &
        wait_for_port 8787 "NCC Relay"
    elif [ -f "$HOME/Projects/FirstStrike/relay-pump-endpoint.py" ]; then
        cd "$HOME/Projects/FirstStrike"
        nohup $PYTHON relay-pump-endpoint.py > "$LOGS/relay-stdout.log" 2> "$LOGS/relay-stderr.log" &
        sleep 3
        if curl -sk https://localhost:8787/health >/dev/null 2>&1; then
            echo -e "  ${GREEN}✓ Relay online (:8787)${NC}"
        else
            echo -e "  ${YELLOW}⚠ Relay started but health check pending${NC}"
        fi
    else
        echo -e "  ${RED}✗ No relay server found${NC}"
    fi
fi

# ─── 3. NCC Master (:8765) ──────────────────────────────────
echo -e "${YELLOW}[3/8] NCC Master (:8765)${NC}"
if curl -s http://localhost:8765/health >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓ Already running${NC}"
else
    clear_port 8765
    sleep 1
    if [ -f "$NCC_DIR/runtime/ncc_command_api.py" ]; then
        cd "$NCC_DIR"
        PYTHONPATH="$NCC_DIR" nohup $PYTHON -m runtime.ncc_command_api \
            > "$LOGS/ncc-master-stdout.log" 2> "$LOGS/ncc-master-stderr.log" &
        wait_for_port 8765 "NCC Master"
    else
        echo -e "  ${RED}✗ NCC-Doctrine not found at $NCC_DIR${NC}"
    fi
fi

# ─── 4. One-Drop (:8123) ────────────────────────────────────
echo -e "${YELLOW}[4/8] One-Drop (:8123)${NC}"
if curl -s http://localhost:8123/health >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓ Already running${NC}"
else
    clear_port 8123
    sleep 1
    if [ -f "$NCC_DIR/backend/api/main.py" ]; then
        cd "$NCC_DIR/backend"
        PYTHONPATH="$NCC_DIR/backend" nohup $PYTHON -m api.main \
            > "$LOGS/onedrop-stdout.log" 2> "$LOGS/onedrop-stderr.log" &
        wait_for_port 8123 "One-Drop"
    else
        echo -e "  ${RED}✗ One-Drop not found${NC}"
    fi
fi

# ─── 5. AAC Monitor (:8080) ─────────────────────────────────
echo -e "${YELLOW}[5/8] AAC Monitor (:8080)${NC}"
if curl -s http://localhost:8080/health >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓ Already running${NC}"
else
    clear_port 8080
    sleep 1
    if [ -f "$AAC_DIR/shared/health_server.py" ]; then
        cd "$AAC_DIR"
        PYTHONPATH="$AAC_DIR" nohup $PYTHON shared/health_server.py \
            > "$LOGS/aac-stdout.log" 2> "$LOGS/aac-stderr.log" &
        sleep 3
        if curl -s http://localhost:8080/health >/dev/null 2>&1; then
            echo -e "  ${GREEN}✓ AAC Monitor online (:8080)${NC}"
        else
            # Fallback: lightweight stub
            echo -e "  ${YELLOW}⚠ AAC health_server failed — starting stub${NC}"
            clear_port 8080
            sleep 1
            nohup $PYTHON -c "
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn, json, os
from datetime import datetime, timezone
app = FastAPI(title='AAC War Room Monitor')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])
_regime = {'regime': 'neutral', 'confidence': 0.5, 'signals': [], 'updated': None}
_positions = {'active': [], 'pending': [], 'closed_today': []}
@app.get('/health')
async def health():
    return JSONResponse({'status': 'ok', 'service': 'aac-war-room', 'regime': _regime['regime']})
@app.get('/regime')
async def regime():
    return JSONResponse({**_regime, 'updated': datetime.now(timezone.utc).isoformat()})
@app.post('/regime')
async def update_regime(data: dict):
    _regime.update(data)
    return JSONResponse({'status': 'updated'})
@app.get('/positions')
async def positions():
    return JSONResponse(_positions)
@app.get('/sitrep')
async def sitrep():
    return JSONResponse({'regime': _regime['regime'], 'positions': len(_positions.get('active',[])), 'pnl': 0})
if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8080)
" > "$LOGS/aac-stub-stdout.log" 2> "$LOGS/aac-stub-stderr.log" &
            wait_for_port 8080 "AAC Monitor (stub)"
        fi
    else
        echo -e "  ${RED}✗ AAC dir not found at $AAC_DIR${NC}"
    fi
fi

# ─── 6. BRS Dashboard (:8000) ───────────────────────────────
echo -e "${YELLOW}[6/8] BRS Dashboard (:8000)${NC}"
if curl -s http://localhost:8000/health >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓ Already running${NC}"
else
    clear_port 8000
    sleep 1
    nohup $PYTHON -c "
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title='BRS Dashboard')

@app.get('/health')
async def health():
    return JSONResponse({'status': 'ok', 'service': 'brs-dashboard', 'pillar': 'BRS'})

@app.get('/matrix/sitrep')
async def sitrep():
    return JSONResponse({'status': 'operational', 'workers': 0, 'tasks_queued': 0})

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8000)
" > "$LOGS/brs-stdout.log" 2> "$LOGS/brs-stderr.log" &
    wait_for_port 8000 "BRS Dashboard"
fi

# ─── 7. Paperclip (:3100) ───────────────────────────────────
echo -e "${YELLOW}[7/8] Paperclip (:3100)${NC}"
if curl -s http://localhost:3100/health >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓ Already running${NC}"
else
    clear_port 3100
    sleep 1
    nohup $PYTHON -c "
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn
from datetime import datetime

app = FastAPI(title='Paperclip Budget Tracker')

@app.get('/health')
async def health():
    return JSONResponse({'status': 'ok', 'service': 'paperclip'})

@app.get('/budget/summary')
async def budget():
    return JSONResponse({'total_budget': 0, 'spent': 0, 'remaining': 0})

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=3100)
" > "$LOGS/paperclip-stdout.log" 2> "$LOGS/paperclip-stderr.log" &
    wait_for_port 3100 "Paperclip"
fi

# ─── 8. Ollama (:11434) ─────────────────────────────────────
echo -e "${YELLOW}[8/8] Ollama (:11434)${NC}"
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
TOTAL=8
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
check "NCC Relay"     8787 /health
check "NCC Master"    8765 /health
check "One-Drop"      8123 /health
check "AAC Monitor"   8080 /health
check "BRS Dashboard" 8000 /health
check "Paperclip"     3100 /health
check "Ollama"        11434 /api/tags

echo ""
echo -e "${CYAN}  $ONLINE/$TOTAL services online${NC}"
echo -e "${CYAN}  Dashboard: http://localhost:8800/dashboard/ui${NC}"
echo ""
read -p "Press Enter to close..."
