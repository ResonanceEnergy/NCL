"""
Tests for the bi-temporal knowledge graph (Loop 8).

Run:
    cd ~/dev/NCL && python -m pytest tests/test_temporal_graph.py -v
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent))

from runtime.memory.knowledge_graph import KnowledgeGraph
from runtime.memory.temporal import (
    TemporalEdge,
    TemporalGraph,
    run_temporal_rebuild,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="ncl_temporal_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def kg(temp_dir):
    """Underlying v1 KnowledgeGraph (gives us a real data_dir)."""
    return KnowledgeGraph(temp_dir)


@pytest.fixture
def tg(kg):
    g = TemporalGraph(kg)
    assert g._ensure_graph(), "networkx must be installed for these tests"
    return g


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat() if dt.tzinfo is None else dt.isoformat()


# ── 1. add_temporal_edge ────────────────────────────────────────────────


def test_add_temporal_edge_stores_and_returns_id(tg):
    edge = TemporalEdge(
        src="natrix",
        dst="resonance_energy",
        relation="OWNS",
        valid_at=_iso(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        source_unit_ids=["u-1"],
    )
    eid = tg.add_temporal_edge(edge)

    assert eid == edge.edge_id
    assert eid in tg._edges
    # And it lives on the underlying multigraph too.
    assert tg._graph.has_edge("natrix", "resonance_energy", key=eid)
    assert tg.stats()["active"] == 1


# ── 2. supersede ────────────────────────────────────────────────────────


def test_supersede_marks_old_and_chains_new(tg):
    t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 3, 1, tzinfo=timezone.utc)
    old = TemporalEdge(src="acme", dst="alice", relation="CEO_OF", valid_at=_iso(t1))
    tg.add_temporal_edge(old)

    new = TemporalEdge(src="acme", dst="bob", relation="CEO_OF", valid_at=_iso(t2))
    tg.supersede(old.edge_id, new)

    assert tg._edges[old.edge_id].invalidated_at == new.valid_at
    assert tg._edges[old.edge_id].superseded_by == new.edge_id
    assert tg._edges[new.edge_id].invalidated_at is None

    s = tg.stats()
    assert s["active"] == 1
    assert s["superseded"] == 1


# ── 3. query_at_time ────────────────────────────────────────────────────


def test_query_at_time_returns_only_valid_edges(tg):
    t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 3, 1, tzinfo=timezone.utc)

    e1 = TemporalEdge(src="acme", dst="alice", relation="CEO_OF", valid_at=_iso(t1))
    tg.add_temporal_edge(e1)
    e2 = TemporalEdge(src="acme", dst="bob", relation="CEO_OF", valid_at=_iso(t2))
    tg.supersede(e1.edge_id, e2)

    # Before t1 → nothing.
    pre = tg.query_at_time(t1 - timedelta(days=1), src="acme", relation="CEO_OF")
    assert pre == []

    # Between t1 and t2 (exclusive of t2) → only e1.
    mid = tg.query_at_time(t1 + timedelta(days=30), src="acme", relation="CEO_OF")
    assert [e.edge_id for e in mid] == [e1.edge_id]

    # At/after t2 → only e2 (e1.invalidated_at == t2, so > t2 means invalid).
    post = tg.query_at_time(t2 + timedelta(days=1), src="acme", relation="CEO_OF")
    assert [e.edge_id for e in post] == [e2.edge_id]


# ── 4. history ──────────────────────────────────────────────────────────


def test_history_returns_chain_in_order(tg):
    t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    t3 = datetime(2026, 9, 1, tzinfo=timezone.utc)

    a = TemporalEdge(src="proj", dst="planning", relation="STATUS", valid_at=_iso(t1))
    tg.add_temporal_edge(a)
    b = TemporalEdge(src="proj", dst="planning", relation="STATUS", valid_at=_iso(t2))
    tg.supersede(a.edge_id, b)
    # NOTE: we keep src/dst the same to test that history is per-relation,
    # not per-active-vs-superseded.
    c = TemporalEdge(src="proj", dst="planning", relation="STATUS", valid_at=_iso(t3))
    tg.supersede(b.edge_id, c)

    hist = tg.history("proj", "planning", "STATUS")
    assert [e.valid_at for e in hist] == [_iso(t1), _iso(t2), _iso(t3)]
    # Only the last one is still active.
    assert [e.invalidated_at is None for e in hist] == [False, False, True]


# ── 5. inferred-stale marking and persistence ──────────────────────────


def test_stale_marking_and_roundtrip_persistence(kg, tg):
    """
    Edges whose latest supporting evidence is too old should be tagged
    `inferred_stale` (NOT invalidated). And the persisted JSONL should
    survive a reload.
    """
    long_ago = datetime.now(timezone.utc) - timedelta(days=120)
    edge = TemporalEdge(
        src="$AAPL",
        dst="growing",
        relation="STATUS",
        valid_at=_iso(long_ago),
        metadata={"last_seen": _iso(long_ago)},
    )
    tg.add_temporal_edge(edge)

    tg.mark_inferred_stale(edge.edge_id)
    assert tg._edges[edge.edge_id].metadata.get("inferred_stale") is True
    # Stale != invalidated — the edge is still "active" (no contradiction).
    assert tg._edges[edge.edge_id].invalidated_at is None

    # Persist + reload via a fresh TemporalGraph wrapping the same KG.
    asyncio.run(tg.persist())
    tg2 = TemporalGraph(kg)
    assert tg2._ensure_graph()
    reloaded = tg2._edges.get(edge.edge_id)
    assert reloaded is not None
    assert reloaded.metadata.get("inferred_stale") is True
    assert reloaded.src == "$AAPL" and reloaded.dst == "growing"


# ── Bonus: run_temporal_rebuild end-to-end with a fake brain ───────────


class _FakeUnit:
    def __init__(self, uid, created_at, relationships):
        self.unit_id = uid
        self.created_at = created_at
        self.content = ""
        self.relationships = relationships


class _FakeMemoryStore:
    def __init__(self, units, kg):
        self._units = units
        self._knowledge_graph = kg

    async def _load_all_units(self):
        return list(self._units)


class _FakeBrain:
    def __init__(self, store):
        self.memory_store = store


def test_run_temporal_rebuild_creates_and_supersedes(kg):
    t_old = datetime.now(timezone.utc) - timedelta(days=3)
    t_new = datetime.now(timezone.utc) - timedelta(hours=2)

    units = [
        _FakeUnit(
            "u-1",
            t_old,
            [
                {"subject": "acme", "predicate": "CEO_OF", "object": "alice"},
            ],
        ),
        _FakeUnit(
            "u-2",
            t_new,
            [
                # Same single-valued (src, relation), new object → should supersede u-1's edge.
                {"subject": "acme", "predicate": "CEO_OF", "object": "bob"},
                # Brand-new fact.
                {"subject": "$AAPL", "predicate": "MENTIONS", "object": "earnings"},
            ],
        ),
    ]
    brain = _FakeBrain(_FakeMemoryStore(units, kg))

    counts = asyncio.run(run_temporal_rebuild(brain, lookback_days=7, stale_threshold_days=30))

    assert counts["units_scanned"] == 2
    assert counts["edges_processed"] == 3
    assert counts["new_edges"] >= 2
    assert counts["superseded"] >= 1

    # Verify by reading the freshly-persisted file via a new graph instance.
    tg2 = TemporalGraph(kg)
    assert tg2._ensure_graph()
    ceo_hist = tg2.history("acme", "alice", "CEO_OF")
    assert len(ceo_hist) == 1
    assert ceo_hist[0].invalidated_at is not None  # superseded
    active_ceo = tg2.find_active("acme", "bob", "CEO_OF")
    assert active_ceo is not None
    assert active_ceo.invalidated_at is None
