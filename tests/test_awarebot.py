"""End-to-end tests for Awarebot scanner and signal processing."""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import httpx
import pytest

from runtime.awarebot.scanner import Scanner
from runtime.ncl_brain.models import InsightSignal


# ────────────────────────────────────────────────────────────────────────────
# Test Fixtures
# ────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def scanner():
    """Create a Scanner instance with test credentials."""
    return Scanner(
        x_bearer_token="test-x-token",
        youtube_api_key="test-youtube-key",
        reddit_client_id="test-reddit-id",
        reddit_client_secret="test-reddit-secret",
    )


@pytest.fixture
async def mock_httpx_client():
    """Create a mock httpx AsyncClient."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    return mock_client


# ────────────────────────────────────────────────────────────────────────────
# Scanner Initialization Tests
# ────────────────────────────────────────────────────────────────────────────


def test_scanner_initialization():
    """Test Scanner initializes with credentials."""
    scanner = Scanner(
        x_bearer_token="token-x",
        youtube_api_key="key-youtube",
        reddit_client_id="id-reddit",
        reddit_client_secret="secret-reddit",
    )

    assert scanner.x_bearer_token == "token-x"
    assert scanner.youtube_api_key == "key-youtube"
    assert scanner.reddit_client_id == "id-reddit"
    assert scanner.reddit_client_secret == "secret-reddit"
    assert scanner.http_client is not None


def test_scanner_initialization_with_defaults():
    """Test Scanner initializes with default values."""
    scanner = Scanner()

    assert scanner.x_bearer_token is None
    assert scanner.youtube_api_key is None
    assert scanner.reddit_client_id is None
    assert scanner.reddit_client_secret is None
    assert scanner.reddit_user_agent == "NCL-Awarebot/1.0"


# ────────────────────────────────────────────────────────────────────────────
# X (Twitter) Scanner Tests
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_x_returns_signals(scanner):
    """Test scan_x returns list of InsightSignal objects with mocked HTTP."""
    # Mock the HTTP response
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {
                "id": "123456",
                "text": "Breaking: AI model achieves new benchmark",
            },
            {
                "id": "123457",
                "text": "Market volatility increases amid geopolitical tensions",
            },
        ]
    }
    mock_response.raise_for_status.return_value = None

    with patch.object(
        scanner.http_client, "get", new_callable=AsyncMock, return_value=mock_response
    ) as mock_get:
        signals = await scanner.scan_x("AI breakthrough", max_results=10)

        # Verify HTTP call was made correctly
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "https://api.twitter.com/2/tweets/search/recent" in str(call_args)
        assert call_args.kwargs["params"]["query"] == "AI breakthrough"
        assert call_args.kwargs["params"]["max_results"] <= 100

        # Verify signals returned
        assert len(signals) == 2
        assert all(isinstance(s, InsightSignal) for s in signals)
        assert signals[0].source_platform == "x"
        assert signals[0].content == "Breaking: AI model achieves new benchmark"
        assert signals[0].url == "https://twitter.com/i/web/status/123456"


@pytest.mark.asyncio
async def test_scan_x_returns_empty_without_token(scanner):
    """Test scan_x returns empty list when X bearer token is missing."""
    scanner.x_bearer_token = None
    signals = await scanner.scan_x("query")
    assert signals == []


@pytest.mark.asyncio
async def test_scan_x_api_failure_handling(scanner):
    """Test scan_x gracefully handles API failures."""
    with patch.object(
        scanner.http_client,
        "get",
        new_callable=AsyncMock,
        side_effect=httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock()),
    ):
        signals = await scanner.scan_x("query")
        assert signals == []


@pytest.mark.asyncio
async def test_scan_x_timeout_handling(scanner):
    """Test scan_x gracefully handles timeout."""
    with patch.object(
        scanner.http_client,
        "get",
        new_callable=AsyncMock,
        side_effect=asyncio.TimeoutError(),
    ):
        signals = await scanner.scan_x("query")
        assert signals == []


# ────────────────────────────────────────────────────────────────────────────
# YouTube Scanner Tests
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_youtube_returns_signals(scanner):
    """Test scan_youtube returns list of InsightSignal objects."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "items": [
            {
                "id": {"videoId": "video123"},
                "snippet": {
                    "title": "Understanding AI Ethics",
                    "description": "A deep dive into AI ethics framework",
                },
            },
            {
                "id": {"videoId": "video124"},
                "snippet": {
                    "title": "Latest Tech News",
                    "description": "Weekly tech roundup",
                },
            },
        ]
    }
    mock_response.raise_for_status.return_value = None

    with patch.object(
        scanner.http_client, "get", new_callable=AsyncMock, return_value=mock_response
    ) as mock_get:
        signals = await scanner.scan_youtube("AI ethics", max_results=10)

        # Verify HTTP call
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "googleapis.com/youtube/v3/search" in str(call_args)
        assert call_args.kwargs["params"]["q"] == "AI ethics"

        # Verify signals
        assert len(signals) == 2
        assert all(isinstance(s, InsightSignal) for s in signals)
        assert signals[0].source_platform == "youtube"
        assert signals[0].url == "https://youtu.be/video123"
        assert "Understanding AI Ethics" in signals[0].content


