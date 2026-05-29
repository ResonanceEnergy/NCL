"""
NCL Lane Router — Wave 14W-C

Encodes the 5-lane mandates as a pure decision function. Every producer
calls `route(datum)` at write-time. The decision:
  - assigns ONE primary lane (PORTFOLIO/INTEL/MEMORY/CALENDAR/JOURNAL)
  - lists secondary lane cross-references
  - decides whether the write passes the lane's pre-gate (e.g. MEMORY
    write-gate per MEMORY_MANDATE §3)
  - explains the decision so producers + dashboards can audit

The router has NO async, NO memory_store dependency, NO file I/O — it is
pure logic. This keeps it cheap (microseconds per call), testable, and
safe to call from anywhere.

Lane assignment is **source-prefix driven** by default. Producers can
override with `kind=` to force a different lane.

Mandates this module enforces:
  - INTEL_MANDATE.md §4 — pre-gate rules at ingest
  - MEMORY_MANDATE.md §3 — write-time gate (THE key policy)
  - CALENDAR_MANDATE.md §4 — ISO date requirement
  - JOURNAL_MANDATE.md §4 — voice-primacy (always pass NATRIX writes)
  - LANE_ARCHITECTURE.md §2 — "one primary lane per datum" invariant

Public surface:
  Lane                  — enum of 5 lanes + UNKNOWN
  DatumKind             — enum of producer datum types
  LaneRouteDecision     — dataclass returned by route()
  route(datum)          — main entrypoint
  source_to_lane(s)     — quick source-prefix lookup
  apply_memory_gate(d)  — pre-gate decision for memory writes
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


log = logging.getLogger("ncl.lane_router")


# ─────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────


class Lane(str, Enum):
    """The 5 lanes from LANE_ARCHITECTURE.md."""

    PORTFOLIO = "portfolio"
    INTEL = "intel"
    MEMORY = "memory"
    CALENDAR = "calendar"
    JOURNAL = "journal"
    UNKNOWN = "unknown"


class DatumKind(str, Enum):
    """Producer datum types — informs lane assignment + gate rules."""

    AWAREBOT_SIGNAL = "awarebot_signal"
    BRIEF_OUTPUT = "brief_output"
    PREDICTION = "prediction"
    COUNCIL_OUTPUT = "council_output"
    ROTATION_SNAPSHOT = "rotation_snapshot"
    JOURNAL_ENTRY = "journal_entry"
    MORNING_QUIZ = "morning_quiz"
    LIFE_PLAN = "life_plan"
    CALENDAR_EVENT = "calendar_event"
    LUNAR_EVENT = "lunar_event"
    PORTFOLIO_EVENT = "portfolio_event"
    PAPER_TRADE = "paper_trade"
    SCANNER_HIT = "scanner_hit"
    AGENT_REASONING_CHAIN = "agent_reasoning_chain"
    AGENT_OPEN = "agent_open"
    AGENT_CLOSE = "agent_close"
    USER_PIN = "user_pin"
    SYSTEM_AUDIT = "system_audit"
    MANDATE = "mandate"
    NARRATIVE_THREAD = "narrative_thread"
    UNKNOWN = "unknown"


# ─────────────────────────────────────────────────────────────────────
# Source-prefix → Lane map
# ─────────────────────────────────────────────────────────────────────


# Source-prefix routing. Longest-prefix match wins.
# This is the single source of truth for "which lane does X belong to".
SOURCE_PREFIX_LANE: list[tuple[str, Lane]] = [
    # PORTFOLIO lane
    ("portfolio:", Lane.PORTFOLIO),
    ("paper:", Lane.PORTFOLIO),
    ("auto_trader:", Lane.PORTFOLIO),
    ("scanner:goat", Lane.PORTFOLIO),
    ("scanner:bravo", Lane.PORTFOLIO),
    ("strike-point", Lane.PORTFOLIO),
    # INTEL lane
    ("awarebot:", Lane.INTEL),
    ("intel:", Lane.INTEL),
    ("intelligence:", Lane.INTEL),
    ("brief:", Lane.INTEL),
    ("brief_pro:", Lane.INTEL),
    ("rotation:", Lane.INTEL),
    ("cycle_phase:", Lane.INTEL),
    ("style_ratios:", Lane.INTEL),
    ("predictions:", Lane.INTEL),
    ("youtube_council:", Lane.INTEL),
    ("council_youtube:", Lane.INTEL),
    ("morning_brief:", Lane.INTEL),
    # CALENDAR lane
    ("calendar:", Lane.CALENDAR),
    ("lunar:", Lane.CALENDAR),
    ("events:", Lane.CALENDAR),
    ("local_events:", Lane.CALENDAR),
    ("ticketmaster:", Lane.CALENDAR),
    ("city_events:", Lane.CALENDAR),
    # JOURNAL lane
    ("journal:", Lane.JOURNAL),
    ("morning_quiz:", Lane.JOURNAL),
    ("weekly_review:", Lane.JOURNAL),
    ("yearly_review:", Lane.JOURNAL),
    ("life:", Lane.JOURNAL),
    ("life_plan:", Lane.JOURNAL),
    ("natrix:", Lane.JOURNAL),
    ("reflection:", Lane.JOURNAL),
    # MEMORY lane (only specific markers — most things land in Memory
    # by promotion from another lane, not because they were born here)
    ("memory:", Lane.MEMORY),
    ("council:", Lane.MEMORY),
    ("mandate:", Lane.MEMORY),
    ("system:", Lane.MEMORY),
    ("user:", Lane.MEMORY),
    ("pin:", Lane.MEMORY),
    ("narrative_thread:", Lane.MEMORY),
    ("first-strike", Lane.MEMORY),  # iOS chat fragments
    ("brain:", Lane.MEMORY),
]


def source_to_lane(source: str) -> Lane:
    """Resolve source string → Lane via longest-prefix match.

    Unknown sources default to MEMORY (conservative — better to land in
    Memory than to silently drop). Producers should pass an explicit
    `kind=` to override.
    """
    if not source:
        return Lane.UNKNOWN
    s = source.lower().strip()
    best: tuple[int, Lane] = (-1, Lane.UNKNOWN)
    for prefix, lane in SOURCE_PREFIX_LANE:
        if s.startswith(prefix):
            if len(prefix) > best[0]:
                best = (len(prefix), lane)
    return best[1] if best[0] > 0 else Lane.UNKNOWN


# ─────────────────────────────────────────────────────────────────────
# DatumKind → Lane (overrides source when set)
# ─────────────────────────────────────────────────────────────────────


KIND_LANE: dict[DatumKind, Lane] = {
    DatumKind.AWAREBOT_SIGNAL: Lane.INTEL,
    DatumKind.BRIEF_OUTPUT: Lane.INTEL,
    DatumKind.PREDICTION: Lane.INTEL,
    DatumKind.ROTATION_SNAPSHOT: Lane.INTEL,
    DatumKind.COUNCIL_OUTPUT: Lane.MEMORY,
    DatumKind.JOURNAL_ENTRY: Lane.JOURNAL,
    DatumKind.MORNING_QUIZ: Lane.JOURNAL,
    DatumKind.LIFE_PLAN: Lane.JOURNAL,
    DatumKind.CALENDAR_EVENT: Lane.CALENDAR,
    DatumKind.LUNAR_EVENT: Lane.CALENDAR,
    DatumKind.PORTFOLIO_EVENT: Lane.PORTFOLIO,
    DatumKind.PAPER_TRADE: Lane.PORTFOLIO,
    DatumKind.SCANNER_HIT: Lane.PORTFOLIO,
    DatumKind.AGENT_REASONING_CHAIN: Lane.PORTFOLIO,
    DatumKind.AGENT_OPEN: Lane.PORTFOLIO,
    DatumKind.AGENT_CLOSE: Lane.PORTFOLIO,
    DatumKind.USER_PIN: Lane.MEMORY,
    DatumKind.SYSTEM_AUDIT: Lane.MEMORY,
    DatumKind.MANDATE: Lane.MEMORY,
    DatumKind.NARRATIVE_THREAD: Lane.MEMORY,
}


# ─────────────────────────────────────────────────────────────────────
# Memory-write gate per MEMORY_MANDATE §3
# ─────────────────────────────────────────────────────────────────────


# Tier thresholds — match MemoryAuthority enum values
TIER_COUNCIL = 80
TIER_BRAIN = 60
TIER_NATRIX = 100

# Memory-gate config (env overridable)
MEMORY_GATE_DISABLED = os.getenv("NCL_LANE_MEMORY_GATE", "1") != "1"
MEMORY_GATE_MIN_IMPORTANCE = float(os.getenv("NCL_LANE_MEMORY_GATE_IMP", "80"))
MEMORY_GATE_MIN_SCORE = float(os.getenv("NCL_LANE_MEMORY_GATE_SCORE", "0.75"))
MEMORY_GATE_MIN_CROSS_SOURCE = int(os.getenv("NCL_LANE_MEMORY_GATE_XSRC", "2"))


def apply_memory_gate(
    *,
    source: str = "",
    kind: Optional[DatumKind] = None,
    importance: float = 0.0,
    score: float = 0.0,
    cross_source: int = 0,
    authority_tier: int = 0,
    tags: Optional[list[str]] = None,
    memory_type: str = "",
) -> tuple[bool, str]:
    """Return (passed, reason). MEMORY_MANDATE §3 write-time gate.

    Gate PASSES when ONE OF:
      - authority_tier ≥ COUNCIL (80) — never gate council/NATRIX output
      - importance ≥ 80 (caller-bumped)
      - composite_score ≥ 0.75 (CRITICAL Awarebot)
      - cross_source ≥ 2 (confirmed by ≥ 2 producers)
      - tags carry operator pin marker
      - kind in {USER_PIN, COUNCIL_OUTPUT, MANDATE, AGENT_REASONING_CHAIN,
                 AGENT_OPEN, AGENT_CLOSE, NARRATIVE_THREAD}
      - memory_type in {procedural, decision, preference} (LML)
      - source begins with always-allowed lane prefix
    """
    if MEMORY_GATE_DISABLED:
        return True, "gate_disabled"

    tags = tags or []
    tags_lower = {str(t).lower() for t in tags}

    # 1. Authority tier ≥ COUNCIL
    if authority_tier >= TIER_COUNCIL:
        return True, f"authority_tier={authority_tier}_≥{TIER_COUNCIL}"

    # 2. Caller bumped importance
    if importance >= MEMORY_GATE_MIN_IMPORTANCE:
        return True, f"importance={importance:.1f}_≥{MEMORY_GATE_MIN_IMPORTANCE}"

    # 3. CRITICAL score
    if score >= MEMORY_GATE_MIN_SCORE:
        return True, f"score={score:.3f}_≥{MEMORY_GATE_MIN_SCORE}"

    # 4. Cross-source confirmation
    if cross_source >= MEMORY_GATE_MIN_CROSS_SOURCE:
        return True, f"cross_source={cross_source}_≥{MEMORY_GATE_MIN_CROSS_SOURCE}"

    # 5. Operator pin
    pin_markers = {"pin", "pinned", "operator_pin", "natrix_pin"}
    if tags_lower & pin_markers:
        return True, "operator_pin_tag"

    # 6. Auto-pass kinds (council/mandate/agent decisions/narrative)
    auto_kinds = {
        DatumKind.USER_PIN,
        DatumKind.COUNCIL_OUTPUT,
        DatumKind.MANDATE,
        DatumKind.AGENT_REASONING_CHAIN,
        DatumKind.AGENT_OPEN,
        DatumKind.AGENT_CLOSE,
        DatumKind.NARRATIVE_THREAD,
        DatumKind.MORNING_QUIZ,  # journal type, important for posture
        DatumKind.LIFE_PLAN,
        DatumKind.SYSTEM_AUDIT,
    }
    if kind in auto_kinds:
        return True, f"kind={kind.value}_auto_pass"

    # 7. Permanent memory types (LML)
    permanent_types = {"procedural", "decision", "preference"}
    if memory_type.lower() in permanent_types:
        return True, f"memory_type={memory_type}_LML"

    # 8. Always-allowed source prefixes (per-lane bypass)
    always_ok_sources = (
        "council:",
        "mandate:",
        "natrix:",
        "system:",
        "user:",
        "pin:",
        "journal:",
        "morning_quiz:",
        "life:",
        "life_plan:",
        "portfolio:auto_trade",
        "portfolio:significant_move",
        "portfolio:cycle_phase",
    )
    s = (source or "").lower()
    for pfx in always_ok_sources:
        if s.startswith(pfx):
            return True, f"source_prefix={pfx}_allowlist"

    # Default: REJECT
    return False, (
        f"gate_reject: score={score:.3f}<{MEMORY_GATE_MIN_SCORE} "
        f"x_src={cross_source}<{MEMORY_GATE_MIN_CROSS_SOURCE} "
        f"imp={importance:.1f}<{MEMORY_GATE_MIN_IMPORTANCE} "
        f"tier={authority_tier}<{TIER_COUNCIL}"
    )


# ─────────────────────────────────────────────────────────────────────
# Decision dataclass
# ─────────────────────────────────────────────────────────────────────


@dataclass
class LaneRouteDecision:
    """The decision packet returned by route()."""

    primary_lane: Lane
    secondary_refs: list[Lane] = field(default_factory=list)
    kind: DatumKind = DatumKind.UNKNOWN
    # Per-lane gate results
    memory_gate_passed: bool = True
    memory_gate_reason: str = ""
    # Audit
    source: str = ""
    explain: str = ""

    def to_dict(self) -> dict:
        return {
            "primary_lane": self.primary_lane.value,
            "secondary_refs": [ln.value for ln in self.secondary_refs],
            "kind": self.kind.value,
            "memory_gate_passed": self.memory_gate_passed,
            "memory_gate_reason": self.memory_gate_reason,
            "source": self.source,
            "explain": self.explain,
        }


# ─────────────────────────────────────────────────────────────────────
# Main entrypoint
# ─────────────────────────────────────────────────────────────────────


def route(
    *,
    source: str = "",
    kind: Optional[DatumKind] = None,
    importance: float = 0.0,
    score: float = 0.0,
    cross_source: int = 0,
    authority_tier: int = 0,
    tags: Optional[list[str]] = None,
    memory_type: str = "",
    secondary_hints: Optional[list[str]] = None,
) -> LaneRouteDecision:
    """Decide which lane a datum belongs in + whether it passes pre-gates.

    Args:
      source: source string (e.g. "awarebot:reddit", "council:session-123")
      kind: optional explicit DatumKind override
      importance: 0-100 caller-set importance
      score: 0-1 composite score (Awarebot only)
      cross_source: number of independent producers confirming
      authority_tier: 0-100 authority tier (COUNCIL=80, NATRIX=100, etc.)
      tags: signal tags
      memory_type: episodic/semantic/procedural/decision/preference/signal
      secondary_hints: optional list of additional lane names

    Returns:
      LaneRouteDecision with primary_lane + memory_gate_passed.
    """
    tags = tags or []

    # 1. Resolve primary lane: kind override wins, else source-prefix
    primary_lane = Lane.UNKNOWN
    if kind is not None and kind in KIND_LANE:
        primary_lane = KIND_LANE[kind]
    if primary_lane == Lane.UNKNOWN:
        primary_lane = source_to_lane(source)
    # Fallback: MEMORY (conservative)
    if primary_lane == Lane.UNKNOWN:
        primary_lane = Lane.MEMORY

    # 2. Secondary refs
    sec: list[Lane] = []
    if secondary_hints:
        for h in secondary_hints:
            try:
                lane = Lane(h.lower())
                if lane != primary_lane and lane not in sec:
                    sec.append(lane)
            except ValueError:
                pass

    # 3. Memory gate — applies when primary_lane is MEMORY OR when the
    #    write is destined for the MemoryStore even if its lane is
    #    elsewhere. Callers explicitly ask for the gate via this function.
    passed, reason = apply_memory_gate(
        source=source,
        kind=kind,
        importance=importance,
        score=score,
        cross_source=cross_source,
        authority_tier=authority_tier,
        tags=tags,
        memory_type=memory_type,
    )

    # 4. Decision
    return LaneRouteDecision(
        primary_lane=primary_lane,
        secondary_refs=sec,
        kind=kind or DatumKind.UNKNOWN,
        memory_gate_passed=passed,
        memory_gate_reason=reason,
        source=source,
        explain=(
            f"lane={primary_lane.value} via "
            f"{'kind' if (kind and kind in KIND_LANE) else 'source'}"
        ),
    )


__all__ = [
    "Lane",
    "DatumKind",
    "LaneRouteDecision",
    "route",
    "source_to_lane",
    "apply_memory_gate",
    "SOURCE_PREFIX_LANE",
    "KIND_LANE",
]
