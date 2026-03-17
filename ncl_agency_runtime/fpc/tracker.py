"""Prediction accuracy tracker — version, store, and score predictions.

Uses SQLite persistence layer (state/fpc.db) for concurrent-safe storage.
Falls back to JSON file if SQLite is unavailable.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TRACKER_FILE = Path("state/predictions.json")


def _use_sqlite() -> bool:
    """Check if SQLite persistence is available."""
    try:
        from . import persistence  # noqa: F401
        return True
    except ImportError:
        return False


class PredictionTracker:
    """Persist predictions and score them against actual outcomes.

    Prefers SQLite (via persistence.PredictionStore) when available,
    falls back to JSON file storage.
    """

    def __init__(self, path: Path | None = None):
        self._sqlite = None
        if not path and _use_sqlite():
            from .persistence import PredictionStore
            self._sqlite = PredictionStore()
        self.path = path or TRACKER_FILE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self._sqlite:
            self._predictions: list[dict[str, Any]] = self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> list[dict[str, Any]]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("Corrupt tracker file — starting fresh")
        return []

    def _save(self):
        self.path.write_text(
            json.dumps(self._predictions, indent=2, default=str), encoding="utf-8"
        )

    # ── Record & resolve ─────────────────────────────────────────────────────

    def record(self, prediction: dict[str, Any]) -> dict[str, Any]:
        """Record a new prediction. Auto-versions with timestamp."""
        if self._sqlite:
            return self._sqlite.record(prediction)

        entry = {
            "id": prediction.get("id", f"pred_{len(self._predictions)}"),
            "topic": prediction.get("topic", ""),
            "predicted_outcome": prediction.get("predicted_outcome", ""),
            "confidence": prediction.get("confidence", 0),
            "risk_level": str(prediction.get("risk_level", "")),
            "council_member": prediction.get("council_member", ""),
            "recorded_at": datetime.now().isoformat(),
            "resolved": False,
            "actual_outcome": None,
            "accuracy_score": None,
        }
        self._predictions.append(entry)
        self._save()
        logger.info("Tracked prediction %s", entry["id"])
        return entry

    def resolve(self, prediction_id: str, actual_outcome: str, score: float) -> bool:
        """Resolve a prediction with the actual outcome and an accuracy score (0-1)."""
        if self._sqlite:
            return self._sqlite.resolve(prediction_id, actual_outcome, score)

        for p in self._predictions:
            if p["id"] == prediction_id and not p["resolved"]:
                p["resolved"] = True
                p["actual_outcome"] = actual_outcome
                p["accuracy_score"] = max(0.0, min(1.0, score))
                p["resolved_at"] = datetime.now().isoformat()
                self._save()
                logger.info("Resolved prediction %s (score=%.2f)", prediction_id, score)
                return True
        return False

    # ── Queries ──────────────────────────────────────────────────────────────

    def list_all(self) -> list[dict[str, Any]]:
        if self._sqlite:
            return self._sqlite.list_all()
        return list(self._predictions)

    def list_unresolved(self) -> list[dict[str, Any]]:
        if self._sqlite:
            return self._sqlite.list_unresolved()
        return [p for p in self._predictions if not p["resolved"]]

    def accuracy_summary(self) -> dict[str, Any]:
        """Return aggregate accuracy stats for resolved predictions."""
        if self._sqlite:
            return self._sqlite.accuracy_summary()

        resolved = [p for p in self._predictions if p["resolved"] and p["accuracy_score"] is not None]
        if not resolved:
            return {"total": 0, "resolved": 0, "avg_accuracy": None}
        scores = [p["accuracy_score"] for p in resolved]
        return {
            "total": len(self._predictions),
            "resolved": len(resolved),
            "avg_accuracy": sum(scores) / len(scores),
            "best": max(scores),
            "worst": min(scores),
        }
