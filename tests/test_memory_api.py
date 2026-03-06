#!/usr/bin/env python3
"""Tests for ncl_agency_runtime/runtime/memory_api.py — pure-logic helpers."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import ncl_agency_runtime.runtime.memory_api as memory_api_mod  # noqa: E402
from ncl_agency_runtime.runtime.memory_api import MemoryAPI  # noqa: E402


@pytest.fixture
def api():
    return MemoryAPI()


# ── _calculate_event_importance ────────────────────────────


class TestCalculateEventImportance:

    def test_base_importance(self, api):
        score = api._calculate_event_importance({})
        assert score == 0.5

    def test_high_importance_event_types(self, api):
        for etype in ["focus_session", "decision_point", "milestone_reached", "error_log", "alert_fired"]:
            score = api._calculate_event_importance({"event_type": etype})
            assert score >= 0.8, f"{etype} should be high importance"

    def test_data_richness_bonus(self, api):
        rich = {"data": {"a": 1, "b": 2, "c": 3, "d": 4}}
        lean = {"data": {"a": 1}}
        assert api._calculate_event_importance(rich) > api._calculate_event_importance(lean)

    def test_combined_boosts_capped_at_1(self, api):
        event = {"event_type": "focus_alert", "data": {"a": 1, "b": 2, "c": 3, "d": 4}}
        assert api._calculate_event_importance(event) <= 1.0

    def test_floor_at_0_1(self, api):
        assert api._calculate_event_importance({}) >= 0.1


# ── _calculate_chat_importance ─────────────────────────────


class TestCalculateChatImportance:

    def test_base_importance(self, api):
        assert api._calculate_chat_importance({}) == pytest.approx(0.3)  # 0.5 base - 0.1 (short msgs) - 0.1 (short dur)

    def test_long_conversation_boost(self, api):
        chat = {"messages": list(range(25))}
        assert api._calculate_chat_importance(chat) > 0.5

    def test_long_duration_boost(self, api):
        assert api._calculate_chat_importance({"duration": 90}) > api._calculate_chat_importance({"duration": 2})

    def test_group_chat_boost(self, api):
        group = {"participants": ["a", "b", "c", "d"]}
        solo = {"participants": ["a"]}
        assert api._calculate_chat_importance(group) > api._calculate_chat_importance(solo)

    def test_action_items_boost(self, api):
        assert api._calculate_chat_importance({"has_action_items": True}) > api._calculate_chat_importance({})

    def test_decisions_boost(self, api):
        assert api._calculate_chat_importance({"has_decisions": True}) > api._calculate_chat_importance({})

    def test_capped_at_1(self, api):
        chat = {
            "messages": list(range(30)),
            "duration": 120,
            "participants": ["a", "b", "c", "d"],
            "has_action_items": True,
            "has_decisions": True,
        }
        assert api._calculate_chat_importance(chat) <= 1.0

    def test_floor_at_0_1(self, api):
        assert api._calculate_chat_importance({}) >= 0.1


# ── _summarize_conversation ────────────────────────────────


class TestSummarizeConversation:

    def test_empty_messages(self, api):
        assert api._summarize_conversation([]) == "Empty conversation"

    def test_single_participant(self, api):
        msgs = [{"participant": "Alice", "content": "hi"}]
        s = api._summarize_conversation(msgs)
        assert "1 participants" in s
        assert "Alice: 1 messages" in s

    def test_multiple_participants(self, api):
        msgs = [
            {"participant": "Alice", "content": "hi"},
            {"participant": "Bob", "content": "hey"},
            {"participant": "Alice", "content": "how are you?"},
        ]
        s = api._summarize_conversation(msgs)
        assert "2 participants" in s
        assert "Alice: 2 messages" in s
        assert "Bob: 1 messages" in s


# ── _extract_topics ────────────────────────────────────────


class TestExtractTopics:

    def test_empty_messages(self, api):
        assert api._extract_topics([]) == []

    def test_filters_short_words(self, api):
        msgs = [{"content": "the cat sat on a mat"}]
        # No word appears more than once, and some are short
        topics = api._extract_topics(msgs)
        assert all(len(t) > 4 for t in topics)

    def test_returns_repeated_words(self, api):
        msgs = [
            {"content": "python programming is great"},
            {"content": "python development and programming tools"},
        ]
        topics = api._extract_topics(msgs)
        assert "python" in topics
        assert "programming" in topics

    def test_limits_to_5_topics(self, api):
        # Create messages with many repeated long words
        msgs = [{"content": " ".join(f"topic{i}" * 3 for i in range(10))}]
        topics = api._extract_topics(msgs)
        assert len(topics) <= 5


# ── disabled-memory convenience functions ──────────────────


class TestDisabledMemoryGuards:

    @pytest.fixture(autouse=True)
    def _disable_memory(self):
        with patch.object(memory_api_mod, "MEMORY_ENABLED", False):
            self.api = MemoryAPI()
            yield

    def test_store_event_returns_none(self):
        assert self.api.store_event_memory({"event_type": "test"}) is None

    def test_store_task_returns_none(self):
        assert self.api.store_task_memory({}, {}) is None

    def test_store_learning_returns_none(self):
        assert self.api.store_learning("concept", "knowledge") is None

    def test_recall_event_returns_empty(self):
        assert self.api.recall_event_pattern("test") == []

    def test_find_similar_tasks_returns_empty(self):
        assert self.api.find_similar_tasks("test") == []

    def test_get_memory_stats_disabled(self):
        assert self.api.get_memory_stats() == {"enabled": False}

    def test_consolidate_returns_zero(self):
        assert self.api.consolidate_memories() == 0

    def test_prune_noop(self):
        self.api.prune_memories()  # Just shouldn't raise

    def test_store_chat_memory_disabled(self):
        assert self.api.store_chat_memory({"messages": []}) is None

    def test_store_chat_insight_disabled(self):
        assert self.api.store_chat_insight("conv1", "insight") is None

    def test_recall_chat_history_disabled(self):
        assert self.api.recall_chat_history() == []

    def test_search_chat_content_disabled(self):
        assert self.api.search_chat_content("query") == []

    def test_search_knowledge_disabled(self):
        assert self.api.search_knowledge("query") == []

    def test_get_recent_learnings_disabled(self):
        assert self.api.get_recent_learnings() == []

    def test_store_working_context_disabled(self):
        assert self.api.store_working_context("ctx", {}) is None
