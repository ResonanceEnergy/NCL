"""
NCL Trade Idea Tracker — Wave 14J Phase 2 (J1d)

Closed-loop attribution: every trade idea emitted by the brief pipeline,
GOAT/BRAVO scanners, or paper trading carries a stable `trade_idea_id`.
This module:

  1. Persists the issuance (source, strategy, ticker, entry/stop/target,
     R_per_share, issued_at) keyed by trade_idea_id.
  2. Records outcomes (taken / not-taken / stopped_out / target_hit /
     manually_closed / expired) with realized R_multiple at close.
  3. Computes per-strategy expectancy stats: hit_rate, avg_win_R,
     avg_loss_R, profit_factor, expectancy_R, system_quality_number
     (Van Tharp's SQN), avg_holding_days.

Two-tier storage (consistent with W10/W13 SQLite double-write pattern):
  - JSONL append-only: data/portfolio/trade_ideas.jsonl
    (every issuance + outcome update writes a row; canonical state
    rebuilt by replay)
  - In-memory dict keyed by trade_idea_id, snapshotted to
    data/portfolio/trade_ideas_state.json on every mutation

Outcome states:
  emitted          - issued but not yet acted on
  taken            - operator confirmed entry
  stopped_out      - hit stop_price
  target_hit       - hit target_price
  manually_closed  - operator-initiated close (any reason)
  expired          - time-stop fired
  not_taken        - operator explicitly skipped
  superseded       - replaced by a newer idea on same ticker (regen)

R_multiple computation:
  R_multiple = (exit_price - entry_price) / R_per_share          (long)
             = (entry_price - exit_price) / R_per_share          (short)
  win  = R_multiple > 0
  loss = R_multiple < 0

The expectancy formula:
  expectancy_R = hit_rate * avg_win_R - (1 - hit_rate) * |avg_loss_R|
  profit_factor = sum_wins_R / |sum_losses_R|
  SQN = sqrt(N) * mean(R_multiples) / stdev(R_multiples)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ncl.portfolio.trade_idea_tracker")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio"
JSONL_FILE = DATA_DIR / "trade_ideas.jsonl"
STATE_FILE = DATA_DIR / "trade_ideas_state.json"

VALID_OUTCOMES = {
    "emitted", "taken", "stopped_out", "target_hit",
    "manually_closed", "expired", "not_taken", "superseded",
}


@dataclass
class TradeIdea:
    trade_idea_id: str
    source: str                  # "brief" | "goat" | "bravo" | "polymarket" | "manual" | etc.
    strategy: str                # normalized strategy bucket (matches risk_governor)
    ticker: str
    direction: Optional[str] = None  # "long" | "short" | None
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    R_per_share: Optional[float] = None
    planned_qty: Optional[float] = None
    stop_type: Optional[str] = None
    stop_basis: Optional[str] = None
    target_basis: Optional[str] = None
    thesis: Optional[str] = None
    issued_at_iso: Optional[str] = None
    # Outcome attribution
    outcome: str = "emitted"
    closed_at_iso: Optional[str] = None
    exit_price: Optional[float] = None
    R_multiple: Optional[float] = None
    holding_days: Optional[float] = None
    notes: str = ""
    # Wave 14CR — promote sources to a top-level field so policy.py
    # can read `idea.get("sources")` without metadata-key spelunking.
    # Resolves audit B4.2 "no source citations" false rejects (20% of
    # the auto-trader's 106 historical rejects were this single bug).
    sources: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_R_multiple(idea: TradeIdea, exit_price: float) -> Optional[float]:
    if idea.entry_price is None or idea.R_per_share is None or idea.R_per_share <= 0:
        return None
    direction = (idea.direction or "long").lower()
    if direction == "short":
        return (idea.entry_price - exit_price) / idea.R_per_share
    return (exit_price - idea.entry_price) / idea.R_per_share


def _compute_holding_days(idea: TradeIdea, closed_at_iso: str) -> Optional[float]:
    if not idea.issued_at_iso:
        return None
    try:
        a = datetime.fromisoformat(idea.issued_at_iso.replace("Z", "+00:00"))
        b = datetime.fromisoformat(closed_at_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((b - a).total_seconds() / 86400.0, 3)


class TradeIdeaTracker:
    """Persistent store + per-strategy expectancy computation."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._ideas: dict[str, TradeIdea] = {}
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            await self._load_state()
            self._initialized = True
            log.info(
                "[TRADE-IDEAS] tracker initialized — %d ideas loaded (%d open)",
                len(self._ideas),
                sum(1 for i in self._ideas.values() if i.outcome in ("emitted", "taken")),
            )

    async def _load_state(self) -> None:
        if not STATE_FILE.exists():
            return
        try:
            raw = json.loads(STATE_FILE.read_text())
            if not isinstance(raw, dict):
                return
            field_names = {f for f in TradeIdea.__dataclass_fields__}  # type: ignore[attr-defined]
            for tid, payload in raw.items():
                if not isinstance(payload, dict):
                    continue
                kept = {k: v for k, v in payload.items() if k in field_names}
                kept.setdefault("trade_idea_id", tid)
                try:
                    self._ideas[tid] = TradeIdea(**kept)
                except Exception as e:
                    log.warning("[TRADE-IDEAS] skipping malformed %s: %s", tid, e)
        except Exception as e:
            log.warning("[TRADE-IDEAS] state load failed: %s", e)

    async def _persist_state(self) -> None:
        snapshot = {tid: asdict(i) for tid, i in self._ideas.items()}
        tmp = STATE_FILE.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(snapshot, indent=2, sort_keys=True))
            tmp.replace(STATE_FILE)
        except Exception as e:
            log.error("[TRADE-IDEAS] state persist failed: %s", e)

    def _append_jsonl(self, action: str, idea: TradeIdea) -> None:
        row = {
            "ts": _now_iso(),
            "action": action,
            "idea": asdict(idea),
        }
        try:
            with open(JSONL_FILE, "a") as f:
                f.write(json.dumps(row) + "\n")
        except Exception as e:
            log.warning("[TRADE-IDEAS] jsonl append failed: %s", e)

    # ── Public API ───────────────────────────────────────────────────

    async def record_emission(
        self,
        *,
        source: str,
        strategy: str,
        ticker: str,
        direction: Optional[str] = None,
        entry_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        target_price: Optional[float] = None,
        R_per_share: Optional[float] = None,
        planned_qty: Optional[float] = None,
        stop_type: Optional[str] = None,
        stop_basis: Optional[str] = None,
        target_basis: Optional[str] = None,
        thesis: Optional[str] = None,
        trade_idea_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        sources: Optional[list] = None,
    ) -> dict:
        """Record a new trade idea. Returns the persisted dict.

        Wave 14CR: `sources` is now a first-class kwarg AND a top-level
        TradeIdea field. Callers can pass it directly OR nest it under
        metadata["sources"] (back-compat); both get promoted.
        """
        await self.initialize()
        tid = trade_idea_id or uuid.uuid4().hex[:16]
        # Promote metadata["sources"] to top-level so legacy callers
        # don't suddenly start hitting the no-citation policy gate.
        meta = dict(metadata or {})
        sources_final = list(sources or [])
        if not sources_final:
            nested = meta.get("sources")
            if isinstance(nested, list) and nested:
                sources_final = list(nested)
        async with self._lock:
            if tid in self._ideas:
                # Idempotent — return existing without overwriting
                return asdict(self._ideas[tid])
            idea = TradeIdea(
                trade_idea_id=tid,
                source=source,
                strategy=strategy,
                ticker=ticker.upper(),
                direction=direction,
                entry_price=entry_price,
                stop_price=stop_price,
                target_price=target_price,
                R_per_share=R_per_share,
                planned_qty=planned_qty,
                stop_type=stop_type,
                stop_basis=stop_basis,
                target_basis=target_basis,
                thesis=thesis,
                issued_at_iso=_now_iso(),
                outcome="emitted",
                sources=sources_final,
                metadata=meta,
            )
            self._ideas[tid] = idea
            await self._persist_state()
            self._append_jsonl("emitted", idea)
            return asdict(idea)

    async def update_outcome(
        self,
        trade_idea_id: str,
        *,
        outcome: str,
        exit_price: Optional[float] = None,
        notes: str = "",
    ) -> Optional[dict]:
        if outcome not in VALID_OUTCOMES:
            raise ValueError(f"outcome must be one of {sorted(VALID_OUTCOMES)}; got {outcome!r}")
        await self.initialize()
        async with self._lock:
            idea = self._ideas.get(trade_idea_id)
            if idea is None:
                return None
            idea.outcome = outcome
            idea.closed_at_iso = _now_iso()
            if notes:
                idea.notes = (idea.notes + " | " + notes).strip(" |") if idea.notes else notes
            if exit_price is not None:
                idea.exit_price = float(exit_price)
                idea.R_multiple = _compute_R_multiple(idea, float(exit_price))
            idea.holding_days = _compute_holding_days(idea, idea.closed_at_iso)
            await self._persist_state()
            self._append_jsonl(f"outcome:{outcome}", idea)
            return asdict(idea)

    async def get(self, trade_idea_id: str) -> Optional[dict]:
        await self.initialize()
        async with self._lock:
            idea = self._ideas.get(trade_idea_id)
            return asdict(idea) if idea else None

    async def list_by_strategy(self, strategy: Optional[str] = None) -> list[dict]:
        await self.initialize()
        async with self._lock:
            ideas = list(self._ideas.values())
        if strategy:
            ideas = [i for i in ideas if i.strategy == strategy]
        return sorted([asdict(i) for i in ideas],
                      key=lambda x: x.get("issued_at_iso") or "",
                      reverse=True)

    async def expectancy_by_strategy(self) -> dict:
        """Compute per-strategy expectancy stats.

        Returns:
          {
            <strategy>: {
              n_emitted, n_closed, n_winners, n_losers,
              hit_rate, avg_win_R, avg_loss_R, profit_factor,
              expectancy_R, sqn, avg_holding_days,
              total_R_realized,
            },
            "_all": same shape across all strategies
          }
        """
        await self.initialize()
        async with self._lock:
            all_ideas = list(self._ideas.values())

        by_strategy: dict[str, list[TradeIdea]] = {}
        for i in all_ideas:
            by_strategy.setdefault(i.strategy or "unknown", []).append(i)

        def _stats(group: list[TradeIdea]) -> dict:
            n_emitted = len(group)
            closed = [
                i for i in group
                if i.outcome in ("stopped_out", "target_hit", "manually_closed", "expired")
                and i.R_multiple is not None
            ]
            n_closed = len(closed)
            winners = [i for i in closed if (i.R_multiple or 0) > 0]
            losers = [i for i in closed if (i.R_multiple or 0) <= 0]
            n_winners = len(winners)
            n_losers = len(losers)
            hit_rate = n_winners / n_closed if n_closed else 0.0
            avg_win_R = sum(i.R_multiple for i in winners) / n_winners if n_winners else 0.0
            avg_loss_R = sum(i.R_multiple for i in losers) / n_losers if n_losers else 0.0
            sum_wins = sum(i.R_multiple for i in winners)
            sum_losses = sum(i.R_multiple for i in losers)
            profit_factor = (sum_wins / abs(sum_losses)) if sum_losses else (float("inf") if sum_wins > 0 else 0.0)
            expectancy_R = hit_rate * avg_win_R - (1 - hit_rate) * abs(avg_loss_R)
            # SQN — Van Tharp: sqrt(N) * mean / stdev
            sqn = 0.0
            if n_closed >= 2:
                rs = [i.R_multiple for i in closed]
                mean = sum(rs) / n_closed
                var = sum((r - mean) ** 2 for r in rs) / (n_closed - 1)
                std = math.sqrt(var) if var > 0 else 0.0
                if std > 0:
                    sqn = math.sqrt(n_closed) * mean / std
            holding = [i.holding_days for i in closed if i.holding_days is not None]
            avg_holding_days = sum(holding) / len(holding) if holding else 0.0
            total_R_realized = sum(i.R_multiple or 0 for i in closed)
            return {
                "n_emitted": n_emitted,
                "n_closed": n_closed,
                "n_winners": n_winners,
                "n_losers": n_losers,
                "hit_rate": round(hit_rate, 4),
                "avg_win_R": round(avg_win_R, 4),
                "avg_loss_R": round(avg_loss_R, 4),
                "profit_factor": (
                    round(profit_factor, 4)
                    if math.isfinite(profit_factor)
                    else None
                ),
                "expectancy_R": round(expectancy_R, 4),
                "sqn": round(sqn, 4),
                "avg_holding_days": round(avg_holding_days, 2),
                "total_R_realized": round(total_R_realized, 4),
            }

        out = {strat: _stats(group) for strat, group in by_strategy.items()}
        out["_all"] = _stats(all_ideas)
        return out


