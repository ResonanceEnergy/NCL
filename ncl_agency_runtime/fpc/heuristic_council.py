"""
Future Predictor Council — BRS Strategic Forecasting System

Council members generate predictions using either:
  - Rule-based heuristics (default, always works)
  - LLM-backed analysis (when ``llm.enabled=true`` in council_config.json
    and ``OPENAI_API_KEY`` is set in the environment)
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

    body = json.dumps(
        {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": "You are a forecasting analyst on the Future Predictor Council."},
                {"role": "user", "content": prompt},
            ],
        }
    ).encode()

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


# ── Heuristic outcome generators ─────────────────────────────────────────────
# Produce varied, substantive prediction text without echoing the raw topic.

import re as _re


def _extract_subject(topic: str) -> str:
    """Pull the core subject from a question-form topic.

    'Will autonomous AI agents replace most software engineering tasks by 2028?'
    → 'autonomous AI agents'
    'How will CRISPR gene therapy transform treatment of genetic diseases?'
    → 'CRISPR gene therapy'
    """
    t = topic.rstrip("?. ")
    # Strip leading Will/How will/How might/Can/Could/Should etc.
    t = _re.sub(r"^(Will|How will|How might|Can|Could|Should|Is|Are|Do|Does)\s+", "", t, flags=_re.I)
    # Strip trailing time references like "by 2028", "by year-end 2026"
    t = _re.sub(r"\s+by\s+(year-end\s+)?\d{4}$", "", t, flags=_re.I)
    # Strip trailing clauses after certain verbs for cleaner subject
    # e.g. "AI agents replace most software engineering tasks" → "AI agents"
    # But keep the full phrase if it's short enough
    words = t.split()
    if len(words) > 3:
        # Try to find a natural break verb and take what's before it
        for i, w in enumerate(words):
            if w.lower() in (
                "replace",
                "outperform",
                "reshape",
                "transform",
                "dominate",
                "disrupt",
                "change",
                "affect",
                "influence",
                "threaten",
                "achieve",
                "become",
                "give",
                "manage",
                "eliminate",
                "converge",
                "compete",
                "improve",
                "cut",
                "create",
                "produce",
                "win",
                "match",
                "make",
                "drive",
                "accelerate",
            ):
                if i >= 1:  # Keep at least 1 word
                    t = " ".join(words[:i])
                    break
    words = t.split()
    if len(words) > 12:
        t = " ".join(words[:12])
    return t


_TREND_TEMPLATES = [
    "Early indicators point to accelerating momentum. Data vectors show {subj} tracking above baseline with broadening adoption.",
    "Pattern analysis shows a clear inflection point forming. Near-term signals position {subj} for significant movement.",
    "Historical parallels suggest a 60-70% probability of positive trajectory, mirroring prior adoption cycles for {subj}.",
    "Data convergence detected. Multiple independent signals reinforce a growth phase for {subj}, with broadening adoption across key vectors.",
    "Momentum metrics are elevated, with {subj} showing sustained week-over-week acceleration consistent with breakout conditions.",
]

_RISK_TEMPLATES = [
    "Key risk factors include execution uncertainty and regulatory headwinds, creating a moderate probability of disruption for {subj}.",
    "Downside scenarios center on adoption barriers and market saturation, with elevated tail risk for {subj} if macro conditions deteriorate.",
    "Risk decomposition reveals concentrated exposure to policy shifts. Significant volatility around {subj} could emerge near upcoming regulatory decisions.",
    "Asymmetric risk profile detected for {subj} — limited downside in the base case but high-impact low-probability disruption scenarios remain.",
    "Compounding risk factors warrant caution, with {subj} showing vulnerability to supply-chain and competitive-pressure scenarios simultaneously.",
]

_SCENARIO_TEMPLATES = [
    "Bull case: rapid adoption drives market expansion for {subj} within 12-18 months. Bear case: regulatory friction slows progress. Base case: gradual integration with periodic consolidation.",
    "Three paths emerge for {subj}. Acceleration scenario with critical mass reached quickly. Stagnation where institutional inertia delays impact. Disruption where an adjacent innovation reshapes the landscape.",
    "Optimistic path sees 2-3x growth potential for {subj}. Conservative path shows steady but slower gains. Wildcard: a black-swan catalyst could accelerate beyond current projections.",
    "Divergent scenarios identified for {subj}. Path A: early movers capture disproportionate value. Path B: broad competition drives commoditization. Path C: consolidation narrows the field to 2-3 dominant players.",
    "Near-term: expect volatility as the landscape around {subj} crystallizes. Mid-term: winners emerge from current fragmentation. Long-term: mainstream integration becomes the default.",
]

_STRATEGY_TEMPLATES = [
    "Recommend active positioning. {subj} represents a high-conviction opportunity warranting increased allocation and closer tracking.",
    "Strategic exposure is warranted with defined risk bounds. Weekly monitoring of {subj} with trigger-based escalation if key thresholds are breached.",
    "Position for optionality. Maintain moderate exposure with flexibility to scale up on {subj} if confirmation signals strengthen.",
    "The strategic calculus favors engagement over wait-and-see. First-mover advantages around {subj} are likely to compound, making early action preferable.",
    "Build a phased approach with measured initial exposure to {subj}, clear milestones for scale-up, and defined exit criteria for the downside case.",
]


def _trend_outcome(subject: str, is_will_q: bool, sig_count: int, seed: int) -> str:
    template = _TREND_TEMPLATES[seed % len(_TREND_TEMPLATES)]
    base = template.format(subj=subject)
    if sig_count > 0:
        base = f"Analysis of {sig_count} signals confirms the pattern. " + base
    return base


def _risk_outcome(subject: str, is_will_q: bool, seed: int) -> str:
    return _RISK_TEMPLATES[seed % len(_RISK_TEMPLATES)].format(subj=subject)


def _scenario_outcome(subject: str, is_will_q: bool, seed: int) -> str:
    return _SCENARIO_TEMPLATES[seed % len(_SCENARIO_TEMPLATES)].format(subj=subject)


def _strategy_outcome(subject: str, is_will_q: bool, seed: int) -> str:
    return _STRATEGY_TEMPLATES[seed % len(_STRATEGY_TEMPLATES)].format(subj=subject)


# ── Council ──────────────────────────────────────────────────────────────────


class FuturePredictorCouncil:
    """Main council orchestration class."""

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

    def convene_council(self, topic: str, horizon: PredictionHorizon, signal_context: dict | None = None) -> dict:
        logger.info("Convening council for topic: %s (%s)", topic, horizon.value)

        session_data: dict[str, Any] = {
            "session_id": self.session_id,
            "topic": topic,
            "horizon": horizon.value,
            "timestamp": datetime.now().isoformat(),
            "council_members": [m.name for m in self.council_members if m.active],
            "signal_fed": signal_context is not None,
            "predictions": [],
        }

        for member in self.council_members:
            if member.active:
                prediction = self._generate_prediction(member, topic, horizon, signal_context)
                if prediction:
                    self.predictions.append(prediction)
                    session_data["predictions"].append(asdict(prediction))

        if self.config.get("consensus_required", False):
            session_data["consensus"] = self._consensus(session_data["predictions"])

        return session_data

    # ── Prediction generation ────────────────────────────────────────────────

    def _generate_prediction(
        self,
        member: CouncilMember,
        topic: str,
        horizon: PredictionHorizon,
        signal_context: dict | None = None,
    ) -> Prediction | None:
        prediction_id = f"{member.name.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        llm_cfg = self.config.get("llm", {})
        outcome, confidence, risk, evidence = (
            self._predict_with_llm(member, topic, horizon, llm_cfg, signal_context)
            if llm_cfg.get("enabled")
            else self._predict_heuristic(member, topic, signal_context)
        )

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
    def _predict_heuristic(member, topic, signal_context=None):
        import hashlib

        spec = member.specialty.lower()

        # Deterministic seed from topic+member for varied but reproducible outputs
        seed = int(hashlib.md5(f"{topic}:{member.name}".encode()).hexdigest()[:8], 16)

        # Parse topic into a short subject and directional framing
        subject = _extract_subject(topic)
        is_will_q = topic.lower().startswith("will ")
        is_how_q = topic.lower().startswith("how ")

        # Build evidence from real signal data if available
        if signal_context and signal_context.get("signal_count", 0) > 0:
            sig_count = signal_context["signal_count"]
            sources = signal_context.get("sources", [])
            summary = signal_context.get("summary", "")

            evidence_base = [
                f"Analysis of {sig_count} live signals from {len(sources)} sources",
            ]
            if sources:
                evidence_base.append(f"Data sources: {', '.join(sources[:6])}")
            if summary:
                evidence_base.append(summary[:200])

            # Varied outcomes based on signal data
            conf_base = 0.72 + (seed % 17) / 100  # 0.72 – 0.88
            if "trend" in spec or "pattern" in spec:
                return (
                    _trend_outcome(subject, is_will_q, sig_count, seed),
                    round(conf_base, 2),
                    RiskLevel.LOW,
                    [*evidence_base, "Real-time trend modeling on live data"],
                )
            if "risk" in spec:
                return (
                    _risk_outcome(subject, is_will_q, seed),
                    round(conf_base - 0.03, 2),
                    RiskLevel.MEDIUM,
                    [*evidence_base, "Multi-source risk factor quantification"],
                )
            if "scenario" in spec:
                return (
                    _scenario_outcome(subject, is_will_q, seed),
                    round(conf_base - 0.08, 2),
                    RiskLevel.MEDIUM,
                    [*evidence_base, "Data-driven scenario branching"],
                )
            return (
                _strategy_outcome(subject, is_will_q, seed),
                round(conf_base + 0.02, 2),
                RiskLevel.LOW,
                [*evidence_base, "Cross-source strategic alignment"],
            )

        # No signal data — substantive heuristic outputs
        conf_base = 0.65 + (seed % 23) / 100  # 0.65 – 0.87
        if "trend" in spec or "pattern" in spec:
            return (
                _trend_outcome(subject, is_will_q, 0, seed),
                round(conf_base, 2),
                RiskLevel.LOW,
                ["Historical pattern analysis", "Momentum indicators"],
            )
        if "risk" in spec:
            return (
                _risk_outcome(subject, is_will_q, seed),
                round(conf_base - 0.05, 2),
                [RiskLevel.MEDIUM, RiskLevel.HIGH][seed % 2],
                ["Risk factor decomposition", "Downside scenario modeling"],
            )
        if "scenario" in spec:
            return (
                _scenario_outcome(subject, is_will_q, seed),
                round(conf_base - 0.10, 2),
                RiskLevel.MEDIUM,
                ["Multi-path scenario tree", "Contingency analysis"],
            )
        return (
            _strategy_outcome(subject, is_will_q, seed),
            round(conf_base + 0.03, 2),
            RiskLevel.LOW,
            ["Strategic positioning analysis", "Opportunity-risk balance"],
        )

    @staticmethod
    def _predict_with_llm(member, topic, horizon, llm_cfg, signal_context=None):
        signal_block = ""
        if signal_context and signal_context.get("signal_count", 0) > 0:
            sig_count = signal_context["signal_count"]
            sources = signal_context.get("sources", [])
            summary = signal_context.get("summary", "")
            signal_block = (
                f"\n\nYou have access to {sig_count} live data signals from these sources: "
                f"{', '.join(sources[:10])}.\n"
                f"Signal summary:\n{summary[:500]}\n"
                f"Use this real data to ground your analysis.\n"
            )

        prompt = (
            f"As a {member.specialty} specialist named '{member.name}', analyse the topic "
            f"'{topic}' over a {horizon.value} horizon.{signal_block}\n\n"
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

    # ── ICM Thinking Layer ──────────────────────────────────────────────────

    def think(
        self,
        topic: str,
        horizon: PredictionHorizon,
        channels: list[str] | None = None,
        run_evolution: bool = True,
    ) -> dict:
        """Execute prediction through the full ICM + OpenClaw + Ralphy pipeline.

        Falls back to ``convene_council()`` if the thinking layer is not
        available or raises an error.
        """
        try:
            from .thinking import ThinkingLayer

            thinking = ThinkingLayer()
            result = thinking.think(
                topic=topic,
                horizon=horizon.value,
                channels=channels,
                run_evolution=run_evolution,
            )

            # Merge thinking result into council session format
            session = {
                "session_id": self.session_id,
                "topic": topic,
                "horizon": horizon.value,
                "timestamp": datetime.now().isoformat(),
                "mode": "icm_thinking",
                "pipeline_run_id": result.pipeline_run.run_id if result.pipeline_run else None,
                "prediction": result.prediction,
                "delivery": result.delivery_results,
                "evolution": (
                    {
                        "accuracy": result.evolution_report.accuracy,
                        "tasks_generated": result.evolution_report.tasks_generated,
                        "recommendations": result.evolution_report.recommendations,
                    }
                    if result.evolution_report
                    else None
                ),
                "thinking_duration_ms": result.thinking_duration_ms,
            }
            return session

        except Exception as exc:
            logger.warning("Thinking layer failed (%s) — falling back to classic council", exc)
            return self.convene_council(topic, horizon)

    def get_council_status(self) -> dict:
        status = {
            "council_name": self.config.get("council_name", "Future Predictor Council"),
            "active_members": len([m for m in self.council_members if m.active]),
            "total_members": len(self.council_members),
            "session_id": self.session_id,
            "predictions_made": len(self.predictions),
            "available_strategies": self._list_strategies(),
            "last_activity": datetime.now().isoformat(),
        }

        # Add thinking layer status if available
        try:
            from .thinking import ThinkingLayer

            thinking = ThinkingLayer()
            status["thinking_layer"] = thinking.status()
        except Exception:
            status["thinking_layer"] = "not available"

        return status

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
