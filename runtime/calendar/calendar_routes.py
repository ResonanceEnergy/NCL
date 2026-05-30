"""
Calendar API routes -- lunar phases, market events, energy states, correlation.

All endpoints require Strike authentication via _verify_strike_token().
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from .events import (
    EVENT_CATEGORIES,
    add_custom_event,
    get_all_events,
)
from .local_events import (
    CITIES,
    LOCAL_EVENT_CATEGORIES,
    add_local_event,
    get_cities_list,
    get_city_payload,
    get_local_events,
)
from .lunar import (
    get_calendar_range,
    get_cycle_context,
    get_moon_phase,
    get_upcoming_major_phases,
)
from .watchlist import WATCHLIST_CATEGORIES, build_watchlist


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
        day["has_high_impact"] = any(e.get("impact") in ("high", "critical") for e in day["events"])

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
        day["has_high_impact"] = any(e.get("impact") in ("high", "critical") for e in day["events"])

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": days,
        "major_phases": [
            p for p in major_phases if start.isoformat() <= p["datetime"][:10] <= end.isoformat()
        ],
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
        todos.append(
            {
                "priority": i + 1,
                "action": action,
                "category": phase["energy_mode"],
                "phase_context": phase["phase_name"],
            }
        )

    # Add phase-specific intel suggestions
    mode = phase["energy_mode"]
    if mode in ("initiate", "build"):
        todos.append(
            {
                "priority": len(todos) + 1,
                "action": "Check scanner for new entry opportunities",
                "category": "intel",
                "phase_context": "Waxing energy favors new entries",
            }
        )
    elif mode in ("harvest", "analyze"):
        todos.append(
            {
                "priority": len(todos) + 1,
                "action": "Run prediction accuracy review",
                "category": "intel",
                "phase_context": "Peak energy ideal for assessment",
            }
        )
    elif mode in ("release", "reflect"):
        todos.append(
            {
                "priority": len(todos) + 1,
                "action": "Run memory consolidation and pruning",
                "category": "system",
                "phase_context": "Waning energy favors cleanup",
            }
        )

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


@calendar_router.get("/events/split")
async def list_events_split(
    start: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    city_id: str = Query("edmonton", description="City for local events"),
    authorization: str = Header(default=""),
):
    """Wave 14AQ — return events partitioned into financial + infotainment.

    iOS Calendar tab renders each stream as a separate section per
    NATRIX directive 2026-05-30: "separate financial from infotainment".

    Returns:
        {financial: [...], infotainment: [...], counts: {financial,
        infotainment}, window: {start, end, days, city_id}}.
    """
    _verify_strike_token(authorization)

    from .events import get_all_events_split

    today = date.today()
    s = date.fromisoformat(start) if start else today
    e = date.fromisoformat(end) if end else today + timedelta(days=14)
    return await get_all_events_split(s, e, city_id=city_id)


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
    flat: bool = Query(
        False, description="Legacy flat-events response (no landmarks/notable_dates)"
    ),
    authorization: str = Header(default=""),
):
    """
    Rich per-city events payload — events + landmarks + notable_dates + fun_finder.

    Pass ?flat=true for the pre-2026-05-22 flat list response shape.
    """
    _verify_strike_token(authorization)

    if city_id not in CITIES:
        raise HTTPException(status_code=404, detail=f"Unknown city: {city_id}")

    today = date.today()
    s = date.fromisoformat(start) if start else today
    e = date.fromisoformat(end) if end else today + timedelta(days=30)

    if flat:
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

    return await get_city_payload(city_id, s, e)


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
    from .lunar import get_cycle_context, get_moon_phase

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


# ─────────────────────────────────────────────────────────────────────
# v2 endpoints — Calendar Agent + city preferences
# ─────────────────────────────────────────────────────────────────────


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _err_response(detail: str, status_code: int = 500) -> JSONResponse:
    """Uniform JSON error envelope (never let exceptions leak)."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": detail,
            "generated_at": _utc_iso(),
        },
    )


def _maybe_await(value):
    """Return value if it's a coroutine to be awaited, else wrap as awaited."""
    return value


async def _call_maybe_async(fn, *args, **kwargs):
    """Call fn (sync or async) and return its result."""
    result = fn(*args, **kwargs)
    if asyncio.iscoroutine(result):
        result = await result
    return result


def _get_calendar_agent_or_none():
    """Lazy import calendar_agent so missing module doesn't break route registration."""
    try:
        from .calendar_agent import get_calendar_agent  # type: ignore

        return get_calendar_agent()
    except Exception as exc:  # pragma: no cover - import failure path
        log.warning("calendar_agent unavailable: %s", exc)
        return None


