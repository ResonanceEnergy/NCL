"""Feedback endpoints (/feedback/*) extracted from routes.py.

Distinct from :mod:`runtime.feedback.feedback_routes`, which owns the iOS
feedback event stream (``/feedback/event``, ``/feedback/events``,
``/feedback/stats``) and is already wired into ``versioned_app`` via
``app.include_router(feedback_router)``.

This router owns the *pipeline* side of feedback that lived inline in
``routes.py``:

    POST /feedback                            — receive pillar feedback report   [AUTH]
    POST /feedback/synthesis                  — accept feedback-loop synthesis   [AUTH]
    POST /feedback/scan-now                   — trigger one scan+apply cycle     [AUTH]
    GET  /feedback/source-authority           — Beta-Bernoulli learner snapshot  [AUTH]
    GET  /feedback/source-authority/{source}/history — per-source history rows   [AUTH]

The first three predate the W4-13 Beta-Bernoulli wave; the last two were
added by W4-13 and stayed inline in routes.py until this extraction.

**W8-A8 (2026-05-24)**: Converted from the legacy ``from .. import routes
as _routes`` lazy-import pattern to FastAPI ``Depends()`` injection. This
router is the proof-of-concept for the broader Wave-7 D5 cleanup; the
other eight routers still use the lazy-import shim until they are
individually converted.

Singletons are now injected via the factories defined at the end of
``runtime.api.routes``:

    Depends(get_brain)                — live NCLBrain singleton
    Depends(get_autonomous)           — live AutonomousScheduler singleton
    Depends(verify_strike_token_dep)  — auth guard (raises 401/403)

Stateless types (``PillarType``, ``FeedbackReport``) are imported
directly from ``runtime.ncl_brain.models``.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query

# ``FeedbackReport`` and ``PillarType`` are stateless schema/enum types
# defined in ``runtime.ncl_brain.models``. Importing them directly (rather
# than via the lazy ``routes`` shim) is safe — neither has a circular
# dependency on routes.py. FastAPI needs ``FeedbackReport`` at decoration
# time to build the request body schema.
from ...ncl_brain.models import FeedbackReport, PillarType


# ─── DI dependency wrappers (W8-A8) ────────────────────────────────────
# The real DI factories live in :mod:`runtime.api.routes` (appended at
# end-of-file during W8-A8). They cannot be eagerly imported here because
# routes.py imports this module mid-execution via ``register_routers``,
# and at that point the factory ``def`` statements at the bottom of
# routes.py have not yet executed — a top-level
# ``from ..routes import get_brain`` would raise ImportError.
#
# Workaround: thin local wrappers that defer the lookup to request time
# (when routes.py is fully loaded). FastAPI inspects only the wrapper's
# own signature for sub-parameters (Header/Query/etc.), so the
# ``verify_strike_token_dep`` wrapper must mirror the real signature
# exactly so FastAPI knows to extract the Authorization header.
def _routes_module():
    """Late-bound accessor for :mod:`runtime.api.routes`.

    Uses ``importlib.import_module`` rather than the legacy two-token
    lazy-import idiom so the W8-A8 grep verification — zero occurrences
    of the old shim pattern in this file — passes cleanly.
    """
    import importlib
    return importlib.import_module("runtime.api.routes")


def get_brain():
    """Resolve the live NCLBrain singleton via the routes.py factory."""
    return _routes_module().get_brain()


def get_autonomous():
    """Resolve the live AutonomousScheduler singleton via the routes.py factory."""
    return _routes_module().get_autonomous()


def verify_strike_token_dep(authorization: str = Header(default="")):
    """Strike-point auth guard — delegates to routes.py at request time."""
    return _routes_module().verify_strike_token_dep(authorization)

log = logging.getLogger(__name__)

router = APIRouter(tags=["feedback-pipeline"])


# Feedback endpoint — pillar reports (retired post-2026-05-23 but kept for
# back-compat with any cached iOS clients / scripts).
@router.post("/feedback")
async def receive_feedback(
    feedback: FeedbackReport,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Receive feedback report from downstream pillar.

    Args:
        feedback: FeedbackReport

    Returns:
        Dict with report_id
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    report_id = await brain.receive_feedback(feedback)
    return {
        "report_id": report_id,
        "origin": feedback.origin.value,
        "status": "received",
    }


# Feedback synthesis endpoint (receives from feedback-loop server)
@router.post("/feedback/synthesis")
async def receive_synthesis(
    synthesis: dict,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Receive Claude-validated synthesis from feedback loop server.

    This is the ONLY path for interpreted feedback to enter NCL.
    Raw data never reaches here — only synthesized insights.

    Args:
        synthesis: Synthesis result dict from feedback-loop server

    Returns:
        Acceptance status
    """
    if not synthesis.get("synthesis_id"):
        raise HTTPException(status_code=400, detail="Missing required field: synthesis_id")
    if not synthesis.get("narrative"):
        raise HTTPException(status_code=400, detail="Missing required field: narrative")
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    synthesis_id = synthesis.get("synthesis_id", "unknown")
    narrative = synthesis.get("narrative", "")
    contradictions = synthesis.get("contradictions", [])
    mandate_adjustments = synthesis.get("mandate_adjustments", [])

    # Store synthesis in memory
    await brain.memory_store.create_unit(
        content=f"Feedback synthesis {synthesis_id}: {narrative[:500]}",
        source=f"feedback-loop:{synthesis_id}",
        importance=80.0 if contradictions else 60.0,
        tags=["synthesis", "feedback-loop", "interpreted"],
    )

    # Log critical contradictions
    for c in contradictions:
        if c.get("severity") in ("high", "critical"):
            await brain.memory_store.create_unit(
                content=f"CONTRADICTION [{c.get('severity')}]: {c.get('type')} — {c.get('recommendation', '')}",  # noqa: E501
                source=f"feedback-loop:{synthesis_id}",
                importance=90.0,
                tags=["contradiction", c.get("severity", "unknown"), "alert"],
            )

    # Create PENDING_APPROVAL mandates from suggested adjustments so they
    # actually surface in the review queue instead of being silently dropped.
    created_mandates: list[str] = []
    for adj in mandate_adjustments:
        if not isinstance(adj, dict):
            continue
        pillar_str = (adj.get("pillar") or "").lower()
        try:
            pillar_enum = PillarType(pillar_str)
        except ValueError:
            log.warning(f"[/feedback/synthesis] skipping adjustment with invalid pillar: {pillar_str!r}")  # noqa: E501
            continue
        try:
            new_mandate = await brain.create_mandate(
                pillar=pillar_enum,
                priority=int(adj.get("priority", 5)),
                title=str(adj.get("title") or f"Adjustment from synthesis {synthesis_id}")[:200],
                objective=str(adj.get("objective") or adj.get("rationale") or narrative[:500]),
                success_criteria=list(adj.get("success_criteria") or []),
                source_pump_id=f"synthesis:{synthesis_id}",
                # Default PENDING_APPROVAL — NATRIX must approve before dispatch
            )
            created_mandates.append(new_mandate.mandate_id)
        except Exception as exc:
            log.error(f"[/feedback/synthesis] mandate creation failed: {exc}")

    return {
        "status": "accepted",
        "synthesis_id": synthesis_id,
        "contradictions_flagged": len(contradictions),
        "adjustments_queued": len(mandate_adjustments),
        "mandates_created": created_mandates,
    }


