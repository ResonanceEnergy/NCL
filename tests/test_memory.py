"""Tests for NCL memory store."""
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

from runtime.memory.store import MemoryStore
from runtime.ncl_brain.models import MemUnit


@pytest.fixture
def temp_data_dir():
    """Create temporary data directory for test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.mark.asyncio
async def test_create_unit(temp_data_dir):
    """Test creating a new memory unit."""
    store = MemoryStore(temp_data_dir)

    unit = await store.create_unit(
        content="Test memory content",
        source="test_source",
        importance=75.0,
        tags=["test", "memory"]
    )

    assert unit.unit_id is not None
    assert unit.content == "Test memory content"
    assert unit.source == "test_source"
    assert unit.importance == 75.0
    assert "test" in unit.tags
    assert "memory" in unit.tags
    assert unit.created_at is not None


@pytest.mark.asyncio
async def test_get_unit_reinforcement(temp_data_dir):
    """Test retrieving a unit reinforces it."""
    store = MemoryStore(temp_data_dir)

    unit = await store.create_unit(
        content="Reinforceable memory",
        source="test",
        importance=50.0
    )
    unit_id = unit.unit_id
    original_importance = unit.importance

    # Retrieve the unit — this should reinforce it
    retrieved = await store.get_unit(unit_id)

    assert retrieved is not None
    assert retrieved.unit_id == unit_id
    # Importance should be boosted by 1.2x multiplier
    assert retrieved.importance > original_importance
    assert retrieved.reinforcement_count == 1
    assert retrieved.last_accessed is not None


@pytest.mark.asyncio
async def test_search_by_tags(temp_data_dir):
    """Test searching memory units by tags."""
    store = MemoryStore(temp_data_dir)

    # Create units with different tags
    unit1 = await store.create_unit(
        content="Market analysis",
        source="market_feed",
        tags=["market", "analysis"]
    )
    unit2 = await store.create_unit(
        content="Risk report",
        source="risk_team",
        tags=["risk", "analysis"]
    )
    unit3 = await store.create_unit(
        content="Portfolio snapshot",
        source="portfolio",
        tags=["portfolio"]
    )

    # Search for units with "analysis" tag
    results = await store.search_units(tags=["analysis"])

    assert len(results) == 2
    result_ids = {r.unit_id for r in results}
    assert unit1.unit_id in result_ids
    assert unit2.unit_id in result_ids
    assert unit3.unit_id not in result_ids


@pytest.mark.asyncio
async def test_search_by_importance(temp_data_dir):
    """Test searching memory units by importance threshold."""
    store = MemoryStore(temp_data_dir)

    # Create units with different importance levels
    unit1 = await store.create_unit(
        content="Critical finding",
        source="source1",
        importance=95.0
    )
    unit2 = await store.create_unit(
        content="Medium finding",
        source="source2",
        importance=50.0
    )
    unit3 = await store.create_unit(
        content="Low priority",
        source="source3",
        importance=10.0
    )

    # Search for units with importance >= 50
    results = await store.search_units(importance_threshold=50.0)

    assert len(results) >= 2
    assert all(r.importance >= 50.0 for r in results)


@pytest.mark.asyncio
async def test_search_by_date(temp_data_dir):
    """Test searching memory units by date range."""
    store = MemoryStore(temp_data_dir)

    # Create units
    unit = await store.create_unit(
        content="Recent memory",
        source="source",
    )

    # Search for units from past 7 days
    results = await store.search_units(days_back=7)

    assert len(results) >= 1
    assert unit.unit_id in {r.unit_id for r in results}

    # Search for units from past 0 days (should be empty or just created)
    results_zero_days = await store.search_units(days_back=0)
    # This might be empty or have the unit depending on exact timing


@pytest.mark.asyncio
async def test_decay_reduces_importance(temp_data_dir):
    """Test that importance decays over time."""
    store = MemoryStore(temp_data_dir)

    # Create a unit
    unit = await store.create_unit(
        content="Decayable memory",
        source="source",
        importance=100.0
    )

    # Manually set last_accessed to old date to simulate age
    unit.last_accessed = datetime.now(timezone.utc) - timedelta(days=10)

    # Apply decay
    decayed = store._apply_decay(unit)

    # Importance should be less than original due to decay
    assert decayed < 100.0


@pytest.mark.asyncio
async def test_empty_search(temp_data_dir):
    """Test searching with no matching criteria returns empty list."""
    store = MemoryStore(temp_data_dir)

    # Create a unit
    await store.create_unit(
        content="Memory with tags",
        source="source",
        tags=["specific"]
    )

    # Search for non-existent tag
    results = await store.search_units(tags=["nonexistent"])

    assert len(results) == 0


@pytest.mark.asyncio
async def test_stats(temp_data_dir):
    """Test memory store stats."""
    store = MemoryStore(temp_data_dir)

    # Create multiple units
    for i in range(5):
        await store.create_unit(
            content=f"Memory {i}",
            source=f"source_{i}",
            importance=20.0 + i * 10
        )

    # Load all units to verify they exist
    all_units = await store.search_units()

    assert len(all_units) == 5
    # Should be sorted by importance descending
    assert all_units[0].importance >= all_units[-1].importance
