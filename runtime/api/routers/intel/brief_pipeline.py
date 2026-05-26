"""Morning-brief multi-stage pipeline — Wave 14D (2026-05-25).

Per docs/MORNING_BRIEF_QUALITY_2026-05-25.md Phase B. Replaces the single
mega-prompt with a planner → executor → critic → conditional-regenerate
chain that yields verifiable, citation-grounded briefs at cost-neutral
spend.

Pipeline
========

1. PLANNER (Sonnet 4, ~300 tokens, JSON-out)
   Receives a CONDENSED signal summary (per-source counts + top-3 by
   importance per source). Decides:
     - mode: full / short / no-edge
     - which macro lanes have real signal vs which to skip
     - which sections to include / omit
     - which tickers the brief should center on
     - portfolio alerts that need immediate-action treatment
     - seed research topics
   Mode = "no-edge" short-circuits the pipeline to a 200-char
   "quiet day" brief; no executor call, ~$0.001 total.

2. EXECUTOR (Sonnet 4 extended thinking, ~3500 tokens, JSON-out)
   Receives plan + filtered signal data per active_lanes. Produces
   structured JSON where every section carries text + citations:
   list[signal_id]. Trade ideas have explicit sources: list[signal_id].

3. CRITIC (Haiku 4.5, ~200 tokens, JSON-out)
   Mechanical validation against the executor output + valid signal_id
   set:
     - every trade idea has ≥1 valid (non-fabricated) signal_id cite
     - no markdown leaks
     - no empty text fields
     - no "quiet" / "unavailable" / "Signals quiet" stubs
   Returns {ship, score, fixable, sections_to_regen, reasons}.

4. REGENERATE (conditional, Sonnet 4, capped at 1)
   If critic.ship is False and critic.fixable: re-runs the executor
   for ONLY the failed sections with critic notes injected. One
   cycle max so cost stays bounded.

5. RENDERER
   Converts the final JSON to the plain-text format the iOS
   BriefRenderer already parses — no iOS changes required for v1.

Cost model (per brief, USD)
---------------------------
  Planner   : ~$0.001
  Executor  : ~$0.040  (~3500 out × $15/1M + ~3000 in × $3/1M)
  Critic    : ~$0.0005
  Regenerate: ~$0.012  (50% trigger rate × ~$0.025 per regen)
  TOTAL     : ~$0.045 typical, ~$0.054 worst case
  vs Phase A: ~$0.050 (single Sonnet pass) — pipeline is cheaper.

All stages share the same anthropic budget gate. If the budget is
exhausted mid-pipeline, partial brief is rendered with a degraded
flag. Caller (handler in __init__.py) falls back to the Phase A
single-pass path on any unrecoverable exception.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

log = logging.getLogger(__name__)

# Models — kept here as constants so they can be overridden via env
# without touching the call sites.
_MODEL_PLANNER = os.getenv("NCL_BRIEF_PLANNER_MODEL", "claude-sonnet-4-20250514")
_MODEL_EXECUTOR = os.getenv("NCL_BRIEF_EXECUTOR_MODEL", "claude-sonnet-4-20250514")
_MODEL_CRITIC = os.getenv("NCL_BRIEF_CRITIC_MODEL", "claude-haiku-4-5-20251001")

# Budget gates — pre-call check, falls through to fallback on exhaust
_BUDGET_PLANNER = float(os.getenv("NCL_BRIEF_BUDGET_PLANNER", "0.002"))
_BUDGET_EXECUTOR = float(os.getenv("NCL_BRIEF_BUDGET_EXECUTOR", "0.04"))
_BUDGET_CRITIC = float(os.getenv("NCL_BRIEF_BUDGET_CRITIC", "0.001"))
_BUDGET_REGEN = float(os.getenv("NCL_BRIEF_BUDGET_REGEN", "0.015"))

# Anthropic API base
_ANTHROPIC_BASE = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"

# Pricing for cost tracking (USD per 1M tokens). Sonnet 4 = 3/15,
# Haiku 4.5 = 1/5 per Anthropic published rates.
_PRICES_PER_M = {
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "claude-opus-4-20250514": (15.0, 75.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}


# ════════════════════════════════════════════════════════════════════════════
# Schema definitions (documented as comments — JSON Schema would be nice but
# Anthropic's tool-use is the validation surface, not strict schemas here)
# ════════════════════════════════════════════════════════════════════════════
#
# Planner output:
#   {
#     "mode": "full" | "short" | "no-edge",
#     "themes": [str],
#     "active_lanes": [str],          # subset of MACRO_LANES
#     "skipped_lanes": [str],
#     "focus_tickers": [str],
#     "include_sections": [str],      # subset of SECTION_NAMES
#     "portfolio_alerts": [{"ticker": str, "concern": str}],
#     "research_topic_seeds": [{"topic": str, "why": str}]
#   }
#
# Executor output (CitedText = {"text": str, "citations": [signal_id]}):
#   {
#     "immediate_action": [CitedText] | null,
#     "executive_summary": CitedText,
#     "portfolio_health": {
#       "looking_good": CitedText,
#       "needs_monitoring": CitedText,
#       "recommended_actions": CitedText
#     } | null,
#     "capital_flow": {
#       "institutional": CitedText, "retail_and_macro": CitedText
#     } | null,
#     "macro_landscape": {<LANE_NAME>: CitedText, ...},
#     "key_movements": [CitedText],
#     "emerging_opportunities_and_risks": [CitedText],
#     "scanner_readout": {"goat": CitedText|null, "bravo": CitedText|null} | null,
#     "trade_ideas": [{
#       "type": "stock"|"options"|"futures",
#       "ticker": str, "thesis": str,
#       "entry"?: str, "stop"?: str, "target": str, "timeframe"?: str,
#       "structure"?: str, "max_risk"?: str,
#       "contract"?: str, "level_to_watch"?: str, "direction"?: str,
#       "sources": [signal_id]
#     }],
#     "polymarket_watch": [CitedText] | null,
#     "top_movers": [{"ticker": str, "dir": str, "why": str, "catalyst": str}],
#     "research_topics": [{"topic": str, "why": str, "investigate": str}]
#   }
#
# Critic output:
#   {
#     "ship": bool, "score": int, "fixable": bool,
#     "sections_to_regen": [str], "reasons": [str]
#   }


MACRO_LANES = (
    "PRECIOUS METALS", "OIL", "US RATES (FED)", "BOND MARKET", "CRYPTO",
    "DAILY/WEEKLY OUTLOOK",
)

SECTION_NAMES = (
    "IMMEDIATE_ACTION", "EXECUTIVE_SUMMARY", "PORTFOLIO_HEALTH",
    "CAPITAL_FLOW", "MACRO_LANDSCAPE", "KEY_MOVEMENTS",
    "EMERGING_OPPORTUNITIES_AND_RISKS", "SCANNER_READOUT",
    "PRE_MARKET_TRADE_IDEAS", "POLYMARKET_WATCH",
    "TOP_POTENTIAL_DAILY_MOVERS", "TODAYS_RESEARCH_TOPICS",
)


# ════════════════════════════════════════════════════════════════════════════
# Anthropic call helper
# ════════════════════════════════════════════════════════════════════════════


async def _anthropic_call(
    model: str,
    prompt: str,
    *,
    max_tokens: int,
    timeout_s: float,
    api_key: str,
    label: str,
    extra_body: dict | None = None,
) -> tuple[str, int, int]:
    """One Anthropic Messages call. Returns (text, input_toks, output_toks).

    Raises on non-2xx or empty response. Caller decides how to handle
    failure (fall through to next stage, or bail entirely).
    """
    import httpx

    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if extra_body:
        body.update(extra_body)

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(
            _ANTHROPIC_BASE,
            headers={
                "x-api-key": api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
            },
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

    content_blocks = data.get("content", [])
    text = ""
    for block in content_blocks:
        if block.get("type") == "text":
            text = block.get("text", "")
            break
    if not text:
        raise RuntimeError(f"empty text response from {label}")

    usage = data.get("usage", {}) or {}
    in_toks = int(usage.get("input_tokens", 0))
    out_toks = int(usage.get("output_tokens", 0))

    # Track cost — non-fatal if cost_tracker missing
    try:
        from ....cost_tracker import record_cost

        rates = _PRICES_PER_M.get(model, (3.0, 15.0))
        cost = (in_toks * rates[0] + out_toks * rates[1]) / 1_000_000
        await record_cost("anthropic", cost, "intel_brief", f"{label} in={in_toks} out={out_toks}")
    except Exception:
        pass

    log.info(
        "[BRIEF-PIPELINE] %s — %s in=%d out=%d chars=%d",
        label, model, in_toks, out_toks, len(text),
    )
    return text, in_toks, out_toks


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict:
    """Extract the first balanced JSON object from a string. Tolerant of
    backtick fences and leading prose preamble.
    """
    cleaned = text.strip()
    # Strip markdown code fences first
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    # Find the largest braced span
    m = _JSON_BLOCK_RE.search(cleaned)
    if not m:
        raise ValueError(f"no JSON object in response (first 200 chars: {cleaned[:200]!r})")
    return json.loads(m.group(0))


# ════════════════════════════════════════════════════════════════════════════
# Stage 1 — PLANNER
# ════════════════════════════════════════════════════════════════════════════


def _condense_for_planner(brief, held_tickers: set[str]) -> dict:
    """Compress brief.top_signals into per-source counts + top-3 per source."""
    by_source: dict[str, list] = {}
    for s in brief.top_signals:
        src = getattr(s.source, "value", str(s.source)) or "unknown"
        by_source.setdefault(src, []).append(s)

    source_summary = []
    for src, sigs in sorted(by_source.items(), key=lambda kv: -len(kv[1])):
        top3 = sorted(sigs, key=lambda s: s.importance_score(), reverse=True)[:3]
        source_summary.append({
            "source": src,
            "count": len(sigs),
            "top3": [
                {
                    "id": (getattr(s, "signal_id", "") or "")[:8],
                    "title": (s.title or "")[:100],
                    "direction": s.direction.value,
                    "conf": round(s.confidence, 2),
                }
                for s in top3
            ],
        })

    return {
        "total_signals": len(brief.top_signals),
        "source_count": len(by_source),
        "sources": source_summary,
        "sectors": [
            {"sector": s.sector, "signals": s.signal_count, "direction": s.direction.value}
            for s in brief.sectors[:8]
        ],
        "held_tickers": sorted(held_tickers),
        "risk_alerts_count": len(brief.risk_alerts),
    }


async def _plan_stage(condensed: dict, api_key: str) -> dict:
    """Run the Planner. Returns plan dict or raises."""
    prompt = f"""You are the PLANNER for NATRIX's morning intelligence brief. Your job is to decide what should and should not appear in today's brief based on the signal data the scanner pipeline collected. You do NOT write the brief — a downstream writer does. Your output is a JSON plan.

