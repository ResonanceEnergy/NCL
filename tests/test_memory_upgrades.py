"""
Integration tests for NCL memory system upgrades.

Tests: Two-speed decay, typed collections, importance scoring,
entity extraction, knowledge graph, reflection loop.

Run: cd ~/dev/NCL && python -m pytest tests/test_memory_upgrades.py -v
"""

import asyncio
import json
import os
import tempfile
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test data."""
    d = tempfile.mkdtemp(prefix="ncl_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


class TestMemUnitModel:
    """Test MemUnit backward compatibility with new fields."""

    def test_default_fields(self):
        from runtime.ncl_brain.models import MemUnit
        unit = MemUnit(unit_id="test-1", content="test", source="test")
        assert unit.memory_type == "episodic"
        assert unit.memory_tier == "SML"
        assert unit.llm_importance_score is None
        assert unit.entities == []
        assert unit.relationships == []
        assert unit.consolidated_from == []
        assert unit.reflection_quality is None

    def test_backward_compat_json(self):
        """Old JSONL without new fields should parse fine."""
        from runtime.ncl_brain.models import MemUnit
        old_json = {
            "unit_id": "old-1",
            "content": "old memory",
            "source": "test",
            "importance": 50.0,
            "decay_rate": 0.95,
            "tags": ["test"],
            "reinforcement_count": 0,
            "related_units": [],
        }
        unit = MemUnit(**old_json)
        assert unit.memory_type == "episodic"
        assert unit.memory_tier == "SML"


class TestTwoSpeedDecay:
    """Test FadeMem two-speed decay pattern."""

    def test_lml_decays_slower(self):
        from runtime.ncl_brain.models import MemUnit
        from runtime.memory.store import MemoryStore

        store = MemoryStore.__new__(MemoryStore)  # Skip __init__

        lml_unit = MemUnit(
            unit_id="lml-1", content="fact", source="test",
            importance=80.0, memory_tier="LML",
            last_accessed=datetime.now(timezone.utc) - timedelta(days=7),
        )
        sml_unit = MemUnit(
            unit_id="sml-1", content="signal", source="test",
            importance=80.0, memory_tier="SML",
            last_accessed=datetime.now(timezone.utc) - timedelta(days=7),
        )

        lml_decayed = store._apply_decay(lml_unit)
        sml_decayed = store._apply_decay(sml_unit)

        # LML should retain more importance than SML after same time
        assert lml_decayed > sml_decayed, f"LML ({lml_decayed}) should be > SML ({sml_decayed})"
        # LML should still be high, SML should be significantly lower
        assert lml_decayed > 50.0, "LML should retain most importance after 7 days"


class TestImportanceScorer:
    """Test rule-based importance scoring."""

    def test_explicit_remember_high(self):
        from runtime.memory.importance_scorer import rule_based_score
        score = rule_based_score("Remember that we decided to use PostgreSQL")
        assert score >= 9.0

    def test_decision_high(self):
        from runtime.memory.importance_scorer import rule_based_score
        score = rule_based_score("We decided to migrate to AWS")
        assert score >= 8.0

    def test_casual_low(self):
        from runtime.memory.importance_scorer import rule_based_score
        score = rule_based_score("Random chatter about nothing important")
        assert score <= 4.0

    def test_council_source_moderate(self):
        from runtime.memory.importance_scorer import rule_based_score
        score = rule_based_score("Analysis complete", source="council:youtube")
        assert score >= 6.0


class TestEntityExtraction:
    """Test fast entity extraction."""

    def test_extract_tickers(self):
        from runtime.memory.entity_extractor import fast_extract_entities
        entities = fast_extract_entities("AAPL stock rose 5% while TSLA shares dropped")
        assert "$AAPL" in entities or "AAPL" in entities

    def test_extract_names(self):
        from runtime.memory.entity_extractor import fast_extract_entities
        entities = fast_extract_entities("Elon Musk announced that Tim Cook will join the board")
        assert any("Elon Musk" in e for e in entities)
        assert any("Tim Cook" in e for e in entities)

    def test_extract_relationships(self):
        from runtime.memory.entity_extractor import fast_extract_relationships
        rels = fast_extract_relationships("Apple acquired Beats for $3 billion")
        assert len(rels) > 0
        assert rels[0]["predicate"] == "ACQUIRED"

    def test_extract_urls(self):
        from runtime.memory.entity_extractor import fast_extract_entities
        entities = fast_extract_entities("Check out https://www.reddit.com/r/stocks for details")
        assert any("reddit.com" in e for e in entities)


class TestKnowledgeGraph:
    """Test in-memory knowledge graph."""

    @pytest.fixture
    def kg(self, temp_dir):
        from runtime.memory.knowledge_graph import KnowledgeGraph
        return KnowledgeGraph(data_dir=temp_dir)

    @pytest.mark.asyncio
    async def test_add_entities(self, kg):
        added = await kg.add_entities(["Apple", "Google", "Microsoft"], source_unit_id="test-1")
        assert added == 3
        stats = await kg.stats()
        assert stats["nodes"] == 3

    @pytest.mark.asyncio
    async def test_add_relationships(self, kg):
        rels = [{"subject": "Apple", "predicate": "ACQUIRED", "object": "Beats"}]
        added = await kg.add_relationships(rels, source_unit_id="test-1")
        assert added == 1
        stats = await kg.stats()
        assert stats["edges"] == 1

    @pytest.mark.asyncio
    async def test_query_entity(self, kg):
        await kg.add_entities(["Apple", "Beats"])
        await kg.add_relationships([
            {"subject": "Apple", "predicate": "ACQUIRED", "object": "Beats"}
        ])
        result = await kg.query_entity("Apple")
        assert result["found"] is True
        assert len(result["outgoing"]) == 1
        assert result["outgoing"][0]["target"] == "Beats"

    @pytest.mark.asyncio
    async def test_find_path(self, kg):
        await kg.add_relationships([
            {"subject": "A", "predicate": "KNOWS", "object": "B"},
            {"subject": "B", "predicate": "KNOWS", "object": "C"},
        ])
        path = await kg.find_path("A", "C")
        assert path == ["A", "B", "C"]

    @pytest.mark.asyncio
    async def test_persistence(self, temp_dir):
        from runtime.memory.knowledge_graph import KnowledgeGraph
        kg1 = KnowledgeGraph(data_dir=temp_dir)
        await kg1.add_entities(["Persisted"])

        # Create new instance (simulates restart)
        kg2 = KnowledgeGraph(data_dir=temp_dir)
        result = await kg2.query_entity("Persisted")
        assert result["found"] is True


class TestReflection:
    """Test reflection loop."""

    def test_quality_scoring(self):
        from runtime.ncl_brain.models import MemUnit
        from runtime.memory.reflection import MemoryReflector

        reflector = MemoryReflector()

        good_unit = MemUnit(
            unit_id="good-1",
            content="[reddit] Apple announced new MacBook Pro with M5 chip, significant performance gains expected",
            source="awarebot:reddit",
            tags=["apple", "macbook", "m5"],
            reinforcement_count=3,
        )

        bad_unit = MemUnit(
            unit_id="bad-1",
            content="hi",
            source="unknown",
            tags=[],
            reinforcement_count=0,
        )

        good_score = reflector._score_quality(good_unit)
        bad_score = reflector._score_quality(bad_unit)

        assert good_score > bad_score
        assert good_score >= 0.6
        assert bad_score <= 0.3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
