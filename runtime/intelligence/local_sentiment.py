"""Wave 14AJ (2026-05-30) — Local sentiment classification.

Two pre-trained, open-weight transformer models with MIT/Apache 2.0
licensing replace Anthropic Sonnet calls in the AWAREBOT scorer's
"actionability" + "context relevance" factors for text-heavy signals:

  - **FinBERT** (`ProsusAI/finbert`) — financial-news sentiment.
    Positive / Negative / Neutral. Trained on financial news headlines +
    SEC filings. The standard for headline-grade financial sentiment;
    +9-12% over leading LLMs on 5 finance benchmarks per the FinBERT2
    paper (arXiv 2506.06335).
  - **Twitter-RoBERTa-base-sentiment-latest**
    (`cardiffnlp/twitter-roberta-base-sentiment-latest`) — social-media
    sentiment trained on 124M tweets. Positive / Neutral / Negative.

Both load lazily on first use; M1 Ultra MPS-accelerated when available.
A single inference is ~5-20ms on M1 Ultra vs ~500-2000ms for an
Anthropic API round-trip — and $0 per call.

USAGE
-----
    from runtime.intelligence import local_sentiment as ls

    fin = await ls.score_financial("Fed signals June hold; markets shrug")
    # fin = {"label": "neutral", "score": 0.92, "polarity": 0.05,
    #        "raw": {"positive": 0.04, "neutral": 0.92, "negative": 0.04},
    #        "model": "finbert"}

    soc = await ls.score_social("absolutely cooked nvda today imo")
    # soc = {"label": "negative", "score": 0.74, "polarity": -0.62, ...}

INTEGRATION POINTS
------------------
1. `runtime/awarebot/agent.py::reason_about_signal` — replace the
   ambiguous-signal Sonnet pass with a sentiment+actionability lookup.
2. `runtime/intelligence/brief_prep.py::_collect_reddit_top10` —
   pre-tag each Reddit post with sentiment before chair sees them.
3. `runtime/intelligence/free_sources.py::fetch_fed_press_releases` —
   tag press-release titles with financial sentiment for the brief.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Optional

log = logging.getLogger("ncl.intelligence.local_sentiment")


# ── Module-level lazy-loaded pipelines ────────────────────────────────

_FIN_LOCK = threading.Lock()
_SOC_LOCK = threading.Lock()
_fin_pipeline = None  # type: ignore[assignment]
_soc_pipeline = None  # type: ignore[assignment]

# Model ids (FinBERT2 not yet on HF as of May 2026 — fall back to FinBERT
# v1 which is the established production standard with 5+ years of
# validation in finance NLP pipelines).
_FINBERT_MODEL = os.getenv("NCL_FINBERT_MODEL", "ProsusAI/finbert")
_TWITTER_RB_MODEL = os.getenv(
    "NCL_TWITTER_SENTIMENT_MODEL",
    "cardiffnlp/twitter-roberta-base-sentiment-latest",
)


def _resolve_device() -> int:
    """Return the device int for HF pipeline (`-1` CPU, `0` MPS/CUDA).

    Apple-Silicon MPS is supported by transformers >= 4.30 via setting
    `device=torch.device("mps")` when the pipeline is constructed.
    Falls back to CPU on import errors.
    """
    try:
        import torch  # type: ignore

        if torch.backends.mps.is_available() and torch.backends.mps.is_built():
            return 0  # transformers will use the MPS device on macOS
    except Exception:
        pass
    return -1


def _load_financial_pipeline():
    """Lazy-load + cache the FinBERT pipeline. Thread-safe."""
    global _fin_pipeline
    if _fin_pipeline is not None:
        return _fin_pipeline
    with _FIN_LOCK:
        if _fin_pipeline is not None:
            return _fin_pipeline
        try:
            from transformers import pipeline  # type: ignore
        except ImportError as e:
            log.warning("[finbert] transformers not installed: %s", e)
            return None
        try:
            device = _resolve_device()
            _fin_pipeline = pipeline(
                "sentiment-analysis",
                model=_FINBERT_MODEL,
                device=device,
                top_k=None,  # return all class probs
            )
            log.info("[finbert] loaded %s on device=%s", _FINBERT_MODEL, device)
        except Exception as e:
            log.warning("[finbert] load failed: %s", e)
            return None
    return _fin_pipeline


def _load_social_pipeline():
    """Lazy-load + cache the Twitter-RoBERTa pipeline. Thread-safe."""
    global _soc_pipeline
    if _soc_pipeline is not None:
        return _soc_pipeline
    with _SOC_LOCK:
        if _soc_pipeline is not None:
            return _soc_pipeline
        try:
            from transformers import pipeline  # type: ignore
        except ImportError as e:
            log.warning("[twitter-rb] transformers not installed: %s", e)
            return None
        try:
            device = _resolve_device()
            _soc_pipeline = pipeline(
                "sentiment-analysis",
                model=_TWITTER_RB_MODEL,
                device=device,
                top_k=None,
            )
            log.info("[twitter-rb] loaded %s on device=%s", _TWITTER_RB_MODEL, device)
        except Exception as e:
            log.warning("[twitter-rb] load failed: %s", e)
            return None
    return _soc_pipeline


# ── Public scoring API ────────────────────────────────────────────────


def _normalize_scores(raw: list[dict], label_map: dict[str, str]) -> dict:
    """Convert pipeline raw output into NCL's canonical sentiment dict.

    Args:
        raw: list like [{"label": "positive", "score": 0.83}, ...]
        label_map: mapping pipeline label → canonical {positive, neutral, negative}
    """
    if not raw:
        return {"label": "neutral", "score": 0.0, "polarity": 0.0, "raw": {}}

    # Some pipelines wrap results in nested list when top_k=None
    if raw and isinstance(raw[0], list):
        raw = raw[0]

    by_label = {label_map.get(str(item.get("label", "")).lower(), str(item.get("label", ""))).lower(): float(item.get("score") or 0.0) for item in raw}
    # Ensure all 3 classes present (defaults 0)
    for key in ("positive", "neutral", "negative"):
        by_label.setdefault(key, 0.0)

    # Polarity = positive - negative (∈ [-1, 1])
    polarity = round(by_label["positive"] - by_label["negative"], 4)

    # Top class
    top_label = max(by_label, key=by_label.get)
    return {
        "label": top_label,
        "score": round(by_label[top_label], 4),
        "polarity": polarity,
        "raw": {k: round(v, 4) for k, v in by_label.items()},
    }


_FINBERT_LABEL_MAP = {
    "positive": "positive",
    "neutral": "neutral",
    "negative": "negative",
    # FinBERT-v1 emits exactly those three; map defensively.
}

_TWITTER_LABEL_MAP = {
    "positive": "positive",
    "neutral": "neutral",
    "negative": "negative",
    "label_0": "negative",
    "label_1": "neutral",
    "label_2": "positive",
}


def _score_sync(pipe, text: str, label_map: dict[str, str], model_name: str) -> dict:
    if not pipe or not text:
        return {
            "label": "neutral",
            "score": 0.0,
            "polarity": 0.0,
            "raw": {},
            "model": model_name,
        }
    try:
        # FinBERT and Twitter-RoBERTa have token caps; truncate aggressively.
        text = text.strip()
        if len(text) > 2000:
            text = text[:2000]
        raw = pipe(text, truncation=True)
        out = _normalize_scores(raw, label_map)
        out["model"] = model_name
        return out
    except Exception as e:
        log.debug("[sentiment] inference failed (%s): %s", model_name, e)
        return {
            "label": "neutral",
            "score": 0.0,
            "polarity": 0.0,
            "raw": {},
            "model": model_name,
            "error": str(e)[:120],
        }


async def score_financial(text: str) -> dict:
    """Financial sentiment via FinBERT.

    Use for: headlines, SEC filings, earnings transcripts, press releases.
    Returns: {label, score, polarity ∈ [-1,1], raw, model}.
    """
    pipe = await asyncio.to_thread(_load_financial_pipeline)
    return await asyncio.to_thread(_score_sync, pipe, text, _FINBERT_LABEL_MAP, "finbert")


async def score_social(text: str) -> dict:
    """Social-media sentiment via Twitter-RoBERTa.

    Use for: Bluesky / X / Mastodon / Reddit posts, Telegram channel posts.
    Returns: {label, score, polarity, raw, model}.
    """
    pipe = await asyncio.to_thread(_load_social_pipeline)
    return await asyncio.to_thread(_score_sync, pipe, text, _TWITTER_LABEL_MAP, "twitter-roberta")


async def score_batch(
    texts: list[str], domain: str = "financial"
) -> list[dict]:
    """Batch-score a list of texts. Single pipeline call per batch."""
    if not texts:
        return []
    if domain == "financial":
        pipe = await asyncio.to_thread(_load_financial_pipeline)
        label_map = _FINBERT_LABEL_MAP
        model_name = "finbert"
    else:
        pipe = await asyncio.to_thread(_load_social_pipeline)
        label_map = _TWITTER_LABEL_MAP
        model_name = "twitter-roberta"

    if not pipe:
        return [
            {"label": "neutral", "score": 0.0, "polarity": 0.0, "raw": {}, "model": model_name}
            for _ in texts
        ]

    def _run() -> list[dict]:
        out: list[dict] = []
        try:
            results = pipe([t.strip()[:2000] for t in texts], truncation=True)
            for raw in results:
                if not isinstance(raw, list):
                    raw = [raw]
                d = _normalize_scores(raw, label_map)
                d["model"] = model_name
                out.append(d)
        except Exception as e:
            log.debug("[sentiment-batch] failed: %s", e)
            for _ in texts:
                out.append({"label": "neutral", "score": 0.0, "polarity": 0.0, "raw": {}, "model": model_name})
        return out

    return await asyncio.to_thread(_run)


__all__ = [
    "score_financial",
    "score_social",
    "score_batch",
]
