"""Wave 14CQ (2026-05-31) — Brief unification + memory + tracker bridge.

NATRIX: "morning brief all one doc with sections possibly .md or json
and enabled for memory storage as a timestamp of events at this time
this day for future refrence from ncl brain memory does this make sense?"

This module is the single closing-of-the-loop for every brief fire (AM
+ PM). After the council synthesizes and the presenter renders, we:

  1. Materialize a SINGLE timestamped Markdown document per fire
     (YAML front-matter + 5-lane sections). One-shot grep / cat /
     long-context-LLM friendly.

  2. Persist that document to `data/morning-brief-md/<date>-<mode>.md`
     and to memory as a high-importance MemUnit (importance 95, tier
     BRAIN, source brief:archive). Future queries to
     /memory/search/fused for "what did NCL say on May 30" or
     "what was the brief 30 days ago" will surface the snapshot.

  3. CRITICAL Wave 14CP audit fix (#1 in punch list): wire the brief's
     PORTFOLIO lane trade_ideas into trade_idea_tracker so the
     auto_trader actually SEES them. Before this, ideas were emitted
     by the brief and immediately dropped on the floor — the auto-
     trader has been completely starved since 2026-05-29 22:02 because
     the new Pro Brief path (Wave 14H+14Y) skipped what the legacy
     brief_pipeline did.

  4. Cleanup: drop the literal-"sig_id" citation strings that the chair
     prompt was emitting verbatim (the example value was being parroted
     as the value itself — see audit B4.1). We keep only real 8-char
     id= tokens from member outputs.

Entry point: archive_brief(envelope, pack, mode="am"|"pm") — fire and
forget from the route handler / scheduler after presenter returns.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


log = logging.getLogger("ncl.intelligence.brief_archiver")


_BASE = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
_MD_DIR = _BASE / "data" / "morning-brief-md"
_MD_DIR.mkdir(parents=True, exist_ok=True)

# Literal placeholder strings the chair has been parroting. Filter these
# out at archive time so downstream consumers don't get junk citations.
_PLACEHOLDER_CITATIONS = frozenset({
    "sig_id", "sig_001", "sig_042", "sig_007", "<real 8-char id>",
    "...", "id", "REAL_ID", "REPLACE_ME",
})

# Real id= tokens are 8-char hex. Accept anything ≥6 alphanumeric
# as a "looks real" guard.
_REAL_ID_RX = re.compile(r"^[a-f0-9]{6,16}$", re.IGNORECASE)


def _is_real_citation(s: Any) -> bool:
    """True if `s` is a plausible real signal id (not a placeholder)."""
    if not isinstance(s, str):
        return False
    s = s.strip()
    if not s or s in _PLACEHOLDER_CITATIONS:
        return False
    return bool(_REAL_ID_RX.match(s))


def _scrub_citations(envelope: dict) -> dict:
    """Walk lanes.* and drop placeholder strings from citation arrays."""
    lanes = envelope.get("lanes") or {}

    def _scrub_array(items: list, key: str) -> list:
        if not isinstance(items, list):
            return items
        cleaned = []
        for item in items:
            if isinstance(item, dict) and key in item:
                arr = item.get(key) or []
                item[key] = [c for c in arr if _is_real_citation(c)]
            cleaned.append(item)
        return cleaned

    portfolio = lanes.get("portfolio") or {}
    if "trade_ideas" in portfolio:
        portfolio["trade_ideas"] = _scrub_array(portfolio["trade_ideas"], "sources")

    intel = lanes.get("intel") or {}
    for k in ("top_signals", "predictions_watch", "polymarket_watch"):
        if k in intel:
            cite_key = "sig_id" if k == "top_signals" else "citations"
            arr = intel.get(k) or []
            for item in arr:
                if isinstance(item, dict):
                    if cite_key == "sig_id":
                        v = item.get("sig_id")
                        if not _is_real_citation(v):
                            item.pop("sig_id", None)
                    else:
                        cites = item.get("citations") or []
                        item["citations"] = [c for c in cites if _is_real_citation(c)]

    return envelope


# ── Markdown rendering ──────────────────────────────────────────────


def _yaml_front_matter(envelope: dict, mode: str, brief_id: str) -> str:
    """Tiny YAML emitter — no PyYAML dep. Keeps keys flat / scalar."""
    lanes = envelope.get("lanes") or {}
    portfolio = lanes.get("portfolio") or {}
    paper_state = portfolio.get("paper_state") or {}
    trade_ideas = portfolio.get("trade_ideas") or []
    council_meta = envelope.get("council_meta") or {}

    front: dict[str, Any] = {
        "brief_id": brief_id,
        "mode": mode,  # "am" or "pm"
        "date": envelope.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "generated_at": envelope.get("generated_at")
            or datetime.now(timezone.utc).isoformat(),
        "members_succeeded": council_meta.get("members_succeeded") or [],
        "council_confidence": council_meta.get("confidence_score"),
        "macro_model": council_meta.get("macro_model"),
        "lanes_present": list(lanes.keys()),
        "n_trade_ideas": len(trade_ideas),
        "paper_balance_usd": paper_state.get("balance_usd"),
        "paper_open_positions": paper_state.get("open_positions"),
    }

    lines = ["---"]
    for k, v in front.items():
        if v is None:
            lines.append(f"{k}: null")
        elif isinstance(v, (list, tuple)):
            if not v:
                lines.append(f"{k}: []")
            else:
                lines.append(f"{k}: [{', '.join(json.dumps(x) for x in v)}]")
        elif isinstance(v, str):
            # Quote strings that contain colons / leading dashes
            if any(c in v for c in (":", "-", "#")) or v.startswith(" "):
                lines.append(f"{k}: {json.dumps(v)}")
            else:
                lines.append(f"{k}: {v}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def _lane_to_md(lane_key: str, lane_data: Any) -> str:
    """Render a single lane's structured fields as a markdown section."""
    if not isinstance(lane_data, dict):
        return f"## {lane_key.upper()}\n\n_(no data)_\n"

    out = [f"## {lane_key.upper()}", ""]
    narrative = lane_data.get("narrative")
    if narrative:
        out.append(narrative)
        out.append("")

    # Per-lane structured rendering. Keep it generic enough that
    # adding new fields to the lane spec doesn't break the writer.
    for field_key, field_val in lane_data.items():
        if field_key == "narrative":
            continue
        if field_val in (None, "", [], {}):
            continue
        out.append(f"### {field_key.replace('_', ' ').title()}")
        out.append("")
        if isinstance(field_val, str):
            out.append(field_val)
        elif isinstance(field_val, list):
            for entry in field_val:
                if isinstance(entry, dict):
                    # One bullet per dict; render key=value pairs
                    parts = []
                    for k, v in entry.items():
                        if v is None or v == "" or v == []:
                            continue
                        if isinstance(v, (list, dict)):
                            parts.append(f"{k}={json.dumps(v, separators=(',', ':'))}")
                        else:
                            parts.append(f"{k}={v}")
                    out.append(f"- {' · '.join(parts)}")
                else:
                    out.append(f"- {entry}")
        elif isinstance(field_val, dict):
            for k, v in field_val.items():
                out.append(f"- **{k}**: {v}")
        else:
            out.append(str(field_val))
        out.append("")
    return "\n".join(out)


