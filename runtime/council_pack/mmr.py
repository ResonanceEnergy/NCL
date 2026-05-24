"""
MMR — Maximal Marginal Relevance over retrieval candidates.

Carbonell & Goldstein 1998. Picks items that are simultaneously relevant to
the query AND diverse from items already picked. Standard antidote to the
paraphrase echo chamber that vanilla top-K cosine produces.

We don't have a per-candidate embedding handy at MMR time (the FusedRetriever
keeps embeddings inside ChromaDB and discards them after RRF). So we use a
lightweight TF-IDF cosine over the candidate ``content`` field. That is:

* Cheap (no extra Anthropic / Cohere roundtrip).
* Good enough — MMR's diversity check is between *candidates*, not between
  query and candidate. Lexical similarity is a strong-enough proxy for
  paraphrase detection at this granularity.
* Always available — the candidates already carry their content string.

Formula
-------
At step ``i``, pick the candidate ``c`` that maximizes::

    score(c) = λ · rel(c, query) − (1 − λ) · max( sim(c, s) for s in selected )

where ``rel(c, query)`` is the candidate's ``fused_score`` (already query-
relevance-scored by RRF + authority) and ``sim(c, s)`` is the TF-IDF cosine
between two candidates' content strings.

λ controls the relevance/diversity trade-off:
*   1.0 → pure relevance (vanilla top-K)
*   0.0 → pure diversity
*  ~0.7 → relevance-leaning with diversity floor (our default — same default
         used by every production MMR implementation I've ever seen)
"""

from __future__ import annotations  # noqa: I001

import hashlib
import logging
import math
import re
from collections import Counter, OrderedDict
from typing import Iterable  # noqa: F401

log = logging.getLogger("ncl.council_pack.mmr")

# ── TF-IDF bag cache ────────────────────────────────────────────────────────
# Audit 2026-05-23 (W4-10): MMR was rebuilding ~900 TF bags per assemble call.
# Content strings rarely change across assembles for the same memory unit, so
# hash the text and cache the resulting bag. Cache key = first 16 hex of
# sha256(content) — 64 bits, ample for our scale (collisions ~negligible at
# ~25K units). Simple OrderedDict LRU with size cap; drop oldest 50% on
# overflow rather than evicting one-at-a-time to keep amortized cost low.
_BAG_CACHE: "OrderedDict[str, dict[str, float]]" = OrderedDict()
_BAG_CACHE_MAX = 5000
_BAG_CACHE_HITS = 0
_BAG_CACHE_MISSES = 0
_BAG_CACHE_CALL_LOG_EVERY = 1000


def clear_mmr_cache() -> dict:
    """Clear the TF-bag cache. Returns prior stats. Callable from tests or
    the weekly memory-eval loop (we do not auto-clear)."""
    global _BAG_CACHE_HITS, _BAG_CACHE_MISSES
    prior = {
        "size": len(_BAG_CACHE),
        "hits": _BAG_CACHE_HITS,
        "misses": _BAG_CACHE_MISSES,
    }
    _BAG_CACHE.clear()
    _BAG_CACHE_HITS = 0
    _BAG_CACHE_MISSES = 0
    return prior


# Stopwords kept tiny on purpose. The content strings are noisy enough that an
# aggressive stopword list would scrub away useful tokens (ticker symbols,
# council vocabulary, etc.).
_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "if",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "with",
        "by",
        "from",
        "as",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "he",
        "she",
        "they",
        "we",
        "you",
        "i",
        "me",
        "my",
        "your",
        "their",
        "our",
        "will",
        "would",
        "should",
        "can",
        "could",
        "may",
        "might",
        "must",
        "not",
        "no",
        "so",
        "too",
        "very",
        "than",
        "then",
    }
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_$%][A-Za-z0-9_'$%-]{1,30}")


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS]


