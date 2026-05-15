"""
Shared Blackboard for the NCL Agent Swarm.

Provides a task-scoped key-value store with TTL expiration, pattern-based
subscriptions, and optional file persistence. Used for inter-agent communication,
checkpointing, and shared memory.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

SubscriptionCallback = Callable[[str, Any], Coroutine[Any, Any, None]]


class _Entry:
    """Internal storage entry with value and expiration."""

    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, ttl: int | None) -> None:
        self.value = value
        self.expires_at = (time.time() + ttl) if ttl else None

    def is_expired(self) -> bool:
        return self.expires_at is not None and time.time() > self.expires_at


class Blackboard:
    """
    Async shared-state store for the swarm.

    Features:
    - Task-scoped namespaces (keys are prefixed by task_id)
    - TTL-based auto-expiration
    - Pattern subscriptions (fnmatch globs)
    - Optional JSON file persistence
    - Hard cap of MAX_ENTRIES entries (oldest-first eviction when exceeded)
    """

    MAX_ENTRIES: int = 1000

    def __init__(
        self,
        persist_path: str | Path | None = None,
        max_entries: int | None = None,
    ) -> None:
        self._store: dict[str, _Entry] = {}
        self._subscriptions: list[tuple[str, SubscriptionCallback]] = []
        self._lock = asyncio.Lock()
        self._persist_path = Path(persist_path) if persist_path else None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._max_entries: int = max_entries if max_entries is not None else self.MAX_ENTRIES
        self._seq: int = 0  # Monotonic sequence counter for notifications (Gap 13)

        # Defer disk loading to async init() to avoid blocking the event
        # loop with synchronous file I/O (Gap 12).  The synchronous
        # _load_from_disk path is kept for backwards compatibility but
        # callers should prefer ``await blackboard.init()``.

    # ------------------------------------------------------------------
    # Async initialization
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Load persisted state from disk without blocking the event loop.

        Call this once after construction when an asyncio loop is running.
        Replaces the old synchronous ``_load_from_disk`` call in ``__init__``
        (Gap 12).
        """
        if self._persist_path and self._persist_path.exists():
            await asyncio.get_running_loop().run_in_executor(
                None, self._load_from_disk
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def put(self, key: str, value: Any, ttl: int | None = None) -> None:
        """
        Store a value under the given key.

        If the store has reached ``max_entries`` the oldest entry (by
        insertion order) is evicted before writing the new one. Keys that
        are being overwritten do not count as new entries.

        Args:
            key: The storage key (typically "namespace:subtopic:id").
            value: Any JSON-serializable value.
            ttl: Time-to-live in seconds. None means no expiration.
        """
        async with self._lock:
            is_new_key = key not in self._store
            if is_new_key and len(self._store) >= self._max_entries:
                # Evict the oldest entry (dict preserves insertion order in Python 3.7+)
                oldest_key = next(iter(self._store))
                del self._store[oldest_key]
                logger.warning(
                    "Blackboard max_entries=%d reached; evicted oldest key '%s'",
                    self._max_entries,
                    oldest_key,
                )
            self._store[key] = _Entry(value=value, ttl=ttl)

        # Fire subscriptions (outside lock)
        await self._notify_subscribers(key, value)

        # Persist if configured (_persist acquires its own lock for snapshot)
        if self._persist_path:
            await self._persist()

        logger.debug("Blackboard PUT: %s (ttl=%s)", key, ttl)

    async def get(self, key: str) -> Any | None:
        """
        Retrieve a value by key. Returns None if missing or expired.

        Args:
            key: The storage key to look up.

        Returns:
            The stored value, or None if not found or expired.
        """
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.is_expired():
                del self._store[key]
                return None
            return entry.value

    async def subscribe(self, pattern: str, callback: SubscriptionCallback) -> None:
        """
        Register a callback for keys matching a glob pattern.

        The callback is invoked asynchronously whenever a matching key is written.

        Args:
            pattern: fnmatch-style glob (e.g., "checkpoint:*", "result:task_abc:*").
            callback: Async function(key, value) called on matching writes.
        """
        async with self._lock:
            self._subscriptions.append((pattern, callback))
        logger.debug("Blackboard subscription added: %s", pattern)

    async def list_keys(self, prefix: str = "") -> list[str]:
        """
        List all non-expired keys matching the given prefix.

        Args:
            prefix: Key prefix to filter by. Empty string returns all keys.

        Returns:
            Sorted list of matching keys.
        """
        async with self._lock:
            now = time.time()
            keys = [
                k
                for k, entry in self._store.items()
                if k.startswith(prefix)
                and (entry.expires_at is None or now < entry.expires_at)
            ]
        return sorted(keys)

    async def delete(self, key: str) -> bool:
        """
        Remove a key from the store.

        Args:
            key: The key to delete.

        Returns:
            True if the key existed and was deleted.
        """
        deleted = False
        async with self._lock:
            if key in self._store:
                del self._store[key]
                deleted = True

        # Persist outside the lock to avoid deadlock — _persist acquires
        # the lock internally for its snapshot (Gap 11).
        if deleted and self._persist_path:
            await self._persist()

        return deleted

    async def clear_namespace(self, prefix: str) -> int:
        """
        Remove all keys with the given prefix.

        Args:
            prefix: Key prefix identifying the namespace to clear.

        Returns:
            Number of keys removed.
        """
        async with self._lock:
            to_remove = [k for k in self._store if k.startswith(prefix)]
            for k in to_remove:
                del self._store[k]

        if to_remove and self._persist_path:
            await self._persist()

        logger.debug("Blackboard cleared namespace '%s': %d keys removed", prefix, len(to_remove))
        return len(to_remove)

    async def start_cleanup_loop(self, interval: float = 60.0) -> None:
        """Start a background task that prunes expired entries periodically."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop(interval))

    async def stop(self) -> None:
        """Stop the cleanup loop and persist final state."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        if self._persist_path:
            await self._persist()

        logger.info("Blackboard stopped. %d entries in store.", len(self._store))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _notify_subscribers(self, key: str, value: Any) -> None:
        """Fire callbacks for subscriptions matching the key.

        Each notification carries a monotonically increasing sequence number
        so subscribers can detect and discard out-of-order deliveries (Gap 13).
        """
        # Atomically obtain the next sequence number
        async with self._lock:
            self._seq += 1
            seq = self._seq

        # Take a snapshot so that concurrent subscribe() calls cannot mutate
        # _subscriptions while we iterate over it (Gap 27).
        for pattern, callback in list(self._subscriptions):
            if fnmatch.fnmatch(key, pattern):
                try:
                    await callback(key, value, seq)
                except TypeError:
                    # Callback may not accept seq (backwards compat)
                    try:
                        await callback(key, value)
                    except Exception as exc:
                        logger.error(
                            "Subscription callback error for pattern '%s' on key '%s': %s",
                            pattern,
                            key,
                            exc,
                        )
                except Exception as exc:
                    logger.error(
                        "Subscription callback error for pattern '%s' on key '%s': %s",
                        pattern,
                        key,
                        exc,
                    )

    async def _cleanup_loop(self, interval: float) -> None:
        """Periodically remove expired entries."""
        while True:
            await asyncio.sleep(interval)
            removed = await self._prune_expired()
            if removed > 0:
                logger.debug("Blackboard cleanup: pruned %d expired entries", removed)

    async def _prune_expired(self) -> int:
        """Remove all expired entries. Returns count of removed."""
        async with self._lock:
            now = time.time()
            expired_keys = [
                k
                for k, entry in self._store.items()
                if entry.expires_at is not None and now > entry.expires_at
            ]
            for k in expired_keys:
                del self._store[k]

        if expired_keys and self._persist_path:
            await self._persist()

        return len(expired_keys)

    async def _persist(self) -> None:
        """Write current state to disk as JSON.

        Snapshots _store under the lock to avoid reading stale/inconsistent
        data (Gap 10), then performs blocking I/O outside the lock so callers
        like delete() don't deadlock (Gap 11).
        """
        if not self._persist_path:
            return

        # Snapshot under lock
        async with self._lock:
            serializable: dict[str, Any] = {}
            for key, entry in self._store.items():
                if not entry.is_expired():
                    serializable[key] = {
                        "value": entry.value,
                        "expires_at": entry.expires_at,
                    }

        self._persist_path.parent.mkdir(parents=True, exist_ok=True)

        # Write atomically via temp file (outside lock)
        tmp_path = self._persist_path.with_suffix(".tmp")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: tmp_path.write_text(json.dumps(serializable, default=str)),
        )
        await loop.run_in_executor(None, lambda: tmp_path.replace(self._persist_path))

    def _load_from_disk(self) -> None:
        """Load persisted state from disk at startup (synchronous, for use in __init__).

        NOTE: Called from __init__ which must be synchronous. For async callers,
        prefer calling ``await blackboard.load()`` after construction to avoid
        blocking the event loop with file I/O.
        """
        if not self._persist_path or not self._persist_path.exists():
            return

        try:
            data = json.loads(self._persist_path.read_text())
            now = time.time()
            for key, meta in data.items():
                expires_at = meta.get("expires_at")
                if expires_at and now > expires_at:
                    continue  # Skip already-expired entries
                entry = _Entry(value=meta["value"], ttl=None)
                entry.expires_at = expires_at
                self._store[key] = entry

            logger.info("Blackboard loaded %d entries from %s", len(self._store), self._persist_path)
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error("Failed to load blackboard from disk: %s", exc)

    async def load(self) -> None:
        """Async alternative to the __init__ disk load.

        Re-hydrates the store from disk off the event loop.  Call this after
        construction when an asyncio loop is already running so that the
        blocking file read does not stall the event loop.

        Usage::

            board = Blackboard(persist_path=path)
            await board.load()  # non-blocking re-hydrate
        """
        await asyncio.get_running_loop().run_in_executor(None, self._load_from_disk)
