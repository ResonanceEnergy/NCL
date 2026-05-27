"""
Auto-Trader working-context awareness — Wave 14K hardening (#3)

Reads data/working_context/today.json once per tick (cached 5min) and
exposes two checks the loop can apply to each trade idea:

  1. NATRIX-tier mandate violation — if a pinned NATRIX-tier item
     contradicts the trade direction or ticker, block. Right now this
     looks for "ban" / "avoid" / "no trades on" patterns in pinned-item
     content + extracts ticker mentions from the mandate body.

  2. Ticker alignment boost — if a working-context item explicitly
     mentions the trade-idea ticker with a positive sentiment ("watch",
     "load up", "long", "buy"), flag the idea as aligned so the executor
     reasoning chain records the working-context alignment.

The check is non-blocking on failure — if working_context isn't loaded
yet (e.g., before 6am first assembly), the loop proceeds without it.

Tunables (env):
  NCL_AT_WC_CACHE_TTL_S=300       (re-read disk every 5 min)
  NCL_AT_WC_MIN_AUTHORITY=80      (only NATRIX/COUNCIL-tier items gate)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.working_context_gate")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
WC_FILE = NCL_BASE / "data" / "working_context" / "today.json"

CACHE_TTL_S = int(os.getenv("NCL_AT_WC_CACHE_TTL_S", "300"))
MIN_AUTHORITY = float(os.getenv("NCL_AT_WC_MIN_AUTHORITY", "80"))

# Phrases that, when found in a NATRIX-tier item alongside a ticker,
# mark that ticker as off-limits.
BLOCK_PATTERNS = [
    r"\bdo not (?:trade|open|buy|sell|touch)\b",
    r"\bavoid\b",
    r"\bban(?:ned)?\b",
    r"\bno (?:new )?(?:trades?|positions?) (?:on|in)\b",
    r"\bskip\b",
    r"\bblocked?\b",
    r"\bdo not enter\b",
]
# Phrases that flag positive alignment for a ticker in a pinned item.
ALIGN_PATTERNS = [
    r"\bwatch(?:ing)?\b",
    r"\bload(?:ing)? (?:up|in)?\b",
    r"\blong\b",
    r"\bbuy(?:ing)?\b",
    r"\bbullish\b",
    r"\bconviction\b",
]

_TICKER_RE = re.compile(r"\b\$?([A-Z]{1,5})\b")
_CACHE: dict = {"loaded_at_ts": 0.0, "items": []}
_LOCK = asyncio.Lock()


def _extract_tickers(text: str) -> set[str]:
    """Cheap ticker extractor. Filters obvious noise (common English
    words that happen to be uppercase)."""
    if not text:
        return set()
    NOISE = {
        "A", "I", "AN", "AT", "BE", "BY", "DO", "GO", "IF", "IN", "IS",
        "IT", "MY", "NO", "OF", "ON", "OR", "SO", "TO", "UP", "US", "WE",
        "AM", "PM", "ET", "PT", "UTC", "CEO", "CFO", "AI", "IPO", "USD",
        "CAD", "EUR", "JPY", "GBP", "ETF", "OK", "API", "REST", "JSON",
        "URL", "USA", "UK", "EU", "GDP", "CPI", "PPI", "FOMC", "OPEX",
        "VIX", "BLS", "BEA", "FED", "ECB", "BOJ", "SEC", "NYSE", "NASD",
        "NEW", "FOR", "AND", "BUT", "NOT", "ALL", "THE", "MAX", "MIN",
        "NCL", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
        "JAN", "FEB", "MAR", "APR",
    }
    out = set()
    for m in _TICKER_RE.finditer(text):
        sym = m.group(1)
        if 2 <= len(sym) <= 5 and sym not in NOISE:
            out.add(sym)
    return out


async def _load_context_cached() -> list[dict]:
    """Re-read today.json every CACHE_TTL_S seconds, otherwise serve
    cached items."""
    async with _LOCK:
        now_ts = datetime.now(timezone.utc).timestamp()
        if (now_ts - _CACHE.get("loaded_at_ts", 0)) < CACHE_TTL_S:
            return _CACHE.get("items") or []
        if not WC_FILE.exists():
            return []
        try:
            raw = json.loads(WC_FILE.read_text())
            items = raw.get("items") if isinstance(raw, dict) else None
            if not isinstance(items, list):
                return []
        except Exception as e:
            log.warning("[WC-GATE] read failed: %s", e)
            return []
        _CACHE["loaded_at_ts"] = now_ts
        _CACHE["items"] = items
        return items


async def check_working_context(ticker: str) -> dict:
    """Returns a dict:
      {
        blocked: bool,
        block_reason: str,
        aligned_with: list[str]    # source names of pinned items mentioning ticker positively
        contradicted_by: list[str] # source names blocking this ticker
      }
    Non-blocking on disk read failure.
    """
    ticker = (ticker or "").upper()
    out = {"blocked": False, "block_reason": "",
           "aligned_with": [], "contradicted_by": []}
    if not ticker:
        return out
    items = await _load_context_cached()
    if not items:
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        # Authority weighting
        imp = float(it.get("importance") or 0)
        if imp < MIN_AUTHORITY:
            continue
        content = (it.get("content") or "").strip()
        if not content:
            continue
        source = it.get("source") or "(unknown)"
        mentioned = _extract_tickers(content)
        if ticker not in mentioned:
            continue
        body_low = content.lower()
        # Block check
        if any(re.search(p, body_low) for p in BLOCK_PATTERNS):
            out["blocked"] = True
            out["contradicted_by"].append(source)
            out["block_reason"] = (
                f"NATRIX-tier item '{source}' (importance={imp:.0f}) "
                f"blocks {ticker}: {content[:120]}"
            )
        # Align check
        elif any(re.search(p, body_low) for p in ALIGN_PATTERNS):
            out["aligned_with"].append(source)
    return out


async def working_context_summary() -> dict:
    """Snapshot for /dashboard rollup."""
    items = await _load_context_cached()
    natrix_tier_count = sum(
        1 for i in items if isinstance(i, dict) and (i.get("importance") or 0) >= MIN_AUTHORITY
    )
    natrix_tier_sources = sorted({
        (i.get("source") or "?")
        for i in items
        if isinstance(i, dict) and (i.get("importance") or 0) >= MIN_AUTHORITY
    })
    return {
        "loaded": bool(items),
        "total_items": len(items),
        "high_authority_items": natrix_tier_count,
        "high_authority_sources": natrix_tier_sources[:10],
        "min_authority_threshold": MIN_AUTHORITY,
        "cache_ttl_s": CACHE_TTL_S,
    }
