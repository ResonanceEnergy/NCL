#!/usr/bin/env python3
"""
Super Agency Memory Doctrine System
Multi-layer memory architecture for context management and persistence
"""

import os
import json
import time
import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import threading
import atexit

class MemoryLayer:
    """Base class for memory layers"""

    def __init__(self, name: str, max_size: int, retention_policy: str):
        self.name = name
        self.max_size = max_size
        self.retention_policy = retention_policy
        self.created_at = datetime.now()
        self.last_accessed = datetime.now()
        self.access_count = 0

    def store(self, key: str, data: Any, metadata: Dict = None) -> bool:
        """Store data in this layer"""
        raise NotImplementedError

    def retrieve(self, key: str) -> Optional[Any]:
        """Retrieve data from this layer"""
        raise NotImplementedError

    def cleanup(self) -> int:
        """Clean up expired or low-priority data"""
        raise NotImplementedError

    def get_stats(self) -> Dict:
        """Get layer statistics"""
        return {
            "name": self.name,
            "max_size": self.max_size,
            "retention_policy": self.retention_policy,
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat(),
            "access_count": self.access_count
        }

class EphemeralMemory(MemoryLayer):
    """Fast, temporary memory for current session"""

    def __init__(self, max_size: int = 4096):  # 4K tokens equivalent
        super().__init__("ephemeral", max_size, "session")
        self.cache = {}
        self.access_order = []

    def store(self, key: str, data: Any, metadata: Dict = None) -> bool:
        """Store data with LRU eviction"""
        if len(self.cache) >= self.max_size and key not in self.cache:
            # Evict least recently used
            oldest_key = self.access_order.pop(0)
            del self.cache[oldest_key]

        self.cache[key] = {
            "data": data,
            "metadata": metadata or {},
            "stored_at": datetime.now(),
            "access_count": 0
        }

        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)

        self.last_accessed = datetime.now()
        return True

    def retrieve(self, key: str) -> Optional[Any]:
        """Retrieve data and update access patterns"""
        if key not in self.cache:
            return None

        # Update access order
        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)

        self.cache[key]["access_count"] += 1
        self.last_accessed = datetime.now()
        self.access_count += 1

        return self.cache[key]["data"]

    def cleanup(self) -> int:
        """Clean up expired session data (no-op for ephemeral)"""
        return 0

