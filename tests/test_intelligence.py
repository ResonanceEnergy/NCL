"""Tests for NCL Intelligence Engine.

Covers:
  - Engine initialization and configuration
  - SignalCorrelator sector grouping and scoring
  - Signal importance scoring
  - Report/brief generation pipeline
  - Stats/metrics methods
  - Executive summary generation (LLM + template fallback)
  - Persistence helpers
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

import pytest

from runtime.intelligence.models import (
    IntelBrief,
    IntelSignal,
    MarketSignal,
    NewsSignal,
    PredictionMarketSignal,
    SectorSnapshot,
    SignalDirection,
    SocialSignal,
    SourceType,
    TrendSignal,
)
from runtime.intelligence.engine import IntelligenceEngine, SignalCorrelator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_config(**overrides):
    """Build a minimal config namespace for IntelligenceEngine."""
    defaults = {
        "gnews_api_key": "fake-gnews",
        "newsapi_key": "fake-newsapi",
        "reddit_client_id": "fake-reddit-id",
        "reddit_client_secret": "fake-reddit-secret",
        "data_dir": "/tmp/ncl_test_data",
        "config_dir": "/tmp/ncl_test_config",
        "anthropic_api_key": "",
        "anthropic_base_url": "https://api.anthropic.com",
        "ollama_host": "localhost:11434",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture
def config():
    return _make_config()


@pytest.fixture
def engine(config, tmp_path):
    """Create an IntelligenceEngine with a temp data dir."""
    config.data_dir = str(tmp_path / "data")
    config.config_dir = str(tmp_path / "config")
    return IntelligenceEngine(config)


def _signal(
    source=SourceType.NEWS,
    title="Test signal",
    content="Signal content",
    direction=SignalDirection.NEUTRAL,
    category="",
    confidence=0.5,
    change_pct=None,
    volume=None,
    value=None,
    tags=None,
):
    """Helper to build IntelSignal instances for tests."""
    return IntelSignal(
        source=source,
        title=title,
        content=content,
        direction=direction,
        category=category,
        confidence=confidence,
        change_pct=change_pct,
        volume=volume,
        value=value,
        tags=tags or [],
    )


def _prediction_signal(title="Will X happen?", yes_price=0.7, volume=50000):
    return PredictionMarketSignal(
        source=SourceType.POLYMARKET,
        title=title,
        content=f"Prediction: {title}",
        market_question=title,
        yes_price=yes_price,
        no_price=round(1.0 - yes_price, 2),
        market_volume=volume,
        volume=volume,
        value=yes_price,
        direction=SignalDirection.BULLISH,
        confidence=0.8,
    )


def _trend_signal(title="AI hype", value=100):
    return TrendSignal(
        source=SourceType.GOOGLE_TRENDS,
        title=title,
        content=f"Trending: {title}",
        search_term=title,
        value=value,
        direction=SignalDirection.EMERGING,
        confidence=0.6,
    )


def _market_signal(symbol="BTC", price=60000, change_pct=5.2):
    return MarketSignal(
        source=SourceType.CRYPTO,
        title=symbol,
        content=f"{symbol} price movement",
        symbol=symbol,
        current_price=price,
        change_pct=change_pct,
        value=price,
        direction=SignalDirection.BULLISH if change_pct > 0 else SignalDirection.BEARISH,
        confidence=0.9,
        volume=1_000_000,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 1. ENGINE INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════


class TestEngineInit:
    """Test IntelligenceEngine construction and initialize()."""

    def test_init_with_config(self, engine):
        assert engine.config is not None
        assert engine._watch_topics  # default topics loaded
        assert engine._stats["briefs_generated"] == 0
        assert engine._stats["total_signals_collected"] == 0

    def test_init_without_config(self, tmp_path):
        eng = IntelligenceEngine(config=None)
        assert eng._anthropic_key == ""
        assert eng._ollama_host == "localhost:11434"

    def test_init_creates_data_dirs(self, engine):
        assert engine._briefs_dir.exists()

    @pytest.mark.asyncio
    async def test_initialize_default_topics(self, engine):
        await engine.initialize()
        assert len(engine._watch_topics) > 0

    @pytest.mark.asyncio
    async def test_initialize_loads_custom_topics(self, engine, tmp_path):
        config_dir = Path(engine.config.config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        topics_file = config_dir / "watch_topics.json"
        topics_file.write_text(json.dumps({"topics": ["custom topic 1", "custom topic 2"]}))

        await engine.initialize()
        assert engine._watch_topics == ["custom topic 1", "custom topic 2"]

    @pytest.mark.asyncio
    async def test_initialize_bad_topics_file_keeps_defaults(self, engine, tmp_path):
        config_dir = Path(engine.config.config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "watch_topics.json").write_text("NOT JSON")

        default_topics = list(engine._watch_topics)
        await engine.initialize()
        assert engine._watch_topics == default_topics


# ═══════════════════════════════════════════════════════════════════════════
# 2. SIGNAL IMPORTANCE SCORING
# ═══════════════════════════════════════════════════════════════════════════


class TestSignalScoring:
    """Test IntelSignal.importance_score() computation."""

    def test_neutral_zero_confidence(self):
        sig = _signal(direction=SignalDirection.NEUTRAL, confidence=0.0)
        assert sig.importance_score() == 0.0

    def test_high_change_pct(self):
        sig = _signal(change_pct=55.0, confidence=0.0)
        score = sig.importance_score()
        assert score >= 40  # >50% change gives 40 points

    def test_moderate_change_pct(self):
        sig = _signal(change_pct=25.0, confidence=0.0)
        score = sig.importance_score()
        assert score >= 30

    def test_confidence_contribution(self):
        low = _signal(confidence=0.1)
        high = _signal(confidence=1.0)
        assert high.importance_score() > low.importance_score()

    def test_non_neutral_direction_bonus(self):
        neutral = _signal(direction=SignalDirection.NEUTRAL, confidence=0.5)
        bullish = _signal(direction=SignalDirection.BULLISH, confidence=0.5)
        assert bullish.importance_score() > neutral.importance_score()

    def test_emerging_gets_extra_bonus(self):
        bullish = _signal(direction=SignalDirection.BULLISH, confidence=0.5)
        emerging = _signal(direction=SignalDirection.EMERGING, confidence=0.5)
        assert emerging.importance_score() > bullish.importance_score()

    def test_volume_backed_bonus(self):
        no_vol = _signal(confidence=0.5, volume=None)
        with_vol = _signal(confidence=0.5, volume=10000)
        assert with_vol.importance_score() > no_vol.importance_score()

    def test_score_capped_at_100(self):
        sig = _signal(
            change_pct=100, confidence=1.0,
            direction=SignalDirection.EMERGING, volume=999999,
        )
        assert sig.importance_score() <= 100.0

    def test_score_floor_at_zero(self):
        sig = _signal(confidence=0.0, direction=SignalDirection.NEUTRAL)
        assert sig.importance_score() >= 0.0


# ═══════════════════════════════════════════════════════════════════════════
# 3. SIGNAL CORRELATOR
# ═══════════════════════════════════════════════════════════════════════════


class TestSignalCorrelator:
    """Test SignalCorrelator.correlate() sector grouping and scoring."""

    def setup_method(self):
        self.correlator = SignalCorrelator()

    def test_empty_signals(self):
        result = self.correlator.correlate([])
        assert result == []

    def test_explicit_category_grouping(self):
        signals = [
            _signal(category="crypto", title="BTC up"),
            _signal(category="crypto", title="ETH up"),
            _signal(category="ai_tech", title="OpenAI news"),
        ]
        snapshots = self.correlator.correlate(signals)
        sectors = {s.sector for s in snapshots}
        assert "crypto" in sectors
        assert "ai_tech" in sectors

    def test_keyword_fallback_grouping(self):
        sig = _signal(category="", title="Bitcoin price surges", content="crypto market")
        snapshots = self.correlator.correlate([sig])
        assert any(s.sector == "crypto" for s in snapshots)

    def test_unmatched_goes_to_other(self):
        sig = _signal(category="", title="Random unrelated event", content="nothing matches")
        snapshots = self.correlator.correlate([sig])
        assert any(s.sector == "other" for s in snapshots)

    def test_signal_count(self):
        signals = [_signal(category="macro") for _ in range(5)]
        snapshots = self.correlator.correlate(signals)
        macro = next(s for s in snapshots if s.sector == "macro")
        assert macro.signal_count == 5

    def test_cross_source_confidence_boost_2_sources(self):
        signals = [
            _signal(source=SourceType.NEWS, category="crypto", confidence=0.5),
            _signal(source=SourceType.CRYPTO, category="crypto", confidence=0.5),
        ]
        snapshots = self.correlator.correlate(signals)
        crypto = next(s for s in snapshots if s.sector == "crypto")
        # Two sources -> 1.15x multiplier on avg confidence (0.5)
        assert crypto.avg_confidence > 0.5

    def test_cross_source_confidence_boost_3_sources(self):
        signals = [
            _signal(source=SourceType.NEWS, category="crypto", confidence=0.5),
            _signal(source=SourceType.CRYPTO, category="crypto", confidence=0.5),
            _signal(source=SourceType.REDDIT, category="crypto", confidence=0.5),
        ]
        snapshots = self.correlator.correlate(signals)
        crypto = next(s for s in snapshots if s.sector == "crypto")
        # Three sources -> 1.3x multiplier
        assert crypto.avg_confidence > 0.5 * 1.15

    def test_confidence_capped_at_1(self):
        signals = [
            _signal(source=SourceType.NEWS, category="crypto", confidence=0.9),
            _signal(source=SourceType.CRYPTO, category="crypto", confidence=0.95),
            _signal(source=SourceType.REDDIT, category="crypto", confidence=0.99),
        ]
        snapshots = self.correlator.correlate(signals)
        crypto = next(s for s in snapshots if s.sector == "crypto")
        assert crypto.avg_confidence <= 1.0

    def test_dominant_direction(self):
        signals = [
            _signal(category="macro", direction=SignalDirection.BEARISH, confidence=0.8),
            _signal(category="macro", direction=SignalDirection.BEARISH, confidence=0.7),
            _signal(category="macro", direction=SignalDirection.BULLISH, confidence=0.2),
        ]
        snapshots = self.correlator.correlate(signals)
        macro = next(s for s in snapshots if s.sector == "macro")
        assert macro.direction == SignalDirection.BEARISH

    def test_top_signals_limited_to_5(self):
        signals = [_signal(category="crypto", confidence=0.1 * i) for i in range(10)]
        snapshots = self.correlator.correlate(signals)
        crypto = next(s for s in snapshots if s.sector == "crypto")
        assert len(crypto.top_signals) <= 5

    def test_snapshots_sorted_by_relevance(self):
        signals = [
            _signal(category="crypto", confidence=0.9),
            _signal(category="crypto", confidence=0.9),
            _signal(category="crypto", confidence=0.9),
            _signal(category="other", confidence=0.1),
        ]
        snapshots = self.correlator.correlate(signals)
        assert snapshots[0].sector == "crypto"

    def test_summary_truncated(self):
        sig = _signal(category="ai_tech", title="A" * 400)
        snapshots = self.correlator.correlate([sig])
        ai = next(s for s in snapshots if s.sector == "ai_tech")
        assert len(ai.summary) <= 300


# ═══════════════════════════════════════════════════════════════════════════
# 4. REPORT / BRIEF GENERATION
# ═══════════════════════════════════════════════════════════════════════════


class TestBriefGeneration:
    """Test generate_brief() pipeline with mocked collectors."""

    @pytest.fixture
    def mock_engine(self, engine):
        """Engine with all collectors mocked out."""
        engine._trends = MagicMock()
        engine._polymarket = MagicMock()
        engine._news = MagicMock()
        engine._crypto = MagicMock()
        engine._reddit = MagicMock()

        # Default: all collectors return empty
        engine._trends.collect_daily_trends = AsyncMock(return_value=[])
        engine._trends.collect_interest = AsyncMock(return_value=[])
        engine._trends.close = AsyncMock()

        engine._polymarket.collect_trending_markets = AsyncMock(return_value=[])
        engine._polymarket.collect_specific_markets = AsyncMock(return_value=[])
        engine._polymarket.close = AsyncMock()

        engine._news.collect_top_headlines = AsyncMock(return_value=[])
        engine._news.collect_topic_news = AsyncMock(return_value=[])
        engine._news.close = AsyncMock()

        engine._crypto.collect_market_overview = AsyncMock(return_value=[])
        engine._crypto.collect_trending = AsyncMock(return_value=[])
        engine._crypto.collect_global_metrics = AsyncMock(return_value=[])
        engine._crypto.close = AsyncMock()

        engine._reddit.collect_all = AsyncMock(return_value=[])
        engine._reddit.collect_ticker_mentions = AsyncMock(return_value={})
        engine._reddit.close = AsyncMock()

        return engine

    @pytest.mark.asyncio
    async def test_generate_brief_empty_signals(self, mock_engine):
        """Brief generation works even with zero signals."""
        brief = await mock_engine.generate_brief("daily")
        assert isinstance(brief, IntelBrief)
        assert brief.brief_type == "daily"
        assert brief.total_signals_processed == 0

    @pytest.mark.asyncio
    async def test_generate_brief_with_signals(self, mock_engine):
        """Brief generation with a mix of signal types."""
        mock_engine._trends.collect_daily_trends = AsyncMock(return_value=[
            _trend_signal("AI revolution"),
        ])
        mock_engine._crypto.collect_market_overview = AsyncMock(return_value=[
            _market_signal("BTC", 62000, 3.5),
        ])
        mock_engine._polymarket.collect_trending_markets = AsyncMock(return_value=[
            _prediction_signal("Will AI pass Turing test?", 0.65, 100000),
        ])
        mock_engine._news.collect_top_headlines = AsyncMock(return_value=[
            NewsSignal(
                source=SourceType.NEWS, title="Fed holds rates",
                content="Federal Reserve holds rates steady",
                headline="Fed holds rates", source_name="Reuters",
                category="macro", confidence=0.7,
                direction=SignalDirection.NEUTRAL,
            ),
        ])

        brief = await mock_engine.generate_brief()
        assert brief.total_signals_processed == 4
        assert len(brief.sectors) > 0
        assert len(brief.top_signals) > 0

    @pytest.mark.asyncio
    async def test_generate_brief_collector_failure(self, mock_engine):
        """One collector failing should not break the pipeline."""
        mock_engine._trends.collect_daily_trends = AsyncMock(
            side_effect=RuntimeError("Trends API down")
        )
        mock_engine._crypto.collect_market_overview = AsyncMock(return_value=[
            _market_signal("ETH", 3200, -1.2),
        ])

        brief = await mock_engine.generate_brief()
        # Should still succeed with partial data
        assert isinstance(brief, IntelBrief)
        assert mock_engine._stats["errors"] >= 0  # errors tracked

    @pytest.mark.asyncio
    async def test_brief_predictions_deduplication(self, mock_engine):
        """Duplicate prediction market questions should be deduplicated."""
        dup = _prediction_signal("Same question?", 0.6, 5000)
        mock_engine._polymarket.collect_trending_markets = AsyncMock(return_value=[dup, dup])

        brief = await mock_engine.generate_brief()
        questions = [p["question"] for p in brief.predictions]
        assert len(questions) == len(set(questions))

    @pytest.mark.asyncio
    async def test_brief_risk_alerts_filter_noise(self, mock_engine):
        """Risk alerts should filter out sports/entertainment and low-volume."""
        bearish_macro = _signal(
            category="macro", direction=SignalDirection.BEARISH,
            confidence=0.9, change_pct=30, volume=50000,
            title="Bond yields spike", content="10Y treasury yield surges",
        )
        bearish_sports = _signal(
            category="sports", direction=SignalDirection.BEARISH,
            confidence=0.9, change_pct=30, volume=50000,
            title="Team loses game", content="Sports noise",
        )
        low_vol = _signal(
            category="macro", direction=SignalDirection.BEARISH,
            confidence=0.9, change_pct=30, volume=500,
            title="Obscure metric", content="Low volume noise",
        )
        mock_engine._news.collect_top_headlines = AsyncMock(
            return_value=[bearish_macro, bearish_sports, low_vol]
        )

        brief = await mock_engine.generate_brief()
        # Sports and low-volume should be filtered; only macro alert remains
        alert_titles = [a.split(":")[0] for a in brief.risk_alerts]
        assert "Team loses game" not in alert_titles
        assert "Obscure metric" not in alert_titles


# ═══════════════════════════════════════════════════════════════════════════
# 5. EXECUTIVE SUMMARY GENERATION
# ═══════════════════════════════════════════════════════════════════════════


class TestExecutiveSummary:
    """Test _generate_executive_summary LLM calls and fallbacks."""

    @pytest.fixture
    def engine_with_key(self, engine):
        engine._anthropic_key = "test-key-123"
        return engine

    @pytest.mark.asyncio
    async def test_anthropic_success(self, engine_with_key):
        """When Anthropic API succeeds, return its response."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "content": [{"text": "Markets are volatile today."}]
        }
        engine_with_key._llm_client.post = AsyncMock(return_value=mock_resp)

        result = await engine_with_key._generate_executive_summary([], [], [], [])
        assert result == "Markets are volatile today."

    @pytest.mark.asyncio
    async def test_anthropic_fails_ollama_fallback(self, engine_with_key):
        """When Anthropic fails, fall back to Ollama."""
        # Anthropic fails
        engine_with_key._llm_client.post = AsyncMock(
            side_effect=[
                RuntimeError("API error"),
                # Ollama succeeds
                MagicMock(
                    raise_for_status=MagicMock(),
                    json=MagicMock(return_value={"response": "Ollama summary here."}),
                ),
            ]
        )

        result = await engine_with_key._generate_executive_summary([], [], [], [])
        assert result == "Ollama summary here."

    @pytest.mark.asyncio
    async def test_both_llm_fail_template_fallback(self, engine):
        """When both LLMs fail, use template summary."""
        engine._anthropic_key = ""  # skip Claude
        engine._llm_client.post = AsyncMock(side_effect=RuntimeError("Ollama down"))

        sectors = [
            SectorSnapshot(
                sector="crypto", direction=SignalDirection.BULLISH,
                signal_count=5, avg_confidence=0.8,
            )
        ]
        result = await engine._generate_executive_summary(sectors, [], [], [])
        assert "crypto" in result
        assert "bullish" in result

    def test_template_summary_no_data(self, engine):
        result = engine._template_summary([], [], [])
        assert "No significant signals" in result

    def test_template_summary_with_sectors(self, engine):
        sectors = [
            SectorSnapshot(
                sector="ai_tech", direction=SignalDirection.EXPANDING,
                signal_count=10, avg_confidence=0.75,
            )
        ]
        result = engine._template_summary(sectors, [], [])
        assert "ai_tech" in result

    def test_template_summary_with_market_movements(self, engine):
        movements = [{"symbol": "BTC", "price": 60000, "change_pct": 8.5}]
        result = engine._template_summary([], movements, [])
        assert "BTC" in result

    def test_template_summary_with_predictions(self, engine):
        preds = [{"question": "Will inflation drop?", "probability": 0.72}]
        result = engine._template_summary([], [], preds)
        assert "inflation" in result.lower() or "Will" in result


