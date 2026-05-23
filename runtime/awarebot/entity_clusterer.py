"""
Entity-Streaming Clusterer for Awarebot Cross-Source Scoring
==============================================================

Replaces the token-Jaccard cross-source heuristic in ``Awarebot._compute_cross_source``
(``runtime/awarebot/agent.py`` ~line 2040) with an entity-graph + sector + time-window
co-occurrence clusterer.

Motivation
----------
The legacy ``_compute_cross_source`` walks ``_context_7d`` (last 500 signals), tokenizes
each one, and counts other signals that share >30% token overlap. Because tokenization
is purely lexical, an HN post about "AI tooling" gets credited as confirming a Polymarket
contract about "AI in elections" — they share the token ``ai`` but are otherwise unrelated.
The result: cross-source factor saturates noisily and the council_auto trigger fires on
junk convergence.

This module clusters incoming signals on two stricter criteria:

1. **Shared named entities** — extracted via ``fast_extract_entities`` (tickers like
   ``$TSLA``, person/org names, hashtags). A signal joins a cluster only if it shares
   ≥``min_entity_overlap`` entities with the cluster's anchor set.
2. **Sector co-occurrence within a time window** — sector tags come from
   ``SignalCorrelator.SECTOR_KEYWORDS`` (mirrored here so we have no circular import).
   Clusters time out after ``window_hours``; older clusters get evicted and any
   constituent signals that arrive later seed a new cluster.

The cross-source factor becomes a saturating function of the *number of distinct
sources* in the cluster (not the raw cluster size), so 5 Reddit posts about TSLA
don't beat 2 cross-source confirmations.

    cross_source_score = 0.15 * (1 - exp(-0.6 * n_sources))

This matches the original 6-factor weight of 0.15 documented in the NCL CLAUDE.md
scoring table (item 12 in the audit).

Integration
-----------
See module-level integration notes in agent.py — this file is a drop-in.

Caveats
-------
- Entity extraction quality bounds cluster quality. ``fast_extract_entities`` is regex-only;
  it catches tickers and capitalized multi-word names but misses lowercased company names
  ("openai" without capitalization slips through unless the SECTOR_KEYWORDS sector tag
  catches it). LLM-augmented entity extraction would improve recall at ~2s/signal cost.
- Sector tagging is keyword-based and OR-matches multiple sectors. Cluster sector is
  set to whichever sector matched on the *first* signal — subsequent signals can still
  join via entity overlap even if their sector differs.
- The clusterer is purely streaming/online — no global re-clustering pass. If two
  clusters about the same entity get created (e.g. because signals arrived out of order
  across the time window boundary), they stay separate. Acceptable for an online scorer
  that runs at ingest tempo.
- LRU eviction at ``max_clusters`` triggers on by-cluster basis (drops least-recently-
  updated cluster). High-throughput scanners (>500 distinct entities/hour) will see
  thrash; bump ``max_clusters`` if so.
- Thread safety: clusterer is NOT thread-safe. The Awarebot ingest path is single-
  threaded async — protect with an ``asyncio.Lock`` if you call ``ingest`` from
  multiple coroutines concurrently.
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from collections import OrderedDict, Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional

log = logging.getLogger("ncl.awarebot.entity_clusterer")


# ── Sector keyword mirror ──────────────────────────────────────────────
# Mirrored verbatim from runtime/intelligence/engine.py SignalCorrelator.SECTOR_KEYWORDS
# (as of 2026-05-22). Mirroring avoids importing the heavy SignalCorrelator just to
# read a constant dict. Keep in sync if engine.py changes — if drift becomes a problem,
# refactor SECTOR_KEYWORDS into its own module both can import.
SECTOR_KEYWORDS: dict[str, list[str]] = {
    "crypto": [
        "bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain",
        "defi", "solana", "web3", "nft", "token", "stablecoin", "altcoin",
    ],
    "ai_tech": [
        "ai", "artificial intelligence", "llm", "openai", "anthropic",
        "claude", "gpt", "machine learning", "deepmind", "agi",
        "chatgpt", "gemini ai", "nvidia ai",
    ],
    "macro": [
        "fed", "federal reserve", "inflation", "interest rate", "gdp",
        "recession", "employment", "treasury", "bond", "cpi",
        "tariff", "trade war", "debt ceiling", "yield curve",
        "unemployment", "central bank",
    ],
    "politics": [
        "election", "president", "congress", "senate", "regulation",
        "policy", "government", "democrat", "republican", "trump",
        "biden", "vote", "legislation", "supreme court",
        "war", "ceasefire", "ukraine", "russia", "china", "israel",
        "nato", "sanctions", "hezbollah", "hamas", "iran", "military",
        "geopolit",
    ],
    "markets": [
        "stock", "s&p", "nasdaq", "dow", "equity", "trading",
        "options", "call flow", "put flow", "unusual whales",
        "earnings", "ipo", "merger", "acquisition",
    ],
    "tech": [
        "apple", "google", "microsoft", "amazon", "meta", "tesla",
        "spacex", "semiconductor", "chip", "iphone", "startup",
        "software", "saas", "cloud computing",
    ],
    "entertainment": [
        "movie", "film", "oscars", "emmy", "grammy", "album",
        "eurovision", "gta", "game release", "box office",
        "streaming", "netflix", "disney", "tv show", "celebrity",
        "music award",
    ],
    "sports": [
        "sport", "nba", "nfl", "mlb", "nhl", "soccer", "football",
        "world cup", "fifa", "olympics", "f1", "ufc", "boxing",
        "playoffs", "championship", "super bowl", "premier league",
        "champions league", "grand slam",
    ],
    "energy": [
        "oil", "gas", "energy", "solar", "nuclear", "opec",
        "renewable", "petroleum", "lng",
    ],
    "gaming": ["game", "gaming", "indie", "steam", "unity", "unreal"],
    "music": ["music", "production", "audio", "streaming", "dubforge"],
    "climate": [
        "climate", "weather", "hurricane", "earthquake", "wildfire",
        "temperature", "carbon", "renewable energy",
    ],
}


def _tag_sector(text: str, sector_keywords: dict[str, list[str]]) -> Optional[str]:
    """Return the first matching sector, or None. Lowercased substring match."""
    if not text:
        return None
    low = text.lower()
    for sector, kws in sector_keywords.items():
        for kw in kws:
            if kw in low:
                return sector
    return None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(dt: datetime) -> datetime:
    """Coerce naive datetimes to UTC. Awarebot signals are stamped UTC at ingest,
    but defensive normalization keeps eviction comparisons sane."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ── Data classes ──────────────────────────────────────────────────────


