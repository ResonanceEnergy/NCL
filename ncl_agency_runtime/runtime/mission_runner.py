#!/usr/bin/env python3
import argparse
import contextlib
import datetime
import json
import logging
import sys
import time
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from collections.abc import Callable

from lib_ncl import append_ndjson, ensure_dirs, expanduser

LOG = logging.getLogger("ncl.mission_runner")

# Import memory system
try:
    from learning_engine import analyze_recent_patterns, learn_from_task
    from memory_api import store_task_execution
    MEMORY_ENABLED = True
except ImportError:
    LOG.warning("Memory API not available — running without memory integration")
    MEMORY_ENABLED = False


def load_events_for_date(event_log_dir: Path, date_str: str):
    path = event_log_dir / f"{date_str}.ndjson"
    if not path.exists():
        return [], path
    events = []
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:  # noqa: S112
                continue
    return events, path


def make_daily_brief(events, date_str):
    # Habit 1 (Be Proactive): Generate briefs before the user asks.
    # Art of War: 'Supreme excellence — win without fighting.'
    # Law 6 (Court attention): Push insights proactively.
    counts: dict[str, int] = {}
    for e in events:
        et = e.get('event_type','unknown')
        counts[et] = counts.get(et, 0) + 1

    top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]
    lines = []
    lines.append(f"# NCL Daily Brief — {date_str}")
    lines.append("")
    lines.append("## Signal Summary")
    lines.append(f"Total events: **{len(events)}**")
    lines.append("")
    lines.append("## Top Event Types")
    for et, n in top:
        lines.append(f"- {et}: {n}")
    lines.append("")
    lines.append("## Next Actions (v0)")
    lines.append("- Capture 1 QuickLog (energy/stress) if none exists today.")
    lines.append("- If you saw multiple focus switches, consider a 20–40 min Deep Work block.")
    lines.append("- If you’re low energy, prioritize recovery and 1 small win.")
    lines.append("")
    lines.append("## Receipts")
    lines.append("- This v0 brief is computed from local NDJSON counts only.")
    return "\n".join(lines)


def make_weekly_brief(events, start_date, end_date):
    """Generate a weekly brief covering start_date to end_date."""
    counts: dict[str, int] = {}
    for e in events:
        et = e.get('event_type', 'unknown')
        counts[et] = counts.get(et, 0) + 1

    top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]
    total = len(events)
    daily_avg = total / 7 if total > 0 else 0

    lines = []
    lines.append(f"# NCL Weekly Brief — {start_date} to {end_date}")
    lines.append("")
    lines.append("## Signal Summary")
    lines.append(f"Total events: **{total}**")
    lines.append(f"Daily average: **{daily_avg:.1f}**")
    lines.append("")
    lines.append("## Top Event Types")
    for et, n in top:
        lines.append(f"- {et}: {n}")
    lines.append("")
    lines.append("## Weekly Trends")
    if total > 50:
        lines.append("- High activity week — consider reviewing priorities")
    elif total > 0:
        lines.append("- Normal activity levels")
    else:
        lines.append("- No events captured this week")
    lines.append("")
    lines.append("## Next Week Focus")
    lines.append("- Review top event types for patterns")
    lines.append("- Set 1–3 intentional focus goals")
    lines.append("")
    lines.append("## Receipts")
    lines.append("- Weekly brief computed from local NDJSON counts.")
    return "\n".join(lines)


def investigate_drift(events, date_str, baseline_path=None):
    """Investigate drift from baseline patterns.

    Art of War: 'Know yourself, know your enemy' — drift reveals blind spots.
    Habit 5: Seek First to Understand — diagnose before prescribing.
    Law 33: Discover each person's thumbscrew — find the leverage point.
    """
    total = len(events)
    counts: dict[str, int] = {}
    for e in events:
        et = e.get('event_type', 'unknown')
        counts[et] = counts.get(et, 0) + 1

    lines = []
    lines.append(f"# NCL Drift Report — {date_str}")
    lines.append("")
    lines.append("## Signal Summary")
    lines.append(f"Total events: **{total}**")
    lines.append("")

    anomalies = []

    if baseline_path:
        try:
            with open(baseline_path, encoding='utf-8') as f:
                baseline = json.load(f)

            lines.append("## Baseline Comparison")
            for et, baseline_avg in baseline.items():
                current_count = counts.get(et, 0)
                deviation = abs(current_count - baseline_avg)
                if deviation > baseline_avg * 0.5 and deviation > 1:
                    anomalies.append(f"- **{et}**: expected ~{baseline_avg:.1f}, got {current_count} (Δ={deviation:.1f})")

            if anomalies:
                lines.append("")
                lines.append("## Anomalies Detected")
                lines.extend(anomalies)
            else:
                lines.append("")
                lines.append("## No Significant Drift")
                lines.append("- All event types within baseline tolerance")

        except (json.JSONDecodeError, FileNotFoundError):
            lines.append("## Baseline Error")
            lines.append("- Could not load baseline file")
    else:
        lines.append("## No Significant Drift")
        lines.append("- No baseline provided for comparison")

    lines.append("")
    lines.append("## Current Event Distribution")
    for et, n in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]:
        lines.append(f"- {et}: {n}")

    return "\n".join(lines)


