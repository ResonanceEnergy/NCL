"""Journal endpoints (/journal/*) extracted from routes.py.

Owns the FirstStrike Journal tab surface — operator knowledge base, tips,
reflections, and pattern insights:

    POST /journal/entry              — create a journal entry          [AUTH]
    GET  /journal/entries            — list entries with filters       [AUTH]
    GET  /journal/today              — today's entries                 [AUTH]
    GET  /journal/entry/{entry_id}   — single entry detail             [AUTH]
    GET  /journal/search             — full-text search                [AUTH]
    POST /journal/tip                — create a tip/technique          [AUTH]
    GET  /journal/tips               — list tips with filters          [AUTH]
    GET  /journal/tips/contextual    — context-aware tips              [AUTH]
    GET  /journal/reflection/{date}  — reflection for a specific date  [AUTH]
    GET  /journal/reflections        — recent reflections              [AUTH]
    POST /journal/reflect            — trigger reflection generation   [AUTH]
    GET  /journal/insights           — pattern insights                [AUTH]
    GET  /journal/analytics          — journal analytics over N days   [AUTH]
    GET  /journal/stats              — quick journal stats             [AUTH]
    GET  /journal/context            — context string for briefs       [AUTH]

W10B-3 (2026-05-24): Converted from the legacy ``from .. import routes as
_routes`` lazy-import pattern to FastAPI ``Depends()`` injection. The
three subsystem singletons (``JournalStore``, ``ReflectionEngine``,
``ContextAwareTips``) are now injected via DI factories in
:mod:`runtime.api.deps`. Auth flows through ``verify_strike_token_dep``.
"""

from __future__ import annotations  # noqa: I001

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..deps import (
    get_context_tips,
    get_journal_store,
    get_reflection_engine,
    verify_strike_token_dep,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["journal"])


# ---------------------------------------------------------------------------
# Request schemas — kept under leading-underscore names to mirror the
# originals in routes.py (these were private to the module).
# ---------------------------------------------------------------------------


class _JournalEntryRequest(BaseModel):
    content: str
    entry_type: str = "note"
    title: str = ""
    tags: list[str] = Field(default_factory=list)
    importance: float = 50.0  # 0-100 scale (was 0.5 — wrong scale)
    source_context: str = ""


class _JournalTipRequest(BaseModel):
    title: str
    content: str
    category: str = "general"
    tags: list[str] = Field(default_factory=list)
    source: str = ""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/journal/entry")