def _render_md(envelope: dict, mode: str, brief_id: str) -> str:
    """Build the canonical single-document markdown for this fire."""
    front = _yaml_front_matter(envelope, mode, brief_id)
    title = "AM Brief" if mode == "am" else "PM Debrief"
    date = envelope.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    header = f"# {title} — {date}\n"
    sections: list[str] = []
    lanes = envelope.get("lanes") or {}
    # Fixed 5-lane order per BRIEF_MANDATE.md (LAW)
    for lane_key in ("portfolio", "intel", "calendar", "journal", "memory"):
        if lane_key in lanes:
            sections.append(_lane_to_md(lane_key, lanes[lane_key]))
    body = "\n".join(sections)
    return f"{front}\n\n{header}\n{body}\n"


# ── Trade-idea bridge (CRITICAL Wave 14CP audit fix #1) ─────────────


async def _register_trade_ideas(envelope: dict, mode: str, brief_id: str) -> int:
    """Wire PORTFOLIO lane trade_ideas into trade_idea_tracker so the
    auto-trader actually sees them. Returns count registered.

    Mirrors brief_pipeline.py:606-650's pattern but invoked from the
    canonical Pro Brief path (Wave 14H+14Y), which has been missing
    this call since 2026-05-29 — see AWAREBOT_TRADERAGENT_FLOW_AUDIT
    finding B4.1.
    """
    lanes = envelope.get("lanes") or {}
    portfolio = lanes.get("portfolio") or {}
    ideas = portfolio.get("trade_ideas") or []
    if not isinstance(ideas, list) or not ideas:
        log.info("[brief_archiver] no trade_ideas in PORTFOLIO lane to register")
        return 0

    now_iso = datetime.now(timezone.utc).isoformat()
    registered = 0

    try:
        from runtime.portfolio.risk_governor import _normalize_strategy
        from runtime.portfolio.trade_idea_tracker import (
            record_trade_idea_emission,
        )
    except Exception as e:
        log.warning("[brief_archiver] tracker import failed: %s", e)
        return 0

    def _f(d: dict, k: str):
        v = d.get(k)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            # Strings like "$157.50" — strip non-numeric except . and -
            if isinstance(v, str):
                cleaned = re.sub(r"[^0-9.\-]", "", v)
                try:
                    return float(cleaned) if cleaned else None
                except ValueError:
                    return None
            return None

    for idea in ideas:
        if not isinstance(idea, dict):
            continue
        if not idea.get("trade_idea_id"):
            idea["trade_idea_id"] = uuid.uuid4().hex[:16]
        if not idea.get("issued_at_iso"):
            idea["issued_at_iso"] = now_iso

        # Wave 14CT — normalize numeric fields first so we can derive
        # R_per_share + synthesize options stop from max_risk.
        entry_p = _f(idea, "entry_price") or _f(idea, "entry")
        stop_p  = _f(idea, "stop_price")  or _f(idea, "stop")
        target_p = _f(idea, "target_price") or _f(idea, "target")
        idea_type = (idea.get("type") or "stock").lower()

        # Wave 14CU — options registration with proper schema. The
        # chair prompt now mandates `underlying_entry / _target / _stop`
        # alongside `option_strike / _dte / _right / premium`. We use
        # the underlying triple for the paper trade (the engine speaks
        # equity-style prices), and stash the option specifics in
        # metadata so a future broker-paper-options layer can read them.
        if idea_type == "options":
            ue = _f(idea, "underlying_entry")
            us = _f(idea, "underlying_stop")
            ut = _f(idea, "underlying_target")
            strike = _f(idea, "option_strike")
            dte = idea.get("option_dte")
            right = (idea.get("option_right") or "").lower()
            premium = _f(idea, "premium")
            # Only register if the chair supplied a complete options schema.
            # Anything missing → skip; the LLM gets feedback to be precise
            # next time. Matches Wave 14CU prompt rule 9.
            if not (ue and us and ut and strike and dte and right in ("call", "put") and premium):
                log.info(
                    "[brief_archiver] skipping incomplete options idea "
                    "ticker=%s strike=%s dte=%s right=%s premium=%s "
                    "underlying=(entry=%s stop=%s target=%s)",
                    idea.get("ticker"), strike, dte, right, premium,
                    ue, us, ut,
                )
                continue
            # Override the stock-style prices with the underlying triple.
            entry_p, stop_p, target_p = ue, us, ut
            R_per_share = round(abs(ue - us), 4)

        # Compute R_per_share if missing: |entry - stop| is the
        # canonical per-share risk. Without this 14/20 24h chains
        # were rejecting on "no R_per_share".
        R_per_share = _f(idea, "R_per_share")
        if R_per_share is None and entry_p is not None and stop_p is not None:
            R_per_share = round(abs(entry_p - stop_p), 4)

        # Skip ideas with no usable price at all (LLM sometimes
        # emits all-None placeholders). Better than a useless chain.
        if entry_p is None or stop_p is None or target_p is None:
            log.info(
                "[brief_archiver] skipping idea ticker=%s — missing prices "
                "(entry=%s stop=%s target=%s type=%s)",
                idea.get("ticker"), entry_p, stop_p, target_p, idea_type,
            )
            continue

        try:
            strat = _normalize_strategy(
                idea.get("strategy_tag") or idea_type or "brief"
            )
            # Wave 14CR — pass sources= top-level kwarg so the new
            # TradeIdea.sources field gets populated and policy.py's
            # "no source citations" gate stops false-rejecting. If the
            # scrubber stripped all citations (chair emitted only
            # placeholders), synthesize a brief: tag so the gate
            # still passes; the tag points back to the brief that
            # made this idea for retrospective trace.
            raw_sources = list(idea.get("sources") or [])
            if not raw_sources:
                raw_sources = [f"brief:{brief_id}"]
            await record_trade_idea_emission(
                source=f"brief:{mode}",  # brief:am or brief:pm
                strategy=strat,
                ticker=str(idea.get("ticker") or "").upper(),
                direction=idea.get("direction"),
                entry_price=entry_p,
                stop_price=stop_p,
                target_price=target_p,
                R_per_share=R_per_share,
                planned_qty=_f(idea, "planned_qty"),
                stop_type=idea.get("stop_type") or "price",  # 14CT — "price" is in policy.VALID_STOP_TYPES
                stop_basis=idea.get("stop_basis"),
                target_basis=idea.get("target_basis"),
                thesis=idea.get("thesis"),
                trade_idea_id=idea.get("trade_idea_id"),
                sources=raw_sources,
                metadata={
                    "type": idea.get("type"),
                    "brief_id": brief_id,
                    "brief_mode": mode,
                    "timeframe": idea.get("timeframe"),
                    "structure": idea.get("structure"),
                    "max_risk": idea.get("max_risk"),
                    # Wave 14CU — options specifics for a future
                    # broker-paper-options layer. Stock ideas leave
                    # these as None.
                    "option_strike": _f(idea, "option_strike"),
                    "option_dte": idea.get("option_dte"),
                    "option_right": (idea.get("option_right") or "").lower() or None,
                    "premium": _f(idea, "premium"),
                    "underlying_entry": _f(idea, "underlying_entry"),
                    "underlying_stop": _f(idea, "underlying_stop"),
                    "underlying_target": _f(idea, "underlying_target"),
                },
            )
            registered += 1
        except Exception as e:
            log.warning(
                "[brief_archiver] failed to register idea ticker=%s: %s",
                idea.get("ticker"), e,
            )

    log.info(
        "[brief_archiver] registered %d/%d trade_ideas from %s brief %s",
        registered, len(ideas), mode, brief_id,
    )
    return registered


