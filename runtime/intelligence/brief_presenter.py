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
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional


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
            if not d.get("connected"):
                err = d.get("error", "brokers disconnected")
                lines.append(f"  ⚠ ERROR: {err}")
            else:
                cad = float(d.get("total_value_cad") or 0)
                usd = float(d.get("total_value_usd") or 0)
                pl_pct = float(d.get("daily_pl_pct") or 0)
                lines.append(
                    f"  NAV ${cad:,.0f} CAD (${usd:,.0f} USD) · "
                    f"positions={d.get('positions_count', 0)} · "
                    f"daily_pl={pl_pct:+.2f}%"
                )
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
                # Wave 14S+1: dedup by ticker (scanner JSONL has multiple
                # intraday snapshots per ticker). Take the best score
                # per ticker, keep top 5 unique.
                seen: dict = {}
                for it in items:
                    tk = it.get("ticker") or ""
                    if not tk:
                        continue
                    cur = seen.get(tk)
                    if cur is None or (it.get("score") or 0) > (cur.get("score") or 0):
                        seen[tk] = it
                unique = sorted(seen.values(), key=lambda r: r.get("score") or 0, reverse=True)[:5]
                lines.append(f"  Top {len(unique)} (unique tickers) from {scan_date} scan:")
                for it in unique:
                    score = float(it.get("score") or 0)
                    price = float(it.get("price") or 0)
                    stop = float(it.get("stop_loss") or 0)
                    target = float(it.get("target_1") or 0)
                    aligned = "✓rotation" if it.get("rotation_aligned") else ""
                    lines.append(
                        f"  • {(it.get('ticker') or '?'):6s} score={score:.0f} "
                        f"@ ${price:.2f} stop ${stop:.2f} target ${target:.2f} {aligned}"
                    )
        elif name == "OPTIONS":
            d = data if isinstance(data, dict) else {}
            rows = d.get("rows", [])
            lookback = d.get("lookback_hours", 24)
            if not rows:
                lines.append(f"  (no flow data — last {lookback}h)")
            else:
                lines.append(f"  Top tickers by total premium (last {lookback}h):")
                for r in rows[:6]:
                    prem = float(r.get("total_premium") or 0)
                    top = float(r.get("top_single_premium") or 0)
                    lines.append(
                        f"  • {(r.get('ticker') or '?'):6s} "
                        f"premium=${prem:>11,.0f} "
                        f"trades={r.get('trade_count', 0):>3d} "
                        f"top=${top:>10,.0f} "
                        f"dir={r.get('direction', 'neu')}"
                    )
        elif name == "CRYPTO":
            d = data if isinstance(data, dict) else {}
            items = d.get("items") or []
            src = d.get("source", "?")
            if not items:
                lines.append(f"  (no crypto data — source: {src})")
            else:
                lines.append(f"  Top {len(items)} crypto movers (24h, sorted by |%change|):")
                for it in items[:8]:
                    pct = float(it.get("pct_24h") or 0)
                    arrow = "▲" if pct >= 0 else "▼"
                    last = float(it.get("last") or 0)
                    name_label = (it.get("name") or it.get("symbol") or "?")[:14]
                    lines.append(
                        f"  • {name_label:14s} {it.get('symbol', ''):10s} "
                        f"${last:>10,.2f}  {arrow} {pct:+5.2f}%"
                    )
        elif name == "POLYMARKET":
            d = data if isinstance(data, dict) else {}
            mode = d.get("mode", "edges")
            items = d.get("items") or []
            if not items:
                lines.append(f"  (no polymarket data — mode: {mode})")
            elif mode == "edges":
                for it in items[:5]:
                    edge = float(it.get("edge_pp") or 0)
                    price = float(it.get("market_yes_price") or 0)
                    lines.append(
                        f"  • {it.get('side', '?')} {edge:+.1f}pp edge — "
                        f"{(it.get('market_question') or '')[:60]} "
                        f"(market=${price:.2f}, "
                        f"{it.get('days_to_resolution', '?')}d)"
                    )
            else:
                # fallback_signals mode: show top active markets by importance
                lines.append("  (no edges; showing top active polymarket signals)")
                for it in items[:5]:
                    imp = float(it.get("importance") or 0)
                    lines.append(
                        f"  • [{it.get('lifecycle', 'active'):>7s}] "
                        f"imp={imp:>5.1f} — "
                        f"{(it.get('market_question') or '')[:70]}"
                    )
        elif name == "PREDICTIONS":
            d = data if isinstance(data, dict) else {}
            for it in (d.get("items") or [])[:5]:
                conf = it.get("confidence") or it.get("stated_probability") or 0
                window = it.get("forecast_window_days")
                window_str = f"{window}d" if window else "no-window"
                title_or_topic = (
                    it.get("title")
                    or it.get("description", "")
                    or it.get("topic", "")
                    or "(no title)"
                )[:70]
                lines.append(
                    f"  • {it.get('direction', '?'):8s} {conf:.0%} ({window_str}) — {title_or_topic}"
                )
        elif name == "YTC":
            d = data if isinstance(data, dict) else {}
            for it in (d.get("items") or [])[:5]:
                ts = (it.get("modified_iso") or "")[11:16]
                lines.append(f"  • {ts} {it.get('filename', '')[:70]}")
        elif name == "CONTEXT":
            # data is dict: {pinned, top_by_salience, themes, total_items}
            d = data if isinstance(data, dict) else {}
            total = d.get("total_items", 0)
            pinned = d.get("pinned") or []
            top = d.get("top_by_salience") or []
            themes = d.get("themes") or []
            lines.append(f"  ({total} items in working_context — top by salience):")
            if pinned:
                lines.append("  📌 PINNED:")
                for it in pinned[:5]:
                    if isinstance(it, dict):
                        txt = (it.get("text") or it.get("content") or "")[:90]
                        if txt:
                            lines.append(f"    • {txt}")
            if top:
                for it in top[:8]:
                    if isinstance(it, dict):
                        txt = (it.get("text") or it.get("content") or "")[:90]
                        sal = float(it.get("salience") or 0)
                        cat = (it.get("category") or "")[:6]
                        if txt:
                            lines.append(f"  • [{cat:6s} sal={sal:.2f}] {txt}")
            if themes:
                theme_strs = [
                    (t.get("text") if isinstance(t, dict) else str(t))[:30] for t in themes[:6]
                ]
                # Filter thread:* UUID noise
                theme_strs = [t for t in theme_strs if not t.startswith("thread:")][:5]
                if theme_strs:
                    lines.append(f"  🏷  themes: {' · '.join(theme_strs)}")
        elif name == "TODO_7DAY":
            d = data if isinstance(data, dict) else {}
            items = d.get("items") or d.get("todos") or []
            if not items:
                lines.append("  (no scheduled items)")
            for it in items[:10]:
                if isinstance(it, dict):
                    pri = it.get("priority", "?")
                    urg = it.get("urgency", "")
                    action = it.get("action") or it.get("title") or it.get("text") or "?"
                    src = it.get("source", "")
                    src_tag = f" [{src}]" if src else ""
                    lines.append(f"  • P{pri} {urg:9s} {action[:60]}{src_tag}")
                else:
                    lines.append(f"  • {str(it)[:80]}")
    except Exception as e:
        lines.append(f"  (render error: {e})")
    return lines