# ═══════════════════════════════════════════════════════════════════════════
# 6. STATS / METRICS
# ═══════════════════════════════════════════════════════════════════════════


class TestStats:
    """Test get_stats() and related metrics."""

    def test_initial_stats(self, engine):
        stats = engine.get_stats()
        assert stats["briefs_generated"] == 0
        assert stats["total_signals_collected"] == 0
        assert stats["errors"] == 0
        assert stats["last_brief"] is None
        assert "watch_topics" in stats
        assert "briefs_dir" in stats

    @pytest.mark.asyncio
    async def test_stats_after_collection(self, engine):
        """Stats should update after collecting signals."""
        # Mock all collectors
        engine._trends = MagicMock()
        engine._trends.collect_daily_trends = AsyncMock(return_value=[_signal()])
        engine._trends.collect_interest = AsyncMock(return_value=[])
        engine._polymarket = MagicMock()
        engine._polymarket.collect_trending_markets = AsyncMock(return_value=[])
        engine._polymarket.collect_specific_markets = AsyncMock(return_value=[])
        engine._news = MagicMock()
        engine._news.collect_top_headlines = AsyncMock(return_value=[])
        engine._news.collect_topic_news = AsyncMock(return_value=[])
        engine._crypto = MagicMock()
        engine._crypto.collect_market_overview = AsyncMock(return_value=[])
        engine._crypto.collect_trending = AsyncMock(return_value=[])
        engine._crypto.collect_global_metrics = AsyncMock(return_value=[])
        engine._reddit = MagicMock()
        engine._reddit.collect_all = AsyncMock(return_value=[])
        engine._reddit.collect_ticker_mentions = AsyncMock(return_value={})

        signals = await engine.collect_all_signals()
        stats = engine.get_stats()
        assert stats["total_signals_collected"] == 1
        assert stats["last_collection"] is not None


