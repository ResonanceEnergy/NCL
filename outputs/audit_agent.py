#!/usr/bin/env python3
"""Auto-trader agent audit — strategy distribution, symbols seen,
decisions made, mandate sanity, learning artifacts."""
import json, os
from collections import Counter
from pathlib import Path

BASE = Path(os.path.expanduser("~/dev/NCL/data/portfolio/auto_trader"))
CHAINS = BASE / "reasoning_chains.jsonl"
QUANT  = BASE / "quant_scan_events.jsonl"
BANDIT = BASE / "bandit_state.json"
POLICY = BASE / "policy.json"
EOD    = BASE / "eod_summaries.jsonl"

def head(s): print("\n" + "="*70 + f"\n{s}\n" + "="*70)

# 1. Mandate
head("1. MANDATE (operator policy)")
pol = json.loads(POLICY.read_text())
print(f"  notes: {pol.get('notes','?')}")
print(f"  max opens/day: {pol.get('max_opens_per_day')}")
print(f"  max opens/tick: {pol.get('max_opens_per_tick')}")
print(f"  min R:R ratio: {pol.get('min_R_R_ratio')}")
print(f"  allow counter-trend: {pol.get('allow_counter_trend')}")
print(f"  goat requires trend-with: {pol.get('goat_require_with_trend')}")
print(f"  revision: {pol.get('revision')} updated {pol.get('updated_at_iso','')[:19]} by {pol.get('updated_by')}")

# 2. Strategy distribution over decisions
head("2. REASONING CHAIN ANALYSIS")
chains = []
with CHAINS.open() as f:
    for ln in f:
        try: chains.append(json.loads(ln))
        except: continue
print(f"  total chains logged: {len(chains)}")
strats   = Counter(c.get("strategy","?") for c in chains)
symbols  = Counter(c.get("symbol","?") for c in chains if c.get("symbol"))
def _decision(c):
    d = c.get("governor_decision")
    if isinstance(d, dict): return d.get("decision","?")
    return str(d) if d else "?"
def _reject_reason(c):
    d = c.get("governor_decision")
    if isinstance(d, dict):
        rs = d.get("reasons",[])
        return rs[0] if rs else ""
    return ""
decisions = Counter(_decision(c) for c in chains)
reasons   = Counter(_reject_reason(c)[:80] for c in chains)
print(f"\n  strategies seen ({len(strats)} unique):")
for s, n in strats.most_common(15):
    print(f"    {s:20s} {n}")
print(f"\n  symbols seen ({len(symbols)} unique):")
for s, n in symbols.most_common(15):
    print(f"    {s:6s} {n}")
print(f"\n  governor decisions:")
for d, n in decisions.most_common():
    print(f"    {d:10s} {n}")
print(f"\n  top reject reasons (top 5):")
for r, n in reasons.most_common(5):
    if r.strip(): print(f"    [{n}] {r}")

# 3. Bandit state
head("3. BANDIT STATE (Beta-Bernoulli per strategy)")
if BANDIT.exists():
    b = json.loads(BANDIT.read_text())
    for strat, d in b.items():
        w, l = d.get("n_wins",0), d.get("n_losses",0)
        n = d.get("n_observed", w+l)
        sumR = d.get("sum_R_multiple", 0)
        avg = sumR / n if n else 0
        print(f"  {strat:20s} n={n:3d} wins={w} losses={l} sumR={sumR:+.2f} avgR={avg:+.2f}")

# 4. Quant scanner activity
head("4. QUANT SCAN EVENTS (last 5)")
if QUANT.exists():
    rows = QUANT.read_text().splitlines()[-5:]
    for ln in rows:
        try:
            d = json.loads(ln)
            print(f"  {d.get('timestamp_iso','')[:19]} scanner={d.get('scanner','?')} hits={d.get('hit_count','?')}")
            top5 = d.get('symbols_top5') or d.get('top_symbols') or []
            if top5: print(f"    top: {top5[:5]}")
        except Exception as e:
            print(f"  err: {e}")

# 5. EOD summaries
head("5. EOD SUMMARIES (last 3)")
if EOD.exists():
    rows = EOD.read_text().splitlines()[-3:]
    for ln in rows:
        try:
            d = json.loads(ln)
            print(f"  {d.get('date','?')} ideas_eval={d.get('ideas_evaluated',0)} "
                  f"opens={d.get('ideas_opened',0)} closes={d.get('paper_closes',0)} "
                  f"realized_R={d.get('total_realized_R','?')}")
        except: pass
