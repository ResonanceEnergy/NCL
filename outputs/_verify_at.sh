#!/bin/bash
set -a
. /Users/natrix/dev/NCL/.env
set +a
T="$STRIKE_AUTH_TOKEN"
B="http://100.72.223.123:8800"

echo "=== GET /auto-trader/status (default: inactive) ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/portfolio/auto-trader/status" | /opt/homebrew/bin/python3 -m json.tool | head -20
echo
echo "=== GET /auto-trader/policy ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/portfolio/auto-trader/policy" | /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
print('revision:', d['revision'])
print('min_R_R_ratio:', d['min_R_R_ratio'])
print('max_opens_per_day:', d['max_opens_per_day'])
print('allow_counter_trend:', d['allow_counter_trend'])
"
echo
echo "=== POST /auto-trader/eligibility-check (passing idea) ==="
curl -sS --max-time 8 -X POST -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
  -d '{"idea":{"trade_idea_id":"x","ticker":"NVDA","strategy_tag":"goat","thesis":"Blackwell ramp + AI capex re-acceleration thesis","entry_price":180,"stop_price":170,"target_price":220,"R_per_share":10,"stop_type":"atr","sources":["s1"],"rotation_stance":"with_trend","breadth_veto":{"vetoed":false}},"governor_decision":{"approved":true,"band":"green"}}' \
  "$B/portfolio/auto-trader/eligibility-check"
echo
echo
echo "=== POST /auto-trader/eligibility-check (governor-rejected halt band) ==="
curl -sS --max-time 8 -X POST -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
  -d '{"idea":{"ticker":"X","thesis":"placeholder thesis text here for length","entry_price":100,"stop_price":95,"target_price":115,"R_per_share":5,"stop_type":"price","sources":["s1"]},"governor_decision":{"approved":false,"band":"halt","reasons":["Drawdown band=halt"]}}' \
  "$B/portfolio/auto-trader/eligibility-check"
echo
echo
echo "=== POST /auto-trader/resume ==="
curl -sS --max-time 8 -X POST -H "Authorization: Bearer $T" "$B/portfolio/auto-trader/resume"
echo
echo
echo "=== POST /auto-trader/pause ==="
curl -sS --max-time 8 -X POST -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
  -d '{"reason":"verify-test"}' "$B/portfolio/auto-trader/pause"
echo DONE
