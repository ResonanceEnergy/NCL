"""Memory-tier endpoints (/memory/*) extracted from routes.py.

Owns the FirstStrike Memory tab + KG/working-context surface:

  Core CRUD / search
    GET   /memory/query                      — tag-based query
    GET   /memory/stats                      — bridge stats
    POST  /memory/cleanup-sources            — one-time source normalize
    GET   /memory/timeline                   — event timeline
    POST  /memory/search                     — text/tag/importance/date filter
    POST  /memory/semantic                   — vector search
    GET   /memory/search/fused               — RRF (vector + BM25 + KG)
    POST  /memory/store                      — create unit
    POST  /memory/reindex                    — rebuild vector index
    GET   /memory/dashboard                  — HTML dashboard

  Enhanced subsystem
    POST  /memory/consolidate-v2             — ACE reflection loop
    GET   /memory/knowledge-graph/stats
    GET   /memory/knowledge-graph/entity/{entity}
    GET   /memory/knowledge-graph/top-entities
    GET   /memory/knowledge-graph/path
    POST  /memory/knowledge-graph/prune
    POST  /memory/score                      — hybrid LLM+rule importance
    POST  /memory/extract-entities
    GET   /memory/typed-stats
    POST  /memory/migrate-types

  Budget telemetry
    GET   /memory/budget
    GET   /memory/budget/history
    POST  /memory/budget/check

  Authority / provenance
    GET   /memory/by-authority
    POST  /memory/backfill-authority
    POST  /memory/retag-authority
    POST  /memory/bootstrap-claude-md
    POST  /memory/kg-cleanup

  Async writer
    GET   /memory/async-writer/stats
    GET   /memory/async-writer/dlq
    POST  /memory/async-writer/retry-dlq

  PII audit
    GET   /memory/pii/recent

  Working context
    GET    /memory/working-context
    GET    /memory/working-context/text
    POST   /memory/working-context/refresh
    POST   /memory/working-context/assemble
    POST   /memory/working-context/pin
    DELETE /memory/working-context/pin
    GET    /memory/working-context/history
    GET    /memory/working-context/stats
    POST   /memory/working-context/eod
    POST   /memory/working-context/promote
    POST   /memory/working-context/dismiss
    POST   /memory/working-context/toggle-pin
    POST   /memory/working-context/score

All endpoints are gated by ``verify_strike_token_dep`` (DI factory in
:mod:`runtime.api.deps`). The three subsystem singletons consumed by this
router — ``NCLBrain`` (for ``memory_store`` + ``knowledge_graph``),
``MemoryBridge`` (for the bridged read/write surface), and
``AutonomousScheduler`` (for ``_working_context``) — arrive via
``Depends()`` injection rather than the legacy
``from .. import routes as _routes`` lazy-import shim.

W10C-2 (2026-05-24): Converted from the legacy ``from .. import routes as
_routes`` lazy-import pattern to FastAPI ``Depends()`` injection. Mirrors
the W8-A8 / W10B-3 conversions of routers/feedback.py, routers/system.py,
routers/journal.py, routers/mandate.py. The new ``get_memory_bridge``
DI factory was added to ``runtime.api.deps`` to back this conversion.
"""

from __future__ import annotations  # noqa: I001

import json
import logging
import os
import re as _re
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..deps import (
    get_autonomous,
    get_brain,
    get_memory_bridge,
    verify_strike_token_dep,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["memory"])


# ── Core CRUD / search ─────────────────────────────────────────────────────


