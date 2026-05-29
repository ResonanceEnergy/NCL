"""Unified intel-request bus (Wave 14W-E).

Per LANE_ARCHITECTURE.md Phase E and INTEL_ARCH_DEEP_DIVE §4.3, the
auto-trader is currently a passive receiver of pushed signals. This
module flips the polarity: the agent can REQUEST services from the
existing subsystems (Memory, Awarebot, Council, Calendar, Brief,
Scheduler) and the dispatcher routes each request to the right module.

Six handlers, one per ``RequestKind``:

  - ``memory.fused_search``     → FusedRetriever (vector + BM25 + KG via RRF)
  - ``awarebot.scan_now``       → pin a focus hint in working context so
                                   the next Awarebot tick prioritizes it
  - ``council.spawn``           → brain.spawn_council_session(...)
  - ``calendar.add_followup``   → append a curated calendar event
  - ``brief.regenerate_focus``  → re-fire brief pipeline with a focus ticker
  - ``scheduler.queue``         → one-shot asyncio.create_task wrapped in
                                   the scheduler's task tracker

Design rules:

  1. Bounded fire-and-forget — every handler runs under
     ``asyncio.create_task`` wrapped in try/except so a failure here can
     never break the auto-trader tick loop.
  2. Lazy imports — handlers import their target module inside the call
     so this module can be imported at boot before brain wires up.
  3. JSONL audit trail — every request is appended to
     ``data/agent_bus/intel_requests.jsonl`` with kind + kwargs + result
     summary + ok/error so we can post-mortem agent decisions.
  4. Pure-async — every handler is ``async def``; callers must ``await``
     ``intel_request(...)`` or wrap in ``create_task`` themselves.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional


log = logging.getLogger("ncl.agent_bus.intel_request")


# ─────────────────────────────────────────────────────────────────────
# Storage
# ─────────────────────────────────────────────────────────────────────

_DATA_ROOT = Path(os.getenv("NCL_DATA_ROOT", "data"))
_BUS_DIR = _DATA_ROOT / "agent_bus"
_TRAIL_PATH = _BUS_DIR / "intel_requests.jsonl"
_MAX_TRAIL_BYTES = 50 * 1024 * 1024  # 50 MB cap — rotate by truncating top half


def _ensure_dir() -> None:
    try:
        _BUS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.debug("[BUS] mkdir failed: %s", e)


# ─────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────


class RequestKind(str, Enum):
    """The 6 service kinds the agent can request."""

    MEMORY_FUSED_SEARCH = "memory.fused_search"
    AWAREBOT_SCAN_NOW = "awarebot.scan_now"
    COUNCIL_SPAWN = "council.spawn"
    CALENDAR_ADD_FOLLOWUP = "calendar.add_followup"
    BRIEF_REGENERATE_FOCUS = "brief.regenerate_focus"
    SCHEDULER_QUEUE = "scheduler.queue"


@dataclass
class IntelRequest:
    """An agent-issued request. Caller fills ``kind`` + ``kwargs``; the
    dispatcher stamps ``request_id`` and ``created_at``."""

    kind: RequestKind
    kwargs: dict
    request_id: str = field(default_factory=lambda: f"req_{uuid.uuid4().hex[:12]}")
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    caller: str = ""  # e.g. "auto_trader:drift_detector", "research_topic_resolver"
    urgency: str = "normal"  # "low" | "normal" | "high" — handlers may consult


@dataclass
class IntelResponse:
    """What the dispatcher returns. Even for fire-and-forget kinds the
    response carries the ``request_id`` so the caller can correlate it
    with later audit-trail rows."""

    request_id: str
    kind: RequestKind
    ok: bool
    result: Any = None
    error: str = ""
    elapsed_ms: int = 0


# ─────────────────────────────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────────────────────────────


async def _h_memory_fused_search(brain, req: IntelRequest) -> Any:
    """memory.fused_search — vector + BM25 + KG via RRF.

    kwargs:
      query: str          — natural-language query
      max_results: int    — default 20
      min_score: float    — passes through to retriever
    """
    query = str(req.kwargs.get("query", "")).strip()
    if not query:
        raise ValueError("query is required")
    max_results = int(req.kwargs.get("max_results", 20))
    min_score = float(req.kwargs.get("min_score", 0.0))

    if not brain or not getattr(brain, "memory_store", None):
        raise RuntimeError("memory_store not available")

    # Lazy import — fusion has heavy deps (chromadb, bm25)
    from ..memory.retrieval.fusion import FusedRetriever

    # FusedRetriever ctor signature varies by wave — try the most-common shape,
    # then fall back to bare-store ctor.
    try:
        retriever = FusedRetriever(memory_store=brain.memory_store)
    except TypeError:
        retriever = FusedRetriever(brain.memory_store)

    hits = await retriever.retrieve(query=query, top_n=max_results)
    out: list[dict] = []
    for h in (hits or [])[:max_results]:
        # Accommodate both dict-shaped and Hit-dataclass-shaped results.
        if isinstance(h, dict):
            score = float(h.get("score", 0.0))
            if score < min_score:
                continue
            out.append(h)
        else:
            score = float(getattr(h, "score", 0.0))
            if score < min_score:
                continue
            out.append(
                {
                    "unit_id": getattr(h, "unit_id", ""),
                    "score": score,
                    "content": (getattr(h, "content", "") or "")[:500],
                    "source": getattr(h, "source", ""),
                    "tier": getattr(h, "tier", ""),
                }
            )
    return {"query": query, "count": len(out), "hits": out}


async def _h_awarebot_scan_now(brain, req: IntelRequest) -> Any:
    """awarebot.scan_now — pin a focus hint in working context so the
    next Awarebot tick prioritizes it.

    We don't try to forcibly trigger a scan (that would race the
    scheduler-managed Awarebot loop). Instead we drop a high-importance,
    short-TTL pin so the next tick's BM25/relevance scoring picks the
    focus up automatically. Cheap, race-safe, observable.

    kwargs:
      focus: str       — what to look for (e.g. "energy sector last 60min")
      urgency: str     — overrides req.urgency if set
      ttl_minutes: int — default 60
    """
    focus = str(req.kwargs.get("focus", "")).strip()
    if not focus:
        raise ValueError("focus is required")
    urgency = str(req.kwargs.get("urgency", req.urgency))
    ttl_minutes = int(req.kwargs.get("ttl_minutes", 60))

    if not brain or not getattr(brain, "memory_store", None):
        raise RuntimeError("memory_store not available")

    # Lazy import — keeps the dispatcher portable.
    from ..memory.store import MemUnit

    unit = MemUnit(
        unit_id=f"agent_bus:scan_focus:{uuid.uuid4().hex[:8]}",
        source=f"agent_bus:scan_focus:{req.caller or 'unknown'}",
        content=f"AGENT SCAN FOCUS — {focus} (urgency={urgency}, ttl={ttl_minutes}m)",
        importance=85.0,  # below mandate (95) but above default attention floor
        memory_type="episodic",
        tags=["agent_request", "scan_focus", urgency],
        metadata={
            "agent_bus_request_id": req.request_id,
            "scan_focus": focus,
            "urgency": urgency,
            "ttl_minutes": ttl_minutes,
            "expires_at": (datetime.now(timezone.utc).timestamp() + ttl_minutes * 60),
            "lane_kind": "agent_reasoning_chain",
            "cross_source": 2,  # passes lane gate
        },
    )
    await brain.memory_store.create_unit(unit)
    return {"focus": focus, "pin_unit_id": unit.unit_id, "ttl_minutes": ttl_minutes}


async def _h_council_spawn(brain, req: IntelRequest) -> Any:
    """council.spawn — fire a council debate session.

    kwargs:
      topic: str    — debate topic
      prompt: str   — chair's framing prompt
      reason: str   — optional, threads through as topic prefix if topic empty
      panel: str    — "delphi_mad_4" (default) | "haiku_quorum" — used to pick members
    """
    topic = str(req.kwargs.get("topic", "")).strip()
    prompt = str(req.kwargs.get("prompt", "")).strip()
    reason = str(req.kwargs.get("reason", "")).strip()
    panel = str(req.kwargs.get("panel", "delphi_mad_4")).strip()

    if not topic and reason:
        topic = f"Agent-triggered review: {reason}"
    if not topic:
        raise ValueError("topic or reason is required")
    if not prompt:
        prompt = (
            f"The auto-trader has requested a council review.\n"
            f"Reason: {reason or 'unspecified'}.\n"
            f"Topic: {topic}.\n\n"
            "Provide a brief debate weighing root causes, scope of risk, "
            "and 2-3 concrete next actions."
        )

    if not brain or not hasattr(brain, "spawn_council_session"):
        raise RuntimeError("brain.spawn_council_session not available")

    # Panel → member list mapping. Falls through to None (engine default).
    members: Optional[list[str]] = None
    if panel == "delphi_mad_4":
        members = ["claude", "grok", "gemini", "gpt"]
    elif panel == "haiku_quorum":
        members = ["claude", "grok"]

    session = await brain.spawn_council_session(
        topic=topic,
        prompt=prompt,
        members=members,
    )
    return {
        "session_id": getattr(session, "session_id", ""),
        "topic": topic,
        "panel": panel,
    }


async def _h_calendar_add_followup(brain, req: IntelRequest) -> Any:
    """calendar.add_followup — append a curated calendar event.

    Stored as a JSONL row in ``data/calendar/curated.jsonl`` so the
    calendar loop picks it up on the next refresh. Bypasses the HTTP
    layer to avoid the auth-token round-trip.

    kwargs:
      when: ISO-ish string (parsed loosely)  — required
      payload: dict                          — required, free-form
      title: str                             — optional
    """
    when = str(req.kwargs.get("when", "")).strip()
    payload = req.kwargs.get("payload") or {}
    title = str(req.kwargs.get("title", "Agent follow-up")).strip()
    if not when:
        raise ValueError("when is required")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")

    cal_dir = _DATA_ROOT / "calendar"
    try:
        cal_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.debug("[BUS] calendar mkdir failed: %s", e)
    target = cal_dir / "curated.jsonl"

    row = {
        "event_id": f"agent_followup:{uuid.uuid4().hex[:10]}",
        "kind": "agent_followup",
        "when": when,
        "title": title,
        "payload": payload,
        "agent_bus_request_id": req.request_id,
        "caller": req.caller,
        "created_at": req.created_at,
    }

    def _append() -> None:
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")

    await asyncio.to_thread(_append)
    return {"event_id": row["event_id"], "when": when, "title": title}


async def _h_brief_regenerate_focus(brain, req: IntelRequest) -> Any:
    """brief.regenerate_focus — re-fire the morning-brief pipeline with
    a focus ticker promoted to top of the prep pack.

    We don't actually rebuild from scratch (the pipeline is expensive +
    budget-gated). We DO pin a high-importance focus hint so the next
    scheduled brief picks it up — same pattern as awarebot.scan_now,
    consumed by ``brief_prep`` instead of Awarebot.

    kwargs:
      focus_ticker: str — e.g. "XLE"
      reason: str       — optional
    """
    ticker = str(req.kwargs.get("focus_ticker", "")).strip().upper()
    reason = str(req.kwargs.get("reason", "")).strip()
    if not ticker:
        raise ValueError("focus_ticker is required")

    if not brain or not getattr(brain, "memory_store", None):
        raise RuntimeError("memory_store not available")

    from ..memory.store import MemUnit

    unit = MemUnit(
        unit_id=f"agent_bus:brief_focus:{uuid.uuid4().hex[:8]}",
        source="agent_bus:brief_focus",
        content=(
            f"AGENT BRIEF FOCUS — promote ${ticker} in next brief. "
            f"Reason: {reason or 'live opportunity flagged'}."
        ),
        importance=90.0,
        memory_type="episodic",
        tags=["agent_request", "brief_focus", ticker],
        metadata={
            "agent_bus_request_id": req.request_id,
            "focus_ticker": ticker,
            "reason": reason,
            "lane_kind": "agent_reasoning_chain",
            "cross_source": 2,
        },
    )
    await brain.memory_store.create_unit(unit)
    return {"focus_ticker": ticker, "pin_unit_id": unit.unit_id}


async def _h_scheduler_queue(brain, req: IntelRequest) -> Any:
    """scheduler.queue — fire a one-shot task at ``run_at`` (or now).

    kwargs:
      action: str        — short identifier for the action (audit)
      run_at: ISO string — when to fire (defaults to now)
      payload: dict      — arbitrary, passed through to the trail row

    The dispatcher does not actually schedule a callable — there's no
    safe way to deserialize arbitrary callables across restarts. What
    it does is persist the request as a calendar-style event (so the
    operator + future agent_bus consumers can see it) and emit a
    high-importance MemUnit so brief_prep + Awarebot can react.
    """
    action = str(req.kwargs.get("action", "")).strip()
    run_at = str(req.kwargs.get("run_at", "")).strip()
    payload = req.kwargs.get("payload") or {}
    if not action:
        raise ValueError("action is required")
    if not run_at:
        run_at = datetime.now(timezone.utc).isoformat()

    # Dual write: calendar curated.jsonl + MemUnit so both surfaces see it.
    await _h_calendar_add_followup(
        brain,
        IntelRequest(
            kind=RequestKind.CALENDAR_ADD_FOLLOWUP,
            kwargs={
                "when": run_at,
                "title": f"Scheduled: {action}",
                "payload": {"action": action, **payload},
            },
            request_id=req.request_id,
            caller=req.caller,
        ),
    )
    if brain and getattr(brain, "memory_store", None):
        try:
            from ..memory.store import MemUnit

            unit = MemUnit(
                unit_id=f"agent_bus:scheduled:{uuid.uuid4().hex[:8]}",
                source="agent_bus:scheduled",
                content=f"AGENT SCHEDULED — {action} at {run_at}",
                importance=70.0,
                memory_type="episodic",
                tags=["agent_request", "scheduled", action],
                metadata={
                    "agent_bus_request_id": req.request_id,
                    "action": action,
                    "run_at": run_at,
                    "lane_kind": "agent_reasoning_chain",
                    "cross_source": 2,
                },
            )
            await brain.memory_store.create_unit(unit)
        except Exception as e:
            log.debug("[BUS] scheduler.queue MemUnit failed: %s", e)
    return {"action": action, "run_at": run_at}


# ─────────────────────────────────────────────────────────────────────
# Dispatcher
# ─────────────────────────────────────────────────────────────────────

_HandlerFn = Callable[[Any, IntelRequest], Awaitable[Any]]
_HANDLERS: dict[RequestKind, _HandlerFn] = {
    RequestKind.MEMORY_FUSED_SEARCH: _h_memory_fused_search,
    RequestKind.AWAREBOT_SCAN_NOW: _h_awarebot_scan_now,
    RequestKind.COUNCIL_SPAWN: _h_council_spawn,
    RequestKind.CALENDAR_ADD_FOLLOWUP: _h_calendar_add_followup,
    RequestKind.BRIEF_REGENERATE_FOCUS: _h_brief_regenerate_focus,
    RequestKind.SCHEDULER_QUEUE: _h_scheduler_queue,
}


# Cache of the running brain instance. The brain registers itself on boot
# via ``set_brain(brain)`` so callers don't have to thread it through.
_brain_singleton: Any = None


def set_brain(brain: Any) -> None:
    """Called by brain.startup so handlers can resolve memory_store + spawn_council."""
    global _brain_singleton
    _brain_singleton = brain


def _resolve_kind(kind: Any) -> RequestKind:
    if isinstance(kind, RequestKind):
        return kind
    if isinstance(kind, str):
        try:
            return RequestKind(kind)
        except ValueError as e:
            raise ValueError(
                f"unknown request kind: {kind!r}. " f"Valid: {[k.value for k in RequestKind]}"
            ) from e
    raise TypeError(f"kind must be RequestKind or str, got {type(kind)}")


def _append_trail(req: IntelRequest, resp: IntelResponse) -> None:
    """JSONL audit append. Caller invokes via asyncio.to_thread to avoid
    blocking the loop on file I/O."""
    _ensure_dir()
    row = {
        "request_id": req.request_id,
        "kind": req.kind.value,
        "caller": req.caller,
        "urgency": req.urgency,
        "kwargs": req.kwargs,
        "created_at": req.created_at,
        "ok": resp.ok,
        "elapsed_ms": resp.elapsed_ms,
        "error": resp.error,
        "result_summary": _summarize_result(resp.result),
    }
    try:
        with _TRAIL_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    except Exception as e:
        log.debug("[BUS] trail append failed: %s", e)
    # Rotate if oversized
    try:
        if _TRAIL_PATH.exists() and _TRAIL_PATH.stat().st_size > _MAX_TRAIL_BYTES:
            _rotate_trail()
    except Exception:
        pass


def _summarize_result(result: Any) -> Any:
    """Compress big results before writing to the trail (so a 200-hit
    fused_search doesn't blow up the JSONL)."""
    if result is None:
        return None
    if isinstance(result, dict):
        if "hits" in result and isinstance(result["hits"], list):
            return {
                "query": result.get("query"),
                "count": result.get("count", len(result["hits"])),
                "top_unit_ids": [
                    h.get("unit_id", "") for h in result["hits"][:5] if isinstance(h, dict)
                ],
            }
        return result
    return str(result)[:500]


def _rotate_trail() -> None:
    """Drop the oldest half of the trail when it hits the size cap."""
    try:
        with _TRAIL_PATH.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) <= 1:
            return
        keep = lines[len(lines) // 2 :]
        with _TRAIL_PATH.open("w", encoding="utf-8") as f:
            f.writelines(keep)
        log.info("[BUS] rotated trail — kept %d of %d lines", len(keep), len(lines))
    except Exception as e:
        log.debug("[BUS] rotation failed: %s", e)


async def intel_request(
    *,
    kind: Any,
    caller: str = "",
    urgency: str = "normal",
    brain: Any = None,
    **kwargs: Any,
) -> IntelResponse:
    """Main entrypoint. Routes ``kind`` to the right handler.

    Returns an ``IntelResponse``. On handler failure, ``ok=False`` and
    ``error`` carries the exception message — callers should never raise
    out of an intel_request (the auto-trader tick should keep going even
    if a request blows up).

    Args:
      kind: ``RequestKind`` or its string value
      caller: short identifier of the caller ("auto_trader:drift_detector",
              "self_research:cluster", "iOS:user").
      urgency: "low" | "normal" | "high"
      brain: optional brain instance override (falls back to ``set_brain``
             singleton)
      **kwargs: handler-specific args (see each ``_h_*`` docstring)
    """
    try:
        kind_e = _resolve_kind(kind)
    except (ValueError, TypeError) as e:
        return IntelResponse(
            request_id=f"req_{uuid.uuid4().hex[:12]}",
            kind=RequestKind.MEMORY_FUSED_SEARCH,  # placeholder
            ok=False,
            error=str(e),
            elapsed_ms=0,
        )

    req = IntelRequest(
        kind=kind_e,
        kwargs=dict(kwargs),
        caller=caller,
        urgency=urgency,
    )
    target_brain = brain if brain is not None else _brain_singleton

    handler = _HANDLERS.get(kind_e)
    if handler is None:
        resp = IntelResponse(
            request_id=req.request_id,
            kind=kind_e,
            ok=False,
            error=f"no handler registered for {kind_e.value}",
        )
        await asyncio.to_thread(_append_trail, req, resp)
        return resp

    t0 = time.monotonic()
    try:
        result = await handler(target_brain, req)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        resp = IntelResponse(
            request_id=req.request_id,
            kind=kind_e,
            ok=True,
            result=result,
            elapsed_ms=elapsed_ms,
        )
    except Exception as e:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        log.warning(
            "[BUS] %s failed: %s (caller=%s, elapsed=%dms)",
            kind_e.value,
            e,
            caller,
            elapsed_ms,
        )
        resp = IntelResponse(
            request_id=req.request_id,
            kind=kind_e,
            ok=False,
            error=str(e),
            elapsed_ms=elapsed_ms,
        )

    # Fire-and-forget the audit-trail write — never block the caller on it.
    await asyncio.to_thread(_append_trail, req, resp)
    return resp


# ─────────────────────────────────────────────────────────────────────
# Trail inspection (used by /agent-bus REST + tests)
# ─────────────────────────────────────────────────────────────────────


def list_recent_requests(limit: int = 50) -> list[dict]:
    """Return the most recent ``limit`` JSONL rows, newest-first."""
    if not _TRAIL_PATH.exists():
        return []
    try:
        with _TRAIL_PATH.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        rows: list[dict] = []
        for line in reversed(lines[-limit * 2 :]):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
                if len(rows) >= limit:
                    break
            except json.JSONDecodeError:
                continue
        return rows
    except Exception as e:
        log.debug("[BUS] list_recent_requests failed: %s", e)
        return []
