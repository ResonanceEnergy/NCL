"""Tests for runtime/memory/async_writer.py — fire-and-forget queue."""
from __future__ import annotations

import asyncio
import pytest

from runtime.memory.async_writer import (
    AsyncMemoryWriter,
    WriteRequest,
    init_async_writer,
    get_async_writer,
    _reset_singleton_for_tests,
)


# ── Fake stores ──────────────────────────────────────────────────────────


class FakeUnit:
    def __init__(self, content: str, source: str, importance: float,
                 tags=None, memory_type="episodic"):
        self.unit_id = f"unit-{id(self)}"
        self.content = content
        self.source = source
        self.importance = importance
        self.tags = tags or []
        self.memory_type = memory_type
        self.entities = []


class FakeMemoryStore:
    """In-memory stand-in. Records every create_unit/index_unit call."""

    def __init__(self, fail_on_source: str | None = None,
                 sleep_s: float = 0.0):
        self.units: list[FakeUnit] = []
        self.indexed: list[FakeUnit] = []
        self._fail_on_source = fail_on_source
        self._sleep_s = sleep_s
        self.calls = 0

    async def create_unit(self, content, source, importance=50.0,
                          tags=None, memory_type="episodic"):
        self.calls += 1
        if self._sleep_s:
            await asyncio.sleep(self._sleep_s)
        if self._fail_on_source and source == self._fail_on_source:
            raise RuntimeError(f"forced failure on {source}")
        unit = FakeUnit(content, source, importance, tags, memory_type)
        self.units.append(unit)
        return unit

    async def index_unit(self, unit):
        self.indexed.append(unit)


@pytest.fixture(autouse=True)
def _reset_singleton():
    _reset_singleton_for_tests()
    yield
    _reset_singleton_for_tests()


@pytest.fixture
def store():
    return FakeMemoryStore()


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enqueue_returns_instantly(store):
    """Producer must NOT block — even with a slow store."""
    slow_store = FakeMemoryStore(sleep_s=0.5)
    writer = AsyncMemoryWriter(slow_store, drainer_concurrency=2)
    await writer.start()
    try:
        import time
        t0 = time.monotonic()
        for i in range(20):
            await writer.enqueue(WriteRequest(
                content=f"signal {i}", source="awarebot:test", importance=60.0,
            ))
        elapsed = time.monotonic() - t0
        # 20 enqueues should be well under the 500ms-per-write blocking cost
        assert elapsed < 0.2, f"enqueue blocked: {elapsed:.3f}s"
        assert writer.get_stats()["enqueued_total"] == 20
    finally:
        await writer.stop()


@pytest.mark.asyncio
async def test_drainer_persists_to_store(store):
    """Drainer must call memory_store.create_unit for every enqueued item."""
    writer = AsyncMemoryWriter(store, drainer_concurrency=2)
    await writer.start()
    try:
        for i in range(10):
            await writer.enqueue(WriteRequest(
                content=f"signal {i}", source="awarebot:test",
                importance=60.0, tags=[f"tag{i}"],
            ))
        # Wait for drainer to catch up
        await asyncio.sleep(0.2)
        assert len(store.units) == 10
        assert writer.get_stats()["drained_total"] == 10
        assert writer.get_stats()["failed_total"] == 0
    finally:
        await writer.stop()


@pytest.mark.asyncio
async def test_backpressure_drops_oldest(store):
    """Full queue must drop OLDEST, not block the producer."""
    writer = AsyncMemoryWriter(store, max_queue=5, drainer_concurrency=0)
    # No drainers — queue fills permanently
    for i in range(8):
        await writer.enqueue(WriteRequest(
            content=f"signal {i}", source="test",
        ))
    stats = writer.get_stats()
    assert stats["enqueued_total"] == 8
    assert stats["dropped_oldest_total"] >= 3
    assert stats["queue_size"] <= 5


@pytest.mark.asyncio
async def test_dlq_captures_failed_writes():
    """Store failures must land in DLQ, not crash the drainer."""
    store = FakeMemoryStore(fail_on_source="awarebot:bad")
    writer = AsyncMemoryWriter(store, drainer_concurrency=1)
    await writer.start()
    try:
        await writer.enqueue(WriteRequest(content="bad", source="awarebot:bad"))
        await writer.enqueue(WriteRequest(content="good", source="awarebot:ok"))
        await asyncio.sleep(0.1)
        stats = writer.get_stats()
        assert stats["failed_total"] == 1
        assert stats["drained_total"] == 1
        dlq = writer.get_dlq()
        assert len(dlq) == 1
        assert dlq[0]["source"] == "awarebot:bad"
        assert "forced failure" in dlq[0]["reason"]
    finally:
        await writer.stop()


