#!/bin/bash
set -a
. /Users/natrix/dev/NCL/.env
set +a
T="$STRIKE_AUTH_TOKEN"
B="http://100.72.223.123:8800"

echo "=== GET /portfolio/risk-state (initial — should have NVDA from smoke) ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/portfolio/risk-state" | /opt/homebrew/bin/python3 -m json.tool | head -40

echo
echo "=== PATCH /portfolio/risk-state (set AAPL) ==="
curl -sS --max-time 8 -X PATCH -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
  -d '{"broker":"MOOMOO","account_id":"M1","symbol":"AAPL","qty":50,"entry_price":195,"stop_price":188,"stop_type":"price","stop_basis":"below 50d SMA","target_price":215,"thesis":"Buyback acceleration + Vision Pro 2","metadata":{"strategy_tag":"bravo"}}' \
  "$B/portfolio/risk-state" | /opt/homebrew/bin/python3 -m json.tool

echo
echo "=== GET /portfolio/risk-state/moomoo:m1:AAPL ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/portfolio/risk-state/moomoo:m1:AAPL" | /opt/homebrew/bin/python3 -m json.tool | head -25

echo
echo "=== GET /portfolio/risk-state aggregate (should show 2 positions, sum R) ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/portfolio/risk-state" | /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
print('aggregate:', json.dumps(d.get('aggregate', {}), indent=2))
print('position count:', len(d.get('positions', {})))
"

echo
echo "=== /portfolio/positions has R-field enrichment (no live positions, but the shape is exercised) ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/portfolio/positions" | /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
pos = d.get('positions', [])
print('total_positions:', d.get('total_positions'))
if pos:
    print('first position keys include:', sorted([k for k in pos[0].keys() if k in ('risk_status', 'R_dollars', 'position_key', 'stop_price', 'thesis')]))
else:
    print('(no live positions to enrich — adapter side is offline)')
"
echo DONE
