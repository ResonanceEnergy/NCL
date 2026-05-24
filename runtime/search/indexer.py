"""
NCL On-Device Indexer & Search Engine v1.

Provides full-text search across events, memory units, mandates,
and council sessions — all on-device with zero external dependencies.

Architecture:
    - Inverted index for full-text search (tokenised keywords)
    - Secondary indices for structured queries (event type, correlation_id, etc.)
    - NDJSON-backed persistence with lazy loading
    - In-memory index rebuilt on startup, incrementally updated on writes

Usage:
    indexer = SearchIndexer(data_dir="~/dev/NCL/data")
    await indexer.load()
    await indexer.index_event(ncl_event)
    results = await indexer.search("geopolitical risk Asia", limit=20)
    results = await indexer.search_events(event_type="council_completed", days_back=7)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _json_safe(obj: Any) -> Any:
    """JSON serialization fallback for sets, datetimes, Path, etc."""
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, (Path,)):
        return str(obj)
    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            pass
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    return str(obj)


import aiofiles  # noqa: E402

from ..ncl_brain.models import MemUnit, NCLEvent  # noqa: E402


log = logging.getLogger("ncl.search")

# Index size limits
MAX_INDEX_DOCS = 100_000  # Max number of documents in the in-memory index
MAX_DOC_TEXT_CHARS = 10_000  # Max characters of text stored per document

# Common stop words to exclude from indexing
STOP_WORDS = frozenset(
    "a an and are as at be by for from has have he in is it its of on or "
    "that the this to was were will with".split()
)


def tokenize(text: str) -> list[str]:
    """Split text into searchable tokens, lowercased, stop words removed."""
    words = re.findall(r"[a-zA-Z0-9_-]{2,}", text.lower())
    return [w for w in words if w not in STOP_WORDS]


class SearchResult:
    """Single search result with relevance score."""

    __slots__ = ("doc_id", "doc_type", "score", "snippet", "timestamp", "data")

    def __init__(
        self,
        doc_id: str,
        doc_type: str,
        score: float,
        snippet: str,
        timestamp: datetime,
        data: dict[str, Any],
    ):
        self.doc_id = doc_id
        self.doc_type = doc_type
        self.score = score
        self.snippet = snippet
        self.timestamp = timestamp
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "doc_type": self.doc_type,
            "score": round(self.score, 4),
            "snippet": self.snippet,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
        }


class SearchIndexer:
    """
    On-device full-text + structured search engine for NCL data.

    Index structure:
        _inverted: token → set[doc_id]  (full-text)
        _by_type:  event_type → set[doc_id]
        _by_correlation: correlation_id → set[doc_id]
        _by_pump:  pump_id → set[doc_id]
        _by_mandate: mandate_id → set[doc_id]
        _docs:     doc_id → {type, text, timestamp, data}
    """

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.index_dir = self.data_dir / "search"
        self.index_dir.mkdir(parents=True, exist_ok=True)

        # In-memory indices
        self._inverted: dict[str, set[str]] = defaultdict(set)
        self._by_type: dict[str, set[str]] = defaultdict(set)
        self._by_correlation: dict[str, set[str]] = defaultdict(set)
        self._by_pump: dict[str, set[str]] = defaultdict(set)
        self._by_mandate: dict[str, set[str]] = defaultdict(set)
        self._docs: dict[str, dict[str, Any]] = {}

        # Document frequency for TF-IDF scoring
        self._doc_count = 0
        self._df: dict[str, int] = defaultdict(int)  # token → num docs containing it

        self._loaded = False
        self._load_lock = asyncio.Lock()  # Prevents double-initialization under concurrency
        self._cache_file = self.index_dir / "index_cache.json"

    async def load(self) -> None:
        """Load index from cache if available, otherwise rebuild from source files.

        The check-and-load pattern is wrapped in _load_lock so that concurrent
        callers (e.g., simultaneous search requests on startup) cannot both see
        _loaded=False and trigger two full index rebuilds in parallel.
        """
        # Fast path: already loaded (no lock needed — bool read is atomic in CPython)
        if self._loaded:
            return

        async with self._load_lock:
            # Re-check inside the lock: a concurrent caller may have finished loading
            # while we were waiting to acquire it.
            if self._loaded:
                return

            # Try loading from serialized cache first (fast path)
            if await self._load_cache():
                self._loaded = True
                return

            # Cache miss — rebuild from source NDJSON files (still inside the lock
            # so only one coroutine performs the rebuild)
            events_file = self.data_dir / "events.ndjson"
            memory_file = self.data_dir / "memory" / "units.jsonl"
            mandates_file = self.data_dir / "mandates.json"

            indexed = 0

            # Index events
            if events_file.exists():
                async with aiofiles.open(events_file, "r") as f:
                    async for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            raw = json.loads(line)
                            self._index_event_dict(raw)
                            indexed += 1
                        except (json.JSONDecodeError, KeyError):
                            continue

            # Index memory units
            if memory_file.exists():
                async with aiofiles.open(memory_file, "r") as f:
                    async for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            raw = json.loads(line)
                            self._index_memory_dict(raw)
                            indexed += 1
                        except (json.JSONDecodeError, KeyError):
                            continue

            # Index mandates
            if mandates_file.exists():
                try:
                    async with aiofiles.open(mandates_file, "r") as f:
                        content = await f.read()
                    mandates = json.loads(content)
                    if isinstance(mandates, list):
                        for m in mandates:
                            self._index_mandate_dict(m)
                            indexed += 1
                    elif isinstance(mandates, dict):
                        for m in mandates.values():
                            self._index_mandate_dict(m)
                            indexed += 1
                except (json.JSONDecodeError, KeyError):
                    pass

            self._loaded = True
            log.info(
                f"Search index rebuilt: {indexed} documents, {len(self._inverted)} unique tokens"
            )

        # Save cache for next startup
        await self._save_cache()

    async def _save_cache(self) -> None:
        """Serialize index to disk for fast reload."""
        try:
            cache = {
                "inverted": {k: list(v) for k, v in self._inverted.items()},
                "by_type": {k: list(v) for k, v in self._by_type.items()},
                "by_correlation": {k: list(v) for k, v in self._by_correlation.items()},
                "by_pump": {k: list(v) for k, v in self._by_pump.items()},
                "by_mandate": {k: list(v) for k, v in self._by_mandate.items()},
                "docs": self._docs,
                "doc_count": self._doc_count,
                "df": dict(self._df),
            }
            async with aiofiles.open(self._cache_file, "w") as f:
                await f.write(json.dumps(cache, default=_json_safe))
            log.info(
                f"Search index cache saved: {self._doc_count} docs, {len(self._inverted)} tokens"
            )
        except Exception as e:
            log.warning(f"Failed to save search index cache: {e}")

    async def _load_cache(self) -> bool:
        """Load index from cache file. Returns True if cache was valid."""
        if not self._cache_file.exists():
            return False
        try:
            async with aiofiles.open(self._cache_file, "r") as f:
                content = await f.read()
            cache = json.loads(content)
            self._inverted = defaultdict(
                set, {k: set(v) for k, v in cache.get("inverted", {}).items()}
            )
            self._by_type = defaultdict(
                set, {k: set(v) for k, v in cache.get("by_type", {}).items()}
            )
            self._by_correlation = defaultdict(
                set, {k: set(v) for k, v in cache.get("by_correlation", {}).items()}
            )
            self._by_pump = defaultdict(
                set, {k: set(v) for k, v in cache.get("by_pump", {}).items()}
            )
            self._by_mandate = defaultdict(
                set, {k: set(v) for k, v in cache.get("by_mandate", {}).items()}
            )
            self._docs = cache.get("docs", {})
            self._doc_count = cache.get("doc_count", 0)
            self._df = defaultdict(int, cache.get("df", {}))
            log.info(
                f"Search index loaded from cache: {self._doc_count} docs, {len(self._inverted)} tokens"  # noqa: E501
            )
            return True
        except Exception as e:
            log.warning(f"Failed to load search index cache: {e}")
            return False

    def _add_doc(
        self,
        doc_id: str,
        doc_type: str,
        text: str,
        timestamp: datetime,
        data: dict[str, Any],
    ) -> None:
        """Add a document to all indices, enforcing size limits."""
        # Skip if already indexed (idempotent re-index)
        if doc_id in self._docs:
            return

        # Enforce index size cap: evict no-op (log and skip) to keep memory bounded
        if len(self._docs) >= MAX_INDEX_DOCS:
            log.warning(
                "Search index at capacity (%d docs). Skipping doc_id=%s type=%s. "
                "Consider running a reindex after pruning old data.",
                MAX_INDEX_DOCS,
                doc_id,
                doc_type,
            )
            return

        # Truncate text to keep memory footprint bounded
        truncated_text = text[:MAX_DOC_TEXT_CHARS] if len(text) > MAX_DOC_TEXT_CHARS else text

        self._docs[doc_id] = {
            "type": doc_type,
            "text": truncated_text,
            "timestamp": timestamp,
            "data": data,
        }
        self._doc_count += 1

        tokens = set(tokenize(truncated_text))
        for token in tokens:
            self._inverted[token].add(doc_id)
            self._df[token] += 1

    def _index_event_dict(self, raw: dict) -> None:
        """Index a raw event dict (supports both v1 schema and legacy)."""
        event_id = raw.get("event_id", "")
        if not event_id:
            return

        event_type = raw.get("type", "custom")
        description = raw.get("description", "")
        ts_str = raw.get("timestamp", "")

        try:
            ts = (
                datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts_str
                else datetime.now(timezone.utc)
            )
        except (ValueError, AttributeError):
            ts = datetime.now(timezone.utc)

        # Build searchable text from description + payload/metadata
        payload = raw.get("payload", raw.get("metadata", {}))
        text_parts = [description, event_type]
        if isinstance(payload, dict):
            for v in payload.values():
                if isinstance(v, str):
                    text_parts.append(v)
        text = " ".join(text_parts)

        self._add_doc(event_id, "event", text, ts, raw)
        self._by_type[event_type].add(event_id)

        # Provenance indices (v1 schema)
        prov = raw.get("provenance", {})
        if isinstance(prov, dict):
            if cid := prov.get("correlation_id"):
                self._by_correlation[cid].add(event_id)
            if pid := prov.get("pump_id"):
                self._by_pump[pid].add(event_id)
            if mid := prov.get("mandate_id"):
                self._by_mandate[mid].add(event_id)

        # Legacy metadata indices
        if isinstance(payload, dict):
            if cid := payload.get("correlation_id"):
                self._by_correlation[cid].add(event_id)
            if pid := payload.get("pump_id"):
                self._by_pump[pid].add(event_id)
            if mid := payload.get("mandate_id"):
                self._by_mandate[mid].add(event_id)

    def _index_memory_dict(self, raw: dict) -> None:
        """Index a raw memory unit dict."""
        unit_id = raw.get("unit_id", "")
        if not unit_id:
            return

        content = raw.get("content", "")
        source = raw.get("source", "")
        tags = raw.get("tags", [])
        ts_str = raw.get("created_at", "")

        try:
            ts = (
                datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts_str
                else datetime.now(timezone.utc)
            )
        except (ValueError, AttributeError):
            ts = datetime.now(timezone.utc)

        text = " ".join([content, source] + (tags if isinstance(tags, list) else []))
        self._add_doc(f"mem-{unit_id}", "memory", text, ts, raw)

    def _index_mandate_dict(self, raw: dict) -> None:
        """Index a raw mandate dict."""
        mid = raw.get("mandate_id", "")
        if not mid:
            return

        title = raw.get("title", "")
        objective = raw.get("objective", "")
        criteria = raw.get("success_criteria", [])
        ts_str = raw.get("created_at", "")

        try:
            ts = (
                datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts_str
                else datetime.now(timezone.utc)
            )
        except (ValueError, AttributeError):
            ts = datetime.now(timezone.utc)

        text = " ".join([title, objective] + (criteria if isinstance(criteria, list) else []))
        self._add_doc(f"mandate-{mid}", "mandate", text, ts, raw)
        self._by_mandate[mid].add(f"mandate-{mid}")

    async def index_event(self, event: NCLEvent) -> None:
        """Index a new NCLEvent (call after persisting to NDJSON)."""
        try:
            raw = json.loads(event.to_ndjson())
            self._index_event_dict(raw)
        except Exception as e:
            log.warning(
                "index_event failed for event_id=%s: %s", getattr(event, "event_id", "?"), e
            )

    async def index_memory(self, unit: MemUnit) -> None:
        """Index a new MemUnit."""
        try:
            raw = json.loads(unit.model_dump_json())
            self._index_memory_dict(raw)
        except Exception as e:
            log.warning("index_memory failed for unit_id=%s: %s", getattr(unit, "unit_id", "?"), e)

    async def search(
        self,
        query: str,
        limit: int = 20,
        doc_types: list[str] | None = None,
        days_back: int | None = None,
    ) -> list[SearchResult]:
        """
        Full-text search across all indexed documents using TF-IDF scoring.

        Args:
            query: Free-text search query
            limit: Maximum results to return
            doc_types: Filter by doc type (event, memory, mandate)
            days_back: Only include documents from the past N days

        Returns:
            List of SearchResult sorted by relevance score descending
        """
        if not self._loaded:
            try:
                await self.load()
            except Exception as e:
                log.error("search: index load failed: %s", e)
                return []

        if self._doc_count == 0:
            return []

        tokens = tokenize(query)
        if not tokens:
            return []

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)) if days_back else None

        # Collect candidate doc_ids (union of all token matches)
        candidates: dict[str, float] = defaultdict(float)
        for token in tokens:
            if token not in self._inverted:
                continue
            idf = math.log(self._doc_count / (1 + self._df.get(token, 0)))
            for doc_id in self._inverted[token]:
                doc = self._docs[doc_id]
                # TF: count of this token in document text
                doc_tokens = tokenize(doc["text"])
                tf = doc_tokens.count(token) / max(len(doc_tokens), 1)
                candidates[doc_id] += tf * idf

        results: list[SearchResult] = []
        for doc_id, score in candidates.items():
            doc = self._docs[doc_id]
            if doc_types and doc["type"] not in doc_types:
                continue
            if cutoff and doc["timestamp"] < cutoff:
                continue

            snippet = doc["text"][:200]
            results.append(
                SearchResult(
                    doc_id=doc_id,
                    doc_type=doc["type"],
                    score=score,
                    snippet=snippet,
                    timestamp=doc["timestamp"],
                    data=doc["data"],
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    async def search_events(
        self,
        event_type: str | None = None,
        correlation_id: str | None = None,
        pump_id: str | None = None,
        mandate_id: str | None = None,
        days_back: int | None = None,
        limit: int = 50,
    ) -> list[SearchResult]:
        """
        Structured search across events using secondary indices.

        All filters are AND-combined. At least one filter must be provided.
        """
        if not self._loaded:
            await self.load()

        candidates: set[str] | None = None

        def intersect(new: set[str]) -> set[str]:
            nonlocal candidates
            candidates = new if candidates is None else candidates & new
            return candidates

        if event_type:
            intersect(self._by_type.get(event_type, set()))
        if correlation_id:
            intersect(self._by_correlation.get(correlation_id, set()))
        if pump_id:
            intersect(self._by_pump.get(pump_id, set()))
        if mandate_id:
            intersect(self._by_mandate.get(mandate_id, set()))

        if candidates is None:
            candidates = set(self._docs.keys())

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)) if days_back else None

        results: list[SearchResult] = []
        for doc_id in candidates:
            doc = self._docs.get(doc_id)
            if not doc or doc["type"] != "event":
                continue
            if cutoff and doc["timestamp"] < cutoff:
                continue
            results.append(
                SearchResult(
                    doc_id=doc_id,
                    doc_type="event",
                    score=1.0,
                    snippet=doc["text"][:200],
                    timestamp=doc["timestamp"],
                    data=doc["data"],
                )
            )

        results.sort(key=lambda r: r.timestamp, reverse=True)
        return results[:limit]

    async def get_chain(self, correlation_id: str) -> list[SearchResult]:
        """Retrieve all events in a causality chain, ordered chronologically."""
        results = await self.search_events(correlation_id=correlation_id, limit=500)
        results.sort(key=lambda r: r.timestamp)
        return results

    def get_stats(self) -> dict[str, Any]:
        """Return index statistics."""
        type_counts = defaultdict(int)
        for doc in self._docs.values():
            type_counts[doc["type"]] += 1

        return {
            "total_documents": self._doc_count,
            "unique_tokens": len(self._inverted),
            "documents_by_type": dict(type_counts),
            "event_types_indexed": len(self._by_type),
            "correlation_chains": len(self._by_correlation),
            "pumps_tracked": len(self._by_pump),
            "mandates_tracked": len(self._by_mandate),
        }
