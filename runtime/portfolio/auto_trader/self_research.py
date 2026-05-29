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

import json
import logging
import os
from collections import defaultdict
from dataclasses import asdict, dataclass, field
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
    rationale: str  # one-line "why this matters"
    cluster_features: dict  # {feature: value} dimensions that define the cluster
    n_losses: int
    avg_R: float
    example_trade_idea_ids: list = field(default_factory=list)
    status: str = "open"  # open | researched | dismissed
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
                adjustments.append(
                    {
                        "source": source,
                        "lift": lift,
                        "n": n,
                        "delta": delta,
                        "outcome": outcome,
                    }
                )
            except Exception as e:
                log.warning(
                    "[SR-AUTH] record_outcome failed for %s: %s",
                    source,
                    e,
                )
    if adjustments:
        log.info("[SR-AUTH] applied %d authority adjustments from SHAP", len(adjustments))
    return {
        "adjustments": adjustments,
        "strategy": attribution.get("strategy"),
        "computed_at_iso": _now_iso(),
    }


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
        out.append(
            {
                "feature": dim,
                "value": value,
                "n_losses": len(trades),
                "avg_R": round(avg_R, 4),
                "trade_idea_ids": [t.get("trade_idea_id") for t in trades],
            }
        )
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
        i
        for i in all_ideas
        if (i.get("R_multiple") or 0) < 0
        and (i.get("closed_at_iso") or "") > cutoff
        and i.get("outcome") in ("stopped_out", "manually_closed", "expired")
    ]
    if not losing:
        return []

    # Enrich with feature columns from reasoning chains
    chains = {
        c["trade_idea_id"]: c
        for c in await list_recent_chains(limit=1000)
        if c.get("trade_idea_id")
    }
    enriched = []
    for idea in losing:
        tid = idea.get("trade_idea_id")
        chain = chains.get(tid, {})
        snap = chain.get("idea_snapshot") or {}
        enriched.append(
            {
                "trade_idea_id": tid,
                "ticker": idea.get("ticker"),
                "R_multiple": idea.get("R_multiple"),
                "source": chain.get("source"),
                "sector_etf": snap.get("sector_etf"),
                "stop_type": snap.get("stop_type"),
                "rotation_quadrant": snap.get("rotation_quadrant"),
            }
        )

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
            topic_id=tid,
            title=title,
            rationale=rationale,
            cluster_features=cluster_features,
            n_losses=c["n_losses"],
            avg_R=c["avg_R"],
            example_trade_idea_ids=c["trade_idea_ids"][:5],
            status="open",
            created_at_iso=_now_iso(),
        )
        new_topics.append(asdict(topic))

    if new_topics:
        # Append + cap at MAX_OPEN_TOPICS (FIFO eviction of resolved/oldest)
        combined = open_topics + new_topics
        open_only = [t for t in combined if t.get("status") == "open"]
        if len(open_only) > MAX_OPEN_TOPICS:
            open_only = sorted(
                open_only, key=lambda t: t.get("created_at_iso") or "", reverse=True
            )[:MAX_OPEN_TOPICS]
        _persist_topics(open_only)
        for t in new_topics:
            _append_history("created", t)
        log.info(
            "[SR-TOPICS] generated %d new research topics (open queue: %d)",
            len(new_topics),
            len(open_only),
        )

        # Wave 14W-E: fire the auto-deep-dive pipeline for each new topic.
        # Bounded fire-and-forget — running synchronously would multiply
        # research_topic generation latency by Sonnet's. Each topic gets
        # its own background task so they fan out.
        import asyncio as _asyncio
        import os as _os

        if _os.getenv("NCL_AGENT_BUS_AUTO_DEEPDIVE", "1") == "1":
            try:
                loop = _asyncio.get_event_loop()
                for t in new_topics:
                    loop.create_task(auto_deepdive_topic(t))
            except Exception as _e:
                log.debug("[SR-TOPICS] auto deep-dive scheduling failed: %s", _e)

    return new_topics


# ─────────────────────────────────────────────────────────────────────
# Wave 14W-E — research-topic auto deep dive
# ─────────────────────────────────────────────────────────────────────


