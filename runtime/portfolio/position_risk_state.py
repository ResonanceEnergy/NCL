"""
NCL Position Risk State — Wave 14J Phase 1 (J0b)

Carries per-position R-fields (entry / stop / R_dollars / R_basis / target /
thesis / risk_status) as a separate state file. Adapters DON'T know how to
infer these from the broker feed — they're operator-set, persisted across
syncs, and merged into `get_positions()` output by PortfolioManager.

Why a separate module:
  - Adapter layer would otherwise need per-broker fill-handler extensions
    to compute stops at entry. That's a Phase 2+ project. For Phase 1 we
    just want the *storage* foundation so J1a (heat caps), J1c (stop
    enforcement), J1d (per-strategy expectancy) all have R_dollars to bind
    to.
  - Position cache (self._positions in PortfolioManager) is volatile —
    cleared on every sync. R-fields need to outlive a sync cycle.
  - Audit trail matters: every PATCH should append to a JSONL so we can
    reconstruct "what was the stop when this trade went on" later.

Position-key:
  f"{broker_lower}:{account_id_lower}:{symbol_upper}" — stable across syncs
  for the same (broker, account, symbol) tuple. Multiple lots / accounts
  for the same symbol get separate keys; same broker account aggregates.

Storage:
  - data/portfolio/position_risk_state.json   — current state per key
  - data/portfolio/position_risk_state.jsonl  — append-only audit log
    (every set/update/clear writes one entry)

risk_status values:
  unset           — no risk set yet
  at_risk         — position open, between entry and stop (worst-case loss intact)
  break_even      — stop moved to entry (free trade)
  profit          — stop above entry (locked-in profit floor)
  stopped_out     — stop triggered (historical)
  closed          — position closed (historical, R-fields archived)

stop_type values:
  price           — fixed price level
  atr             — multiple of average true range
  volatility      — explicit IV / realized-vol multiple
  time            — calendar-based exit (e.g. close in N days)
  thesis_break    — exit on thesis invalidation, no price level

R_dollars = |entry_price - stop_price| * abs(qty)  (computed at set/update time)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ncl.portfolio.position_risk_state")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
RISK_DIR = NCL_BASE / "data" / "portfolio"
RISK_FILE = RISK_DIR / "position_risk_state.json"
RISK_LOG = RISK_DIR / "position_risk_state.jsonl"

VALID_STOP_TYPES = {"price", "atr", "volatility", "time", "thesis_break"}
VALID_RISK_STATUS = {
    "unset",
    "at_risk",
    "break_even",
    "profit",
    "stopped_out",
    "closed",
}


@dataclass
class RiskState:
    """Operator-set risk fields for a single position-key.

    Fields are all optional — a brand-new position-key starts with risk_status
    'unset' and zero R_dollars. PATCH operations fill them in.
    """

    position_key: str
    broker: str
    account_id: str
    symbol: str
    qty: Optional[float] = None  # snapshotted at set-time for reference
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    stop_type: Optional[str] = None
    stop_basis: Optional[str] = None
    target_price: Optional[float] = None
    target_basis: Optional[str] = None
    thesis: Optional[str] = None
    R_dollars: Optional[float] = None
    R_basis_date: Optional[str] = None
    risk_status: str = "unset"
    last_updated: Optional[str] = None
    metadata: dict = field(default_factory=dict)


def make_position_key(broker: str, account_id: str, symbol: str) -> str:
    """Stable position-key. Empty account_id → '_' so the key is still parseable."""
    b = (broker or "_").lower()
    a = (account_id or "_").lower()
    s = (symbol or "_").upper()
    return f"{b}:{a}:{s}"


def parse_position_key(key: str) -> tuple[str, str, str]:
    """Reverse of make_position_key — returns (broker, account_id, symbol)."""
    parts = key.split(":", 2)
    while len(parts) < 3:
        parts.append("_")
    return parts[0], parts[1], parts[2]


def compute_R_dollars(entry_price: Optional[float], stop_price: Optional[float], qty: Optional[float]) -> Optional[float]:
    """|entry - stop| * |qty| — None if any input missing."""
    if entry_price is None or stop_price is None or qty is None:
        return None
    try:
        return abs(float(entry_price) - float(stop_price)) * abs(float(qty))
    except (TypeError, ValueError):
        return None


class PositionRiskStore:
    """File-backed risk-state store. JSON for current state, JSONL for audit."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._state: dict[str, RiskState] = {}
        self._initialized: bool = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            RISK_DIR.mkdir(parents=True, exist_ok=True)
            await self._load_state()
            self._initialized = True
            log.info(
                "[POS-RISK] initialized — %d position-keys with risk fields loaded",
                len(self._state),
            )

    async def _load_state(self) -> None:
        if not RISK_FILE.exists():
            return
        try:
            raw = json.loads(RISK_FILE.read_text())
            if not isinstance(raw, dict):
                return
            for key, payload in raw.items():
                try:
                    if not isinstance(payload, dict):
                        continue
                    # Drop any keys not in RiskState — be tolerant of schema drift.
                    field_names = {f for f in RiskState.__dataclass_fields__}  # type: ignore[attr-defined]
                    payload = {k: v for k, v in payload.items() if k in field_names}
                    payload.setdefault("position_key", key)
                    payload.setdefault("broker", parse_position_key(key)[0])
                    payload.setdefault("account_id", parse_position_key(key)[1])
                    payload.setdefault("symbol", parse_position_key(key)[2])
                    self._state[key] = RiskState(**payload)
                except Exception as e:
                    log.warning("[POS-RISK] skipping malformed entry for %s: %s", key, e)
        except Exception as e:
            log.warning("[POS-RISK] failed to load state: %s", e)

    async def _persist_state(self) -> None:
        """Atomic write of full state JSON. Called under the lock."""
        snapshot = {k: asdict(v) for k, v in self._state.items()}
        tmp = RISK_FILE.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(snapshot, indent=2, sort_keys=True))
            tmp.replace(RISK_FILE)
        except Exception as e:
            log.error("[POS-RISK] state persist failed: %s", e)

    def _append_audit(self, action: str, state: RiskState) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "state": asdict(state),
        }
        try:
            with open(RISK_LOG, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            log.warning("[POS-RISK] audit log append failed: %s", e)

    # ── Public API ────────────────────────────────────────────────────

    async def get(self, position_key: str) -> Optional[dict]:
        """Return RiskState as dict, or None if no R-fields set for this key."""
        await self.initialize()
        async with self._lock:
            s = self._state.get(position_key)
            return asdict(s) if s is not None else None

    async def get_many(self, keys: list[str]) -> dict[str, dict]:
        """Bulk-fetch R-fields for many keys (used by get_positions enrichment)."""
        await self.initialize()
        async with self._lock:
            return {k: asdict(s) for k, s in self._state.items() if k in keys}

    async def all_keys(self) -> list[str]:
        await self.initialize()
        async with self._lock:
            return list(self._state.keys())

    async def set(
        self,
        *,
        broker: str,
        account_id: str,
        symbol: str,
        qty: Optional[float] = None,
        entry_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        stop_type: Optional[str] = None,
        stop_basis: Optional[str] = None,
        target_price: Optional[float] = None,
        target_basis: Optional[str] = None,
        thesis: Optional[str] = None,
        risk_status: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """Set or update R-fields for a position-key. Computes R_dollars
        whenever entry_price + stop_price + qty are all available.

        Returns the resulting RiskState as a dict.

        Tolerates partial updates — pass only the fields you want to change;
        anything not supplied is preserved from the previous state."""
        await self.initialize()
        key = make_position_key(broker, account_id, symbol)
        if stop_type is not None and stop_type not in VALID_STOP_TYPES:
            raise ValueError(f"stop_type must be one of {sorted(VALID_STOP_TYPES)}; got {stop_type!r}")
        if risk_status is not None and risk_status not in VALID_RISK_STATUS:
            raise ValueError(f"risk_status must be one of {sorted(VALID_RISK_STATUS)}; got {risk_status!r}")

        async with self._lock:
            current = self._state.get(key)
            if current is None:
                current = RiskState(
                    position_key=key,
                    broker=broker.lower(),
                    account_id=(account_id or "").lower(),
                    symbol=symbol.upper(),
                )
            # Partial update — only overwrite supplied fields.
            if qty is not None:
                current.qty = float(qty)
            if entry_price is not None:
                current.entry_price = float(entry_price)
            if stop_price is not None:
                current.stop_price = float(stop_price)
            if stop_type is not None:
                current.stop_type = stop_type
            if stop_basis is not None:
                current.stop_basis = stop_basis
            if target_price is not None:
                current.target_price = float(target_price)
            if target_basis is not None:
                current.target_basis = target_basis
            if thesis is not None:
                current.thesis = thesis
            if risk_status is not None:
                current.risk_status = risk_status
            elif current.risk_status == "unset" and (current.entry_price is not None and current.stop_price is not None):
                # First time setting both → flip status to at_risk automatically
                current.risk_status = "at_risk"
            if metadata is not None:
                # Shallow-merge; passing {} clears nothing.
                merged = dict(current.metadata or {})
                merged.update(metadata)
                current.metadata = merged

            # Recompute R_dollars on every set (entry/stop/qty might have changed).
            current.R_dollars = compute_R_dollars(
                current.entry_price, current.stop_price, current.qty
            )
            if current.R_dollars is not None and current.R_basis_date is None:
                current.R_basis_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            current.last_updated = datetime.now(timezone.utc).isoformat()

            self._state[key] = current
            await self._persist_state()
            self._append_audit("set", current)
            return asdict(current)

    async def clear(self, position_key: str) -> bool:
        """Remove a key entirely (e.g. position closed and history archived)."""
        await self.initialize()
        async with self._lock:
            removed = self._state.pop(position_key, None)
            if removed is None:
                return False
            await self._persist_state()
            self._append_audit("clear", removed)
            return True

    async def mark_closed(self, position_key: str) -> Optional[dict]:
        """Set risk_status='closed' but keep the record for audit / expectancy."""
        await self.initialize()
        async with self._lock:
            s = self._state.get(position_key)
            if s is None:
                return None
            s.risk_status = "closed"
            s.last_updated = datetime.now(timezone.utc).isoformat()
            await self._persist_state()
            self._append_audit("mark_closed", s)
            return asdict(s)

    # ── Aggregations (drive J1a heat caps later) ──────────────────────

    async def aggregate(self) -> dict:
        """Portfolio-level R aggregations.

        - total_R_at_risk: sum of R_dollars across positions whose status
          is 'at_risk' (i.e. worst-case loss exposure if every stop fires).
        - by_strategy: same sum, grouped by metadata.strategy_tag.
        - by_broker / by_asset_class: similarly grouped.
        """
        await self.initialize()
        async with self._lock:
            total = 0.0
            by_strategy: dict[str, float] = {}
            by_broker: dict[str, float] = {}
            for s in self._state.values():
                if s.risk_status != "at_risk":
                    continue
                R = s.R_dollars or 0.0
                total += R
                strat = (s.metadata or {}).get("strategy_tag") or "unknown"
                by_strategy[strat] = by_strategy.get(strat, 0.0) + R
                by_broker[s.broker] = by_broker.get(s.broker, 0.0) + R
            return {
                "total_R_at_risk_usd": round(total, 6),
                "by_strategy": by_strategy,
                "by_broker": by_broker,
                "open_positions_with_risk": sum(
                    1 for s in self._state.values() if s.risk_status == "at_risk"
                ),
                "total_keys_tracked": len(self._state),
            }


# ── Singleton ───────────────────────────────────────────────────────────

_STORE_SINGLETON: Optional[PositionRiskStore] = None
_STORE_LOCK = asyncio.Lock()


async def get_risk_store() -> PositionRiskStore:
    global _STORE_SINGLETON
    if _STORE_SINGLETON is not None:
        await _STORE_SINGLETON.initialize()
        return _STORE_SINGLETON
    async with _STORE_LOCK:
        if _STORE_SINGLETON is None:
            _STORE_SINGLETON = PositionRiskStore()
            await _STORE_SINGLETON.initialize()
    return _STORE_SINGLETON


# Enrichment helper — called by PortfolioManager.get_positions to merge
# R-fields into each broker position dict without changing the adapter
# layer. Safe to call from synchronous code via asyncio.run_coroutine_threadsafe
# if needed; the simpler integration is to await it from the router.
async def enrich_positions_with_risk(positions: list[dict]) -> list[dict]:
    """Merge R-fields into a list of position dicts (as returned by
    PortfolioManager.get_positions). Non-destructive — adds these keys:

      risk_status, R_dollars, entry_price (operator-set, distinct from
      avg_cost), stop_price, stop_type, target_price, thesis,
      position_key.

    Missing R-fields → risk_status='unset', R_dollars=None.
    """
    store = await get_risk_store()
    out: list[dict] = []
    for p in positions:
        key = make_position_key(
            p.get("broker", "") or "_",
            p.get("account_id", "") or "_",
            p.get("symbol", "") or "_",
        )
        risk = await store.get(key)
        merged = dict(p)
        merged["position_key"] = key
        if risk is None:
            merged.update(
                {
                    "risk_status": "unset",
                    "R_dollars": None,
                    "operator_entry_price": None,
                    "stop_price": None,
                    "stop_type": None,
                    "target_price": None,
                    "thesis": None,
                }
            )
        else:
            merged.update(
                {
                    "risk_status": risk.get("risk_status"),
                    "R_dollars": risk.get("R_dollars"),
                    "operator_entry_price": risk.get("entry_price"),
                    "stop_price": risk.get("stop_price"),
                    "stop_type": risk.get("stop_type"),
                    "target_price": risk.get("target_price"),
                    "thesis": risk.get("thesis"),
                }
            )
        out.append(merged)
    return out
