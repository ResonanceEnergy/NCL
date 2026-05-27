#!/bin/bash
set -a
. /Users/natrix/dev/NCL/.env
set +a
TOKEN="$STRIKE_AUTH_TOKEN"
echo "=== bootstrap-claude-md ==="
curl -sS --max-time 120 -w "\nHTTP %{http_code}  %{time_total}s\n" \
  -X POST "http://100.72.223.123:8800/memory/bootstrap-claude-md" \
  -H "Authorization: Bearer $TOKEN"
echo
echo "=== working-context/refresh ==="
curl -sS --max-time 60 -w "\nHTTP %{http_code}  %{time_total}s\n" \
  -X POST "http://100.72.223.123:8800/memory/working-context/refresh" \
  -H "Authorization: Bearer $TOKEN"
echo
echo "=== system/health/rollup (summary) ==="
curl -sS --max-time 15 "http://100.72.223.123:8800/system/health/rollup" \
  -H "Authorization: Bearer $TOKEN" | /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
print('overall:', d.get('overall'))
print('brain.status:', (d.get('brain') or {}).get('status'))
mem = d.get('memory') or {}
print('memory.units:', mem.get('units'))
sch = d.get('scheduler') or {}
print('scheduler.active_tasks:', sch.get('active_tasks'))
"
echo "DONE"
