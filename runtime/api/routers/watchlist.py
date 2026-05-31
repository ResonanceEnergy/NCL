"""Wave 14DB (2026-05-31) — Watchlist tickers in Intel context.

NATRIX: "ensure the watch list is always in context in intel".

Backend persistence of the operator's curated ticker watchlist. Used by:
  - AWAREBOT compute_situational_relevance (boosts matching signals)
  - Brief INTEL lane (WATCHLIST HITS section)
  - iOS NOW/STREAM rows (yellow WATCH badge when ticker matches)

Storage: data/watchlist/tickers.json — single JSON file with
{"tickers": [...], "tradingview_url": "...", "updated_at": "..."}.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from ..deps import verify_strike_token_dep


log = logging.getLogger("ncl.api.watchlist")
router = APIRouter(tags=["watchlist"])


def _watchlist_path() -> Path:
    base = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    d = base / "data" / "watchlist"
    d.mkdir(parents=True, exist_ok=True)
    return d / "tickers.json"


def _normalize_tickers(raw: list[str]) -> list[str]:
    """Uppercase, strip, dedup while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for t in raw or []:
        if not isinstance(t, str):
            continue
        v = t.strip().upper()
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def load_watchlist() -> dict:
    """Read tickers from disk. Empty default if no file yet."""
    p = _watchlist_path()
    if not p.exists():
        return {"tickers": [], "tradingview_url": "", "updated_at": None}
    try:
        return json.loads(p.read_text())
    except Exception as e:
        log.warning("[watchlist] read failed: %s", e)
        return {"tickers": [], "tradingview_url": "", "updated_at": None}


def get_watchlist_tickers() -> list[str]:
    """Module-level helper for AWAREBOT scorer + brief prep."""
    try:
        return list(load_watchlist().get("tickers") or [])
    except Exception:
        return []


class WatchlistPayload(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    tradingview_url: Optional[str] = ""


@router.get("/watchlist/tickers")
async def watchlist_get(_: None = Depends(verify_strike_token_dep)) -> dict:
    """Return the current watchlist + TradingView URL."""
    return load_watchlist()


@router.post("/watchlist/tickers")
async def watchlist_set(
    payload: WatchlistPayload = Body(...),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Replace the watchlist with a new ticker set.

    Tickers are normalized (uppercase, dedup, strip). URL is stored as-is.
    """
    tickers = _normalize_tickers(payload.tickers)
    data = {
        "tickers": tickers,
        "tradingview_url": (payload.tradingview_url or "").strip(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _watchlist_path().write_text(json.dumps(data, indent=2))
    except Exception as e:
        log.error("[watchlist] write failed: %s", e)
        raise HTTPException(status_code=500, detail=f"write failed: {e}")
    log.info("[watchlist] updated: %d tickers", len(tickers))
    return data


__all__ = ["router", "load_watchlist", "get_watchlist_tickers"]
