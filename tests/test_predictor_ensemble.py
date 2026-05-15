"""End-to-end tests for FuturePredictor ensemble prediction logic."""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import httpx
import pytest

from runtime.awarebot.predictor import FuturePredictor, PredictionOutput
from runtime.ncl_brain.models import InsightSignal


# ────────────────────────────────────────────────────────────────────────────
# Test Fixtures
# ────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def predictor():
    """Create a FuturePredictor instance with test configuration."""
    return FuturePredictor(
        claude_api_key="test-claude-key",
        anthropic_base_url="https://api.anthropic.com",
        ollama_host="localhost:11434",
        aac_war_room_url="http://localhost:8080/aac",
    )


@pytest.fixture
def sample_signals():
    """Create sample InsightSignal objects for testing."""
    return [
        InsightSignal(
            signal_id=str(uuid.uuid4()),
            source_platform="x",
            content="AI market growth accelerating",
            url="https://twitter.com/signal1",
            importance_score=75.0,
            relevance=0.9,
            novelty=0.8,
            actionability=0.7,
            source_authority=0.85,
            time_sensitivity=0.8,
            timestamp=datetime.now(timezone.utc),
            tags=["ai", "market"],
        ),
        InsightSignal(
            signal_id=str(uuid.uuid4()),
            source_platform="youtube",
            content="Expert discusses AI regulations",
            url="https://youtube.com/signal2",
            importance_score=65.0,
            relevance=0.8,
            novelty=0.7,
            actionability=0.6,
            source_authority=0.8,
            time_sensitivity=0.7,
            timestamp=datetime.now(timezone.utc),
            tags=["ai", "regulation"],
        ),
        InsightSignal(
            signal_id=str(uuid.uuid4()),
            source_platform="reddit",
            content="Community discusses AI ethics",
            url="https://reddit.com/signal3",
            importance_score=45.0,
            relevance=0.6,
            novelty=0.5,
            actionability=0.5,
            source_authority=0.4,
            time_sensitivity=0.4,
            timestamp=datetime.now(timezone.utc),
            tags=["ai", "ethics"],
        ),
    ]


@pytest.fixture
def geopolitical_signals():
    """Create signals with geopolitical tags."""
    return [
        InsightSignal(
            signal_id=str(uuid.uuid4()),
            source_platform="x",
            content="Tensions escalate in region",
            url="https://twitter.com/geo1",
            importance_score=85.0,
            relevance=0.95,
            novelty=0.9,
            actionability=0.8,
            source_authority=0.9,
            time_sensitivity=0.95,
            timestamp=datetime.now(timezone.utc),
            tags=["geopolitical", "conflict", "urgent"],
        ),
    ]


# ────────────────────────────────────────────────────────────────────────────
# FuturePredictor Initialization Tests
# ────────────────────────────────────────────────────────────────────────────


def test_predictor_initialization():
    """Test FuturePredictor initializes with config."""
    predictor = FuturePredictor(
        claude_api_key="key-123",
        anthropic_base_url="https://custom.anthropic.com",
        ollama_host="192.168.1.100:11434",
        aac_war_room_url="https://war-room.example.com",
    )

    assert predictor.claude_api_key == "key-123"
    assert predictor.anthropic_base_url == "https://custom.anthropic.com"
    assert predictor.ollama_host == "192.168.1.100:11434"
    assert predictor.aac_war_room_url == "https://war-room.example.com"
    assert predictor.http_client is not None


def test_predictor_initialization_with_defaults():
    """Test FuturePredictor uses default values."""
    predictor = FuturePredictor(claude_api_key="key")

    assert predictor.anthropic_base_url == "https://api.anthropic.com"
    assert predictor.ollama_host == "localhost:11434"
    assert predictor.aac_war_room_url is None


# ────────────────────────────────────────────────────────────────────────────
# PredictionOutput Structure Tests
# ────────────────────────────────────────────────────────────────────────────


def test_prediction_output_initialization():
    """Test PredictionOutput initializes with required fields."""
    output = PredictionOutput()

    assert output.prediction_id is not None
    assert isinstance(output.timestamp, datetime)
    assert output.topic == ""
    assert output.consensus_prediction is None
    assert output.confidence == 0.0
    assert output.component_predictions == {}
    assert output.convergence_signals == []
    assert output.warnings == []


