#!/usr/bin/env python3
"""
Moomoo Portfolio Adapter — read-only portfolio data from Moomoo/Futu via OpenD.
Requires: pip install moomoo-api  |  OpenD gateway running locally.

Env config: MOOMOO_HOST, MOOMOO_PORT, MOOMOO_TRADE_ENV, MOOMOO_MARKET, MOOMOO_SECURITY_FIRM
"""

import asyncio
import logging
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Load .env from NCL runtime root (two levels up)
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
if _ENV_PATH.exists():
    with open(_ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                _key, _val = _key.strip(), _val.strip().strip("\"'")
                if _key and _key not in os.environ:
                    os.environ[_key] = _val

try:
    from moomoo import (
        RET_OK, OpenQuoteContext, OpenSecTradeContext,
        SecurityFirm, TrdEnv, TrdMarket,
    )
    MOOMOO_AVAILABLE = True
except ImportError:
    MOOMOO_AVAILABLE = False

logger = logging.getLogger("ncl.portfolio.moomoo")

TRD_MARKET_MAP: Dict[str, Any] = {}
if MOOMOO_AVAILABLE:
    TRD_MARKET_MAP = {
        "US": TrdMarket.US, "HK": TrdMarket.HK, "CN": TrdMarket.CN,
        "SG": TrdMarket.SG, "AU": TrdMarket.AU, "JP": TrdMarket.JP,
        "CA": TrdMarket.CA,
    }

CURRENCY_BY_MARKET = {
    "US": "USD", "HK": "HKD", "SH": "CNY", "SZ": "CNY",
    "SG": "SGD", "AU": "AUD", "JP": "JPY", "CA": "CAD",
}


def _moomoo_to_ticker(code: str) -> str:
    """US.AAPL -> AAPL"""
    parts = code.split(".")
    return parts[1] if len(parts) == 2 else code


class MoomooAdapter:
    """Read-only portfolio adapter for Moomoo/Futu via OpenD gateway."""

    def __init__(self) -> None:
        self._host = os.getenv("MOOMOO_HOST", "127.0.0.1")
        self._port = int(os.getenv("MOOMOO_PORT", "11111"))
        self._trade_env_str = os.getenv("MOOMOO_TRADE_ENV", "REAL").upper()
        self._market = os.getenv("MOOMOO_MARKET", "US").upper()
        self._security_firm_str = os.getenv("MOOMOO_SECURITY_FIRM", "FUTUCA")
        self._currency = CURRENCY_BY_MARKET.get(self._market, "USD")
        self._quote_ctx: Optional[Any] = None
        self._trade_ctx: Optional[Any] = None
        self._connected = False
        self._last_sync: Optional[str] = None

    @property
    def connected(self) -> bool:
        return self._connected

    # -- Connection --------------------------------------------------------

    async def connect(self) -> bool:
        """Connect to OpenD. Returns False if SDK missing or connection fails.
        Times out after 10 seconds to avoid blocking Brain startup."""
        if not MOOMOO_AVAILABLE:
            logger.warning("moomoo-api not installed — adapter disabled. pip install moomoo-api")
            return False
        try:
            quote_ctx, trade_ctx = await asyncio.wait_for(
                asyncio.to_thread(self._connect_sync), timeout=10
            )
            self._quote_ctx = quote_ctx
            self._trade_ctx = trade_ctx
            self._connected = True
            self._last_sync = datetime.now(timezone.utc).isoformat()
            logger.info("Connected to Moomoo OpenD %s:%d market=%s env=%s",
                        self._host, self._port, self._market, self._trade_env_str)
            return True
        except asyncio.TimeoutError:
            logger.warning("Moomoo connection timed out (OpenD not running on %s:%d)",
                           self._host, self._port)
            self._connected = False
            return False
        except Exception as exc:
            logger.error("Moomoo connection failed: %s", exc)
            self._connected = False
            return False

    def _connect_sync(self):
        # Pre-check: verify OpenD is actually listening before letting the SDK
        # block for minutes with its own retry loop.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        try:
            sock.connect((self._host, self._port))
        except (ConnectionRefusedError, OSError, socket.timeout):
            raise ConnectionError(
                f"OpenD not reachable at {self._host}:{self._port}"
            )
        finally:
            sock.close()

        security_firm = getattr(SecurityFirm, self._security_firm_str, SecurityFirm.FUTUINC)
        trd_market = TRD_MARKET_MAP.get(self._market, TrdMarket.US)
        quote_ctx = OpenQuoteContext(host=self._host, port=self._port)
        trade_ctx = OpenSecTradeContext(
            host=self._host, port=self._port,
            security_firm=security_firm, filter_trdmarket=trd_market,
        )
        return quote_ctx, trade_ctx

    async def disconnect(self) -> None:
        """Close OpenD connections."""
        for ctx in (self._quote_ctx, self._trade_ctx):
            if ctx:
                try:
                    ctx.close()
                except Exception:
                    pass
        self._quote_ctx = self._trade_ctx = None
        self._connected = False
        logger.info("Moomoo adapter disconnected")

    # -- Account -----------------------------------------------------------

    async def get_accounts(self) -> List[Dict[str, Any]]:
        """Fetch account summary. Returns [] if disconnected or SDK missing."""
        if not MOOMOO_AVAILABLE or not self._connected or not self._trade_ctx:
            return []
        try:
            data = await asyncio.to_thread(self._fetch_account_sync)
        except Exception as exc:
            logger.error("Failed to fetch Moomoo account: %s", exc)
            return []
        if data is None or data.empty:
            return []

        row = data.iloc[0]
        self._last_sync = datetime.now(timezone.utc).isoformat()
        net_liq = float(row.get("total_assets", 0) or 0)
        cash = float(row.get("cash", 0) or 0)
        unrealized = float(row.get("unrealized_pl", 0) or 0)
        realized = float(row.get("realized_pl", 0) or 0)
        buying_power = float(row.get("power", 0) or row.get("max_power_short", 0) or 0)

        return [{
            "broker": "MOOMOO",
            "account_id": str(row.get("acc_id", "moomoo-default")),
            "name": f"Moomoo {self._market}",
            "account_type": self._trade_env_str.lower(),
            "currency": self._currency,
            "net_liquidation": net_liq,
            "cash_balance": cash,
            "buying_power": buying_power,
            "unrealized_pl": unrealized,
            "daily_pl": realized if realized else 0.0,
            "connected": True,
            "last_sync": self._last_sync,
        }]

    def _fetch_account_sync(self):
        trd_env = TrdEnv.SIMULATE if self._trade_env_str == "SIMULATE" else TrdEnv.REAL
        ret, data = self._trade_ctx.accinfo_query(trd_env=trd_env)
        if ret != RET_OK:
            raise RuntimeError(f"accinfo_query failed: {data}")
        return data

    # -- Positions ---------------------------------------------------------

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch current positions. Returns [] if disconnected or SDK missing."""
        if not MOOMOO_AVAILABLE or not self._connected or not self._trade_ctx:
            return []
        try:
            data = await asyncio.to_thread(self._fetch_positions_sync)
        except Exception as exc:
            logger.error("Failed to fetch Moomoo positions: %s", exc)
            return []
        if data is None or data.empty:
            return []

        self._last_sync = datetime.now(timezone.utc).isoformat()
        account_id = await self._resolve_account_id()
        positions: List[Dict[str, Any]] = []

        for _, row in data.iterrows():
            qty = float(row.get("qty", 0) or 0)
            if qty == 0:
                continue
            symbol = _moomoo_to_ticker(str(row.get("code", "")))
            cost = float(row.get("cost_price", 0) or 0)
            pl_ratio = float(row.get("pl_ratio", 0) or 0)
            unrealized_pct = pl_ratio * 100 if abs(pl_ratio) < 1 else pl_ratio
            today_pl = float(row.get("today_pl_val", 0) or 0)
            today_pl_pct = (today_pl / (cost * qty)) * 100 if cost and qty and today_pl else 0.0

            positions.append({
                "symbol": symbol,
                "name": str(row.get("stock_name", symbol)),
                "broker": "MOOMOO",
                "account_id": account_id,
                "quantity": qty,
                "avg_cost": cost,
                "current_price": float(row.get("nominal_price", 0) or 0),
                "market_value": float(row.get("market_val", 0) or 0),
                "unrealized_pl": float(row.get("pl_val", 0) or 0),
                "unrealized_pl_pct": unrealized_pct,
                "daily_pl": today_pl,
                "daily_pl_pct": today_pl_pct,
                "currency": self._currency,
                "sector": "",
                "asset_class": "equity",
            })
        return positions

    def _fetch_positions_sync(self):
        trd_env = TrdEnv.SIMULATE if self._trade_env_str == "SIMULATE" else TrdEnv.REAL
        ret, data = self._trade_ctx.position_list_query(trd_env=trd_env)
        if ret != RET_OK:
            raise RuntimeError(f"position_list_query failed: {data}")
        return data

    async def _resolve_account_id(self) -> str:
        try:
            data = await asyncio.to_thread(self._fetch_account_sync)
            if data is not None and not data.empty:
                return str(data.iloc[0].get("acc_id", "moomoo-default"))
        except Exception:
            pass
        return "moomoo-default"
