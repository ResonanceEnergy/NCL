#!/usr/bin/env python3
"""
NCL Backup & Restore — automated SQLite backup with rotation.

Backs up the three NCL SQLite databases (working, short-term, long-term memory)
and the NDJSON event log directory to a timestamped archive.

Usage:
    python tools/backup_restore.py backup              # backup now → backups/
    python tools/backup_restore.py restore <archive>   # restore from archive
    python tools/backup_restore.py list                # list available backups
    python tools/backup_restore.py prune --keep 30     # remove old backups (keep N)

Configuration (environment variables):
    NCL_BACKUP_DIR   — where to store backups (default: ~/NCL/backups)
    NCL_DATA_DIR     — NCL data root (default: ~/NCL)
    NCL_MEMORY_DIR   — memory SQLite root (default: ~/NCL/memory)
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import shutil
import sqlite3
import sys
import tarfile
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s ncl.backup %(levelname)s %(message)s",
)
logger = logging.getLogger("ncl.backup")

_DEFAULT_BACKUP_DIR = Path(os.environ.get("NCL_BACKUP_DIR", "~/NCL/backups")).expanduser()
_DEFAULT_DATA_DIR = Path(os.environ.get("NCL_DATA_DIR", "~/NCL")).expanduser()
_DEFAULT_MEMORY_DIR = Path(os.environ.get("NCL_MEMORY_DIR", "~/NCL/memory")).expanduser()


def _ts() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")


def backup(backup_dir: Path = _DEFAULT_BACKUP_DIR) -> Path:
    """Create a timestamped backup archive. Returns path to the archive."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = _ts()
    archive_path = backup_dir / f"ncl_backup_{ts}.tar.gz"

    staging = backup_dir / f".staging_{ts}"
    staging.mkdir(parents=True, exist_ok=True)

    try:
        manifest: dict = {"created_at": ts, "sources": []}

        # 1. SQLite databases — use sqlite3 backup API for safe hot-copy
        memory_dir = _DEFAULT_MEMORY_DIR
        db_names = ["working_memory.db", "short_term.db", "long_term.db"]
        for db_name in db_names:
            src = memory_dir / db_name
            if src.exists():
                dst = staging / db_name
                _sqlite_backup(src, dst)
                manifest["sources"].append(str(src))
                logger.info("Backed up database: %s", db_name)

        # 2. NDJSON event log directory
        event_log = _DEFAULT_DATA_DIR / "data" / "event_log"
        if event_log.exists():
            dst_events = staging / "event_log"
            shutil.copytree(str(event_log), str(dst_events))
            manifest["sources"].append(str(event_log))
            ndjson_count = sum(1 for _ in event_log.rglob("*.ndjson"))
            logger.info("Backed up event log (%d NDJSON files).", ndjson_count)

        # 3. ncl_config.json
        config_src = Path(__file__).parent.parent / "ncl_config.json"
        if config_src.exists():
            shutil.copy2(str(config_src), str(staging / "ncl_config.json"))
            manifest["sources"].append(str(config_src))

        # Write manifest
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        # Create compressed archive
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(staging, arcname="ncl_backup")

        logger.info("Backup complete: %s", archive_path)
        return archive_path

    finally:
        shutil.rmtree(staging, ignore_errors=True)