@pytest.mark.asyncio
async def test_scan_youtube_returns_empty_without_key(scanner):
    """Test scan_youtube returns empty list when API key is missing."""
    scanner.youtube_api_key = None
    signals = await scanner.scan_youtube("query")
    assert signals == []


@pytest.mark.asyncio
async def test_scan_youtube_api_failure(scanner):
    """Test scan_youtube gracefully handles API failures."""
    with patch.object(
        scanner.http_client,
        "get",
        new_callable=AsyncMock,
        side_effect=httpx.HTTPStatusError("403", request=MagicMock(), response=MagicMock()),
    ):
        signals = await scanner.scan_youtube("query")
        assert signals == []


# ────────────────────────────────────────────────────────────────────────────
# Reddit Scanner Tests
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_reddit_returns_signals(scanner):
    """Test scan_reddit returns list of InsightSignal objects."""
    # Mock auth token response
    auth_response = MagicMock()
    auth_response.json.return_value = {"access_token": "reddit-token-abc"}
    auth_response.raise_for_status.return_value = None

    # Mock posts response
    posts_response = MagicMock()
    posts_response.json.return_value = {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "New AI breakthrough announced",
                        "selftext": "Here's what we know so far...",
                        "permalink": "/r/MachineLearning/comments/abc123",
                    }
                },
                {
                    "data": {
                        "title": "Discussion: Future of LLMs",
                        "selftext": "What's next for large language models?",
                        "permalink": "/r/MachineLearning/comments/def456",
                    }
                },
            ]
        }
    }
    posts_response.raise_for_status.return_value = None

    with patch.object(scanner.http_client, "post", new_callable=AsyncMock, return_value=auth_response):
        with patch.object(
            scanner.http_client, "get", new_callable=AsyncMock, return_value=posts_response
        ) as mock_get:
            signals = await scanner.scan_reddit("MachineLearning", max_results=10)

            # Verify signals
            assert len(signals) == 2
            assert all(isinstance(s, InsightSignal) for s in signals)
            assert signals[0].source_platform == "reddit"
            assert signals[0].url == "https://reddit.com/r/MachineLearning/comments/abc123"
            assert "New AI breakthrough" in signals[0].content


@pytest.mark.asyncio
async def test_scan_reddit_returns_empty_without_credentials(scanner):
    """Test scan_reddit returns empty list when credentials missing."""
    scanner.reddit_client_id = None
    signals = await scanner.scan_reddit("subreddit")
    assert signals == []

    scanner.reddit_client_id = "id"
    scanner.reddit_client_secret = None
    signals = await scanner.scan_reddit("subreddit")
    assert signals == []


@pytest.mark.asyncio
async def test_scan_reddit_auth_failure(scanner):
    """Test scan_reddit gracefully handles auth failure."""
    with patch.object(
        scanner.http_client,
        "post",
        new_callable=AsyncMock,
        side_effect=httpx.HTTPStatusError("401", request=MagicMock(), response=MagicMock()),
    ):
        signals = await scanner.scan_reddit("subreddit")
        assert signals == []


# ────────────────────────────────────────────────────────────────────────────
# Importance Scoring Tests
# ────────────────────────────────────────────────────────────────────────────


