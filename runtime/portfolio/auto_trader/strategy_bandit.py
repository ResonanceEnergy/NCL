"""
Auto-Trader strategy bandit — Wave 14K Phase 4 (K3a)

Beta-Bernoulli per-strategy posteriors + Thompson sampling for arm
selection. Each strategy gets a Beta(α, β) posterior over its true
win rate; updated on every closed paper trade.

Why Beta-Bernoulli (research from P27-A):
  - Closed trade = Bernoulli outcome (win/loss)
  - Beta is the conjugate prior; posterior update is one addition
  - Cheap, correct, and converges to true rate in probability/MS/distribution
  - NCL already uses Beta-Bernoulli for source authority — same machinery
    promoted one level up to strategy success rate

Why Thompson sampling (research from P27-A):
  - When N strategies compete for capital under uncertain win rates,
    sampling from posteriors beats arg-max
  - Poly-log regret bounds; keeps exploring under-performing strategies
    until data definitively rules them out
  - Direct application: when brief emits 6 ideas + heat budget allows 3,
    sample which to take rather than always picking from historically-best

Storage:
  - data/portfolio/auto_trader/bandit_state.json (current posteriors)
  - data/portfolio/auto_trader/bandit_history.jsonl (every update appended)

API:
  - get_bandit() — singleton accessor
  - bandit.record_result(strategy, win: bool, R_multiple: float, idea_id)
  - bandit.posterior(strategy) -> {alpha, beta, mean, ci_low, ci_high, n}
  - bandit.sample_arm(candidates) -> str (Thompson sample)
  - bandit.all_posteriors() -> {strategy: posterior_dict}
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.strategy_bandit")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio" / "auto_trader"
STATE_FILE = DATA_DIR / "bandit_state.json"
HISTORY_FILE = DATA_DIR / "bandit_history.jsonl"

# Prior: Beta(1, 1) = uniform — every new strategy starts assumed equally
# likely to have any win rate in [0, 1]. Tunable via env if operator wants
# stronger / weaker priors (e.g. Beta(5, 5) for "I believe strategies tend
# to be near 50% until proven otherwise").
PRIOR_ALPHA = float(os.getenv("NCL_BANDIT_PRIOR_ALPHA", "1.0"))
PRIOR_BETA = float(os.getenv("NCL_BANDIT_PRIOR_BETA", "1.0"))


@dataclass
class StrategyPosterior:
    """Beta(α, β) posterior over a strategy's true win rate."""
    strategy: str
    alpha: float = PRIOR_ALPHA       # successes + prior_α
    beta: float = PRIOR_BETA         # failures + prior_β
    n_observed: int = 0              # total closed trades observed
    n_wins: int = 0
    n_losses: int = 0
    sum_R_multiple: float = 0.0      # sum of R-multiples (signed)
    last_update_iso: Optional[str] = None

    @property
    def mean(self) -> float:
        """Posterior mean of true win rate."""
        s = self.alpha + self.beta
        return self.alpha / s if s > 0 else 0.0

    def credible_interval(self, ci: float = 0.95) -> tuple[float, float]:
        """Beta(α, β) credible interval. Uses scipy when available; falls
        back to a normal approximation otherwise (still gives a sensible
        answer for α + β >= 10)."""
        try:
            from scipy.stats import beta as _beta
            return tuple(_beta.interval(ci, self.alpha, self.beta))
        except ImportError:
            import math
            # Normal approx: mean ± z * sqrt(α*β / ((α+β)^2 * (α+β+1)))
            a, b = self.alpha, self.beta
            mean = a / (a + b)
            var = (a * b) / (((a + b) ** 2) * (a + b + 1))
            std = math.sqrt(var)
            # 95% z = 1.96; tighten/loosen by ci
            z = 1.96 if ci >= 0.95 else 1.64 if ci >= 0.90 else 1.0
            return max(0.0, mean - z * std), min(1.0, mean + z * std)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


