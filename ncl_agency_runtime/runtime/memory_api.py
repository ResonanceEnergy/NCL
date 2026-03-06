#!/usr/bin/env python3
"""
NCL Memory API - High-level memory operations for cognitive augmentation
"""

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

try:
    from ncl_memory import (
        MemoryUnit,
        get_memory_manager,
        search_memories,
        store_episodic_memory,
        store_semantic_memory,
        store_working_memory,
    )
    MEMORY_ENABLED = True
except ImportError:
    print("Warning: Memory system not available")
    MEMORY_ENABLED = False


class MemoryAPI:
    """High-level API for memory operations in NCL"""

    def __init__(self):
        self.memory_manager = get_memory_manager() if MEMORY_ENABLED else None

    def store_event_memory(self, event: dict) -> str | None:
        """Store an event as episodic memory"""
        if not MEMORY_ENABLED:
            return None

        tags = [f"event:{event.get('event_type', 'unknown')}"]
        if "category" in event:
            tags.append(f"category:{event['category']}")

        context = {
            "event_type": event.get("event_type"),
            "occurred_at": event.get("occurred_at"),
            "source": "event_ingestion",
            "importance": self._calculate_event_importance(event)
        }

        return store_episodic_memory(event, tags, context)

    def store_task_memory(self, task: dict, result: Any) -> str | None:
        """Store task execution as procedural memory"""
        if not MEMORY_ENABLED:
            return None

        content = {
            "task": task,
            "result": result,
            "execution_time": datetime.now().isoformat()
        }

        tags = ["task", "execution", f"task:{task.get('type', 'unknown')}"]
        context = {
            "task_type": task.get("type"),
            "success": result.get("success", False),
            "duration": result.get("duration"),
            "source": "task_execution"
        }

        return store_episodic_memory(content, tags, context)

    def store_learning(self, concept: str, knowledge: Any, confidence: float = 0.8) -> str | None:
        """Store learned knowledge as semantic memory"""
        if not MEMORY_ENABLED:
            return None

        content = {
            "concept": concept,
            "knowledge": knowledge,
            "learned_at": datetime.now().isoformat()
        }

        tags = ["learning", "semantic", f"concept:{concept}"]
        context = {
            "confidence": confidence,
            "source": "learning_system",
            "concept": concept
        }

        return store_semantic_memory(content, tags, context)

    def store_working_context(self, context_type: str, data: Any) -> str | None:
        """Store temporary working context"""
        if not MEMORY_ENABLED:
            return None

        tags = ["working", f"context:{context_type}"]
        context = {
            "context_type": context_type,
            "source": "working_memory",
            "temporary": True
        }

        return store_working_memory(data, tags, context)

    def recall_event_pattern(self, event_type: str, days_back: int = 7) -> list[dict]:
        """Recall similar events from recent history"""
        if not MEMORY_ENABLED:
            return []

        query = {
            "tags": [f"event:{event_type}"],
            "time_range": (datetime.now() - timedelta(days=days_back), datetime.now())
        }

        memories = search_memories(query, limit=20)
        return [self._memory_to_dict(mem) for mem in memories]

    def find_similar_tasks(self, task_type: str) -> list[dict]:
        """Find similar task executions"""
        if not MEMORY_ENABLED:
            return []

        query = {
            "tags": [f"task:{task_type}"]
        }

        memories = search_memories(query, limit=10)
        return [self._memory_to_dict(mem) for mem in memories]

    def get_recent_learnings(self, limit: int = 10) -> list[dict]:
        """Get recently learned knowledge"""
        if not MEMORY_ENABLED:
            return []

        query = {
            "memory_type": "semantic"
        }

        memories = search_memories(query, limit=limit)
        return [self._memory_to_dict(mem) for mem in memories]

    def search_knowledge(self, query_text: str, limit: int = 20) -> list[dict]:
        """Search semantic knowledge"""
        if not MEMORY_ENABLED:
            return []

        query = {
            "content": query_text,
            "memory_type": "semantic"
        }

        memories = search_memories(query, limit=limit)
        return [self._memory_to_dict(mem) for mem in memories]

    def get_memory_stats(self) -> dict:
        """Get memory system statistics"""
        if not MEMORY_ENABLED:
            return {"enabled": False}

        assert self.memory_manager is not None
        stats = self.memory_manager.get_memory_stats()
        stats["enabled"] = True
        return stats

    def consolidate_memories(self) -> int:
        """Trigger memory consolidation"""
        if not MEMORY_ENABLED:
            return 0

        assert self.memory_manager is not None
        return self.memory_manager.consolidate_memories()

    def prune_memories(self) -> None:
        """Trigger memory pruning"""
        if MEMORY_ENABLED:
            assert self.memory_manager is not None
            self.memory_manager.prune_memories()

    def store_chat_memory(self, chat_data: dict) -> str | None:
        """Store a chat conversation as episodic memory"""
        if not MEMORY_ENABLED:
            return None

        # Extract conversation metadata
        conversation_id = chat_data.get("conversation_id", f"chat_{int(time.time())}")
        participants = chat_data.get("participants", [])
        messages = chat_data.get("messages", [])

        # Create comprehensive memory content
        content = {
            "conversation_id": conversation_id,
            "participants": participants,
            "message_count": len(messages),
            "duration": chat_data.get("duration"),
            "summary": chat_data.get("summary", self._summarize_conversation(messages)),
            "key_topics": chat_data.get("topics", self._extract_topics(messages)),
            "messages": messages  # Store full conversation for detailed recall
        }

        # Generate tags
        tags = ["chat", f"conversation:{conversation_id}"]
        for participant in participants:
            tags.append(f"participant:{participant}")

        # Add topic tags
        topics = content.get("key_topics", [])
        for topic in topics[:3]:  # Limit to top 3 topics
            tags.append(f"topic:{topic}")

        # Calculate importance based on conversation characteristics
        context = {
            "conversation_type": chat_data.get("type", "general"),
            "message_count": len(messages),
            "participants_count": len(participants),
            "duration_minutes": chat_data.get("duration", 0),
            "source": "chat_system",
            "importance": self._calculate_chat_importance(chat_data)
        }

        return store_episodic_memory(content, tags, context)

    def store_chat_insight(self, conversation_id: str, insight: str, confidence: float = 0.8) -> str | None:
        """Store a learned insight from chat analysis"""
        if not MEMORY_ENABLED:
            return None

        content = {
            "conversation_id": conversation_id,
            "insight": insight,
            "learned_at": datetime.now().isoformat(),
            "confidence": confidence
        }

        tags = ["chat_insight", "learning", f"conversation:{conversation_id}"]
        context = {
            "source": "chat_analysis",
            "confidence": confidence,
            "conversation_id": conversation_id
        }

        return store_semantic_memory(content, tags, context)

    def recall_chat_history(self, participant: str | None = None, topic: str | None = None, limit: int = 10) -> list[dict]:
        """Recall relevant chat conversations"""
        if not MEMORY_ENABLED:
            return []

        query = {"tags": ["chat"]}

        if participant:
            query["tags"].append(f"participant:{participant}")
        if topic:
            query["tags"].append(f"topic:{topic}")

        memories = search_memories(query, limit=limit)
        return [self._memory_to_dict(mem) for mem in memories]

    def search_chat_content(self, query_text: str, limit: int = 20) -> list[dict]:
        """Search through chat content"""
        if not MEMORY_ENABLED:
            return []

        # Search for chats containing the query
        query = {
            "tags": ["chat"],
            "content": query_text
        }

        memories = search_memories(query, limit=limit)
        return [self._memory_to_dict(mem) for mem in memories]

    def _summarize_conversation(self, messages: list[dict]) -> str:
        """Generate a simple summary of the conversation"""
        if not messages:
            return "Empty conversation"

        # Simple summarization - count messages by participant
        participant_counts: dict[str, int] = {}
        for msg in messages:
            participant = msg.get("participant", "unknown")
            participant_counts[participant] = participant_counts.get(participant, 0) + 1

        summary_parts = []
        for participant, count in participant_counts.items():
            summary_parts.append(f"{participant}: {count} messages")

        return f"Conversation with {len(participant_counts)} participants - " + ", ".join(summary_parts)

    def _extract_topics(self, messages: list[dict]) -> list[str]:
        """Extract key topics from conversation (simple keyword-based)"""
        all_text = " ".join([msg.get("content", "") for msg in messages])
        words = all_text.lower().split()

        # Simple topic extraction - most common meaningful words
        common_words = ["the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "an", "a"]
        filtered_words = [word for word in words if len(word) > 4 and word not in common_words]

        from collections import Counter
        word_counts = Counter(filtered_words)
        return [word for word, count in word_counts.most_common(5) if count > 1]

    def _calculate_event_importance(self, event: dict) -> float:
        """Calculate importance score for an event"""
        importance = 0.5  # Base importance

        event_type = event.get("event_type", "")
        # Higher importance for certain event types
        high_importance_types = ["focus", "decision", "milestone", "error", "alert"]
        if any(t in event_type.lower() for t in high_importance_types):
            importance += 0.3

        # Data richness adds importance
        data = event.get("data", {})
        if isinstance(data, dict) and len(data) > 3:
            importance += 0.1

        return min(1.0, max(0.1, importance))

    def _calculate_chat_importance(self, chat_data: dict) -> float:
        """Calculate importance score for a chat conversation"""
        importance = 0.5  # Base importance

        # Length factors
        message_count = len(chat_data.get("messages", []))
        if message_count > 20:
            importance += 0.2
        elif message_count < 5:
            importance -= 0.1

        # Duration factors
        duration = chat_data.get("duration", 0)
        if duration > 60:  # Long conversations
            importance += 0.2
        elif duration < 5:  # Very short
            importance -= 0.1

        # Participant factors
        participants = chat_data.get("participants", [])
        if len(participants) > 3:  # Group conversations
            importance += 0.1

        # Content factors
        if chat_data.get("has_action_items"):
            importance += 0.3
        if chat_data.get("has_decisions"):
            importance += 0.3

        return min(1.0, max(0.1, importance))

    def _memory_to_dict(self, memory: MemoryUnit) -> dict:
        """Convert memory unit to dictionary"""
        return {
            "id": memory.id,
            "content": memory.content,
            "type": memory.memory_type,
            "tags": memory.tags,
            "context": memory.context,
            "importance": memory.importance,
            "timestamp": memory.timestamp.isoformat(),
            "last_accessed": memory.last_accessed.isoformat(),
            "access_count": memory.access_count,
            "consolidated": memory.consolidated,
            "source": memory.source
        }


# Global API instance
_memory_api = None

def get_memory_api() -> MemoryAPI:
    """Get or create global memory API instance"""
    global _memory_api
    if _memory_api is None:
        _memory_api = MemoryAPI()
    return _memory_api

def store_event(event: dict) -> str | None:
    """Convenience function for storing events"""
    return get_memory_api().store_event_memory(event)

def store_task_execution(task: dict, result: Any) -> str | None:
    """Convenience function for storing task executions"""
    return get_memory_api().store_task_memory(task, result)

def learn_knowledge(concept: str, knowledge: Any, confidence: float = 0.8) -> str | None:
    """Convenience function for storing learned knowledge"""
    return get_memory_api().store_learning(concept, knowledge, confidence)

def recall_similar_events(event_type: str, days_back: int = 7) -> list[dict]:
    """Convenience function for recalling similar events"""
    return get_memory_api().recall_event_pattern(event_type, days_back)

def find_similar_tasks(task_type: str) -> list[dict]:
    """Convenience function for finding similar tasks"""
    return get_memory_api().find_similar_tasks(task_type)

def store_chat_conversation(chat_data: dict) -> str | None:
    """Convenience function for storing chat conversations"""
    return get_memory_api().store_chat_memory(chat_data)

def learn_from_chat(conversation_id: str, insight: str, confidence: float = 0.8) -> str | None:
    """Convenience function for storing chat insights"""
    return get_memory_api().store_chat_insight(conversation_id, insight, confidence)

def recall_chat_history(participant: str | None = None, topic: str | None = None, limit: int = 10) -> list[dict]:
    """Convenience function for recalling chat conversations"""
    return get_memory_api().recall_chat_history(participant, topic, limit)

def search_chat_content(query: str, limit: int = 20) -> list[dict]:
    """Convenience function for searching chat content"""
    return get_memory_api().search_chat_content(query, limit)


if __name__ == "__main__":
    # Example usage
    api = get_memory_api()

    # Store a sample event
    event = {
        "event_type": "focus_session",
        "occurred_at": "2024-01-15T10:00:00Z",
        "data": {"duration": 25, "quality": "high"}
    }
    mem_id = api.store_event_memory(event)
    print(f"Stored event memory: {mem_id}")

    # Store learned knowledge
    learn_id = api.store_learning(
        "focus_technique",
        "Pomodoro technique with 25-minute focused work blocks",
        confidence=0.9
    )
    print(f"Stored learning: {learn_id}")

    # Search knowledge
    results = api.search_knowledge("focus")
    print(f"Found {len(results)} knowledge items about focus")

    # Get stats
    stats = api.get_memory_stats()
    print(f"Memory stats: {stats}")
