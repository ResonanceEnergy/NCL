#!/usr/bin/env python3
"""
MetaMask Read-Only Adapter for NCL Brain
==========================================
Surfaces ETH + top ERC-20 holdings for a public wallet address.

No private key. No signing. No tx submission. Pure read-only JSON-RPC
queries against a free public Ethereum mainnet RPC.

Env vars
--------
    METAMASK_ADDRESS    EVM address starting with 0x (40 hex chars)

Data flow
---------
1. ``eth_getBalance(address, "latest")`` → ETH balance (wei → ether)
2. For each token in ``data/erc20_tokens.json``:
       ``eth_call`` with ``balanceOf(address)`` (selector 0x70a08231)
       Decode 32-byte uint256, divide by 10^decimals.
3. CoinGecko ``simple/price`` for USD prices (5-min cache, free tier).

If ``METAMASK_ADDRESS`` is missing or RPC fails, returns ``[]`` gracefully.

Position dict::

    {
        "broker": "METAMASK",
        "symbol": "ETH",
        "name": "Ethereum",
        "account_id": "0x...truncated",
        "quantity": 1.42,
        "current_price": 3850.0,
        "market_value": 5467.0,
        "asset_class": "crypto",
        "currency": "USD",
    }
"""

from __future__ import annotations

import asyncio
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

logger = logging.getLogger("ncl.portfolio.metamask")

_TOKENS_FILE = Path(__file__).resolve().parent / "data" / "erc20_tokens.json"

# Free public Ethereum mainnet RPCs (try in order)
_RPC_ENDPOINTS = [
    "https://eth-mainnet.public.blastapi.io",
    "https://rpc.ankr.com/eth",
    "https://ethereum-rpc.publicnode.com",
    "https://cloudflare-eth.com",
]

_COINGECKO_API = "https://api.coingecko.com/api/v3"
_PRICE_CACHE_SECONDS = 300

# ERC-20 balanceOf(address) selector: keccak256("balanceOf(address)")[:4]
_BALANCE_OF_SELECTOR = "0x70a08231"


