"""Audit recent reasoning chains for the auto-trader.

Shows:
  - Rejection-reason distribution (last 24h vs last 7d)
  - Per-ticker reject pattern
  - Time histogram (did anything land post-14CR/14CS?)
  - Source distribution (did brief ideas reach the loop?)
"""
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

PATH = Path("/Users/natrix/dev/NCL/data/portfolio/auto_trader/reasoning_chains.jsonl")
rows = []
with PATH.open() as f:
    for line in f:
        if line.strip():
            try:
                rows.append(json.loads(line))
            except Exception:
                continue

print(f"total chains in file: {len(rows)}")
print()

now = datetime.now(timezone.utc)
last_24h = [r for r in rows if r.get("ts", "") >= (now - timedelta(hours=24)).isoformat()]
last_7d  = [r for r in rows if r.get("ts", "") >= (now - timedelta(days=7)).isoformat()]
print(f"last 24h: {len(last_24h)}, last 7d: {len(last_7d)}")
print()

# Latest chain
if rows:
    latest = rows[-1]
    print(f"latest chain: ts={latest.get('ts')}, ticker={latest.get('idea_snapshot',{}).get('ticker')}, decision={latest.get('decision')}")
    print(f"  final_reason: {latest.get('final_reason')}")
print()

# Decision breakdown
decisions_7d = Counter(r.get("decision", "?") for r in last_7d)
print("decisions (7d):", dict(decisions_7d))
print()

# Reject reasons breakdown
reject_reasons_7d = Counter()
for r in last_7d:
    if r.get("decision") == "reject":
        reason = (r.get("final_reason") or "?")[:80]
        reject_reasons_7d[reason] += 1
print("top reject reasons (7d):")
for reason, n in reject_reasons_7d.most_common(15):
    print(f"  {n:4d}  {reason}")
print()

# Per-source breakdown of recent chains
src_24h = Counter()
for r in last_24h:
    snap = r.get("idea_snapshot") or {}
    src = snap.get("source", "?")
    src_24h[src] += 1
print(f"24h chains by idea source: {dict(src_24h)}")
print()

# Ticker breakdown of recent chains
ticker_24h = Counter(
    (r.get("idea_snapshot") or {}).get("ticker", "?") for r in last_24h
)
print(f"24h chains by ticker (top 10): {ticker_24h.most_common(10)}")
print()

# Did anything PASS the gate chain in last 7d?
passed = [r for r in last_7d if r.get("decision") in ("approve", "open", "ok", "passed")]
print(f"non-reject chains in 7d: {len(passed)}")
for r in passed[:5]:
    snap = r.get("idea_snapshot") or {}
    print(f"  {r.get('ts','')[:19]}  {snap.get('ticker'):6s} decision={r.get('decision')}")
print()

# Stage-by-stage where things died
stage_death = Counter()
for r in last_7d:
    if r.get("decision") != "reject":
        continue
    # Find which stage rejected — look for first failing stage in the snapshot
    for stage_key in ("sanity_check", "risk_governor_check", "policy_check",
                       "calendar_gate", "working_context_gate", "tax_sizing",
                       "exposure_gate", "council_check"):
        stage_val = r.get(stage_key)
        if isinstance(stage_val, dict):
            ok = stage_val.get("eligible", stage_val.get("approved", True))
            if not ok:
                stage_death[stage_key] += 1
                break
    else:
        stage_death["unknown_stage"] += 1
print(f"reject stage distribution (7d): {dict(stage_death)}")
