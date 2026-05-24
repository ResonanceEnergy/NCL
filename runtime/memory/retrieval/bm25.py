"""
BM25 keyword index over memory units.

Persisted to ``data/memory/bm25/index.pkl`` as ``(unit_ids, tokenized_docs,
metadata)``; the live ``BM25Okapi`` object is rebuilt from the tokenized
corpus on load (BM25Okapi instances do not pickle cleanly across
``rank_bm25`` versions).

Tokenization: lowercase, strip punctuation, split on whitespace. No
stemming, no stopword removal — the goal is a transparent keyword signal
that complements vector similarity, not a full NLP pipeline.

Atomic persistence — writes to a ``.tmp`` file then ``os.replace()``.
"""

from __future__ import annotations

import json
import logging
import os
import pickle
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING


log = logging.getLogger("ncl.memory.retrieval.bm25")

if TYPE_CHECKING:
    from ..store import MemoryStore


# Module-level lazy import — keeps import-time cheap and lets the rest of
# memory still load if rank-bm25 is missing.
_BM25_IMPORT_ERROR: Exception | None = None
try:
    from rank_bm25 import BM25Okapi  # type: ignore
except Exception as _e:  # pragma: no cover - exercised on machines without dep
    BM25Okapi = None  # type: ignore[assignment]
    _BM25_IMPORT_ERROR = _e


