"""
Future Predictor Council — LLM-backed council orchestration.

Council members generate predictions using either:
  - Rule-based heuristics (default, always works)
  - LLM-backed analysis (when ``llm.enabled=true`` in council_config.json
    and ``OPENAI_API_KEY`` is set in the environment)

This module complements the WeightedEnsemble (council/ensemble.py) by providing
strategic-level predictions via named council members rather than pure ML forecasts.
"""

import json
import logging
import os
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ── Enums & data classes ─────────────────────────────────────────────────────

class PredictionHorizon(Enum):
    SHORT_TERM = "1-3 months"
    MEDIUM_TERM = "3-12 months"
    LONG_TERM = "1-5 years"
    STRATEGIC = "5+ years"


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Prediction:
    id: str
    topic: str
    horizon: PredictionHorizon
    confidence: float
    risk_level: RiskLevel
    predicted_outcome: str
    evidence: list[str]
    timestamp: datetime
    council_member: str


@dataclass
class CouncilMember:
    name: str
    specialty: str
    weight: float
    active: bool = True


# ── LLM helper ───────────────────────────────────────────────────────────────

def _llm_complete(prompt: str, config: dict) -> str | None:
    """Call the configured LLM provider (OpenAI-compatible).

    Returns the assistant message text, or *None* on failure so the
    caller can fall back to heuristics.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    model = config.get("model", "gpt-4o-mini")
    temperature = config.get("temperature", 0.7)
    max_tokens = config.get("max_tokens", 1024)

    body = json.dumps({
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": "You are a forecasting analyst on the Future Predictor Council."},
            {"role": "user", "content": prompt},
        ],
    }).encode()

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.warning("LLM call failed (%s) — falling back to heuristics", exc)
        return None


# ── Council ──────────────────────────────────────────────────────────────────

class FuturePredictorCouncil:
    """Main council orchestration class — strategic-level predictions."""

    def __init__(self, config_path: str = "config/council_config.json"):
        self.config = self._load_config(config_path)
        self.council_members = self._init_members()
        self.predictions: list[Prediction] = []
        self.session_id = f"council_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # ── Config ───────────────────────────────────────────────────────────────

    @staticmethod
    def _load_config(config_path: str) -> dict:
        try:
            with open(config_path) as f:
                return json.load(f)
        except FileNotFoundError:
            return {
                "council_name": "Future Predictor Council",
                "quorum_threshold": 0.6,
                "max_predictions_per_session": 10,
                "evidence_required": True,
                "consensus_required": True,
                "llm": {"enabled": False},
            }

    def _init_members(self) -> list[CouncilMember]:
        raw = self.config.get("council_members")
        if raw:
            return [CouncilMember(**m) for m in raw]
        return [
            CouncilMember("Trend Analyzer", "Pattern Recognition", 0.3),
            CouncilMember("Risk Assessor", "Risk Analysis", 0.25),
            CouncilMember("Scenario Planner", "Scenario Development", 0.25),
            CouncilMember("Strategy Advisor", "Strategic Planning", 0.2),
        ]

    # ── Session ──────────────────────────────────────────────────────────────

    def convene_council(self, topic: str, horizon: PredictionHorizon) -> dict:
        logger.info("Convening council for topic: %s (%s)", topic, horizon.value)

        session_data: dict[str, Any] = {
            "session_id": self.session_id,
            "topic": topic,
            "horizon": horizon.value,
            "timestamp": datetime.now().isoformat(),
            "council_members": [m.name for m in self.council_members if m.active],
            "predictions": [],
        }

        for member in self.council_members:
            if member.active:
                prediction = self._generate_prediction(member, topic, horizon)
                if prediction:
                    self.predictions.append(prediction)
                    session_data["predictions"].append(asdict(prediction))

        if self.config.get("consensus_required", False):
            session_data["consensus"] = self._consensus(session_data["predictions"])

        return session_data

    # ── Prediction generation ────────────────────────────────────────────────

    def _generate_prediction(
        self, member: CouncilMember, topic: str, horizon: PredictionHorizon
    ) -> Prediction | None:
        prediction_id = (
            f"{member.name.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        )

        llm_cfg = self.config.get("llm", {})
        outcome, confidence, risk, evidence = self._predict_with_llm(
            member, topic, horizon, llm_cfg
        ) if llm_cfg.get("enabled") else self._predict_heuristic(member, topic)

        return Prediction(
            id=prediction_id,
            topic=topic,
            horizon=horizon,
            confidence=confidence,
            risk_level=risk,
            predicted_outcome=outcome,
            evidence=evidence,
            timestamp=datetime.now(),
            council_member=member.name,
        )

    @staticmethod
    def _predict_heuristic(member, topic):
        spec = member.specialty.lower()
        if "trend" in spec or "pattern" in spec:
            return (f"Trend analysis suggests {topic} will show steady growth",
                    0.75, RiskLevel.LOW,
                    ["Historical data analysis", "Trend modeling"])
        if "risk" in spec:
            return (f"Risk assessment identifies moderate uncertainty in {topic}",
                    0.80, RiskLevel.MEDIUM,
                    ["Risk factor analysis", "Volatility assessment"])
        if "scenario" in spec:
            return (f"Multiple scenarios developed for {topic} evolution",
                    0.70, RiskLevel.MEDIUM,
                    ["Scenario modeling", "Expert consultation"])
        return (f"Strategic recommendation: Monitor {topic} closely",
                0.85, RiskLevel.LOW,
                ["Strategic analysis", "Portfolio alignment check"])

    @staticmethod
    def _predict_with_llm(member, topic, horizon, llm_cfg):
        prompt = (
            f"As a {member.specialty} specialist named '{member.name}', analyse the topic "
            f"'{topic}' over a {horizon.value} horizon.\n\n"
            f"Return ONLY valid JSON with keys: outcome (str), confidence (0-1 float), "
            f"risk (low|medium|high|critical), evidence (list of strings)."
        )
        raw = _llm_complete(prompt, llm_cfg)
        if raw:
            try:
                data = json.loads(raw.strip().strip("`").removeprefix("json").strip())
                risk_map = {r.value: r for r in RiskLevel}
                return (
                    data["outcome"],
                    float(data["confidence"]),
                    risk_map.get(data.get("risk", "medium"), RiskLevel.MEDIUM),
                    data.get("evidence", ["LLM analysis"]),
                )
            except (json.JSONDecodeError, KeyError, ValueError):
                logger.warning("LLM returned unparseable JSON — falling back")
        # Fallback
        return FuturePredictorCouncil._predict_heuristic(member, topic)

    # ── Consensus ────────────────────────────────────────────────────────────

    @staticmethod
    def _consensus(predictions: list[dict]) -> dict:
        if not predictions:
            return {"consensus_reached": False, "reason": "No predictions available"}

        # Weighted confidence: use member weight if available, else equal weight
        weights = []
        confs = []
        for p in predictions:
            w = p.get("weight", 1.0 / len(predictions))
            weights.append(w)
            confs.append(p.get("confidence", 0))

        total_w = sum(weights) or 1.0
        weighted_confidence = sum(w * c for w, c in zip(weights, confs)) / total_w

        outcomes = [p.get("predicted_outcome", "") for p in predictions]
        consensus_outcome = max(set(outcomes), key=outcomes.count) if outcomes else "No consensus"

        # Measure agreement: fraction that agree with consensus outcome
        agreement_ratio = outcomes.count(consensus_outcome) / len(outcomes) if outcomes else 0

        return {
            "consensus_reached": weighted_confidence > 0.7,
            "average_confidence": round(weighted_confidence, 4),
            "consensus_outcome": consensus_outcome,
            "participant_count": len(predictions),
            "agreement_ratio": round(agreement_ratio, 4),
            "aggregation_method": "weighted",
        }

    # ── Status ───────────────────────────────────────────────────────────────

    def get_council_status(self) -> dict:
        return {
            "council_name": self.config.get("council_name", "Future Predictor Council"),
            "active_members": len([m for m in self.council_members if m.active]),
            "total_members": len(self.council_members),
            "session_id": self.session_id,
            "predictions_made": len(self.predictions),
            "available_strategies": self._list_strategies(),
            "last_activity": datetime.now().isoformat(),
        }

    @staticmethod
    def _list_strategies() -> list[str]:
        """Return names of importable forecast strategies."""
        strategies = ["StatsForecastStrategy"]
        optional = {
            "ChronosStrategy": "chronos",
            "TimesFMStrategy": "timesfm",
            "ProphetStrategy": "prophet",
            "NeuralForecastStrategy": "neuralforecast",
        }
        for name, pkg in optional.items():
            try:
                __import__(pkg)
                strategies.append(name)
            except ImportError:
                strategies.append(f"{name} (not installed)")
        return strategies
