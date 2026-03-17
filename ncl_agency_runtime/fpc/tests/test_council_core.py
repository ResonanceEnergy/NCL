#!/usr/bin/env python3
"""Tests for future-predictor-council."""

import json
from pathlib import Path

import pytest

# ── Version & imports ────────────────────────────────────────────────────────


def test_version():
    from ncl_agency_runtime.fpc import __version__
    assert __version__ == "0.6.0"


def test_public_imports():
    from ncl_agency_runtime.fpc import FuturePredictorCouncil, PredictionHorizon, RiskLevel
    assert FuturePredictorCouncil is not None
    assert len(PredictionHorizon) == 4
    assert len(RiskLevel) == 4


# ── Council ──────────────────────────────────────────────────────────────────


class TestCouncil:
    def test_init_defaults(self):
        from ncl_agency_runtime.fpc.heuristic_council import FuturePredictorCouncil
        council = FuturePredictorCouncil()
        assert len(council.council_members) == 4
        assert council.session_id.startswith("council_")

    def test_convene_returns_predictions(self):
        from ncl_agency_runtime.fpc.heuristic_council import FuturePredictorCouncil, PredictionHorizon
        council = FuturePredictorCouncil()
        result = council.convene_council("AI adoption", PredictionHorizon.SHORT_TERM)
        assert result["topic"] == "AI adoption"
        assert result["horizon"] == "1-3 months"
        assert len(result["predictions"]) == 4

    def test_consensus_calculated(self):
        from ncl_agency_runtime.fpc.heuristic_council import FuturePredictorCouncil, PredictionHorizon
        council = FuturePredictorCouncil()
        result = council.convene_council("test", PredictionHorizon.MEDIUM_TERM)
        assert "consensus" in result
        assert isinstance(result["consensus"]["consensus_reached"], bool)
        assert result["consensus"]["participant_count"] == 4

    def test_consensus_empty(self):
        from ncl_agency_runtime.fpc.heuristic_council import FuturePredictorCouncil
        council = FuturePredictorCouncil()
        c = council._consensus([])
        assert c["consensus_reached"] is False

    def test_prediction_confidence_range(self):
        from ncl_agency_runtime.fpc.heuristic_council import FuturePredictorCouncil, PredictionHorizon
        council = FuturePredictorCouncil()
        result = council.convene_council("test", PredictionHorizon.LONG_TERM)
        for pred in result["predictions"]:
            assert 0.0 <= pred["confidence"] <= 1.0

    def test_get_council_status(self):
        from ncl_agency_runtime.fpc.heuristic_council import FuturePredictorCouncil
        council = FuturePredictorCouncil()
        status = council.get_council_status()
        assert status["active_members"] == 4
        assert status["council_name"] == "Future Predictor Council"

    def test_heuristic_all_specialties(self):
        from ncl_agency_runtime.fpc.heuristic_council import CouncilMember, FuturePredictorCouncil
        for spec in ["Pattern Recognition", "Risk Analysis", "Scenario Development", "Strategic Planning"]:
            member = CouncilMember("Test", spec, 0.25)
            outcome, conf, _risk, evidence = FuturePredictorCouncil._predict_heuristic(member, "crypto")
            assert isinstance(outcome, str)
            assert 0.0 <= conf <= 1.0
            assert len(evidence) > 0


# ── Eval / Metrics ───────────────────────────────────────────────────────────


class TestMetrics:
    def test_smape_identical(self):
        import numpy as np

        from ncl_agency_runtime.fpc.eval.metrics import smape
        y = np.array([1.0, 2.0, 3.0])
        assert smape(y, y) == pytest.approx(0.0, abs=1e-9)

    def test_smape_range(self):
        import numpy as np

        from ncl_agency_runtime.fpc.eval.metrics import smape
        y_true = np.array([1.0, 2.0, 3.0])
        y_pred = np.array([3.0, 4.0, 5.0])
        result = smape(y_true, y_pred)
        assert 0.0 <= result <= 2.0

    def test_mase_naive(self):
        import numpy as np

        from ncl_agency_runtime.fpc.eval.metrics import mase
        y_true = np.array([10.0, 11.0])
        y_pred = np.array([10.5, 11.5])
        y_ins = np.array([8.0, 9.0, 10.0, 11.0])
        result = mase(y_true, y_pred, y_ins, m=1)
        assert result > 0.0

    def test_mase_short_insample(self):
        import numpy as np

        from ncl_agency_runtime.fpc.eval.metrics import mase
        result = mase(np.array([1.0]), np.array([2.0]), np.array([1.0]), m=5)
        assert result > 0.0


