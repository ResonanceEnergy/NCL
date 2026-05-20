#!/usr/bin/env python3
"""
SnapTrade Adapter — Wealthsimple Account Access for NCL Brain
=============================================================
Read-only adapter that pulls account balances and positions from
Wealthsimple via the SnapTrade API intermediary.

Env vars required:
    SNAPTRADE_CLIENT_ID      — from https://dashboard.snaptrade.com
    SNAPTRADE_CONSUMER_KEY   — from dashboard
    SNAPTRADE_USER_ID        — created via _setup_snaptrade.py --register
    SNAPTRADE_USER_SECRET    — created via _setup_snaptrade.py --register

Requirements:
    pip install snaptrade-python-sdk python-dotenv
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Load .env from NCL root (two levels up from this file)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parents[2] / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass  # dotenv optional — env vars can be set externally

# ---------------------------------------------------------------------------
# Conditional SDK import
# ---------------------------------------------------------------------------
try:
    from snaptrade_client.client import SnapTrade

    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False

logger = logging.getLogger("ncl.portfolio.snaptrade")


class SnapTradeAdapter:
    """
    Async adapter for pulling Wealthsimple data through SnapTrade.

    All SnapTrade SDK calls are blocking — they are wrapped with
    ``asyncio.to_thread()`` so the Brain event loop is never blocked.
    """

    def __init__(
        self,
        client_id: str = "",
        consumer_key: str = "",
        user_id: str = "",
        user_secret: str = "",
    ):
        self.client_id = client_id or os.getenv("SNAPTRADE_CLIENT_ID", "")
        self.consumer_key = consumer_key or os.getenv("SNAPTRADE_CONSUMER_KEY", "")
        self.user_id = user_id or os.getenv("SNAPTRADE_USER_ID", "")
        self.user_secret = user_secret or os.getenv("SNAPTRADE_USER_SECRET", "")

        self._snap: Optional[Any] = None
        self._connected: bool = False
        self._last_sync: Optional[str] = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Initialise the SnapTrade client and verify credentials."""
        if not _SDK_AVAILABLE:
            logger.warning(
                "snaptrade-python-sdk not installed — adapter will return empty data. "
                "Install with: pip install snaptrade-python-sdk"
            )
            return False

        if not self.client_id or not self.consumer_key:
            logger.error("SNAPTRADE_CLIENT_ID / SNAPTRADE_CONSUMER_KEY not set")
            return False

        if not self.user_id or not self.user_secret:
            logger.error("SNAPTRADE_USER_ID / SNAPTRADE_USER_SECRET not set")
            return False

        try:
            self._snap = SnapTrade(
                consumer_key=self.consumer_key,
                client_id=self.client_id,
            )

            # Verify connectivity by fetching account list
            await asyncio.to_thread(
                self._snap.account_information.get_all_user_account_balances,
                user_id=self.user_id,
                user_secret=self.user_secret,
            )

            self._connected = True
            self._last_sync = datetime.now(timezone.utc).isoformat()
            logger.info("SnapTrade adapter connected — credentials verified")
            return True

        except Exception as exc:
            logger.error("SnapTrade connection failed: %s", exc)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Clear client state (SnapTrade is stateless REST)."""
        self._snap = None
        self._connected = False
        self._last_sync = None
        logger.info("SnapTrade adapter disconnected")

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------

    async def get_accounts(self) -> List[Dict]:
        """
        Return normalised account summaries from all linked Wealthsimple accounts.

        Each dict contains:
            broker, account_id, name, account_type, currency,
            net_liquidation, cash_balance, buying_power,
            unrealized_pl, daily_pl, connected, last_sync
        """
        if not self._connected or not self._snap:
            logger.warning("get_accounts called while disconnected — returning []")
            return []

        try:
            raw = await asyncio.to_thread(
                self._snap.account_information.get_all_user_account_balances,
                user_id=self.user_id,
                user_secret=self.user_secret,
            )
            accounts_list: list = raw if isinstance(raw, list) else []
        except Exception as exc:
            logger.error("Failed to fetch SnapTrade accounts: %s", exc)
            return []

        now_iso = datetime.now(timezone.utc).isoformat()
        self._last_sync = now_iso
        results: List[Dict] = []

        for acct in accounts_list:
            acct_id = str(acct.get("id", "unknown"))
            raw_name = str(acct.get("name", acct_id))
            acct_type = self._infer_account_type(raw_name)

            cash_info = acct.get("cash", {})
            cash_balance = float(cash_info.get("amount", 0))
            market_value = float(acct.get("market_value", 0))
            net_liq = cash_balance + market_value

            # SnapTrade doesn't provide P&L at account level — derive later
            # from positions if needed; default to 0 here.
            results.append(
                {
                    "broker": "WEALTHSIMPLE",
                    "account_id": acct_id,
                    "name": self._friendly_name(raw_name),
                    "account_type": acct_type,
                    "currency": "CAD",
                    "net_liquidation": round(net_liq, 2),
                    "cash_balance": round(cash_balance, 2),
                    "buying_power": 0,
                    "unrealized_pl": 0,
                    "daily_pl": 0,
                    "connected": True,
                    "last_sync": now_iso,
                }
            )

        return results

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    async def get_positions(self) -> List[Dict]:
        """
        Return normalised positions across all linked Wealthsimple accounts.

        Each dict contains:
            symbol, name, broker, account_id, quantity, avg_cost,
            current_price, market_value, unrealized_pl, unrealized_pl_pct,
            daily_pl, daily_pl_pct, currency, sector, asset_class
        """
        if not self._connected or not self._snap:
            logger.warning("get_positions called while disconnected — returning []")
            return []

        try:
            raw = await asyncio.to_thread(
                self._snap.account_information.get_user_holdings,
                user_id=self.user_id,
                user_secret=self.user_secret,
            )
        except Exception as exc:
            logger.error("Failed to fetch SnapTrade holdings: %s", exc)
            return []

        self._last_sync = datetime.now(timezone.utc).isoformat()
        results: List[Dict] = []

        # Holdings may be grouped by account
        accounts = raw if isinstance(raw, list) else ([raw] if raw else [])

        for entry in accounts:
            acct_obj = getattr(entry, "account", None) or {}
            acct_id = str(
                acct_obj.get("id", "") if isinstance(acct_obj, dict) else getattr(acct_obj, "id", "")
            ) or "unknown"

            positions = getattr(entry, "positions", None) or []

            for pos in positions:
                symbol_info = getattr(pos, "symbol", None) or {}
                if isinstance(symbol_info, dict):
                    symbol = symbol_info.get("symbol", "?")
                    name = symbol_info.get("description", symbol)
                else:
                    symbol = str(symbol_info)
                    name = symbol

                units = float(getattr(pos, "units", 0))
                avg_cost = float(getattr(pos, "average_purchase_price", 0))
                mkt_val = float(getattr(pos, "market_value", 0))

                # Derive current price from market_value / units
                current_price = round(mkt_val / units, 4) if units else 0
                cost_basis = avg_cost * units
                unrealized_pl = round(mkt_val - cost_basis, 2)
                unrealized_pl_pct = (
                    round((unrealized_pl / cost_basis) * 100, 2) if cost_basis else 0
                )

                results.append(
                    {
                        "symbol": symbol,
                        "name": name,
                        "broker": "WEALTHSIMPLE",
                        "account_id": acct_id,
                        "quantity": units,
                        "avg_cost": round(avg_cost, 4),
                        "current_price": current_price,
                        "market_value": round(mkt_val, 2),
                        "unrealized_pl": unrealized_pl,
                        "unrealized_pl_pct": unrealized_pl_pct,
                        "daily_pl": 0,
                        "daily_pl_pct": 0,
                        "currency": "CAD",
                        "sector": "",
                        "asset_class": "equity",
                    }
                )

        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_account_type(name: str) -> str:
        """Map Wealthsimple account name to a normalised type string."""
        lower = name.lower()
        if "tfsa" in lower:
            return "tfsa"
        if "rrsp" in lower:
            return "rrsp"
        if "margin" in lower:
            return "margin"
        if "resp" in lower:
            return "resp"
        if "lira" in lower:
            return "lira"
        return "cash"

    @staticmethod
    def _friendly_name(name: str) -> str:
        """Return a short display name for the account."""
        lower = name.lower()
        for label in ("TFSA", "RRSP", "RESP", "LIRA", "Margin", "Personal"):
            if label.lower() in lower:
                return label
        return name
