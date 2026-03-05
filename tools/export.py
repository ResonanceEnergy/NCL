#!/usr/bin/env python3
"""
NCL Data Export Tool
Export event logs, memory, audit trails, and reports to portable archive.
Privacy-aware: respects sensitivity levels and anonymization settings.
"""
import json
import os
import sys
import shutil
import hashlib
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from lib_ncl import expanduser
except ImportError:
    def expanduser(p):
        return Path(os.path.expanduser(p))


def anonymize_event(event: dict, level: str = "P2") -> dict:
    """Strip PII / sensitive fields based on privacy level."""
    clean = dict(event)

    # Always remove raw content above threshold
    privacy = clean.get("privacy", {})
    event_level = privacy.get("level", "P3")

    pii_fields = {"name", "email", "phone", "address", "ssn", "ip_address",
                  "location", "gps", "user_name", "full_name"}

    if event_level in ("P0", "P1"):
        # Strip payload entirely for high-sensitivity events
        clean["payload"] = {"redacted": True, "reason": f"sensitivity={event_level}"}
    else:
        # Scrub known PII fields
        if "payload" in clean and isinstance(clean["payload"], dict):
            for field in pii_fields:
                if field in clean["payload"]:
                    clean["payload"][field] = f"[REDACTED-{hashlib.sha256(str(clean['payload'][field]).encode()).hexdigest()[:8]}]"

    # Remove source.ip if present
    if "source" in clean and isinstance(clean["source"], dict):
        clean["source"].pop("ip_address", None)
        clean["source"].pop("ip", None)

    return clean


def export_data(ncl_root: Path, output_path: Path,
                include_events: bool = True, include_memory: bool = True,
                include_audit: bool = True, include_reports: bool = True,
                anonymize: bool = True, date_from: Optional[str] = None,
                date_to: Optional[str] = None) -> Dict[str, Any]:
    """Export NCL data to a zip archive.

    Returns the manifest dict describing what was exported.
    """

    manifest = {
        "export_version": "1.0",
        "exported_at": datetime.now().isoformat(),
        "ncl_version": "3.0",
        "anonymized": anonymize,
        "date_range": {"from": date_from, "to": date_to},
        "contents": {}
    }

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:

        # Events
        if include_events:
            event_dir = ncl_root / "data" / "event_log"
            count = 0
            if event_dir.exists():
                for ndjson_file in sorted(event_dir.glob("*.ndjson")):
                    day = ndjson_file.stem
                    if date_from and day < date_from:
                        continue
                    if date_to and day > date_to:
                        continue
                    lines = []
                    for line in ndjson_file.read_text(encoding="utf-8").strip().split("\n"):
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                            if anonymize:
                                event = anonymize_event(event)
                            lines.append(json.dumps(event))
                            count += 1
                        except json.JSONDecodeError:
                            continue
                    zf.writestr(f"events/{ndjson_file.name}", "\n".join(lines))
            manifest["contents"]["events"] = count

        # Memory
        if include_memory:
            memory_dir = ncl_root / "memory"
            count = 0
            if memory_dir.exists():
                for f in memory_dir.rglob("*"):
                    if f.is_file() and f.suffix in (".json", ".db", ".ndjson"):
                        arcname = f"memory/{f.relative_to(memory_dir)}"
                        zf.write(f, arcname)
                        count += 1
            manifest["contents"]["memory_files"] = count

        # Audit
        if include_audit:
            audit_dir = ncl_root / "audit"
            count = 0
            if audit_dir.exists():
                for f in sorted(audit_dir.glob("*.json")):
                    zf.write(f, f"audit/{f.name}")
                    count += 1
            manifest["contents"]["audit"] = count

        # Reports
        if include_reports:
            report_dir = ncl_root / "dist" / "reports"
            count = 0
            if report_dir.exists():
                for f in report_dir.rglob("*.md"):
                    arcname = f"reports/{f.relative_to(report_dir)}"
                    zf.write(f, arcname)
                    count += 1
            manifest["contents"]["reports"] = count

        # Write manifest
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    print(f"Exported to {output_path}")
    print(f"  Contents: {json.dumps(manifest['contents'])}")
    return manifest


def main():
    import argparse
    ap = argparse.ArgumentParser(description="NCL Data Export")
    ap.add_argument("--output", "-o", default="ncl_export.zip", help="Output zip path")
    ap.add_argument("--root", default="~/NCL", help="NCL root directory")
    ap.add_argument("--no-events", action="store_true", help="Skip events")
    ap.add_argument("--no-memory", action="store_true", help="Skip memory")
    ap.add_argument("--no-audit", action="store_true", help="Skip audit")
    ap.add_argument("--no-reports", action="store_true", help="Skip reports")
    ap.add_argument("--no-anonymize", action="store_true", help="Skip anonymization")
    ap.add_argument("--from", dest="date_from", help="Start date (YYYY-MM-DD)")
    ap.add_argument("--to", dest="date_to", help="End date (YYYY-MM-DD)")
    args = ap.parse_args()

    ncl_root = expanduser(args.root)
    export_data(
        ncl_root, Path(args.output),
        include_events=not args.no_events,
        include_memory=not args.no_memory,
        include_audit=not args.no_audit,
        include_reports=not args.no_reports,
        anonymize=not args.no_anonymize,
        date_from=args.date_from,
        date_to=args.date_to
    )


if __name__ == "__main__":
    main()
