"""Signal Scorer — rank and grade predictions/signals by impact and importance.

Every prediction and data signal gets an ``impact_score`` computed as:

    impact_score = confidence × domain_weight × urgency × horizon_factor

Grades map scores to action tiers:
    S  (≥0.80) — Act immediately, high-confidence + high-impact
    A  (≥0.60) — High priority, review within hours
    B  (≥0.40) — Monitor, review daily
    C  (≥0.20) — Background, review weekly
    D  (<0.20) — Archive, low signal

Usage::

    scorer = SignalScorer()
    ranked = scorer.rank_predictions()
    for item in ranked:
        print(f"[{item['grade']}] {item['topic']} — score={item['impact_score']:.2f}")
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Grade thresholds ─────────────────────────────────────────────────────────

GRADE_THRESHOLDS = [
    (0.80, "S"),
    (0.60, "A"),
    (0.40, "B"),
    (0.20, "C"),
    (0.00, "D"),
]

# ── Domain importance weights (aligned with scraper_priority_tiers) ──────────
# tier_1_daily domains get 1.0, tier_2_weekly=0.7, tier_3_monthly=0.4, tier_4_quarterly=0.2

DOMAIN_WEIGHTS = {
    # Tier 1 — daily
    "01_crypto_defi": 1.0,
    "02_financial_markets": 1.0,
    "03_macroeconomics": 0.9,
    "14_governance": 0.8,
    # Tier 2 — weekly
    "04_geopolitics": 0.7,
    "05_energy_resources": 0.7,
    "06_technology": 0.7,
    "07_weather_climate": 0.6,
    # Tier 3 — monthly
    "08_health_disease": 0.4,
    "09_food_agriculture": 0.4,
    "10_demographics": 0.4,
    "11_disasters": 0.5,
    # Tier 4 — quarterly
    "12_space_transport": 0.2,
    "13_alt_fringe": 0.2,
}

# ── Risk → urgency multiplier ───────────────────────────────────────────────

RISK_URGENCY = {
    "critical": 1.5,
    "high": 1.2,
    "medium": 1.0,
    "low": 0.7,
}

# ── Horizon factor (shorter = more urgent) ───────────────────────────────────

HORIZON_FACTOR = {
    "1-3 months": 1.3,
    "3-12 months": 1.0,
    "1-5 years": 0.7,
    "5+ years": 0.4,
    "short": 1.3,
    "medium": 1.0,
    "long": 0.7,
    "strategic": 0.4,
}


def _grade(score: float) -> str:
    """Convert a 0–1 score to a letter grade."""
    for threshold, letter in GRADE_THRESHOLDS:
        if score >= threshold:
            return letter
    return "D"


def _domain_for_topic(topic: str) -> str:
    """Best-effort topic → domain mapping using keyword matching."""
    topic_lower = topic.lower()
    keyword_map = {
        "01_crypto_defi": ["bitcoin", "btc", "ethereum", "eth", "crypto", "defi", "blockchain",
                           "token", "nft", "stablecoin", "mining", "halving"],
        "02_financial_markets": ["stock", "equity", "bond", "yield", "s&p", "nasdaq", "dow",
                                 "forex", "commodity", "gold", "silver", "oil", "market"],
        "03_macroeconomics": ["gdp", "inflation", "cpi", "fed", "interest rate", "unemployment",
                              "recession", "fiscal", "monetary", "debt", "trade deficit"],
        "04_geopolitics": ["war", "conflict", "sanction", "nato", "china", "russia", "trade war",
                           "election", "geopolit", "diplomacy", "military"],
        "05_energy_resources": ["energy", "solar", "wind", "nuclear", "natural gas", "petroleum",
                                "renewable", "grid", "power", "lithium", "cobalt"],
        "06_technology": ["ai", "artificial intelligence", "semiconductor", "chip", "quantum",
                          "software", "saas", "cloud", "cybersecurity", "tech"],
        "07_weather_climate": ["weather", "climate", "temperature", "hurricane", "drought",
                               "flood", "carbon", "emissions", "sea level"],
        "08_health_disease": ["health", "disease", "pandemic", "vaccine", "who", "covid",
                              "mortality", "outbreak", "pharma", "drug"],
        "09_food_agriculture": ["food", "agriculture", "crop", "famine", "grain", "livestock",
                                "fertilizer", "farming"],
        "10_demographics": ["population", "migration", "birth rate", "census", "aging",
                            "urbanization", "refugee"],
        "11_disasters": ["earthquake", "volcano", "tsunami", "wildfire", "disaster", "fema",
                         "tornado", "cyclone"],
        "12_space_transport": ["space", "nasa", "spacex", "satellite", "transport", "ev",
                               "autonomous", "aviation"],
        "13_alt_fringe": ["conspiracy", "anomaly", "unidentified", "fringe", "alternative"],
        "14_governance": ["governance", "regulation", "policy", "law", "congress", "parliament",
                          "UN", "imf", "world bank", "wto"],
    }

    best_domain = "03_macroeconomics"  # default
    best_hits = 0
    for domain, keywords in keyword_map.items():
        hits = sum(1 for kw in keywords if kw in topic_lower)
        if hits > best_hits:
            best_hits = hits
            best_domain = domain
    return best_domain


class SignalScorer:
    """Score and rank predictions/signals by impact."""

    def __init__(self, predictions_path: str = "state/predictions.json"):
        self.predictions_path = Path(predictions_path)

    def score_prediction(self, prediction: dict[str, Any]) -> dict[str, Any]:
        """Compute impact_score and grade for a single prediction.

        Returns the prediction dict enriched with:
            impact_score, grade, domain, domain_weight, urgency, horizon_factor
        """
        confidence = float(prediction.get("confidence", 0.5))
        risk = str(prediction.get("risk_level", "medium")).lower()
        topic = prediction.get("topic", "")

        # Detect horizon from prediction or default
        horizon_raw = prediction.get("horizon", "medium")
        if isinstance(horizon_raw, dict):
            horizon_raw = horizon_raw.get("value", "medium")
        horizon_factor = HORIZON_FACTOR.get(str(horizon_raw), 1.0)

        # Use stored domain hint if available, fall back to keyword matching
        domain = None
        extra = prediction.get("extra")
        if extra:
            try:
                extra_data = json.loads(extra) if isinstance(extra, str) else extra
                domain = extra_data.get("scorer_domain")
            except (json.JSONDecodeError, TypeError):
                pass
        if not domain:
            domain = _domain_for_topic(topic)
        domain_weight = DOMAIN_WEIGHTS.get(domain, 0.5)
        urgency = RISK_URGENCY.get(risk, 1.0)

        raw_score = confidence * domain_weight * urgency * horizon_factor
        # Normalize to 0–1 range (max possible ≈ 1.0 × 1.0 × 1.5 × 1.3 = 1.95)
        impact_score = min(1.0, raw_score / 1.95)

        return {
            **prediction,
            "impact_score": round(impact_score, 4),
            "grade": _grade(impact_score),
            "domain": domain,
            "domain_weight": domain_weight,
            "urgency_multiplier": urgency,
            "horizon_factor": horizon_factor,
        }

    def _load_predictions(self) -> list[dict[str, Any]]:
        """Load predictions from SQLite (preferred) or JSON fallback."""
        try:
            from .persistence import PredictionStore
            store = PredictionStore()
            data = store.list_all()
            if data:
                return data
        except Exception:
            pass
        if not self.predictions_path.exists():
            return []
        return json.loads(self.predictions_path.read_text(encoding="utf-8"))

    def rank_predictions(self, include_resolved: bool = False) -> list[dict[str, Any]]:
        """Load all predictions, score them, return sorted by impact_score desc."""
        predictions = self._load_predictions()

        if not include_resolved:
            predictions = [p for p in predictions if not p.get("resolved", False)]

        scored = [self.score_prediction(p) for p in predictions]
        scored.sort(key=lambda x: x["impact_score"], reverse=True)
        return scored

    def domain_health(self) -> dict[str, dict[str, Any]]:
        """Aggregate accuracy and prediction count per domain."""
        predictions = self._load_predictions()
        domains: dict[str, dict[str, Any]] = {}

        for p in predictions:
            domain = _domain_for_topic(p.get("topic", ""))
            if domain not in domains:
                domains[domain] = {
                    "total": 0, "resolved": 0, "accuracy_sum": 0.0,
                    "avg_confidence": 0.0, "confidence_sum": 0.0,
                }
            domains[domain]["total"] += 1
            domains[domain]["confidence_sum"] += float(p.get("confidence", 0))
            if p.get("resolved") and p.get("accuracy_score") is not None:
                domains[domain]["resolved"] += 1
                domains[domain]["accuracy_sum"] += p["accuracy_score"]

        # Compute averages
        for _domain, stats in domains.items():
            if stats["total"]:
                stats["avg_confidence"] = round(stats["confidence_sum"] / stats["total"], 4)
            if stats["resolved"]:
                stats["avg_accuracy"] = round(stats["accuracy_sum"] / stats["resolved"], 4)
            else:
                stats["avg_accuracy"] = None
            del stats["confidence_sum"]
            del stats["accuracy_sum"]

        return domains

    def member_accuracy(self) -> dict[str, dict[str, Any]]:
        """Per council-member accuracy stats."""
        if not self.predictions_path.exists():
            return {}

        predictions = json.loads(self.predictions_path.read_text(encoding="utf-8"))
        members: dict[str, dict[str, Any]] = {}

        for p in predictions:
            member = p.get("council_member", "Unknown")
            if not member:
                member = "Unknown"
            if member not in members:
                members[member] = {"total": 0, "resolved": 0, "accuracy_sum": 0.0}
            members[member]["total"] += 1
            if p.get("resolved") and p.get("accuracy_score") is not None:
                members[member]["resolved"] += 1
                members[member]["accuracy_sum"] += p["accuracy_score"]

        for _member, stats in members.items():
            if stats["resolved"]:
                stats["avg_accuracy"] = round(stats["accuracy_sum"] / stats["resolved"], 4)
            else:
                stats["avg_accuracy"] = None
            del stats["accuracy_sum"]

        return members

    def score_signal(self, signal: dict[str, Any], domain: str | None = None) -> dict[str, Any]:
        """Score a raw data signal (from signal_cache)."""
        title = signal.get("title", "")
        source = signal.get("source", "")
        detected_domain = domain or _domain_for_topic(title + " " + source)
        domain_weight = DOMAIN_WEIGHTS.get(detected_domain, 0.5)

        # Signals don't have confidence — use source reliability proxy
        source_reliability = 0.7  # default
        raw_score = source_reliability * domain_weight
        impact_score = min(1.0, raw_score)

        return {
            **signal,
            "impact_score": round(impact_score, 4),
            "grade": _grade(impact_score),
            "domain": detected_domain,
        }
