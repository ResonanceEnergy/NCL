"""
Auto-Trader calendar awareness — Wave 14K hardening (#1)

Reads CalendarAgent's compiled event feed + per-ticker earnings calendar
and decides whether NEW opens should be blocked because a macro or
ticker-specific event is too close. Open positions are NOT touched;
this only gates new entries.

Macro blocks (blanket — affects EVERY new open):
  - FOMC meeting/decision   — blocks opens within NCL_AT_BLOCK_FOMC_D (1d default)
  - Quad witching / OPEX    — blocks within NCL_AT_BLOCK_OPEX_D (1d default)
  - VIX expiry              — blocks within NCL_AT_BLOCK_VIX_D (0d default; risk_governor handles)
  - Futures roll            — informational (sizing modifier elsewhere)

Per-ticker blocks:
  - Earnings within NCL_AT_BLOCK_EARNINGS_D (2d default) for that ticker

Storage: data/portfolio/auto_trader/calendar_cache.json (24h TTL).

Tunables (env):
  NCL_AT_BLOCK_FOMC_D=1
  NCL_AT_BLOCK_OPEX_D=1
  NCL_AT_BLOCK_VIX_D=0
  NCL_AT_BLOCK_EARNINGS_D=2
  NCL_AT_CALENDAR_TTL_S=86400
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.calendar_gate")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio" / "auto_trader"
CACHE_FILE = DATA_DIR / "calendar_cache.json"

BLOCK_FOMC_D = int(os.getenv("NCL_AT_BLOCK_FOMC_D", "1"))
BLOCK_OPEX_D = int(os.getenv("NCL_AT_BLOCK_OPEX_D", "1"))
BLOCK_VIX_D = int(os.getenv("NCL_AT_BLOCK_VIX_D", "0"))
BLOCK_EARNINGS_D = int(os.getenv("NCL_AT_BLOCK_EARNINGS_D", "2"))
CACHE_TTL_S = int(os.getenv("NCL_AT_CALENDAR_TTL_S", "86400"))

# Categories that count as macro blanket blocks
BLOCKING_CATEGORIES = {
    "fomc": BLOCK_FOMC_D,
    "opex": BLOCK_OPEX_D,
    "quad_witching": BLOCK_OPEX_D,
    "vix_expiry": BLOCK_VIX_D,
}


_CACHE: dict = {}
_CACHE_LOCK = asyncio.Lock()
_CACHE_LOADED = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_cache_from_disk() -> None:
    global _CACHE_LOADED
    if _CACHE_LOADED:
        return
    _CACHE_LOADED = True
    if not CACHE_FILE.exists():
        return
    try:
        raw = json.loads(CACHE_FILE.read_text())
        if isinstance(raw, dict):
            _CACHE.update(raw)
    except Exception as e:
        log.warning("[CAL-GATE] cache load failed: %s", e)


def _persist_cache() -> None:
    _ensure_dir()
    tmp = CACHE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(_CACHE, indent=2, sort_keys=True))
        tmp.replace(CACHE_FILE)
    except Exception as e:
        log.error("[CAL-GATE] cache persist failed: %s", e)


def _is_cache_fresh(key: str) -> bool:
    entry = _CACHE.get(key)
    if not isinstance(entry, dict):
        return False
    ts = entry.get("cached_at_ts", 0)
    return (datetime.now(timezone.utc).timestamp() - ts) < CACHE_TTL_S


async def _fetch_macro_events(days_ahead: int = 7) -> list[dict]:
    """Read compiled calendar events directly from disk (avoids the
    HTTP self-loop). Falls back to empty list if unavailable."""
    cache_key = f"macro:{days_ahead}"
    async with _CACHE_LOCK:
        _load_cache_from_disk()
        if _is_cache_fresh(cache_key):
            return _CACHE[cache_key].get("events") or []
    try:
        from runtime.calendar.events_compiler import compile_brain_events
        today = _today()
        end = today + timedelta(days=days_ahead)
        events = await compile_brain_events(today, end) or []
    except Exception as e:
        log.warning("[CAL-GATE] compile_brain_events failed: %s", e)
        events = []
    async with _CACHE_LOCK:
        _CACHE[cache_key] = {
            "events": events,
            "cached_at_iso": _now_iso(),
            "cached_at_ts": datetime.now(timezone.utc).timestamp(),
        }
        _persist_cache()
    return events


async def _fetch_earnings_dates(ticker: str) -> Optional[list[str]]:
    """Per-ticker earnings ISO dates (next 90 days)."""
    cache_key = f"earnings:{ticker.upper()}"
    async with _CACHE_LOCK:
        _load_cache_from_disk()
        if _is_cache_fresh(cache_key):
            return _CACHE[cache_key].get("dates") or []
    dates: list[str] = []
    try:
        from runtime.stocks.enrichments import get_earnings_map
        emap = get_earnings_map(tickers=[ticker.upper()]) or {}
        raw = emap.get(ticker.upper()) or []
        for r in raw:
            d = r.get("date") if isinstance(r, dict) else r
            if d:
                dates.append(str(d)[:10])
    except Exception as e:
        log.debug("[CAL-GATE] earnings lookup failed for %s: %s", ticker, e)
    async with _CACHE_LOCK:
        _CACHE[cache_key] = {
            "dates": dates,
            "cached_at_iso": _now_iso(),
            "cached_at_ts": datetime.now(timezone.utc).timestamp(),
        }
        _persist_cache()
    return dates


def _parse_iso_date(s: str) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except (ValueError, TypeError):
        return None


async def check_calendar_block(ticker: str) -> tuple[bool, str]:
    """Returns (blocked, reason). False / "" means clear to trade.

    Order:
      1. Macro events (FOMC, OPEX, quad-witching, VIX expiry) within N
         days → blanket block, regardless of ticker
      2. Per-ticker earnings within NCL_AT_BLOCK_EARNINGS_D days → ticker
         block
    """
    today = _today()
    ticker = (ticker or "").upper()

    # Macro check
    try:
        events = await _fetch_macro_events(days_ahead=14)
    except Exception as e:
        log.warning("[CAL-GATE] macro event fetch failed: %s", e)
        events = []
    for ev in events:
        cat = (ev.get("category") or "").lower()
        if cat not in BLOCKING_CATEGORIES:
            continue
        block_days = BLOCKING_CATEGORIES[cat]
        d = _parse_iso_date(ev.get("date") or "")
        if d is None:
            continue
        delta = (d - today).days
        if 0 <= delta <= block_days:
            title = (ev.get("title") or cat.upper())[:60]
            return True, (
                f"macro event in {delta}d ({cat}): {title} "
                f"[blocking_window={block_days}d]"
            )

    # Per-ticker earnings
    if ticker and BLOCK_EARNINGS_D > 0:
        try:
            dates = await _fetch_earnings_dates(ticker)
            for ds in (dates or []):
                d = _parse_iso_date(ds)
                if d is None:
                    continue
                delta = (d - today).days
                if 0 <= delta <= BLOCK_EARNINGS_D:
                    return True, (
                        f"earnings in {delta}d for {ticker} "
                        f"[blocking_window={BLOCK_EARNINGS_D}d]"
                    )
        except Exception as e:
            log.debug("[CAL-GATE] earnings check failed for %s: %s", ticker, e)

    return False, ""


async def calendar_summary() -> dict:
    """Operator-facing snapshot for /dashboard rollup."""
    events = await _fetch_macro_events(days_ahead=14)
    today = _today()
    upcoming = []
    for ev in events:
        cat = (ev.get("category") or "").lower()
        d = _parse_iso_date(ev.get("date") or "")
        if d is None:
            continue
        delta = (d - today).days
        if 0 <= delta <= 14:
            upcoming.append({
                "date": ev.get("date"),
                "days_away": delta,
                "category": cat,
                "title": ev.get("title", ""),
                "is_blocking": (
                    cat in BLOCKING_CATEGORIES
                    and delta <= BLOCKING_CATEGORIES[cat]
                ),
            })
    upcoming.sort(key=lambda e: e["days_away"])
    return {
        "today": today.isoformat(),
        "next_14d_count": len(upcoming),
        "blocking_now": [e for e in upcoming if e["is_blocking"]],
        "upcoming": upcoming[:5],
        "thresholds": {
            "fomc_d": BLOCK_FOMC_D, "opex_d": BLOCK_OPEX_D,
            "vix_d": BLOCK_VIX_D, "earnings_d": BLOCK_EARNINGS_D,
        },
    }