SIGNAL FEED SUMMARY:
{json.dumps(condensed, indent=2, default=str)}

Decisions you must make:

1. mode — overall edge in today's data. DEFAULT to "full" — only downgrade if data is genuinely thin.
   - "full": ≥2 distinct sources active, options flow OR market data present, ≥30 total signals. This is the EXPECTED case for a market day; pick "full" by default.
   - "short": one-source dominated (e.g. only Reddit), OR <30 total signals, OR market is closed (weekend/holiday).
   - "no-edge": signal feed is empty or pure noise (almost never — only if every scanner failed today).
   With 100+ signals across 5+ sources, mode is "full" — do not pick "short" because individual sectors look quiet.
   STRICT THRESHOLD (Wave 14G P17-C): if total_signals_in_window > 300 AND distinct_sources >= 3, you MUST pick "full". A brief generated from ~1,000 signals is by definition a full-data day; "short" mode is reserved for genuinely thin slices.

2. themes — 1-4 short narrative themes (3-8 words each) the brief should organize around. Examples: "energy distribution divergence", "tech accumulation late-cycle", "fed-pause repricing", "crypto regulatory headlines".

3. active_lanes — macro lanes that have REAL signal in the data. Pick from:
   PRECIOUS METALS, OIL, US RATES (FED), BOND MARKET, CRYPTO, DAILY/WEEKLY OUTLOOK
   Only include a lane if you see evidence in the signal feed. Lanes with no evidence go to skipped_lanes.

4. skipped_lanes — the other lanes. Will be OMITTED from the brief (no stub line).

5. focus_tickers — 3-8 tickers the brief should center trade ideas around. Prefer tickers with multiple signal hits or large dollar values. Exclude tickers already in held_tickers unless they have fresh news.

6. include_sections — which sections of the brief to render. Choose subset of:
   IMMEDIATE_ACTION (only if held_tickers has positions with imminent concerns)
   EXECUTIVE_SUMMARY (always include)
   PORTFOLIO_HEALTH (only if held_tickers is non-empty)
   CAPITAL_FLOW (only if institutional flow data is present)
   MACRO_LANDSCAPE (only if active_lanes is non-empty)
   KEY_MOVEMENTS (always include)
   EMERGING_OPPORTUNITIES_AND_RISKS (always include unless mode=no-edge)
   SCANNER_READOUT (only if scanner:goat or scanner:bravo sources present)
   PRE_MARKET_TRADE_IDEAS (always include unless mode=no-edge)
   POLYMARKET_WATCH (only if polymarket source is present with >5 signals)
   TOP_POTENTIAL_DAILY_MOVERS (always include unless mode=no-edge)
   TODAYS_RESEARCH_TOPICS (always include)

7. portfolio_alerts — for held_tickers showing concerning signals (sector against, near stop, concentration risk). [{{ticker, concern}}] or [].

8. research_topic_seeds — 1-5 seed topics the executor will refine. {{topic, why}}.

9. trade_idea_count_target — explicit number of PRE-MARKET TRADE IDEAS the executor MUST emit. Map from mode + data:
   - mode=full + options flow data present → target = 6 (default for a normal market day)
   - mode=full + thin data → target = 4
   - mode=short → target = 4 (not 2 — even thin data should yield 4 honest setups)
   - mode=no-edge → target = 0 (and remove PRE_MARKET_TRADE_IDEAS from include_sections)
   When PRE_MARKET_TRADE_IDEAS is in include_sections, target MUST be >= 4. Trade ideas are the brief's most-used surface — NATRIX scans them pre-open to size positions. A brief with 2 ideas is functionally a brief with no ideas.

Output ONLY valid JSON matching this shape:

{{
  "mode": "full" | "short" | "no-edge",
  "themes": ["string", ...],
  "active_lanes": ["string", ...],
  "skipped_lanes": ["string", ...],
  "focus_tickers": ["string", ...],
  "include_sections": ["string", ...],
  "portfolio_alerts": [{{"ticker": "string", "concern": "string"}}],
  "research_topic_seeds": [{{"topic": "string", "why": "string"}}],
  "trade_idea_count_target": 0 | 2 | 4 | 6
}}