class StrategyBandit:
    """Beta-Bernoulli per-strategy bandit with Thompson sampling."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._posteriors: dict[str, StrategyPosterior] = {}
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            _ensure_dir()
            await self._load()
            self._initialized = True
            log.info(
                "[BANDIT] initialized — %d strategies with posteriors",
                len(self._posteriors),
            )

    async def _load(self) -> None:
        if not STATE_FILE.exists():
            return
        try:
            raw = json.loads(STATE_FILE.read_text())
            if not isinstance(raw, dict):
                return
            field_names = {f for f in StrategyPosterior.__dataclass_fields__}  # type: ignore[attr-defined]
            for strategy, payload in raw.items():
                if not isinstance(payload, dict):
                    continue
                kept = {k: v for k, v in payload.items() if k in field_names}
                kept.setdefault("strategy", strategy)
                try:
                    self._posteriors[strategy] = StrategyPosterior(**kept)
                except Exception as e:
                    log.warning("[BANDIT] skip malformed %s: %s", strategy, e)
        except Exception as e:
            log.warning("[BANDIT] load failed: %s", e)

    async def _persist(self) -> None:
        snap = {k: asdict(p) for k, p in self._posteriors.items()}
        tmp = STATE_FILE.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(snap, indent=2, sort_keys=True))
            tmp.replace(STATE_FILE)
        except Exception as e:
            log.error("[BANDIT] persist failed: %s", e)

    def _append_history(self, action: str, posterior: StrategyPosterior,
                         extra: Optional[dict] = None) -> None:
        row = {"ts": _now_iso(), "action": action,
               "posterior": asdict(posterior), "extra": extra or {}}
        try:
            with open(HISTORY_FILE, "a") as f:
                f.write(json.dumps(row) + "\n")
        except Exception as e:
            log.warning("[BANDIT] history append failed: %s", e)

    # ── Public API ───────────────────────────────────────────────

    async def record_result(
        self,
        strategy: str,
        *,
        win: bool,
        R_multiple: float = 0.0,
        trade_idea_id: Optional[str] = None,
    ) -> dict:
        """Update the strategy's posterior with one closed-trade outcome.

        win: True if R_multiple > 0; False otherwise. Scratches (R == 0)
             count as losses for posterior purposes — conservative.
        R_multiple: signed R units realized.
        trade_idea_id: optional, for traceability.
        """
        await self.initialize()
        async with self._lock:
            p = self._posteriors.get(strategy)
            if p is None:
                p = StrategyPosterior(strategy=strategy)
                self._posteriors[strategy] = p
            if win:
                p.alpha += 1
                p.n_wins += 1
            else:
                p.beta += 1
                p.n_losses += 1
            p.n_observed += 1
            p.sum_R_multiple += float(R_multiple)
            p.last_update_iso = _now_iso()
            await self._persist()
            self._append_history(
                "win" if win else "loss",
                p,
                extra={"R_multiple": R_multiple, "trade_idea_id": trade_idea_id},
            )
            log.info(
                "[BANDIT] %s: %s → α=%.0f β=%.0f mean=%.4f (n=%d, ΣR=%.2f)",
                strategy, "WIN" if win else "LOSS",
                p.alpha, p.beta, p.mean, p.n_observed, p.sum_R_multiple,
            )
            return asdict(p)

    async def posterior(self, strategy: str) -> Optional[dict]:
        await self.initialize()
        async with self._lock:
            p = self._posteriors.get(strategy)
            if p is None:
                return None
            ci_low, ci_high = p.credible_interval(0.95)
            out = asdict(p)
            out["mean"] = round(p.mean, 4)
            out["ci_low_95"] = round(ci_low, 4)
            out["ci_high_95"] = round(ci_high, 4)
            out["avg_R_per_trade"] = (
                round(p.sum_R_multiple / p.n_observed, 4)
                if p.n_observed > 0 else 0.0
            )
            return out

    async def all_posteriors(self) -> dict:
        await self.initialize()
        async with self._lock:
            out = {}
            for strategy, p in self._posteriors.items():
                ci_low, ci_high = p.credible_interval(0.95)
                d = asdict(p)
                d["mean"] = round(p.mean, 4)
                d["ci_low_95"] = round(ci_low, 4)
                d["ci_high_95"] = round(ci_high, 4)
                d["avg_R_per_trade"] = (
                    round(p.sum_R_multiple / p.n_observed, 4)
                    if p.n_observed > 0 else 0.0
                )
                out[strategy] = d
            return out

    async def sample_arm(self, candidates: list[str]) -> Optional[str]:
        """Thompson sample: draw one sample from each candidate's posterior;
        pick the strategy with the highest draw. Unknown candidates use
        the uniform prior."""
        if not candidates:
            return None
        await self.initialize()
        try:
            from scipy.stats import beta as _beta
            use_scipy = True
        except ImportError:
            use_scipy = False
        async with self._lock:
            draws = {}
            for s in candidates:
                p = self._posteriors.get(s)
                a = p.alpha if p else PRIOR_ALPHA
                b = p.beta if p else PRIOR_BETA
                if use_scipy:
                    draws[s] = float(_beta.rvs(a, b))
                else:
                    # Fallback: betavariate
                    draws[s] = random.betavariate(a, b)
            best = max(draws, key=draws.get)
            log.debug("[BANDIT] sample_arm picked %s (draws=%s)", best, draws)
            return best

    async def ranked_by_credible_lower_bound(
        self, candidates: Optional[list[str]] = None, ci: float = 0.95,
    ) -> list[dict]:
        """Sort strategies by lower 95% CI on win rate (lower-confidence-bound
        / LCB). Conservative ranking — favours strategies whose win rate
        we can confidently say is high. Useful for the brief pipeline
        bias call (K3c)."""
        await self.initialize()
        async with self._lock:
            keys = candidates if candidates else list(self._posteriors.keys())
            out = []
            for s in keys:
                p = self._posteriors.get(s)
                if p is None:
                    p = StrategyPosterior(strategy=s)
                ci_low, ci_high = p.credible_interval(ci)
                out.append({
                    "strategy": s,
                    "lcb": round(ci_low, 4),
                    "ucb": round(ci_high, 4),
                    "mean": round(p.mean, 4),
                    "n_observed": p.n_observed,
                    "avg_R_per_trade": (
                        round(p.sum_R_multiple / p.n_observed, 4)
                        if p.n_observed > 0 else 0.0
                    ),
                })
            return sorted(out, key=lambda r: -r["lcb"])


_BANDIT: Optional[StrategyBandit] = None
_BANDIT_LOCK = asyncio.Lock()


async def get_bandit() -> StrategyBandit:
    global _BANDIT
    if _BANDIT is not None:
        await _BANDIT.initialize()
        return _BANDIT
    async with _BANDIT_LOCK:
        if _BANDIT is None:
            _BANDIT = StrategyBandit()
            await _BANDIT.initialize()
    return _BANDIT
