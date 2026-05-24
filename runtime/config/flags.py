"""Central feature flag accessors for NCL (W10B-2, 2026-05-24).

Wave 9 D2 collapsed 30+ duplicated ``os.getenv("NCL_..._SQLITE", "false")
.lower() == "true"`` predicates spread across 11 runtime files into the
five accessors below. Each accessor reads ``os.environ`` on every call
(no caching) so launchd ``.env`` edits take effect on the next call
without a Brain restart — this matches the behaviour of every site we
collapsed and of DoubleWriteHook (which W10B-1 already centralized for
write paths).

Why not ``functools.lru_cache``?
    Earlier drafts of this module cached results. That breaks the
    operator workflow we already rely on elsewhere: edit ``.env``,
    ``launchctl kickstart`` only the affected service, see the flag flip
    on the next request. A process-lifetime cache would silently keep
    the old value until full restart and re-introduce exactly the kind
    of "is this actually on?" confusion W10B-2 was supposed to kill.

Supported truthy literals are the same superset every existing site
already accepted (``ab_test.is_ab_enabled`` was the loosest of the
bunch): ``{"1", "true", "yes", "on"}`` — case-insensitive, trimmed.

DoubleWriteHook ownership
-------------------------
DoubleWriteHook (``runtime/persistence/double_write.py``) owns the
write-path env-flag check for the units_index / mandates / cost_ledger /
predictions tables. Those sites pass an ``env_flag=`` string to the hook
and DO NOT have an inline predicate to collapse. The accessors here are
for the remaining READ-path / status / branching sites that the hook
doesn't subsume.
"""

from __future__ import annotations

import os


# Literal set accepted as "on". Mirrors ``ab_test.is_ab_enabled`` which
# was the most permissive of the call sites we collapsed; the SQLite
# sites used the stricter ``== "true"`` check, but widening them to the
# same superset is strictly safe — "1"/"yes"/"on" already evaluated to
# False on the old strict comparison and there are no operators relying
# on that specific quirk.
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _read_bool(name: str, default: str = "false") -> bool:
    """Read an env var as bool. Reads fresh on every call — no cache."""
    return os.environ.get(name, default).strip().lower() in _TRUTHY


# ── SQLite double-write / read-path gates ──────────────────────────────
# All four mirror the pattern set by W4-14 (units_index) and extended
# through W10A-14 (predictions): JSONL stays the source of truth,
# SQLite is a double-write target behind a flag. Read paths consult
# SQLite first when the flag is ON and fall back to the JSONL scan on
# any miss or error.


def units_index_sqlite() -> bool:
    """``NCL_UNITS_INDEX_SQLITE`` — W4-14 units_index table gate."""
    return _read_bool("NCL_UNITS_INDEX_SQLITE")


def mandates_sqlite() -> bool:
    """``NCL_MANDATES_SQLITE`` — mandates table double-write gate."""
    return _read_bool("NCL_MANDATES_SQLITE")


def cost_ledger_sqlite() -> bool:
    """``NCL_COST_LEDGER_SQLITE`` — cost_ledger table double-write gate."""
    return _read_bool("NCL_COST_LEDGER_SQLITE")


def predictions_sqlite() -> bool:
    """``NCL_PREDICTIONS_SQLITE`` — W10A-14 predictions mirror gate."""
    return _read_bool("NCL_PREDICTIONS_SQLITE")


# ── Memory subsystem A/B ───────────────────────────────────────────────


def ab_haiku_enabled() -> bool:
    """``NCL_AB_HAIKU`` — Haiku shadow-scoring A/B harness gate."""
    return _read_bool("NCL_AB_HAIKU")


__all__ = [
    "units_index_sqlite",
    "mandates_sqlite",
    "cost_ledger_sqlite",
    "predictions_sqlite",
    "ab_haiku_enabled",
]