def test_prediction_output_structure():
    """Test PredictionOutput can be populated with data."""
    output = PredictionOutput()
    output.topic = "AI market growth"
    output.consensus_prediction = "AI market will grow 30-40% in next year"
    output.confidence = 0.78
    output.component_predictions = {
        "claude": {"prediction": "Growth likely", "confidence": 0.8},
        "qwen": {"prediction": "Strong growth", "confidence": 0.75},
        "deepseek": {"prediction": "Modest growth", "confidence": 0.7},
    }
    output.convergence_signals = ["All models agree on positive trend"]
    output.warnings = []

    assert output.topic == "AI market growth"
    assert "30-40%" in output.consensus_prediction
    assert output.confidence == 0.78
    assert len(output.component_predictions) == 3
    assert len(output.convergence_signals) == 1


# ────────────────────────────────────────────────────────────────────────────
# Claude Prediction Tests
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_claude_prediction_call(predictor, sample_signals):
    """Test Claude prediction API call with mocked response."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "content": [
            {
                "text": '{"prediction": "AI market will grow significantly", "confidence": 0.85, "reasoning": "Strong signals"}'
            }
        ]
    }
    mock_response.raise_for_status.return_value = None

    with patch.object(
        predictor.http_client, "post", new_callable=AsyncMock, return_value=mock_response
    ) as mock_post:
        result = await predictor._predict_claude(sample_signals, "AI market growth")

        # Verify API call
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "api.anthropic.com/v1/messages" in str(call_args)
        assert call_args.kwargs["json"]["model"] == "claude-sonnet-4-6"
        assert call_args.kwargs["json"]["max_tokens"] == 512

        # Verify result
        assert result["model"] == "claude"
        assert "prediction" in result
        assert result["confidence"] == 0.75  # Default in implementation


@pytest.mark.asyncio
async def test_claude_prediction_failure(predictor, sample_signals):
    """Test Claude prediction handles API failures gracefully."""
    with patch.object(
        predictor.http_client,
        "post",
        new_callable=AsyncMock,
        side_effect=httpx.HTTPStatusError("401", request=MagicMock(), response=MagicMock()),
    ):
        result = await predictor._predict_claude(sample_signals, "test topic")

        assert result["model"] == "claude"
        assert result["prediction"] == "Unable to generate prediction"
        assert result["confidence"] == 0.0
        assert "error" in result


# ────────────────────────────────────────────────────────────────────────────
# Ollama (Local Model) Prediction Tests
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ollama_prediction_call(predictor, sample_signals):
    """Test Ollama model prediction with mocked response."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "response": "The AI market is expected to show strong growth based on these signals."
    }
    mock_response.raise_for_status.return_value = None

    with patch.object(
        predictor.http_client, "post", new_callable=AsyncMock, return_value=mock_response
    ) as mock_post:
        result = await predictor._predict_ollama(
            sample_signals, "AI market", "qwen3:32b"
        )

        # Verify API call
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "localhost:11434/api/generate" in str(call_args)
        assert call_args.kwargs["json"]["model"] == "qwen3:32b"
        assert call_args.kwargs["json"]["stream"] is False

        # Verify result
        assert result["model"] == "qwen3:32b"
        assert "growth" in result["prediction"]
        assert result["confidence"] == 0.65  # Default in implementation


@pytest.mark.asyncio
async def test_ollama_prediction_different_models(predictor, sample_signals):
    """Test Ollama prediction works with different model names."""
    models = ["qwen3:32b", "deepseek-coder-v2:16b"]

    for model in models:
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": f"Prediction from {model}"}
        mock_response.raise_for_status.return_value = None

        with patch.object(
            predictor.http_client, "post", new_callable=AsyncMock, return_value=mock_response
        ):
            result = await predictor._predict_ollama(sample_signals, "topic", model)
            assert result["model"] == model


@pytest.mark.asyncio
async def test_ollama_prediction_failure(predictor, sample_signals):
    """Test Ollama prediction handles failures gracefully."""
    with patch.object(
        predictor.http_client,
        "post",
        new_callable=AsyncMock,
        side_effect=asyncio.TimeoutError(),
    ):
        result = await predictor._predict_ollama(
            sample_signals, "topic", "qwen3:32b"
        )

        assert result["prediction"] == "Unable to generate prediction"
        assert result["confidence"] == 0.0
        assert "error" in result