No preamble, no explanation, just the JSON object."""

    text, _, _ = await _anthropic_call(
        _MODEL_PLANNER, prompt,
        max_tokens=600, timeout_s=30.0, api_key=api_key, label="planner",
    )
    plan = _extract_json(text)
    # Defensive defaults
    plan.setdefault("mode", "full")
    plan.setdefault("themes", [])
    plan.setdefault("active_lanes", [])
    plan.setdefault("skipped_lanes", [])
    plan.setdefault("focus_tickers", [])
    plan.setdefault("include_sections", ["EXECUTIVE_SUMMARY", "KEY_MOVEMENTS"])
    plan.setdefault("portfolio_alerts", [])
    plan.setdefault("research_topic_seeds", [])
    # Default trade_idea_count_target — fall back to 4 if missing and the
    # section is included, 0 otherwise. Clamp to {0, 2, 4, 6}.
    raw_target = plan.get("trade_idea_count_target")
    if raw_target is None:
        raw_target = 4 if "PRE_MARKET_TRADE_IDEAS" in plan["include_sections"] else 0
    try:
        target = int(raw_target)
    except (TypeError, ValueError):
        target = 4
    plan["trade_idea_count_target"] = min(6, max(0, target))

    # Wave 14G P17-C — hard override: if signal volume is high, force "full"
    # mode regardless of what the LLM picked. Wave 14G P16 caught a brief
    # with 978 signals stuck in mode=short — the planner's heuristic was too
    # cautious. Threshold: > 300 signals + >= 3 distinct sources.
    try:
        sig_count = int(condensed.get("total_signals", 0))
        src_count = int(condensed.get("source_count", 0))
        if plan.get("mode") == "short" and sig_count > 300 and src_count >= 3:
            plan["mode"] = "full"
            # Bump trade_idea_count_target to match — full-mode default is 6.
            if plan.get("trade_idea_count_target", 0) < 6:
                plan["trade_idea_count_target"] = 6
            log.info(
                "[planner] P17-C override: mode short→full (signals=%d, sources=%d)",
                sig_count, src_count,
            )
    except Exception as e:
        log.debug("[planner] P17-C override skipped: %s", e)

    return plan


# ════════════════════════════════════════════════════════════════════════════
# Stage 2 — EXECUTOR
# ════════════════════════════════════════════════════════════════════════════


def _format_signal_for_executor(s) -> str:
    sid = (getattr(s, "signal_id", "") or "")[:8]
    src = getattr(s.source, "value", str(s.source)) or "?"
    title = (s.title or "")[:120]
    content = (s.content or "")[:200]
    direction = s.direction.value
    conf = s.confidence
    return f"- id={sid} [{src}] {title}: {content} (dir={direction}, conf={conf:.0%})"


def _filter_signals_for_executor(brief, plan: dict, lane_resolvers: dict) -> dict:
    """Bucket brief.top_signals into the slices the executor needs.

    `lane_resolvers` is a dict[lane_name -> callable(signal) -> bool] passed
    from the handler (re-uses the Phase A _lane helpers without import cycle).
    """
    focus_set = {t.upper() for t in plan.get("focus_tickers", [])}
    active_lanes = set(plan.get("active_lanes", []))

    out: dict[str, list] = {"macro_landscape": {}}

    out["top_signals"] = brief.top_signals[:12]
    out["sectors"] = brief.sectors[:8]
    out["risk_alerts"] = brief.risk_alerts[:5]

    # Per-lane slices (only for active lanes per plan)
    for lane, resolver in lane_resolvers.items():
        if lane in active_lanes:
            out["macro_landscape"][lane] = [s for s in brief.top_signals if resolver(s)][:6]

    # Focus-ticker slices for trade ideas
    if focus_set:
        out["focus_signals"] = [
            s for s in brief.top_signals
            if any(t in (s.title or "").upper() or t in (s.content or "").upper() for t in focus_set)
        ][:15]
    else:
        out["focus_signals"] = brief.top_signals[:15]

    return out


def _annotate_rotation_execution(executor_out: dict) -> None:
    """Wave 14J J3a/b/c — apply rotation pacing + breadth veto + stance
    tagging to each trade idea. Reads today's rotation snapshot and
    mutates each idea in-place to add:
        rotation_quadrant, rotation_stance, rotation_pacing,
        breadth_veto
    Non-fatal — silently skipped if rotation data isn't available."""
    ideas = executor_out.get("trade_ideas")
    if not isinstance(ideas, list):
        return
    try:
        from runtime.intelligence.rotation_tracker import load_latest_rotation
        from runtime.portfolio.rotation_execution import annotate_trade_idea
        snap = load_latest_rotation()
        if snap is None:
            return
        for idea in ideas:
            if isinstance(idea, dict):
                annotate_trade_idea(idea, rotation_snapshot=snap)
    except Exception as e:
        log.debug("[J3] rotation annotation skipped: %s", e)


def _stamp_trade_idea_ids(executor_out: dict) -> None:
    """Wave 14J J1c — every trade_idea gets a stable trade_idea_id so the
    J1d expectancy tracker can attribute outcomes. UUID4-derived hex, 16
    chars (collision-safe at NCL volume). Preserves any existing id so
    regenerated briefs keep continuity for ideas the regen kept verbatim.

    Also stamps `issued_at_iso` so the expectancy tracker can compute
    holding-period stats, and fire-and-forget registers each idea with
    the J1d tracker module.

    Mutates in-place. No-op on briefs without trade_ideas.
    """
    import uuid
    import asyncio as _asyncio
    from datetime import datetime, timezone

    ideas = executor_out.get("trade_ideas")
    if not isinstance(ideas, list):
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    for idea in ideas:
        if not isinstance(idea, dict):
            continue
        if not idea.get("trade_idea_id"):
            idea["trade_idea_id"] = uuid.uuid4().hex[:16]
        if not idea.get("issued_at_iso"):
            idea["issued_at_iso"] = now_iso
        # J1d: fire-and-forget emission registration. If we can't get
        # a running loop (e.g. called from a sync test path), skip
        # silently — the JSON output still carries the id for later
        # attribution.
        try:
            from runtime.portfolio.trade_idea_tracker import (
                record_trade_idea_emission,
            )
            # Map free-form ticker direction-like fields onto the tracker
            # schema. The brief emits descriptive strings ("entry" /
            # "stop" / "target") AND numeric counterparts ("entry_price"
            # / "stop_price" / "target_price"). Use the numeric ones.
            def _f(k):
                v = idea.get(k)
                try:
                    return float(v) if v is not None else None
                except (TypeError, ValueError):
                    return None

            # Strategy bucket via risk_governor normalization
            from runtime.portfolio.risk_governor import _normalize_strategy
            strat = _normalize_strategy(
                idea.get("strategy_tag") or idea.get("type") or "manual"
            )
            loop = _asyncio.get_running_loop()
            loop.create_task(
                record_trade_idea_emission(
                    source="brief",
                    strategy=strat,
                    ticker=str(idea.get("ticker") or "").upper(),
                    direction=idea.get("direction"),
                    entry_price=_f("entry_price"),
                    stop_price=_f("stop_price"),
                    target_price=_f("target_price"),
                    R_per_share=_f("R_per_share"),
                    planned_qty=_f("planned_qty"),
                    stop_type=idea.get("stop_type"),
                    stop_basis=idea.get("stop_basis"),
                    target_basis=idea.get("target_basis"),
                    thesis=idea.get("thesis"),
                    trade_idea_id=idea.get("trade_idea_id"),
                    metadata={
                        "type": idea.get("type"),
                        "sources": idea.get("sources") or [],
                    },
                )
            )
        except RuntimeError:
            # No running event loop — sync caller; silently skip.
            pass
        except Exception as _e:
            log.debug("[J1d] emission register skipped: %s", _e)


