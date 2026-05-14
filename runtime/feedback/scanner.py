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


class FeedbackScanner:
    """Scans pillar report dirs, produces synthesis notes."""

    def __init__(self, base_dir: Path) -> None:
        self.base = Path(base_dir)
        self.synthesis_dir = self.base / "synthesis"
        self.synthesis_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.base / "LOG.md"

    def _iter_inbox(self) -> Iterable[tuple[str, Path]]:
        for pillar, sub in PILLAR_DIRS.items():
            inbox = self.base / sub
            if not inbox.exists():
                continue
            for path in sorted(inbox.glob("*.json")):
                yield pillar, path

    def _move_to(self, src: Path, dest_dir: Path) -> None:
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / src.name
        # Avoid clobbers — append timestamp on collision
        if target.exists():
            stem = target.stem
            target = dest_dir / f"{stem}-{int(datetime.now().timestamp())}.json"
        src.rename(target)

    def scan_once(self) -> SynthesisNote | None:
        """Run one scan pass. Returns the synthesis note (or None if no input)."""
        window_start = datetime.now(timezone.utc)
        consumed: list[FeedbackReport] = []
        consumed_ids: list[str] = []

        for pillar, path in self._iter_inbox():
            try:
                data = json.loads(path.read_text())
                report = FeedbackReport.model_validate(data)
                if report.pillar != pillar:
                    raise ValueError(
                        f"pillar field '{report.pillar}' does not match dir '{pillar}'"
                    )
                consumed.append(report)
                consumed_ids.append(report.report_id)
                self._move_to(path, path.parent / ".consumed")
            except Exception as e:
                log.warning(f"feedback report invalid {path.name}: {e}")
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
        out.write_text(note.model_dump_json(indent=2))

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
