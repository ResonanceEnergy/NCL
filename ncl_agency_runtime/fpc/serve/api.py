"""Future Predictor Council — FastAPI application.

Endpoints:
    GET  /health          – liveness check
    POST /council/convene – run a council session on a topic
    GET  /council/status  – current council status
    POST /forecast/run    – run a statistical backtest
    GET  /predictions     – list tracked predictions
    GET  /dashboard       – command center summary
    GET  /alerts          – active alerts
    POST /alerts/scan     – trigger alert scan
    POST /alerts/{id}/ack – acknowledge an alert
    GET  /rank            – ranked prediction leaderboard
"""

import logging
import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from ..heuristic_council import FuturePredictorCouncil, PredictionHorizon
from ..tracker import PredictionTracker

logger = logging.getLogger(__name__)
app = FastAPI(title="Future Predictor Council", version="0.3.0")

# ── Auth ─────────────────────────────────────────────────────────────────────

_bearer = HTTPBearer()


def _load_api_token() -> str:
    """Load FPC_API_TOKEN from .env or environment, or generate one."""
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("FPC_API_TOKEN=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip()
    return os.getenv("FPC_API_TOKEN", "")


_API_TOKEN = _load_api_token()
if not _API_TOKEN:
    _API_TOKEN = secrets.token_urlsafe(32)
    logger.warning(
        "No FPC_API_TOKEN in .env — generated ephemeral token: %s", _API_TOKEN
    )


def verify_token(
    creds: HTTPAuthorizationCredentials = Security(_bearer),
) -> str:
    """Validate Bearer token against FPC_API_TOKEN."""
    if not secrets.compare_digest(creds.credentials, _API_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid or missing API token")
    return creds.credentials

# Singletons
_council = FuturePredictorCouncil()
_tracker = PredictionTracker()


# ── Request / Response models ────────────────────────────────────────────────

class ConveneRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    horizon: str = Field(default="medium", pattern="^(short|medium|long|strategic)$")


class ForecastRequest(BaseModel):
    data_path: str = Field(default="data/raw/example.csv")
    freq: str = Field(default="D")
    h: int = Field(default=14, ge=1, le=365)
    n_windows: int = Field(default=3, ge=1, le=20)


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/council/convene")
def convene(req: ConveneRequest, _token: str = Depends(verify_token)):
    horizon_map = {
        "short": PredictionHorizon.SHORT_TERM,
        "medium": PredictionHorizon.MEDIUM_TERM,
        "long": PredictionHorizon.LONG_TERM,
        "strategic": PredictionHorizon.STRATEGIC,
    }
    result = _council.convene_council(req.topic, horizon_map[req.horizon])
    # Track predictions
    for pred in result.get("predictions", []):
        _tracker.record(pred)
    return result


@app.get("/council/status")
def council_status(_token: str = Depends(verify_token)):
    return _council.get_council_status()


@app.post("/forecast/run")
def run_forecast(req: ForecastRequest, _token: str = Depends(verify_token)):
    from pathlib import Path

    import pandas as pd

    from ..eval import rolling_backtest
    from ..forecasting import StatsForecastStrategy

    csv_path = Path(req.data_path)
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail=f"Data file not found: {req.data_path}")

    df = pd.read_csv(csv_path, parse_dates=["ds"])
    model = StatsForecastStrategy()
    report = rolling_backtest(df, model, freq=req.freq, h=req.h, n_windows=req.n_windows, seasonal_m=7)
    return report.to_dict(orient="records")


@app.get("/predictions")
def list_predictions(_token: str = Depends(verify_token)):
    return _tracker.list_all()


# ── Dashboard / Alerts / Ranking endpoints ───────────────────────────────────

@app.get("/dashboard")
def dashboard(_token: str = Depends(verify_token)):
    """Command center summary: alerts, predictions, domain health."""
    from ..alerting import AlertEngine
    from ..signal_scorer import SignalScorer

    engine = AlertEngine()
    engine.scan()

    scorer = SignalScorer()
    return {
        "alerts": engine.summary(),
        "active_alerts": engine.get_active_alerts()[:10],
        "ranked_predictions": scorer.rank_predictions()[:10],
        "domain_health": scorer.domain_health(),
        "member_accuracy": scorer.member_accuracy(),
    }


@app.get("/alerts")
def get_alerts(level: str | None = None, _token: str = Depends(verify_token)):
    """Get active alerts, optionally filtered by level."""
    from ..alerting import AlertEngine
    engine = AlertEngine()
    return engine.get_active_alerts(level)


@app.post("/alerts/scan")
def scan_alerts(_token: str = Depends(verify_token)):
    """Trigger a full alert scan."""
    from ..alerting import AlertEngine
    engine = AlertEngine()
    new = engine.scan()
    return {"new_alerts": len(new), "alerts": new}


@app.post("/alerts/{alert_id}/ack")
def acknowledge_alert(alert_id: str, _token: str = Depends(verify_token)):
    """Acknowledge a specific alert."""
    from ..alerting import AlertEngine
    engine = AlertEngine()
    if engine.acknowledge(alert_id):
        return {"status": "acknowledged", "id": alert_id}
    raise HTTPException(status_code=404, detail=f"Alert not found: {alert_id}")


@app.get("/rank")
def ranked_predictions(include_resolved: bool = False, limit: int = 25, _token: str = Depends(verify_token)):
    """Get predictions ranked by impact score."""
    from ..signal_scorer import SignalScorer
    scorer = SignalScorer()
    return scorer.rank_predictions(include_resolved=include_resolved)[:limit]
