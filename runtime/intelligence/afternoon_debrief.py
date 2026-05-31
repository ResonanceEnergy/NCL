"""Wave 14X-Y Phase 2 (2026-05-29) — Afternoon Debrief.

Per the REVAMP spec: morning + evening Briefs are NATRIX's twice-daily
anchors. The Morning Brief Pro at 05:30 ET sets the plan. This module
provides the 16:30 ET counterpart: a post-close reflection that closes
the loop on today's calls and seeds tonight's Night Watch.

Single-LLM (Claude Opus 4 via dispatcher) — no 4-member council. The
debrief job is simpler than the morning Brief: read today's outcomes,
write a short reflection. ~$0.08/run vs Brief's ~$0.42.

Six tiles (per Dashboard situational-cockpit spec):
  1. TODAY'S SCOREBOARD  — ideas given vs taken, P&L, hit rate
  2. NIGHT WATCH FOCUS  — what tonight's 2am cycle should investigate
  3. AGENT REASONING    — top 3 reasoning chains from today's opens/closes
  4. POST-MARKET SCAN   — EOD scanner pulse, setups for tomorrow
  5. ROTATION SHIFT     — sector regime change vs yesterday
  6. ONE-Q QUIZ PROMPT  — "what trade do you wish you'd taken?"
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional


log = logging.getLogger("ncl.intel.afternoon_debrief")

NCL_BASE = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DEBRIEF_DIR = NCL_BASE / "data" / "afternoon-debrief"

# Single model — Opus for synthesis quality. Cheaper than full council.
_MODEL = "claude-opus-4-20250514"


def _read_today_eod() -> dict:
    """Today's auto-trader EOD summary (or empty if not yet emitted)."""
    path = NCL_BASE / "data" / "portfolio" / "auto_trader" / "eod_summaries.jsonl"
    if not path.exists():
        return {}
    today = date.today().isoformat()
    try:
        with open(path, "r") as fh:
            for raw in reversed(fh.readlines()[-30:]):
                try:
                    d = json.loads(raw.strip())
                except json.JSONDecodeError:
                    continue
                if d.get("date") == today:
                    return d
    except OSError as e:
        log.warning("[debrief] eod read failed: %s", e)
    return {}


def _read_today_brief() -> dict:
    """This morning's brief output for compare-against-ideas."""
    path = NCL_BASE / "data" / "morning-brief-pro" / f"{date.today().isoformat()}.json"
    if not path.exists():
        return {}
    try:
        d = json.loads(path.read_text())
        synth = d.get("synthesis") or {}
        return {
            "trade_ideas": synth.get("trade_ideas", []),
            "market_open_plan": synth.get("market_open_plan", {}),
            "headline": synth.get("headline", ""),
        }
    except (OSError, json.JSONDecodeError) as e:
        log.warning("[debrief] brief read failed: %s", e)
    return {}


def _read_today_cross_refs() -> list[dict]:
    """Today's cross-reference promotions (intel that converged today)."""
    path = NCL_BASE / "data" / "cross_reference" / "promotions.jsonl"
    if not path.exists():
        return []
    today = date.today().isoformat()
    out: list[dict] = []
    try:
        with open(path, "r") as fh:
            for raw in fh.readlines()[-500:]:
                try:
                    d = json.loads(raw.strip())
                except json.JSONDecodeError:
                    continue
                if (d.get("promoted_at", "") or "")[:10] == today:
                    out.append(d)
    except OSError as e:
        log.warning("[debrief] cross-ref read failed: %s", e)
    return out


def _read_rotation_today_vs_yesterday() -> dict:
    """Compare today's rotation snapshot to yesterday."""
    rot_dir = NCL_BASE / "data" / "rotation"
    today = date.today().isoformat()
    today_path = rot_dir / f"{today}.json"
    try:
        files = sorted(rot_dir.glob("2026-*.json"), reverse=True)
        prior = next((f for f in files if f.name != today_path.name), None)
        today_d = json.loads(today_path.read_text()) if today_path.exists() else {}
        prior_d = json.loads(prior.read_text()) if prior else {}
        return {
            "today_leading": today_d.get("leading", []),
            "today_weakening": today_d.get("weakening", []),
            "yesterday_leading": prior_d.get("leading", []),
            "yesterday_weakening": prior_d.get("weakening", []),
        }
    except (OSError, json.JSONDecodeError) as e:
        log.warning("[debrief] rotation compare failed: %s", e)
        return {}


