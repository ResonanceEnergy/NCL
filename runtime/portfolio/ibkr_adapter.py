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


class CircuitOpenError(ConnectionError):
    """Raised when the IBKR connect circuit breaker is open (skip-fast path)."""

    pass


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
# Lazy import: ib_insync (via eventkit) caches the event loop at import time.
# Importing at module level before uvicorn starts causes "Future attached to a
# different loop" errors.  Instead we import inside connect() when uvicorn's
# loop is already running.  _try_import() is the deferred check.


def _try_import_ib_insync():
    """Import ib_insync at call time (inside a running event loop).

    Python 3.14 removed the implicit event loop from get_event_loop().
    eventkit (used by ib_insync) calls get_event_loop() at import time.
    We must register the running loop with the policy before importing.
    """
    global IB, Stock, Option, Forex, Contract, IB_INSYNC_AVAILABLE
    if IB_INSYNC_AVAILABLE:
        return True
    try:
        # Make the current running loop visible to get_event_loop()
        try:
            loop = asyncio.get_running_loop()
            asyncio.get_event_loop_policy().set_event_loop(loop)
        except RuntimeError:
            # No running loop — create a temporary one
            asyncio.set_event_loop(asyncio.new_event_loop())

        from ib_insync import IB as _IB
        from ib_insync import Contract as _Contract
        from ib_insync import Forex as _Forex
        from ib_insync import Option as _Option
        from ib_insync import Stock as _Stock

        IB, Stock, Option, Forex, Contract = _IB, _Stock, _Option, _Forex, _Contract
        IB_INSYNC_AVAILABLE = True
        return True
    except ImportError:
        logger.warning(
            "ib_insync not installed — IBKRAdapter will return empty data. "
            "Install with: pip install ib_insync"
        )
        return False


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

    Class-level circuit breaker prevents the boot-time retry storm that
    was holding port 8800 bind for ~10 minutes when TWS/Gateway is offline.
    After 3 consecutive connect failures the breaker opens for 1 hour and
    subsequent connect() calls raise CircuitOpenError immediately.
    """

    # ── Class-level circuit breaker state ──────────────────────────
    # Shared across all IBKRAdapter instances so multiple managers can't
    # each hammer a dead TWS independently.
    _consecutive_failures: int = 0
    _circuit_open_until: Optional[float] = None  # monotonic timestamp
    _CIRCUIT_FAIL_THRESHOLD: int = 3
    _CIRCUIT_OPEN_SECONDS: float = 3600.0  # 1 hour skip
    _CONNECT_TIMEOUT: float = 10.0  # per-attempt wait_for timeout

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

    # ── Circuit breaker helpers ─────────────────────────────────────

    @classmethod
    def _circuit_is_open(cls) -> bool:
        """True if the breaker is currently in the open (skip) state."""
        if cls._circuit_open_until is None:
            return False
        now = time.monotonic()
        if now >= cls._circuit_open_until:
            # Window elapsed — close the breaker and let one probe through
            cls._circuit_open_until = None
            cls._consecutive_failures = 0
            return False
        return True

    @classmethod
    def _record_success(cls) -> None:
        cls._consecutive_failures = 0
        cls._circuit_open_until = None

    @classmethod
    def _record_failure(cls) -> None:
        cls._consecutive_failures += 1
        if cls._consecutive_failures >= cls._CIRCUIT_FAIL_THRESHOLD:
            cls._circuit_open_until = time.monotonic() + cls._CIRCUIT_OPEN_SECONDS
            logger.warning(
                "IBKR circuit breaker OPEN — %d consecutive failures, "
                "skipping IBKR connect attempts for %.0fs",
                cls._consecutive_failures,
                cls._CIRCUIT_OPEN_SECONDS,
            )

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
        Raises CircuitOpenError immediately if the circuit breaker is open.
        Raises ConnectionError on socket/auth failures.

        Behavior:
        - Per-attempt timeout of ``_CONNECT_TIMEOUT`` (10s) via asyncio.wait_for.
        - Up to 3 attempts with exponential backoff (1s, 2s, 4s).
        - After ``_CIRCUIT_FAIL_THRESHOLD`` (3) consecutive failures across
          calls, the class-level circuit breaker opens for 1 hour.
        """
        # Fast-fail if the circuit is open
        if self._circuit_is_open():
            ts = self._circuit_open_until or 0.0
            raise CircuitOpenError(
                f"ibkr circuit open (skip-fast); will retry after monotonic={ts:.0f}"
            )

        if not _try_import_ib_insync():
            logger.error("ib_insync not installed — cannot connect to IBKR")
            return False

        start = time.time()
        last_exc: Optional[BaseException] = None
        backoffs = (1.0, 2.0, 4.0)  # 3 attempts max

        for attempt_idx, backoff in enumerate(backoffs):
            try:
                self._ib = IB()
                # Wrap the inner connectAsync in our own bounded wait_for so a
                # hung TWS handshake can't stall lifespan past _CONNECT_TIMEOUT.
                await asyncio.wait_for(
                    self._ib.connectAsync(
                        host=self.host,
                        port=self.port,
                        clientId=self.client_id,
                        timeout=self._CONNECT_TIMEOUT,
                        readonly=True,  # portfolio read-only — no trading
                    ),
                    timeout=self._CONNECT_TIMEOUT,
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

                # Healthy connect — reset breaker
                self._record_success()

                logger.info(
                    f"Connected to IBKR — account {self.account} "
                    f"via {self.host}:{self.port} ({elapsed_ms:.0f}ms, "
                    f"attempt {attempt_idx + 1}/{len(backoffs)})"
                )
                return True

            except asyncio.TimeoutError as e:
                last_exc = e
                logger.warning(
                    "IBKR connect attempt %d/%d timed out after %.1fs",
                    attempt_idx + 1,
                    len(backoffs),
                    self._CONNECT_TIMEOUT,
                )
                # Tear down the half-open IB handle before retry
                try:
                    if self._ib is not None and self._ib.isConnected():
                        self._ib.disconnect()
                except Exception as cleanup_err:
                    logger.debug("IBKR half-open disconnect swallowed: %s", cleanup_err)
                self._ib = None
            except Exception as e:
                last_exc = e
                logger.warning(
                    "IBKR connect attempt %d/%d failed: %s",
                    attempt_idx + 1,
                    len(backoffs),
                    e,
                )
                try:
                    if self._ib is not None and self._ib.isConnected():
                        self._ib.disconnect()
                except Exception as cleanup_err:
                    logger.debug("IBKR error-path disconnect swallowed: %s", cleanup_err)
                self._ib = None

            # Backoff before next attempt (skip after the final attempt)
            if attempt_idx + 1 < len(backoffs):
                await asyncio.sleep(backoff)

        # All attempts exhausted — bump breaker
        self._record_failure()
        msg = (
            f"Cannot connect to TWS/Gateway at {self.host}:{self.port} "
            f"after {len(backoffs)} attempts: {last_exc}. "
            f"Ensure TWS or IB Gateway is running."
        )
        logger.error(msg)
        raise ConnectionError(msg) from last_exc

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
            values = await asyncio.to_thread(self._ib.accountValues, self.account)

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
            items = await asyncio.to_thread(self._ib.portfolio, self.account)

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
                unrealized_pl_pct = (unrealized_pl / cost_basis * 100.0) if cost_basis > 0 else 0.0

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
            values = await asyncio.to_thread(self._ib.accountValues, self.account)

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