# ── Forecasting base ────────────────────────────────────────────────────────


class TestForecastBase:
    def test_forecast_result(self):
        import pandas as pd

        from ncl_agency_runtime.fpc.forecasting.base import ForecastResult
        fr = ForecastResult(yhat=pd.Series([1.0, 2.0]))
        assert len(fr.yhat) == 2
        assert fr.q == {}
        assert fr.meta == {}

    def test_model_strategy_is_abstract(self):
        from ncl_agency_runtime.fpc.forecasting.base import ModelStrategy
        with pytest.raises(TypeError):
            ModelStrategy()


# ── Tracker ──────────────────────────────────────────────────────────────────


class TestTracker:
    def test_record_and_list(self, tmp_path):
        from ncl_agency_runtime.fpc.tracker import PredictionTracker
        t = PredictionTracker(path=tmp_path / "preds.json")
        t.record({"id": "p1", "topic": "test", "confidence": 0.8})
        assert len(t.list_all()) == 1
        assert t.list_all()[0]["id"] == "p1"

    def test_resolve(self, tmp_path):
        from ncl_agency_runtime.fpc.tracker import PredictionTracker
        t = PredictionTracker(path=tmp_path / "preds.json")
        t.record({"id": "p2", "topic": "test", "confidence": 0.7})
        assert t.resolve("p2", "it happened", 0.9) is True
        assert t.list_all()[0]["resolved"] is True
        assert t.list_all()[0]["accuracy_score"] == 0.9

    def test_resolve_nonexistent(self, tmp_path):
        from ncl_agency_runtime.fpc.tracker import PredictionTracker
        t = PredictionTracker(path=tmp_path / "preds.json")
        assert t.resolve("nope", "x", 0.5) is False

    def test_accuracy_summary(self, tmp_path):
        from ncl_agency_runtime.fpc.tracker import PredictionTracker
        t = PredictionTracker(path=tmp_path / "preds.json")
        t.record({"id": "a", "confidence": 0.8})
        t.record({"id": "b", "confidence": 0.7})
        t.resolve("a", "correct", 0.95)
        t.resolve("b", "partial", 0.60)
        summary = t.accuracy_summary()
        assert summary["resolved"] == 2
        assert summary["avg_accuracy"] == pytest.approx(0.775)

    def test_list_unresolved(self, tmp_path):
        from ncl_agency_runtime.fpc.tracker import PredictionTracker
        t = PredictionTracker(path=tmp_path / "preds.json")
        t.record({"id": "x"})
        t.record({"id": "y"})
        t.resolve("x", "done", 1.0)
        assert len(t.list_unresolved()) == 1


# ── Report generator ────────────────────────────────────────────────────────


class TestReportGenerator:
    def test_generate_council_report(self, tmp_path):
        from ncl_agency_runtime.fpc.reports import ReportGenerator
        rg = ReportGenerator(output_dir=str(tmp_path))
        session = {
            "session_id": "s1",
            "topic": "test topic",
            "horizon": "1-3 months",
            "timestamp": "2026-03-11T00:00:00",
            "council_members": ["A", "B"],
            "predictions": [
                {"council_member": "A", "predicted_outcome": "growth", "confidence": 0.8, "risk_level": "low", "evidence": ["data"]},
            ],
        }
        paths = rg.generate(session)
        assert Path(paths["json_path"]).exists()
        assert Path(paths["md_path"]).exists()
        md_content = Path(paths["md_path"]).read_text()
        assert "test topic" in md_content


# ── Flywheel feed ────────────────────────────────────────────────────────────


