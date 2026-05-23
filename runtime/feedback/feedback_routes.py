"""FastAPI router for the iOS feedback event stream.

Distinct from the pillar-feedback synthesis pipeline (scanner.py).
Wired by Brain startup via `set_feedback_recorder(recorder)`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .recorder import FeedbackRecorder

log = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])

# Module-level recorder — injected at Brain startup.
_recorder: Optional[FeedbackRecorder] = None


def set_feedback_recorder(recorder: FeedbackRecorder) -> None:
    """Called by Brain startup to inject the FeedbackRecorder."""
    global _recorder
    _recorder = recorder


def _require_recorder() -> FeedbackRecorder:
    if _recorder is None:
        raise HTTPException(status_code=503, detail="feedback recorder not initialized")
    return _recorder


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class FeedbackEventIn(BaseModel):
    event_type: str = Field(..., description="One of FeedbackRecorder.EVENT_TYPES")
    signal_id: str = Field(..., min_length=1)
    source: str = Field(default="", description="e.g. 'reddit', 'youtube', 'prediction'")
    tier: str = Field(default="", description="e.g. 'focused', 'micro', 'macro'")
    metadata: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/event")
async def post_event(body: FeedbackEventIn) -> dict:
    rec = _require_recorder()
    try:
        event = await rec.record(
            event_type=body.event_type,
            signal_id=body.signal_id,
            source=body.source,
            tier=body.tier,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "event": event}


@router.get("/events")
async def get_events(
    event_type: Optional[str] = Query(default=None),
    signal_id: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None, description="ISO-8601 timestamp"),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict:
    rec = _require_recorder()
    since_dt: Optional[datetime] = None
    if since:
        try:
            # Accept trailing 'Z' as UTC
            since_norm = since.replace("Z", "+00:00")
            since_dt = datetime.fromisoformat(since_norm)
            if since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=timezone.utc)
        except Exception:
            raise HTTPException(status_code=400, detail=f"invalid since timestamp: {since}")

    events = await rec.query(
        event_type=event_type,
        signal_id=signal_id,
        since=since_dt,
        limit=limit,
    )
    return {"ok": True, "count": len(events), "events": events}


@router.get("/stats")
async def get_stats() -> dict:
    rec = _require_recorder()
    return {"ok": True, "stats": rec.stats()}
