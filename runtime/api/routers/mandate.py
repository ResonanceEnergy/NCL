"""Mandate endpoints (/mandates/*) extracted from routes.py.

Owns the mandate lifecycle surface — create, list, detail, state
transitions, and purge:

    POST /mandates                       — create a mandate         [AUTH]
    GET  /mandates                       — list w/ filters          [AUTH]
    GET  /mandates/{mandate_id}          — mandate detail           [AUTH]
    POST /mandates/{mandate_id}/complete — mark completed           [AUTH]
    POST /mandates/{mandate_id}/approve  — transition to ACTIVE     [AUTH]
    POST /mandates/{mandate_id}/cancel   — transition to CANCELLED  [AUTH]
    POST /mandates/purge                 — purge stale mandates     [AUTH]

The pump → mandate pipeline was MERGED into the Brain on 2026-05-23.
``brain.create_mandate`` and the state-machine helpers
(``brain._persist_mandates_unlocked``, ``brain._policy_allows_dispatch``,
``brain._emergency_stop_engaged``) all live on the in-process Brain.
There is no pillar dispatcher anymore — these endpoints just shape
mandate state for the iOS Strike Point review screen.

The W5-05 retirement note: ``POST /mandate/{id}/requeue`` (singular form)
was removed entirely with the rest of the strike-point pipeline. The
FAILED → DRAFT escape pattern is preserved in
``archive/strike-point-pre-merge/PILLAR_DISPATCH.md`` if it ever needs
to come back.

W10B-3 (2026-05-24): Converted from the legacy ``from .. import routes as
_routes`` lazy-import pattern to FastAPI ``Depends()`` injection. Brain
arrives via :func:`runtime.api.deps.get_brain`; auth via
:func:`runtime.api.deps.verify_strike_token_dep`. The ``PillarType`` and
``MandateStatus`` enums are still imported directly from the models
layer — they have no dependency on routes.py.
"""

from __future__ import annotations  # noqa: I001

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel  # noqa: F401  (consumed by future schema additions)

# Pillar/MandateStatus enums are Pydantic-friendly types from the model
# layer, safe to import eagerly (no circular dep on routes.py).
from ...ncl_brain.models import MandateStatus, PillarType
from ..deps import get_brain, verify_strike_token_dep

log = logging.getLogger(__name__)

router = APIRouter(tags=["mandate"])


