"""Smoke tests for the Future Predictor Council."""

from __future__ import annotations

import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "raw" / "example.csv"
CONFIG_PATH = ROOT / "config" / "steering.json"


def test_example_data_loads():
    df = pd.read_csv(DATA_PATH)
    assert len(df) > 0
    assert set(df.columns) >= {"unique_id", "ds", "y"}


def test_steering_config_loads():
    data = json.loads(CONFIG_PATH.read_text())
    assert data["metric_gate"] == "MASE"
    assert data["budget_weekly_usd"] > 0


def test_base_imports():
    from future_predictor_council.src.council.base import ForecastResult, ModelStrategy

    assert hasattr(ModelStrategy, "fit")
    assert hasattr(ModelStrategy, "predict")
    assert "yhat" in ForecastResult.__dataclass_fields__


def test_statsforecast_strategy_init():
    from future_predictor_council.src.council.strategy_statsforecast import StatsForecastStrategy

    s = StatsForecastStrategy()
    assert s.name == "statsforecast_auto"


def test_ensemble_equal_weights():
    from future_predictor_council.src.council.ensemble import WeightedEnsemble
    from future_predictor_council.src.council.strategy_statsforecast import StatsForecastStrategy

    strategies: list = [StatsForecastStrategy(), StatsForecastStrategy()]
    ens = WeightedEnsemble(strategies)
    assert len(ens._weights) == 2
    assert abs(sum(ens._weights) - 1.0) < 1e-9


def test_mase_metric():
    from future_predictor_council.src.eval import mase

    # Perfect prediction
    assert mase([1, 2, 3], [1, 2, 3], [1, 2, 3, 4, 5], seasonality=1) == 0.0


def test_smape_metric():
    from future_predictor_council.src.eval import smape

    # Perfect prediction
    assert smape([1, 2, 3], [1, 2, 3]) == 0.0
    # Symmetric
    s1 = smape([100], [110])
    s2 = smape([110], [100])
    assert abs(s1 - s2) < 1e-9


def test_agent_roles_loaded():
    from future_predictor_council.src.agents import LAUNCH_SQUADRON, get_agent

    assert len(LAUNCH_SQUADRON) == 10
    mc = get_agent("mc")
    assert mc is not None
    assert mc.name == "Mission Control"


def test_burst_config_loads():
    from future_predictor_council.src.agents.burst import BURST_RECIPES, load_burst_config

    config = load_burst_config(CONFIG_PATH)
    assert config.budget_weekly_usd == 50.0
    assert "chronos2" in BURST_RECIPES
    assert "timesfm" in BURST_RECIPES


def test_burst_cost_check():
    from future_predictor_council.src.agents.burst import BurstConfig, can_burst

    config = BurstConfig(budget_weekly_usd=50, gpu_max_hourly=1.20, gpu_max_daily_min=60)
    ok, _msg = can_burst("chronos2", 30, config)
    assert ok


def test_orchestrator_launch_plan():
    from future_predictor_council.src.agents.orchestrator import build_launch_plan

    plan = build_launch_plan()
    assert len(plan) == 10
    assert plan[0].agent_codename == "ds"
    assert plan[-1].requires_approval


def test_release_policy_loads():
    policy_path = ROOT / "ops" / "ReleasePolicy.yaml"
    assert policy_path.exists()
    # Just verify it's valid YAML
    import yaml  # type: ignore[import-untyped]

    with open(policy_path) as f:
        data = yaml.safe_load(f)
    assert "channels" in data
    assert "alpha" in data["channels"]