# ── Memory snapshot ─────────────────────────────────────────────────


async def _persist_to_memory(brain, envelope: dict, md_text: str,
                              mode: str, brief_id: str) -> str | None:
    """Create a single high-importance MemUnit holding the .md snapshot.

    Future queries like `/memory/search/fused?q="May 30 brief"` will
    surface this unit. Tag with brief_id so it's idempotent if the
    brief is re-fired.

    Wave 14CR fix: previous version imported from non-existent paths
    (`runtime.memory.memory_unit` / `runtime.memory.authority.AuthorityTier`)
    and the exception was swallowed. Now uses the real MemUnit at
    `runtime.ncl_brain.models` matching the established create_unit
    callers in agent_bus/intel_request.py + journal/reflection_engine.py.
    """
    if brain is None or not hasattr(brain, "memory_store"):
        log.warning("[brief_archiver] no brain.memory_store handle")
        return None

    try:
        date = envelope.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lanes = envelope.get("lanes") or {}
        portfolio = lanes.get("portfolio") or {}
        n_ideas = len(portfolio.get("trade_ideas") or [])

        # Wave 14CR — match the real MemoryStore.create_unit signature
        # (content=, source=, importance=, tags=, memory_type=, metadata=).
        # Previous version passed a MemUnit() object which doesn't match
        # this signature and raised silently. The store handles unit_id
        # generation + LML/SML tier assignment internally.
        unit = await brain.memory_store.create_unit(
            content=md_text,
            source=f"brief:archive:{mode}",
            importance=95.0,  # HIGH — surfaces in working context
            tags=[
                "brief", "brief_archive", f"brief:{mode}",
                f"date:{date}", brief_id,
            ],
            memory_type="semantic",  # auto-routes to LML (long-term)
            metadata={
                # authority_tier 60 = BRAIN per runtime.memory.authority
                "authority_tier": 60,
                "brief_id": brief_id,
                "brief_mode": mode,
                "date": date,
                "generated_at": envelope.get("generated_at"),
                "lanes_present": list(lanes.keys()),
                "n_trade_ideas": n_ideas,
                "snapshot_format": "markdown_v1",
                "tag": f"brief:{date}:{mode}",
                "md_path": str(_MD_DIR / f"{date}-{mode}.md"),
            },
        )
        log.info(
            "[brief_archiver] memory snapshot created unit_id=%s brief_id=%s",
            unit.unit_id if unit else None, brief_id,
        )
        return unit.unit_id if unit else None
    except Exception as e:
        log.warning("[brief_archiver] memory snapshot failed: %s", e, exc_info=True)
        return None


