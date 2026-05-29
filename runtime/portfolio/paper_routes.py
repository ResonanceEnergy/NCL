"""
Paper Trading API routes for NCL Brain.

Endpoints for creating, tracking, closing, and analyzing paper trades.
Enforces pre-trade discipline: every trade requires entry + stop + target.
"""

import logging
import os
import secrets
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .paper_trading import PaperTradingEngine


log = logging.getLogger(__name__)

router = APIRouter(prefix="/paper", tags=["paper-trading"])

# Module-level engine — initialized at Brain startup
_engine: Optional[PaperTradingEngine] = None


def set_paper_engine(engine: PaperTradingEngine) -> None:
    """Called by Brain startup to inject the PaperTradingEngine."""
    global _engine
    _engine = engine


def _get_strike_token() -> str:
    try:
        from runtime.api.routes import STRIKE_TOKEN

        return STRIKE_TOKEN
    except ImportError:
        return os.getenv("STRIKE_AUTH_TOKEN", "")


def _verify(authorization: str):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.replace("Bearer ", "").strip()
    strike_token = _get_strike_token()
    if not strike_token or not secrets.compare_digest(token, strike_token):
        raise HTTPException(status_code=403, detail="Invalid strike token")


def _require_engine() -> PaperTradingEngine:
    if _engine is None:
        raise HTTPException(status_code=503, detail="Paper trading engine not initialized")
    return _engine


# ── Request Models ────────────────────────────────────────────────


class CreateTradeRequest(BaseModel):
    """Trade ticket — stop and target REQUIRED (no plan = no trade)."""

    symbol: str = Field(..., description="Ticker symbol (e.g. AAPL, BTC-USD)")
    entry_price: float = Field(..., gt=0, description="Entry price")
    stop_loss: float = Field(..., gt=0, description="Stop loss price (REQUIRED)")
    target_1: float = Field(..., gt=0, description="Primary profit target (REQUIRED)")
    direction: str = Field(default="long", description="long or short")
    asset_type: str = Field(default="stock", description="stock, option, or crypto")
    strategy: str = Field(default="manual", description="GOAT, BRAVO, or manual")
    quantity: float = Field(default=0, description="Share count (auto-sized if 0)")
    target_2: float = Field(default=0, description="Second profit target")
    target_3: float = Field(default=0, description="Third profit target")
    trailing_stop_pct: float = Field(default=0, ge=0, le=50, description="Trailing stop %")
    max_hold_days: int = Field(default=30, ge=1, le=365, description="Max days to hold")
    confidence: int = Field(default=3, ge=1, le=5, description="Confidence 1-5")
    notes: str = Field(default="", description="Trade notes/thesis")
    tags: list = Field(default_factory=list, description="Tags for categorization")
    scanner_data: dict = Field(default_factory=dict, description="Original scanner result")
    # Option fields
    option_type: str = Field(default="", description="call or put")
    strike_price: float = Field(default=0, description="Option strike price")
    expiration: str = Field(default="", description="Option expiration date")


class CloseTradeRequest(BaseModel):
    exit_price: float = Field(..., gt=0, description="Exit price")
    reason: str = Field(default="manual", description="Exit reason")
    trade_grade: str = Field(default="", description="A, B, or C grade")
    notes: str = Field(default="", description="Exit notes")


class UpdateTradeRequest(BaseModel):
    notes: Optional[str] = None
    confidence: Optional[int] = Field(default=None, ge=1, le=5)
    trade_grade: Optional[str] = None
    rules_followed: Optional[bool] = None
    tags: Optional[list] = None
    trailing_stop_pct: Optional[float] = Field(default=None, ge=0, le=50)
    max_hold_days: Optional[int] = Field(default=None, ge=1, le=365)
    stop_loss: Optional[float] = Field(default=None, gt=0)
    target_1: Optional[float] = Field(default=None, gt=0)
    target_2: Optional[float] = Field(default=None, ge=0)
    target_3: Optional[float] = Field(default=None, ge=0)


class UpdatePricesRequest(BaseModel):
    prices: dict = Field(..., description="Symbol -> current price mapping")


# ── Endpoints ─────────────────────────────────────────────────────


