import json
from collections import Counter
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

now = datetime.now(timezone.utc)
last_24h = [r for r in rows if r.get("ts", "") >= (now - timedelta(hours=24)).isoformat()]
last_7d  = [r for r in rows if r.get("ts", "") >= (now - timedelta(days=7)).isoformat()]
print(f"total chains: {len(rows)}, 24h: {len(last_24h)}, 7d: {len(last_7d)}")
print()

# Real schema — look at stage results
def stage_outcome(chain):
    """Return (stage_name, reason) for the first failing stage."""
    for stage in ["sanity_check", "policy_check", "calendar_gate",
                  "working_context_gate", "exposure_gate", "council_check"]:
        s = chain.get(stage)
        if isinstance(s, dict):
            eligible = s.get("eligible", s.get("approved", True))
            if not eligible:
                return stage, (s.get("reason") or "?")
    # Governor
    g = chain.get("governor_decision")
    if isinstance(g, dict) and not g.get("approved", True):
        return "risk_governor", (g.get("reason") or "?")
    # If we got here it's a pass (or partial)
    if chain.get("paper_trade_id"):
        return "opened", "trade opened"
    return "advanced", "passed all checked stages"

stage_reason_24h = Counter()
stage_reason_7d = Counter()
for r in last_24h:
    stage, reason = stage_outcome(r)
    stage_reason_24h[f"{stage}: {reason[:50]}"] += 1
for r in last_7d:
    stage, reason = stage_outcome(r)
    stage_reason_7d[f"{stage}: {reason[:50]}"] += 1

print(f"24h stage/reason ({sum(stage_reason_24h.values())} total):")
for k, n in stage_reason_24h.most_common(15):
    print(f"  {n:3d}  {k}")
print()
print(f"7d stage/reason ({sum(stage_reason_7d.values())} total):")
for k, n in stage_reason_7d.most_common(15):
    print(f"  {n:3d}  {k}")
print()

# What did brief ideas LOOK like — any with missing stop?
brief_ideas_24h = [r for r in last_24h if (r.get("source") or "").startswith("brief")]
print(f"brief ideas 24h: {len(brief_ideas_24h)}")
no_stop = [r for r in brief_ideas_24h if not (r.get("idea_snapshot") or {}).get("stop_price")]
print(f"  brief ideas with NO stop_price: {len(no_stop)} / {len(brief_ideas_24h)}")

# Breakdown by type
type_counts = Counter()
for r in brief_ideas_24h:
    snap = r.get("idea_snapshot") or {}
    md = snap.get("metadata") or {}
    t = md.get("type", "?")
    has_stop = snap.get("stop_price") is not None
    type_counts[f"{t} (stop={'yes' if has_stop else 'no'})"] += 1
print(f"  by type: {dict(type_counts)}")
print()

# What stop_basis did the working ones have?
print("brief stock ideas in 24h — entry/stop/target:")
for r in brief_ideas_24h:
    snap = r.get("idea_snapshot") or {}
    md = snap.get("metadata") or {}
    t = md.get("type", "?")
    if t != "stock":
        continue
    print(f"  {snap.get('ticker'):6s} entry={snap.get('entry_price')} stop={snap.get('stop_price')} target={snap.get('target_price')} thesis={(snap.get('thesis') or '')[:40]!r}")
