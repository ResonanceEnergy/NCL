"""
NCL Health Roll-up
==================

Single rolled-up health snapshot for the iOS Dashboard and external
ops checks. Aggregates:

  - Scheduler tasks + stale-loop watchdog state
  - Awarebot cycle stats
  - Portfolio adapter states (IBKR / Moomoo / SnapTrade)
  - Memory store size + last consolidation
  - Cost spend (today + pct of platform cap)
  - Calendar agent last scan
  - Journal last reflection

Written to ``data/health/current.json`` every 60s by the
``ncl-health-rollup`` scheduler loop. iOS can hit
``GET /system/health/rollup`` for a single-call status.

Overall status precedence: red > yellow > green.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("ncl.health")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_get(obj: Any, *path, default=None):
    """Walk attribute/dict path safely."""
    cur = obj
    for p in path:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(p, default if p == path[-1] else None)
        else:
            cur = getattr(cur, p, default if p == path[-1] else None)
    return cur if cur is not None else default


def _scheduler_component(autonomous) -> dict:
    """Health for the scheduler itself."""
    if autonomous is None:
        return {"status": "red", "reason": "scheduler not initialized"}
    active = [t.get_name() for t in autonomous._tasks if not t.done()]
    dead = [t.get_name() for t in autonomous._tasks if t.done()]
    stale = autonomous._stats.get("stale_loops", []) or []
    status = "green"
    if dead:
        status = "red"
    elif stale:
        status = "yellow"
    return {
        "status": status,
        "active_tasks": len(active),
        "dead_tasks": dead,
        "stale_loops": [s.get("loop") for s in stale],
        "heartbeat_count": autonomous._stats.get("heartbeat_count", 0),
    }


def _awarebot_component(autonomous) -> dict:
    aw = getattr(autonomous, "awarebot", None) if autonomous else None
    if aw is None:
        return {"status": "yellow", "reason": "awarebot not initialized"}
    try:
        stats = aw.get_stats() if hasattr(aw, "get_stats") else (aw._stats or {})
    except Exception as e:
        return {"status": "red", "reason": f"awarebot.get_stats failed: {e}"}
    cycles = int(stats.get("cycles_completed", 0))
    last_scan = stats.get("last_scan_at")
    # Yellow if it's been over 30 min since last scan AND we have started.
    status = "green"
    if last_scan:
        try:
            ts = datetime.fromisoformat(str(last_scan).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            if age > 30 * 60:
                status = "yellow"
            if age > 2 * 3600:
                status = "red"
        except Exception:
            pass
    else:
        # Never scanned — yellow if just-started, otherwise treat as green
        # (warm-start is async).
        status = "yellow"
    return {
        "status": status,
        "cycles": cycles,
        "last_scan_at": last_scan,
        "last_prediction_at": stats.get("last_prediction_at"),
        "last_brief_at": stats.get("last_brief_at"),
    }


def _portfolio_component() -> dict:
    """Pull from the portfolio manager singleton without importing it at
    module load time (avoids circular imports + lets us fail soft)."""
    try:
        from ..portfolio import portfolio_routes  # noqa: WPS433
        pm = getattr(portfolio_routes, "_portfolio_manager", None)
    except Exception as e:
        return {"status": "yellow", "reason": f"portfolio import failed: {e}"}
    if pm is None:
        return {"status": "yellow", "reason": "portfolio manager not started"}
    try:
        h = pm.health()
    except Exception as e:
        return {"status": "red", "reason": f"portfolio.health() failed: {e}"}
    adapters = {
        name: ("green" if info.get("connected") else "red")
        for name, info in (h.get("adapters") or {}).items()
    }
    connected = sum(1 for v in adapters.values() if v == "green")
    total = max(len(adapters), 1)
    if connected == 0:
        status = "red"
    elif connected < total:
        status = "yellow"
    else:
        status = "green"
    return {
        "status": status,
        "adapters": adapters,
        "accounts": h.get("accounts_cached", 0),
        "positions": h.get("positions_cached", 0),
        "last_sync": h.get("last_sync"),
        "market_open": h.get("market_open", False),
    }


async def _memory_component(brain) -> dict:
    store = getattr(brain, "memory_store", None) if brain else None
    if store is None:
        return {"status": "yellow", "reason": "memory store unavailable"}
    units = None
    # Audit 2026-05-22: get_stats() IS a coroutine; the prior code closed
    # it without awaiting and fell through to attribute fallbacks that
    # don't exist on the current MemoryStore -> rollup showed units=0
    # despite 9k+ units on disk. Now properly awaited.
    try:
        if hasattr(store, "get_stats"):
            try:
                import inspect
                stats = store.get_stats()
                if inspect.iscoroutine(stats):
                    stats = await stats
                if isinstance(stats, dict):
                    units = (
                        stats.get("total_units")
                        or stats.get("count")
                        or stats.get("units")
                    )
            except Exception:
                units = None
        if units is None:
            # Last-resort: count units.jsonl line count (read-only, no lock)
            try:
                from pathlib import Path
                p = getattr(store, "data_path", None) or getattr(store, "_data_path", None)
                if p is None:
                    # Default location
                    p = Path("data/memory/units.jsonl")
                if Path(p).exists():
                    with open(p) as f:
                        units = sum(1 for line in f if line.strip())
            except Exception:
                pass
        if units is None:
            for attr in ("_units", "units", "_store", "_data"):
                val = getattr(store, attr, None)
                if val is not None:
                    try:
                        units = len(val)
                        break
                    except Exception:
                        continue
    except Exception:
        units = None
    # Don't compute heavy stats here; rollup runs every 60s.
    status = "green"
    if units is not None and units >= 9500:
        # We're approaching MAX_TOTAL_UNITS=10K — yellow flag.
        status = "yellow"
    return {
        "status": status,
        "units": units if units is not None else 0,
        "last_consolidation": None,  # filled by caller from scheduler stats
    }


async def _cost_component() -> dict:
    try:
        from ..cost_tracker import get_tracker, PLATFORM_DAILY_CAP
        tracker = await get_tracker()
        summary = await tracker.get_daily_summary()
    except Exception as e:
        return {"status": "yellow", "reason": f"cost_tracker unavailable: {e}"}
    total = float(summary.get("total_spent_usd", 0.0) or 0.0)
    cap = float(PLATFORM_DAILY_CAP or 1.0)
    pct = (total / cap * 100.0) if cap > 0 else 0.0
    blocked = [
        name for name, info in (summary.get("sources") or {}).items()
        if info.get("blocked")
    ]
    if blocked or pct >= 100:
        status = "red"
    elif pct >= 80:
        status = "yellow"
    else:
        status = "green"
    return {
        "status": status,
        "today_spent_usd": round(total, 4),
        "platform_cap_usd": cap,
        "pct_of_budget": round(pct, 1),
        "blocked_sources": blocked,
    }


def _calendar_component(autonomous) -> dict:
    if autonomous is None or getattr(autonomous, "calendar_agent", None) is None:
        return {"status": "yellow", "reason": "calendar agent not initialized"}
    last = autonomous._stats.get("last_calendar_scan")
    return {
        "status": "green",
        "last_scan": last,
    }


def _journal_component(autonomous) -> dict:
    if autonomous is None:
        return {"status": "yellow", "reason": "scheduler not initialized"}
    last = autonomous._stats.get("last_journal_reflection")
    # Journal reflection is daily; only red if 48h+ stale.
    status = "green"
    if last:
        try:
            ts = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            if age > 48 * 3600:
                status = "red"
            elif age > 26 * 3600:
                status = "yellow"
        except Exception:
            pass
    return {"status": status, "last_reflection": last}


def _rollup_overall(components: dict[str, dict]) -> str:
    statuses = {c.get("status", "yellow") for c in components.values()}
    if "red" in statuses:
        return "red"
    if "yellow" in statuses:
        return "yellow"
    return "green"


async def build_health_rollup(autonomous, brain) -> dict:
    """Build one comprehensive health snapshot.

    Args:
        autonomous: AutonomousScheduler instance (may be None)
        brain: NCLBrain instance (may be None)
    """
    components: dict[str, dict] = {}
    warnings: list[str] = []
    errors: list[str] = []

    try:
        components["scheduler"] = _scheduler_component(autonomous)
    except Exception as e:
        components["scheduler"] = {"status": "red", "reason": str(e)}
        errors.append(f"scheduler component failed: {e}")

    try:
        components["awarebot"] = _awarebot_component(autonomous)
    except Exception as e:
        components["awarebot"] = {"status": "red", "reason": str(e)}
        errors.append(f"awarebot component failed: {e}")

    try:
        components["portfolio"] = _portfolio_component()
    except Exception as e:
        components["portfolio"] = {"status": "yellow", "reason": str(e)}
        warnings.append(f"portfolio component failed: {e}")

    try:
        mem = await _memory_component(brain)
        if autonomous:
            mem["last_consolidation"] = autonomous._stats.get("last_consolidation")
        components["memory"] = mem
    except Exception as e:
        components["memory"] = {"status": "yellow", "reason": str(e)}
        warnings.append(f"memory component failed: {e}")

    try:
        components["cost"] = await _cost_component()
    except Exception as e:
        components["cost"] = {"status": "yellow", "reason": str(e)}
        warnings.append(f"cost component failed: {e}")

    try:
        components["calendar"] = _calendar_component(autonomous)
    except Exception as e:
        components["calendar"] = {"status": "yellow", "reason": str(e)}
        warnings.append(f"calendar component failed: {e}")

    try:
        components["journal"] = _journal_component(autonomous)
    except Exception as e:
        components["journal"] = {"status": "yellow", "reason": str(e)}
        warnings.append(f"journal component failed: {e}")

    # Promote component reasons into warnings/errors
    for name, comp in components.items():
        if comp.get("status") == "red" and comp.get("reason"):
            errors.append(f"{name}: {comp['reason']}")
        elif comp.get("status") == "yellow" and comp.get("reason"):
            warnings.append(f"{name}: {comp['reason']}")

    return {
        "timestamp": _now_iso(),
        "overall": _rollup_overall(components),
        "components": components,
        "warnings": warnings,
        "errors": errors,
    }


def write_rollup_atomic(rollup: dict, target_dir: Path) -> Path:
    """Write the rollup JSON to ``target_dir/current.json`` atomically.

    Uses a ``.tmp`` sibling then ``os.replace`` — readers never see a
    partial file.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    final_path = target_dir / "current.json"
    tmp_path = target_dir / "current.json.tmp"
    tmp_path.write_text(json.dumps(rollup, indent=2))
    os.replace(tmp_path, final_path)
    return final_path
