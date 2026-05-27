import ast
import sys


for p in [
    "/Users/natrix/dev/NCL/runtime/portfolio/trade_cost_ledger.py",
    "/Users/natrix/dev/NCL/runtime/api/routers/portfolio.py",
]:
    ast.parse(open(p).read())
    print("AST OK:", p.split("/")[-1])

sys.path.insert(0, "/Users/natrix/dev/NCL")
from runtime.portfolio.trade_cost_ledger import (
    get_trade_cost_ledger,
    record_trade_cost,
)


print("imports OK")

import asyncio


async def smoke():
    # Record a smoke entry — the file lives at data/portfolio/trade_costs.jsonl
    # so it WILL persist; just a synthetic smoke row tagged for filtering.
    await record_trade_cost(
        broker="SMOKE",
        action="commission",
        amount_usd=0.001,
        symbol="SMOKE",
        asset_class="equity",
        strategy_tag="smoke_test",
        metadata={"smoke": True, "wave": "14J-J0a"},
    )
    ledger = await get_trade_cost_ledger()
    s = await ledger.summary_today()
    print("summary today total:", s["total_usd"], "entries:", s["entries"])
    print("by_broker:", s["by_broker"])
    print("by_action:", s["by_action"])
    recent = await ledger.recent_entries(limit=3)
    print("recent_count:", len(recent))


asyncio.run(smoke())
print("smoke OK")
