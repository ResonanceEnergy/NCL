import json, urllib.request
req = urllib.request.Request(
    "http://100.72.223.123:8800/intel/convergence?hours=24",
    headers={"Authorization": "Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU"},
)
d = json.loads(urllib.request.urlopen(req).read())
print(f"count: {d.get('count')}, dual: {d.get('dual_count')}, xref_only: {d.get('xref_only')}, prediction_only: {d.get('prediction_only')}")
cards = d.get("cards", [])
print(f"total cards: {len(cards)}")
print()
# Group by ticker/theme + rule
by_kind = {}
suspect = []
KNOWN_WORDS = {"NEVER", "REST", "THEY", "ONLY", "FREE", "WILL", "GREAT", "NEED", "POINT",
               "YOUR", "JUST", "SORRY", "DIRE", "TRADE", "DON", "EVER", "ALWAYS", "FROM",
               "HERE", "THAT", "THIS", "WHEN", "WHAT", "WHERE", "WITH", "MUST", "MAKE"}
for c in cards:
    kind = c.get("rule", "?")
    by_kind[kind] = by_kind.get(kind, 0) + 1
    ticker = c.get("ticker") or ""
    if ticker in KNOWN_WORDS:
        suspect.append(c)
print("by rule:", by_kind)
print()
print(f"junk-word tickers still appearing: {len(suspect)}")
for s in suspect[:8]:
    print(f"  {s.get('rule'):20s} ticker={s.get('ticker')}  sources={s.get('sources')}")
print()
print("first 5 cards (any rule):")
for c in cards[:5]:
    print(f"  {c.get('rule'):20s} ticker={c.get('ticker'):8s} sources={c.get('sources')}")
