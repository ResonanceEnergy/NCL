"""
Auto-Trader entry-criteria policy — Wave 14K K0b + K0c

Single function `auto_open_eligible(idea, governor_decision)` returns
(eligible: bool, reason: str). The Phase-2 decision loop will call this
for every emitted trade idea before opening a paper trade.

Operator can tune thresholds via REST PATCH /auto-trader/policy without
a brain bounce — policy is loaded from data/portfolio/auto_trader/
policy.json on every check (cheap; small file).

K0c drawdown auto-pause: the policy itself doesn't read drawdown_bucket
directly — the governor_decision passed in already encodes band + mult.
A halt band shows up as governor_decision.approved == False with reason
"Drawdown band=halt ...". The loop ALSO consults state.set_drawdown_halt()
so the entire loop pauses rather than just rejecting per-idea.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.policy")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio" / "auto_trader"
POLICY_FILE = DATA_DIR / "policy.json"

VALID_STOP_TYPES = {"price", "atr", "volatility", "time", "thesis_break"}


@dataclass
class AutoTraderPolicy:
    """Operator-tunable thresholds. All fields have safe defaults."""

    # Hard gates (none of these can be relaxed without explicit operator flip)
    require_governor_approved: bool = True
    block_on_drawdown_halt: bool = True
    block_on_breadth_veto: bool = True

    # Quality gates
    require_stop_price: bool = True
    require_target_price: bool = True
    require_R_per_share: bool = True
    require_source_citations: bool = True
    min_R_R_ratio: float = 1.5            # target/stop distance ratio
    min_stop_distance_pct: float = 0.5    # stop must be >=0.5% from entry (don't bracket too tight)
    max_stop_distance_pct: float = 15.0   # stop must be <=15% from entry (don't risk too much per share)
    require_thesis_min_chars: int = 20    # must have a one-line thesis at minimum
    valid_stop_types: tuple = (
        "price", "atr", "volatility", "time", "thesis_break",
    )

    # Strategy-specific extras
    goat_require_with_trend: bool = True       # GOAT counter-trend = operator review only
    options_require_high_iv_rank: bool = False # placeholder (J2b not landed)
    polymarket_require_kelly_positive: bool = True

    # Counter-trend handling
    allow_counter_trend: bool = False     # blanket: operator must opt in
    counter_trend_max_R_dollars: float = 200.0  # if allowed, cap at small R

    # Confidence weighting (research: size by, don't gate on)
    use_confidence_as_size_multiplier: bool = True
    min_confidence_pct: float = 0          # 0 = no minimum; sizing scales but doesn't gate

    # Rate-limiting (don't open 50 trades in one tick if the brief shipped 50)
    max_opens_per_tick: int = 3
    max_opens_per_day: int = 12
    cooldown_seconds_after_open: int = 30  # don't open twice on same ticker within 30s

    # Metadata
    revision: int = 1
    updated_at_iso: Optional[str] = None
    updated_by: str = "default"
    notes: str = ""

    # Free-form
    metadata: dict = field(default_factory=dict)


_POLICY: Optional[AutoTraderPolicy] = None
_LOCK = asyncio.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def default_policy() -> AutoTraderPolicy:
    """Fresh defaults — used when no file exists yet."""
    p = AutoTraderPolicy()
    p.updated_at_iso = _now_iso()
    return p


def _persist(policy: AutoTraderPolicy) -> None:
    _ensure_dir()
    tmp = POLICY_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(asdict(policy), indent=2, sort_keys=True))
        tmp.replace(POLICY_FILE)
    except Exception as e:
        log.error("[AT-POLICY] persist failed: %s", e)


def _load() -> AutoTraderPolicy:
    if not POLICY_FILE.exists():
        p = default_policy()
        _persist(p)
        return p
    try:
        raw = json.loads(POLICY_FILE.read_text())
        if not isinstance(raw, dict):
            return default_policy()
        field_names = {f for f in AutoTraderPolicy.__dataclass_fields__}  # type: ignore[attr-defined]
        kept = {k: v for k, v in raw.items() if k in field_names}
        # Coerce tuple field — JSON has lists
        if isinstance(kept.get("valid_stop_types"), list):
            kept["valid_stop_types"] = tuple(kept["valid_stop_types"])
        return AutoTraderPolicy(**kept)
    except Exception as e:
        log.warning("[AT-POLICY] load failed (%s) — using defaults", e)
        return default_policy()


async def get_policy(*, force_reload: bool = False) -> AutoTraderPolicy:
    """Returns the active policy. Cheap on the hot path — single file
    read, async-safe via _LOCK."""
    global _POLICY
    if _POLICY is not None and not force_reload:
        return _POLICY
    async with _LOCK:
        if _POLICY is None or force_reload:
            _POLICY = _load()
            log.info(
                "[AT-POLICY] loaded rev=%s min_R:R=%.2f max_opens/tick=%d",
                _POLICY.revision, _POLICY.min_R_R_ratio, _POLICY.max_opens_per_tick,
            )
    return _POLICY


async def update_policy(
    patches: dict,
    *,
    updated_by: str = "operator",
) -> AutoTraderPolicy:
    """PATCH-style update. Only listed fields change; rest preserved.
    Caller may NOT remove/null fields — pass a value to update."""
    current = await get_policy()
    async with _LOCK:
        field_names = {f for f in AutoTraderPolicy.__dataclass_fields__}  # type: ignore[attr-defined]
        unknown = [k for k in patches if k not in field_names]
        if unknown:
            raise ValueError(f"Unknown policy fields: {unknown}")
        for k, v in patches.items():
            if k in ("valid_stop_types",) and isinstance(v, list):
                v = tuple(v)
            setattr(current, k, v)
        current.revision = (current.revision or 0) + 1
        current.updated_at_iso = _now_iso()
        current.updated_by = updated_by
        _persist(current)
    return current


# ── Eligibility check ────────────────────────────────────────────

async def auto_open_eligible(
    idea: dict,
    governor_decision: Optional[dict] = None,
    *,
    policy: Optional[AutoTraderPolicy] = None,
) -> tuple[bool, str]:
    """The auto-bar. Returns (eligible, reason).

    `idea` is a trade_idea dict from trade_idea_tracker.list_by_strategy()
    or the brief's trade_ideas[] element (post-J1c).

    `governor_decision` is the risk_governor.check_proposed_trade() output
    for this idea. The loop will compute it before calling this function.
    Pass None to skip the governor gate (useful for unit tests).
    """
    if policy is None:
        policy = await get_policy()

    # 1. Hard governor gates
    if governor_decision is not None and policy.require_governor_approved:
        if not governor_decision.get("approved"):
            reasons = governor_decision.get("reasons") or ["governor rejected"]
            return False, f"governor: {reasons[0]}"
        band = governor_decision.get("band")
        if policy.block_on_drawdown_halt and band == "halt":
            return False, f"drawdown halt (band={band})"

    # 2. Breadth veto (J3b)
    if policy.block_on_breadth_veto:
        bv = idea.get("breadth_veto") or {}
        if bv.get("vetoed"):
            return False, f"breadth veto: {bv.get('reason', '')[:80]}"

    # 3. Stop / target presence
    if policy.require_stop_price and idea.get("stop_price") in (None, 0, 0.0):
        return False, "no stop_price"
    if policy.require_target_price and idea.get("target_price") in (None, 0, 0.0):
        return False, "no target_price"
    if policy.require_R_per_share and not (idea.get("R_per_share") or 0) > 0:
        return False, "no R_per_share"

    # 4. R:R floor
    try:
        entry = float(idea.get("entry_price") or 0)
        stop = float(idea.get("stop_price") or 0)
        target = float(idea.get("target_price") or 0)
        if entry > 0 and stop > 0 and target > 0 and entry != stop:
            rr = abs(target - entry) / abs(entry - stop)
            if rr < policy.min_R_R_ratio:
                return False, f"R:R {rr:.2f} below {policy.min_R_R_ratio} floor"
            # Stop-distance sanity
            stop_pct = abs(entry - stop) / entry * 100
            if stop_pct < policy.min_stop_distance_pct:
                return False, (
                    f"stop too tight: {stop_pct:.2f}% < "
                    f"{policy.min_stop_distance_pct}% floor"
                )
            if stop_pct > policy.max_stop_distance_pct:
                return False, (
                    f"stop too wide: {stop_pct:.2f}% > "
                    f"{policy.max_stop_distance_pct}% ceiling"
                )
    except (TypeError, ValueError) as e:
        return False, f"price fields not parseable: {e}"

    # 5. Stop-type whitelist
    stop_type = idea.get("stop_type")
    if stop_type and stop_type not in policy.valid_stop_types:
        return False, f"invalid stop_type {stop_type!r}"

    # 6. Source citation requirement
    if policy.require_source_citations:
        sources = idea.get("sources") or []
        if not sources:
            return False, "no source citations"

    # 7. Thesis length
    thesis = idea.get("thesis") or ""
    if policy.require_thesis_min_chars and len(thesis) < policy.require_thesis_min_chars:
        return False, (
            f"thesis too short ({len(thesis)} chars < "
            f"{policy.require_thesis_min_chars} required)"
        )

    # 8. Counter-trend handling
    stance = idea.get("rotation_stance")
    if stance == "counter_trend":
        if not policy.allow_counter_trend:
            return False, "counter-trend ideas require operator review"

    # 9. Strategy-specific gates
    strat = (
        (idea.get("strategy_tag") or idea.get("strategy") or idea.get("type") or "")
        .lower()
    )
    if strat in ("goat", "momentum") and policy.goat_require_with_trend:
        if stance and stance != "with_trend" and stance != "neutral":
            return False, f"GOAT requires with_trend stance (got {stance!r})"

    # 10. Confidence floor (sized-by-confidence, not gated, by research —
    # but operator can set a minimum if they want)
    conf = (idea.get("confidence_pct") or idea.get("confidence") or 0)
    try:
        conf_f = float(conf)
    except (TypeError, ValueError):
        conf_f = 0.0
    if policy.min_confidence_pct and conf_f < policy.min_confidence_pct:
        return False, (
            f"confidence {conf_f:.1f}% below "
            f"{policy.min_confidence_pct}% minimum"
        )

    return True, "passed auto-bar"
