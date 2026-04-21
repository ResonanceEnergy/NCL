#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  NCL Brain — Smoke Test                                                ║
# ║  Verifies the brain is running and all endpoints respond.              ║
# ║  Usage: ./smoke-test.sh [--host localhost] [--port 8800]               ║
# ╚══════════════════════════════════════════════════════════════════════════╝

HOST="localhost"
PORT="8800"
BASE="http://$HOST:$PORT"

while [[ $# -gt 0 ]]; do
    case $1 in
        --host) HOST="$2"; BASE="http://$HOST:$PORT"; shift 2 ;;
        --port) PORT="$2"; BASE="http://$HOST:$PORT"; shift 2 ;;
        *) shift ;;
    esac
done

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

PASS=0
FAIL=0
SKIP=0

check() {
    local name="$1"
    local method="$2"
    local path="$3"
    local expected="${4:-200}"

    if [ "$method" = "GET" ]; then
        STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$BASE$path" 2>/dev/null)
    else
        STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 -X POST "$BASE$path" -H "Content-Type: application/json" -d '{}' 2>/dev/null)
    fi

    if [ "$STATUS" = "$expected" ] || [ "$STATUS" = "200" ] || [ "$STATUS" = "422" ]; then
        echo -e "  ${GREEN}[PASS]${NC} $name ($STATUS)"
        PASS=$((PASS + 1))
    elif [ "$STATUS" = "000" ]; then
        echo -e "  ${RED}[DOWN]${NC} $name (no response)"
        FAIL=$((FAIL + 1))
    else
        echo -e "  ${YELLOW}[WARN]${NC} $name ($STATUS)"
        SKIP=$((SKIP + 1))
    fi
}

echo ""
echo -e "${BOLD}NCL BRAIN SMOKE TEST${NC}"
echo -e "Target: $BASE"
echo ""

# Check if server is up at all
echo -e "${BOLD}── Core ──${NC}"
check "Health"                    GET  "/health"
check "Root"                      GET  "/"

echo ""
echo -e "${BOLD}── Dashboards ──${NC}"
check "Main Dashboard"            GET  "/dashboard"
check "LDE Dashboard"             GET  "/lde/dashboard"
check "Review Queue Dashboard"    GET  "/review-queue/dashboard"
check "Memory Dashboard"          GET  "/memory/dashboard"

echo ""
echo -e "${BOLD}── Sprint 1: Events + Search ──${NC}"
check "Search Stats"              GET  "/search/stats"
check "Shortcuts Config"          GET  "/shortcuts/config"

echo ""
echo -e "${BOLD}── Sprint 2: Telemetry ──${NC}"
check "Telemetry Config"          GET  "/telemetry/config"
check "Telemetry Stats"           GET  "/telemetry/stats"
check "Availability Dashboard"    GET  "/availability/dashboard"
check "Availability Alerts"       GET  "/availability/alerts"

echo ""
echo -e "${BOLD}── Sprint 2: Governance ──${NC}"
check "Policy Rules"              GET  "/governance/policy/rules"
check "Pending Actions"           GET  "/governance/actions/pending"
check "Emergency Stop Status"     GET  "/governance/emergency-stop"
check "Governance Audit"          GET  "/governance/audit"

echo ""
echo -e "${BOLD}── Sprint 2: Evaluation ──${NC}"
check "Evaluation Results"        GET  "/evaluation/results"
check "Evaluation Summary"        GET  "/evaluation/summary"

echo ""
echo -e "${BOLD}── Sprint 3: Review Queue ──${NC}"
check "Queue Items"               GET  "/review-queue/items"
check "Queue Stats"               GET  "/review-queue/stats"

echo ""
echo -e "${BOLD}── Sprint 4: Council Runner ──${NC}"
check "Council Runs"              GET  "/council-runner/runs"
check "Council Stats"             GET  "/council-runner/stats"

echo ""
echo -e "${BOLD}── Hardening: UNI Research ──${NC}"
check "UNI Results"               GET  "/uni/results"
check "UNI Stats"                 GET  "/uni/stats"

echo ""
echo -e "${BOLD}── Hardening: Memory ──${NC}"
check "Memory Stats"              GET  "/memory/stats"
check "Memory Timeline"           GET  "/memory/timeline"
check "Memory Query"              GET  "/memory/query"

echo ""
echo -e "${BOLD}── Hardening: Deployment ──${NC}"
check "Deployment Status"         GET  "/deployment/status"
check "Deployment Uptime"         GET  "/deployment/uptime"
check "Deployment Dashboard"      GET  "/deployment/dashboard"

echo ""
echo -e "${BOLD}── Pump Pipeline ──${NC}"
check "Pump Pending"              GET  "/pump/pending"
check "Mandates"                  GET  "/mandates"

echo ""
echo "──────────────────────────────────────"
TOTAL=$((PASS + FAIL + SKIP))
echo -e "  ${GREEN}Passed: $PASS${NC}  ${RED}Failed: $FAIL${NC}  ${YELLOW}Warn: $SKIP${NC}  Total: $TOTAL"
echo ""

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}${BOLD}All endpoints responding.${NC}"
    exit 0
elif [ $FAIL -eq $TOTAL ]; then
    echo -e "${RED}${BOLD}Server not running. Start with: ./run.sh${NC}"
    exit 1
else
    echo -e "${YELLOW}${BOLD}Some endpoints not responding — check logs.${NC}"
    exit 1
fi