class TestFlywheelFeed:
    def test_emit_and_read(self, tmp_path, monkeypatch):
        import ncl_agency_runtime.fpc.flywheel_feed as ff
        monkeypatch.setattr(ff, "STATE_DIR", tmp_path)
        monkeypatch.setattr(ff, "FEED_FILE", tmp_path / "flywheel_feed.json")
        status = ff.emit_status("backtest", "running h=14")
        assert status["stage"] == "backtest"
        read = ff.read_status()
        assert read["stage"] == "backtest"

    def test_read_missing(self, tmp_path, monkeypatch):
        import ncl_agency_runtime.fpc.flywheel_feed as ff
        monkeypatch.setattr(ff, "FEED_FILE", tmp_path / "nope.json")
        status = ff.read_status()
        assert status["stage"] == "unknown"


# ── Ingestion ────────────────────────────────────────────────────────────────


class TestIngestion:
    def test_csv_ingester(self, tmp_path):
        from ncl_agency_runtime.fpc.ingestion import CSVIngester
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("title,content\nHeadline,Body text\n")
        signals = CSVIngester().fetch(str(csv_file))
        assert len(signals) == 1
        assert signals[0].title == "Headline"

    def test_csv_ingester_missing_file(self):
        from ncl_agency_runtime.fpc.ingestion import CSVIngester
        signals = CSVIngester().fetch("/nonexistent/file.csv")
        assert signals == []

    def test_pipeline_no_sources(self):
        from ncl_agency_runtime.fpc.ingestion import IngestionPipeline
        pipeline = IngestionPipeline(config_path="/nonexistent/config.json")
        signals = pipeline.run()
        assert signals == []


# ── New strategy imports ─────────────────────────────────────────────────────


class TestStrategyLazyImports:
    """Verify lazy import wrappers exist and are callable without hard deps."""

    def test_all_strategies_exported(self):
        from ncl_agency_runtime.fpc.forecasting import __all__
        expected = [
            "ModelStrategy", "ForecastResult",
            "StatsForecastStrategy", "ChronosStrategy",
            "TimesFMStrategy", "ProphetStrategy",
            "NeuralForecastStrategy",
        ]
        for name in expected:
            assert name in __all__, f"{name} missing from __all__"

    def test_chronos_module_exists(self):
        import importlib
        mod = importlib.import_module("ncl_agency_runtime.fpc.forecasting.strategy_chronos")
        assert hasattr(mod, "ChronosStrategy")

    def test_timesfm_module_exists(self):
        import importlib
        mod = importlib.import_module("ncl_agency_runtime.fpc.forecasting.strategy_timesfm")
        assert hasattr(mod, "TimesFMStrategy")

    def test_prophet_module_exists(self):
        import importlib
        mod = importlib.import_module("ncl_agency_runtime.fpc.forecasting.strategy_prophet")
        assert hasattr(mod, "ProphetStrategy")

    def test_neuralforecast_module_exists(self):
        import importlib
        mod = importlib.import_module("ncl_agency_runtime.fpc.forecasting.strategy_neuralforecast")
        assert hasattr(mod, "NeuralForecastStrategy")

    def test_strategies_are_model_strategy_subclass(self):
        from ncl_agency_runtime.fpc.forecasting.base import ModelStrategy
        from ncl_agency_runtime.fpc.forecasting.strategy_chronos import ChronosStrategy
        from ncl_agency_runtime.fpc.forecasting.strategy_neuralforecast import NeuralForecastStrategy
        from ncl_agency_runtime.fpc.forecasting.strategy_prophet import ProphetStrategy
        from ncl_agency_runtime.fpc.forecasting.strategy_timesfm import TimesFMStrategy
        for cls in [ChronosStrategy, TimesFMStrategy, ProphetStrategy, NeuralForecastStrategy]:
            assert issubclass(cls, ModelStrategy), f"{cls.__name__} must subclass ModelStrategy"


# ── Data Sources ─────────────────────────────────────────────────────────────


