"""
Calendar API routes -- lunar phases, market events, energy states, correlation.

All endpoints require Strike authentication via _verify_strike_token().
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request

from .lunar import (
    get_moon_phase,
    get_calendar_range,
    get_upcoming_major_phases,
    get_cycle_context,
)
from .events import (
    get_all_events,
    add_custom_event,
    EVENT_CATEGORIES,
)
from .local_events import (
    get_local_events,
    get_cities_list,
    add_local_event,
    CITIES,
    LOCAL_EVENT_CATEGORIES,
)
from .watchlist import build_watchlist, WATCHLIST_CATEGORIES

log = logging.getLogger("ncl.calendar.routes")

calendar_router = APIRouter(prefix="/calendar", tags=["calendar"])


def _get_strike_token() -> str:
    """Lazily resolve the strike token."""
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


# ── Today ─────────────────────────────────────────────────────────────

@calendar_router.get("/today")
async def calendar_today(authorization: str = Header(default="")):
    """
    Today's calendar -- moon phase, energy state, events, suggested actions.
    One-stop endpoint for the dashboard moon banner.
    """
    _verify_strike_token(authorization)

    now = datetime.now(timezone.utc)
    today = date.today()

    phase = get_moon_phase(now)
    events = await get_all_events(today, today)
    context = get_cycle_context()

    return {
        "date": today.isoformat(),
        "moon": phase,
        "events": events,
        "cycle_context": context,
        "daily_frame": context["daily_brief_frame"],
    }


# ── Week View (7 days) ───────────────────────────────────────────────

@calendar_router.get("/week")
async def calendar_week(
    offset: int = Query(0, description="Week offset from today (0=current, 1=next, -1=last)"),
    authorization: str = Header(default=""),
):
    """
    7-day calendar with daily moon phases and all events.
    """
    _verify_strike_token(authorization)

    today = date.today()
    start = today + timedelta(days=offset * 7)
    end = start + timedelta(days=6)

    start_dt = datetime.combine(start, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(end, datetime.max.time()).replace(tzinfo=timezone.utc)

    days = get_calendar_range(start_dt, end_dt)
    events = await get_all_events(start, end)
    major_phases = get_upcoming_major_phases(14)

    # Attach events to their days
    events_by_date: dict[str, list] = {}
    for e in events:
        d = e["date"]
        events_by_date.setdefault(d, []).append(e)

    for day in days:
        day["events"] = events_by_date.get(day["date"], [])
        day["event_count"] = len(day["events"])
        day["has_high_impact"] = any(
            e.get("impact") in ("high", "critical") for e in day["events"]
        )

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": days,
        "major_phases": major_phases,
        "event_count": len(events),
    }


# ── Month View (30 days) ─────────────────────────────────────────────

@calendar_router.get("/month")
async def calendar_month(
    offset: int = Query(0, description="Month offset from today (0=current, 1=next, -1=last)"),
    authorization: str = Header(default=""),
):
    """
    30-day calendar with daily moon phases and all events.
    """
    _verify_strike_token(authorization)

    today = date.today()
    if offset == 0:
        start = today
    elif offset > 0:
        start = date(today.year, today.month + offset, 1)
    else:
        m = today.month + offset
        y = today.year
        while m < 1:
            m += 12
            y -= 1
        start = date(y, m, 1)

    end = start + timedelta(days=29)

    start_dt = datetime.combine(start, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(end, datetime.max.time()).replace(tzinfo=timezone.utc)

    days = get_calendar_range(start_dt, end_dt)
    events = await get_all_events(start, end)
    major_phases = get_upcoming_major_phases(60)

    # Attach events to days
    events_by_date: dict[str, list] = {}
    for e in events:
        d = e["date"]
        events_by_date.setdefault(d, []).append(e)

    for day in days:
        day["events"] = events_by_date.get(day["date"], [])
        day["event_count"] = len(day["events"])
        day["has_high_impact"] = any(
            e.get("impact") in ("high", "critical") for e in day["events"]
        )

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": days,
        "major_phases": [p for p in major_phases if start.isoformat() <= p["datetime"][:10] <= end.isoformat()],
        "event_count": len(events),
    }


# ── Moon Phase Details ────────────────────────────────────────────────

@calendar_router.get("/moon")
async def moon_current(authorization: str = Header(default="")):
    """Current moon phase with full energy state and cycle context."""
    _verify_strike_token(authorization)
    return get_cycle_context()


@calendar_router.get("/moon/phases")
async def moon_upcoming_phases(
    days: int = Query(60, description="How many days ahead to look"),
    authorization: str = Header(default=""),
):
    """Upcoming major moon phases (new, full, quarters)."""
    _verify_strike_token(authorization)
    return {
        "phases": get_upcoming_major_phases(days),
        "current": get_moon_phase(),
    }


# ── Energy State ──────────────────────────────────────────────────────

@calendar_router.get("/energy")
async def energy_state(authorization: str = Header(default="")):
    """
    Current energy state with suggested to-do list framed by moon phase.
    Designed for the dashboard banner and journal integration.
    """
    _verify_strike_token(authorization)

    phase = get_moon_phase()
    context = get_cycle_context()

    # Build a prioritized to-do list based on energy state
    todos = []
    for i, action in enumerate(phase["suggested_actions"]):
        todos.append({
            "priority": i + 1,
            "action": action,
            "category": phase["energy_mode"],
            "phase_context": phase["phase_name"],
        })

    # Add phase-specific intel suggestions
    mode = phase["energy_mode"]
    if mode in ("initiate", "build"):
        todos.append({
            "priority": len(todos) + 1,
            "action": "Check scanner for new entry opportunities",
            "category": "intel",
            "phase_context": "Waxing energy favors new entries",
        })
    elif mode in ("harvest", "analyze"):
        todos.append({
            "priority": len(todos) + 1,
            "action": "Run prediction accuracy review",
            "category": "intel",
            "phase_context": "Peak energy ideal for assessment",
        })
    elif mode in ("release", "reflect"):
        todos.append({
            "priority": len(todos) + 1,
            "action": "Run memory consolidation and pruning",
            "category": "system",
            "phase_context": "Waning energy favors cleanup",
        })

    return {
        "phase": phase,
        "cycle_context": context,
        "suggested_todos": todos,
        "daily_frame": context["daily_brief_frame"],
    }


# ── Events Management ────────────────────────────────────────────────

@calendar_router.get("/events")
async def list_events(
    start: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    category: Optional[str] = Query(None, description="Filter by category"),
    authorization: str = Header(default=""),
):
    """List events in a date range, optionally filtered by category."""
    _verify_strike_token(authorization)

    today = date.today()
    s = date.fromisoformat(start) if start else today
    e = date.fromisoformat(end) if end else today + timedelta(days=30)

    events = await get_all_events(s, e)

    if category:
        events = [ev for ev in events if ev.get("category") == category]

    return {
        "start": s.isoformat(),
        "end": e.isoformat(),
        "events": events,
        "count": len(events),
    }


@calendar_router.post("/events")
async def create_event(request: Request, authorization: str = Header(default="")):
    """Add a custom event to the calendar."""
    _verify_strike_token(authorization)

    body = await request.json()
    required = ["date", "title"]
    for field in required:
        if field not in body:
            return {"error": f"Missing required field: {field}"}, 400

    event = add_custom_event(body)
    return {"status": "created", "event": event}


# ── Categories metadata ──────────────────────────────────────────────

@calendar_router.get("/categories")
async def list_categories(authorization: str = Header(default="")):
    """List all event categories with their metadata."""
    _verify_strike_token(authorization)
    return {"categories": EVENT_CATEGORIES}


# ── Local Events ────────────────────────────────────────────────────

@calendar_router.get("/cities")
async def list_cities(authorization: str = Header(default="")):
    """List all available cities for local events tracking."""
    _verify_strike_token(authorization)
    return {"cities": get_cities_list()}


@calendar_router.get("/local/{city_id}")
async def city_events(
    city_id: str,
    start: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    authorization: str = Header(default=""),
):
    """Get local events for a specific city."""
    _verify_strike_token(authorization)

    if city_id not in CITIES:
        raise HTTPException(status_code=404, detail=f"Unknown city: {city_id}")

    today = date.today()
    s = date.fromisoformat(start) if start else today
    e = date.fromisoformat(end) if end else today + timedelta(days=30)

    events = await get_local_events(city_id, s, e)
    city_meta = CITIES[city_id]

    return {
        "city": city_id,
        "city_name": city_meta["name"],
        "country": city_meta["country"],
        "start": s.isoformat(),
        "end": e.isoformat(),
        "events": events,
        "count": len(events),
    }


@calendar_router.post("/local/events")
async def create_local_event(request: Request, authorization: str = Header(default="")):
    """Add a curated local event."""
    _verify_strike_token(authorization)

    body = await request.json()
    required = ["date", "title", "city"]
    for field in required:
        if field not in body:
            return {"error": f"Missing required field: {field}"}, 400

    event = add_local_event(body)
    return {"status": "created", "event": event}


@calendar_router.get("/local/categories")
async def local_categories(authorization: str = Header(default="")):
    """List local event categories with metadata."""
    _verify_strike_token(authorization)
    return {"categories": LOCAL_EVENT_CATEGORIES}


# ── Watchlist / Suggested To-Do ──────────────────────────────────────

@calendar_router.get("/watchlist")
async def get_watchlist(authorization: str = Header(default="")):
    """
    Full correlated watchlist/to-do for today.
    Pulls from moon energy, predictions, scanners, council, journal,
    paper trades, portfolio, and calendar events.
    """
    _verify_strike_token(authorization)

    now = datetime.now(timezone.utc)
    from .lunar import get_moon_phase, get_cycle_context

    phase = get_moon_phase(now)
    context = get_cycle_context()

    # Build the watchlist using internal Brain calls
    todos = await build_watchlist(
        brain_client=None,  # uses internal HTTP calls
        moon_phase=phase,
        cycle_context=context,
    )

    return {
        "date": date.today().isoformat(),
        "energy_mode": phase.get("energy_mode", ""),
        "phase_name": phase.get("phase_name", ""),
        "todos": todos,
        "count": len(todos),
        "categories": WATCHLIST_CATEGORIES,
    }
