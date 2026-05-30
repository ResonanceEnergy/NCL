import json
import urllib.request as r

req = r.Request(
    "http://100.72.223.123:8800/system/costs/dashboard.json?days=1",
    headers={"Authorization": "Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU"},
)
d = json.loads(r.urlopen(req).read())
print("today total:", d.get("totals", {}).get("today"))
print()
print("by_source_model:")
for k, v in d.get("by_source_model", {}).items():
    print(f"  {k}: ${v:.4f}")
print()
print("top ops (today):")
for o in d.get("top_ops", [])[:10]:
    key = o["key"]
    spend = o["spend_usd"]
    calls = o["calls"]
    print(f"  {key}: ${spend:.4f} ({calls} calls)")
