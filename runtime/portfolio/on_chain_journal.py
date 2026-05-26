"""
NCL On-Chain Transaction Journal — Wave 14J J5a + J5b + J5c

Self-custody crypto positions (MetaMask + other wallets) carry NO
cost-basis info from the wallet itself. The wallet shows current
balance; the chain shows transactions; the operator's actual cost
basis lives nowhere unless we journal it.

This module gives that journal:

  J5a — Per-wallet transaction journal indexed by tx_hash with
        cost_basis computed at block-time price.
        Categories: buy / sell / transfer_in / transfer_out / swap /
                   lp_deposit / lp_withdraw / stake / unstake / yield /
                   airdrop / gas
        Each gas expenditure is a basis-adjustment hit; not free.

  J5b — Multi-chain aggregation across L1 + L2.
        Supported chains (config-level constants):
          ethereum / arbitrum / base / polygon / optimism / bsc /
          avalanche / solana / bitcoin
        Same wallet address (or per-chain address) rollups to one
        composite position view.

  J5c — LP + liquid-staking valuation.
        LP token entries carry:
          underlying_a, underlying_b, ratio_at_deposit,
          fees_accrued_to_date, impermanent_loss_pct
        Liquid-staking tokens (stETH, rETH, cbETH, etc.) carry:
          underlying = "ETH"
          conversion_ratio (live oracle ratio)
          accrued_yield_pct

Storage (JSONL append + JSON state, same pattern as everything else):
  data/portfolio/on_chain/{tx_journal,positions_state}.jsonl/.json

This module DOES NOT pull from Etherscan/Alchemy live (that's network
plumbing operator can wire later). It accepts pre-fetched tx rows via
record_tx() — works for CSV imports, manual entry, or a future live
fetcher.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.on_chain_journal")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio" / "on_chain"
TX_JOURNAL = DATA_DIR / "tx_journal.jsonl"
POSITIONS_FILE = DATA_DIR / "positions_state.json"

SUPPORTED_CHAINS = {
    "ethereum", "arbitrum", "base", "polygon", "optimism",
    "bsc", "avalanche", "solana", "bitcoin",
}

VALID_TX_CATEGORIES = {
    "buy", "sell", "transfer_in", "transfer_out", "swap",
    "lp_deposit", "lp_withdraw", "stake", "unstake", "yield",
    "airdrop", "gas",
}


@dataclass
class OnChainTx:
    tx_hash: str
    chain: str             # ethereum / arbitrum / etc.
    wallet: str            # lowercase address
    timestamp_iso: str
    block_number: Optional[int]
    category: str          # one of VALID_TX_CATEGORIES
    asset_symbol: str      # uppercase (ETH / USDC / WETH / stETH / ...)
    contract_address: Optional[str]  # ERC-20 contract; None for native
    qty: float             # SIGNED — incoming positive, outgoing negative
    price_at_block_usd: Optional[float]
    cost_basis_per_unit_usd: Optional[float]
    gas_paid_usd: float = 0.0
    counterparty: Optional[str] = None
    notes: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class OnChainPosition:
    """Aggregated open position for one (wallet, chain, asset_symbol)."""
    key: str               # f"{chain}:{wallet}:{asset_symbol}"
    chain: str
    wallet: str
    asset_symbol: str
    contract_address: Optional[str] = None
    qty: float = 0.0
    avg_cost_basis_usd: float = 0.0
    total_gas_spent_usd: float = 0.0
    last_tx_ts: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    # J5c — LP / liquid-staking enrichment when applicable
    is_lp: bool = False
    is_liquid_staked: bool = False
    underlying_a: Optional[str] = None
    underlying_b: Optional[str] = None
    conversion_ratio: Optional[float] = None
    accrued_yield_pct: Optional[float] = None
    impermanent_loss_pct: Optional[float] = None


# ── Classification helpers (J5c) ─────────────────────────────────

_LIQUID_STAKE_TOKENS = {
    "STETH": "ETH",       # Lido
    "RETH": "ETH",        # Rocket Pool
    "CBETH": "ETH",       # Coinbase
    "WSTETH": "ETH",      # Lido wrapped
    "FRXETH": "ETH",      # Frax
    "SFRXETH": "ETH",
    "JITOSOL": "SOL",
    "BSOL": "SOL",
    "MSOL": "SOL",        # Marinade
}

_LP_TOKEN_PREFIXES = {
    "UNI-V2-",            # Uniswap V2
    "UNI-V3-",            # Uniswap V3 NFTs
    "BPT-",               # Balancer
    "CRV-",               # Curve
    "CAKE-LP-",           # PancakeSwap
    "SLP-",               # Sushi
}


def classify_asset(symbol: str) -> dict:
    """Return classification flags for an asset symbol."""
    s = (symbol or "").upper().strip()
    if s in _LIQUID_STAKE_TOKENS:
        return {
            "is_liquid_staked": True,
            "underlying_a": _LIQUID_STAKE_TOKENS[s],
            "is_lp": False,
        }
    for prefix in _LP_TOKEN_PREFIXES:
        if s.startswith(prefix):
            return {
                "is_liquid_staked": False,
                "is_lp": True,
                "underlying_a": None,  # caller fills from tx metadata
                "underlying_b": None,
            }
    return {"is_liquid_staked": False, "is_lp": False}


def _position_key(chain: str, wallet: str, symbol: str) -> str:
    return f"{chain.lower()}:{wallet.lower()}:{symbol.upper()}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OnChainJournal:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._positions: dict[str, OnChainPosition] = {}
        self._seen_hashes: set[tuple[str, str]] = set()  # (chain, tx_hash) dedup
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            await self._load_state()
            await self._replay_seen()
            self._initialized = True
            log.info(
                "[ON-CHAIN] initialized — %d positions, %d known tx hashes",
                len(self._positions), len(self._seen_hashes),
            )

    async def _load_state(self) -> None:
        if not POSITIONS_FILE.exists():
            return
        try:
            raw = json.loads(POSITIONS_FILE.read_text())
            if not isinstance(raw, dict):
                return
            field_names = {f for f in OnChainPosition.__dataclass_fields__}  # type: ignore[attr-defined]
            for k, p in raw.items():
                if not isinstance(p, dict):
                    continue
                kept = {kk: vv for kk, vv in p.items() if kk in field_names}
                kept.setdefault("key", k)
                try:
                    self._positions[k] = OnChainPosition(**kept)
                except Exception as e:
                    log.warning("[ON-CHAIN] skip malformed %s: %s", k, e)
        except Exception as e:
            log.warning("[ON-CHAIN] load failed: %s", e)

    async def _replay_seen(self) -> None:
        if not TX_JOURNAL.exists():
            return
        try:
            with open(TX_JOURNAL, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                        tx = row.get("tx", {})
                        self._seen_hashes.add(
                            (tx.get("chain", "").lower(), tx.get("tx_hash", ""))
                        )
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            log.warning("[ON-CHAIN] tx replay failed: %s", e)

    async def _persist_positions(self) -> None:
        snap = {k: asdict(p) for k, p in self._positions.items()}
        tmp = POSITIONS_FILE.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(snap, indent=2, sort_keys=True))
            tmp.replace(POSITIONS_FILE)
        except Exception as e:
            log.error("[ON-CHAIN] persist failed: %s", e)

    def _append_tx(self, tx: OnChainTx) -> None:
        try:
            with open(TX_JOURNAL, "a") as f:
                f.write(json.dumps({"ts": _now(), "tx": asdict(tx)}) + "\n")
        except Exception as e:
            log.warning("[ON-CHAIN] tx append failed: %s", e)

    # ── Public API ──────────────────────────────────────────────

    async def record_tx(
        self,
        *,
        tx_hash: str,
        chain: str,
        wallet: str,
        timestamp_iso: str,
        category: str,
        asset_symbol: str,
        qty: float,
        price_at_block_usd: Optional[float] = None,
        block_number: Optional[int] = None,
        contract_address: Optional[str] = None,
        gas_paid_usd: float = 0.0,
        counterparty: Optional[str] = None,
        notes: str = "",
        metadata: Optional[dict] = None,
    ) -> dict:
        """Idempotent — (chain, tx_hash) seen before returns the existing
        aggregated position without re-applying."""
        if category not in VALID_TX_CATEGORIES:
            raise ValueError(f"category must be in {sorted(VALID_TX_CATEGORIES)}")
        if chain.lower() not in SUPPORTED_CHAINS:
            log.warning(
                "[ON-CHAIN] unsupported chain %r — recording anyway", chain
            )
        await self.initialize()
        key = _position_key(chain, wallet, asset_symbol)
        dedup = (chain.lower(), tx_hash)
        async with self._lock:
            if dedup in self._seen_hashes:
                pos = self._positions.get(key)
                return asdict(pos) if pos else {"status": "duplicate", "key": key}
            self._seen_hashes.add(dedup)
            cost_basis = (
                price_at_block_usd if price_at_block_usd is not None else 0.0
            )
            tx = OnChainTx(
                tx_hash=tx_hash,
                chain=chain.lower(),
                wallet=wallet.lower(),
                timestamp_iso=timestamp_iso,
                block_number=block_number,
                category=category,
                asset_symbol=asset_symbol.upper(),
                contract_address=(contract_address or None),
                qty=float(qty),
                price_at_block_usd=price_at_block_usd,
                cost_basis_per_unit_usd=cost_basis,
                gas_paid_usd=float(gas_paid_usd),
                counterparty=counterparty,
                notes=notes,
                metadata=metadata or {},
            )
            self._append_tx(tx)
            pos = self._positions.get(key)
            if pos is None:
                cls = classify_asset(asset_symbol)
                pos = OnChainPosition(
                    key=key, chain=chain.lower(), wallet=wallet.lower(),
                    asset_symbol=asset_symbol.upper(),
                    contract_address=contract_address,
                    is_lp=cls["is_lp"], is_liquid_staked=cls["is_liquid_staked"],
                    underlying_a=cls.get("underlying_a"),
                    underlying_b=cls.get("underlying_b"),
                )
                self._positions[key] = pos
            # Update aggregated position
            old_qty = pos.qty
            if category in ("buy", "transfer_in", "swap", "lp_withdraw",
                            "unstake", "yield", "airdrop"):
                # Inflow — weighted-avg cost basis update
                new_qty = old_qty + abs(qty)
                if new_qty > 0:
                    pos.avg_cost_basis_usd = (
                        (pos.avg_cost_basis_usd * old_qty + cost_basis * abs(qty))
                        / new_qty
                    ) if cost_basis > 0 else pos.avg_cost_basis_usd
                pos.qty = new_qty
            elif category in ("sell", "transfer_out", "lp_deposit",
                              "stake"):
                pos.qty = max(0.0, old_qty - abs(qty))
            elif category == "gas":
                pos.total_gas_spent_usd += gas_paid_usd
                pos.qty = max(0.0, old_qty - abs(qty))
            pos.total_gas_spent_usd += gas_paid_usd
            pos.last_tx_ts = timestamp_iso
            await self._persist_positions()
            return asdict(pos)

    async def positions_for(
        self,
        wallet: Optional[str] = None,
        chain: Optional[str] = None,
    ) -> list[dict]:
        await self.initialize()
        async with self._lock:
            out = []
            for p in self._positions.values():
                if wallet and p.wallet != wallet.lower():
                    continue
                if chain and p.chain != chain.lower():
                    continue
                if p.qty <= 0:
                    continue
                out.append(asdict(p))
            return sorted(out, key=lambda x: -x["qty"])

    async def aggregate_multichain(
        self,
        wallet: str,
    ) -> dict:
        """J5b — Same wallet (or per-chain wallet) rolled up across
        all chains. Returns:
          {
            wallet, chains_with_balance,
            by_symbol: {SYM: {total_qty, by_chain: {chain: qty},
                              total_basis_usd, est_value_usd_at_basis}}
          }
        """
        await self.initialize()
        w = wallet.lower()
        async with self._lock:
            by_symbol: dict[str, dict] = {}
            chains: set[str] = set()
            for p in self._positions.values():
                if p.wallet != w or p.qty <= 0:
                    continue
                chains.add(p.chain)
                entry = by_symbol.setdefault(p.asset_symbol, {
                    "total_qty": 0.0, "by_chain": {},
                    "total_basis_usd": 0.0,
                })
                entry["total_qty"] += p.qty
                entry["by_chain"][p.chain] = (
                    entry["by_chain"].get(p.chain, 0.0) + p.qty
                )
                entry["total_basis_usd"] += p.qty * p.avg_cost_basis_usd
            for sym, e in by_symbol.items():
                e["est_value_usd_at_basis"] = round(e["total_basis_usd"], 2)
                e["total_qty"] = round(e["total_qty"], 8)
            return {
                "wallet": w,
                "chains_with_balance": sorted(chains),
                "by_symbol": by_symbol,
            }


_JOURNAL: Optional[OnChainJournal] = None
_JOURNAL_LOCK = asyncio.Lock()


async def get_on_chain_journal() -> OnChainJournal:
    global _JOURNAL
    if _JOURNAL is not None:
        await _JOURNAL.initialize()
        return _JOURNAL
    async with _JOURNAL_LOCK:
        if _JOURNAL is None:
            _JOURNAL = OnChainJournal()
            await _JOURNAL.initialize()
    return _JOURNAL
