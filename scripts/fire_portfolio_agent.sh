#!/usr/bin/env bash
# Manual trigger for the Portfolio Analyst Agent.
set -e
TOKEN="${STRIKE_TOKEN:-QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU}"
OUT="/tmp/portfolio_agent_run.json"
echo "[fire-PO-agent] POST /portfolio/analyst/run dry_run=false ..."
HTTP=$(curl -s -m 240 -o "$OUT" -w "%{http_code}" \
    -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"dry_run": false}' \
    http://100.72.223.123:8800/portfolio/analyst/run)
echo "[fire-PO-agent] http=$HTTP bytes=$(wc -c < "$OUT")"
echo "---"
head -c 4000 "$OUT"
echo
echo "---"
echo "(full body at $OUT)"
