#!/usr/bin/env python3
"""Full system audit — pulls everything from REST endpoints + scheduler state."""

import json
import subprocess
from datetime import datetime


BASE = "http://100.72.223.123:8800"
TOKEN = "QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU"
H = ["-H", f"Authorization: Bearer {TOKEN}"]


def fetch(path):
    try:
        r = subprocess.run(
            ["curl", "-sS", "-m", "10"] + H + [f"{BASE}{path}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode != 0:
            return {"_err": f"curl failed: {r.returncode}"}
        return json.loads(r.stdout)
    except Exception as e:
        return {"_err": str(e)}


print("=" * 70)
print(f"NCL SYSTEM AUDIT  {datetime.now().isoformat(timespec='seconds')}")
print("=" * 70)

# 1. Brain alive
print("\n[1] BRAIN ALIVE")
r = subprocess.run(["curl", "-sS", "-m", "5", f"{BASE}/"], capture_output=True, text=True)
print(f"  root: {r.stdout[:80]}")

# 2. Health rollup
print("\n[2] HEALTH ROLLUP")
h = fetch("/system/health/rollup")
if "_err" in h:
    print(f"  ERR: {h['_err']}")
else:
    print(f"  overall: {h.get('overall')}")
    for k, v in (h.get("components") or {}).items():
        status = v.get("status") if isinstance(v, dict) else v
        extra = ""
        if isinstance(v, dict):
            if v.get("active_tasks") is not None:
                extra = f" active={v['active_tasks']} dead={len(v.get('dead_tasks') or [])} stale={len(v.get('stale_loops') or [])}"
            elif v.get("units") is not None:
                extra = f" units={v.get('units')}"
            elif v.get("reason"):
                extra = f" — {v['reason'][:60]}"
        print(f"  {k:14s}: {status}{extra}")

# 3. Scheduler loops
print("\n[3] SCHEDULER LOOPS")
loops = fetch("/autonomous/loops")
if "_err" in loops:
    print(f"  ERR: {loops['_err']}")
else:
    tasks = loops.get("tasks") or loops.get("loops") or []
    if isinstance(tasks, list):
        running = sum(
            1 for t in tasks if t.get("state") in ("running", "ACTIVE") or t.get("active")
        )
        total = len(tasks)
        print(f"  total: {total}, running: {running}")
        # show non-running
        for t in tasks:
            state = t.get("state") or ("running" if t.get("active") else "?")
            if state not in ("running", "ACTIVE", "active"):
                name = t.get("name") or t.get("task")
                print(f"  NOT RUNNING: {name} state={state}")
    else:
        print(f"  shape: {type(tasks).__name__}")

# 4. Auto-trader state
print("\n[4] AUTO-TRADER STATE")
at = fetch("/portfolio/auto-trader/dashboard")
if "_err" in at:
    print(f"  ERR: {at['_err']}")
else:
    s = at.get("state") or {}
    print(
        f"  active: {s.get('active')}  paused_by: {s.get('paused_by')}  dd_halt: {s.get('drawdown_halt_pause')}"
    )
    print(f"  last_loop_tick: {s.get('last_loop_tick_iso')}")
    print(
        f"  today: evaluated={s.get('ideas_evaluated_today')} opened={s.get('ideas_opened_today')} rejected={s.get('ideas_rejected_today')}"
    )
    reg = at.get("registry") or {}
    print(f"  registry: {reg.get('enabled_count')}/{reg.get('total_recipes')} recipes enabled")
    cap = at.get("capabilities") or {}
    print(f"  capabilities: {cap.get('available_count')} avail / {cap.get('gap_count')} gaps")
    scout = at.get("scout") or {}
    print(f"  scout last tick: {scout.get('last_tick_iso')}")
    ladder = at.get("ladder") or {}
    print(f"  ladder: enabled={ladder.get('enabled')} fired={ladder.get('total_laddered_ever')}")

# 5. Auto-trader circuit breakers
print("\n[5] AUTO-TRADER CIRCUIT BREAKERS")
cb = fetch("/portfolio/auto-trader/circuit-breakers")
if "_err" in cb:
    print(f"  ERR: {cb['_err']}")
else:
    breakers = cb.get("breakers", [])
    open_b = [b for b in breakers if b.get("is_open")]
    print(f"  {len(breakers)} breakers, {len(open_b)} OPEN")
    for b in open_b:
        print(f"  OPEN: {b.get('name')} fails={b.get('fails')} skip_s={b.get('remaining_skip_s')}")
    for b in breakers:
        if not b.get("is_open") and b.get("fails", 0) > 0:
            print(f"  warn: {b['name']} fails={b['fails']}")

# 6. Costs
print("\n[6] COSTS TODAY")
c = fetch("/system/costs")
if "_err" in c:
    print(f"  ERR: {c['_err']}")
else:
    print(f"  total: ${c.get('total_usd', 0):.4f}  cap: ${c.get('daily_cap_usd', 'n/a')}")
    by_src = c.get("by_source") or {}
    for src, info in sorted(
        by_src.items(),
        key=lambda x: -float(x[1].get("cost_usd", 0)) if isinstance(x[1], dict) else 0,
    ):
        if isinstance(info, dict):
            cost = info.get("cost_usd", 0)
            cap = info.get("daily_cap_usd", 0)
            pct = (cost / cap * 100) if cap else 0
            print(f"  {src:14s}: ${cost:7.4f} / ${cap:6.2f} ({pct:5.1f}%)")

# 7. Awarebot
print("\n[7] AWAREBOT")
ab = fetch("/intelligence/stats")
if "_err" in ab:
    print(f"  ERR: {ab['_err']}")
else:
    print(f"  signals: {ab.get('signal_count')}  sources: {ab.get('source_count')}")
    print(f"  last_scan: {ab.get('last_scan_at')}")
    print(f"  routed: {ab.get('signals_routed')}  hi/crit: {ab.get('high_critical_count')}")

# 8. Memory
print("\n[8] MEMORY")
m = fetch("/memory/stats")
if "_err" in m:
    print(f"  ERR: {m['_err']}")
else:
    print(f"  units: {m.get('total_units') or m.get('units')}")
    print(f"  working_context_size: {m.get('working_context_size')}")

# 9. Portfolio
print("\n[9] PORTFOLIO")
p = fetch("/portfolio/summary")
if "_err" in p:
    print(f"  ERR: {p['_err']}")
else:
    print(
        f"  NAV: ${p.get('total_equity_cad', 0):,.2f} CAD  ({p.get('total_equity_usd', 0):,.2f} USD)"
    )
    print(f"  positions: {p.get('positions_count')}  quotes_failed: {p.get('quotes_failed', 0)}")
    print(f"  fx_rate: {p.get('fx_rate_usd_cad', p.get('fx_rate', 'n/a'))}")

# 10. Calendar freshness
print("\n[10] CALENDAR")
cal = fetch("/calendar/today")
if "_err" in cal:
    print(f"  ERR: {cal['_err']}")
else:
    print(f"  date: {cal.get('date')}")
    moon = cal.get("moon") or {}
    print(f"  moon: {moon.get('phase')} ({moon.get('illumination_pct', 0):.0f}%)")
    print(f"  events_today: {len(cal.get('events_today') or [])}")

print("\n" + "=" * 70)
print("DONE")
