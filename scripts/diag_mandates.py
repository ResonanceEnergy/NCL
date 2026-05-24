"""Diagnostic — which mandates in mandates.json fail validation under current Mandate model."""

import json
import sys
from collections import Counter


sys.path.insert(0, "/Users/natrix/dev/NCL")
from runtime.ncl_brain.brain import Mandate


d = json.load(open("/Users/natrix/dev/NCL/data/mandates.json"))
errs = Counter()
ok = 0
pillars_ok = Counter()
pillars_bad = Counter()
for m in d:
    p = m.get("target_pillar") or m.get("pillar")
    try:
        Mandate(**m)
        ok += 1
        pillars_ok[p] += 1
    except Exception as e:
        text = str(e)
        line2 = text.split("\n")[1] if "\n" in text else text
        first_part = line2.split("For further")[0].strip()
        errs[first_part[:160]] += 1
        pillars_bad[p] += 1

print(f"total: {len(d)}  valid: {ok}  invalid: {len(d) - ok}")
print(f"pillars_ok: {dict(pillars_ok)}")
print(f"pillars_bad: {dict(pillars_bad)}")
print("--- top errors ---")
for msg, n in errs.most_common(8):
    print(f"{n:4d}  {msg}")