async def create_journal_entry(
    body: _JournalEntryRequest,
    journal_store=Depends(get_journal_store),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Create a new journal entry."""
    if not journal_store:
        raise HTTPException(status_code=503, detail="Journal store not initialized")
    try:
        entry = await journal_store.create_entry(
            content=body.content,
            entry_type=body.entry_type,
            title=body.title,
            tags=body.tags,
            importance=body.importance,
            source_context=body.source_context,
        )
        return {
            "status": "created",
            "entry": entry
            if isinstance(entry, dict)
            else entry.__dict__
            if hasattr(entry, "__dict__")
            else vars(entry),
        }  # noqa: E501
    except Exception as e:
        log.exception("Endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/journal/entries")
async def list_journal_entries(
    date_from: str | None = Query(default=None, description="Start date ISO (YYYY-MM-DD)"),
    date_to: str | None = Query(default=None, description="End date ISO (YYYY-MM-DD)"),
    entry_type: str | None = Query(default=None, description="Filter by entry type"),
    tags: str | None = Query(default=None, description="Comma-separated tag filter"),
    limit: int = Query(default=50, ge=1, le=500),
    journal_store=Depends(get_journal_store),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """List journal entries with optional filters."""
    if not journal_store:
        raise HTTPException(status_code=503, detail="Journal store not initialized")
    try:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        from datetime import date as date_type

        parsed_from = date_type.fromisoformat(date_from) if date_from else None
        parsed_to = date_type.fromisoformat(date_to) if date_to else None
        entries = await journal_store.get_entries(
            date_from=parsed_from,
            date_to=parsed_to,
            entry_type=entry_type,
            tags=tag_list,
            limit=limit,
        )
        serialized = []
        for e in entries:
            serialized.append(
                e if isinstance(e, dict) else e.__dict__ if hasattr(e, "__dict__") else vars(e)
            )  # noqa: E501
        return {"entries": serialized, "count": len(serialized)}
    except Exception as e:
        log.exception("Endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/journal/today")
async def journal_today(
    journal_store=Depends(get_journal_store),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get today's journal entries."""
    if not journal_store:
        raise HTTPException(status_code=503, detail="Journal store not initialized")
    try:
        today = datetime.now(timezone.utc).date()
        entries = await journal_store.get_today_entries()
        serialized = []
        for e in entries:
            serialized.append(
                e if isinstance(e, dict) else e.__dict__ if hasattr(e, "__dict__") else vars(e)
            )  # noqa: E501
        return {"date": today.isoformat(), "entries": serialized, "count": len(serialized)}
    except Exception as e:
        log.exception("Endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/journal/entry/{entry_id}")
async def get_journal_entry(
    entry_id: str,
    journal_store=Depends(get_journal_store),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get a single journal entry by ID."""
    if not journal_store:
        raise HTTPException(status_code=503, detail="Journal store not initialized")
    try:
        entry = await journal_store.get_entry(entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")
        return (
            entry
            if isinstance(entry, dict)
            else entry.__dict__
            if hasattr(entry, "__dict__")
            else vars(entry)
        )  # noqa: E501
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/journal/search")
async def search_journal(
    q: str = Query(..., description="Search query"),
    limit: int = Query(default=20, ge=1, le=200),
    journal_store=Depends(get_journal_store),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Full-text search across journal entries."""
    if not journal_store:
        raise HTTPException(status_code=503, detail="Journal store not initialized")
    try:
        results = await journal_store.search(query=q, limit=limit)
        serialized = []
        for e in results:
            serialized.append(
                e if isinstance(e, dict) else e.__dict__ if hasattr(e, "__dict__") else vars(e)
            )  # noqa: E501
        return {"query": q, "results": serialized, "count": len(serialized)}
    except Exception as e:
        log.exception("Endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/journal/tip")
async def create_journal_tip(
    body: _JournalTipRequest,
    journal_store=Depends(get_journal_store),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Create a new tip or technique entry."""
    if not journal_store:
        raise HTTPException(status_code=503, detail="Journal store not initialized")
    try:
        tip = await journal_store.create_tip(
            title=body.title,
            content=body.content,
            category=body.category,
            tags=body.tags,
            source=body.source,
        )
        return {
            "status": "created",
            "tip": tip
            if isinstance(tip, dict)
            else tip.__dict__
            if hasattr(tip, "__dict__")
            else vars(tip),
        }  # noqa: E501
    except Exception as e:
        log.exception("Endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/journal/tips")
async def list_journal_tips(
    category: str | None = Query(default=None),
    tags: str | None = Query(default=None, description="Comma-separated tag filter"),
    q: str | None = Query(default=None, description="Optional text search"),
    limit: int = Query(default=50, ge=1, le=500),
    journal_store=Depends(get_journal_store),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """List tips/techniques with optional filters."""
    if not journal_store:
        raise HTTPException(status_code=503, detail="Journal store not initialized")
    try:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        tips = await journal_store.get_tips(category=category, tags=tag_list, query=q, limit=limit)  # noqa: E501
        serialized = []
        for t in tips:
            serialized.append(
                t if isinstance(t, dict) else t.__dict__ if hasattr(t, "__dict__") else vars(t)
            )  # noqa: E501
        return {"tips": serialized, "count": len(serialized)}
    except Exception as e:
        log.exception("Endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/journal/tips/contextual")
async def contextual_tips(
    context_tips=Depends(get_context_tips),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get context-aware tips based on today's activity."""
    if not context_tips:
        raise HTTPException(status_code=503, detail="Context tips engine not initialized")
    try:
        tips = await context_tips.get_contextual_tips()
        serialized = []
        for t in tips:
            serialized.append(
                t if isinstance(t, dict) else t.__dict__ if hasattr(t, "__dict__") else vars(t)
            )  # noqa: E501
        return {"tips": serialized, "count": len(serialized)}
    except Exception as e:
        log.exception("Endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/journal/reflection/{date}")
async def get_journal_reflection(
    date: str,
    journal_store=Depends(get_journal_store),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get reflection for a specific date (YYYY-MM-DD)."""
    if not journal_store:
        raise HTTPException(status_code=503, detail="Journal store not initialized")
    try:
        reflection = await journal_store.get_reflection(date)
        if not reflection:
            return {
                "date": date,
                "status": "no_reflection",
                "message": "No reflection for this date. POST /journal/reflect to generate one.",
            }  # noqa: E501
        return (
            reflection
            if isinstance(reflection, dict)
            else reflection.__dict__
            if hasattr(reflection, "__dict__")
            else vars(reflection)
        )  # noqa: E501
    except Exception as e:
        log.exception("Endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/journal/reflections")
async def list_journal_reflections(
    days: int = Query(default=7, ge=1, le=90),
    journal_store=Depends(get_journal_store),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get recent reflections."""
    if not journal_store:
        raise HTTPException(status_code=503, detail="Journal store not initialized")
    try:
        reflections = await journal_store.get_recent_reflections(days=days)
        serialized = []
        for r in reflections:
            serialized.append(
                r if isinstance(r, dict) else r.__dict__ if hasattr(r, "__dict__") else vars(r)
            )  # noqa: E501
        return {"reflections": serialized, "count": len(serialized), "days": days}
    except Exception as e:
        log.exception("Endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/journal/reflect")
async def trigger_reflection(
    reflection_engine=Depends(get_reflection_engine),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Trigger reflection generation for today."""
    if not reflection_engine:
        raise HTTPException(status_code=503, detail="Reflection engine not initialized")
    try:
        reflection = await reflection_engine.generate_daily_reflection()
        return {
            "status": "generated",
            "reflection": reflection
            if isinstance(reflection, dict)
            else reflection.__dict__
            if hasattr(reflection, "__dict__")
            else vars(reflection),
        }  # noqa: E501
    except Exception as e:
        log.exception("Endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/journal/insights")
async def journal_insights(
    journal_store=Depends(get_journal_store),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get pattern insights derived from journal entries."""
    if not journal_store:
        raise HTTPException(status_code=503, detail="Journal store not initialized")
    try:
        insights = await journal_store.get_insights()
        serialized = []
        for i in insights:
            serialized.append(
                i if isinstance(i, dict) else i.__dict__ if hasattr(i, "__dict__") else vars(i)
            )  # noqa: E501
        return {"insights": serialized, "count": len(serialized)}
    except Exception as e:
        log.exception("Endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/journal/analytics")
async def journal_analytics(
    days: int = Query(default=30, ge=1, le=365),
    journal_store=Depends(get_journal_store),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get journal analytics over a date range."""
    if not journal_store:
        raise HTTPException(status_code=503, detail="Journal store not initialized")
    try:
        analytics = await journal_store.get_analytics(days=days)
        return {
            "days": days,
            "analytics": analytics if isinstance(analytics, dict) else {"data": analytics},
        }  # noqa: E501
    except Exception as e:
        log.exception("Endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/journal/stats")
async def journal_stats(
    journal_store=Depends(get_journal_store),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get quick journal stats."""
    if not journal_store:
        raise HTTPException(status_code=503, detail="Journal store not initialized")
    try:
        stats = journal_store.get_stats()
        return stats if isinstance(stats, dict) else {"data": stats}
    except Exception as e:
        log.exception("Endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/journal/context")
async def journal_context(
    days: int = Query(default=3, ge=1, le=30),
    journal_store=Depends(get_journal_store),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get journal context string for intelligence briefs."""
    if not journal_store:
        raise HTTPException(status_code=503, detail="Journal store not initialized")
    try:
        context_str = await journal_store.get_context_for_brief(days=days)
        return {"days": days, "context": context_str}
    except Exception as e:
        log.exception("Endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")
