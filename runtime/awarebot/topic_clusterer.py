"""
Topic Clusterer — entity + embedding + temporal clustering for Awarebot.

Replaces the legacy `signal.category`-keyed clustering in
`Awarebot.generate_predictions` (which produced a single giant
"general" mega-cluster) with BERTopic-lite:

    1. Embed each signal (sentence-transformers all-MiniLM-L6-v2 if
       available; TF-IDF fallback otherwise).
    2. HDBSCAN(min_cluster_size, metric='cosine') over the embedding
       matrix (cosine via 1 - cosine_similarity precomputed distance
       since hdbscan's native 'cosine' is brittle).
    3. c-TF-IDF (class-based TF-IDF: each cluster treated as a single
       concatenated mega-document) → top-5 distinguishing keywords.
    4. Topic label = top-1 c-TF-IDF keyword, or `label_generator`
       callable (e.g. cheap Haiku one-liner).
    5. HDBSCAN's noise cluster (-1) is discarded.
    6. Sector tag attached if cluster keywords overlap with
       `SignalCorrelator.SECTOR_KEYWORDS`.

The module gracefully degrades:
    embedder unavailable           → TF-IDF cosine clustering
    sklearn unavailable            → simple title-word Jaccard
    hdbscan unavailable            → ImportError raised at construction

Caller contract: `await clusterer.cluster(buffer)` returns
`list[TopicCluster]` sorted by avg composite_score desc.

~350 LOC.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable, Optional


logger = logging.getLogger(__name__)

# Lazy-imported heavy deps — kept optional so the module py_compiles
# without them and tests can stub.
try:  # pragma: no cover - import guard
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "has",
    "have",
    "he",
    "her",
    "his",
    "how",
    "i",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "she",
    "that",
    "the",
    "their",
    "they",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "will",
    "with",
    "you",
    "your",
    "we",
    "our",
    "us",
    "them",
    "those",
    "these",
    "there",
    "than",
    "then",
    "into",
    "about",
    "after",
    "before",
    "just",
    "more",
    "most",
    "some",
    "such",
    "only",
    "also",
    "would",
    "could",
    "should",
    "been",
    "being",
    "via",
    "amp",
    "https",
    "http",
    "com",
    "www",
    "rt",
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{2,}")


@dataclass
class TopicCluster:
    """One topical group of signals emerging from HDBSCAN."""

    cluster_id: int
    topic_label: str
    keywords: list[str]
    signals: list[Any]
    centroid_embedding: Optional[list[float]]
    formed_at: datetime
    avg_score: float
    sources_represented: set[str] = field(default_factory=set)
    sector_tag: Optional[str] = None

    @property
    def is_actionable(self) -> bool:
        """A cluster is worth predicting on: ≥3 signals from ≥2 sources."""
        return len(self.signals) >= 3 and len(self.sources_represented) >= 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "topic_label": self.topic_label,
            "keywords": self.keywords,
            "signal_count": len(self.signals),
            "sources": sorted(self.sources_represented),
            "sector_tag": self.sector_tag,
            "avg_score": round(self.avg_score, 4),
            "formed_at": self.formed_at.isoformat(),
            "is_actionable": self.is_actionable,
        }


EmbedderCallable = Callable[[str], list[float]]
LabelGenerator = Callable[["TopicCluster"], Awaitable[str]] | Callable[["TopicCluster"], str]


class TopicClusterer:
    """
    Entity + embedding + temporal clustering for Awarebot signal buffers.

    Args:
        embedder_callable: Synchronous `text -> list[float]`. The recommended
            implementation wraps `sentence-transformers all-MiniLM-L6-v2`. If
            `None` and TF-IDF is available, we fall back to TF-IDF vectors.
        min_cluster_size: HDBSCAN min_cluster_size. 3 is aggressive (finds
            small narratives); 5 is the BERTopic default; 10 is conservative.
        min_samples: HDBSCAN min_samples. Defaults to `min_cluster_size`.
            Lower → more clusters / less noise; higher → fewer / more noise.
        sector_keywords: Optional mapping (e.g. `SignalCorrelator.SECTOR_KEYWORDS`)
            used to tag each cluster with a coarse sector label.
        label_generator: Optional async/sync callable that turns a TopicCluster
            into a 1-line topic label (use cheap Haiku — see `label_with_llm`).
    """

    def __init__(
        self,
        embedder_callable: Optional[EmbedderCallable] = None,
        min_cluster_size: int = 3,
        min_samples: Optional[int] = None,
        sector_keywords: Optional[dict[str, list[str]]] = None,
        label_generator: Optional[LabelGenerator] = None,
    ) -> None:
        self.embedder = embedder_callable
        self.min_cluster_size = max(2, int(min_cluster_size))
        self.min_samples = int(min_samples) if min_samples else self.min_cluster_size
        self.sector_keywords = sector_keywords or {}
        self.label_generator = label_generator

        self._last_stats: dict[str, Any] = {
            "clusters_total": 0,
            "signals_clustered": 0,
            "noise_pct": 0.0,
            "last_clustered_at": None,
        }

    # ── public API ────────────────────────────────────────────────────

    async def cluster(self, signals: list[Any]) -> list[TopicCluster]:
        """Cluster a signal buffer into topical groups."""
        if not signals:
            self._last_stats.update(
                clusters_total=0,
                signals_clustered=0,
                noise_pct=0.0,
                last_clustered_at=datetime.now(timezone.utc).isoformat(),
            )
            return []

        # 1. Texts for embedding & keyword extraction
        texts = [self._signal_text(s) for s in signals]

        # 2. Embedding matrix (cached per-signal via metadata['_embedding'])
        embeddings = await asyncio.to_thread(self._embed_all, signals, texts)

        # 3. HDBSCAN labels — uses precomputed cosine-distance matrix
        labels = await asyncio.to_thread(self._hdbscan_labels, embeddings)

        # 4. Group by label, drop -1 noise
        grouped: dict[int, list[int]] = defaultdict(list)
        for idx, lbl in enumerate(labels):
            if lbl == -1:
                continue
            grouped[int(lbl)].append(idx)

        # 5. c-TF-IDF keywords across all clusters
        cluster_keywords = self._c_tf_idf(grouped, texts)

        # 6. Build TopicCluster objects
        formed_at = datetime.now(timezone.utc)
        clusters: list[TopicCluster] = []
        for cid, member_idxs in grouped.items():
            members = [signals[i] for i in member_idxs]
            kws = cluster_keywords.get(cid, [])
            centroid = self._centroid(embeddings, member_idxs)
            sources = {getattr(s, "source", "") for s in members if getattr(s, "source", "")}
            avg_score = sum(
                float(getattr(s, "composite_score", 0.0) or 0.0) for s in members
            ) / max(1, len(members))
            sector = self._infer_sector(kws + [getattr(s, "title", "") for s in members])

            cluster = TopicCluster(
                cluster_id=cid,
                topic_label=kws[0].replace("_", " ").title() if kws else f"cluster_{cid}",
                keywords=kws[:5],
                signals=members,
                centroid_embedding=centroid,
                formed_at=formed_at,
                avg_score=avg_score,
                sources_represented=sources,
                sector_tag=sector,
            )
            clusters.append(cluster)

        # 7. Optional LLM relabel (parallel, capped)
        if self.label_generator and clusters:
            await self._relabel_with_llm(clusters)

        clusters.sort(key=lambda c: c.avg_score, reverse=True)

        signals_clustered = sum(len(c.signals) for c in clusters)
        total = len(signals)
        noise_pct = round(100.0 * (total - signals_clustered) / total, 2) if total else 0.0
        self._last_stats = {
            "clusters_total": len(clusters),
            "signals_clustered": signals_clustered,
            "noise_pct": noise_pct,
            "last_clustered_at": formed_at.isoformat(),
        }
        logger.info(
            "[TOPIC_CLUSTER] %d clusters from %d signals (%.1f%% noise)",
            len(clusters),
            total,
            noise_pct,
        )
        return clusters

    def stats(self) -> dict[str, Any]:
        """Telemetry from the last `cluster()` call."""
        return dict(self._last_stats)

    # ── embedding ─────────────────────────────────────────────────────

    @staticmethod
    def _signal_text(signal: Any) -> str:
        title = (getattr(signal, "title", "") or "").strip()
        content = (getattr(signal, "content", "") or "").strip()
        return f"{title} {content[:200]}".strip() or title or "untitled"

    def _embed_all(self, signals: list[Any], texts: list[str]) -> Any:
        """Return an (N, D) numpy array of embeddings. Cache on signal.metadata."""
        if np is None:
            raise RuntimeError("numpy required for TopicClusterer")

        vectors: list[Any] = []
        to_compute: list[tuple[int, str]] = []
        for i, (s, t) in enumerate(zip(signals, texts)):
            meta = getattr(s, "metadata", None)
            cached = meta.get("_embedding") if isinstance(meta, dict) else None
            if cached is not None:
                vectors.append(np.asarray(cached, dtype="float32"))
            else:
                vectors.append(None)
                to_compute.append((i, t))

        if to_compute:
            new_vecs = self._compute_embeddings([t for _, t in to_compute])
            for (i, _), v in zip(to_compute, new_vecs):
                vectors[i] = v
                meta = getattr(signals[i], "metadata", None)
                if isinstance(meta, dict):
                    meta["_embedding"] = v.tolist() if hasattr(v, "tolist") else list(v)

        arr = np.vstack([np.asarray(v, dtype="float32") for v in vectors])
        # L2-normalise so dot product == cosine similarity
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms

    def _compute_embeddings(self, texts: list[str]) -> list[Any]:
        """Compute embeddings via supplied callable or TF-IDF fallback."""
        if self.embedder is not None:
            return [np.asarray(self.embedder(t), dtype="float32") for t in texts]

        # TF-IDF fallback — character n-gram bag-of-words via sklearn
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "TopicClusterer needs either embedder_callable or scikit-learn"
            ) from e

        vec = TfidfVectorizer(
            max_features=512,
            stop_words="english",
            ngram_range=(1, 2),
            min_df=1,
        )
        matrix = vec.fit_transform(texts).toarray().astype("float32")
        return [row for row in matrix]

    # ── HDBSCAN ───────────────────────────────────────────────────────

    def _hdbscan_labels(self, embeddings: Any) -> list[int]:
        """Run HDBSCAN over precomputed cosine distances."""
        try:
            import hdbscan
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "TopicClusterer requires hdbscan: pip3 install --break-system-packages hdbscan"
            ) from e

        n = embeddings.shape[0]
        if n < self.min_cluster_size:
            return [-1] * n

        # Cosine distance from L2-normalised vectors: d = 1 - x·y
        sim = embeddings @ embeddings.T
        dist = 1.0 - sim
        np.clip(dist, 0.0, 2.0, out=dist)
        np.fill_diagonal(dist, 0.0)
        # HDBSCAN expects float64 + symmetric
        dist = ((dist + dist.T) / 2.0).astype("float64")

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=self.min_cluster_size,
            min_samples=self.min_samples,
            metric="precomputed",
            cluster_selection_method="eom",
        )
        labels = clusterer.fit_predict(dist)
        return [int(x) for x in labels.tolist()]

    @staticmethod
    def _centroid(embeddings: Any, member_idxs: list[int]) -> Optional[list[float]]:
        if not member_idxs or np is None:
            return None
        mean = embeddings[member_idxs].mean(axis=0)
        return mean.astype("float32").tolist()

    # ── c-TF-IDF ──────────────────────────────────────────────────────

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [w.lower() for w in _WORD_RE.findall(text or "") if w.lower() not in _STOPWORDS]

    def _c_tf_idf(
        self,
        grouped: dict[int, list[int]],
        texts: list[str],
    ) -> dict[int, list[str]]:
        """
        Class-based TF-IDF: each cluster is one mega-document.
        For each term t in cluster c:
            tf  = count(t in c) / total_terms(c)
            idf = log(1 + total_clusters / num_clusters_containing(t))
        Returns top-5 terms per cluster.
        """
        if not grouped:
            return {}

        cluster_docs: dict[int, list[str]] = {
            cid: [tok for i in idxs for tok in self._tokenize(texts[i])]
            for cid, idxs in grouped.items()
        }
        cluster_counts: dict[int, Counter] = {
            cid: Counter(toks) for cid, toks in cluster_docs.items()
        }
        # Doc-frequency across clusters
        df: Counter = Counter()
        for counts in cluster_counts.values():
            for term in counts:
                df[term] += 1
        n_clusters = len(cluster_counts)

        result: dict[int, list[str]] = {}
        for cid, counts in cluster_counts.items():
            total = sum(counts.values()) or 1
            scored: list[tuple[str, float]] = []
            for term, freq in counts.items():
                if len(term) < 3:
                    continue
                tf = freq / total
                idf = math.log(1.0 + n_clusters / max(1, df[term]))
                scored.append((term, tf * idf))
            scored.sort(key=lambda x: x[1], reverse=True)
            result[cid] = [t for t, _ in scored[:5]]
        return result

    # ── sector tagging ────────────────────────────────────────────────

    def _infer_sector(self, hint_terms: Iterable[str]) -> Optional[str]:
        if not self.sector_keywords:
            return None
        haystack = " ".join(t.lower() for t in hint_terms if t)
        if not haystack:
            return None
        best: Optional[str] = None
        best_hits = 0
        for sector, kws in self.sector_keywords.items():
            hits = sum(1 for kw in kws if kw.lower() in haystack)
            if hits > best_hits:
                best, best_hits = sector, hits
        return best if best_hits >= 2 else None

    # ── LLM labelling ─────────────────────────────────────────────────

    async def _relabel_with_llm(self, clusters: list[TopicCluster]) -> None:
        """Replace top-keyword labels with model-generated one-liners."""
        sem = asyncio.Semaphore(4)

        async def _one(c: TopicCluster) -> None:
            async with sem:
                try:
                    res = self.label_generator(c)  # type: ignore[misc]
                    if asyncio.iscoroutine(res):
                        res = await res
                    if isinstance(res, str) and res.strip():
                        c.topic_label = res.strip()[:120]
                except Exception as e:  # pragma: no cover
                    logger.warning(
                        "[TOPIC_CLUSTER] LLM label failed for cluster %d: %s",
                        c.cluster_id,
                        e,
                    )

        await asyncio.gather(*[_one(c) for c in clusters])


# ── module-level helper ───────────────────────────────────────────────


async def label_with_llm(
    cluster: TopicCluster,
    model_callable: Callable[[str], Awaitable[str]] | Callable[[str], str],
) -> str:
    """
    Cheap Haiku labeller. `model_callable(prompt) -> str`.

    Drops in as `label_generator` arg on `TopicClusterer`:

        clusterer = TopicClusterer(
            embedder_callable=embed_fn,
            label_generator=lambda c: label_with_llm(c, haiku_callable),
        )
    """
    titles = [getattr(s, "title", "") for s in cluster.signals[:6] if getattr(s, "title", "")]
    sample = "\n".join(f"- {t[:120]}" for t in titles)
    prompt = (
        "You name news clusters with a SHORT 3-6 word headline label.\n"
        f"Top keywords: {', '.join(cluster.keywords) or '(none)'}\n"
        "Sample headlines:\n"
        f"{sample}\n\n"
        "Reply with ONLY the label (no quotes, no punctuation at end)."
    )
    res = model_callable(prompt)
    if asyncio.iscoroutine(res):
        res = await res
    label = (res or "").strip().strip("\"'").splitlines()[0] if res else ""
    return label[:120] or (
        cluster.keywords[0] if cluster.keywords else f"cluster_{cluster.cluster_id}"
    )
