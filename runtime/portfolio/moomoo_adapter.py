#!/usr/bin/env python3
"""
Moomoo Portfolio Adapter — read-only portfolio data from Moomoo/Futu via OpenD.
Requires: pip install moomoo-api  |  OpenD gateway running locally.

Env config: MOOMOO_HOST, MOOMOO_PORT, MOOMOO_TRADE_ENV, MOOMOO_MARKET, MOOMOO_SECURITY_FIRM
"""

import asyncio
import logging
import os
import re
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
        RET_OK,
        Currency,
        OpenQuoteContext,
        OpenSecTradeContext,
        SecurityFirm,
        TrdEnv,
        TrdMarket,
    )

    MOOMOO_AVAILABLE = True
except ImportError:
    MOOMOO_AVAILABLE = False

logger = logging.getLogger("ncl.portfolio.moomoo")

TRD_MARKET_MAP: Dict[str, Any] = {}
if MOOMOO_AVAILABLE:
    TRD_MARKET_MAP = {
        "US": TrdMarket.US,
        "HK": TrdMarket.HK,
        "CN": TrdMarket.CN,
        "SG": TrdMarket.SG,
        "AU": TrdMarket.AU,
        "JP": TrdMarket.JP,
        "CA": TrdMarket.CA,
    }

CURRENCY_BY_MARKET = {
    "US": "USD",
    "HK": "HKD",
    "SH": "CNY",
    "SZ": "CNY",
    "CN": "CNH",
    "SG": "SGD",
    "AU": "AUD",
    "JP": "JPY",
    "CA": "CAD",
    "MY": "MYR",
}


def _safe_num(val) -> float:
    """Coerce any Moomoo numeric field to float, treating 'N/A' / 'None' / ''
    / null as 0.0. The SDK returns the literal string 'N/A' for fields not
    applicable to an account/position type — float('N/A') would otherwise
    blow up the entire adapter on the first such row."""
    if val is None:
        return 0.0
    try:
        s = str(val).strip()
        if not s or s.upper() in ("N/A", "NA", "NONE", "-", "--"):
            return 0.0
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def _native_currency_for_markets(market_auth: List[str]) -> str:
    """Infer native currency from a Moomoo account's authorized markets.

    Moomoo accounts have a native currency tied to the market(s) they trade.
    A US account is USD, HK is HKD, CN is CNH, etc. `accinfo_query` only
    accepts a currency the account is entitled to — picking the wrong one
    triggers "This account does not support converting to this currency".
    """
    if not market_auth:
        return "USD"
    # First authorized market wins (Moomoo lists primary first)
    primary = str(market_auth[0]).upper().split(".")[-1]  # e.g. "TrdMarket.US" -> "US"
    return CURRENCY_BY_MARKET.get(primary, "USD")


