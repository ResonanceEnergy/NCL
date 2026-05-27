import ast
import sys


for p in [
    "/Users/natrix/dev/NCL/runtime/portfolio/risk_governor.py",
    "/Users/natrix/dev/NCL/runtime/api/routers/portfolio.py",
    "/Users/natrix/dev/NCL/runtime/api/routes.py",
]:
    ast.parse(open(p).read())
    print("AST OK:", p.split("/")[-1])

sys.path.insert(0, "/Users/natrix/dev/NCL")
from runtime.portfolio.risk_governor import (
    _normalize_strategy,
    _resolve_budgets_pct,
    check_proposed_trade,
    heat_summary,
)


print("imports OK")

# Tag normalization
assert _normalize_strategy("GOAT") == "goat"
assert _normalize_strategy("Momentum") == "goat"
assert _normalize_strategy("bravo") == "bravo"
assert _normalize_strategy("iron_condor") == "options"
assert _normalize_strategy("Polymarket") == "polymarket"
assert _normalize_strategy(None) == "unknown"
assert _normalize_strategy("xyz_random") == "unknown"
print("normalize tests OK")

b = _resolve_budgets_pct()
print("default budgets pct:", b)

import asyncio


async def smoke():
    # NAV forced via override so tests are deterministic regardless of
    # current portfolio state.
    NAV = 100000.0

    # Reset drawdown bucket to known-fresh state — earlier smoke tests
    # left manual override pinned which would put governor in halt.
    from runtime.portfolio.drawdown_bucket import get_drawdown_bucket

    bucket = await get_drawdown_bucket()
    await bucket.set_manual_peak(None, note="")  # clear any prior override
    await bucket.compute(NAV)  # force green band against NAV peak

    # 1. Small reasonable trade in goat — should approve
    d = await check_proposed_trade(
        strategy_tag="goat",
        R_dollars_proposed=500.0,
        nav_cad_override=NAV,
    )
    print(
        f"goat $500 R: decision={d['decision']} approved={d['approved']} "
        f"effective_R=${d['effective_R_dollars']} band={d['band']} mult={d['sizing_multiplier']}"
    )
    assert d["decision"] in ("approve", "throttle")

    # 2. Massive trade that blows total cap — should reject
    d = await check_proposed_trade(
        strategy_tag="goat",
        R_dollars_proposed=15000.0,  # 15% of NAV — over 10% total cap
        nav_cad_override=NAV,
    )
    print(f"goat $15K R: decision={d['decision']} reasons[0]={d['reasons'][0][:80]}")
    assert not d["approved"]
    assert "Total heat" in d["reasons"][0] or "Strategy" in d["reasons"][0]

    # 3. Trade that breaches per-strategy cap but not total
    # (goat cap default 3% of NAV = $3000; total cap 10% = $10000)
    d = await check_proposed_trade(
        strategy_tag="goat",
        R_dollars_proposed=4000.0,  # 4% of NAV
        nav_cad_override=NAV,
    )
    print(f"goat $4K R: decision={d['decision']} reasons[0]={d['reasons'][0][:80]}")
    assert not d["approved"]
    assert "Strategy 'goat'" in d["reasons"][0]

    # 4. Options bucket cap should be higher
    d = await check_proposed_trade(
        strategy_tag="iron_condor",
        R_dollars_proposed=3500.0,  # 3.5% — under options 4% cap
        nav_cad_override=NAV,
    )
    print(f"iron_condor $3.5K R: decision={d['decision']} approved={d['approved']}")
    assert d["approved"]

    # 5. Heat summary
    h = await heat_summary(nav_cad_override=NAV)
    print(
        f"heat summary: nav={h['nav_cad']} band={h['band']} mult={h['sizing_multiplier']} "
        f"total_util={h['total']['utilization']}"
    )
    print(
        f"  goat util={h['by_strategy']['goat']['utilization']} "
        f"cap=${h['by_strategy']['goat']['cap_R']}"
    )


asyncio.run(smoke())
print("smoke OK")
