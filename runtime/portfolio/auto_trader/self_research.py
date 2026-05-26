"""
Auto-Trader self-research feedback — Wave 14K Phase 5 (K4a + K4c + K4d)

Closes the meta-loop: SHAP attributions + bandit posteriors feed BACK
into the upstream systems that produced the trade ideas in the first
place.

  K4a — apply_shap_to_authority_learner(attribution):
        For each (source, lift) pair in SHAP output, push outcomes
        into SourceAuthorityLearner so high-lift sources get authority
        weight boosts and low-lift sources get downgrades. Net effect:
        sources that PREDICT WINS get more weight in next morning brief;
        sources that PREDICT LOSSES get demoted.

  K4c — generate_research_topics():
        Cluster recent losing trades by ticker / sector / source / stop_type.
        Each cluster with >= 3 losses generates a research topic:
        "Why did 4 NVDA short-premium trades lose this week?"
        Topics are persisted + exposed to the brief executor so the
        brief can drive deeper research on its actual failures.

  K4d — brief_context_packet():
        Compact context block the brief pipeline prepends to executor
        prompt. Includes:
          - Top-3 strategies by LCB win rate (from bandit)
          - Most-recent strategy_learn findings (top predictors per strategy)
          - Open research topics from K4c
        The brief uses this to bias trade-idea allocation + frame
        narrative.

Storage:
  - data/portfolio/auto_trader/research_topics.json   (open topics)
  - data/portfolio/auto_trader/research_topics_history.jsonl (audit)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.self_research")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio" / "auto_trader"
TOPICS_FILE = DATA_DIR / "research_topics.json"
TOPICS_HISTORY = DATA_DIR / "research_topics_history.jsonl"

# Minimum losses to form a research-topic cluster
MIN_CLUSTER_SIZE = int(os.getenv("NCL_RESEARCH_MIN_CLUSTER", "3"))
# Max topics in the open queue at once (rotate oldest out)
MAX_OPEN_TOPICS = int(os.getenv("NCL_RESEARCH_MAX_OPEN", "12"))
# Lift threshold for SourceAuthorityLearner adjustment
# (any |lift| < this and we skip — too noisy to act on)
SHAP_LIFT_AUTHORITY_THRESHOLD = float(os.getenv("NCL_SHAP_AUTH_THRESHOLD", "0.10"))


@dataclass
class ResearchTopic:
    topic_id: str
    title: str
    rationale: str          # one-line "why this matters"
    cluster_features: dict  # {feature: value} dimensions that define the cluster
    n_losses: int
    avg_R: float
    example_trade_idea_ids: list = field(default_factory=list)
    status: str = "open"    # open | researched | dismissed
    created_at_iso: Optional[str] = None
    resolved_at_iso: Optional[str] = None
    resolution_notes: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# ── K4a: SHAP -> SourceAuthorityLearner ───────────────────────────

async def apply_shap_to_authority_learner(attribution: dict) -> dict:
    """For each source identified in SHAP top_positive/top_negative,
    push synthetic "correct"/"wrong" outcomes into SourceAuthorityLearner.

    Why synthetic outcomes vs the raw lift number: SourceAuthorityLearner
    is already a Beta-Bernoulli ledger; the cleanest update is to add
    counts. We add `int(round(lift * n))` correct/wrong outcomes — that
    is, if a source had +20% lift over 10 trades, we add ~2 'correct'
    outcomes to its posterior.

    Returns a summary dict of which sources got bumped.
    """
    try:
        from ...feedback.source_authority_learner import get_learner
    except Exception as e:
        log.warning("[SR-AUTH] cannot import SourceAuthorityLearner: %s", e)
        return {"error": str(e), "adjustments": []}

    learner = get_learner()
    adjustments = []

    # Iterate features → values; only act on 'source' feature
    for feat, value_list in (attribution.get("features") or {}).items():
        if feat != "source":
            continue
        for entry in value_list:
            source = entry["value"]
            lift = entry["lift_vs_overall"]
            n = entry["n"]
            if abs(lift) < SHAP_LIFT_AUTHORITY_THRESHOLD:
                continue
            # Compute how many synthetic outcomes to add (cap at n//2)
            delta = max(1, min(int(round(abs(lift) * n)), n // 2 + 1))
            outcome = "correct" if lift > 0 else "wrong"
            try:
                # SourceAuthorityLearner.record signature: (source, outcome, *, ...)
                await learner.record(
                    source,
                    outcome,
                    delta=float(delta),
                    notes=(
                        f"K4a SHAP feedback: lift={lift:+.3f} n={n} "
                        f"strategy={attribution.get('strategy', '?')}"
                    ),
                )
                adjustments.append({
                    "source": source, "lift": lift, "n": n,
                    "delta": delta, "outcome": outcome,
                })
            except Exception as e:
                log.warning(
                    "[SR-AUTH] record_outcome failed for %s: %s", source, e,
                )
    if adjustments:
        log.info("[SR-AUTH] applied %d authority adjustments from SHAP", len(adjustments))
    return {"adjustments": adjustments,
            "strategy": attribution.get("strategy"),
            "computed_at_iso": _now_iso()}


# ── K4c: Research topic generator ─────────────────────────────────

def _topic_id_from_cluster(cluster_features: dict) -> str:
    """Stable id from sorted feature:value pairs."""
    parts = []
    for k in sorted(cluster_features.keys()):
        parts.append(f"{k}={cluster_features[k]}")
    return "topic:" + "|".join(parts)[:80]


def _cluster_losses(closed_losing_trades: list[dict]) -> list[dict]:
    """Group losing trades into clusters by shared (ticker, sector_etf,
    source, stop_type, rotation_quadrant) tuples. Each cluster needs
    >= MIN_CLUSTER_SIZE.

    Each trade is expected to carry: ticker, sector_etf, source,
    stop_type, rotation_quadrant, R_multiple, trade_idea_id.
    """
    clusters: dict[tuple, list[dict]] = defaultdict(list)
    cluster_dims = ("sector_etf", "source", "stop_type", "rotation_quadrant")
    for t in closed_losing_trades:
        for dim in cluster_dims:
            value = t.get(dim) or "unknown"
            if value in ("unknown", None, ""):
                continue
            key = (dim, value)
            clusters[key].append(t)
    out = []
    for (dim, value), trades in clusters.items():
        if len(trades) < MIN_CLUSTER_SIZE:
            continue
        avg_R = sum(t.get("R_multiple", 0) for t in trades) / len(trades)
        out.append({
            "feature": dim, "value": value,
            "n_losses": len(trades), "avg_R": round(avg_R, 4),
            "trade_idea_ids": [t.get("trade_idea_id") for t in trades],
        })
    return sorted(out, key=lambda c: c["n_losses"], reverse=True)


def _phrase_topic(cluster: dict) -> tuple[str, str]:
    """Generate (title, rationale) for a cluster."""
    feat = cluster["feature"]
    val = cluster["value"]
    n = cluster["n_losses"]
    avg_R = cluster["avg_R"]
    if feat == "sector_etf":
        title = f"Why did {n} {val}-sector trades lose ({avg_R:+.2f}R avg)?"
        rationale = (
            f"Concentrated losses in {val} suggest a sector-specific "
            f"thesis blind spot. Worth a fundamentals dive."
        )
    elif feat == "source":
        title = f"Why is the '{val}' source over-emitting losing setups?"
        rationale = (
            f"{n} losing trades all sourced from '{val}'. Check if the "
            f"scoring threshold + cross-source confirmation rules are tight enough."
        )
    elif feat == "stop_type":
        title = f"Why are {val}-type stops underperforming ({n} losses, {avg_R:+.2f}R avg)?"
        rationale = (
            f"Stop methodology '{val}' may be calibrated wrong for current regime. "
            f"Compare with stop_type performance in other regimes."
        )
    elif feat == "rotation_quadrant":
        title = f"Why are {val}-quadrant entries losing ({n} trades)?"
        rationale = (
            f"Rotation-quadrant {val} should be informative but is producing "
            f"losses. Check if breadth-veto threshold is too loose."
        )
    else:
        title = f"Why is {feat}={val} associated with {n} losses?"
        rationale = "Cluster surfaced by losing-trade attribution."
    return title, rationale


async def generate_research_topics(
    *,
    lookback_days: int = 14,
    min_cluster_size: int = MIN_CLUSTER_SIZE,
) -> list[dict]:
    """Pull recent closed losing trades, cluster them, persist new
    open research topics. Idempotent — same cluster doesn't generate
    duplicate topics within the lookback window."""
    from datetime import timedelta
    from ..trade_idea_tracker import get_trade_idea_tracker
    from .observability import list_recent_chains

    tracker = await get_trade_idea_tracker()
    all_ideas = await tracker.list_by_strategy(None)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    losing = [
        i for i in all_ideas
        if (i.get("R_multiple") or 0) < 0
        and (i.get("closed_at_iso") or "") > cutoff
        and i.get("outcome") in ("stopped_out", "manually_closed", "expired")
    ]
    if not losing:
        return []

    # Enrich with feature columns from reasoning chains
    chains = {c["trade_idea_id"]: c for c in await list_recent_chains(limit=1000)
              if c.get("trade_idea_id")}
    enriched = []
    for idea in losing:
        tid = idea.get("trade_idea_id")
        chain = chains.get(tid, {})
        snap = chain.get("idea_snapshot") or {}
        enriched.append({
            "trade_idea_id": tid,
            "ticker": idea.get("ticker"),
            "R_multiple": idea.get("R_multiple"),
            "source": chain.get("source"),
            "sector_etf": snap.get("sector_etf"),
            "stop_type": snap.get("stop_type"),
            "rotation_quadrant": snap.get("rotation_quadrant"),
        })

    clusters = _cluster_losses(enriched)
    # Filter to clusters >= min_cluster_size already done in _cluster_losses
    open_topics = _load_open_topics()
    existing_ids = {t["topic_id"] for t in open_topics}
    new_topics = []
    for c in clusters:
        cluster_features = {c["feature"]: c["value"]}
        tid = _topic_id_from_cluster(cluster_features)
        if tid in existing_ids:
            continue  # already in open queue
        title, rationale = _phrase_topic(c)
        topic = ResearchTopic(
            topic_id=tid, title=title, rationale=rationale,
            cluster_features=cluster_features,
            n_losses=c["n_losses"], avg_R=c["avg_R"],
            example_trade_idea_ids=c["trade_idea_ids"][:5],
            status="open", created_at_iso=_now_iso(),
        )
        new_topics.append(asdict(topic))

    if new_topics:
        # Append + cap at MAX_OPEN_TOPICS (FIFO eviction of resolved/oldest)
        combined = open_topics + new_topics
        open_only = [t for t in combined if t.get("status") == "open"]
        if len(open_only) > MAX_OPEN_TOPICS:
            open_only = sorted(open_only, key=lambda t: t.get("created_at_iso") or "",
                              reverse=True)[:MAX_OPEN_TOPICS]
        _persist_topics(open_only)
        for t in new_topics:
            _append_history("created", t)
        log.info(
            "[SR-TOPICS] generated %d new research topics (open queue: %d)",
            len(new_topics), len(open_only),
        )
    return new_topics


def _load_open_topics() -> list[dict]:
    if not TOPICS_FILE.exists():
        return []
    try:
        raw = json.loads(TOPICS_FILE.read_text())
        return raw if isinstance(raw, list) else []
    except Exception as e:
        log.warning("[SR-TOPICS] load failed: %s", e)
        return []


def _persist_topics(topics: list[dict]) -> None:
    _ensure_dir()
    tmp = TOPICS_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(topics, indent=2, sort_keys=True))
        tmp.replace(TOPICS_FILE)
    except Exception as e:
        log.error("[SR-TOPICS] persist failed: %s", e)


def _append_history(action: str, topic: dict) -> None:
    row = {"ts": _now_iso(), "action": action, "topic": topic}
    try:
        _ensure_dir()
        with open(TOPICS_HISTORY, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:
        log.warning("[SR-TOPICS] history append failed: %s", e)


async def resolve_research_topic(
    topic_id: str, *, resolution_notes: str = "", dismiss: bool = False,
) -> Optional[dict]:
    """Mark a topic researched or dismissed."""
    topics = _load_open_topics()
    found = None
    for t in topics:
        if t.get("topic_id") == topic_id:
            found = t
            break
    if found is None:
        return None
    found["status"] = "dismissed" if dismiss else "researched"
    found["resolved_at_iso"] = _now_iso()
    found["resolution_notes"] = resolution_notes
    _persist_topics([t for t in topics if t.get("topic_id") != topic_id])
    _append_history(found["status"], found)
    return found


def list_open_research_topics() -> list[dict]:
    return _load_open_topics()


# ── K4d: Brief context packet ──────────────────────────────────

async def brief_context_packet(*, max_strategies: int = 5,
                                  max_topics: int = 5) -> str:
    """Compact text block the brief executor prompt prepends. Includes:
      - Top strategies by LCB win rate (from bandit)
      - Most-recent strategy_learn findings (top predictors)
      - Open research topics

    Returns a multi-line string ready to embed in the prompt.
    """
    lines: list[str] = []

    # Bandit top strategies
    try:
        from .strategy_bandit import get_bandit
        bandit = await get_bandit()
        ranked = await bandit.ranked_by_credible_lower_bound(ci=0.95)
        if ranked:
            lines.append("=== STRATEGY EXPECTANCY (Bayesian posteriors over win rate) ===")
            lines.append(
                "Strategies ranked by lower 95% CI (conservative). Bias "
                "trade-idea allocation toward higher-LCB strategies; deprioritize "
                "lower-LCB strategies until evidence accumulates."
            )
            for r in ranked[:max_strategies]:
                if r["n_observed"] < 3:
                    continue  # too little data to be informative
                lines.append(
                    f"  {r['strategy']}: LCB {r['lcb']:.2%} | mean {r['mean']:.2%} | "
                    f"avgR {r['avg_R_per_trade']:+.2f} | n={r['n_observed']}"
                )
            lines.append("")
    except Exception as e:
        log.debug("[SR-PACKET] bandit unavailable: %s", e)

    # Recent SHAP findings — look for most-recent strategy_learn MemUnits
    try:
        from .shap_attribution import ATTR_HISTORY
        if ATTR_HISTORY.exists():
            with open(ATTR_HISTORY, "r") as f:
                rows = [json.loads(line) for line in f if line.strip()]
            # Most recent per strategy
            latest_by_strat: dict[str, dict] = {}
            for r in rows:
                s = r.get("strategy")
                if s and r.get("computed_at_iso", "") > latest_by_strat.get(
                    s, {}
                ).get("computed_at_iso", ""):
                    latest_by_strat[s] = r
            if latest_by_strat:
                lines.append("=== STRATEGY LEARN (top predictors from closed paper trades) ===")
                for strat, attr in list(latest_by_strat.items())[:max_strategies]:
                    pos = attr.get("top_positive") or []
                    neg = attr.get("top_negative") or []
                    lines.append(
                        f"  [{strat}] n={attr['n']} overall hit "
                        f"{attr['overall_hit_rate']:.0%}"
                    )
                    for e in pos[:2]:
                        lines.append(
                            f"    + {e['feature']}={e['value']} -> "
                            f"hit {e['hit_rate']:.0%} ({e['lift']:+.0%})"
                        )
                    for e in neg[:2]:
                        lines.append(
                            f"    - {e['feature']}={e['value']} -> "
                            f"hit {e['hit_rate']:.0%} ({e['lift']:+.0%})"
                        )
                lines.append("")
    except Exception as e:
        log.debug("[SR-PACKET] SHAP history unavailable: %s", e)

    # Open research topics
    try:
        topics = list_open_research_topics()
        if topics:
            lines.append("=== OPEN RESEARCH TOPICS (from losing-trade clusters) ===")
            lines.append(
                "These are the loss patterns the system is currently failing on. "
                "Consider these gaps when emitting trade ideas — avoid setups "
                "that match the cluster's profile until the topic is researched."
            )
            for t in topics[:max_topics]:
                lines.append(
                    f"  - {t['title']} (n_losses={t['n_losses']}, "
                    f"avgR {t['avg_R']:+.2f})"
                )
            lines.append("")
    except Exception as e:
        log.debug("[SR-PACKET] research topics unavailable: %s", e)

    if not lines:
        return ""
    return "\n".join(lines)