def _render_lane_section(lane_key: str, lane_data: dict, header_label: str, parts: list[str]) -> None:
    """Wave 14Y revised — executive prose format. NATRIX's mandate (2026-05-29 evening):

    'one formatted professional document... written to me as an executive in a
    professional format... a document to be preserved in memory as a snapshot of today.'

    Each lane renders as: ALL-CAPS section header, blank line, narrative paragraph,
    then **BOLD** sub-section markers with flowing prose underneath. No ASCII box
    characters. No '1 / 5' numbering. No '── sub-section ──' rules. The structure
    is invisible to the reader; what they see is a clean executive brief.
    """
    if not lane_data:
        lane_data = {}
    parts.append(header_label)
    parts.append("")
    narrative = _strip_markdown(str(lane_data.get("narrative", "")).strip())
    if narrative:
        parts.append(narrative)
    parts.append("")

    if lane_key == "portfolio":
        # YESTERDAY — one-line summary, then prose lesson.
        yr = lane_data.get("yesterday_recap") or {}
        if yr and (yr.get("headline") or yr.get("lesson")):
            parts.append("**YESTERDAY**")
            if yr.get("headline"):
                parts.append(_strip_markdown(str(yr["headline"])))
            if yr.get("lesson") and yr.get("lesson") != "none":
                parts.append(f"Lesson carried forward: {_strip_markdown(str(yr['lesson']))}")
            parts.append("")
        # PAPER ACCOUNT — one-sentence prose.
        ps = lane_data.get("paper_state") or {}
        if ps:
            parts.append("**PAPER ACCOUNT**")
            bal = ps.get("balance_usd")
            bal_str = f"${bal:,.2f}" if bal is not None else "balance unrecorded"
            tr = ps.get("today_realized_r")
            tr_str = f"{tr:+.2f}R realized" if tr is not None else "no realized P&L"
            parts.append(
                f"Cash position {bal_str} against {ps.get('open_positions', 0)} open positions, "
                f"{ps.get('today_closes', 0)} closes today, {tr_str}."
            )
            parts.append("")
        # TODAY'S TRADE IDEAS — numbered list, prose thesis per idea.
        ideas = lane_data.get("trade_ideas") or []
        if ideas:
            parts.append("**TODAY'S TRADE IDEAS**")
            for i, idea in enumerate(ideas, 1):
                typ = (idea.get("type") or "stock").lower()
                ticker = idea.get("ticker", "?")
                thesis = _strip_markdown(idea.get("thesis", ""))
                parts.append(f"{i}. {ticker} ({typ}). {thesis}")
                # Plan parameters as a single inline sentence.
                plan_bits = []
                for fld_key, fld_label in (
                    ("entry", "Entry"), ("stop", "Stop"),
                    ("target", "Target"), ("timeframe", "Horizon"),
                ):
                    v = idea.get(fld_key)
                    if v:
                        plan_bits.append(f"{fld_label} {_strip_markdown(str(v))}")
                if plan_bits:
                    parts.append("   Plan: " + ", ".join(plan_bits) + ".")
            parts.append("")
        # ROTATION REGIME — one-paragraph prose.
        rr = lane_data.get("rotation_regime") or {}
        if rr and any(rr.values()):
            parts.append("**ROTATION REGIME**")
            phase = rr.get("current_phase", "")
            leaders = rr.get("leading_sectors") or []
            weakening = rr.get("weakening_sectors") or []
            breadth = rr.get("breadth_pct")
            bits = []
            if phase:
                bits.append(f"Cycle phase is {phase}")
            if leaders:
                bits.append(f"leading sectors are {', '.join(leaders)}")
            if weakening:
                bits.append(f"weakening sectors are {', '.join(weakening)}")
            if breadth is not None:
                state = "broad" if breadth >= 70 else "narrow" if breadth <= 30 else "neutral"
                bits.append(f"market breadth is {breadth}% above 50d ({state})")
            if bits:
                parts.append(". ".join(bits).capitalize() + ".")
            if rr.get("one_liner"):
                parts.append(_strip_markdown(rr["one_liner"]))
            parts.append("")
        # RISK FLAGS — prose paragraph if any.
        rf = lane_data.get("risk_flags") or []
        if rf:
            parts.append("**RISK FLAGS**")
            for f in rf:
                sev = (f.get("severity") or "").upper()
                txt = _strip_markdown(f.get("text") or "")
                prefix = f"[{sev}] " if sev else ""
                parts.append(f"{prefix}{txt}")
            parts.append("")

    elif lane_key == "intel":
        sigs = lane_data.get("top_signals") or []
        if sigs:
            parts.append("**TOP SIGNALS**")
            for it in sigs[:6]:
                if isinstance(it, dict):
                    txt = _strip_markdown(it.get("text", ""))
                    src = it.get("source", "")
                    src_tag = f" ({src})" if src else ""
                    parts.append(f"{txt}{src_tag}")
                else:
                    parts.append(_strip_markdown(str(it)))
            parts.append("")
        preds = lane_data.get("predictions_watch") or []
        if preds:
            parts.append("**PREDICTIONS WATCH**")
            for it in preds[:6]:
                if isinstance(it, dict):
                    txt = _strip_markdown(it.get("text", ""))
                    direction = it.get("direction", "")
                    conf = it.get("confidence_pct")
                    suffix = ""
                    if direction or conf is not None:
                        suffix = f" ({direction}, {conf}% conf)" if (direction and conf is not None) else (f" ({direction})" if direction else f" ({conf}% conf)")
                    parts.append(f"{txt}{suffix}")
                else:
                    parts.append(_strip_markdown(str(it)))
            parts.append("")
        poly = lane_data.get("polymarket_watch") or []
        if poly:
            parts.append("**POLYMARKET WATCH**")
            for it in poly[:6]:
                txt = _strip_markdown(it.get("text", "") if isinstance(it, dict) else str(it))
                parts.append(txt)
            parts.append("")
        xref = lane_data.get("cross_reference_promotions") or []
        if xref:
            parts.append("**CROSS-REFERENCE PROMOTIONS**")
            for it in xref[:5]:
                txt = _strip_markdown(it.get("text", "") if isinstance(it, dict) else str(it))
                parts.append(txt)
            parts.append("")

    elif lane_key == "calendar":
        ev = lane_data.get("today_events") or []
        if ev:
            parts.append("**TODAY**")
            for e in ev[:8]:
                if isinstance(e, dict):
                    t = e.get("time_et", "")
                    txt = _strip_markdown(e.get("text", ""))
                    parts.append(f"{t} — {txt}".strip(" —") if t else txt)
                else:
                    parts.append(_strip_markdown(str(e)))
            parts.append("")
        lp = lane_data.get("lunar_phase") or {}
        if lp:
            parts.append("**LUNAR**")
            phase = lp.get("phase", "")
            energy = lp.get("energy", "")
            one_liner = _strip_markdown(lp.get("one_liner", ""))
            line = phase.replace("_", " ").title() if phase else "Lunar"
            if energy:
                line += f" — {energy} energy"
            parts.append(line + ".")
            if one_liner:
                parts.append(one_liner)
            parts.append("")
        nx = lane_data.get("next_7_days_to_watch") or []
        if nx:
            parts.append("**WATCH WINDOW (NEXT 7 DAYS)**")
            for n in nx[:5]:
                if isinstance(n, dict):
                    d = n.get("date", "")
                    txt = _strip_markdown(n.get("text", ""))
                    parts.append(f"{d}: {txt}" if d else txt)
            parts.append("")

    elif lane_key == "journal":
        focus = lane_data.get("today_focus_from_quiz") or ""
        if focus:
            parts.append("**TODAY'S FOCUS**")
            parts.append(_strip_markdown(str(focus)))
            parts.append("")
        posture = lane_data.get("yesterday_quiz_posture") or {}
        if posture and any(posture.values()):
            parts.append("**YESTERDAY'S POSTURE**")
            posture_bits = []
            for k in ("mood", "risk_appetite", "priority"):
                v = posture.get(k)
                if v:
                    posture_bits.append(f"{k}: {_strip_markdown(str(v))}")
            if posture_bits:
                parts.append("; ".join(posture_bits) + ".")
            parts.append("")
        lesson = lane_data.get("yesterday_lesson") or ""
        if lesson:
            parts.append("**YESTERDAY'S LESSON**")
            parts.append(_strip_markdown(str(lesson)))
            parts.append("")
        tickers = lane_data.get("tickers_in_journal_today") or []
        if tickers:
            parts.append("**TICKERS UNDER WATCH**")
            parts.append(", ".join(str(t) for t in tickers[:12]) + ".")
            parts.append("")

    elif lane_key == "memory":
        pinned = lane_data.get("pinned_priorities") or []
        if pinned:
            parts.append("**PINNED PRIORITIES**")
            for p in pinned[:6]:
                if isinstance(p, dict):
                    imp = p.get("importance")
                    txt = _strip_markdown(p.get("text", ""))
                    imp_str = f" (importance {imp})" if imp else ""
                    parts.append(f"{txt}{imp_str}")
                else:
                    parts.append(_strip_markdown(str(p)))
            parts.append("")
        themes = lane_data.get("active_themes") or []
        if themes:
            parts.append("**ACTIVE THEMES**")
            for t in themes[:4]:
                if isinstance(t, dict):
                    txt = _strip_markdown(t.get("text", ""))
                    why = _strip_markdown(t.get("why_relevant_today", ""))
                    parts.append(f"{txt}. {why}" if why else txt)
            parts.append("")