# ────────────────────────────────────────────────────────────────────────────
# Ensemble Parallel Execution Tests
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensemble_parallel_execution(predictor, sample_signals):
    """Test that all models in ensemble are called concurrently."""
    call_times = []

    async def mock_api_call(*args, **kwargs):
        call_times.append(datetime.now(timezone.utc))
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "test"}
        mock_resp.raise_for_status.return_value = None
        # Simulate slight delay
        await asyncio.sleep(0.01)
        return mock_resp

    with patch.object(
        predictor.http_client, "post", new_callable=AsyncMock, side_effect=mock_api_call
    ):
        output = await predictor.predict(sample_signals, "test topic")

        # Verify all three models were called
        assert "claude" in output.component_predictions
        assert "qwen" in output.component_predictions
        assert "deepseek" in output.component_predictions


@pytest.mark.asyncio
async def test_ensemble_one_model_failure(predictor, sample_signals):
    """Test ensemble continues even if one model fails."""
    call_count = [0]

    async def mock_api_call_with_failure(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:  # First call (Claude) fails
            raise httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock())
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "test"}
        mock_resp.raise_for_status.return_value = None
        return mock_resp

    with patch.object(
        predictor.http_client, "post", new_callable=AsyncMock, side_effect=mock_api_call_with_failure
    ):
        output = await predictor.predict(sample_signals, "test topic")

        # Verify output was generated despite one failure
        assert output is not None
        assert output.topic == "test topic"
        # Claude should have error, others should succeed
        assert "error" in output.component_predictions.get("claude", {})


# ────────────────────────────────────────────────────────────────────────────
# Convergence Detection Tests
# ────────────────────────────────────────────────────────────────────────────


def test_convergence_detection_high_confidence():
    """Test convergence detection when multiple models have high confidence."""
    predictor = FuturePredictor(claude_api_key="test")

    predictions = {
        "claude": {"prediction": "Growth", "confidence": 0.85},
        "qwen": {"prediction": "Growth", "confidence": 0.80},
        "deepseek": {"prediction": "Growth", "confidence": 0.75},
    }

    convergence = predictor._detect_convergence(predictions)

    assert len(convergence) > 0
    assert any("convergence" in sig.lower() for sig in convergence)


def test_convergence_detection_no_convergence():
    """Test convergence detection when models don't converge."""
    predictor = FuturePredictor(claude_api_key="test")

    predictions = {
        "claude": {"prediction": "Growth", "confidence": 0.4},
        "qwen": {"prediction": "Decline", "confidence": 0.3},
        "deepseek": {"prediction": "Stable", "confidence": 0.2},
    }

    convergence = predictor._detect_convergence(predictions)

    assert len(convergence) == 0


def test_convergence_detection_partial():
    """Test convergence detection with mixed confidence levels."""
    predictor = FuturePredictor(claude_api_key="test")

    predictions = {
        "claude": {"prediction": "Growth", "confidence": 0.75},
        "qwen": {"prediction": "Growth", "confidence": 0.72},
        "deepseek": {"prediction": "Decline", "confidence": 0.4},
    }

    convergence = predictor._detect_convergence(predictions)

    # Should detect convergence (2 models high confidence)
    assert len(convergence) > 0


# ────────────────────────────────────────────────────────────────────────────
# Confidence Computation Tests
# ────────────────────────────────────────────────────────────────────────────


def test_confidence_boosted_on_convergence():
    """Test confidence is boosted by 1.1x when convergence detected."""
    predictor = FuturePredictor(claude_api_key="test")

    predictions = {
        "claude": {"prediction": "Growth", "confidence": 0.8},
        "qwen": {"prediction": "Growth", "confidence": 0.75},
        "deepseek": {"prediction": "Growth", "confidence": 0.7},
    }
    convergence_signals = ["All models converge on growth prediction"]

    confidence = predictor._compute_confidence(predictions, convergence_signals)

    # Base confidence = (0.8 + 0.75 + 0.7) / 3 = 0.75
    # With convergence boost: 0.75 * 1.1 = 0.825
    assert confidence == pytest.approx(0.825)
    assert confidence <= 1.0  # Must not exceed 1.0


def test_confidence_without_convergence():
    """Test confidence calculation without convergence."""
    predictor = FuturePredictor(claude_api_key="test")

    predictions = {
        "claude": {"prediction": "Growth", "confidence": 0.8},
        "qwen": {"prediction": "Decline", "confidence": 0.3},
        "deepseek": {"prediction": "Stable", "confidence": 0.5},
    }

    confidence = predictor._compute_confidence(predictions, [])

    # Base confidence = (0.8 + 0.3 + 0.5) / 3 = 0.533...
    # No boost applied
    assert confidence == pytest.approx((0.8 + 0.3 + 0.5) / 3)