def investigate_overload(events, date_str, threshold=50):
    """Investigate cognitive/event overload signals.

    Art of War: 'In the midst of chaos, there is opportunity' — high signal
    density is raw material for insight extraction.
    Habit 3: First Things First — prioritise what matters when overloaded.
    Law 35: Master the art of timing — know when to capture and when to rest.
    """
    total = len(events)
    counts: dict[str, int] = {}
    for e in events:
        et = e.get('event_type', 'unknown')
        counts[et] = counts.get(et, 0) + 1

    distinct_types = len(counts)

    # Hourly distribution
    hourly: dict[int, int] = {}
    for e in events:
        occurred = e.get('occurred_at', '')
        try:
            dt = datetime.datetime.fromisoformat(occurred.replace('Z', '+00:00'))
            hour = dt.hour
            hourly[hour] = hourly.get(hour, 0) + 1
        except Exception:
            pass

    lines = []
    lines.append(f"# NCL Overload Investigation — {date_str}")
    lines.append("")
    lines.append("## Signal Summary")
    lines.append(f"Total events: **{total}**")
    lines.append(f"Distinct event types: **{distinct_types}**")
    lines.append(f"Overload threshold: **{threshold}**")
    lines.append("")

    if total > threshold:
        lines.append("## Overload Signals")
        lines.append(f"- Event count ({total}) exceeds threshold ({threshold})")
        if distinct_types > 10:
            lines.append(f"- High context-switching detected: {distinct_types} distinct event types")
        lines.append("- Consider: batching, prioritisation, or reduced capture frequency")
    else:
        lines.append("## No Overload Detected")
        lines.append(f"- Event count ({total}) within threshold ({threshold})")

    if distinct_types > 10 and total <= threshold:
        lines.append(f"\n- High context-switching detected: {distinct_types} distinct event types")

    lines.append("")
    lines.append("## Hourly Distribution")
    for hour in sorted(hourly.keys()):
        bar = "█" * min(hourly[hour], 40)
        lines.append(f"- {hour:02d}:00 — {hourly[hour]:>3} {bar}")

    if not hourly:
        lines.append("- No hourly data available")

    lines.append("")
    lines.append("## Top Event Types")
    for et, n in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]:
        lines.append(f"- {et}: {n}")

    return "\n".join(lines)


# ── Mission History & Dead-Letter ────────────────────────────