@router.post("/trade")
async def create_trade(
    req: CreateTradeRequest,
    authorization: str = Header(default=""),
) -> dict:
    """
    Create a new paper trade.

    ENFORCES: entry_price + stop_loss + target_1 all required.
    R:R must be >= 1.0 or the trade is rejected.
    Position size auto-calculated if quantity = 0.
    """
    _verify(authorization)
    engine = _require_engine()

    try:
        trade = engine.create_trade(req.model_dump())
        return {
            "status": "created",
            "trade": trade.to_summary(),
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        log.exception("Failed to create paper trade: %s", e)
        raise HTTPException(status_code=500, detail=f"Trade creation failed: {e}")


@router.post("/admin/deposit")
async def admin_deposit(
    payload: dict,
    authorization: str = Header(default=""),
) -> dict:
    """Wave 14X-5 (2026-05-29): credit/debit the paper account balance.
    Body: {amount: float, note?: str, absolute?: bool}.
    When absolute=true, sets balance to amount; otherwise adds amount.
    """
    _verify(authorization)
    engine = _require_engine()
    amount = float(payload.get("amount", 0))
    note = str(payload.get("note", ""))
    absolute = bool(payload.get("absolute", False))
    new_balance = (
        engine.set_balance(amount, note=note)
        if absolute
        else engine.deposit(amount, note=note)
    )
    return {
        "status": "ok",
        "operation": "set_balance" if absolute else "deposit",
        "amount": amount,
        "new_balance": new_balance,
        "note": note,
    }


@router.post("/trade/{trade_id}/close")
async def close_trade(
    trade_id: str,
    req: CloseTradeRequest,
    authorization: str = Header(default=""),
) -> dict:
    """Close an open paper trade with exit price and optional grade."""
    _verify(authorization)
    engine = _require_engine()

    try:
        trade = engine.close_trade(
            trade_id,
            req.exit_price,
            req.reason,
            grade=req.trade_grade,
            notes=req.notes,
        )
        if trade is None:
            raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
        return {
            "status": "closed",
            "trade": trade.to_summary(),
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Failed to close paper trade: %s", e)
        raise HTTPException(status_code=500, detail=f"Trade close failed: {e}")


@router.delete("/trade/{trade_id}")
async def delete_trade(
    trade_id: str,
    authorization: str = Header(default=""),
) -> dict:
    """Delete an open paper trade. Closed trades cannot be deleted (historical record)."""
    _verify(authorization)
    engine = _require_engine()

    try:
        engine.delete_trade(trade_id)
        return {"status": "deleted", "trade_id": trade_id}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.exception("Failed to delete paper trade: %s", e)
        raise HTTPException(status_code=500, detail=f"Trade deletion failed: {e}")


@router.put("/trade/{trade_id}")
async def update_trade(
    trade_id: str,
    req: UpdateTradeRequest,
    authorization: str = Header(default=""),
) -> dict:
    """Update trade metadata (notes, grade, confidence, tags, trailing stop)."""
    _verify(authorization)
    engine = _require_engine()

    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    trade = engine.update_trade(trade_id, updates)
    if trade is None:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")

    return {"status": "updated", "trade": trade.to_summary()}


@router.get("/trade/{trade_id}")
async def get_trade(
    trade_id: str,
    authorization: str = Header(default=""),
) -> dict:
    """Get full trade details including price history."""
    _verify(authorization)
    engine = _require_engine()

    trade = engine.get_trade(trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")

    return {"trade": trade}


@router.get("/trades")
async def list_trades(
    status: str = Query(default="all", description="all, open, closed"),
    strategy: str = Query(default="all", description="GOAT, BRAVO, manual, all"),
    limit: int = Query(default=50, ge=1, le=200),
    authorization: str = Header(default=""),
) -> dict:
    """List paper trades with optional filters."""
    _verify(authorization)
    engine = _require_engine()

    trades = engine.get_trades(status=status, strategy=strategy, limit=limit)
    return {
        "trades": trades,
        "total": len(trades),
    }


@router.post("/prices")
async def update_prices(
    req: UpdatePricesRequest,
    authorization: str = Header(default=""),
) -> dict:
    """
    Update current prices for open trades and check for triggers.

    Called by portfolio sync loop or manually.
    Returns any triggered events (stop hit, target hit, etc.).
    """
    _verify(authorization)
    engine = _require_engine()

    triggers = engine.update_prices(req.prices)
    return {
        "status": "updated",
        "triggers": triggers,
        "open_symbols": engine.get_open_symbols(),
    }


@router.get("/stats")
async def trading_stats(
    authorization: str = Header(default=""),
) -> dict:
    """
    Comprehensive trading statistics.

    Returns: win rate, expectancy, R-multiples, profit factor,
    equity curve, strategy breakdown, graduation readiness.
    """
    _verify(authorization)
    engine = _require_engine()

    return engine.get_stats()


@router.get("/open-symbols")
async def open_symbols(
    authorization: str = Header(default=""),
) -> dict:
    """Get list of symbols with open paper trades (for price feed)."""
    _verify(authorization)
    engine = _require_engine()

    symbols = engine.get_open_symbols()
    return {"symbols": symbols, "count": len(symbols)}