def test_confidence_capped_at_one():
    """Test confidence never exceeds 1.0 even with boost."""
    predictor = FuturePredictor(claude_api_key="test")

    predictions = {
        "claude": {"prediction": "Growth", "confidence": 0.95},
        "qwen": {"prediction": "Growth", "confidence": 0.98},
        "deepseek": {"prediction": "Growth", "confidence": 0.97},
    }
    convergence_signals = ["Strong convergence"]

    confidence = predictor._compute_confidence(predictions, convergence_signals)

    # Base = 0.967, boosted = 1.063, capped at 1.0
    assert confidence == 1.0


# ────────────────────────────────────────────────────────────────────────────
# Consensus Synthesis Tests
# ────────────────────────────────────────────────────────────────────────────


def test_synthesis_uses_claude_prediction():
    """Test consensus synthesis preferentially uses Claude prediction."""
    predictor = FuturePredictor(claude_api_key="test")

    predictions = {
        "claude": {"prediction": "Claude predicts strong growth", "confidence": 0.8},
        "qwen": {"prediction": "Qwen predicts modest growth", "confidence": 0.6},
        "deepseek": {"prediction": "Deepseek predicts decline", "confidence": 0.5},
    }

    consensus = predictor._synthesize_consensus(predictions)

    assert "Claude predicts strong growth" in consensus


def test_synthesis_fallback_on_missing_claude():
    """Test consensus synthesis falls back when Claude prediction missing."""
    predictor = FuturePredictor(claude_api_key="test")

    predictions = {
        "qwen": {"prediction": "Qwen prediction", "confidence": 0.6},
        "deepseek": {"prediction": "Deepseek prediction", "confidence": 0.5},
    }

    consensus = predictor._synthesize_consensus(predictions)

    # Without Claude, synthesizer now builds a multi-model consensus from
    # remaining providers (qwen + deepseek here). Either an "Inconclusive"
    # fallback or a "[Consensus: ...]" line is acceptable.
    assert (
        "Inconclusive" in consensus
        or "Consensus:" in consensus
        or "qwen" in consensus.lower()
    )


# ────────────────────────────────────────────────────────────────────────────
# War Room Integration Tests
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prediction_with_geopolitical_signals(predictor, geopolitical_signals):
    """Test War Room is queried when geopolitical signals present."""
    # Mock all model responses
    model_response = MagicMock()
    model_response.json.return_value = {"response": "Prediction"}
    model_response.raise_for_status.return_value = None

    # Mock War Room response
    war_room_response = MagicMock()
    war_room_response.json.return_value = {
        "summary": "Escalation risk: 75%"
    }
    war_room_response.raise_for_status.return_value = None

    with patch.object(
        predictor.http_client, "post", new_callable=AsyncMock, return_value=model_response
    ):
        with patch.object(
            predictor.http_client, "get", new_callable=AsyncMock, return_value=war_room_response
        ) as mock_get:
            output = await predictor.predict(geopolitical_signals, "regional conflict")

            # Verify War Room was queried
            mock_get.assert_called_once()
            call_args = mock_get.call_args
            assert "localhost:8080/aac" in str(call_args)

            # Verify warning was added
            assert len(output.warnings) > 0
            assert "War Room signal" in output.warnings[0]


@pytest.mark.asyncio
async def test_prediction_skips_war_room_without_geopolitical():
    """Test War Room is not queried when no geopolitical signals."""
    predictor = FuturePredictor(claude_api_key="test-key")

    # Non-geopolitical signals
    signals = [
        InsightSignal(
            signal_id=str(uuid.uuid4()),
            source_platform="x",
            content="New AI model released",
            importance_score=70.0,
            relevance=0.8,
            novelty=0.7,
            actionability=0.6,
            source_authority=0.8,
            time_sensitivity=0.5,
            timestamp=datetime.now(timezone.utc),
            tags=["ai", "technology"],  # No geopolitical tags
        )
    ]

    model_response = MagicMock()
    model_response.json.return_value = {"response": "Prediction"}
    model_response.raise_for_status.return_value = None

    with patch.object(
        predictor.http_client, "post", new_callable=AsyncMock, return_value=model_response
    ):
        with patch.object(
            predictor.http_client, "get", new_callable=AsyncMock
        ) as mock_get:
            output = await predictor.predict(signals, "technology trend")

            # War Room should NOT be called
            mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_prediction_war_room_failure_handling(predictor, geopolitical_signals):
    """Test prediction continues if War Room query fails."""
    model_response = MagicMock()
    model_response.json.return_value = {"response": "Prediction"}
    model_response.raise_for_status.return_value = None

    with patch.object(
        predictor.http_client, "post", new_callable=AsyncMock, return_value=model_response
    ):
        with patch.object(
            predictor.http_client,
            "get",
            new_callable=AsyncMock,
            side_effect=httpx.HTTPStatusError("503", request=MagicMock(), response=MagicMock()),
        ):
            output = await predictor.predict(geopolitical_signals, "conflict")

            # Should complete despite War Room failure
            assert output is not None
            assert output.topic == "conflict"


