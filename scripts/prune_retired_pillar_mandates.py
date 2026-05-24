"""One-shot cleanup — drop mandates whose target_pillar is BRS or AAC (retired 2026-05-23).

Backs up mandates.json with timestamp suffix, filters out retired-pillar entries,
writes cleaned list. Idempotent — safe to re-run.
"""

import json
import shutil
import time
from pathlib import Path


SRC = Path("/Users/natrix/dev/NCL/data/mandates.json")
ts = time.strftime("%Y%m%d-%H%M%S")
BAK = SRC.with_suffix(f".json.pre-prune-{ts}.bak")

retired = {"brs", "aac"}
data = json.loads(SRC.read_text())
assert isinstance(data, list), f"expected list, got {type(data)}"

before = len(data)
keep, drop = [], []
for m in data:
    p = (m.get("target_pillar") or m.get("pillar") or "").lower()
    (drop if p in retired else keep).append(m)

if not drop:
    print(f"nothing to do — 0 retired-pillar mandates in {before} entries")
else:
    shutil.copy2(SRC, BAK)
    SRC.write_text(json.dumps(keep, indent=2))
    print(f"backup: {BAK.name}")
    print(f"before: {before}  kept: {len(keep)}  dropped: {len(drop)}")
    from collections import Counter

    print(
        f"dropped pillars: {dict(Counter((m.get('target_pillar') or m.get('pillar') or '').lower() for m in drop))}"
    )
