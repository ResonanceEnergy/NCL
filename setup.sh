#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  NCL Brain — Full Setup Script                                         ║
# ║  Run once on a fresh Mac to get everything installed and configured.    ║
# ║  Usage: chmod +x setup.sh && ./setup.sh                                ║
# ╚══════════════════════════════════════════════════════════════════════════╝

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

NCL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo -e "${CYAN}${BOLD}"
echo "╔══════════════════════════════════════════════════╗"
echo "║       NCL BRAIN — SETUP                         ║"
echo "║       RESONANCE ENERGY / NARTIX                 ║"
echo "╚══════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── Step 1: Check Python ────────────────────────────────────────────────────
echo -e "${BOLD}[1/7] Checking Python...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}  Python 3 not found. Install: brew install python@3.12${NC}"
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 12 ]); then
    echo -e "${RED}  Python 3.12+ required (found $PY_VERSION). Install: brew install python@3.12${NC}"
    exit 1
fi
echo -e "${GREEN}  Python $PY_VERSION${NC}"

# ── Step 2: Create directories ──────────────────────────────────────────────
echo -e "${BOLD}[2/7] Creating directories...${NC}"
mkdir -p ~/NCL/data
mkdir -p ~/NCL/config
mkdir -p ~/NCL/logs
mkdir -p ~/NCL/data/memory
mkdir -p ~/NCL/data/telemetry
mkdir -p ~/NCL/data/governance
mkdir -p ~/NCL/data/evaluation
mkdir -p ~/NCL/data/review_queue
mkdir -p ~/NCL/data/council_runner
mkdir -p ~/NCL/data/uni
mkdir -p ~/NCL/data/lde
echo -e "${GREEN}  ~/NCL/data, ~/NCL/config, ~/NCL/logs created${NC}"

# ── Step 3: Install Python dependencies ─────────────────────────────────────
echo -e "${BOLD}[3/7] Installing Python dependencies...${NC}"
cd "$NCL_DIR"

pip3 install --upgrade pip --quiet

# Core deps
pip3 install -r requirements.txt --quiet 2>&1 | tail -3
echo -e "${GREEN}  Core dependencies installed${NC}"

# Install the package itself (editable mode)
pip3 install -e . --quiet 2>&1 | tail -1
echo -e "${GREEN}  NCL package installed (editable)${NC}"

# ── Step 4: Setup .env ──────────────────────────────────────────────────────
echo -e "${BOLD}[4/7] Setting up environment...${NC}"
if [ ! -f "$NCL_DIR/.env" ]; then
    cp "$NCL_DIR/.env.example" "$NCL_DIR/.env"
    echo -e "${YELLOW}  Created .env from template — EDIT THIS FILE with your API keys:${NC}"
    echo -e "${YELLOW}    nano $NCL_DIR/.env${NC}"
else
    echo -e "${GREEN}  .env already exists${NC}"
fi

# Generate STRIKE_AUTH_TOKEN if not set
if grep -q "^STRIKE_AUTH_TOKEN=$" "$NCL_DIR/.env" 2>/dev/null; then
    TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/^STRIKE_AUTH_TOKEN=$/STRIKE_AUTH_TOKEN=$TOKEN/" "$NCL_DIR/.env"
    else
        sed -i "s/^STRIKE_AUTH_TOKEN=$/STRIKE_AUTH_TOKEN=$TOKEN/" "$NCL_DIR/.env"
    fi
    echo -e "${GREEN}  Auto-generated STRIKE_AUTH_TOKEN: $TOKEN${NC}"
    echo -e "${YELLOW}  Copy this token into your iOS Shortcuts${NC}"
fi

# ── Step 5: Setup Ollama (optional) ─────────────────────────────────────────
echo -e "${BOLD}[5/7] Checking Ollama (local models)...${NC}"
if command -v ollama &> /dev/null; then
    echo -e "${GREEN}  Ollama installed${NC}"
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo -e "${GREEN}  Ollama server running${NC}"
    else
        echo -e "${YELLOW}  Ollama installed but not running. Start with: ollama serve${NC}"
    fi
else
    echo -e "${YELLOW}  Ollama not installed (optional — provides free local model fallback)${NC}"
    echo -e "${YELLOW}  Install: brew install ollama${NC}"
    echo -e "${YELLOW}  Then: ollama serve && ollama pull qwen3:32b${NC}"
fi

# ── Step 6: Validate config ─────────────────────────────────────────────────
echo -e "${BOLD}[6/7] Validating configuration...${NC}"
python3 -c "
import sys
sys.path.insert(0, '$NCL_DIR')
from runtime.api.config import load_config
config = load_config()
print(f'  Service: {config.service_name} v{config.service_version}')
print(f'  Port: {config.port}')
print(f'  Data: {config.data_dir}')
print(f'  Anthropic key: {\"SET\" if config.anthropic_api_key and config.anthropic_api_key != \"sk-ant-...\" else \"NOT SET\"}')
print(f'  xAI key: {\"SET\" if config.xai_api_key else \"NOT SET\"}')
print(f'  Google key: {\"SET\" if config.google_api_key else \"NOT SET\"}')
print(f'  OpenAI key: {\"SET\" if config.openai_api_key else \"NOT SET\"}')
print(f'  YouTube key: {\"SET\" if config.youtube_api_key else \"NOT SET\"}')
print(f'  X Bearer: {\"SET\" if config.x_bearer_token else \"NOT SET\"}')
print(f'  Ollama: {config.ollama_host}')
print(f'  Strike token: {\"SET\" if config.strike_auth_token else \"NOT SET\"}')
" 2>&1 || echo -e "${RED}  Config validation failed — check .env file${NC}"

# ── Step 7: Syntax check ────────────────────────────────────────────────────
echo -e "${BOLD}[7/7] Verifying codebase...${NC}"
cd "$NCL_DIR"
RESULT=$(python3 -c "
import ast, sys
from pathlib import Path
passed = failed = 0
for f in sorted(Path('runtime').rglob('*.py')):
    try:
        ast.parse(f.read_text(), filename=str(f))
        passed += 1
    except SyntaxError as e:
        failed += 1
        print(f'  FAIL: {f}: {e}', file=sys.stderr)
print(f'{passed} files OK, {failed} failed')
sys.exit(1 if failed else 0)
" 2>&1)
echo -e "${GREEN}  $RESULT${NC}"

# ── Done ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════╗"
echo "║  SETUP COMPLETE                                  ║"
echo "╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BOLD}Next steps:${NC}"
echo ""
echo -e "  1. ${YELLOW}Edit your API keys:${NC}"
echo -e "     nano $NCL_DIR/.env"
echo ""
echo -e "  2. ${YELLOW}Start the brain:${NC}"
echo -e "     cd $NCL_DIR && ./run.sh"
echo ""
echo -e "  3. ${YELLOW}Open dashboards:${NC}"
echo -e "     http://localhost:8800/dashboard"
echo -e "     http://localhost:8800/lde/dashboard"
echo -e "     http://localhost:8800/review-queue/dashboard"
echo -e "     http://localhost:8800/memory/dashboard"
echo ""
echo -e "  4. ${YELLOW}Install 24/7 daemons (optional):${NC}"
echo -e "     ./runtime/deployment/install_services.sh"
echo ""
echo -e "  5. ${YELLOW}Run tests:${NC}"
echo -e "     pip install pytest pytest-asyncio && pytest tests/ -v"
echo ""
