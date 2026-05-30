"""Wave 14AN (2026-05-30) — BERTopic-learned theme clusters.

Per FREE_RESOURCES_BY_LANE Intel recommendation: replace the 5 hardcoded
theme keyword clusters in cross_reference/__init__.py with themes
*learned* from a rolling AWAREBOT signal window.

How it works
------------
1. ``train_bertopic_themes(signals, save_path)`` fits a BERTopic model
   over the past N days of signal text. The model uses:
     - sentence-transformers all-MiniLM-L6-v2 embeddings (fast, English,
       installed in Wave 14AF)
     - UMAP dimensionality reduction
     - HDBSCAN density clustering
     - c-TF-IDF for human-readable topic labels
   Saves the fitted model + a metadata.json with topic_id→label map.

2. ``load_bertopic_themes(save_path)`` reads a fitted model into memory.

3. ``classify_themes_bertopic(text, model)`` returns the matched topic
   id + label + probability for a single signal text.

4. The cross_reference engine calls classify_themes_bertopic when the
   model is loaded and NCL_CROSS_REF_BERTOPIC_ENABLED=true; otherwise
   falls through to the existing keyword-cluster path.

5. The model gets retrained periodically by a scheduler loop (added
   separately) once it has been validated on real signals.

This module ships standalone. The existing hardcoded clusters in
__init__.py remain as the safety net.
"""

from __future__ import annotations

import json
import logging
import os
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


log = logging.getLogger("ncl.cross_reference.bertopic_themes")


# ── Defaults ─────────────────────────────────────────────────────────

_DEFAULT_MIN_TOPIC_SIZE = 5  # minimum signals per cluster
_DEFAULT_N_GRAMS = (1, 2)  # uni + bi-grams for label extraction
_DEFAULT_EMBED_MODEL = os.getenv(
    "NCL_BERTOPIC_EMBED_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2",
)


# ── Paths ────────────────────────────────────────────────────────────

_NCL_BASE = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
_BERTOPIC_DIR = _NCL_BASE / "data" / "cross_reference" / "bertopic_model"
_BERTOPIC_FILE = "model.pkl"
_BERTOPIC_META = "meta.json"


# ── Public API ────────────────────────────────────────────────────────


def train_bertopic_themes(
    signal_texts: list[str],
    save_path: Optional[Path] = None,
    min_topic_size: int = _DEFAULT_MIN_TOPIC_SIZE,
    embed_model: str = _DEFAULT_EMBED_MODEL,
) -> dict:
    """Fit a BERTopic model from a list of signal texts.

    Args:
        signal_texts: 100+ signal text strings — typically the
            content / title fields of agent_signals.jsonl entries
            within a rolling 7d window. Quality > quantity; 200-1000
            recent signals give better clusters than 10000 noisy ones.
        save_path: directory to persist model + metadata. Defaults to
            data/cross_reference/bertopic_model/.
        min_topic_size: minimum signals per cluster. Smaller = more
            topics, more noise. 5 is the BERTopic default.
        embed_model: sentence-transformers model id.

    Returns dict with:
        n_topics, n_documents, topic_labels, train_elapsed_s,
        saved_to.
    """
    try:
        from bertopic import BERTopic  # type: ignore
        from sentence_transformers import SentenceTransformer  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "BERTopic + sentence-transformers required — "
            "pip install bertopic"
        ) from e

    if not signal_texts:
        raise ValueError("signal_texts must be non-empty")
    # Drop empties and dedup so the model sees real diversity
    cleaned: list[str] = []
    seen: set[str] = set()
    for s in signal_texts:
        if not s or len(s.strip()) < 10:
            continue
        key = s.strip()[:200]
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(s.strip())
    if len(cleaned) < min_topic_size * 3:
        raise ValueError(
            f"too few unique non-trivial signals "
            f"({len(cleaned)} after dedup; need ≥{min_topic_size * 3})"
        )

    import time as _t

    t0 = _t.time()
    embed = SentenceTransformer(embed_model)
    topic_model = BERTopic(
        embedding_model=embed,
        min_topic_size=min_topic_size,
        n_gram_range=_DEFAULT_N_GRAMS,
        calculate_probabilities=False,
        verbose=False,
    )
    topics, _ = topic_model.fit_transform(cleaned)
    elapsed = round(_t.time() - t0, 2)

    # Build human-readable label per topic_id (skip the noise topic -1).
    label_map: dict[int, str] = {}
    topic_info = topic_model.get_topic_info()
    for _, row in topic_info.iterrows():
        tid = int(row["Topic"])
        if tid == -1:
            continue
        # BERTopic builds "0_word1_word2_word3..." by default; trim.
        name = str(row.get("Name", "") or "")
        if "_" in name:
            words = name.split("_")[1:]  # drop leading int
            label_map[tid] = " ".join(words[:3]).replace("-", " ")
        else:
            label_map[tid] = name

    # Persist
    sp = Path(save_path or _BERTOPIC_DIR)
    sp.mkdir(parents=True, exist_ok=True)
    with (sp / _BERTOPIC_FILE).open("wb") as f:
        pickle.dump(topic_model, f, protocol=pickle.HIGHEST_PROTOCOL)
    (sp / _BERTOPIC_META).write_text(
        json.dumps(
            {
                "trained_at": datetime.now(timezone.utc).isoformat(),
                "n_documents": len(cleaned),
                "n_topics": len(label_map),
                "min_topic_size": min_topic_size,
                "embed_model": embed_model,
                "topic_labels": label_map,
                "train_elapsed_s": elapsed,
            },
            indent=2,
            default=str,
        )
    )
    log.info(
        "[bertopic-themes] trained on %d docs → %d topics in %.1fs (%s)",
        len(cleaned),
        len(label_map),
        elapsed,
        sp,
    )
    return {
        "n_topics": len(label_map),
        "n_documents": len(cleaned),
        "topic_labels": label_map,
        "train_elapsed_s": elapsed,
        "saved_to": str(sp),
    }


