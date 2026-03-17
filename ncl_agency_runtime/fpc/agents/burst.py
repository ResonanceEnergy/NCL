"""Cost-capped cloud burst helper for foundation model inference."""

from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class BurstConfig:
    cloud: str = "AWS"
    budget_weekly_usd: float = 50.0
    gpu_max_hourly: float = 1.20
    gpu_max_daily_min: int = 60
    ram_max_hourly: float = 0.80


@dataclass
class BurstSession:
    model: str
    instance_type: str
    start_time: float
    cost_estimate: float = 0.0
    duration_min: float = 0.0


def load_burst_config(config_path: str | pathlib.Path | None = None) -> BurstConfig:
    """Load burst limits from steering.json."""
    if config_path is None:
        config_path = pathlib.Path(__file__).resolve().parents[1] / "config" / "steering.json"
    path = pathlib.Path(config_path)
    if not path.exists():
        return BurstConfig()

    data = json.loads(path.read_text())
    return BurstConfig(
        cloud=data.get("cloud", "AWS"),
        budget_weekly_usd=data.get("budget_weekly_usd", 50.0),
        gpu_max_hourly=data.get("gpu_max_hourly", 1.20),
        gpu_max_daily_min=data.get("gpu_max_daily_min", 60),
        ram_max_hourly=data.get("ram_max_hourly", 0.80),
    )


# Instance recommendations per model
BURST_RECIPES: dict[str, dict[str, Any]] = {
    "chronos2": {
        "instance_type": "g5.xlarge",  # A10G GPU
        "hourly_cost": 1.006,
        "min_gpu_vram_gb": 24,
        "description": "Chronos-2 on A10G GPU — probabilistic forecasting",
    },
    "timesfm": {
        "instance_type": "r6i.2xlarge",  # 64 GB RAM
        "hourly_cost": 0.504,
        "min_ram_gb": 64,
        "description": "TimesFM 2.5 on high-memory CPU instance",
    },
}


def estimate_cost(model: str, duration_min: float) -> float:
    """Estimate burst cost for a model run."""
    recipe = BURST_RECIPES.get(model)
    if recipe is None:
        return 0.0
    return float(recipe["hourly_cost"]) * (duration_min / 60.0)


def can_burst(model: str, duration_min: float, config: BurstConfig | None = None) -> tuple[bool, str]:
    """Check if a burst session is within budget/time constraints."""
    if config is None:
        config = load_burst_config()

    recipe = BURST_RECIPES.get(model)
    if recipe is None:
        return False, f"Unknown model: {model}"

    cost = estimate_cost(model, duration_min)
    hourly = recipe["hourly_cost"]

    if hourly > config.gpu_max_hourly:
        return False, f"Hourly cost ${hourly:.2f} exceeds cap ${config.gpu_max_hourly:.2f}"

    if duration_min > config.gpu_max_daily_min:
        return False, f"Duration {duration_min}min exceeds daily cap {config.gpu_max_daily_min}min"

    if cost > config.budget_weekly_usd:
        return False, f"Estimated cost ${cost:.2f} exceeds weekly budget ${config.budget_weekly_usd:.2f}"

    return True, f"Approved: {model} on {recipe['instance_type']} for {duration_min}min (~${cost:.2f})"


def start_burst(model: str, duration_min: float = 30) -> BurstSession:
    """Start a burst session (stub — real impl launches cloud instance)."""
    ok, msg = can_burst(model, duration_min)
    if not ok:
        raise RuntimeError(f"Burst denied: {msg}")

    recipe = BURST_RECIPES[model]
    return BurstSession(
        model=model,
        instance_type=recipe["instance_type"],
        start_time=time.time(),
        cost_estimate=estimate_cost(model, duration_min),
        duration_min=duration_min,
    )