@dataclass
class StreamingCluster:
    """A live cluster of related signals from (ideally) multiple sources.

    A cluster is anchored on its top entities (the most-mentioned entities across
    its constituent signals). New signals join if they share ≥``min_entity_overlap``
    entities with the anchor set OR if their entity set is a non-empty subset of
    the anchor set and their sector matches.
    """

    cluster_id: str
    primary_entity: str
    primary_sector: Optional[str]
    signal_ids: set[str] = field(default_factory=set)
    sources_represented: set[str] = field(default_factory=set)
    # Entity frequency across all constituent signals; top-N becomes the anchor set
    _entity_counts: Counter = field(default_factory=Counter)
    first_seen_at: datetime = field(default_factory=_utc_now)
    last_updated_at: datetime = field(default_factory=_utc_now)

    @property
    def size(self) -> int:
        """Number of distinct signals in the cluster."""
        return len(self.signal_ids)

    @property
    def n_sources(self) -> int:
        """Number of distinct sources represented (the cross-source metric)."""
        return len(self.sources_represented)

    @property
    def anchor_entities(self) -> set[str]:
        """Top-3 most-mentioned entities — used to decide future joins."""
        return {ent for ent, _ in self._entity_counts.most_common(3)}

    @staticmethod
    def cross_source_score(n_sources: int) -> float:
        """Saturating cross-source factor in [0, 0.15].

        Replaces the legacy step function (0 / 0.40 / 0.70 / 1.0). The 0.15 cap
        matches the 15% weight of the cross_source factor in the 6-factor composite
        (NCL CLAUDE.md scoring table). The exponential shape rewards the first
        2-3 confirming sources heavily and saturates so a noisy single source can't
        spam the score.

            n_sources = 1 → 0.067
            n_sources = 2 → 0.105
            n_sources = 3 → 0.126
            n_sources = 4 → 0.139
            n_sources = 5 → 0.145
            n_sources → ∞ → 0.15
        """
        if n_sources <= 0:
            return 0.0
        return 0.15 * (1.0 - math.exp(-0.6 * n_sources))

    def to_dict(self) -> dict[str, Any]:
        """Serialize for telemetry / inspection."""
        return {
            "cluster_id": self.cluster_id,
            "primary_entity": self.primary_entity,
            "primary_sector": self.primary_sector,
            "size": self.size,
            "n_sources": self.n_sources,
            "sources": sorted(self.sources_represented),
            "anchor_entities": sorted(self.anchor_entities),
            "first_seen_at": self.first_seen_at.isoformat(),
            "last_updated_at": self.last_updated_at.isoformat(),
            "cross_source_score": self.cross_source_score(self.n_sources),
        }


