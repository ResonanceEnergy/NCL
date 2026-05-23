"""
Per-source Bayesian authority learning for Awarebot.

Replaces (or augments) the hardcoded `base_authority` dict in
`compute_authority` with a Beta-Bernoulli posterior that updates from
prediction outcomes.

Theory
------
Each source has a latent "true accuracy" theta_s in [0, 1] — the probability
that a signal from that source contributes to a correct downstream prediction.
We model theta_s ~ Beta(alpha_s, beta_s).

Conjugacy gives the dead-simple update rule:
    correct outcome  -> alpha += weight
    wrong outcome    -> beta  += weight

Posterior mean = alpha / (alpha + beta).

Priors are seeded from the existing hardcoded `base_authority` dict so the
system starts where it is today and drifts toward learned values as outcomes
accumulate. `prior_strength` controls how many pseudo-observations the prior
counts for — higher = slower learning, lower = faster learning.

Usage
-----
    learner = AuthorityLearner(data_dir=Path("~/dev/NCL/data/awarebot"))
    auth = learner.get_authority("reddit")  # posterior mean, clamped

    # When a prediction made primarily from a reddit signal hits/misses:
    learner.record_outcome("reddit", correct=True)

Persistence
-----------
State is JSON-serialized to `{data_dir}/authority_state.json` on every update
via atomic temp-file + rename. File is tiny (one row per source).
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:  # scipy is preferred for exact Beta intervals
    from scipy.stats import beta as _scipy_beta  # type: ignore

    _HAS_SCIPY = True
except ImportError:  # pragma: no cover - scipy is usually present
    _HAS_SCIPY = False

logger = logging.getLogger(__name__)


# Mirrors the hardcoded base_authority dict in
# runtime/awarebot/agent.py::compute_authority. Keep these in sync.
DEFAULT_PRIOR_MEANS: dict[str, float] = {
    "google_trends": 0.8,
    "polymarket": 0.85,
    "crypto": 0.6,
    "unusual_whales": 0.75,
    "news": 0.7,
    "x": 0.4,
    "youtube": 0.45,
    "reddit": 0.45,
    "council": 0.7,
}

# Clamp to keep any single source from collapsing to 0 or saturating at 1,
# which would otherwise dominate routing decisions and stop learning.
_MIN_AUTHORITY = 0.05
_MAX_AUTHORITY = 0.95

# Fallback default when a source has no prior at all.
_FALLBACK_PRIOR_MEAN = 0.35


@dataclass
class SourceAuthorityState:
    """Per-source Beta(alpha, beta) posterior over true authority."""

    source: str
    alpha: float = 1.0  # successes + 1 (Laplace smoothing)
    beta: float = 1.0  # failures + 1
    n_outcomes: int = 0
    last_updated: Optional[datetime] = None
    prior_mean: float = 0.5
    prior_strength: float = 10.0

    @property
    def mean(self) -> float:
        """Posterior mean = alpha / (alpha + beta)."""
        denom = self.alpha + self.beta
        if denom <= 0:
            return self.prior_mean
        return self.alpha / denom

    @property
    def stddev(self) -> float:
        """Beta distribution standard deviation."""
        a, b = self.alpha, self.beta
        denom = (a + b) ** 2 * (a + b + 1)
        if denom <= 0:
            return 0.0
        return math.sqrt((a * b) / denom)

    @property
    def confidence_interval_95(self) -> tuple[float, float]:
        """95% credible interval. Uses scipy if available, else mean +/- 2*sd."""
        if _HAS_SCIPY:
            try:
                lo, hi = _scipy_beta.interval(0.95, self.alpha, self.beta)
                return (float(lo), float(hi))
            except Exception:  # pragma: no cover - defensive
                pass
        m, s = self.mean, self.stddev
        return (max(0.0, m - 2 * s), min(1.0, m + 2 * s))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.last_updated is not None:
            d["last_updated"] = self.last_updated.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SourceAuthorityState":
        ts = d.get("last_updated")
        last_updated: Optional[datetime] = None
        if isinstance(ts, str):
            try:
                last_updated = datetime.fromisoformat(ts)
            except ValueError:
                last_updated = None
        return cls(
            source=d["source"],
            alpha=float(d.get("alpha", 1.0)),
            beta=float(d.get("beta", 1.0)),
            n_outcomes=int(d.get("n_outcomes", 0)),
            last_updated=last_updated,
            prior_mean=float(d.get("prior_mean", 0.5)),
            prior_strength=float(d.get("prior_strength", 10.0)),
        )


class AuthorityLearner:
    """
    Beta-Bernoulli per-source authority learner.

    Each source's posterior is seeded from a prior mean (matching Awarebot's
    hardcoded `base_authority`) weighted by `prior_strength` pseudo-observations.
    Outcomes update the posterior in-place; state persists to disk on every
    update via atomic write.

    Thread-safe via a single coarse lock — write volume is low (a few per
    prediction-resolution cycle).
    """

    STATE_FILENAME = "authority_state.json"

    def __init__(
        self,
        data_dir: Path,
        prior_means: Optional[dict[str, float]] = None,
        prior_strength: float = 10.0,
    ) -> None:
        self._data_dir = Path(data_dir).expanduser()
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._state_path = self._data_dir / self.STATE_FILENAME

        self._prior_means: dict[str, float] = dict(
            prior_means if prior_means is not None else DEFAULT_PRIOR_MEANS
        )
        self._prior_strength = max(1.0, float(prior_strength))

        self._lock = threading.Lock()
        self._states: dict[str, SourceAuthorityState] = {}

        self._load()
        # Make sure every known source has a state row even before first outcome.
        for src in self._prior_means:
            self._ensure_state(src)

    # ------------------------------------------------------------------ public

    def get_authority(self, source: str) -> float:
        """Posterior mean for `source`, clamped to [0.05, 0.95]."""
        state = self._ensure_state(source)
        return self._clamp(state.mean)

    def record_outcome(
        self, source: str, correct: bool, weight: float = 1.0
    ) -> SourceAuthorityState:
        """
        Update Beta(alpha, beta) with a single outcome.

        correct=True  -> alpha += weight
        correct=False -> beta  += weight

        `weight` defaults to 1.0; pass a fractional weight when attribution is
        shared across multiple sources or when the outcome is partial.
        """
        if weight <= 0:
            raise ValueError(f"weight must be > 0, got {weight}")

        with self._lock:
            state = self._ensure_state_unlocked(source)
            if correct:
                state.alpha += float(weight)
            else:
                state.beta += float(weight)
            state.n_outcomes += 1
            state.last_updated = datetime.now(timezone.utc)
            self._persist_unlocked()
            return state

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """Per-source stats dict: mean, stddev, ci_95, n_outcomes, last_updated."""
        out: dict[str, dict[str, Any]] = {}
        with self._lock:
            for src, st in self._states.items():
                lo, hi = st.confidence_interval_95
                out[src] = {
                    "source": src,
                    "mean": round(st.mean, 4),
                    "clamped_mean": round(self._clamp(st.mean), 4),
                    "stddev": round(st.stddev, 4),
                    "ci_95_low": round(lo, 4),
                    "ci_95_high": round(hi, 4),
                    "n_outcomes": st.n_outcomes,
                    "alpha": round(st.alpha, 3),
                    "beta": round(st.beta, 3),
                    "prior_mean": round(st.prior_mean, 4),
                    "prior_strength": st.prior_strength,
                    "last_updated": (
                        st.last_updated.isoformat() if st.last_updated else None
                    ),
                }
        return out

    def export_for_api(self) -> list[dict[str, Any]]:
        """
        Sortable list for iOS display, ordered by posterior mean descending.

        Shape per item: source, authority (clamped mean), stddev, ci_low,
        ci_high, n_outcomes, last_updated, trend ("up"/"down"/"flat" vs prior).
        """
        items: list[dict[str, Any]] = []
        for src, stats in self.get_all_stats().items():
            mean = stats["mean"]
            prior = stats["prior_mean"]
            if mean > prior + 0.02:
                trend = "up"
            elif mean < prior - 0.02:
                trend = "down"
            else:
                trend = "flat"
            items.append(
                {
                    "source": src,
                    "authority": stats["clamped_mean"],
                    "raw_mean": stats["mean"],
                    "stddev": stats["stddev"],
                    "ci_low": stats["ci_95_low"],
                    "ci_high": stats["ci_95_high"],
                    "n_outcomes": stats["n_outcomes"],
                    "prior_mean": prior,
                    "trend": trend,
                    "last_updated": stats["last_updated"],
                }
            )
        items.sort(key=lambda x: x["authority"], reverse=True)
        return items

    # ----------------------------------------------------------------- private

    def _clamp(self, x: float) -> float:
        return max(_MIN_AUTHORITY, min(_MAX_AUTHORITY, float(x)))

    def _ensure_state(self, source: str) -> SourceAuthorityState:
        with self._lock:
            return self._ensure_state_unlocked(source)

    def _ensure_state_unlocked(self, source: str) -> SourceAuthorityState:
        st = self._states.get(source)
        if st is not None:
            return st
        prior_mean = self._prior_means.get(source, _FALLBACK_PRIOR_MEAN)
        # Translate prior_mean + prior_strength into Beta(alpha0, beta0):
        #   alpha0 = prior_mean * prior_strength
        #   beta0  = (1 - prior_mean) * prior_strength
        alpha0 = max(1e-3, prior_mean * self._prior_strength)
        beta0 = max(1e-3, (1.0 - prior_mean) * self._prior_strength)
        st = SourceAuthorityState(
            source=source,
            alpha=alpha0,
            beta=beta0,
            n_outcomes=0,
            last_updated=None,
            prior_mean=prior_mean,
            prior_strength=self._prior_strength,
        )
        self._states[source] = st
        # Note: not persisted here — only persist on real outcome updates to
        # avoid touching disk every time get_authority() is called for a
        # never-seen source.
        return st

    def _load(self) -> None:
        if not self._state_path.exists():
            return
        try:
            with self._state_path.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(
                "AuthorityLearner: failed to load %s (%s) — starting fresh",
                self._state_path,
                e,
            )
            return
        sources = raw.get("sources", {}) if isinstance(raw, dict) else {}
        for src, d in sources.items():
            try:
                self._states[src] = SourceAuthorityState.from_dict(d)
            except (KeyError, ValueError, TypeError) as e:
                logger.warning(
                    "AuthorityLearner: skipping corrupt entry for %s: %s", src, e
                )

    def _persist_unlocked(self) -> None:
        payload = {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "prior_strength": self._prior_strength,
            "sources": {src: st.to_dict() for src, st in self._states.items()},
        }
        # Atomic write: tmp file in same directory, then os.replace.
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=".authority_state.", suffix=".tmp", dir=str(self._data_dir)
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
            os.replace(tmp_path, self._state_path)
        except Exception:
            # Best-effort cleanup; re-raise so callers see the failure.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


__all__ = [
    "AuthorityLearner",
    "SourceAuthorityState",
    "DEFAULT_PRIOR_MEANS",
]
