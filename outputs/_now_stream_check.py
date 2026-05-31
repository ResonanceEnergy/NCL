import json
import urllib.request


def get(path):
    req = urllib.request.Request(
        f"http://100.72.223.123:8800{path}",
        headers={"Authorization": "Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU"},
    )
    return json.loads(urllib.request.urlopen(req).read())


print("=== /intel/now first 5 items ===")
d = get("/intel/now")
print(f"count={d['count']}, breakdown={d['breakdown']}")
for i, item in enumerate(d.get("items", [])[:5]):
    title = (item.get("title") or "").strip() or "(no title)"
    content = (item.get("content") or "")[:90]
    src = item.get("source", "")
    item_id = item.get("item_id", "")
    print(f"  [{i}] src={src} id_kind={item_id.split(':')[0] if ':' in item_id else 'none'}")
    print(f"      title: {title[:80]}")
    print(f"      content: {content}")
    print(f"      route={item.get('route_level','-')} composite={item.get('composite_score','-')}")
print()
print("=== /intel/stream first 5 items ===")
d = get("/intel/stream?window=24h&limit=5")
print(f"total={d['total']}, count={d['count']}")
print(f"source facets: {list(d['facets']['sources'].items())[:6]}")
for i, item in enumerate(d.get("items", [])[:5]):
    title = item.get("title", "(no title)")
    src = item.get("source", "")
    tags = item.get("tags", [])
    promo = "filter:promo" in tags or "promo_detected" in str(item.get("metadata") or {})
    print(f"  [{i}] src={src} composite={item.get('composite_score','-'):.3f}  promo={promo}")
    print(f"      title: {title[:90]}")
