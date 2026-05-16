#!/bin/bash
# Quick-start the NCC Relay from NCC-Doctrine
cd "$(dirname "$0")"
PYTHON=/opt/homebrew/bin/python3
NCC_DIR="$HOME/dev/NCC-Doctrine"
LOGS="$HOME/dev/NCL/logs"
mkdir -p "$LOGS"

echo "Clearing port 8787..."
for pid in $(lsof -ti :8787 2>/dev/null); do
    echo "  killing PID $pid"
    kill -9 "$pid" 2>/dev/null || true
done
sleep 2

echo "Starting NCC Relay from $NCC_DIR/runtime/relay_server.py..."
cd "$NCC_DIR/runtime"
PYTHONPATH="$NCC_DIR" nohup $PYTHON relay_server.py > "$LOGS/relay-stdout.log" 2> "$LOGS/relay-stderr.log" &

# Wait for it
for i in $(seq 1 10); do
    if curl -s http://localhost:8787/health >/dev/null 2>&1; then
        echo "✓ NCC Relay online (:8787)"
        read -p "Press Enter to close..."
        exit 0
    fi
    sleep 1
done

echo "✗ Relay failed to start. Checking logs:"
tail -20 "$LOGS/relay-stderr.log"
read -p "Press Enter to close..."
