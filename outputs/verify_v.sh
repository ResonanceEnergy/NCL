#!/bin/bash
TOK=$(grep STRIKE_AUTH_TOKEN ~/dev/NCL/.env | cut -d= -f2 | tr -d '"')
BASE=http://100.72.223.123:8800
sleep 25

echo "=== V1 — journal write speed test ==="
START=$(date +%s%N)
RESP=$(curl -s --max-time 15 -X POST -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d '{"entry_type":"note","content":"V1 hang fix verification - should return immediately","importance":50,"tags":["v1_test"]}' \
  $BASE/journal/entry)
END=$(date +%s%N)
MS=$(( (END - START) / 1000000 ))
echo "POST /journal/entry returned in ${MS}ms"
echo "Response: $(echo $RESP | head -c 200)"
echo

echo "=== V2 — portfolio bg sync ==="
curl -s -H "Authorization: Bearer $TOK" $BASE/portfolio/health | /opt/homebrew/bin/python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'  background_sync: {d.get(\"background_sync\")}')
print(f'  positions_cached: {d.get(\"positions_cached\")}')
print(f'  last_sync: {d.get(\"last_sync\")}')
print(f'  market_open: {d.get(\"market_open\")}')"
echo

echo "=== V3 — pin auto-promote (memory unit_id) ==="
UID=$(curl -s -H "Authorization: Bearer $TOK" "$BASE/memory/by-authority?min_tier=council" | /opt/homebrew/bin/python3 -c "import json,sys; d=json.load(sys.stdin); us=d.get('units',[]); print(us[0]['unit_id'] if us else '')")
echo "  picked unit_id: $UID"
curl -s -X POST -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d "{\"item_id\":\"$UID\"}" $BASE/memory/working-context/pin | head -c 200
echo

echo "=== V4 — top-entities limit + noise filter ==="
curl -s -H "Authorization: Bearer $TOK" "$BASE/memory/knowledge-graph/top-entities?limit=10" | /opt/homebrew/bin/python3 -c "
import json,sys
d = json.load(sys.stdin)
ents = d.get('entities', [])
print(f'  returned: {d.get(\"returned\")}, requested: {d.get(\"requested\")}, noise_filtered: {d.get(\"noise_filtered\")}')
for e in ents[:5]:
    name = e.get('name') or e.get('entity') or '?'
    n = e.get('mention_count') or e.get('count') or 0
    print(f'  - {name[:40]:40s} {n}')"
echo

echo "=== V5 — timeline source-prefix cap ==="
curl -s -H "Authorization: Bearer $TOK" "$BASE/memory/timeline?limit=30" | /opt/homebrew/bin/python3 -c "
import json,sys
from collections import Counter
d = json.load(sys.stdin)
evs = d.get('events') or []
src = Counter(e.get('source','?') for e in evs if e.get('type')=='created')
print(f'  events: {len(evs)}, degraded: {d.get(\"degraded\")}')
print('  top sources:')
for s, n in src.most_common(6):
    print(f'    {s[:50]:50s} {n}')"
echo

echo "=== V7 — fused search tier + signal_id projection ==="
curl -s -H "Authorization: Bearer $TOK" "$BASE/memory/search/fused?q=trading&top_k=3" | /opt/homebrew/bin/python3 -c "
import json,sys
d = json.load(sys.stdin)
for r in d.get('results', [])[:3]:
    print(f'  unit_id: {(r.get(\"unit_id\") or \"\")[:8]} tier={r.get(\"tier\")} sig_id={(r.get(\"signal_id\") or \"\")[:8]} auth={r.get(\"authority_tier_name\")}')"
