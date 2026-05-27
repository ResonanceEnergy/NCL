#!/bin/bash
set -a
. /Users/natrix/dev/NCL/.env
set +a
T="$STRIKE_AUTH_TOKEN"
B="http://100.72.223.123:8800"

echo "=== /autonomous/loops (looking for ncl-auto-trader-loop) ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/autonomous/loops" 2>&1 | /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
loops = d.get('loops') if isinstance(d, dict) else d
if not isinstance(loops, list):
    loops = []
auto = [l for l in loops if 'auto-trader' in l.get('name', '')]
print(f'auto-trader loops found: {len(auto)}')
for l in auto:
    print(' ', l.get('name'), '|', l.get('status', '?'), '|', 'last:', l.get('last_run', '?'))
"

echo
echo "=== /auto-trader/status ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/portfolio/auto-trader/status" | /opt/homebrew/bin/python3 -m json.tool | head -22

echo
echo "=== /auto-trader/reasoning-chains (should be empty until ideas open) ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/portfolio/auto-trader/reasoning-chains?limit=3" | /opt/homebrew/bin/python3 -m json.tool

echo DONE
