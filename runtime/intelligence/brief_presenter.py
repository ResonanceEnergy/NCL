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


def _render_block(name: str, data) -> list[str]:
    """Wave 14S — render one of the 12 context blocks as plain text lines.
    Strict data-only renderer. Every value comes from the cached pack,
    no LLM in this path. If pack is empty/missing, returns []."""
    lines: list[str] = []
    if data is None or (isinstance(data, (list, dict)) and not data):
        return lines
    try:
        if name == "PORTFOLIO":
            d = data if isinstance(data, dict) else {}
            if d.get("connected"):
                lines.append(
                    f"  NAV ${d.get('total_value_cad', 0):,.0f} CAD "
                    f"(${d.get('total_value_usd', 0):,.0f} USD), "
                    f"positions={d.get('positions_count', 0)}, "
                    f"daily_pl={d.get('daily_pl_pct', 0)}%"
                )
            else:
                lines.append("  (brokers disconnected — paper-only context)")
        elif name == "AGENT":
            d = data if isinstance(data, dict) else {}
            active = d.get("active", False)
            paused = d.get("paused_by")
            state = "ACTIVE" if active else (f"PAUSED · {paused}" if paused else "OFF")
            it = d.get("ideas_today", {})
            lines.append(
                f"  state={state}, today: "
                f"eval={it.get('evaluated', 0)} open={it.get('opened', 0)} "
                f"reject={it.get('rejected', 0)}"
            )
            for s in (d.get("top_strategies_lcb") or [])[:3]:
                if isinstance(s, dict):
                    lines.append(
                        f"  • {s.get('strategy', '?')}: "
                        f"LCB={s.get('lcb', 0):.0%} n={s.get('n', 0)}"
                    )
        elif name == "ROTATION":
            d = data if isinstance(data, dict) else {}
            quads = d.get("by_quadrant", {}) if isinstance(d.get("by_quadrant"), dict) else {}
            lead = quads.get("Leading", []) if isinstance(quads, dict) else []
            weak = quads.get("Weakening", []) if isinstance(quads, dict) else []
            br = d.get("breadth", {}) if isinstance(d.get("breadth"), dict) else {}
            lines.append(
                f"  Leading: {', '.join(lead) or 'none'} | "
                f"Weakening: {', '.join(weak) or 'none'} | "
                f"Breadth: {br.get('pct', 0)}% above 50d ({br.get('regime', '?')})"
            )
        elif name in ("GOAT", "BRAVO"):
            d = data if isinstance(data, dict) else {}
            scan_date = d.get("scan_date", "?")
            items = d.get("items", [])
            if not items:
                lines.append(f"  (no fresh scan — last scan {scan_date})")
            else:
                lines.append(f"  Top {len(items)} from {scan_date} scan:")
                for it in items:
                    score = it.get("score", 0)
                    aligned = "✓rotation" if it.get("rotation_aligned") else ""
                    lines.append(
                        f"  • {it.get('ticker', '?'):6s} score={score:.0f} "
                        f"@ ${it.get('price', 0):.2f} "
                        f"stop ${it.get('stop_loss', 0):.2f} "
                        f"target ${it.get('target_1', 0):.2f} {aligned}"
                    )
        elif name == "OPTIONS":
            d = data if isinstance(data, dict) else {}
            rows = d.get("rows", [])
            if not rows:
                lines.append("  (no flow data)")
            else:
                for r in rows[:5]:
                    lines.append(
                        f"  • {r.get('ticker', '?')} "
                        f"call/put={r.get('call_put_ratio', '?')} "
                        f"premium=${r.get('total_premium_usd', 0):,.0f}"
                    )
        elif name == "CRYPTO":
            d = data if isinstance(data, dict) else {}
            for it in (d.get("items") or [])[:5]:
                lines.append(
                    f"  • {it.get('title', '')[:70]} (score {it.get('score', 0):.2f})"
                )
        elif name == "POLYMARKET":
            d = data if isinstance(data, dict) else {}
            for it in (d.get("items") or [])[:5]:
                lines.append(
                    f"  • {it.get('side', '?')} {it.get('edge_pp', 0):.1f}pp edge — "
                    f"{it.get('market_question', '')[:60]} "
                    f"(market=${it.get('market_yes_price', 0):.2f}, "
                    f"{it.get('days_to_resolution', '?')}d)"
                )
        elif name == "PREDICTIONS":
            d = data if isinstance(data, dict) else {}
            for it in (d.get("items") or [])[:5]:
                conf = it.get("confidence") or it.get("stated_probability") or 0
                lines.append(
                    f"  • {it.get('direction', '?'):8s} {conf:.0%} ({it.get('forecast_window_days', '?')}d) — "
                    f"{(it.get('title') or '')[:70]}"
                )
        elif name == "YTC":
            d = data if isinstance(data, dict) else {}
            for it in (d.get("items") or [])[:5]:
                ts = (it.get("modified_iso") or "")[11:16]
                lines.append(f"  • {ts} {it.get('filename', '')[:70]}")
        elif name == "CONTEXT":
            items = data if isinstance(data, list) else []
            for it in items[:10]:
                if isinstance(it, dict):
                    txt = (it.get("content") or it.get("title") or "")[:80]
                    sal = it.get("salience_score", 0)
                    lines.append(f"  • [{sal:.2f}] {txt}")
        elif name == "TODO_7DAY":
            d = data if isinstance(data, dict) else {}
            items = d.get("items") or d.get("todos") or []
            if not items:
                lines.append("  (no scheduled items)")
            for it in items[:10]:
                if isinstance(it, dict):
                    date_s = it.get("date") or it.get("scheduled_date") or "?"
                    title = it.get("title") or it.get("text") or it.get("content") or "?"
                    lines.append(f"  • {date_s}  {title[:70]}")
                else:
                    lines.append(f"  • {str(it)[:80]}")
    except Exception as e:
        lines.append(f"  (render error: {e})")
    return lines


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

    # ── Wave 14S — 12 context blocks, each with timestamp + provenance ──
    # Pull from the prep pack (passed in by the council runner). Every
    # section gets a header line: "── {NAME} (generated_at: ..., source: ...) ──"
    # so the operator can verify the data is fresh and trace it to its source.
    # Anti-hallucination: blocks render straight from cached data, NOT LLM output.
    if pack and isinstance(pack, dict):
        parts.append("═══════════════════════════════════════════════════════")
        parts.append("DAILY CONTEXT — full picture (12 blocks, timestamped, sourced)")
        parts.append("═══════════════════════════════════════════════════════")
        parts.append("")
        for block_name in (
            "PORTFOLIO", "AGENT", "ROTATION", "GOAT", "BRAVO",
            "OPTIONS", "CRYPTO", "POLYMARKET", "PREDICTIONS",
            "YTC", "CONTEXT", "TODO_7DAY",
        ):
            block = pack.get(block_name)
            if not block:
                continue
            data = block.get("data") if isinstance(block, dict) else block
            ts = block.get("generated_at_iso", "")[:19] if isinstance(block, dict) else ""
            src = block.get("source_endpoint", "") if isinstance(block, dict) else ""
            count = block.get("item_count", 0) if isinstance(block, dict) else None
            cnt_str = f" · {count} items" if count else ""
            parts.append(f"── {block_name} (as of {ts}Z · src: {src}{cnt_str}) ──")
            rendered = _render_block(block_name, data)
            if rendered:
                parts.extend(rendered)
            else:
                parts.append("  (no data)")
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