def render_pro_brief(synthesis: dict, pack: dict | None = None) -> dict:
    """Wave 14Y — Render council synthesis as 5-lane brief.

    NATRIX's mandate: every brief has EXACTLY 5 sections in fixed order:
       1. PORTFOLIO   2. INTEL   3. CALENDAR   4. JOURNAL   5. MEMORY

    Returns envelope with:
        full_brief:  plain-text brief (back-compat for iOS BriefRenderer)
        topics:      same as full_brief (legacy alias)
        lanes:       {portfolio, intel, calendar, journal, memory} dicts
        council_meta
        generated_at, date, source
    """
    today = date.today().isoformat()
    now = datetime.now(timezone.utc).isoformat()

    parts: list[str] = []

    # ── HEADER ── Executive briefing voice. NATRIX's mandate: written to
    # him as an executive in a professional format, preserved in memory
    # as a snapshot of today. No ASCII boxes, no section numbering.
    parts.append(f"NCL MORNING BRIEF — {today}")
    parts.append(f"Prepared {now[:19]}Z")
    parts.append("")

    # ── Wave 14Y — 5-LANE BODY ──
    # Each lane comes from the chair's synthesis (synthesis["portfolio"]
    # etc) and falls back to pack["lanes"][...] if the chair didn't fill
    # the section. Order is FIXED — NATRIX's law.
    pack_lanes = (pack or {}).get("lanes") or {}
    lanes_5: dict[str, dict] = {}
    for key, header in (
        ("portfolio", "PORTFOLIO"),
        ("intel", "INTEL"),
        ("calendar", "CALENDAR"),
        ("journal", "JOURNAL"),
        ("memory", "MEMORY"),
    ):
        lane = synthesis.get(key)
        if not isinstance(lane, dict) or not lane:
            lane = pack_lanes.get(key) or {}
        lanes_5[key] = lane
        _render_lane_section(key, lane, header, parts)

    text = "\n".join(parts).rstrip() + "\n"

    envelope = {
        "date": today,
        "generated_at": now,
        "full_brief": text,
        "topics": text,  # back-compat with legacy iOS BriefRenderer
        "lanes": lanes_5,
        "council_meta": synthesis.get("council_meta") or synthesis.get("_meta"),
        "source": "morning_brief_pro_v2_5lane",
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


def _legacy_render_unused(synthesis: dict, pack: dict | None = None) -> dict:
    """Wave 14X pre-5-lane renderer — kept as dead reference only.
    Wave 14Y replaced this with the strict 5-lane format. Do not call.
    """
    today = date.today().isoformat()
    now = datetime.now(timezone.utc).isoformat()
    parts: list[str] = []

    yr = synthesis.get("yesterday_recap") or {}
    if yr and (yr.get("headline") or yr.get("scoreboard")):
        parts.append("═══════════════════════════════════════════════════════")
        parts.append("YESTERDAY'S RECAP")
        parts.append("═══════════════════════════════════════════════════════")
        if yr.get("headline"):
            parts.append(_strip_markdown(str(yr["headline"])))
        sb = yr.get("scoreboard") or {}
        if sb:
            sb_line = (
                f"  closes={sb.get('closes', 0)} "
                f"({sb.get('winners', 0)}W / {sb.get('losers', 0)}L / {sb.get('scratches', 0)}S)"
                f"  realized={sb.get('total_r', 0):+.2f}R"
            )
            if sb.get("ideas_given") is not None:
                sb_line += f"  ideas_given={sb['ideas_given']}"
            parts.append(sb_line)
        if yr.get("lesson"):
            parts.append(f"  lesson: {_strip_markdown(str(yr['lesson']))}")
        if yr.get("drift_flags"):
            for df in yr["drift_flags"][:3]:
                parts.append(f"  drift: {_strip_markdown(str(df))}")
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
                txt = _strip_markdown(
                    item.get("text") or item if isinstance(item, dict) else str(item)
                )
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
            for cat in (
                "gap_up_watch",
                "gap_down_reversal_candidates",
                "rvol_3x_list",
                "orb_candidates",
            ):
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
                state = "broad" if breadth >= 70 else "narrow" if breadth <= 30 else "neutral"
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
            label = (
                "OPTIONS PLAY"
                if typ == "OPTIONS"
                else ("FUTURES" if typ == "FUTURES" else "STOCK SETUP")
            )
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
    # Wave 14X-1B: cut Wave 14S 12-block sprawl back to canonical context.
    # OPTIONS/CRYPTO/POLYMARKET/YTC/GOAT/BRAVO/PREDICTIONS live in their
    # own iOS tabs (PORTFOLIO / INTEL) per the new architecture — the
    # Brief is for decision-grade morning synthesis, not a data dump.
    # ROTATION already renders above as ROTATION REGIME inside MARKET
    # OPEN PLAN, so we drop it from the bottom context too.
    # Kept: PORTFOLIO (book state), AGENT (auto-trader state),
    # CONTEXT (working context), TODO_7DAY (calendar). Four blocks of
    # NATRIX-anchoring context, not twelve of source noise.
    if pack and isinstance(pack, dict):
        parts.append("═══════════════════════════════════════════════════════")
        parts.append("CONTEXT — book, agent, attention, calendar")
        parts.append("═══════════════════════════════════════════════════════")
        parts.append("")
        for block_name in (
            "PORTFOLIO",
            "AGENT",
            "CONTEXT",
            "TODO_7DAY",
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
