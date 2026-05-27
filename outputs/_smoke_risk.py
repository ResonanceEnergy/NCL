import ast
import sys


for p in [
    "/Users/natrix/dev/NCL/runtime/portfolio/position_risk_state.py",
    "/Users/natrix/dev/NCL/runtime/api/routers/portfolio.py",
]:
    ast.parse(open(p).read())
    print("AST OK:", p.split("/")[-1])

sys.path.insert(0, "/Users/natrix/dev/NCL")
from runtime.portfolio.position_risk_state import (
    compute_R_dollars,
    enrich_positions_with_risk,
    get_risk_store,
    make_position_key,
    parse_position_key,
)


print("imports OK")

# Pure unit tests first
assert make_position_key("IBKR", "DU123", "NVDA") == "ibkr:du123:NVDA"
assert parse_position_key("ibkr:du123:NVDA") == ("ibkr", "du123", "NVDA")
assert compute_R_dollars(100, 95, 10) == 50.0
assert compute_R_dollars(None, 95, 10) is None
print("unit tests OK")

import asyncio


async def smoke():
    store = await get_risk_store()
    # Set R-fields for a synthetic position
    r = await store.set(
        broker="IBKR",
        account_id="DU123",
        symbol="NVDA",
        qty=100,
        entry_price=180.0,
        stop_price=170.0,
        stop_type="atr",
        stop_basis="2x ATR(14) below 50d SMA",
        target_price=210.0,
        target_basis="prior swing high",
        thesis="Q3 data-center growth + Blackwell ramp",
        metadata={"strategy_tag": "goat", "rotation_aligned": True},
    )
    print("set result keys:", sorted(r.keys()))
    print("R_dollars:", r["R_dollars"], "expected 1000.0")
    assert r["R_dollars"] == 1000.0
    assert r["risk_status"] == "at_risk"
    assert r["position_key"] == "ibkr:du123:NVDA"

    # Enrich a mock position list
    enriched = await enrich_positions_with_risk(
        [
            {"broker": "IBKR", "account_id": "DU123", "symbol": "NVDA", "quantity": 100},
            {"broker": "MOOMOO", "account_id": "M1", "symbol": "AAPL", "quantity": 50},
        ]
    )
    print(
        "enriched[0]:",
        {
            k: enriched[0][k]
            for k in ("symbol", "risk_status", "R_dollars", "stop_price", "thesis", "position_key")
        },
    )
    print(
        "enriched[1]:",
        {k: enriched[1][k] for k in ("symbol", "risk_status", "R_dollars", "position_key")},
    )
    assert enriched[0]["risk_status"] == "at_risk"
    assert enriched[0]["R_dollars"] == 1000.0
    assert enriched[1]["risk_status"] == "unset"
    assert enriched[1]["R_dollars"] is None

    # Aggregate
    agg = await store.aggregate()
    print("aggregate:", agg)
    assert agg["total_R_at_risk_usd"] >= 1000.0
    assert "goat" in agg["by_strategy"]


asyncio.run(smoke())
print("smoke OK")
