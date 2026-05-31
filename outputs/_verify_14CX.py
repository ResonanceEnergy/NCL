import json, urllib.request

BASE = "http://100.72.223.123:8800"
HDR = {"Authorization": "Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU"}

def get(path):
    req = urllib.request.Request(BASE + path, headers=HDR)
    return json.loads(urllib.request.urlopen(req).read())

def post(path):
    req = urllib.request.Request(BASE + path, method="POST", headers=HDR)
    return json.loads(urllib.request.urlopen(req).read())

# (1) Reddit queries — verify new set live
print("=== (1) Reddit queries ===")
fq = get("/focus/queries")
print(f"  reddit: {fq.get('reddit')}")

# (3) Refresh trends + verify youtube_search ratios diversified
print("\n=== (3) MOVES — ratios diversified by source? ===")
tr = post("/intelligence/trends/refresh")
alerts = tr.get("alerts", [])
yt = [a for a in alerts if a.get("source") == "youtube_search"]
rd = [a for a in alerts if a.get("source") == "reddit"]
yt_ratios = sorted({a.get("ratio_vs_7d") for a in yt})
rd_ratios = sorted({a.get("ratio_vs_7d") for a in rd})
print(f"  youtube_search: {len(yt)} alerts, {len(yt_ratios)} unique ratios → {yt_ratios[:8]}")
print(f"  reddit:        {len(rd)} alerts, {len(rd_ratios)} unique ratios → {rd_ratios[:8]}")

# (4) Digest freshness flag
print("\n=== (4) /intelligence/digest freshness ===")
d = get("/intelligence/digest")
print(f"  stale: {d.get('stale')}, brief_age_hours: {d.get('brief_age_hours')}")
print(f"  fresh_pro_brief headline: {(d.get('fresh_pro_brief') or {}).get('headline','-')[:80]}")

# (5) XREF: check current cards for NOW
print("\n=== (5) XREF — NOW still appearing? ===")
xr = get("/intel/convergence?hours=24")
cards = xr.get("cards", [])
print(f"  total: {len(cards)}")
for c in cards[:8]:
    print(f"    {c.get('kind','?'):8s} {(c.get('ticker') or c.get('theme') or '?'):14s}")