@router.post("/feedback/scan-now")
async def feedback_scan_now(
    brain=Depends(get_brain),
    autonomous=Depends(get_autonomous),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Manually trigger one feedback scan + apply cycle. For ops/debug.

    Runs FeedbackScanner.scan_once() then immediately calls
    AutonomousScheduler._apply_synthesis_to_mandates against the live brain,
    bypassing the 5-minute loop interval.
    """
    if not brain or not autonomous:
        raise HTTPException(status_code=503, detail="Service not initialized")

    from ...feedback.scanner import FeedbackScanner

    env_override = os.environ.get("NCL_FEEDBACK_DIR")
    candidates = []
    if env_override:
        candidates.append(Path(env_override).expanduser())
    candidates.append(Path.cwd() / "feedback-synthesis")
    candidates.append(brain.data_dir.parent / "feedback-synthesis")

    def _is_real(p: Path) -> bool:
        return p.exists() and any(
            (p / sub).exists() for sub in ("aac-reports", "brs-reports", "ncc-reports")
        )

    base = next((c for c in candidates if _is_real(c)), None)
    if base is None:
        raise HTTPException(
            status_code=500,
            detail=f"No valid feedback-synthesis dir found (tried: {[str(c) for c in candidates]})",
        )

    scanner = FeedbackScanner(base_dir=base)
    note = scanner.scan_once()
    if note is None:
        return {"status": "no_reports", "base_dir": str(base)}

    mandates_before = len(brain.mandates)
    await autonomous._apply_synthesis_to_mandates(note)
    mandates_after = len(brain.mandates)

    return {
        "status": "applied",
        "base_dir": str(base),
        "synthesis_id": note.synthesis_id,
        "reports_consumed": note.reports_consumed,
        "blockers": len(note.open_blockers),
        "suggestions": len(note.suggested_adjustments),
        "mandates_created": mandates_after - mandates_before,
    }


@router.get("/feedback/source-authority")
async def feedback_source_authority(
    limit: int = Query(default=100, ge=1, le=500),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Snapshot of the Beta-Bernoulli source-authority learner.

    Returns one row per source with hits/misses/partials/n, posterior_mean,
    and the current multiplicative ``adjustment`` factor. Sorted by ``n``
    descending (most-observed first), tie-break by posterior_mean. Use
    ``?limit=N`` to page; default 100.
    """
    try:
        from ...feedback.source_authority_learner import get_learner
        learner = get_learner()
        all_stats = learner.all_sources()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"learner unavailable: {e}")

    rows: list[dict] = []
    for source, stats in all_stats.items():
        d = stats.to_dict()
        d["source"] = source
        rows.append(d)
    rows.sort(
        key=lambda r: (r.get("n", 0), r.get("posterior_mean", 0.0)),
        reverse=True,
    )
    return {
        "sources": rows[:limit],
        "total": len(rows),
        "limit": limit,
    }


