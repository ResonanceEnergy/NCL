import json
from collections import Counter
rows = []
with open("/Users/natrix/dev/NCL/data/cross_reference/promotions.jsonl") as f:
    for line in f:
        if line.strip():
            rows.append(json.loads(line))
print(f"total rows: {len(rows)}")
print(f"last 24h rows: {sum(1 for r in rows if r.get('promoted_at','') >= '2026-05-30')}")
print()
recent = rows[-50:]
print(f"last 50 by rule: {Counter(r.get('rule') for r in recent)}")
print(f"last 50 by ticker (top 10): {Counter(r.get('ticker') for r in recent).most_common(10)}")
print()
print("any junk-word tickers ever?:")
JUNK = {"NEVER", "REST", "THEY", "ONLY", "FREE", "WILL", "GREAT", "NEED",
        "POINT", "YOUR", "JUST", "SORRY", "DIRE", "TRADE", "DON", "EVER",
        "ALWAYS", "FROM", "HERE", "THAT", "THIS", "WHEN", "WHAT", "WHERE",
        "WITH", "MUST", "MAKE", "PC", "DTCC", "HR", "OS", "IA", "UC", "ITS"}
junky = [r for r in rows if (r.get("ticker") or "") in JUNK]
print(f"  total junk-word rows ever: {len(junky)}")
if junky:
    when = Counter(r.get("promoted_at", "")[:10] for r in junky)
    print(f"  junk by date: {when.most_common(5)}")
    print(f"  most recent 5:")
    for r in junky[-5:]:
        print(f"    {r.get('promoted_at','')[:19]}  {r.get('rule'):20s} {r.get('ticker')}")
