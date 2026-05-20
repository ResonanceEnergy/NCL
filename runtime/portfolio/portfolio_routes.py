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

STRIKE_TOKEN = os.getenv("STRIKE_POINT_TOKEN", "")

# Module-level reference — injected by Brain startup via set_portfolio_manager()
_portfolio_manager = None


def set_portfolio_manager(pm) -> None:
    """Called by Brain startup to inject the PortfolioManager singleton."""
    global _portfolio_manager
    _portfolio_manager = pm


def _verify_strike_token(authorization: str):
    """Verify the strike point auth token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.replace("Bearer ", "").strip()
    if not STRIKE_TOKEN or not secrets.compare_digest(token, STRIKE_TOKEN):
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
            "daily_pl": summary.get("daily_pl", 0),
            "daily_pl_pct": summary.get("daily_pl_pct", 0),
            "total_pl": summary.get("total_pl", 0),
            "total_pl_pct": summary.get("total_pl_pct", 0),
            "cash_total": summary.get("cash_total", 0),
            "accounts": summary.get("accounts", []),
            "allocation": summary.get("allocation", {}),
            "fx_rate": summary.get("fx_rate", 1.0),
            "last_sync": summary.get("last_sync"),
            "market_open": summary.get("market_open", False),
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
