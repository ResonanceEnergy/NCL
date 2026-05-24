"""
Loop 11 — Multi-signal Retrieval Fusion
========================================

Reciprocal Rank Fusion (RRF) over three retrieval signals:
  - Vector similarity (ChromaDB cosine)
  - BM25 keyword scoring
  - Entity overlap (NetworkX knowledge graph)

Mem0's 2026 benchmark shows fusing these three signals yields +29.6 on
temporal queries and +23.1 on multi-hop queries vs vector-only retrieval.

Public surface:
  - BM25Index   — persistent BM25Okapi index over units.jsonl
  - FusedRetriever — RRF fusion of vector + bm25 + entity-overlap

Usage::

    from runtime.memory.retrieval import BM25Index, FusedRetriever

    bm25 = BM25Index(memory_store)
    await asyncio.to_thread(bm25.build)
    fr = FusedRetriever(memory_store, bm25, knowledge_graph=kg)
    results = await fr.retrieve("Awarebot scoring tiers", top_k=10)
"""

from .bm25 import BM25Index
from .fusion import FusedRetriever


__all__ = ["BM25Index", "FusedRetriever"]