@router.post("/mandates")
async def create_mandate(
    pillar: str,
    priority: int,
    title: str,
    objective: str,
    success_criteria: list[str],
    deadline: str | None = None,
    source_pump_id: str | None = None,
    status: str | None = None,
    force: bool = False,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Create a new mandate.

    By default, mandates land in PENDING_APPROVAL and require explicit
    NATRIX approval before dispatch. Setting status='active' requires
    force=true, which is audit-logged. Any other status passes through
    the normal MWP state machine via brain.create_mandate.
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    if not (1 <= priority <= 10):
        raise HTTPException(status_code=400, detail="Priority must be between 1 and 10")

    # BRS/AAC retired 2026-05-23 per NATRIX directive — hard reject at the API.
    if pillar and pillar.strip().upper() in ("BRS", "AAC"):
        raise HTTPException(
            status_code=400,
            detail="pillar BRS/AAC is no longer supported",
        )
    try:
        pillar_enum = PillarType(pillar)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid pillar: {pillar}")

    # Resolve and validate status (default PENDING_APPROVAL post 2026-05-15 audit)
    if status is None:
        status_enum = MandateStatus.PENDING_APPROVAL
    else:
        try:
            status_enum = MandateStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    if status_enum == MandateStatus.ACTIVE and not force:
        raise HTTPException(
            status_code=400,
            detail="status=active requires force=true; default is pending_approval",
        )

    if status_enum == MandateStatus.ACTIVE and force:
        log.warning(
            f"[mandates] force-active create requested: pillar={pillar} title={title!r} "
            f"source_pump_id={source_pump_id} — audit"
        )

    deadline_dt = None
    if deadline:
        try:
            deadline_dt = datetime.fromisoformat(deadline)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid deadline format")

    mandate = await brain.create_mandate(
        pillar=pillar_enum,
        priority=priority,
        title=title,
        objective=objective,
        success_criteria=success_criteria,
        deadline=deadline_dt,
        source_pump_id=source_pump_id,
        status=status_enum,
    )

    return {
        "mandate_id": mandate.mandate_id,
        "pillar": mandate.pillar.value,
        "priority": mandate.priority,
        "title": mandate.title,
        "objective": mandate.objective,
        "status": mandate.status.value,
        "created_at": mandate.created_at.isoformat(),
    }


@router.get("/mandates")
async def list_mandates(
    pillar: str | None = None,
    status: str | None = None,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    List mandates with optional filters.

    Args:
        pillar: Filter by pillar
        status: Filter by status

    Returns:
        Dict with mandates list
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    pillar_enum = None
    if pillar:
        # BRS/AAC retired 2026-05-23 per NATRIX directive — hard reject.
        if pillar.strip().upper() in ("BRS", "AAC"):
            raise HTTPException(
                status_code=400,
                detail="pillar BRS/AAC is no longer supported",
            )
        try:
            pillar_enum = PillarType(pillar)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid pillar: {pillar}")

    status_enum = None
    if status:
        try:
            status_enum = MandateStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    mandates = await brain.list_mandates(pillar=pillar_enum, status=status_enum)

    return {
        "count": len(mandates),
        "mandates": [
            {
                "mandate_id": m.mandate_id,
                "pillar": m.pillar.value,
                "priority": m.priority,
                "title": m.title,
                "status": m.status.value,
                "deadline": m.deadline.isoformat() if m.deadline else None,
            }
            for m in mandates
        ],
    }


@router.get("/mandates/{mandate_id}")
async def get_mandate(
    mandate_id: str,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Get mandate details.

    Args:
        mandate_id: Mandate ID

    Returns:
        Mandate details
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    mandate = await brain.get_mandate(mandate_id)
    if not mandate:
        raise HTTPException(status_code=404, detail="Mandate not found")

    return {
        "mandate_id": mandate.mandate_id,
        "pillar": mandate.pillar.value,
        "priority": mandate.priority,
        "title": mandate.title,
        "objective": mandate.objective,
        "status": mandate.status.value,
        "success_criteria": mandate.success_criteria,
        "deadline": mandate.deadline.isoformat() if mandate.deadline else None,
        "created_at": mandate.created_at.isoformat(),
        "updated_at": mandate.updated_at.isoformat(),
    }


@router.post("/mandates/{mandate_id}/complete")
async def complete_mandate(
    mandate_id: str,
    notes: str | None = None,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Mark mandate as completed.

    Args:
        mandate_id: Mandate ID
        notes: Optional completion notes

    Returns:
        Status dict
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    await brain.complete_mandate(mandate_id, notes)
    return {"mandate_id": mandate_id, "status": "completed"}


@router.post("/mandates/{mandate_id}/approve")
async def approve_mandate(
    mandate_id: str,
    reason: str = "Approved by NATRIX",
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Approve a pending_approval mandate, transitioning it to ACTIVE.

    Used to dispatch mandates directly without going through the pump
    approval flow (useful for backfilling approvals on orphaned mandates
    or bulk-approving a triaged set).
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Atomic compare-and-swap: lookup + transition under a single lock hold
    async with brain._mandates_lock:
        mandate = brain.mandates.get(mandate_id)
        if not mandate:
            raise HTTPException(status_code=404, detail=f"Mandate not found: {mandate_id}")

        # Governance gates — emergency stop + policy kernel before activation
        if await brain._emergency_stop_engaged():
            raise HTTPException(status_code=423, detail="Emergency stop engaged; approval blocked")
        try:
            allowed = await brain._policy_allows_dispatch(mandate)
        except Exception as exc:
            log.error(f"[approve] PolicyKernel raised; FAIL CLOSED: {exc}")
            allowed = False
        if not allowed:
            raise HTTPException(status_code=403, detail="PolicyKernel blocked approval")

        try:
            mandate.transition_to(MandateStatus.ACTIVE, reason=reason)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=f"Invalid transition: {e}")
        await brain._persist_mandates_unlocked()

    return {"mandate_id": mandate_id, "status": "active", "reason": reason}


@router.post("/mandates/{mandate_id}/cancel")
async def cancel_mandate(
    mandate_id: str,
    reason: str = "Cancelled by NATRIX",
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Cancel a mandate (valid from DRAFT or PENDING_APPROVAL).

    Used to dismiss stale or obsolete pending_approval mandates without
    going through the pump approval flow. Requires mandate to be in a
    cancellable state.
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Atomic compare-and-swap: lookup + transition under a single lock hold
    async with brain._mandates_lock:
        mandate = brain.mandates.get(mandate_id)
        if not mandate:
            raise HTTPException(status_code=404, detail=f"Mandate not found: {mandate_id}")
        try:
            mandate.transition_to(MandateStatus.CANCELLED, reason=reason)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=f"Invalid transition: {e}")
        await brain._persist_mandates_unlocked()

    return {"mandate_id": mandate_id, "status": "cancelled", "reason": reason}


# /mandate/{id}/requeue endpoint archived 2026-05-23 with the rest of the
# strike-point pipeline. Pillar dispatch was retired; mandates are now an
# in-process Brain concept that doesn't get "stuck in FAILED awaiting requeue".
# If FAILED → DRAFT escape ever becomes useful again, the impl lives at
# archive/strike-point-pre-merge/PILLAR_DISPATCH.md.


@router.post("/mandates/purge")
async def purge_mandates(
    status: str = Query(..., description="Status to purge (e.g. 'pending_approval')"),
    older_than_hours: int = Query(24, ge=0, description="Only purge entries older than N hours"),
    confirm: bool = Query(False, description="Must be true to actually delete"),
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Purge stale mandates from in-memory store and persisted state.

    Used to recover from accumulation bugs (e.g. orphaned pending_approval
    mandates from pumps that never reached the approval gate). Requires
    explicit confirm=true to actually mutate state.
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    try:
        target = MandateStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown status: {status}")

    cutoff = datetime.now(timezone.utc).timestamp() - (older_than_hours * 3600)

    async with brain._mandates_lock:
        candidates = [
            mid for mid, m in brain.mandates.items()
            if m.status == target and m.created_at.timestamp() < cutoff
        ]
        if not confirm:
            return {
                "would_purge": len(candidates),
                "total_in_memory": len(brain.mandates),
                "status_filter": status,
                "older_than_hours": older_than_hours,
                "confirm_required": True,
            }
        for mid in candidates:
            brain.mandates.pop(mid, None)
        await brain._persist_mandates_unlocked()

    return {
        "purged": len(candidates),
        "remaining": len(brain.mandates),
        "status_filter": status,
    }
