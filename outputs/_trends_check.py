import json, urllib.request
req = urllib.request.Request(
    "http://100.72.223.123:8800/intelligence/trends/refresh",
    method="POST",
    headers={"Authorization": "Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU"},
)
d = json.loads(urllib.request.urlopen(req).read())
print(f"buckets: {d.get('n_buckets')}, alerts: {d.get('n_alerts')}")
print()
print("top 10 alerts:")
for a in d.get("alerts", [])[:10]:
    src = a.get("source", "")
    tkr = a.get("ticker", "")
    cur = a.get("current_24h_mentions", 0)
    ratio = a.get("ratio_vs_7d", 0)
    z = a.get("z_score_vs_30d", 0)
    flags = a.get("flags", [])
    print(f"  {src:14} {tkr:8} 24h={cur:3}  ratio={ratio}x  z={z}  {flags}")
