"""Future Predictor Council - ensemble forecast engine."""

import json
import logging
import math
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from ..ncl_brain.models import InsightSignal

logger = logging.getLogger(__name__)


class PredictionOutput:
    """Output from ensemble prediction."""

    def __init__(self) -> None:
        """Initialize prediction output."""
        self.prediction_id: str = str(uuid.uuid4())
        self.timestamp: datetime = datetime.now(timezone.utc)
        self.topic: str = ""
        self.consensus_prediction: Optional[str] = None
        self.confidence: float = 0.0
        self.component_predictions: dict[str, dict[str, str | float]] = {}
        self.convergence_signals: list[str] = []
        self.warnings: list[str] = []


def _compute_model_confidence(
    signals: list,
    response_text: str,
    base: float = 0.5,
) -> float:
    """
    Compute a confidence score from data quality and response characteristics.

    Factors:
    - Signal count: more signals = more data to ground the prediction
    - Average signal importance: higher importance = stronger evidence base
    - Response includes explicit probability: boosts confidence
    - Caps at 0.95 to avoid overconfidence.

    Args:
        signals: The InsightSignal objects used for the prediction.
        response_text: The raw model response text.
        base: Model-specific baseline (Claude = 0.6, local = 0.45).

    Returns:
        Confidence score in [0.0, 0.95].
    """
    score = base

    # Signal quantity bonus (up to +0.15 for 10+ signals)
    n = len(signals)
    if n > 0:
        score += min(0.15, 0.015 * n)

    # Signal quality bonus: average importance (0-100 scale assumed)
    if signals:
        avg_importance = sum(
            getattr(s, "importance_score", 0)
            for s in signals
        ) / len(signals)
        # Normalise to 0-0.10 bonus
        score += min(0.10, avg_importance / 100)

    # Explicitness bonus: response contains a numeric probability
    import re
    if re.search(r"\b(\d{1,3})\s*(?:–|-|to)\s*(\d{1,3})\s*%", response_text):
        score += 0.05  # Model gave a probability range
    elif re.search(r"\b\d{1,3}\s*%", response_text):
        score += 0.02  # At least one percentage mentioned

    return round(min(0.95, max(0.0, score)), 3)


