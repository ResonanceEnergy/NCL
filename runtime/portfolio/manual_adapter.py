"""
NCL Manual-Entry Adapter — Wave 14J out-of-scope finisher

The "7th broker" the audit said wasn't needed turns out to be useful
in one specific shape: a manual-entry adapter for holdings that DON'T
have an API. Cold-storage Bitcoin, paper certificates, private
placements, employer stock pre-IPO, real estate REIT tokens — all
exist in real portfolios and have nowhere to live in the current
6-adapter setup.

This is NOT a 7th broker in the audit's sense. It's a fallback for the
6 brokers' coverage gaps. The interface matches MockAdapter exactly
(same 7 methods PortfolioManager calls) so it slots in alongside the
live adapters with zero PortfolioManager changes.

Storage: data/portfolio/manual_holdings.json (operator-maintained,
single JSON file). Operator edits the file directly OR uses the REST
endpoints exposed in portfolio.py.

Shape:
  {
    "accounts": [
      {
        "broker": "MANUAL",
        "account_id": "cold-storage-1",
        "account_name": "Trezor Hardware Wallet",
        "cash": 0.0,
        "nav": 0.0,
        "currency": "USD"
      }
    ],
    "positions": [
      {
        "symbol": "BTC",
        "broker": "MANUAL",
        "account_id": "cold-storage-1",
        "quantity": 0.5,
        "avg_cost": 45000.0,
        "current_price": 90000.0,
        "currency": "USD",
        "asset_class": "crypto",
        "notes": "Cold storage; not for sale unless thesis breaks"
      }
    ]
  }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.manual_adapter")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
MANUAL_FILE = NCL_BASE / "data" / "portfolio" / "manual_holdings.json"


class ManualAdapter:
    """Same 7-method interface as the 6 live broker adapters."""

    def __init__(self, broker_name: str = "MANUAL") -> None:
        self.broker = broker_name
        self.broker_name = broker_name
        self._connected = False
        self._lock = asyncio.Lock()
        self._cache: dict = {"accounts": [], "positions": []}

    async def connect(self) -> None:
        """Loads the manual_holdings.json file. Errors only if the file is
        malformed; missing file is treated as empty holdings (operator may
        not use this adapter yet)."""
        async with self._lock:
            if MANUAL_FILE.exists():
                try:
                    raw = json.loads(MANUAL_FILE.read_text())
                    if not isinstance(raw, dict):
                        raise ValueError("manual_holdings.json must be a dict")
                    self._cache = {
                        "accounts": raw.get("accounts") or [],
                        "positions": raw.get("positions") or [],
                    }
                except Exception as e:
                    log.error("[MANUAL] load failed: %s", e)
                    raise
            self._connected = True
            log.info(
                "[MANUAL] connected — %d accounts, %d positions",
                len(self._cache["accounts"]), len(self._cache["positions"]),
            )

    async def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    async def fetch_accounts(self) -> list[dict]:
        if not self._connected:
            await self.connect()
        return list(self._cache["accounts"])

    async def fetch_positions(self) -> list[dict]:
        if not self._connected:
            await self.connect()
        return list(self._cache["positions"])

    async def fetch_quotes(self, symbols: list[str]) -> dict[str, float]:
        """Manual adapter has no quote feed — operator-set `current_price`
        on each position is used directly by PortfolioManager. This method
        returns empty so the quote-fill chain falls through to yfinance."""
        return {}

    def health(self) -> dict:
        return {
            "broker": self.broker,
            "connected": self._connected,
            "file_exists": MANUAL_FILE.exists(),
            "accounts_cached": len(self._cache["accounts"]),
            "positions_cached": len(self._cache["positions"]),
            "manual_file_path": str(MANUAL_FILE),
        }

    # ── Operator-facing helpers (the REST endpoints call these) ────

    async def add_position(self, position: dict) -> dict:
        """Append a position to the manual holdings file."""
        async with self._lock:
            await self.connect()
            position = dict(position)
            position.setdefault("broker", self.broker)
            self._cache["positions"].append(position)
            await self._persist()
            return position

    async def remove_position(self, symbol: str, account_id: Optional[str] = None) -> int:
        """Remove all positions matching symbol [+ optional account_id].
        Returns count removed."""
        async with self._lock:
            await self.connect()
            sym = symbol.upper()
            before = len(self._cache["positions"])
            self._cache["positions"] = [
                p for p in self._cache["positions"]
                if not (
                    (p.get("symbol") or "").upper() == sym
                    and (account_id is None or p.get("account_id") == account_id)
                )
            ]
            await self._persist()
            return before - len(self._cache["positions"])

    async def set_account(self, account: dict) -> dict:
        """Upsert an account by account_id."""
        async with self._lock:
            await self.connect()
            account = dict(account)
            account.setdefault("broker", self.broker)
            aid = account.get("account_id")
            if not aid:
                raise ValueError("account_id is required")
            self._cache["accounts"] = [
                a for a in self._cache["accounts"]
                if a.get("account_id") != aid
            ]
            self._cache["accounts"].append(account)
            await self._persist()
            return account

    async def _persist(self) -> None:
        MANUAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = MANUAL_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._cache, indent=2, sort_keys=True))
        tmp.replace(MANUAL_FILE)


_INSTANCE: Optional[ManualAdapter] = None
_LOCK = asyncio.Lock()


async def get_manual_adapter() -> ManualAdapter:
    global _INSTANCE
    if _INSTANCE is not None:
        return _INSTANCE
    async with _LOCK:
        if _INSTANCE is None:
            _INSTANCE = ManualAdapter()
            await _INSTANCE.connect()
    return _INSTANCE