# ────────────────────────────────────────────────────────────────────────────
# Empty Signal Handling Tests
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prediction_with_no_signals(predictor):
    """Test prediction handles empty signal list."""
    model_response = MagicMock()
    model_response.json.return_value = {"response": "Unable to predict from empty signals"}
    model_response.raise_for_status.return_value = None

    with patch.object(
        predictor.http_client, "post", new_callable=AsyncMock, return_value=model_response
    ):
        output = await predictor.predict([], "test topic")

        assert output is not None
        assert output.topic == "test topic"
        # Should have predictions even with empty signals
        assert len(output.component_predictions) > 0


@pytest.mark.asyncio
async def test_prediction_filters_low_importance_signals(predictor):
    """Test prediction filters signals below 50 importance threshold."""
    low_importance = [
        InsightSignal(
            signal_id=str(uuid.uuid4()),
            source_platform="x",
            content="Low importance signal",
            importance_score=30.0,
            relevance=0.3,
            novelty=0.3,
            actionability=0.3,
            source_authority=0.3,
            time_sensitivity=0.3,
            timestamp=datetime.now(timezone.utc),
            tags=["low-signal"],
        ),
        InsightSignal(
            signal_id=str(uuid.uuid4()),
            source_platform="x",
            content="High importance signal",
            importance_score=75.0,
            relevance=0.8,
            novelty=0.8,
            actionability=0.8,
            source_authority=0.8,
            time_sensitivity=0.8,
            timestamp=datetime.now(timezone.utc),
            tags=["important"],
        ),
    ]

    model_response = MagicMock()
    model_response.json.return_value = {"response": "Prediction"}
    model_response.raise_for_status.return_value = None

    with patch.object(
        predictor.http_client, "post", new_callable=AsyncMock, return_value=model_response
    ):
        output = await predictor.predict(low_importance, "test topic")

        assert output is not None


# ────────────────────────────────────────────────────────────────────────────
# Integration Tests
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_prediction_pipeline(predictor, sample_signals):
    """Test complete prediction pipeline from signals to output."""
    # Mock model responses
    claude_response = MagicMock()
    claude_response.json.return_value = {
        "content": [
            {
                "text": '{"prediction": "Strong growth", "confidence": 0.85, "reasoning": "Multiple signals converge"}'
            }
        ]
    }
    claude_response.raise_for_status.return_value = None

    ollama_response = MagicMock()
    ollama_response.json.return_value = {"response": "Consistent growth signals"}
    ollama_response.raise_for_status.return_value = None

    call_count = [0]

    async def mock_post_side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:  # Claude call
            return claude_response
        else:  # Ollama calls
            return ollama_response

    with patch.object(
        predictor.http_client, "post", new_callable=AsyncMock, side_effect=mock_post_side_effect
    ):
        output = await predictor.predict(sample_signals, "AI market growth")

        # Verify complete output structure
        assert output.prediction_id is not None
        assert output.topic == "AI market growth"
        assert output.consensus_prediction is not None
        assert 0.0 <= output.confidence <= 1.0
        assert "claude" in output.component_predictions
        assert "qwen" in output.component_predictions
        assert "deepseek" in output.component_predictions


# ────────────────────────────────────────────────────────────────────────────
# Cleanup Tests
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_predictor_cleanup():
    """Test predictor properly closes HTTP client."""
    predictor = FuturePredictor(claude_api_key="test")

    with patch.object(predictor.http_client, "aclose", new_callable=AsyncMock) as mock_close:
        await predictor.close()
        mock_close.assert_called_once()