# ── Singleton ───────────────────────────────────────────────────────────

_TRACKER: Optional[TradeIdeaTracker] = None
_TRACKER_LOCK = asyncio.Lock()


async def get_trade_idea_tracker() -> TradeIdeaTracker:
    global _TRACKER
    if _TRACKER is not None:
        await _TRACKER.initialize()
        return _TRACKER
    async with _TRACKER_LOCK:
        if _TRACKER is None:
            _TRACKER = TradeIdeaTracker()
            await _TRACKER.initialize()
    return _TRACKER


# Convenience helper for hot paths (brief pipeline, scanners)
async def record_trade_idea_emission(
    *,
    source: str,
    strategy: str,
    ticker: str,
    direction: Optional[str] = None,
    entry_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    target_price: Optional[float] = None,
    R_per_share: Optional[float] = None,
    planned_qty: Optional[float] = None,
    stop_type: Optional[str] = None,
    stop_basis: Optional[str] = None,
    target_basis: Optional[str] = None,
    thesis: Optional[str] = None,
    trade_idea_id: Optional[str] = None,
    metadata: Optional[dict] = None,
    sources: Optional[list] = None,
) -> dict:
    """Wave 14CR — `sources` kwarg added so brief callers can populate
    the new TradeIdea.sources top-level field directly."""
    tracker = await get_trade_idea_tracker()
    return await tracker.record_emission(
        source=source,
        strategy=strategy,
        ticker=ticker,
        direction=direction,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        R_per_share=R_per_share,
        planned_qty=planned_qty,
        stop_type=stop_type,
        stop_basis=stop_basis,
        target_basis=target_basis,
        thesis=thesis,
        trade_idea_id=trade_idea_id,
        metadata=metadata,
        sources=sources,
    )
