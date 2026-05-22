"""
Bi-Temporal Knowledge Graph (Loop 8)
=====================================

Adds a temporal layer on top of the existing KnowledgeGraph so that facts can
be **superseded** rather than overwritten. Inspired by Zep / Graphiti — every
edge carries:

    * valid_at        — when the fact became true (real-world time)
    * invalidated_at  — when the fact was superseded or proven false
    * superseded_by   — id of the edge that replaced it (for forward-tracing)
    * source_unit_ids — which memory units back this edge (for evidence)

This layer is **additive**: the v1 `KnowledgeGraph` continues to work as
before. The v1 graph keeps node lifecycle / mention counts; this module
keeps the time-versioned edge history in a NetworkX `MultiDiGraph` so that
multiple parallel edges between the same nodes (different `valid_at`) can
coexist.

Storage:
    data/memory/knowledge_graph/temporal_edges.jsonl   (this module)
    data/memory/knowledge_graph/nodes.jsonl            (existing v1)
    data/memory/knowledge_graph/edges.jsonl            (existing v1)

NO LaunchAgent / scheduler changes — `run_temporal_rebuild` is exposed as a
plain async function for Night Watch Phase 2 to call after memory
consolidation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Any, Iterable

log = logging.getLogger("ncl.memory.temporal")


# ── Relations that are treated as "single-valued" (a new fact supersedes) ──
#
# These are functional relations — at any point in time only ONE object is
# valid for a given (src, relation). A new edge contradicts the old.
SINGLE_VALUED_RELATIONS = {
    "owns",
    "OWNS",
    "located_in",
    "LOCATED_IN",
    "ceo_of",
    "CEO_OF",
    "leads",
    "LEADS",
    "employs",  # not strictly single-valued but treat per-(src,dst) pair instead
    "decided",
    "DECIDED",
    "current_price",
    "CURRENT_PRICE",
    "status",
    "STATUS",
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: str) -> datetime:
    """Parse ISO-8601 into a timezone-aware datetime (defaults to UTC)."""
    if not ts:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        # Python's fromisoformat handles "+00:00" but not trailing "Z".
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


@dataclass
class TemporalEdge:
    """
    Time-versioned edge between two entities.

    Equality / identity is by `edge_id`. Two TemporalEdges with the same
    src/dst/relation/valid_at are distinct records — that supports rebuilds
    that touch the same fact at the same wall-clock time without colliding.
    """
    src: str
    dst: str
    relation: str
    valid_at: str                              # ISO-8601
    invalidated_at: Optional[str] = None       # ISO-8601 or None
    superseded_by: Optional[str] = None        # edge_id of replacement
    source_unit_ids: list[str] = field(default_factory=list)
    confidence: float = 1.0
    metadata: dict = field(default_factory=dict)
    edge_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TemporalEdge":
        # Tolerant loader — ignore unknown keys, supply defaults for missing ones.
        return cls(
            src=data.get("src", ""),
            dst=data.get("dst", ""),
            relation=data.get("relation", "RELATED_TO"),
            valid_at=data.get("valid_at") or _utcnow_iso(),
            invalidated_at=data.get("invalidated_at"),
            superseded_by=data.get("superseded_by"),
            source_unit_ids=list(data.get("source_unit_ids") or []),
            confidence=float(data.get("confidence", 1.0)),
            metadata=dict(data.get("metadata") or {}),
            edge_id=data.get("edge_id") or str(uuid.uuid4()),
        )

    def is_valid_at(self, t: datetime) -> bool:
        v_at = _parse_iso(self.valid_at)
        if v_at > t:
            return False
        if self.invalidated_at is None:
            return True
        i_at = _parse_iso(self.invalidated_at)
        return i_at > t


class TemporalGraph:
    """
    Bi-temporal layer over the existing KnowledgeGraph.

    Backed by a NetworkX MultiDiGraph keyed by edge_id so multiple parallel
    edges can coexist between the same node pair (one per validity period).
    Persists to `temporal_edges.jsonl` next to the v1 nodes/edges files.
    """

    def __init__(self, knowledge_graph) -> None:
        """
        Args:
            knowledge_graph: existing v1 KnowledgeGraph instance (for shared
                             persistence directory + node lifecycle reuse).
                             May be None for standalone tests — in that case
                             we resolve a default `data/memory/knowledge_graph`
                             relative to the cwd.
        """
        self.kg = knowledge_graph
        if knowledge_graph is not None and getattr(knowledge_graph, "data_dir", None):
            self.data_dir = Path(knowledge_graph.data_dir)
        else:
            self.data_dir = Path("data") / "memory" / "knowledge_graph"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.edges_file = self.data_dir / "temporal_edges.jsonl"

        self._graph = None       # NetworkX MultiDiGraph (lazy)
        self._nx = None
        self._edges: dict[str, TemporalEdge] = {}  # edge_id → TemporalEdge
        self._lock = asyncio.Lock()

    # ── Lifecycle ────────────────────────────────────────────────────────

    def _ensure_graph(self) -> bool:
        if self._graph is not None:
            return True
        try:
            import networkx as nx
            self._nx = nx
            self._graph = nx.MultiDiGraph()
            self._load_from_disk()
            log.info(
                "TemporalGraph initialized: %d nodes, %d edges (%d active)",
                self._graph.number_of_nodes(),
                self._graph.number_of_edges(),
                sum(1 for e in self._edges.values() if e.invalidated_at is None),
            )
            return True
        except ImportError:
            log.info("networkx not installed — TemporalGraph disabled")
            return False
        except Exception as e:                  # pragma: no cover (defensive)
            log.warning("TemporalGraph init failed: %s", e)
            return False

    def _load_from_disk(self) -> None:
        if not self.edges_file.exists():
            return
        try:
            with open(self.edges_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        edge = TemporalEdge.from_dict(json.loads(line))
                    except (json.JSONDecodeError, KeyError, TypeError) as e:
                        log.debug("skip malformed temporal edge: %s", e)
                        continue
                    self._edges[edge.edge_id] = edge
                    self._graph.add_edge(
                        edge.src, edge.dst, key=edge.edge_id,
                        relation=edge.relation,
                        valid_at=edge.valid_at,
                        invalidated_at=edge.invalidated_at,
                    )
        except Exception as e:                  # pragma: no cover
            log.warning("Failed to load temporal edges: %s", e)

    async def _persist_to_disk(self) -> None:
        """Atomically rewrite the JSONL file."""
        tmp = str(self.edges_file) + ".tmp"
        try:
            with open(tmp, "w") as f:
                for edge in self._edges.values():
                    f.write(json.dumps(edge.to_dict(), default=str) + "\n")
            os.replace(tmp, str(self.edges_file))
        except Exception as e:                  # pragma: no cover
            log.error("Failed to persist temporal edges: %s", e)
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # ── Public API ───────────────────────────────────────────────────────

    def add_temporal_edge(self, edge: TemporalEdge) -> str:
        """
        Add a new temporal edge. Returns the edge_id.

        Does NOT auto-supersede — caller is responsible for calling
        `supersede(...)` when a new edge invalidates an old one.
        """
        if not self._ensure_graph():
            return edge.edge_id

        if not edge.src or not edge.dst:
            raise ValueError("TemporalEdge requires non-empty src and dst")

        self._edges[edge.edge_id] = edge
        self._graph.add_edge(
            edge.src, edge.dst, key=edge.edge_id,
            relation=edge.relation,
            valid_at=edge.valid_at,
            invalidated_at=edge.invalidated_at,
        )
        return edge.edge_id

    def supersede(self, old_edge_id: str, new_edge: TemporalEdge) -> None:
        """
        Mark `old_edge_id` as invalidated at `new_edge.valid_at` and
        record the forward pointer. The new edge itself is also added.
        """
        if not self._ensure_graph():
            return
        old = self._edges.get(old_edge_id)
        if old is None:
            log.debug("supersede: unknown old_edge_id=%s", old_edge_id)
            # Still add the new edge.
            self.add_temporal_edge(new_edge)
            return

        # Ensure the new edge is registered first so we can point to it.
        if new_edge.edge_id not in self._edges:
            self.add_temporal_edge(new_edge)

        old.invalidated_at = new_edge.valid_at
        old.superseded_by = new_edge.edge_id

        # Reflect mutation on the multigraph as well.
        try:
            self._graph[old.src][old.dst][old.edge_id]["invalidated_at"] = old.invalidated_at
        except KeyError:                        # pragma: no cover
            pass

    def query_at_time(
        self,
        t: datetime,
        src: Optional[str] = None,
        relation: Optional[str] = None,
    ) -> list[TemporalEdge]:
        """
        Return edges that were VALID at time `t`.

        Either `src` or `relation` may be None to widen the query. Both None
        scans every edge — fine at NCL scale (<50k edges target).
        """
        if not self._ensure_graph():
            return []
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)

        result: list[TemporalEdge] = []
        for edge in self._edges.values():
            if src is not None and edge.src != src:
                continue
            if relation is not None and edge.relation != relation:
                continue
            if edge.is_valid_at(t):
                result.append(edge)
        return result

    def history(self, src: str, dst: str, relation: str) -> list[TemporalEdge]:
        """
        Return every edge between `src` and `dst` with this `relation`,
        sorted by `valid_at` ascending — the supersede chain in order.
        """
        if not self._ensure_graph():
            return []
        rows = [
            e for e in self._edges.values()
            if e.src == src and e.dst == dst and e.relation == relation
        ]
        rows.sort(key=lambda e: _parse_iso(e.valid_at))
        return rows

    def find_active(
        self, src: str, dst: str, relation: str
    ) -> Optional[TemporalEdge]:
        """Convenience: most recent active edge (None if all superseded)."""
        if not self._ensure_graph():
            return None
        active = [
            e for e in self._edges.values()
            if e.src == src and e.dst == dst and e.relation == relation
            and e.invalidated_at is None
        ]
        if not active:
            return None
        active.sort(key=lambda e: _parse_iso(e.valid_at), reverse=True)
        return active[0]

    def find_active_for_subject(
        self, src: str, relation: str
    ) -> list[TemporalEdge]:
        """All currently-active edges where (src, relation, *) holds."""
        if not self._ensure_graph():
            return []
        return [
            e for e in self._edges.values()
            if e.src == src and e.relation == relation
            and e.invalidated_at is None
        ]

    def mark_inferred_stale(self, edge_id: str) -> None:
        """
        Tag an edge as `inferred_stale` in metadata without invalidating it
        — caller hasn't seen contradictory evidence, just absence of recent
        supporting evidence.
        """
        edge = self._edges.get(edge_id)
        if edge is None:
            return
        edge.metadata = {**edge.metadata, "inferred_stale": True,
                         "stale_marked_at": _utcnow_iso()}

    def stats(self) -> dict:
        if not self._ensure_graph():
            return {"status": "disabled", "edges": 0, "active": 0}
        total = len(self._edges)
        active = sum(1 for e in self._edges.values() if e.invalidated_at is None)
        stale = sum(1 for e in self._edges.values()
                    if e.metadata.get("inferred_stale"))
        return {
            "status": "active",
            "nodes": self._graph.number_of_nodes(),
            "edges": total,
            "active": active,
            "superseded": total - active,
            "inferred_stale": stale,
        }

    async def persist(self) -> None:
        """Public wrapper so callers (the rebuild loop, tests) can flush."""
        async with self._lock:
            await self._persist_to_disk()


# ─────────────────────────────────────────────────────────────────────────
# Nightly rebuild loop — called from Night Watch Phase 2.
# ─────────────────────────────────────────────────────────────────────────

def _normalize_relation(predicate: str) -> str:
    """Uppercase + strip — predicates can come in inconsistently."""
    return (predicate or "RELATED_TO").strip().upper()


def _is_single_valued(relation: str) -> bool:
    return relation.lower() in {r.lower() for r in SINGLE_VALUED_RELATIONS}


def _unit_created_at(unit: Any) -> datetime:
    """Robust accessor for the unit timestamp — defaults to 'now'."""
    ca = getattr(unit, "created_at", None)
    if isinstance(ca, datetime):
        return ca if ca.tzinfo else ca.replace(tzinfo=timezone.utc)
    if isinstance(ca, str):
        return _parse_iso(ca)
    return datetime.now(timezone.utc)


def _unit_id(unit: Any) -> str:
    return str(getattr(unit, "unit_id", "") or getattr(unit, "id", "") or "")


def _unit_content(unit: Any) -> str:
    return str(getattr(unit, "content", "") or "")


def _unit_relationships(unit: Any) -> list[dict]:
    """
    Return relationships already extracted on the unit. We do NOT call the
    LLM here — that work is owned by the entity extractor (which the memory
    consolidation loop already invokes).
    """
    rels = getattr(unit, "relationships", None)
    if not rels:
        return []
    out: list[dict] = []
    for r in rels:
        if not isinstance(r, dict):
            continue
        subj = (r.get("subject") or "").strip()
        pred = _normalize_relation(r.get("predicate") or "")
        obj = (r.get("object") or "").strip()
        if subj and obj:
            out.append({"subject": subj, "predicate": pred, "object": obj})
    return out


async def run_temporal_rebuild(
    brain: Any,
    *,
    lookback_days: int = 7,
    stale_threshold_days: int = 30,
) -> dict:
    """
    Nightly temporal-graph maintenance pass.

    1. Walk memory units created in the last `lookback_days` days.
    2. Reuse relationships already extracted on each unit (the entity
       extractor runs during memory consolidation — we don't duplicate it).
    3. For each (subject, predicate, object) found:
         * If no existing edge → add it with `valid_at = unit.created_at`.
         * If matches existing active edge → bump `last_seen` metadata.
         * If contradicts an existing active edge (single-valued relation
           with a different object for the same subject) → supersede.
    4. Mark edges with no supporting unit in the last `stale_threshold_days`
       days as `inferred_stale`.
    5. Persist to `temporal_edges.jsonl`.

    Returns a counts dict suitable for Night Watch synthesis.
    """
    result = {
        "edges_processed": 0,
        "new_edges": 0,
        "reinforced": 0,
        "superseded": 0,
        "stale": 0,
        "units_scanned": 0,
        "skipped_no_kg": False,
    }

    memory_store = getattr(brain, "memory_store", None)
    if memory_store is None:
        result["skipped_no_kg"] = True
        return result

    kg = (
        getattr(memory_store, "_knowledge_graph", None)
        or getattr(brain, "knowledge_graph", None)
    )
    # We can run with no v1 KG — TemporalGraph will fall back to a default
    # data dir — but log it so it's visible during ops.
    if kg is None:
        log.info("run_temporal_rebuild: no v1 KnowledgeGraph — using default data dir")

    tg = TemporalGraph(kg)
    if not tg._ensure_graph():
        result["skipped_no_kg"] = True
        return result

    # 1. Pull recent units.
    try:
        units = await memory_store._load_all_units()
    except Exception as e:
        log.warning("run_temporal_rebuild: _load_all_units failed: %s", e)
        return result

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    recent = [u for u in units if _unit_created_at(u) >= cutoff]
    result["units_scanned"] = len(recent)

    # 2 & 3. Walk relationships per unit.
    async with tg._lock:
        for unit in recent:
            uid = _unit_id(unit)
            u_ts = _unit_created_at(unit).isoformat()

            for rel in _unit_relationships(unit):
                result["edges_processed"] += 1
                subj = rel["subject"]
                pred = rel["predicate"]
                obj = rel["object"]

                active_exact = tg.find_active(subj, obj, pred)
                if active_exact is not None:
                    # Same fact, reinforce.
                    if uid and uid not in active_exact.source_unit_ids:
                        active_exact.source_unit_ids.append(uid)
                        active_exact.source_unit_ids = active_exact.source_unit_ids[-25:]
                    active_exact.metadata["last_seen"] = u_ts
                    active_exact.metadata["seen_count"] = int(
                        active_exact.metadata.get("seen_count", 1)
                    ) + 1
                    result["reinforced"] += 1
                    continue

                # Contradiction check — single-valued relations only.
                if _is_single_valued(pred):
                    competing = [
                        e for e in tg.find_active_for_subject(subj, pred)
                        if e.dst != obj
                    ]
                else:
                    competing = []

                new_edge = TemporalEdge(
                    src=subj, dst=obj, relation=pred,
                    valid_at=u_ts,
                    source_unit_ids=[uid] if uid else [],
                    confidence=1.0,
                    metadata={"last_seen": u_ts, "seen_count": 1,
                              "ingested_at": _utcnow_iso()},
                )

                if competing:
                    # First add the replacement, then supersede each competitor.
                    tg.add_temporal_edge(new_edge)
                    for old in competing:
                        tg.supersede(old.edge_id, new_edge)
                        result["superseded"] += 1
                    result["new_edges"] += 1
                else:
                    tg.add_temporal_edge(new_edge)
                    result["new_edges"] += 1

        # 4. Stale marking — edges with no supporting unit recent enough.
        stale_cutoff = datetime.now(timezone.utc) - timedelta(days=stale_threshold_days)
        for edge in tg._edges.values():
            if edge.invalidated_at is not None:
                continue
            if edge.metadata.get("inferred_stale"):
                continue
            last_seen_str = edge.metadata.get("last_seen") or edge.valid_at
            last_seen = _parse_iso(last_seen_str)
            if last_seen < stale_cutoff:
                tg.mark_inferred_stale(edge.edge_id)
                result["stale"] += 1

        # 5. Persist.
        await tg._persist_to_disk()

    log.info("run_temporal_rebuild: %s", result)
    return result


__all__ = [
    "TemporalEdge",
    "TemporalGraph",
    "run_temporal_rebuild",
    "SINGLE_VALUED_RELATIONS",
]
