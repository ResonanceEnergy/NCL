"""Council Runner legacy endpoints (``/council-runner/*``) — extracted in W5-06.

Owns the legacy v1 Council Runner surface that the FirstStrike iOS app
hits when running the Planner / Skeptic / Risk parallel council:

    POST   /council-runner/run                       — kick off a run (background)   [AUTH]
    GET    /council-runner/runs                      — list runs (paginated)          [AUTH]
    GET    /council-runner/runs/{run_id}             — fetch one run                  [AUTH]
    GET    /council-runner/runs/{run_id}/provenance  — provenance chain               [AUTH]
    POST   /council-runner/replay/{run_id}           — replay a historical run        [AUTH]
    GET    /council-runner/compare/{a}/{b}           — side-by-side comparison        [AUTH]
    GET    /council-runner/search?q=...              — text search by topic/prompt    [AUTH]
    GET    /council-runner/stats                     — aggregate stats                [AUTH]

**Pack routing**: ``POST /council-runner/run`` was rewired in W3 (Agent
B, 2026-05-23) to route through ``council_pack.run_council_with_pack``
so the universal pack benefits (MMR diversity, temporal split,
contradictions, calibration, peer review, 3-tier write-back) also apply
to this surface. The pack-produced session is then projected into a
synthetic ``CouncilRunRecord`` and persisted to ``_council_store`` so
``/council-runner/runs``, ``/council-runner/runs/{id}``, and the replay
engine continue to work unchanged. The legacy v1 path (Planner /
Skeptic / Risk via ``council_pack.legacy.run_parallel_council``) is
kept as a fallback so the endpoint never regresses on pack-path
failure.

**Storage**: ``CouncilRunStore`` and ``ReplayEngine`` were relocated
from ``runtime/council_runner/`` to ``runtime/council_pack/`` in W5-06
(2026-05-23). The source directory is archived at
``archive/strike-point-pre-merge/council_runner/``.

Module-level globals (``_council_store``, ``_replay_engine``,
``brain``, ``STRIKE_TOKEN``, etc.) live in :mod:`runtime.api.routes`
and are accessed via lazy import inside each handler — same pattern as
``routers/system.py``.
"""

from __future__ import annotations  # noqa: I001

import asyncio
import logging
import time
import uuid

from fastapi import APIRouter, Header, HTTPException, Query, Request

log = logging.getLogger(__name__)

router = APIRouter(tags=["council-runner"])


# ── POST /council-runner/run — pack-routed, with v1 fallback ──────────────


