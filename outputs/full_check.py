#!/usr/bin/env python3
"""Post-Wave-14R full system check.

Hits every endpoint the 6 iOS tabs consume + all 5 Portfolio sub-tabs
+ new polymarket-agent surface, plus scheduler + health rollup.
"""

import json
import subprocess
from datetime import datetime


BASE = "http://100.72.223.123:8800"
H = ["-H", "Authorization: Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU"]


def hit(path, label=None):
    label = label or path
    try:
        r = subprocess.run(
            ["curl", "-sS", "-m", "8"] + H + [f"{BASE}{path}"],
            capture_output=True,
            text=True,
            timeout=12,
        )
        if r.returncode != 0:
            return False, label, f"curl exit {r.returncode}"
        body = r.stdout.strip()
        if not body:
            return False, label, "empty"
        try:
            d = json.loads(body)
            if isinstance(d, dict) and d.get("detail") == "Not Found":
                return False, label, "404"
            return True, label, _summarize(d)
        except json.JSONDecodeError:
            return True, label, body[:60]
    except Exception as e:
        return False, label, str(e)


def _summarize(d):
    if isinstance(d, list):
        return f"list[{len(d)}]"
    if not isinstance(d, dict):
        return type(d).__name__
    if "status" in d and len(d) <= 3:
        return f"status={d.get('status')}"
    keys = list(d.keys())[:6]
    return f"keys={keys}"


print("=" * 78)
print(f"NCL FULL SYSTEM CHECK  {datetime.now().isoformat(timespec='seconds')}")
print("=" * 78)

# ── 1. Health + scheduler ──────────────────────────────────────────────
print("\n[1] CORE HEALTH")
ok, lbl, s = hit("/system/health/rollup", "health/rollup")
print(f"  {'✓' if ok else '✗'} {lbl}: {s}")
ok, lbl, s = hit("/autonomous/loops", "scheduler/loops")
print(f"  {'✓' if ok else '✗'} {lbl}: {s}")

# Get scheduler details
try:
    r = subprocess.run(
        ["curl", "-sS"] + H + [f"{BASE}/autonomous/loops"],
        capture_output=True,
        text=True,
        timeout=8,
    )
    loops = json.loads(r.stdout)
    tasks = loops.get("tasks") or loops.get("loops") or []
    if isinstance(tasks, list):
        running = sum(1 for t in tasks if t.get("active") or t.get("state") == "running")
        poly = [t for t in tasks if "poly" in (t.get("name", "") or "").lower()]
        print(f"  total tasks: {len(tasks)}, running: {running}")
        print(f"  ncl-poly-* tasks: {len(poly)} → {[t.get('name') for t in poly]}")
except Exception as e:
    print(f"  could not enumerate loops: {e}")

# ── 2. Every iOS-consumed endpoint ─────────────────────────────────────
print("\n[2] iOS TAB ENDPOINTS")

tab_endpoints = {
    "DASHBOARD": [
        "/system/health/rollup",
        "/autonomous/loops",
        "/system/costs",
    ],
    "PORTFOLIO": [
        "/portfolio/summary",
        "/portfolio/positions",
        "/portfolio/accounts",
        "/portfolio/performance",
        "/portfolio/options-flow",
    ],
    "AGENT (auto-trader)": [
        "/portfolio/auto-trader/dashboard",
        "/portfolio/auto-trader/circuit-breakers",
        "/portfolio/auto-trader/capabilities",
    ],
    "POLYMARKET AGENT (new)": [
        "/portfolio/polymarket-agent/dashboard",
        "/portfolio/polymarket-agent/state",
        "/portfolio/polymarket-agent/edges?limit=10",
        "/portfolio/polymarket-agent/bets?status=all",
    ],
    "INTEL": [
        "/intelligence/stats",
        "/predictions?limit=10&sort=confidence",
        "/focus/queries",
        "/focus/subreddits",
        "/intelligence/rotation",
        "/intelligence/digest",
        "/intelligence/morning-brief/pro",
        "/youtube/reports/recent?limit=10",
    ],
    "MEMORY": [
        "/memory/stats",
        "/memory/timeline?limit=20",
        "/memory/working-context",
        "/memory/knowledge-graph/stats",
    ],
    "CALENDAR": [
        "/calendar/today",
        "/calendar/week",
        "/calendar/month",
        "/calendar/moon",
        "/calendar/sun",
        "/calendar/watchlist",
        "/calendar/cities",
    ],
    "JOURNAL": [
        "/journal/today",
        "/journal/morning-quiz/today",
        "/life/dashboard",
    ],
}

fail_count = 0
for tab, paths in tab_endpoints.items():
    print(f"\n  ── {tab} ──")
    for p in paths:
        ok, lbl, s = hit(p)
        mark = "✓" if ok else "✗"
        print(f"    {mark} {lbl[:55]:55s} {s[:60]}")
        if not ok:
            fail_count += 1

print("\n" + "=" * 78)
print(f"DONE — {fail_count} failing endpoints")
