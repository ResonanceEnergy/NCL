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
from typing import Any

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

1. mode — overall edge in today's data
   - "full": rich, multi-source data, real actionable themes → full brief
   - "short": some data but thin / one-source dominated → 3-section abbreviated brief
   - "no-edge": data is empty or noise-dominated → ship a single-line quiet-day note

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

Output ONLY valid JSON matching this shape:

{{
  "mode": "full" | "short" | "no-edge",
  "themes": ["string", ...],
  "active_lanes": ["string", ...],
  "skipped_lanes": ["string", ...],
  "focus_tickers": ["string", ...],
  "include_sections": ["string", ...],
  "portfolio_alerts": [{{"ticker": "string", "concern": "string"}}],
  "research_topic_seeds": [{{"topic": "string", "why": "string"}}]
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

7. Avoid tickers in held_tickers as NEW entries — label them ADD TO EXISTING in thesis if you want to recommend adding.

8. macro_landscape: keys are the lane names from active_lanes ONLY. No "Signals quiet" stubs.

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
      "entry"?: "string",
      "stop"?: "string",
      "target": "string",
      "timeframe"?: "string",
      "structure"?: "string",
      "max_risk"?: "string",
      "contract"?: "string",
      "level_to_watch"?: "string",
      "direction"?: "string",
      "sources": ["signal_id", ...]
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


def _local_critique(executor_out: dict, valid_ids: set[str]) -> dict:
    """Pure-Python critic — runs first, cheap, deterministic.

    Returns critic-shape dict. If this passes cleanly we skip the LLM
    critic entirely (saves $0.0005 and ~3s). If this flags issues we
    surface them as the critic result without the LLM call.
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
    for i, idea in enumerate(executor_out.get("trade_ideas", []) or []):
        sources = idea.get("sources", []) or []
        if not sources:
            reasons.append(f"trade_ideas[{i}] missing sources")
            failed_sections.add("trade_ideas")

    # 4) Required-section presence
    if not executor_out.get("executive_summary"):
        reasons.append("missing executive_summary")
        failed_sections.add("executive_summary")

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


async def _critic_stage(executor_out: dict, valid_ids: set[str], api_key: str) -> dict:
    """Run local critic first; only escalate to LLM if local passes.

    The LLM critic does a second, semantic-level pass for things the
    regex can't catch (e.g. claims unsupported by their cited signal).
    """
    local = _local_critique(executor_out, valid_ids)
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
    stages.append("executor")

    # CRITIQUE — local critic is free; LLM critic is gated separately
    # inside _critic_stage so the pipeline can always ship a critique.
    valid_ids = set()
    for s in brief.top_signals:
        sid = getattr(s, "signal_id", "") or ""
        if sid:
            valid_ids.add(sid)

    critic = await _critic_stage(executor_out, valid_ids, api_key)
    stages.append("critic")

    regenerated = False
    if not critic.get("ship", True) and critic.get("fixable", False):
        try:
            if await check_budget("anthropic", _BUDGET_REGEN):
                executor_out = await _regenerate_stage(
                    executor_out, critic, plan, slices, held_tickers, api_key,
                )
                stages.append("regenerator")
                # Re-critique after regen (local-only, cheap)
                critic = _local_critique(executor_out, valid_ids)
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
