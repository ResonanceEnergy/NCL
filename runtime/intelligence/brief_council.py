"""Wave 14H — Morning Brief Pro: Council Research stage.

Runs nightly at 05:00 ET. Reads the NightWatch prep pack and runs a
Delphi-MAD style multi-LLM council where each member owns a domain. The
chair synthesizes member outputs into the brief envelope the presenter
will render.

Members:
    Macro Analyst       Claude Sonnet 4              macro + cross-asset + futures + VIX
    Real-Time Pulse     Grok 4 (or Sonnet fallback)  X/news sentiment + breaking events
    Flow Detective      Gemini 2.5 Pro (or Sonnet)   options flow + dark pool + GEX
    Technical Tactician GPT-5 (or Sonnet)            per-ticker setups + momentum
    Chair               Claude Opus 4 / Sonnet ext    synthesis + final brief
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ncl.intel.brief_council")

NCL_BASE = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
COUNCIL_DIR = NCL_BASE / "data" / "morning-brief-council"

# Wave 14X-2 (2026-05-29): real multi-provider council. The 4-Sonnet
# placeholder was 5× the cost with zero diversity (4 copies of the same
# brain debating itself). Now each member runs on a different model
# family so chair-resolved contradictions reflect real differences in
# training data + reasoning style, not random sampling noise.
#
# Provider routing in _anthropic_call/_xai_call/_openai_call (model
# prefix decides). Gemini slot is currently a 2nd GPT call (no Google
# key in .env) — Flow + Tech share OpenAI but with distinct prompts so
# the chair still sees flow-vs-tactics tension.
_MODEL_MACRO = "claude-opus-4-20250514"  # heavy macro reasoning
_MODEL_PULSE = "grok-4"                   # xAI — real-time sentiment, X/news
_MODEL_FLOW = "gemini-2.5-flash"          # Google — flow analysis (GOOGLE_API_KEY)
_MODEL_TECH = "gpt-4o"                    # OpenAI — chart setups
_MODEL_CHAIR = "claude-opus-4-20250514"  # heaviest synthesis

# How much of the prep pack each member sees (token budget per call).
_PACK_BUDGET_CHARS = 12000


# ─────────────────────────────────────────────────────────────────────────
# Member prompts — each one is a specialist with one job
# ─────────────────────────────────────────────────────────────────────────


def _macro_prompt(pack: dict) -> str:
    return f"""You are the MACRO ANALYST on NATRIX's morning brief council. Your job is to read the overnight macro picture and call the direction for today's open. Wave 14I adds capital rotation context — use it as a primary input alongside futures and VIX.

PREP PACK:
{json.dumps({
    "futures": pack.get("futures"),
    "vix_term_structure": pack.get("vix_term_structure"),
    "economic_calendar": pack.get("economic_calendar"),
    "polymarket_leading": pack.get("polymarket_leading"),
    "headlines": pack.get("headlines", [])[:15],
    "night_watch_summary": (pack.get("night_watch_summary") or "")[:2000],
    "rotation_snapshot": pack.get("rotation_snapshot"),
    "style_ratios": pack.get("style_ratios"),
    "cycle_phase": pack.get("cycle_phase"),
}, default=str)[:_PACK_BUDGET_CHARS]}

Today is {date.today().isoformat()}. Be specific. Cite signal IDs (sig_id field) when referencing news/polymarket items.

