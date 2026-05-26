"""Wave 14H — Morning Brief Pro: Presentation stage.

Renders the chair's synthesis JSON into NATRIX's preferred plain-text
format with the new MARKET OPEN PLAN section pinned to the top.

The renderer is pure: no LLM calls. It takes the council synthesis dict
and produces:
  - a plain-text brief (back-compat with the iOS BriefRenderer)
  - a structured JSON envelope for API consumers
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional
import os

log = logging.getLogger("ncl.intel.brief_presenter")

NCL_BASE = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
PRO_BRIEF_DIR = NCL_BASE / "data" / "morning-brief-pro"


_MD_PATTERN = re.compile(r"\*\*([^*\n]+?)\*\*|`([^`\n]+)`|^#{1,6}\s+", re.MULTILINE)


def _strip_markdown(text: str) -> str:
    """Same strip pass used in Phase 14C — defangs **bold** + #headers + `code`."""
    if not text:
        return text

    def _repl(m):
        return m.group(1) or m.group(2) or ""

    return _MD_PATTERN.sub(_repl, text)


def _cite(citations) -> str:
    """Render a citation list as ' (id=a1b2,c3d4)'."""
    if not citations:
        return ""
    ids = [str(c)[:8] for c in citations if c]
    if not ids:
        return ""
    return f" (id={','.join(ids)})"


