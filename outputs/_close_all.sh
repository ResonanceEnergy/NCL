#!/bin/bash
TOK=QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU
BASE=http://100.72.223.123:8800

echo "=== Get all open trades ==="
curl -s -H "Authorization: Bearer $TOK" --max-time 5 "$BASE/paper/trades?status=open" > /tmp/op.json

/usr/bin/python3 << 'PY'
import json, urllib.request
TOK = "QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU"
BASE = "http://100.72.223.123:8800"

d = json.load(open('/tmp/op.json'))
trades = d.get('trades', []) if isinstance(d, dict) else d
print(f"  to close: {len(trades)}")
total = 0.0
closed = 0
for t in trades:
    tid = t.get('id') or t.get('trade_id')
    symbol = t.get('symbol', '?')
    entry = float(t.get('entry_price', 0))
    body = json.dumps({"exit_price": entry, "reason": "rebuild_to_cash"}).encode()
    req = urllib.request.Request(
        f"{BASE}/paper/trade/{tid}/close",
        data=body,
        headers={"Authorization": f"Bearer {TOK}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.load(r)
            tr = resp.get('trade', {})
            pnl = tr.get('realized_pl', tr.get('pnl_dollars', 0)) or 0
            total += float(pnl)
            closed += 1
            print(f"    {symbol[:28]:28} pnl={pnl:+.2f}")
    except Exception as e:
        print(f"    {symbol[:28]:28} ERR: {str(e)[:50]}")

print(f"\n  closed={closed}  pnl_sum=${total:+.2f}")
PY

echo ""
echo "=== Final paper state ==="
curl -s -H "Authorization: Bearer $TOK" --max-time 5 "$BASE/paper/stats" > /tmp/fs.json
/usr/bin/python3 - << 'PY'
import json
d = json.load(open('/tmp/fs.json'))
print(f"  balance: ${d.get('account_balance', 0):.2f}")
print(f"  open_trades: {d.get('open_trades')}")
print(f"  total_trades: {d.get('total_trades')}")
print(f"  closed: {d.get('closed_trades')}")
print(f"  total_realized_pl: ${d.get('total_realized_pl', 0):.2f}")
PY