def _prompt(pack: dict) -> str:
    return f"""You are writing NATRIX's AFTERNOON DEBRIEF for {date.today().isoformat()}.

The morning brief gave NATRIX these trade ideas + plan. Now the close
is in. Write a SHORT structured reflection that closes today's loop and
seeds tonight's Night Watch focus.

CONTEXT:
{json.dumps(pack, default=str)[:12000]}

Output ONLY JSON in this shape:
{{
  "headline": "1-line: today's net read",
  "today_scoreboard": {{
    "ideas_given": int,
    "closes_today": int,
    "winners": int,
    "losers": int,
    "scratches": int,
    "total_r": float,
    "best_setup": "ticker + 1-line why it worked",
    "worst_setup": "ticker + 1-line why it didn't"
  }},
  "night_watch_focus": [
    "specific intel topic 1 (e.g. 'XLE post-OPEC reaction')",
    "specific intel topic 2",
    "specific intel topic 3"
  ],
  "agent_reasoning_highlights": [
    "1-line summary of an interesting open/close decision today",
    "..."
  ],
  "post_market_scan": [
    "ticker + setup forming at close for tomorrow"
  ],
  "rotation_shift": "1-line on whether sector leadership moved today",
  "one_q_quiz_prompt": "What's the one trade you wish you'd taken today? (NATRIX answers this in the journal)"
}}
"""


def _adapt_pm_to_envelope(out: dict) -> dict:
    """Wave 14CV — map PM debrief shape onto the 5-lane envelope so
    brief_archiver.archive_brief can render a .md document.

    PM debrief has its own structure (scoreboard/night_watch/scan/etc).
    We project it into PORTFOLIO + INTEL + MEMORY lanes so the .md
    renderer treats it like an evening complement to the AM brief.
    Empty lanes (CALENDAR/JOURNAL) keep the section count visually
    consistent with AM but stay clearly labeled as 'PM'.
    """
    synth = out.get("synthesis") or {}
    scoreboard = synth.get("today_scoreboard") or {}
    return {
        "date": out.get("date"),
        "generated_at": out.get("built_at"),
        "headline": synth.get("headline", ""),
        "council_meta": {"mode": "pm", "model": _MODEL},
        "lanes": {
            "portfolio": {
                "narrative": synth.get("headline", ""),
                "today_scoreboard": scoreboard,
                "agent_reasoning_highlights": synth.get("agent_reasoning_highlights", []),
                "post_market_scan": synth.get("post_market_scan", []),
                "rotation_shift": synth.get("rotation_shift", ""),
            },
            "intel": {
                "narrative": "Today's converged intel + reddit pulse",
                "night_watch_focus": synth.get("night_watch_focus", []),
                "reddit_top10": (synth.get("reddit_top10") or [])[:10],
            },
            "calendar": {
                "narrative": "(see AM brief for today's calendar)",
            },
            "journal": {
                "narrative": "End-of-day reflection prompt",
                "one_q_quiz_prompt": synth.get("one_q_quiz_prompt", ""),
            },
            "memory": {
                "narrative": "Seeds for tonight's Night Watch cycle",
                "themes_to_carry": synth.get("night_watch_focus", []),
            },
        },
    }


async def build_debrief() -> dict:
    """Single Opus call. Returns synthesized debrief dict; persists to disk."""
    DEBRIEF_DIR.mkdir(parents=True, exist_ok=True)
    started = time.time()

    # Wave 14AE: include top-10 Reddit across the full 54-sub watchlist
    # over the last 12h so the PM Debrief carries the same Reddit pulse
    # the AM Brief does — twice-daily summary per NATRIX directive.
    from .brief_prep import _collect_reddit_top10

    reddit_top10 = _collect_reddit_top10(window_hours=12, limit=10)

    pack = {
        "date": date.today().isoformat(),
        "today_eod": _read_today_eod(),
        "today_brief": _read_today_brief(),
        "cross_ref_today": _read_today_cross_refs()[:20],
        "rotation_shift": _read_rotation_today_vs_yesterday(),
        "reddit_top10": reddit_top10,
    }

    try:
        from .brief_council import _dispatch_call, _extract_json

        text, in_tok, out_tok = await _dispatch_call(
            _MODEL, _prompt(pack), max_tokens=2000, timeout_s=60.0, label="debrief"
        )
        synthesis = _extract_json(text)
    except Exception as e:
        log.error("[debrief] LLM call failed: %s", e)
        synthesis = {"error": str(e), "headline": "Debrief unavailable — LLM call failed"}

    # Surface reddit_top10 at the envelope level so iOS BriefLandingCard's
    # PM Debrief sheet can render REDDIT PULSE the same way the AM Brief
    # does. The LLM synthesis carries the *narrative*; the persisted
    # AWAREBOT array is the source of truth for the link list.
    if isinstance(synthesis, dict) and reddit_top10 and not synthesis.get("reddit_top10"):
        synthesis["reddit_top10"] = reddit_top10

    out = {
        "date": pack["date"],
        "built_at": datetime.now(timezone.utc).isoformat(),
        "synthesis": synthesis,
        "elapsed_s": round(time.time() - started, 1),
        "pack_meta": {
            "had_eod": bool(pack["today_eod"]),
            "had_brief": bool(pack["today_brief"]),
            "cross_ref_count": len(pack["cross_ref_today"]),
            "reddit_top10_count": len(reddit_top10),
        },
    }

    try:
        (DEBRIEF_DIR / f"{pack['date']}.json").write_text(json.dumps(out, indent=2, default=str))
    except OSError as e:
        log.warning("[debrief] persist failed: %s", e)

    # Wave 14CV — write the unified .md archive so BriefLandingCard
    # can render PM debrief as a single document (same UX as AM brief).
    # We adapt the PM synthesis shape into the lanes envelope shape that
    # archive_brief expects. Trade-idea registration is a no-op for PM
    # (auto-trader's already seen AM's ideas; PM is reflection only).
    try:
        from runtime.intelligence.brief_archiver import archive_brief
        pm_envelope = _adapt_pm_to_envelope(out)
        await archive_brief(pm_envelope, pack=None, mode="pm", brain=None)
    except Exception as e:
        log.warning("[debrief] archive_brief failed: %s", e)

    # Wave 14BD (2026-05-30): render Piper TTS spoken-debrief .wav so
    # iOS BriefLandingCard PM mode Play button can fetch it. Fire-and-
    # forget; never blocks the return.
    try:
        import asyncio as _asyncio

        from .spoken_brief import render_text_to_wav as _render_wav

        text = _debrief_text_for_tts(synthesis)
        if text:
            audio_dir = _NCL_BASE_PATH / "data" / "morning-brief-pro" / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            out_path = audio_dir / f"{pack['date']}-debrief.wav"
            _asyncio.create_task(_render_wav(text, out_path))
    except Exception as e:
        log.debug("[debrief] spoken-debrief render kick-off failed: %s", e)

    return out


