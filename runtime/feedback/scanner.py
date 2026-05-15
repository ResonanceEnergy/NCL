"""Feedback scanner — consumes {pillar}-reports/*.json on an interval.

On each tick:
  1. Walk feedback-synthesis/{ncc,brs,aac}-reports/ for new *.json
  2. Validate against FeedbackReport schema
  3. Move processed → feedback-synthesis/{pillar}-reports/.consumed/
  4. Move invalid → feedback-synthesis/{pillar}-reports/.quarantine/
  5. Write SynthesisNote to feedback-synthesis/synthesis/synth-<ts>.json
  6. Append summary line to feedback-synthesis/LOG.md
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import FeedbackReport, SynthesisNote

log = logging.getLogger("ncl.feedback")

PILLAR_DIRS: dict[str, str] = {
    "NCC": "ncc-reports",
    "BRS": "brs-reports",
    "AAC": "aac-reports",
}

# Rate limiting: max reports to process per scan pass (prevents runaway I/O
# if thousands of files appear at once, e.g. after a long outage).
MAX_REPORTS_PER_SCAN = 100

# Maximum size (bytes) of a single feedback report file — oversized files are
# quarantined without reading to prevent memory exhaustion.
MAX_REPORT_FILE_BYTES = 1 * 1024 * 1024  # 1 MB


class FeedbackScanner:
    """Scans pillar report dirs, produces synthesis notes."""

    def __init__(self, base_dir: Path) -> None:
        self.base = Path(base_dir)
        self.synthesis_dir = self.base / "synthesis"
        self.synthesis_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.base / "LOG.md"
        self._last_scan_ts: float = 0.0   # monotonic time of last scan (for external callers)

    def _iter_inbox(self) -> Iterable[tuple[str, Path]]:
        for pillar, sub in PILLAR_DIRS.items():
            inbox = self.base / sub
            if not inbox.exists():
                continue
            for path in sorted(inbox.glob("*.json")):
                yield pillar, path

    def _move_to(self, src: Path, dest_dir: Path) -> None:
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            target = dest_dir / src.name
            # Avoid clobbers — append timestamp on collision
            if target.exists():
                stem = target.stem
                target = dest_dir / f"{stem}-{int(datetime.now().timestamp())}.json"
            shutil.move(str(src), str(target))
        except OSError as e:
            log.error("Failed to move %s → %s: %s", src.name, dest_dir, e)

    def scan_once(self) -> SynthesisNote | None:
        """Run one scan pass. Returns the synthesis note (or None if no input)."""
        self._last_scan_ts = time.monotonic()
        window_start = datetime.now(timezone.utc)
        consumed: list[FeedbackReport] = []
        consumed_ids: list[str] = []
        processed_count = 0

        for pillar, path in self._iter_inbox():
            # Rate limit: stop processing when per-scan cap is reached
            if processed_count >= MAX_REPORTS_PER_SCAN:
                log.warning(
                    "Rate limit reached (%d reports/scan). Remaining files will be "
                    "processed on the next tick.",
                    MAX_REPORTS_PER_SCAN,
                )
                break

            processed_count += 1

            try:
                # Guard against oversized files
                try:
                    file_size = path.stat().st_size
                except OSError as e:
                    log.warning("Cannot stat %s: %s — skipping", path.name, e)
                    self._move_to(path, path.parent / ".quarantine")
                    continue

                if file_size > MAX_REPORT_FILE_BYTES:
                    log.warning(
                        "Feedback report %s is too large (%d bytes > %d limit) — quarantining",
                        path.name, file_size, MAX_REPORT_FILE_BYTES,
                    )
                    self._move_to(path, path.parent / ".quarantine")
                    continue

                data = json.loads(path.read_text(encoding="utf-8"))
                report = FeedbackReport.model_validate(data)
                if report.pillar != pillar:
                    raise ValueError(
                        f"pillar field '{report.pillar}' does not match dir '{pillar}'"
                    )
                consumed.append(report)
                consumed_ids.append(report.report_id)
                self._move_to(path, path.parent / ".consumed")
            except Exception as e:
                log.warning("feedback report invalid %s: %s", path.name, e)
                self._move_to(path, path.parent / ".quarantine")

        if not consumed:
            return None

        window_end = datetime.now(timezone.utc)
        by_pillar = Counter(r.pillar for r in consumed)
        by_outcome = Counter(r.outcome for r in consumed)
        open_blockers = [
            {
                "pillar": r.pillar,
                "blocker": b,
                "mandate_id": r.mandate_id or "",
            }
            for r in consumed
            for b in r.blockers
        ]
        suggested = [
            r.next_action_request for r in consumed if r.next_action_request
        ]

        ts = window_end.strftime("%Y%m%d-%H%M%S")
        note = SynthesisNote(
            synthesis_id=f"synth-{ts}",
            generated_at=window_end,
            window_start=window_start,
            window_end=window_end,
            reports_consumed=len(consumed),
            by_pillar=dict(by_pillar),
            by_outcome=dict(by_outcome),
            open_blockers=open_blockers,
            suggested_adjustments=suggested,
            raw_report_ids=consumed_ids,
        )

        out = self.synthesis_dir / f"{note.synthesis_id}.json"
        try:
            out.write_text(note.model_dump_json(indent=2), encoding="utf-8")
        except OSError as e:
            log.error("Failed to write synthesis note %s: %s", out.name, e)
            return note  # still return the in-memory note even if write failed

        # Append a one-line LOG entry
        summary_line = (
            f"- {ts} | {len(consumed)} reports "
            f"({dict(by_pillar)}) outcomes={dict(by_outcome)} "
            f"blockers={len(open_blockers)} → {out.name}\n"
        )
        try:
            with self.log_path.open("a") as f:
                f.write(summary_line)
        except Exception as e:
            log.warning(f"failed to append feedback LOG.md: {e}")

        log.info(
            f"feedback synthesis: {len(consumed)} reports consumed → {out.name}"
        )
        return note
