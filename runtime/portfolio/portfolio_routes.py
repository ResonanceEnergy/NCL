"""
Portfolio API routes for NCL Brain.

Provides endpoints for portfolio summary, positions, accounts,
performance history, and manual sync triggers.
"""

import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

log = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

# Module-level reference — injected by Brain startup via set_portfolio_manager()
_portfolio_manager = None


def set_portfolio_manager(pm) -> None:
    """Called by Brain startup to inject the PortfolioManager singleton."""
    global _portfolio_manager
    _portfolio_manager = pm


def _get_strike_token() -> str:
    """Lazily resolve the strike token — reads at call time, not import time."""
    try:
        from runtime.api.routes import STRIKE_TOKEN
        return STRIKE_TOKEN
    except ImportError:
        return os.getenv("STRIKE_AUTH_TOKEN", "")


def _verify_strike_token(authorization: str):
    """Verify the strike point auth token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.replace("Bearer ", "").strip()
    strike_token = _get_strike_token()
    if not strike_token or not secrets.compare_digest(token, strike_token):
        raise HTTPException(status_code=403, detail="Invalid strike token")


def _require_manager():
    """Return the portfolio manager or raise 503 if not initialized."""
    if _portfolio_manager is None:
        raise HTTPException(
            status_code=503,
            detail="Portfolio manager not initialized",
        )
    return _portfolio_manager


# ─────────────────────────────────────────────────────────────────────────────
# GET /portfolio/summary
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/summary")
async def portfolio_summary(
    base_currency: str = Query(default="CAD"),
    authorization: str = Header(default=""),
) -> dict:
    """
    Aggregated portfolio snapshot across all brokerage accounts.

    Returns total value, daily/total P&L, cash totals, allocation
    breakdown, FX rate, sync timestamp, and market-open flag.
    """
    _verify_strike_token(authorization)
    pm = _require_manager()

    try:
        summary = pm.get_summary(base_currency=base_currency)
        return {
            "total_value": summary.get("total_value", 0),
            "base_currency": summary.get("base_currency", base_currency),
            "daily_pl": summary.get("daily_pl", 0),
            "daily_pl_pct": summary.get("daily_pl_pct", 0),
            "total_pl": summary.get("total_pl", 0),
            "total_pl_pct": summary.get("total_pl_pct", 0),
            "cash_total": summary.get("cash_total", 0),
            "positions_count": summary.get("positions_count", 0),
            "accounts": summary.get("accounts", []),
            "allocation": summary.get("allocation", {}),
            "fx_rate_usd_cad": summary.get("fx_rate_usd_cad", 1.0),
            "last_sync": summary.get("last_sync"),
            "market_open": summary.get("market_open", False),
            "brokers_connected": summary.get("brokers_connected", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Portfolio summary failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Portfolio summary error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# GET /portfolio/positions
# ─────────────────────────────────────────────────────────────────────────────

VALID_ACCOUNTS = {"all", "IBKR", "MOOMOO", "WEALTHSIMPLE"}


@router.get("/positions")
async def portfolio_positions(
    account: str = Query(default="all"),
    authorization: str = Header(default=""),
) -> dict:
    """
    List positions, optionally filtered by brokerage account.
    """
    _verify_strike_token(authorization)
    pm = _require_manager()

    if account not in VALID_ACCOUNTS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid account filter '{account}'. Must be one of: {', '.join(sorted(VALID_ACCOUNTS))}",
        )

    try:
        positions = pm.get_positions(account_filter=account)
        return {
            "positions": positions,
            "total_positions": len(positions),
            "last_sync": pm._last_sync,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Portfolio positions failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Portfolio positions error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# GET /portfolio/accounts
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/accounts")
async def portfolio_accounts(
    authorization: str = Header(default=""),
) -> dict:
    """
    List all connected brokerage accounts with metadata.
    """
    _verify_strike_token(authorization)
    pm = _require_manager()

    try:
        accounts = pm.get_accounts()
        return {"accounts": accounts}
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Portfolio accounts failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Portfolio accounts error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# GET /portfolio/performance
# ─────────────────────────────────────────────────────────────────────────────

VALID_RANGES = {"1D", "1W", "1M", "3M", "YTD", "1Y", "ALL"}


@router.get("/performance")
async def portfolio_performance(
    range: str = Query(default="1M", alias="range"),
    authorization: str = Header(default=""),
) -> dict:
    """
    Historical performance data for charting.

    Returns data points, start/end values, and absolute/percentage change
    over the requested time range.
    """
    _verify_strike_token(authorization)
    pm = _require_manager()

    if range not in VALID_RANGES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid range '{range}'. Must be one of: {', '.join(sorted(VALID_RANGES))}",
        )

    try:
        perf = pm.get_performance(range=range)
        return {
            "range": range,
            "data_points": perf.get("data_points", []),
            "start_value": perf.get("start_value", 0),
            "end_value": perf.get("end_value", 0),
            "change": perf.get("change", 0),
            "change_pct": perf.get("change_pct", 0),
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Portfolio performance failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Portfolio performance error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# GET /portfolio/health
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/health")
async def portfolio_health(
    authorization: str = Header(default=""),
) -> dict:
    """
    Portfolio system health — adapter connection status, cache info, FX rate.
    """
    _verify_strike_token(authorization)
    pm = _require_manager()
    return pm.health()


# ─────────────────────────────────────────────────────────────────────────────
# POST /portfolio/sync
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/sync")
async def portfolio_sync(
    authorization: str = Header(default=""),
) -> dict:
    """
    Trigger an immediate sync of all brokerage accounts.
    """
    _verify_strike_token(authorization)
    pm = _require_manager()

    try:
        await pm.sync()
        return {
            "status": "ok",
            "accounts_synced": len(pm._accounts),
            "positions_count": len(pm._positions),
            "last_sync": pm._last_sync,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Portfolio sync failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Portfolio sync error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# GET /portfolio/events
# ─────────────────────────────────────────────────────────────────────────────

def _serialize_portfolio_unit(u) -> dict:
    """Render a MemUnit as a compact JSON payload for the events endpoints."""
    try:
        created = u.created_at.isoformat() if hasattr(u.created_at, "isoformat") else str(u.created_at)
    except Exception:
        created = ""
    meta = getattr(u, "metadata", None) or {}
    return {
        "unit_id": u.unit_id,
        "source": u.source,
        "content": u.content,
        "importance": u.importance,
        "tags": u.tags,
        "memory_type": getattr(u, "memory_type", "episodic"),
        "memory_tier": getattr(u, "memory_tier", "SML"),
        "authority_tier": meta.get("authority_tier"),
        "created_at": created,
        "metadata": {k: v for k, v in meta.items() if k != "authority_tier"},
    }


@router.get("/events")
async def portfolio_events(
    limit: int = Query(default=20, ge=1, le=200),
    source: Optional[str] = Query(default=None, description="Filter by portfolio:* source (snapshot, position_opened, etc.)"),
    authorization: str = Header(default=""),
) -> dict:
    """
    Recent portfolio:* memory units, newest first.

    Each unit is one event written by the portfolio memory bridge —
    snapshots, position open/close, significant moves, account drift,
    buying-power risk, quantity changes.
    """
    _verify_strike_token(authorization)

    try:
        # Re-fetch module each call to dodge stale-global capture.
        import runtime.api.routes as _routes
        _brain = getattr(_routes, "brain", None)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Brain unavailable: {exc}")

    if _brain is None or not getattr(_brain, "memory_store", None):
        raise HTTPException(status_code=503, detail="Memory store not initialised")

    try:
        units = await _brain.memory_store.search_units(
            tags=["portfolio"],
            importance_threshold=0.0,
            days_back=30,
        )
    except Exception as e:
        log.exception("Portfolio events search failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Portfolio events error: {e}")

    # Newest first
    try:
        from datetime import datetime, timezone
        units.sort(
            key=lambda u: getattr(u, "created_at", datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True,
        )
    except Exception:
        pass

    if source:
        # Normalize to portfolio:<event> form if caller passed a bare name
        wanted = source if source.startswith("portfolio:") else f"portfolio:{source}"
        units = [u for u in units if u.source == wanted]

    events = [_serialize_portfolio_unit(u) for u in units[:limit]]
    return {
        "events": events,
        "count": len(events),
        "filter_source": source,
        "limit": limit,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /portfolio/significant-moves
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/bridge-state")
async def portfolio_bridge_state(
    authorization: str = Header(default=""),
) -> dict:
    """
    Peek at the in-memory portfolio bridge state.

    Returns the freshest cached summary + position count + when the
    bridge last saw a sync. Used for verifying the chat-context portfolio
    injector has live data without having to hit the (potentially slow)
    create_unit path.
    """
    _verify_strike_token(authorization)
    try:
        from .memory_bridge import get_bridge
        bridge = get_bridge()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bridge import failed: {e}")
    if bridge is None:
        return {"bridge_initialized": False}

    summary = bridge.latest_summary() or {}
    positions = bridge.latest_positions() or []
    latest_at = bridge.latest_at()
    return {
        "bridge_initialized": True,
        "latest_at": latest_at.isoformat() if latest_at else None,
        "summary_keys": sorted(summary.keys()),
        "nlv": summary.get("total_value"),
        "base_currency": summary.get("base_currency"),
        "day_pl": summary.get("daily_pl"),
        "day_pl_pct": summary.get("daily_pl_pct"),
        "position_count": len(positions),
        "top_positions": [
            {
                "symbol": p.get("symbol"),
                "market_value_cad": p.get("market_value_cad"),
                "daily_pl_pct": p.get("daily_pl_pct"),
            }
            for p in positions[:5]
        ],
    }


@router.get("/significant-moves")
async def portfolio_significant_moves(
    days: int = Query(default=7, ge=1, le=90),
    scope: Optional[str] = Query(default=None, description="position | portfolio"),
    authorization: str = Header(default=""),
) -> dict:
    """
    Portfolio:significant_move events in the requested window.

    Returns position-level AND portfolio-level moves unless scope is
    constrained. Sorted newest first.
    """
    _verify_strike_token(authorization)

    try:
        # Re-fetch module each call to dodge stale-global capture.
        import runtime.api.routes as _routes
        _brain = getattr(_routes, "brain", None)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Brain unavailable: {exc}")

    if _brain is None or not getattr(_brain, "memory_store", None):
        raise HTTPException(status_code=503, detail="Memory store not initialised")

    try:
        units = await _brain.memory_store.search_units(
            tags=["portfolio:significant_move"],
            importance_threshold=0.0,
            days_back=days,
        )
    except Exception as e:
        log.exception("Portfolio significant-moves search failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Significant-moves error: {e}")

    if scope:
        scope_tag = f"scope:{scope}"
        units = [u for u in units if scope_tag in (u.tags or [])]

    try:
        from datetime import datetime, timezone
        units.sort(
            key=lambda u: getattr(u, "created_at", datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True,
        )
    except Exception:
        pass

    moves = [_serialize_portfolio_unit(u) for u in units]
    return {
        "moves": moves,
        "count": len(moves),
        "window_days": days,
        "scope_filter": scope,
    }
