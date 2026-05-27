import ast
import sys


for p in [
    "/Users/natrix/dev/NCL/runtime/portfolio/options_portfolio.py",
    "/Users/natrix/dev/NCL/runtime/api/routers/portfolio.py",
    "/Users/natrix/dev/NCL/runtime/api/routers/intel/brief_pipeline.py",
]:
    ast.parse(open(p).read())
    print("AST OK:", p.split("/")[-1])

sys.path.insert(0, "/Users/natrix/dev/NCL")
from runtime.portfolio.options_portfolio import (
    _is_option,
    aggregate_greeks,
    compute_position_greeks,
    dte_watchlist,
    pin_risk_watchlist,
)


print("imports OK")

# Smoke positions — mix of equity, short put, long call, short Friday-expiry put
from datetime import datetime, timedelta, timezone


# Build positions with OCC-style symbols
# OCC format: ROOT+YYMMDD+C/P+STRIKE(8d, 1/1000)
# NVDA short put 200506P190 = 2025-05-06 P $190 — should be EXPIRED so dte<0
# NVDA short put 261218P190 = 2026-12-18 P $190 — long-dated
# AAPL short call expiring this Friday at +0.4% spot for pin risk
this_friday = datetime.now(timezone.utc).date()
# walk forward to next Friday
while this_friday.weekday() != 4:
    this_friday += timedelta(days=1)
yymmdd = this_friday.strftime("%y%m%d")
near_friday_sym = f"AAPL{yymmdd}P00200000"  # $200 strike put, friday
# DTE 14 short put (inside 21-DTE window)
in14 = datetime.now(timezone.utc).date() + timedelta(days=14)
yymmdd14 = in14.strftime("%y%m%d")
in14_sym = f"NVDA{yymmdd14}P00180000"  # NVDA short put $180

positions = [
    {"symbol": "NVDA", "asset_class": "equity", "quantity": 100, "last_price": 185.0},
    {
        "symbol": "AAPL",
        "asset_class": "equity",
        "quantity": 50,
        "last_price": 200.50,
    },  # within 0.5% of $200
    {
        "symbol": in14_sym,
        "asset_class": "option",
        "quantity": -2,
        "underlying_price": 185.0,
    },  # short put DTE=14
    {
        "symbol": near_friday_sym,
        "asset_class": "option",
        "quantity": -1,
        "underlying_price": 200.50,
    },  # short put expiring Friday near strike
]

# _is_option detection
assert _is_option(positions[0]) is False
assert _is_option(positions[2]) is True
assert _is_option(positions[3]) is True
print("_is_option OK")

# Greeks computation
spot_lookup = {"NVDA": 185.0, "AAPL": 200.50}
per = compute_position_greeks(positions, spot_lookup=spot_lookup)
print(f"per-position greeks for {len(per)} options:")
for g in per:
    print(
        f"  {g.symbol}: delta={g.delta} gamma={g.gamma} theta={g.theta} vega={g.vega} dte={g.dte} short={g.is_short}"
    )

# Aggregate
agg = aggregate_greeks(per, nav_cad=50000)
print(f"net: {agg['net']}")
print(f"by_underlying: {agg['by_underlying']}")
print(f"budgets: {agg['budgets']}")
print(f"flags: {agg['flags']}")
assert agg["position_count"] == 2

# DTE watchlist
candidates = dte_watchlist(positions, threshold=21)
print(f"DTE watchlist ({len(candidates)} candidates):")
for c in candidates:
    print(f"  {c['symbol']} dte={c['dte']} rec={c['recommendation']}")
assert any(c["dte"] <= 21 for c in candidates)

pinned = pin_risk_watchlist(positions, spot_lookup=spot_lookup, pct=1.0)
print(f"Pin risk ({len(pinned)} candidates):")
for c in pinned:
    print(f"  {c['symbol']} gap={c['gap_pct']}% days_until={c['days_until_expiry']}")

print("smoke OK")
