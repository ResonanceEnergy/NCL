#!/usr/bin/env python3
"""
Polymarket Read-Only Adapter for NCL Brain
============================================
Surfaces open prediction-market positions for a Polymarket account.

Two public APIs (no auth required for the read paths used here):

* **Gamma API** ``https://gamma-api.polymarket.com``
  Markets + events metadata (slugs, titles, end-dates, outcomes).
* **Data API** ``https://data-api.polymarket.com/positions?user=<addr>``
  Per-wallet open positions: market_id, outcome, size, avg_price,
  current_price, value, cash_pnl.

Env vars
--------
    POLYMARKET_PRIVATE_KEY     reserved for future signing/trading paths
    POLYMARKET_FUNDER_ADDRESS  the EVM address that holds USDC + positions
    POLYMARKET_CHAIN_ID        defaults to 137 (Polygon mainnet)

We only need ``POLYMARKET_FUNDER_ADDRESS`` for read flows. ``connect()``
verifies the address by hitting the positions endpoint — empty list is OK
(account exists, no open positions); HTTP failure → disconnected.

Position dict::

    {
        "broker": "POLYMARKET",
        "account_id": "<funder>",
        "symbol": "will-trump-win-the-2024-presidential-election",  # market_slug
        "name": "Will Trump win the 2024 presidential election?",
        "quantity": 250,                  # shares
        "avg_cost": 0.52,
        "current_price": 0.71,            # implied probability * $1
        "market_value": 177.5,
        "asset_class": "prediction",
        "currency": "USD",
        "metadata": {
            "end_date": "2024-11-05T23:59:00Z",
            "event_id": "12345",
            "outcome": "Yes",
        }
    }
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


try:
    import httpx

    _HTTPX_AVAILABLE = True
except ImportError:
    httpx = None  # type: ignore
    _HTTPX_AVAILABLE = False

try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parents[2] / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass

logger = logging.getLogger("ncl.portfolio.polymarket")

_DATA_API = "https://data-api.polymarket.com"
_GAMMA_API = "https://gamma-api.polymarket.com"


class PolymarketAdapter:
    """Read-only Polymarket adapter — positions only, no trade execution."""

    def __init__(
        self,
        private_key: str = "",
        funder_address: str = "",
        chain_id: int = 137,
    ):
        # Private key reserved for future trade flow — not used in read paths
        self.private_key = private_key or os.getenv("POLYMARKET_PRIVATE_KEY", "")
        self.funder_address = (funder_address or os.getenv("POLYMARKET_FUNDER_ADDRESS", "")).strip()
        try:
            self.chain_id = int(chain_id or os.getenv("POLYMARKET_CHAIN_ID", "137"))
        except (TypeError, ValueError):
            self.chain_id = 137

        self._connected = False
        self._last_sync: Optional[str] = None
        self._cached_positions: List[Dict[str, Any]] = []
        self._cached_usdc: float = 0.0

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def broker(self) -> str:
        return "POLYMARKET"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Verify the positions endpoint is reachable for our funder address."""
        if not self.funder_address:
            logger.info("Polymarket: POLYMARKET_FUNDER_ADDRESS not set — disconnected")
            return False
        if not _HTTPX_AVAILABLE:
            logger.warning("Polymarket: httpx not installed — disconnected")
            return False

        try:
            positions = await self._fetch_positions_raw()
        except Exception as exc:
            logger.warning("Polymarket connect failed: %s", exc)
            return False

        # Empty list is a valid response (means "no open positions")
        self._connected = True
        self._last_sync = datetime.now(timezone.utc).isoformat()
        # Prime caches
        self._cached_positions = positions or []
        self._cached_usdc = self._derive_usdc(positions or [])
        logger.info(
            "Polymarket adapter connected — funder=%s positions=%d",
            self._truncated(),
            len(self._cached_positions),
        )
        return True

    async def disconnect(self) -> None:
        self._connected = False
        self._last_sync = None
        self._cached_positions = []
        self._cached_usdc = 0.0

    def _truncated(self) -> str:
        if len(self.funder_address) >= 10:
            return f"{self.funder_address[:6]}...{self.funder_address[-4:]}"
        return self.funder_address

    # ------------------------------------------------------------------
    # Data methods
    # ------------------------------------------------------------------

    async def get_accounts(self) -> List[Dict[str, Any]]:
        """Single synthetic account with the USDC cash balance."""
        if not self._connected:
            return []
        return [
            {
                "broker": "POLYMARKET",
                "account_id": self.funder_address,
                "name": f"Polymarket {self._truncated()}",
                "account_type": "prediction",
                "currency": "USD",
                "net_liquidation": round(self._cached_usdc, 2),
                "cash_balance": round(self._cached_usdc, 2),
                "buying_power": round(self._cached_usdc, 2),
                "unrealized_pl": 0.0,
                "daily_pl": 0.0,
                "connected": True,
                "last_sync": self._last_sync,
            }
        ]

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Open positions, freshened each call."""
        if not self._connected:
            return []
        try:
            raw = await self._fetch_positions_raw()
        except Exception as exc:
            logger.warning("Polymarket get_positions failed: %s", exc)
            return self._cached_positions  # fall back to last good snapshot

        self._cached_positions = raw or []
        self._cached_usdc = self._derive_usdc(raw or [])

        out: List[Dict[str, Any]] = []
        for p in raw or []:
            try:
                qty = float(p.get("size", 0) or 0)
            except (TypeError, ValueError):
                qty = 0.0
            if qty == 0:
                continue

            try:
                avg_cost = float(p.get("avgPrice", 0) or 0)
                current = float(p.get("curPrice", p.get("currentPrice", 0)) or 0)
                value = float(p.get("currentValue", p.get("value", qty * current)) or 0)
                upl = float(p.get("cashPnl", 0) or 0)
                upl_pct = float(p.get("percentPnl", 0) or 0)
            except (TypeError, ValueError):
                avg_cost = current = value = upl = upl_pct = 0.0

            slug = p.get("slug") or p.get("conditionId") or p.get("market", "unknown")
            title = p.get("title") or p.get("question") or slug
            outcome = p.get("outcome") or p.get("outcomeName") or ""
            end_date = p.get("endDate") or p.get("end_date_iso") or ""
            event_id = p.get("eventSlug") or p.get("eventId") or ""

            out.append(
                {
                    "broker": "POLYMARKET",
                    "account_id": self.funder_address,
                    "symbol": str(slug),
                    "name": str(title),
                    "quantity": qty,
                    "avg_cost": avg_cost,
                    "current_price": current,
                    "market_value": round(value, 2),
                    "asset_class": "prediction",
                    "currency": "USD",
                    "sector": "Prediction",
                    "unrealized_pl": round(upl, 2),
                    "unrealized_pl_pct": round(upl_pct, 2),
                    "daily_pl": 0.0,
                    "daily_pl_pct": 0.0,
                    "metadata": {
                        "end_date": end_date,
                        "event_id": event_id,
                        "outcome": outcome,
                        "condition_id": p.get("conditionId", ""),
                    },
                }
            )

        return out

    async def get_balances(self) -> Dict[str, float]:
        if not self._connected:
            return {}
        return {"USDC": round(self._cached_usdc, 2)}

    async def list_open_markets(self) -> List[Dict[str, Any]]:
        """Convenience helper for the iOS PLYMKT view (open markets browse)."""
        if not _HTTPX_AVAILABLE:
            return []
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{_GAMMA_API}/markets",
                    params={"active": "true", "closed": "false", "limit": 20},
                )
            if resp.status_code != 200:
                return []
            return resp.json() or []
        except Exception as exc:
            logger.debug("Polymarket markets fetch failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Internal HTTP
    # ------------------------------------------------------------------

    async def _fetch_positions_raw(self) -> List[Dict[str, Any]]:
        if not _HTTPX_AVAILABLE:
            return []
        url = f"{_DATA_API}/positions"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params={"user": self.funder_address})
        if resp.status_code != 200:
            logger.debug("Polymarket positions: HTTP %s — %s", resp.status_code, resp.text[:200])
            return []
        body = resp.json()
        # API returns a JSON array of position dicts directly
        if isinstance(body, list):
            return body
        # Some deployments wrap in {"positions": [...]}
        if isinstance(body, dict) and "positions" in body:
            return body["positions"] or []
        return []

    @staticmethod
    def _derive_usdc(positions: List[Dict[str, Any]]) -> float:
        """Best-effort USDC cash balance — Data API doesn't always expose it.

        Falls back to 0.0 if no `cash` / `usdcBalance` field is present on
        any position row.
        """
        for p in positions:
            for key in ("usdcBalance", "cash", "freeCollateral"):
                if key in p:
                    try:
                        return float(p[key] or 0)
                    except (TypeError, ValueError):
                        pass
        return 0.0
