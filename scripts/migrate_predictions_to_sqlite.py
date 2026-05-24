#!/usr/bin/env python3
"""
migrate_predictions_to_sqlite.py — one-shot, idempotent JSON→SQLite move.

What it does:
    * Reads data/predictions/pred-*.json AND data/predictions/council/
      council-pred-*.json (the two on-disk prediction shapes).
    * Inserts each prediction into the SQLite ``predictions`` table.
    * Idempotent via INSERT OR REPLACE on the PRIMARY KEY (id) — re-running
      the migration after new prediction files are written is a no-op for
      already-imported predictions and picks up the new ones.
    * Does NOT delete the source JSON files — we keep them on disk for the
      burn-in period so the existing GET /predictions code path still works
      while the SQL-backed reader is being shaken out.
    * Tolerates malformed entries (counts as errors, continues).
    * Verifies row count with SELECT COUNT(*) at the end.
    * Reports rows scanned / inserted / replaced / errors / final row count.

Run:
    python3 scripts/migrate_predictions_to_sqlite.py
    python3 scripts/migrate_predictions_to_sqlite.py --dry-run
    python3 scripts/migrate_predictions_to_sqlite.py --source data/predictions
    python3 scripts/migrate_predictions_to_sqlite.py --batch-size 1000 --verbose

Idempotency:
    The table's PRIMARY KEY is ``id`` (derived from the file stem when the
    JSON body doesn't carry one). INSERT OR REPLACE makes the migration
    safe to re-run any number of times — already-imported predictions are
    silently overwritten with the latest disk content (handy if a prediction
    was patched in place).

NATRIX activation procedure (after running this script):
    1. python3 scripts/migrate_predictions_to_sqlite.py
    2. echo NCL_PREDICTIONS_SQLITE=true >> .env   # (when the SQL-backed reader lands)
    3. launchctl kickstart -k gui/$(id -u)/com.resonanceenergy.ncl-brain
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

# Allow `python3 scripts/migrate_predictions_to_sqlite.py` from the repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.persistence import get_store  # noqa: E402

log = logging.getLogger("ncl.migrate.predictions")

DEFAULT_SOURCE = REPO_ROOT / "data" / "predictions"


INSERT_SQL = """
INSERT OR REPLACE INTO predictions
    (id, created_at, topic, direction, probability, confidence,
     description, cited_sources_json, linked_signals_json,
     outcome, outcome_recorded_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

COUNT_SQL = "SELECT COUNT(*) AS n FROM predictions"


# ── Helpers (mirror runtime/api/routers/intel.py post-processing) ─────

_JSON_BLOCK_RE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)


def _extract_description(entry: dict) -> Optional[str]:
    """
    Pull a human-readable prediction string out of the raw entry.

    Order of preference:
      1. Explicit ``description`` field (council-pred-*.json shape).
      2. ``prediction`` key inside a ```json``` fenced block of ``consensus``.
      3. The ``consensus`` string with the ```json``` block stripped.
      4. Fall through to ``consensus`` raw.
    """
    desc = entry.get("description")
    if isinstance(desc, str) and desc.strip():
        return desc.strip()

    consensus = entry.get("consensus")
    if not isinstance(consensus, str) or not consensus.strip():
        return None

    m = _JSON_BLOCK_RE.search(consensus)
    if m:
        try:
            body = json.loads(m.group(1))
            pred = body.get("prediction") if isinstance(body, dict) else None
            if isinstance(pred, str) and pred.strip():
                return pred.strip()
        except json.JSONDecodeError:
            pass

    # Fall back to the consensus with the JSON block removed.
    stripped = _JSON_BLOCK_RE.sub("", consensus).strip()
    return stripped or consensus.strip()


_DIRECTION_BULLISH = re.compile(
    r"\b(bull(?:ish)?|rally|surge|moon|breakout|uptrend|climb|rise|gain|spike up|outperform)\b",
    re.IGNORECASE,
)
_DIRECTION_BEARISH = re.compile(
    r"\b(bear(?:ish)?|crash|plunge|drop|downtrend|decline|fall|sell-off|tank|underperform)\b",
    re.IGNORECASE,
)


def _classify_direction(text: str) -> Optional[str]:
    """Lightweight regex classifier — mirrors runtime/api/routers/intel.py."""
    if not text:
        return None
    bull = bool(_DIRECTION_BULLISH.search(text))
    bear = bool(_DIRECTION_BEARISH.search(text))
    if bull and not bear:
        return "bullish"
    if bear and not bull:
        return "bearish"
    if bull and bear:
        return "mixed"
    return "neutral"


_STEM_TS_RE = re.compile(r"(?:council-)?pred-(\d{8})-(\d{6})")


def _derive_id(path: Path, entry: dict) -> str:
    """
    Resolve the row id.

    Preference order:
      1. ``prediction_id`` or ``id`` field on the JSON body.
      2. The file stem (``pred-YYYYMMDD-HHMMSS`` /
         ``council-pred-YYYYMMDD-HHMMSS``).
    """
    raw = entry.get("prediction_id") or entry.get("id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return path.stem


def _derive_created_at(path: Path, entry: dict) -> str:
    """
    Resolve the created-at ISO timestamp.

    Preference order:
      1. ``timestamp`` / ``generated_at`` / ``created_at`` on the body.
      2. Parse the YYYYMMDD-HHMMSS embedded in the file stem.
      3. File mtime as a last resort.
    """
    for key in ("timestamp", "generated_at", "created_at"):
        v = entry.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()

    m = _STEM_TS_RE.search(path.stem)
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)}{m.group(2)}", "%Y%m%d%H%M%S")
            return dt.replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass

    try:
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except OSError:
        return datetime.now(timezone.utc).isoformat()


