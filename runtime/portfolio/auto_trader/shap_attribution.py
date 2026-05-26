"""
Auto-Trader feature attribution — Wave 14K Phase 4 (K3d)

Not the SHAP package — a Shapley-flavored conditional-win-rate analysis
that does the same job for our schema without the heavyweight dep.

The question: "Of the features attached to closed trades, which ones
actually predicted win/loss?"

Approach for each feature:
  - For each unique value v of the feature:
    - hit_rate_given_v = wins_with_v / closed_with_v
    - delta = hit_rate_given_v − overall_hit_rate
    - signed_lift = delta (positive = this value predicts wins)
  - Feature importance = abs(delta) weighted by sample size

This is mathematically equivalent to the marginal Shapley value when
features are independent (rarely true, but a reasonable approximation
for a portfolio-level feedback loop). It's also more interpretable than
SHAP because the unit is "lift in hit rate" rather than "log-odds
contribution" — operator can read it directly.

Computed every 10 closed trades per strategy (config K3D_TRIGGER_EVERY_N).
Emits portfolio:strategy_learn MemUnit at importance 90 with the top-3
positive and top-3 negative attributions.

Features analyzed (drawn from trade_idea + scanner_data snapshot):
  - source              (brief | goat | bravo | polymarket | manual)
  - strategy            (already grouped; used for filtering)
  - sector_etf          (sector ETF code)
  - rotation_quadrant   (Leading | Improving | Weakening | Lagging)
  - rotation_stance     (with_trend | counter_trend | neutral)
  - stop_type           (price | atr | volatility | time | thesis_break)
  - issued_hour_utc     (bucketed: pre-market | open | midday | close)
  - days_held_bucket    (intraday | 1-3d | 4-7d | 8-30d)
  - direction           (long | short)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.shap_attribution")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio" / "auto_trader"
ATTR_HISTORY = DATA_DIR / "attribution_history.jsonl"

# Trigger SHAP analysis every N closed trades per strategy
TRIGGER_EVERY_N = int(os.getenv("NCL_BANDIT_SHAP_EVERY_N", "10"))

# Minimum samples for a feature value to count (avoid noise from
# singleton observations)
MIN_SAMPLES_PER_VALUE = int(os.getenv("NCL_BANDIT_SHAP_MIN_N", "3"))


def _bucket_hour_utc(iso_ts: Optional[str]) -> str:
    """Pre-market / open / midday / close-window bucket."""
    if not iso_ts:
        return "unknown"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        et_hour = (dt.hour - 4) % 24
        if et_hour < 9 or (et_hour == 9 and dt.minute < 30):
            return "pre-market"
        if (et_hour, dt.minute) <= (10, 30):
            return "open-hour"
        if et_hour < 15:
            return "midday"
        return "close-hour"
    except (ValueError, TypeError):
        return "unknown"


def _bucket_days_held(d: Optional[float]) -> str:
    if d is None:
        return "unknown"
    try:
        d_f = float(d)
    except (TypeError, ValueError):
        return "unknown"
    if d_f < 1:
        return "intraday"
    if d_f <= 3:
        return "1-3d"
    if d_f <= 7:
        return "4-7d"
    if d_f <= 30:
        return "8-30d"
    return "30d+"


def _extract_features(chain: dict, paper_trade_meta: dict) -> dict:
    """Pull the feature vector from a reasoning chain + paper-trade close metadata."""
    idea = chain.get("idea_snapshot") or {}
    scanner = idea.get("scanner_data") or chain.get("metadata") or {}
    return {
        "source": chain.get("source") or "unknown",
        "sector_etf": (idea.get("sector_etf") or "none").upper(),
        "rotation_quadrant": idea.get("rotation_quadrant") or "unknown",
        "rotation_stance": idea.get("rotation_stance") or "neutral",
        "stop_type": idea.get("stop_type") or "unknown",
        "issued_hour_bucket": _bucket_hour_utc(chain.get("ts")),
        "days_held_bucket": _bucket_days_held(paper_trade_meta.get("days_held")),
        "direction": (idea.get("direction") or "long").lower(),
    }


def _compute_attributions(
    rows: list[dict], min_samples: int = MIN_SAMPLES_PER_VALUE
) -> dict:
    """Each row: {features: dict, win: bool, R_multiple: float}.

    Returns:
      {
        overall_hit_rate: float,
        n: int,
        features: {feature_name: [
          {value, n, hit_rate, lift_vs_overall, avg_R}
        ]},
        top_positive: [(feature, value, lift, n), ...],   # most-predictive of wins
        top_negative: [(feature, value, lift, n), ...]    # most-predictive of losses
      }
    """
    n_total = len(rows)
    if n_total == 0:
        return {"n": 0, "overall_hit_rate": 0.0, "features": {},
                "top_positive": [], "top_negative": []}
    n_wins = sum(1 for r in rows if r["win"])
    overall = n_wins / n_total

    # Pivot: feature -> value -> [list of rows]
    by_feature: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        for fname, fval in r["features"].items():
            by_feature[fname][str(fval)].append(r)

    features_out: dict[str, list[dict]] = {}
    flat_pos = []
    flat_neg = []
    for fname, val_map in by_feature.items():
        per_value = []
        for fval, group in val_map.items():
            n_g = len(group)
            if n_g < min_samples:
                continue
            wins_g = sum(1 for r in group if r["win"])
            rate_g = wins_g / n_g
            lift = rate_g - overall
            avg_R = sum(r["R_multiple"] for r in group) / n_g
            entry = {
                "value": fval, "n": n_g,
                "hit_rate": round(rate_g, 4),
                "lift_vs_overall": round(lift, 4),
                "avg_R": round(avg_R, 4),
            }
            per_value.append(entry)
            flat_entry = (fname, fval, lift, n_g, rate_g, avg_R)
            if lift > 0:
                flat_pos.append(flat_entry)
            elif lift < 0:
                flat_neg.append(flat_entry)
        per_value.sort(key=lambda x: -x["lift_vs_overall"])
        features_out[fname] = per_value

    # Top-3 each side by |lift|
    flat_pos.sort(key=lambda x: -x[2])  # descending lift
    flat_neg.sort(key=lambda x: x[2])   # ascending lift (most-negative first)

    def _serialize(entry):
        f, v, l, n, hr, avg_R = entry
        return {"feature": f, "value": v, "lift": round(l, 4),
                "n": n, "hit_rate": round(hr, 4), "avg_R": round(avg_R, 4)}

    return {
        "n": n_total,
        "overall_hit_rate": round(overall, 4),
        "features": features_out,
        "top_positive": [_serialize(e) for e in flat_pos[:3]],
        "top_negative": [_serialize(e) for e in flat_neg[:3]],
    }


# ── Public API ───────────────────────────────────────────────────

async def maybe_run_attribution(
    *,
    brain,
    strategy: str,
    closed_trades_count: int,
) -> Optional[dict]:
    """Called by outcome_attributor after every paper close. Decides
    whether to run SHAP for this strategy (every TRIGGER_EVERY_N) and
    emits result + memory unit if so.

    Returns the attribution dict if run, None if skipped."""
    if closed_trades_count <= 0:
        return None
    if closed_trades_count % TRIGGER_EVERY_N != 0:
        return None
    log.info(
        "[SHAP] triggering attribution for strategy=%s after %d closes",
        strategy, closed_trades_count,
    )
    return await run_attribution_for_strategy(brain=brain, strategy=strategy)


async def run_attribution_for_strategy(
    *,
    brain,
    strategy: str,
) -> dict:
    """Read closed paper trades + their reasoning chains for `strategy`,
    compute attributions, emit memory unit, persist to history."""
    from ..trade_idea_tracker import get_trade_idea_tracker
    from .observability import list_recent_chains

    tracker = await get_trade_idea_tracker()
    ideas = await tracker.list_by_strategy(strategy=strategy)
    # Only closed (non-emitted, non-taken) with R_multiple recorded
    closed = [
        i for i in ideas
        if i.get("outcome") in ("stopped_out", "target_hit", "manually_closed", "expired")
        and i.get("R_multiple") is not None
    ]
    if len(closed) < 5:
        log.info("[SHAP] not enough closed trades (%d) for %s", len(closed), strategy)
        return {"strategy": strategy, "n": len(closed),
                "reason": "need >=5 closed trades for stable attribution"}

    # Stitch chains by trade_idea_id
    all_chains = await list_recent_chains(limit=1000)
    chains_by_id = {c.get("trade_idea_id"): c for c in all_chains if c.get("trade_idea_id")}

    rows = []
    for idea in closed:
        tid = idea.get("trade_idea_id")
        chain = chains_by_id.get(tid)
        if chain is None:
            continue
        meta = {"days_held": idea.get("holding_days") or 0}
        features = _extract_features(chain, meta)
        rows.append({
            "features": features,
            "win": float(idea["R_multiple"]) > 0,
            "R_multiple": float(idea["R_multiple"]),
            "trade_idea_id": tid,
        })

    if len(rows) < 5:
        return {"strategy": strategy, "n": len(rows),
                "reason": "rows < 5 after chain stitching"}

    attribution = _compute_attributions(rows)
    attribution["strategy"] = strategy
    attribution["computed_at_iso"] = datetime.now(timezone.utc).isoformat()

    # Persist to history
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(ATTR_HISTORY, "a") as f:
            f.write(json.dumps(attribution) + "\n")
    except Exception as e:
        log.warning("[SHAP] history persist failed: %s", e)

    # Emit memory unit
    await _emit_attribution_memory(brain, attribution)

    # Wave 14K Phase 5 K4a: push source-level lifts into
    # SourceAuthorityLearner. Non-fatal — never blocks SHAP completion.
    try:
        from .self_research import apply_shap_to_authority_learner
        auth_result = await apply_shap_to_authority_learner(attribution)
        if auth_result.get("adjustments"):
            log.info(
                "[SHAP->K4a] applied %d authority adjustments",
                len(auth_result["adjustments"]),
            )
    except Exception as e:
        log.warning("[SHAP] K4a authority push skipped: %s", e)

    # Wave 14K Phase 5 K4c: regenerate research topics opportunistically
    # whenever we have fresh attribution data. Idempotent — same cluster
    # doesn't generate duplicate topic.
    try:
        from .self_research import generate_research_topics
        new_topics = await generate_research_topics()
        if new_topics:
            log.info("[SHAP->K4c] generated %d research topics", len(new_topics))
    except Exception as e:
        log.warning("[SHAP] K4c topic generation skipped: %s", e)

    return attribution


async def _emit_attribution_memory(brain, attribution: dict) -> None:
    """K3d memory emission at importance 90 — strategy-learn signal
    that the brief pipeline / SourceAuthorityLearner can react to."""
    mem = getattr(brain, "memory_store", None)
    if mem is None or not hasattr(mem, "create_unit"):
        return
    strategy = attribution["strategy"]
    n = attribution["n"]
    overall = attribution["overall_hit_rate"]
    pos = attribution["top_positive"]
    neg = attribution["top_negative"]

    pos_lines = [
        f"{e['feature']}={e['value']} → hit {e['hit_rate']:.0%} "
        f"({e['lift']:+.0%} vs avg, n={e['n']}, avgR={e['avg_R']:+.2f})"
        for e in pos[:3]
    ]
    neg_lines = [
        f"{e['feature']}={e['value']} → hit {e['hit_rate']:.0%} "
        f"({e['lift']:+.0%} vs avg, n={e['n']}, avgR={e['avg_R']:+.2f})"
        for e in neg[:3]
    ]
    content = (
        f"STRATEGY-LEARN [{strategy}] after {n} closed paper trades "
        f"(overall hit rate {overall:.1%}):\n"
        + "PREDICTORS OF WINS:\n  " + "\n  ".join(pos_lines or ["(none)"])
        + "\nPREDICTORS OF LOSSES:\n  " + "\n  ".join(neg_lines or ["(none)"])
    )
    try:
        await mem.create_unit(
            content=content,
            source="portfolio:strategy_learn",
            importance=90.0,
            tags=[
                "portfolio", "auto_trader", "strategy_learn",
                f"strategy:{strategy}",
            ],
            memory_type="semantic",
            metadata={
                "strategy": strategy,
                "n_closed": n,
                "overall_hit_rate": overall,
                "top_positive": pos[:3],
                "top_negative": neg[:3],
                "wave": "14K-K3d",
            },
        )
        log.info(
            "[SHAP] strategy_learn memory emitted for %s "
            "(n=%d, hit=%.1f%%)",
            strategy, n, overall * 100,
        )
    except Exception as e:
        log.warning("[SHAP] memory emission failed: %s", e)
