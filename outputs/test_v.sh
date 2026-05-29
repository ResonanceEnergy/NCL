#!/bin/bash
TOK=$(grep STRIKE_AUTH_TOKEN ~/dev/NCL/.env | cut -d= -f2 | tr -d '"')
BASE=http://100.72.223.123:8800
echo === V3 pin auto-promote ===
UNIT=$(curl -s -H "Authorization: Bearer $TOK" "$BASE/memory/by-authority?min_tier=council" | /opt/homebrew/bin/python3 -c "import json,sys;d=json.load(sys.stdin);us=d.get('units',[]);print(us[0]['unit_id'] if us else '')")
echo picked: $UNIT
curl -s -X POST -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' -d "{\"item_id\":\"$UNIT\"}" $BASE/memory/working-context/pin
echo
echo === V4 top-entities ===
curl -s -H "Authorization: Bearer $TOK" "$BASE/memory/knowledge-graph/top-entities?limit=10" | head -c 800
echo
echo === V5 timeline ===
curl -s -H "Authorization: Bearer $TOK" "$BASE/memory/timeline?limit=30" > /tmp/tl.json
/opt/homebrew/bin/python3 << 'PYEOF'
import json
from collections import Counter
d = json.load(open('/tmp/tl.json'))
evs = d.get('events') or []
src = Counter(e.get('source','?') for e in evs if e.get('type')=='created')
print(f'events: {len(evs)}, degraded: {d.get("degraded")}')
for s, n in src.most_common(8):
    print(f'  {s[:50]:50s} {n}')
PYEOF
echo === V7 fused projection ===
curl -s -H "Authorization: Bearer $TOK" "$BASE/memory/search/fused?q=trading&top_k=3" > /tmp/f.json
/opt/homebrew/bin/python3 << 'PYEOF'
import json
d = json.load(open('/tmp/f.json'))
for r in d.get('results', [])[:3]:
    print(f"unit_id={(r.get('unit_id') or '')[:8]} tier={r.get('tier')} sig_id={(r.get('signal_id') or '')[:8]} auth={r.get('authority_tier_name')}")
PYEOF
