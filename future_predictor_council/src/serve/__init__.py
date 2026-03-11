"""FastAPI serve layer — ensemble + council endpoints.

Endpoints:
    GET  /health           – liveness check
    POST /forecast         – run ensemble forecast on data
    POST /explain          – XAI panel (stub)
    POST /whatif           – causal what-if intervention (stub)
    POST /council/convene  – run a council prediction session
    GET  /council/status   – current council status
    GET  /predictions      – list tracked predictions
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ..council.base import ModelStrategy
from ..council.ensemble import WeightedEnsemble
from ..council.strategy_statsforecast import StatsForecastStrategy
from ..council_orchestrator import FuturePredictorCouncil, PredictionHorizon
from ..tracker import PredictionTracker

app = FastAPI(title="Future Predictor Council", version="0.3.0")

# ── Global state (loaded on startup) ────────────────────────────
_ensemble: WeightedEnsemble | None = None
_steering: dict[str, Any] = {}
_council: FuturePredictorCouncil | None = None
_tracker: PredictionTracker | None = None

STEERING_PATH = pathlib.Path(__file__).resolve().parents[2] / "config" / "steering.json"
COUNCIL_PATH = pathlib.Path(__file__).resolve().parents[2] / "config" / "council_config.json"


# ── Request models ──────────────────────────────────────────────

class ForecastRequest(BaseModel):
    data: list[dict[str, Any]]
    freq: str = "D"
    h: int = 14
    quantiles: list[float] = [0.1, 0.5, 0.9]


class WhatIfRequest(BaseModel):
    data: list[dict[str, Any]]
    intervention: dict[str, float]
    outcome: str = "y"
    features: list[str] = []


class ConveneRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    horizon: str = Field(default="medium", pattern="^(short|medium|long|strategic)$")


# ── Startup ─────────────────────────────────────────────────────

@app.on_event("startup")
def _load() -> None:
    global _ensemble, _steering, _council, _tracker
    if STEERING_PATH.exists():
        _steering = json.loads(STEERING_PATH.read_text())

    strategies: list[ModelStrategy] = [StatsForecastStrategy()]
    _ensemble = WeightedEnsemble(strategies)

    config_path = str(COUNCIL_PATH) if COUNCIL_PATH.exists() else "config/council_config.json"
    _council = FuturePredictorCouncil(config_path)
    _tracker = PredictionTracker()


# ── Ensemble endpoints ──────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.3.0"}


@app.post("/forecast")
def forecast(req: ForecastRequest) -> dict[str, Any]:
    if _ensemble is None:
        raise HTTPException(503, "Ensemble not loaded")

    df = pd.DataFrame(req.data)
    _ensemble.fit(df, req.freq, h=req.h)
    result = _ensemble.predict(req.h, tuple(req.quantiles))

    return {
        "yhat": result.yhat.tolist(),
        "quantiles": {str(k): v.tolist() for k, v in result.quantiles.items()},
        "meta": result.meta,
    }


@app.post("/explain")
def explain(req: ForecastRequest) -> dict[str, Any]:
    return {"status": "stub", "message": "XAI panel integration pending"}


@app.post("/whatif")
def whatif(req: WhatIfRequest) -> dict[str, Any]:
    return {"status": "stub", "message": "Causal what-if integration pending"}


# ── Council endpoints ───────────────────────────────────────────

@app.post("/council/convene")
def convene(req: ConveneRequest) -> dict[str, Any]:
    if _council is None:
        raise HTTPException(503, "Council not loaded")

    horizon_map = {
        "short": PredictionHorizon.SHORT_TERM,
        "medium": PredictionHorizon.MEDIUM_TERM,
        "long": PredictionHorizon.LONG_TERM,
        "strategic": PredictionHorizon.STRATEGIC,
    }
    result = _council.convene_council(req.topic, horizon_map[req.horizon])
    # Track predictions
    if _tracker:
        for pred in result.get("predictions", []):
            _tracker.record(pred)
    return result


@app.get("/council/status")
def council_status() -> dict[str, Any]:
    if _council is None:
        raise HTTPException(503, "Council not loaded")
    return _council.get_council_status()


@app.get("/predictions")
def list_predictions() -> list[dict[str, Any]]:
    if _tracker is None:
        return []
    return _tracker.list_all()
