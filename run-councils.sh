#!/usr/bin/env bash
# NARTIX Intelligence Council Runner
# Usage:
#   ./run-councils.sh              Run both YouTube + X councils
#   ./run-councils.sh youtube      YouTube council only
#   ./run-councils.sh x            X (Twitter) council only
#   ./run-councils.sh --dry        Dry run (scrape only, no AI analysis)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NCL_ROOT="${SCRIPT_DIR}"
VENV="${NCL_ROOT}/.venv"
LOG_DIR="${NCL_ROOT}/logs"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  NARTIX Intelligence Council Runner${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Ensure log directory exists
mkdir -p "${LOG_DIR}"

# Activate venv if present
if [[ -d "${VENV}" ]]; then
    source "${VENV}/bin/activate"
    echo -e "${GREEN}✓${NC} Virtual environment activated"
else
    echo -e "${YELLOW}⚠${NC} No .venv found — using system Python"
fi

# Check required tools
check_dep() {
    if ! command -v "$1" &>/dev/null; then
        echo -e "${RED}✗${NC} Missing dependency: $1"
        echo "  Install with: $2"
        return 1
    fi
    echo -e "${GREEN}✓${NC} $1 available"
}

MISSING=0
check_dep python3 "pyenv install 3.12" || MISSING=1
check_dep yt-dlp "pip install yt-dlp" || MISSING=1

# Optional deps — warn but don't block
if ! python3 -c "import httpx" 2>/dev/null; then
    echo -e "${YELLOW}⚠${NC} httpx not installed (pip install httpx) — AI analysis will fail"
fi

if python3 -c "import twscrape" 2>/dev/null; then
    echo -e "${GREEN}✓${NC} twscrape available (X scraping fallback)"
else
    echo -e "${YELLOW}⚠${NC} twscrape not installed (pip install twscrape) — X scraping will use API/Grok only"
fi

if [[ $MISSING -eq 1 ]]; then
    echo -e "${RED}Cannot proceed — install missing dependencies${NC}"
    exit 1
fi

# Check for API keys
if [[ -z "${ANTHROPIC_API_KEY:-}" ]] && [[ -z "${XAI_API_KEY:-}" ]]; then
    # Try loading from .env
    if [[ -f "${NCL_ROOT}/.env" ]]; then
        set -a
        source "${NCL_ROOT}/.env"
        set +a
        echo -e "${GREEN}✓${NC} Loaded .env"
    elif [[ -f "${NCL_ROOT}/../.env" ]]; then
        set -a
        source "${NCL_ROOT}/../.env"
        set +a
        echo -e "${GREEN}✓${NC} Loaded ../.env"
    fi
fi

if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    echo -e "${GREEN}✓${NC} ANTHROPIC_API_KEY set"
elif [[ -n "${XAI_API_KEY:-}" ]]; then
    echo -e "${GREEN}✓${NC} XAI_API_KEY set (will use Grok)"
else
    echo -e "${YELLOW}⚠${NC} No API keys — will attempt Ollama local fallback"
fi

echo ""

# Parse arguments
MODE="--both"
DRY=""
SESSION_ID=""

for arg in "$@"; do
    case "$arg" in
        youtube|yt)  MODE="--youtube" ;;
        x|twitter)   MODE="--x" ;;
        both)        MODE="--both" ;;
        --dry|dry)   DRY="--dry" ;;
        --session-id=*) SESSION_ID="--session-id=${arg#*=}" ;;
        -h|--help)
            echo "Usage: $0 [youtube|x|both] [--dry] [--session-id=ID]"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown argument: $arg${NC}"
            echo "Usage: $0 [youtube|x|both] [--dry] [--session-id=ID]"
            exit 1
            ;;
    esac
done

echo -e "${CYAN}Mode:${NC} ${MODE#--}"
[[ -n "$DRY" ]] && echo -e "${YELLOW}DRY RUN — scrape only, no AI analysis${NC}"
echo ""

# Run the council
cd "${NCL_ROOT}"
python3 -m runtime.councils.runner ${MODE} ${DRY} ${SESSION_ID}

EXIT_CODE=$?
if [[ $EXIT_CODE -eq 0 ]]; then
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}  Council session complete${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "  Reports: ${NCL_ROOT}/intelligence-scan/council-reports/"
    echo -e "  Signals: ${NCL_ROOT}/intelligence-scan/signals/"
    echo -e "  Alerts:  ${NCL_ROOT}/intelligence-scan/alerts/"
    echo -e "  Logs:    ${LOG_DIR}/council-runner.log"
else
    echo ""
    echo -e "${RED}Council session failed (exit code: $EXIT_CODE)${NC}"
    echo -e "Check logs: ${LOG_DIR}/council-runner.log"
    exit $EXIT_CODE
fi