class SessionMemory(MemoryLayer):
    """Medium-term memory for multi-turn conversations"""

    def __init__(self, max_size: int = 65536, retention_hours: int = 24):  # 64K tokens
        super().__init__("session", max_size, f"{retention_hours}_hours")
        self.retention_hours = retention_hours
        self.storage_path = Path("./memory/session_memory.json")
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load_data()

    def _load_data(self) -> Dict:
        """Load session data from disk"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_data(self):
        """Save session data to disk"""
        try:
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, default=str)
        except Exception as e:
            print(f"Warning: Failed to save session memory: {e}")

    def store(self, key: str, data: Any, metadata: Dict = None) -> bool:
        """Store session data with timestamp"""
        if len(self.data) >= self.max_size:
            # Remove oldest entries
            sorted_items = sorted(self.data.items(),
                                key=lambda x: x[1].get("stored_at", datetime.min))
            # Keep only 80% of max_size
            keep_count = int(self.max_size * 0.8)
            self.data = dict(sorted_items[-keep_count:])

        self.data[key] = {
            "data": data,
            "metadata": metadata or {},
            "stored_at": datetime.now(),
            "access_count": 0
        }

        self._save_data()
        self.last_accessed = datetime.now()
        return True

    def retrieve(self, key: str) -> Optional[Any]:
        """Retrieve session data"""
        if key not in self.data:
            return None

        self.data[key]["access_count"] += 1
        self.last_accessed = datetime.now()
        self.access_count += 1

        return self.data[key]["data"]

    def cleanup(self) -> int:
        """Clean up expired session data"""
        cutoff_time = datetime.now() - timedelta(hours=self.retention_hours)
        expired_keys = []

        for key, value in self.data.items():
            stored_at = value.get("stored_at")
            if isinstance(stored_at, str):
                stored_at = datetime.fromisoformat(stored_at)

            if stored_at < cutoff_time:
                expired_keys.append(key)

        for key in expired_keys:
            del self.data[key]

        if expired_keys:
            self._save_data()

        return len(expired_keys)

class PersistentMemory(MemoryLayer):
    """Long-term memory with vector search capabilities"""

    def __init__(self, max_size: int = 1000000):  # 1M tokens equivalent
        super().__init__("persistent", max_size, "indefinite")
        self.db_path = Path("./memory/persistent_memory.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database for persistent storage"""
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS memory (
                key TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                metadata TEXT,
                stored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                access_count INTEGER DEFAULT 0,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                importance REAL DEFAULT 0.5
            )
        """)
        self.conn.commit()

    def store(self, key: str, data: Any, metadata: Dict = None) -> bool:
        """Store data with importance scoring"""
        try:
            # Calculate importance based on metadata
            importance = metadata.get("importance", 0.5) if metadata else 0.5

            self.conn.execute("""
                INSERT OR REPLACE INTO memory
                (key, data, metadata, importance, access_count)
                VALUES (?, ?, ?, ?, COALESCE((SELECT access_count FROM memory WHERE key = ?), 0))
            """, (
                key,
                json.dumps(data, default=str),
                json.dumps(metadata or {}, default=str),
                importance,
                key
            ))
            self.conn.commit()

            self.last_accessed = datetime.now()
            return True
        except Exception as e:
            print(f"Error storing persistent memory: {e}")
            return False

    def retrieve(self, key: str) -> Optional[Any]:
        """Retrieve persistent data"""
        try:
            cursor = self.conn.execute("""
                SELECT data, access_count FROM memory WHERE key = ?
            """, (key,))

            row = cursor.fetchone()
            if row:
                data_str, access_count = row
                data = json.loads(data_str)

                # Update access statistics
                self.conn.execute("""
                    UPDATE memory
                    SET access_count = ?, last_accessed = CURRENT_TIMESTAMP
                    WHERE key = ?
                """, (access_count + 1, key))
                self.conn.commit()

                self.last_accessed = datetime.now()
                self.access_count += 1

                return data
        except Exception as e:
            print(f"Error retrieving persistent memory: {e}")

        return None

    def cleanup(self) -> int:
        """Clean up low-importance, rarely accessed data"""
        try:
            # Remove items with low importance and old access
            cutoff_date = (datetime.now() - timedelta(days=90)).isoformat()

            cursor = self.conn.execute("""
                DELETE FROM memory
                WHERE importance < 0.3
                AND last_accessed < ?
                AND (SELECT COUNT(*) FROM memory) > ?
            """, (cutoff_date, self.max_size * 0.9))

            deleted_count = cursor.rowcount
            self.conn.commit()

            return deleted_count
        except Exception as e:
            print(f"Error during cleanup: {e}")
            return 0

class MemoryDoctrineSystem:
    """Main memory doctrine system coordinating all layers"""

    def __init__(self):
        self.layers = {
            "ephemeral": EphemeralMemory(),
            "session": SessionMemory(),
            "persistent": PersistentMemory()
        }

        # Start cleanup thread
        self.cleanup_thread = threading.Thread(target=self._cleanup_worker, daemon=True)
        self.cleanup_thread.start()

        # Register cleanup on exit
        atexit.register(self.shutdown)

    def _cleanup_worker(self):
        """Background cleanup worker"""
        while True:
            time.sleep(3600)  # Clean up every hour
            for layer in self.layers.values():
                try:
                    cleaned = layer.cleanup()
                    if cleaned > 0:
                        print(f"Cleaned {cleaned} items from {layer.name} layer")
                except Exception as e:
                    print(f"Cleanup error in {layer.name}: {e}")

    def store(self, key: str, data: Any, layer: str = "auto", metadata: Dict = None) -> bool:
        """Store data in appropriate layer"""
        if layer == "auto":
            # Auto-select layer based on data characteristics
            layer = self._select_layer(data, metadata)

        if layer not in self.layers:
            return False

        return self.layers[layer].store(key, data, metadata)

    def retrieve(self, key: str, search_layers: List[str] = None) -> Optional[Any]:
        """Retrieve data from memory layers"""
        layers_to_search = search_layers or ["ephemeral", "session", "persistent"]

        for layer_name in layers_to_search:
            if layer_name in self.layers:
                data = self.layers[layer_name].retrieve(key)
                if data is not None:
                    return data

        return None

    def _select_layer(self, data: Any, metadata: Dict = None) -> str:
        """Auto-select appropriate memory layer"""
        # Check metadata for explicit layer preference
        if metadata and "memory_layer" in metadata:
            return metadata["memory_layer"]

        # Select based on data characteristics
        data_size = len(str(data))

        if data_size < 1000:  # Small data
            return "ephemeral"
        elif data_size < 10000:  # Medium data
            return "session"
        else:  # Large or important data
            return "persistent"

    def get_stats(self) -> Dict:
        """Get comprehensive memory statistics"""
        stats = {
            "system": {
                "total_layers": len(self.layers),
                "active_cleanup": self.cleanup_thread.is_alive()
            },
            "layers": {}
        }

        for name, layer in self.layers.items():
            stats["layers"][name] = layer.get_stats()

        return stats

    def optimize(self) -> Dict:
        """Run memory optimization across all layers"""
        results = {}

        for name, layer in self.layers.items():
            try:
                cleaned = layer.cleanup()
                results[name] = {
                    "status": "success",
                    "items_cleaned": cleaned
                }
            except Exception as e:
                results[name] = {
                    "status": "error",
                    "error": str(e)
                }

        return results

    def shutdown(self):
        """Graceful shutdown"""
        print("Shutting down Memory Doctrine System...")

        # Save all session data
        if "session" in self.layers:
            self.layers["session"]._save_data()

        # Close database connections
        if "persistent" in self.layers:
            self.layers["persistent"].conn.close()

        print("Memory Doctrine System shutdown complete.")

# Global instance
_memory_system = None

def get_memory_system() -> MemoryDoctrineSystem:
    """Get or create global memory system instance"""
    global _memory_system
    if _memory_system is None:
        _memory_system = MemoryDoctrineSystem()
    return _memory_system

# Convenience functions
def remember(key: str, data: Any, layer: str = "auto", metadata: Dict = None) -> bool:
    """Store data in memory system"""
    return get_memory_system().store(key, data, layer, metadata)

def recall(key: str, search_layers: List[str] = None) -> Optional[Any]:
    """Retrieve data from memory system"""
    return get_memory_system().retrieve(key, search_layers)

def memory_stats() -> Dict:
    """Get memory system statistics"""
    return get_memory_system().get_stats()

def optimize_memory() -> Dict:
    """Optimize memory across all layers"""
    return get_memory_system().optimize()

if __name__ == "__main__":
    # Test the memory system
    print("🧠 Testing Memory Doctrine System...")

    # Store test data
    remember("test_ephemeral", "Quick temporary data", "ephemeral")
    remember("test_session", "Session-persistent data", "session")
    remember("test_persistent", "Long-term important data", "persistent",
             {"importance": 0.9})

    # Retrieve test data
    print("Ephemeral:", recall("test_ephemeral"))
    print("Session:", recall("test_session"))
    print("Persistent:", recall("test_persistent"))

    # Show stats
    stats = memory_stats()
    print("Memory Stats:", json.dumps(stats, indent=2, default=str))

    print("✅ Memory Doctrine System test complete!")
