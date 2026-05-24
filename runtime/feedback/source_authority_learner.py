"""
Source Authority Learner — Beta-Bernoulli posterior over each source's track
record.

The static SOURCE_TIER_MAP in ``runtime/memory/authority.py`` is a *prior*:
NATRIX gets weight 1.0, scanner gets 0.2, the Reddit scraper bucket carries
0.2 too. The map never updates. But empirical reality drifts: some scanners
genuinely call the move 70% of the time; some "council" outputs systematically
underperform when they cite a specific upstream source.

This module attaches a Beta(α, β) posterior to each (source, optional source-
specific subkey) pair. When a prediction grounded in a source resolves, we
``record_outcome(source, correct)`` to update the posterior. The posterior
mean is then exposed as a multiplicative *adjustment factor* on top of the
static tier weight at retrieval / salience time.

Math
----
Per source, prior Beta(α₀, β₀) = Beta(1, 1) (uniform — no evidence). After
observing ``hits`` correct outcomes and ``misses`` wrong outcomes, the
posterior is Beta(1 + hits, 1 + misses), with mean::

    mean = (1 + hits) / (2 + hits + misses)

To keep this multiplicative-and-not-runaway, we map the posterior mean to an
adjustment in ``[0.6, 1.4]``::

    adjustment = 0.6 + 0.8 * mean

So:
    50% accuracy (the prior mean) → 1.00 (no adjustment)
    100% accuracy                  → 1.40 (40% boost)
    0% accuracy                    → 0.60 (40% penalty)

Combined with the static tier weight ``w_t``::

    effective_weight = clamp(w_t * adjustment, 0.05, 1.5)

Persistence
-----------
A flat JSON file at ``$NCL_BASE/data/feedback/source_authority.json`` keyed
by source string. Written atomically (tmp + os.replace). Reads are eager
(loaded on construction). Updates rewrite the whole file — fine because the
state is bounded (a few hundred source strings at most) and writes are rare
(one per resolved prediction).

Outcome wiring
--------------
``record_prediction_outcome(prediction_id, outcome, cited_sources)`` is the
single entry point the predictions outcome endpoint calls. It:
1. Records ±1 on each cited source.
2. Appends a row to ``data/feedback/authority_history.jsonl`` for audit.
3. Returns the new adjustment for each touched source so the caller can log
   it back through the iOS app.
"""

from __future__ import annotations  # noqa: I001

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field  # noqa: F401
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("ncl.feedback.source_authority_learner")


# Stored prompt-injection guard.
#
# ``record_prediction_outcome`` is the single funnel feeding cited-source
# strings into the learner. Those strings are persisted to JSON on disk
# (``source_authority.json``) AND to an append-only JSONL audit log
# (``authority_history.jsonl``). Downstream, the learner's adjustment map
# is consulted at retrieval / salience time, and the audit log is fair game
# for council replay and analyst tooling.
#
# Without validation, a malicious or malformed signal could ship a
# "source" payload containing newlines, quote-breaks, control chars, or
# embedded HTML/template syntax, which would then be replayed verbatim
# into LLM context windows or rendered in audit views. We require source
# ids to look like the well-formed kind we actually emit
# (e.g. "awarebot:reddit", "intelligence:news") and silently drop the rest.
_SAFE_SOURCE_RE = re.compile(r"[a-zA-Z0-9_:./-]{1,200}")


def _is_safe_source(s: str) -> bool:
    """True iff ``s`` is a well-formed source id safe to persist + replay.

    Allowed: ASCII letters, digits, underscore, colon, dot, slash, hyphen.
    Length 1-200. No newlines, control chars, quotes, angle brackets, or
    backslashes — these are the vectors for stored prompt injection into
    downstream LLM context or audit rendering.
    """
    if not isinstance(s, str):
        return False
    if not s or len(s) > 200:
        return False
    # Belt-and-braces: explicitly reject the dangerous chars even though
    # the regex below would also reject them — keeps the intent legible.
    for bad in ('<', '>', '"', "'", '\\'):
        if bad in s:
            return False
    for ch in s:
        if ord(ch) < 0x20:  # control chars incl. \x00, \n, \r, \t
            return False
    return re.fullmatch(_SAFE_SOURCE_RE, s) is not None


# Adjustment range — mean=0.5 → 1.0, mean=1.0 → 1.4, mean=0.0 → 0.6.
ADJUSTMENT_FLOOR = 0.6
ADJUSTMENT_SPAN = 0.8

# Clamp the COMBINED tier*adjustment so a perfect-score scanner still can't
# crowd out a NATRIX directive, and a wrong council can't drop below ~RAW.
EFFECTIVE_FLOOR = 0.05
EFFECTIVE_CEIL = 1.5


def _data_dir() -> Path:
    base = os.environ.get("NCL_BASE") or os.path.expanduser("~/dev/NCL")
    return Path(base) / "data" / "feedback"


