import json, urllib.request, collections

req = urllib.request.Request(
    "http://100.72.223.123:8800/intel/convergence?hours=24",
    headers={"Authorization": "Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU"},
)
d = json.loads(urllib.request.urlopen(req).read())
cards = d.get("cards", [])
print(f"TOTAL CARDS: {len(cards)}")
print(f"  dual:        {d.get('dual_count')}")
print(f"  xref only:   {d.get('xref_only')}")
print(f"  pred only:   {d.get('prediction_only')}")
print()
kinds = collections.Counter(c.get("kind") for c in cards)
print("CARD BREAKDOWN BY KIND:")
for k, n in kinds.most_common():
    print(f"  {k}: {n}")
print()
print("ALL TICKER CARDS (sorted by source-count):")
ticker_cards = sorted(
    [c for c in cards if c.get("kind") == "ticker"],
    key=lambda c: -len(c.get("sources", [])),
)
for c in ticker_cards:
    t = c.get("ticker") or "?"
    sources = c.get("sources", [])
    xref = c.get("xref_promotions", [])
    sample = ""
    if xref:
        titles = xref[0].get("sample_titles", [])
        if titles:
            sample = titles[0][:80]
    print(f"  {t:10} sources={sources}  ex: {sample}")
print()
print("ALL THEME CARDS:")
theme_cards = [c for c in cards if c.get("kind") == "theme"]
for c in theme_cards:
    theme = c.get("theme") or "?"
    sources = c.get("sources", [])
    print(f"  {theme:35} sources={sources}")
