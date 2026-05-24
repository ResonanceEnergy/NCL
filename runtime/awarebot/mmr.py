"""
Maximal Marginal Relevance (MMR) diversification for Awarebot signal routing.

WHY MMR
-------
NCL Awarebot routes ~150 signals per cycle into Focused / Micro / Macro tiers
(10 slots each). After RRF pre-sort, the top of the list is frequently
dominated by near-duplicates: 3 versions of the same Reddit thread mirrored
across r/wallstreetbets / r/options / r/stocks, 4 YouTube-council reports
quoting the same upstream tweet, etc. The per-source hard cap in
`route_to_tiers()` blunts the symptom (one channel can't sweep all slots)
but does nothing about intra-source duplication or cross-source restatements
of the same underlying story.

MMR (Carbonell & Goldstein, 1998) re-ranks an already-relevance-sorted list
by trading off relevance against novelty:

    MMR(d) = lambda * rel(d)  -  (1 - lambda) * max_sim(d, already_selected)

Pick the doc that maximizes that score, add it to the selected set, repeat
until top_k. Lambda is the relevance/diversity knob.

RECOMMENDED INTEGRATION
-----------------------
File: `runtime/awarebot/agent.py`
Function: `route_to_tiers()`
Where:   After the RRF / composite_score pre-sort, BEFORE the per-tier slice
         (i.e. instead of `all_signals[:10]`, run MMR over the eligible pool
         and take its top_k).

Per-tier defaults:
    Focused: lambda_=0.7  (high relevance — these are act-now signals)
    Micro:   lambda_=0.6  (balanced)
    Macro:   lambda_=0.5  (more diversity — narratives benefit from variety)

Copy-paste call signature (apply inside each tier pass, after sort, before slice):

    from runtime.awarebot.mmr import apply_mmr_with_min_per_source

    focused_pool = [s for s in sorted(all_signals, key=...) if _focused_eligible(s)]
    focused = apply_mmr_with_min_per_source(
        focused_pool,
        key_score=lambda s: s.composite_score,
        key_text=lambda s: f"{s.title} {s.content[:300]}",
        key_source=lambda s: _src(s),
        lambda_=0.7,
        top_k=10,
    )

Default similarity is token-set Jaccard (lowercase tokens >=3 chars). Pass a
custom `similarity_fn(text_a, text_b) -> [0,1]` to swap in embedding cosine
later (e.g. via the ChromaDB embedder already loaded in MemoryStore).

CAVEATS
-------
- Jaccard is cheap but blind to paraphrase. A Reddit title saying "Powell
  hints at pause" and a YouTube title "Fed chair signals dovish turn" share
  zero tokens and will NOT be deduped. Upgrade to embedding-cosine when the
  vector path is wired.
- O(top_k * pool_size) per call. At pool=200, top_k=10 that's 2K similarity
  computations per tier — fine.
- Empty `key_text(item)` collapses similarity to 0, so blank-text items are
  treated as maximally novel (acceptable: they get picked once, then have
  no effect on future picks because they're already selected).

NO external dependencies — stdlib only.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable


_TOKEN_RE = re.compile(r"[a-zA-Z0-9]{3,}")


def _tokenize(text: str) -> frozenset[str]:
    if not text:
        return frozenset()
    return frozenset(m.group(0).lower() for m in _TOKEN_RE.finditer(text))


def _jaccard(text_a: str, text_b: str) -> float:
    a, b = _tokenize(text_a), _tokenize(text_b)
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def apply_mmr(
    items: Iterable[Any],
    key_score: Callable[[Any], float],
    key_text: Callable[[Any], str],
    lambda_: float = 0.7,
    top_k: int = 10,
    similarity_fn: Callable[[str, str], float] | None = None,
) -> list[Any]:
    """
    Maximal Marginal Relevance diversification.

    items:         iterable of dicts or objects
    key_score:     callable(item) -> float (relevance score, any scale)
    key_text:      callable(item) -> str   (text used for similarity)
    lambda_:       0.0 = pure diversity, 1.0 = pure relevance
    top_k:         number of items to return
    similarity_fn: callable(text_a, text_b) -> float in [0,1].
                   Defaults to token-set Jaccard (lowercase 3+ char tokens).

    Returns: list of selected items, in selection order.
    """
    pool = list(items)
    if not pool or top_k <= 0:
        return []
    if top_k >= len(pool):
        # Nothing to diversify — return everything sorted by score desc.
        return sorted(pool, key=lambda it: key_score(it), reverse=True)

    sim = similarity_fn or _jaccard
    lambda_ = max(0.0, min(1.0, lambda_))

    # Normalize scores into [0,1] so the relevance term and similarity term
    # live on the same scale. If all scores are equal (or zero), normalized
    # relevance becomes 1.0 for every item and MMR collapses to pure
    # diversity-driven selection.
    scores = [float(key_score(it) or 0.0) for it in pool]
    s_min, s_max = min(scores), max(scores)
    if s_max > s_min:
        norm = [(s - s_min) / (s_max - s_min) for s in scores]
    else:
        norm = [1.0] * len(pool)

    texts = [key_text(it) or "" for it in pool]

    selected_idx: list[int] = []
    remaining = set(range(len(pool)))

    # Seed: highest normalized relevance.
    first = max(remaining, key=lambda i: norm[i])
    selected_idx.append(first)
    remaining.remove(first)

    while len(selected_idx) < top_k and remaining:
        best_i, best_score = None, -float("inf")
        for i in remaining:
            max_sim_to_selected = max(sim(texts[i], texts[j]) for j in selected_idx)
            mmr = lambda_ * norm[i] - (1.0 - lambda_) * max_sim_to_selected
            if mmr > best_score:
                best_score, best_i = mmr, i
        if best_i is None:
            break
        selected_idx.append(best_i)
        remaining.remove(best_i)

    return [pool[i] for i in selected_idx]


def apply_mmr_with_min_per_source(
    items: Iterable[Any],
    key_score: Callable[[Any], float],
    key_text: Callable[[Any], str],
    key_source: Callable[[Any], str],
    lambda_: float = 0.7,
    top_k: int = 10,
    similarity_fn: Callable[[str, str], float] | None = None,
) -> list[Any]:
    """
    MMR variant that GUARANTEES at least one item from each unique source
    (if the source contributes any item to the pool).

    Softer alternative to the hard MAX_PER_SOURCE cap in `route_to_tiers`:
    instead of "at most N per source," this is "at least 1 per source,
    then MMR fills the rest." Useful when you'd rather see all 6 source
    types represented than have 4 slots from the single best-scoring source.
    """
    pool = list(items)
    if not pool or top_k <= 0:
        return []

    # Bucket by source, sorted within each bucket by score desc.
    by_source: dict[str, list[Any]] = {}
    for it in pool:
        src = key_source(it) or "unknown"
        by_source.setdefault(src, []).append(it)
    for src in by_source:
        by_source[src].sort(key=lambda it: key_score(it) or 0.0, reverse=True)

    selected: list[Any] = []
    seen_ids: set[int] = set()

    # Phase 1: top-scoring item from each source (round-robin by source's
    # best score so the strongest source gets seeded first).
    source_order = sorted(
        by_source.keys(), key=lambda s: key_score(by_source[s][0]) or 0.0, reverse=True
    )
    for src in source_order:
        if len(selected) >= top_k:
            break
        top = by_source[src][0]
        selected.append(top)
        seen_ids.add(id(top))

    if len(selected) >= top_k:
        return selected

    # Phase 2: MMR over the remaining pool to fill the rest, treating
    # the Phase-1 picks as already-selected so similarity penalizes
    # near-duplicates of them too.
    remaining_pool = [it for it in pool if id(it) not in seen_ids]
    if not remaining_pool:
        return selected

    sim = similarity_fn or _jaccard
    lambda_ = max(0.0, min(1.0, lambda_))

    all_scores = [float(key_score(it) or 0.0) for it in pool]
    s_min, s_max = min(all_scores), max(all_scores)

    def _norm(it: Any) -> float:
        if s_max <= s_min:
            return 1.0
        return (float(key_score(it) or 0.0) - s_min) / (s_max - s_min)

    selected_texts = [key_text(it) or "" for it in selected]

    while len(selected) < top_k and remaining_pool:
        best_it, best_score = None, -float("inf")
        for it in remaining_pool:
            t = key_text(it) or ""
            max_sim = max((sim(t, st) for st in selected_texts), default=0.0)
            mmr = lambda_ * _norm(it) - (1.0 - lambda_) * max_sim
            if mmr > best_score:
                best_score, best_it = mmr, it
        if best_it is None:
            break
        selected.append(best_it)
        selected_texts.append(key_text(best_it) or "")
        remaining_pool.remove(best_it)

    return selected