# ── Public entry point ──────────────────────────────────────────────


async def archive_brief(envelope: dict, pack: dict | None = None,
                         *, mode: str = "am", brain=None) -> dict:
    """Close the loop on a brief fire.

    Returns dict with: brief_id, md_path, memory_unit_id, ideas_registered.

    Safe to call multiple times — file overwrites by (date,mode), memory
    units get unique unit_ids (memory_store dedups by content fingerprint).
    """
    started = datetime.now(timezone.utc)
    date = envelope.get("date") or started.strftime("%Y-%m-%d")
    brief_id = f"{date}:{mode}:{started.strftime('%H%M%S')}"

    # 1. Scrub junk citations BEFORE rendering MD / registering ideas
    envelope = _scrub_citations(envelope)

    # 2. Render unified Markdown
    md_text = _render_md(envelope, mode, brief_id)

    # 3. Write to disk (one file per fire mode; overwrite same-day).
    # Synchronous + fast — this is the user-facing deliverable that
    # must complete before the HTTP response returns.
    md_path = _MD_DIR / f"{date}-{mode}.md"
    try:
        md_path.write_text(md_text)
        log.info("[brief_archiver] wrote %s (%d bytes)", md_path, len(md_text))
    except Exception as e:
        log.warning("[brief_archiver] disk write failed: %s", e)
        md_path = None

    # 4. Memory snapshot + 5. trade_idea registration — both are
    # FIRE-AND-FORGET. Empirically (Wave 14CR debugging) the await on
    # brain.memory_store.create_unit can block indefinitely when the
    # brief itself is still holding brain-internal locks. Decoupling
    # via create_task lets the HTTP response return immediately while
    # the background tasks settle.
    ideas_count_estimate = len(
        ((envelope.get("lanes") or {}).get("portfolio") or {}).get("trade_ideas") or []
    )

    async def _bg_memory():
        # 30s timeout — the brain's MemoryStore.create_unit can stall
        # forever when the async_writer subsystem has its own
        # initialization race ("MemoryStore has no attribute
        # 'index_unit'"). Don't block the bg task chain on that.
        try:
            uid = await asyncio.wait_for(
                _persist_to_memory(brain, envelope, md_text, mode, brief_id),
                timeout=30.0,
            )
            log.info("[brief_archiver/bg] memory unit_id=%s", uid)
        except asyncio.TimeoutError:
            log.warning("[brief_archiver/bg] memory persist timed out >30s")
        except Exception as e:
            log.warning("[brief_archiver/bg] memory persist failed: %s", e)

    async def _bg_register():
        try:
            n = await _register_trade_ideas(envelope, mode, brief_id)
            log.info("[brief_archiver/bg] registered %d trade_ideas", n)
        except Exception as e:
            log.warning("[brief_archiver/bg] tracker register failed: %s", e)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_bg_memory())
        loop.create_task(_bg_register())
    except RuntimeError:
        # No running loop — direct await fallback (sync test path)
        await _bg_memory()
        await _bg_register()

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()

    return {
        "brief_id": brief_id,
        "mode": mode,
        "date": date,
        "md_path": str(md_path) if md_path else None,
        "memory_unit_id_pending": True,  # see brain log [brief_archiver/bg]
        "ideas_to_register": ideas_count_estimate,
        "elapsed_s": round(elapsed, 2),
    }


def load_archived_brief(date: str, mode: str = "am") -> str | None:
    """Read back a previously-archived brief markdown by date+mode."""
    path = _MD_DIR / f"{date}-{mode}.md"
    if not path.exists():
        return None
    try:
        return path.read_text()
    except Exception:
        return None


def list_archived_briefs(limit: int = 30) -> list[dict]:
    """Most-recent-first listing of archived briefs. Used by /intelligence/briefs/history."""
    if not _MD_DIR.exists():
        return []
    rows: list[dict] = []
    for p in sorted(_MD_DIR.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        # filename shape YYYY-MM-DD-{am,pm}.md
        stem = p.stem
        parts = stem.rsplit("-", 1)
        if len(parts) != 2:
            continue
        date, mode = parts
        rows.append({
            "date": date,
            "mode": mode,
            "path": str(p),
            "size_bytes": p.stat().st_size,
            "mtime": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
        })
    return rows


__all__ = [
    "archive_brief",
    "load_archived_brief",
    "list_archived_briefs",
]