def _as_json_array(value: Any) -> Optional[str]:
    """Coerce a list-like value into a compact JSON array string."""
    if value is None:
        return None
    if isinstance(value, str):
        # Already-serialised arrays come through as-is; wrap bare strings.
        s = value.strip()
        if s.startswith("[") and s.endswith("]"):
            return s
        return json.dumps([s], separators=(",", ":"))
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value), separators=(",", ":"))
    # Defensive: dump anything else as a single-element array.
    return json.dumps([value], separators=(",", ":"))


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def iter_prediction_files(source: Path) -> Iterable[Path]:
    """
    Yield every prediction-shaped file under ``source``.

    Looks for ``pred-*.json`` at the top level (the ensemble predictor's
    output) and ``council/council-pred-*.json`` in the council subdir.
    Honors the source being either the predictions directory or a
    specific file.
    """
    if source.is_file():
        yield source
        return
    if not source.is_dir():
        return
    for p in sorted(source.glob("pred-*.json")):
        if p.is_file():
            yield p
    council_dir = source / "council"
    if council_dir.is_dir():
        for p in sorted(council_dir.glob("council-pred-*.json")):
            if p.is_file():
                yield p


def entry_to_row(path: Path, entry: dict) -> Optional[tuple]:
    """
    Map one parsed JSON entry to the predictions column tuple.

    Returns None for entries that don't look like a prediction (e.g. a
    bare list wrapper — see council aggregator files). The caller bumps
    the error counter for those.
    """
    if not isinstance(entry, dict):
        return None

    description = _extract_description(entry)
    direction = entry.get("direction")
    if not isinstance(direction, str) or not direction.strip():
        direction = _classify_direction(description or entry.get("consensus") or "")

    return (
        _derive_id(path, entry),
        _derive_created_at(path, entry),
        entry.get("topic") if isinstance(entry.get("topic"), str) else None,
        direction,
        _as_float(entry.get("probability")),
        _as_float(entry.get("confidence")),
        description,
        _as_json_array(entry.get("cited_sources") or entry.get("cited_sources_full")),
        _as_json_array(entry.get("linked_signals")),
        entry.get("outcome") if isinstance(entry.get("outcome"), str) else None,
        entry.get("outcome_recorded_at") if isinstance(entry.get("outcome_recorded_at"), str) else None,
    )


def iter_entries(path: Path) -> Iterable[dict]:
    """
    Read one prediction file and yield each prediction-like dict.

    Some files (council aggregator) wrap predictions in a list or under
    a ``predictions`` key — handle both shapes.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return

    if isinstance(data, dict) and "predictions" in data and isinstance(data["predictions"], list):
        for item in data["predictions"]:
            if isinstance(item, dict):
                yield item
        return
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                yield item
        return
    if isinstance(data, dict):
        yield data


async def migrate(source: Path, *, dry_run: bool = False, batch_size: int = 500) -> dict:
    store = await get_store()
    await store.apply_migrations()

    scanned = 0
    inserted = 0
    errors = 0

    files = list(iter_prediction_files(source))
    if not files:
        log.warning("No prediction JSON files found under %s", source)
        return {"scanned": 0, "inserted": 0, "errors": 0, "files": [], "final_count": 0}

    log.info("Scanning %d file(s) for predictions migration", len(files))

    batch: list[tuple] = []
    for path in files:
        for entry in iter_entries(path):
            scanned += 1
            row = entry_to_row(path, entry)
            if row is None:
                errors += 1
                continue
            batch.append(row)
            if len(batch) >= batch_size:
                if dry_run:
                    inserted += len(batch)
                else:
                    inserted += await _flush(store, batch)
                batch.clear()
        if scanned and scanned % 200 == 0:
            log.info("…progress: scanned=%d inserted=%d errors=%d", scanned, inserted, errors)

    if batch:
        if dry_run:
            inserted += len(batch)
        else:
            inserted += await _flush(store, batch)

    # Final row count (post-write) — verifies the table is populated.
    final_count = 0
    if not dry_run:
        async with store.acquire("read") as conn:
            cur = conn.execute(COUNT_SQL)
            row = cur.fetchone()
            final_count = int(row[0]) if row else 0

    result = {
        "scanned": scanned,
        "inserted": inserted,
        "errors": errors,
        "file_count": len(files),
        "final_count": final_count,
        "dry_run": dry_run,
        "db_path": str(store.db_path),
    }
    log.info(
        "DONE: files=%d scanned=%d inserted=%d errors=%d final_count=%d (db=%s)",
        len(files), scanned, inserted, errors, final_count, store.db_path,
    )
    return result


async def _flush(store, batch: list[tuple]) -> int:
    """
    Execute the batch insert. Returns the # of rows written (INSERT OR
    REPLACE always counts every row, even when the id already exists).
    """
    async with store.acquire("write") as conn:
        before = conn.total_changes
        try:
            conn.execute("BEGIN")
            conn.executemany(INSERT_SQL, batch)
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        after = conn.total_changes
        return after - before


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="Path to the predictions directory (or a single pred-*.json file)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan + parse but don't write to SQLite",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Rows per INSERT batch (default 500)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.source.exists():
        print(f"ERROR: source path does not exist: {args.source}", file=sys.stderr)
        return 2

    result = asyncio.run(migrate(args.source, dry_run=args.dry_run, batch_size=args.batch_size))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
