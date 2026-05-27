#!/bin/bash
set -a
. /Users/natrix/dev/NCL/.env
set +a
T="$STRIKE_AUTH_TOKEN"
B="http://100.72.223.123:8800"

echo "=== GET /portfolio/trade-ideas (initial) ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/portfolio/trade-ideas" | /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
print('count:', d['count'])
for i in d['ideas'][:3]:
    print(f\"  {i['trade_idea_id'][:8]} {i['strategy']:8} {i['ticker']:6} {i['outcome']:12} R_mult={i.get('R_multiple')}\")
"

echo
echo "=== GET /portfolio/trade-ideas/expectancy ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/portfolio/trade-ideas/expectancy" | /opt/homebrew/bin/python3 -m json.tool | head -40

echo
echo "=== Drive a new outcome via REST ==="
# Use one of the bravo emissions from smoke as a target_hit at +2R (entry 195 + 14 = 209)
# First find a bravo id
BID=$(curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/portfolio/trade-ideas?strategy=bravo" | /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
for i in d['ideas']:
    if i['outcome'] == 'emitted':
        print(i['trade_idea_id']); break
")
echo "BID=$BID"
if [ -n "$BID" ]; then
  curl -sS --max-time 8 -X POST -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
    -d '{"outcome":"target_hit","exit_price":209,"notes":"REST verify"}' \
    "$B/portfolio/trade-ideas/$BID/outcome" | /opt/homebrew/bin/python3 -m json.tool | head -20
fi

echo
echo "=== Expectancy after BRAVO close ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/portfolio/trade-ideas/expectancy" | /opt/homebrew/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
for strat, s in d.items():
    if strat == '_all':
        continue
    if s['n_emitted']:
        print(f\"{strat:12} n_em={s['n_emitted']:2} n_cl={s['n_closed']:2} \"
              f\"hit={s['hit_rate']:.2f} expR={s['expectancy_R']:+.2f} \"
              f\"PF={s['profit_factor']} SQN={s['sqn']:.2f}\")
print('---all---')
a = d['_all']
print(f\"all          n_em={a['n_emitted']:2} n_cl={a['n_closed']:2} \"
      f\"hit={a['hit_rate']:.2f} expR={a['expectancy_R']:+.2f}\")
"
echo DONE
