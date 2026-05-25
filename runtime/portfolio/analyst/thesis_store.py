"""
Thesis on-disk store.

One JSON file per position at:
    data/portfolio/analyst/theses/<safe_instrument_id>.json

Closed theses move to:
    data/portfolio/analyst/theses/closed/<safe_instrument_id>__<exit_date>.json

Why per-file (not one big JSONL)? Theses are read individually by:
  - iOS (one tap = one thesis detail view)
  - The nightly evaluator (iterate held positions, load each)
  - The Morning Brief (load only theses for held instruments)

Per-file gives natural concurrency, easy debugging, and clean delete
semantics. The whole directory is small (one position = one file under
50 KB).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .theses import PositionThesis, ThesisStatus


log = logging.getLogger("ncl.portfolio.analyst.thesis_store")


# Restrict filenames to a safe charset — instrument_ids contain colons
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(instrument_id: str) -> str:
    """Map an instrument_id like 'EQ:AAPL:US' to a filesystem-safe name."""
    return _SAFE_RE.sub("_", instrument_id)


class ThesisStore:
    """Persist + load PositionThesis objects."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.theses_dir = self.data_dir / "portfolio" / "analyst" / "theses"
        self.closed_dir = self.theses_dir / "closed"
        self.theses_dir.mkdir(parents=True, exist_ok=True)
        self.closed_dir.mkdir(parents=True, exist_ok=True)

    # ── single-thesis I/O ─────────────────────────────────────────────

    def _path(self, instrument_id: str) -> Path:
        return self.theses_dir / f"{_safe_filename(instrument_id)}.json"

    async def load(self, instrument_id: str) -> Optional[PositionThesis]:
        """Load one thesis. Returns None if no file."""
        path = self._path(instrument_id)
        if not path.exists():
            return None

        def _read() -> Optional[PositionThesis]:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                return PositionThesis.model_validate(raw)
            except Exception as exc:
                log.warning("[THESIS-STORE] failed to load %s: %s", instrument_id, exc)
                return None

        return await asyncio.to_thread(_read)

    async def save(self, thesis: PositionThesis) -> None:
        """Atomic save: write to .tmp, fsync, rename."""
        path = self._path(thesis.instrument_id)
        tmp = path.with_suffix(".json.tmp")
        # Mutating updated_at on save is convenient
        thesis_to_save = thesis.model_copy(
            update={"updated_at": datetime.now(timezone.utc)}
        )

        def _do_write() -> None:
            payload = thesis_to_save.model_dump_json(indent=2)
            tmp.write_text(payload, encoding="utf-8")
            with open(tmp, "rb+") as f:
                os.fsync(f.fileno())
            os.replace(str(tmp), str(path))

        await asyncio.to_thread(_do_write)

    # ── close + archive ───────────────────────────────────────────────

    async def close(
        self,
        thesis: PositionThesis,
        exit_kind: str,
        exit_price: Optional[float] = None,
        final_pl_pct: Optional[float] = None,
        post_mortem: Optional[str] = None,
    ) -> PositionThesis:
        """Move a thesis to the closed/ archive with exit metadata.

        Returns the closed copy; removes the live file.
        """
        now = datetime.now(timezone.utc)
        status_map = {
            "target": ThesisStatus.EXITED_WIN,
            "stop": ThesisStatus.EXITED_LOSS,
            "time": ThesisStatus.EXITED_TIME,
            "thesis": ThesisStatus.EXITED_THESIS,
            "manual": ThesisStatus.EXITED_WIN if (final_pl_pct or 0) >= 0 else ThesisStatus.EXITED_LOSS,
        }
        new_status = status_map.get(exit_kind, ThesisStatus.EXITED_THESIS)

        closed = thesis.model_copy(
            update={
                "status": new_status,
                "exited_at": now,
                "exit_kind": exit_kind,
                "exit_price": exit_price,
                "final_pl_pct": final_pl_pct,
                "post_mortem": post_mortem,
                "updated_at": now,
            }
        )

        archive_name = (
            f"{_safe_filename(thesis.instrument_id)}__{now.strftime('%Y%m%d-%H%M%S')}.json"
        )
        archive_path = self.closed_dir / archive_name

        def _do_archive() -> None:
            archive_path.write_text(closed.model_dump_json(indent=2), encoding="utf-8")
            live = self._path(thesis.instrument_id)
            if live.exists():
                try:
                    live.unlink()
                except OSError:
                    pass

        await asyncio.to_thread(_do_archive)
        return closed

    # ── list ──────────────────────────────────────────────────────────

    async def list_active(self) -> list[PositionThesis]:
        """Return every live (non-closed) thesis."""

        def _scan() -> list[PositionThesis]:
            out: list[PositionThesis] = []
            for p in sorted(self.theses_dir.glob("*.json")):
                if "closed" in p.parts:
                    continue
                try:
                    raw = json.loads(p.read_text(encoding="utf-8"))
                    out.append(PositionThesis.model_validate(raw))
                except Exception as exc:
                    log.warning("[THESIS-STORE] skip bad file %s: %s", p, exc)
            return out

        return await asyncio.to_thread(_scan)

    async def list_closed(self, limit: int = 50) -> list[PositionThesis]:
        """Return recently-closed theses, newest first."""

        def _scan() -> list[PositionThesis]:
            files = sorted(self.closed_dir.glob("*.json"), reverse=True)[:limit]
            out: list[PositionThesis] = []
            for p in files:
                try:
                    raw = json.loads(p.read_text(encoding="utf-8"))
                    out.append(PositionThesis.model_validate(raw))
                except Exception:
                    pass
            return out

        return await asyncio.to_thread(_scan)
