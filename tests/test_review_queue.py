"""Tests for NCL review queue manager."""

import tempfile

import pytest

from runtime.review_queue.manager import (
    ReviewItem,
    ReviewItemType,
    ReviewQueueManager,
    Suggestion,
    UrgencyLevel,
)


@pytest.fixture
def temp_data_dir():
    """Create temporary data directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
async def review_queue(temp_data_dir):
    """Create and initialize a review queue manager."""
    manager = ReviewQueueManager(temp_data_dir)
    await manager.init()
    return manager


def test_review_item_type_values():
    """Test review item type enum values."""
    assert ReviewItemType.PUMP == "PUMP"
    assert ReviewItemType.ACTION == "ACTION"
    assert ReviewItemType.COUNCIL == "COUNCIL"
    assert ReviewItemType.MANDATE == "MANDATE"


def test_urgency_level_values():
    """Test urgency level enum values."""
    assert UrgencyLevel.CRITICAL == "critical"
    assert UrgencyLevel.HIGH == "high"
    assert UrgencyLevel.NORMAL == "normal"
    assert UrgencyLevel.LOW == "low"


def test_review_item_creation():
    """Test creating a review item."""
    item = ReviewItem(
        item_type=ReviewItemType.PUMP,
        title="Test Pump",
        description="A test pump prompt",
        urgency=UrgencyLevel.HIGH,
        source_agent="First Strike",
        source_id="pump-123",
    )

    assert item.item_id is not None
    assert item.item_type == ReviewItemType.PUMP
    assert item.title == "Test Pump"
    assert item.urgency == UrgencyLevel.HIGH
    assert item.archived is False


@pytest.mark.asyncio
async def test_ingest_pump(review_queue):
    """Test ingesting a pump into the review queue."""
    pump_data = {
        "pump_id": "pump-001",
        "intent": "Market Signal Pump",
        "description": "Analyze recent market signal",
        "urgency": "high",
        "source_agent": "Strike Point",
        "signal": "volatility_spike",
        "market": "equities",
    }

    item = await review_queue.ingest_pump(pump_data)

    # Verify item is in queue
    items = review_queue.get_items()
    assert len(items) >= 1
    assert any(i.item_id == item.item_id for i in items)


@pytest.mark.asyncio
async def test_ingest_action(review_queue):
    """Test ingesting an action into the review queue."""
    action_data = {
        "action_id": "action-001",
        "title": "Execute Mandate",
        "description": "Dispatch mandate for market hedge",
        "urgency": "critical",
    }

    item = await review_queue.ingest_action(action_data)  # noqa: F841

    items = review_queue.get_items()
    assert any(i.source_agent == "Governance" for i in items)


@pytest.mark.asyncio
async def test_get_items_filtered(review_queue):
    """Test filtering items."""
    # Add items with different urgency levels
    for i in range(3):
        pump_data = {
            "pump_id": f"item-{i}",
            "intent": f"Item {i}",
            "description": f"Description {i}",
            "urgency": "critical" if i == 0 else "normal",
            "source_agent": "Test",
        }
        await review_queue.ingest_pump(pump_data)

    # Get all items
    all_items = review_queue.get_items()
    assert len(all_items) >= 3

    # Filter by urgency using get_items
    critical_items = review_queue.get_items(urgency_filter="critical")
    assert len(critical_items) >= 1


@pytest.mark.asyncio
async def test_batch_tag(review_queue):
    """Test batch tagging items."""
    # Create and ingest items
    items = []
    for i in range(3):
        pump_data = {
            "pump_id": f"item-{i}",
            "intent": f"Item {i}",
            "description": f"Description {i}",
            "source_agent": "Test",
        }
        item = await review_queue.ingest_pump(pump_data)
        items.append(item)

    # Tag all items
    item_ids = [item.item_id for item in items]
    tagged_items = await review_queue.batch_tag(item_ids, ["market", "high-priority"])

    # Verify tags were applied
    for item in tagged_items:
        assert "market" in item.tags
        assert "high-priority" in item.tags


@pytest.mark.asyncio
async def test_batch_link(review_queue):
    """Test batch linking items."""
    # Create and ingest items
    items = []

    pump_data = {
        "pump_id": "item-0",
        "intent": "Item 0",
        "description": "Description 0",
        "source_agent": "Test",
    }
    pump_item = await review_queue.ingest_pump(pump_data)
    items.append(pump_item)

    action_data = {"action_id": "item-1", "title": "Item 1", "description": "Description 1"}
    action_item = await review_queue.ingest_action(action_data)
    items.append(action_item)

    # Link the items using batch_link
    if len(items) >= 2:
        item_ids = [items[0].item_id, items[1].item_id]
        linked_items = await review_queue.batch_link(item_ids)

        # Verify links were created
        assert len(linked_items) == 2
        for item in linked_items:
            assert len(item.linked_items) > 0


@pytest.mark.asyncio
async def test_batch_archive(review_queue):
    """Test batch archiving items."""
    # Create and ingest items
    items = []
    for i in range(2):
        pump_data = {
            "pump_id": f"item-{i}",
            "intent": f"Item {i}",
            "description": f"Description {i}",
            "source_agent": "Test",
        }
        item = await review_queue.ingest_pump(pump_data)
        items.append(item)

    # Archive items
    item_ids = [item.item_id for item in items]
    archived_items = await review_queue.batch_archive(item_ids)

    # Verify items were archived
    assert len(archived_items) == 2
    for item in archived_items:
        assert item.archived is True


@pytest.mark.asyncio
async def test_suggestions_generated(review_queue):
    """Test that suggestions can be generated for items."""
    pump_data = {
        "pump_id": "pump-001",
        "intent": "Market Alert",
        "description": "Unusual trading volume detected",
        "urgency": "high",
        "source_agent": "Market Monitor",
    }

    item = await review_queue.ingest_pump(pump_data)

    # Suggestions are automatically generated during ingest
    assert len(item.suggestions) > 0
    # Check that at least one suggestion was created
    assert any(s.action_type in ["approve", "defer", "escalate"] for s in item.suggestions)


@pytest.mark.asyncio
async def test_stats(review_queue):
    """Test review queue statistics."""
    # Add items with different statuses
    for i in range(5):
        if i < 3:
            pump_data = {
                "pump_id": f"item-{i}",
                "intent": f"Item {i}",
                "description": f"Description {i}",
                "urgency": "critical" if i < 2 else "normal",
                "source_agent": "Test",
            }
            await review_queue.ingest_pump(pump_data)
        else:
            action_data = {
                "action_id": f"item-{i}",
                "title": f"Item {i}",
                "description": f"Description {i}",
                "urgency": "critical" if i < 2 else "normal",
            }
            await review_queue.ingest_action(action_data)

    # Get items
    items = review_queue.get_items()

    assert len(items) >= 5
    assert sum(1 for i in items if i.item_type == ReviewItemType.PUMP) >= 3
    assert sum(1 for i in items if i.item_type == ReviewItemType.ACTION) >= 2
    assert sum(1 for i in items if i.urgency == UrgencyLevel.CRITICAL) >= 2


def test_suggestion_creation():
    """Test creating a suggestion."""
    suggestion = Suggestion(
        action_text="Approve request",
        action_type="approve",
        confidence=0.92,
        reasoning="Meets all criteria and passes review",
    )

    assert suggestion.suggestion_id is not None
    assert suggestion.action_text == "Approve request"
    assert suggestion.action_type == "approve"
    assert suggestion.confidence == 0.92
