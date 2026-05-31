import json, urllib.request
req = urllib.request.Request(
    "http://100.72.223.123:8800/intelligence/trends/refresh",
    method="POST",
    headers={"Authorization": "Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU"},
)
d = json.loads(urllib.request.urlopen(req).read())
print(f"buckets: {d.get('n_buckets')}, alerts: {d.get('n_alerts')}")
flags_by_kind = {}
for a in d.get("alerts", []):
    for f in a.get("flags", []):
        kind = f.split("_")[0]
        flags_by_kind[kind] = flags_by_kind.get(kind, 0) + 1
print(f"flag breakdown: {flags_by_kind}")
print("\ntop 8 alerts:")
for a in d.get("alerts", [])[:8]:
    print(f"  {a.get('source',''):14s} {a.get('ticker',''):6s} 24h={a.get('current_24h_mentions',0):3d}  ratio={a.get('ratio_vs_7d')}x  z={a.get('z_score_vs_30d')}  {a.get('flags',[])}")