@pytest.mark.asyncio
async def test_retry_dlq_reenqueues(store):
    """retry_dlq() pushes failed requests back onto the queue."""
    bad_store = FakeMemoryStore(fail_on_source="awarebot:bad")
    writer = AsyncMemoryWriter(bad_store, drainer_concurrency=1)
    await writer.start()
    try:
        await writer.enqueue(WriteRequest(content="x", source="awarebot:bad"))
        await asyncio.sleep(0.1)
        assert len(writer.get_dlq()) == 1
        n = await writer.retry_dlq()
        assert n == 1
        await asyncio.sleep(0.1)
        # It will fail again — should be back in DLQ
        assert len(writer.get_dlq()) == 1
    finally:
        await writer.stop()


@pytest.mark.asyncio
async def test_singleton_lifecycle(store):
    """get_async_writer raises before init, returns instance after."""
    _reset_singleton_for_tests()
    with pytest.raises(RuntimeError, match="not initialized"):
        get_async_writer()
    w = init_async_writer(store)
    assert get_async_writer() is w
    # Idempotent: second init returns same instance
    w2 = init_async_writer(store)
    assert w is w2


@pytest.mark.asyncio
async def test_get_stats_shape(store):
    """get_stats must expose all the keys the API endpoint relies on."""
    writer = AsyncMemoryWriter(store, drainer_concurrency=2)
    stats = writer.get_stats()
    for key in (
        "enqueued_total", "drained_total", "failed_total",
        "queue_size", "queue_max", "dlq_size", "dlq_cap",
        "avg_drain_latency_s", "llm_scoring_calls", "llm_entity_calls",
        "drainer_concurrency", "running", "model",
    ):
        assert key in stats, f"missing stat: {key}"
    assert stats["model"] == "claude-sonnet-4-6-20250514"
    assert stats["drainer_concurrency"] == 2


@pytest.mark.asyncio
async def test_model_kwarg_passthrough_score_memory(monkeypatch, store):
    """Drainer must call score_memory with model=claude-sonnet-4-6-20250514."""
    captured = {}

    async def fake_score(content, source, tags, use_llm=True, model=None):
        captured["model"] = model
        captured["use_llm"] = use_llm
        return {"final_score": 90.0, "memory_type": "decision",
                "llm_score": 9.0, "rule_score": 9.0}

    # Force rule_based_score high so the scorer is triggered
    monkeypatch.setattr(
        "runtime.memory.importance_scorer.rule_based_score",
        lambda *a, **kw: 9.0,
    )
    monkeypatch.setattr(
        "runtime.memory.importance_scorer.score_memory",
        fake_score,
    )
    # Stub budget check
    async def fake_budget(src, est):
        return True
    monkeypatch.setattr("runtime.cost_tracker.check_budget", fake_budget)

    writer = AsyncMemoryWriter(store, drainer_concurrency=1)
    await writer.start()
    try:
        # importance=50.0 (default) triggers the scoring branch
        await writer.enqueue(WriteRequest(
            content="critical decision approved",
            source="awarebot:test",
            importance=50.0,
        ))
        await asyncio.sleep(0.2)
        assert captured.get("model") == "claude-sonnet-4-6-20250514"
        assert captured.get("use_llm") is True
        assert writer.get_stats()["llm_scoring_calls"] == 1
        # Persisted with LLM-derived importance
        assert store.units[0].importance == 90.0
    finally:
        await writer.stop()


@pytest.mark.asyncio
async def test_skip_scoring_when_caller_set_importance(monkeypatch, store):
    """If caller passed importance != 50.0, don't call the scorer."""
    called = {"n": 0}

    async def fake_score(*a, **kw):
        called["n"] += 1
        return {"final_score": 99.0, "memory_type": "episodic",
                "llm_score": 9, "rule_score": 9}

    monkeypatch.setattr(
        "runtime.memory.importance_scorer.score_memory", fake_score,
    )
    writer = AsyncMemoryWriter(store, drainer_concurrency=1)
    await writer.start()
    try:
        await writer.enqueue(WriteRequest(
            content="x", source="awarebot:test", importance=65.0,
        ))
        await asyncio.sleep(0.1)
        assert called["n"] == 0
        assert store.units[0].importance == 65.0
    finally:
        await writer.stop()


@pytest.mark.asyncio
async def test_budget_exhaustion_skips_llm(monkeypatch, store):
    """When budget closed, drainer still persists — just without LLM."""
    monkeypatch.setattr(
        "runtime.memory.importance_scorer.rule_based_score",
        lambda *a, **kw: 9.0,
    )

    async def closed_budget(*a, **kw):
        return False
    monkeypatch.setattr("runtime.cost_tracker.check_budget", closed_budget)

    writer = AsyncMemoryWriter(store, drainer_concurrency=1)
    await writer.start()
    try:
        await writer.enqueue(WriteRequest(
            content="x", source="awarebot:test", importance=50.0,
        ))
        await asyncio.sleep(0.1)
        stats = writer.get_stats()
        assert stats["llm_scoring_budget_skips"] == 1
        assert stats["llm_scoring_calls"] == 0
        # Still persisted (rule score 9 -> 90.0)
        assert len(store.units) == 1
        assert store.units[0].importance == 90.0
    finally:
        await writer.stop()
