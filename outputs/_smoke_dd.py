import ast
import sys


for p in [
    "/Users/natrix/dev/NCL/runtime/portfolio/drawdown_bucket.py",
    "/Users/natrix/dev/NCL/runtime/autonomous/scheduler.py",
    "/Users/natrix/dev/NCL/runtime/api/routers/portfolio.py",
]:
    ast.parse(open(p).read())
    print("AST OK:", p.split("/")[-1])

sys.path.insert(0, "/Users/natrix/dev/NCL")
from runtime.portfolio.drawdown_bucket import (
    _classify,
    _peak_from_snapshots,
    get_drawdown_bucket,
    get_sizing_multiplier_sync,
)


print("imports OK")

# Pure classifier tests
assert _classify(0.0) == ("green", 1.00)
assert _classify(-2.5) == ("green", 1.00)
assert _classify(-3.0) == ("green", 1.00)
assert _classify(-3.5) == ("caution", 0.75)
assert _classify(-7.0) == ("caution", 0.75)
assert _classify(-7.5) == ("warning", 0.50)
assert _classify(-12.0) == ("warning", 0.50)
assert _classify(-12.5) == ("halt", 0.00)
assert _classify(-50.0) == ("halt", 0.00)
print("classifier tests OK")

# Replay live snapshots
peak, peak_date, n = _peak_from_snapshots(lookback_days=90)
print(f"snapshot replay: peak=${peak:.2f} on {peak_date} from {n} samples")

import asyncio


async def smoke():
    bucket = await get_drawdown_bucket()

    # Compute against various synthetic NAVs to exercise band transitions
    for nav in (0.0, 50000.0, 49000.0, 47000.0, 44000.0, 41000.0, 55000.0):
        state = await bucket.compute(nav)
        print(
            f"  nav=${nav:>8.2f}  peak=${state['peak_nav_cad']:>8.2f}  "
            f"dd={state['drawdown_pct']:>+8.2f}%  "
            f"band={state['band']:<8}  mult={state['sizing_multiplier']}"
        )

    # Manual peak override
    over = await bucket.set_manual_peak(50000.0, note="smoke override")
    print(f"after override: manual_peak={over['manual_peak_override']} notes={over['notes']!r}")
    state = await bucket.compute(45000.0)
    print(
        f"after recompute @ nav=45000 with override 50000: dd={state['drawdown_pct']}% band={state['band']}"
    )
    # Clear override
    over = await bucket.set_manual_peak(None, note="")
    print(f"override cleared: manual_peak={over['manual_peak_override']}")

    # Sync multiplier accessor
    print("sync multiplier:", get_sizing_multiplier_sync())


asyncio.run(smoke())
print("smoke OK")