def load_bertopic_themes(save_path: Optional[Path] = None) -> Optional[dict]:
    """Load a fitted BERTopic model + its metadata.

    Returns dict with keys 'model' (BERTopic), 'meta' (dict),
    'label_map' (dict[int,str]). Returns None when no model exists or
    bertopic isn't installed.
    """
    sp = Path(save_path or _BERTOPIC_DIR)
    model_path = sp / _BERTOPIC_FILE
    meta_path = sp / _BERTOPIC_META
    if not (model_path.exists() and meta_path.exists()):
        return None
    try:
        with model_path.open("rb") as f:
            model = pickle.load(f)
        meta = json.loads(meta_path.read_text())
    except Exception as e:
        log.warning("[bertopic-themes] load failed: %s", e)
        return None
    # Normalize label map to int keys (JSON stringifies them)
    raw_labels = meta.get("topic_labels") or {}
    label_map = {int(k): str(v) for k, v in raw_labels.items()}
    return {"model": model, "meta": meta, "label_map": label_map}


def classify_themes_bertopic(
    text: str,
    loaded: dict,
    top_n: int = 1,
) -> list[tuple[str, float]]:
    """Classify a single signal text against the loaded BERTopic model.

    Returns up to top_n (topic_label, score) tuples. Empty list when the
    text didn't match any topic above the noise threshold.
    """
    if not text or not loaded:
        return []
    model = loaded.get("model")
    label_map = loaded.get("label_map") or {}
    if model is None:
        return []
    try:
        topics, probs = model.transform([text])
    except Exception as e:
        log.debug("[bertopic-themes] transform failed: %s", e)
        return []
    if not topics:
        return []
    tid = int(topics[0])
    if tid == -1:  # noise — no theme
        return []
    label = label_map.get(tid, f"topic_{tid}")
    # `probs` is a 2D array of per-topic probabilities — here we take
    # the assigned topic's score directly.
    score = 0.0
    try:
        if probs is not None and len(probs) > 0:
            row = probs[0]
            if hasattr(row, "__len__"):
                score = float(row[tid]) if tid < len(row) else 0.0
            else:
                score = float(row)
    except Exception:
        score = 0.0
    return [(label, score)]


__all__ = [
    "train_bertopic_themes",
    "load_bertopic_themes",
    "classify_themes_bertopic",
    "train_source_stratified_bertopic",
    "load_source_stratified_bertopic",
    "classify_themes_for_source",
]


