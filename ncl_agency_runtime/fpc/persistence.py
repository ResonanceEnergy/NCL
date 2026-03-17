"""SQLite persistence layer — concurrent-safe storage for predictions, alerts, and status.

Replaces JSON file storage with SQLite for:
  - Thread-safe concurrent access (multiple CLI invocations)
  - Better querying (filter by date, status, level)
  - Automatic migration from existing JSON files on first use

Database: state/fpc.db
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DB_DIR = Path("state")
DB_PATH = DB_DIR / "fpc.db"

# JSON files we can migrate from
_JSON_PREDICTIONS = DB_DIR / "predictions.json"
_JSON_ALERTS = DB_DIR / "alerts.json"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    predicted_outcome TEXT,
    confidence REAL DEFAULT 0,
    risk_level TEXT,
    council_member TEXT,
    recorded_at TEXT NOT NULL,
    resolved INTEGER DEFAULT 0,
    actual_outcome TEXT,
    accuracy_score REAL,
    resolved_at TEXT,
    extra TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    level TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT,
    source TEXT DEFAULT 'system',
    data TEXT,
    created_at TEXT NOT NULL,
    acknowledged INTEGER DEFAULT 0,
    acknowledged_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_predictions_topic ON predictions(topic);
CREATE INDEX IF NOT EXISTS idx_predictions_resolved ON predictions(resolved);
CREATE INDEX IF NOT EXISTS idx_alerts_level ON alerts(level);
CREATE INDEX IF NOT EXISTS idx_alerts_acknowledged ON alerts(acknowledged);
CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at);
"""


def _get_connection() -> sqlite3.Connection:
    """Create or open the SQLite database with WAL mode for concurrent reads."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


def _migrate_json():
    """One-time migration: load existing JSON files into SQLite."""
    conn = _get_connection()
    try:
        # Migrate predictions
        if _JSON_PREDICTIONS.exists():
            try:
                preds = json.loads(_JSON_PREDICTIONS.read_text(encoding="utf-8"))
                if isinstance(preds, list) and preds:
                    for p in preds:
                        _upsert_prediction(conn, p)
                    conn.commit()
                    # Rename old file as backup
                    backup = _JSON_PREDICTIONS.with_suffix(".json.bak")
                    _JSON_PREDICTIONS.rename(backup)
                    logger.info("Migrated %d predictions from JSON → SQLite", len(preds))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not migrate predictions JSON: %s", exc)

        # Migrate alerts
        if _JSON_ALERTS.exists():
            try:
                alerts = json.loads(_JSON_ALERTS.read_text(encoding="utf-8"))
                if isinstance(alerts, list) and alerts:
                    for a in alerts:
                        _upsert_alert(conn, a)
                    conn.commit()
                    backup = _JSON_ALERTS.with_suffix(".json.bak")
                    _JSON_ALERTS.rename(backup)
                    logger.info("Migrated %d alerts from JSON → SQLite", len(alerts))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not migrate alerts JSON: %s", exc)
    finally:
        conn.close()


def _upsert_prediction(conn: sqlite3.Connection, p: dict):
    """Insert or ignore a prediction row."""
    conn.execute(
        """INSERT OR IGNORE INTO predictions
           (id, topic, predicted_outcome, confidence, risk_level,
            council_member, recorded_at, resolved, actual_outcome,
            accuracy_score, resolved_at, extra)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            p.get("id", ""),
            p.get("topic", ""),
            p.get("predicted_outcome", ""),
            p.get("confidence", 0),
            str(p.get("risk_level", "")),
            p.get("council_member", ""),
            p.get("recorded_at", datetime.now().isoformat()),
            1 if p.get("resolved") else 0,
            p.get("actual_outcome"),
            p.get("accuracy_score"),
            p.get("resolved_at"),
            json.dumps({k: v for k, v in p.items()
                        if k not in ("id", "topic", "predicted_outcome", "confidence",
                                     "risk_level", "council_member", "recorded_at",
                                     "resolved", "actual_outcome", "accuracy_score",
                                     "resolved_at")}, default=str) or None,
        ),
    )