def _bag(text: str) -> dict[str, float]:
    """TF bag — token → log-scaled term frequency. ``log(1 + tf)`` so a token
    repeated 20× doesn't drown out 5 distinct rare tokens that appear once each.

    Cached by sha256(text) prefix. The cache is per-process and is safe to
    share across MMR calls because the bag is purely a function of ``text``.
    """
    global _BAG_CACHE_HITS, _BAG_CACHE_MISSES
    if not text:
        # Don't pollute cache with empty strings.
        _BAG_CACHE_MISSES += 1
        return {}

    key = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
    cached = _BAG_CACHE.get(key)
    if cached is not None:
        # Touch for LRU.
        _BAG_CACHE.move_to_end(key)
        _BAG_CACHE_HITS += 1
        _maybe_log_hit_rate()
        return cached

    counts: Counter[str] = Counter(_tokenize(text))
    bag = {t: math.log1p(c) for t, c in counts.items()}

    _BAG_CACHE[key] = bag
    _BAG_CACHE_MISSES += 1

    # Bulk eviction: when we exceed cap, drop oldest 50% in one shot. Cheaper
    # amortized than evicting one entry per insert above the cap.
    if len(_BAG_CACHE) > _BAG_CACHE_MAX:
        drop = len(_BAG_CACHE) // 2
        for _ in range(drop):
            _BAG_CACHE.popitem(last=False)

    _maybe_log_hit_rate()
    return bag


def _maybe_log_hit_rate() -> None:
    total = _BAG_CACHE_HITS + _BAG_CACHE_MISSES
    if total and total % _BAG_CACHE_CALL_LOG_EVERY == 0:
        rate = (_BAG_CACHE_HITS / total) * 100.0
        log.info(
            "[MMR] cache hit rate: %.1f%% over %d calls (size=%d)",
            rate,
            total,
            len(_BAG_CACHE),
        )


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    common = set(a).intersection(b)
    if not common:
        return 0.0
    dot = sum(a[t] * b[t] for t in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def mmr_select(
    candidates: list[dict],
    top_k: int,
    lambda_: float = 0.7,
    content_key: str = "content",
    relevance_key: str = "fused_score",
) -> list[dict]:
    """Pick top_k diverse items from ``candidates``.

    Parameters
    ----------
    candidates : list[dict]
        FusedRetriever output dicts. Order doesn't matter — MMR re-ranks.
    top_k : int
        Number of items to return. ``min(top_k, len(candidates))`` is honored.
    lambda_ : float, default 0.7
        Relevance/diversity trade-off. Clamped to ``[0.0, 1.0]``.
    content_key : str, default "content"
        Dict key whose value is the candidate's text body.
    relevance_key : str, default "fused_score"
        Dict key whose value is the candidate's query-relevance score (e.g.
        the RRF-+-authority-weighted score from FusedRetriever.retrieve()).
        Missing key defaults to ``0.0``.

    Returns
    -------
    list[dict]
        Up to ``top_k`` candidates, ordered by MMR pick order, with a new key
        ``mmr_score`` set on each picked item.
    """
    if not candidates or top_k <= 0:
        return []

    lambda_c = max(0.0, min(1.0, float(lambda_)))
    bags = [_bag(c.get(content_key, "") or "") for c in candidates]

    # Normalize relevance to [0, 1] using max value present. Avoids dominance
    # when relevance is in raw RRF scale (~0.05) vs cosine diversity (~0.5).
    raw_rel = [float(c.get(relevance_key, 0.0) or 0.0) for c in candidates]
    max_rel = max(raw_rel) if raw_rel else 0.0
    rel = [r / max_rel if max_rel > 0 else 0.0 for r in raw_rel]

    selected_indices: list[int] = []
    remaining = set(range(len(candidates)))

    target = min(top_k, len(candidates))
    while len(selected_indices) < target and remaining:
        best_i = -1
        best_score = float("-inf")
        for i in remaining:
            if not selected_indices:
                diversity_pen = 0.0
            else:
                diversity_pen = max(_cosine(bags[i], bags[s]) for s in selected_indices)
            score = lambda_c * rel[i] - (1.0 - lambda_c) * diversity_pen
            if score > best_score:
                best_score = score
                best_i = i
        if best_i < 0:
            break
        selected_indices.append(best_i)
        remaining.discard(best_i)
        # Attach MMR score for downstream telemetry / debugging.
        picked = candidates[best_i]
        picked["mmr_score"] = round(best_score, 6)

    return [candidates[i] for i in selected_indices]


__all__ = ["mmr_select", "clear_mmr_cache"]
