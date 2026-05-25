"""W11-2 — Reorganize YTC council reports into per-date subfolders.

Idempotent migration that:

1.  Walks ``intelligence-scan/council-reports/`` for filenames matching
    ``ytc-dedicated-*`` or ``youtube-council-*`` (json + md). For each
    file it parses the date (YYYY-MM-DD) — directly from
    ``youtube-council-YYYY-MM-DD-...`` filenames, or by normalising the
    embedded ``YYYYMMDD`` stamp in ``ytc-dedicated-YYYYMMDD-...``
    filenames — and moves the file to::

        intelligence-scan/council-reports/youtube/YYYY-MM-DD/<original>

    Already-relocated files (anything already living under the
    ``youtube/`` subtree) are skipped, so the script is safe to re-run.

2.  Once the YTC migration is in place, verifies that every
    ``session_id`` present under ``intelligence-scan/youtube-reports/``
    is also present in the new ``council-reports/youtube/<date>/`` tree
    (or in any youtube-council file we just moved). When the check
    passes, the parallel ``youtube-reports/`` directory is deleted.

Run with ``--dry-run`` (the default unless ``--apply`` is supplied) to
preview moves + deletion without touching disk. Reports total files +
bytes that would be moved.

Usage::

    python3 scripts/reorganize_ytc_reports.py --dry-run
    python3 scripts/reorganize_ytc_reports.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path


NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
COUNCIL_REPORTS = NCL_BASE / "intelligence-scan" / "council-reports"
YOUTUBE_SUBDIR = COUNCIL_REPORTS / "youtube"
PARALLEL_YT_REPORTS = NCL_BASE / "intelligence-scan" / "youtube-reports"


# Filename patterns that should be moved into the per-date youtube/ tree.
# Anchored at start of basename — we only match top-level reports, not
# anything already sitting under ``council-reports/youtube/``.
YTC_DEDICATED_RE = re.compile(r"^ytc-dedicated-(\d{8})")          # YYYYMMDD
YOUTUBE_COUNCIL_RE = re.compile(r"^youtube-council-(\d{4}-\d{2}-\d{2})")


def _parse_date(name: str) -> str | None:
    """Return YYYY-MM-DD parsed from a YTC/youtube-council filename, or None."""
    m = YOUTUBE_COUNCIL_RE.match(name)
    if m:
        return m.group(1)
    m = YTC_DEDICATED_RE.match(name)
    if m:
        raw = m.group(1)  # YYYYMMDD
        try:
            return datetime.strptime(raw, "%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def _iter_top_level_ytc_files() -> list[Path]:
    """Top-level (non-recursive) files in council-reports matching YTC names."""
    if not COUNCIL_REPORTS.exists():
        return []
    out: list[Path] = []
    for p in COUNCIL_REPORTS.iterdir():
        if not p.is_file():
            continue
        if YOUTUBE_COUNCIL_RE.match(p.name) or YTC_DEDICATED_RE.match(p.name):
            out.append(p)
    return out


def _collect_session_ids_under_youtube(root: Path) -> set[str]:
    """Read every *.json under root and return the set of ``session_id``s
    we find. Used to verify the parallel ``youtube-reports/`` dir is fully
    represented before we delete it.
    """
    ids: set[str] = set()
    if not root.exists():
        return ids
    for f in root.rglob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        sid = data.get("session_id")
        if isinstance(sid, str) and sid:
            ids.add(sid)
    return ids


def _collect_session_ids_in_dir(d: Path) -> set[str]:
    ids: set[str] = set()
    if not d.exists():
        return ids
    for f in d.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        sid = data.get("session_id")
        if isinstance(sid, str) and sid:
            ids.add(sid)
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group()
    g.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Print planned actions without touching disk (default).",
    )
    g.add_argument(
        "--apply",
        dest="apply",
        action="store_true",
        help="Actually perform the moves + delete parallel youtube-reports/.",
    )
    args = parser.parse_args()

    # Default to dry-run unless --apply is explicitly passed.
    dry_run = not args.apply

    if not COUNCIL_REPORTS.exists():
        print(f"council-reports directory missing: {COUNCIL_REPORTS}", file=sys.stderr)
        return 2

    candidates = _iter_top_level_ytc_files()
    moves: list[tuple[Path, Path, int]] = []
    skipped_no_date: list[Path] = []
    skipped_already_placed: list[Path] = []

    for src in candidates:
        date = _parse_date(src.name)
        if not date:
            skipped_no_date.append(src)
            continue
        dest_dir = YOUTUBE_SUBDIR / date
        dest = dest_dir / src.name
        if dest.exists():
            # Already moved (re-run idempotency) — skip silently.
            skipped_already_placed.append(src)
            continue
        try:
            size = src.stat().st_size
        except OSError:
            size = 0
        moves.append((src, dest, size))

    total_bytes = sum(m[2] for m in moves)
    print(f"=== W11-2 YTC reorg ({'DRY-RUN' if dry_run else 'APPLY'}) ===")
    print(f"Base: {NCL_BASE}")
    print(f"Source dir: {COUNCIL_REPORTS}")
    print(f"Target dir: {YOUTUBE_SUBDIR}/<YYYY-MM-DD>/")
    print(f"Top-level YTC candidates: {len(candidates)}")
    print(f"  - to move:                {len(moves)}")
    print(f"  - already in date subdir: {len(skipped_already_placed)}")
    print(f"  - unparseable date:       {len(skipped_no_date)}")
    print(f"Total bytes to move: {total_bytes:,} ({total_bytes / 1024 / 1024:.2f} MiB)")
    if skipped_no_date:
        print("\nFiles skipped (could not parse date):")
        for p in skipped_no_date[:10]:
            print(f"  ! {p.name}")
        if len(skipped_no_date) > 10:
            print(f"  ... and {len(skipped_no_date) - 10} more")

    # Group preview by destination date.
    by_date: dict[str, int] = {}
    for _src, dest, _size in moves:
        by_date[dest.parent.name] = by_date.get(dest.parent.name, 0) + 1
    if by_date:
        print("\nPlanned moves per date:")
        for d in sorted(by_date):
            print(f"  {d}: {by_date[d]:>4} files")

    # ── Phase 1: move YTC reports into per-date subfolders ───────────────
    if not dry_run and moves:
        YOUTUBE_SUBDIR.mkdir(parents=True, exist_ok=True)
        moved = 0
        for src, dest, _size in moves:
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(src), str(dest))
                moved += 1
            except Exception as e:
                print(f"  ! move failed: {src.name} -> {dest}: {e}", file=sys.stderr)
        print(f"\nMoved {moved}/{len(moves)} files into per-date subfolders.")

    # ── Phase 2: verify + delete parallel youtube-reports/ dir ───────────
    yr_ids = _collect_session_ids_under_youtube(PARALLEL_YT_REPORTS)
    if not PARALLEL_YT_REPORTS.exists():
        print(f"\nParallel youtube-reports/ already gone — nothing to verify.")
    else:
        # Build the set of session_ids represented in the new tree. In
        # dry-run mode the moves haven't happened yet, so union the
        # already-placed youtube/ subtree with the top-level YTC files
        # we *would* move.
        if dry_run:
            new_tree_ids = _collect_session_ids_under_youtube(YOUTUBE_SUBDIR)
            for src in candidates:
                try:
                    data = json.loads(src.read_text(encoding="utf-8"))
                except Exception:
                    continue
                sid = data.get("session_id")
                if isinstance(sid, str) and sid:
                    new_tree_ids.add(sid)
        else:
            new_tree_ids = _collect_session_ids_under_youtube(YOUTUBE_SUBDIR)

        missing = yr_ids - new_tree_ids
        print(f"\nParallel youtube-reports/ session_id check:")
        print(f"  youtube-reports/ session_ids: {len(yr_ids)}")
        print(f"  council-reports/youtube/ session_ids (post-move): {len(new_tree_ids)}")
        if missing:
            print(
                f"  ! {len(missing)} session_id(s) in youtube-reports/ NOT found in "
                f"council-reports/youtube/ — NOT deleting parallel dir."
            )
            for sid in list(missing)[:5]:
                print(f"      missing: {sid}")
            if len(missing) > 5:
                print(f"      ... and {len(missing) - 5} more")
        else:
            print(
                f"  OK — every youtube-reports/ session_id is represented in the new tree."
            )
            if dry_run:
                print(
                    f"  [DRY-RUN] would delete {PARALLEL_YT_REPORTS} "
                    f"({sum(f.stat().st_size for f in PARALLEL_YT_REPORTS.rglob('*') if f.is_file()):,} bytes)"
                )
            else:
                try:
                    shutil.rmtree(PARALLEL_YT_REPORTS)
                    print(f"  Deleted {PARALLEL_YT_REPORTS}")
                except Exception as e:
                    print(f"  ! rmtree failed: {e}", file=sys.stderr)
                    return 3

    if dry_run:
        print("\n(dry-run — re-run with --apply to perform moves)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
