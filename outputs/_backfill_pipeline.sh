#!/bin/bash
TOK=QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU
BASE=http://100.72.223.123:8800

echo "=== STEP 1: Fire auto-trader EOD summary ==="
curl -s -X POST -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"force":true}' --max-time 30 \
  "$BASE/portfolio/auto-trader/eod-summary" | head -c 800
echo ""
echo ""

echo "=== STEP 2: Fire morning brief (Pro pipeline) ==="
curl -s -X POST -H "Authorization: Bearer $TOK" --max-time 180 \
  "$BASE/intelligence/morning-brief/pro/fire" | head -c 600
echo ""
echo ""

echo "=== STEP 3: Re-fire afternoon debrief (should have data now) ==="
curl -s -X POST -H "Authorization: Bearer $TOK" --max-time 120 \
  "$BASE/intelligence/afternoon-debrief/fire" > /tmp/debrief.json
/usr/bin/python3 << 'PY'
import json
d = json.load(open('/tmp/debrief.json'))
print('=== DEBRIEF AFTER BACKFILL ===')
print(f"date: {d.get('date')}")
print(f"elapsed: {d.get('elapsed_s')}s")
print(f"pack_meta: {d.get('pack_meta')}")
synth = d.get('synthesis', {})
print(f"headline: {synth.get('headline', '')[:120]}")
sb = synth.get('today_scoreboard', {})
if sb:
    print(f"scoreboard: closes={sb.get('closes_today', sb.get('closes'))} "
          f"W={sb.get('winners',0)}/L={sb.get('losers',0)} R={sb.get('total_r',0):+.2f}")
nwf = synth.get('night_watch_focus', [])
if nwf:
    print(f"night_watch_focus: {nwf[:2]}")
PY