async def auto_deepdive_topic(topic: dict) -> dict:
    """For a freshly-created research topic, fan out:
      1. memory.fused_search to pull every relevant prior MemUnit
      2. awarebot.scan_now to bias the next scanner pass toward this topic
      3. Sonnet 4 synthesis using (1)'s hits + the topic title/rationale
      4. write the synthesis back as ``resolution_notes`` so the next
         brief sees it

    Returns a small status dict so a caller (or test) can inspect what
    happened. Never raises — failures fall through to the next topic.

    Per LANE_ARCHITECTURE Phase E item 11.
    """
    topic_id = topic.get("topic_id", "")
    title = topic.get("title", "")
    rationale = topic.get("rationale", "")

    try:
        from ...agent_bus import intel_request as _bus
    except Exception as e:
        log.debug("[DEEPDIVE] agent_bus unavailable: %s", e)
        return {"topic_id": topic_id, "ok": False, "reason": "no_agent_bus"}

    # 1. Pull prior MemUnits via fused search
    query = f"{title}. {rationale}"
    fused = await _bus.intel_request(
        kind=_bus.RequestKind.MEMORY_FUSED_SEARCH,
        caller=f"self_research:deepdive:{topic_id}",
        urgency="normal",
        query=query,
        max_results=15,
    )
    hits = []
    if fused.ok and isinstance(fused.result, dict):
        hits = fused.result.get("hits") or []

    # 2. Bias the next scanner pass toward this topic
    scan_focus = title.replace("Why did ", "").replace("Why is ", "")[:140]
    await _bus.intel_request(
        kind=_bus.RequestKind.AWAREBOT_SCAN_NOW,
        caller=f"self_research:deepdive:{topic_id}",
        urgency="normal",
        focus=scan_focus,
        ttl_minutes=120,
    )

    # 3. Sonnet synthesis — budget-gated, falls through to a rule-based
    # summary if the LLM call can't fire.
    synthesis = await _synthesize_topic_notes(title=title, rationale=rationale, hits=hits)

    # 4. Write back as resolution_notes (stays open=True so NATRIX can
    # still close manually after reviewing).
    try:
        _write_topic_notes(topic_id, synthesis)
    except Exception as e:
        log.debug("[DEEPDIVE] write_notes failed for %s: %s", topic_id, e)

    return {
        "topic_id": topic_id,
        "ok": True,
        "memory_hits": len(hits),
        "synthesis_chars": len(synthesis or ""),
    }


async def _synthesize_topic_notes(*, title: str, rationale: str, hits: list) -> str:
    """Sonnet 4 synthesis. Budget-gated. Returns a string (possibly
    empty) — callers must tolerate falsy."""
    try:
        from ...cost_tracker import can_spend
        from ...llm.facade import llm_facade
    except Exception as e:
        log.debug("[DEEPDIVE] llm/cost imports failed: %s", e)
        return _rule_based_topic_notes(title=title, rationale=rationale, hits=hits)

    if not can_spend("anthropic", 0.03):
        log.info("[DEEPDIVE] budget exhausted — using rule-based notes")
        return _rule_based_topic_notes(title=title, rationale=rationale, hits=hits)

    # Build a tight context block from the top hits.
    hit_block_lines: list[str] = []
    for i, h in enumerate(hits[:10]):
        if not isinstance(h, dict):
            continue
        snippet = (h.get("content") or "")[:250].replace("\n", " ")
        hit_block_lines.append(
            f"[{i + 1}] ({h.get('source', '?')}, tier={h.get('tier', '?')}) {snippet}"
        )
    hits_text = "\n".join(hit_block_lines) or "(no prior memory hits)"

    prompt = (
        f"You are NCL's research analyst. The auto-trader's "
        f"self-research module just surfaced a losing-trade cluster.\n\n"
        f"TOPIC TITLE: {title}\n"
        f"RATIONALE: {rationale}\n\n"
        f"PRIOR MEMORY HITS (top {len(hit_block_lines)}):\n{hits_text}\n\n"
        "Write a tight 200-300 word synthesis covering:\n"
        "  1. What the prior memory says about this cluster.\n"
        "  2. Most-likely root cause (regime, recipe drift, source quality).\n"
        "  3. 2-3 concrete actions the next brief or council should consider.\n"
        "  4. One falsifiable hypothesis to test going forward.\n"
        "Plain prose, no markdown headers."
    )

    try:
        out = await llm_facade.complete(
            model="claude-sonnet-4-20250514",
            prompt=prompt,
            max_tokens=600,
            cost_tag="self_research:deepdive",
        )
        text = (out or "").strip() if isinstance(out, str) else ""
        return text or _rule_based_topic_notes(title=title, rationale=rationale, hits=hits)
    except Exception as e:
        log.warning("[DEEPDIVE] sonnet synthesis failed: %s", e)
        return _rule_based_topic_notes(title=title, rationale=rationale, hits=hits)