class FuturePredictor:
    """
    Ensemble prediction system.

    Ingests signals from Awarebot scanner and runs multi-model predictions.
    Detects convergence when multiple sources agree.
    Integrates with AAC War Room for geopolitical signals.
    """

    # Rolling accuracy window: last N prediction outcomes
    _ACCURACY_WINDOW = 100

    def __init__(
        self,
        claude_api_key: str,
        anthropic_base_url: str = "https://api.anthropic.com",
        ollama_host: str = "localhost:11434",
        aac_war_room_url: Optional[str] = None,
        accuracy_file: Optional[Path] = None,
    ) -> None:
        """
        Initialize future predictor.

        Args:
            claude_api_key: Anthropic API key for Claude
            anthropic_base_url: Anthropic API base URL
            ollama_host: Ollama server host:port for local models
            aac_war_room_url: AAC War Room API URL for geopolitical data
            accuracy_file: Optional path to persist prediction outcomes (JSON lines)
        """
        self.claude_api_key = claude_api_key
        self.anthropic_base_url = anthropic_base_url
        self.ollama_host = ollama_host
        self.aac_war_room_url = aac_war_room_url
        self.http_client = httpx.AsyncClient(timeout=60.0)

        # Accuracy tracking — rolling deque of {"prediction_id": ..., "correct": bool}
        self._outcomes: deque[dict] = deque(maxlen=self._ACCURACY_WINDOW)
        self._accuracy_file = accuracy_file

        # Load persisted outcomes from disk
        if self._accuracy_file and self._accuracy_file.exists():
            try:
                lines = self._accuracy_file.read_text().strip().splitlines()
                for line in lines[-self._ACCURACY_WINDOW:]:
                    self._outcomes.append(json.loads(line))
            except Exception:
                pass  # Start fresh on any parse error

    async def predict(
        self, signals: list[InsightSignal], topic: str
    ) -> PredictionOutput:
        """
        Run ensemble prediction on signals.

        Args:
            signals: List of InsightSignals to analyze
            topic: Prediction topic

        Returns:
            PredictionOutput with consensus and confidence
        """
        output = PredictionOutput()
        output.topic = topic

        # Filter high-importance signals
        high_importance = [s for s in signals if s.importance_score >= 50.0]
        if not high_importance:
            high_importance = signals

        # Run predictions across ensemble
        predictions = {}

        # Claude strategic analysis
        claude_pred = await self._predict_claude(high_importance, topic)
        predictions["claude"] = claude_pred

        # Local model (qwen3:32b) - technical/data analysis
        qwen_pred = await self._predict_ollama(high_importance, topic, "qwen3:32b")
        predictions["qwen"] = qwen_pred

        # Local model (deepseek-coder) - edge case detection
        deepseek_pred = await self._predict_ollama(
            high_importance, topic, "deepseek-coder-v2:16b"
        )
        predictions["deepseek"] = deepseek_pred

        output.component_predictions = predictions

        # Detect convergence
        convergence = self._detect_convergence(predictions)
        output.convergence_signals = convergence

        # Build consensus
        output.consensus_prediction = self._synthesize_consensus(predictions)
        output.confidence = self._compute_confidence(predictions, convergence)

        # Query AAC War Room if geopolitical signals present
        if any("geopolitical" in s.tags or "conflict" in s.tags for s in high_importance):
            war_room_data = await self._query_war_room(high_importance, topic)
            if war_room_data:
                output.warnings.append(f"War Room signal: {war_room_data}")

        return output

    async def _predict_claude(
        self, signals: list[InsightSignal], topic: str
    ) -> dict[str, str | float | None]:
        """
        Get strategic prediction from Claude.

        Args:
            signals: List of signals
            topic: Prediction topic

        Returns:
            Prediction with confidence
        """
        signals_text = "\n".join(
            [f"- {s.content[:100]} (importance: {s.importance_score:.1f})" for s in signals[:5]]
        )

        prompt = f"""Given these intelligence signals about {topic}:

{signals_text}

Provide a brief prediction (2-3 sentences) about likely outcomes in the next 30 days.
Be specific about probability ranges (e.g., 60-70% likely).
Format your response as JSON with keys: prediction, confidence (0-1), reasoning."""

        try:
            response = await self.http_client.post(
                f"{self.anthropic_base_url}/v1/messages",
                headers={
                    "x-api-key": self.claude_api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 512,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            data = response.json()
            text = data["content"][0]["text"]

            # Compute confidence from data quality: signal count, avg importance,
            # and whether the model returned structured probability ranges.
            confidence = _compute_model_confidence(
                signals=signals,
                response_text=text,
                base=0.6,
            )
            return {
                "model": "claude",
                "prediction": text,
                "confidence": confidence,
            }
        except Exception as e:
            logger.warning(f"Claude prediction failed for topic '{topic}': {e}")
            return {
                "model": "claude",
                "prediction": "Unable to generate prediction",
                "confidence": 0.0,
                "error": str(e),
            }

    async def _predict_ollama(
        self, signals: list[InsightSignal], topic: str, model: str
    ) -> dict[str, str | float | None]:
        """
        Get prediction from local Ollama model.

        Args:
            signals: List of signals
            topic: Prediction topic
            model: Model name (qwen3:32b, deepseek-coder-v2:16b)

        Returns:
            Prediction with confidence
        """
        signals_text = "\n".join(
            [f"- {s.content[:100]}" for s in signals[:5]]
        )

        prompt = f"""Analyze these signals about {topic}:
{signals_text}

What is the most likely outcome? Provide 1-2 sentences."""

        try:
            response = await self.http_client.post(
                f"http://{self.ollama_host}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                },
            )
            response.raise_for_status()
            data = response.json()

            response_text = data.get("response", "")[:200]
            confidence = _compute_model_confidence(
                signals=signals,
                response_text=response_text,
                base=0.45,  # Local models get lower base than Claude
            )
            return {
                "model": model,
                "prediction": response_text,
                "confidence": confidence,
            }
        except Exception as e:
            logger.warning(f"Ollama prediction failed with model '{model}' for topic '{topic}': {e}")
            return {
                "model": model,
                "prediction": "Unable to generate prediction",
                "confidence": 0.0,
                "error": str(e),
            }

    def _detect_convergence(self, predictions: dict[str, dict[str, str | float]]) -> list[str]:
        """
        Detect convergence when multiple models agree.

        Args:
            predictions: Dict of model predictions

        Returns:
            List of convergence signals
        """
        convergence_signals = []

        # Simple heuristic: if multiple models have high confidence
        high_confidence_count = sum(
            1 for p in predictions.values()
            if isinstance(p.get("confidence"), float) and p.get("confidence") >= 0.7
        )

        if high_confidence_count >= 2:
            convergence_signals.append(
                f"Strong convergence: {high_confidence_count} models have high confidence"
            )

        return convergence_signals

    def _synthesize_consensus(
        self, predictions: dict[str, dict[str, str | float]]
    ) -> str:
        """
        Synthesize consensus from multiple predictions using weighted voting.

        Weights models by confidence, extracts key phrases, and builds
        a composite prediction that represents multi-model agreement.
        Integrates with Paperclip cost tracking via prediction events.

        Args:
            predictions: Dict of model predictions

        Returns:
            Weighted consensus prediction
        """
        # Filter out failed predictions
        valid = {
            k: v for k, v in predictions.items()
            if v.get("prediction") and v.get("confidence", 0) > 0
            and "Unable to generate" not in str(v.get("prediction", ""))
        }

        if not valid:
            return "Inconclusive — all models failed to generate predictions"

        if len(valid) == 1:
            sole = list(valid.values())[0]
            return f"[Single-model] {sole.get('prediction', '')}"

        # Weight by confidence (higher confidence = more influence)
        total_confidence = sum(v.get("confidence", 0.5) for v in valid.values())

        # Build weighted composite
        parts = []
        model_weights = {}
        for model_name, pred in valid.items():
            conf = pred.get("confidence", 0.5)
            weight = conf / total_confidence if total_confidence > 0 else 1.0 / len(valid)
            model_weights[model_name] = weight
            parts.append({
                "model": model_name,
                "prediction": str(pred.get("prediction", "")),
                "weight": weight,
                "confidence": conf,
            })

        # Sort by weight descending — lead with highest-confidence model
        parts.sort(key=lambda x: x["weight"], reverse=True)

        # Extract key terms from all predictions for convergence detection
        all_text = " ".join(p["prediction"].lower() for p in parts)
        # Simple keyword extraction: words that appear in multiple predictions
        word_counts: dict[str, int] = {}
        for part in parts:
            seen = set()
            for word in part["prediction"].lower().split():
                word = word.strip(".,;:!?()[]{}\"'")
                if len(word) > 4 and word not in seen:
                    word_counts[word] = word_counts.get(word, 0) + 1
                    seen.add(word)
        shared_terms = [w for w, c in word_counts.items() if c >= 2]

        # Build synthesis
        lead = parts[0]
        synthesis = f"[Consensus: {len(valid)} models, "
        synthesis += f"lead={lead['model']}@{lead['confidence']:.0%}] "
        synthesis += lead["prediction"]

        if len(parts) > 1:
            supporting = parts[1:]
            divergences = []
            for s in supporting:
                # Check if supporting model broadly agrees or diverges
                if s["confidence"] >= 0.5:
                    synthesis += f" [{s['model']} concurs@{s['confidence']:.0%}]"
                else:
                    divergences.append(f"{s['model']}@{s['confidence']:.0%}")

            if divergences:
                synthesis += f" [Divergence: {', '.join(divergences)}]"

        if shared_terms:
            synthesis += f" [Converging themes: {', '.join(shared_terms[:5])}]"

        return synthesis

    def _compute_confidence(
        self, predictions: dict[str, dict[str, str | float]], convergence: list[str]
    ) -> float:
        """
        Compute overall confidence in prediction.

        Args:
            predictions: Dict of model predictions
            convergence: List of convergence signals

        Returns:
            Confidence score 0-1
        """
        confidences = [
            p.get("confidence", 0.0)
            for p in predictions.values()
            if isinstance(p.get("confidence"), float)
        ]

        base_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        # Boost if convergence detected
        if convergence:
            base_confidence = min(1.0, base_confidence * 1.1)

        return base_confidence

    async def _query_war_room(
        self, signals: list[InsightSignal], topic: str
    ) -> Optional[str]:
        """
        Query AAC War Room for geopolitical signals.

        Args:
            signals: List of signals
            topic: Prediction topic

        Returns:
            War room data or None
        """
        if not self.aac_war_room_url:
            return None

        try:
            # Serialize signals to a compact form the War Room endpoint can consume
            signals_payload = [
                {
                    "content": s.content[:200],
                    "importance": getattr(s, "importance_score", 0),
                    "tags": list(getattr(s, "tags", [])),
                }
                for s in signals[:20]  # Cap at 20 to keep payload reasonable
            ]
            response = await self.http_client.post(
                f"{self.aac_war_room_url}/geopolitical/signals",
                json={
                    "topic": topic,
                    "signals": signals_payload,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("summary", None)
        except Exception as e:
            logger.warning(f"War room query failed for topic '{topic}': {e}")
            return None

    # ── Accuracy Tracking ────────────────────────────────────────────────

    def record_outcome(self, prediction_id: str, correct: bool) -> None:
        """
        Record whether a prediction was correct.

        Call this once the ground truth is known (e.g. 30 days after prediction).

        Args:
            prediction_id: The PredictionOutput.prediction_id value.
            correct: True if the prediction proved accurate.
        """
        record = {
            "prediction_id": prediction_id,
            "correct": correct,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        self._outcomes.append(record)

        if self._accuracy_file:
            try:
                self._accuracy_file.parent.mkdir(parents=True, exist_ok=True)
                with self._accuracy_file.open("a") as f:
                    f.write(json.dumps(record) + "\n")
            except Exception as e:
                logger.warning(f"Failed to persist prediction outcome: {e}")

    def rolling_accuracy(self) -> Optional[float]:
        """
        Compute rolling accuracy over the last N recorded outcomes.

        Returns:
            Fraction correct (0.0–1.0), or None if no outcomes recorded.
        """
        if not self._outcomes:
            return None
        correct = sum(1 for o in self._outcomes if o.get("correct"))
        return round(correct / len(self._outcomes), 3)

    def accuracy_stats(self) -> dict:
        """Return accuracy stats dict for logging/reporting."""
        acc = self.rolling_accuracy()
        return {
            "outcomes_recorded": len(self._outcomes),
            "rolling_accuracy": acc,
            "window_size": self._ACCURACY_WINDOW,
        }

    async def close(self) -> None:
        """Close HTTP client."""
        await self.http_client.aclose()
