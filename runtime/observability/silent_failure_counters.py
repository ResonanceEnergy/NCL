"""Wave 14CS (2026-05-31) — Silent-failure counters.

Audit B4.7 finding: a half-dozen subsystems catch their own exceptions
and `log.debug` (or worse, swallow silently). Examples:

  - EntityClusterer.ingest() exception → cross_source=0.0 fallback
  - AuthorityLearner blend failure → log.debug only
  - compute_situational_relevance import failure → silent pass
  - BERTopic load failure → log.debug
  - _PROMO_MARKERS keyword cap → no telemetry on which marker fires
  - _persist_dedup_cache drop → no counter

When these fail at scale we have no idea. This module is a tiny
process-wide counter store + a `/system/silent-failures` endpoint so
the operator can see what's failing without rebooting at log level.

Usage:
  from runtime.observability.silent_failure_counters import bump
  try:
      ...
  except Exception as e:
      bump("entity_cluster_failed", reason=type(e).__name__)

  # Snapshot:
  from runtime.observability.silent_failure_counters import snapshot
  snapshot()  # → {"counters": {...}, "by_reason": {...}, "since": iso}
"""
from __future__ import annotations

import threading
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Optional


_LOCK = threading.Lock()
_COUNTERS: Counter[str] = Counter()
_BY_REASON: dict[str, Counter[str]] = defaultdict(Counter)
_FIRST_BUMP_AT: dict[str, str] = {}
_LAST_BUMP_AT: dict[str, str] = {}
_STARTED_AT = datetime.now(timezone.utc).isoformat()


def bump(name: str, *, reason: Optional[str] = None, n: int = 1) -> None:
    """Bump counter `name` by `n`. Optional `reason` tracks sub-counts."""
    if not name:
        return
    now = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        _COUNTERS[name] += n
        if reason:
            _BY_REASON[name][reason] += n
        if name not in _FIRST_BUMP_AT:
            _FIRST_BUMP_AT[name] = now
        _LAST_BUMP_AT[name] = now


def snapshot() -> dict:
    """Return current counter state. Cheap to call."""
    with _LOCK:
        return {
            "started_at": _STARTED_AT,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "n_distinct_counters": len(_COUNTERS),
            "counters": dict(_COUNTERS),
            "by_reason": {
                k: dict(v.most_common(10)) for k, v in _BY_REASON.items()
            },
            "first_bump_at": dict(_FIRST_BUMP_AT),
            "last_bump_at": dict(_LAST_BUMP_AT),
        }


def reset() -> None:
    """Clear all counters. Useful for tests / operator nuking."""
    global _STARTED_AT
    with _LOCK:
        _COUNTERS.clear()
        _BY_REASON.clear()
        _FIRST_BUMP_AT.clear()
        _LAST_BUMP_AT.clear()
        _STARTED_AT = datetime.now(timezone.utc).isoformat()


__all__ = ["bump", "snapshot", "reset"]