class TestDataSources:
    def test_fred_ingester_no_key(self):
        from ncl_agency_runtime.fpc.data_sources import FREDIngester
        ing = FREDIngester(api_key="")
        signals = ing.fetch_series("GDP")
        assert signals == []

    def test_fred_default_indicators(self):
        from ncl_agency_runtime.fpc.data_sources import FRED_INDICATORS
        assert "GDP" in FRED_INDICATORS
        assert "CPIAUCSL" in FRED_INDICATORS
        assert len(FRED_INDICATORS) >= 5

    def test_alpha_vantage_no_key(self):
        from ncl_agency_runtime.fpc.data_sources import AlphaVantageIngester
        ing = AlphaVantageIngester(api_key="")
        signals = ing.fetch_daily("AAPL")
        assert signals == []

    def test_alpha_vantage_crypto_no_key(self):
        from ncl_agency_runtime.fpc.data_sources import AlphaVantageIngester
        AlphaVantageIngester(api_key="")


# ── Topic Mapper ─────────────────────────────────────────────────────────────

class TestTopicMapper:
    def test_init_loads_topics(self):
        from ncl_agency_runtime.fpc.topic_mapper import TopicMapper
        mapper = TopicMapper()
        assert len(mapper.topics_data.get("domains", {})) >= 10

    def test_crypto_topic_returns_crypto_sources(self):
        from ncl_agency_runtime.fpc.topic_mapper import TopicMapper
        mapper = TopicMapper()
        sources = mapper.sources_for_topic("bitcoin price prediction")
        assert "coingecko" in sources or "blockchain_com" in sources or "fear_greed" in sources

    def test_macro_topic_returns_macro_sources(self):
        from ncl_agency_runtime.fpc.topic_mapper import TopicMapper
        mapper = TopicMapper()
        sources = mapper.sources_for_topic("inflation GDP economy")
        assert any(s in sources for s in ["fred", "world_bank", "imf"])

    def test_unknown_topic_returns_fallback(self):
        from ncl_agency_runtime.fpc.topic_mapper import TopicMapper
        mapper = TopicMapper()
        sources = mapper.sources_for_topic("xyzzy_nonsense_completely_unknown")
        assert len(sources) >= 3

    def test_sources_for_tier(self):
        from ncl_agency_runtime.fpc.topic_mapper import TopicMapper
        mapper = TopicMapper()
        sources = mapper.sources_for_tier("tier_1_daily")
        assert len(sources) >= 5
        assert any(s in sources for s in ["coingecko", "fred", "fear_greed"])

    def test_tier_schedule(self):
        from ncl_agency_runtime.fpc.topic_mapper import TopicMapper
        mapper = TopicMapper()
        schedule = mapper.tier_schedule()
        assert "tier_1_daily" in schedule
        assert "tier_2_weekly" in schedule
        assert "tier_3_monthly" in schedule
        assert "tier_4_quarterly" in schedule
        for tier in schedule.values():
            assert "sources" in tier
            assert "key_feeds" in tier

    def test_all_domains(self):
        from ncl_agency_runtime.fpc.topic_mapper import TopicMapper
        mapper = TopicMapper()
        domains = mapper.all_domains()
        assert len(domains) >= 10
        assert "01_CRYPTO_DEFI" in domains

    def test_missing_file_returns_empty(self):
        from ncl_agency_runtime.fpc.topic_mapper import TopicMapper
        mapper = TopicMapper("nonexistent_file.json")
        sources = mapper.sources_for_topic("bitcoin")
        assert len(sources) >= 3  # Should return fallback

    def test_domain_sources_cover_all_domains(self):
        from ncl_agency_runtime.fpc.topic_mapper import DOMAIN_SOURCES, TopicMapper
        mapper = TopicMapper()
        for domain_id in mapper.all_domains():
            assert domain_id in DOMAIN_SOURCES, f"Missing DOMAIN_SOURCES entry for {domain_id}"


# ── Scraper ──────────────────────────────────────────────────────────────────

