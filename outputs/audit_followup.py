#!/usr/bin/env python3
"""Audit follow-up: stale loop, portfolio $0, why 26/26 rejected."""

import json
import subprocess


BASE = "http://100.72.223.123:8800"
H = ["-H", "Authorization: Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU"]


def fetch(p):
    r = subprocess.run(
        ["curl", "-sS", "-m", "10"] + H + [f"{BASE}{p}"], capture_output=True, text=True, timeout=15
    )
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"_raw": r.stdout[:300]}


# 1. Which loop is stale?
print("[A] STALE LOOP")
h = fetch("/system/health/rollup")
sched = (h.get("components") or {}).get("scheduler", {})
print(f"  stale_loops: {sched.get('stale_loops')}")

# 2. Portfolio detail
print("\n[B] PORTFOLIO DETAIL")
acc = fetch("/portfolio/accounts")
print(f"  accounts: {len(acc.get('accounts', [])) if isinstance(acc, dict) else 'n/a'}")
if isinstance(acc, dict):
    for a in acc.get("accounts", [])[:5]:
        print(
            f"    {a.get('broker')}/{a.get('account_number','?')[:8]}: "
            f"${a.get('equity_cad', 0):,.2f} pos={a.get('positions_count')}"
        )
# health rollup portfolio reason
p_health = (h.get("components") or {}).get("portfolio", {})
print(f"  health-rollup reason: {p_health.get('reason', 'no reason')}")

# 3. Why 26/26 rejected? Look at recent rejections
print("\n[C] AUTO-TRADER REJECTIONS")
# look at tracker recent — for trade ideas with no auto-open
recent = fetch("/portfolio/auto-trader/dashboard")
if "recent_closes" in recent:
    print(f"  recent_closes: {len(recent['recent_closes'])}")
# evaluate any rejection metric
# Check observability JSONL count
import subprocess as sp


out = sp.run(
    ["tail", "-50", "/Users/natrix/dev/NCL/data/portfolio/auto_trader/reasoning_chains.jsonl"],
    capture_output=True,
    text=True,
)
lines = out.stdout.strip().split("\n") if out.stdout.strip() else []
print(f"  reasoning chains last 50: {len(lines)} lines")
rejections = []
for ln in lines[-30:]:
    try:
        e = json.loads(ln)
        gov = e.get("governor_decision") or {}
        if not gov.get("approved", True):
            rejections.append({"ticker": e.get("ticker"), "reason": gov.get("reason", "?")[:80]})
    except Exception:
        pass
print(f"  rejected last 30: {len(rejections)}")
for r in rejections[:8]:
    print(f"    {r['ticker']}: {r['reason']}")