# ─────────────────────────────────────────────────────────────────────
# Wave 14BJ — source-stratified BERTopic
# ─────────────────────────────────────────────────────────────────────
#
# Themes in a Reddit thread, a YouTube transcript chunk, and a news
# headline span DIFFERENT topic spaces — mixing them in one model
# means tickers dominate (because options-flow + Polymarket short
# text both contain a dense ticker prior), and macro themes from
# YTC transcripts get drowned out. A separate model per source
# preserves the within-source signal.
#
# Layout on disk:
#   data/cross_reference/bertopic_model/_global/{model.pkl,meta.json}
#   data/cross_reference/bertopic_model/reddit/{model.pkl,meta.json}
#   data/cross_reference/bertopic_model/youtube/{model.pkl,meta.json}
#   ... etc
#
# The Wave 14AN single-model path stays as the fallback when the
# stratified directory is empty.


def train_source_stratified_bertopic(
    signals_by_source: dict[str, list[str]],
    save_root: Optional[Path] = None,
    min_topic_size: int = _DEFAULT_MIN_TOPIC_SIZE,
    embed_model: str = _DEFAULT_EMBED_MODEL,
    min_docs_per_source: int = 30,
) -> dict:
    """Train one BERTopic model per source. Skips sources below the
    minimum-doc bar (clusters need volume to find structure).

    Args:
        signals_by_source: {'reddit': [text, ...], 'youtube': [...], ...}
        save_root: directory under which each source gets its own subdir.
        min_topic_size: cluster floor — passed through to per-source trainer.
        embed_model: sentence-transformers model id.
        min_docs_per_source: skip sources with fewer than this many docs.

    Returns:
        {
          'trained': {source: {n_topics, n_documents, train_elapsed_s}},
          'skipped': {source: reason},
          'saved_to': str(save_root),
        }
    """
    root = Path(save_root or _BERTOPIC_DIR)
    root.mkdir(parents=True, exist_ok=True)
    trained: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    for source, texts in signals_by_source.items():
        if not source or source == "_global":
            continue
        if len(texts) < min_docs_per_source:
            skipped[source] = (
                f"only {len(texts)} docs, need >= {min_docs_per_source}"
            )
            continue
        sub = root / source
        try:
            res = train_bertopic_themes(
                texts,
                save_path=sub,
                min_topic_size=min_topic_size,
                embed_model=embed_model,
            )
            trained[source] = {
                "n_topics": res["n_topics"],
                "n_documents": res["n_documents"],
                "train_elapsed_s": res["train_elapsed_s"],
            }
        except Exception as e:
            skipped[source] = f"train failed: {e}"
            log.warning("[bertopic-themes] source %s skipped: %s", source, e)
    return {
        "trained": trained,
        "skipped": skipped,
        "saved_to": str(root),
    }


_source_loaded_cache: dict[str, Optional[dict]] = {}
_source_lookup_attempted: set[str] = set()


def load_source_stratified_bertopic(
    save_root: Optional[Path] = None,
) -> dict[str, dict]:
    """Load all per-source models that exist under save_root.

    Returns dict: {source: loaded_payload}.
    Sources without a fitted model are simply absent from the returned
    map — caller falls back to the global model.
    """
    root = Path(save_root or _BERTOPIC_DIR)
    out: dict[str, dict] = {}
    if not root.exists():
        return out
    for sub in root.iterdir():
        if not sub.is_dir() or sub.name.startswith("_"):
            continue
        loaded = load_bertopic_themes(save_path=sub)
        if loaded:
            out[sub.name] = loaded
    if out:
        log.info(
            "[bertopic-themes] source-stratified models loaded: %s",
            ", ".join(f"{k}={v['meta'].get('n_topics', '?')}" for k, v in out.items()),
        )
    return out


def classify_themes_for_source(
    text: str,
    source: str,
    loaded_by_source: dict[str, dict],
    fallback: Optional[dict] = None,
    top_n: int = 1,
) -> list[tuple[str, float]]:
    """Classify against the per-source model first, fall back to the
    global model if no source-specific model exists for *source*."""
    head = (source or "").split(":")[0].lower()
    loaded = loaded_by_source.get(head)
    if loaded is None and fallback is not None:
        loaded = fallback
    if loaded is None:
        return []
    return classify_themes_bertopic(text, loaded, top_n=top_n)
