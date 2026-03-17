"""Flywheel feed — emit JSON status for the SuperAgency Repo Depot pipeline."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STATE_DIR = Path("state")
FEED_FILE = STATE_DIR / "flywheel_feed.json"


def emit_status(
    stage: str = "idle",
    detail: str = "",
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write current flywheel status to state/flywheel_feed.json.

    Parameters
    ----------
    stage : str
        Current pipeline stage, e.g. "ingestion", "council", "backtest", "idle".
    detail : str
        Human-readable detail message.
    metrics : dict, optional
        Arbitrary key/value metrics to include.

    Returns the status dict that was written.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    status: dict[str, Any] = {
        "repo": "future-predictor-council",
        "stage": stage,
        "detail": detail,
        "timestamp": datetime.now().isoformat(),
        "metrics": metrics or {},
    }

    FEED_FILE.write_text(json.dumps(status, indent=2), encoding="utf-8")
    logger.info("Flywheel status → %s : %s", stage, detail)
    return status


def read_status() -> dict[str, Any]:
    """Read the latest flywheel status."""
    if FEED_FILE.exists():
        return json.loads(FEED_FILE.read_text(encoding="utf-8"))
    return {"stage": "unknown", "detail": "No status file found"}
