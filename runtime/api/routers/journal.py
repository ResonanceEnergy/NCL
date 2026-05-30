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

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
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


@router.post("/journal/voice-entry")
async def create_journal_voice_entry(
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
    min_speakers: int = Form(default=1),
    max_speakers: int = Form(default=4),
    importance: int = Form(default=60),
    title: str | None = Form(default=None),
    journal_store=Depends(get_journal_store),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Wave 14AY: voice journal upload + diarized transcription.

    Accepts a multipart audio file (.wav / .mp3 / .m4a / .ogg / .webm),
    runs runtime/journal/voice_transcribe.transcribe_with_diarization
    (mlx-whisper + pyannote when HF_TOKEN set), and persists the
    resulting transcript as a JournalEntry kind=voice_journal.

    Response:
        {
            "status": "created",
            "entry": {...},
            "transcript": {
                "language": "en",
                "duration_s": 42.1,
                "speakers": ["SPEAKER_00", ...],
                "model": "mlx-whisper:... + pyannote:..."
            }
        }
    """
    if not journal_store:
        raise HTTPException(status_code=503, detail="Journal store not initialized")

    import os as _os
    import tempfile
    from pathlib import Path as _Path

    # Persist the uploaded blob to a temp file so the transcriber can read
    # it. Same-process cleanup via context manager.
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty audio file")
    suffix = ".wav"
    if file.filename:
        _, ext = _os.path.splitext(file.filename)
        if ext.lower() in (".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac"):
            suffix = ext.lower()

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(raw)
            tmp_path = _Path(tmp.name)

        try:
            from ...journal.voice_transcribe import transcribe_with_diarization
        except Exception as e:
            log.warning("voice_transcribe import failed: %s", e)
            raise HTTPException(
                status_code=503,
                detail="voice transcription module unavailable (Wave 14AP)",
            )

        result = await transcribe_with_diarization(
            tmp_path,
            language=language,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
        )
    finally:
        try:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass

    text = result.get("text", "").strip()
    if not text:
        return {
            "status": "error",
            "error": result.get("error", "no transcript produced"),
            "transcript": result,
        }

    speakers = result.get("speakers", [])
    tags = ["voice_journal"]
    if speakers:
        tags.append(f"speakers:{len(speakers)}")

    try:
        entry = await journal_store.create_entry(
            content=text,
            entry_type="voice_journal",
            title=title or f"Voice entry ({result.get('duration_s', 0)}s)",
            tags=tags,
            importance=importance,
            source_context={
                "transcript_language": result.get("language"),
                "transcript_duration_s": result.get("duration_s"),
                "transcript_speakers": speakers,
                "transcript_model": result.get("model"),
            },
        )
    except Exception as e:
        log.exception("voice-entry create failed: %s", e)
        raise HTTPException(status_code=500, detail="journal entry create failed")

    return {
        "status": "created",
        "entry": entry if isinstance(entry, dict) else (
            entry.__dict__ if hasattr(entry, "__dict__") else vars(entry)
        ),
        "transcript": {
            "language": result.get("language"),
            "duration_s": result.get("duration_s"),
            "speakers": speakers,
            "segments_count": len(result.get("segments") or []),
            "model": result.get("model"),
        },
    }


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


# ===========================================================================
# Morning Quiz — Wave 14E (2026-05-25)
# ===========================================================================
#
# Daily 7-question intention-setting protocol that anchors the Journal
# system to actual operator input. See docs/JOURNAL_REDESIGN_2026-05-25.md
# for design rationale.
#
# Endpoints:
#   POST   /journal/morning-quiz                — submit today's quiz
#   GET    /journal/morning-quiz/today          — today's quiz if exists
#   GET    /journal/morning-quiz/latest         — most recent quiz
#   GET    /journal/morning-quiz/by-date/{d}    — specific date
#   GET    /journal/morning-quiz/history        — recent quizzes list


class _MorningQuizSubmit(BaseModel):
    """Inbound shape for POST /journal/morning-quiz.

    Date defaults to operator-local today; the propagator handles
    re-submission idempotency (same date overwrites the day's file
    + updates existing journal entry rather than duplicating).
    """

    date: str = Field(default="", description="YYYY-MM-DD; blank = today")
    mood_score: int = Field(..., ge=1, le=10)
    mood_word: str = Field(default="")
    top_priority: str = Field(..., min_length=1, max_length=300)
    supporting_tasks: list[str] = Field(default_factory=list)
    market_posture: str = Field(default="neutral")
    research_question: str = Field(default="")
    gratitude: str = Field(default="")
    yesterday_lesson: str = Field(default="")
    notes: str = Field(default="")
    wisdom_id_shown: str = Field(default="")


def _operator_local_today() -> str:
    """Operator-local today, YYYY-MM-DD. Reuses journal_store helper."""
    from ...journal.store import local_today_str

    return local_today_str()


@router.post("/journal/morning-quiz")
async def submit_morning_quiz(
    body: _MorningQuizSubmit,
    journal_store=Depends(get_journal_store),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Submit the morning quiz. Propagates to context + journal + calendar."""
    from ...journal.morning_quiz import MorningQuiz, submit_quiz

    try:
        # Resolve date
        date_str = (body.date or "").strip() or _operator_local_today()

        quiz = MorningQuiz(
            date=date_str,
            mood_score=body.mood_score,
            mood_word=body.mood_word,
            top_priority=body.top_priority,
            supporting_tasks=body.supporting_tasks,
            market_posture=body.market_posture,
            research_question=body.research_question,
            gratitude=body.gratitude,
            yesterday_lesson=body.yesterday_lesson,
            notes=body.notes,
            wisdom_id_shown=body.wisdom_id_shown,
        )

        # Pull working_context off the autonomous scheduler if available
        working_context = None
        try:
            from .. import routes as _routes

            sched = getattr(_routes, "_autonomous", None)
            if sched is not None:
                working_context = getattr(sched, "_working_context", None)
        except Exception:
            pass

        quiz, fired = await submit_quiz(
            quiz,
            journal_store=journal_store,
            working_context=working_context,
            calendar_todos_callback=None,  # calendar push wired in W14E followup
        )
        return {
            "status": "ok",
            "quiz_id": quiz.quiz_id,
            "date": quiz.date,
            "fired": fired,
            "journal_entry_id": quiz.journal_entry_id,
            "lesson_entry_id": quiz.lesson_entry_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Morning quiz submit failed: %s", e)
        raise HTTPException(status_code=500, detail=f"submit failed: {type(e).__name__}: {e}")


@router.get("/journal/morning-quiz/today")
async def morning_quiz_today(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Today's quiz if it exists, else {status: not_yet_submitted}."""
    from ...journal.morning_quiz import load_quiz_by_date

    today = _operator_local_today()
    quiz = load_quiz_by_date(today)
    if not quiz:
        return {"status": "not_yet_submitted", "date": today}
    return {"status": "ok", "date": today, "quiz": quiz.model_dump(mode="json")}


@router.get("/journal/morning-quiz/latest")
async def morning_quiz_latest(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Most recent quiz on disk (today preferred, else newest)."""
    from ...journal.morning_quiz import load_quiz_by_date, load_quiz_history

    today = _operator_local_today()
    quiz = load_quiz_by_date(today)
    if not quiz:
        history = load_quiz_history(limit=1)
        quiz = history[0] if history else None
    if not quiz:
        return {"status": "not_found", "message": "No morning quizzes yet."}
    return {
        "status": "ok",
        "quiz": quiz.model_dump(mode="json"),
        "is_today": quiz.date == today,
    }


@router.get("/journal/morning-quiz/by-date/{date}")
async def morning_quiz_by_date(
    date: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Specific date's quiz."""
    import re as _re

    from ...journal.morning_quiz import load_quiz_by_date

    if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD")
    quiz = load_quiz_by_date(date)
    if not quiz:
        return {"status": "not_found", "date": date}
    return {"status": "ok", "date": date, "quiz": quiz.model_dump(mode="json")}


@router.get("/journal/morning-quiz/history")
async def morning_quiz_history(
    limit: int = Query(default=30, ge=1, le=120),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Recent quizzes (newest first, deduped by quiz_id)."""
    from ...journal.morning_quiz import load_quiz_history

    items = load_quiz_history(limit=limit)
    return {
        "status": "ok",
        "count": len(items),
        "items": [
            {
                "quiz_id": q.quiz_id,
                "date": q.date,
                "mood_score": q.mood_score,
                "mood_word": q.mood_word,
                "top_priority": q.top_priority,
                "market_posture": q.market_posture,
                "submitted_at": q.submitted_at.isoformat(),
                "journal_entry_id": q.journal_entry_id,
            }
            for q in items
        ],
    }


# ===========================================================================
# Weekly + Yearly Review Wizards — Wave 14F (2026-05-25)
# ===========================================================================
#
# Same pattern as morning-quiz: persist to data/journal/{weekly,yearly}-review/
# + create a JournalEntry that the reflection engine consumes.


class _WeeklyReviewSubmit(BaseModel):
    iso_week: str = Field(default="", description="YYYY-Www; blank = current week")
    wins: list[str] = Field(default_factory=list)
    biggest_miss: str = ""
    miss_lesson: str = ""
    energy_score: int = Field(default=7, ge=1, le=10)
    focus_score: int = Field(default=7, ge=1, le=10)
    mood_score: int = Field(default=7, ge=1, le=10)
    needle_moved: str = ""
    top_kr_movement: str = ""
    next_week_focus: str = Field(..., min_length=1, max_length=300)
    open_threads: list[str] = Field(default_factory=list)
    notes: str = ""


class _YearlyReviewSubmit(BaseModel):
    year: int
    wins: list[str] = Field(default_factory=list)
    hard_lesson: str = ""
    would_change: str = ""
    north_star_progress: str = ""
    next_year_themes: list[str] = Field(default_factory=list)
    open_question: str = ""
    notes: str = ""


def _current_iso_week() -> str:
    d = datetime.now(timezone.utc).date()
    iy, iw, _ = d.isocalendar()
    return f"{iy}-W{iw:02d}"


@router.post("/journal/weekly-review")
async def submit_weekly_review_endpoint(
    body: _WeeklyReviewSubmit,
    journal_store=Depends(get_journal_store),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    from ...journal.review_wizards import WeeklyReview, submit_weekly_review

    iso_week = (body.iso_week or "").strip() or _current_iso_week()
    review = WeeklyReview(
        iso_week=iso_week,
        wins=body.wins,
        biggest_miss=body.biggest_miss,
        miss_lesson=body.miss_lesson,
        energy_score=body.energy_score,
        focus_score=body.focus_score,
        mood_score=body.mood_score,
        needle_moved=body.needle_moved,
        top_kr_movement=body.top_kr_movement,
        next_week_focus=body.next_week_focus,
        open_threads=body.open_threads,
        notes=body.notes,
    )
    fired = await submit_weekly_review(review, journal_store=journal_store)
    return {
        "status": "ok",
        "review_id": review.review_id,
        "iso_week": review.iso_week,
        "fired": fired,
    }


@router.get("/journal/weekly-review/latest")
async def weekly_review_latest(_: None = Depends(verify_strike_token_dep)) -> dict:
    from ...journal.review_wizards import load_weekly

    iw = _current_iso_week()
    r = load_weekly(iw)
    if not r:
        return {"status": "not_yet_submitted", "iso_week": iw}
    return {"status": "ok", "review": r.model_dump(mode="json")}


@router.post("/journal/yearly-review")
async def submit_yearly_review_endpoint(
    body: _YearlyReviewSubmit,
    journal_store=Depends(get_journal_store),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    from ...journal.review_wizards import YearlyReview, submit_yearly_review

    review = YearlyReview(
        year=body.year,
        wins=body.wins,
        hard_lesson=body.hard_lesson,
        would_change=body.would_change,
        north_star_progress=body.north_star_progress,
        next_year_themes=body.next_year_themes,
        open_question=body.open_question,
        notes=body.notes,
    )
    fired = await submit_yearly_review(review, journal_store=journal_store)
    return {
        "status": "ok",
        "review_id": review.review_id,
        "year": review.year,
        "fired": fired,
    }


@router.get("/journal/yearly-review/{year}")
async def yearly_review_by_year(year: int, _: None = Depends(verify_strike_token_dep)) -> dict:
    from ...journal.review_wizards import load_yearly

    r = load_yearly(year)
    if not r:
        return {"status": "not_yet_submitted", "year": year}
    return {"status": "ok", "review": r.model_dump(mode="json")}