_NCL_BASE_PATH = NCL_BASE  # already defined at module top


def _debrief_text_for_tts(synthesis: dict) -> str:
    """Flatten the 6-tile debrief synthesis into a coherent paragraph
    Piper can narrate. Skips empty fields to keep playback under
    ~3-5 minutes."""
    if not isinstance(synthesis, dict):
        return ""
    parts: list[str] = []
    headline = (synthesis.get("headline") or "").strip()
    if headline:
        parts.append(f"NCL afternoon debrief, {date.today().isoformat()}. {headline}")
    sb = synthesis.get("today_scoreboard") or {}
    if isinstance(sb, dict):
        ideas = sb.get("ideas_given")
        wins = sb.get("winners")
        losses = sb.get("losers")
        scratches = sb.get("scratches")
        total_r = sb.get("total_r")
        if ideas is not None or wins is not None:
            chunks = []
            if ideas is not None:
                chunks.append(f"{ideas} ideas given")
            if wins is not None:
                chunks.append(f"{wins} winners")
            if losses is not None:
                chunks.append(f"{losses} losers")
            if scratches is not None:
                chunks.append(f"{scratches} scratches")
            if total_r is not None:
                chunks.append(f"{total_r:+.2f}R realized")
            parts.append("Today's scoreboard: " + ", ".join(chunks) + ".")
    night = synthesis.get("night_watch_focus")
    if isinstance(night, list) and night:
        parts.append("Night watch focus: " + "; ".join(str(n)[:120] for n in night[:3]) + ".")
    highlights = synthesis.get("agent_reasoning_highlights")
    if isinstance(highlights, list) and highlights:
        parts.append("Agent reasoning highlights: " + "; ".join(str(h)[:120] for h in highlights[:3]) + ".")
    pm = synthesis.get("post_market_scan")
    if isinstance(pm, list) and pm:
        parts.append("Post-market scan: " + "; ".join(str(p)[:120] for p in pm[:4]) + ".")
    rotation = synthesis.get("rotation_shift")
    if rotation:
        parts.append(f"Rotation shift: {rotation}.")
    quiz = synthesis.get("one_q_quiz_prompt")
    if quiz:
        parts.append(f"One-question quiz: {quiz}.")
    return "  ".join(parts).strip()


def load_today_debrief() -> Optional[dict]:
    """Load today's persisted debrief if it exists."""
    path = DEBRIEF_DIR / f"{date.today().isoformat()}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def load_latest_debrief() -> Optional[dict]:
    """Load most recent debrief (today's or last available)."""
    if not DEBRIEF_DIR.exists():
        return None
    files = sorted(DEBRIEF_DIR.glob("2026-*.json"), reverse=True)
    if not files:
        return None
    try:
        return json.loads(files[0].read_text())
    except (OSError, json.JSONDecodeError):
        return None


__all__ = ["build_debrief", "load_today_debrief", "load_latest_debrief", "DEBRIEF_DIR"]