Output ONLY JSON:
{{
  "domain": "macro",
  "section_text": "3-5 sentences. Lead with concrete data point — futures level, VIX shape, dominant overnight headline. End with directional call (bullish/bearish/balanced).",
  "key_findings": [{{"text": "one sentence", "citations": ["sig_id"]}}],
  "direction_indicators": [
    {{"name": "ES futures", "level_to_watch": "above 4585 = bullish, below 4570 = risk-off", "current": "${{value}}"}},
    {{"name": "VIX term", "level_to_watch": "backwardation = stress, contango = calm", "current": "..."}},
    {{"name": "Sector leadership", "level_to_watch": "Leading sectors from RRG quadrant", "current": "..."}},
    {{"name": "Breadth", "level_to_watch": ">70 = broad, <30 = narrow", "current": "..."}},
    {{"name": "Cycle phase", "level_to_watch": "early/mid/late/recession", "current": "..."}}
  ],
  "rotation_regime": {{
    "current_phase": "early_expansion|mid_cycle|late_cycle|recession|mixed|unknown",
    "leading_sectors": ["XLE", "XLP", ...],
    "weakening_sectors": ["XLK", "XLY", ...],
    "breadth_pct": 64,
    "active_style_rotations": ["IWM/SPY rotating in (+1.2% 5d)", ...],
    "one_liner": "Late-cycle with defensives bidding; cyclicals rolling over"
  }},
  "trade_idea_seeds": [{{"ticker": "SYMBOL", "rationale": "...", "type": "stock|options|futures"}}],
  "watch_list": ["TICKER", ...],
  "confidence": 0.0-1.0
}}"""


def _pulse_prompt(pack: dict) -> str:
    return f"""You are the REAL-TIME PULSE on NATRIX's morning brief council. Your job is to surface what CHANGED overnight — breaking news, X chatter, geopolitical shifts, narrative movements.

PREP PACK:
{json.dumps({
    "headlines": pack.get("headlines", []),
    "polymarket_leading": pack.get("polymarket_leading", []),
    "overnight_movers": pack.get("overnight_movers", {}),
    "night_watch_summary": (pack.get("night_watch_summary") or "")[:1500],
}, default=str)[:_PACK_BUDGET_CHARS]}

Today is {date.today().isoformat()}. Focus on stories that are 0-12 hours old AND likely to move price today. Skip evergreen analysis.

Output ONLY JSON:
{{
  "domain": "pulse",
  "section_text": "2-3 sentences highlighting the top overnight narrative shift.",
  "breaking_developments": [{{"event": "...", "citations": ["sig_id"], "tickers_affected": ["..."]}}],
  "narrative_shifts": [{{"from": "...", "to": "...", "evidence": "..."}}],
  "watch_list": ["TICKER", ...],
  "confidence": 0.0-1.0
}}"""


def _flow_prompt(pack: dict) -> str:
    flow = pack.get("options_flow_yesterday", {})
    return f"""You are the FLOW DETECTIVE on NATRIX's morning brief council. Your job is to read where institutional money positioned overnight and yesterday — options flow, dark pool prints, GEX, unusual whales.

PREP PACK:
{json.dumps({
    "options_flow_yesterday_goat_top10": flow.get("goat", []),
    "options_flow_yesterday_bravo_top10": flow.get("bravo", []),
    "overnight_movers": pack.get("overnight_movers", {}),
    "futures": pack.get("futures"),
    "vix_term_structure": pack.get("vix_term_structure"),
}, default=str)[:_PACK_BUDGET_CHARS]}

Today is {date.today().isoformat()}. Be concrete about dollar amounts and call/put ratios. The reader is NATRIX — he trades individual names, not sectors.

Output ONLY JSON:
{{
  "domain": "flow",
  "section_text": "3-4 sentences on the dominant institutional positioning yesterday + the carry-over for today's open.",
  "institutional_positioning": [{{"ticker": "...", "thesis": "...", "evidence": "..."}}],
  "trade_idea_seeds": [{{"ticker": "...", "rationale": "...", "type": "stock|options"}}],
  "watch_list": ["TICKER", ...],
  "confidence": 0.0-1.0
}}"""


def _tech_prompt(pack: dict) -> str:
    return f"""You are the TECHNICAL TACTICIAN on NATRIX's morning brief council. Your job is to identify the best per-ticker setups for today's session — breakouts, momentum continuations, gap reactions, reversals.

PREP PACK:
{json.dumps({
    "overnight_movers": pack.get("overnight_movers", {}),
    "options_flow_yesterday_goat_top10": pack.get("options_flow_yesterday", {}).get("goat", []),
    "options_flow_yesterday_bravo_top10": pack.get("options_flow_yesterday", {}).get("bravo", []),
    "held_positions": pack.get("held_positions", []),
    "earnings_today": pack.get("earnings_today", []),
    "futures": pack.get("futures"),
}, default=str)[:_PACK_BUDGET_CHARS]}

Today is {date.today().isoformat()}. Give 4-6 tactical setups with entry / stop / target / timeframe. Mix stock and options. AT MOST ONE may be a sector/index ETF — prefer individual names.

