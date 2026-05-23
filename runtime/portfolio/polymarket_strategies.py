"""Polymarket strategy opportunity endpoints.

Wires the PlanktonXD and WeatherBetter scorers to the Polymarket Gamma
API. These are GET-only — no real trades are executed. Designed to back
the iOS PLYMKT sub-tabs (PLANKTONXD, WEATHERBETTER).

Endpoints
---------
- ``GET /portfolio/polymarket/planktonxd/opportunities``
- ``GET /portfolio/polymarket/weatherbetter/opportunities``

The router is mounted on the main ``portfolio_router`` in
:mod:`runtime.portfolio.portfolio_routes` via ``include_router``.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Query

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    httpx = None  # type: ignore
    _HTTPX_AVAILABLE = False

from .strategies.planktonxd_scorer import score_market, classify_category
from .strategies.weatherbetter_scorer import (
    is_weather_market,
    score_weather_market,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio/polymarket", tags=["portfolio", "polymarket"])

_GAMMA_API = "https://gamma-api.polymarket.com"

# Simple in-process cache so the iOS view can hammer refresh without
# blasting the Gamma API. 60s TTL.
_MARKETS_CACHE: dict[str, Any] = {"at": 0.0, "data": []}
_CACHE_TTL_S = 60.0


def _get_strike_token() -> str:
    """Lazily resolve the strike token — reads at call time, not import."""
    try:
        from runtime.api.routes import STRIKE_TOKEN
        return STRIKE_TOKEN
    except ImportError:
        return os.getenv("STRIKE_AUTH_TOKEN", "")


def _verify_strike_token(authorization: str) -> None:
    import secrets
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.replace("Bearer ", "").strip()
    expected = _get_strike_token()
    if not expected or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Invalid strike token")


# ── Gamma API fetch ──────────────────────────────────────────────────

async def _fetch_active_markets(limit: int = 200) -> list[dict[str, Any]]:
    """Fetch active Polymarket markets via Gamma API.

    Cached for 60s in-process. Returns the raw market list straight from
    the API — callers do the parsing.

    Gamma caps each page at 100 markets, so we paginate via the ``offset``
    parameter when ``limit > 100``. Errors mid-page just stop pagination
    and return what we have so far (or last cache snapshot if empty).
    """
    import time
    now = time.time()
    if (
        now - _MARKETS_CACHE["at"] < _CACHE_TTL_S
        and _MARKETS_CACHE["data"]
        and len(_MARKETS_CACHE["data"]) >= limit
    ):
        return _MARKETS_CACHE["data"]

    if not _HTTPX_AVAILABLE:
        return []

    url = f"{_GAMMA_API}/markets"
    page_size = 100
    pages = max(1, (limit + page_size - 1) // page_size)
    collected: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for i in range(pages):
                params = {
                    "active": "true",
                    "closed": "false",
                    "limit": page_size,
                    "offset": i * page_size,
                }
                try:
                    resp = await client.get(url, params=params)
                except Exception as exc:
                    log.warning("Polymarket Gamma page %d fetch failed: %s", i, exc)
                    break
                if resp.status_code != 200:
                    log.warning("Polymarket Gamma /markets: HTTP %s (page %d)",
                                resp.status_code, i)
                    break
                body = resp.json() or []
                if not isinstance(body, list) or not body:
                    break
                collected.extend(body)
                if len(body) < page_size:
                    # Last page short → no more results
                    break
    except Exception as exc:
        log.warning("Polymarket Gamma /markets fetch failed: %s", exc)
        return _MARKETS_CACHE["data"] or []

    if not collected:
        return _MARKETS_CACHE["data"] or []
    _MARKETS_CACHE["at"] = now
    _MARKETS_CACHE["data"] = collected
    return collected


def _parse_prices(market: dict[str, Any]) -> tuple[float, float]:
    """Extract (yes_price, no_price) from a Gamma market dict.

    Gamma returns ``outcomePrices`` as a JSON-encoded list-of-strings
    OR as a real list, depending on endpoint. Handles both.
    """
    raw = market.get("outcomePrices")
    if isinstance(raw, str):
        try:
            import json
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = None
    if not isinstance(raw, list) or len(raw) < 2:
        # Fallback to bestBid/bestAsk midpoint
        try:
            bid = float(market.get("bestBid") or 0)
            ask = float(market.get("bestAsk") or 0)
            mid = (bid + ask) / 2.0 if (bid and ask) else (bid or ask)
            return float(mid or 0), float(1 - mid if mid else 0)
        except (TypeError, ValueError):
            return 0.0, 0.0
    try:
        yes = float(raw[0] or 0)
        no = float(raw[1] or 0)
        return yes, no
    except (TypeError, ValueError):
        return 0.0, 0.0


def _parse_volume(market: dict[str, Any]) -> float:
    """Pick the best-available 24h volume metric from a market dict."""
    for key in ("volume24hr", "volume24Hr", "volumeNum", "volume"):
        v = market.get(key)
        try:
            f = float(v) if v is not None else 0.0
            if f > 0:
                return f
        except (TypeError, ValueError):
            pass
    return 0.0


def _parse_liquidity(market: dict[str, Any]) -> float:
    for key in ("liquidityNum", "liquidity"):
        v = market.get(key)
        try:
            f = float(v) if v is not None else 0.0
            if f > 0:
                return f
        except (TypeError, ValueError):
            pass
    return 0.0


def _parse_tags(market: dict[str, Any]) -> list[str]:
    tags = market.get("tags") or []
    if not isinstance(tags, list):
        return []
    out: list[str] = []
    for t in tags:
        if isinstance(t, dict):
            for key in ("label", "name", "slug"):
                if key in t and t[key]:
                    out.append(str(t[key]))
                    break
        elif isinstance(t, str):
            out.append(t)
    return out


# ── Optional memory write (fire-and-forget) ──────────────────────────

async def _maybe_write_memory(
    strategy: str,
    rows: list[dict[str, Any]],
) -> None:
    """Best-effort enqueue of each opportunity into MemoryStore.

    Tagged with ``portfolio:polymarket:<strategy>`` source and a
    ``signal`` memory type. Silent no-op on any failure (writer not
    initialized, store unavailable, etc.).
    """
    if not rows:
        return
    try:
        from runtime.memory.async_writer import get_async_writer, WriteRequest
    except Exception:
        return
    try:
        writer = get_async_writer()
    except RuntimeError:
        # Writer not initialized — skip silently
        return
    for row in rows[:10]:  # cap writes per-call so we don't spam
        try:
            content = (
                f"Polymarket {strategy} opportunity: '{row.get('title', '')}' "
                f"({row.get('outcome', '')} @ {row.get('entry_price', 0):.4f}) — "
                f"edge {row.get('edge', 0):.4f}, "
                f"~{row.get('implied_payoff_multiple', 0):.0f}x payoff, "
                f"suggested ${row.get('suggested_size_usd', 0):.2f}"
            )
            req = WriteRequest(
                content=content,
                source=f"portfolio:polymarket:{strategy}",
                memory_type="signal",
                importance=65.0,
                tags=["polymarket", strategy, row.get("category", "other")],
                metadata={
                    "market_id": row.get("market_id"),
                    "slug": row.get("slug"),
                    "edge_score": row.get("edge_score"),
                    "authority_tier": "SCANNER",
                },
            )
            await writer.enqueue(req)
        except Exception as exc:
            log.debug("memory enqueue failed for %s: %s", strategy, exc)


# ── Endpoints ────────────────────────────────────────────────────────


@router.get("/planktonxd/opportunities")
async def planktonxd_opportunities(
    limit: int = Query(default=20, ge=1, le=100),
    pool_size: int = Query(default=200, ge=20, le=500,
                           description="How many active markets to pull from Gamma before scoring"),
    write_memory: bool = Query(default=True,
                               description="Fire-and-forget enqueue top opportunities into MemoryStore"),
    authorization: str = Header(default=""),
) -> dict:
    """Top deep-OTM Polymarket opportunities ranked by composite edge.

    Pulls active markets via Gamma API (cached 60s), filters to YES OR NO
    prices in [0.001, 0.03], scores each via the PlanktonXD math, and
    returns the top *limit* ranked by ``edge_score``.

    Each row carries: ``market_id``, ``slug``, ``title``, ``category``,
    ``yes_price``, ``no_price``, ``volume_24h``, ``end_date``,
    ``edge_score``, ``suggested_size_usd``, plus the rest of the
    :class:`ScoredMarket` fields.
    """
    _verify_strike_token(authorization)
    markets = await _fetch_active_markets(limit=pool_size)

    scored: list[dict[str, Any]] = []
    for m in markets:
        if not isinstance(m, dict):
            continue
        yes, no = _parse_prices(m)
        if yes <= 0 and no <= 0:
            continue
        result = score_market(
            market_id=m.get("conditionId") or m.get("id") or m.get("slug") or "",
            slug=m.get("slug") or "",
            title=m.get("question") or m.get("title") or "",
            yes_price=yes,
            no_price=no,
            volume_24h=_parse_volume(m),
            end_date=m.get("endDate") or m.get("end_date_iso") or "",
            tags=_parse_tags(m),
            liquidity=_parse_liquidity(m),
        )
        if result is None:
            continue
        scored.append(vars(result))

    scored.sort(key=lambda r: r.get("edge_score", 0.0), reverse=True)
    rows = scored[:limit]

    if write_memory:
        try:
            await _maybe_write_memory("planktonxd", rows)
        except Exception as exc:
            log.debug("planktonxd memory write skipped: %s", exc)

    return {
        "rows": rows,
        "_meta": {
            "strategy": "planktonxd",
            "wallet_emulated": "0x4ffe49ba2a4cae123536a8af4fda48faeb609f71",
            "tagline": "Deep OTM Harvester — emulating PlanktonXD",
            "filter": {
                "deep_otm_min_price": 0.001,
                "deep_otm_max_price": 0.03,
                "min_edge_deep_otm": 0.005,
                "min_edge_contrarian": 0.02,
            },
            "pool_size": pool_size,
            "scored_count": len(scored),
            "returned_count": len(rows),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "categories_seen": sorted({r.get("category", "other") for r in scored}),
        },
    }


@router.get("/weatherbetter/opportunities")
async def weatherbetter_opportunities(
    limit: int = Query(default=20, ge=1, le=100),
    pool_size: int = Query(default=2000, ge=20, le=5000,
                           description="How many active markets to pull from Gamma before filtering. "
                                       "Default is high because weather markets are a small fraction "
                                       "of Polymarket's catalog."),
    write_memory: bool = Query(default=True),
    authorization: str = Header(default=""),
) -> dict:
    """Weather-themed Polymarket opportunities.

    Filters active markets to those matching weather keywords (rain,
    snow, temperature, hurricane, etc.), scores via the WeatherBetter
    math, and returns the top *limit* ranked by liquidity × edge ×
    proximity-to-resolve.
    """
    _verify_strike_token(authorization)
    markets = await _fetch_active_markets(limit=pool_size)

    scored: list[dict[str, Any]] = []
    skipped_non_weather = 0
    for m in markets:
        if not isinstance(m, dict):
            continue
        title = m.get("question") or m.get("title") or ""
        tags = _parse_tags(m)
        if not is_weather_market(title, tags):
            skipped_non_weather += 1
            continue
        yes, no = _parse_prices(m)
        if yes <= 0 and no <= 0:
            continue
        result = score_weather_market(
            market_id=m.get("conditionId") or m.get("id") or m.get("slug") or "",
            slug=m.get("slug") or "",
            title=title,
            yes_price=yes,
            no_price=no,
            volume_24h=_parse_volume(m),
            liquidity=_parse_liquidity(m),
            end_date=m.get("endDate") or m.get("end_date_iso") or "",
            tags=tags,
        )
        if result is None:
            continue
        scored.append(vars(result))

    scored.sort(key=lambda r: r.get("edge_score", 0.0), reverse=True)
    rows = scored[:limit]

    if write_memory:
        try:
            await _maybe_write_memory("weatherbetter", rows)
        except Exception as exc:
            log.debug("weatherbetter memory write skipped: %s", exc)

    return {
        "rows": rows,
        "_meta": {
            "strategy": "weatherbetter",
            "tagline": "Weather Market Scanner — micro-bets on weather events",
            "filter": {
                "price_floor": 0.001,
                "price_ceil": 0.10,
                "min_edge": 0.005,
                "keywords": [
                    "rain", "snow", "temperature", "hurricane", "tornado",
                    "drought", "weather", "climate", "storm", "wind", "hail",
                ],
            },
            "pool_size": pool_size,
            "non_weather_skipped": skipped_non_weather,
            "scored_count": len(scored),
            "returned_count": len(rows),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "weather_events_seen": sorted({r.get("weather_event_type", "")
                                           for r in scored if r.get("weather_event_type")}),
        },
    }
