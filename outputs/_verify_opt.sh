#!/bin/bash
set -a
. /Users/natrix/dev/NCL/.env
set +a
T="$STRIKE_AUTH_TOKEN"
B="http://100.72.223.123:8800"

echo "=== GET /portfolio/options/greeks ==="
curl -sS --max-time 12 -H "Authorization: Bearer $T" "$B/portfolio/options/greeks" | /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
print('position_count:', d.get('position_count'))
print('net:', d.get('net'))
print('budgets:', d.get('budgets'))
print('flags:', d.get('flags'))
"

echo
echo "=== GET /portfolio/options/dte-watch?threshold=21 ==="
curl -sS --max-time 12 -H "Authorization: Bearer $T" "$B/portfolio/options/dte-watch?threshold=21" | /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
print('threshold:', d.get('threshold_days'), 'count:', d.get('count'))
for c in d.get('candidates', [])[:5]:
    print(' ', c)
"

echo
echo "=== GET /portfolio/options/pin-risk?pct=1.0 ==="
curl -sS --max-time 12 -H "Authorization: Bearer $T" "$B/portfolio/options/pin-risk?pct=1.0" | /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
print('pct:', d.get('pct_threshold'), 'count:', d.get('count'))
for c in d.get('candidates', [])[:5]:
    print(' ', c)
"
echo DONE