def restore(archive_path: Path) -> None:
    """Restore from a backup archive. OVERWRITES current databases."""
    archive_path = Path(archive_path)
    if not archive_path.exists():
        logger.error("Archive not found: %s", archive_path)
        sys.exit(1)

    staging = archive_path.parent / f".restore_{_ts()}"
    staging.mkdir(parents=True, exist_ok=True)

    try:
        logger.info("Extracting %s...", archive_path.name)
        with tarfile.open(archive_path, "r:gz") as tar:
            # filter="data" prevents path traversal and chmod attacks (Python 3.12+;
            # silently ignored on older interpreters where it is not yet the default)
            tar.extractall(staging, filter="data")

        src_base = staging / "ncl_backup"

        # Restore databases
        memory_dir = _DEFAULT_MEMORY_DIR
        memory_dir.mkdir(parents=True, exist_ok=True)

        for db_name in ["working_memory.db", "short_term.db", "long_term.db"]:
            src = src_base / db_name
            if src.exists():
                dst = memory_dir / db_name
                _sqlite_backup(src, dst)
                logger.info("Restored database: %s", db_name)

        # Restore event log
        src_events = src_base / "event_log"
        if src_events.exists():
            dst_events = _DEFAULT_DATA_DIR / "data" / "event_log"
            dst_events.mkdir(parents=True, exist_ok=True)
            for f in src_events.rglob("*.ndjson"):
                rel = f.relative_to(src_events)
                dst_file = dst_events / rel
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(f), str(dst_file))
            logger.info("Restored event log.")

        # Restore config (optional)
        src_config = src_base / "ncl_config.json"
        if src_config.exists():
            dst_config = Path(__file__).parent.parent / "ncl_config_restored.json"
            shutil.copy2(str(src_config), str(dst_config))
            logger.info("Config saved as ncl_config_restored.json (manual merge required).")

        logger.info("Restore complete from %s.", archive_path.name)

    finally:
        shutil.rmtree(staging, ignore_errors=True)


def list_backups(backup_dir: Path = _DEFAULT_BACKUP_DIR) -> list[Path]:
    """List available backups sorted newest first."""
    if not backup_dir.exists():
        print("No backups directory found.")
        return []
    archives = sorted(backup_dir.glob("ncl_backup_*.tar.gz"), reverse=True)
    if not archives:
        print("No backups found.")
    else:
        print(f"{'Archive':<55} {'Size':>10}")
        print("-" * 67)
        for p in archives:
            size_mb = p.stat().st_size / 1_048_576
            print(f"{p.name:<55} {size_mb:>8.2f} MB")
    return archives


def prune(backup_dir: Path = _DEFAULT_BACKUP_DIR, keep: int = 30) -> None:
    """Remove old backups, keeping the most recent *keep* archives."""
    archives = sorted(backup_dir.glob("ncl_backup_*.tar.gz"), reverse=True)
    to_delete = archives[keep:]
    if not to_delete:
        logger.info("Nothing to prune (found %d backups, keep=%d).", len(archives), keep)
        return
    for p in to_delete:
        p.unlink()
        logger.info("Pruned %s", p.name)
    logger.info("Pruned %d old backup(s). Kept %d.", len(to_delete), min(len(archives), keep))


def _sqlite_backup(src: Path, dst: Path) -> None:
    """Safe hot-copy using sqlite3 backup API."""
    src_conn = sqlite3.connect(str(src))
    dst_conn = sqlite3.connect(str(dst))
    try:
        src_conn.backup(dst_conn)
    finally:
        src_conn.close()
        dst_conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="NCL Backup & Restore")
    sub = ap.add_subparsers(dest="command", required=True)

    bp = sub.add_parser("backup", help="Backup NCL data now")
    bp.add_argument("--dir", default=str(_DEFAULT_BACKUP_DIR), help="Backup output directory")

    rp = sub.add_parser("restore", help="Restore from a backup archive")
    rp.add_argument("archive", help="Path to the .tar.gz backup archive")

    sub.add_parser("list", help="List available backups")

    pp = sub.add_parser("prune", help="Remove old backups")
    pp.add_argument("--keep", type=int, default=30, help="Number of recent backups to keep")

    args = ap.parse_args()

    if args.command == "backup":
        archive = backup(backup_dir=Path(args.dir).expanduser())
        print(f"Backup: {archive}")

    elif args.command == "restore":
        confirm = input(
            f"⚠  This will OVERWRITE current NCL data with {args.archive}.\n"
            "Type 'yes' to confirm: "
        )
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            sys.exit(0)
        restore(Path(args.archive))

    elif args.command == "list":
        list_backups()

    elif args.command == "prune":
        prune(keep=args.keep)


if __name__ == "__main__":
    main()