Output ONLY JSON:
{{
  "domain": "technical",
  "section_text": "2-3 sentences on the dominant tactical theme.",
  "momentum_signals": [
    {{"category": "gap_up_>2pct_vol_1.5x", "tickers": ["..."]}},
    {{"category": "rvol_>3x", "tickers": ["..."]}},
    {{"category": "ORB_candidates", "tickers": ["..."]}}
  ],
  "trade_idea_seeds": [{{
      "ticker": "...", "type": "stock|options",
      "entry": "$X", "stop": "$Y", "target": "$Z", "timeframe": "...",
      "thesis": "..."
  }}],
  "watch_list": ["TICKER", ...],
  "confidence": 0.0-1.0
}}"""


def _chair_prompt(pack: dict, members: dict) -> str:
    return f"""You are the CHAIR of NATRIX's morning brief council. Four specialists have submitted findings. Your job is to synthesize them into the final brief and write the MARKET OPEN PLAN section that NATRIX reads first.

MEMBER OUTPUTS:
{json.dumps(members, default=str)[:18000]}

PREP CONTEXT (light):
{json.dumps({
    "futures": pack.get("futures"),
    "vix_term_structure": pack.get("vix_term_structure"),
    "economic_calendar": pack.get("economic_calendar"),
    "earnings_today": pack.get("earnings_today"),
    "yesterday_recap": pack.get("yesterday_recap"),
    "situational_context": pack.get("situational_context"),
}, default=str)[:4000]}

Today is {date.today().isoformat()}.

Synthesis rules:
1. Resolve contradictions between members. If macro is bullish but flow is bearish, call it out and lean on the one with better evidence.
2. Trade ideas: max 6 total, AT MOST 1 broad/sector ETF (SPY/QQQ/IWM/DIA/XLF/XLK/XLE/XLV/XLI/XLP/XLY/XLB/XLU/XLC/XLRE/GLD/SLV/USO/UNG/ARKK/SMH/SOXX). Rest must be individual stocks.
3. NO references to pre-2026 dates as forward catalysts. Today is 2026.
4. Each section text claim must include id= citations from member outputs.
5. The MARKET OPEN PLAN section is the flagship — make it sharp, actionable, scan-friendly.
6. ROTATION ALIGNMENT (Wave 14I rule 7d): If the rotation_snapshot in the prep pack identifies Leading sectors, your trade ideas should mostly lean WITH that leadership. If you include trade ideas in Weakening or Lagging sectors, label them as "counter-trend" in the thesis and explain why the catalyst overrides the regime. The Market Open Plan's rotation_regime field MUST reflect the actual current data — don't fabricate a leadership read.

