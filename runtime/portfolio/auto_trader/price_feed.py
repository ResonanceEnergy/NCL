"""
Auto-Trader price feed — Wave 14K Phase 3 (K2a + K2d)

Pulls quotes for open paper-trade symbols and applies them to
PaperTradingEngine.update_prices(). Any triggered events (stop /
target / trailing / time-exit) flow into outcome_attributor.attribute_batch.

Cadence: 30s in market hours, 300s off-hours.

Quote source: quote_source.default_quote_chain() (J0c-era abstraction).
Fall-through chain: operator static overrides → yfinance cached 30s.

Self-healing:
  - Empty open_symbols → skip tick (no work to do)
  - Quote source returns None for all → log + skip; no false closes
  - update_prices() raises → log + continue (don't kill loop)
  - attribute_batch raises per-event → caught per-event in attributor
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.price_feed")

TICK_MARKET = 30   # seconds
TICK_OFFHOURS = 300


def _is_market_open(now: Optional[datetime] = None) -> bool:
    """Match loop.py's classifier — M-F 09:30-16:00 ET (UTC-4 EDT approx)."""
    now = now or datetime.now(timezone.utc)
    et_hour = (now.hour - 4) % 24
    if now.weekday() >= 5:
        return False
    return (et_hour, now.minute) >= (9, 30) and et_hour < 16


async def price_feed_loop(brain) -> None:
    """ncl-auto-trader-prices scheduler task. Runs forever."""
    log.info("[AT-PRICE] starting price-feed loop")
    # Late imports — keep module import-safe in tests
    from ..paper_trading import PaperTradingEngine
    from ..quote_source import default_quote_chain
    from .outcome_attributor import attribute_batch
    from .state import is_active

    paper = PaperTradingEngine()
    chain = default_quote_chain()

    while True:
        try:
            # Cadence
            tick_secs = TICK_MARKET if _is_market_open() else TICK_OFFHOURS

            # Even if auto-trader is paused, we STILL keep marking-to-
            # market existing open paper trades — pause stops NEW opens
            # via loop.py, not existing-position management. (Operator
            # might pause manually mid-day but the trades they took
            # before still need price updates so they hit their stops.)
            #
            # If you want a full freeze, send a separate "freeze" signal.
            # Today: price feed always runs.
            try:
                open_symbols = paper.get_open_symbols() or []
            except Exception as e:
                log.warning("[AT-PRICE] get_open_symbols failed: %s", e)
                await asyncio.sleep(tick_secs)
                continue

            if not open_symbols:
                # No work — sleep + continue
                await asyncio.sleep(tick_secs)
                continue

            # Fetch quotes via chain (cached 30s per default)
            prices: dict[str, float] = {}
            miss = 0
            for sym in open_symbols:
                try:
                    px = await chain.get(sym)
                except Exception as e:
                    log.debug("[AT-PRICE] quote fetch failed for %s: %s", sym, e)
                    px = None
                if px is not None and px > 0:
                    prices[sym] = float(px)
                else:
                    miss += 1

            if not prices:
                log.warning(
                    "[AT-PRICE] all %d symbols quote-failed; skipping tick",
                    len(open_symbols),
                )
                await asyncio.sleep(tick_secs)
                continue

            if miss > 0:
                log.info(
                    "[AT-PRICE] %d/%d quoted (miss=%d)",
                    len(prices), len(open_symbols), miss,
                )

            # Apply prices — returns triggered events
            try:
                events = paper.update_prices(prices) or []
            except Exception as e:
                log.error("[AT-PRICE] update_prices raised: %s", e, exc_info=True)
                await asyncio.sleep(tick_secs)
                continue

            if events:
                log.info("[AT-PRICE] %d trigger event(s) this tick", len(events))
                results = await attribute_batch(
                    brain=brain, paper_engine=paper,
                    triggered_events=events,
                )
                wins = sum(1 for r in results
                          if r.get("ok") and (r.get("engine_R_multiple") or 0) > 0)
                losses = sum(1 for r in results
                            if r.get("ok") and (r.get("engine_R_multiple") or 0) < 0)
                drifts = sum(1 for r in results if r.get("r_drift_warning"))
                log.info(
                    "[AT-PRICE] attributed: wins=%d losses=%d r_drifts=%d",
                    wins, losses, drifts,
                )
            # else: silent — most ticks are no-ops which is fine

        except asyncio.CancelledError:
            log.info("[AT-PRICE] cancelled")
            raise
        except Exception as e:
            log.error("[AT-PRICE] tick error: %s", e, exc_info=True)

        await asyncio.sleep(tick_secs)
