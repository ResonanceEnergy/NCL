"""
NCL Position Streaming Scaffold — Wave 14J out-of-scope finisher

NOT a live WebSocket subscriber. This is the BASE CLASS that an opt-in
adapter (e.g. IBKR ib_insync updateEvent, Moomoo's push trade callback)
can subclass when J7c slippage data shows the 60s polling lag matters.

Today's PortfolioManager polls every 60s in market hours. For most
NCL use cases this is fine. If slippage analysis reveals that fills
arrive faster than the polling can react (e.g. operator-set stops
trigger but the position cache doesn't reflect the fill for up to 60s),
we'll wire one adapter to push deltas in real time.

Architecture:
  - PositionDeltaPublisher: pure abstract; subclass per broker
  - PositionDeltaConsumer: receives delta events, applies to cache,
    triggers risk_governor re-check + drawdown_bucket recompute
  - DeltaEvent dataclass: {symbol, broker, account_id, qty_delta,
                          new_qty, price, ts, source}

When the time comes:
  class IBKRDeltaPublisher(PositionDeltaPublisher):
      async def start(self):
          # ib_insync wires up an updateEvent handler
          self._ib.updateEvent += self._on_update
          ...

For now this module just defines the contract. No live streams open;
no event loops eating CPU; opt-in only.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Callable, Awaitable

log = logging.getLogger("ncl.portfolio.streaming_scaffold")


@dataclass
class DeltaEvent:
    symbol: str
    broker: str
    account_id: str
    qty_delta: float          # signed
    new_qty: float
    price: Optional[float]
    timestamp_iso: str
    source: str               # "ibkr_updateEvent" | "moomoo_push" | etc.
    metadata: dict = field(default_factory=dict)


DeltaHandler = Callable[[DeltaEvent], Awaitable[None]]


class PositionDeltaPublisher:
    """Base class for opt-in real-time position streams.

    Subclasses MUST implement:
      async def start() -> None      — open WebSocket, register handlers
      async def stop()  -> None      — clean shutdown
      def is_active() -> bool

    Subclasses CALL `self._emit(DeltaEvent)` from their internal handlers.
    """

    def __init__(self, broker: str) -> None:
        self.broker = broker
        self._handlers: list[DeltaHandler] = []
        self._active = False
        self._lock = asyncio.Lock()

    def subscribe(self, handler: DeltaHandler) -> None:
        self._handlers.append(handler)

    def unsubscribe(self, handler: DeltaHandler) -> None:
        try:
            self._handlers.remove(handler)
        except ValueError:
            pass

    async def _emit(self, evt: DeltaEvent) -> None:
        """Fan-out an event to all subscribed handlers. Errors in one
        handler don't block the others."""
        for h in list(self._handlers):
            try:
                await h(evt)
            except Exception as e:
                log.warning("[STREAM:%s] handler %r raised: %s", self.broker, h, e)

    async def start(self) -> None:
        raise NotImplementedError("subclass must open the stream")

    async def stop(self) -> None:
        raise NotImplementedError("subclass must close the stream")

    def is_active(self) -> bool:
        return self._active


class PositionDeltaConsumer:
    """Sample consumer: applies deltas to a cache dict + optionally
    recomputes drawdown_bucket / risk_governor heat on each event.

    Operator wires this into PortfolioManager via:
        consumer = PositionDeltaConsumer(position_cache=pm._positions)
        publisher.subscribe(consumer.on_delta)

    Use when the polling lag actually matters; opt-in.
    """

    def __init__(
        self,
        position_cache: list[dict],
        on_delta_callback: Optional[Callable[[DeltaEvent], Awaitable[None]]] = None,
    ) -> None:
        self._positions = position_cache
        self._on_callback = on_delta_callback
        self.deltas_applied = 0

    async def on_delta(self, evt: DeltaEvent) -> None:
        # Locate matching position in cache
        found = None
        for p in self._positions:
            if (
                (p.get("symbol") or "").upper() == evt.symbol.upper()
                and (p.get("account_id") or "") == evt.account_id
            ):
                found = p
                break
        if found is None:
            # New position appeared via stream
            self._positions.append({
                "symbol": evt.symbol.upper(),
                "broker": evt.broker,
                "account_id": evt.account_id,
                "quantity": evt.new_qty,
                "current_price": evt.price,
            })
        else:
            found["quantity"] = evt.new_qty
            if evt.price is not None:
                found["current_price"] = evt.price
                found["last_price"] = evt.price
            found["quote_timestamp"] = evt.timestamp_iso
        self.deltas_applied += 1
        if self._on_callback:
            try:
                await self._on_callback(evt)
            except Exception as e:
                log.warning("[STREAM] downstream callback raised: %s", e)


# Convenience factory for the most-likely-first publisher
class MockDeltaPublisher(PositionDeltaPublisher):
    """Test/dev publisher — emits canned events on demand."""
    async def start(self) -> None:
        async with self._lock:
            self._active = True

    async def stop(self) -> None:
        async with self._lock:
            self._active = False

    async def emit_test(
        self,
        *,
        symbol: str,
        broker: str = "MOCK",
        account_id: str = "TEST",
        qty_delta: float = 0.0,
        new_qty: float = 0.0,
        price: Optional[float] = None,
    ) -> None:
        evt = DeltaEvent(
            symbol=symbol.upper(),
            broker=broker,
            account_id=account_id,
            qty_delta=qty_delta,
            new_qty=new_qty,
            price=price,
            timestamp_iso=datetime.now(timezone.utc).isoformat(),
            source="mock_test",
        )
        await self._emit(evt)