def _upsert_alert(conn: sqlite3.Connection, a: dict):
    """Insert or ignore an alert row."""
    data_json = a.get("data")
    if isinstance(data_json, dict):
        data_json = json.dumps(data_json, default=str)
    conn.execute(
        """INSERT OR IGNORE INTO alerts
           (id, level, category, title, detail, source, data,
            created_at, acknowledged, acknowledged_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            a.get("id", ""),
            a.get("level", "LOW"),
            a.get("category", ""),
            a.get("title", ""),
            a.get("detail", ""),
            a.get("source", "system"),
            data_json,
            a.get("created_at", datetime.now().isoformat()),
            1 if a.get("acknowledged") else 0,
            a.get("acknowledged_at"),
        ),
    )


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row)


# ── Public API: Predictions ─────────────────────────────────────────────────

class PredictionStore:
    """SQLite-backed prediction storage — drop-in replacement for PredictionTracker."""

    def __init__(self):
        self._ensure_db()

    @staticmethod
    def _ensure_db():
        conn = _get_connection()
        conn.close()

    def record(self, prediction: dict[str, Any]) -> dict[str, Any]:
        _CORE_KEYS = {"id", "topic", "predicted_outcome", "confidence", "risk_level",
                       "council_member", "recorded_at", "resolved", "actual_outcome",
                       "accuracy_score", "resolved_at"}
        entry = {
            "id": prediction.get("id", f"pred_{datetime.now().strftime('%Y%m%d%H%M%S')}"),
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
        # Preserve caller-supplied extra fields (e.g. scorer_domain)
        for k, v in prediction.items():
            if k not in _CORE_KEYS and k not in entry:
                entry[k] = v
        conn = _get_connection()
        try:
            _upsert_prediction(conn, entry)
            conn.commit()
        finally:
            conn.close()
        logger.info("Tracked prediction %s (SQLite)", entry["id"])
        return entry

    def resolve(self, prediction_id: str, actual_outcome: str, score: float) -> bool:
        score = max(0.0, min(1.0, score))
        conn = _get_connection()
        try:
            cur = conn.execute(
                """UPDATE predictions
                   SET resolved=1, actual_outcome=?, accuracy_score=?, resolved_at=?
                   WHERE id=? AND resolved=0""",
                (actual_outcome, score, datetime.now().isoformat(), prediction_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def list_all(self) -> list[dict[str, Any]]:
        conn = _get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM predictions ORDER BY recorded_at DESC"
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def list_unresolved(self) -> list[dict[str, Any]]:
        conn = _get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM predictions WHERE resolved=0 ORDER BY recorded_at DESC"
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def accuracy_summary(self) -> dict[str, Any]:
        conn = _get_connection()
        try:
            row = conn.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN resolved=1 THEN 1 ELSE 0 END) as resolved,
                       AVG(CASE WHEN resolved=1 THEN accuracy_score END) as avg_accuracy,
                       MAX(CASE WHEN resolved=1 THEN accuracy_score END) as best,
                       MIN(CASE WHEN resolved=1 THEN accuracy_score END) as worst
                FROM predictions
            """).fetchone()
            return {
                "total": row["total"],
                "resolved": row["resolved"],
                "avg_accuracy": row["avg_accuracy"],
                "best": row["best"],
                "worst": row["worst"],
            }
        finally:
            conn.close()


# ── Public API: Alerts ───────────────────────────────────────────────────────

class AlertStore:
    """SQLite-backed alert storage — used by AlertEngine."""

    def __init__(self):
        self._ensure_db()

    @staticmethod
    def _ensure_db():
        conn = _get_connection()
        conn.close()

    def add(self, alert_dict: dict[str, Any]) -> dict[str, Any]:
        conn = _get_connection()
        try:
            _upsert_alert(conn, alert_dict)
            conn.commit()
        finally:
            conn.close()
        return alert_dict

    def get_all(self) -> list[dict[str, Any]]:
        conn = _get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM alerts ORDER BY created_at DESC"
            ).fetchall()
            result = []
            for r in rows:
                d = _row_to_dict(r)
                # Parse data JSON back to dict
                if d.get("data") and isinstance(d["data"], str):
                    try:
                        d["data"] = json.loads(d["data"])
                    except json.JSONDecodeError:
                        d["data"] = {}
                d["acknowledged"] = bool(d["acknowledged"])
                result.append(d)
            return result
        finally:
            conn.close()

    def get_active(self, level: str | None = None) -> list[dict[str, Any]]:
        conn = _get_connection()
        try:
            if level:
                rows = conn.execute(
                    "SELECT * FROM alerts WHERE acknowledged=0 AND level=? ORDER BY created_at DESC",
                    (level,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM alerts WHERE acknowledged=0 ORDER BY created_at DESC"
                ).fetchall()
            result = []
            for r in rows:
                d = _row_to_dict(r)
                if d.get("data") and isinstance(d["data"], str):
                    try:
                        d["data"] = json.loads(d["data"])
                    except json.JSONDecodeError:
                        d["data"] = {}
                d["acknowledged"] = False
                result.append(d)
            return result
        finally:
            conn.close()

    def acknowledge(self, alert_id: str) -> bool:
        conn = _get_connection()
        try:
            cur = conn.execute(
                "UPDATE alerts SET acknowledged=1, acknowledged_at=? WHERE id=?",
                (datetime.now().isoformat(), alert_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def acknowledge_all(self) -> int:
        conn = _get_connection()
        try:
            cur = conn.execute(
                "UPDATE alerts SET acknowledged=1, acknowledged_at=? WHERE acknowledged=0",
                (datetime.now().isoformat(),),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def exists_recent(self, category: str, level: str, hours: int = 1) -> bool:
        """Check if a similar alert exists within the last N hours."""
        conn = _get_connection()
        try:
            from datetime import timedelta
            cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM alerts
                   WHERE category=? AND level=? AND acknowledged=0
                   AND created_at > ?""",
                (category, level, cutoff),
            ).fetchone()
            return row["cnt"] > 0
        finally:
            conn.close()


# ── Migration entrypoint ────────────────────────────────────────────────────

def init_db():
    """Initialize the database and run any pending migrations."""
    conn = _get_connection()
    conn.close()
    _migrate_json()
    logger.info("SQLite database ready at %s", DB_PATH)
