#!/bin/bash
set -a
. /Users/natrix/dev/NCL/.env
set +a
T="$STRIKE_AUTH_TOKEN"
B="http://100.72.223.123:8800"

echo "=== GET /portfolio/drawdown (initial) ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/portfolio/drawdown" | /opt/homebrew/bin/python3 -m json.tool

echo
echo "=== POST /portfolio/drawdown/recompute (live NAV) ==="
curl -sS --max-time 8 -X POST -H "Authorization: Bearer $T" "$B/portfolio/drawdown/recompute" | /opt/homebrew/bin/python3 -m json.tool

echo
echo "=== POST /portfolio/drawdown/peak-override (test) ==="
curl -sS --max-time 8 -X POST -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
  -d '{"peak_nav_cad":50000,"note":"test override (Wave 14J J0c verify)"}' \
  "$B/portfolio/drawdown/peak-override" | /opt/homebrew/bin/python3 -m json.tool | head -15

echo
echo "=== POST /portfolio/drawdown/recompute (with override pinned) ==="
curl -sS --max-time 8 -X POST -H "Authorization: Bearer $T" "$B/portfolio/drawdown/recompute" | /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'nav=\${d[\"current_nav_cad\"]:.2f}  peak=\${d[\"peak_nav_cad\"]:.2f}  '
      f'dd={d[\"drawdown_pct\"]}%  band={d[\"band\"]}  mult={d[\"sizing_multiplier\"]}')
print(f'manual_override={d.get(\"manual_peak_override\")}  notes={d.get(\"notes\")!r}')
"

echo
echo "=== Clear override ==="
curl -sS --max-time 8 -X POST -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
  -d '{"peak_nav_cad":null,"note":""}' \
  "$B/portfolio/drawdown/peak-override" | /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
print('override cleared. manual_peak_override:', d.get('manual_peak_override'))
"

echo
echo "=== Verify scheduler task is running ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/autonomous/loops" | /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
loops = d.get('loops') or d
if not isinstance(loops, list):
    loops = []
for L in loops:
    if 'drawdown' in L.get('name', ''):
        print(L.get('name'), '|', L.get('status'), '|', 'last_run:', L.get('last_run'))
"
echo DONE
