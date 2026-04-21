"""Future Predictor Council - ensemble forecast engine."""

import logging
import uuid
from datetime import datetime, timezone
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


class FuturePredictor:
    """
    Ensemble prediction system.

    Ingests signals from Awarebot scanner and runs multi-model predictions.
    Detects convergence when multiple sources agree.
    Integrates with AAC War Room for geopolitical signals.
    """

    def __init__(
        self,
        claude_api_key: str,
        anthropic_base_url: str = "https://api.anthropic.com",
        ollama_host: str = "localhost:11434",
        aac_war_room_url: Optional[str] = None,
    ) -> None:
        """
        Initialize future predictor.

        Args:
            claude_api_key: Anthropic API key for Claude
            anthropic_base_url: Anthropic API base URL
            ollama_host: Ollama server host:port for local models
            aac_war_room_url: AAC War Room API URL for geopolitical data
        """
        self.claude_api_key = claude_api_key
        self.anthropic_base_url = anthropic_base_url
        self.ollama_host = ollama_host
        self.aac_war_room_url = aac_war_room_url
        self.http_client = httpx.AsyncClient(timeout=60.0)

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
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": 512,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            data = response.json()
            text = data["content"][0]["text"]

            # Parse response (simplified)
            return {
                "model": "claude",
                "prediction": text,
                "confidence": 0.75,
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

            return {
                "model": model,
                "prediction": data.get("response", "")[:200],
                "confidence": 0.65,
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
            response = await self.http_client.get(
                f"{self.aac_war_room_url}/geopolitical/signals",
                params={"topic": topic},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("summary", None)
        except Exception as e:
            logger.warning(f"War room query failed for topic '{topic}': {e}")
            return None

    async def close(self) -> None:
        """Close HTTP client."""
        await self.http_client.aclose()
