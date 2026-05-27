#!/bin/bash
set -a
. /Users/natrix/dev/NCL/.env
set +a
TOKEN="$STRIKE_AUTH_TOKEN"

echo "=== working-context/refresh ==="
curl -sS --max-time 30 -w "\nHTTP %{http_code} %{time_total}s\n" \
  -X POST "http://100.72.223.123:8800/memory/working-context/refresh" \
  -H "Authorization: Bearer $TOKEN" | head -c 600

echo
echo "=== claude-md-refresh status (via /autonomous/loops) ==="
curl -sS --max-time 10 "http://100.72.223.123:8800/autonomous/loops" \
  -H "Authorization: Bearer $TOKEN" \
  | /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
loops = d.get('loops') or d if isinstance(d, list) else d.get('loops', [])
if isinstance(loops, list):
    for L in loops:
        n = L.get('name','')
        if 'claude' in n or 'working' in n:
            print(n, '|', L.get('status','?'), '|', L.get('last_run','?'))
"
echo DONE