class MissionStatus:
    """Tracks status lifecycle: queued → running → completed / failed / dead-letter."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"

    def __init__(self, history_dir: Path):
        self.history_dir = history_dir
        ensure_dirs(history_dir)
        self._history_file = history_dir / "mission_history.ndjson"
        self._dead_letter_dir = history_dir / "dead_letter"
        ensure_dirs(self._dead_letter_dir)

    def record(self, mission_id: str, status: str, *,
               mission_type: str = "", error: str = "",
               attempt: int = 1, extra: dict | None = None) -> dict:
        """Append a status record to mission history."""
        record = {
            "mission_id": mission_id,
            "status": status,
            "mission_type": mission_type,
            "attempt": attempt,
            "error": error,
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        if extra:
            record["extra"] = extra
        append_ndjson(self._history_file, record)
        return record

    def dead_letter(self, mission: dict, error: str, attempts: int) -> Path:
        """Move a permanently failed mission to the dead-letter directory."""
        mission_id = mission.get("mission_id", "unknown")
        dl_record = {
            "mission": mission,
            "error": str(error),
            "attempts": attempts,
            "dead_lettered_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        dl_path = self._dead_letter_dir / f"{mission_id}.json"
        dl_path.write_text(json.dumps(dl_record, indent=2), encoding="utf-8")
        self.record(mission_id, self.DEAD_LETTER,
                    mission_type=mission.get("mission_type", ""),
                    error=str(error), attempt=attempts)
        return dl_path

    def load_history(self, limit: int = 100) -> list[dict]:
        """Load recent mission history records."""
        if not self._history_file.exists():
            return []
        records: list[dict] = []
        with self._history_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                with contextlib.suppress(Exception):
                    records.append(json.loads(line))
        return records[-limit:]


def run_with_retry(func: Callable[[dict], str], mission: dict, *,
                   max_attempts: int = 3,
                   base_delay: float = 1.0,
                   mission_status: MissionStatus | None = None) -> str:
    """Execute *func(mission)* with exponential backoff on failure.

    Strategic Doctrine:
    - Law 28 (Enter action with boldness): Commit fully; no half-measures.
    - Law 15 (Crush your enemy totally): Exhaust all retries before dead-letter.
    - Art of War: 'In the midst of chaos, there is opportunity' — each retry
      is a renewed chance to succeed.
    - Habit 1 (Be Proactive): Don't accept failure passively; fight through.

    Returns the result string on success.
    Raises the last exception after *max_attempts* exhausted.
    """
    mission_id = mission.get("mission_id", "unknown")
    mission_type = mission.get("mission_type", "unknown")
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        if mission_status:
            mission_status.record(mission_id, MissionStatus.RUNNING,
                                  mission_type=mission_type, attempt=attempt)
        try:
            result = func(mission)
            if mission_status:
                mission_status.record(mission_id, MissionStatus.COMPLETED,
                                      mission_type=mission_type, attempt=attempt)
            return result
        except Exception as exc:
            last_exc = exc
            LOG.warning("Mission %s attempt %d/%d failed: %s",
                        mission_id, attempt, max_attempts, exc)
            if mission_status:
                mission_status.record(mission_id, MissionStatus.FAILED,
                                      mission_type=mission_type,
                                      error=str(exc), attempt=attempt)
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                time.sleep(delay)

    # All attempts exhausted — dead-letter
    if mission_status and last_exc:
        mission_status.dead_letter(mission, str(last_exc), max_attempts)

    raise last_exc  # type: ignore[misc]


# ── Mission Type Router ──────────────────────────────────────

MISSION_HANDLERS: dict[str, Callable[[dict], str]] = {}  # populated after function definitions


def _execute_daily_brief(mission: dict) -> str:
    """Execute a daily_brief mission. Returns path to report."""
    ncl_root = expanduser("~/NCL")
    event_log_dir = ncl_root / "data" / "event_log"
    reports_dir = ncl_root / "dist" / "reports" / "daily"
    ensure_dirs(event_log_dir, reports_dir)

    date_str = mission.get("inputs", {}).get("date")
    if not date_str:
        date_str = datetime.date.today().isoformat()

    events, _src_path = load_events_for_date(event_log_dir, date_str)
    brief = make_daily_brief(events, date_str)
    out_path = reports_dir / f"{date_str}.md"
    out_path.write_text(brief, encoding="utf-8")
    return str(out_path)


def _execute_weekly_brief(mission: dict) -> str:
    """Execute a weekly_brief mission."""
    ncl_root = expanduser("~/NCL")
    event_log_dir = ncl_root / "data" / "event_log"
    reports_dir = ncl_root / "dist" / "reports" / "weekly"
    ensure_dirs(event_log_dir, reports_dir)

    inputs = mission.get("inputs", {})
    end_date = inputs.get("end_date", datetime.date.today().isoformat())
    start_date = inputs.get("start_date",
                            (datetime.date.fromisoformat(end_date)
                             - datetime.timedelta(days=6)).isoformat())

    all_events: list[dict] = []
    current = datetime.date.fromisoformat(start_date)
    end = datetime.date.fromisoformat(end_date)
    while current <= end:
        day_events, _ = load_events_for_date(event_log_dir, current.isoformat())
        all_events.extend(day_events)
        current += datetime.timedelta(days=1)

    brief = make_weekly_brief(all_events, start_date, end_date)
    out_path = reports_dir / f"{start_date}_to_{end_date}.md"
    out_path.write_text(brief, encoding="utf-8")
    return str(out_path)


def _execute_drift(mission: dict) -> str:
    """Execute a drift_investigation mission."""
    ncl_root = expanduser("~/NCL")
    event_log_dir = ncl_root / "data" / "event_log"
    reports_dir = ncl_root / "dist" / "reports" / "drift"
    ensure_dirs(event_log_dir, reports_dir)

    inputs = mission.get("inputs", {})
    date_str = inputs.get("date", datetime.date.today().isoformat())
    baseline_path = inputs.get("baseline_path")

    events, _ = load_events_for_date(event_log_dir, date_str)
    report = investigate_drift(events, date_str, baseline_path)
    out_path = reports_dir / f"{date_str}.md"
    out_path.write_text(report, encoding="utf-8")
    return str(out_path)


def _execute_overload(mission: dict) -> str:
    """Execute an overload_investigation mission."""
    ncl_root = expanduser("~/NCL")
    event_log_dir = ncl_root / "data" / "event_log"
    reports_dir = ncl_root / "dist" / "reports" / "overload"
    ensure_dirs(event_log_dir, reports_dir)

    inputs = mission.get("inputs", {})
    date_str = inputs.get("date", datetime.date.today().isoformat())
    threshold = inputs.get("threshold", 50)

    events, _ = load_events_for_date(event_log_dir, date_str)
    report = investigate_overload(events, date_str, threshold)
    out_path = reports_dir / f"{date_str}.md"
    out_path.write_text(report, encoding="utf-8")
    return str(out_path)


MISSION_HANDLERS = {
    "daily_brief": _execute_daily_brief,
    "weekly_brief": _execute_weekly_brief,
    "drift_investigation": _execute_drift,
    "overload_investigation": _execute_overload,
}


def route_mission(mission: dict) -> str:
    """Route a mission to its handler by mission_type.

    Strategic Doctrine:
    - Art of War: 'The terrain dictates strategy' — route based on context.
    - Law 48 (Assume formlessness): The router adapts to any mission type.
    - Habit 2 (Begin with the End in Mind): Each handler targets a clear outcome.

    Raises ``ValueError`` for unknown mission types.
    """
    mission_type = mission.get("mission_type", "")
    handler = MISSION_HANDLERS.get(mission_type)
    if handler is None:
        raise ValueError(f"Unknown mission type: {mission_type!r}")
    return handler(mission)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mission', required=True, help='path to mission JSON')
    ap.add_argument('--max-retries', type=int, default=3, help='max retry attempts')
    ap.add_argument('--retry-delay', type=float, default=1.0, help='base retry delay seconds')
    args = ap.parse_args()

    mission_path = Path(args.mission)
    mission = json.loads(mission_path.read_text(encoding='utf-8'))

    ncl_root = expanduser('~/NCL')
    audit_dir = ncl_root / 'audit'
    history_dir = ncl_root / 'audit' / 'history'
    ensure_dirs(audit_dir)

    mission_status = MissionStatus(history_dir)
    mission_id = mission.get('mission_id', 'unknown')
    mission_type = mission.get('mission_type', 'unknown')

    # Record queued
    mission_status.record(mission_id, MissionStatus.QUEUED,
                          mission_type=mission_type)

    try:
        out_path = run_with_retry(
            route_mission, mission,
            max_attempts=args.max_retries,
            base_delay=args.retry_delay,
            mission_status=mission_status,
        )
    except (ValueError, Exception) as exc:
        LOG.error("Mission %s permanently failed: %s", mission_id, exc)
        print(f"FAILED: {exc}")
        sys.exit(1)

    # Write derived summary event
    date_str = mission.get('inputs', {}).get('date', datetime.date.today().isoformat())
    derived = {
        "schema_version": "ncl.event.v1",
        "event_id": f"derived-{mission_id}",
        "event_type": f"derived.summary.{mission_type}",
        "occurred_at": datetime.datetime.now(datetime.UTC).astimezone().isoformat(),
        "source": {"device": "mac", "origin": "mission_runner", "collector_version": "runtime-mac-v1"},
        "privacy": {"level": "P1", "raw_retention": "none", "derived_retention_days": 365},
        "payload": {"date": date_str, "report_path": out_path},
        "links": {"mission_id": mission_id, "trace_id": mission.get('trace_id')}
    }
    derived_path = ncl_root / 'data' / 'derived' / f"{date_str}.ndjson"
    ensure_dirs(derived_path.parent)
    append_ndjson(derived_path, derived)

    # Store mission execution in memory
    if MEMORY_ENABLED:
        try:
            execution_result = {
                "success": True,
                "duration": None,
                "output_files": [out_path, str(derived_path)],
                "date_processed": date_str
            }

            memory_id = store_task_execution(mission, execution_result)
            print(f"Stored mission execution in memory: {memory_id}")

            from memory_api import store_event
            store_event(derived)
            learn_from_task(mission, execution_result)

            if mission_type == "daily_brief":
                try:
                    patterns = analyze_recent_patterns(days_back=7)
                    print(f"Pattern analysis: {patterns['total_events']} events, {len(patterns['insights'])} insights")
                except Exception as e:
                    print(f"Pattern analysis failed: {e}")

        except Exception as e:
            print(f"Memory storage failed: {e}")

    # audit
    audit = {
        "mission_id": mission_id,
        "trace_id": mission.get('trace_id'),
        "mission_type": mission_type,
        "date": date_str,
        "report": out_path,
        "derived": str(derived_path),
        "completed_at": datetime.datetime.now(datetime.UTC).astimezone().isoformat()
    }
    (audit_dir / f"{mission_id}.json").write_text(json.dumps(audit, indent=2), encoding='utf-8')

    print(f"OK: wrote {out_path}")


if __name__ == '__main__':
    main()