class TestScraper:
    def test_init(self, tmp_path):
        from ncl_agency_runtime.fpc.scraper import TopicScraper
        TopicScraper(cache_dir=str(tmp_path / "cache"))
        assert (tmp_path / "cache").is_dir()

    def test_cache_status_empty(self, tmp_path):
        from ncl_agency_runtime.fpc.scraper import TopicScraper
        scraper = TopicScraper(cache_dir=str(tmp_path / "cache"))
        status = scraper.cache_status()
        assert "tier_1_daily" in status
        for tier_info in status.values():
            assert tier_info["last_scraped"] is None
            assert tier_info["cached_signals"] == 0

    def test_latest_signals_empty(self, tmp_path):
        from ncl_agency_runtime.fpc.scraper import TopicScraper
        scraper = TopicScraper(cache_dir=str(tmp_path / "cache"))
        assert scraper.latest_signals() == []
        assert scraper.latest_signals("tier_1_daily") == []

    def test_latest_signals_from_cache(self, tmp_path):
        from ncl_agency_runtime.fpc.scraper import TopicScraper
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        # Write a fake cache file
        (cache_dir / "tier_1_daily_20260312_120000.json").write_text(
            json.dumps({"tier": "tier_1_daily", "signals": [{"source": "test", "title": "hi"}]}),
            encoding="utf-8",
        )
        scraper = TopicScraper(cache_dir=str(cache_dir))
        signals = scraper.latest_signals("tier_1_daily")
        assert len(signals) == 1
        assert signals[0]["source"] == "test"

    def test_tier_interval_days(self):
        from ncl_agency_runtime.fpc.scraper import TIER_INTERVAL_DAYS
        assert TIER_INTERVAL_DAYS["tier_1_daily"] == 1
        assert TIER_INTERVAL_DAYS["tier_2_weekly"] == 7
        assert TIER_INTERVAL_DAYS["tier_3_monthly"] == 30
        assert TIER_INTERVAL_DAYS["tier_4_quarterly"] == 90


# ── Signal-Fed Council ───────────────────────────────────────────────────────

class TestSignalFedCouncil:
    def test_convene_without_signals(self):
        from ncl_agency_runtime.fpc.heuristic_council import FuturePredictorCouncil, PredictionHorizon
        council = FuturePredictorCouncil()
        result = council.convene_council("test topic", PredictionHorizon.SHORT_TERM)
        assert len(result["predictions"]) == 4
        assert result.get("signal_fed") is False

    def test_convene_with_signals(self):
        from ncl_agency_runtime.fpc.heuristic_council import FuturePredictorCouncil, PredictionHorizon
        council = FuturePredictorCouncil()
        signal_context = {
            "signal_count": 1500,
            "sources": ["coingecko", "blockchain_com", "fear_greed", "defi_llama"],
            "summary": "1500 signals from 4 sources:\n  blockchain_com: 1400\n  coingecko: 50",
        }
        result = council.convene_council("bitcoin", PredictionHorizon.SHORT_TERM, signal_context)
        assert result["signal_fed"] is True
        assert len(result["predictions"]) == 4
        # Signal-fed predictions should reference signal count in outcome or evidence
        for pred in result["predictions"]:
            combined = pred["predicted_outcome"] + " ".join(pred["evidence"])
            assert "1500" in combined or "signal" in combined.lower()

    def test_heuristic_with_signal_context(self):
        from ncl_agency_runtime.fpc.heuristic_council import CouncilMember, FuturePredictorCouncil
        signal_context = {
            "signal_count": 200,
            "sources": ["fred", "world_bank"],
            "summary": "200 signals from 2 sources",
        }
        for spec in ["Pattern Recognition", "Risk Analysis", "Scenario Development", "Strategic Planning"]:
            member = CouncilMember("Test", spec, 0.25)
            outcome, conf, _risk, evidence = FuturePredictorCouncil._predict_heuristic(
                member, "economy", signal_context
            )
            assert "200" in outcome
            assert any("200" in e or "signal" in e.lower() for e in evidence)
            assert 0.0 <= conf <= 1.0

    def test_heuristic_without_signal_context(self):
        from ncl_agency_runtime.fpc.heuristic_council import CouncilMember, FuturePredictorCouncil
        member = CouncilMember("Test", "Pattern Recognition", 0.25)
        outcome, _conf, _risk, _evidence = FuturePredictorCouncil._predict_heuristic(
            member, "crypto", None
        )
        assert isinstance(outcome, str)
        assert "signal" not in outcome.lower() or "data" not in outcome.lower()


# ── ICM Pipeline Signal Flow ─────────────────────────────────────────────────