@router.post("/council-runner/run")
async def run_council_runner(
    request: Request,
    topic: str,
    prompt: str,
    authorization: str = Header(default=""),
) -> dict:
    """Run the Planner/Skeptic/Risk parallel council on a topic.

    Wave 3 (2026-05-23): Routes through ``council_pack.run_council_with_pack``
    first so the universal pack benefits (MMR diversity, temporal split,
    contradiction surfacing, calibration, peer review, 3-tier write-back)
    apply to this surface too. The pack-produced session is then projected
    into a synthetic ``CouncilRunRecord`` and persisted to ``_council_store``
    so ``/council-runner/runs``, ``/council-runner/runs/{id}``, and the
    replay engine continue to function unchanged.

    On ANY pack-path failure we fall back to the legacy
    ``run_parallel_council(topic, prompt)`` (now living in
    ``council_pack.legacy``) so this endpoint NEVER regresses.
    """
    from .. import routes as _routes

    _routes._verify_strike_token(authorization)
    _routes._check_rate_limit(request)

    if not _routes._council_store:
        raise HTTPException(status_code=503, detail="CouncilRunner not initialized")

    # Imports are lazy so this module loads cleanly even if council_pack
    # has not yet been touched at app boot.
    from ...council_pack import (
        CouncilRunRecord,
        run_parallel_council,
    )

    run_id = str(uuid.uuid4())

    async def _run():
        try:
            record: CouncilRunRecord | None = None
            # ── Pack path (Wave 3) ────────────────────────────────────
            if _routes.brain is not None:
                try:
                    from ...council_pack import run_council_with_pack  # noqa: I001
                    from ...council_pack import (
                        AgentOutput,
                        AgentRole,
                        ConsensusResult,
                        CouncilRunRecord as _CRR,  # noqa: N814
                    )
                    from ...memory.retrieval import BM25Index, FusedRetriever

                    store = _routes.brain.memory_store
                    if not getattr(store, "_bm25_index", None):
                        store._bm25_index = BM25Index(store)
                    fused = FusedRetriever(
                        store,
                        store._bm25_index,
                        knowledge_graph=getattr(store, "_knowledge_graph", None),
                    )

                    async_writer = None
                    try:
                        from ...memory.async_writer import get_async_writer

                        async_writer = get_async_writer()
                    except Exception:
                        async_writer = None

                    learner = None
                    try:
                        from ...feedback.source_authority_learner import get_learner

                        learner = get_learner()
                    except Exception:
                        learner = None

                    working_context = getattr(_routes.brain, "_working_context_ref", None)

                    pack_t0 = time.time()
                    pack_result = await run_council_with_pack(
                        council_engine=_routes.brain.council_engine,
                        topic=topic,
                        base_prompt=prompt,
                        fused_retriever=fused,
                        working_context=working_context,
                        learner=learner,
                        async_writer=async_writer,
                        session_id=run_id,
                        council_type="api:council_runner_run",
                        peer_review=True,
                    )
                    pack_duration_ms = int((time.time() - pack_t0) * 1000)

                    # Project pack session → CouncilRunRecord so the v1
                    # store (used by /council-runner/runs, replay, etc.)
                    # keeps working. Roles are synthetic — the pack debate
                    # uses the 6-member Delphi-MAD roster, not Planner/
                    # Skeptic/Risk — so we collapse round-1 replies into
                    # one ``AgentOutput`` per member tagged as PLANNER for
                    # storage purposes only.
                    session = pack_result["session"]
                    agent_outputs: list[AgentOutput] = []
                    try:
                        if session.rounds:
                            r1 = session.rounds[0]
                            for member_name, reply in (r1.responses or {}).items():
                                agent_outputs.append(
                                    AgentOutput(
                                        role=AgentRole.PLANNER,
                                        response_text=reply or "",
                                        model_used=str(member_name),
                                    )
                                )
                    except Exception as proj_err:
                        log.debug(
                            "[/council-runner/run] pack→record projection (round 1) failed: %s",
                            proj_err,
                        )  # noqa: E501

                    consensus_text = session.consensus or session.synthesis or ""
                    confidence_pct = 50
                    try:
                        if session.consensus_score and session.consensus_score.confidence_weighted:
                            confidence_pct = int(session.consensus_score.confidence_weighted)
                    except Exception:
                        pass

                    consensus_obj = ConsensusResult(
                        consensus_text=consensus_text,
                        consensus_score=max(0, min(100, confidence_pct)),
                        dissent_areas=list((session.dissents or {}).keys())
                        if isinstance(session.dissents, dict)
                        else [],  # noqa: E501
                        recommendations=list(session.recommendations or [])
                        if hasattr(session, "recommendations")
                        else [],  # noqa: E501
                    )

                    record = _CRR(
                        run_id=run_id,
                        topic=topic,
                        prompt=prompt,
                        agent_outputs=agent_outputs,
                        consensus=consensus_obj,
                        provenance={
                            "routed_through": "council_pack",
                            "pack_size_items": pack_result["pack"].get("pack_size_items", 0),
                            "surfaced_conflicts": len(
                                pack_result["pack"].get("surfaced_conflicts", []) or []
                            ),  # noqa: E501
                            "calibration_count": len(pack_result.get("calibrations") or []),
                            "peer_reviews": len(pack_result.get("peer_review") or []),
                            "writeback_gist_chars": len(
                                (pack_result.get("writeback") or {}).get("gist") or ""
                            ),  # noqa: E501
                            "pack_session_id": session.session_id,
                        },
                        total_duration_ms=pack_duration_ms,
                    )
                    log.info(
                        "[/council-runner/run] pack path complete run_id=%s pack_session=%s",
                        run_id,
                        session.session_id,
                    )
                except Exception as pack_err:
                    log.warning(
                        "[/council-runner/run] pack path failed (%s) — falling back to legacy run_parallel_council",  # noqa: E501
                        pack_err,
                    )
                    record = None

            # ── Fallback: legacy v1 Planner/Skeptic/Risk ─────────────
            if record is None:
                record = await run_parallel_council(topic=topic, prompt=prompt)

            await _routes._council_store.save_run(record)
        except Exception as e:
            log.exception(f"[/council-runner/run] council run failed: {e}")

    task = asyncio.create_task(_run())
    task.add_done_callback(
        lambda t: log.error(f"Council runner task died: {t.exception()!r}")
        if not t.cancelled() and t.exception()
        else None
    )  # noqa: E501
    return {
        "status": "started",
        "run_id": run_id,
        "message": "Council running in background. Check /council-runner/runs for results.",
    }  # noqa: E501


