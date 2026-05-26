"""
NCL Mock Adapter — Wave 14J finisher

Shared mock adapter that fits PortfolioManager's adapter interface so
test_portfolio_manager.py can exercise the broker boundary without a
live broker connection.

The 6 real adapters (ibkr/moomoo/snaptrade/ndax/metamask/polymarket)
all expose the same shape to PortfolioManager:

  async connect() -> None
  async disconnect() -> None
  is_connected() -> bool
  async fetch_accounts() -> list[dict]
  async fetch_positions() -> list[dict]
  async fetch_quotes(symbols: list[str]) -> dict[str, float]
  health() -> dict

The mock implements the same shape with knobs for:
  - simulate_connect_failure  -> connect() raises
  - simulate_quote_failure    -> fetch_quotes returns {} or raises
  - simulate_partial_quotes   -> some symbols return None
  - simulate_disconnect_after_n_calls
  - canned_accounts / canned_positions / canned_quotes
  - canned_account_balance
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

log = logging.getLogger("ncl.portfolio.mock_adapter")


class MockBrokerError(Exception):
    pass


class MockAdapter:
    """Drop-in mock for any of the 6 broker adapters.

    Usage in tests:
        m = MockAdapter(broker_name="MOCK1",
                        canned_positions=[{"symbol": "NVDA", "quantity": 100, ...}])
        await m.connect()
        positions = await m.fetch_positions()
    """

    def __init__(
        self,
        *,
        broker_name: str = "MOCK",
        canned_accounts: Optional[list[dict]] = None,
        canned_positions: Optional[list[dict]] = None,
        canned_quotes: Optional[dict[str, float]] = None,
        simulate_connect_failure: bool = False,
        simulate_quote_failure: bool = False,
        simulate_partial_quotes: bool = False,
        simulate_disconnect_after_n_calls: Optional[int] = None,
        connect_delay_s: float = 0.0,
    ) -> None:
        self.broker = broker_name
        self.broker_name = broker_name  # alias
        self._canned_accounts = canned_accounts or [
            {
                "broker": broker_name,
                "account_id": f"MOCK-{broker_name}-001",
                "account_name": f"Mock {broker_name} Account",
                "buying_power": 100000.0,
                "cash": 30000.0,
                "nav": 100000.0,
                "currency": "USD",
            }
        ]
        self._canned_positions = canned_positions or []
        self._canned_quotes = canned_quotes or {}
        self._simulate_connect_failure = simulate_connect_failure
        self._simulate_quote_failure = simulate_quote_failure
        self._simulate_partial_quotes = simulate_partial_quotes
        self._simulate_disconnect_after = simulate_disconnect_after_n_calls
        self._connect_delay = connect_delay_s
        self._connected = False
        self._call_count = 0

    async def connect(self) -> None:
        await asyncio.sleep(self._connect_delay)
        if self._simulate_connect_failure:
            raise MockBrokerError(f"Simulated connect failure for {self.broker}")
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def _check_disconnect_window(self) -> None:
        self._call_count += 1
        if (
            self._simulate_disconnect_after is not None
            and self._call_count >= self._simulate_disconnect_after
        ):
            self._connected = False

    async def fetch_accounts(self) -> list[dict]:
        if not self._connected:
            raise MockBrokerError(f"{self.broker} not connected")
        self._check_disconnect_window()
        return list(self._canned_accounts)

    async def fetch_positions(self) -> list[dict]:
        if not self._connected:
            raise MockBrokerError(f"{self.broker} not connected")
        self._check_disconnect_window()
        return list(self._canned_positions)

    async def fetch_quotes(self, symbols: list[str]) -> dict[str, float]:
        if not self._connected:
            raise MockBrokerError(f"{self.broker} not connected")
        self._check_disconnect_window()
        if self._simulate_quote_failure:
            return {}
        out = {}
        for sym in symbols:
            if self._simulate_partial_quotes and hash(sym) % 2 == 0:
                continue  # half the symbols quote-fail
            if sym in self._canned_quotes:
                out[sym] = self._canned_quotes[sym]
            else:
                # Default fake quote — deterministic from symbol
                out[sym] = round(100.0 + (abs(hash(sym)) % 200), 2)
        return out

    def health(self) -> dict:
        return {
            "broker": self.broker,
            "connected": self._connected,
            "call_count": self._call_count,
            "accounts_cached": len(self._canned_accounts),
            "positions_cached": len(self._canned_positions),
            "simulated_failure_flags": {
                "connect": self._simulate_connect_failure,
                "quote": self._simulate_quote_failure,
                "partial_quote": self._simulate_partial_quotes,
                "disconnect_after_n": self._simulate_disconnect_after,
            },
        }


def make_canned_positions(*specs) -> list[dict]:
    """Test helper. Each spec is a tuple:
        (symbol, quantity, broker, asset_class[, price])
    """
    out = []
    for s in specs:
        sym, qty, broker = s[0], s[1], s[2]
        ac = s[3] if len(s) > 3 else "equity"
        price = s[4] if len(s) > 4 else 100.0
        out.append({
            "symbol": sym,
            "broker": broker,
            "account_id": f"{broker}-001",
            "quantity": qty,
            "current_price": price,
            "last_price": price,
            "avg_cost": price * 0.95,
            "market_value": qty * price,
            "currency": "USD",
            "asset_class": ac,
            "quote_ok": True,
        })
    return out
