"""
Polymarket edge engine — Wave 14R R3

For each active Polymarket market, find any recent NCL predictions whose
topic/title/text overlaps materially. If found, compute:

    edge_pp = stated_probability - market_yes_price

A positive `edge_pp` of ≥10pp is a candidate bet. Half-Kelly sizing,
clipped by liquidity cap + cluster heat (delegated to discipline module
from Wave 14J).

This replaces the hardcoded 5pp edge in Wave 14L's polymarket_kelly
scanner with a REAL signal grounded in our own forecasts.

Output: list[EdgeOpportunity] sorted by edge_pp descending.

Env:
  NCL_POLY_EDGE_MIN_PP   (default 10 — minimum edge in percentage points)
  NCL_POLY_EDGE_PRED_LOOKBACK_HOURS (default 48 — how far back to look for predictions)
  NCL_POLY_EDGE_MIN_OVERLAP (default 2 — keyword matches required to consider linked)
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.polymarket_agent.edge_engine")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
PRED_DIR = NCL_BASE / "data" / "predictions"

MIN_EDGE_PP = float(os.getenv("NCL_POLY_EDGE_MIN_PP", "10"))
PRED_LOOKBACK_HOURS = int(os.getenv("NCL_POLY_EDGE_PRED_LOOKBACK_HOURS", "48"))
MIN_OVERLAP = int(os.getenv("NCL_POLY_EDGE_MIN_OVERLAP", "2"))

# Words that don't help match a prediction to a market
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "will", "would", "could", "should", "may", "might", "must", "can",
    "of", "to", "in", "on", "at", "for", "by", "from", "with", "about",
    "as", "and", "or", "but", "if", "then", "than", "this", "that",
    "these", "those", "it", "its", "we", "you", "they", "have", "has",
    "had", "do", "does", "did", "what", "which", "who", "when", "where",
    "why", "how", "very", "likely", "probability", "chance", "likelihood",
    "next", "before", "after", "during", "through", "until", "by",
})


@dataclass
class EdgeOpportunity:
    market_slug: str
    market_question: str
    market_yes_price: float
    market_volume_24h_usd: float
    market_liquidity_usd: float
    market_end_date_iso: Optional[str]
    side: str  # "YES" if edge>0, "NO" if edge<0 (we bet against the side we disagree with)
    prediction_id: Optional[str]
    prediction_title: Optional[str]
    prediction_stated_probability: Optional[float]
    edge_pp: float            # absolute edge in percentage points (always positive)
    raw_edge: float           # signed edge for debugging
    overlap_score: int
    overlap_terms: list[str] = field(default_factory=list)
    days_to_resolution: Optional[int] = None
    computed_at_iso: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    raw = re.findall(r"[a-zA-Z]{3,}", text.lower())
    return {t for t in raw if t not in _STOPWORDS}


def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _load_recent_predictions(hours: int = PRED_LOOKBACK_HOURS) -> list[dict]:
    """Scan disk for predictions emitted in the last N hours."""
    if not PRED_DIR.exists():
        return []
    cutoff = _now() - timedelta(hours=hours)
    out: list[dict] = []
    # Both ensemble + council prediction files
    patterns = ["pred-*.json", "council/council-pred-*.json"]
    for pattern in patterns:
        for f in PRED_DIR.glob(pattern):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    continue
                data = json.loads(f.read_text())
                preds = []
                if isinstance(data, list):
                    preds = data
                elif isinstance(data, dict) and "predictions" in data:
                    preds = data["predictions"]
                elif isinstance(data, dict):
                    preds = [data]
                for p in preds:
                    if not isinstance(p, dict):
                        continue
                    out.append(p)
            except Exception:
                continue
    return out


def _stated_prob(pred: dict) -> Optional[float]:
    """Pull stated_probability the same way predictions.py exposes it.
    Falls back to confidence if not present."""
    sp = pred.get("stated_probability")
    if isinstance(sp, (int, float)) and 0 < sp <= 1:
        return float(sp)
    # confidence may already be overridden with stated_probability per Wave 14Q
    c = pred.get("confidence")
    if isinstance(c, (int, float)) and 0 < c <= 1:
        return float(c)
    return None


def _prediction_text(pred: dict) -> str:
    """Best human-readable text for matching."""
    parts = [
        pred.get("title", ""),
        pred.get("description", ""),
        pred.get("topic", ""),
    ]
    return " ".join(p for p in parts if p)


def _days_to_resolution(market: dict) -> Optional[int]:
    end_iso = market.get("end_date_iso")
    if not end_iso:
        return None
    d = _parse_iso(end_iso)
    if d is None:
        return None
    return max(0, (d - _now()).days)


def _match_predictions(market_question: str, predictions: list[dict]) -> tuple[Optional[dict], int, list[str]]:
    """Find best-overlapping prediction. Returns (pred or None, overlap_count, terms)."""
    market_tokens = _tokens(market_question)
    if not market_tokens:
        return None, 0, []
    best = None
    best_score = 0
    best_terms: list[str] = []
    for p in predictions:
        pred_tokens = _tokens(_prediction_text(p))
        overlap = market_tokens & pred_tokens
        if len(overlap) > best_score:
            best = p
            best_score = len(overlap)
            best_terms = sorted(overlap)[:6]
    return best, best_score, best_terms


def compute_edges(
    markets: list[dict],
    predictions: Optional[list[dict]] = None,
    *,
    min_edge_pp: float = MIN_EDGE_PP,
    min_overlap: int = MIN_OVERLAP,
) -> list[EdgeOpportunity]:
    """Compute edge opportunities from market list + recent predictions.

    Strategy: for each market in (0.10-0.90) price range with non-zero
    volume, find the best-matching prediction (≥min_overlap shared
    terms). If matched, compute edge. Emit only those with
    |edge_pp| >= min_edge_pp.

    If no prediction matches a market, we DO NOT bet — pure market-vs-
    nothing has no edge. (Future work: bake LLM-based prior here.)
    """
    if predictions is None:
        predictions = _load_recent_predictions()
    log.info(
        "[POLY-EDGE] computing edges over %d markets × %d predictions "
        "(min_edge=%.0fpp, min_overlap=%d)",
        len(markets), len(predictions), min_edge_pp, min_overlap,
    )

    out: list[EdgeOpportunity] = []
    now_iso = _now().isoformat()

    for m in markets:
        try:
            if m.get("lifecycle_status") == "resolved":
                continue
            yes = m.get("yes_price")
            if not isinstance(yes, (int, float)):
                continue
            if not (0.05 <= yes <= 0.95):
                continue  # avoid degenerate priced edges
            vol24 = float(m.get("volume_24h_usd") or 0)
            if vol24 < 1000:
                continue  # need liquidity to enter/exit

            question = m.get("question") or ""
            pred, overlap, terms = _match_predictions(question, predictions)
            if pred is None or overlap < min_overlap:
                continue

            stated = _stated_prob(pred)
            if stated is None:
                continue

            raw_edge = stated - float(yes)
            edge_pp = abs(raw_edge) * 100.0
            if edge_pp < min_edge_pp:
                continue

            side = "YES" if raw_edge > 0 else "NO"
            out.append(EdgeOpportunity(
                market_slug=m.get("slug") or "",
                market_question=question,
                market_yes_price=float(yes),
                market_volume_24h_usd=vol24,
                market_liquidity_usd=float(m.get("liquidity_usd") or 0),
                market_end_date_iso=m.get("end_date_iso"),
                side=side,
                prediction_id=pred.get("prediction_id"),
                prediction_title=pred.get("title") or pred.get("description"),
                prediction_stated_probability=stated,
                edge_pp=round(edge_pp, 2),
                raw_edge=round(raw_edge, 4),
                overlap_score=overlap,
                overlap_terms=terms,
                days_to_resolution=_days_to_resolution(m),
                computed_at_iso=now_iso,
            ))
        except Exception as e:
            log.debug("[POLY-EDGE] market skip: %s (%s)", m.get("slug"), e)
            continue

    out.sort(key=lambda e: e.edge_pp, reverse=True)
    log.info(
        "[POLY-EDGE] %d opportunities >= %.0fpp edge (top=%.1fpp)",
        len(out), min_edge_pp, out[0].edge_pp if out else 0,
    )
    return out
