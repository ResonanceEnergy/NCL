import ast
import sys


for p in [
    "/Users/natrix/dev/NCL/runtime/portfolio/trade_idea_tracker.py",
    "/Users/natrix/dev/NCL/runtime/api/routers/intel/brief_pipeline.py",
    "/Users/natrix/dev/NCL/runtime/api/routers/portfolio.py",
]:
    ast.parse(open(p).read())
    print("AST OK:", p.split("/")[-1])

sys.path.insert(0, "/Users/natrix/dev/NCL")
from runtime.portfolio.trade_idea_tracker import (
    TradeIdea,
    _compute_holding_days,
    _compute_R_multiple,
    get_trade_idea_tracker,
    record_trade_idea_emission,
)


print("imports OK")

# Pure unit tests
idea = TradeIdea(
    trade_idea_id="t1",
    source="brief",
    strategy="goat",
    ticker="NVDA",
    direction="long",
    entry_price=180,
    R_per_share=10,
    issued_at_iso="2026-05-26T00:00:00+00:00",
)
assert _compute_R_multiple(idea, 200) == 2.0  # +20 / 10 = +2R win
assert _compute_R_multiple(idea, 170) == -1.0  # -10 / 10 = -1R loss
idea.direction = "short"
assert _compute_R_multiple(idea, 170) == 1.0  # short, exit lower = +1R win
print("R_multiple tests OK")

hd = _compute_holding_days(idea, "2026-05-28T12:00:00+00:00")
assert hd == 2.5  # 2 days 12 hours
print("holding_days test OK")

import asyncio


async def smoke():
    tracker = await get_trade_idea_tracker()

    # Emit 3 ideas across 2 strategies
    i1 = await record_trade_idea_emission(
        source="brief",
        strategy="goat",
        ticker="NVDA",
        direction="long",
        entry_price=180,
        stop_price=170,
        target_price=210,
        R_per_share=10,
        stop_type="atr",
        stop_basis="2x ATR below 50d SMA",
        target_basis="prior swing high",
        thesis="Blackwell ramp",
    )
    print("emitted:", i1["trade_idea_id"], i1["strategy"], i1["outcome"])
    i2 = await record_trade_idea_emission(
        source="brief",
        strategy="goat",
        ticker="AMD",
        direction="long",
        entry_price=140,
        stop_price=132,
        target_price=160,
        R_per_share=8,
        stop_type="price",
        stop_basis="below 20d low",
        target_basis="May 2026 high",
        thesis="AI accel competition",
    )
    i3 = await record_trade_idea_emission(
        source="brief",
        strategy="bravo",
        ticker="AAPL",
        direction="long",
        entry_price=195,
        stop_price=188,
        target_price=215,
        R_per_share=7,
        stop_type="price",
        stop_basis="below 50d SMA",
        target_basis="prior all-time-high",
        thesis="Vision Pro 2 demand",
    )
    print("emitted 3 ideas, ids:", [i1["trade_idea_id"], i2["trade_idea_id"], i3["trade_idea_id"]])

    # Close one as a +2R winner
    closed = await tracker.update_outcome(i1["trade_idea_id"], outcome="target_hit", exit_price=200)
    print(f"closed NVDA at $200: R_multiple={closed['R_multiple']} outcome={closed['outcome']}")
    assert closed["R_multiple"] == 2.0

    # Close one as a -1R loser
    closed = await tracker.update_outcome(
        i2["trade_idea_id"], outcome="stopped_out", exit_price=132
    )
    print(f"closed AMD at $132: R_multiple={closed['R_multiple']} outcome={closed['outcome']}")
    assert closed["R_multiple"] == -1.0

    # Expectancy
    exp = await tracker.expectancy_by_strategy()
    goat = exp.get("goat", {})
    print(
        f"goat stats: n_closed={goat['n_closed']} hit_rate={goat['hit_rate']} "
        f"avg_win_R={goat['avg_win_R']} avg_loss_R={goat['avg_loss_R']} "
        f"expectancy_R={goat['expectancy_R']} profit_factor={goat['profit_factor']}"
    )
    assert goat["n_closed"] == 2
    assert goat["hit_rate"] == 0.5
    # expectancy = 0.5*2 - 0.5*1 = 0.5
    assert goat["expectancy_R"] == 0.5

    # Bravo still 0-closed
    bravo = exp.get("bravo", {})
    print(f"bravo stats: n_emitted={bravo['n_emitted']} n_closed={bravo['n_closed']}")
    assert bravo["n_emitted"] >= 1
    assert bravo["n_closed"] == 0

    # _all rollup
    all_stats = exp["_all"]
    print(f"_all: n_emitted={all_stats['n_emitted']} n_closed={all_stats['n_closed']}")


asyncio.run(smoke())
print("smoke OK")
