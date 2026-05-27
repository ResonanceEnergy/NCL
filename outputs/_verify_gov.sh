#!/bin/bash
set -a
. /Users/natrix/dev/NCL/.env
set +a
T="$STRIKE_AUTH_TOKEN"
B="http://100.72.223.123:8800"

# Reset drawdown to green first via override clear + recompute against
# a healthy NAV so we get clean test output.
curl -sS --max-time 5 -X POST -H "Authorization: Bearer $T" \
  -H "Content-Type: application/json" \
  -d '{"peak_nav_cad":null}' \
  "$B/portfolio/drawdown/peak-override" > /dev/null
curl -sS --max-time 5 -X POST -H "Authorization: Bearer $T" \
  "$B/portfolio/drawdown/recompute" > /dev/null

echo "=== GET /portfolio/risk-governor/heat ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/portfolio/risk-governor/heat" | /opt/homebrew/bin/python3 -m json.tool

echo
echo "=== POST /portfolio/risk-governor/check goat 500 R, NAV=100K ==="
curl -sS --max-time 8 -X POST -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
  -d '{"strategy_tag":"goat","R_dollars_proposed":500,"nav_cad_override":100000}' \
  "$B/portfolio/risk-governor/check" | /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
print('decision:', d['decision'], 'approved:', d['approved'])
print('reason:', d['reasons'][0])
print('effective_R:', d['effective_R_dollars'])
"

echo
echo "=== POST /portfolio/risk-governor/check bravo 4K R (breaches cap), NAV=100K ==="
curl -sS --max-time 8 -X POST -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
  -d '{"strategy_tag":"bravo","R_dollars_proposed":4000,"nav_cad_override":100000}' \
  "$B/portfolio/risk-governor/check" | /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
print('decision:', d['decision'], 'approved:', d['approved'])
print('reason:', d['reasons'][0])
"
echo DONE