def test_importance_scoring_formula():
    """Test importance scoring formula: (rel*0.3 + nov*0.25 + act*0.25 + auth*0.1 + time*0.1)*100."""
    scanner = Scanner()

    # Create signal with known component values
    signal = InsightSignal(
        signal_id=str(uuid.uuid4()),
        source_platform="x",
        content="Test signal",
        importance_score=0.0,
        relevance=0.8,
        novelty=0.6,
        actionability=0.7,
        source_authority=0.9,
        time_sensitivity=0.5,
        timestamp=datetime.now(timezone.utc),
    )

    # Compute importance
    importance = scanner._compute_importance(signal)

    # Verify formula
    expected = (0.8 * 0.3 + 0.6 * 0.25 + 0.7 * 0.25 + 0.9 * 0.1 + 0.5 * 0.1) * 100
    assert abs(importance - expected) < 0.01
    assert importance == pytest.approx(70.5)


def test_importance_scoring_bounds():
    """Test importance score stays within bounds [0, 100]."""
    scanner = Scanner()

    # Test max value
    signal_max = InsightSignal(
        signal_id=str(uuid.uuid4()),
        source_platform="x",
        content="Test",
        importance_score=0.0,
        relevance=1.0,
        novelty=1.0,
        actionability=1.0,
        source_authority=1.0,
        time_sensitivity=1.0,
        timestamp=datetime.now(timezone.utc),
    )
    assert scanner._compute_importance(signal_max) == 100.0

    # Test min value
    signal_min = InsightSignal(
        signal_id=str(uuid.uuid4()),
        source_platform="x",
        content="Test",
        importance_score=0.0,
        relevance=0.0,
        novelty=0.0,
        actionability=0.0,
        source_authority=0.0,
        time_sensitivity=0.0,
        timestamp=datetime.now(timezone.utc),
    )
    assert scanner._compute_importance(signal_min) == 0.0


def test_importance_scoring_component_weights():
    """Test that importance score correctly weights components."""
    scanner = Scanner()

    # High relevance only
    signal1 = InsightSignal(
        signal_id=str(uuid.uuid4()),
        source_platform="x",
        content="Test",
        importance_score=0.0,
        relevance=1.0,
        novelty=0.0,
        actionability=0.0,
        source_authority=0.0,
        time_sensitivity=0.0,
        timestamp=datetime.now(timezone.utc),
    )
    score1 = scanner._compute_importance(signal1)
    assert score1 == pytest.approx(30.0)  # 1.0 * 0.3 * 100

    # High time sensitivity only (lowest weight)
    signal2 = InsightSignal(
        signal_id=str(uuid.uuid4()),
        source_platform="x",
        content="Test",
        importance_score=0.0,
        relevance=0.0,
        novelty=0.0,
        actionability=0.0,
        source_authority=0.0,
        time_sensitivity=1.0,
        timestamp=datetime.now(timezone.utc),
    )
    score2 = scanner._compute_importance(signal2)
    assert score2 == pytest.approx(10.0)  # 1.0 * 0.1 * 100


# ────────────────────────────────────────────────────────────────────────────
# InsightSignal Structure Tests
# ────────────────────────────────────────────────────────────────────────────


def test_insight_signal_structure():
    """Test InsightSignal has all required fields."""
    signal = InsightSignal(
        signal_id="sig-001",
        source_platform="x",
        content="Test signal content",
        url="https://example.com/signal",
        importance_score=65.5,
        relevance=0.8,
        novelty=0.6,
        actionability=0.7,
        source_authority=0.9,
        time_sensitivity=0.5,
        timestamp=datetime.now(timezone.utc),
        tags=["test", "ai"],
    )

    # Verify all fields
    assert signal.signal_id == "sig-001"
    assert signal.source_platform == "x"
    assert signal.content == "Test signal content"
    assert signal.url == "https://example.com/signal"
    assert signal.importance_score == 65.5
    assert signal.relevance == 0.8
    assert signal.novelty == 0.6
    assert signal.actionability == 0.7
    assert signal.source_authority == 0.9
    assert signal.time_sensitivity == 0.5
    assert "test" in signal.tags
    assert isinstance(signal.timestamp, datetime)


