import json
import urllib.request


TOKEN = "QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU"
BASE = "http://100.72.223.123:8800"


def get(path):
    req = urllib.request.Request(f"{BASE}{path}", headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


print("=== AUTO-TRADER DASHBOARD ===")
d = get("/portfolio/auto-trader/dashboard")
s = d["state"]
print(
    f"  active: {s['active']}  paused_by: {s['paused_by']}  "
    f"dd_pause: {s['drawdown_halt_pause']}  band: {s['drawdown_halt_band']}"
)
print(f"  last_loop_tick: {s['last_loop_tick_iso']}")
print(
    f"  today: evaluated={s['ideas_evaluated_today']} "
    f"opened={s['ideas_opened_today']} rejected={s['ideas_rejected_today']}"
)
print(f"  top_strategies: {len(d['top_strategies'])}")
print(f"  drift: {d['drift']}")
print(f"  graduation: {d['graduation']}")
print(f"  friction: {d['friction']}")
print(f"  recent_closes: {len(d['recent_closes'])}")
print(f"  research_topics: {d['research_topics']}")

print()
print("=== PAPER STATS ===")
p = get("/paper/stats")
print(
    f"  total_trades: {p['total_trades']}  open: {p['open_trades']}  closed: {p['closed_trades']}"
)
print(f"  open_unrealized_pl: ${p['open_unrealized_pl']:.2f}")
print(f"  account_balance: ${p['account_balance']:.2f}")
bs = p.get("by_strategy", {})
print(f"  strategies tracked: {list(bs.keys())}")
for k, v in bs.items():
    print(f"    {k}: {v.get('total_trades')} trades, win_rate={v.get('win_rate')}")

print()
print("=== POLICY ===")
po = get("/portfolio/auto-trader/policy")
print(f"  rev={po['revision']} updated_by={po['updated_by']}")
print(f"  max_opens/tick={po['max_opens_per_tick']}  " f"max_opens/day={po['max_opens_per_day']}")
print(f"  min_R:R={po['min_R_R_ratio']}  " f"allow_counter_trend={po['allow_counter_trend']}")
print(f"  notes: {po['notes'][:120]}")

print()
print("=== CIRCUIT BREAKERS ===")
cb = get("/portfolio/auto-trader/circuit-breakers")
for b in cb["breakers"]:
    print(f"  {b['name']}: fails={b['fails']} open={b['is_open']}")
