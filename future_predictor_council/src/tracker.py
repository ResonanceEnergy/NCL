"""Prediction accuracy tracker — version, store, and score predictions."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TRACKER_FILE = Path("state/predictions.json")


class PredictionTracker:
    """Persist predictions and score them against actual outcomes."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or TRACKER_FILE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._predictions: List[Dict[str, Any]] = self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> List[Dict[str, Any]]:
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

    def record(self, prediction: Dict[str, Any]) -> Dict[str, Any]:
        """Record a new prediction. Auto-versions with timestamp."""
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

    def list_all(self) -> List[Dict[str, Any]]:
        return list(self._predictions)

    def list_unresolved(self) -> List[Dict[str, Any]]:
        return [p for p in self._predictions if not p["resolved"]]

    def accuracy_summary(self) -> Dict[str, Any]:
        """Return aggregate accuracy stats for resolved predictions."""
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