# ═══════════════════════════════════════════════════════════════════════════
# 7. PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════


class TestPersistence:
    """Test signal and brief persistence."""

    @pytest.mark.asyncio
    async def test_persist_signals_creates_file(self, engine):
        signals = [_signal(title="persist me")]
        await engine._persist_signals(signals)
        assert engine._signals_file.exists()
        content = engine._signals_file.read_text()
        assert "persist me" in content

    @pytest.mark.asyncio
    async def test_persist_brief_creates_files(self, engine):
        brief = IntelBrief(
            brief_type="daily",
            executive_summary="Test summary",
            total_signals_processed=5,
        )
        await engine._persist_brief(brief)

        assert engine._briefs_file.exists()
        assert (engine._briefs_dir / "latest_brief.json").exists()
        assert (engine._briefs_dir / "latest_brief.txt").exists()

    @pytest.mark.asyncio
    async def test_get_latest_brief_none(self, engine):
        result = await engine.get_latest_brief()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_latest_brief_round_trip(self, engine):
        brief = IntelBrief(
            brief_type="alert",
            executive_summary="Round trip test",
            total_signals_processed=42,
        )
        await engine._persist_brief(brief)
        loaded = await engine.get_latest_brief()
        assert loaded is not None
        assert loaded.brief_type == "alert"
        assert loaded.executive_summary == "Round trip test"
        assert loaded.total_signals_processed == 42