@router.get("/memory/query")
async def query_memory(
    tags: list[str] | None = None,
    importance_threshold: float = 0.0,
    days_back: int | None = None,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Query memory system by tags / importance / days_back."""
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return await brain.query_memory(
        tags=tags,
        importance_threshold=importance_threshold,
        days_back=days_back,
    )


@router.get("/memory/stats")
async def get_memory_stats(
    memory_bridge=Depends(get_memory_bridge),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get memory store statistics for the dashboard."""
    if not memory_bridge:
        raise HTTPException(status_code=503, detail="MemoryBridge not initialized")
    return await memory_bridge.get_stats()


@router.post("/memory/cleanup-sources")
async def cleanup_memory_sources(
    memory_bridge=Depends(get_memory_bridge),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """One-time fix: normalize corrupted nested consolidation source tags."""
    if not memory_bridge:
        raise HTTPException(status_code=503, detail="MemoryBridge not initialized")
    result = await memory_bridge.store.cleanup_sources()
    return {"status": "ok", **result}


@router.get("/memory/timeline")
async def get_memory_timeline(
    limit: int = Query(default=50, le=200),
    memory_bridge=Depends(get_memory_bridge),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get memory event timeline.

    P1-B (2026-05-24): the bridge now returns either a list (legacy) OR
    a ``{"events": [...], "degraded": bool}`` envelope so iOS sees the
    last-known snapshot instead of an empty response when the memory
    store is locked by the Awarebot drainer flood.
    """
    if not memory_bridge:
        raise HTTPException(status_code=503, detail="MemoryBridge not initialized")
    result = await memory_bridge.get_timeline(limit=limit)
    # Back-compat: tolerate both list and dict envelope.
    if isinstance(result, dict):
        events = result.get("events", [])
        degraded = bool(result.get("degraded", False))
    else:
        events = result or []
        degraded = False
    return {"events": events, "count": len(events), "degraded": degraded}


@router.post("/memory/search")
async def search_memory(
    body: dict,
    memory_bridge=Depends(get_memory_bridge),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Search memory units with text, tags, importance, and date filters."""
    if not body.get("query_text") and not body.get("tags"):
        raise HTTPException(
            status_code=400,
            detail="Missing required field: 'query_text' or 'tags'",
        )
    if not memory_bridge:
        raise HTTPException(status_code=503, detail="MemoryBridge not initialized")
    results = await memory_bridge.search(
        query_text=body.get("query_text"),
        tags=body.get("tags"),
        importance_threshold=body.get("importance_threshold", 0),
        days_back=body.get("days_back", 30),
    )
    return {"results": results, "count": len(results)}


@router.post("/memory/semantic")
async def semantic_search_memory(
    body: dict,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Semantic similarity search over memory units using vector embeddings."""
    if not brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    query = body.get("query", "")
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    results = await brain.memory_store.semantic_search(
        query=query,
        n_results=body.get("n_results", 10),
        importance_threshold=body.get("importance_threshold", 0.0),
    )
    return {
        "results": [r.model_dump(mode="json") for r in results],
        "count": len(results),
        "query": query,
    }


@router.get("/memory/search/fused")
async def search_memory_fused(
    q: str = Query(..., min_length=1, description="Search query"),
    top_k: int = Query(default=10, ge=1, le=50),
    importance_threshold: float = Query(default=0.0, ge=0.0, le=100.0),
    rerank: bool = Query(default=False, description="Run optional Haiku rerank after RRF"),
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Multi-signal retrieval fusion (Loop 11).

    Always uses ``FusedRetriever`` — Reciprocal Rank Fusion over:
      - Vector similarity (ChromaDB)
      - BM25 keyword
      - Entity overlap (knowledge graph)

    Falls back gracefully to vector-only if BM25 index is missing or
    rank_bm25 is unavailable. ``rerank=true`` enables a Haiku cross-encoder
    second pass; the actual rerank also requires ``NCL_FUSION_RERANK=1``
    in the Brain's environment for safety.
    """
    if not brain or not brain.memory_store:
        raise HTTPException(status_code=503, detail="Memory store not available")

    from ...memory.retrieval import BM25Index, FusedRetriever

    store = brain.memory_store
    if not getattr(store, "_bm25_index", None):
        store._bm25_index = BM25Index(store)
    fr = FusedRetriever(
        store,
        store._bm25_index,
        knowledge_graph=getattr(store, "_knowledge_graph", None),
    )

    if rerank:
        results = await fr.retrieve_with_rerank(q, top_k=top_k)
    else:
        results = await fr.retrieve(q, top_k=top_k)

    if importance_threshold > 0:
        results = [r for r in results if r.get("importance", 0) >= importance_threshold]

    bm25_stats = store._bm25_index.stats() if getattr(store, "_bm25_index", None) else {}
    return {
        "query": q,
        "count": len(results),
        "results": results,
        "bm25_index": bm25_stats,
        "rerank_applied": rerank and os.getenv("NCL_FUSION_RERANK", "0") in ("1", "true", "yes"),
    }


class MemoryStoreRequest(BaseModel):
    """Request to store a new memory unit."""

    content: str = Field(..., min_length=1, max_length=50000, description="Memory content to store")
    source: str = Field(
        ...,
        min_length=1,
        description="Source identifier (e.g. 'first-strike-ios', 'council:session-id')",
    )  # noqa: E501
    importance: float = Field(default=50.0, ge=0.0, le=100.0, description="Importance score 0-100")
    tags: list[str] = Field(default_factory=list, description="Search tags")


@router.post("/memory/store")
async def store_memory(
    req: MemoryStoreRequest,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Store a new memory unit. Creates a persistent memory entry with vector indexing."""
    if not brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    unit = await brain.memory_store.create_unit(
        content=req.content,
        source=req.source,
        importance=req.importance,
        tags=req.tags,
    )
    return {
        "status": "stored",
        "unit_id": unit.unit_id,
        "source": unit.source,
        "importance": unit.importance,
        "tags": unit.tags,
        "created_at": unit.created_at.isoformat() if hasattr(unit, "created_at") else None,
    }


@router.post("/memory/reindex")
async def reindex_memory(
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Rebuild the vector search index from all stored memory units."""
    if not brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    return await brain.memory_store.reindex_all()


@router.get("/memory/dashboard")
async def memory_dashboard(
    _: None = Depends(verify_strike_token_dep),
) -> HTMLResponse:
    """Serve the Memory Dashboard."""
    dashboard_path = Path(__file__).parent.parent.parent.parent / "dashboard" / "memory.html"
    if not dashboard_path.exists():
        raise HTTPException(status_code=404, detail="Memory dashboard not found")
    async with aiofiles.open(dashboard_path, "r") as f:
        html = await f.read()
    return HTMLResponse(content=html)


# ── Enhanced Memory System ─────────────────────────────────────────────────


@router.post("/memory/consolidate-v2")
async def consolidate_memory_v2(
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Run enhanced consolidation with reflection loop and entity extraction."""
    if not brain or not brain.memory_store:
        return {"error": "Memory store not available"}
    result = await brain.memory_store.consolidate_v2()
    return {"status": "ok", "result": result}


@router.get("/memory/knowledge-graph/stats")
async def get_knowledge_graph_stats(
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get knowledge graph statistics."""
    kg = getattr(brain.memory_store, "_knowledge_graph", None) if brain else None
    if not kg:
        return {"status": "not_initialized", "nodes": 0, "edges": 0}
    return await kg.stats()


@router.get("/memory/knowledge-graph/entity/{entity}")
async def query_knowledge_graph_entity(
    entity: str,
    depth: int = Query(default=1, ge=1, le=3),
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Query a specific entity in the knowledge graph."""
    kg = getattr(brain.memory_store, "_knowledge_graph", None) if brain else None
    if not kg:
        return {"found": False, "error": "Knowledge graph not initialized"}
    return await kg.query_entity(entity, depth=depth)


@router.get("/memory/knowledge-graph/top-entities")
async def get_top_entities(
    n: int = Query(default=20, ge=1, le=100),
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get top entities by mention count."""
    kg = getattr(brain.memory_store, "_knowledge_graph", None) if brain else None
    if not kg:
        return {"entities": []}
    entities = await kg.get_top_entities(n=n)
    return {"entities": entities}


@router.get("/memory/knowledge-graph/path")
async def find_entity_path(
    source: str = Query(...),
    target: str = Query(...),
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Find shortest path between two entities in the knowledge graph."""
    kg = getattr(brain.memory_store, "_knowledge_graph", None) if brain else None
    if not kg:
        return {"path": None, "error": "Knowledge graph not initialized"}
    path = await kg.find_path(source, target)
    return {"source": source, "target": target, "path": path}


@router.post("/memory/knowledge-graph/prune")
async def prune_knowledge_graph(
    days: int = Query(default=90, ge=7),
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Prune stale entities and edges from the knowledge graph."""
    kg = getattr(brain.memory_store, "_knowledge_graph", None) if brain else None
    if not kg:
        return {"error": "Knowledge graph not initialized"}
    result = await kg.prune_stale(days=days)
    return {"status": "ok", "result": result}


@router.post("/memory/score")
async def score_memory_content(
    body: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Score memory content for importance using LLM + rule-based hybrid."""
    content = body.get("content", "")
    source = body.get("source", "")
    tags = body.get("tags", [])
    use_llm = body.get("use_llm", True)
    if not content:
        return {"error": "content is required"}

    from ...memory.importance_scorer import score_memory as _score_memory

    result = await _score_memory(content, source, tags, use_llm=use_llm)
    return result


@router.post("/memory/extract-entities")
async def extract_entities_endpoint(
    body: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Extract entities and relationships from content."""
    content = body.get("content", "")
    use_llm = body.get("use_llm", False)
    if not content:
        return {"error": "content is required"}

    from ...memory.entity_extractor import extract_entities_and_relationships

    result = await extract_entities_and_relationships(content, use_llm=use_llm)
    return result


@router.get("/memory/typed-stats")
async def get_typed_memory_stats(
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get memory statistics broken down by memory type and tier."""
    if not brain or not brain.memory_store:
        return {"error": "Memory store not available"}

    units = await brain.memory_store._load_all_units()

    type_counts: dict[str, int] = {}
    tier_counts: dict[str, int] = {"LML": 0, "SML": 0}
    type_avg_importance: dict[str, list[float]] = {}

    for unit in units:
        mem_type = getattr(unit, "memory_type", "episodic")
        mem_tier = getattr(unit, "memory_tier", "SML")
        type_counts[mem_type] = type_counts.get(mem_type, 0) + 1
        tier_counts[mem_tier] = tier_counts.get(mem_tier, 0) + 1
        if mem_type not in type_avg_importance:
            type_avg_importance[mem_type] = []
        type_avg_importance[mem_type].append(unit.importance)

    type_stats: dict[str, dict] = {}
    for mem_type, importances in type_avg_importance.items():
        type_stats[mem_type] = {
            "count": type_counts.get(mem_type, 0),
            "avg_importance": round(sum(importances) / len(importances), 2) if importances else 0,
        }

    collection_stats: dict[str, object] = {}
    if hasattr(brain.memory_store, "_chroma_collections"):
        for name, col in brain.memory_store._chroma_collections.items():
            try:
                collection_stats[name] = col.count()
            except Exception:
                collection_stats[name] = "error"

    return {
        "total_units": len(units),
        "by_type": type_stats,
        "by_tier": tier_counts,
        "chromadb_collections": collection_stats,
    }


@router.post("/memory/migrate-types")
async def migrate_memory_types_endpoint(
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Migrate all memory units to proper memory_type and memory_tier.

    Pre-type-system units are all stuck as SML/episodic. This endpoint
    infers the correct type from source/content/tags and assigns proper
    tiers. One-time migration — safe to re-run (idempotent).
    """
    if not brain or not brain.memory_store:
        return {"error": "Memory store not available"}
    try:
        result = await brain.memory_store.migrate_memory_types()
        return {"status": "ok", **result}
    except Exception as e:
        log.error(f"Memory type migration failed: {e}")
        return {"error": str(e)}


# ── Memory Budget Telemetry ────────────────────────────────────────────────


@router.get("/memory/budget")
async def get_memory_budget_summary(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Today's per-category context-token spend + caps + platform pct."""
    try:
        from ...memory.budget_tracker import get_tracker as _bt_get

        tracker = await _bt_get()
        return await tracker.get_daily_summary()
    except Exception as e:
        log.error(f"[/memory/budget] failed: {e}")
        return {"error": str(e)}


@router.get("/memory/ab-test/summary")
async def get_ab_test_summary(
    window_hours: int = 24,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Sonnet⇄Haiku A/B harness summary for the trailing N hours.

    Computes mean/p95 abs delta, type-agreement, error counts, projected
    savings, and a swap/keep recommendation. ``enabled`` key reflects the
    NCL_AB_HAIKU env flag.
    """
    try:
        from ...memory.ab_test import compute_summary, is_ab_enabled

        return {
            "enabled": is_ab_enabled(),
            **compute_summary(window_hours=max(1, min(720, int(window_hours)))),
        }
    except Exception as e:
        log.error(f"[/memory/ab-test/summary] failed: {e}")
        return {"error": str(e)}


@router.get("/memory/budget/history")
async def get_memory_budget_history(
    days: int = 7,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Per-day rollup of context-token spend for the last N days."""
    try:
        from ...memory.budget_tracker import get_tracker as _bt_get

        tracker = await _bt_get()
        history = await tracker.get_history(days=max(1, min(int(days), 90)))
        return {"days": days, "history": history}
    except Exception as e:
        log.error(f"[/memory/budget/history] failed: {e}")
        return {"error": str(e)}


@router.post("/memory/budget/check")
async def check_memory_budget(
    category: str,
    est_tokens: int,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Pre-flight budget gate for a planned context injection."""
    try:
        from ...memory.budget_tracker import get_tracker as _bt_get

        tracker = await _bt_get()
        allowed, reason = await tracker.check_budget(category, int(est_tokens))
        return {
            "allowed": allowed,
            "reason": reason,
            "category": category,
            "est_tokens": int(est_tokens),
        }
    except Exception as e:
        log.error(f"[/memory/budget/check] failed: {e}")
        return {"error": str(e)}


# ── Authority / Provenance ─────────────────────────────────────────────────


@router.get("/memory/by-authority")
async def list_memory_by_authority(
    min_tier: str = Query(
        default="council",
        description=(
            "Inclusive lower bound. Accepts a tier name "
            "(natrix|council|brain|calendar|llm_single|scanner|raw) "
            "or a bare integer (10..100)."
        ),
    ),
    limit: int = Query(default=20, ge=1, le=500),
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Return units whose authority_tier >= ``min_tier``, newest-first."""
    if not brain or not brain.memory_store:
        return {"error": "Memory store not available"}

    from ...memory.authority import (  # noqa: I001
        AuthorityTier,
        TIER_BY_NAME,
        filter_by_min_tier,
        tier_for_source,
    )

    raw = (min_tier or "").strip().lower()
    if not raw:
        return {"error": "min_tier is required"}
    try:
        floor_int = int(raw)
    except ValueError:
        if raw not in TIER_BY_NAME:
            return {
                "error": f"unknown tier name: {min_tier!r}",
                "valid_names": sorted(TIER_BY_NAME),
            }
        floor_int = int(TIER_BY_NAME[raw])

    units = await brain.memory_store._load_all_units()
    matching = filter_by_min_tier(units, floor_int)
    matching.sort(key=lambda u: getattr(u, "created_at", None) or 0, reverse=True)
    sliced = matching[:limit]

    out: list[dict] = []
    for u in sliced:
        meta = getattr(u, "metadata", None) or {}
        tv = meta.get("authority_tier")
        if tv is None:
            tv = int(tier_for_source(getattr(u, "source", "")))
        try:
            tier_name = AuthorityTier(int(tv)).name.lower()
        except ValueError:
            tier_name = "raw"
        out.append(
            {
                "unit_id": u.unit_id,
                "source": u.source,
                "content": (u.content[:500] + ("…" if len(u.content) > 500 else "")),
                "importance": float(u.importance),
                "memory_type": getattr(u, "memory_type", "episodic"),
                "memory_tier": getattr(u, "memory_tier", "SML"),
                "authority_tier": int(tv),
                "authority_tier_name": tier_name,
                "tags": list(u.tags or []),
                "created_at": (
                    u.created_at.isoformat()
                    if hasattr(u.created_at, "isoformat")
                    else str(u.created_at)
                ),
                "last_accessed": (
                    u.last_accessed.isoformat()
                    if hasattr(u.last_accessed, "isoformat")
                    else str(u.last_accessed)
                ),
            }
        )

    return {
        "min_tier": floor_int,
        "min_tier_name": (
            AuthorityTier(floor_int).name.lower()
            if floor_int in {int(t) for t in AuthorityTier}
            else None
        ),
        "matched": len(matching),
        "returned": len(out),
        "units": out,
    }


@router.post("/memory/backfill-authority")
async def backfill_authority_endpoint(
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Stamp ``metadata.authority_tier`` on any unit missing it. Idempotent."""
    if not brain or not brain.memory_store:
        return {"error": "Memory store not available"}
    try:
        from ...memory.authority import backfill_authority_tiers

        result = await backfill_authority_tiers(brain.memory_store)
        return {"status": "ok", **result}
    except Exception as e:
        log.error(f"Authority backfill failed: {e}")
        return {"status": "error", "error": str(e)}


@router.post("/memory/retag-authority")
async def retag_authority_endpoint(
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Force-re-apply the SOURCE_TIER_MAP to every unit.

    Use after editing the tier map (e.g. demoting portfolio:snapshot from
    NATRIX to BRAIN). Unlike /memory/backfill-authority, this overwrites
    already-stamped units.
    """
    if not brain or not brain.memory_store:
        return {"error": "Memory store not available"}
    try:
        from ...memory.authority import retag_authority_tiers

        result = await retag_authority_tiers(brain.memory_store)
        return {"status": "ok", **result}
    except Exception as e:
        log.error(f"Authority retag failed: {e}")
        return {"status": "error", "error": str(e)}


@router.post("/memory/bootstrap-claude-md")
async def bootstrap_claude_md_endpoint(
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """One-shot CLAUDE.md ingestion.

    Reads ~/dev/NCL/CLAUDE.md and ~/Projects/FirstStrike/CLAUDE.md, splits
    each on `##` headers, and creates a procedural MemUnit per section at
    BRAIN(60) authority. Idempotent — dedupes by content_hash.
    """
    if not brain or not brain.memory_store:
        return {"error": "Memory store not available"}
    try:
        from ...memory.claude_md_bootstrap import bootstrap_claude_md

        result = await bootstrap_claude_md(brain.memory_store)
        return {"status": "ok", **result}
    except Exception as e:
        log.error(f"CLAUDE.md bootstrap failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@router.post("/memory/kg-cleanup")
async def kg_cleanup_endpoint(
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Purge blacklisted entities (URL stems, sector buckets) from the KG.

    One-shot. Removes nodes that fail the entity blacklist and their
    incident edges, then re-classifies surviving nodes against the
    current entity_extractor classifier.
    """
    if not brain or not brain.memory_store:
        return {"error": "Memory store not available"}
    kg = getattr(brain.memory_store, "_knowledge_graph", None) or getattr(
        brain, "knowledge_graph", None
    )
    if kg is None:
        return {"error": "Knowledge graph not initialized"}
    try:
        result = await kg.cleanup_blacklisted()
        return {"status": "ok", **result}
    except Exception as e:
        log.error(f"KG cleanup failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


# ── Async Memory Writer ────────────────────────────────────────────────────


@router.get("/memory/async-writer/stats")
async def get_async_writer_stats(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Snapshot of AsyncMemoryWriter queue / drainer / DLQ health."""
    try:
        from ...memory.async_writer import get_async_writer

        return get_async_writer().get_stats()
    except RuntimeError:
        return {"error": "AsyncMemoryWriter not initialized"}
    except Exception as e:
        return {"error": str(e)}


@router.get("/memory/async-writer/dlq")
async def get_async_writer_dlq(
    limit: int = 20,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Recent dead-letter queue entries (newest first, capped at ``limit``)."""
    try:
        from ...memory.async_writer import get_async_writer

        items = get_async_writer().get_dlq(limit=max(1, min(500, limit)))
        return {"count": len(items), "items": items}
    except RuntimeError:
        return {"error": "AsyncMemoryWriter not initialized"}
    except Exception as e:
        return {"error": str(e)}


@router.post("/memory/async-writer/retry-dlq")
async def retry_async_writer_dlq(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Re-enqueue all DLQ entries under MAX_ATTEMPTS for another try."""
    try:
        from ...memory.async_writer import get_async_writer

        n = await get_async_writer().retry_dlq()
        return {"status": "ok", "requeued": n}
    except RuntimeError:
        return {"error": "AsyncMemoryWriter not initialized"}
    except Exception as e:
        return {"error": str(e)}


# ── PII Audit ──────────────────────────────────────────────────────────────


@router.get("/memory/pii/recent")
async def get_recent_pii_redactions(
    limit: int = Query(default=20, ge=1, le=500),
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Recent PII redaction audit records (Loop 10 transparency endpoint).

    Returns counts + types per redacted unit, never the raw matched values.
    Lets NATRIX verify the redactor is doing the right thing without the
    audit log itself becoming a PII vector.
    """
    if not brain or not brain.memory_store:
        return {"redactions": [], "lifetime_total": 0, "error": "Memory store not available"}
    try:
        return await brain.memory_store.get_pii_redactions(limit=limit)
    except Exception as e:
        log.error(f"PII redaction read failed: {e}")
        return {"redactions": [], "lifetime_total": 0, "error": str(e)}


# ── Working Context Window ─────────────────────────────────────────────────


@router.get("/memory/working-context")
async def get_working_context(
    max_items: int = Query(default=50, le=100),
    mark_accessed: bool = Query(
        default=True,
        description="Mark returned items as accessed today (reinforces for EOD)",
    ),
    autonomous=Depends(get_autonomous),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get today's daily working context window.

    Returns the curated, salience-scored subset of memory that's relevant
    today. Includes council insights, memory units, signals, mandates,
    and pinned items.

    By default, returned items are marked as accessed_today so the EOD
    promote/demote cycle reinforces them. Pass ?mark_accessed=false to
    suppress (read-only dashboards that shouldn't influence reinforcement).
    """
    if not autonomous or not getattr(autonomous, "_working_context", None):
        raise HTTPException(
            status_code=503,
            detail="Working context not initialized (scheduler not running or context not yet assembled)",  # noqa: E501
        )
    ctx_window = autonomous._working_context
    ctx = ctx_window.get_current()
    if not ctx:
        return {
            "status": "not_assembled",
            "message": "Working context has not been assembled yet. Will assemble at 6am or call POST /memory/working-context/refresh.",  # noqa: E501
        }
    selected = ctx.items[:max_items]
    items = [item.to_dict() for item in selected]

    if mark_accessed and selected:
        try:
            await ctx_window.mark_accessed_batch([i.item_id for i in selected])
        except Exception as e:
            log.warning(f"[working-context] mark_accessed_batch failed: {e}")

    return {
        "date": ctx.date,
        "assembled_at": ctx.assembled_at,
        "themes": ctx.themes,
        "items": items,
        "total_items": len(ctx.items),
        "pinned_count": len(ctx.pinned_ids),
        "stats": ctx.stats,
    }


@router.get("/memory/working-context/text")
async def get_working_context_text(
    max_items: int = Query(default=20, le=50),
    autonomous=Depends(get_autonomous),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get the working context as formatted text for LLM prompt injection."""
    if not autonomous or not getattr(autonomous, "_working_context", None):
        raise HTTPException(status_code=503, detail="Working context not initialized")
    text = autonomous._working_context.get_context_text(max_items=max_items)
    return {"text": text, "has_context": bool(text)}


@router.post("/memory/working-context/refresh")
async def refresh_working_context(
    themes: list[str] | None = None,
    autonomous=Depends(get_autonomous),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Force a refresh of the daily working context.

    Re-scores existing items and pulls any new high-priority items.
    Optionally accepts a list of themes for relevance scoring.
    """
    if not autonomous or not getattr(autonomous, "_working_context", None):
        raise HTTPException(status_code=503, detail="Working context not initialized")
    ctx = await autonomous._working_context.refresh(themes=themes)
    return {
        "status": "refreshed",
        "date": ctx.date,
        "items": len(ctx.items),
        "themes": ctx.themes,
        "stats": ctx.stats,
    }


@router.post("/memory/working-context/assemble")
async def assemble_working_context(
    themes: list[str] | None = None,
    autonomous=Depends(get_autonomous),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Force a full assembly of the daily working context.

    Archives the current context and builds a fresh one from scratch.
    """
    if not autonomous or not getattr(autonomous, "_working_context", None):
        raise HTTPException(status_code=503, detail="Working context not initialized")
    ctx = await autonomous._working_context.assemble(themes=themes)
    return {
        "status": "assembled",
        "date": ctx.date,
        "items": len(ctx.items),
        "themes": ctx.themes,
        "stats": ctx.stats,
    }


@router.post("/memory/working-context/pin")
async def pin_working_context_item(
    item_id: str | None = None,
    body: dict | None = Body(default=None),
    autonomous=Depends(get_autonomous),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Pin an item to keep it in working context across days.

    Accepts either:
      - Query param ``item_id`` (legacy) — pins an existing context item.
      - JSON body with at minimum ``item_id`` or a signal payload
        (``content``/``title`` + optional ``source``/``tags``).

    If the referenced item is not already in the current working context
    (typical for an Intel-tab signal that lives only in Awarebot's tier
    buffers), this endpoint promotes the signal into the context with
    ``pinned=True`` so it survives day rollover via ``_carry_forward_pinned``.
    """
    if not autonomous or not getattr(autonomous, "_working_context", None):
        raise HTTPException(status_code=503, detail="Working context not initialized")
    wc = autonomous._working_context

    payload = dict(body) if isinstance(body, dict) else {}
    target_id = (payload.get("item_id") or item_id or "").strip()

    if target_id:
        if await wc.pin_item(target_id):
            return {"status": "pinned", "item_id": target_id, "promoted": False}

    content = (payload.get("content") or payload.get("title") or "").strip()
    if not content:
        raise HTTPException(
            status_code=404,
            detail=f"Item not found: {target_id or '(no item_id)'}",
        )

    source = payload.get("source") or "intel-signal"
    tags = payload.get("tags") or []
    promote_id = target_id or None
    item = await wc.promote_item(
        content=content,
        source=source,
        tags=tags,
        item_id=promote_id,
    )
    return {"status": "pinned", "item_id": item.item_id, "promoted": True}


@router.delete("/memory/working-context/pin")
async def unpin_working_context_item(
    item_id: str | None = None,
    body: dict | None = Body(default=None),
    autonomous=Depends(get_autonomous),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Unpin an item from working context.

    Accepts the id via query param ``item_id`` or JSON body
    ``{"item_id": ...}``. Idempotent: returns 200 with ``status=not_found``
    if the id is unknown so iOS doesn't need to track local state perfectly.
    """
    if not autonomous or not getattr(autonomous, "_working_context", None):
        raise HTTPException(status_code=503, detail="Working context not initialized")
    payload = dict(body) if isinstance(body, dict) else {}
    target_id = (payload.get("item_id") or item_id or "").strip()
    if not target_id:
        raise HTTPException(status_code=400, detail="item_id is required")
    success = await autonomous._working_context.unpin_item(target_id)
    return {
        "status": "unpinned" if success else "not_found",
        "item_id": target_id,
    }


@router.get("/memory/working-context/history")
async def get_working_context_history(
    days_back: int = Query(default=7, le=30),
    autonomous=Depends(get_autonomous),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get working context history for the last N days."""
    if not autonomous or not getattr(autonomous, "_working_context", None):
        raise HTTPException(status_code=503, detail="Working context not initialized")
    history = autonomous._working_context.get_history(days_back=days_back)
    return {"history": history, "days": len(history)}


@router.get("/memory/working-context/stats")
async def get_working_context_stats(
    autonomous=Depends(get_autonomous),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get working context statistics."""
    if not autonomous or not getattr(autonomous, "_working_context", None):
        raise HTTPException(status_code=503, detail="Working context not initialized")
    return autonomous._working_context.get_stats()


@router.post("/memory/working-context/eod")
async def trigger_working_context_eod(
    autonomous=Depends(get_autonomous),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Manually trigger end-of-day promote/demote cycle."""
    if not autonomous or not getattr(autonomous, "_working_context", None):
        raise HTTPException(status_code=503, detail="Working context not initialized")
    stats = await autonomous._working_context.end_of_day()
    return {"status": "eod_complete", **stats}


@router.post("/memory/working-context/promote")
async def promote_working_context_item(
    body: dict,
    autonomous=Depends(get_autonomous),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Promote an item into the working context with high importance and pinned."""
    if not autonomous or not getattr(autonomous, "_working_context", None):
        raise HTTPException(status_code=503, detail="Working context not initialized")
    content = body.get("content", "")
    source = body.get("source", "manual")
    tags = body.get("tags", [])
    item_id = body.get("item_id")
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    item = await autonomous._working_context.promote_item(
        content=content,
        source=source,
        tags=tags,
        item_id=item_id,
    )
    ctx = autonomous._working_context.get_current()
    return {
        "status": "ok",
        "item_id": item.item_id,
        "items_count": len(ctx.items) if ctx else 0,
    }


@router.post("/memory/working-context/dismiss")
async def dismiss_working_context_item(
    body: dict,
    autonomous=Depends(get_autonomous),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Remove an item from the current working context."""
    if not autonomous or not getattr(autonomous, "_working_context", None):
        raise HTTPException(status_code=503, detail="Working context not initialized")
    item_id = body.get("item_id", "")
    if not item_id:
        raise HTTPException(status_code=400, detail="item_id is required")
    success = await autonomous._working_context.dismiss_item(item_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Item not found: {item_id}")
    return {"status": "ok", "dismissed": item_id}


@router.post("/memory/working-context/toggle-pin")
async def toggle_pin_working_context_item(
    body: dict,
    autonomous=Depends(get_autonomous),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Toggle pin state on a working context item."""
    if not autonomous or not getattr(autonomous, "_working_context", None):
        raise HTTPException(status_code=503, detail="Working context not initialized")
    item_id = body.get("item_id", "")
    if not item_id:
        raise HTTPException(status_code=400, detail="item_id is required")
    result = await autonomous._working_context.toggle_pin(item_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Item not found: {item_id}")
    return {"status": "ok", "item_id": item_id, "pinned": result}


@router.post("/memory/working-context/score")
async def score_working_context_items(
    body: dict,
    autonomous=Depends(get_autonomous),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Score items against current context themes for relevance."""
    if not autonomous or not getattr(autonomous, "_working_context", None):
        raise HTTPException(status_code=503, detail="Working context not initialized")
    items = body.get("items", [])
    if not items:
        raise HTTPException(status_code=400, detail="items list is required")

    ctx_window = autonomous._working_context
    ctx = ctx_window.get_current()
    themes = ctx.themes if ctx else []

    scores = []
    for entry in items:
        content = entry.get("content", "")
        relevance = ctx_window.compute_relevance(content, themes)
        matched = []
        if themes:
            content_tokens = set(_re.findall(r"[a-z0-9_-]{3,}", content.lower()))
            for theme in themes:
                theme_tokens = set(_re.findall(r"[a-z0-9_-]{3,}", theme.lower()))
                if content_tokens & theme_tokens:
                    matched.append(theme)
        scores.append(
            {
                "content": content[:100],
                "relevance": round(relevance, 4),
                "matched_themes": matched,
            }
        )

    return {"scores": scores}


# ── W8-A10 additions (2026-05-24): unit delete, conflict queue, ─────────────
# authority learner history, prediction provenance.


@router.delete("/memory/unit/{unit_id}")
async def delete_memory_unit(
    unit_id: str,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Hard-delete a memory unit across all backing stores.

    Removes the unit from:
      1. ``data/memory/units.jsonl`` (atomic rewrite of survivors)
      2. ChromaDB collections (via ``delete_unit_embeddings``)
      3. NetworkX knowledge graph (drops graph nodes whose ``source_units``
         list contains *only* this unit_id; also prunes the unit_id from
         the ``source_units`` lists of nodes referenced by more units)

    Returns 404 if no unit with this id exists. No undo — caller is
    expected to gate this behind a confirmation step in the iOS UI.
    """
    if not brain or not brain.memory_store:
        raise HTTPException(status_code=503, detail="Memory store not available")

    store = brain.memory_store

    # Step 1 — locate + rewrite units.jsonl
    try:
        await store._acquire_write()
        try:
            units = await store._load_all_units()
            found = any(u.unit_id == unit_id for u in units)
            if not found:
                raise HTTPException(status_code=404, detail=f"Unit not found: {unit_id}")
            survivors = [u for u in units if u.unit_id != unit_id]
            await store._rewrite_units(survivors)
        finally:
            store._release_write()
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"[unit-delete] units.jsonl rewrite failed for {unit_id}: {e}")
        raise HTTPException(status_code=500, detail=f"jsonl rewrite failed: {e}")

    # Step 2 — Chroma embeddings (best effort)
    chroma_deleted = 0
    try:
        from ...memory.chroma_gc import delete_unit_embeddings

        chroma_deleted = await delete_unit_embeddings(store, [unit_id]) or 0
    except Exception as e:
        log.warning(f"[unit-delete] chroma cleanup failed for {unit_id}: {e}")

    # Step 3 — Knowledge graph (best effort)
    kg_nodes_dropped = 0
    kg_nodes_updated = 0
    kg = getattr(store, "_knowledge_graph", None)
    if kg is not None:
        try:
            async with kg._lock:
                graph = kg._graph
                drop_nodes: list[str] = []
                for node_id, ndata in list(graph.nodes(data=True)):
                    src_units = list(ndata.get("source_units") or [])
                    if unit_id not in src_units:
                        continue
                    remaining = [s for s in src_units if s != unit_id]
                    if not remaining and graph.degree(node_id) == 0:
                        drop_nodes.append(node_id)
                    else:
                        graph.nodes[node_id]["source_units"] = remaining
                        kg_nodes_updated += 1
                for n in drop_nodes:
                    graph.remove_node(n)
                    kg_nodes_dropped += 1
                # Edge cleanup — prune unit_id from edge source_units too
                for u, v, edata in list(graph.edges(data=True)):
                    src_units = list(edata.get("source_units") or [])
                    if unit_id in src_units:
                        edata["source_units"] = [s for s in src_units if s != unit_id]
                if kg_nodes_dropped or kg_nodes_updated:
                    await kg._persist_to_disk()
        except Exception as e:
            log.warning(f"[unit-delete] KG cleanup failed for {unit_id}: {e}")

    return {
        "deleted": True,
        "unit_id": unit_id,
        "chroma_embeddings_dropped": chroma_deleted,
        "kg_nodes_dropped": kg_nodes_dropped,
        "kg_nodes_updated": kg_nodes_updated,
    }


@router.get("/memory/conflicts/pending")
async def list_pending_conflicts(
    limit: int = Query(default=50, ge=1, le=500),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Tail the conflict-resolver arbitration queue.

    Reads ``data/memory/contradicts_index.jsonl`` (single source of truth
    written by ``ConflictResolver.link_contradicts``) and returns the
    most recent N entries in newest-first order.

    Each row exposes the iOS-friendly shape:
        {conflict_id, unit_a, unit_b, importance_delta, tags_shared,
         queued_at, severity, entity, reason}

    ``importance_delta`` is computed from the persisted ``importances``
    pair. ``tags_shared`` is the persisted ``shared_entities`` list
    (entity tokens are the resolver's notion of "shared tags").
    """
    base = os.environ.get("NCL_BASE") or os.path.expanduser("~/dev/NCL")
    path = Path(base) / "data" / "memory" / "contradicts_index.jsonl"
    if not path.exists():
        return {"count": 0, "items": [], "path": str(path), "note": "no conflicts persisted yet"}

    rows: list[dict] = []
    try:
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            async for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception as e:
        log.error(f"[conflicts/pending] read failed: {e}")
        raise HTTPException(status_code=500, detail=f"jsonl read failed: {e}")

    # Newest-first — file is append-only so reverse the tail
    rows.reverse()
    items: list[dict] = []
    for r in rows[:limit]:
        units = list(r.get("units") or [])
        imps = list(r.get("importances") or [])
        try:
            delta = abs(float(imps[0]) - float(imps[1])) if len(imps) == 2 else None
        except (TypeError, ValueError):
            delta = None
        items.append(
            {
                "conflict_id": r.get("conflict_id"),
                "unit_a": units[0] if len(units) > 0 else None,
                "unit_b": units[1] if len(units) > 1 else None,
                "importance_delta": delta,
                "tags_shared": list(
                    r.get("shared_entities") or ([r.get("entity")] if r.get("entity") else [])
                ),  # noqa: E501
                "queued_at": r.get("ts") or r.get("queued_at"),
                "severity": r.get("severity"),
                "entity": r.get("entity"),
                "reason": r.get("reason"),
                "schema_version": r.get("schema_version", 0),
            }
        )

    return {"count": len(items), "items": items}


@router.get("/memory/authority/history/{source}")
async def get_authority_learner_history(
    source: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Read the Beta-Bernoulli posterior for one source.

    Maps the on-disk ``SourceStats`` (hits/misses/partials/last_updated)
    onto the iOS-stable shape ``{source, alpha, beta, n_observations,
    ema_quality, last_updated}``. ``alpha = 1 + hits + 0.5*partials``,
    ``beta = 1 + misses + 0.5*partials``, ``ema_quality`` is the posterior
    mean (a clean 0..1 quality proxy). Returns defaults for unknown
    sources rather than 404 so iOS doesn't need to pre-check existence.
    """
    try:
        from ...feedback.source_authority_learner import get_learner

        learner = get_learner()
        all_state = learner.all_sources()
        if source in all_state:
            stats = all_state[source]
            alpha = 1.0 + stats.hits + 0.5 * stats.partials
            beta = 1.0 + stats.misses + 0.5 * stats.partials
            return {
                "source": source,
                "alpha": round(alpha, 4),
                "beta": round(beta, 4),
                "n_observations": stats.n,
                "hits": stats.hits,
                "misses": stats.misses,
                "partials": stats.partials,
                "ema_quality": round(stats.posterior_mean, 4),
                "posterior_mean": round(stats.posterior_mean, 4),
                "adjustment": round(stats.adjustment, 4),
                "last_updated": stats.last_updated,
                "known": True,
            }
        # Unknown source — return uniform prior defaults
        return {
            "source": source,
            "alpha": 1.0,
            "beta": 1.0,
            "n_observations": 0,
            "hits": 0,
            "misses": 0,
            "partials": 0,
            "ema_quality": 0.5,
            "posterior_mean": 0.5,
            "adjustment": 1.0,
            "last_updated": "",
            "known": False,
        }
    except Exception as e:
        log.error(f"[authority/history/{source}] failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/predictions/{prediction_id}/provenance")
async def get_prediction_provenance(
    prediction_id: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Trace a prediction back through cited sources → memory units → factors.

    The R-series predictor doesn't persist a one-shot ``unit_provenance``
    block. We assemble the best we can from the on-disk prediction
    record:
      - ``cited_sources_full`` / ``cited_sources_platform`` (per-platform
        feedback signals; what the authority learner sees)
      - ``linked_signals`` / ``signal_ids`` (the awarebot writer captures
        these; the council-pred writer currently emits ``signal_refs``
        indices rather than IDs — see note conditions below)
      - For each cited source, the learner's current adjustment + the
        static tier weight (best proxy for "scoring factors").

    W10A-14 (2026-05-24) shipped the live SQLite mirror hook
    (``runtime/persistence/predictions_writer.py``) so new predictions
    now persist into the ``predictions`` table behind
    ``NCL_PREDICTIONS_SQLITE``. That closes the JSON→SQLite gap but does
    NOT add a ``signal_id → unit_id`` resolver — every entry below
    still reports ``unit_id: None`` until that linkage is wired.

    Returned shape (sets ``note`` when linkage is partial):
        {prediction_id, linked_signals, unit_provenance: [...], note?}
    """
    # Locate the prediction file the same way intel.py's GET handler does
    base = os.environ.get("NCL_DATA_DIR") or "data"
    pred_dir = Path(base) / "predictions"
    if not pred_dir.is_absolute():
        ncl_base = os.environ.get("NCL_BASE") or os.path.expanduser("~/dev/NCL")
        pred_dir = Path(ncl_base) / pred_dir

    found_pred: dict | None = None
    for pattern in ("pred-*.json", "council/council-pred-*.json"):
        if found_pred:
            break
        for f in sorted(pred_dir.glob(pattern), reverse=True):
            try:
                data = json.loads(f.read_text())
            except Exception:
                continue
            preds = (
                data
                if isinstance(data, list)
                else (
                    data.get("predictions")
                    if isinstance(data, dict) and "predictions" in data
                    else [data]  # noqa: E501
                )
            )
            for pred in preds or []:
                if pred.get("prediction_id") == prediction_id:
                    found_pred = pred
                    break
            if found_pred:
                break

    if not found_pred:
        raise HTTPException(status_code=404, detail=f"Prediction not found: {prediction_id}")

    cited_platforms = list(found_pred.get("cited_sources_platform") or [])
    cited_full = list(found_pred.get("cited_sources_full") or [])
    linked_signals = list(
        found_pred.get("linked_signals")
        or found_pred.get("signal_ids")
        or found_pred.get("source_signals")
        or []
    )

    # Per-source provenance: combine static tier + learned adjustment
    unit_provenance: list[dict] = []
    try:
        from ...feedback.source_authority_learner import get_learner  # noqa: I001
        from ...memory.authority import tier_for_source, AuthorityTier

        learner = get_learner()
        all_state = learner.all_sources()
        for src in cited_full or cited_platforms:
            stats = all_state.get(src)
            try:
                tier_val = int(tier_for_source(src))
                tier_name = AuthorityTier(tier_val).name.lower()
            except Exception:
                tier_val, tier_name = 10, "raw"
            entry = {
                "source": src,
                "authority_tier": tier_val,
                "authority_tier_name": tier_name,
                "learned_adjustment": round(learner.adjustment_for(src), 4),
                "effective_weight": round(learner.effective_weight(src, tier_val / 100.0), 4),
                "factors": {
                    "static_tier": tier_val,
                    "learned_quality": (round(stats.posterior_mean, 4) if stats else 0.5),
                    "n_observations": stats.n if stats else 0,
                },
                "unit_id": None,  # signal_id → unit_id resolver not yet wired
                "importance": None,
            }
            unit_provenance.append(entry)
    except Exception as e:
        log.warning(f"[predictions/{prediction_id}/provenance] learner read failed: {e}")

    response = {
        "prediction_id": prediction_id,
        "topic": found_pred.get("topic"),
        "confidence": found_pred.get("confidence"),
        "linked_signals": linked_signals,
        "cited_sources_platform": cited_platforms,
        "cited_sources_full": cited_full,
        "unit_provenance": unit_provenance,
    }
    # W10A-14 landed the live SQLite mirror, so signal-level linkage is
    # populated on the awarebot path (council-pred writes still emit
    # signal_refs indices rather than IDs). The remaining gap is the
    # signal_id → memory unit_id resolver: every entry's unit_id is
    # None until that resolver is wired, so the note still fires.
    missing_signals = not linked_signals
    missing_units = any(p["unit_id"] is None for p in unit_provenance)
    if missing_signals or missing_units:
        if missing_signals and missing_units:
            response["note"] = (
                "linkage partial: no signal_ids persisted (council-pred "
                "path) and signal_id → unit_id resolver not yet wired"
            )
        elif missing_signals:
            response["note"] = (
                "linkage partial: no signal_ids persisted "
                "(council-pred path emits signal_refs indices instead)"
            )
        else:
            response["note"] = (
                "linkage partial: signal_id → memory unit_id resolver "
                "not yet wired (unit_id is None for every cited source)"
            )
    return response