Output ONLY JSON:
{{
  "yesterday_recap": {{
    "headline": "1-line summary — 'Yesterday auto-trader closed N: Xw / Yl for +R total. Top lesson: ...'",
    "scoreboard": {{
      "ideas_given": int_or_null,
      "closes": int,
      "winners": int,
      "losers": int,
      "scratches": int,
      "total_r": float
    }},
    "lesson": "short pattern observed — RVOL won / ETFs lagged / drift on bravo / etc",
    "drift_flags": ["bravo: DRIFT_DOWN since 5/27"]
  }},
  "market_open_plan": {{
    "what_to_watch": [
      {{"text": "08:30 ET — ${{event}}, consensus X, prior Y. Above Z = ${{reaction}}", "category": "macro_release|earnings|geopolitical|technical"}},
      ...
    ],
    "direction_indicators": [
      {{"name": "ES futures", "current_level": "...", "trigger": "above X = bullish, below Y = risk-off"}},
      {{"name": "VIX term structure", "current": "...", "interpretation": "..."}},
      ...
    ],
    "momentum_signals": {{
      "gap_up_watch": ["TICKER (+2.3% pre-mkt, vol 1.8x)"],
      "gap_down_reversal_candidates": [],
      "rvol_3x_list": [],
      "orb_candidates": []
    }},
    "risk_flags": [
      {{"text": "...", "severity": "low|med|high"}}
    ]
  }},
  "executive_summary": "string with id= citations, 2-3 sentences setting today's lead theme",
  "key_movements": [{{"text": "...", "citations": ["sig_id"]}}],
  "emerging_opportunities_and_risks": [{{"text": "...", "citations": ["sig_id"]}}],
  "trade_ideas": [{{
      "type": "stock|options|futures",
      "ticker": "...",
      "thesis": "...",
      "entry": "...", "stop": "...", "target": "...", "timeframe": "...",
      "structure": "..." (options only),
      "max_risk": "..." (options only),
      "sources": ["sig_id1", "sig_id2"]
  }}],
  "polymarket_watch": [{{"text": "...", "citations": ["sig_id"]}}],
  "today_research_topics": [{{"topic": "...", "why": "...", "investigate": "..."}}],
  "council_meta": {{
    "members_succeeded": ["macro", "pulse", "flow", "technical"],
    "contradictions_resolved": ["short string each"],
    "confidence": 0.0-1.0
  }}
}}"""


# ─────────────────────────────────────────────────────────────────────────
# Anthropic call helper — lazy-imported so module loads without anthropic
# ─────────────────────────────────────────────────────────────────────────


async def _anthropic_call(model: str, prompt: str, *, max_tokens: int = 3000,
                           timeout_s: float = 60.0, api_key: str = "",
                           label: str = "council") -> tuple[str, int, int]:
    """Call Anthropic Claude. Returns (text, input_tokens, output_tokens)."""
    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    import httpx
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            json=payload, headers=headers,
        )
        r.raise_for_status()
        body = r.json()
    text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
    usage = body.get("usage", {})
    in_tok = int(usage.get("input_tokens", 0))
    out_tok = int(usage.get("output_tokens", 0))
    log.info("[council/%s] %s in=%d out=%d", label, model, in_tok, out_tok)
    return text, in_tok, out_tok


# Wave 14X-2 — xAI (Grok) + OpenAI (GPT) call helpers. Both use the
# OpenAI-compatible chat-completions schema so the body shape is shared.
async def _xai_call(model: str, prompt: str, *, max_tokens: int = 3000,
                     timeout_s: float = 60.0, label: str = "council") -> tuple[str, int, int]:
    """Call xAI (Grok). Same schema as OpenAI chat-completions."""
    api_key = os.environ.get("XAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("XAI_API_KEY not set")
    import httpx
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post(
            "https://api.x.ai/v1/chat/completions",
            json=payload, headers=headers,
        )
        r.raise_for_status()
        body = r.json()
    text = (body.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    usage = body.get("usage", {})
    in_tok = int(usage.get("prompt_tokens", 0))
    out_tok = int(usage.get("completion_tokens", 0))
    log.info("[council/%s] %s in=%d out=%d", label, model, in_tok, out_tok)
    return text, in_tok, out_tok


async def _openai_call(model: str, prompt: str, *, max_tokens: int = 3000,
                        timeout_s: float = 60.0, label: str = "council") -> tuple[str, int, int]:
    """Call OpenAI chat-completions."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    import httpx
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            json=payload, headers=headers,
        )
        r.raise_for_status()
        body = r.json()
    text = (body.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    usage = body.get("usage", {})
    in_tok = int(usage.get("prompt_tokens", 0))
    out_tok = int(usage.get("completion_tokens", 0))
    log.info("[council/%s] %s in=%d out=%d", label, model, in_tok, out_tok)
    return text, in_tok, out_tok


async def _gemini_call(model: str, prompt: str, *, max_tokens: int = 3000,
                        timeout_s: float = 60.0, label: str = "council") -> tuple[str, int, int]:
    """Call Google Gemini via generativeLanguage REST."""
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    import httpx
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    headers = {"Content-Type": "application/json"}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post(url, json=payload, headers=headers,
                              params={"key": api_key})
        r.raise_for_status()
        body = r.json()
    # Extract text from first candidate
    text = ""
    cands = body.get("candidates") or []
    if cands:
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
    usage = body.get("usageMetadata", {})
    in_tok = int(usage.get("promptTokenCount", 0))
    out_tok = int(usage.get("candidatesTokenCount", 0))
    log.info("[council/%s] %s in=%d out=%d", label, model, in_tok, out_tok)
    return text, in_tok, out_tok


async def _dispatch_call(model: str, prompt: str, *, max_tokens: int = 3000,
                          timeout_s: float = 60.0, api_key: str = "",
                          label: str = "council") -> tuple[str, int, int]:
    """Wave 14X-2: route by model-name prefix. All 4 providers live."""
    m = (model or "").lower()
    if m.startswith("claude-"):
        return await _anthropic_call(
            model, prompt, max_tokens=max_tokens, timeout_s=timeout_s,
            api_key=api_key, label=label,
        )
    if m.startswith("grok-"):
        return await _xai_call(
            model, prompt, max_tokens=max_tokens, timeout_s=timeout_s, label=label,
        )
    if m.startswith("gpt-"):
        return await _openai_call(
            model, prompt, max_tokens=max_tokens, timeout_s=timeout_s, label=label,
        )
    if m.startswith("gemini-"):
        return await _gemini_call(
            model, prompt, max_tokens=max_tokens, timeout_s=timeout_s, label=label,
        )
    raise RuntimeError(f"unknown model provider for: {model!r}")


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM response."""
    import re
    text = text.strip()
    # Strip markdown fences
    text = re.sub(r"^```(json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    # Find first { ... } block
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    start = -1
                    continue
    raise ValueError(f"no JSON object in response: {text[:200]}")


# ─────────────────────────────────────────────────────────────────────────
# Member runners + chair synthesis
# ─────────────────────────────────────────────────────────────────────────


async def _run_member(name: str, prompt_fn, model: str, pack: dict,
                       api_key: str) -> Optional[dict]:
    """Run one council member. Returns None on failure (chair handles)."""
    try:
        prompt = prompt_fn(pack)
        text, _, _ = await _dispatch_call(
            model, prompt, max_tokens=2200, timeout_s=45.0,
            api_key=api_key, label=name,
        )
        return _extract_json(text)
    except Exception as e:
        log.warning("[council/%s] member failed: %s", name, e)
        return None


async def run_council(pack: dict, api_key: str = "") -> dict:
    """Run all 4 members in parallel, then the chair. Returns synthesis dict."""
    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    started = time.time()

    # Members in parallel
    macro, pulse, flow, tech = await asyncio.gather(
        _run_member("macro", _macro_prompt, _MODEL_MACRO, pack, api_key),
        _run_member("pulse", _pulse_prompt, _MODEL_PULSE, pack, api_key),
        _run_member("flow", _flow_prompt, _MODEL_FLOW, pack, api_key),
        _run_member("technical", _tech_prompt, _MODEL_TECH, pack, api_key),
    )
    members_succeeded = [
        n for n, m in
        (("macro", macro), ("pulse", pulse), ("flow", flow), ("technical", tech))
        if m is not None
    ]
    members = {
        "macro": macro or {"_failed": True},
        "pulse": pulse or {"_failed": True},
        "flow": flow or {"_failed": True},
        "technical": tech or {"_failed": True},
    }

    if not members_succeeded:
        raise RuntimeError("all council members failed")

    # Chair synthesis
    chair_text, chair_in, chair_out = await _dispatch_call(
        _MODEL_CHAIR, _chair_prompt(pack, members),
        max_tokens=4000, timeout_s=90.0, api_key=api_key, label="chair",
    )
    synthesis = _extract_json(chair_text)
    synthesis["_meta"] = {
        "members_succeeded": members_succeeded,
        "elapsed_s": round(time.time() - started, 1),
        "chair_in_tokens": chair_in,
        "chair_out_tokens": chair_out,
    }
    # Persist
    COUNCIL_DIR.mkdir(parents=True, exist_ok=True)
    out_path = COUNCIL_DIR / f"{date.today().isoformat()}.json"
    try:
        out_path.write_text(json.dumps({
            "members": members,
            "synthesis": synthesis,
            "prep_date": pack.get("date"),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2, default=str))
    except Exception as e:
        log.warning("[council] persist failed: %s", e)
    return synthesis


def load_latest_council() -> Optional[dict]:
    """Return today's council output if it exists."""
    today = date.today().isoformat()
    path = COUNCIL_DIR / f"{today}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


__all__ = ["run_council", "load_latest_council", "COUNCIL_DIR"]
