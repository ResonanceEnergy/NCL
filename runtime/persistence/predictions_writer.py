"""
predictions_writer.py — live JSON→SQLite mirror for new predictions.

W10A-14 (2026-05-24): Wave 9 #3 follow-up. The bulk migration in
``scripts/migrate_predictions_to_sqlite.py`` populated the
``predictions`` SQLite table once (784 rows). New predictions land as
``data/predictions/pred-*.json`` (and ``council/council-pred-*.json``)
but were NOT being written to SQLite — the table froze at 784 while
the JSON dir grew by ~88 files in a day.

W10B-1 (2026-05-24): collapsed onto the shared ``DoubleWriteHook``
abstraction. The public API (``mirror_prediction_to_sqlite`` /
``mirror_outcome_to_sqlite``) is preserved so the 3 existing callers
(awarebot.agent, api.routers.intel, this module's tests) don't change.
``NCL_PREDICTIONS_SQLITE`` is still the gating env flag — now read by
the hook at call time, so launchd .env edits take effect on the next
prediction without a restart.

Row shape still mirrors ``scripts/migrate_predictions_to_sqlite.py``
exactly, so a migrated row and a live-double-written row are
bit-identical (handy when reconciling counts during burn-in).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from .double_write import DoubleWriteHook

log = logging.getLogger("ncl.persistence.predictions_writer")

# Feature flag — kept as a module-level constant for back-compat with
# diagnostics that introspect this module. The hot path consults the
# hook (which reads the env var fresh on every call).
ENV_VAR = "NCL_PREDICTIONS_SQLITE"


def _enabled() -> bool:
    """Back-compat shim for any direct callers.

    The hook does its own per-call env read; this remains so tests and
    diagnostic code can still call ``predictions_writer._enabled()``.
    """
    return os.getenv(ENV_VAR, "false").lower() == "true"


# ── Coercion helpers (parallel to the migration script) ──────────────


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_json_array(value: Any) -> Optional[str]:
    """Coerce a list-like value into a compact JSON array string."""
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("[") and s.endswith("]"):
            return s
        return json.dumps([s], separators=(",", ":"))
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value), separators=(",", ":"))
    return json.dumps([value], separators=(",", ":"))


def _coerce_str(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _entry_to_row(entry: dict, *, fallback_id: Optional[str] = None) -> Optional[tuple]:
    """Map a parsed prediction-shaped dict to the predictions column tuple.

    Returns None when the dict doesn't look like a prediction (no id /
    no fallback_id) — DoubleWriteHook will skip the row.
    """
    if not isinstance(entry, dict):
        return None

    pid = entry.get("prediction_id") or entry.get("id") or fallback_id
    pid = _coerce_str(pid)
    if not pid:
        return None

    created_at = (
        _coerce_str(entry.get("timestamp"))
        or _coerce_str(entry.get("generated_at"))
        or _coerce_str(entry.get("created_at"))
        or datetime.now(timezone.utc).isoformat()
    )

    description = (
        _coerce_str(entry.get("description"))
        or _coerce_str(entry.get("consensus"))
        or _coerce_str(entry.get("content"))
    )

    direction = _coerce_str(entry.get("direction"))
    topic = entry.get("topic") if isinstance(entry.get("topic"), str) else None

    cited = entry.get("cited_sources") or entry.get("cited_sources_full")
    linked = entry.get("linked_signals")

    return (
        pid,
        created_at,
        topic,
        direction,
        _as_float(entry.get("probability")),
        _as_float(entry.get("confidence")),
        description,
        _as_json_array(cited),
        _as_json_array(linked),
        _coerce_str(entry.get("outcome")),
        _coerce_str(entry.get("outcome_recorded_at")),
    )


# ── Shared DoubleWriteHook (module-level singleton) ──────────────────
#
# Each caller used to import this module + call mirror_prediction_to_sqlite.
# Underneath, all of them now share one DoubleWriteHook instance — so
# the warn-once flag remains module-scoped (matches pre-W10B-1
# behaviour: an outage warns ONCE per process across all producers, not
# once per producer).

_HOOK: DoubleWriteHook[dict] = DoubleWriteHook(
    env_flag=ENV_VAR,
    table="predictions",
    columns=(
        "id", "created_at", "topic", "direction", "probability",
        "confidence", "description", "cited_sources_json",
        "linked_signals_json", "outcome", "outcome_recorded_at",
    ),
    # build_row is set per-call below (needs the fallback_id closure).
    # The hook accepts None to mean "skip" so the default sentinel
    # builder here just refuses everything; the public API overrides
    # via execute_custom / direct row construction.
    build_row=lambda _entity: None,
    conflict_strategy="replace",
    log_prefix="[PREDICTIONS_SQLITE]",
)

# Outcome-only UPDATE — keeps the rest of the row untouched. The
# migrator never sets outcome so this is the live path for resolution.
_UPDATE_OUTCOME_SQL = (
    "UPDATE predictions SET outcome = ?, outcome_recorded_at = ? WHERE id = ?"
)


# ── Public API ────────────────────────────────────────────────────────


async def mirror_prediction_to_sqlite(
    entry: dict,
    *,
    fallback_id: Optional[str] = None,
) -> bool:
    """Mirror a freshly-written prediction JSON into the SQLite table.

    Args:
        entry: Parsed prediction body (same shape as on-disk
            ``pred-*.json`` / ``council-pred-*.json``).
        fallback_id: Used as the row id when ``entry`` carries no
            ``prediction_id`` / ``id`` (e.g. the file stem).

    Returns:
        True on a successful write. False on a no-op (flag off, bad
        row, backend error). NEVER raises.
    """
    if not _HOOK.enabled():
        return False
    row = _entry_to_row(entry, fallback_id=fallback_id)
    if row is None:
        return False

    # Bypass the hook's build_row indirection (which has the closure
    # problem) and call execute_custom with the compiled INSERT SQL.
    # We use the hook for: env-flag check (above), store acquisition +
    # retry, warn-once, and uniform logging.
    rowcount = await _HOOK.execute_custom(_HOOK.sql, row)
    return rowcount is not None and rowcount != 0


async def mirror_outcome_to_sqlite(
    prediction_id: str,
    outcome: str,
    *,
    recorded_at: Optional[str] = None,
) -> bool:
    """Stamp an outcome onto an existing SQLite predictions row.

    Args:
        prediction_id: Row PK — must match the JSON's prediction_id.
        outcome: ``correct`` / ``incorrect`` / ``partial`` (string the
            outcome endpoint already settled on).
        recorded_at: ISO timestamp; defaults to now-UTC.

    Returns:
        True if the row existed and was updated. False on no-op.
        NEVER raises.
    """
    pid = _coerce_str(prediction_id)
    if not pid:
        return False

    out = _coerce_str(outcome)
    if not out:
        return False

    ts = _coerce_str(recorded_at) or datetime.now(timezone.utc).isoformat()

    rowcount = await _HOOK.execute_custom(_UPDATE_OUTCOME_SQL, (out, ts, pid))
    if rowcount is None:
        return False
    # Some drivers report -1 when rowcount is unsupported. Treat any
    # non-negative non-zero as success; for safety we also accept the
    # 0-rowcount path (driver quirk) as a no-op.
    return rowcount > 0 or rowcount == -1
