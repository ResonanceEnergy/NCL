"""Integration tests for FPC v0.3.0 modules merged into NCL.

Covers: council_orchestrator, tracker, reports, ingestion, data_sources,
        explainability, flywheel_feed, strategy_prophet, council_config.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_FPC_CONFIG = ROOT / "ncl_agency_runtime" / "fpc" / "config"


# ── Version & public imports ────────────────────────────────────


def test_version():
    from ncl_agency_runtime.fpc import __version__
    assert __version__ == "0.6.0"


def test_public_imports():
    from ncl_agency_runtime.fpc import FuturePredictorCouncil, PredictionHorizon, RiskLevel
    assert FuturePredictorCouncil is not None
    assert len(PredictionHorizon) == 4
    assert len(RiskLevel) == 4


# ── Council orchestrator ────────────────────────────────────────


class TestCouncilOrchestrator:
    def test_init_defaults(self):
        from ncl_agency_runtime.fpc.council_orchestrator import FuturePredictorCouncil
        council = FuturePredictorCouncil()
        assert len(council.council_members) == 4
        assert council.session_id.startswith("council_")

    def test_convene_returns_predictions(self):
        from ncl_agency_runtime.fpc.council_orchestrator import (
            FuturePredictorCouncil,
            PredictionHorizon,
        )
        council = FuturePredictorCouncil()
        result = council.convene_council("AI adoption", PredictionHorizon.SHORT_TERM)
        assert result["topic"] == "AI adoption"
        assert result["horizon"] == "1-3 months"
        assert len(result["predictions"]) == 4

    def test_consensus_calculated(self):
        from ncl_agency_runtime.fpc.council_orchestrator import (
            FuturePredictorCouncil,
            PredictionHorizon,
        )
        council = FuturePredictorCouncil()
        result = council.convene_council("test", PredictionHorizon.MEDIUM_TERM)
        assert "consensus" in result
        assert isinstance(result["consensus"]["consensus_reached"], bool)
        assert result["consensus"]["participant_count"] == 4

    def test_consensus_empty(self):
        from ncl_agency_runtime.fpc.council_orchestrator import FuturePredictorCouncil
        council = FuturePredictorCouncil()
        c = council._consensus([])
        assert c["consensus_reached"] is False

    def test_prediction_confidence_range(self):
        from ncl_agency_runtime.fpc.council_orchestrator import (
            FuturePredictorCouncil,
            PredictionHorizon,
        )
        council = FuturePredictorCouncil()
        result = council.convene_council("test", PredictionHorizon.LONG_TERM)
        for pred in result["predictions"]:
            assert 0.0 <= pred["confidence"] <= 1.0

    def test_get_council_status(self):
        from ncl_agency_runtime.fpc.council_orchestrator import FuturePredictorCouncil
        council = FuturePredictorCouncil()
        status = council.get_council_status()
        assert status["active_members"] == 4
        assert status["council_name"] == "Future Predictor Council"

    def test_heuristic_all_specialties(self):
        from ncl_agency_runtime.fpc.council_orchestrator import (
            CouncilMember,
            FuturePredictorCouncil,
        )
        for spec in ["Pattern Recognition", "Risk Analysis", "Scenario Development", "Strategic Planning"]:
            member = CouncilMember("Test", spec, 0.25)
            outcome, conf, _risk, evidence = FuturePredictorCouncil._predict_heuristic(member, "crypto")
            assert isinstance(outcome, str)
            assert 0.0 <= conf <= 1.0
            assert len(evidence) > 0

    def test_consensus_weighted(self):
        from ncl_agency_runtime.fpc.council_orchestrator import FuturePredictorCouncil
        preds = [
            {"predicted_outcome": "growth", "confidence": 0.9, "weight": 0.5},
            {"predicted_outcome": "growth", "confidence": 0.6, "weight": 0.3},
            {"predicted_outcome": "decline", "confidence": 0.5, "weight": 0.2},
        ]
        c = FuturePredictorCouncil._consensus(preds)
        assert c["consensus_reached"] is True
        assert c["aggregation_method"] == "weighted"
        assert c["agreement_ratio"] > 0.5
        assert c["average_confidence"] == pytest.approx(0.73, abs=0.01)

    def test_consensus_no_weight_fallback(self):
        from ncl_agency_runtime.fpc.council_orchestrator import FuturePredictorCouncil
        preds = [
            {"predicted_outcome": "growth", "confidence": 0.8},
            {"predicted_outcome": "growth", "confidence": 0.7},
        ]
        c = FuturePredictorCouncil._consensus(preds)
        assert c["consensus_reached"] is True
        assert c["average_confidence"] == pytest.approx(0.75, abs=0.01)

    def test_status_has_strategies(self):
        from ncl_agency_runtime.fpc.council_orchestrator import FuturePredictorCouncil
        council = FuturePredictorCouncil()
        status = council.get_council_status()
        assert "available_strategies" in status
        assert "StatsForecastStrategy" in status["available_strategies"]


# ── Tracker ─────────────────────────────────────────────────────


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


# ── Report generator ────────────────────────────────────────────


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
                {"council_member": "A", "predicted_outcome": "growth", "confidence": 0.8,
                 "risk_level": "low", "evidence": ["data"]},
            ],
        }
        paths = rg.generate(session)
        assert Path(paths["json_path"]).exists()
        assert Path(paths["md_path"]).exists()
        md_content = Path(paths["md_path"]).read_text()
        assert "test topic" in md_content


# ── Flywheel feed ───────────────────────────────────────────────


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


# ── Ingestion ───────────────────────────────────────────────────


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


# ── Data Sources ────────────────────────────────────────────────


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
        ing = AlphaVantageIngester(api_key="")
        signals = ing.fetch_crypto("BTC")
        assert signals == []


# ── Explainability ──────────────────────────────────────────────


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


# ── Prophet strategy ───────────────────────────────────────────


class TestProphetStrategy:
    def test_import_and_name(self):
        from ncl_agency_runtime.fpc.council.strategy_prophet import ProphetStrategy
        s = ProphetStrategy()
        assert s.name == "prophet_additive"


# ── Config ──────────────────────────────────────────────────────


class TestConfig:
    def test_council_config_exists(self):
        path = _FPC_CONFIG / "council_config.json"
        assert path.exists(), "config/council_config.json must exist"

    def test_council_config_valid_json(self):
        with open(_FPC_CONFIG / "council_config.json") as f:
            cfg = json.load(f)
        assert "council_name" in cfg
        assert "council_members" in cfg
        assert isinstance(cfg["council_members"], list)
        assert len(cfg["council_members"]) >= 1

    def test_steering_config_still_exists(self):
        path = _FPC_CONFIG / "steering.json"
        assert path.exists(), "config/steering.json must still exist"
