#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  NCL Brain — Run Script                                                ║
# ║  Starts the NCL brain service and opens the dashboard.                 ║
# ║  Usage: ./run.sh [--port 8800] [--debug] [--no-open]                   ║
# ╚══════════════════════════════════════════════════════════════════════════╝

set -e

NCL_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$NCL_DIR"

PORT=8800
DEBUG=""
OPEN_BROWSER=true

# Parse args
while [[ $# -gt 0 ]]; do
    case $1 in
        --port) PORT="$2"; shift 2 ;;
        --debug) DEBUG="--log-level debug"; shift ;;
        --no-open) OPEN_BROWSER=false; shift ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# Check .env
if [ ! -f ".env" ]; then
    echo "No .env file found. Run ./setup.sh first."
    exit 1
fi

# Auto-kill stale process on port
if lsof -i :$PORT > /dev/null 2>&1; then
    STALE_PID=$(lsof -ti :$PORT 2>/dev/null)
    if [ -n "$STALE_PID" ]; then
        echo "  ⚡ Port $PORT in use by PID $STALE_PID — killing..."
        kill $STALE_PID 2>/dev/null
        sleep 1
        # Force kill if still alive
        if kill -0 $STALE_PID 2>/dev/null; then
            kill -9 $STALE_PID 2>/dev/null
            sleep 1
        fi
        echo "  ✓ Cleared."
    fi
fi

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
echo "  API:            http://localhost:$PORT/health"
echo "  Docs:           http://localhost:$PORT/docs"
echo ""
echo "  Press Ctrl+C to stop."
echo ""

# Open browser (macOS)
if [ "$OPEN_BROWSER" = true ] && [[ "$OSTYPE" == "darwin"* ]]; then
    (sleep 2 && open "http://localhost:$PORT/dashboard") &
fi

# Run
exec python3 -m uvicorn runtime.api.routes:app \
    --host 0.0.0.0 \
    --port $PORT \
    --reload \
    $DEBUG
