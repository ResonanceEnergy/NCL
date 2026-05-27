#!/bin/bash
set -a
. /Users/natrix/dev/NCL/.env
set +a
T="$STRIKE_AUTH_TOKEN"
B="http://100.72.223.123:8800"

echo "=== GET /auto-trader/bandit/posteriors (initial — empty until trades close) ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/portfolio/auto-trader/bandit/posteriors" | /opt/homebrew/bin/python3 -m json.tool

echo
echo "=== POST /auto-trader/bandit/record-result (synthetic goat WIN) ==="
curl -sS --max-time 8 -X POST -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
  -d '{"strategy":"goat","win":true,"R_multiple":2.0,"trade_idea_id":"verify-1"}' \
  "$B/portfolio/auto-trader/bandit/record-result" | /opt/homebrew/bin/python3 -m json.tool | head -15

echo
echo "=== POST /auto-trader/bandit/record-result (synthetic bravo LOSS) ==="
curl -sS --max-time 8 -X POST -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
  -d '{"strategy":"bravo","win":false,"R_multiple":-1.0,"trade_idea_id":"verify-2"}' \
  "$B/portfolio/auto-trader/bandit/record-result" | /opt/homebrew/bin/python3 -m json.tool | head -10

echo
echo "=== GET /auto-trader/bandit/ranked ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/portfolio/auto-trader/bandit/ranked" | /opt/homebrew/bin/python3 -m json.tool

echo
echo "=== POST /auto-trader/bandit/sample-arm goat vs bravo ==="
for i in 1 2 3 4 5; do
  curl -sS --max-time 8 -X POST -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
    -d '{"candidates":["goat","bravo"]}' "$B/portfolio/auto-trader/bandit/sample-arm" | /opt/homebrew/bin/python3 -c "
import sys, json
print('  pick:', json.load(sys.stdin)['picked'])
"
done

echo DONE
