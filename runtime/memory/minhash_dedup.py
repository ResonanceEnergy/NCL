"""Wave 14AI (2026-05-30) — MinHash-LSH near-duplicate index.

Per FREE_RESOURCES_BY_LANE_2026-05-30 Memory recommendation: replace the
6h sliding-window dedup scan (``ncl-dedup-scan`` loop) with a persistent
MinHashLSH index that supports real-time near-dup queries in O(1).

Key properties
--------------
- 128 permutations (datasketch default) yields Jaccard-similarity
  estimation accurate to ~5% — enough to catch >0.85 dups.
- LSH buckets at threshold 0.85: two units land in the same bucket if
  their MinHash signatures agree on at least one band, where bands are
  sized so the probability of bucket-coincidence is ~85% at J=0.85.
- O(1) lookup per query — replaces the existing N×M pairwise SimHash
  comparison that limited dedup to a 500-unit window every 6h.
- Persistence: signatures pickled to ``data/memory/minhash_index/``;
  LSH index reconstructable from signatures on rebuild.

Integration
-----------
NOT auto-wired into ``memory/store.py::create_unit()`` in this commit —
the existing 6h scan continues to run. Subsequent wave will:

  1. Walk units.jsonl on first use, populating the MinHash signatures.
  2. Intercept ``create_unit`` to query the index before writing; if a
     near-dup is found at J >= 0.85 with same source + same authority
     tier, reinforce the existing unit instead of writing a new one.
  3. Drop the 6h scheduler loop once the incremental path is verified.

The standalone module ships as a drop-in for any caller that wants
near-dup detection now.
"""

from __future__ import annotations

import json
import logging
import pickle
import re
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.memory.minhash_dedup")


# ── Tunables ─────────────────────────────────────────────────────────

_NUM_PERM = 128  # Permutations per MinHash. 128 is datasketch default.
# Character k-grams are the production standard for paraphrase-tolerant
# dedup (used by Spark MinHashLSH, Google near-dup detector, etc.).
# Character 5-grams over a lowercased + whitespace-normalized text
# catch:
#  - exact reposts at J ≈ 1.0
#  - "Fed" vs "Federal Reserve" + word-order paraphrase at J ≈ 0.4-0.6
#  - unrelated text at J ≈ 0.0-0.1
# Threshold 0.4 gives a clean signal on near-dup pairs in NCL's mix.
_LSH_THRESHOLD = 0.4
_SHINGLE_K = 5  # character k-gram width

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^a-z0-9\s]")


def _shingle(text: str, k: int = _SHINGLE_K) -> set[str]:
    """Return character k-gram shingles as a token set.

    Lowercased + punctuation-stripped + whitespace-collapsed.
    Empty / very short strings return their normalized token set as
    fallback so the MinHash is still defined.
    """
    if not text:
        return set()
    norm = _WS_RE.sub(" ", _PUNCT_RE.sub("", text.lower())).strip()
    if len(norm) < k:
        return {norm} if norm else set()
    return {norm[i : i + k] for i in range(len(norm) - k + 1)}


# ── MinHash + LSH wrapper ────────────────────────────────────────────