# ── GET /council-runner/runs ─────────────────────────────────────────────


@router.get("/council-runner/runs")
async def list_council_runs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    authorization: str = Header(default=""),
) -> dict:
    """List council runner runs."""
    from .. import routes as _routes

    _routes._verify_strike_token(authorization)
    if not _routes._council_store:
        raise HTTPException(status_code=503, detail="CouncilRunner not initialized")
    runs = await _routes._council_store.list_runs(limit=limit, offset=offset)
    return {"runs": [r.model_dump() for r in runs], "count": len(runs)}


# ── GET /council-runner/runs/{run_id} ────────────────────────────────────


@router.get("/council-runner/runs/{run_id}")
async def get_council_run(run_id: str, authorization: str = Header(default="")) -> dict:
    """Get a specific council run record."""
    from .. import routes as _routes

    _routes._verify_strike_token(authorization)
    if not _routes._council_store:
        raise HTTPException(status_code=503, detail="CouncilRunner not initialized")
    record = await _routes._council_store.get_run(run_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return record.model_dump()


# ── GET /council-runner/runs/{run_id}/provenance ─────────────────────────


@router.get("/council-runner/runs/{run_id}/provenance")
async def get_council_run_provenance(run_id: str, authorization: str = Header(default="")) -> dict:
    """Get full provenance chain for a council run."""
    from .. import routes as _routes

    _routes._verify_strike_token(authorization)
    if not _routes._council_store:
        raise HTTPException(status_code=503, detail="CouncilRunner not initialized")
    provenance = await _routes._council_store.get_provenance(run_id)
    if not provenance:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return provenance


# ── POST /council-runner/replay/{run_id} ─────────────────────────────────


@router.post("/council-runner/replay/{run_id}")
async def replay_council_run(
    run_id: str,
    temperature_override: float = Query(default=None),
    authorization: str = Header(default=""),
) -> dict:
    """Replay a previous council run for deterministic comparison."""
    from .. import routes as _routes

    _routes._verify_strike_token(authorization)
    if not _routes._replay_engine:
        raise HTTPException(status_code=503, detail="ReplayEngine not initialized")

    async def _replay():
        try:
            record = await _routes._replay_engine.replay(
                run_id=run_id,
                temperature_override=temperature_override,
            )
            if _routes._council_store:
                await _routes._council_store.save_run(record)
        except Exception as e:
            log.exception(f"[/council-runner/replay] replay failed: {e}")

    task = asyncio.create_task(_replay())
    task.add_done_callback(
        lambda t: log.error(f"Replay task died: {t.exception()!r}")
        if not t.cancelled() and t.exception()
        else None
    )  # noqa: E501
    return {"status": "replay_started", "original_run_id": run_id}


# ── GET /council-runner/compare/{run_id_a}/{run_id_b} ────────────────────


@router.get("/council-runner/compare/{run_id_a}/{run_id_b}")
async def compare_council_runs(
    run_id_a: str, run_id_b: str, authorization: str = Header(default="")
) -> dict:  # noqa: E501
    """Compare two council runs side-by-side."""
    from .. import routes as _routes

    _routes._verify_strike_token(authorization)
    if not _routes._replay_engine:
        raise HTTPException(status_code=503, detail="ReplayEngine not initialized")
    comparison = await _routes._replay_engine.compare_runs(run_id_a, run_id_b)
    return comparison


# ── GET /council-runner/search ───────────────────────────────────────────


@router.get("/council-runner/search")
async def search_council_runs(
    q: str = Query(..., description="Search query for topic/prompt"),
    limit: int = Query(default=20, le=100),
    authorization: str = Header(default=""),
) -> dict:
    """Search council runs by topic/prompt text."""
    from .. import routes as _routes

    _routes._verify_strike_token(authorization)
    if not _routes._council_store:
        raise HTTPException(status_code=503, detail="CouncilRunner not initialized")
    runs = await _routes._council_store.search_runs(topic_query=q, limit=limit)
    return {"runs": [r.model_dump() for r in runs], "count": len(runs), "query": q}


# ── GET /council-runner/stats ────────────────────────────────────────────


@router.get("/council-runner/stats")
async def get_council_runner_stats(authorization: str = Header(default="")) -> dict:
    """Get council runner statistics."""
    from .. import routes as _routes

    _routes._verify_strike_token(authorization)
    if not _routes._council_store:
        raise HTTPException(status_code=503, detail="CouncilRunner not initialized")
    return await _routes._council_store.get_stats()
