"""
Auto-Trader capability registry — Wave 14L L5

Self-awareness layer: the agent knows what data sources + tools it
depends on, tracks their availability + freshness, and flags gaps as
importance-95 MemUnits so the operator sees what's missing.

Registry seeded with the dependencies the scanners + loops actually
use:

  yfinance              — primary price + OHLCV source (free, rate-limited)
  earnings_calendar     — get_earnings_map via yfinance fallback
  rotation_snapshot     — daily data/rotation/*.json from rotation_tracker
  cycle_phase           — data/rotation/cycle-*.json
  ivr_data              — IV rank for options regime gating (often missing)
  unusual_whales        — options flow API (needs API key)
  finnhub               — economic calendar + IEX-like quotes (needs API key)
  ibkr_market_data      — IBKR scanner + options chain (needs ib_insync)
  polymarket            — REST API (free)
  coingecko             — crypto prices (free, rate-limited)
  fred                  — macro time series (needs key for some series)

Each entry tracks: file_marker (path to a sentinel file the source
writes), env_required (env vars needed), staleness_days_max, last_check_iso,
status, gap_reason.

check_capability(name) is the fast hot-path call scanners use before
attempting data lookups. Returns {available, status, last_ok_iso,
gap_reason}. Stale or unavailable → auto-emits a tool:capability_request
MemUnit (deduplicated per ET date).

Storage:
  data/portfolio/auto_trader/capability_state.json (per-capability state)

Tunables (env):
  NCL_AT_CAPABILITY_ENABLED=1
  NCL_AT_CAPABILITY_GAP_IMPORTANCE=95
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.capability_registry")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio" / "auto_trader"
STATE_FILE = DATA_DIR / "capability_state.json"

ENABLED = os.getenv("NCL_AT_CAPABILITY_ENABLED", "1") not in ("0", "false", "False")
GAP_IMPORTANCE = float(os.getenv("NCL_AT_CAPABILITY_GAP_IMPORTANCE", "95"))


@dataclass
class CapabilityCheck:
    name: str
    description: str
    # Path to a sentinel file the source writes; staleness checked here
    file_marker: Optional[str] = None
    # Env vars that must all be present for this capability to be usable
    env_required: list = field(default_factory=list)
    # If the file_marker is older than this, capability is degraded
    staleness_days_max: float = 7.0
    # Module/import probe — if set + import fails, capability is missing
    import_probe: Optional[str] = None
    # Tags for filtering (e.g. "price_data", "alt_data", "macro")
    tags: list = field(default_factory=list)
    # If True: missing/degraded just degrades upstream gracefully; no
    # capability_request MemUnit emitted. For sources where we have a
    # working fallback (e.g. Finnhub → yfinance).
    optional: bool = False


# ─────────────────────────────────────────────────────────────────────
# DEFAULT CAPABILITIES
# ─────────────────────────────────────────────────────────────────────

DEFAULT_CAPABILITIES: list[CapabilityCheck] = [
    CapabilityCheck(
        name="yfinance",
        description="Primary OHLCV + quote source",
        import_probe="yfinance",
        tags=["price_data", "free"],
    ),
    CapabilityCheck(
        name="earnings_calendar",
        description="get_earnings_map (yfinance fallback)",
        import_probe="runtime.stocks.enrichments",
        tags=["calendar", "fundamentals"],
    ),
    CapabilityCheck(
        name="rotation_snapshot",
        description="Daily SPDR sector RRG snapshot from rotation_tracker",
        file_marker="data/rotation/{today}.json",
        staleness_days_max=2.0,
        tags=["macro", "regime"],
    ),
    CapabilityCheck(
        name="cycle_phase",
        description="Business cycle phase classifier (FRED-fed)",
        file_marker="data/rotation/cycle-{today}.json",
        staleness_days_max=4.0,
        tags=["macro", "regime"],
    ),
    CapabilityCheck(
        name="ivr_data",
        description="IV rank for options vol-regime gating",
        env_required=[],  # often unavailable; scanners use as soft signal
        tags=["options", "volatility"],
    ),
    CapabilityCheck(
        name="unusual_whales",
        description="Options flow API (copy-trade signals)",
        env_required=["UNUSUAL_WHALES_API_KEY"],
        tags=["alt_data", "options_flow", "paid_api"],
    ),
    CapabilityCheck(
        name="finnhub",
        description="Economic calendar + IEX-style quotes (yfinance fallback in place)",
        env_required=["FINNHUB_API_KEY"],
        tags=["macro", "calendar", "paid_api"],
        optional=True,
    ),
    CapabilityCheck(
        name="ibkr_market_data",
        description="IBKR scanner + options chain depth",
        env_required=["IBKR_HOST", "IBKR_PORT", "IBKR_CLIENT_ID"],
        import_probe="ib_insync",
        tags=["broker", "options"],
    ),
    CapabilityCheck(
        name="polymarket",
        description="Prediction market REST API",
        import_probe="httpx",
        tags=["alt_data", "prediction"],
    ),
    CapabilityCheck(
        name="coingecko",
        description="Crypto prices (rate-limited free tier)",
        import_probe="httpx",
        tags=["crypto", "alt_data"],
    ),
    CapabilityCheck(
        name="fred",
        description="Macro time series (some series need FRED_API_KEY)",
        import_probe="httpx",
        tags=["macro", "fundamentals"],
    ),
]


_STATE: dict[str, dict] = {}
_LOCK = asyncio.Lock()
_LOADED = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_et() -> str:
    now_utc = datetime.now(timezone.utc)
    et = now_utc - timedelta(hours=4)
    return et.strftime("%Y-%m-%d")


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_state() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    if not STATE_FILE.exists():
        return
    try:
        raw = json.loads(STATE_FILE.read_text())
        if isinstance(raw, dict):
            _STATE.update(raw)
    except Exception as e:
        log.warning("[CAPABILITY] state load failed: %s", e)


def _persist_state() -> None:
    _ensure_dir()
    tmp = STATE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(_STATE, indent=2, sort_keys=True))
        tmp.replace(STATE_FILE)
    except Exception as e:
        log.error("[CAPABILITY] state persist failed: %s", e)


def _get_capability_def(name: str) -> Optional[CapabilityCheck]:
    for c in DEFAULT_CAPABILITIES:
        if c.name == name:
            return c
    return None


def _resolve_marker_path(marker: str) -> Path:
    """Expand {today} placeholder in file marker paths.

    Strategy: try today's ET date first. If the file doesn't exist,
    fall back to the most recent file in the parent directory that
    matches the pattern with {today} replaced by a YYYY-MM-DD glob.
    This handles snapshot writers that name their file based on the
    last *trading* day (which can be 1-3 days behind calendar today
    on weekends/holidays).
    """
    today = _today_et()
    expanded = marker.format(today=today)
    primary = NCL_BASE / expanded
    if primary.exists():
        return primary
    # Glob fallback — find most recent match in the parent dir
    try:
        glob_pattern = Path(marker.format(today="*")).name
        parent = (NCL_BASE / expanded).parent
        if parent.exists():
            matches = sorted(parent.glob(glob_pattern), reverse=True)
            if matches:
                return matches[0]
    except Exception:
        pass
    return primary  # report the today-path as "missing" downstream


def _probe_import(module_name: str) -> bool:
    """Return True if the module imports cleanly."""
    try:
        __import__(module_name)
        return True
    except Exception:
        return False


def _check_env(env_vars: list) -> tuple[bool, list]:
    """Return (all_present, missing_names)."""
    missing = [v for v in env_vars if not os.getenv(v)]
    return len(missing) == 0, missing


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────

async def check_capability(name: str) -> dict:
    """Hot-path: scanners + loops call this before doing data lookups.
    Returns:
      {
        available: bool,
        status: "ok" | "missing_env" | "missing_module" |
                "stale_marker" | "missing_marker" | "unknown",
        last_check_iso: str,
        gap_reason: str,           # human-readable, included in MemUnit
        missing_env: list[str],
        marker_age_days: float | None,
      }
    """
    if not ENABLED:
        return {"available": True, "status": "disabled_check",
                "gap_reason": "capability checks disabled"}

    cap = _get_capability_def(name)
    if cap is None:
        return {"available": False, "status": "unknown_capability",
                "gap_reason": f"no registry entry for '{name}'"}

    now_iso = _now_iso()
    status = "ok"
    gap_reason = ""
    available = True
    marker_age_days = None
    missing_env: list = []

    # 1. Env check
    if cap.env_required:
        env_ok, missing_env = _check_env(cap.env_required)
        if not env_ok:
            available = False
            status = "missing_env"
            gap_reason = (
                f"required env vars not set: {', '.join(missing_env)}"
            )

    # 2. Module probe
    if available and cap.import_probe:
        if not _probe_import(cap.import_probe):
            available = False
            status = "missing_module"
            gap_reason = (
                f"module '{cap.import_probe}' not importable"
            )

    # 3. File marker freshness
    if available and cap.file_marker:
        marker_path = _resolve_marker_path(cap.file_marker)
        if not marker_path.exists():
            available = False
            status = "missing_marker"
            gap_reason = f"expected marker file missing: {marker_path}"
        else:
            try:
                mtime = datetime.fromtimestamp(
                    marker_path.stat().st_mtime, tz=timezone.utc,
                )
                age = datetime.now(timezone.utc) - mtime
                marker_age_days = age.total_seconds() / 86400
                if marker_age_days > cap.staleness_days_max:
                    available = False
                    status = "stale_marker"
                    gap_reason = (
                        f"marker {marker_path.name} is "
                        f"{marker_age_days:.1f}d old (max "
                        f"{cap.staleness_days_max:.1f}d)"
                    )
            except Exception as e:
                log.debug("[CAPABILITY] marker stat failed for %s: %s", name, e)

    result = {
        "available": available, "status": status,
        "last_check_iso": now_iso,
        "gap_reason": gap_reason,
        "missing_env": missing_env,
        "marker_age_days": (
            round(marker_age_days, 2) if marker_age_days is not None else None
        ),
        "name": name,
        "tags": cap.tags,
    }

    # Persist state
    async with _LOCK:
        _load_state()
        _STATE[name] = result
        if available:
            _STATE[name]["last_ok_iso"] = now_iso
        _persist_state()

    return result


async def check_and_request(
    name: str, *, brain=None, requesting_module: str = "?",
) -> dict:
    """Combined check + auto-MemUnit on gap. Returns the same dict as
    check_capability(). Idempotent per ET date per capability per
    requesting_module."""
    result = await check_capability(name)
    if result.get("available"):
        return result
    if not ENABLED:
        return result

    # Optional capabilities (have working fallbacks) — skip the MemUnit
    # emission entirely. Caller still sees available=False so it can
    # degrade gracefully.
    cap_def = _get_capability_def(name)
    if cap_def and getattr(cap_def, "optional", False):
        return result

    # Dedup: only emit MemUnit once per ET date per (capability, module)
    dedup_key = f"req:{name}:{requesting_module}:{_today_et()}"
    async with _LOCK:
        _load_state()
        if _STATE.get(dedup_key):
            return result
        _STATE[dedup_key] = {"emitted_iso": _now_iso()}
        _persist_state()

    if brain is None:
        return result

    mem = getattr(brain, "memory_store", None)
    if mem is None or not hasattr(mem, "create_unit"):
        return result

    try:
        cap = _get_capability_def(name)
        desc = cap.description if cap else name
        content = (
            f"TOOL REQUEST: '{requesting_module}' needs capability '{name}' "
            f"({desc}) but it's unavailable. Reason: {result.get('gap_reason')}. "
            f"Either install/configure the dependency or operator review whether "
            f"the agent should attempt a workaround."
        )
        await mem.create_unit(
            content=content,
            source="tool:capability_request",
            importance=GAP_IMPORTANCE,
            tags=[
                "tool_request", "capability_gap", f"capability:{name}",
                f"requested_by:{requesting_module}",
            ] + (cap.tags if cap else []),
            memory_type="semantic",
            metadata={
                "capability": name,
                "requesting_module": requesting_module,
                "gap_reason": result.get("gap_reason"),
                "missing_env": result.get("missing_env"),
                "status": result.get("status"),
                "wave": "14L-L5",
            },
        )
        log.info(
            "[CAPABILITY] tool-request MemUnit emitted: %s needs %s (%s)",
            requesting_module, name, result.get("status"),
        )
    except Exception as e:
        log.debug("[CAPABILITY] MemUnit emit failed: %s", e)
    return result


async def list_capabilities() -> list[dict]:
    """Return all registered capabilities with current status."""
    out = []
    async with _LOCK:
        _load_state()
        for cap in DEFAULT_CAPABILITIES:
            state = _STATE.get(cap.name) or {}
            entry = asdict(cap)
            entry.update({
                "available": state.get("available"),
                "status": state.get("status"),
                "last_check_iso": state.get("last_check_iso"),
                "last_ok_iso": state.get("last_ok_iso"),
                "gap_reason": state.get("gap_reason"),
            })
            out.append(entry)
    return out


async def list_gaps() -> list[dict]:
    """Return only currently-unavailable capabilities."""
    all_caps = await list_capabilities()
    return [c for c in all_caps if c.get("available") is False]


async def refresh_all() -> dict:
    """Force a check on every registered capability. Returns summary."""
    summary = {"checked": 0, "available": 0, "unavailable": 0, "gaps": []}
    for cap in DEFAULT_CAPABILITIES:
        result = await check_capability(cap.name)
        summary["checked"] += 1
        if result.get("available"):
            summary["available"] += 1
        else:
            summary["unavailable"] += 1
            summary["gaps"].append({
                "name": cap.name,
                "status": result.get("status"),
                "gap_reason": result.get("gap_reason"),
            })
    return summary


async def capability_summary() -> dict:
    """Snapshot for dashboard rollup."""
    summary = await refresh_all()
    return {
        "enabled": ENABLED,
        "total_capabilities": summary["checked"],
        "available_count": summary["available"],
        "gap_count": summary["unavailable"],
        "gaps": summary["gaps"][:10],  # top 10
    }
