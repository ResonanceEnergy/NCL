"""
Authority / Provenance Tier System
==================================

Every memory unit is born somewhere. A NATRIX directive is not the same as
an Awarebot Reddit scrape, and they should not compete for context on equal
salience footing.

This module classifies the `source` string already carried on every MemUnit
into a numeric authority tier (10..100) and exposes a multiplicative weight
that the salience and retrieval-fusion layers apply on top of their normal
ranking math.

Authority chain (from CLAUDE.md):
    NATRIX (absolute) -> NCL -> NCC/BRS/AAC

That chain is mirrored in the tier scale below.

Tier table
----------
    100  natrix       direct NATRIX directives (pump prompts, journal entries,
                      chat user messages)
     80  council      ratified council consensus decisions, mandates
     60  brain        brain-generated outputs (briefs, predictions,
                      reflections, chat responses)
     50  calendar     calendar events, scheduler-generated facts
     40  llm_single   one-shot single-LLM responses (Claude/Grok/Gemini)
     20  scanner      Awarebot scans, raw signals
     10  raw          unverified ingestion (paste imports, unknown sources)

Resolution rules (`tier_for_source`):

1. Exact match on the full source string wins.
2. Otherwise, split the source on ":" and ",", strip leading "consolidation:"
   prefixes, and resolve EACH part. The maximum tier across parts wins —
   so a consolidation merging a NATRIX directive with a scanner item keeps
   the NATRIX rank.
3. For each part, exact match wins, then prefix match (so "awarebot:newfeed"
   still maps to SCANNER even though the full string is novel).
4. Unknown source -> RAW.

Weighting
---------
``authority_weight(tier)`` maps the integer tier into a multiplicative
weight in [0.1, 1.0] (linear, weight = tier/100, clamped). This is what the
salience formula and the FusedRetriever multiply through.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from enum import IntEnum
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from .store import MemoryStore

log = logging.getLogger("ncl.memory.authority")


# ---------------------------------------------------------------------------
# Tier enum
# ---------------------------------------------------------------------------


class AuthorityTier(IntEnum):
    """Provenance tier for a memory unit. Higher = more trustworthy."""

    NATRIX = 100        # NATRIX directive — absolute authority
    COUNCIL = 80        # Ratified council consensus
    BRAIN = 60          # Brain-generated synthesis output
    CALENDAR = 50       # Scheduler / calendar fact
    LLM_SINGLE = 40     # Single-LLM one-shot response
    SCANNER = 20        # Awarebot scanner / raw signal
    RAW = 10            # Unknown / unverified ingestion


# Convenience: lower-cased name -> tier (for the API endpoint)
TIER_BY_NAME: dict[str, AuthorityTier] = {t.name.lower(): t for t in AuthorityTier}


# ---------------------------------------------------------------------------
# Source -> tier mapping
# ---------------------------------------------------------------------------
#
# These keys must match what each writer actually puts in `unit.source` at
# create-unit time. Keep the keys lowercase — `tier_for_source()` normalizes
# input before lookup. Both exact strings and namespace prefixes (ending in
# ":") are accepted; prefix matching is checked after exact matching.

SOURCE_TIER_MAP: dict[str, AuthorityTier] = {
    # ---- NATRIX (100) -------------------------------------------------
    "natrix-directive": AuthorityTier.NATRIX,
    "natrix": AuthorityTier.NATRIX,
    "pump-prompt": AuthorityTier.NATRIX,
    "pump_prompt": AuthorityTier.NATRIX,
    "pump": AuthorityTier.NATRIX,
    "journal-entry": AuthorityTier.NATRIX,
    "journal_entry": AuthorityTier.NATRIX,
    "journal": AuthorityTier.NATRIX,                # raw NATRIX journal entries
    # Audit 2026-05-22: chat fragments like "health", "Wild" landed at NATRIX(100)
    # and poisoned ticker searches (TSLA query returned chat noise as top hit).
    # Demoted to CALENDAR(50) — chat is still high-authority but won't dominate
    # vector search the way verified pumps/directives do. Pump endpoints +
    # journal entries remain at full NATRIX(100).
    "first-strike-chat": AuthorityTier.CALENDAR,    # demoted from NATRIX
    "first_strike_chat": AuthorityTier.CALENDAR,    # demoted from NATRIX
    # Portfolio events — NATRIX's money is absolute authority. The
    # snapshot/event writers in runtime/portfolio/memory_bridge.py emit
    # source strings under the "portfolio:" namespace; prefix-match
    # rules below catch anything new added later.
    "portfolio": AuthorityTier.NATRIX,
    "portfolio:snapshot": AuthorityTier.NATRIX,
    "portfolio:position_opened": AuthorityTier.NATRIX,
    "portfolio:position_closed": AuthorityTier.NATRIX,
    "portfolio:significant_move": AuthorityTier.NATRIX,
    "portfolio:quantity_change": AuthorityTier.NATRIX,
    "portfolio:account_change": AuthorityTier.NATRIX,
    "portfolio:buying_power_risk": AuthorityTier.NATRIX,

    # ---- COUNCIL (80) -------------------------------------------------
    "council-decision": AuthorityTier.COUNCIL,
    "council_decision": AuthorityTier.COUNCIL,
    "council": AuthorityTier.COUNCIL,
    "council:claude": AuthorityTier.COUNCIL,
    "council:grok": AuthorityTier.COUNCIL,
    "council:gemini": AuthorityTier.COUNCIL,
    "council:gpt": AuthorityTier.COUNCIL,
    "council:perplexity": AuthorityTier.COUNCIL,
    "council:copilot": AuthorityTier.COUNCIL,
    "council:youtube": AuthorityTier.COUNCIL,
    "council:youtube:insight": AuthorityTier.COUNCIL,
    "council:x": AuthorityTier.COUNCIL,
    "mandate": AuthorityTier.COUNCIL,

    # ---- BRAIN (60) ---------------------------------------------------
    "brain-chat-response": AuthorityTier.BRAIN,
    "brain_chat_response": AuthorityTier.BRAIN,
    "intel-brief": AuthorityTier.BRAIN,
    "intel_brief": AuthorityTier.BRAIN,
    "intelligence:brief": AuthorityTier.BRAIN,
    "agent-brief": AuthorityTier.BRAIN,
    "agent_brief": AuthorityTier.BRAIN,
    "prediction": AuthorityTier.BRAIN,
    "predictions": AuthorityTier.BRAIN,
    "awarebot:predictor": AuthorityTier.BRAIN,
    "reflection": AuthorityTier.BRAIN,
    "journal-reflection": AuthorityTier.BRAIN,
    "journal_reflection": AuthorityTier.BRAIN,
    "night-watch": AuthorityTier.BRAIN,
    "night_watch": AuthorityTier.BRAIN,
    "morning-brief": AuthorityTier.BRAIN,
    "morning_brief": AuthorityTier.BRAIN,

    # ---- CALENDAR (50) -----------------------------------------------
    "calendar-event": AuthorityTier.CALENDAR,
    "calendar_event": AuthorityTier.CALENDAR,
    "calendar-todo": AuthorityTier.CALENDAR,
    "calendar_todo": AuthorityTier.CALENDAR,
    "calendar-agent": AuthorityTier.CALENDAR,
    "calendar_agent": AuthorityTier.CALENDAR,
    "calendar": AuthorityTier.CALENDAR,
    "scheduler": AuthorityTier.CALENDAR,

    # ---- LLM_SINGLE (40) ---------------------------------------------
    "llm-haiku": AuthorityTier.LLM_SINGLE,
    "llm_haiku": AuthorityTier.LLM_SINGLE,
    "llm-sonnet": AuthorityTier.LLM_SINGLE,
    "llm_sonnet": AuthorityTier.LLM_SINGLE,
    "claude-direct": AuthorityTier.LLM_SINGLE,
    "claude_direct": AuthorityTier.LLM_SINGLE,
    "grok-direct": AuthorityTier.LLM_SINGLE,
    "grok_direct": AuthorityTier.LLM_SINGLE,
    "gemini-direct": AuthorityTier.LLM_SINGLE,
    "gpt-direct": AuthorityTier.LLM_SINGLE,
    "perplexity-direct": AuthorityTier.LLM_SINGLE,

    # ---- SCANNER (20) ------------------------------------------------
    "awarebot": AuthorityTier.SCANNER,
    "awarebot:reddit": AuthorityTier.SCANNER,
    "awarebot:x": AuthorityTier.SCANNER,
    "awarebot:youtube": AuthorityTier.SCANNER,
    "awarebot:google_trends": AuthorityTier.SCANNER,
    "awarebot:polymarket": AuthorityTier.SCANNER,
    "awarebot:news": AuthorityTier.SCANNER,
    "awarebot:options_flow": AuthorityTier.SCANNER,
    "awarebot:unusual_whales": AuthorityTier.SCANNER,
    "awarebot:crypto": AuthorityTier.SCANNER,
    "awarebot:unknown": AuthorityTier.SCANNER,
    "intelligence_polymarket": AuthorityTier.SCANNER,
    "scanner": AuthorityTier.SCANNER,
    "signal": AuthorityTier.SCANNER,
}


# Marker tokens that prefix a tag without setting the tier themselves.
# `consolidation:awarebot:reddit` -> strip leading "consolidation" parts.
_TRANSPARENT_PREFIXES = {"consolidation"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _strip_transparent(part: str) -> str:
    """Strip leading transparent prefixes (e.g. 'consolidation:') from a part."""
    while True:
        head, sep, rest = part.partition(":")
        if sep and head in _TRANSPARENT_PREFIXES:
            part = rest
            continue
        return part


def _resolve_single(part: str) -> AuthorityTier:
    """Resolve a single (already-split, already-stripped) part to a tier.

    Tries exact match first, then prefix match against the first namespace
    segment (e.g. ``awarebot:newfeed`` -> ``awarebot:``). Unknown -> RAW.
    """
    if not part:
        return AuthorityTier.RAW

    part = part.strip().lower()
    if not part:
        return AuthorityTier.RAW

    # 1) Exact match on the full part.
    if part in SOURCE_TIER_MAP:
        return SOURCE_TIER_MAP[part]

    # 2) Multi-segment exact match — try progressively shorter colon prefixes
    #    so 'council:youtube:ytc-dedicated-xyz' falls back to 'council:youtube'
    #    and then 'council'.
    segs = part.split(":")
    while len(segs) > 1:
        segs.pop()
        candidate = ":".join(segs)
        if candidate in SOURCE_TIER_MAP:
            return SOURCE_TIER_MAP[candidate]

    # 3) First-segment namespace lookup as a final fallback (catches a bare
    #    'awarebot' that didn't match above because every concrete entry
    #    is 'awarebot:...').
    head = part.split(":", 1)[0]
    if head in SOURCE_TIER_MAP:
        return SOURCE_TIER_MAP[head]

    return AuthorityTier.RAW


def tier_for_source(source: str | None) -> AuthorityTier:
    """Classify a raw `unit.source` string into an :class:`AuthorityTier`.

    Handles:
    - exact lookup
    - prefix lookup (`awarebot:newsource` -> SCANNER)
    - comma-joined consolidation sources (`a,b,c` -> max-tier wins)
    - leading transparent prefixes like ``consolidation:``

    Unknown sources fall back to :attr:`AuthorityTier.RAW`.
    """
    if not source:
        return AuthorityTier.RAW

    raw = source.strip().lower()
    if not raw:
        return AuthorityTier.RAW

    # Fast path — exact full-string hit.
    if raw in SOURCE_TIER_MAP:
        return SOURCE_TIER_MAP[raw]

    # Strip a leading 'consolidation:' before splitting, so the whole label
    # 'consolidation:awarebot:reddit,council:claude' becomes the parts
    # ['awarebot:reddit', 'council:claude'] for max-tier resolution.
    stripped = _strip_transparent(raw)

    parts = [_strip_transparent(p.strip()) for p in stripped.split(",") if p.strip()]
    if not parts:
        return AuthorityTier.RAW

    return AuthorityTier(max(int(_resolve_single(p)) for p in parts))


def authority_weight(tier: "AuthorityTier | int | None") -> float:
    """Convert a tier into a multiplicative salience weight in [0.1, 1.0].

    Linear mapping: 10 -> 0.10, 100 -> 1.00. Anything outside that range
    clamps to the bounds. ``None`` is treated as RAW (the safe default).
    """
    if tier is None:
        val = int(AuthorityTier.RAW)
    elif isinstance(tier, AuthorityTier):
        val = int(tier)
    else:
        try:
            val = int(tier)
        except (TypeError, ValueError):
            val = int(AuthorityTier.RAW)
    return max(0.1, min(1.0, val / 100.0))


def authority_weight_for_source(source: str | None) -> float:
    """Shortcut: classify + weight in one call."""
    return authority_weight(tier_for_source(source))


def tier_at_least(tier: AuthorityTier | int, floor: AuthorityTier | int | str) -> bool:
    """True iff `tier` is at or above `floor`.

    `floor` may be a tier value, an ``AuthorityTier``, or a tier name
    (case-insensitive: "council", "natrix", ...).
    """
    if isinstance(floor, str):
        try:
            floor_val = int(TIER_BY_NAME[floor.strip().lower()])
        except KeyError:
            raise ValueError(
                f"unknown authority tier name: {floor!r} "
                f"(valid: {sorted(TIER_BY_NAME)})"
            )
    else:
        floor_val = int(floor)
    return int(tier) >= floor_val


# ---------------------------------------------------------------------------
# Backfill migration
# ---------------------------------------------------------------------------


async def backfill_authority_tiers(memory_store: "MemoryStore") -> dict:
    """Walk every persisted MemUnit and stamp ``metadata.authority_tier``.

    Idempotent — units that already have an ``authority_tier`` in their
    metadata are left alone (unless `force=True` is added in the future).
    Persists by atomic rewrite via the store's `_rewrite_units()`.

    Returns
    -------
    dict
        ``{
            "updated": int,
            "scanned": int,
            "already_set": int,
            "by_tier": {tier_name: count, ...},   # full distribution after backfill
            "newly_tiered_by_tier": {tier_name: count, ...},
        }``
    """
    # Acquire the exclusive write lock so a concurrent `create_unit` either
    # lands before our snapshot or blocks until after our rewrite — same
    # pattern store.consolidate() uses.
    await memory_store._acquire_write()
    try:
        units = await memory_store._load_all_units()
        if not units:
            return {
                "updated": 0,
                "scanned": 0,
                "already_set": 0,
                "by_tier": {t.name.lower(): 0 for t in AuthorityTier},
                "newly_tiered_by_tier": {t.name.lower(): 0 for t in AuthorityTier},
            }

        updated = 0
        already = 0
        newly_by_tier: Counter[str] = Counter()
        final_by_tier: Counter[str] = Counter()

        for unit in units:
            meta = getattr(unit, "metadata", None)
            if not isinstance(meta, dict):
                meta = {}
                unit.metadata = meta

            if "authority_tier" in meta:
                already += 1
                try:
                    tier = AuthorityTier(int(meta["authority_tier"]))
                except (ValueError, TypeError):
                    tier = tier_for_source(unit.source)
                    meta["authority_tier"] = int(tier)
                    updated += 1
                    newly_by_tier[tier.name.lower()] += 1
            else:
                tier = tier_for_source(unit.source)
                meta["authority_tier"] = int(tier)
                updated += 1
                newly_by_tier[tier.name.lower()] += 1

            final_by_tier[tier.name.lower()] += 1

        if updated > 0:
            await memory_store._rewrite_units(units)
            log.info(
                "authority backfill: updated=%d already_set=%d scanned=%d",
                updated, already, len(units),
            )
        else:
            log.info(
                "authority backfill: no-op (already_set=%d scanned=%d)",
                already, len(units),
            )

        return {
            "updated": updated,
            "scanned": len(units),
            "already_set": already,
            "by_tier": {t.name.lower(): final_by_tier.get(t.name.lower(), 0)
                        for t in AuthorityTier},
            "newly_tiered_by_tier": {t.name.lower(): newly_by_tier.get(t.name.lower(), 0)
                                     for t in AuthorityTier},
        }
    finally:
        memory_store._release_write()


# ---------------------------------------------------------------------------
# Read helpers used by the API layer (kept here so the routing layer can
# stay thin).
# ---------------------------------------------------------------------------


def filter_by_min_tier(units: Iterable, min_tier: AuthorityTier | int | str) -> list:
    """Return only units whose authority_tier >= `min_tier`.

    Units missing the metadata field fall back to ``tier_for_source`` so
    the endpoint stays useful even before the backfill has run.
    """
    if isinstance(min_tier, str):
        try:
            floor = int(TIER_BY_NAME[min_tier.strip().lower()])
        except KeyError:
            raise ValueError(f"unknown authority tier name: {min_tier!r}")
    else:
        floor = int(min_tier)

    out = []
    for u in units:
        meta = getattr(u, "metadata", None) or {}
        tv = meta.get("authority_tier")
        if tv is None:
            tv = int(tier_for_source(getattr(u, "source", "")))
        try:
            if int(tv) >= floor:
                out.append(u)
        except (TypeError, ValueError):
            continue
    return out
