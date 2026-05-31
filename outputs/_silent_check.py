import json, urllib.request
req = urllib.request.Request(
    "http://100.72.223.123:8800/system/silent-failures",
    headers={"Authorization": "Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU"},
)
d = json.loads(urllib.request.urlopen(req).read())
print(f"started_at: {d.get('started_at')}")
print(f"as_of: {d.get('as_of')}")
print(f"n_distinct_counters: {d.get('n_distinct_counters')}")
print()
counters = d.get("counters", {})
print(f"counters ({len(counters)}):")
for name, n in sorted(counters.items(), key=lambda kv: -kv[1])[:15]:
    print(f"  {name:45s}  {n}")
print()
br = d.get("by_reason", {})
for name, reasons in br.items():
    if reasons:
        print(f"{name} by reason:")
        for r, n in list(reasons.items())[:5]:
            print(f"  {r:40s}  {n}")