def _currency_enum(code: str) -> Any:
    """Map ISO currency string to moomoo Currency enum (defaults to USD)."""
    if not MOOMOO_AVAILABLE:
        return None
    mapping = {
        "USD": Currency.USD,
        "HKD": Currency.HKD,
        "CNH": Currency.CNH,
        "CNY": Currency.CNH,
        "JPY": Currency.JPY,
        "SGD": Currency.SGD,
        "AUD": Currency.AUD,
        "CAD": Currency.CAD,
        "MYR": Currency.MYR,
    }
    return mapping.get(code.upper(), Currency.USD)


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
            logger.info(
                "Connected to Moomoo OpenD %s:%d market=%s env=%s",
                self._host,
                self._port,
                self._market,
                self._trade_env_str,
            )
            return True
        except asyncio.TimeoutError:
            logger.warning(
                "Moomoo connection timed out (OpenD not running on %s:%d)", self._host, self._port
            )
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
            raise ConnectionError(f"OpenD not reachable at {self._host}:{self._port}")
        finally:
            sock.close()

        security_firm = getattr(SecurityFirm, self._security_firm_str, SecurityFirm.FUTUINC)
        trd_market = TRD_MARKET_MAP.get(self._market, TrdMarket.US)
        quote_ctx = OpenQuoteContext(host=self._host, port=self._port)
        trade_ctx = OpenSecTradeContext(
            host=self._host,
            port=self._port,
            security_firm=security_firm,
            filter_trdmarket=trd_market,
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
        """Fetch summary for every connected Moomoo account.

        Iterates over the account list returned by `get_acc_list()` and queries
        each one in ITS native currency (USD for US accounts, HKD for HK, etc.).
        The default `accinfo_query` currency is HKD — passing the wrong currency
        raises "This account does not support converting to this currency".
        """
        if not MOOMOO_AVAILABLE or not self._connected or not self._trade_ctx:
            return []
        try:
            account_rows = await asyncio.to_thread(self._fetch_all_accounts_sync)
        except Exception as exc:
            logger.error("Failed to fetch Moomoo accounts: %s", exc)
            return []
        if not account_rows:
            return []

        self._last_sync = datetime.now(timezone.utc).isoformat()
        accounts: List[Dict[str, Any]] = []
        for entry in account_rows:
            row = entry["info"]
            acc_id = entry["acc_id"]
            native_currency = entry["currency"]
            trd_env = entry["trd_env"]
            acc_type = entry["acc_type"]

            net_liq = _safe_num(row.get("total_assets"))
            cash = _safe_num(row.get("cash"))
            unrealized = _safe_num(row.get("unrealized_pl"))
            buying_power = _safe_num(row.get("power")) or _safe_num(row.get("max_power_short"))

            label_market = entry["primary_market"]
            accounts.append(
                {
                    "broker": "MOOMOO",
                    "account_id": str(acc_id),
                    "name": f"Moomoo {label_market} ({acc_type})"
                    if acc_type
                    else f"Moomoo {label_market}",
                    "account_type": (trd_env or self._trade_env_str).lower(),
                    "currency": native_currency,
                    "net_liquidation": net_liq,
                    "cash_balance": cash,
                    "buying_power": buying_power,
                    "unrealized_pl": unrealized,
                    # No true daily P&L field from Moomoo accinfo; realized_pl is cumulative, not daily  # noqa: E501
                    "daily_pl": 0.0,
                    "connected": True,
                    "last_sync": self._last_sync,
                }
            )
        return accounts

    def _list_accounts_sync(self) -> List[Dict[str, Any]]:
        """Pull the raw account list, return list of dicts keyed by acc_id."""
        ret, data = self._trade_ctx.get_acc_list()
        if ret != RET_OK or data is None or data.empty:
            raise RuntimeError(f"get_acc_list failed: {data}")
        accounts: List[Dict[str, Any]] = []
        target_env = TrdEnv.SIMULATE if self._trade_env_str == "SIMULATE" else TrdEnv.REAL
        for _, row in data.iterrows():
            acc_env = str(row.get("trd_env", ""))
            if acc_env and acc_env != target_env:
                continue
            market_auth = list(row.get("trdmarket_auth", []) or [])
            native_currency = _native_currency_for_markets(market_auth)
            primary_market = (
                str(market_auth[0]).upper().split(".")[-1] if market_auth else self._market
            )
            accounts.append(
                {
                    "acc_id": int(row["acc_id"]),
                    "trd_env": acc_env or target_env,
                    "acc_type": str(row.get("acc_type", "")),
                    "market_auth": market_auth,
                    "primary_market": primary_market,
                    "currency": native_currency,
                }
            )
        return accounts

    def _fetch_all_accounts_sync(self) -> List[Dict[str, Any]]:
        """For each account, run accinfo_query in its native currency.
        Returns list of {acc_id, currency, primary_market, trd_env, info(row)}."""
        results: List[Dict[str, Any]] = []
        try:
            account_list = self._list_accounts_sync()
        except Exception as exc:
            logger.error("Could not list Moomoo accounts: %s", exc)
            return results

        target_env = TrdEnv.SIMULATE if self._trade_env_str == "SIMULATE" else TrdEnv.REAL
        for acc in account_list:
            acc_id = acc["acc_id"]
            currency_str = acc["currency"]
            currency_enum = _currency_enum(currency_str)
            try:
                ret, data = self._trade_ctx.accinfo_query(
                    trd_env=target_env,
                    acc_id=acc_id,
                    currency=currency_enum,
                )
                if ret != RET_OK:
                    # Some accounts only accept HKD even when the primary market
                    # implies otherwise; fall back to HKD then USD before giving up.
                    fallback_chain = ["HKD", "USD"]
                    if currency_str in fallback_chain:
                        fallback_chain.remove(currency_str)
                    recovered = False
                    for fallback in fallback_chain:
                        f_ret, f_data = self._trade_ctx.accinfo_query(
                            trd_env=target_env,
                            acc_id=acc_id,
                            currency=_currency_enum(fallback),
                        )
                        if f_ret == RET_OK and f_data is not None and not f_data.empty:
                            data = f_data
                            currency_str = fallback
                            recovered = True
                            logger.info(
                                "Moomoo acc %s queried in %s (native %s rejected)",
                                acc_id,
                                fallback,
                                acc["currency"],
                            )
                            break
                    if not recovered:
                        logger.warning(
                            "Moomoo acc %s skipped: accinfo_query failed for currency %s: %s",
                            acc_id,
                            currency_str,
                            data,
                        )
                        continue
                if data is None or data.empty:
                    continue
                # SDK populates `currency` column with whatever it returned in
                results.append(
                    {
                        "acc_id": acc_id,
                        "trd_env": acc.get("trd_env"),
                        "acc_type": acc.get("acc_type"),
                        "primary_market": acc.get("primary_market"),
                        "currency": currency_str,
                        "info": data.iloc[0].to_dict(),
                    }
                )
            except Exception as exc:
                logger.warning("Moomoo acc %s accinfo_query raised: %s", acc_id, exc)
                continue
        return results

    # -- Positions ---------------------------------------------------------

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch current positions across every connected Moomoo account.
        Returns [] if disconnected or SDK missing."""
        if not MOOMOO_AVAILABLE or not self._connected or not self._trade_ctx:
            return []
        try:
            grouped = await asyncio.to_thread(self._fetch_positions_sync)
        except Exception as exc:
            logger.error("Failed to fetch Moomoo positions: %s", exc)
            return []
        if not grouped:
            return []

        self._last_sync = datetime.now(timezone.utc).isoformat()
        positions: List[Dict[str, Any]] = []

        for group in grouped:
            data = group["data"]
            acc_id = group["acc_id"]
            currency = group["currency"]
            if data is None or data.empty:
                continue
            for _, row in data.iterrows():
                qty = _safe_num(row.get("qty"))
                if qty == 0:
                    continue
                symbol = _moomoo_to_ticker(str(row.get("code", "")))

                # -- current price: prefer price field, then nominal_price, then derive from market_val  # noqa: E501
                current_price = _safe_num(row.get("price"))
                if current_price == 0:
                    current_price = _safe_num(row.get("nominal_price"))
                market_value = _safe_num(row.get("market_val"))
                if current_price == 0 and qty != 0 and market_value != 0:
                    current_price = market_value / qty

                # -- avg cost: prefer cost_price, then average_cost, then diluted_cost
                cost = _safe_num(row.get("cost_price"))
                if cost == 0:
                    cost = _safe_num(row.get("average_cost"))
                if cost == 0:
                    cost = _safe_num(row.get("diluted_cost"))

                # -- asset class: detect options via sec_type or symbol pattern
                sec_type = str(row.get("sec_type", "")).upper()
                if sec_type in ("OPT", "OPTION", "DRVT"):
                    asset_class = "option"
                elif re.match(r"^[A-Z]+\d{6}[CP]\d+$", symbol):
                    asset_class = "option"
                else:
                    asset_class = "equity"

                # Audit 2026-05-22 P0 fix: Moomoo SDK reports cost_price as
                # PER-CONTRACT premium (e.g. $13.315 per share) but options
                # multiplier is 100 — true cost basis = cost_price * qty * 100.
                # Previous code derived cost_basis = qty * avg_cost downstream,
                # missing the ×100, poisoning all P&L math.
                multiplier = 100 if asset_class == "option" else 1
                cost_basis = cost * qty * multiplier

                pl_ratio = _safe_num(row.get("pl_ratio"))
                unrealized_pct = pl_ratio * 100 if abs(pl_ratio) < 1 else pl_ratio
                # Recompute unrealized_pl from market_value - cost_basis;
                # don't trust raw pl_val (Moomoo bug returns it == market_value
                # on options, ignoring premium paid).
                if cost_basis > 0 and market_value > 0:
                    unrealized_pl = market_value - cost_basis
                    unrealized_pct = (unrealized_pl / cost_basis) * 100 if cost_basis else 0.0
                else:
                    unrealized_pl = _safe_num(row.get("pl_val"))
                today_pl = _safe_num(row.get("today_pl_val"))
                # Today's PL also needs ×100 for options (SDK reports per-share)
                today_pl = today_pl * multiplier if asset_class == "option" else today_pl
                today_pl_pct = (today_pl / cost_basis) * 100 if cost_basis else 0.0
                # Clamp absurd values from stale/missing quotes
                if abs(today_pl_pct) > 100:
                    today_pl_pct = 0.0
                row_currency = str(row.get("currency", "") or "").upper() or currency

                positions.append(
                    {
                        "symbol": symbol,
                        "name": str(row.get("stock_name", symbol)),
                        "broker": "MOOMOO",
                        "account_id": str(acc_id),
                        "quantity": qty,
                        "avg_cost": cost,
                        "cost_basis": cost_basis,  # NEW — needed for total_pl_pct
                        "multiplier": multiplier,  # NEW — explicit
                        "current_price": current_price,
                        "market_value": market_value,
                        "unrealized_pl": unrealized_pl,
                        "unrealized_pl_pct": unrealized_pct,
                        "daily_pl": today_pl,
                        "daily_pl_pct": today_pl_pct,
                        "currency": row_currency,
                        "sector": "",
                        "asset_class": asset_class,
                    }
                )
        return positions

    def _fetch_positions_sync(self) -> List[Dict[str, Any]]:
        """Query positions per account in its native currency."""
        results: List[Dict[str, Any]] = []
        try:
            account_list = self._list_accounts_sync()
        except Exception as exc:
            logger.error("Could not list Moomoo accounts for positions: %s", exc)
            return results

        target_env = TrdEnv.SIMULATE if self._trade_env_str == "SIMULATE" else TrdEnv.REAL
        for acc in account_list:
            acc_id = acc["acc_id"]
            currency_str = acc["currency"]
            currency_enum = _currency_enum(currency_str)
            try:
                ret, data = self._trade_ctx.position_list_query(
                    trd_env=target_env,
                    acc_id=acc_id,
                    currency=currency_enum,
                )
                if ret != RET_OK:
                    # Same currency fallback chain as accinfo
                    fallback_chain = ["USD", "HKD"]
                    if currency_str in fallback_chain:
                        fallback_chain.remove(currency_str)
                    recovered = False
                    for fallback in fallback_chain:
                        f_ret, f_data = self._trade_ctx.position_list_query(
                            trd_env=target_env,
                            acc_id=acc_id,
                            currency=_currency_enum(fallback),
                        )
                        if f_ret == RET_OK:
                            data = f_data
                            currency_str = fallback
                            recovered = True
                            break
                    if not recovered:
                        logger.warning("Moomoo acc %s positions skipped: %s", acc_id, data)
                        continue
                results.append(
                    {
                        "acc_id": acc_id,
                        "currency": currency_str,
                        "data": data,
                    }
                )
            except Exception as exc:
                logger.warning("Moomoo acc %s position_list_query raised: %s", acc_id, exc)
                continue
        return results

    async def _resolve_account_id(self) -> str:
        """Backwards-compat helper — returns the first known account id."""
        try:
            accounts = await asyncio.to_thread(self._list_accounts_sync)
            if accounts:
                return str(accounts[0]["acc_id"])
        except Exception:
            pass
        return "moomoo-default"
