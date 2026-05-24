"""Pump endpoints (/pump/*) extracted from routes.py.

This is the SOLE strike point into the NCL brain from NATRIX:

    POST /pump                       — receive pump prompt (rate-limited) [AUTH]
    GET  /pump/pending               — list pumps awaiting approval        [AUTH]
    GET  /pump/health                — pipeline health + file-side telemetry [AUTH]
    GET  /pump/review/{pump_id}      — review proposed mandates before approving [AUTH]
    POST /pump/approve/{pump_id}     — NATRIX approves + dispatches mandates [AUTH]
    POST /pump/reject/{pump_id}      — NATRIX rejects + cancels pending mandates [AUTH]

The pump → council → mandate pipeline was MERGED into the Brain on
2026-05-23. ``POST /pump`` with ``auto_flow=True`` (default) drives the
full pipeline in-process via ``brain.receive_pump_prompt``; no external
orchestrator polls the file queue anymore.

W10C-4 (2026-05-24): Converted from the legacy ``from .. import routes as
_routes`` lazy-import pattern to FastAPI ``Depends()`` injection. Mirrors
the W8-A8 / W10B-3 / W10C-2 / W10C-3 conversions of routers/feedback.py,
routers/system.py, routers/journal.py, routers/mandate.py,
routers/memory.py, routers/portfolio.py. The ``NCLBrain`` singleton now
arrives via ``Depends(get_brain)`` and auth flows through
``verify_strike_token_dep`` rather than the inline header read.

The four pump-specific module-level helpers — ``_check_rate_limit``,
``_pump_count``, ``_PUMP_QUALITY``, ``_maybe_limit`` — still live in
:mod:`runtime.api.routes` and are accessed via a single lazy import inside
each handler that needs them. They are *helpers / process-local state*, not
singletons, so no DI factory was added for them; promoting them is a
separate decision out of scope for this wave. The slowapi rate-limit
decorator on ``POST /pump`` continues to resolve at import time via
``_pump_rate_limit()`` so slowapi sees the parent module's limiter.
"""

from __future__ import annotations  # noqa: I001

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from ...ncl_brain.models import PumpPrompt
from ..deps import get_brain, verify_strike_token_dep

log = logging.getLogger(__name__)

router = APIRouter(tags=["pump"])


class ApprovalRequest(BaseModel):
    """Request body for pump approval."""
    mandate_ids: list[str] | None = None  # None = approve all
    modifications: dict[str, dict] | None = None  # mandate_id → field overrides


class RejectionRequest(BaseModel):
    """Request body for pump rejection."""
    reason: str = ""


# Resolve the slowapi 10/minute decorator at import time. The parent
# ``routes.py`` constructs ``_limiter`` + ``_maybe_limit`` before it calls
# ``register_routers(app)``, so this lazy import is safe. Falls back to a
# no-op decorator if slowapi isn't installed.
def _pump_rate_limit():
    try:
        from .. import routes as _routes
        return _routes._maybe_limit("10/minute")
    except Exception:
        def _noop(fn):
            return fn
        return _noop