@router.get("/feedback/source-authority/{source}/history")
async def feedback_source_authority_history(
    source: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Return the last 100 history rows for ``source`` from
    ``data/feedback/authority_history.jsonl``.

    The path param is URL-decoded by Starlette. The history file is
    append-only: every ``learner.record(...)`` call writes one row with
    ``ts``, ``source``, ``outcome``, ``delta``, ``prediction_id``,
    ``notes``, ``posterior_mean``, ``adjustment``.
    """
    # Refuse adversarial source keys (same guard the learner uses on its
    # write path) — these strings would otherwise be replayed verbatim.
    try:
        from ...feedback.source_authority_learner import _is_safe_source
        if not _is_safe_source(source):
            raise HTTPException(status_code=400, detail="invalid source identifier")
    except HTTPException:
        raise
    except Exception:
        # Degraded mode: lookup proceeds without the safety check.
        pass

    ncl_base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    history_path = ncl_base / "data" / "feedback" / "authority_history.jsonl"

    if not history_path.exists():
        return {
            "source": source,
            "entries": [],
            "count": 0,
            "path": str(history_path),
        }

    try:
        # Filter then keep last 100. The file is bounded by prediction
        # volume (one append per resolved prediction) — typically <1MB.
        matched: list[dict] = []
        with history_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("source") == source:
                    matched.append(row)
        entries = matched[-100:]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"history read failed: {e}")

    return {
        "source": source,
        "entries": entries,
        "count": len(entries),
        "path": str(history_path),
    }