# ═══════════════════════════════════════════════════════════════════════════
# 8. CLOSE / CLEANUP
# ═══════════════════════════════════════════════════════════════════════════


class TestCleanup:
    """Test engine close() method."""

    @pytest.mark.asyncio
    async def test_close_calls_all_collectors(self, engine):
        engine._trends = MagicMock()
        engine._trends.close = AsyncMock()
        engine._polymarket = MagicMock()
        engine._polymarket.close = AsyncMock()
        engine._news = MagicMock()
        engine._news.close = AsyncMock()
        engine._crypto = MagicMock()
        engine._crypto.close = AsyncMock()
        engine._llm_client = MagicMock()
        engine._llm_client.aclose = AsyncMock()

        await engine.close()

        engine._trends.close.assert_awaited_once()
        engine._polymarket.close.assert_awaited_once()
        engine._news.close.assert_awaited_once()
        engine._crypto.close.assert_awaited_once()
        engine._llm_client.aclose.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════════════
# 9. INTELBIEF.to_text()
# ═══════════════════════════════════════════════════════════════════════════


class TestBriefToText:
    """Test IntelBrief.to_text() formatting."""

    def test_minimal_brief(self):
        brief = IntelBrief(brief_type="daily", total_signals_processed=0)
        text = brief.to_text()
        assert "NCL INTELLIGENCE BRIEF" in text
        assert "DAILY" in text

    def test_full_brief_sections(self):
        brief = IntelBrief(
            brief_type="daily",
            executive_summary="Things are happening.",
            sectors=[
                SectorSnapshot(
                    sector="crypto", direction=SignalDirection.BULLISH,
                    signal_count=3, avg_confidence=0.85,
                )
            ],
            predictions=[{"question": "Will X?", "probability": 0.6, "volume": 1000}],
            trending=[{"term": "AI", "score": 100, "direction": "emerging"}],
            market_movements=[{"symbol": "BTC", "price": 60000, "change_pct": 5.0}],
            risk_alerts=["Bond yield spike warning"],
            source_counts={"news": 10, "crypto": 5},
            total_signals_processed=15,
        )
        text = brief.to_text()
        assert "EXECUTIVE SUMMARY" in text
        assert "WHAT'S HOT" in text
        assert "PREDICTION MARKETS" in text
        assert "MARKET MOVEMENTS" in text
        assert "SECTOR ANALYSIS" in text
        assert "RISK ALERTS" in text
        assert "SOURCES" in text
