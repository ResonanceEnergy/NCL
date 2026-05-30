#!/bin/bash
TOK=QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU
BASE=http://100.72.223.123:8800

echo "=== AUTO-TRADER STATE ==="
curl -s -H "Authorization: Bearer $TOK" --max-time 5 "$BASE/portfolio/auto-trader/status" > /tmp/at.json
/usr/bin/python3 - << 'PY'
import json
d=json.load(open('/tmp/at.json'))
print("  active:", d.get("active"))
print("  paused_by:", d.get("paused_by"))
print("  drawdown_band:", d.get("drawdown_band"))
print("  evaluated/opened/rejected:", d.get("evaluated"), "/", d.get("opened"), "/", d.get("rejected"))
print("  last_tick:", (d.get("last_loop_tick_iso") or "")[:19])
PY

echo ""
echo "=== PAPER STATS ==="
curl -s -H "Authorization: Bearer $TOK" --max-time 5 "$BASE/paper/stats" > /tmp/ps.json
/usr/bin/python3 - << 'PY'
import json
d=json.load(open('/tmp/ps.json'))
print("  full payload:", json.dumps(d, default=str)[:800])
PY

echo ""
echo "=== THE 1 OPEN TRADE ==="
curl -s -H "Authorization: Bearer $TOK" --max-time 5 "$BASE/paper/trades?status=open" > /tmp/op.json
/usr/bin/python3 - << 'PY'
import json
d=json.load(open('/tmp/op.json'))
trades = d.get('trades', []) if isinstance(d, dict) else d
for t in trades:
    print("  trade_id:", t.get('trade_id'))
    print("  ticker:", t.get('ticker'))
    print("  asset_type:", t.get('asset_type'))
    print("  direction:", t.get('direction'))
    print("  entry_price:", t.get('entry_price'))
    print("  current_price:", t.get('current_price'))
    print("  quantity:", t.get('quantity'))
    print("  unrealized_pnl:", t.get('unrealized_pnl', t.get('mfe_dollars')))
    print("  status:", t.get('status'))
    print()
PY

echo ""
echo "=== AWAREBOT signals (last 24h count) ==="
curl -s -H "Authorization: Bearer $TOK" --max-time 5 "$BASE/intelligence/stats" > /tmp/is.json
/usr/bin/python3 - << 'PY'
import json
d=json.load(open('/tmp/is.json'))
print("  signal_count:", d.get("signal_count"))
print("  source_count:", d.get("source_count"))
print("  last_scan_at:", (d.get("last_scan_at") or "")[:19])
print("  signals_routed:", d.get("signals_routed"))
print("  high_critical_count:", d.get("high_critical_count"))
PY