def _rule_based_topic_notes(*, title: str, rationale: str, hits: list) -> str:
    """Fallback when Sonnet is unavailable or budget-blocked."""
    parts: list[str] = []
    parts.append(f"DEEPDIVE (rule-based fallback) — {title}")
    parts.append(rationale)
    if hits:
        parts.append("")
        parts.append(f"Found {len(hits)} prior memory items. Top sources:")
        from collections import Counter

        src_counter: Counter = Counter()
        for h in hits[:15]:
            if isinstance(h, dict):
                src_counter[h.get("source", "?")] += 1
        for src, n in src_counter.most_common(5):
            parts.append(f"  - {src}: {n}")
    else:
        parts.append("No prior memory hits — cluster is novel.")
    parts.append("")
    parts.append(
        "Next steps: queue an Awarebot focused scan (already fired), "
        "and consider council review if the cluster persists across the next 5 closes."
    )
    return "\n".join(parts)


def _write_topic_notes(topic_id: str, notes: str) -> None:
    """In-place update of resolution_notes for a still-open topic."""
    if not notes:
        return
    if not TOPICS_FILE.exists():
        return
    try:
        raw = json.loads(TOPICS_FILE.read_text())
        if not isinstance(raw, list):
            return
        changed = False
        for t in raw:
            if t.get("topic_id") == topic_id:
                # Append rather than overwrite so multiple deep-dives stack.
                existing = (t.get("resolution_notes") or "").strip()
                merged = (existing + "\n\n" + notes).strip() if existing else notes
                t["resolution_notes"] = merged
                t["deepdive_at_iso"] = _now_iso()
                changed = True
                break
        if changed:
            TOPICS_FILE.write_text(json.dumps(raw, indent=2))
            log.info("[DEEPDIVE] wrote notes for %s (%d chars)", topic_id, len(notes))
    except Exception as e:
        log.debug("[DEEPDIVE] _write_topic_notes failed: %s", e)


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
    topic_id: str,
    *,
    resolution_notes: str = "",
    dismiss: bool = False,
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


