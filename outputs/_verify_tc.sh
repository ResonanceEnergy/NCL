#!/bin/bash
set -a
. /Users/natrix/dev/NCL/.env
set +a
T="$STRIKE_AUTH_TOKEN"
B="http://100.72.223.123:8800"

echo "=== /portfolio/trade-costs/today ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/portfolio/trade-costs/today" | /opt/homebrew/bin/python3 -m json.tool | head -20

echo
echo "=== POST /portfolio/trade-costs/record (live ping) ==="
curl -sS --max-time 8 -X POST -H "Authorization: Bearer $T" \
  -H "Content-Type: application/json" \
  -d '{"broker":"IBKR","action":"commission","amount_usd":0.65,"symbol":"NVDA","asset_class":"equity","strategy_tag":"goat","metadata":{"first_strike_test":true,"fill_id":"x9k2"}}' \
  "$B/portfolio/trade-costs/record"

echo
echo "=== /portfolio/trade-costs/ledger?limit=5 ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/portfolio/trade-costs/ledger?limit=5" | /opt/homebrew/bin/python3 -m json.tool | head -30

echo
echo "=== /portfolio/trade-costs/today (after) ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/portfolio/trade-costs/today" | /opt/homebrew/bin/python3 -m json.tool | head -20

echo DONE
