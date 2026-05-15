"""
Council Vector Store — Semantic Search via ChromaDB or LanceDB.

Indexes all council outputs (insights, reports, transcripts) into a vector
database for RAG retrieval. The council agents can query this to recall
related intelligence across sessions.

Fallback chain:
    1. ChromaDB (local, embeddings via sentence-transformers or Ollama)
    2. LanceDB (lightweight, DuckDB-backed, no server needed)
    3. In-memory TF-IDF (zero-dependency fallback — always works)

Usage:
    store = CouncilVectorStore(data_dir="~/dev/NCL/data")
    await store.init()
    await store.index_insight(insight, session_id, source="youtube")
    results = await store.query("geopolitical risk Asia supply chain", top_k=10)
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ncl.councils.vector_store")

# Stop words for TF-IDF fallback
_STOP = frozenset(
    "a an and are as at be by for from has have he in is it its of on or "
    "that the this to was were will with do did does".split()
)


@dataclass
class VectorDocument:
    """A document indexed in the vector store."""
    doc_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] = field(default_factory=list)


@dataclass
class VectorResult:
    """A search result from the vector store."""
    doc_id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class CouncilVectorStore:
    """
    Multi-backend vector store for council knowledge.

    Initializes with the best available backend and exposes a unified
    index/query interface.
    """

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.vector_dir = self.data_dir / "vector_store"
        self.vector_dir.mkdir(parents=True, exist_ok=True)
        self._backend: str = "none"
        self._chroma_collection = None
        self._lance_table = None
        # In-memory TF-IDF fallback
        self._docs: dict[str, VectorDocument] = {}
        self._inverted: dict[str, set[str]] = defaultdict(set)
        self._df: dict[str, int] = defaultdict(int)
        self._doc_count: int = 0
        self._initialized = False

    async def init(self) -> str:
        """Initialize the best available backend. Returns backend name."""
        if self._initialized:
            return self._backend

        # Try ChromaDB
        if self._try_chromadb():
            self._backend = "chromadb"
            log.info("Vector store initialized: ChromaDB")
            self._initialized = True
            return self._backend

        # Try LanceDB
        if self._try_lancedb():
            self._backend = "lancedb"
            log.info("Vector store initialized: LanceDB")
            self._initialized = True
            return self._backend

        # Fallback: in-memory TF-IDF
        self._backend = "tfidf"
        await self._load_tfidf_from_disk()
        log.info(f"Vector store initialized: TF-IDF fallback ({self._doc_count} docs)")
        self._initialized = True
        return self._backend

    def _try_chromadb(self) -> bool:
        """Attempt to initialize ChromaDB."""
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(self.vector_dir / "chroma"))
            self._chroma_collection = client.get_or_create_collection(
                name="council_knowledge",
                metadata={"hnsw:space": "cosine"},
            )
            log.info(f"ChromaDB: {self._chroma_collection.count()} existing documents")
            return True
        except ImportError:
            log.debug("chromadb not installed")
            return False
        except Exception as e:
            log.warning(f"ChromaDB init failed: {e}")
            return False

    def _try_lancedb(self) -> bool:
        """Attempt to initialize LanceDB."""
        try:
            import lancedb
            db = lancedb.connect(str(self.vector_dir / "lance"))
            try:
                self._lance_table = db.open_table("council_knowledge")
            except Exception:
                # Table doesn't exist yet — will create on first insert
                self._lance_table = None
                self._lance_db = db
            return True
        except ImportError:
            log.debug("lancedb not installed")
            return False
        except Exception as e:
            log.warning(f"LanceDB init failed: {e}")
            return False

    async def _load_tfidf_from_disk(self) -> None:
        """Load persisted TF-IDF documents from JSONL backup."""
        backup = self.vector_dir / "tfidf_docs.jsonl"
        if not backup.exists():
            return
        try:
            with open(backup, "r") as f:
                for line in f:
                    if not line.strip():
                        continue
                    raw = json.loads(line)
                    self._add_tfidf_doc(
                        doc_id=raw["doc_id"],
                        text=raw["text"],
                        metadata=raw.get("metadata", {}),
                    )
        except Exception as e:
            log.warning(f"Failed to load TF-IDF backup: {e}")

    def _add_tfidf_doc(self, doc_id: str, text: str, metadata: dict) -> None:
        """Add document to in-memory TF-IDF index."""
        self._docs[doc_id] = VectorDocument(doc_id=doc_id, text=text, metadata=metadata)
        self._doc_count += 1
        tokens = set(_tokenize(text))
        for token in tokens:
            self._inverted[token].add(doc_id)
            self._df[token] += 1

    async def _persist_tfidf_doc(self, doc_id: str, text: str, metadata: dict) -> None:
        """Append document to JSONL backup."""
        backup = self.vector_dir / "tfidf_docs.jsonl"
        with open(backup, "a") as f:
            f.write(json.dumps({"doc_id": doc_id, "text": text, "metadata": metadata}) + "\n")

    # ── Public API ─────────────────────────────────────────────────────

    async def index_document(
        self,
        doc_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Index a document into the vector store."""
        if not self._initialized:
            await self.init()

        meta = metadata or {}

        if self._backend == "chromadb" and self._chroma_collection:
            self._chroma_collection.upsert(
                ids=[doc_id],
                documents=[text],
                metadatas=[meta],
            )
        elif self._backend == "lancedb":
            await self._lance_upsert(doc_id, text, meta)
        else:
            self._add_tfidf_doc(doc_id, text, meta)
            await self._persist_tfidf_doc(doc_id, text, meta)

    async def index_insight(
        self,
        insight_title: str,
        insight_description: str,
        session_id: str,
        source: str,
        category: str = "",
        tags: list[str] | None = None,
        confidence: float = 0.5,
    ) -> None:
        """Index a council insight for retrieval."""
        doc_id = f"insight-{source}-{session_id}-{insight_title[:30].replace(' ', '_')}"
        text = f"{insight_title}. {insight_description}"
        if tags:
            text += " " + " ".join(tags)

        await self.index_document(doc_id, text, metadata={
            "type": "insight",
            "source": source,
            "session_id": session_id,
            "category": category,
            "confidence": confidence,
            "tags": tags or [],
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        })

    async def index_transcript_chunk(
        self,
        video_id: str,
        chunk_text: str,
        chunk_index: int,
        video_title: str = "",
        channel: str = "",
    ) -> None:
        """Index a transcript chunk for RAG retrieval."""
        doc_id = f"transcript-{video_id}-{chunk_index:04d}"
        text = f"{video_title}. {chunk_text}" if video_title else chunk_text

        await self.index_document(doc_id, text, metadata={
            "type": "transcript",
            "video_id": video_id,
            "video_title": video_title,
            "channel": channel,
            "chunk_index": chunk_index,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        })

    async def index_report_summary(
        self,
        session_id: str,
        source: str,
        summary: str,
        insight_count: int = 0,
    ) -> None:
        """Index a full council report summary."""
        doc_id = f"report-{source}-{session_id}"
        await self.index_document(doc_id, summary, metadata={
            "type": "report_summary",
            "source": source,
            "session_id": session_id,
            "insight_count": insight_count,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        })

    async def query(
        self,
        query_text: str,
        top_k: int = 10,
        filter_type: str | None = None,
        filter_source: str | None = None,
    ) -> list[VectorResult]:
        """
        Semantic search across all indexed council knowledge.

        Args:
            query_text: Natural language query
            top_k: Max results to return
            filter_type: Filter by doc type (insight, transcript, report_summary)
            filter_source: Filter by source (youtube, x)
        """
        if not self._initialized:
            await self.init()

        if self._backend == "chromadb" and self._chroma_collection:
            return self._query_chromadb(query_text, top_k, filter_type, filter_source)
        elif self._backend == "lancedb":
            return await self._query_lancedb(query_text, top_k, filter_type, filter_source)
        else:
            return self._query_tfidf(query_text, top_k, filter_type, filter_source)

    # ── ChromaDB backend ───────────────────────────────────────────────

    def _query_chromadb(
        self, query: str, top_k: int,
        filter_type: str | None, filter_source: str | None,
    ) -> list[VectorResult]:
        """Query ChromaDB with optional filters."""
        where = {}
        if filter_type:
            where["type"] = filter_type
        if filter_source:
            where["source"] = filter_source

        kwargs: dict[str, Any] = {
            "query_texts": [query],
            "n_results": top_k,
        }
        if where:
            kwargs["where"] = where

        results = self._chroma_collection.query(**kwargs)

        out: list[VectorResult] = []
        for i in range(len(results["ids"][0])):
            distance = results["distances"][0][i] if results.get("distances") else 0
            score = 1.0 - distance  # cosine distance → similarity
            out.append(VectorResult(
                doc_id=results["ids"][0][i],
                text=results["documents"][0][i] if results.get("documents") else "",
                score=score,
                metadata=results["metadatas"][0][i] if results.get("metadatas") else {},
            ))
        return out

    # ── LanceDB backend ────────────────────────────────────────────────

    async def _lance_upsert(self, doc_id: str, text: str, meta: dict) -> None:
        """Upsert into LanceDB (create table if needed)."""
        try:
            import lancedb
            data = [{"doc_id": doc_id, "text": text, **meta}]
            if self._lance_table is None:
                self._lance_table = self._lance_db.create_table(
                    "council_knowledge", data=data, mode="overwrite"
                )
            else:
                self._lance_table.add(data)
        except Exception as e:
            log.warning(f"LanceDB upsert failed: {e}")
            # Fallback to TF-IDF for this doc
            self._add_tfidf_doc(doc_id, text, meta)

    async def _query_lancedb(
        self, query: str, top_k: int,
        filter_type: str | None, filter_source: str | None,
    ) -> list[VectorResult]:
        """Query LanceDB."""
        if self._lance_table is None:
            return []
        try:
            results = self._lance_table.search(query).limit(top_k).to_list()
            out = []
            for row in results:
                out.append(VectorResult(
                    doc_id=row.get("doc_id", ""),
                    text=row.get("text", ""),
                    score=1.0 - row.get("_distance", 0),
                    metadata={k: v for k, v in row.items() if k not in ("doc_id", "text", "_distance")},
                ))
            return out
        except Exception as e:
            log.warning(f"LanceDB query failed: {e}")
            return self._query_tfidf(query, top_k, filter_type, filter_source)

    # ── TF-IDF fallback ────────────────────────────────────────────────

    def _query_tfidf(
        self, query: str, top_k: int,
        filter_type: str | None, filter_source: str | None,
    ) -> list[VectorResult]:
        """TF-IDF scoring as zero-dependency fallback."""
        tokens = _tokenize(query)
        if not tokens:
            return []

        scores: dict[str, float] = defaultdict(float)
        for token in tokens:
            if token not in self._inverted:
                continue
            idf = math.log(self._doc_count / (1 + self._df.get(token, 0)))
            for doc_id in self._inverted[token]:
                doc = self._docs[doc_id]
                doc_tokens = _tokenize(doc.text)
                tf = doc_tokens.count(token) / max(len(doc_tokens), 1)
                scores[doc_id] += tf * idf

        results: list[VectorResult] = []
        for doc_id, score in sorted(scores.items(), key=lambda x: -x[1])[:top_k * 3]:
            doc = self._docs[doc_id]
            if filter_type and doc.metadata.get("type") != filter_type:
                continue
            if filter_source and doc.metadata.get("source") != filter_source:
                continue
            results.append(VectorResult(
                doc_id=doc_id,
                text=doc.text[:300],
                score=score,
                metadata=doc.metadata,
            ))
            if len(results) >= top_k:
                break
        return results

    def get_stats(self) -> dict[str, Any]:
        """Return vector store statistics."""
        stats = {"backend": self._backend}
        if self._backend == "chromadb" and self._chroma_collection:
            stats["documents"] = self._chroma_collection.count()
        elif self._backend == "tfidf":
            stats["documents"] = self._doc_count
            stats["unique_tokens"] = len(self._inverted)
        return stats


def _tokenize(text: str) -> list[str]:
    """Split text into tokens for TF-IDF."""
    words = re.findall(r"[a-zA-Z0-9_-]{2,}", text.lower())
    return [w for w in words if w not in _STOP]
