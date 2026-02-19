#!/usr/bin/env python3
"""Emulate a Shortcut by writing an NCL envelope JSON event to shortcuts_pack/v1/events/"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

OUT_DIR = os.path.join(os.path.dirname(__file__), "events")

def make_envelope(event_type: str, payload: dict, overrides: dict | None = None) -> dict:
    env = {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "schema_version": "ncl.iphone.v1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ingestion_method": "shortcut",
        "permission": {"granted": True},
        "retention_tier": "short",
        "privacy_level": "metadata_only",
        "provenance": {"source": "Shortcut"},
        "payload": payload or {}
    }
    if overrides:
        env.update(overrides)
    return env


def write_event(event: dict):
    os.makedirs(OUT_DIR, exist_ok=True)
    ts = event["timestamp"].replace(":", "-")
    fname = f"{ts}--{event['event_type'].replace('.', '_')}.json"
    path = os.path.join(OUT_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(event, f, indent=2)
    print(path)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--type", required=True, help="event_type to emit (eg ncl.device.pickup)")
    p.add_argument("--payload", help="path to JSON payload to merge into envelope payload")
    args = p.parse_args()

    payload = {}
    event = None
    if args.payload:
        with open(args.payload, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
        # If the provided file already looks like a full NCL envelope, use it (but fill defaults).
        if isinstance(obj, dict) and ("event_type" in obj or ("payload" in obj and "schema_version" in obj)):
            event = obj
            # ensure minimal required envelope fields exist
            if "event_id" not in event:
                event["event_id"] = str(uuid4())
            if "timestamp" not in event:
                event["timestamp"] = datetime.now(timezone.utc).isoformat()
            if "schema_version" not in event:
                event["schema_version"] = "ncl.iphone.v1"
            if "ingestion_method" not in event:
                event["ingestion_method"] = "shortcut"
            if "provenance" not in event:
                event["provenance"] = {"source": "Shortcut"}
        else:
            # treat the file as the payload object
            payload = obj
            event = make_envelope(args.type, payload)
    else:
        event = make_envelope(args.type, {})

    write_event(event)
