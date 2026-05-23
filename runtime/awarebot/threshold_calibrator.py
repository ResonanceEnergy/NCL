"""
Awarebot Threshold Calibrator
=============================

Isotonic-calibrated tier thresholds for Awarebot signal routing.

CONTEXT
-------
Awarebot.route_to_tiers() uses hardcoded floors:
    Focused ≥ 0.75
    Micro   ≥ 0.50
    Macro   ≥ 0.30

These were initial guesses. This module learns thresholds from NATRIX's
feedback (view / pin / dismiss / council_request) so that each tier
corresponds to a stable *precision target*:

    Focused → P(positive | shown) ≥ 0.60
    Micro   → P(positive | shown) ≥ 0.35
    Macro   → P(positive | shown) ≥ 0.15

where "positive" = the user pinned the signal or convened a council on it,
and "negative" = the user dismissed it. Pure views are ignored as label
(they're impressions, not judgments) but are required as the denominator
when joining feedback to scores.

APPROACH
--------
1. Pull 7-day feedback window from FeedbackRecorder (item 11 of roadmap)
2. Join each {pin, dismiss, council_request} to the originating signal's
   composite_score via signal_id (look up in agent_signals.jsonl)
3. Fit sklearn.isotonic.IsotonicRegression(out_of_bounds='clip') on
   (score → label) where label = 1 for pin/council_request, 0 for dismiss
4. Walk the fitted curve to find the score at which the precision
   target is first satisfied
5. Smooth: if new threshold diverges >30% from current, EMA blend
   (new_eff = 0.7*old + 0.3*new) to avoid iOS UX whiplash
6. Persist to data_dir/calibrated_thresholds.json

USAGE
-----
    calibrator = ThresholdCalibrator(feedback_recorder, data_dir)
    thresholds = calibrator.get_thresholds()  # lazy-recalibrates if stale
    # → CalibratedThresholds(focused=0.71, micro=0.48, macro=0.27, ...)

    # Integration: replace literals in Awarebot.route_to_tiers()
    #   if sig.composite_score >= thresholds.focused and age_h < 4: ...

SCHEDULER
---------
Wire recalibrate_loop() at 6h cadence alongside the other autonomous
loops in runtime/autonomous/scheduler.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np

try:
    from sklearn.isotonic import IsotonicRegression
    SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover
    SKLEARN_AVAILABLE = False

log = logging.getLogger("ncl.awarebot.threshold_calibrator")

# Precision targets per tier — score where P(positive | shown) first ≥ target
PRECISION_FOCUSED = 0.60
PRECISION_MICRO = 0.35
PRECISION_MACRO = 0.15

# Fallback thresholds (current hardcoded defaults in route_to_tiers)
FALLBACK_FOCUSED = 0.75
FALLBACK_MICRO = 0.50
FALLBACK_MACRO = 0.30

# Smoothing parameters
EMA_ALPHA_NEW = 0.30   # weight of newly-calibrated value
EMA_ALPHA_OLD = 0.70   # weight of previously-persisted value
MAX_RELATIVE_DIVERGENCE = 0.30  # >30% drift triggers EMA blend

# Recalibration cadence
STALE_AFTER = timedelta(hours=6)
RECALIBRATE_LOOP_INTERVAL_S = 6 * 3600

# Data requirements
LOOKBACK_DAYS = 7
LABELED_EVENT_KINDS = {"pin", "dismiss", "council_request"}
POSITIVE_KINDS = {"pin", "council_request"}


@dataclass
class CalibratedThresholds:
    """Snapshot of the three tier floors plus calibration metadata."""

    focused: float
    micro: float
    macro: float
    last_calibrated: datetime
    n_events_used: int
    # (score, P(positive)) pairs from the fitted isotonic curve — small,
    # useful for the iOS Intel header to plot a sparkline.
    calibration_curve: list[tuple[float, float]] = field(default_factory=list)
    # True when fallback was used (insufficient data, sklearn missing,
    # or calibration failed); iOS surfaces this as "uncalibrated" badge.
    is_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["last_calibrated"] = self.last_calibrated.isoformat()
        d["calibration_curve"] = [[float(s), float(p)] for s, p in self.calibration_curve]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CalibratedThresholds":
        return cls(
            focused=float(d["focused"]),
            micro=float(d["micro"]),
            macro=float(d["macro"]),
            last_calibrated=datetime.fromisoformat(d["last_calibrated"]),
            n_events_used=int(d.get("n_events_used", 0)),
            calibration_curve=[(float(s), float(p)) for s, p in d.get("calibration_curve", [])],
            is_fallback=bool(d.get("is_fallback", False)),
        )


def _default_fallback() -> CalibratedThresholds:
    return CalibratedThresholds(
        focused=FALLBACK_FOCUSED,
        micro=FALLBACK_MICRO,
        macro=FALLBACK_MACRO,
        last_calibrated=datetime.now(timezone.utc),
        n_events_used=0,
        calibration_curve=[],
        is_fallback=True,
    )


class ThresholdCalibrator:
    """
    Learns Focused/Micro/Macro thresholds from feedback events.

    Persists to ``data_dir/calibrated_thresholds.json`` so values survive
    restarts. Recalibrates lazily on get_thresholds() once STALE_AFTER
    has elapsed, or proactively via recalibrate_loop().
    """

    def __init__(
        self,
        feedback_recorder: Any,
        data_dir: Path,
        min_events: int = 100,
        fallback: CalibratedThresholds | None = None,
    ):
        """
        Args:
            feedback_recorder: instance of FeedbackRecorder (item 11) —
                must expose ``async get_events(since: datetime) -> list[dict]``
                where each dict has at least ``signal_id``, ``kind``, ``timestamp``.
            data_dir: directory for persisted thresholds JSON. Typically
                ``Path("data/awarebot")``.
            min_events: minimum *labeled* events (pin+dismiss+council_request)
                required before isotonic fit is attempted. Below this,
                fallback is returned.
            fallback: defaults to the legacy hardcoded floors
                (0.75 / 0.50 / 0.30) if not supplied.
        """
        self.feedback_recorder = feedback_recorder
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.min_events = min_events
        self.fallback = fallback or _default_fallback()
        self._state_path = self.data_dir / "calibrated_thresholds.json"
        self._signals_path = self.data_dir.parent / "intelligence" / "agent_signals.jsonl"
        self._lock = asyncio.Lock()
        self._cache: CalibratedThresholds | None = self._load_persisted()

    # ── Persistence ──────────────────────────────────────────────────────

    def _load_persisted(self) -> CalibratedThresholds | None:
        if not self._state_path.exists():
            return None
        try:
            with self._state_path.open("r") as f:
                return CalibratedThresholds.from_dict(json.load(f))
        except Exception as e:  # noqa: BLE001
            log.warning("Failed to load calibrated_thresholds.json: %s", e)
            return None

    def _persist(self, thresholds: CalibratedThresholds) -> None:
        try:
            tmp = self._state_path.with_suffix(".json.tmp")
            with tmp.open("w") as f:
                json.dump(thresholds.to_dict(), f, indent=2)
            tmp.replace(self._state_path)
        except Exception as e:  # noqa: BLE001
            log.error("Failed to persist calibrated_thresholds: %s", e)

    # ── Signal lookup ────────────────────────────────────────────────────

    def _load_signal_scores(self, signal_ids: set[str]) -> dict[str, float]:
        """
        Tail agent_signals.jsonl to resolve composite_score per signal_id.
        Reads the whole file; in practice it's bounded by rotation and
        7-day signal_ids comfortably fit. If a signal_id is missing
        (rotated out, or pinned from a non-Awarebot source) it's skipped.
        """
        scores: dict[str, float] = {}
        if not self._signals_path.exists():
            log.warning("agent_signals.jsonl not found at %s", self._signals_path)
            return scores
        try:
            with self._signals_path.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    sid = rec.get("signal_id")
                    if sid in signal_ids and "composite_score" in rec:
                        scores[sid] = float(rec["composite_score"])
        except Exception as e:  # noqa: BLE001
            log.error("Error reading agent_signals.jsonl: %s", e)
        return scores

    # ── Core calibration ─────────────────────────────────────────────────

    @staticmethod
    def _find_threshold_for_precision(
        iso: "IsotonicRegression",
        target: float,
        grid_resolution: int = 1001,
    ) -> float | None:
        """
        Walk the [0, 1] score grid and return the smallest score x where
        the fitted isotonic curve satisfies P(positive | x) >= target.
        Returns None if no point on the grid meets the target.
        """
        grid = np.linspace(0.0, 1.0, grid_resolution)
        preds = iso.predict(grid)
        idx = np.argmax(preds >= target)
        # argmax on bool array returns 0 if no True — disambiguate.
        if not (preds[idx] >= target):
            return None
        return float(grid[idx])

    def _smooth(self, key: str, new_value: float, old: CalibratedThresholds) -> float:
        """
        If new diverges >30% from old (relative), exponential-smooth.
        Otherwise accept new directly.
        """
        old_value = getattr(old, key)
        if old_value <= 0:
            return new_value
        rel = abs(new_value - old_value) / old_value
        if rel <= MAX_RELATIVE_DIVERGENCE:
            return new_value
        blended = EMA_ALPHA_OLD * old_value + EMA_ALPHA_NEW * new_value
        log.info(
            "Smoothing %s: old=%.3f new=%.3f rel_diff=%.1f%% → blended=%.3f",
            key, old_value, new_value, rel * 100, blended,
        )
        return blended

    async def calibrate(self) -> CalibratedThresholds:
        """
        Run the full calibration pipeline. Safe to call concurrently —
        holds an internal lock. Always returns a CalibratedThresholds
        (falls back gracefully on any failure).
        """
        async with self._lock:
            if not SKLEARN_AVAILABLE:
                log.warning("sklearn unavailable — returning fallback thresholds")
                return self._materialize_fallback()

            # 1. Pull 7-day labeled events
            since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
            try:
                events = await self.feedback_recorder.get_events(since=since)
            except Exception as e:  # noqa: BLE001
                log.error("FeedbackRecorder.get_events failed: %s", e)
                return self._materialize_fallback()

            labeled = [
                ev for ev in events
                if ev.get("kind") in LABELED_EVENT_KINDS and ev.get("signal_id")
            ]
            if len(labeled) < self.min_events:
                log.info(
                    "Insufficient labeled events: %d < %d → fallback",
                    len(labeled), self.min_events,
                )
                return self._materialize_fallback()

            # 2. Join to composite_score via signal_id
            signal_ids = {ev["signal_id"] for ev in labeled}
            scores_by_id = self._load_signal_scores(signal_ids)
            paired = []
            for ev in labeled:
                sid = ev["signal_id"]
                if sid not in scores_by_id:
                    continue
                label = 1.0 if ev["kind"] in POSITIVE_KINDS else 0.0
                paired.append((scores_by_id[sid], label))

            if len(paired) < self.min_events:
                log.info(
                    "Pairing dropped too many events: %d < %d → fallback",
                    len(paired), self.min_events,
                )
                return self._materialize_fallback()

            # Need both classes present for a meaningful fit
            labels = [lbl for _, lbl in paired]
            if min(labels) == max(labels):
                log.info("All labels identical (%s) — fallback", labels[0])
                return self._materialize_fallback()

            # 3. Fit isotonic regression
            xs = np.array([s for s, _ in paired], dtype=float)
            ys = np.array(labels, dtype=float)
            try:
                iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
                iso.fit(xs, ys)
            except Exception as e:  # noqa: BLE001
                log.error("IsotonicRegression.fit failed: %s", e)
                return self._materialize_fallback()

            # 4. Resolve thresholds at precision targets
            t_focused = self._find_threshold_for_precision(iso, PRECISION_FOCUSED)
            t_micro = self._find_threshold_for_precision(iso, PRECISION_MICRO)
            t_macro = self._find_threshold_for_precision(iso, PRECISION_MACRO)

            # If a target isn't reachable (e.g. low overall positive rate),
            # fall back to the legacy floor for *that* tier only.
            t_focused = t_focused if t_focused is not None else FALLBACK_FOCUSED
            t_micro = t_micro if t_micro is not None else FALLBACK_MICRO
            t_macro = t_macro if t_macro is not None else FALLBACK_MACRO

            # Enforce monotonicity: focused ≥ micro ≥ macro
            t_micro = min(t_micro, t_focused)
            t_macro = min(t_macro, t_micro)

            # 5. Smooth against previously-persisted thresholds
            old = self._cache or self.fallback
            if not old.is_fallback:
                t_focused = self._smooth("focused", t_focused, old)
                t_micro = self._smooth("micro", t_micro, old)
                t_macro = self._smooth("macro", t_macro, old)

            # 6. Build curve snapshot (40 grid points — compact for iOS)
            grid = np.linspace(0.0, 1.0, 41)
            curve = [(float(g), float(p)) for g, p in zip(grid, iso.predict(grid))]

            result = CalibratedThresholds(
                focused=round(t_focused, 4),
                micro=round(t_micro, 4),
                macro=round(t_macro, 4),
                last_calibrated=datetime.now(timezone.utc),
                n_events_used=len(paired),
                calibration_curve=curve,
                is_fallback=False,
            )
            self._cache = result
            self._persist(result)
            log.info(
                "Calibrated thresholds (n=%d): focused=%.3f micro=%.3f macro=%.3f",
                result.n_events_used, result.focused, result.micro, result.macro,
            )
            return result

    def _materialize_fallback(self) -> CalibratedThresholds:
        """Persist (so iOS can read it) and cache the fallback snapshot."""
        fb = CalibratedThresholds(
            focused=self.fallback.focused,
            micro=self.fallback.micro,
            macro=self.fallback.macro,
            last_calibrated=datetime.now(timezone.utc),
            n_events_used=0,
            calibration_curve=[],
            is_fallback=True,
        )
        self._cache = fb
        self._persist(fb)
        return fb

    # ── Public accessors ─────────────────────────────────────────────────

    def get_thresholds(self) -> CalibratedThresholds:
        """
        Return current cached thresholds. If stale (>STALE_AFTER since
        last_calibrated), schedule a background recalibration but return
        the cached snapshot immediately so callers never block.
        Synchronous on purpose — route_to_tiers() is a hot path.
        """
        if self._cache is None:
            return self.fallback
        age = datetime.now(timezone.utc) - self._cache.last_calibrated
        if age > STALE_AFTER:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.calibrate())
            except RuntimeError:
                # No running loop — caller is sync context, skip background fire
                pass
        return self._cache


# ── Scheduler loop ───────────────────────────────────────────────────────

async def recalibrate_loop(
    calibrator: ThresholdCalibrator,
    interval_s: int = RECALIBRATE_LOOP_INTERVAL_S,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """
    Long-running task for the autonomous scheduler. Re-fits thresholds
    every ``interval_s`` seconds (default 6 hours).

    Wire into runtime/autonomous/scheduler.py:

        from runtime.awarebot.threshold_calibrator import (
            ThresholdCalibrator, recalibrate_loop,
        )
        calibrator = ThresholdCalibrator(feedback_recorder, Path("data/awarebot"))
        self._tasks.append(asyncio.create_task(
            recalibrate_loop(calibrator, shutdown_event=self._shutdown_event),
            name="ncl-threshold-calibrator",
        ))
    """
    log.info("threshold_calibrator loop started (interval=%ss)", interval_s)
    while True:
        try:
            await calibrator.calibrate()
        except Exception as e:  # noqa: BLE001
            log.exception("Calibration cycle failed: %s", e)
        try:
            if shutdown_event is not None:
                await asyncio.wait_for(shutdown_event.wait(), timeout=interval_s)
                if shutdown_event.is_set():
                    log.info("threshold_calibrator loop shutdown signal received")
                    return
            else:
                await asyncio.sleep(interval_s)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            log.info("threshold_calibrator loop cancelled")
            raise
