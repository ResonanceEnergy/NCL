"""
Portfolio -> Memory Bridge
==========================

Bridges live PortfolioManager state into MemoryStore + WorkingContext + the
chat-context injector. Without this, the Brain has no awareness of NATRIX's
actual money — 7 broker accounts / 22 positions sync every 5 minutes but
none of it reaches the cortex.

Architecture
------------
- ``PortfolioMemoryBridge`` owns:
  * a prior-snapshot cache in memory (latest-good summary + positions)
  * a per-bucket "last emitted" timestamp dict (snapshots: hourly during
    market hours, 6-hourly off-hours)
  * an event-diff engine (open/close/quantity change / significant moves /
    BP-risk)
  * a public ``latest_summary()`` for the chat injector (fast read, no I/O)
- All writes go through ``AsyncMemoryWriter.enqueue()`` so we never block
  the portfolio sync loop on Sonnet enrichment.
- All event memory units are tagged ``portfolio`` + event-class so the
  /portfolio/events endpoint can list them with a single search_units().

Authority
---------
Every emitted memory unit carries source ``portfolio:<event>``, classified
as ``AuthorityTier.NATRIX`` (100) by ``runtime/memory/authority.py`` — they
beat scanner noise in working-context salience and in FusedRetriever rank.

Read paths (NEVER write back to broker adapters here)
-----------------------------------------------------
Only consumes ``pm.get_summary()`` + ``pm.get_positions()``. Trading paths
are untouched.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


log = logging.getLogger("ncl.portfolio.memory_bridge")


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# How often to write the "current state" semantic snapshot to memory.
SNAPSHOT_INTERVAL_MARKET_S = 3_600  # 1 hour during market hours
SNAPSHOT_INTERVAL_OFFHOURS_S = 21_600  # 6 hours off-hours

# Significant-move thresholds (percentage)
POSITION_DAY_MOVE_PCT = 5.0
ACCOUNT_DAY_MOVE_PCT = 2.0
ACCOUNT_WEEK_MOVE_PCT = 10.0

# Buying-power risk threshold: BP < this fraction of NLV triggers an alert
BP_RISK_RATIO = 0.05

# Quantity change threshold: |new - old| / max(old, 1) > this -> averaged up/down
QTY_CHANGE_PCT = 0.05

# Importance weights (per task spec)
IMPORTANCE_SNAPSHOT = 70.0
IMPORTANCE_POSITION_OPEN = 85.0
IMPORTANCE_POSITION_CLOSE = 85.0
IMPORTANCE_SIGNIFICANT_MOVE = 80.0
IMPORTANCE_QUANTITY_CHANGE = 75.0
IMPORTANCE_ACCOUNT_WEEK = 80.0
IMPORTANCE_BP_RISK = 95.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _is_market_open() -> bool:
    """Mirror of portfolio_manager._is_market_open(). Kept local to avoid
    circular import while still being one true Sat/Sun check."""
    utc_now = _now_utc()
    month = utc_now.month
    is_dst = (
        3 < month < 11 or (month == 3 and utc_now.day >= 8) or (month == 11 and utc_now.day <= 7)
    )
    offset = timedelta(hours=-4) if is_dst else timedelta(hours=-5)
    et = utc_now + offset
    if et.weekday() >= 5:
        return False
    t = et.hour * 60 + et.minute
    return 570 <= t < 960


def _position_key(pos: dict) -> str:
    """Unique key for a position. (symbol, broker, account_id) is stable
    across syncs even when the underlying market value moves."""
    return f"{pos.get('broker', '')}::{pos.get('account_id', '')}::{pos.get('symbol', '')}"


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Defensive numeric coerce — brokers sometimes return None / 'N/A'."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt_money(value: float, currency: str = "CAD") -> str:
    """Compact money formatter for content strings."""
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1_000_000:
        return f"{sign}${v/1_000_000:.2f}M {currency}"
    if v >= 1_000:
        return f"{sign}${v/1_000:.2f}K {currency}"
    return f"{sign}${v:.2f} {currency}"


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


@dataclass
class _PrevSnapshot:
    """In-memory cache of the most-recent good summary + positions."""

    summary: dict = field(default_factory=dict)
    positions: list[dict] = field(default_factory=list)
    positions_by_key: dict[str, dict] = field(default_factory=dict)
    captured_at: Optional[datetime] = None


class PortfolioMemoryBridge:
    """Diffs portfolio sync output against the prior cycle and emits memory
    units via the async writer.

    Singleton-style — one instance per Brain process, owned by
    PortfolioManager and ticked from inside its sync() method.
    """

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self._prev = _PrevSnapshot()
        self._latest_summary: dict = {}
        self._latest_positions: list[dict] = []
        self._latest_at: Optional[datetime] = None
        self._last_snapshot_emit: float = 0.0
        self._lock = asyncio.Lock()

        # Weekly NLV cache for week-over-week account drift detection.
        # Key: account_id, Value: (nlv_value_cad, captured_at)
        self._weekly_nlv: dict[str, tuple[float, datetime]] = {}

        # Load the most-recent persisted snapshot from snapshots.jsonl as
        # the warm-start "prior" so first sync after restart still diffs
        # correctly against yesterday's close.
        self._warm_start_from_disk()

    # ------------------------------------------------------------------
    # Warm start
    # ------------------------------------------------------------------

    def _warm_start_from_disk(self) -> None:
        """Load last snapshot summary from snapshots.jsonl, if any."""
        snap_file = self.data_dir / "snapshots.jsonl"
        if not snap_file.exists():
            return
        try:
            last_line = ""
            with open(snap_file) as f:
                for line in f:
                    if line.strip():
                        last_line = line
            if last_line:
                snap = json.loads(last_line)
                # Snapshot file only has aggregates, not per-position
                # detail, so we cannot fully warm-start the per-position
                # diff — that gets seeded on the first live sync.
                self._prev.summary = {
                    "total_value": snap.get("total_value_cad", 0.0),
                    "base_currency": "CAD",
                }
                ts = snap.get("timestamp", "")
                try:
                    self._prev.captured_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    self._prev.captured_at = _now_utc()
                log.info(
                    "[BRIDGE] warm-start: prior NLV=%.2f from %s",
                    self._prev.summary.get("total_value", 0.0),
                    snap.get("date", "?"),
                )
        except Exception as exc:
            log.warning("[BRIDGE] warm-start failed: %s", exc)

    # ------------------------------------------------------------------
    # Latest summary (consumed by chat injector — fast sync read)
    # ------------------------------------------------------------------

    def latest_summary(self) -> dict:
        """Return cached latest summary. Empty dict if never synced.

        Safe for read from any thread — only the bridge writer mutates
        this in ``on_sync()`` and the dict is replaced wholesale.
        """
        return self._latest_summary

    def latest_positions(self) -> list[dict]:
        """Return cached latest positions list (sorted by market value)."""
        return self._latest_positions

    def latest_at(self) -> Optional[datetime]:
        return self._latest_at

    # ------------------------------------------------------------------
    # Main entry point — called from PortfolioManager.sync()
    # ------------------------------------------------------------------

    async def on_sync(self, summary: dict, positions: list[dict]) -> None:
        """Called by PortfolioManager after each successful sync.

        Defensive — must NEVER raise back into the sync loop.
        """
        try:
            async with self._lock:
                now = _now_utc()
                self._latest_summary = summary or {}
                self._latest_positions = positions or []
                self._latest_at = now

                # 1. Periodic snapshot write (rate-gated)
                await self._maybe_emit_snapshot(summary, positions, now)

                # 2. Event diffs against prior cycle (skip on cold start —
                #    we need a baseline to compare against first)
                if self._prev.positions_by_key:
                    await self._emit_position_events(positions)
                    await self._emit_significant_moves(summary, positions)
                    await self._emit_bp_risk(summary)
                    await self._emit_weekly_account_drift(summary)

                # 3. Roll forward the prior snapshot
                self._prev = _PrevSnapshot(
                    summary=dict(summary or {}),
                    positions=list(positions or []),
                    positions_by_key={_position_key(p): dict(p) for p in (positions or [])},
                    captured_at=now,
                )
        except Exception as exc:
            # Bridge MUST never break the sync loop.
            log.warning("[BRIDGE] on_sync failed (continuing): %s", exc)

    # ------------------------------------------------------------------
    # Async writer access (lazy + tolerant)
    # ------------------------------------------------------------------

    async def _enqueue(
        self,
        *,
        content: str,
        source: str,
        importance: float,
        memory_type: str,
        tags: list[str],
        metadata: dict,
    ) -> None:
        """Send a memory write request through the async writer queue.

        Falls back to direct memory_store.create_unit if the async writer
        singleton isn't initialized (test environments, early-boot races).
        """
        try:
            from ..memory.async_writer import WriteRequest, get_async_writer

            req = WriteRequest(
                content=content,
                source=source,
                importance=float(importance),
                memory_type=memory_type,
                tags=list(tags),
                metadata=dict(metadata),
            )
            await get_async_writer().enqueue(req)
        except RuntimeError:
            # async writer not initialised yet — try direct path
            await self._direct_create(
                content=content,
                source=source,
                importance=importance,
                memory_type=memory_type,
                tags=tags,
                metadata=metadata,
            )
        except Exception as exc:
            log.debug("[BRIDGE] enqueue failed (%s): %s", source, exc)

    async def _direct_create(
        self,
        *,
        content: str,
        source: str,
        importance: float,
        memory_type: str,
        tags: list[str],
        metadata: dict,
    ) -> bool:
        """Persist a unit directly via memory_store.create_unit.

        Returns True if the unit was created, False if the brain wasn't
        ready (lets caller fall back to enqueue).
        """
        try:
            # Re-fetch the module each call — `brain` is a module-level
            # global that gets assigned inside lifespan(), so a stale
            # `from ... import brain` would always see None.
            import runtime.api.routes as _routes  # late import

            _brain = getattr(_routes, "brain", None)
            if _brain is None or not getattr(_brain, "memory_store", None):
                return False
            # Hard timeout — the underlying create_unit acquires an
            # exclusive write lock that has historically wedged when
            # the reader counter is leaked. We must never block the
            # sync loop on it.
            unit = await asyncio.wait_for(
                _brain.memory_store.create_unit(
                    content=content,
                    source=source,
                    importance=float(importance),
                    tags=list(tags),
                    memory_type=memory_type,
                ),
                timeout=5.0,
            )
            # Attach metadata best-effort
            try:
                if isinstance(getattr(unit, "metadata", None), dict):
                    unit.metadata.update(metadata)
            except Exception:
                pass
            return unit is not None
        except Exception as exc:
            log.debug("[BRIDGE] direct create_unit failed (%s): %s", source, exc)
            return False

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    async def _maybe_emit_snapshot(
        self, summary: dict, positions: list[dict], now: datetime
    ) -> None:
        """Emit a portfolio:snapshot memory unit on a slow cadence."""
        interval = SNAPSHOT_INTERVAL_MARKET_S if _is_market_open() else SNAPSHOT_INTERVAL_OFFHOURS_S
        if self._last_snapshot_emit and (time.time() - self._last_snapshot_emit) < interval:
            return

        if not summary:
            return

        nlv = _safe_float(summary.get("total_value"))
        currency = summary.get("base_currency", "CAD")
        day_pl = _safe_float(summary.get("daily_pl"))
        day_pl_pct = _safe_float(summary.get("daily_pl_pct"))
        cash = _safe_float(summary.get("cash_total"))
        accounts = summary.get("accounts", []) or []
        account_count = len(accounts)
        positions_count = int(summary.get("positions_count", len(positions)))

        # By-broker breakdown
        by_broker_lines: list[str] = []
        for alloc in summary.get("allocation", {}).get("by_account", [])[:5]:
            label = alloc.get("label", "?")
            value = _safe_float(alloc.get("value"))
            by_broker_lines.append(f"{label} {_fmt_money(value, currency)}")

        # Top 3 positions by market value (CAD)
        top_pos_lines: list[str] = []
        nlv_for_weight = nlv if nlv > 0 else 1.0
        for pos in (positions or [])[:3]:
            sym = pos.get("symbol", "?")
            mv = _safe_float(pos.get("market_value_cad") or pos.get("market_value"))
            weight = mv / nlv_for_weight * 100.0
            top_pos_lines.append(f"{sym} {_fmt_money(mv, currency)} ({weight:.1f}%)")

        content = (
            f"[Portfolio snapshot] Total NLV: {_fmt_money(nlv, currency)}. "
            f"By broker: {', '.join(by_broker_lines) if by_broker_lines else 'n/a'}. "
            f"Top positions: {', '.join(top_pos_lines) if top_pos_lines else 'n/a'}. "
            f"Day P&L: {_fmt_money(day_pl, currency)} ({day_pl_pct:+.2f}%). "
            f"Cash: {_fmt_money(cash, currency)}. "
            f"Positions: {positions_count}, accounts: {account_count}."
        )

        # Hand the snapshot to the async writer. We tried "direct
        # create_unit" first but `memory_store.create_unit` acquires
        # an exclusive write lock that can stall on existing reader-
        # count leaks; we don't want to wedge the sync loop on it.
        snapshot_metadata = {
            "nlv": round(nlv, 2),
            "base_currency": currency,
            "day_pl": round(day_pl, 2),
            "day_pl_pct": round(day_pl_pct, 4),
            "cash_total": round(cash, 2),
            "account_count": account_count,
            "position_count": positions_count,
            "snapshot_at": now.isoformat(),
            "by_broker": [
                {"label": a.get("label"), "value": _safe_float(a.get("value"))}
                for a in summary.get("allocation", {}).get("by_account", [])
            ][:10],
        }
        await self._enqueue(
            content=content,
            source="portfolio:snapshot",
            importance=IMPORTANCE_SNAPSHOT,
            memory_type="semantic",
            tags=["portfolio", "portfolio:snapshot"],
            metadata=snapshot_metadata,
        )

        # Also inject the snapshot into working_context so it shows up at
        # the top of the daily window (NATRIX tier wins automatically;
        # this is just for guaranteed inclusion on the same sync tick).
        try:
            await self._inject_into_working_context(content)
        except Exception as exc:
            log.debug("[BRIDGE] working_context inject failed: %s", exc)

        self._last_snapshot_emit = time.time()
        log.info("[BRIDGE] portfolio:snapshot enqueued (NLV=%.2f %s)", nlv, currency)

    async def _inject_into_working_context(self, content: str) -> None:
        """Pin the freshest snapshot into the working-context window."""
        try:
            # Re-fetch each call — `_autonomous` is a module-level global
            # populated inside lifespan().
            import runtime.api.routes as _routes  # late import to dodge cycle

            _autonomous = getattr(_routes, "_autonomous", None)
        except Exception:
            return
        if _autonomous is None:
            return
        wc = getattr(_autonomous, "_working_context", None)
        if wc is None:
            return
        try:
            await wc.inject_signal(
                content=content,
                source="portfolio:snapshot",
                importance=IMPORTANCE_SNAPSHOT,
                tags=["portfolio", "portfolio:snapshot"],
            )
        except Exception as exc:
            log.debug("[BRIDGE] inject_signal failed: %s", exc)

    # ------------------------------------------------------------------
    # Position open / close / quantity change
    # ------------------------------------------------------------------

    async def _emit_position_events(self, positions: list[dict]) -> None:
        """Diff the new positions list against the prior cache and emit
        position_opened, position_closed, and quantity_change events."""
        prev_keys = set(self._prev.positions_by_key.keys())
        curr_by_key = {_position_key(p): p for p in (positions or [])}
        curr_keys = set(curr_by_key.keys())

        # Opened
        for k in curr_keys - prev_keys:
            pos = curr_by_key[k]
            await self._emit_opened(pos)

        # Closed
        for k in prev_keys - curr_keys:
            pos = self._prev.positions_by_key[k]
            await self._emit_closed(pos)

        # Quantity change (averaged up / down)
        for k in curr_keys & prev_keys:
            curr = curr_by_key[k]
            prev = self._prev.positions_by_key[k]
            curr_qty = _safe_float(curr.get("quantity"))
            prev_qty = _safe_float(prev.get("quantity"))
            if prev_qty == 0:
                continue
            change = abs(curr_qty - prev_qty) / max(abs(prev_qty), 1.0)
            if change >= QTY_CHANGE_PCT and curr_qty != prev_qty:
                await self._emit_quantity_change(prev, curr)

    async def _emit_opened(self, pos: dict) -> None:
        sym = pos.get("symbol", "?")
        qty = _safe_float(pos.get("quantity"))
        avg_cost = _safe_float(pos.get("avg_cost"))
        broker = pos.get("broker", "?")
        account_id = pos.get("account_id", "")
        mv = _safe_float(pos.get("market_value"))
        currency = pos.get("currency", "USD")
        direction = "Long" if qty >= 0 else "Short"
        content = (
            f"[Position opened] {direction} {abs(qty):g} {sym} @ ${avg_cost:.2f} "
            f"in {broker} {account_id} — market value {_fmt_money(mv, currency)}"
        )
        await self._enqueue(
            content=content,
            source="portfolio:position_opened",
            importance=IMPORTANCE_POSITION_OPEN,
            memory_type="episodic",
            tags=[
                "portfolio",
                "portfolio:position_opened",
                f"symbol:{sym}",
                f"broker:{broker.lower()}",
            ],
            metadata={
                "symbol": sym,
                "quantity": qty,
                "avg_cost": avg_cost,
                "broker": broker,
                "account_id": account_id,
                "market_value": mv,
                "currency": currency,
                "opened_at": _now_utc().isoformat(),
            },
        )

    async def _emit_closed(self, pos: dict) -> None:
        sym = pos.get("symbol", "?")
        qty = _safe_float(pos.get("quantity"))
        broker = pos.get("broker", "?")
        account_id = pos.get("account_id", "")
        avg_cost = _safe_float(pos.get("avg_cost"))
        prev_mv = _safe_float(pos.get("market_value"))
        currency = pos.get("currency", "USD")
        unrealized = _safe_float(pos.get("unrealized_pl"))
        content = (
            f"[Position closed] {abs(qty):g} {sym} in {broker} {account_id} — "
            f"last cost ${avg_cost:.2f}, last MV {_fmt_money(prev_mv, currency)}, "
            f"unrealized at close {_fmt_money(unrealized, currency)}"
        )
        await self._enqueue(
            content=content,
            source="portfolio:position_closed",
            importance=IMPORTANCE_POSITION_CLOSE,
            memory_type="episodic",
            tags=[
                "portfolio",
                "portfolio:position_closed",
                f"symbol:{sym}",
                f"broker:{broker.lower()}",
            ],
            metadata={
                "symbol": sym,
                "quantity": qty,
                "broker": broker,
                "account_id": account_id,
                "avg_cost": avg_cost,
                "last_market_value": prev_mv,
                "currency": currency,
                "unrealized_pl_at_close": unrealized,
                "closed_at": _now_utc().isoformat(),
            },
        )

    async def _emit_quantity_change(self, prev: dict, curr: dict) -> None:
        sym = curr.get("symbol", "?")
        broker = curr.get("broker", "?")
        prev_qty = _safe_float(prev.get("quantity"))
        new_qty = _safe_float(curr.get("quantity"))
        delta = new_qty - prev_qty
        action = "Averaged up" if abs(new_qty) > abs(prev_qty) else "Trimmed"
        content = (
            f"[Quantity change] {action} {sym} in {broker}: {prev_qty:g} -> {new_qty:g} "
            f"(delta {delta:+g})"
        )
        await self._enqueue(
            content=content,
            source="portfolio:quantity_change",
            importance=IMPORTANCE_QUANTITY_CHANGE,
            memory_type="episodic",
            tags=[
                "portfolio",
                "portfolio:quantity_change",
                f"symbol:{sym}",
                f"broker:{broker.lower()}",
            ],
            metadata={
                "symbol": sym,
                "broker": broker,
                "account_id": curr.get("account_id", ""),
                "prev_quantity": prev_qty,
                "new_quantity": new_qty,
                "delta": delta,
                "changed_at": _now_utc().isoformat(),
            },
        )

    # ------------------------------------------------------------------
    # Significant intraday move
    # ------------------------------------------------------------------

    async def _emit_significant_moves(self, summary: dict, positions: list[dict]) -> None:
        """Emit portfolio:significant_move when:
        - account day_pl_pct >= ACCOUNT_DAY_MOVE_PCT, OR
        - any single position day_pl_pct >= POSITION_DAY_MOVE_PCT
        """
        # Whole-portfolio move
        day_pct = _safe_float(summary.get("daily_pl_pct"))
        if abs(day_pct) >= ACCOUNT_DAY_MOVE_PCT:
            day_pl = _safe_float(summary.get("daily_pl"))
            nlv = _safe_float(summary.get("total_value"))
            currency = summary.get("base_currency", "CAD")
            direction = "up" if day_pct >= 0 else "down"
            content = (
                f"[Significant move] Portfolio {direction} {abs(day_pct):.2f}% today "
                f"({_fmt_money(day_pl, currency)}) on {_fmt_money(nlv, currency)} NLV"
            )
            await self._enqueue(
                content=content,
                source="portfolio:significant_move",
                importance=IMPORTANCE_SIGNIFICANT_MOVE,
                memory_type="episodic",
                tags=["portfolio", "portfolio:significant_move", "scope:portfolio"],
                metadata={
                    "scope": "portfolio",
                    "day_pl": day_pl,
                    "day_pl_pct": day_pct,
                    "nlv": nlv,
                    "currency": currency,
                    "observed_at": _now_utc().isoformat(),
                },
            )

        # Per-position moves
        for pos in positions or []:
            pos_pct = _safe_float(pos.get("daily_pl_pct"))
            if abs(pos_pct) < POSITION_DAY_MOVE_PCT:
                continue
            sym = pos.get("symbol", "?")
            broker = pos.get("broker", "?")
            day_pl = _safe_float(pos.get("daily_pl"))
            mv = _safe_float(pos.get("market_value"))
            currency = pos.get("currency", "USD")
            direction = "up" if pos_pct >= 0 else "down"
            content = (
                f"[Significant move] {sym} position {direction} {abs(pos_pct):.2f}% today "
                f"({_fmt_money(day_pl, currency)}) on {_fmt_money(mv, currency)} base "
                f"in {broker}"
            )
            await self._enqueue(
                content=content,
                source="portfolio:significant_move",
                importance=IMPORTANCE_SIGNIFICANT_MOVE,
                memory_type="episodic",
                tags=[
                    "portfolio",
                    "portfolio:significant_move",
                    "scope:position",
                    f"symbol:{sym}",
                    f"broker:{broker.lower()}",
                ],
                metadata={
                    "scope": "position",
                    "symbol": sym,
                    "broker": broker,
                    "account_id": pos.get("account_id", ""),
                    "day_pl": day_pl,
                    "day_pl_pct": pos_pct,
                    "market_value": mv,
                    "currency": currency,
                    "observed_at": _now_utc().isoformat(),
                },
            )

    # ------------------------------------------------------------------
    # Buying-power risk
    # ------------------------------------------------------------------

    async def _emit_bp_risk(self, summary: dict) -> None:
        """If any account's buying_power < BP_RISK_RATIO * NLV, emit alert."""
        # buying_power is exposed via /portfolio/accounts, not /summary;
        # we read it off the raw account dicts the manager holds. Fall
        # back to skipping if not present.
        nlv = _safe_float(summary.get("total_value"))
        if nlv <= 0:
            return

        # The summary dict has `accounts` with limited fields, but the
        # raw account list lives on the PortfolioManager. Use what we
        # have from `summary["accounts"]` and supplement with broker
        # fields if available.
        for acct in summary.get("accounts", []) or []:
            # `value` here is total account value, not buying power.
            # The /portfolio/accounts response carries buying_power.
            bp = _safe_float(acct.get("buying_power"))
            if bp <= 0:
                continue
            if bp < BP_RISK_RATIO * nlv:
                label = acct.get("label") or acct.get("name") or "?"
                broker = acct.get("broker", "?")
                content = (
                    f"[Buying-power risk] {broker} {label} buying power dropped to "
                    f"${bp:,.0f} ({(bp/nlv*100):.1f}% of NLV) — margin-call risk"
                )
                await self._enqueue(
                    content=content,
                    source="portfolio:buying_power_risk",
                    importance=IMPORTANCE_BP_RISK,
                    memory_type="episodic",
                    tags=["portfolio", "portfolio:buying_power_risk", f"broker:{broker.lower()}"],
                    metadata={
                        "broker": broker,
                        "account_label": label,
                        "buying_power": bp,
                        "nlv": nlv,
                        "ratio": bp / nlv if nlv else 0.0,
                        "observed_at": _now_utc().isoformat(),
                    },
                )

    # ------------------------------------------------------------------
    # Week-over-week account drift
    # ------------------------------------------------------------------

    async def _emit_weekly_account_drift(self, summary: dict) -> None:
        """Emit if any account moved >ACCOUNT_WEEK_MOVE_PCT% over the past 7 days.

        Cached in-memory only — first sample for an account just seeds the
        cache, no event fires until a true week-old baseline is on hand.
        """
        now = _now_utc()
        accts = summary.get("accounts", []) or []
        for acct in accts:
            aid = acct.get("account_id")
            if not aid:
                continue
            value = _safe_float(acct.get("value"))
            if value <= 0:
                continue

            prev = self._weekly_nlv.get(aid)
            if prev is None:
                self._weekly_nlv[aid] = (value, now)
                continue
            prev_val, prev_at = prev
            age_days = (now - prev_at).total_seconds() / 86_400
            if age_days < 6.5:
                continue
            change_pct = ((value - prev_val) / prev_val * 100) if prev_val else 0.0
            if abs(change_pct) >= ACCOUNT_WEEK_MOVE_PCT:
                label = acct.get("label") or acct.get("name") or "?"
                broker = acct.get("broker", "?")
                direction = "up" if change_pct >= 0 else "down"
                content = (
                    f"[Account drift] {broker} {label} {direction} {abs(change_pct):.2f}% "
                    f"week-over-week (${prev_val:,.0f} -> ${value:,.0f})"
                )
                await self._enqueue(
                    content=content,
                    source="portfolio:account_change",
                    importance=IMPORTANCE_ACCOUNT_WEEK,
                    memory_type="episodic",
                    tags=["portfolio", "portfolio:account_change", f"broker:{broker.lower()}"],
                    metadata={
                        "scope": "weekly",
                        "broker": broker,
                        "account_id": aid,
                        "account_label": label,
                        "prev_value": prev_val,
                        "new_value": value,
                        "change_pct": change_pct,
                        "prev_at": prev_at.isoformat(),
                        "observed_at": now.isoformat(),
                    },
                )
            # Roll the cache forward whether we emitted or not
            self._weekly_nlv[aid] = (value, now)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_bridge_singleton: Optional[PortfolioMemoryBridge] = None


def get_bridge() -> Optional[PortfolioMemoryBridge]:
    """Returns the bridge singleton or None if not initialised."""
    return _bridge_singleton


def init_bridge(data_dir: str | Path) -> PortfolioMemoryBridge:
    """Create (or reuse) the bridge singleton."""
    global _bridge_singleton
    if _bridge_singleton is None:
        _bridge_singleton = PortfolioMemoryBridge(data_dir)
    return _bridge_singleton
