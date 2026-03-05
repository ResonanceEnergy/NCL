#!/usr/bin/env python3
import argparse, json, os, datetime
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from lib_ncl import expanduser, ensure_dirs, append_ndjson

# Import memory system
try:
    from memory_api import store_task_execution, get_memory_api
    from learning_engine import learn_from_task, analyze_recent_patterns
    MEMORY_ENABLED = True
except ImportError:
    print("Warning: Memory API not available, running without memory integration")
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
            except Exception:
                continue
    return events, path


def make_daily_brief(events, date_str):
    # Rules-based placeholder (local-only). Replace with smarter agents later.
    counts = {}
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mission', required=True, help='path to mission JSON')
    args = ap.parse_args()

    mission_path = Path(args.mission)
    mission = json.loads(mission_path.read_text(encoding='utf-8'))

    ncl_root = expanduser('~/NCL')
    event_log_dir = ncl_root / 'data' / 'event_log'
    reports_dir = ncl_root / 'dist' / 'reports' / 'daily'
    audit_dir = ncl_root / 'audit'
    ensure_dirs(event_log_dir, reports_dir, audit_dir)

    date_str = mission.get('inputs', {}).get('date')
    if not date_str:
        date_str = datetime.date.today().isoformat()

    events, src_path = load_events_for_date(event_log_dir, date_str)
    brief = make_daily_brief(events, date_str)

    out_path = reports_dir / f"{date_str}.md"
    out_path.write_text(brief, encoding='utf-8')

    # write derived summary event
    derived = {
        "schema_version": "ncl.event.v1",
        "event_id": f"derived-{mission.get('mission_id','unknown')}",
        "event_type": "derived.summary.daily",
        "occurred_at": datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(),
        "source": {"device": "mac", "origin": "mission_runner", "collector_version": "runtime-mac-v1"},
        "privacy": {"level": "P1", "raw_retention": "none", "derived_retention_days": 365},
        "payload": {"date": date_str, "total_events": len(events), "top_event_types": events and list({e.get('event_type'):None for e in events}.keys())[:10] or []},
        "links": {"mission_id": mission.get('mission_id'), "trace_id": mission.get('trace_id')}
    }
    derived_path = ncl_root / 'data' / 'derived' / f"{date_str}.ndjson"
    ensure_dirs(derived_path.parent)
    append_ndjson(derived_path, derived)

    # Store mission execution in memory
    if MEMORY_ENABLED:
        try:
            execution_result = {
                "success": True,
                "duration": None,  # Could be calculated if we tracked start time
                "output_files": [str(out_path), str(derived_path)],
                "event_count": len(events),
                "date_processed": date_str
            }

            memory_id = store_task_execution(mission, execution_result)
            print(f"Stored mission execution in memory: {memory_id}")

            # Also store the derived summary as episodic memory
            from memory_api import store_event
            store_event(derived)

            # Learn from this task execution
            learn_from_task(mission, execution_result)

            # Periodically analyze patterns (e.g., after daily briefs)
            if mission.get("mission_type") == "daily_brief":
                try:
                    patterns = analyze_recent_patterns(days_back=7)
                    print(f"Pattern analysis: {patterns['total_events']} events, {len(patterns['insights'])} insights")
                except Exception as e:
                    print(f"Pattern analysis failed: {e}")

        except Exception as e:
            print(f"Memory storage failed: {e}")

    # audit
    audit = {
        "mission_id": mission.get('mission_id'),
        "trace_id": mission.get('trace_id'),
        "mission_type": mission.get('mission_type'),
        "date": date_str,
        "source_event_file": str(src_path),
        "report": str(out_path),
        "derived": str(derived_path),
        "completed_at": datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
    }
    (audit_dir / f"{mission.get('mission_id','mission')}.json").write_text(json.dumps(audit, indent=2), encoding='utf-8')

    print(f"OK: wrote {out_path}")


if __name__ == '__main__':
    main()