def render_pro_brief(synthesis: dict, pack: dict | None = None) -> dict:
    """Render the council synthesis into the brief envelope.

    Returns a dict with:
        text:                full plain-text brief (back-compat)
        market_open_plan:    structured object for iOS BriefRenderer
        executive_summary:   plain text (no markdown)
        ... all other fields from synthesis ...
        generated_at:        UTC ISO timestamp
        date:                YYYY-MM-DD
    """
    today = date.today().isoformat()
    now = datetime.now(timezone.utc).isoformat()

    parts: list[str] = []

    # ── HEADER ──
    parts.append(f"NCL MORNING BRIEF — {today}")
    parts.append(f"Generated: {now[:19]}Z")
    parts.append("")

    # ── MARKET OPEN PLAN (flagship section) ──
    mop = synthesis.get("market_open_plan") or {}
    if mop:
        parts.append("═══════════════════════════════════════════════════════")
        parts.append("MARKET OPEN PLAN")
        parts.append("═══════════════════════════════════════════════════════")
        parts.append("")

        wtw = mop.get("what_to_watch") or []
        if wtw:
            parts.append("── WHAT TO WATCH ──")
            for i, item in enumerate(wtw, 1):
                txt = _strip_markdown(item.get("text") or item if isinstance(item, dict) else str(item))
                parts.append(f"{i}. {txt}")
            parts.append("")

        di = mop.get("direction_indicators") or []
        if di:
            parts.append("── DIRECTION INDICATORS (read these at open) ──")
            for ind in di:
                if isinstance(ind, dict):
                    name = _strip_markdown(ind.get("name") or "")
                    curr = _strip_markdown(ind.get("current_level") or ind.get("current") or "")
                    trig = _strip_markdown(ind.get("trigger") or ind.get("interpretation") or "")
                    line = f"  • {name}"
                    if curr:
                        line += f" @ {curr}"
                    if trig:
                        line += f" — {trig}"
                    parts.append(line)
                else:
                    parts.append(f"  • {_strip_markdown(str(ind))}")
            parts.append("")

        ms = mop.get("momentum_signals") or {}
        if ms:
            parts.append("── MOMENTUM SIGNALS (first 30 min) ──")
            for cat in ("gap_up_watch", "gap_down_reversal_candidates",
                        "rvol_3x_list", "orb_candidates"):
                tickers = ms.get(cat) or []
                if tickers:
                    pretty = cat.replace("_", " ").upper()
                    line = ", ".join(_strip_markdown(str(t)) for t in tickers[:10])
                    parts.append(f"  • {pretty}: {line}")
            parts.append("")

        rf = mop.get("risk_flags") or []
        if rf:
            parts.append("── RISK FLAGS ──")
            for flag in rf:
                if isinstance(flag, dict):
                    sev = (flag.get("severity") or "").upper()
                    txt = _strip_markdown(flag.get("text") or "")
                    sev_tag = f"[{sev}] " if sev else ""
                    parts.append(f"  • {sev_tag}{txt}")
                else:
                    parts.append(f"  • {_strip_markdown(str(flag))}")
            parts.append("")

        # Wave 14I — ROTATION REGIME sub-block
        rr = synthesis.get("market_open_plan", {}).get("rotation_regime") or {}
        if not rr and pack:
            # Synthesize from prep pack rotation/style/cycle if chair didn't fill it
            rot = pack.get("rotation_snapshot") or {}
            cyc = (pack.get("cycle_phase") or {}).get("classification", {})
            sty = pack.get("style_ratios") or {}
            rr = {
                "current_phase": cyc.get("phase"),
                "leading_sectors": (rot.get("by_quadrant") or {}).get("Leading", []),
                "weakening_sectors": (rot.get("by_quadrant") or {}).get("Weakening", []),
                "breadth_pct": (rot.get("breadth") or {}).get("pct"),
                "active_style_rotations": sty.get("regime_signals", []),
                "one_liner": rot.get("leadership_summary"),
            }
        if rr and any(rr.values()):
            parts.append("── ROTATION REGIME ──")
            phase = rr.get("current_phase")
            if phase:
                parts.append(f"  • Cycle phase: {phase}")
            leaders = rr.get("leading_sectors") or []
            if leaders:
                parts.append(f"  • Leading sectors: {', '.join(leaders)}")
            weakening = rr.get("weakening_sectors") or []
            if weakening:
                parts.append(f"  • Weakening: {', '.join(weakening)}")
            breadth = rr.get("breadth_pct")
            if breadth is not None:
                state = ("broad" if breadth >= 70 else "narrow" if breadth <= 30 else "neutral")
                parts.append(f"  • Breadth: {breadth}% sectors above 50d SMA ({state})")
            style_rotations = rr.get("active_style_rotations") or []
            for s in style_rotations[:4]:
                parts.append(f"  • {_strip_markdown(str(s))}")
            one_liner = rr.get("one_liner")
            if one_liner:
                parts.append(f"  • Read: {_strip_markdown(one_liner)}")
            parts.append("")
        parts.append("")

    # ── EXECUTIVE SUMMARY ──
    es = synthesis.get("executive_summary") or ""
    if isinstance(es, dict):
        es = es.get("text") or ""
    es = _strip_markdown(es)
    if es:
        parts.append("EXECUTIVE SUMMARY")
        parts.append(es)
        parts.append("")

    # ── KEY MOVEMENTS ──
    km = synthesis.get("key_movements") or []
    if km:
        parts.append("KEY MOVEMENTS")
        for item in km:
            txt = _strip_markdown(item.get("text", "") if isinstance(item, dict) else str(item))
            cites = item.get("citations", []) if isinstance(item, dict) else []
            parts.append(f"- {txt}{_cite(cites)}")
        parts.append("")

    # ── EMERGING OPPORTUNITIES & RISKS ──
    eo = synthesis.get("emerging_opportunities_and_risks") or []
    if eo:
        parts.append("EMERGING OPPORTUNITIES AND RISKS")
        for item in eo:
            txt = _strip_markdown(item.get("text", "") if isinstance(item, dict) else str(item))
            cites = item.get("citations", []) if isinstance(item, dict) else []
            parts.append(f"- {txt}{_cite(cites)}")
        parts.append("")

    # ── PRE-MARKET TRADE IDEAS ──
    ideas = synthesis.get("trade_ideas") or []
    if ideas:
        parts.append("PRE-MARKET TRADE IDEAS")
        for i, idea in enumerate(ideas, 1):
            typ = (idea.get("type") or "stock").upper()
            label = "OPTIONS PLAY" if typ == "OPTIONS" else ("FUTURES" if typ == "FUTURES" else "STOCK SETUP")
            parts.append(f"\n{label} {i}")
            parts.append(f"TICKER: {idea.get('ticker', '?')}")
            if idea.get("structure"):
                parts.append(f"STRUCTURE: {_strip_markdown(idea['structure'])}")
            if idea.get("thesis"):
                parts.append(f"THESIS: {_strip_markdown(idea['thesis'])}")
            for fld in ("entry", "stop", "target", "timeframe", "max_risk"):
                v = idea.get(fld)
                if v:
                    parts.append(f"{fld.upper()}: {_strip_markdown(str(v))}")
            srcs = idea.get("sources", [])
            if srcs:
                parts.append(f"SOURCES: {', '.join(str(s)[:8] for s in srcs)}")
        parts.append("")

    # ── POLYMARKET WATCH ──
    pm = synthesis.get("polymarket_watch") or []
    if pm:
        parts.append("POLYMARKET WATCH")
        for item in pm:
            txt = _strip_markdown(item.get("text", "") if isinstance(item, dict) else str(item))
            cites = item.get("citations", []) if isinstance(item, dict) else []
            parts.append(f"- {txt}{_cite(cites)}")
        parts.append("")

    # ── TODAY'S RESEARCH TOPICS ──
    rt = synthesis.get("today_research_topics") or []
    if rt:
        parts.append("TODAY'S RESEARCH TOPICS")
        for t in rt:
            if isinstance(t, dict):
                parts.append(f"TOPIC: {_strip_markdown(t.get('topic', ''))}")
                if t.get("why"):
                    parts.append(f"WHY: {_strip_markdown(t['why'])}")
                if t.get("investigate"):
                    parts.append(f"INVESTIGATE: {_strip_markdown(t['investigate'])}")
                parts.append("")

    text = "\n".join(parts)

    # Wave 14I — ensure the rotation_regime block lives in
    # market_open_plan so iOS can render it as a structured surface.
    if rr and isinstance(mop, dict) and "rotation_regime" not in mop:
        mop = {**mop, "rotation_regime": rr}

    envelope = {
        "date": today,
        "generated_at": now,
        "full_brief": text,
        "topics": text,  # back-compat with iOS BriefRenderer
        "market_open_plan": mop,
        "executive_summary": es,
        "key_movements": km,
        "emerging_opportunities_and_risks": eo,
        "trade_ideas": ideas,
        "polymarket_watch": pm,
        "today_research_topics": rt,
        "council_meta": synthesis.get("council_meta") or synthesis.get("_meta"),
        "source": "morning_brief_pro",
    }

    # Persist
    PRO_BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    try:
        out_path = PRO_BRIEF_DIR / f"{today}.json"
        out_path.write_text(json.dumps(envelope, indent=2, default=str))
        log.info("[brief_pro] wrote %s (%d bytes)", out_path, out_path.stat().st_size)
    except Exception as e:
        log.warning("[brief_pro] persist failed: %s", e)

    return envelope


def load_latest_pro_brief() -> Optional[dict]:
    today = date.today().isoformat()
    path = PRO_BRIEF_DIR / f"{today}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


__all__ = ["render_pro_brief", "load_latest_pro_brief", "PRO_BRIEF_DIR"]
