"""Alerting engine — detect anomalies, flag breaking signals, route alerts.

Monitors predictions and signal cache for conditions that need immediate
attention. Alerts are written to ``state/alerts.json`` and can be routed
to external channels via OpenClaw gateway.

Alert levels::

    CRITICAL — accuracy < 40%, risk=critical + confidence > 85%, volume spike > 3×
    HIGH     — new S-grade prediction, contradicts prior consensus, domain gap
    MEDIUM   — weekly evolution report, coverage gap, stale data
    LOW      — routine status, tier scrape complete, daily summary

Usage::

    engine = AlertEngine()
    new_alerts = engine.scan()           # Run full scan
    active = engine.get_active_alerts()  # View unacknowledged alerts
    engine.acknowledge("alert_id")       # Mark handled
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ALERTS_FILE = Path("state/alerts.json")
SIGNAL_CACHE_DIR = Path("data/signal_cache")
PREDICTIONS_FILE = Path("state/predictions.json")
EVOLUTION_DIR = Path("state/evolution")


def _load_predictions() -> list:
    """Load predictions from SQLite (preferred) or JSON fallback."""
    try:
        from .persistence import PredictionStore
        store = PredictionStore()
        data = store.list_all()
        if data:
            return data
    except Exception:
        pass
    if not PREDICTIONS_FILE.exists():
        return []
    try:
        return json.loads(PREDICTIONS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

# ── Thresholds ───────────────────────────────────────────────────────────────

ACCURACY_CRITICAL = 0.40
CONFIDENCE_CRITICAL = 0.85
VOLUME_SPIKE_FACTOR = 3.0
STALE_DATA_DAYS = 7


class Alert:
    """Single alert record."""

    def __init__(
        self,
        level: str,
        category: str,
        title: str,
        detail: str,
        source: str = "system",
        data: dict | None = None,
    ):
        self.id = f"alert_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{category}"
        self.level = level  # CRITICAL, HIGH, MEDIUM, LOW
        self.category = category
        self.title = title
        self.detail = detail
        self.source = source
        self.data = data or {}
        self.created_at = datetime.now().isoformat()
        self.acknowledged = False
        self.acknowledged_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "level": self.level,
            "category": self.category,
            "title": self.title,
            "detail": self.detail,
            "source": self.source,
            "data": self.data,
            "created_at": self.created_at,
            "acknowledged": self.acknowledged,
            "acknowledged_at": self.acknowledged_at,
        }


# Priority sort order
LEVEL_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


class AlertEngine:
    """Scan system state for conditions that warrant alerts."""

    def __init__(self):
        self._store = None
        try:
            from .persistence import AlertStore
            self._store = AlertStore()
        except ImportError:
            pass
        self._alerts: list[dict[str, Any]] = self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> list[dict[str, Any]]:
        if self._store:
            return self._store.get_all()
        if ALERTS_FILE.exists():
            try:
                return json.loads(ALERTS_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("Corrupt alerts file — starting fresh")
        return []

    def _save(self):
        if self._store:
            return  # SQLite handles persistence per-operation
        ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ALERTS_FILE.write_text(
            json.dumps(self._alerts, indent=2, default=str), encoding="utf-8"
        )

    def _add_alert(self, alert: Alert) -> dict[str, Any]:
        """Add alert if a similar one doesn't already exist (dedup by category + level)."""
        if self._store:
            if self._store.exists_recent(alert.category, alert.level):
                # Return existing-style dict for dedup
                return alert.to_dict()
            d = alert.to_dict()
            self._store.add(d)
            self._alerts.append(d)
            logger.info("[%s] %s — %s", alert.level, alert.title, alert.detail)
            return d

        # JSON fallback: dedup within last hour
        cutoff = (datetime.now() - timedelta(hours=1)).isoformat()
        for existing in self._alerts:
            if (existing["category"] == alert.category
                    and existing["level"] == alert.level
                    and not existing.get("acknowledged")
                    and existing.get("created_at", "") > cutoff):
                return existing  # already have this alert

        d = alert.to_dict()
        self._alerts.append(d)
        self._save()
        logger.info("[%s] %s — %s", alert.level, alert.title, alert.detail)
        return d

    # ── Full scan ────────────────────────────────────────────────────────────

    def scan(self) -> list[dict[str, Any]]:
        """Run all alert checks. Returns list of NEW alerts generated."""
        new_alerts: list[dict[str, Any]] = []
        new_alerts.extend(self._check_accuracy())
        new_alerts.extend(self._check_high_risk_predictions())
        new_alerts.extend(self._check_signal_volume())
        new_alerts.extend(self._check_stale_data())
        new_alerts.extend(self._check_evolution_tasks())
        return new_alerts

    # ── Individual checks ────────────────────────────────────────────────────

    def _check_accuracy(self) -> list[dict[str, Any]]:
        """CRITICAL if overall accuracy drops below threshold."""
        alerts = []
        predictions = _load_predictions()
        resolved = [p for p in predictions
                     if p.get("resolved") and p.get("accuracy_score") is not None]

        if len(resolved) < 3:
            return alerts

        avg = sum(p["accuracy_score"] for p in resolved) / len(resolved)
        if avg < ACCURACY_CRITICAL:
            a = Alert(
                level="CRITICAL",
                category="accuracy_low",
                title="Prediction accuracy critically low",
                detail=f"Average accuracy {avg:.0%} (threshold: {ACCURACY_CRITICAL:.0%}). "
                       f"Based on {len(resolved)} resolved predictions.",
                data={"avg_accuracy": avg, "resolved_count": len(resolved)},
            )
            alerts.append(self._add_alert(a))
        return alerts

    def _check_high_risk_predictions(self) -> list[dict[str, Any]]:
        """HIGH/CRITICAL for predictions with extreme confidence + risk."""
        alerts = []
        predictions = _load_predictions()
        for p in predictions:
            if p.get("resolved"):
                continue

            confidence = float(p.get("confidence", 0))
            risk = str(p.get("risk_level", "")).lower()

            if confidence >= CONFIDENCE_CRITICAL and risk == "critical":
                a = Alert(
                    level="CRITICAL",
                    category="high_risk_prediction",
                    title=f"Critical risk + high confidence: {p.get('topic', 'Unknown')}",
                    detail=f"Confidence {confidence:.0%}, Risk: {risk}. "
                           f"Outcome: {p.get('predicted_outcome', 'N/A')}",
                    source="prediction_tracker",
                    data={"prediction_id": p.get("id"), "confidence": confidence, "risk": risk},
                )
                alerts.append(self._add_alert(a))
            elif confidence >= CONFIDENCE_CRITICAL and risk in ("high", "critical"):
                a = Alert(
                    level="HIGH",
                    category="high_confidence_alert",
                    title=f"High confidence signal: {p.get('topic', 'Unknown')}",
                    detail=f"Confidence {confidence:.0%}, Risk: {risk}. Review recommended.",
                    source="prediction_tracker",
                    data={"prediction_id": p.get("id"), "confidence": confidence, "risk": risk},
                )
                alerts.append(self._add_alert(a))

        return alerts

    def _check_signal_volume(self) -> list[dict[str, Any]]:
        """HIGH if signal volume spikes >3× vs. average for a tier."""
        alerts = []
        if not SIGNAL_CACHE_DIR.exists():
            return alerts

        for tier in ["tier_1_daily", "tier_2_weekly", "tier_3_monthly", "tier_4_quarterly"]:
            files = sorted(SIGNAL_CACHE_DIR.glob(f"{tier}_*.json"))
            if len(files) < 2:
                continue

            counts = []
            for f in files[-10:]:  # last 10 cache files
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    counts.append(data.get("signal_count", 0))
                except (json.JSONDecodeError, OSError):
                    continue

            if len(counts) < 2:
                continue

            avg = sum(counts[:-1]) / len(counts[:-1])
            latest = counts[-1]

            if avg > 0 and latest > avg * VOLUME_SPIKE_FACTOR:
                a = Alert(
                    level="HIGH",
                    category="signal_volume_spike",
                    title=f"Signal volume spike in {tier}",
                    detail=f"Latest: {latest} signals vs. avg {avg:.0f} "
                           f"({latest/avg:.1f}× increase). May indicate breaking event.",
                    source="scraper",
                    data={"tier": tier, "latest": latest, "average": avg},
                )
                alerts.append(self._add_alert(a))

        return alerts

    def _check_stale_data(self) -> list[dict[str, Any]]:
        """MEDIUM if daily-tier data hasn't been refreshed."""
        alerts = []
        if not SIGNAL_CACHE_DIR.exists():
            return alerts

        daily_files = sorted(SIGNAL_CACHE_DIR.glob("tier_1_daily_*.json"))
        if not daily_files:
            a = Alert(
                level="MEDIUM",
                category="stale_data",
                title="No daily-tier signals found",
                detail="Signal cache has no tier_1_daily data. Run: fpc scrape --tier tier_1_daily",
                source="scraper",
            )
            alerts.append(self._add_alert(a))
            return alerts

        latest_file = daily_files[-1]
        try:
            ts_str = latest_file.stem.replace("tier_1_daily_", "")
            last_scrape = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            age_days = (datetime.now() - last_scrape).days
            if age_days >= STALE_DATA_DAYS:
                a = Alert(
                    level="MEDIUM",
                    category="stale_data",
                    title=f"Daily signals are {age_days} days old",
                    detail=f"Last scrape: {last_scrape.isoformat()}. "
                           f"Run: fpc scrape --due",
                    source="scraper",
                    data={"last_scrape": last_scrape.isoformat(), "age_days": age_days},
                )
                alerts.append(self._add_alert(a))
        except ValueError:
            pass

        return alerts

    def _check_evolution_tasks(self) -> list[dict[str, Any]]:
        """MEDIUM if evolution tasks are piling up unaddressed."""
        alerts = []
        tasks_file = EVOLUTION_DIR / "tasks.json"
        if not tasks_file.exists():
            return alerts

        try:
            tasks = json.loads(tasks_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return alerts

        queued = [t for t in tasks if t.get("status") == "queued"]
        critical = [t for t in queued if t.get("priority", 100) <= 20]

        if critical:
            a = Alert(
                level="HIGH",
                category="evolution_critical_tasks",
                title=f"{len(critical)} critical evolution tasks pending",
                detail=f"Top task: {critical[0].get('title', 'Unknown')}. "
                       f"Total queued: {len(queued)}.",
                source="evolution",
                data={"critical_count": len(critical), "total_queued": len(queued)},
            )
            alerts.append(self._add_alert(a))
        elif len(queued) > 5:
            a = Alert(
                level="MEDIUM",
                category="evolution_backlog",
                title=f"{len(queued)} evolution tasks in backlog",
                detail="Consider running: fpc evolve",
                source="evolution",
                data={"total_queued": len(queued)},
            )
            alerts.append(self._add_alert(a))

        return alerts

    # ── Query & manage ───────────────────────────────────────────────────────

    def get_active_alerts(self, level: str | None = None) -> list[dict[str, Any]]:
        """Get unacknowledged alerts, optionally filtered by level."""
        if self._store:
            active = self._store.get_active(level)
        else:
            active = [a for a in self._alerts if not a.get("acknowledged")]
            if level:
                active = [a for a in active if a.get("level") == level.upper()]
        active.sort(key=lambda a: LEVEL_ORDER.get(a.get("level", "LOW"), 9))
        return active

    def get_all_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get all alerts (most recent first), limited."""
        return list(reversed(self._alerts[-limit:]))

    def acknowledge(self, alert_id: str) -> bool:
        """Mark an alert as acknowledged."""
        if self._store:
            return self._store.acknowledge(alert_id)
        for a in self._alerts:
            if a["id"] == alert_id:
                a["acknowledged"] = True
                a["acknowledged_at"] = datetime.now().isoformat()
                self._save()
                return True
        return False

    def acknowledge_all(self, level: str | None = None) -> int:
        """Acknowledge all active alerts (optionally filtered by level)."""
        if self._store and not level:
            return self._store.acknowledge_all()
        count = 0
        now = datetime.now().isoformat()
        for a in self._alerts:
            if a.get("acknowledged"):
                continue
            if level and a.get("level") != level.upper():
                continue
            a["acknowledged"] = True
            a["acknowledged_at"] = now
            count += 1
        if count:
            self._save()
        return count

    def clear_old(self, days: int = 30) -> int:
        """Remove acknowledged alerts older than N days."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        before = len(self._alerts)
        self._alerts = [
            a for a in self._alerts
            if not (a.get("acknowledged") and a.get("created_at", "") < cutoff)
        ]
        removed = before - len(self._alerts)
        if removed:
            self._save()
        return removed

    def summary(self) -> dict[str, Any]:
        """Quick counts by level."""
        active = self.get_active_alerts()
        counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for a in active:
            lv = a.get("level", "LOW")
            counts[lv] = counts.get(lv, 0) + 1
        return {
            "total_active": len(active),
            "total_all": len(self._alerts),
            **counts,
        }
