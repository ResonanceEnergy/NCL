#!/usr/bin/env python3
"""
NCL Memory System - Core Memory Manager
Advanced memory management for cognitive augmentation with multi-tier storage,
semantic indexing, and learning capabilities.
"""

import json
import os
import time
import hashlib
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
import heapq
import pickle
import sqlite3
from collections import defaultdict, deque

class MemoryUnit:
    """Represents a single unit of memory with metadata"""

    def __init__(self, content: Any, memory_type: str = "episodic",
                 tags: List[str] = None, context: Dict = None):
        self.id = hashlib.sha256(f"{time.time()}_{content}_{memory_type}".encode()).hexdigest()[:16]
        self.content = content
        self.memory_type = memory_type  # episodic, semantic, procedural, working
        self.tags = tags or []
        self.context = context or {}
        self.timestamp = datetime.now()
        self.access_count = 0
        self.last_accessed = self.timestamp
        self.importance = 1.0  # 0.0 to 1.0
        self.consolidated = False
        self.source = "system"

    def to_dict(self) -> Dict:
        """Convert to dictionary for storage"""
        return {
            "id": self.id,
            "content": self.content,
            "memory_type": self.memory_type,
            "tags": self.tags,
            "context": self.context,
            "timestamp": self.timestamp.isoformat(),
            "access_count": self.access_count,
            "last_accessed": self.last_accessed.isoformat(),
            "importance": self.importance,
            "consolidated": self.consolidated,
            "source": self.source
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'MemoryUnit':
        """Create from dictionary"""
        unit = cls(
            content=data["content"],
            memory_type=data["memory_type"],
            tags=data["tags"],
            context=data["context"]
        )
        unit.id = data["id"]
        unit.timestamp = datetime.fromisoformat(data["timestamp"])
        unit.access_count = data["access_count"]
        unit.last_accessed = datetime.fromisoformat(data["last_accessed"])
        unit.importance = data["importance"]
        unit.consolidated = data["consolidated"]
        unit.source = data.get("source", "system")
        return unit

    def access(self):
        """Record memory access"""
        self.access_count += 1
        self.last_accessed = datetime.now()

    def calculate_importance(self) -> float:
        """Calculate memory importance based on recency, frequency, and type"""
        # Base importance by memory type
        type_weights = {
            "episodic": 1.0,
            "semantic": 1.5,
            "procedural": 2.0,
            "working": 0.5
        }

        base_weight = type_weights.get(self.memory_type, 1.0)

        # Recency factor (newer = more important)
        hours_old = (datetime.now() - self.timestamp).total_seconds() / 3600
        recency_factor = max(0.1, 1.0 / (1.0 + hours_old / 24))  # Half-life of 24 hours

        # Frequency factor (more accessed = more important)
        frequency_factor = min(2.0, 1.0 + (self.access_count * 0.1))

        # Context importance
        context_boost = 1.0
        if "importance" in self.context:
            context_boost = self.context["importance"]

        importance = base_weight * recency_factor * frequency_factor * context_boost
        self.importance = min(1.0, importance)
        return self.importance


class MemoryIndex:
    """Efficient indexing for memory retrieval"""

    def __init__(self):
        self.tag_index = defaultdict(set)  # tag -> memory_ids
        self.type_index = defaultdict(set)  # type -> memory_ids
        self.time_index = defaultdict(set)  # hour -> memory_ids
        self.content_index = defaultdict(set)  # keyword -> memory_ids
        self.context_index = defaultdict(lambda: defaultdict(set))  # key -> value -> memory_ids

    def add_memory(self, memory: MemoryUnit):
        """Add memory to all relevant indexes"""
        # Tag index
        for tag in memory.tags:
            self.tag_index[tag].add(memory.id)

        # Type index
        self.type_index[memory.memory_type].add(memory.id)

        # Time index (by hour)
        hour_key = memory.timestamp.strftime("%Y-%m-%d-%H")
        self.time_index[hour_key].add(memory.id)

        # Content index (simple keyword extraction)
        if isinstance(memory.content, str):
            keywords = set(memory.content.lower().split())
            for keyword in keywords:
                if len(keyword) > 3:  # Skip short words
                    self.content_index[keyword].add(memory.id)

        # Context index
        for key, value in memory.context.items():
            if isinstance(value, str):
                self.context_index[key][value].add(memory.id)

    def remove_memory(self, memory_id: str):
        """Remove memory from all indexes"""
        # This is expensive - we'd need to rebuild indexes periodically
        # For now, we'll rebuild on demand
        pass

    def search(self, query: Dict) -> set:
        """Search memories using query filters"""
        results = None

        # Tag filter
        if "tags" in query:
            tag_results = set()
            for tag in query["tags"]:
                tag_results.update(self.tag_index.get(tag, set()))
            results = tag_results if results is None else results.intersection(tag_results)

        # Type filter
        if "memory_type" in query:
            type_results = self.type_index.get(query["memory_type"], set())
            results = type_results if results is None else results.intersection(type_results)

        # Time range filter
        if "time_range" in query:
            start_time, end_time = query["time_range"]
            time_results = set()
            current = start_time
            while current <= end_time:
                hour_key = current.strftime("%Y-%m-%d-%H")
                time_results.update(self.time_index.get(hour_key, set()))
                current += timedelta(hours=1)
            results = time_results if results is None else results.intersection(time_results)

        # Content filter
        if "content" in query:
            content_results = set()
            keywords = query["content"].lower().split()
            for keyword in keywords:
                content_results.update(self.content_index.get(keyword, set()))
            results = content_results if results is None else results.intersection(content_results)

        # Context filter
        if "context" in query:
            context_results = set()
            for key, value in query["context"].items():
                context_results.update(self.context_index[key].get(value, set()))
            results = context_results if results is None else results.intersection(context_results)

        return results or set()


class MemoryStorage:
    """Multi-tier memory storage system"""

    def __init__(self, base_path: str = "~/NCL/memory"):
        self.base_path = Path(base_path).expanduser()
        self.base_path.mkdir(parents=True, exist_ok=True)

        # Storage tiers
        self.working_memory = {}  # RAM-based for active context
        self.short_term_db = self.base_path / "short_term.db"  # SQLite for recent memories
        self.long_term_db = self.base_path / "long_term.db"    # SQLite for consolidated memories

        # Initialize databases
        self._init_databases()

        # Working memory limits
        self.working_memory_limit = 1000
        self.working_memory_queue = deque(maxlen=self.working_memory_limit)

    def _init_databases(self):
        """Initialize SQLite databases"""
        for db_path in [self.short_term_db, self.long_term_db]:
            conn = sqlite3.connect(str(db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    memory_type TEXT,
                    importance REAL,
                    timestamp TEXT,
                    last_accessed TEXT,
                    access_count INTEGER
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_type ON memories(memory_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_importance ON memories(importance)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON memories(timestamp)")
            conn.commit()
            conn.close()

    def store_working_memory(self, memory: MemoryUnit):
        """Store in working memory (RAM)"""
        self.working_memory[memory.id] = memory
        self.working_memory_queue.append(memory.id)

        # Evict old memories if over limit
        while len(self.working_memory) > self.working_memory_limit:
            oldest_id = self.working_memory_queue.popleft()
            if oldest_id in self.working_memory:
                del self.working_memory[oldest_id]

    def store_short_term(self, memory: MemoryUnit):
        """Store in short-term database"""
        conn = sqlite3.connect(str(self.short_term_db))
        conn.execute("""
            INSERT OR REPLACE INTO memories
            (id, data, memory_type, importance, timestamp, last_accessed, access_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            memory.id,
            json.dumps(memory.to_dict()),
            memory.memory_type,
            memory.importance,
            memory.timestamp.isoformat(),
            memory.last_accessed.isoformat(),
            memory.access_count
        ))
        conn.commit()
        conn.close()

    def store_long_term(self, memory: MemoryUnit):
        """Store in long-term database"""
        memory.consolidated = True
        conn = sqlite3.connect(str(self.long_term_db))
        conn.execute("""
            INSERT OR REPLACE INTO memories
            (id, data, memory_type, importance, timestamp, last_accessed, access_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            memory.id,
            json.dumps(memory.to_dict()),
            memory.memory_type,
            memory.importance,
            memory.timestamp.isoformat(),
            memory.last_accessed.isoformat(),
            memory.access_count
        ))
        conn.commit()
        conn.close()

    def retrieve_working_memory(self, memory_id: str) -> Optional[MemoryUnit]:
        """Retrieve from working memory"""
        if memory_id in self.working_memory:
            memory = self.working_memory[memory_id]
            memory.access()
            return memory
        return None

    def retrieve_short_term(self, memory_id: str) -> Optional[MemoryUnit]:
        """Retrieve from short-term database"""
        conn = sqlite3.connect(str(self.short_term_db))
        cursor = conn.execute("SELECT data FROM memories WHERE id = ?", (memory_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            data = json.loads(row[0])
            memory = MemoryUnit.from_dict(data)
            memory.access()
            # Update access info
            self.store_short_term(memory)
            return memory
        return None

    def retrieve_long_term(self, memory_id: str) -> Optional[MemoryUnit]:
        """Retrieve from long-term database"""
        conn = sqlite3.connect(str(self.long_term_db))
        cursor = conn.execute("SELECT data FROM memories WHERE id = ?", (memory_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            data = json.loads(row[0])
            memory = MemoryUnit.from_dict(data)
            memory.access()
            # Update access info
            self.store_long_term(memory)
            return memory
        return None

    def search_short_term(self, query: Dict, limit: int = 50) -> List[MemoryUnit]:
        """Search short-term memories"""
        conn = sqlite3.connect(str(self.short_term_db))

        # Build WHERE clause
        conditions = []
        params = []

        if "memory_type" in query:
            conditions.append("memory_type = ?")
            params.append(query["memory_type"])

        if "min_importance" in query:
            conditions.append("importance >= ?")
            params.append(query["min_importance"])

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        cursor = conn.execute(f"""
            SELECT data FROM memories
            WHERE {where_clause}
            ORDER BY importance DESC, last_accessed DESC
            LIMIT ?
        """, params + [limit])

        results = []
        for row in cursor:
            data = json.loads(row[0])
            results.append(MemoryUnit.from_dict(data))

        conn.close()
        return results

    def consolidate_memories(self, threshold_days: int = 7, min_importance: float = 0.7):
        """Move important short-term memories to long-term storage"""
        cutoff_date = datetime.now() - timedelta(days=threshold_days)

        conn = sqlite3.connect(str(self.short_term_db))
        cursor = conn.execute("""
            SELECT data FROM memories
            WHERE importance >= ? AND timestamp < ?
        """, (min_importance, cutoff_date.isoformat()))

        consolidated_count = 0
        for row in cursor:
            data = json.loads(row[0])
            memory = MemoryUnit.from_dict(data)
            self.store_long_term(memory)

            # Remove from short-term
            conn.execute("DELETE FROM memories WHERE id = ?", (memory.id,))
            consolidated_count += 1

        conn.commit()
        conn.close()

        return consolidated_count

    def prune_memories(self, max_short_term: int = 10000, max_long_term: int = 50000):
        """Prune least important memories to maintain size limits"""
        # Prune short-term
        conn = sqlite3.connect(str(self.short_term_db))
        count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

        if count > max_short_term:
            to_delete = count - max_short_term
            conn.execute("""
                DELETE FROM memories
                WHERE id IN (
                    SELECT id FROM memories
                    ORDER BY importance ASC, last_accessed ASC
                    LIMIT ?
                )
            """, (to_delete,))
            conn.commit()

        conn.close()

        # Prune long-term
        conn = sqlite3.connect(str(self.long_term_db))
        count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

        if count > max_long_term:
            to_delete = count - max_long_term
            conn.execute("""
                DELETE FROM memories
                WHERE id IN (
                    SELECT id FROM memories
                    ORDER BY importance ASC, last_accessed ASC
                    LIMIT ?
                )
            """, (to_delete,))
            conn.commit()

        conn.close()


class MemoryManager:
    """Central coordinator for all memory operations"""

    def __init__(self, config_path: str = "ncl_config.json"):
        self.config = self.load_config(config_path)
        self.storage = MemoryStorage(self.config.get("memory", {}).get("storage_path", "~/NCL/memory"))
        self.index = MemoryIndex()

        # Memory processing queues
        self.consolidation_queue = deque()
        self.learning_queue = deque()

        # Background processing
        self.running = True
        self.consolidation_thread = threading.Thread(target=self._consolidation_worker, daemon=True)
        self.consolidation_thread.start()

        # Load existing memories into index
        self._rebuild_index()

    def load_config(self, config_path: str) -> Dict:
        """Load memory configuration"""
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {
                "memory": {
                    "storage_path": "~/NCL/memory",
                    "working_memory_limit": 1000,
                    "consolidation_threshold_days": 7,
                    "consolidation_min_importance": 0.7,
                    "pruning_max_short_term": 10000,
                    "pruning_max_long_term": 50000
                }
            }

    def _rebuild_index(self):
        """Rebuild memory index from storage"""
        # This is a simplified version - in production, we'd index incrementally
        pass

    def _consolidation_worker(self):
        """Background worker for memory consolidation"""
        while self.running:
            try:
                # Consolidate memories periodically
                if len(self.consolidation_queue) > 0:
                    memory_id = self.consolidation_queue.popleft()
                    # Consolidation logic would go here
                    pass

                time.sleep(300)  # Run every 5 minutes

            except Exception as e:
                print(f"Consolidation worker error: {e}")
                time.sleep(60)

    def store_memory(self, content: Any, memory_type: str = "episodic",
                    tags: List[str] = None, context: Dict = None,
                    source: str = "system") -> str:
        """Store a new memory"""
        memory = MemoryUnit(content, memory_type, tags, context)
        memory.source = source

        # Calculate initial importance
        memory.calculate_importance()

        # Store based on type and importance
        if memory_type == "working":
            self.storage.store_working_memory(memory)
        elif memory.importance >= 0.8:  # High importance goes to long-term
            self.storage.store_long_term(memory)
        else:
            self.storage.store_short_term(memory)

        # Add to index
        self.index.add_memory(memory)

        # Queue for potential consolidation
        if memory_type != "working":
            self.consolidation_queue.append(memory.id)

        return memory.id

    def retrieve_memory(self, memory_id: str) -> Optional[MemoryUnit]:
        """Retrieve a specific memory"""
        # Try working memory first
        memory = self.storage.retrieve_working_memory(memory_id)
        if memory:
            return memory

        # Try short-term
        memory = self.storage.retrieve_short_term(memory_id)
        if memory:
            return memory

        # Try long-term
        memory = self.storage.retrieve_long_term(memory_id)
        return memory

    def search_memories(self, query: Dict, limit: int = 50) -> List[MemoryUnit]:
        """Search memories using flexible query"""
        # Use index for fast filtering
        candidate_ids = self.index.search(query)

        memories = []
        if candidate_ids:
            # Retrieve actual memories for candidates
            for memory_id in list(candidate_ids)[:limit * 2]:  # Get more candidates
                memory = self.retrieve_memory(memory_id)
                if memory:
                    memories.append(memory)
        else:
            # Fallback to database search - check both short-term and long-term
            memories.extend(self.storage.search_short_term(query, limit//2))

            # Also search long-term memories
            long_term_query = query.copy()
            if "min_importance" not in long_term_query:
                long_term_query["min_importance"] = 0.0  # Include all long-term memories

            # For long-term, we need to implement a similar search
            # For now, get recent long-term memories
            long_term_memories = self._search_long_term(long_term_query, limit//2)
            memories.extend(long_term_memories)

        # Sort by relevance (importance + recency)
        memories.sort(key=lambda m: (m.importance, m.last_accessed), reverse=True)
        return memories[:limit]

    def _search_long_term(self, query: Dict, limit: int) -> List[MemoryUnit]:
        """Search long-term memories (simplified implementation)"""
        conn = sqlite3.connect(str(self.storage.long_term_db))

        # Build WHERE clause
        conditions = []
        params = []

        if "memory_type" in query:
            conditions.append("memory_type = ?")
            params.append(query["memory_type"])

        if "min_importance" in query:
            conditions.append("importance >= ?")
            params.append(query["min_importance"])

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        cursor = conn.execute(f"""
            SELECT data FROM memories
            WHERE {where_clause}
            ORDER BY importance DESC, last_accessed DESC
            LIMIT ?
        """, params + [limit])

        results = []
        for row in cursor:
            data = json.loads(row[0])
            results.append(MemoryUnit.from_dict(data))

        conn.close()
        return results

    def consolidate_memories(self) -> int:
        """Manually trigger memory consolidation"""
        config = self.config.get("memory", {})
        threshold_days = config.get("consolidation_threshold_days", 7)
        min_importance = config.get("consolidation_min_importance", 0.7)

        return self.storage.consolidate_memories(threshold_days, min_importance)

    def prune_memories(self) -> None:
        """Manually trigger memory pruning"""
        config = self.config.get("memory", {})
        max_short = config.get("pruning_max_short_term", 10000)
        max_long = config.get("pruning_max_long_term", 50000)

        self.storage.prune_memories(max_short, max_long)

    def get_memory_stats(self) -> Dict:
        """Get memory system statistics"""
        # This would query the databases for counts
        return {
            "working_memory_count": len(self.storage.working_memory),
            "short_term_count": self._get_db_count(self.storage.short_term_db),
            "long_term_count": self._get_db_count(self.storage.long_term_db),
            "consolidation_queue_size": len(self.consolidation_queue)
        }

    def _get_db_count(self, db_path: Path) -> int:
        """Get memory count from database"""
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute("SELECT COUNT(*) FROM memories")
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except:
            return 0

    def shutdown(self):
        """Graceful shutdown"""
        self.running = False
        if self.consolidation_thread.is_alive():
            self.consolidation_thread.join(timeout=5)


# Global memory manager instance
_memory_manager = None

def get_memory_manager() -> MemoryManager:
    """Get or create global memory manager instance"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager

def store_episodic_memory(content: Any, tags: List[str] = None, context: Dict = None) -> str:
    """Convenience function for storing episodic memories"""
    return get_memory_manager().store_memory(content, "episodic", tags, context)

def store_semantic_memory(content: Any, tags: List[str] = None, context: Dict = None) -> str:
    """Convenience function for storing semantic memories"""
    return get_memory_manager().store_memory(content, "semantic", tags, context)

def store_working_memory(content: Any, tags: List[str] = None, context: Dict = None) -> str:
    """Convenience function for storing working memories"""
    return get_memory_manager().store_memory(content, "working", tags, context)

def recall_memory(memory_id: str) -> Optional[MemoryUnit]:
    """Convenience function for retrieving memories"""
    return get_memory_manager().retrieve_memory(memory_id)

def search_memories(query: Dict, limit: int = 50) -> List[MemoryUnit]:
    """Convenience function for searching memories"""
    return get_memory_manager().search_memories(query, limit)

if __name__ == "__main__":
    # Example usage
    mm = get_memory_manager()

    # Store some example memories
    mem1_id = store_episodic_memory(
        "User completed daily focus session",
        tags=["productivity", "focus"],
        context={"duration": 25, "quality": "high"}
    )

    mem2_id = store_semantic_memory(
        "Deep work blocks of 90-120 minutes are optimal for complex tasks",
        tags=["productivity", "research"],
        context={"source": "scientific_study", "confidence": 0.85}
    )

    # Search memories
    results = search_memories({"tags": ["productivity"]})
    print(f"Found {len(results)} productivity-related memories")

    # Get stats
    stats = mm.get_memory_stats()
    print(f"Memory stats: {stats}")

    mm.shutdown()