async def _execute_stage(
    plan: dict, slices: dict, held_tickers: set[str], api_key: str
) -> dict:
    """Run the Executor. Returns structured JSON brief body or raises."""

    # Build signal data block for the prompt
    def fmt_list(items):
        if not items:
            return "(none in this slice)"
        return "\n".join(_format_signal_for_executor(s) for s in items)

    top_block = fmt_list(slices["top_signals"])
    focus_block = fmt_list(slices["focus_signals"])
    sectors_block = "\n".join(
        f"- {s.sector}: {s.direction.value}, {s.signal_count} signals" for s in slices["sectors"]
    ) or "(none)"
    risks_block = "\n".join(f"- {r}" for r in slices["risk_alerts"]) or "(none)"

    macro_block_parts = []
    for lane in plan.get("active_lanes", []):
        sigs = slices["macro_landscape"].get(lane, [])
        macro_block_parts.append(f"LANE {lane}:\n{fmt_list(sigs)}")
    macro_block = "\n\n".join(macro_block_parts) or "(no active lanes)"

    held_str = ", ".join(sorted(held_tickers)) if held_tickers else "(no positions)"
    portfolio_alerts_str = json.dumps(plan.get("portfolio_alerts", []), default=str)

    include_sections = plan.get("include_sections", [])
    themes_str = "; ".join(plan.get("themes", [])) or "(no theme designated)"
    seeds_str = json.dumps(plan.get("research_topic_seeds", []), default=str)

    prompt = f"""You are the EXECUTOR for NATRIX's morning intelligence brief. A PLANNER stage has already analyzed the signal feed and decided what should and should not appear. Your job is to write the brief body as STRUCTURED JSON, with citation arrays linking every claim back to signal ids in the data feed.

PLAN FROM PLANNER:
- mode: {plan.get("mode")}
- themes: {themes_str}
- active_lanes: {plan.get("active_lanes")}
- focus_tickers: {plan.get("focus_tickers")}
- include_sections: {include_sections}
- portfolio_alerts: {portfolio_alerts_str}
- research_topic_seeds: {seeds_str}
- trade_idea_count_target: {plan.get("trade_idea_count_target", 4)}  (MUST emit this many trade ideas if section is included)

DATA FEED (signal id is the 8-char prefix; cite by this id):

TOP SIGNALS (12 highest-importance):
{top_block}

FOCUS TICKER SIGNALS (signals mentioning focus_tickers):
{focus_block}

MACRO LANE SIGNALS (only active lanes shown):
{macro_block}

SECTORS:
{sectors_block}

RISK ALERTS:
{risks_block}

HELD POSITIONS:
{held_str}

OUTPUT REQUIREMENTS — strict:

1. Output ONLY valid JSON. No markdown, no preamble, no commentary.

2. Include ONLY the sections in include_sections — omit the others entirely. If a section is omitted, set its JSON value to null. The renderer skips null sections.

3. Every section that contains a claim about a specific signal MUST cite at least one signal id from the data feed in its `citations` array. Trade ideas MUST cite at least one signal id in their `sources` array.

4. Use ONLY signal ids that appear in the data feed above. Do NOT invent ids. The Critic will reject any fabricated id.

5. Lead every text field with a concrete data point: ticker, dollar amount, percentage, named event, or dated catalyst. Avoid vague language like "mixed" / "varied" / "uncertain" / "watching".

6. For trade_ideas, each idea is an object with:
   - type: "stock", "options", or "futures"
   - ticker
   - thesis (1 sentence)
   - stock fields: entry, stop, target, timeframe
   - options fields: structure, max_risk, target
   - futures fields: contract, level_to_watch, direction
   - sources: [signal_id1, signal_id2, ...] — REQUIRED, ≥1 id

   WAVE 14J STOP FRAMEWORK (J1c) — every idea MUST also carry:
   - entry_price (number, $): the level at which to enter
   - stop_price (number, $): the hard stop level
   - stop_type (string): one of "price" (fixed $ level), "atr" (multiple
     of average true range), "volatility" (IV/realized-vol-derived),
     "time" (calendar exit if thesis hasn't worked by date X),
     "thesis_break" (exit on news invalidation, no price level)
   - stop_basis (string, 1 sentence): how the stop was chosen — e.g.
     "below 50d SMA at $X", "2x ATR(14) below 20d high", "if Q3
     guidance comes in below $Y consensus"
   - target_price (number, $): the level at which to take profit or
     re-evaluate
   - target_basis (string, 1 sentence): how the target was chosen
   - R_per_share (number, $): = |entry_price - stop_price|; the risk
     unit if 1 share is held. Risk governor multiplies this by an
     operator-set qty to produce R_dollars for the heat check
   - planned_qty (integer, optional): suggested share count or contract
     count if the idea has a natural unit (e.g. 1 condor, 100 shares,
     5 contracts). If omitted, downstream assumes 100 shares for
     equity ideas.

   Stop-type guidance: equity momentum (goat) → typically "atr" or
   "price"; swing setups (bravo) → "price" referencing structural
   support; options short-premium → "price" at the short strike or
   "thesis_break" on IV expansion; options long-premium → "time"
   (close at 21 DTE rule). Stops MUST be set at issue-time, never
   "TBD" or "decide on entry".

7. TRADE IDEAS QUOTA: if PRE_MARKET_TRADE_IDEAS is in include_sections, you MUST emit EXACTLY {plan.get("trade_idea_count_target", 4)} trade ideas (the planner set this target based on flow data quality). Each idea must cite ≥1 real signal_id. If you genuinely cannot ground that many setups in the data feed, omit the section entirely (set trade_ideas to []) — but the planner already gauged data sufficiency, so dropping below target should be rare. Mix types (some stock, some options, optionally one futures). Prefer focus_tickers but don't repeat the same ticker.

7a. INDIVIDUAL STOCKS OVER SECTOR ETFs: Of the trade ideas you emit, AT MOST ONE may be a broad-market or sector ETF (SPY, QQQ, IWM, DIA, VTI, VOO, VXX, TLT, IEF, XLF, XLK, XLE, XLV, XLI, XLP, XLY, XLB, XLU, XLC, XLRE, GLD, SLV, USO, UNG, ARKK, SMH, SOXX). The rest MUST be individual company stocks (e.g. NVDA, TSLA, AMZN, MSFT, GOOG, AAPL, META, AMD, COIN, PLTR — any named operating company). Sector ETFs are easy to source from options-flow signals but blunt the brief's tactical value — NATRIX trades individual names, not broad sectors. Only break this rule if the entire signal feed genuinely has zero individual-stock catalysts, in which case explain in the thesis why the ETF is the only viable read.

7b. DATE-RECENCY GUARD (Wave 14G P17-B): Today is 2026. Do NOT cite year 2025 or earlier as a forward catalyst. Phrases like "mid-2025 FDA catalyst", "by Q3 2025", "through 2024" describe events in the PAST — they are not actionable forward setups. If a signal feed item references such a date, either drop that claim, rephrase it as historical context, or reject the signal entirely. The Critic will fail any brief that frames a pre-2026 date as upcoming.

7c. POLYMARKET LIFECYCLE (Wave 14G P17-D): Each polymarket signal carries a metadata.lifecycle_status field — "active", "leading", or "resolved". Prefer "leading" markets (one outcome >= 60% probability) for capital-flow and emerging-opportunity references. Avoid citing "resolved" markets as forward catalysts (the event has already happened or expired). If you cite a polymarket signal, lead with the active leading outcome (e.g. "June 30 ceasefire extension at 78% YES") rather than the historical pessimism on an already-resolved earlier outcome.

8. Avoid tickers in held_tickers as NEW entries — label them ADD TO EXISTING in thesis if you want to recommend adding.

8a. SPY -> SPX SUBSTITUTION (Wave 14J J2d): If you propose an OPTIONS idea on SPY, QQQ, or IWM at >= 0.5R risk, ALSO emit an annotation in the thesis pointing out the SPX/NDX/RUT equivalent. SPX/NDX/RUT options qualify for Section 1256 60/40 tax treatment (60% long-term + 40% short-term, regardless of holding period) which cuts effective tax rate from ~37% (ordinary) to ~27% (blended) on identical economic exposure. This is a real opportunity for any premium-selling structure and shows up in thesis text as e.g. "SPX equivalent (1256 60/40 treatment) would be ~10x size at ~10x strike — same delta, better after-tax". Skip this annotation only for sub-0.5R sizes or for SPY/QQQ/IWM EQUITY ideas (stock trades), where 1256 doesn't apply.

9. macro_landscape: keys are the lane names from active_lanes ONLY. No "Signals quiet" stubs.

OUTPUT SHAPE (strict JSON):

{{
  "immediate_action": [{{"text": "string", "citations": ["signal_id"]}}] or null,
  "executive_summary": {{"text": "string", "citations": ["signal_id"]}},
  "portfolio_health": {{
    "looking_good": {{"text": "string", "citations": ["signal_id"]}},
    "needs_monitoring": {{"text": "string", "citations": ["signal_id"]}},
    "recommended_actions": {{"text": "string", "citations": ["signal_id"]}}
  }} or null,
  "capital_flow": {{
    "institutional": {{"text": "string", "citations": ["signal_id"]}},
    "retail_and_macro": {{"text": "string", "citations": ["signal_id"]}}
  }} or null,
  "macro_landscape": {{
    "<LANE NAME>": {{"text": "string", "citations": ["signal_id"]}},
    ...
  }},
  "key_movements": [{{"text": "string", "citations": ["signal_id"]}}, ...],
  "emerging_opportunities_and_risks": [{{"text": "string", "citations": ["signal_id"]}}, ...],
  "scanner_readout": {{
    "goat": {{"text": "string", "citations": ["signal_id"]}} or null,
    "bravo": {{"text": "string", "citations": ["signal_id"]}} or null
  }} or null,
  "trade_ideas": [
    {{
      "type": "stock"|"options"|"futures",
      "ticker": "string",
      "thesis": "string",
      "entry": "string"|null,
      "stop": "string"|null,
      "target": "string"|null,
      "timeframe"?: "string",
      "structure"?: "string",
      "max_risk"?: "string",
      "contract"?: "string",
      "level_to_watch"?: "string",
      "direction"?: "string",
      "sources": ["signal_id", ...],

      // Wave 14J stop framework (REQUIRED on every idea)
      "entry_price": <number>,
      "stop_price": <number>,
      "stop_type": "price"|"atr"|"volatility"|"time"|"thesis_break",
      "stop_basis": "string",
      "target_price": <number>,
      "target_basis": "string",
      "R_per_share": <number>,
      "planned_qty": <integer, optional>
    }}
  ],
  "polymarket_watch": [{{"text": "string", "citations": ["signal_id"]}}] or null,
  "top_movers": [
    {{"ticker": "string", "dir": "bullish"|"bearish"|"volatile", "why": "string", "catalyst": "string"}}
  ],
  "research_topics": [
    {{"topic": "string", "why": "string", "investigate": "string"}}
  ]
}}

Respond with ONLY the JSON object."""

    text, _, _ = await _anthropic_call(
        _MODEL_EXECUTOR, prompt,
        max_tokens=5000, timeout_s=150.0, api_key=api_key, label="executor",
    )
    return _extract_json(text)