def test_insight_signal_validation():
    """Test InsightSignal validates component ranges."""
    with pytest.raises(ValueError):
        # Relevance > 1.0
        InsightSignal(
            signal_id="test",
            source_platform="x",
            content="Test",
            importance_score=50.0,
            relevance=1.5,  # Invalid
            novelty=0.5,
            actionability=0.5,
            source_authority=0.5,
            time_sensitivity=0.5,
            timestamp=datetime.now(timezone.utc),
        )


# ────────────────────────────────────────────────────────────────────────────
# Integration Tests
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scanner_multi_source_scan():
    """Test scanning multiple sources in parallel."""
    scanner = Scanner(
        x_bearer_token="test-token",
        youtube_api_key="test-key",
        reddit_client_id="test-id",
        reddit_client_secret="test-secret",
    )

    # Mock responses for all sources
    x_response = MagicMock()
    x_response.json.return_value = {
        "data": [{"id": "123", "text": "X signal"}]
    }
    x_response.raise_for_status.return_value = None

    youtube_response = MagicMock()
    youtube_response.json.return_value = {
        "items": [
            {
                "id": {"videoId": "vid1"},
                "snippet": {"title": "YouTube signal", "description": "desc"},
            }
        ]
    }
    youtube_response.raise_for_status.return_value = None

    auth_response = MagicMock()
    auth_response.json.return_value = {"access_token": "token"}
    auth_response.raise_for_status.return_value = None

    reddit_response = MagicMock()
    reddit_response.json.return_value = {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "Reddit signal",
                        "selftext": "content",
                        "permalink": "/r/test/abc",
                    }
                }
            ]
        }
    }
    reddit_response.raise_for_status.return_value = None

    get_responses = [x_response, youtube_response, reddit_response]
    get_call_count = [0]

    async def mock_get(*args, **kwargs):
        result = get_responses[get_call_count[0] % len(get_responses)]
        get_call_count[0] += 1
        return result

    with patch.object(scanner.http_client, "get", new_callable=AsyncMock, side_effect=mock_get):
        with patch.object(scanner.http_client, "post", new_callable=AsyncMock, return_value=auth_response):
            # Run scans
            x_signals = await scanner.scan_x("query")
            youtube_signals = await scanner.scan_youtube("query")
            reddit_signals = await scanner.scan_reddit("subreddit")

            # Verify all returned signals
            assert len(x_signals) == 1
            assert len(youtube_signals) == 1
            assert len(reddit_signals) == 1
            assert x_signals[0].source_platform == "x"
            assert youtube_signals[0].source_platform == "youtube"
            assert reddit_signals[0].source_platform == "reddit"


@pytest.mark.asyncio
async def test_scanner_tags_assignment():
    """Test that scanner correctly assigns tags to signals."""
    scanner = Scanner(x_bearer_token="test-token")

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [{"id": "123", "text": "Breaking news"}]
    }
    mock_response.raise_for_status.return_value = None

    with patch.object(
        scanner.http_client, "get", new_callable=AsyncMock, return_value=mock_response
    ):
        signals = await scanner.scan_x("market trends", max_results=5)

        assert len(signals) == 1
        assert "x" in signals[0].tags
        assert "market trends" in signals[0].tags


@pytest.mark.asyncio
async def test_scanner_max_results_limit():
    """Test that scanner respects max_results limits."""
    scanner = Scanner(x_bearer_token="test-token")

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [{"id": str(i), "text": f"Signal {i}"} for i in range(150)]
    }
    mock_response.raise_for_status.return_value = None

    with patch.object(
        scanner.http_client, "get", new_callable=AsyncMock, return_value=mock_response
    ) as mock_get:
        signals = await scanner.scan_x("query", max_results=150)

        # Verify max_results was capped at 100 for X API
        call_args = mock_get.call_args
        assert call_args.kwargs["params"]["max_results"] <= 100


# ────────────────────────────────────────────────────────────────────────────
# Cleanup Tests
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scanner_cleanup():
    """Test scanner properly closes HTTP client."""
    scanner = Scanner()

    with patch.object(scanner.http_client, "aclose", new_callable=AsyncMock) as mock_close:
        await scanner.close()
        mock_close.assert_called_once()