class TestICMSignalFlow:
    def test_build_signal_summary_empty(self):
        from ncl_agency_runtime.fpc.icm_pipeline import ICMPipeline
        summary = ICMPipeline._build_signal_summary([])
        assert "No signals" in summary

    def test_build_signal_summary_with_dicts(self):
        from ncl_agency_runtime.fpc.icm_pipeline import ICMPipeline
        signals = [
            {"source": "coingecko", "title": "BTC price $45000"},
            {"source": "coingecko", "title": "ETH price $3200"},
            {"source": "fear_greed", "title": "Fear & Greed Index: 72"},
        ]
        summary = ICMPipeline._build_signal_summary(signals)
        assert "3 signals" in summary
        assert "2 sources" in summary
        assert "coingecko" in summary

    def test_sources_for_topic_dynamic(self):
        from ncl_agency_runtime.fpc.icm_pipeline import ICMPipeline
        pipeline = ICMPipeline()
        sources = pipeline._sources_for_topic("bitcoin price trajectory")
        assert len(sources) >= 3
        assert any(s in sources for s in ["coingecko", "blockchain_com", "fear_greed"])


# ── Explainability ───────────────────────────────────────────────────────────


class TestExplainability:
    def test_explainer_init(self):
        from ncl_agency_runtime.fpc.explainability import ForecastExplainer
        ex = ForecastExplainer(method="kernel")
        assert ex.method == "kernel"

    def test_summary_text(self):
        from ncl_agency_runtime.fpc.explainability import ForecastExplainer
        explanation = {
            "method": "tree",
            "base_value": 0.5,
            "feature_importance": [
                {"feature": "lag_1", "importance": 0.42},
                {"feature": "lag_7", "importance": 0.31},
                {"feature": "trend", "importance": 0.15},
            ],
        }
        text = ForecastExplainer.summary_text(explanation, top_k=2)
        assert "tree" in text
        assert "lag_1" in text
        assert "lag_7" in text
        assert "trend" not in text  # top_k=2 excludes 3rd


# ── Council v2 ───────────────────────────────────────────────────────────────


class TestCouncilV2:
    def test_consensus_weighted(self):
        from ncl_agency_runtime.fpc.heuristic_council import FuturePredictorCouncil
        preds = [
            {"predicted_outcome": "growth", "confidence": 0.9, "weight": 0.5},
            {"predicted_outcome": "growth", "confidence": 0.6, "weight": 0.3},
            {"predicted_outcome": "decline", "confidence": 0.5, "weight": 0.2},
        ]
        c = FuturePredictorCouncil._consensus(preds)
        assert c["consensus_reached"] is True
        assert c["aggregation_method"] == "weighted"
        assert c["agreement_ratio"] > 0.5
        # weighted = (0.5*0.9 + 0.3*0.6 + 0.2*0.5) / 1.0 = 0.73
        assert c["average_confidence"] == pytest.approx(0.73, abs=0.01)

    def test_consensus_no_weight_fallback(self):
        from ncl_agency_runtime.fpc.heuristic_council import FuturePredictorCouncil
        preds = [
            {"predicted_outcome": "growth", "confidence": 0.8},
            {"predicted_outcome": "growth", "confidence": 0.7},
        ]
        c = FuturePredictorCouncil._consensus(preds)
        # equal weight: (0.5*0.8 + 0.5*0.7) / 1.0 = 0.75
        assert c["consensus_reached"] is True
        assert c["average_confidence"] == pytest.approx(0.75, abs=0.01)

    def test_status_has_strategies(self):
        from ncl_agency_runtime.fpc.heuristic_council import FuturePredictorCouncil
        council = FuturePredictorCouncil()
        status = council.get_council_status()
        assert "available_strategies" in status
        assert "StatsForecastStrategy" in status["available_strategies"]


# ── Config ───────────────────────────────────────────────────────────────────


_FPC_ROOT = Path(__file__).resolve().parent.parent


class TestConfig:
    def test_council_config_exists(self):
        path = _FPC_ROOT / "config" / "council_config.json"
        assert path.exists(), "config/council_config.json must exist"

    def test_council_config_valid_json(self):
        with open(_FPC_ROOT / "config" / "council_config.json") as f:
            cfg = json.load(f)
        assert "council_name" in cfg or "steering" in cfg

    def test_settings_json_exists(self):
        path = _FPC_ROOT / "config" / "settings.json"
        assert path.exists()
