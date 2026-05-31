import json
from collections import Counter
rows = []
with open("/Users/natrix/dev/NCL/data/cross_reference/promotions.jsonl") as f:
    for line in f:
        if line.strip():
            rows.append(json.loads(line))
# theme rows
theme_rows = [r for r in rows if r.get("rule") == "theme_converge"]
print(f"theme_converge rows: {len(theme_rows)}")
themes = Counter()
for r in theme_rows:
    t = r.get("theme") or r.get("themes")
    if isinstance(t, list):
        for x in t:
            themes[str(x)] += 1
    else:
        themes[str(t)] += 1
print("theme labels:", themes.most_common(15))
print()
print("most recent 8 theme_converge:")
for r in theme_rows[-8:]:
    print(f"  {r.get('promoted_at','')[:19]}  theme={r.get('theme') or r.get('themes')}  ticker={r.get('ticker')}  src_count={len(r.get('sources') or [])}")
