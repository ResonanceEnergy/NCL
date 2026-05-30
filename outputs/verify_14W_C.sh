#!/bin/bash
# Wave 14W-C verification — lane endpoints
set -u
TOKEN=$(grep -E '^STRIKE_AUTH_TOKEN=' /Users/natrix/dev/NCL/.env | cut -d= -f2- | tr -d '"' | tr -d "'")
H="-H Authorization:Bearer\ ${TOKEN}"
BASE="http://100.72.223.123:8800"

echo "=== /memory/lane-stats ==="
curl -sS --max-time 15 -H "Authorization: Bearer ${TOKEN}" "${BASE}/memory/lane-stats" | python3 -m json.tool

for L in portfolio intel memory calendar journal unknown; do
  echo
  echo "=== lane=${L} ==="
  curl -sS --max-time 15 -H "Authorization: Bearer ${TOKEN}" "${BASE}/memory/by-lane?lane=${L}&limit=3" \
    | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(json.dumps({k: d[k] for k in d if k != 'results'}, indent=2))
for r in d.get('results', [])[:3]:
    print('  -', r.get('source','?')[:32], r.get('unit_id','')[:20],
          'gate=' + str(r.get('lane_gate_passed','?'))[:1],
          r.get('content','')[:60])
"
done
