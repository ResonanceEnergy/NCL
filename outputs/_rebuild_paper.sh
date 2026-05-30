#!/bin/bash
TOK=QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU
BASE=http://100.72.223.123:8800

echo "=== STEP 1: Get the open trade ID ==="
curl -s -H "Authorization: Bearer $TOK" --max-time 5 "$BASE/paper/trades?status=open" > /tmp/open.json
/usr/bin/python3 - << 'PY'
import json
d = json.load(open('/tmp/open.json'))
trades = d.get('trades', []) if isinstance(d, dict) else d
print("  open trades count:", len(trades))
for t in trades:
    keys = list(t.keys())[:8]
    print("  keys sample:", keys)
    print("  id?", t.get('id') or t.get('trade_id') or t.get('uuid'))
    print("  ticker:", t.get('ticker'))
    print("  entry:", t.get('entry_price'), "  current:", t.get('current_price'))
PY

echo ""
echo "=== STEP 1b: Direct file probe for trade IDs ==="
ls /Users/natrix/dev/NCL/data/paper/ 2>/dev/null
find /Users/natrix/dev/NCL/data -name "paper_trades*.jsonl" -o -name "trades*.jsonl" 2>/dev/null | head -3
