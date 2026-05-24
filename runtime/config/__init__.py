"""Central runtime configuration package.

Currently exposes the W10B-2 feature flag accessors. See ``flags.py`` for
the full rationale; the short version is that 30+ inline
``os.getenv(...).lower() == "true"`` predicates were collapsed into one
module so flag names live in exactly one place and so we don't drift
truthy-literal parsing between sites.
"""

from .flags import (
    ab_haiku_enabled,
    cost_ledger_sqlite,
    mandates_sqlite,
    predictions_sqlite,
    units_index_sqlite,
)


__all__ = [
    "ab_haiku_enabled",
    "cost_ledger_sqlite",
    "mandates_sqlite",
    "predictions_sqlite",
    "units_index_sqlite",
]