# ── Clusterer ─────────────────────────────────────────────────────────


# Default entity extractor — late-bound so tests can inject without importing
# the memory subsystem.
def _default_entity_extractor(text: str) -> list[str]:
    from ..memory.entity_extractor import fast_extract_entities
    return fast_extract_entities(text)


class EntityStreamingClusterer:
    """Online streaming clusterer for Awarebot signals.

    Each ``ingest(signal)`` extracts entities + sector, finds the best matching
    cluster (most overlapping anchor entities), and either joins it or creates
    a new one. Stale clusters are evicted lazily on the next ingest.

    Parameters
    ----------
    window_hours:
        Clusters whose ``last_updated_at`` is older than this are evicted on the
        next ingest. Signals that would have joined an evicted cluster start a
        fresh one — this is how the time-window co-occurrence rule is enforced.
    max_clusters:
        Hard LRU cap on the cluster index. Prevents unbounded memory growth on
        high-cardinality streams. Eviction = least-recently-updated.
    min_entity_freq:
        Minimum entity count required to anchor a new cluster. Signals with fewer
        extracted entities than this get a singleton-tagged cluster but don't act
        as join targets (prevents noise clusters anchored on a single hashtag).
    min_entity_overlap:
        Minimum entity intersection size for a signal to join an existing cluster.
        Default 2 — empirically a single shared entity ($TSLA) is noisy because of
        regex false positives, but two shared entities is strong evidence.
    sector_keywords:
        Override the default SECTOR_KEYWORDS dict. Pass ``{}`` to disable sector
        tagging entirely.
    entity_extractor:
        Callable ``(text: str) -> list[str]``. Defaults to
        ``runtime.memory.entity_extractor.fast_extract_entities`` (lazy-loaded).
        Inject a mock here in tests.
    """

    def __init__(
        self,
        window_hours: float = 6.0,
        max_clusters: int = 500,
        min_entity_freq: int = 2,
        min_entity_overlap: int = 2,
        sector_keywords: Optional[dict[str, list[str]]] = None,
        entity_extractor: Optional[Callable[[str], list[str]]] = None,
    ):
        self.window = timedelta(hours=window_hours)
        self.max_clusters = max_clusters
        self.min_entity_freq = min_entity_freq
        self.min_entity_overlap = min_entity_overlap
        self.sector_keywords = (
            sector_keywords if sector_keywords is not None else SECTOR_KEYWORDS
        )
        self.entity_extractor = entity_extractor or _default_entity_extractor

        # OrderedDict so we can do LRU eviction cheaply (move_to_end on touch,
        # popitem(last=False) on overflow).
        self._clusters: "OrderedDict[str, StreamingCluster]" = OrderedDict()
        # Reverse index: entity → set of cluster_ids that have this entity in
        # their anchor set. Lets ``_find_best_cluster`` skip the linear scan.
        self._entity_index: dict[str, set[str]] = {}

        # Telemetry counters
        self._ingested = 0
        self._joined = 0
        self._created = 0
        self._evicted_stale = 0
        self._evicted_lru = 0

    # ── Public API ────────────────────────────────────────────────────

    def ingest(self, signal: Any) -> tuple[Optional[str], int, int]:
        """Add ``signal`` to a cluster (joining or creating one).

        Returns
        -------
        (cluster_id, cluster_size, n_distinct_sources_in_cluster):
            ``cluster_id`` is None when extraction yielded zero entities AND
            no sector tag — the signal is too thin to cluster meaningfully.
        """
        self._ingested += 1

        # 1. Lazy-evict stale clusters before deciding membership
        self._evict_stale(_utc_now())

        # 2. Extract entities + sector
        text = self._signal_text(signal)
        try:
            entities_list = self.entity_extractor(text) or []
        except Exception as e:
            log.debug(f"entity extractor failed: {e}")
            entities_list = []
        entities = set(entities_list)
        sector = _tag_sector(text, self.sector_keywords)

        if not entities and not sector:
            # Nothing to cluster on — skip
            return (None, 0, 0)

        source = getattr(signal, "source", "") or "unknown"
        signal_id = (
            getattr(signal, "signal_id", None)
            or getattr(signal, "id", None)
            or str(uuid.uuid4())
        )
        ts = getattr(signal, "timestamp", None) or _utc_now()
        ts = _ensure_aware(ts)

        # 3. Find best matching live cluster
        target = self._find_best_cluster(entities, sector)

        if target is not None:
            self._join(target, signal_id, source, entities, ts)
            self._joined += 1
            return (target.cluster_id, target.size, target.n_sources)

        # 4. No match — create a new cluster
        # Only allow this signal to anchor a real (joinable) cluster if it has
        # ≥min_entity_freq distinct entities. Otherwise it's a "thin" cluster
        # that records the signal but won't attract joins from future signals.
        cluster = self._create(entities, sector, signal_id, source, ts)
        self._created += 1
        return (cluster.cluster_id, cluster.size, cluster.n_sources)

    def get_cluster(self, cluster_id: str) -> Optional[StreamingCluster]:
        """Return a cluster by id, or None if it's been evicted."""
        return self._clusters.get(cluster_id)

    def active_clusters(self, min_sources: int = 2) -> list[StreamingCluster]:
        """Return live clusters with ≥``min_sources`` distinct sources.

        Used by ``council_auto_spawn`` candidate selection: a cluster with 3+
        independent sources reporting the same entity within 6h is a strong
        convergence signal worth a council deliberation.

        Returns clusters sorted by (n_sources DESC, size DESC).
        """
        self._evict_stale(_utc_now())
        out = [c for c in self._clusters.values() if c.n_sources >= min_sources]
        out.sort(key=lambda c: (-c.n_sources, -c.size))
        return out

    def stats(self) -> dict[str, Any]:
        """Telemetry snapshot."""
        live = list(self._clusters.values())
        return {
            "live_clusters": len(live),
            "live_signals": sum(c.size for c in live),
            "live_sources_in_any_cluster": len({s for c in live for s in c.sources_represented}),
            "indexed_entities": len(self._entity_index),
            "ingested": self._ingested,
            "joined": self._joined,
            "created": self._created,
            "evicted_stale": self._evicted_stale,
            "evicted_lru": self._evicted_lru,
            "window_hours": self.window.total_seconds() / 3600.0,
            "max_clusters": self.max_clusters,
        }

    # ── Internals ─────────────────────────────────────────────────────

    @staticmethod
    def _signal_text(signal: Any) -> str:
        """Best-effort text extraction. Awarebot ``Signal`` has .title + .content;
        IntelSignal has the same; raw dicts fall through to repr."""
        if isinstance(signal, dict):
            title = signal.get("title", "")
            content = signal.get("content", "")
            return f"{title} {content}"
        title = getattr(signal, "title", "") or ""
        content = getattr(signal, "content", "") or ""
        return f"{title} {content}"

    def _find_best_cluster(
        self, entities: set[str], sector: Optional[str]
    ) -> Optional[StreamingCluster]:
        """Return the live cluster with the largest entity overlap (≥ min_entity_overlap),
        breaking ties by most-recent activity. Falls back to a sector-only match if no
        entity-overlap cluster qualifies and the signal has entities (so we don't pool
        every entity-less crypto blip into one mega-cluster).
        """
        # Use the reverse index to gather candidate cluster ids without scanning all
        candidate_ids: set[str] = set()
        for ent in entities:
            cluster_ids = self._entity_index.get(ent)
            if cluster_ids:
                candidate_ids.update(cluster_ids)

        best: Optional[StreamingCluster] = None
        best_overlap = 0
        for cid in candidate_ids:
            cluster = self._clusters.get(cid)
            if cluster is None:
                continue
            overlap = len(entities & cluster.anchor_entities)
            if overlap < self.min_entity_overlap:
                continue
            if overlap > best_overlap or (
                overlap == best_overlap
                and best is not None
                and cluster.last_updated_at > best.last_updated_at
            ):
                best = cluster
                best_overlap = overlap

        if best is not None:
            return best

        # Sector-only fallback: only consider clusters with the same sector AND at
        # least one entity in common. This keeps the time-windowed sector co-occurrence
        # rule meaningful without devolving into "every AI signal joins one bucket".
        if sector and entities:
            for cid in candidate_ids:
                cluster = self._clusters.get(cid)
                if cluster is None:
                    continue
                if cluster.primary_sector == sector and (entities & cluster.anchor_entities):
                    return cluster

        return None

    def _create(
        self,
        entities: set[str],
        sector: Optional[str],
        signal_id: str,
        source: str,
        ts: datetime,
    ) -> StreamingCluster:
        # Pick primary entity by length (longer entity strings tend to be more
        # specific — "$TSLA" wins over "TSLA", "Elon Musk" wins over "Musk").
        # Falls back to sector name when no entities extracted.
        if entities:
            primary = max(entities, key=lambda e: (len(e), e))
        else:
            primary = sector or "unknown"

        cid = f"cl-{uuid.uuid4().hex[:10]}"
        cluster = StreamingCluster(
            cluster_id=cid,
            primary_entity=primary,
            primary_sector=sector,
            signal_ids={signal_id},
            sources_represented={source},
            first_seen_at=ts,
            last_updated_at=ts,
        )
        for ent in entities:
            cluster._entity_counts[ent] += 1
            self._entity_index.setdefault(ent, set()).add(cid)

        # If the seed signal is too thin to anchor a joinable cluster, we still record
        # it but don't add it to the entity index (prevents thin clusters from
        # attracting subsequent joins). Anchor-eligibility is reconsidered on each
        # join when entity counts grow.
        if len(entities) < self.min_entity_freq:
            for ent in entities:
                self._entity_index.get(ent, set()).discard(cid)

        self._clusters[cid] = cluster
        self._evict_lru()
        return cluster

    def _join(
        self,
        cluster: StreamingCluster,
        signal_id: str,
        source: str,
        entities: set[str],
        ts: datetime,
    ) -> None:
        old_anchors = cluster.anchor_entities
        cluster.signal_ids.add(signal_id)
        cluster.sources_represented.add(source)
        for ent in entities:
            cluster._entity_counts[ent] += 1
        cluster.last_updated_at = ts

        # Update reverse index for any new anchor entities. Anchor set is top-3 by
        # frequency, so a freshly-joining entity might bump an older one out — only
        # re-index the diff.
        new_anchors = cluster.anchor_entities
        for ent in new_anchors - old_anchors:
            self._entity_index.setdefault(ent, set()).add(cluster.cluster_id)
        for ent in old_anchors - new_anchors:
            bucket = self._entity_index.get(ent)
            if bucket:
                bucket.discard(cluster.cluster_id)
                if not bucket:
                    self._entity_index.pop(ent, None)

        # Touch for LRU
        self._clusters.move_to_end(cluster.cluster_id)

    def _evict_stale(self, now: datetime) -> None:
        cutoff = now - self.window
        stale = [
            cid
            for cid, c in self._clusters.items()
            if c.last_updated_at < cutoff
        ]
        for cid in stale:
            self._drop(cid)
            self._evicted_stale += 1

    def _evict_lru(self) -> None:
        while len(self._clusters) > self.max_clusters:
            cid, _ = self._clusters.popitem(last=False)
            self._drop_from_index(cid)
            self._evicted_lru += 1

    def _drop(self, cluster_id: str) -> None:
        self._clusters.pop(cluster_id, None)
        self._drop_from_index(cluster_id)

    def _drop_from_index(self, cluster_id: str) -> None:
        """Remove this cluster_id from every entity bucket. Linear in entity-count
        for the cluster — acceptable because clusters cap at top-3 anchor entities
        in the index."""
        empty_keys = []
        for ent, bucket in self._entity_index.items():
            if cluster_id in bucket:
                bucket.discard(cluster_id)
                if not bucket:
                    empty_keys.append(ent)
        for ent in empty_keys:
            self._entity_index.pop(ent, None)


__all__ = [
    "StreamingCluster",
    "EntityStreamingClusterer",
    "SECTOR_KEYWORDS",
]
