#!/bin/bash
TOK=QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU
BASE=http://100.72.223.123:8800

echo '=== bounce ==='
launchctl kickstart -k "gui/$(id -u)/com.resonanceenergy.ncl-brain" 2>&1
sleep 15

for i in 1 2 3 4 5 6 7 8; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -H "Authorization: Bearer $TOK" "$BASE/health" 2>/dev/null)
  echo "  health attempt $i: $code"
  if [ "$code" = '200' ]; then break; fi
  sleep 4
done

echo ''
echo '=== fire morning-brief/pro ==='
curl -s -X POST -H "Authorization: Bearer $TOK" --max-time 180 "$BASE/intelligence/morning-brief/pro/fire" > /tmp/brief_fire.json 2>&1
echo "  fire response: $(head -c 300 /tmp/brief_fire.json)"
echo ''
echo '=== sleep 90s for pipeline ==='
sleep 90
echo ''
echo '=== fetch today brief ==='
curl -s -H "Authorization: Bearer $TOK" --max-time 30 "$BASE/intelligence/morning-brief/pro" > /tmp/brief_out.json
/usr/bin/python3 << 'PY'
import json
d = json.load(open('/tmp/brief_out.json'))
synth = d.get('synthesis') or {}
print(f"  date: {d.get('date')}")
print(f"  has yesterday_recap: {bool(synth.get('yesterday_recap'))}")
yr = synth.get('yesterday_recap') or {}
if yr:
    print(f"    headline: {(yr.get('headline') or '')[:100]}")
    print(f"    scoreboard: {yr.get('scoreboard')}")
    print(f"    lesson: {(yr.get('lesson') or '')[:100]}")
    print(f"    drift_flags: {yr.get('drift_flags')}")
print(f"  pipeline_meta: {json.dumps(d.get('pipeline_meta') or {}, default=str)[:400]}")
brief_text = d.get('brief_text') or d.get('rendered_text') or ''
if brief_text:
    print()
    print(f"  --- rendered brief first 1200 chars ---")
    print(brief_text[:1200])
PY
