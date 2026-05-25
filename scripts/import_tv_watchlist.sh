#!/usr/bin/env bash
set -e
TOKEN="${STRIKE_TOKEN:-QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU}"
INPUT="${1:-/Users/natrix/dev/NCL/scripts/natrix_tv_watchlist.txt}"
REPLACE="${2:-false}"

# Build a proper JSON wrapper with python so quotes don't bite us
PAYLOAD=$(REPLACE_FLAG="$REPLACE" INPUT_FILE="$INPUT" python3 -c "
import json, os
t = open(os.environ['INPUT_FILE']).read()
r = os.environ['REPLACE_FLAG'].lower() in ('true', '1', 'yes')
print(json.dumps({'text': t, 'replace': r}))
")

echo "[tv-import] POST /stocks/watchlist/import/tradingview replace=$REPLACE ..."
curl -s -m 30 -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    http://100.72.223.123:8800/stocks/watchlist/import/tradingview \
  | python3 -m json.tool
