import json, urllib.request
req = urllib.request.Request(
    "http://127.0.0.1:8800/paper/trades?status=all&strategy=all",
    headers={"Authorization": "Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU"},
)
d = json.loads(urllib.request.urlopen(req).read())
trades = d.get("trades") if isinstance(d, dict) else d
if not isinstance(trades, list):
    trades = []
print(f"count: {len(trades)}")
from collections import Counter
print("by strategy:", Counter(t.get("strategy", "?") for t in trades))
print("by status:", Counter(t.get("status", "?") for t in trades))
print("by source (scanner_data.source):", Counter(((t.get("scanner_data") or {}).get("source") or "-") for t in trades))
print()
print("first 8 trades:")
for t in trades[:8]:
    sd = t.get("scanner_data") or {}
    print(f"  {t.get('symbol','?'):6s} strategy={(t.get('strategy') or '?'):12s} status={(t.get('status') or '?'):8s} source={sd.get('source','-')}  qty={t.get('qty')}  entry={t.get('entry_price')}")
