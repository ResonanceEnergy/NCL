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

            # Verify connectivity by listing linked accounts
            accounts = await asyncio.to_thread(
                self._snap.account_information.list_user_accounts,
                user_id=self.user_id,
                user_secret=self.user_secret,
            )
            acct_list = accounts.body if hasattr(accounts, "body") else accounts
            acct_count = len(acct_list) if isinstance(acct_list, list) else 0

            self._connected = True
            self._last_sync = datetime.now(timezone.utc).isoformat()
            logger.info(
                "SnapTrade adapter connected — %d account(s) linked", acct_count
            )
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
                self._snap.account_information.list_user_accounts,
                user_id=self.user_id,
                user_secret=self.user_secret,
            )
            accounts_list = raw.body if hasattr(raw, "body") else raw
            if not isinstance(accounts_list, list):
                accounts_list = []
        except Exception as exc:
            logger.error("Failed to fetch SnapTrade accounts: %s", exc)
            return []

        now_iso = datetime.now(timezone.utc).isoformat()
        self._last_sync = now_iso
        results: List[Dict] = []

        for acct in accounts_list:
            # Handle both dict and object-style responses
            _get = acct.get if isinstance(acct, dict) else lambda k, d=None: getattr(acct, k, d)
            acct_id = str(_get("id", "unknown"))
            raw_name = str(_get("name", acct_id))
            acct_type = self._infer_account_type(raw_name)

            # Fetch actual balance from dedicated endpoint
            # (list_user_accounts does NOT include balance data)
            net_liq = 0.0
            cash_balance = 0.0
            try:
                bal_response = await asyncio.to_thread(
                    self._snap.account_information.get_user_account_balance,
                    user_id=self.user_id,
                    user_secret=self.user_secret,
                    account_id=acct_id,
                )
                bal_list = bal_response.body if hasattr(bal_response, "body") else bal_response
                if not isinstance(bal_list, list):
                    bal_list = [bal_list] if bal_list else []
                for bal_item in bal_list:
                    b = bal_item if isinstance(bal_item, dict) else (bal_item.__dict__ if hasattr(bal_item, "__dict__") else {})
                    cur = b.get("currency", {})
                    if isinstance(cur, dict):
                        cur_code = cur.get("code", "CAD")
                    else:
                        cur_code = str(getattr(cur, "code", "CAD"))
                    amt = float(b.get("cash", 0) or 0)
                    cash_balance += amt
                    net_liq += amt
            except Exception as exc:
                logger.warning("SnapTrade balance fetch failed for %s: %s", acct_id, exc)

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

        Fetches positions per-account since the SnapTrade SDK requires accountId.
        """
        if not self._connected or not self._snap:
            logger.warning("get_positions called while disconnected — returning []")
            return []

        # First get the list of accounts
        try:
            accts_raw = await asyncio.to_thread(
                self._snap.account_information.list_user_accounts,
                user_id=self.user_id,
                user_secret=self.user_secret,
            )
            accts = accts_raw.body if hasattr(accts_raw, "body") else accts_raw
            if not isinstance(accts, list):
                accts = []
        except Exception as exc:
            logger.error("Failed to list SnapTrade accounts for positions: %s", exc)
            return []

        self._last_sync = datetime.now(timezone.utc).isoformat()
        results: List[Dict] = []

        for acct in accts:
            _get = acct.get if isinstance(acct, dict) else lambda k, d=None: getattr(acct, k, d)
            acct_id = str(_get("id", "unknown"))

            try:
                pos_raw = await asyncio.to_thread(
                    self._snap.account_information.get_user_account_positions,
                    user_id=self.user_id,
                    user_secret=self.user_secret,
                    account_id=acct_id,
                )
                positions = pos_raw.body if hasattr(pos_raw, "body") else pos_raw
                if not isinstance(positions, list):
                    positions = []
            except Exception as exc:
                logger.warning("Failed to fetch positions for account %s: %s", acct_id, exc)
                continue

            for pos in positions:
                if isinstance(pos, dict):
                    symbol_info = pos.get("symbol", {})
                    units = float(pos.get("units", 0) or 0)
                    avg_cost = float(pos.get("average_purchase_price", 0) or 0)
                    current_price_raw = float(pos.get("price", 0) or 0)
                    mkt_val = float(pos.get("market_value", 0) or 0)
                    if mkt_val == 0 and current_price_raw > 0 and units > 0:
                        mkt_val = current_price_raw * units
                else:
                    symbol_info = getattr(pos, "symbol", None) or {}
                    units = float(getattr(pos, "units", 0) or 0)
                    avg_cost = float(getattr(pos, "average_purchase_price", 0) or 0)
                    current_price_raw = float(getattr(pos, "price", 0) or 0)
                    mkt_val = float(getattr(pos, "market_value", 0) or 0)
                    if mkt_val == 0 and current_price_raw > 0 and units > 0:
                        mkt_val = current_price_raw * units

                if isinstance(symbol_info, dict):
                    symbol = symbol_info.get("symbol", "?")
                    name = symbol_info.get("description", symbol)
                else:
                    symbol = str(getattr(symbol_info, "symbol", symbol_info))
                    name = str(getattr(symbol_info, "description", symbol))

                # Safety: SnapTrade SDK may return nested objects instead of strings
                if not isinstance(symbol, str):
                    symbol = str(getattr(symbol, "symbol", None) or getattr(symbol, "raw_symbol", None) or symbol)
                if len(symbol) > 20:
                    # Still got an object repr — try to extract ticker
                    import re
                    m = re.search(r"'symbol':\s*'([^']+)'", symbol)
                    symbol = m.group(1) if m else symbol[:10]

                # Derive current price — prefer raw price field, fall back to mkt_val / units
                current_price = current_price_raw if current_price_raw > 0 else (round(mkt_val / units, 4) if units else 0)
                cost_basis = avg_cost * units
                unrealized_pl = round(mkt_val - cost_basis, 2)
                unrealized_pl_pct = (
                    round((unrealized_pl / cost_basis) * 100, 2) if cost_basis else 0
                )

                # Currency may be a nested object, not a plain string
                pos_currency = pos.get("currency", "CAD") if isinstance(pos, dict) else getattr(pos, "currency", "CAD")
                if isinstance(pos_currency, dict):
                    pos_currency = pos_currency.get("code", "CAD")
                elif not isinstance(pos_currency, str):
                    pos_currency = str(getattr(pos_currency, "code", "CAD"))

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
                        "currency": pos_currency,
                        "sector": "",
                        "asset_class": "equity",
                    }
                )

            # ----- Option holdings (separate SnapTrade endpoint) -----
            try:
                opt_raw = await asyncio.to_thread(
                    self._snap.options.list_option_holdings,
                    user_id=self.user_id,
                    user_secret=self.user_secret,
                    account_id=acct_id,
                )
                option_holdings = opt_raw.body if hasattr(opt_raw, "body") else opt_raw
                if not isinstance(option_holdings, list):
                    option_holdings = []
            except Exception as exc:
                logger.debug("No option holdings for account %s: %s", acct_id, exc)
                option_holdings = []

            for opt in option_holdings:
                try:
                    results.append(self._normalise_option(opt, acct_id))
                except Exception as exc:
                    logger.warning("Failed to normalise option holding: %s", exc)

        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_option(opt: Any, acct_id: str) -> Dict:
        """Normalise a SnapTrade option holding into the standard position dict.

        SnapTrade option response shape (per holding):
            symbol.option_symbol.underlying_symbol.symbol  -> e.g. "GLD"
            symbol.option_symbol.strike_price              -> e.g. 515.0
            symbol.option_symbol.expiration_date            -> e.g. "2027-03-19"
            symbol.option_symbol.option_type                -> "CALL" / "PUT"
            symbol.option_symbol.underlying_symbol.currency.code -> "USD"
            price                                           -> per-share price
            units                                           -> number of contracts
            average_purchase_price                          -> total cost basis
        """
        d = opt if isinstance(opt, dict) else (
            opt.to_dict() if hasattr(opt, "to_dict") else
            {k: v for k, v in opt.__dict__.items() if not k.startswith("_")}
            if hasattr(opt, "__dict__") else {}
        )

        sym_info = d.get("symbol", {}) or {}
        opt_sym = sym_info.get("option_symbol", {}) or {}
        underlying = opt_sym.get("underlying_symbol", {}) or {}

        ticker = underlying.get("symbol", "") or underlying.get("raw_symbol", "?")
        strike = float(opt_sym.get("strike_price", 0) or 0)
        expiry = str(opt_sym.get("expiration_date", "") or "")
        opt_type = str(opt_sym.get("option_type", "") or "").upper()
        description = str(underlying.get("description", ticker) or ticker)

        # Currency from underlying symbol
        cur_obj = underlying.get("currency", {}) or {}
        currency = cur_obj.get("code", "USD") if isinstance(cur_obj, dict) else str(getattr(cur_obj, "code", "USD"))

        # Build display symbol: "GLD $515C 03/19/27"
        type_letter = "C" if "CALL" in opt_type else "P" if "PUT" in opt_type else "?"
        exp_short = ""
        if expiry and len(expiry) >= 10:
            # "2027-03-19" -> "03/19/27"
            parts = expiry.split("-")
            if len(parts) == 3:
                exp_short = f"{parts[1]}/{parts[2]}/{parts[0][2:]}"
        display_symbol = f"{ticker} ${int(strike)}{type_letter} {exp_short}".strip()

        # Display name: "GLD $515 Call 03/19/27"
        type_word = "Call" if "CALL" in opt_type else "Put" if "PUT" in opt_type else opt_type
        display_name = f"{description} ${int(strike)} {type_word} {exp_short}".strip()

        units = float(d.get("units", 0) or 0)
        price_per_share = float(d.get("price", 0) or 0)
        total_cost = float(d.get("average_purchase_price", 0) or 0)

        # Options: price is per share, each contract = 100 shares
        multiplier = 1 if opt_sym.get("is_mini_option", False) else 100
        mkt_val = round(price_per_share * multiplier * units, 2)

        # avg_cost per contract = total_cost / units
        avg_cost_per_contract = round(total_cost / units, 2) if units else 0
        cost_basis = total_cost
        unrealized_pl = round(mkt_val - cost_basis, 2)
        unrealized_pl_pct = round((unrealized_pl / cost_basis) * 100, 2) if cost_basis else 0

        return {
            "symbol": display_symbol,
            "name": display_name,
            "broker": "WEALTHSIMPLE",
            "account_id": acct_id,
            "quantity": units,
            "avg_cost": avg_cost_per_contract,
            "current_price": round(price_per_share * multiplier, 2),
            "market_value": mkt_val,
            "unrealized_pl": unrealized_pl,
            "unrealized_pl_pct": unrealized_pl_pct,
            "daily_pl": 0,
            "daily_pl_pct": 0,
            "currency": currency,
            "sector": "",
            "asset_class": "option",
        }

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
