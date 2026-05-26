"""
Auto-Trader observability — Wave 14K K0a

Every trade open captures a "reasoning chain" — the full audit trail of
HOW the decision was made: which idea, which signals cited, which model
emitted it, what confidence, what governor said, what policy said. When
the trade closes (potentially weeks later), the chain is what gets
attributed to win/loss for SHAP analysis in Phase 4.

Storage: data/portfolio/auto_trader/reasoning_chains.jsonl (append-only).
One row per open-time event. Idempotent on trade_idea_id — re-recording
the same id is a no-op.

Schema:
  {
    "ts": ISO,
    "trade_idea_id": str,
    "paper_trade_id": str | null,    # filled by loop after create_trade()
    "source": "brief" | "goat" | "bravo" | ...,
    "strategy": str,
    "ticker": str,
    "model_meta": {                  # who said this
        "executor_model": "claude-sonnet-4",
        "executor_thinking": bool,
        "brief_revision": int,
    },
    "idea_snapshot": {...},          # full trade_idea dict
    "governor_decision": {...},
    "policy_check": {"eligible": bool, "reason": str, "policy_rev": int},
    "confidence_pct": float | null,
    "rotation_context": {...},       # quadrant/stance/breadth at decision time
    "regime_context": {...},         # cycle_phase + style_ratios at decision time
    "effective_R_dollars": float,
    "planned_qty": float,
    "metadata": {...}
  }

This file is the JSONL for replay + SHAP. A small JSON dict
data/portfolio/auto_trader/recent_chains.json caches the last 100
chains by trade_idea_id for fast lookup from REST (no full-file scan).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.observability")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio" / "auto_trader"
CHAINS_FILE = DATA_DIR / "reasoning_chains.jsonl"
RECENT_FILE = DATA_DIR / "recent_chains.json"

RECENT_CACHE_MAX = int(os.getenv("NCL_AT_RECENT_CHAINS_MAX", "100"))


_LOCK = asyncio.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_recent() -> dict:
    if not RECENT_FILE.exists():
        return {}
    try:
        raw = json.loads(RECENT_FILE.read_text())
        if isinstance(raw, dict):
            return raw
    except Exception:
        pass
    return {}


def _persist_recent(cache: dict) -> None:
    _ensure_dir()
    # Cap at RECENT_CACHE_MAX by ts
    if len(cache) > RECENT_CACHE_MAX:
        # keep most-recent by ts
        sorted_items = sorted(
            cache.items(), key=lambda kv: kv[1].get("ts", ""), reverse=True
        )
        cache = dict(sorted_items[:RECENT_CACHE_MAX])
    tmp = RECENT_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(cache, indent=2, sort_keys=True))
        tmp.replace(RECENT_FILE)
    except Exception as e:
        log.error("[AT-OBS] recent persist failed: %s", e)


async def record_reasoning_chain(
    *,
    trade_idea_id: str,
    idea_snapshot: dict,
    governor_decision: Optional[dict] = None,
    policy_check: Optional[dict] = None,
    paper_trade_id: Optional[str] = None,
    source: str = "brief",
    strategy: Optional[str] = None,
    ticker: Optional[str] = None,
    model_meta: Optional[dict] = None,
    confidence_pct: Optional[float] = None,
    rotation_context: Optional[dict] = None,
    regime_context: Optional[dict] = None,
    effective_R_dollars: Optional[float] = None,
    planned_qty: Optional[float] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """Append a reasoning chain to the JSONL ledger. Idempotent on
    trade_idea_id — re-recording the same id returns the existing entry
    from the recent cache without appending."""
    async with _LOCK:
        recent = _load_recent()
        if trade_idea_id in recent:
            log.debug("[AT-OBS] dedup — chain for %s already recorded", trade_idea_id)
            return recent[trade_idea_id]
        entry = {
            "ts": _now_iso(),
            "trade_idea_id": trade_idea_id,
            "paper_trade_id": paper_trade_id,
            "source": source,
            "strategy": strategy or (idea_snapshot.get("strategy_tag")
                                      or idea_snapshot.get("strategy")
                                      or idea_snapshot.get("type")
                                      or "unknown"),
            "ticker": ticker or (idea_snapshot.get("ticker") or "").upper(),
            "model_meta": model_meta or {},
            "idea_snapshot": idea_snapshot,
            "governor_decision": governor_decision,
            "policy_check": policy_check,
            "confidence_pct": confidence_pct,
            "rotation_context": rotation_context or {
                "quadrant": idea_snapshot.get("rotation_quadrant"),
                "stance": idea_snapshot.get("rotation_stance"),
                "breadth_veto": idea_snapshot.get("breadth_veto"),
            },
            "regime_context": regime_context or {},
            "effective_R_dollars": effective_R_dollars,
            "planned_qty": planned_qty,
            "metadata": metadata or {},
        }
        _ensure_dir()
        try:
            with open(CHAINS_FILE, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            log.error("[AT-OBS] append failed: %s", e)
        recent[trade_idea_id] = entry
        _persist_recent(recent)
        log.info(
            "[AT-OBS] chain recorded: %s %s/%s (paper_trade_id=%s)",
            trade_idea_id, entry["strategy"], entry["ticker"], paper_trade_id,
        )
        return entry


async def update_paper_trade_id(trade_idea_id: str, paper_trade_id: str) -> bool:
    """After create_trade() returns, link the paper_trade_id back to
    the chain so outcome attribution can use either id as a key."""
    async with _LOCK:
        recent = _load_recent()
        if trade_idea_id not in recent:
            return False
        recent[trade_idea_id]["paper_trade_id"] = paper_trade_id
        _persist_recent(recent)
    # NB: the JSONL row is append-only; we don't rewrite it. Outcome
    # attribution stitches via the recent cache or by replay-scan.
    return True


async def get_reasoning_chain(trade_idea_id: str) -> Optional[dict]:
    """Fetch a chain by trade_idea_id (from the recent cache)."""
    async with _LOCK:
        recent = _load_recent()
        return recent.get(trade_idea_id)


async def list_recent_chains(limit: int = 50) -> list[dict]:
    """List most-recent chains, newest first."""
    async with _LOCK:
        recent = _load_recent()
        items = sorted(
            recent.values(),
            key=lambda c: c.get("ts", ""),
            reverse=True,
        )
        return items[:limit]