# Pump Prompt endpoint — THE SOLE STRIKE POINT INTO NCL
@router.post("/pump")
@_pump_rate_limit()
async def receive_pump_prompt(
    request: Request,
    body: dict = Body(...),
    auto_flow: bool = Query(default=True, description="Run council→mandate pipeline (stops before NCC dispatch)"),  # noqa: E501
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Receive pump prompt from iPhone via Grok or Command Center dashboard.

    Accepts two body formats:
    1. Full PumpPrompt: { prompt_id, source, intent, context, ... }
    2. Simple dashboard: { prompt: "text" }  (auto-generates PumpPrompt fields)

    This is the SOLE entry point into the NCL brain from NATRIX.
    Authenticated via Bearer token (STRIKE_AUTH_TOKEN).

    When auto_flow=True (default), runs the pipeline UP TO mandate creation:
    1. Store pump in memory
    2. Spawn council session (Claude chairs, Grok/Gemini/GPT debate)
    3. Extract mandates from council consensus
    4. Create mandates as PENDING_APPROVAL in Paperclip
    5. STOPS — returns council output + proposed mandates for NATRIX review

    NATRIX then calls /pump/approve/{pump_id} to dispatch to NCC,
    or /pump/reject/{pump_id} to discard.
    """
    from .. import routes as _routes
    _routes._check_rate_limit(request)

    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Validate body has at least a prompt or intent
    if not body.get("prompt") and not body.get("intent"):
        _routes._pump_count("rejected")
        raise HTTPException(status_code=400, detail="Missing required field: 'prompt' or 'intent'")

    # Accept simple { "prompt": "text" } from dashboard and convert to PumpPrompt
    if "prompt" in body and "prompt_id" not in body:
        import uuid
        prompt = PumpPrompt(
            prompt_id=f"pump-dash-{uuid.uuid4().hex[:8]}",
            source="command-center-dashboard",
            intent=body["prompt"][:200],
            context={"raw_prompt": body["prompt"], "origin": "dashboard"},
            urgency=body.get("urgency", "normal"),
        )
    else:
        try:
            prompt = PumpPrompt(**body)
        except Exception as e:
            _routes._pump_count("rejected")
            raise HTTPException(status_code=422, detail=f"Invalid PumpPrompt: {e}")

    # Quality: accepted pump
    _routes._pump_count("submitted", prompt.prompt_id)

    if auto_flow:
        # Council pipeline can run for several minutes (multi-LLM rebuttal rounds
        # falling back to local Ollama). Detach so callers (e.g. pump_watcher)
        # don't block past their HTTP timeout. Errors are logged via the
        # task-done callback installed in the autonomous scheduler pattern.
        async def _run_auto_flow() -> None:
            try:
                await brain.receive_pump_prompt(prompt, auto_flow=True)
            except Exception:
                log.exception(
                    f"[/pump] background auto_flow failed for {prompt.prompt_id}"
                )

        task = asyncio.create_task(_run_auto_flow())

        def _pump_task_done(t: asyncio.Task) -> None:
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                log.error(
                    f"[/pump] auto_flow task for {prompt.prompt_id} died: {exc!r}"
                )

        task.add_done_callback(_pump_task_done)
        return {
            "pump_id": prompt.prompt_id,
            "intent": prompt.intent,
            "urgency": prompt.urgency,
            "mode": "background",
            "status": "accepted",
        }

    result = await brain.receive_pump_prompt(prompt, auto_flow=False)
    return result


# ---------------------------------------------------------------------------
# NATRIX Approval Gate — Review / Approve / Reject before NCC dispatch
# ---------------------------------------------------------------------------


@router.get("/pump/pending")
async def list_pending_pumps(
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    List all pump prompts awaiting NATRIX approval.

    Returns pump IDs, proposed mandate counts, and council session refs.
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    pending = {}
    async with brain._pending_dispatches_lock:
        snapshot = list(brain._pending_dispatches.items())
    for pump_id, data in snapshot:
        pending[pump_id] = {
            "council_session_id": data.get("council_session_id"),
            "mandates_proposed": len(data.get("mandates", [])),
            "created_at": data.get("created_at"),
        }

    return {"pending_count": len(pending), "pending": pending}


@router.get("/pump/health")
async def pump_health(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Per-process pump-pipeline quality telemetry.

    Exposes accepted/rejected counters + last-submission time so the iOS
    Dashboard (or a watchdog) can tell whether the pipeline is actually
    flowing — pipelines that stop accepting pumps for >24h are a P0 signal.
    Also reads ``mandate-generation/input/`` directly to confirm the
    file-side pump path (used by relay_server) is also alive.
    """
    from .. import routes as _routes

    _PUMP_QUALITY = _routes._PUMP_QUALITY  # noqa: N806

    # File-side health: count files in mandate-generation/{input,processed,failed}
    file_health: dict = {}
    try:
        ncl_base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
        for sub in ("input", "processed", "failed"):
            d = ncl_base / "mandate-generation" / sub
            if d.exists():
                files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
                file_health[sub] = {
                    "count": len(files),
                    "newest_at": datetime.fromtimestamp(files[0].stat().st_mtime, tz=timezone.utc).isoformat() if files else None,  # noqa: E501
                    "newest_name": files[0].name if files else None,
                }
            else:
                file_health[sub] = {"count": 0, "newest_at": None, "newest_name": None}
    except Exception as e:
        file_health = {"error": str(e)}

    return {
        "submitted_total": _PUMP_QUALITY["submitted_total"],
        "submitted_today": _PUMP_QUALITY["submitted_today"],
        "rejected_total": _PUMP_QUALITY["rejected_total"],
        "rejected_today": _PUMP_QUALITY["rejected_today"],
        "last_submission_at": _PUMP_QUALITY["last_submission_at"],
        "last_submission_id": _PUMP_QUALITY["last_submission_id"],
        "acceptance_pct": (
            round(100.0 * _PUMP_QUALITY["submitted_total"] /
                  max(1, _PUMP_QUALITY["submitted_total"] + _PUMP_QUALITY["rejected_total"]), 1)
        ),
        "file_pipeline": file_health,
    }


@router.get("/pump/review/{pump_id}")
async def review_pump(
    pump_id: str,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Review proposed mandates from a pump prompt before approving.

    Returns full council output + proposed mandates + consensus data
    so NATRIX can make an informed decision.
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    async with brain._pending_dispatches_lock:
        pending = brain._pending_dispatches.get(pump_id)
    if not pending:
        raise HTTPException(status_code=404, detail=f"No pending dispatch for pump {pump_id}")

    # Get council session for full context
    session_id = pending.get("council_session_id", "")
    session = brain.council_sessions.get(session_id)

    review = {
        "pump_id": pump_id,
        "created_at": pending.get("created_at"),
        "proposed_mandates": pending.get("mandates", []),
    }

    if session:
        review["council"] = {
            "session_id": session.session_id,
            "topic": session.topic,
            "synthesis": session.synthesis,
            "consensus": session.consensus,
            "recommendations": session.recommendations,
            "dissents": session.dissents,
            "consensus_score": {
                "agreement_pct": session.consensus_score.agreement_pct,
                "convergence_delta": session.consensus_score.convergence_delta,
                "confidence_weighted": session.consensus_score.confidence_weighted,
                "threshold_met": session.consensus_score.threshold_met,
                "dissent_strength": session.consensus_score.dissent_strength,
            } if session.consensus_score else None,
        }

    review["actions"] = {
        "approve_all": f"POST /pump/approve/{pump_id}",
        "approve_some": f"POST /pump/approve/{pump_id} with body: {{\"mandate_ids\": [...]}}",
        "modify_and_approve": f"POST /pump/approve/{pump_id} with body: {{\"modifications\": {{\"mandate_id\": {{\"priority\": N}}}}}}",  # noqa: E501
        "reject": f"POST /pump/reject/{pump_id}",
    }

    return review


@router.post("/pump/approve/{pump_id}")
async def approve_pump(
    pump_id: str,
    body: ApprovalRequest | None = None,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    NATRIX approves proposed mandates and dispatches to NCC.

    Nothing reaches NCC without this explicit approval.

    Options:
    - Empty body: approve all proposed mandates as-is
    - mandate_ids: approve only specific mandates (rest get cancelled)
    - modifications: override fields before dispatch (priority, objective, etc.)

    Args:
        pump_id: Pump prompt ID
        body: Optional approval constraints
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    result = await brain.approve_and_dispatch(
        pump_id=pump_id,
        approved_mandate_ids=body.mandate_ids if body and body.mandate_ids else None,
        modifications=body.modifications if body and body.modifications else None,
    )

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result


@router.post("/pump/reject/{pump_id}")
async def reject_pump(
    pump_id: str,
    body: RejectionRequest | None = None,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    NATRIX rejects proposed mandates — nothing dispatched to NCC.

    All pending mandates for this pump are cancelled.
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    result = await brain.reject_pump(
        pump_id=pump_id,
        reason=body.reason if body else "",
    )

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result
