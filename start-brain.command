#!/bin/bash
# Start NCL Brain from correct path
echo "============================================="
echo "  NCL BRAIN — Starting API Server"
echo "============================================="

cd /Users/natrix/dev/NCL || { echo "ERROR: Cannot cd to /Users/natrix/dev/NCL"; exit 1; }

# Kill existing brain if running
if lsof -ti:8800 >/dev/null 2>&1; then
    echo "Killing existing process on port 8800..."
    kill $(lsof -ti:8800) 2>/dev/null
    sleep 2
fi

# Activate venv if present
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
    echo "Using venv: $(which python3)"
else
    echo "No .venv found, using system Python"
fi

# Ensure chromadb is installed in venv
if ! python3 -c "import chromadb" 2>/dev/null; then
    echo "Installing chromadb into venv..."
    pip install chromadb 2>&1 | tail -3
    echo "✅ chromadb installed"
else
    echo "✅ chromadb OK"
fi

# Load .env
if [ -f .env ]; then
    set -a
    source .env
    set +a
    echo "Loaded .env (PAPERCLIP_URL=$PAPERCLIP_URL)"
fi

# Start the brain
echo "Starting NCL Brain on port 8800..."
exec uvicorn runtime.api.routes:versioned_app --host 0.0.0.0 --port 8800 --reload
