#!/usr/bin/env python3
"""
NCL Shortcuts Pack v2 — event emulator for development.

Writes a sample event for a given event_type to the spool directory
(or directly to the relay server if reachable).

Usage:
    python shortcuts_pack/v2/emulate_shortcut.py --type ncl.mood.check_in
    python shortcuts_pack/v2/emulate_shortcut.py --type ncl.focus.score --relay http://localhost:8787/event
    python shortcuts_pack/v2/emulate_shortcut.py --list
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

_SPOOL_DIR = Path(__file__).parent.parent.parent / "shortcuts_pack" / "v2" / "events"

_SAMPLES: dict[str, dict] = {
    "ncl.mood.check_in": {
        "mood_score": 7,
        "energy_score": 6,
        "stress_score": 4,
        "context": "morning",
        "notes_label": "Good night sleep, feeling ready.",
        "tags": ["morning_routine"],
    },
    "ncl.focus.score": {
        "date": str(datetime.date.today()),
        "score": 78,
        "deep_work_minutes": 120,
        "distraction_events": 4,
        "focus_blocks": 3,
        "grade": "B",
        "trend": "improving",
    },
    "ncl.health.mindfulness": {
        "session_start": datetime.datetime.now(datetime.UTC).isoformat(),
        "duration_minutes": 10,
        "modality": "guided",
        "app": "Calm",
    },
    "ncl.location.home_away": {
        "transition": "arrived_home",
        "occurred_at_local": datetime.datetime.now().isoformat(),
        "time_away_minutes": 240,
        "transport_mode": "drive",
        "place_label": "work",
    },
    "ncl.knowledge.capture": {
        "capture_type": "insight",
        "label": "Systems thinking: feedback loops compound over time.",
        "tags": ["systems", "mental-model"],
        "importance": 4,
        "follow_up": False,
    },
    "ncl.task.completed": {
        "task_label": "Write weekly review",
        "list_name": "Weekly",
        "completed_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "priority": "high",
    },
    "ncl.social.interaction": {
        "modality": "voice_call",
        "duration_minutes": 30,
        "participant_count": 2,
        "relationship_tier": "tier1_inner",
        "sentiment": "positive",
        "energy_delta": 2,
        "initiated_by_me": False,
    },
    "ncl.activity.workout": {
        "workout_type": "running",
        "duration_minutes": 35,
        "distance_km": 5.2,
        "start_time": datetime.datetime.now(datetime.UTC).isoformat(),
    },
    "ncl.sleep.duration": {
        "date": str(datetime.date.today()),
        "duration_hours": 7.5,
        "bedtime": "22:30",
        "wake_time": "06:00",
    },
}


def _wrap(event_type: str, payload: dict) -> dict:
    return {
        "schema_version": "ncl.iphone.v1",
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "occurred_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "device_model": "emulator",
        "payload": payload,
    }


def _emit_to_relay(event: dict, relay_url: str) -> bool:
    body = json.dumps(event).encode("utf-8")
    req = urllib.request.Request(
        relay_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"[OK] {resp.status} — event_id={event['event_id']}")
            return True
    except urllib.error.HTTPError as exc:
        print(f"[ERROR] HTTP {exc.code} — {exc.read().decode()}")
        return False
    except Exception as exc:
        print(f"[OFFLINE] Relay unreachable ({exc})")
        return False


def _write_spool(event: dict) -> Path:
    _SPOOL_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S%f")
    path = _SPOOL_DIR / f"{ts}--{event['event_id'][:8]}.json"
    path.write_text(json.dumps(event, indent=2), encoding="utf-8")
    print(f"[SPOOL] Written to {path}")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="Emulate NCL Shortcuts Pack v2")
    ap.add_argument("--type", metavar="EVENT_TYPE", help="Event type to emit")
    ap.add_argument("--relay", default=None, help="Relay URL (default: spool only)")
    ap.add_argument("--list", action="store_true", help="List available event types")
    args = ap.parse_args()

    if args.list:
        print("Available event types:")
        for et in sorted(_SAMPLES):
            print(f"  {et}")
        return

    if not args.type:
        ap.print_help()
        sys.exit(1)

    sample = _SAMPLES.get(args.type)
    if sample is None:
        print(f"[ERROR] Unknown event type: {args.type}")
        print("Use --list to see available types.")
        sys.exit(1)

    event = _wrap(args.type, sample)

    if args.relay:
        if not _emit_to_relay(event, args.relay):
            _write_spool(event)
    else:
        _write_spool(event)


if __name__ == "__main__":
    main()
