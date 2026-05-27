#!/bin/bash
set -a
. /Users/natrix/dev/NCL/.env
set +a
TOKEN="$STRIKE_AUTH_TOKEN"
echo "=== /health ==="
curl -sS --max-time 5 http://100.72.223.123:8800/health
echo
echo "=== /system/health/rollup ==="
curl -sS --max-time 15 -H "Authorization: Bearer $TOKEN" \
  http://100.72.223.123:8800/system/health/rollup | \
  /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
print('overall:', d.get('overall'))
print('brain:', (d.get('brain') or {}).get('status'))
mem = d.get('memory') or {}
print('memory.units:', mem.get('units'), 'status:', mem.get('status'))
sch = d.get('scheduler') or {}
print('scheduler.active_tasks:', sch.get('active_tasks'), 'status:', sch.get('status'))
"
echo "=== /intelligence/rotation (live verify) ==="
curl -sS --max-time 10 -H "Authorization: Bearer $TOKEN" \
  http://100.72.223.123:8800/intelligence/rotation | \
  /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
print('date:', d.get('date'))
r = d.get('rotation') or {}
print('benchmark:', r.get('benchmark'), 'breadth.pct:', (r.get('breadth') or {}).get('pct'))
print('by_quadrant:', r.get('by_quadrant'))
c = d.get('cycle_phase') or {}
cls = (c.get('classification') or {})
print('cycle.phase:', cls.get('phase'), 'confidence:', cls.get('confidence'))
"
