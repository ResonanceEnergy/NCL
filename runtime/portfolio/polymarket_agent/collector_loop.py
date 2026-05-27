"""
Polymarket collector loop — Wave 14R R2

ncl-poly-collector scheduler task (15min market / 60min off-hours).

Pulls trending markets from Gamma API via the existing PolymarketCollector
in runtime/intelligence/collectors.py, normalizes them to plain dicts
(no PredictionMarketSignal dependency), enriches with lifecycle status,
and persists to data/intelligence/polymarket/{today}.json.

This is the file the Wave 14L polymarket_kelly scanner has been looking
for since Wave 14L M2 shipped. The cache is also read by the new
edge_engine + decision loop in this same package.

Env:
  NCL_POLY_COLLECTOR_LIMIT     (default 60 — markets per fetch)
  NCL_POLY_COLLECTOR_INTERVAL_S (default 900 = 15min market hours)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from .state import record_tick

log = logging.getLogger("ncl.portfolio.polymarket_agent.collector_loop")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
CACHE_DIR = NCL_BASE / "data" / "intelligence" / "polymarket"

LIMIT = int(os.getenv("NCL_POLY_COLLECTOR_LIMIT", "60"))
INTERVAL_S = int(os.getenv("NCL_POLY_COLLECTOR_INTERVAL_S", "900"))
OFF_HOURS_INTERVAL_S = int(os.getenv("NCL_POLY_COLLECTOR_OFF_S", "3600"))


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _is_market_hours() -> bool:
    """Naive ET trading hours check. Errs toward 'market hours' on weekdays."""
    now = datetime.now(timezone.utc)
    # UTC 13:00-21:00 covers 9-5 ET, weekdays
    return now.weekday() < 5 and 13 <= now.hour < 21


def _signal_to_dict(sig) -> dict:
    """Flatten PredictionMarketSignal into a plain dict suitable for
    JSON serialization + edge_engine consumption."""
    md = getattr(sig, "metadata", {}) or {}
    return {
        "signal_id": getattr(sig, "signal_id", None),
        "question": getattr(sig, "title", None) or md.get("question") or "",
        "slug": md.get("slug", ""),
        "yes_price": md.get("yes_price"),
        "no_price": md.get("no_price"),
        "market_volume_usd": md.get("market_volume"),
        "volume_24h_usd": md.get("volume_24h"),
        "liquidity_usd": md.get("liquidity"),
        "price_change_24h": md.get("price_change_24h"),
        "direction": md.get("direction", ""),
        "end_date_iso": md.get("end_date") or md.get("endDate"),
        "lifecycle_status": md.get("lifecycle_status", "active"),
        "tag_labels": md.get("tag_labels", []),
        "polymarket_url": md.get("url"),
        "fetched_at_iso": _now_iso(),
    }


async def _collect_once() -> dict:
    """Fetch trending markets + persist a snapshot. Returns summary."""
    from runtime.intelligence.collectors import PolymarketCollector

    started = datetime.now(timezone.utc)
    collector = PolymarketCollector()
    try:
        signals = await collector.collect_trending_markets(limit=LIMIT)
    except Exception as e:
        log.error("[POLY-COLL] gamma fetch failed: %s", e)
        return {"ok": False, "error": str(e), "count": 0}

    records = []
    for s in signals:
        try:
            records.append(_signal_to_dict(s))
        except Exception as e:
            log.debug("[POLY-COLL] skip signal %s: %s", getattr(s, "signal_id", "?"), e)

    if not records:
        return {"ok": False, "error": "no signals returned", "count": 0}

    _ensure_dir()
    cache_path = CACHE_DIR / f"{_today()}.json"

    # Merge with any earlier-today snapshots so we preserve markets that
    # may have rolled off the trending list since last fetch. Dedup by slug.
    existing: dict = {}
    if cache_path.exists():
        try:
            prior = json.loads(cache_path.read_text())
            for r in prior.get("markets", []):
                existing[r.get("slug")] = r
        except Exception:
            pass
    for r in records:
        existing[r.get("slug")] = r

    payload = {
        "date_utc": _today(),
        "fetched_at_iso": _now_iso(),
        "count": len(existing),
        "markets": list(existing.values()),
    }
    try:
        tmp = cache_path.with_suffix(".tmp")
        await asyncio.to_thread(
            tmp.write_text, json.dumps(payload, indent=2, default=str),
        )
        tmp.replace(cache_path)
    except Exception as e:
        log.error("[POLY-COLL] cache write failed: %s", e)
        return {"ok": False, "error": str(e), "count": len(records)}

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    log.info(
        "[POLY-COLL] persisted %d markets (%d new this fetch) in %.1fs → %s",
        len(existing), len(records), elapsed, cache_path.name,
    )
    await record_tick("collector")
    return {"ok": True, "count": len(existing), "new": len(records), "elapsed_s": elapsed}


async def poly_collector_loop(brain=None) -> None:
    """Scheduler entry — runs forever, registered via _task_factories.

    Light: no governor, no risk gates. Pure cache producer.
    """
    log.info("[POLY-COLL] loop starting (interval %ds market / %ds off)",
             INTERVAL_S, OFF_HOURS_INTERVAL_S)
    while True:
        try:
            await _collect_once()
        except Exception as e:
            log.error("[POLY-COLL] tick raised: %s", e, exc_info=True)
        secs = INTERVAL_S if _is_market_hours() else OFF_HOURS_INTERVAL_S
        await asyncio.sleep(secs)


async def collect_once_now() -> dict:
    """REST hook — operator-triggered single fetch."""
    return await _collect_once()


def read_today_cache() -> list[dict]:
    """Synchronous read of today's cache (or yesterday's if today is empty).
    Returns list of market dicts, possibly empty."""
    for day_offset in (0, 1):
        day = (datetime.now(timezone.utc).date()).toordinal() - day_offset
        from datetime import date as _date
        target = _date.fromordinal(day).strftime("%Y-%m-%d")
        p = CACHE_DIR / f"{target}.json"
        if p.exists():
            try:
                d = json.loads(p.read_text())
                markets = d.get("markets", [])
                if markets:
                    return markets
            except Exception:
                continue
    return []
