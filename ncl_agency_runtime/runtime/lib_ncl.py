import os, json, datetime
from pathlib import Path


def expanduser(p: str) -> Path:
    return Path(os.path.expanduser(p)).resolve()


def ensure_dirs(*paths: Path):
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)


def day_file(event_log_dir: Path, occurred_at_iso: str) -> Path:
    # Use local date
    try:
        dt = datetime.datetime.fromisoformat(occurred_at_iso)
    except Exception:
        dt = datetime.datetime.now().astimezone()
    day = dt.date().isoformat()
    return event_log_dir / f"{day}.ndjson"


def append_ndjson(path: Path, obj: dict):
    line = json.dumps(obj, ensure_ascii=False)
    with path.open('a', encoding='utf-8') as f:
        f.write(line + "\n")


def validate_minimal(event: dict):
    # Minimal validation aligned with schema required fields.
    required = ["schema_version","event_id","event_type","occurred_at","source","privacy","payload"]
    for k in required:
        if k not in event:
            return False, f"missing:{k}"
    if event.get("schema_version") != "ncl.event.v1":
        return False, "bad_schema_version"
    if not isinstance(event.get("source"), dict) or "device" not in event["source"] or "origin" not in event["source"]:
        return False, "bad_source"
    if not isinstance(event.get("privacy"), dict) or event["privacy"].get("level") not in ["P0","P1","P2","P3"]:
        return False, "bad_privacy"
    if not isinstance(event.get("payload"), dict):
        return False, "bad_payload"
    return True, "ok"