def _get_cities_pref_or_none():
    """Lazy import cities_pref so missing module doesn't break route registration."""
    try:
        from . import cities_pref  # type: ignore

        return cities_pref
    except Exception as exc:  # pragma: no cover - import failure path
        log.warning("cities_pref unavailable: %s", exc)
        return None


# ── Sun / Space Weather ──────────────────────────────────────────────


@calendar_router.get("/sun")
async def calendar_sun(
    city_id: str = Query("edmonton", description="City id for sun times"),
    authorization: str = Header(default=""),
):
    """Sun times + space weather (sunspots, aurora, CME alerts, Schumann)."""
    _verify_strike_token(authorization)
    try:
        agent = _get_calendar_agent_or_none()
        if agent is None:
            return _err_response("calendar_agent module unavailable", 503)
        data = await _call_maybe_async(agent.get_sun_state, city_id)
        if not isinstance(data, dict):
            data = {"value": data}
        data.setdefault("fetched_at", _utc_iso())
        data.setdefault("generated_at", _utc_iso())
        return data
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("calendar/sun failed")
        return _err_response(f"sun fetch failed: {exc}")


# ── Compiled events (deduped + correlated + escalated) ──────────────


@calendar_router.get("/events/compiled")
async def calendar_events_compiled(
    city_id: str = Query("edmonton", description="City id"),
    window: int = Query(7, description="Window in days (7 or 30)"),
    exclude_window: int = Query(
        -1,
        description=(
            "Exclude events with date < today + N days. "
            "Default: window=30 auto-excludes the first 7 days (iOS 7-day tab "
            "already shows them). Pass 0 to disable, or any explicit N to override."
        ),
    ),
    scanner_cap: float = Query(
        0.30,
        description="Max fraction of total events that may come from scanner source (0..1).",
    ),
    min_quality_score: float = Query(
        0.50,
        description="Global minimum quality (0..1) for an event to be included.",
    ),
    authorization: str = Header(default=""),
):
    """Pre-compiled events with correlations + quality filters applied.

    Quality pipeline (order):
      1. exclude first N days (default 7 for window=30, 0 for window=7)
      2. dedup scanner signals per ticker-per-date
      3. dedup same-title-within-same-date across sources
      4. per-source quality threshold + global ``min_quality_score``
      5. cap scanner share of total at ``scanner_cap`` (default 30%)

    Response carries ``metadata.source_distribution`` and ``metadata.metrics``
    so the client can render a "Showing X events: N market, N scanner..."
    footer.
    """
    _verify_strike_token(authorization)
    try:
        if window not in (7, 30):
            raise HTTPException(status_code=400, detail="window must be 7 or 30")
        # Default exclude_window: skip the first 7 days when viewing 30-day,
        # because the iOS 7-day tab already covers them. Caller can pass 0 to
        # disable, or any explicit value to override.
        if exclude_window < 0:
            exclude_window = 7 if window == 30 else 0
        agent = _get_calendar_agent_or_none()
        if agent is None:
            return _err_response("calendar_agent module unavailable", 503)
        data = await _call_maybe_async(agent.compile_events, city_id, window)
        if not isinstance(data, dict):
            data = {"events": data or []}
        raw_events = data.get("events", []) or []
        correlations = data.get("correlations", []) or []

        # Apply quality filters (exclude_window + dedup + quality + scanner-cap).
        try:
            from .events_compiler import apply_quality_filters

            filtered = apply_quality_filters(
                raw_events,
                exclude_window=int(exclude_window),
                scanner_cap=float(scanner_cap),
                min_quality_score=float(min_quality_score),
            )
            events = filtered["events"]
            metrics = filtered["metrics"]
            source_distribution = filtered["source_distribution"]
        except Exception as filt_exc:
            log.warning("calendar/events/compiled filter failed, returning raw: %s", filt_exc)
            events = raw_events
            metrics = {"events_total": len(raw_events), "filter_error": str(filt_exc)}
            source_distribution = {}

        result = {
            "city_id": city_id,
            "window_days": window,
            "events": events,
            "correlations": correlations,
            "count": len(events),
            "generated_at": data.get("generated_at", _utc_iso()),
            "stale": bool(data.get("stale", False)),
            "metadata": {
                "source_distribution": source_distribution,
                "metrics": metrics,
                "exclude_window": int(exclude_window),
                "scanner_cap": float(scanner_cap),
                "min_quality_score": float(min_quality_score),
            },
        }
        return result
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("calendar/events/compiled failed")
        return _err_response(f"compiled events failed: {exc}")


