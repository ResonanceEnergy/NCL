import json
rows = []
with open("/Users/natrix/dev/NCL/data/cross_reference/promotions.jsonl") as f:
    for line in f:
        if line.strip():
            rows.append(json.loads(line))
# After most recent bounce (~22:30 ET = 02:30 UTC May 31)
JUNK = {"NEVER", "REST", "THEY", "ONLY", "FREE", "WILL", "GREAT", "NEED",
        "POINT", "YOUR", "JUST", "SORRY", "DIRE", "TRADE", "DON", "EVER",
        "ALWAYS", "FROM", "HERE", "THAT", "THIS", "WHEN", "WHAT", "WHERE",
        "WITH", "MUST", "MAKE", "PC", "DTCC", "HR", "OS", "IA", "UC", "ITS",
        "ANY", "CAN", "DM", "AMA", "VIVO"}
THRESHOLD = "2026-05-31T02:30"
print(f"rows since {THRESHOLD}:")
new = [r for r in rows if r.get("promoted_at","") >= THRESHOLD]
print(f"  {len(new)} total")
junk_new = [r for r in new if (r.get("ticker") or "") in JUNK]
print(f"  {len(junk_new)} junk (ticker in word stoplist)")
for r in new[:15]:
    print(f"  {r.get('promoted_at','')[:19]}  {r.get('rule'):20s} ticker={(r.get('ticker') or '-'):10s} themes={r.get('themes',[])}")