# ════════════════════════════════════════════════════════════════════════════
# Stage 3 — CRITIC
# ════════════════════════════════════════════════════════════════════════════


def _collect_text_fields(node: Any, out: list[tuple[str, str]], path: str = "") -> None:
    """Walk the executor output, collecting (path, text) tuples."""
    if isinstance(node, dict):
        if "text" in node and isinstance(node["text"], str):
            out.append((path, node["text"]))
        for k, v in node.items():
            _collect_text_fields(v, out, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _collect_text_fields(item, out, f"{path}[{i}]")


def _collect_citations(node: Any, out: list[tuple[str, list[str]]], path: str = "") -> None:
    """Walk the executor output, collecting (path, [citation_id]) tuples."""
    if isinstance(node, dict):
        if "citations" in node and isinstance(node["citations"], list):
            out.append((path, [str(c) for c in node["citations"]]))
        if "sources" in node and isinstance(node["sources"], list):
            out.append((path, [str(c) for c in node["sources"]]))
        for k, v in node.items():
            _collect_citations(v, out, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _collect_citations(item, out, f"{path}[{i}]")


_STUB_PATTERNS = re.compile(
    r"\b(signals quiet|no actionable read|insufficient edge|unavailable|"
    r"snapshot unavailable|portfolio snapshot|polymarket quiet)\b",
    re.IGNORECASE,
)
_MD_PATTERN = re.compile(r"\*\*[^*\n]+?\*\*|`[^`\n]+`|^#{1,6}\s", re.MULTILINE)

# Wave 14G P17-E — price-claim extractor + 52-week range fetcher.
# Match `TICKER ... $NUMBER` where the NUMBER is a plain decimal price
# (NOT followed by M/K/B/million/billion/% which indicates volume,
# premium, market cap, or percentage). Filtered further in
# _extract_price_claims by context substring (rejects matches near
# 'premium', 'volume', 'flow', 'mcap', 'market cap', 'change_24h').
_PRICE_CLAIM_PATTERN = re.compile(
    r"\b([A-Z]{2,5})\b[^.$\n]{0,60}?\$(\d{1,5}(?:\.\d{1,2})?)"
    r"(?![MKB%])(?![,.]?\d)",
)
_PRICE_CLAIM_CONTEXT_BLOCKERS = (
    "premium", "volume", "flow", "mcap", "market cap", "vol:",
    "vol ", "imbalance", "open interest", "p/c ratio", "net option",
    "net call", "net put", "call flow", "put flow", "block trade",
    "in call", "in put", "in flow",
)
# Tickers excluded — too common as words / never quoted as a price
_PRICE_CLAIM_EXCLUDE = {
    "US", "USD", "EUR", "GBP", "JPY", "CNY", "RSI", "MACD", "OHLC",
    "FED", "FOMC", "API", "CPI", "PPI", "GDP", "NFP", "ATR", "VWAP",
    "TICKER", "TARGET", "ENTRY", "STOP", "MAX", "WHY", "TOPIC",
    "SOURCES", "STRUCTURE", "THESIS", "OPTIONS", "STOCK", "PLAY",
    "SETUP", "TIMEFRAME", "PRE", "POST",
}


def _extract_price_claims(texts: list[tuple[str, str]]) -> list[tuple[str, float]]:
    """Pull (ticker, claimed_price) tuples out of brief text fields."""
    seen: set[tuple[str, float]] = set()
    out: list[tuple[str, float]] = []
    for _path, txt in texts:
        for m in _PRICE_CLAIM_PATTERN.finditer(txt):
            sym = m.group(1)
            if sym in _PRICE_CLAIM_EXCLUDE or len(sym) < 2:
                continue
            try:
                px = float(m.group(2))
            except ValueError:
                continue
            if px <= 0 or px > 100_000:
                continue  # implausible
            # P17-F false-positive guard: skip if the matched span sits in
            # a premium/volume/flow context. Inspect the 80-char window
            # around the match for blocker substrings.
            span_lo = max(0, m.start() - 30)
            span_hi = min(len(txt), m.end() + 30)
            window = txt[span_lo:span_hi].lower()
            if any(b in window for b in _PRICE_CLAIM_CONTEXT_BLOCKERS):
                continue
            key = (sym, px)
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
    return out


_PRICE_RANGE_CACHE: dict[str, Optional[tuple[float, float]]] = {}


def _get_price_range_cache() -> dict[str, Optional[tuple[float, float]]]:
    """Return module-level cache. Cleared on Brain restart; that's fine."""
    return _PRICE_RANGE_CACHE


def _fetch_52w_range(symbol: str) -> Optional[tuple[float, float]]:
    """Best-effort 52-week (low, high) lookup via yfinance.

    Returns None on any failure (no yfinance, no network, unknown ticker,
    delisted, etc) — the critic treats None as 'skip this ticker'. We don't
    want a price lookup failure to block briefs.
    """
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        info = yf.Ticker(symbol).info or {}
        low = info.get("fiftyTwoWeekLow")
        high = info.get("fiftyTwoWeekHigh")
        if low and high and float(low) > 0 and float(high) > 0:
            return (float(low), float(high))
    except Exception:
        pass
    return None


def _local_critique(executor_out: dict, valid_ids: set[str], plan: dict | None = None) -> dict:
    """Pure-Python critic — runs first, cheap, deterministic.

    Returns critic-shape dict. If this passes cleanly we skip the LLM
    critic entirely (saves $0.0005 and ~3s). If this flags issues we
    surface them as the critic result without the LLM call.

    `plan` (optional) lets the critic enforce planner contracts that
    aren't visible from executor_out alone — e.g. trade_idea_count_target.
    """
    texts: list[tuple[str, str]] = []
    cites: list[tuple[str, list[str]]] = []
    _collect_text_fields(executor_out, texts)
    _collect_citations(executor_out, cites)

    reasons: list[str] = []
    failed_sections: set[str] = set()

    # 1) No markdown / stub phrases in any text field
    for path, txt in texts:
        if not txt.strip():
            reasons.append(f"empty text at {path}")
            failed_sections.add(path.split(".")[0])
        if _MD_PATTERN.search(txt):
            reasons.append(f"markdown in {path}")
            failed_sections.add(path.split(".")[0])
        if _STUB_PATTERNS.search(txt):
            reasons.append(f"stub phrase in {path}: {_STUB_PATTERNS.search(txt).group(0)!r}")
            failed_sections.add(path.split(".")[0])

    # 2) Every citation must be a real signal id (8-char prefix match)
    short_valid = {vid[:8] for vid in valid_ids if vid}
    for path, ids in cites:
        for cid in ids:
            cid_clean = cid.strip().strip(",.[]")[:8]
            if not cid_clean:
                continue
            if cid_clean not in short_valid:
                reasons.append(f"fabricated id {cid_clean!r} at {path}")
                failed_sections.add(path.split(".")[0])

    # 3) Every trade idea must have ≥1 source
    trade_ideas = executor_out.get("trade_ideas", []) or []
    for i, idea in enumerate(trade_ideas):
        sources = idea.get("sources", []) or []
        if not sources:
            reasons.append(f"trade_ideas[{i}] missing sources")
            failed_sections.add("trade_ideas")

    # 3a) Wave 14J J1c — Stop framework. Every trade idea MUST carry
    # entry_price + stop_price + stop_type + R_per_share + target_price.
    # An idea without a stop is an idea without risk control; the brief
    # should never ship one. stop_basis + target_basis are also required
    # (1-sentence justification each) — without those the operator can't
    # judge whether the level makes sense.
    _VALID_STOP_TYPES = {"price", "atr", "volatility", "time", "thesis_break"}
    for i, idea in enumerate(trade_ideas):
        missing = []
        for fld in ("entry_price", "stop_price", "stop_type", "target_price",
                    "stop_basis", "target_basis", "R_per_share"):
            v = idea.get(fld)
            if v is None or v == "":
                missing.append(fld)
        if missing:
            reasons.append(
                f"trade_ideas[{i}] ({idea.get('ticker', '?')}) missing J1c "
                f"stop-framework fields: {missing}"
            )
            failed_sections.add("trade_ideas")
            continue
        # Type/range sanity
        try:
            ep = float(idea["entry_price"])
            sp = float(idea["stop_price"])
            tp = float(idea["target_price"])
            rps = float(idea["R_per_share"])
            if ep <= 0 or sp <= 0 or tp <= 0:
                reasons.append(
                    f"trade_ideas[{i}] ({idea.get('ticker', '?')}) "
                    f"non-positive price (entry={ep}, stop={sp}, target={tp})"
                )
                failed_sections.add("trade_ideas")
                continue
            # R_per_share must equal |entry - stop| within 1¢ tolerance
            computed_R = abs(ep - sp)
            if abs(rps - computed_R) > 0.01:
                reasons.append(
                    f"trade_ideas[{i}] ({idea.get('ticker', '?')}) "
                    f"R_per_share {rps} != |entry {ep} - stop {sp}| = {computed_R:.4f}"
                )
                failed_sections.add("trade_ideas")
                continue
            # Direction sanity — for a LONG idea, target > entry > stop
            # For a SHORT idea, target < entry < stop. Detect direction
            # from explicit `direction` field if present, else assume
            # long if target > entry.
            direction = (idea.get("direction") or "").lower()
            if direction in ("long", "bullish") or (not direction and tp > ep):
                if not (sp < ep < tp):
                    reasons.append(
                        f"trade_ideas[{i}] ({idea.get('ticker', '?')}) "
                        f"long-side levels out of order: stop {sp} < entry {ep} < target {tp} expected"
                    )
                    failed_sections.add("trade_ideas")
                    continue
            elif direction in ("short", "bearish"):
                if not (tp < ep < sp):
                    reasons.append(
                        f"trade_ideas[{i}] ({idea.get('ticker', '?')}) "
                        f"short-side levels out of order: target {tp} < entry {ep} < stop {sp} expected"
                    )
                    failed_sections.add("trade_ideas")
                    continue
        except (TypeError, ValueError) as ex:
            reasons.append(
                f"trade_ideas[{i}] ({idea.get('ticker', '?')}) "
                f"price field not parseable: {ex}"
            )
            failed_sections.add("trade_ideas")
            continue
        # stop_type whitelist
        if idea.get("stop_type") not in _VALID_STOP_TYPES:
            reasons.append(
                f"trade_ideas[{i}] ({idea.get('ticker', '?')}) "
                f"invalid stop_type {idea.get('stop_type')!r}; "
                f"must be one of {sorted(_VALID_STOP_TYPES)}"
            )
            failed_sections.add("trade_ideas")

    # 4) Planner trade-idea quota — executor must meet target if section was included.
    # Allows up to 1-idea slack below target (executor can ship 3 if target was 4
    # and one would have been fabricated). Pre-iter the executor often shipped 0
    # trade ideas even when there was clear flow data; this guard catches that.
    if plan is not None and "PRE_MARKET_TRADE_IDEAS" in plan.get("include_sections", []):
        target = int(plan.get("trade_idea_count_target", 0) or 0)
        if target > 0 and len(trade_ideas) < max(2, target - 1):
            reasons.append(
                f"trade_ideas count {len(trade_ideas)} below planner target {target} "
                f"(min allowed {max(2, target - 1)})"
            )
            failed_sections.add("trade_ideas")

    # 5) Required-section presence
    if not executor_out.get("executive_summary"):
        reasons.append("missing executive_summary")
        failed_sections.add("executive_summary")

    # 6) Wave 14G P17-A — Rule 7a ETF-quota enforcement. At most one
    # broad-market / sector ETF allowed across all trade ideas. Stops
    # the executor from emitting SPY+IWM+XLF+XLU 4-ETF briefs that
    # don't match NATRIX's individual-stock trading style.
    _BROAD_ETFS = {
        "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "VXX", "TLT", "IEF",
        "XLF", "XLK", "XLE", "XLV", "XLI", "XLP", "XLY", "XLB", "XLU",
        "XLC", "XLRE", "GLD", "SLV", "USO", "UNG", "ARKK", "SMH", "SOXX",
    }
    if trade_ideas:
        etf_tickers = [
            (idea.get("ticker") or "").lstrip("$").upper()
            for idea in trade_ideas
        ]
        etf_count = sum(1 for t in etf_tickers if t in _BROAD_ETFS)
        if etf_count > 1:
            offenders = [t for t in etf_tickers if t in _BROAD_ETFS]
            reasons.append(
                f"trade_ideas has {etf_count} broad-ETF tickers "
                f"({', '.join(offenders)}); rule 7a allows at most 1"
            )
            failed_sections.add("trade_ideas")

    # 7) Wave 14G P17-B — Date-recency check. Today is 2026; any claim
    # citing year 2025 or earlier as a forward catalyst is stale data
    # being repackaged as a current opportunity. Flag the brief for
    # regeneration with a recency hint.
    _STALE_YEARS = ("2025", "2024", "2023", "2022", "2021", "2020")
    _texts: list[tuple[str, str]] = []
    _collect_text_fields(executor_out, _texts)
    for path, txt in _texts:
        for stale_year in _STALE_YEARS:
            if stale_year in txt:
                # Avoid false positives on things like "fiscal 2025
                # comparable" or "since 2021 average" — flag only when
                # the stale year appears alongside future-tense framing
                # like "by", "through", "upcoming", "mid-".
                low = txt.lower()
                if any(p in low for p in (
                    f"by {stale_year}", f"through {stale_year}",
                    f"upcoming {stale_year}", f"mid-{stale_year}",
                    f"mid {stale_year}", f"late {stale_year}",
                    f"early {stale_year}", f"q1 {stale_year}",
                    f"q2 {stale_year}", f"q3 {stale_year}",
                    f"q4 {stale_year}",
                )):
                    reasons.append(
                        f"stale-year reference '{stale_year}' framed as forward "
                        f"catalyst at {path}: '{txt[:120]}...'"
                    )
                    failed_sections.add(path.split(".")[0])
                    break

    # 8) Wave 14G P17-E — Price sanity-check. Extract ticker price claims
    # from the brief text (format: "TICKER at $X" / "$TICKER ... $X" /
    # "TICKER showing ... $X") and flag any that exceed the 52-week range
    # from a small yfinance lookup. Lazy cache to avoid repeated lookups
    # in one brief. Failure to fetch range is non-fatal — sanity check
    # skips that ticker rather than blocking the brief.
    try:
        _price_range_cache = _get_price_range_cache()
        _claims = _extract_price_claims(_texts)
        for sym, claimed_px in _claims[:20]:  # cap to first 20 to bound cost
            rng = _price_range_cache.get(sym)
            if rng is None:
                rng = _fetch_52w_range(sym)
                _price_range_cache[sym] = rng
            if rng is None:
                continue  # lookup failed — skip rather than reject
            low, high = rng
            # Allow 2% headroom for intraday movement / mid-quote variance
            slack = 0.02
            if claimed_px > high * (1 + slack) or claimed_px < low * (1 - slack):
                reasons.append(
                    f"price-sanity: {sym} claimed at ${claimed_px:.2f} outside "
                    f"52w range ${low:.2f}–${high:.2f}"
                )
                failed_sections.add("key_movements")
    except Exception as e:
        log.debug("[critic] price sanity check skipped: %s", e)

    ship = len(reasons) == 0
    score = max(0, 100 - len(reasons) * 8)
    return {
        "ship": ship,
        "score": score,
        "fixable": bool(failed_sections),
        "sections_to_regen": sorted(failed_sections),
        "reasons": reasons,
        "source": "local",
    }


async def _critic_stage(executor_out: dict, valid_ids: set[str], api_key: str, plan: dict | None = None) -> dict:
    """Run local critic first; only escalate to LLM if local passes.

    The LLM critic does a second, semantic-level pass for things the
    regex can't catch (e.g. claims unsupported by their cited signal).
    """
    local = _local_critique(executor_out, valid_ids, plan)
    if not local["ship"]:
        # Local already failed — return its findings without spending on LLM
        return local

    # Optional: LLM second pass. Gated by env so it can be turned off.
    if os.getenv("NCL_BRIEF_LLM_CRITIC", "0") != "1":
        return local

    # Compact view of executor output for the critic
    cited_claims = []
    texts: list[tuple[str, str]] = []
    _collect_text_fields(executor_out, texts)
    for path, txt in texts[:30]:  # cap to 30 to keep critic prompt short
        cited_claims.append({"section": path, "text": txt[:300]})

    prompt = f"""You are the CRITIC for NATRIX's morning brief. The local syntactic checks already passed (no markdown, no fabricated ids, all trade ideas have sources). Your job is the SEMANTIC pass — do the claims in each section actually match what the cited signals say?

Respond ONLY with JSON:
{{
  "ship": true | false,
  "score": 0-100,
  "fixable": true | false,
  "sections_to_regen": ["section_name", ...],
  "reasons": ["short reason string", ...]
}}

CLAIMS TO REVIEW:
{json.dumps(cited_claims, indent=2, default=str)[:4000]}

Be permissive — only fail if a claim is clearly contradicted by no plausible interpretation of the data. Don't fail for stylistic preferences."""

    try:
        text, _, _ = await _anthropic_call(
            _MODEL_CRITIC, prompt,
            max_tokens=400, timeout_s=20.0, api_key=api_key, label="critic-llm",
        )
        llm_result = _extract_json(text)
        llm_result.setdefault("source", "llm")
        # Combine: if either fails, brief fails
        if not llm_result.get("ship", True):
            return llm_result
    except Exception as exc:
        log.warning("[BRIEF-PIPELINE] LLM critic failed (using local result): %s", exc)

    return local


# ════════════════════════════════════════════════════════════════════════════
# Stage 4 — REGENERATE (conditional)
# ════════════════════════════════════════════════════════════════════════════


async def _regenerate_stage(
    executor_out: dict,
    critic: dict,
    plan: dict,
    slices: dict,
    held_tickers: set[str],
    api_key: str,
) -> dict:
    """Re-run executor with critic feedback injected.

    Capped at one regen. The simple v1 strategy is to re-run the FULL
    executor with the critic notes prepended — easier than per-section
    surgical patching, only marginally more expensive (~$0.025 vs $0.012),
    and avoids re-validating cross-section consistency.
    """
    log.info(
        "[BRIEF-PIPELINE] regenerating brief after critic rejection: %s reasons",
        len(critic.get("reasons", [])),
    )

    def fmt_list(items):
        return "\n".join(_format_signal_for_executor(s) for s in items) if items else "(none)"

    top_block = fmt_list(slices["top_signals"])
    focus_block = fmt_list(slices["focus_signals"])
    macro_block_parts = []
    for lane in plan.get("active_lanes", []):
        sigs = slices["macro_landscape"].get(lane, [])
        macro_block_parts.append(f"LANE {lane}:\n{fmt_list(sigs)}")
    macro_block = "\n\n".join(macro_block_parts) or "(no active lanes)"

    held_str = ", ".join(sorted(held_tickers)) if held_tickers else "(no positions)"

    prompt = f"""You are the EXECUTOR re-rolling a brief that the CRITIC rejected. Address every issue below and re-emit the FULL brief as valid JSON.

CRITIC FEEDBACK:
- ship: false
- sections_to_regen: {critic.get("sections_to_regen", [])}
- reasons:
{chr(10).join(f"  - {r}" for r in critic.get("reasons", [])[:20])}

PRIOR OUTPUT (use as a starting point, fix the issues):
{json.dumps(executor_out, indent=2, default=str)[:6000]}

DATA FEED (only these signal ids exist — do NOT invent new ones):
{top_block}

{focus_block}

MACRO:
{macro_block}

HELD: {held_str}
include_sections: {plan.get("include_sections")}
active_lanes: {plan.get("active_lanes")}

Re-emit the full executor JSON in the same shape. Fix every listed reason. No markdown, no preamble. Only the JSON object."""

    text, _, _ = await _anthropic_call(
        _MODEL_EXECUTOR, prompt,
        max_tokens=5000, timeout_s=150.0, api_key=api_key, label="executor-regen",
    )
    return _extract_json(text)


# ════════════════════════════════════════════════════════════════════════════
# Stage 5 — JSON → text renderer
# ════════════════════════════════════════════════════════════════════════════


def _cited(text: str, citations: list[str] | None) -> str:
    """Append (id=...) suffix if citations present."""
    if not citations:
        return text
    ids = [str(c).strip()[:8] for c in citations if c][:3]
    if not ids:
        return text
    return f"{text} (id={','.join(ids)})"


def render_brief_to_text(out: dict) -> str:
    """Convert the executor JSON to the plain-text format iOS BriefRenderer parses."""
    parts: list[str] = []

    # IMMEDIATE ACTION
    ia = out.get("immediate_action")
    if ia:
        parts.append("IMMEDIATE ACTION")
        for item in ia:
            txt = (item or {}).get("text", "").strip()
            if txt:
                parts.append(f"- {_cited(txt, (item or {}).get('citations'))}")
        parts.append("")

    # EXECUTIVE SUMMARY
    es = out.get("executive_summary") or {}
    if es.get("text"):
        parts.append("EXECUTIVE SUMMARY")
        parts.append(_cited(es["text"].strip(), es.get("citations")))
        parts.append("")

    # PORTFOLIO HEALTH
    ph = out.get("portfolio_health")
    if ph:
        parts.append("PORTFOLIO HEALTH")
        for label, key in (
            ("LOOKING GOOD", "looking_good"),
            ("NEEDS MONITORING", "needs_monitoring"),
            ("RECOMMENDED ADDS-TRIMS", "recommended_actions"),
        ):
            blk = ph.get(key) or {}
            if blk.get("text"):
                parts.append(f"{label}: {_cited(blk['text'].strip(), blk.get('citations'))}")
        parts.append("")

    # CAPITAL FLOW
    cf = out.get("capital_flow")
    if cf:
        parts.append("CAPITAL FLOW")
        for label, key in (
            ("INSTITUTIONAL", "institutional"),
            ("RETAIL_AND_MACRO", "retail_and_macro"),
        ):
            blk = cf.get(key) or {}
            if blk.get("text"):
                parts.append(f"{label}: {_cited(blk['text'].strip(), blk.get('citations'))}")
        parts.append("")

    # MACRO LANDSCAPE
    ml = out.get("macro_landscape") or {}
    if ml:
        parts.append("MACRO LANDSCAPE")
        for lane in MACRO_LANES:
            blk = ml.get(lane) or {}
            if blk.get("text"):
                parts.append(f"{lane}: {_cited(blk['text'].strip(), blk.get('citations'))}")
        parts.append("")

    # KEY MOVEMENTS
    km = out.get("key_movements") or []
    if km:
        parts.append("KEY MOVEMENTS")
        for item in km:
            blk = item or {}
            if blk.get("text"):
                parts.append(f"- {_cited(blk['text'].strip(), blk.get('citations'))}")
        parts.append("")

    # EMERGING
    em = out.get("emerging_opportunities_and_risks") or []
    if em:
        parts.append("EMERGING OPPORTUNITIES AND RISKS")
        for item in em:
            blk = item or {}
            if blk.get("text"):
                parts.append(_cited(blk["text"].strip(), blk.get("citations")))
                parts.append("")

    # SCANNER READOUT
    sr = out.get("scanner_readout") or {}
    if sr.get("goat") or sr.get("bravo"):
        parts.append("SCANNER READOUT")
        for label, key in (("GOAT", "goat"), ("BRAVO", "bravo")):
            blk = sr.get(key)
            if blk and blk.get("text"):
                parts.append(f"{label}: {_cited(blk['text'].strip(), blk.get('citations'))}")
        parts.append("")

    # PRE-MARKET TRADE IDEAS
    ideas = out.get("trade_ideas") or []
    if ideas:
        parts.append("PRE-MARKET TRADE IDEAS")
        stock_n = options_n = futures_n = 0
        for idea in ideas:
            kind = (idea.get("type") or "stock").lower()
            sources = idea.get("sources") or []
            src_line = "SOURCES: " + ", ".join(str(s).strip()[:8] for s in sources[:5]) if sources else ""

            if kind == "stock":
                stock_n += 1
                parts.append(f"STOCK SETUP {stock_n}")
                parts.append(f"TICKER: {idea.get('ticker', '?')}")
                parts.append(f"THESIS: {idea.get('thesis', '')}")
                if idea.get("entry"):
                    parts.append(f"ENTRY: {idea['entry']}")
                if idea.get("stop"):
                    parts.append(f"STOP: {idea['stop']}")
                if idea.get("target"):
                    parts.append(f"TARGET: {idea['target']}")
                if idea.get("timeframe"):
                    parts.append(f"TIMEFRAME: {idea['timeframe']}")
            elif kind == "options":
                options_n += 1
                parts.append(f"OPTIONS PLAY {options_n}")
                parts.append(f"TICKER: {idea.get('ticker', '?')}")
                if idea.get("structure"):
                    parts.append(f"STRUCTURE: {idea['structure']}")
                parts.append(f"THESIS: {idea.get('thesis', '')}")
                if idea.get("max_risk"):
                    parts.append(f"MAX RISK: {idea['max_risk']}")
                if idea.get("target"):
                    parts.append(f"TARGET: {idea['target']}")
            elif kind == "futures":
                futures_n += 1
                parts.append("FUTURES ANGLE")
                if idea.get("contract"):
                    parts.append(f"CONTRACT: {idea['contract']}")
                parts.append(f"THESIS: {idea.get('thesis', '')}")
                if idea.get("level_to_watch"):
                    parts.append(f"LEVEL TO WATCH: {idea['level_to_watch']}")
                if idea.get("direction"):
                    parts.append(f"DIRECTION: {idea['direction']}")
            if src_line:
                parts.append(src_line)
            parts.append("")

    # POLYMARKET WATCH
    pw = out.get("polymarket_watch") or []
    if pw:
        parts.append("POLYMARKET WATCH")
        for item in pw:
            blk = item or {}
            if blk.get("text"):
                parts.append(f"- {_cited(blk['text'].strip(), blk.get('citations'))}")
        parts.append("")

    # TOP MOVERS
    movers = out.get("top_movers") or []
    if movers:
        parts.append("TOP POTENTIAL DAILY MOVERS")
        for m in movers:
            tkr = m.get("ticker", "?")
            d = m.get("dir", "?")
            why = m.get("why", "")
            cat = m.get("catalyst", "")
            parts.append(f"- {tkr} (dir: {d}) — {why} — {cat}")
        parts.append("")

    # RESEARCH TOPICS
    rt = out.get("research_topics") or []
    if rt:
        parts.append("TODAY'S RESEARCH TOPICS")
        for t in rt:
            parts.append(f"TOPIC: {t.get('topic', '')}")
            parts.append(f"WHY: {t.get('why', '')}")
            parts.append(f"INVESTIGATE: {t.get('investigate', '')}")
            parts.append("")

    return "\n".join(parts).rstrip() + "\n"


# ════════════════════════════════════════════════════════════════════════════
# Public entry point
# ════════════════════════════════════════════════════════════════════════════


async def run_brief_pipeline(brief, held_tickers: set[str], api_key: str, lane_resolvers: dict) -> dict:
    """End-to-end pipeline: plan → execute → critique → (optional regen) → render.

    Returns dict:
      {
        "text": str,                       # text brief for iOS / persist
        "plan": dict,                      # planner output
        "executor_out": dict,              # final executor JSON (post-regen)
        "critic": dict,                    # final critic verdict
        "regenerated": bool,
        "stages_completed": list[str],
        "pipeline": "ok" | "partial" | "no-edge"
      }

    Raises if planner fails or executor never produces parseable output;
    caller falls back to Phase A single-pass.
    """
    from ....cost_tracker import check_budget

    stages: list[str] = []

    # Stage-by-stage budget gating: only the planner has to fit at entry.
    # The executor and critic each check themselves before firing, so the
    # pipeline degrades gracefully (planner-only short brief if executor
    # can't run; planner+executor unverified brief if critic can't run).
    # Pre-14D this required the full $0.043 chain budget upfront, which
    # was unnecessarily conservative — would fall back to Phase A on any
    # day with <$0.043 headroom even when Phase A's single $0.02 call
    # would have fit fine.
    if not await check_budget("anthropic", _BUDGET_PLANNER):
        raise RuntimeError("anthropic budget too low even for planner; caller should fall back")

    condensed = _condense_for_planner(brief, held_tickers)
    plan = await _plan_stage(condensed, api_key)
    stages.append("planner")

    if plan.get("mode") == "no-edge":
        text = (
            "EXECUTIVE SUMMARY\n"
            "Signal feed is quiet today — no actionable edge across the active scanners. "
            "Pipeline returned mode=no-edge after planner inspection.\n"
        )
        return {
            "text": text,
            "plan": plan,
            "executor_out": {"executive_summary": {"text": text, "citations": []}},
            "critic": {"ship": True, "score": 100, "source": "planner-shortcut"},
            "regenerated": False,
            "stages_completed": stages,
            "pipeline": "no-edge",
        }

    # EXECUTE — gate on its own budget; if exhausted, raise so caller
    # can fall back to Phase A (which is cheaper than executor alone).
    if not await check_budget("anthropic", _BUDGET_EXECUTOR):
        raise RuntimeError(
            "anthropic budget exhausted before executor stage; caller should fall back"
        )

    slices = _filter_signals_for_executor(brief, plan, lane_resolvers)
    executor_out = await _execute_stage(plan, slices, held_tickers, api_key)
    # Wave 14J J1c — stamp every trade_idea with a stable UUID so J1d
    # (per-strategy expectancy) can attribute outcomes back to the issue.
    _stamp_trade_idea_ids(executor_out)
    # Wave 14J J3a/b/c — annotate ideas with rotation pacing + breadth
    # veto + stance vs current rotation quadrants.
    _annotate_rotation_execution(executor_out)
    stages.append("executor")

    # CRITIQUE — local critic is free; LLM critic is gated separately
    # inside _critic_stage so the pipeline can always ship a critique.
    valid_ids = set()
    for s in brief.top_signals:
        sid = getattr(s, "signal_id", "") or ""
        if sid:
            valid_ids.add(sid)

    critic = await _critic_stage(executor_out, valid_ids, api_key, plan)
    stages.append("critic")

    regenerated = False
    if not critic.get("ship", True) and critic.get("fixable", False):
        try:
            if await check_budget("anthropic", _BUDGET_REGEN):
                executor_out = await _regenerate_stage(
                    executor_out, critic, plan, slices, held_tickers, api_key,
                )
                # Re-stamp after regen — regenerated ideas need their own
                # trade_idea_ids, but preserve any existing ones the
                # executor kept verbatim across the regen.
                _stamp_trade_idea_ids(executor_out)
                stages.append("regenerator")
                # Re-critique after regen (local-only, cheap)
                critic = _local_critique(executor_out, valid_ids, plan)
                regenerated = True
        except Exception as exc:
            log.warning("[BRIEF-PIPELINE] regenerate failed (shipping original): %s", exc)

    text = render_brief_to_text(executor_out)
    return {
        "text": text,
        "plan": plan,
        "executor_out": executor_out,
        "critic": critic,
        "regenerated": regenerated,
        "stages_completed": stages,
        "pipeline": "ok" if critic.get("ship") else "partial",
    }