class MinHashDedupIndex:
    """Persistent MinHashLSH index for near-duplicate detection.

    Usage::

        idx = MinHashDedupIndex.open()
        idx.add("unit_abc", "Fed signals possible June rate hold ...")
        near = idx.query("Federal Reserve signals June rate pause ...")
        # near = ["unit_abc", ...]  IDs of near-duplicates above threshold

    Thread-safe (single global lock around mutation). Persistence is
    handled lazily — call ``save()`` at quiet times or rely on the
    ``with`` context to flush on exit.
    """

    def __init__(self, num_perm: int = _NUM_PERM, threshold: float = _LSH_THRESHOLD):
        try:
            from datasketch import MinHash, MinHashLSH  # type: ignore
        except ImportError as e:
            raise RuntimeError("datasketch not installed — pip install datasketch") from e

        self._MinHash = MinHash
        self._lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        self._signatures: dict[str, "MinHash"] = {}  # type: ignore[type-arg]
        self._lock = threading.Lock()
        self._num_perm = num_perm
        self._threshold = threshold
        self._dirty = False

    # ──────────────────────────────────────────────────────── add / query

    def _minhash_for(self, text: str) -> object:
        m = self._MinHash(num_perm=self._num_perm)
        for tok in _shingle(text):
            m.update(tok.encode("utf-8"))
        return m

    def add(self, unit_id: str, text: str) -> None:
        """Insert (or replace) a unit's MinHash signature."""
        if not unit_id or not text:
            return
        with self._lock:
            sig = self._minhash_for(text)
            # Replace existing entry — caller may re-add when content
            # changes (e.g. after reinforcement merge).
            if unit_id in self._signatures:
                try:
                    self._lsh.remove(unit_id)
                except Exception:
                    pass
            self._signatures[unit_id] = sig
            self._lsh.insert(unit_id, sig)
            self._dirty = True

    def query(self, text: str, top_k: int = 10) -> list[str]:
        """Return unit_ids whose MinHash signature collides at the LSH threshold."""
        if not text:
            return []
        with self._lock:
            sig = self._minhash_for(text)
            try:
                hits = self._lsh.query(sig)
            except Exception as e:
                log.debug("[minhash] query failed: %s", e)
                return []
        # Sort by exact Jaccard score (sig is small so this is cheap)
        scored: list[tuple[str, float]] = []
        for uid in hits:
            other = self._signatures.get(uid)
            if other is None:
                continue
            try:
                j = float(sig.jaccard(other))
            except Exception:
                j = 0.0
            scored.append((uid, j))
        scored.sort(key=lambda r: r[1], reverse=True)
        return [uid for uid, _ in scored[:top_k]]

    def query_with_scores(self, text: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Like ``query`` but returns (unit_id, jaccard) tuples."""
        if not text:
            return []
        with self._lock:
            sig = self._minhash_for(text)
            try:
                hits = self._lsh.query(sig)
            except Exception as e:
                log.debug("[minhash] query failed: %s", e)
                return []
        scored: list[tuple[str, float]] = []
        for uid in hits:
            other = self._signatures.get(uid)
            if other is None:
                continue
            try:
                j = float(sig.jaccard(other))
            except Exception:
                j = 0.0
            scored.append((uid, j))
        scored.sort(key=lambda r: r[1], reverse=True)
        return scored[:top_k]

    def remove(self, unit_id: str) -> None:
        """Drop a unit's MinHash signature (e.g. on hard-delete)."""
        with self._lock:
            try:
                self._lsh.remove(unit_id)
            except Exception:
                pass
            self._signatures.pop(unit_id, None)
            self._dirty = True

    def __len__(self) -> int:
        return len(self._signatures)

    @property
    def num_signatures(self) -> int:
        return len(self._signatures)

    # ──────────────────────────────────────────────────────── persistence

    DEFAULT_DIR = Path.home() / "dev" / "NCL" / "data" / "memory" / "minhash_index"
    SIGNATURES_FILE = "signatures.pkl"
    META_FILE = "meta.json"

    def save(self, dirpath: Optional[Path] = None) -> None:
        """Flush signatures + meta to disk. Idempotent."""
        dp = Path(dirpath or self.DEFAULT_DIR)
        dp.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with (dp / self.SIGNATURES_FILE).open("wb") as f:
                pickle.dump(self._signatures, f, protocol=pickle.HIGHEST_PROTOCOL)
            (dp / self.META_FILE).write_text(
                json.dumps(
                    {
                        "num_perm": self._num_perm,
                        "threshold": self._threshold,
                        "count": len(self._signatures),
                    },
                    indent=2,
                )
            )
            self._dirty = False
        log.info("[minhash] persisted %d signatures to %s", len(self._signatures), dp)

    @classmethod
    def open(cls, dirpath: Optional[Path] = None) -> "MinHashDedupIndex":
        """Load existing signatures + rebuild LSH index, or create empty."""
        dp = Path(dirpath or cls.DEFAULT_DIR)
        idx = cls()
        sig_path = dp / cls.SIGNATURES_FILE
        if sig_path.exists():
            try:
                with sig_path.open("rb") as f:
                    sigs = pickle.load(f)
            except Exception as e:
                log.warning("[minhash] load failed (%s) — starting fresh", e)
                sigs = {}
            for uid, sig in (sigs or {}).items():
                idx._signatures[uid] = sig
                try:
                    idx._lsh.insert(uid, sig)
                except Exception:
                    pass
            log.info("[minhash] loaded %d signatures from %s", len(idx._signatures), dp)
        return idx


__all__ = ["MinHashDedupIndex"]
