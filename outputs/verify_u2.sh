#!/bin/bash
TOK=$(grep STRIKE_AUTH_TOKEN ~/dev/NCL/.env | cut -d= -f2 | tr -d '"')
BASE=http://100.72.223.123:8800

echo "=== factor-attribution ==="
curl -s -H "Authorization: Bearer $TOK" $BASE/portfolio/auto-trader/factor-attribution | head -c 250
echo
echo "=== portfolio-drift (ADWIN state) ==="
curl -s -H "Authorization: Bearer $TOK" $BASE/portfolio/auto-trader/portfolio-drift | head -c 350
echo
echo "=== monthly-review fire (force) ==="
curl -s -X POST -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' -d '{"force":true}' $BASE/portfolio/auto-trader/monthly-review/fire | head -c 500
echo
echo "=== monthly review file? ==="
ls -la ~/dev/NCL/data/portfolio/auto_trader/monthly_reviews/ 2>&1
echo "=== loops named auto-trader ==="
curl -s -H "Authorization: Bearer $TOK" $BASE/autonomous/loops > /tmp/loops.json
/opt/homebrew/bin/python3 -c "
import json
d = json.load(open('/tmp/loops.json'))
loops = d.get('loops', d if isinstance(d, list) else [])
for l in loops:
    name = l.get('name', '') if isinstance(l, dict) else str(l)
    if 'auto-trader' in name:
        last = l.get('last_run') or l.get('last_run_iso', '') if isinstance(l, dict) else ''
        print(f'  {name}  last={last[:19] if last else \"never\"}')"
