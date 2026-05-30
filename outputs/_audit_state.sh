#!/bin/bash
TOK=QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU
BASE=http://100.72.223.123:8800

echo "=== MANDATE COVERAGE (docs/) ==="
ls /Users/natrix/dev/NCL/docs/*MANDATE.md 2>/dev/null | xargs -n1 basename

echo ""
echo "=== AUTO-TRADER STATE ==="
curl -s -H "Authorization: Bearer $TOK" --max-time 5 "$BASE/portfolio/auto-trader/status" | /usr/bin/python3 -c '
import json,sys
d=json.load(sys.stdin)
print(f"  active: {d.get(\"active\")}")
print(f"  paused_by: {d.get(\"paused_by\")}")
print(f"  drawdown_band: {d.get(\"drawdown_band\")}")
print(f"  evaluated/opened/rejected: {d.get(\"evaluated\")}/{d.get(\"opened\")}/{d.get(\"rejected\")}")
print(f"  last_tick: {(d.get(\"last_loop_tick_iso\") or \"\")[:19]}")
'

echo ""
echo "=== PAPER TRADING STATS ==="
curl -s -H "Authorization: Bearer $TOK" --max-time 5 "$BASE/paper/stats" | /usr/bin/python3 -c '
import json,sys
d=json.load(sys.stdin)
print(f"  balance: ${d.get(\"current_balance\", d.get(\"balance\", 0)):.2f}")
print(f"  open_count: {d.get(\"open_trades_count\", d.get(\"open_positions_count\", \"?\"))}")
print(f"  total_trades: {d.get(\"total_trades\", \"?\")}")
print(f"  total_r: {d.get(\"total_r\", 0):+.2f}")
print(f"  hit_rate: {d.get(\"hit_rate\", 0):.2%}" if d.get("hit_rate") else "  hit_rate: n/a")
'

echo ""
echo "=== OPEN PAPER TRADES (snapshot) ==="
curl -s -H "Authorization: Bearer $TOK" --max-time 5 "$BASE/paper/trades?status=open" > /tmp/open.json
/usr/bin/python3 << 'PY'
import json
try:
    d = json.load(open('/tmp/open.json'))
    trades = d.get('trades', []) if isinstance(d, dict) else d
    print(f"  open count = {len(trades)}")
    opts = [t for t in trades if (t.get('asset_type') or '').lower() == 'options']
    print(f"  open OPTIONS count = {len(opts)}")
    for t in opts[:10]:
        print(f"    {t.get('ticker','?')} {t.get('direction','?')} entry=${t.get('entry_price','?')} mark=${t.get('current_price', t.get('mark','?'))} qty={t.get('quantity','?')} pnl_r={t.get('unrealized_r',t.get('r_multiple','?'))}")
except Exception as e:
    print(f"  parse error: {e}")
PY

echo ""
echo "=== AWAREBOT FUNCTIONING — recent signals ==="
curl -s -H "Authorization: Bearer $TOK" --max-time 5 "$BASE/intelligence/stats" | /usr/bin/python3 -c '
import json,sys
d=json.load(sys.stdin)
print(f"  signal_count: {d.get(\"signal_count\")}")
print(f"  source_count: {d.get(\"source_count\")}")
print(f"  last_scan_at: {(d.get(\"last_scan_at\") or \"\")[:19]}")
print(f"  signals_routed: {d.get(\"signals_routed\", \"?\")}")
print(f"  high_critical_count: {d.get(\"high_critical_count\", \"?\")}")
'

echo ""
echo "=== CROSS-REF promotions (recent) ==="
ls -lh /Users/natrix/dev/NCL/data/cross_reference/promotions.jsonl 2>/dev/null | head -1
wc -l /Users/natrix/dev/NCL/data/cross_reference/promotions.jsonl 2>/dev/null