@dataclass
class SourceStats:
    hits: int = 0
    misses: int = 0
    partials: int = 0    # half-credit outcomes (count as 0.5 hit)
    last_updated: str = ""

    @property
    def n(self) -> int:
        return self.hits + self.misses + self.partials

    @property
    def posterior_mean(self) -> float:
        # Partials count as half a hit and half a miss.
        h = self.hits + 0.5 * self.partials
        n = self.n
        return (1.0 + h) / (2.0 + n)

    @property
    def adjustment(self) -> float:
        return ADJUSTMENT_FLOOR + ADJUSTMENT_SPAN * self.posterior_mean

    def to_dict(self) -> dict:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "partials": self.partials,
            "last_updated": self.last_updated,
            "n": self.n,
            "posterior_mean": round(self.posterior_mean, 4),
            "adjustment": round(self.adjustment, 4),
        }


class SourceAuthorityLearner:
    """Beta-Bernoulli posterior over source authority — singleton-friendly."""

    # Snapshot cache TTL. Hot-path callers (FusedRetriever scoring 30-60
    # candidates per query, working-context salience rescoring up to 100+
    # items per refresh) hit ``adjustment_for`` repeatedly. The underlying
    # dict lookup is O(1), but materialising the float (incl. property
    # method dispatch + arithmetic) per item adds up. A 60s frozen
    # snapshot is well within the cadence at which posteriors change
    # (one update per resolved prediction, on the order of minutes).
    _SNAPSHOT_TTL_SEC = 60.0

    def __init__(self, state_path: Optional[Path] = None) -> None:
        self._path = state_path or (_data_dir() / "source_authority.json")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._history_path = self._path.parent / "authority_history.jsonl"
        self._lock = asyncio.Lock()
        self._state: dict[str, SourceStats] = {}
        # Frozen adjustment snapshot: {source: float}. Refreshed lazily on
        # ``adjustment_for`` when the TTL has elapsed.
        self._adjustments_snapshot: dict[str, float] = {}
        self._snapshot_ts: float = 0.0
        self._load()
        # Build initial snapshot so the first hot-path call doesn't pay
        # to materialise it.
        self._rebuild_snapshot()

    # ── persistence ────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for src, payload in data.items():
                if not isinstance(payload, dict):
                    continue
                self._state[src] = SourceStats(
                    hits=int(payload.get("hits", 0)),
                    misses=int(payload.get("misses", 0)),
                    partials=int(payload.get("partials", 0)),
                    last_updated=str(payload.get("last_updated", "")),
                )
        except Exception as exc:
            log.warning("[AUTH-LEARNER] load failed: %s", exc)

    def _persist_sync(self) -> None:
        out = {src: s.to_dict() for src, s in self._state.items()}
        tmp = self._path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(out, indent=2), encoding="utf-8")
            # fsync the tmp file before the atomic rename — guarantees the
            # bytes are durably on disk before os.replace flips the pointer.
            # Without this, a crash between write_text and replace can leave
            # us with a zero-byte or torn tmp that the replace then promotes
            # into the live state file.
            with open(tmp, 'rb+') as f:
                os.fsync(f.fileno())
            os.replace(str(tmp), str(self._path))
        except Exception as exc:
            log.error("[AUTH-LEARNER] persist failed: %s", exc)

    def _append_history(self, row: dict) -> None:
        try:
            with self._history_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")
        except Exception as exc:
            log.warning("[AUTH-LEARNER] history append failed: %s", exc)

    # ── public API ─────────────────────────────────────────────────────

    def get(self, source: str) -> SourceStats:
        """Return the stats record for ``source``, creating an empty one if
        unseen. Caller may mutate the returned record only via ``record()``
        below — direct mutation will NOT persist."""
        return self._state.get(source) or SourceStats()

    def all_sources(self) -> dict[str, SourceStats]:
        return dict(self._state)

    def _rebuild_snapshot(self) -> None:
        """Refresh the frozen ``{source: adjustment}`` snapshot from
        ``self._state``. Cheap (a dict comprehension over a few hundred
        entries) and called at most once per ``_SNAPSHOT_TTL_SEC``."""
        self._adjustments_snapshot = {
            src: s.adjustment for src, s in self._state.items()
        }
        self._snapshot_ts = time.monotonic()

    def _maybe_refresh_snapshot(self) -> None:
        if (time.monotonic() - self._snapshot_ts) >= self._SNAPSHOT_TTL_SEC:
            self._rebuild_snapshot()

    def adjustment_for(self, source: str) -> float:
        """Multiplicative adjustment factor for this source. 1.0 if unseen.

        Hot path — reads from a ``_SNAPSHOT_TTL_SEC``-bounded frozen
        snapshot so a 50-item retrieval scan is just 50 dict lookups, not
        50 ``SourceStats.adjustment`` property evaluations.
        """
        self._maybe_refresh_snapshot()
        return self._adjustments_snapshot.get(source, 1.0)

    def effective_weight(self, source: str, static_tier_weight: float) -> float:
        """Combine static tier weight with the learned adjustment.

        Result is clamped to ``[EFFECTIVE_FLOOR, EFFECTIVE_CEIL]``.
        """
        adj = self.adjustment_for(source)
        return max(EFFECTIVE_FLOOR, min(EFFECTIVE_CEIL, static_tier_weight * adj))

    async def record(
        self,
        source: str,
        outcome: str,
        *,
        prediction_id: str = "",
        delta: float = 1.0,
        notes: str = "",
    ) -> SourceStats:
        """Update the posterior for ``source`` with one observation.

        Parameters
        ----------
        source : str
            The source string, exactly as stored on the originating MemUnit.
        outcome : {"correct", "wrong", "partial"}
            Outcome type. ``partial`` counts as half-credit.
        prediction_id : str, optional
            For audit trail.
        delta : float, default 1.0
            Magnitude of the update. ``2.0`` for high-confidence outcomes if
            you want to weight them more heavily (rare; default fine).
        notes : str, optional
            Free-text reason for the update — also written to history.

        Returns
        -------
        SourceStats — the updated record.
        """
        if outcome not in {"correct", "wrong", "partial"}:
            raise ValueError(f"unknown outcome '{outcome}'")
        async with self._lock:
            stats = self._state.get(source) or SourceStats()
            if outcome == "correct":
                stats.hits += max(1, int(round(delta)))
            elif outcome == "wrong":
                stats.misses += max(1, int(round(delta)))
            else:
                stats.partials += max(1, int(round(delta)))
            stats.last_updated = datetime.now(timezone.utc).isoformat()
            self._state[source] = stats
            # Invalidate the frozen snapshot so the new adjustment is
            # visible on the next hot-path read instead of waiting up to
            # _SNAPSHOT_TTL_SEC seconds.
            self._snapshot_ts = 0.0
            self._persist_sync()
            self._append_history(
                {
                    "ts": stats.last_updated,
                    "source": source,
                    "outcome": outcome,
                    "delta": delta,
                    "prediction_id": prediction_id,
                    "notes": notes,
                    "posterior_mean": round(stats.posterior_mean, 4),
                    "adjustment": round(stats.adjustment, 4),
                }
            )
            log.info(
                "[AUTH-LEARNER] %s outcome=%s -> adj=%.3f (h=%d m=%d p=%d)",
                source, outcome, stats.adjustment,
                stats.hits, stats.misses, stats.partials,
            )
            return stats

    async def record_many(self, sources: Iterable[str], outcome: str, *, prediction_id: str = "") -> dict[str, SourceStats]:  # noqa: E501
        """Bulk update — used by the prediction-outcome path."""
        out: dict[str, SourceStats] = {}
        for s in sources:
            if not s:
                continue
            out[s] = await self.record(s, outcome, prediction_id=prediction_id)
        return out


