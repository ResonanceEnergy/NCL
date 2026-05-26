"""
NCL Trade Cost Ledger — Wave 14J Phase 1 (J0a)

Mirror of `runtime/cost_tracker.py` but for *trading* costs instead of
LLM API costs. The architectural symmetry is intentional — same JSONL
append-only + (optional) SQLite double-write pattern; same singleton
access; same crash-safe replay on startup.

What this tracks (NOT what cost_tracker.py tracks):
  - broker commissions (IBKR/Moomoo/SnapTrade)
  - financing / margin interest
  - short borrow fees
  - assignment / exercise fees
  - on-chain gas (MetaMask)
  - exchange fees (NDAX, Polymarket)
  - slippage (arrival or VWAP) when measurable
  - regulatory fees (SEC §31, ORF, OCC clearing)

What this does NOT do (deliberately — see the Wave 14J audit doc):
  - enforce daily budgets (trading costs are after-the-fact; can_spend()
    doesn't apply). The corollary is that record() never blocks and
    cannot reject a write.
  - cap trades. That's a Tier 1 J1a concern (heat caps); this is Tier 0
    observability foundation.

Storage:
  - JSONL append-only at data/portfolio/trade_costs.jsonl  (source of truth)
  - Optional SQLite mirror at NCL_BASE/data/persistence/ncl.db
    table `trade_cost_ledger` when NCL_TRADE_COSTS_SQLITE=true
  - Daily summary cache: data/portfolio/trade_costs_daily.json
    (refreshed at UTC midnight rollover, replayed on startup)

Public surface:
  - get_trade_cost_ledger() -> TradeCostLedger  (singleton, async-init)
  - TradeCostLedger.record(...)
  - TradeCostLedger.summary_today() / summary_for_date(d)
  - TradeCostLedger.by_strategy() / by_broker() / by_asset_class()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ncl.portfolio.trade_cost_ledger")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
COST_DIR = NCL_BASE / "data" / "portfolio"
LEDGER_FILE = COST_DIR / "trade_costs.jsonl"
DAILY_SUMMARY_FILE = COST_DIR / "trade_costs_daily.json"

# Known action types. Free-form is allowed — this is documentation only.
TRADE_COST_ACTIONS = {
    "commission",       # broker commission per fill
    "financing",        # margin interest
    "borrow",           # short borrow fee
    "assignment",       # option assignment / exercise fee
    "gas",              # on-chain gas (MetaMask)
    "exchange_fee",     # NDAX, Polymarket
    "slippage",         # measured arrival or VWAP slippage
    "regulatory",       # SEC §31, ORF, OCC clearing, etc.
    "fx_conversion",    # FX spread on currency conversion
    "other",            # catch-all
}


def _sqlite_enabled() -> bool:
    """Mirror runtime.config.flags pattern but standalone — gates SQLite
    double-write via NCL_TRADE_COSTS_SQLITE env. Default OFF until we've
    double-written for ~1 week."""
    return os.getenv("NCL_TRADE_COSTS_SQLITE", "false").lower() in ("1", "true", "yes")


class TradeCostLedger:
    """File-backed trading cost ledger. Append-only, crash-safe.

    No budget enforcement — record() never blocks. For risk caps see the
    J1a heat-cap module (forthcoming in Wave 14J Phase 2).
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._daily_totals_by_broker: dict[str, float] = defaultdict(float)
        self._daily_totals_by_action: dict[str, float] = defaultdict(float)
        self._daily_totals_by_strategy: dict[str, float] = defaultdict(float)
        self._daily_totals_by_asset_class: dict[str, float] = defaultdict(float)
        self._daily_count: int = 0
        self._daily_sum_usd: float = 0.0
        self._current_date: str = ""  # YYYY-MM-DD (UTC)
        self._initialized: bool = False
        self._sqlite_store = None  # type: ignore[assignment]
        self._sqlite_warned: bool = False

    # ── Initialization + state ────────────────────────────────────────

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            COST_DIR.mkdir(parents=True, exist_ok=True)
            self._current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            await self._replay_today()
            self._initialized = True
            log.info(
                "[TRADE-COST] Ledger initialized — today's trading cost: "
                "$%.4f across %d entries",
                self._daily_sum_usd,
                self._daily_count,
            )

    async def _replay_today(self) -> None:
        """Rebuild today's totals from JSONL after restart."""
        if not LEDGER_FILE.exists():
            return
        today = self._current_date
        count = 0
        try:
            with open(LEDGER_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("date") == today:
                            self._accumulate(entry)
                            count += 1
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            log.warning("[TRADE-COST] Error replaying ledger: %s", e)
        if count > 0:
            log.info("[TRADE-COST] Replayed %d entries for %s", count, today)

    def _accumulate(self, entry: dict) -> None:
        amt = float(entry.get("amount_usd", 0.0))
        self._daily_sum_usd += amt
        self._daily_count += 1
        self._daily_totals_by_broker[entry.get("broker", "unknown")] += amt
        self._daily_totals_by_action[entry.get("action", "other")] += amt
        if entry.get("strategy_tag"):
            self._daily_totals_by_strategy[entry["strategy_tag"]] += amt
        if entry.get("asset_class"):
            self._daily_totals_by_asset_class[entry["asset_class"]] += amt

    def _check_date_rollover(self) -> None:
        """Reset accumulators at UTC midnight, persisting yesterday's summary."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._current_date:
            log.info(
                "[TRADE-COST] Date rollover %s → %s. Yesterday's total: $%.4f / %d entries",
                self._current_date,
                today,
                self._daily_sum_usd,
                self._daily_count,
            )
            try:
                self._save_daily_summary()
            except Exception as e:
                log.warning("[TRADE-COST] failed to save daily summary: %s", e)
            self._daily_totals_by_broker.clear()
            self._daily_totals_by_action.clear()
            self._daily_totals_by_strategy.clear()
            self._daily_totals_by_asset_class.clear()
            self._daily_count = 0
            self._daily_sum_usd = 0.0
            self._current_date = today

    def _save_daily_summary(self) -> None:
        """Append/update DAILY_SUMMARY_FILE with current day rollup."""
        snapshot = {
            "date": self._current_date,
            "total_usd": round(self._daily_sum_usd, 6),
            "entries": self._daily_count,
            "by_broker": dict(self._daily_totals_by_broker),
            "by_action": dict(self._daily_totals_by_action),
            "by_strategy": dict(self._daily_totals_by_strategy),
            "by_asset_class": dict(self._daily_totals_by_asset_class),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        all_days: dict[str, Any] = {}
        if DAILY_SUMMARY_FILE.exists():
            try:
                all_days = json.loads(DAILY_SUMMARY_FILE.read_text())
                if not isinstance(all_days, dict):
                    all_days = {}
            except Exception:
                all_days = {}
        all_days[self._current_date] = snapshot
        # Keep last 365 days
        if len(all_days) > 365:
            for k in sorted(all_days.keys())[:-365]:
                all_days.pop(k, None)
        DAILY_SUMMARY_FILE.write_text(json.dumps(all_days, indent=2, sort_keys=True))

    # ── Record + read API ─────────────────────────────────────────────

    async def record(
        self,
        *,
        broker: str,
        action: str,
        amount_usd: float,
        symbol: Optional[str] = None,
        asset_class: Optional[str] = None,
        account_id: Optional[str] = None,
        strategy_tag: Optional[str] = None,
        currency: str = "USD",
        fx_rate: Optional[float] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """Record a trading-cost event.

        Never blocks, never raises — cost recording must NEVER fail the
        trading path (same invariant as cost_tracker.py).

        amount_usd should be POSITIVE for costs paid (commission, fee,
        gas). For credits (rebates, executed-as-maker rebates) pass a
        NEGATIVE amount.
        """
        await self.initialize()
        now = datetime.now(timezone.utc)
        entry = {
            "timestamp": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "broker": broker,
            "action": action,
            "amount_usd": round(float(amount_usd), 6),
        }
        if symbol:
            entry["symbol"] = symbol
        if asset_class:
            entry["asset_class"] = asset_class
        if account_id:
            entry["account_id"] = account_id
        if strategy_tag:
            entry["strategy_tag"] = strategy_tag
        if currency and currency != "USD":
            entry["currency"] = currency
        if fx_rate is not None:
            entry["fx_rate"] = round(float(fx_rate), 6)
        if metadata:
            entry["metadata"] = metadata

        async with self._lock:
            self._check_date_rollover()
            self._accumulate(entry)
            try:
                COST_DIR.mkdir(parents=True, exist_ok=True)
                with open(LEDGER_FILE, "a") as f:
                    f.write(json.dumps(entry) + "\n")
            except Exception as e:
                log.error("[TRADE-COST] Failed to append ledger: %s", e)

        # SQLite mirror — never blocks, never raises out.
        try:
            await self._try_sqlite_write(entry)
        except Exception as e:
            if not self._sqlite_warned:
                self._sqlite_warned = True
                log.warning("[TRADE-COST] SQLite mirror unavailable: %s", e)

        log.debug(
            "[TRADE-COST] %s/%s/%s: $%.4f (%s)",
            broker,
            action,
            symbol or "-",
            amount_usd,
            strategy_tag or "-",
        )

    async def _try_sqlite_write(self, entry: dict) -> None:
        if not _sqlite_enabled():
            return
        if self._sqlite_store is None:
            try:
                from ..persistence import get_store  # type: ignore
            except Exception:
                return
            self._sqlite_store = await get_store()
        if self._sqlite_store is None:
            return
        # Tolerant write — if the store doesn't yet have a trade_cost_ledger
        # writer, silently skip (the schema migration is a separate task).
        writer = getattr(self._sqlite_store, "record_trade_cost", None)
        if writer is None:
            return
        try:
            await writer(entry)
        except Exception as e:
            log.warning("[TRADE-COST] SQLite write failed (non-fatal): %s", e)

    # ── Read views ────────────────────────────────────────────────────

    async def summary_today(self) -> dict:
        """Today's rollup (in-memory)."""
        await self.initialize()
        async with self._lock:
            self._check_date_rollover()
            return {
                "date": self._current_date,
                "total_usd": round(self._daily_sum_usd, 6),
                "entries": self._daily_count,
                "by_broker": dict(self._daily_totals_by_broker),
                "by_action": dict(self._daily_totals_by_action),
                "by_strategy": dict(self._daily_totals_by_strategy),
                "by_asset_class": dict(self._daily_totals_by_asset_class),
            }

    async def history(self, *, days: int = 30) -> list[dict]:
        """Rollups for the most recent N days (reads daily summary cache)."""
        await self.initialize()
        if not DAILY_SUMMARY_FILE.exists():
            return [await self.summary_today()]
        try:
            all_days = json.loads(DAILY_SUMMARY_FILE.read_text())
        except Exception:
            return [await self.summary_today()]
        if not isinstance(all_days, dict):
            return [await self.summary_today()]
        keys = sorted(all_days.keys(), reverse=True)[:days]
        return [all_days[k] for k in keys]

    async def recent_entries(self, *, limit: int = 100) -> list[dict]:
        """Last N raw entries from the JSONL (for debugging / audit)."""
        await self.initialize()
        if not LEDGER_FILE.exists():
            return []
        try:
            # Tail-read — fine for ledgers < 100MB; switch to seek-from-end
            # if the file grows beyond that.
            with open(LEDGER_FILE, "r") as f:
                lines = f.readlines()
        except Exception:
            return []
        out: list[dict] = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


# ── Singleton ───────────────────────────────────────────────────────────

_LEDGER_SINGLETON: Optional[TradeCostLedger] = None
_LEDGER_LOCK = asyncio.Lock()


async def get_trade_cost_ledger() -> TradeCostLedger:
    """Singleton accessor. Async-safe init."""
    global _LEDGER_SINGLETON
    if _LEDGER_SINGLETON is not None:
        await _LEDGER_SINGLETON.initialize()
        return _LEDGER_SINGLETON
    async with _LEDGER_LOCK:
        if _LEDGER_SINGLETON is None:
            _LEDGER_SINGLETON = TradeCostLedger()
            await _LEDGER_SINGLETON.initialize()
    return _LEDGER_SINGLETON


# Convenience function — the typical caller doesn't want the singleton,
# just to record one event.
async def record_trade_cost(
    *,
    broker: str,
    action: str,
    amount_usd: float,
    symbol: Optional[str] = None,
    asset_class: Optional[str] = None,
    account_id: Optional[str] = None,
    strategy_tag: Optional[str] = None,
    currency: str = "USD",
    fx_rate: Optional[float] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Module-level convenience — get singleton, record, return."""
    ledger = await get_trade_cost_ledger()
    await ledger.record(
        broker=broker,
        action=action,
        amount_usd=amount_usd,
        symbol=symbol,
        asset_class=asset_class,
        account_id=account_id,
        strategy_tag=strategy_tag,
        currency=currency,
        fx_rate=fx_rate,
        metadata=metadata,
    )