class MetaMaskAdapter:
    """Read-only wallet adapter for any EVM address."""

    def __init__(self, address: str = ""):
        self.address = (address or os.getenv("METAMASK_ADDRESS", "")).strip()

        self._connected = False
        self._last_sync: Optional[str] = None
        self._tokens: List[Dict[str, Any]] = []
        self._rpc_url: Optional[str] = None

        # Price cache
        self._price_cache: Dict[str, float] = {}
        self._price_cache_at: float = 0.0

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def broker(self) -> str:
        return "METAMASK"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Probe an RPC for chain id; pick the first one that responds."""
        if not self.address:
            logger.info("MetaMask adapter: METAMASK_ADDRESS not set — disconnected")
            return False
        if not self.address.startswith("0x") or len(self.address) != 42:
            logger.warning("MetaMask: address %r does not look like an EVM address", self.address)
            return False
        if not _HTTPX_AVAILABLE:
            logger.warning("MetaMask: httpx not installed — disconnected")
            return False

        self._load_token_list()

        for url in _RPC_ENDPOINTS:
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.post(
                        url,
                        json={
                            "jsonrpc": "2.0",
                            "method": "eth_chainId",
                            "params": [],
                            "id": 1,
                        },
                    )
                if resp.status_code == 200 and "result" in (resp.json() or {}):
                    self._rpc_url = url
                    self._connected = True
                    self._last_sync = datetime.now(timezone.utc).isoformat()
                    logger.info(
                        "MetaMask adapter connected — rpc=%s wallet=%s", url, self._truncated()
                    )
                    return True
            except Exception as exc:
                logger.debug("MetaMask RPC %s failed: %s", url, exc)
                continue

        logger.warning("MetaMask: no RPC reachable — disconnected")
        return False

    async def disconnect(self) -> None:
        self._connected = False
        self._last_sync = None
        self._rpc_url = None

    def _load_token_list(self) -> None:
        if not _TOKENS_FILE.exists():
            self._tokens = []
            return
        try:
            with open(_TOKENS_FILE) as f:
                data = json.load(f) or {}
            self._tokens = data.get("tokens", []) or []
        except Exception as exc:
            logger.warning("MetaMask: token list unreadable: %s", exc)
            self._tokens = []

    def _truncated(self) -> str:
        if len(self.address) >= 10:
            return f"{self.address[:6]}...{self.address[-4:]}"
        return self.address

    # ------------------------------------------------------------------
    # Data methods
    # ------------------------------------------------------------------

    async def get_accounts(self) -> List[Dict[str, Any]]:
        """Single synthetic account representing the wallet."""
        if not self._connected:
            return []
        return [
            {
                "broker": "METAMASK",
                "account_id": self.address,
                "name": f"Wallet {self._truncated()}",
                "account_type": "wallet",
                "currency": "USD",
                "net_liquidation": 0.0,  # filled by manager from positions
                "cash_balance": 0.0,
                "buying_power": 0.0,
                "unrealized_pl": 0.0,
                "daily_pl": 0.0,
                "connected": True,
                "last_sync": self._last_sync,
            }
        ]

    async def get_positions(self) -> List[Dict[str, Any]]:
        """ETH + ERC-20 holdings priced via CoinGecko USD."""
        if not self._connected or not self._rpc_url:
            return []

        # 1) ETH balance
        eth_balance = await self._eth_balance()
        # 2) Concurrent token balanceOf calls
        token_balances = await asyncio.gather(
            *[self._token_balance(tok) for tok in self._tokens],
            return_exceptions=True,
        )

        # Collect non-zero holdings to price
        holdings: List[Dict[str, Any]] = []
        if eth_balance > 0:
            holdings.append(
                {
                    "symbol": "ETH",
                    "name": "Ethereum",
                    "quantity": eth_balance,
                    "coingecko_id": "ethereum",
                }
            )
        for tok, bal in zip(self._tokens, token_balances):
            if isinstance(bal, Exception) or not bal or bal <= 0:
                continue
            holdings.append(
                {
                    "symbol": tok["symbol"],
                    "name": tok.get("name", tok["symbol"]),
                    "quantity": bal,
                    "coingecko_id": tok.get("coingecko_id"),
                }
            )

        if not holdings:
            return []

        # Price all in one shot
        cg_ids = [h["coingecko_id"] for h in holdings if h.get("coingecko_id")]
        prices = await self._fetch_prices_usd(cg_ids)

        out: List[Dict[str, Any]] = []
        for h in holdings:
            price = prices.get(h.get("coingecko_id", ""), 0.0)
            mv = round(h["quantity"] * price, 2)
            out.append(
                {
                    "broker": "METAMASK",
                    "account_id": self.address,
                    "symbol": h["symbol"],
                    "name": h["name"],
                    "quantity": h["quantity"],
                    "avg_cost": 0.0,
                    "current_price": price,
                    "market_value": mv,
                    "asset_class": "crypto",
                    "currency": "USD",
                    "sector": "Crypto",
                    "unrealized_pl": 0.0,
                    "unrealized_pl_pct": 0.0,
                    "daily_pl": 0.0,
                    "daily_pl_pct": 0.0,
                    "metadata": {
                        "wallet": self.address,
                        "chain": "ethereum",
                    },
                }
            )
        return out

    async def get_balances(self) -> Dict[str, float]:
        positions = await self.get_positions()
        return {p["symbol"]: p["quantity"] for p in positions}

    # ------------------------------------------------------------------
    # RPC helpers
    # ------------------------------------------------------------------

    async def _rpc(self, method: str, params: List[Any]) -> Any:
        if not self._rpc_url or not _HTTPX_AVAILABLE:
            return None
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    self._rpc_url,
                    json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
                )
            if resp.status_code != 200:
                return None
            body = resp.json() or {}
            return body.get("result")
        except Exception as exc:
            logger.debug("RPC %s failed: %s", method, exc)
            return None

    async def _eth_balance(self) -> float:
        result = await self._rpc("eth_getBalance", [self.address, "latest"])
        if not result:
            return 0.0
        try:
            wei = int(result, 16)
            return wei / 1e18
        except (TypeError, ValueError):
            return 0.0

    async def _token_balance(self, token: Dict[str, Any]) -> float:
        # ABI-encoded balanceOf(address) call: selector + left-padded address
        addr_no_prefix = self.address[2:].lower().zfill(64)
        data = _BALANCE_OF_SELECTOR + addr_no_prefix
        result = await self._rpc(
            "eth_call",
            [{"to": token["address"], "data": data}, "latest"],
        )
        if not result or result == "0x":
            return 0.0
        try:
            raw = int(result, 16)
            decimals = int(token.get("decimals", 18))
            return raw / (10**decimals)
        except (TypeError, ValueError):
            return 0.0

    # ------------------------------------------------------------------
    # Price helpers
    # ------------------------------------------------------------------

    async def _fetch_prices_usd(self, cg_ids: List[str]) -> Dict[str, float]:
        if not cg_ids or not _HTTPX_AVAILABLE:
            return {}
        now = time.time()
        cache_key = ",".join(sorted(cg_ids))
        if (
            now - self._price_cache_at
        ) < _PRICE_CACHE_SECONDS and cache_key in self._price_cache_meta:
            return self._price_cache_meta[cache_key]
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    f"{_COINGECKO_API}/simple/price",
                    params={"ids": ",".join(cg_ids), "vs_currencies": "usd"},
                )
            if resp.status_code != 200:
                return {}
            body = resp.json() or {}
            out = {cg: float((p or {}).get("usd", 0) or 0) for cg, p in body.items()}
            self._price_cache_meta[cache_key] = out
            self._price_cache_at = now
            return out
        except Exception as exc:
            logger.debug("CoinGecko USD fetch failed: %s", exc)
            return {}

    @property
    def _price_cache_meta(self) -> Dict[str, Dict[str, float]]:
        if not hasattr(self, "_pc_meta"):
            self._pc_meta: Dict[str, Dict[str, float]] = {}
        return self._pc_meta
