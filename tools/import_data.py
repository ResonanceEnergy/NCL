#!/usr/bin/env python3
"""
NCL Data Import Tool
Import event logs, memory, and audit trails from a portable archive.
Validates integrity and merges without duplicates.
"""
import json
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from lib_ncl import append_ndjson, ensure_dirs, expanduser
except ImportError:
    def expanduser(p):
        return Path(os.path.expanduser(p))
    def ensure_dirs(*dirs):
        for d in dirs:
            Path(d).mkdir(parents=True, exist_ok=True)
    def append_ndjson(path, obj):
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(obj) + '\n')


def load_existing_event_ids(event_dir: Path) -> set[str]:
    """Load all existing event IDs from NDJSON files to avoid duplicates."""
    ids = set()
    if event_dir.exists():
        for f in event_dir.glob("*.ndjson"):
            for line in f.read_text(encoding="utf-8").strip().split("\n"):
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                    eid = evt.get("event_id")
                    if eid:
                        ids.add(eid)
                except json.JSONDecodeError:
                    continue
    return ids


def import_data(archive_path: Path, ncl_root: Path,
                import_events: bool = True, import_memory: bool = True,
                import_audit: bool = True, import_reports: bool = True,
                dry_run: bool = False) -> dict[str, int] | None:
    """Import NCL data from a zip archive.

    Returns a stats dict on success, or ``None`` if the archive is missing.
    """

    if not archive_path.exists():
        print(f"Error: archive not found: {archive_path}")
        return None

    stats = {"events_imported": 0, "events_skipped": 0,
             "memory_files": 0, "audit_files": 0, "reports": 0}

    with zipfile.ZipFile(archive_path, 'r') as zf:
        # Read manifest
        manifest = {}
        if "manifest.json" in zf.namelist():
            manifest = json.loads(zf.read("manifest.json"))
            print(f"Importing archive from {manifest.get('exported_at', 'unknown')}")
            print(f"  NCL version: {manifest.get('ncl_version', 'unknown')}")
            print(f"  Anonymized: {manifest.get('anonymized', 'unknown')}")

        # Events
        if import_events:
            event_dir = ncl_root / "data" / "event_log"
            if not dry_run:
                ensure_dirs(event_dir)
            existing_ids = load_existing_event_ids(event_dir)

            for name in sorted(zf.namelist()):
                if not name.startswith("events/") or not name.endswith(".ndjson"):
                    continue
                content = zf.read(name).decode("utf-8")
                basename = Path(name).name
                target = event_dir / basename

                for line in content.strip().split("\n"):
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                        eid = evt.get("event_id")
                        if eid and eid in existing_ids:
                            stats["events_skipped"] += 1
                            continue
                        if not dry_run:
                            append_ndjson(target, evt)
                        if eid:
                            existing_ids.add(eid)
                        stats["events_imported"] += 1
                    except json.JSONDecodeError:
                        continue

        # Memory
        if import_memory:
            memory_dir = ncl_root / "memory"
            for name in zf.namelist():
                if not name.startswith("memory/"):
                    continue
                rel = name[len("memory/"):]
                if not rel:
                    continue
                target = memory_dir / rel
                if not dry_run:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(name))
                stats["memory_files"] += 1

        # Audit
        if import_audit:
            audit_dir = ncl_root / "audit"
            if not dry_run:
                ensure_dirs(audit_dir)
            for name in zf.namelist():
                if not name.startswith("audit/") or not name.endswith(".json"):
                    continue
                basename = Path(name).name
                target = audit_dir / basename
                if not target.exists():
                    if not dry_run:
                        target.write_bytes(zf.read(name))
                    stats["audit_files"] += 1

        # Reports
        if import_reports:
            report_dir = ncl_root / "dist" / "reports"
            for name in zf.namelist():
                if not name.startswith("reports/") or not name.endswith(".md"):
                    continue
                rel = name[len("reports/"):]
                if not rel:
                    continue
                target = report_dir / rel
                if not dry_run:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(name))
                stats["reports"] += 1

    prefix = "[DRY RUN] " if dry_run else ""
    print(f"\n{prefix}Import complete:")
    print(f"  Events imported: {stats['events_imported']}")
    print(f"  Events skipped (duplicate): {stats['events_skipped']}")
    print(f"  Memory files: {stats['memory_files']}")
    print(f"  Audit files: {stats['audit_files']}")
    print(f"  Reports: {stats['reports']}")
    return stats


def main():
    import argparse
    ap = argparse.ArgumentParser(description="NCL Data Import")
    ap.add_argument("archive", help="Path to NCL export zip")
    ap.add_argument("--root", default="~/NCL", help="NCL root directory")
    ap.add_argument("--no-events", action="store_true")
    ap.add_argument("--no-memory", action="store_true")
    ap.add_argument("--no-audit", action="store_true")
    ap.add_argument("--no-reports", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="Preview without importing")
    args = ap.parse_args()

    ncl_root = expanduser(args.root)
    import_data(
        Path(args.archive), ncl_root,
        import_events=not args.no_events,
        import_memory=not args.no_memory,
        import_audit=not args.no_audit,
        import_reports=not args.no_reports,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()