# ───────────────────────────────────────────────────────────────────────
# Process-wide singleton
# ───────────────────────────────────────────────────────────────────────


_LEARNER: Optional[SourceAuthorityLearner] = None


def get_learner() -> SourceAuthorityLearner:
    """Return (lazy-creating) the singleton learner instance."""
    global _LEARNER
    if _LEARNER is None:
        _LEARNER = SourceAuthorityLearner()
    return _LEARNER


# ───────────────────────────────────────────────────────────────────────
# Prediction outcome → ±1 feedback (single entry point)
# ───────────────────────────────────────────────────────────────────────


async def record_prediction_outcome(
    prediction_id: str,
    outcome: str,
    cited_sources: Iterable[str],
) -> dict[str, dict]:
    """Apply a single ±1 outcome to every cited source.

    Called from the predictions outcome endpoint when NATRIX (or an
    auto-scorer) closes out a prediction.

    Returns ``{source: stats_dict}`` for telemetry.
    """
    learner = get_learner()
    if outcome not in {"correct", "wrong", "partial"}:
        raise ValueError(f"unknown outcome '{outcome}'")
    updated: dict[str, dict] = {}
    for src in cited_sources or []:
        if not src:
            continue
        # Stored prompt-injection guard at the funnel: each ``src`` will be
        # written verbatim to source_authority.json AND authority_history.jsonl,
        # then replayed through retrieval/audit. Drop malformed entries rather
        # than raising — feedback path must degrade gracefully.
        if not _is_safe_source(src):
            log.warning("[AUTH-LEARNER] dropped unsafe cited_source: %r", src)
            continue
        stats = await learner.record(src, outcome, prediction_id=prediction_id)
        updated[src] = stats.to_dict()
    log.info(
        "[AUTH-LEARNER] prediction %s outcome=%s -> %d sources updated",
        prediction_id, outcome, len(updated),
    )
    return updated


__all__ = [
    "SourceStats",
    "SourceAuthorityLearner",
    "get_learner",
    "record_prediction_outcome",
]
