#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  NCL Brain — One-Shot Start                                            ║
# ║  Kills stale processes, runs setup if needed, boots the brain.         ║
# ║  Usage: ./start-brain.sh                                               ║
# ╚══════════════════════════════════════════════════════════════════════════╝

set -e

NCL_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$NCL_DIR"

echo ""
echo "  ⚡ NCL BRAIN — Auto-Start"
echo "  ─────────────────────────"

# ── 1. Force-kill ALL processes on 8800 ────────────────────────────────────
PORT=8800
echo "  → Clearing port $PORT..."
for pid in $(lsof -ti :$PORT 2>/dev/null); do
    echo "    killing PID $pid..."
    kill -9 $pid 2>/dev/null || true
done
sleep 2
# Double-check
for pid in $(lsof -ti :$PORT 2>/dev/null); do
    echo "    force-killing PID $pid..."
    kill -9 $pid 2>/dev/null || true
done
sleep 1
if lsof -i :$PORT > /dev/null 2>&1; then
    echo "  ✗ Port $PORT still in use. Cannot start."
    exit 1
fi
echo "  ✓ Port $PORT clear."

# ── 2. Check Python ───────────────────────────────────────────────────────
if ! command -v python3 &> /dev/null; then
    echo "  ✗ Python 3 not found. Install it first."
    exit 1
fi
echo "  ✓ Python: $(python3 --version 2>&1)"

# ── 3. Install deps if needed ─────────────────────────────────────────────
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "  → Installing dependencies..."
    pip3 install -r requirements.txt -q 2>&1 | tail -3
    echo "  ✓ Dependencies installed."
else
    echo "  ✓ Dependencies OK"
fi

# ── 4. Create data dirs ───────────────────────────────────────────────────
mkdir -p ~/NCL/data/{pumps/{incoming,processed,failed},mandates,councils,memory,telemetry,review_queue,evaluation,deployment,uni}
mkdir -p ~/NCL/config
echo "  ✓ Data directories OK"

# ── 5. Check .env ─────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo "  → Creating .env from template..."
    cp .env.example .env
    # Auto-generate STRIKE_AUTH_TOKEN
    TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/^STRIKE_AUTH_TOKEN=.*/STRIKE_AUTH_TOKEN=$TOKEN/" .env
    else
        sed -i "s/^STRIKE_AUTH_TOKEN=.*/STRIKE_AUTH_TOKEN=$TOKEN/" .env
    fi
    echo "  ✓ .env created (STRIKE_AUTH_TOKEN auto-generated)"
    echo "  ⚠ Add your ANTHROPIC_API_KEY to .env for full functionality"
fi
echo "  ✓ .env present"

# ── 6. Boot ───────────────────────────────────────────────────────────────
echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║  NCL BRAIN — Starting on :$PORT      ║"
echo "  ╚══════════════════════════════════════╝"
echo ""
echo "  Dashboards:"
echo "    Main:         http://localhost:$PORT/dashboard"
echo "    LDE:          http://localhost:$PORT/lde/dashboard"
echo "    Review Queue: http://localhost:$PORT/review-queue/dashboard"
echo "    Memory:       http://localhost:$PORT/memory/dashboard"
echo ""
echo "  API:  http://localhost:$PORT/health"
echo "  Docs: http://localhost:$PORT/docs"
echo ""
echo "  Press Ctrl+C to stop."
echo ""

# Open browser
if [[ "$OSTYPE" == "darwin"* ]]; then
    (sleep 2 && open "http://localhost:$PORT/dashboard") &
fi

# Start uvicorn
exec python3 -m uvicorn runtime.api.routes:app \
    --host 0.0.0.0 \
    --port $PORT \
    --reload