_PUNCT_RE = re.compile(r"[^\w\s$#]+", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+")
# Hard cap on document length so a single 50K-char unit does not skew the
# BM25 average-doc-length and tank scoring for the rest of the corpus.
_MAX_TOKENS_PER_DOC = 1500


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation (keep ``$`` and ``#`` so tickers/tags
    survive), split on whitespace, drop empties and 1-char tokens.
    """
    if not text:
        return []
    lowered = text.lower()
    cleaned = _PUNCT_RE.sub(" ", lowered)
    cleaned = _WS_RE.sub(" ", cleaned).strip()
    if not cleaned:
        return []
    out: list[str] = []
    for tok in cleaned.split(" "):
        if len(tok) < 2:
            continue
        out.append(tok)
        if len(out) >= _MAX_TOKENS_PER_DOC:
            break
    return out


class BM25Index:
    """Persistent BM25Okapi keyword index over ``MemoryStore.memory_file``."""

    def __init__(self, memory_store: "MemoryStore") -> None:
        self.store = memory_store
        self.index_dir: Path = memory_store.data_dir / "bm25"
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.index_file: Path = self.index_dir / "index.pkl"
        self.meta_file: Path = self.index_dir / "meta.json"

        self._bm25: BM25Okapi | None = None  # type: ignore[valid-type]
        self._unit_ids: list[str] = []
        # unit_id -> position in self._tokenized_docs (for incremental update)
        self._unit_pos: dict[str, int] = {}
        self._tokenized_docs: list[list[str]] = []
        self._meta: dict = {
            "docs": 0,
            "avg_doc_length": 0.0,
            "vocabulary_size": 0,
            "last_built": None,
            "build_seconds": None,
        }

        # Best-effort load on construction — missing/corrupt index is fine.
        self._try_load_from_disk()

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _is_available() -> bool:
        return BM25Okapi is not None

    def _try_load_from_disk(self) -> bool:
        """Load tokenized corpus + ids from disk and rebuild the BM25 object."""
        if not self.index_file.exists():
            return False
        if not self._is_available():
            log.debug("[BM25] rank_bm25 not installed — cannot load index")
            return False
        try:
            with open(self.index_file, "rb") as f:
                payload = pickle.load(f)
            self._unit_ids = list(payload.get("unit_ids", []))
            self._tokenized_docs = list(payload.get("tokenized_docs", []))
            self._meta = dict(payload.get("meta", self._meta))
            self._unit_pos = {uid: i for i, uid in enumerate(self._unit_ids)}
            if self._tokenized_docs:
                self._bm25 = BM25Okapi(self._tokenized_docs)
            log.info(
                "[BM25] loaded index — %d docs, vocab=%d, last_built=%s",
                self._meta.get("docs", 0),
                self._meta.get("vocabulary_size", 0),
                self._meta.get("last_built"),
            )
            return True
        except Exception as e:
            log.warning("[BM25] failed to load index from %s: %s", self.index_file, e)
            self._bm25 = None
            self._unit_ids = []
            self._tokenized_docs = []
            self._unit_pos = {}
            return False

    def _persist_atomic(self) -> None:
        """Atomically pickle tokenized corpus + ids; write meta.json sidecar."""
        tmp_pkl = str(self.index_file) + ".tmp"
        tmp_meta = str(self.meta_file) + ".tmp"
        payload = {
            "unit_ids": self._unit_ids,
            "tokenized_docs": self._tokenized_docs,
            "meta": self._meta,
        }
        try:
            with open(tmp_pkl, "wb") as f:
                pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_pkl, str(self.index_file))

            with open(tmp_meta, "w") as f:
                json.dump(self._meta, f, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_meta, str(self.meta_file))
        except Exception as e:
            log.error("[BM25] persist failed: %s", e)
            for tmp in (tmp_pkl, tmp_meta):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    # ----------------------------------------------------------------- build

    def build(self) -> int:
        """Full rebuild from ``units.jsonl``. Synchronous on purpose — call
        via ``asyncio.to_thread()`` from async callers.

        Returns the number of docs indexed.
        """
        if not self._is_available():
            log.warning(
                "[BM25] rank_bm25 not installed: %s — skipping build",
                _BM25_IMPORT_ERROR,
            )
            return 0

        memory_file = self.store.memory_file
        if not memory_file.exists():
            log.info("[BM25] no units.jsonl yet — empty index")
            self._bm25 = None
            self._unit_ids = []
            self._tokenized_docs = []
            self._unit_pos = {}
            self._meta = {
                "docs": 0,
                "avg_doc_length": 0.0,
                "vocabulary_size": 0,
                "last_built": datetime.now(timezone.utc).isoformat(),
                "build_seconds": 0.0,
            }
            self._persist_atomic()
            return 0

        t0 = time.perf_counter()
        # Dedup by unit_id — last occurrence wins, matching MemoryStore.
        seen: dict[str, list[str]] = {}
        try:
            with open(memory_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    uid = obj.get("unit_id")
                    content = obj.get("content")
                    if not uid or not content:
                        continue
                    tokens = _tokenize(content)
                    if not tokens:
                        continue
                    seen[uid] = tokens
        except Exception as e:
            log.error("[BM25] failed reading %s: %s", memory_file, e)
            return 0

        if not seen:
            log.info("[BM25] no tokenizable units — empty index")
            self._bm25 = None
            self._unit_ids = []
            self._tokenized_docs = []
            self._unit_pos = {}
            self._meta = {
                "docs": 0,
                "avg_doc_length": 0.0,
                "vocabulary_size": 0,
                "last_built": datetime.now(timezone.utc).isoformat(),
                "build_seconds": round(time.perf_counter() - t0, 3),
            }
            self._persist_atomic()
            return 0

        unit_ids = list(seen.keys())
        tokenized = [seen[u] for u in unit_ids]
        bm25 = BM25Okapi(tokenized)
        vocab: set[str] = set()
        total_tokens = 0
        for doc in tokenized:
            vocab.update(doc)
            total_tokens += len(doc)
        avg_len = total_tokens / len(tokenized)

        self._bm25 = bm25
        self._unit_ids = unit_ids
        self._tokenized_docs = tokenized
        self._unit_pos = {uid: i for i, uid in enumerate(unit_ids)}
        elapsed = round(time.perf_counter() - t0, 3)
        self._meta = {
            "docs": len(unit_ids),
            "avg_doc_length": round(avg_len, 2),
            "vocabulary_size": len(vocab),
            "last_built": datetime.now(timezone.utc).isoformat(),
            "build_seconds": elapsed,
        }
        self._persist_atomic()
        log.info(
            "[BM25] built index — %d docs, vocab=%d, avg_len=%.1f tokens, took %.2fs",
            len(unit_ids),
            len(vocab),
            avg_len,
            elapsed,
        )
        return len(unit_ids)

    # -------------------------------------------------------------- search

    def search(self, query: str, top_k: int = 20) -> list[tuple[str, float]]:
        """Return ``[(unit_id, bm25_score), ...]`` sorted by score desc.

        Empty results on missing index / dep / empty query — never raises.
        """
        if not self._is_available() or self._bm25 is None or not self._unit_ids:
            return []
        tokens = _tokenize(query)
        if not tokens:
            return []
        try:
            scores = self._bm25.get_scores(tokens)
        except Exception as e:
            log.warning("[BM25] scoring failed: %s", e)
            return []

        # Argpartition would be faster on huge indexes but for 10K docs
        # a single sorted() is already well under 10ms.
        ranked = sorted(
            ((self._unit_ids[i], float(s)) for i, s in enumerate(scores) if s > 0),
            key=lambda x: x[1],
            reverse=True,
        )
        return ranked[:top_k]

    # -------------------------------------------------------------- update

    def update(self, new_unit_ids: list[str]) -> int:
        """Incrementally add new units. Returns count successfully added.

        Failure path falls back to a full ``build()``.
        """
        if not self._is_available():
            return 0
        if not new_unit_ids:
            return 0
        if self._bm25 is None or not self._unit_ids:
            log.info("[BM25] no live index — incremental update falling through to build()")
            return self.build()

        memory_file = self.store.memory_file
        if not memory_file.exists():
            return 0

        wanted = set(new_unit_ids) - set(self._unit_pos.keys())
        if not wanted:
            return 0

        added = 0
        try:
            # Single pass — pick up the latest occurrence of each wanted id.
            latest: dict[str, list[str]] = {}
            with open(memory_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    uid = obj.get("unit_id")
                    if uid in wanted:
                        tokens = _tokenize(obj.get("content", ""))
                        if tokens:
                            latest[uid] = tokens

            if not latest:
                return 0

            for uid, tokens in latest.items():
                self._unit_ids.append(uid)
                self._tokenized_docs.append(tokens)
                self._unit_pos[uid] = len(self._unit_ids) - 1
                added += 1

            # rank_bm25 has no incremental add, so rebuild the small in-mem
            # object — this is O(N) tokens but no disk IO. Worth it.
            self._bm25 = BM25Okapi(self._tokenized_docs)

            # Refresh meta
            vocab: set[str] = set()
            total = 0
            for d in self._tokenized_docs:
                vocab.update(d)
                total += len(d)
            self._meta["docs"] = len(self._unit_ids)
            self._meta["vocabulary_size"] = len(vocab)
            self._meta["avg_doc_length"] = round(total / len(self._unit_ids), 2)
            self._meta["last_built"] = datetime.now(timezone.utc).isoformat()
            self._persist_atomic()
            log.info(
                "[BM25] incremental update — added %d docs (total=%d)", added, len(self._unit_ids)
            )
            return added
        except Exception as e:
            log.warning("[BM25] incremental update failed (%s) — falling back to full rebuild", e)
            return self.build()

    # ------------------------------------------------------------- stats

    def stats(self) -> dict:
        return dict(self._meta)
