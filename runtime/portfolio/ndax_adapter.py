#!/usr/bin/env python3
"""
NDAX Crypto Adapter for NCL Brain
==================================
Read-only adapter that surfaces NDAX (Canadian crypto exchange, AlphaPoint
backend) balances and positions to the portfolio manager.

Two data paths
--------------
1. **Live REST**: when ``NDAX_API_KEY`` / ``NDAX_API_SECRET`` / ``NDAX_USER_ID``
   are all set, attempts authenticated AlphaPoint calls at
   ``https://api.ndax.io:8443``. Auth = SHA256 HMAC of ``nonce + user_id + api_key``
   signed with ``api_secret``. The AlphaPoint REST surface is gnarly (typed
   message envelopes, OMS account discovery, etc.) so this path is best-effort
   — failures fall through to the manual file.

2. **Manual JSON** (default): reads ``data/portfolio/ndax_manual.json``, a
   user-curated holdings file. Shape::

       {
         "cad_balance": 4492.04,
         "holdings": [
           {"symbol": "BTC", "quantity": 0.025, "avg_cost_cad": 75000},
           {"symbol": "ETH", "quantity": 1.2,   "avg_cost_cad": 5200},
           ...
         ]
       }

   Prices are looked up via CoinGecko free tier (cached 5 min).

If neither path produces data, returns ``[]`` everywhere — never raises.

Per-position dict shape (matches portfolio_manager contract)::

    {
        "broker": "NDAX",
        "symbol": "BTC",
        "name": "Bitcoin",
        "account_id": "NDAX",
        "quantity": 0.025,
        "avg_cost": 75000.0,
        "current_price": 110000.0,
        "market_value": 2750.0,
        "asset_class": "crypto",
        "currency": "CAD",
    }
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
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

logger = logging.getLogger("ncl.portfolio.ndax")

# Paths
_ROOT = Path(__file__).resolve().parents[2]
_MANUAL_FILE = _ROOT / "data" / "portfolio" / "ndax_manual.json"

# AlphaPoint endpoint (NDAX uses port 8443 for REST)
_NDAX_REST = "https://api.ndax.io:8443"

# CoinGecko (no auth, public free tier — 30 calls/min)
_COINGECKO_API = "https://api.coingecko.com/api/v3"

# 5-min price cache (CoinGecko is rate limited)
_PRICE_CACHE_SECONDS = 300

# Common CAD-quoted spot pairs (used for naive symbol → CoinGecko-id mapping)
_SYMBOL_TO_CG_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "ADA": "cardano",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "LINK": "chainlink",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "AVAX": "avalanche-2",
    "USDC": "usd-coin",
    "USDT": "tether",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "UNI": "uniswap",
    "AAVE": "aave",
    "SHIB": "shiba-inu",
}


class NDAXAdapter:
    """NDAX read-only adapter — manual JSON + best-effort REST."""

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        user_id: str = "",
    ):
        self.api_key = api_key or os.getenv("NDAX_API_KEY", "")
        self.api_secret = api_secret or os.getenv("NDAX_API_SECRET", "")
        self.user_id = user_id or os.getenv("NDAX_USER_ID", "")

        self._connected = False
        self._last_sync: Optional[str] = None

        # Price cache
        self._price_cache: Dict[str, float] = {}
        self._price_cache_at: float = 0.0

        # Mode: "manual" or "live"
        self._mode = "disconnected"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def broker(self) -> str:
        return "NDAX"

    async def connect(self) -> bool:
        """
        Decide which data path is active for this adapter.

        * If creds are set AND a live verification call succeeds → "live"
        * Else if manual JSON exists → "manual"
        * Else → disconnected (everything returns [])
        """
        live_ok = False
        if self.api_key and self.api_secret and self.user_id and _HTTPX_AVAILABLE:
            try:
                live_ok = await self._verify_live_credentials()
            except Exception as exc:
                logger.warning("NDAX live verification raised: %s", exc)

        if live_ok:
            self._mode = "live"
            self._connected = True
            self._last_sync = datetime.now(timezone.utc).isoformat()
            logger.info("NDAX adapter connected — mode=live")
            return True

        if _MANUAL_FILE.exists():
            self._mode = "manual"
            self._connected = True
            self._last_sync = datetime.now(timezone.utc).isoformat()
            logger.info("NDAX adapter connected — mode=manual (%s)", _MANUAL_FILE)
            return True

        self._mode = "disconnected"
        self._connected = False
        if not (self.api_key or self.api_secret or self.user_id):
            logger.info("NDAX adapter disconnected — no creds + no manual file")
        else:
            logger.info("NDAX adapter disconnected — partial creds + no manual file")
        return False

    async def disconnect(self) -> None:
        self._connected = False
        self._mode = "disconnected"
        self._last_sync = None

    async def _verify_live_credentials(self) -> bool:
        """Try ``GetUserAccounts`` on the AlphaPoint REST surface.

        This is the simplest GET that proves the HMAC signature is valid.
        Returns True only on HTTP 200 with a parseable body.
        """
        if not _HTTPX_AVAILABLE:
            return False
        nonce = str(int(time.time() * 1000))
        signature = self._hmac_sign(nonce)
        headers = {
            "Nonce": nonce,
            "APIKey": self.api_key,
            "Signature": signature,
            "UserId": str(self.user_id),
            "Content-Type": "application/json",
        }
        url = f"{_NDAX_REST}/AP/GetUserAccounts"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    url,
                    headers=headers,
                    params={"UserId": str(self.user_id)},
                )
            if resp.status_code != 200:
                logger.debug("NDAX live verify: HTTP %s — %s", resp.status_code, resp.text[:200])
                return False
            body = resp.json()
            return body is not None
        except Exception as exc:
            logger.debug("NDAX live verify raised: %s", exc)
            return False

    def _hmac_sign(self, nonce: str) -> str:
        """AlphaPoint HMAC: SHA256(nonce + user_id + api_key) keyed by api_secret."""
        msg = (nonce + str(self.user_id) + self.api_key).encode("utf-8")
        key = self.api_secret.encode("utf-8")
        return hmac.new(key, msg, hashlib.sha256).hexdigest()

    # ------------------------------------------------------------------
    # Data methods
    # ------------------------------------------------------------------

    async def get_accounts(self) -> List[Dict[str, Any]]:
        """Return a single synthetic 'NDAX' account."""
        if not self._connected:
            return []

        manual = self._load_manual_safe()
        cad_balance = float(manual.get("cad_balance", 0.0) or 0.0)

        return [
            {
                "broker": "NDAX",
                "account_id": "NDAX",
                "name": "NDAX Crypto",
                "account_type": "crypto",
                "currency": "CAD",
                "net_liquidation": cad_balance,
                "cash_balance": cad_balance,
                "buying_power": cad_balance,
                "unrealized_pl": 0.0,
                "daily_pl": 0.0,
                "connected": True,
                "last_sync": self._last_sync,
                "mode": self._mode,
            }
        ]

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Return per-holding rows with live CoinGecko prices."""
        if not self._connected:
            return []

        manual = self._load_manual_safe()
        holdings = manual.get("holdings", []) or []
        if not holdings:
            return []

        # Build CoinGecko symbol set once
        cg_ids: List[str] = []
        for h in holdings:
            sym = str(h.get("symbol", "")).upper()
            cg = _SYMBOL_TO_CG_ID.get(sym)
            if cg and cg not in cg_ids:
                cg_ids.append(cg)

        prices_usd = await self._fetch_prices_usd(cg_ids)
        # We want CAD prices — use USD price * FX (NDAX is CAD-denominated).
        # FX is owned by portfolio_manager; here we report market_value in CAD
        # by converting USD → CAD via the manager's rate at sync time. To keep
        # the adapter self-contained, we just emit current_price in CAD by
        # looking up CoinGecko's `cad` market directly when possible.
        prices_cad = await self._fetch_prices_cad(cg_ids)

        out: List[Dict[str, Any]] = []
        for h in holdings:
            sym = str(h.get("symbol", "")).upper()
            try:
                qty = float(h.get("quantity", 0) or 0)
            except (TypeError, ValueError):
                qty = 0.0
            if qty == 0:
                continue
            try:
                avg_cost = float(h.get("avg_cost_cad", 0) or 0)
            except (TypeError, ValueError):
                avg_cost = 0.0

            cg = _SYMBOL_TO_CG_ID.get(sym)
            price_cad = prices_cad.get(cg, 0.0) if cg else 0.0
            price_usd = prices_usd.get(cg, 0.0) if cg else 0.0

            market_value_cad = round(qty * price_cad, 2) if price_cad else 0.0
            unrealized_pl = (
                round((price_cad - avg_cost) * qty, 2) if price_cad and avg_cost else 0.0
            )
            unrealized_pl_pct = round((price_cad / avg_cost - 1) * 100, 2) if avg_cost else 0.0

            out.append(
                {
                    "broker": "NDAX",
                    "account_id": "NDAX",
                    "symbol": sym,
                    "name": h.get("name") or sym,
                    "quantity": qty,
                    "avg_cost": avg_cost,
                    "current_price": price_cad,
                    "current_price_usd": price_usd,
                    "market_value": market_value_cad,
                    "asset_class": "crypto",
                    "currency": "CAD",
                    "sector": "Crypto",
                    "unrealized_pl": unrealized_pl,
                    "unrealized_pl_pct": unrealized_pl_pct,
                    "daily_pl": 0.0,
                    "daily_pl_pct": 0.0,
                    "metadata": {"source": self._mode},
                }
            )

        return out

    async def get_balances(self) -> Dict[str, float]:
        """Return a currency-keyed balance dict (CAD + per-coin quantities)."""
        if not self._connected:
            return {}
        manual = self._load_manual_safe()
        out: Dict[str, float] = {"CAD": float(manual.get("cad_balance", 0.0) or 0.0)}
        for h in manual.get("holdings", []) or []:
            sym = str(h.get("symbol", "")).upper()
            try:
                qty = float(h.get("quantity", 0) or 0)
            except (TypeError, ValueError):
                qty = 0.0
            if qty:
                out[sym] = qty
        return out

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_manual_safe(self) -> Dict[str, Any]:
        if not _MANUAL_FILE.exists():
            return {}
        try:
            with open(_MANUAL_FILE) as f:
                data = json.load(f) or {}
            if not isinstance(data, dict):
                return {}
            return data
        except Exception as exc:
            logger.warning("NDAX manual file unreadable: %s", exc)
            return {}

    async def _fetch_prices_usd(self, cg_ids: List[str]) -> Dict[str, float]:
        return await self._fetch_prices(cg_ids, vs="usd")

    async def _fetch_prices_cad(self, cg_ids: List[str]) -> Dict[str, float]:
        return await self._fetch_prices(cg_ids, vs="cad")

    async def _fetch_prices(self, cg_ids: List[str], vs: str = "usd") -> Dict[str, float]:
        if not cg_ids or not _HTTPX_AVAILABLE:
            return {}
        # 5-min cache keyed by id+vs
        cache_key = f"{vs}:{','.join(sorted(cg_ids))}"
        now = time.time()
        if (
            now - self._price_cache_at
        ) < _PRICE_CACHE_SECONDS and cache_key in self._price_cache_meta:
            return self._price_cache_meta[cache_key]

        url = f"{_COINGECKO_API}/simple/price"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    url,
                    params={"ids": ",".join(cg_ids), "vs_currencies": vs},
                )
            if resp.status_code != 200:
                logger.debug("CoinGecko %s: %s", resp.status_code, resp.text[:120])
                return {}
            body = resp.json() or {}
            out: Dict[str, float] = {}
            for cg, payload in body.items():
                try:
                    out[cg] = float(payload.get(vs, 0) or 0)
                except (TypeError, ValueError):
                    out[cg] = 0.0
            self._price_cache_meta[cache_key] = out
            self._price_cache_at = now
            return out
        except Exception as exc:
            logger.debug("CoinGecko fetch failed: %s", exc)
            return {}

    # Per-(currency,id-set) cache so a CAD lookup doesn't blow away the USD one
    @property
    def _price_cache_meta(self) -> Dict[str, Dict[str, float]]:
        if not hasattr(self, "_pc_meta"):
            self._pc_meta: Dict[str, Dict[str, float]] = {}
        return self._pc_meta
