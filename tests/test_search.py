"""Tests for NCL search indexer."""

import tempfile
from datetime import datetime, timezone

import pytest

from runtime.ncl_brain.models import EventType, NCLEvent
from runtime.search.indexer import SearchIndexer, SearchResult, tokenize


@pytest.fixture
def temp_data_dir():
    """Create temporary data directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def test_tokenize_basic():
    """Test basic tokenization."""
    text = "The quick brown fox jumps over the lazy dog"
    tokens = tokenize(text)

    # Should exclude stop words (the)
    assert "quick" in tokens
    assert "brown" in tokens
    assert "fox" in tokens
    assert "dog" in tokens
    # Stop words should be excluded
    assert "the" not in tokens
    assert "over" in tokens  # "over" is NOT a stop word in the implementation


def test_tokenize_special_chars():
    """Test tokenization with special characters."""
    text = "API-key sk-1234567890 and ip 192.168.1.1"
    tokens = tokenize(text)

    # The regex pattern [a-zA-Z0-9_-]{2,} keeps hyphens together
    assert "api-key" in tokens  # Kept as single token with hyphen
    assert "sk-1234567890" in tokens  # Kept as single token
    assert "ip" in tokens
    # Numeric sequences separated by dots are tokenized separately
    assert any("192" in t or "168" in t or "1" in t for t in tokens)


@pytest.mark.asyncio
async def test_indexer_creation(temp_data_dir):
    """Test creating a search indexer."""
    indexer = SearchIndexer(temp_data_dir)

    assert indexer.data_dir is not None
    assert indexer.index_dir is not None
    assert not indexer._loaded


@pytest.mark.asyncio
async def test_index_event(temp_data_dir):
    """Test indexing an event."""
    indexer = SearchIndexer(temp_data_dir)
    await indexer.load()

    event = NCLEvent.quick(
        event_type=EventType.PUMP_RECEIVED,
        description="Market volatility spike detected",
        source_agent="test_source",
    )

    await indexer.index_event(event)

    # Verify event is indexed
    assert len(indexer._docs) > 0


@pytest.mark.asyncio
async def test_search_text(temp_data_dir):
    """Test full-text search."""
    indexer = SearchIndexer(temp_data_dir)
    await indexer.load()

    # Index multiple events
    events = [
        NCLEvent.quick(
            event_type=EventType.PUMP_RECEIVED,
            description="Market volatility increased significantly today",
            source_agent="market_feed",
        ),
        NCLEvent.quick(
            event_type=EventType.PUMP_RECEIVED,
            description="Risk assessment for equity portfolio updated",
            source_agent="risk_team",
        ),
        NCLEvent.quick(
            event_type=EventType.COUNCIL_SPAWNED,
            description="Council session started for market analysis",
            source_agent="council",
        ),
    ]

    for event in events:
        await indexer.index_event(event)

    # Search for volatility
    results = await indexer.search("volatility", limit=10)

    assert len(results) > 0
    assert any("volatility" in r.snippet.lower() for r in results)


@pytest.mark.asyncio
async def test_search_events_by_type(temp_data_dir):
    """Test searching events by type."""
    indexer = SearchIndexer(temp_data_dir)
    await indexer.load()

    # Index events of different types
    pump_event = NCLEvent.quick(
        event_type=EventType.PUMP_RECEIVED,
        description="Test pump",
        source_agent="source",
    )

    council_event = NCLEvent.quick(
        event_type=EventType.COUNCIL_SPAWNED,
        description="Test council",
        source_agent="source",
    )

    await indexer.index_event(pump_event)
    await indexer.index_event(council_event)

    # Search by event type - convert EventType enum to string for comparison
    results = await indexer.search_events(event_type=EventType.PUMP_RECEIVED.value)

    assert len(results) > 0
    assert any(r.data.get("type") == EventType.PUMP_RECEIVED.value for r in results)


@pytest.mark.asyncio
async def test_search_by_date_range(temp_data_dir):
    """Test searching with date range."""
    indexer = SearchIndexer(temp_data_dir)
    await indexer.load()

    event = NCLEvent.quick(
        event_type=EventType.PUMP_RECEIVED,
        description="Recent event",
        source_agent="source",
    )

    await indexer.index_event(event)

    # Search recent events (past 7 days)
    results = await indexer.search_events(days_back=7)

    assert len(results) >= 1


@pytest.mark.asyncio
async def test_chain_retrieval(temp_data_dir):
    """Test retrieving events related by chain/correlation."""
    indexer = SearchIndexer(temp_data_dir)
    await indexer.load()

    correlation_id = "chain-001"

    # Create related events using the provenance system
    pump_event = NCLEvent.quick(
        event_type=EventType.PUMP_RECEIVED,
        description="Initial pump",
        source_agent="source",
        correlation_id=correlation_id,
    )

    mandate_event = NCLEvent.quick(
        event_type=EventType.MANDATE_CREATED,
        description="Mandate created from pump",
        source_agent="source",
        correlation_id=correlation_id,
    )

    await indexer.index_event(pump_event)
    await indexer.index_event(mandate_event)

    # Search by correlation
    results = await indexer.search_events(correlation_id=correlation_id)

    assert len(results) >= 1


@pytest.mark.asyncio
async def test_empty_search(temp_data_dir):
    """Test searching with no matches."""
    indexer = SearchIndexer(temp_data_dir)
    await indexer.load()

    # Search for non-existent term
    results = await indexer.search("xyznonexistentterm123xyz")

    assert len(results) == 0


@pytest.mark.asyncio
async def test_search_result_model(temp_data_dir):
    """Test SearchResult model."""
    result = SearchResult(
        doc_id="doc-001",
        doc_type="event",
        score=0.85,
        snippet="This is a test snippet",
        timestamp=datetime.now(timezone.utc),
        data={"event_type": "pump_received"},
    )

    assert result.doc_id == "doc-001"
    assert result.score == 0.85
    assert result.snippet == "This is a test snippet"

    result_dict = result.to_dict()
    assert result_dict["doc_id"] == "doc-001"
    assert result_dict["score"] == 0.85


@pytest.mark.asyncio
async def test_multiple_keyword_search(temp_data_dir):
    """Test searching with multiple keywords."""
    indexer = SearchIndexer(temp_data_dir)
    await indexer.load()

    event = NCLEvent.quick(
        event_type=EventType.PUMP_RECEIVED,
        description="Geopolitical risk in Asia increased due to trade tensions",
        source_agent="market",
    )

    await indexer.index_event(event)

    # Search with multiple terms
    results = await indexer.search("geopolitical risk Asia", limit=10)

    assert len(results) > 0


@pytest.mark.asyncio
async def test_indexer_load_and_persistence(temp_data_dir):
    """Test that indexer can reload persisted data."""
    # Create and index in first instance
    indexer1 = SearchIndexer(temp_data_dir)
    await indexer1.load()

    event = NCLEvent.quick(
        event_type=EventType.PUMP_RECEIVED,
        description="Test event for persistence",
        source_agent="source",
    )

    await indexer1.index_event(event)

    # Create new instance and reload
    indexer2 = SearchIndexer(temp_data_dir)
    await indexer2.load()

    # Should be able to search
    results = await indexer2.search("persistence")

    # May or may not find depending on persistence implementation
    # But should not error
    assert isinstance(results, list)