async def brief_context_packet(*, max_strategies: int = 5, max_topics: int = 5) -> str:
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
                if s and r.get("computed_at_iso", "") > latest_by_strat.get(s, {}).get(
                    "computed_at_iso", ""
                ):
                    latest_by_strat[s] = r
            if latest_by_strat:
                lines.append("=== STRATEGY LEARN (top predictors from closed paper trades) ===")
                for strat, attr in list(latest_by_strat.items())[:max_strategies]:
                    pos = attr.get("top_positive") or []
                    neg = attr.get("top_negative") or []
                    lines.append(
                        f"  [{strat}] n={attr['n']} overall hit " f"{attr['overall_hit_rate']:.0%}"
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
                    f"  - {t['title']} (n_losses={t['n_losses']}, " f"avgR {t['avg_R']:+.2f})"
                )
            lines.append("")
    except Exception as e:
        log.debug("[SR-PACKET] research topics unavailable: %s", e)

    # Wave 14N N1 — yesterday's profit-ladder fires
    try:
        from .profit_ladder import ladder_summary

        ladder = await ladder_summary()
        recent = ladder.get("recent_10_emissions") or []
        if recent:
            lines.append("=== PROFIT LADDER ACTIVITY (last 10 fires) ===")
            lines.append(
                f"Threshold {ladder.get('r_threshold')}R, roll {ladder.get('profit_ratio'):.0%} "
                f"to {ladder.get('destination_recipe')}. "
                f"Total ever fired: {ladder.get('total_laddered_ever')}."
            )
            for r in recent[-3:]:
                lines.append(
                    f"  - {r.get('ticker')} {r.get('direction')} closed "
                    f"+{r.get('engine_r', 0):.2f}R (${r.get('realized_profit_usd', 0):.0f}) "
                    f"→ ladder ${r.get('ladder_R_dollars', 0):.0f} R into "
                    f"{r.get('destination_recipe')} {r.get('target_dte_min', 0)}-{r.get('target_dte_max', 0)}d"
                )
            lines.append("")
    except Exception as e:
        log.debug("[SR-PACKET] ladder unavailable: %s", e)

    # Wave 14N N1 — recent quant scanner activity
    try:
        from .quant_scanners import quant_scan_summary

        qsum = await quant_scan_summary()
        recent = qsum.get("recent_10_ticks") or []
        if recent:
            total_emitted = sum(t.get("total_ideas_emitted", 0) for t in recent)
            if total_emitted > 0:
                lines.append("=== QUANT SCANNER ACTIVITY (last 10 ticks) ===")
                lines.append(
                    f"7 scanners (mean_rev, pead, factor, pairs, whale_flow, "
                    f"crypto_carry, polymarket_kelly) emitted {total_emitted} "
                    f"trade ideas across recent ticks. Their ideas already "
                    f"flow through the auto-trader gate chain; mentioned here "
                    f"so brief executor knows the agent has independent "
                    f"signal sources beyond the brief itself."
                )
                # Most-recent tick scanner breakdown
                last_tick = recent[-1]
                scanners = last_tick.get("scanners") or {}
                summary_parts = []
                for name, s in scanners.items():
                    if isinstance(s, dict) and s.get("emitted", 0) > 0:
                        summary_parts.append(f"{name}={s['emitted']}")
                if summary_parts:
                    lines.append(f"  Last tick: {', '.join(summary_parts)}")
                lines.append("")
    except Exception as e:
        log.debug("[SR-PACKET] quant_scan unavailable: %s", e)

    # Wave 14N N1 — pro-active scout findings
    try:
        from .scout import scout_summary

        scout = await scout_summary()
        recent = scout.get("recent_10_ticks") or []
        if recent:
            # Aggregate counts across recent ticks
            pt = sum(t.get("profit_targets", {}).get("count", 0) for t in recent)
            rs = sum(t.get("regime_shifts", {}).get("count", 0) for t in recent)
            cc = sum(t.get("cc_opportunities", {}).get("count", 0) for t in recent)
            ed = sum(t.get("earnings_defensive", {}).get("count", 0) for t in recent)
            if any([pt, rs, cc, ed]):
                lines.append("=== SCOUT ACTIVITY (last 10 ticks aggregated) ===")
                lines.append("Pro-active 5-min scan of open positions + holdings:")
                if pt:
                    lines.append(f"  PROFIT-TARGET HITS: {pt} (consider closing/trailing)")
                if rs:
                    lines.append(f"  REGIME SHIFTS: {rs} (defensive close on demoted sectors)")
                if cc:
                    lines.append(
                        f"  COVERED-CALL OPPORTUNITIES: {cc} (premium harvest on holdings)"
                    )
                if ed:
                    lines.append(f"  EARNINGS DEFENSIVE FLAGS: {ed} (close/roll/hedge within 5d)")
                lines.append("")
    except Exception as e:
        log.debug("[SR-PACKET] scout unavailable: %s", e)

    # Wave 14N N1 — capability gaps (so the brief knows what data is missing)
    try:
        from .capability_registry import list_gaps

        gaps = await list_gaps()
        if gaps:
            lines.append("=== CAPABILITY GAPS (what the agent is currently missing) ===")
            lines.append(
                "These data sources/tools are unavailable today. The brief "
                "should acknowledge the gaps (e.g. 'no IVR data → don't gate "
                "options on IVR') and consider whether the operator can fix."
            )
            for g in gaps[:5]:
                lines.append(f"  - {g.get('name')}: {g.get('gap_reason', 'unknown')}")
            lines.append("")
    except Exception as e:
        log.debug("[SR-PACKET] capability gaps unavailable: %s", e)

    if not lines:
        return ""
    return "\n".join(lines)