# ── Todos (correlated to-do list) ────────────────────────────────────


@calendar_router.get("/todos")
async def calendar_todos(
    city_id: str = Query("edmonton", description="City id"),
    window: int = Query(7, description="Window in days (7 or 30)"),
    authorization: str = Header(default=""),
):
    """Correlated to-do list for the calendar tab."""
    _verify_strike_token(authorization)
    try:
        if window not in (7, 30):
            raise HTTPException(status_code=400, detail="window must be 7 or 30")
        agent = _get_calendar_agent_or_none()
        if agent is None:
            return _err_response("calendar_agent module unavailable", 503)
        data = await _call_maybe_async(agent.get_todos, city_id, window)
        if not isinstance(data, dict):
            data = {"todos": data or []}
        todos = data.get("todos", []) or []
        result = {
            "city_id": city_id,
            "window_days": window,
            "todos": todos,
            "count": data.get("count", len(todos)),
            "generated_at": data.get("generated_at", _utc_iso()),
            "stale": bool(data.get("stale", False)),
        }
        return result
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("calendar/todos failed")
        return _err_response(f"todos fetch failed: {exc}")


# ── Dashboard (one-shot mega-endpoint) ───────────────────────────────


@calendar_router.get("/dashboard")
async def calendar_dashboard(
    city_id: str = Query("edmonton", description="City id"),
    authorization: str = Header(default=""),
):
    """One-shot dashboard payload for the iOS Calendar tab initial load."""
    _verify_strike_token(authorization)
    try:
        agent = _get_calendar_agent_or_none()
        cities_pref = _get_cities_pref_or_none()

        # City metadata — prefer cities_pref lookup, fall back to CITIES dict
        city_meta: Dict[str, Any] = {}
        if cities_pref is not None and hasattr(cities_pref, "get_city_meta"):
            try:
                city_meta = await _call_maybe_async(cities_pref.get_city_meta, city_id) or {}
            except Exception as exc:
                log.warning("cities_pref.get_city_meta failed: %s", exc)
        if not city_meta:
            city_meta = CITIES.get(city_id, {"id": city_id, "name": city_id})

        # Moon context (always available — uses local lunar module)
        try:
            moon = get_cycle_context()
        except Exception as exc:
            log.warning("get_cycle_context failed: %s", exc)
            moon = {"error": str(exc)}

        if agent is None:
            # Degraded response — moon + city only, agent-dependent fields empty
            return {
                "city": city_meta,
                "moon": moon,
                "sun": {"error": "calendar_agent unavailable"},
                "events_7d": {"events": [], "count": 0, "generated_at": _utc_iso()},
                "events_30d": {"events": [], "count": 0, "generated_at": _utc_iso()},
                "todos_7d": {"todos": [], "count": 0, "generated_at": _utc_iso()},
                "todos_30d": {"todos": [], "count": 0, "generated_at": _utc_iso()},
                "agent_status": {"available": False, "reason": "calendar_agent module unavailable"},
                "generated_at": _utc_iso(),
            }

        # Run agent sub-calls in parallel
        async def _safe(coro, fallback):
            try:
                return await coro
            except Exception as exc:
                log.warning("dashboard sub-call failed: %s", exc)
                return fallback

        sun_task = _safe(
            _call_maybe_async(agent.get_sun_state, city_id), {"error": "sun fetch failed"}
        )
        events7_task = _safe(
            _call_maybe_async(agent.compile_events, city_id, 7), {"events": [], "count": 0}
        )
        events30_task = _safe(
            _call_maybe_async(agent.compile_events, city_id, 30), {"events": [], "count": 0}
        )
        todos7_task = _safe(
            _call_maybe_async(agent.get_todos, city_id, 7), {"todos": [], "count": 0}
        )
        todos30_task = _safe(
            _call_maybe_async(agent.get_todos, city_id, 30), {"todos": [], "count": 0}
        )
        status_task = _safe(
            _call_maybe_async(getattr(agent, "get_status", lambda: {"available": True})),
            {"available": True, "warning": "no get_status method"},
        )

        sun, events7, events30, todos7, todos30, agent_status = await asyncio.gather(
            sun_task, events7_task, events30_task, todos7_task, todos30_task, status_task
        )

        def _shape_events(d):
            if not isinstance(d, dict):
                d = {"events": d or []}
            evs = d.get("events", []) or []
            return {
                "events": evs,
                "count": d.get("count", len(evs)),
                "generated_at": d.get("generated_at", _utc_iso()),
            }

        def _shape_todos(d):
            if not isinstance(d, dict):
                d = {"todos": d or []}
            tds = d.get("todos", []) or []
            return {
                "todos": tds,
                "count": d.get("count", len(tds)),
                "generated_at": d.get("generated_at", _utc_iso()),
            }

        return {
            "city": city_meta,
            "moon": moon,
            "sun": sun if isinstance(sun, dict) else {"value": sun},
            "events_7d": _shape_events(events7),
            "events_30d": _shape_events(events30),
            "todos_7d": _shape_todos(todos7),
            "todos_30d": _shape_todos(todos30),
            "agent_status": agent_status
            if isinstance(agent_status, dict)
            else {"value": agent_status},
            "generated_at": _utc_iso(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("calendar/dashboard failed")
        return _err_response(f"dashboard failed: {exc}")


# ── City preference ──────────────────────────────────────────────────


@calendar_router.post("/city/select")
async def calendar_city_select(request: Request, authorization: str = Header(default="")):
    """Set the default city for calendar views."""
    _verify_strike_token(authorization)
    try:
        body = await request.json()
        if not isinstance(body, dict) or not body.get("city_id"):
            raise HTTPException(status_code=400, detail="Missing required field: city_id")
        city_id = str(body["city_id"]).strip()

        cities_pref = _get_cities_pref_or_none()
        if cities_pref is None:
            return _err_response("cities_pref module unavailable", 503)

        if hasattr(cities_pref, "set_preferred_city"):
            await _call_maybe_async(cities_pref.set_preferred_city, city_id)
        else:
            return _err_response("cities_pref.set_preferred_city missing", 503)

        # Resolve metadata to echo back
        city_meta: Dict[str, Any] = {}
        if hasattr(cities_pref, "get_city_meta"):
            try:
                city_meta = await _call_maybe_async(cities_pref.get_city_meta, city_id) or {}
            except Exception as exc:
                log.warning("cities_pref.get_city_meta failed: %s", exc)
        if not city_meta:
            city_meta = CITIES.get(city_id, {"id": city_id, "name": city_id})

        return {
            "status": "set",
            "city_id": city_id,
            "city_meta": city_meta,
            "generated_at": _utc_iso(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("calendar/city/select failed")
        return _err_response(f"city select failed: {exc}")


@calendar_router.get("/city/current")
async def calendar_city_current(authorization: str = Header(default="")):
    """Return the currently selected default city."""
    _verify_strike_token(authorization)
    try:
        cities_pref = _get_cities_pref_or_none()
        if cities_pref is None:
            return _err_response("cities_pref module unavailable", 503)

        if not hasattr(cities_pref, "get_default_city"):
            return _err_response("cities_pref.get_default_city missing", 503)

        city_id = await _call_maybe_async(cities_pref.get_default_city)
        city_id = str(city_id) if city_id else "edmonton"

        city_meta: Dict[str, Any] = {}
        if hasattr(cities_pref, "get_city_meta"):
            try:
                city_meta = await _call_maybe_async(cities_pref.get_city_meta, city_id) or {}
            except Exception as exc:
                log.warning("cities_pref.get_city_meta failed: %s", exc)
        if not city_meta:
            city_meta = CITIES.get(city_id, {"id": city_id, "name": city_id})

        return {
            "city_id": city_id,
            "city_meta": city_meta,
            "generated_at": _utc_iso(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("calendar/city/current failed")
        return _err_response(f"city current failed: {exc}")


# ── Force refresh ────────────────────────────────────────────────────


@calendar_router.post("/refresh")
async def calendar_refresh(request: Request, authorization: str = Header(default="")):
    """Force a calendar_agent.scan_cycle() to run now (no cache)."""
    _verify_strike_token(authorization)
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        city_id = body.get("city_id")

        agent = _get_calendar_agent_or_none()
        if agent is None:
            return _err_response("calendar_agent module unavailable", 503)

        if not hasattr(agent, "scan_cycle"):
            return _err_response("calendar_agent.scan_cycle missing", 503)

        if city_id:
            try:
                summary = await _call_maybe_async(agent.scan_cycle, city_id)
            except TypeError:
                # scan_cycle may not accept city_id
                summary = await _call_maybe_async(agent.scan_cycle)
        else:
            summary = await _call_maybe_async(agent.scan_cycle)

        if not isinstance(summary, dict):
            summary = {"result": summary}
        summary.setdefault("generated_at", _utc_iso())
        if city_id:
            summary.setdefault("city_id", city_id)
        return summary
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("calendar/refresh failed")
        return _err_response(f"refresh failed: {exc}")
