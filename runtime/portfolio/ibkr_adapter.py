#!/usr/bin/env python3
"""
IBKR Portfolio Adapter for NCL Brain
=====================================
Lightweight read-only adapter that connects to Interactive Brokers
via ib_insync and returns portfolio data in a standardized format.

Wraps connection patterns from AAC's ibkr_connector but strips all
trading logic — this is portfolio READ only.

Requirements:
    pip install ib_insync

Connection:
    Requires TWS or IB Gateway running (locally or via Tailscale).
    - TWS Live Trading: port 7496
    - TWS Paper Trading: port 7497
    - IB Gateway Live: port 4001
    - IB Gateway Paper: port 4002

Configuration via env vars (or NCL/.env):
    IBKR_HOST=127.0.0.1
    IBKR_PORT=7496
    IBKR_CLIENT_ID=1
    IBKR_ACCOUNT=DU1234567
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Load .env from NCL root (two levels up from this file) ──────
try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(_env_path)
except ImportError:
    pass  # dotenv not required — env vars can be set directly

logger = logging.getLogger("ncl.portfolio.ibkr")

# ── ib_insync import guard ──────────────────────────────────────
IB: Any = None
Stock: Any = None
Option: Any = None
Forex: Any = None
Contract: Any = None

IB_INSYNC_AVAILABLE = False
try:
    from ib_insync import IB, Contract, Forex, Option, Stock

    IB_INSYNC_AVAILABLE = True
except (ImportError, RuntimeError):
    logger.warning(
        "ib_insync not installed — IBKRAdapter will return empty data. "
        "Install with: pip install ib_insync"
    )


# ── Asset class mapping ────────────────────────────────────────
_SEC_TYPE_MAP: Dict[str, str] = {
    "STK": "equity",
    "OPT": "option",
    "FUT": "future",
    "CASH": "forex",
    "CRYPTO": "crypto",
    "BOND": "bond",
    "FOP": "option",
    "WAR": "equity",
    "IND": "index",
    "CFD": "equity",
}


class IBKRAdapter:
    """
    Read-only IBKR portfolio adapter for NCL Brain.

    Connects to TWS/Gateway via ib_insync socket, exposes accounts,
    positions, and account summary in standardized dict format.

    All blocking ib_insync calls are wrapped with asyncio.to_thread()
    so this adapter plays nicely with the Brain's async event loop.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        client_id: Optional[int] = None,
        account: Optional[str] = None,
    ):
        self.host = host or os.getenv("IBKR_HOST", "127.0.0.1")
        self.port = int(port or os.getenv("IBKR_PORT", "7496"))
        self.client_id = int(client_id or os.getenv("IBKR_CLIENT_ID", "1"))
        self.account = account or os.getenv("IBKR_ACCOUNT", "")

        self._ib: Any = None
        self._connected = False
        self._last_sync: Optional[str] = None

    # ── Connection ──────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        """True if actively connected to TWS/Gateway."""
        if self._ib is None:
            return False
        try:
            return self._ib.isConnected()
        except Exception:
            return False

    async def connect(self) -> bool:
        """
        Connect to TWS or IB Gateway.

        Returns True on success, False if ib_insync is missing.
        Raises ConnectionError on socket/auth failures.
        """
        if not IB_INSYNC_AVAILABLE:
            logger.error("ib_insync not installed — cannot connect to IBKR")
            return False

        start = time.time()
        try:
            self._ib = IB()
            await self._ib.connectAsync(
                host=self.host,
                port=self.port,
                clientId=self.client_id,
                timeout=15,
                readonly=True,  # portfolio read-only — no trading
            )

            if not self._ib.isConnected():
                raise ConnectionError("Failed to establish connection to TWS/Gateway")

            # Resolve account
            accounts = self._ib.managedAccounts()
            if not accounts:
                raise ConnectionError("No managed accounts found")

            if self.account and self.account in accounts:
                pass  # keep specified account
            elif self.account and self.account not in accounts:
                logger.warning(
                    f"Account {self.account} not found. "
                    f"Available: {accounts}. Using {accounts[0]}"
                )
                self.account = accounts[0]
            else:
                self.account = accounts[0]

            self._connected = True
            self._last_sync = datetime.now(timezone.utc).isoformat()
            elapsed_ms = (time.time() - start) * 1000

            logger.info(
                f"Connected to IBKR — account {self.account} "
                f"via {self.host}:{self.port} ({elapsed_ms:.0f}ms)"
            )
            return True

        except ConnectionError:
            raise
        except Exception as e:
            logger.error(f"IBKR connection failed: {e}")
            raise ConnectionError(
                f"Cannot connect to TWS/Gateway at {self.host}:{self.port}: {e}. "
                f"Ensure TWS or IB Gateway is running."
            ) from e

    async def disconnect(self) -> None:
        """Disconnect from TWS/Gateway."""
        if self._ib is not None:
            try:
                if self._ib.isConnected():
                    self._ib.disconnect()
                    logger.info("Disconnected from IBKR")
            except Exception as e:
                logger.warning(f"Error during IBKR disconnect: {e}")
        self._ib = None
        self._connected = False

    def _ensure_connected(self) -> None:
        """Raise if not connected."""
        if not self.connected:
            raise ConnectionError("Not connected to IBKR. Call connect() first.")

    # ── Portfolio Data ──────────────────────────────────────────

    async def get_accounts(self) -> List[Dict[str, Any]]:
        """
        Get account information.

        Returns list of dicts with standardized account fields.
        Returns empty list if ib_insync unavailable or not connected.
        """
        if not IB_INSYNC_AVAILABLE or not self.connected:
            return []

        self._ensure_connected()

        try:
            values = await asyncio.to_thread(
                self._ib.accountValues, self.account
            )

            # Parse account values into a lookup
            av_map: Dict[str, float] = {}
            for av in values:
                if av.currency in ("BASE", "USD"):
                    try:
                        av_map[av.tag] = float(av.value)
                    except (ValueError, TypeError):
                        pass

            net_liq = av_map.get("NetLiquidation", 0.0)
            cash = av_map.get("TotalCashValue", 0.0)
            buying_power = av_map.get("BuyingPower", 0.0)
            unrealized_pl = av_map.get("UnrealizedPnL", 0.0)
            daily_pl = av_map.get("DailyPnL", 0.0)

            self._last_sync = datetime.now(timezone.utc).isoformat()

            return [
                {
                    "broker": "IBKR",
                    "account_id": self.account,
                    "name": self.account,
                    "account_type": "margin",
                    "currency": "USD",
                    "net_liquidation": net_liq,
                    "cash_balance": cash,
                    "buying_power": buying_power,
                    "unrealized_pl": unrealized_pl,
                    "daily_pl": daily_pl,
                    "connected": True,
                    "last_sync": self._last_sync,
                }
            ]

        except Exception as e:
            logger.error(f"Failed to get accounts: {e}")
            return []

    async def get_positions(self) -> List[Dict[str, Any]]:
        """
        Get all current positions with P&L.

        Uses ib_insync portfolio() which provides marketPrice,
        marketValue, unrealizedPNL, and averageCost per position.

        Returns empty list if ib_insync unavailable or not connected.
        """
        if not IB_INSYNC_AVAILABLE or not self.connected:
            return []

        self._ensure_connected()

        try:
            items = await asyncio.to_thread(
                self._ib.portfolio, self.account
            )

            result = []
            for item in items:
                contract = item.contract
                symbol = contract.symbol
                qty = item.position
                avg_cost = item.averageCost or 0.0
                market_price = item.marketPrice or 0.0
                market_value = item.marketValue or 0.0
                unrealized_pl = item.unrealizedPNL or 0.0
                sec_type = contract.secType or "STK"

                # Calculate percentages
                cost_basis = abs(qty * avg_cost) if qty and avg_cost else 0.0
                unrealized_pl_pct = (
                    (unrealized_pl / cost_basis * 100.0) if cost_basis > 0 else 0.0
                )

                asset_class = _SEC_TYPE_MAP.get(sec_type, "equity")

                result.append(
                    {
                        "symbol": symbol,
                        "name": symbol,  # IBKR doesn't provide long name in portfolio()
                        "broker": "IBKR",
                        "account_id": self.account,
                        "quantity": qty,
                        "avg_cost": avg_cost,
                        "current_price": market_price,
                        "market_value": market_value,
                        "unrealized_pl": unrealized_pl,
                        "unrealized_pl_pct": round(unrealized_pl_pct, 2),
                        "daily_pl": 0.0,  # not available per-position from portfolio()
                        "daily_pl_pct": 0.0,
                        "currency": contract.currency or "USD",
                        "sector": "",  # not available from IBKR portfolio()
                        "asset_class": asset_class,
                    }
                )

            return result

        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []

    async def get_account_summary(self) -> Dict[str, Any]:
        """
        Get key account metrics.

        Returns dict with net_liquidation, cash, buying_power,
        margin, daily_pl, unrealized_pl.

        Returns zeroed dict if ib_insync unavailable or not connected.
        """
        empty = {
            "net_liquidation": 0.0,
            "cash": 0.0,
            "buying_power": 0.0,
            "margin": 0.0,
            "daily_pl": 0.0,
            "unrealized_pl": 0.0,
        }

        if not IB_INSYNC_AVAILABLE or not self.connected:
            return empty

        self._ensure_connected()

        try:
            values = await asyncio.to_thread(
                self._ib.accountValues, self.account
            )

            av_map: Dict[str, float] = {}
            for av in values:
                if av.currency in ("BASE", "USD"):
                    try:
                        av_map[av.tag] = float(av.value)
                    except (ValueError, TypeError):
                        pass

            return {
                "net_liquidation": av_map.get("NetLiquidation", 0.0),
                "cash": av_map.get("TotalCashValue", 0.0),
                "buying_power": av_map.get("BuyingPower", 0.0),
                "margin": av_map.get("MaintMarginReq", 0.0),
                "daily_pl": av_map.get("DailyPnL", 0.0),
                "unrealized_pl": av_map.get("UnrealizedPnL", 0.0),
            }

        except Exception as e:
            logger.error(f"Failed to get account summary: {e}")
            return empty
