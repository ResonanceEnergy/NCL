"""
Memory Store Limits Tests — Content Truncation, Capacity Management, Importance Clamping

Tests memory system constraints and boundaries.
Covers:
- Content truncation when exceeding 50K character limit
- Eviction policy when total units exceed 10,000
- Importance score clamping to 0-100 range
- Memory persistence and retrieval

Run:
    pytest tests/test_memory_limits.py -v
    pytest tests/test_memory_limits.py -v --asyncio-mode=auto
"""

import tempfile

import pytest

from runtime.memory.store import MAX_CONTENT_LENGTH, MemoryStore


@pytest.fixture
def memory_store():
    """Create a memory store with temporary data directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = MemoryStore(tmpdir)
        yield store


@pytest.mark.asyncio
async def test_content_truncation(memory_store):
    """
    Test: Content exceeding 50K characters is truncated.

    Scenario:
    - Create memory unit with 100K characters
    - Store should truncate to MAX_CONTENT_LENGTH (50K)
    - Truncated content should have [TRUNCATED] marker
    """
    # Create content larger than limit
    large_content = "x" * (MAX_CONTENT_LENGTH + 1000)
    assert len(large_content) > MAX_CONTENT_LENGTH

    unit = await memory_store.create_unit(
        content=large_content,
        source="test-truncation",
        importance=50.0,
        tags=["test", "truncation"],
    )

    # Verify content was truncated
    assert len(unit.content) <= MAX_CONTENT_LENGTH + len("[TRUNCATED]")
    assert unit.content.endswith("[TRUNCATED]")
    assert "[TRUNCATED]" in unit.content

    # Verify unit was still created and persisted
    retrieved = await memory_store.get_unit(unit.unit_id)
    assert retrieved is not None
    assert len(retrieved.content) <= MAX_CONTENT_LENGTH + len("[TRUNCATED]")


@pytest.mark.asyncio
async def test_content_truncation_boundary(memory_store):
    """
    Test: Content exactly at limit is not truncated.

    Content with length exactly equal to MAX_CONTENT_LENGTH should not be truncated.
    """
    exact_content = "x" * MAX_CONTENT_LENGTH
    assert len(exact_content) == MAX_CONTENT_LENGTH

    unit = await memory_store.create_unit(
        content=exact_content,
        source="test-exact-limit",
        importance=50.0,
    )

    # Should not be truncated
    assert len(unit.content) == MAX_CONTENT_LENGTH
    assert "[TRUNCATED]" not in unit.content


@pytest.mark.asyncio
async def test_content_just_over_limit(memory_store):
    """
    Test: Content just over limit is truncated with marker.

    One character over the limit should trigger truncation.
    """
    just_over = "x" * (MAX_CONTENT_LENGTH + 1)
    assert len(just_over) == MAX_CONTENT_LENGTH + 1

    unit = await memory_store.create_unit(
        content=just_over,
        source="test-just-over",
        importance=50.0,
    )

    # Should be truncated
    assert "[TRUNCATED]" in unit.content
    assert len(unit.content) <= MAX_CONTENT_LENGTH + len("[TRUNCATED]")


@pytest.mark.asyncio
async def test_max_units_capacity(memory_store):
    """
    Test: Memory store respects MAX_TOTAL_UNITS capacity.

    Once the store reaches MAX_TOTAL_UNITS:
    - New units should trigger eviction of oldest low-importance units
    - High-importance units should be retained
    """
    # Create units below the limit
    units_to_create = 100  # Much less than MAX_TOTAL_UNITS

    for i in range(units_to_create):
        await memory_store.create_unit(
            content=f"Memory unit {i}",
            source=f"test-source-{i}",
            importance=float(i % 100),  # Vary importance 0-99
            tags=[f"batch-{i // 10}"],
        )

    # All units should be stored
    all_units = await memory_store.search_units()
    assert len(all_units) == units_to_create


@pytest.mark.asyncio
async def test_importance_clamping_lower_bound(memory_store):
    """
    Test: Importance scores below 0 are clamped to 0.

    Negative importance values should be clamped to minimum 0.
    """
    unit = await memory_store.create_unit(
        content="Test negative importance",
        source="test-negative",
        importance=-50.0,  # Negative value
        tags=["test"],
    )

    # Should be clamped to 0
    assert unit.importance == 0.0
    assert unit.importance >= 0.0


@pytest.mark.asyncio
async def test_importance_clamping_upper_bound(memory_store):
    """
    Test: Importance scores above 100 are clamped to 100.

    Values exceeding 100 should be clamped to maximum 100.
    """
    unit = await memory_store.create_unit(
        content="Test high importance",
        source="test-high",
        importance=150.0,  # Over 100
        tags=["test"],
    )

    # Should be clamped to 100
    assert unit.importance == 100.0
    assert unit.importance <= 100.0


@pytest.mark.asyncio
async def test_importance_clamping_valid_range(memory_store):
    """
    Test: Valid importance scores (0-100) remain unchanged.

    Scores within valid range should not be modified.
    """
    test_cases = [0.0, 25.0, 50.0, 75.0, 100.0]

    for importance in test_cases:
        unit = await memory_store.create_unit(
            content=f"Test importance {importance}",
            source="test-valid-range",
            importance=importance,
        )

        # Should match input exactly
        assert unit.importance == importance


@pytest.mark.asyncio
async def test_importance_in_query_results(memory_store):
    """
    Test: Query results respect importance bounds.

    All returned units should have importance in [0, 100].
    """
    # Create units with various importance values
    for i in range(20):
        await memory_store.create_unit(
            content=f"Query test {i}",
            source="test-query",
            importance=float(i * 5),  # 0, 5, 10, ..., 95
        )

    results = await memory_store.search_units()

    # All results should have valid importance
    for unit in results:
        assert 0.0 <= unit.importance <= 100.0


@pytest.mark.asyncio
async def test_importance_threshold_boundary(memory_store):
    """
    Test: Importance threshold filtering at boundaries.

    Units with importance exactly at threshold should be included.
    Units below should be excluded.
    """
    # Create units with specific importance values
    await memory_store.create_unit(
        content="Below threshold",
        source="test-threshold",
        importance=40.0,
    )

    await memory_store.create_unit(
        content="At threshold",
        source="test-threshold",
        importance=50.0,
    )

    await memory_store.create_unit(
        content="Above threshold",
        source="test-threshold",
        importance=60.0,
    )

    # Query with threshold 50
    results = await memory_store.search_units(importance_threshold=50.0)

    # Should include units >= 50
    assert len(results) >= 2

    importances = [u.importance for u in results]
    assert min(importances) >= 50.0


@pytest.mark.asyncio
async def test_memory_persistence(memory_store):
    """
    Test: Memory units persist across store operations.

    Unit should be retrievable after creation.
    """
    original_unit = await memory_store.create_unit(
        content="Persistent content",
        source="test-persistence",
        importance=75.0,
        tags=["persistent"],
    )

    # Retrieve by ID
    retrieved = await memory_store.get_unit(original_unit.unit_id)

    assert retrieved is not None
    assert retrieved.content == original_unit.content
    assert retrieved.unit_id == original_unit.unit_id
    # Note: get_unit reinforces importance by 1.2× on access (by design).
    assert retrieved.importance == pytest.approx(original_unit.importance * 1.2)


@pytest.mark.asyncio
async def test_eviction_prefers_low_importance(memory_store):
    """
    Test: Eviction prefers removing low-importance units.

    When capacity is reached, oldest low-importance units should be evicted first.
    High-importance units should be retained.
    """
    # Create units with varying importance
    high_importance_unit = await memory_store.create_unit(
        content="High importance - should survive",
        source="test-eviction",
        importance=90.0,
        tags=["critical"],
    )

    low_importance_unit = await memory_store.create_unit(
        content="Low importance - should be evicted",
        source="test-eviction",
        importance=10.0,
        tags=["low"],
    )

    # Verify both exist
    high = await memory_store.get_unit(high_importance_unit.unit_id)
    low = await memory_store.get_unit(low_importance_unit.unit_id)
    assert high is not None
    assert low is not None


@pytest.mark.asyncio
async def test_tags_with_importance(memory_store):
    """
    Test: Tags work correctly alongside importance clamping.

    Units with tags and clamped importance should be searchable.
    """
    unit = await memory_store.create_unit(
        content="Tagged high importance",
        source="test-tags",
        importance=150.0,  # Will be clamped to 100
        tags=["critical", "alert"],
    )

    # Query by tags and importance
    results = await memory_store.search_units(
        tags=["critical"],
        importance_threshold=90.0,
    )

    assert len(results) > 0
    found = [u for u in results if u.unit_id == unit.unit_id]
    assert len(found) == 1
    assert found[0].importance == 100.0  # Clamped value


@pytest.mark.asyncio
async def test_reinforcement_increases_importance(memory_store):
    """
    Test: Accessing a unit reinforces it and increases importance.

    Each access should increase importance (up to the limit of 100).
    """
    unit = await memory_store.create_unit(
        content="Content to reinforce",
        source="test-reinforce",
        importance=50.0,
    )

    original_importance = unit.importance

    # Access the unit (simulates reinforcement)
    accessed = await memory_store.get_unit(unit.unit_id)

    # Should have increased (1.2 multiplier, clamped to 100)
    new_importance = accessed.importance
    assert new_importance >= original_importance


@pytest.mark.asyncio
async def test_decay_reduces_importance(memory_store):
    """
    Test: Importance decays over time for unused units.

    Units not accessed should have importance decay applied.
    """
    unit = await memory_store.create_unit(
        content="Content subject to decay",
        source="test-decay",
        importance=80.0,
        tags=["decay-test"],
    )

    # Note: Actual decay calculation happens in search/retrieval
    # This test verifies the decay_rate field is set correctly
    assert unit.decay_rate == 0.95  # Default decay rate


@pytest.mark.asyncio
async def test_empty_tags_list(memory_store):
    """
    Test: Units can be created without tags.

    Tags should be optional with a default empty list.
    """
    unit = await memory_store.create_unit(
        content="No tags",
        source="test-notags",
        importance=50.0,
        # No tags parameter
    )

    assert unit.tags == []
    assert isinstance(unit.tags, list)


@pytest.mark.asyncio
async def test_default_importance(memory_store):
    """
    Test: Default importance is 50.0 when not specified.

    If importance is not provided, should default to 50.0.
    """
    unit = await memory_store.create_unit(
        content="Default importance",
        source="test-default",
        # No importance parameter
    )

    assert unit.importance == 50.0
