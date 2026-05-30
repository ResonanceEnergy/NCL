#!/bin/bash
TOK=QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU
BASE=http://100.72.223.123:8800

echo "=== STEP 1: Close trade cb4e8ec6 at mark ($56.385) ==="
curl -s -X POST -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"exit_price": 56.385, "reason": "manual_liquidation_rebuild"}' \
  --max-time 15 \
  "$BASE/paper/trade/cb4e8ec6-f471-4789-8f3e-0c4ba7fd9caf/close" | /usr/bin/python3 -c '
import json,sys
d=json.load(sys.stdin)
print("  status:", d.get("status"))
t = d.get("trade", {})
print("  realized_pnl:", t.get("realized_pl", t.get("pnl_dollars", t.get("pnl"))))
print("  r_multiple:", t.get("r_multiple"))
print("  hold_minutes:", t.get("hold_minutes"))
'

echo ""
echo "=== STEP 2: Run seed_paper_from_live.py ==="
cd /Users/natrix/dev/NCL && /opt/homebrew/bin/python3 scripts/seed_paper_from_live.py 2>&1 | tail -20

echo ""
echo "=== STEP 3: Post-rebuild state ==="
curl -s -H "Authorization: Bearer $TOK" --max-time 5 "$BASE/paper/stats" > /tmp/ps2.json
/usr/bin/python3 - << 'PY'
import json
d=json.load(open('/tmp/ps2.json'))
print("  balance:", d.get("account_balance", d.get("current_balance")))
print("  open_trades:", d.get("open_trades", d.get("open_trades_count")))
print("  total_trades:", d.get("total_trades"))
print("  closed:", d.get("closed_trades"))
print("  realized_pnl:", d.get("total_realized_pl"))
PY

echo ""
echo "=== STEP 4: Auto-trader status (active?) ==="
curl -s -H "Authorization: Bearer $TOK" --max-time 5 "$BASE/portfolio/auto-trader/status" | head -c 400
echo ""
