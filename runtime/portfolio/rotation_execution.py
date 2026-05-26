"""
NCL Rotation Execution — Wave 14J Phase 4 (J3a + J3b + J3c)

Turns the Wave 14I rotation backend (RRG, breadth, cycle phase) into
execution discipline:

  J3a — Pacing rule: 1/3 initial / 1/3 confirm / 1/3 retest
        ETF first (5d Leading required) → graduate to top names
        Counter-trend ideas allowed only if explicitly labeled

  J3b — Breadth veto: if breadth_pct < 40, the brief should NOT
        propose new directional rotation trades on Leading-quadrant
        sectors. The leadership is too narrow to trust.

  J3c — Counter-trend P&L bucket: every trade idea tied to a quadrant
        gets `rotation_stance: with-trend | counter-trend | neutral`.
        Expectancy tracker rolls counter-trend P&L separately so the
        operator can see whether contrarian calls actually outperform.

Reads from runtime/intelligence/rotation_tracker (load_latest_rotation)
+ runtime/intelligence/cycle_phase (load_latest_cycle).

Public surface:
  - pacing_plan(ticker, sector_etf, quadrant_data) -> dict
      returns {stage_1, stage_2, stage_3} sizing + conditions
  - breadth_veto_check(breadth_pct, threshold=40) -> tuple[bool, reason]
  - classify_stance(idea_quadrant, idea_direction) -> str
"""

from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger("ncl.portfolio.rotation_execution")

BREADTH_VETO_THRESHOLD = float(os.getenv("NCL_BREADTH_VETO_PCT", "40"))
PACING_CONFIRM_DAYS = int(os.getenv("NCL_PACING_CONFIRM_DAYS", "5"))


def pacing_plan(
    ticker: str,
    quadrant: Optional[str],
    days_in_quadrant: Optional[int] = None,
) -> dict:
    """Propose a three-stage entry plan for a ticker tied to a rotation
    quadrant. The 'effective' size at any stage is the operator's
    intended R times the stage fraction.

    Stages:
      Stage 1 (1/3 R): immediate entry on the rotation signal
      Stage 2 (1/3 R): on 5d-confirmed Leading status
      Stage 3 (1/3 R): on a constructive retest of the initial entry

    The pacing rule is the most-skipped retail discipline. Building it
    into the brief output means trade ideas SHIP with the staging plan
    rather than the operator having to apply it manually.
    """
    q = (quadrant or "").lower()
    d = days_in_quadrant or 0
    if q == "leading":
        if d >= PACING_CONFIRM_DAYS:
            # Already confirmed — stage 1 + stage 2 both eligible
            return {
                "stage_1": {"fraction": 1 / 3, "condition": "immediate", "eligible": True},
                "stage_2": {
                    "fraction": 1 / 3,
                    "condition": f"5d-confirm Leading (currently {d}d) — eligible NOW",
                    "eligible": True,
                },
                "stage_3": {
                    "fraction": 1 / 3,
                    "condition": "constructive retest of stage 1 entry zone",
                    "eligible": False,
                },
                "notes": (
                    f"{ticker} Leading {d}d (>= {PACING_CONFIRM_DAYS}d confirmation). "
                    f"Pacing: 2/3 R now eligible; final 1/3 on retest."
                ),
            }
        # Brand-new Leading — only stage 1
        return {
            "stage_1": {"fraction": 1 / 3, "condition": "immediate", "eligible": True},
            "stage_2": {
                "fraction": 1 / 3,
                "condition": f"wait for {PACING_CONFIRM_DAYS}d of confirmed Leading",
                "eligible": False,
            },
            "stage_3": {
                "fraction": 1 / 3,
                "condition": "constructive retest of stage 1 entry zone",
                "eligible": False,
            },
            "notes": (
                f"{ticker} Leading only {d}d. Pacing: 1/3 R now; "
                f"hold 2/3 R for confirmation + retest."
            ),
        }
    if q == "improving":
        return {
            "stage_1": {
                "fraction": 1 / 3,
                "condition": "Improving quadrant — small initial",
                "eligible": True,
            },
            "stage_2": {
                "fraction": 1 / 3,
                "condition": "promotion to Leading quadrant",
                "eligible": False,
            },
            "stage_3": {
                "fraction": 1 / 3,
                "condition": "Leading confirmed + retest",
                "eligible": False,
            },
            "notes": (
                f"{ticker} Improving — not Leading yet. Take only 1/3 R; "
                f"upgrades unlock more size."
            ),
        }
    # Lagging / Weakening / unknown
    return {
        "stage_1": {"fraction": 0.0, "condition": "no with-trend setup", "eligible": False},
        "stage_2": {"fraction": 0.0, "condition": "no with-trend setup", "eligible": False},
        "stage_3": {"fraction": 0.0, "condition": "no with-trend setup", "eligible": False},
        "notes": (
            f"{ticker} quadrant={q or 'unknown'}. Not a with-trend rotation setup. "
            f"Any entry here is COUNTER-TREND and must be explicitly labeled."
        ),
    }


def breadth_veto_check(
    breadth_pct: Optional[float],
    threshold: float = BREADTH_VETO_THRESHOLD,
) -> tuple[bool, str]:
    """Returns (vetoed, reason).

    Veto = breadth is too narrow to trust the rotation signal. When
    breadth < threshold (default 40%), the brief should NOT propose
    new with-trend rotation entries; the leadership is too thin and
    the regime may flip.
    """
    if breadth_pct is None:
        return False, "breadth data unavailable — no veto"
    if breadth_pct < threshold:
        return True, (
            f"Breadth veto: {breadth_pct:.1f}% of sectors above 50d SMA, "
            f"below {threshold:.0f}% threshold. Rotation signal is too narrow "
            f"to trust for new with-trend entries."
        )
    return False, f"Breadth OK: {breadth_pct:.1f}% >= {threshold:.0f}% threshold"


def classify_stance(
    idea_sector_etf: Optional[str],
    idea_direction: Optional[str],
    leading_etfs: list[str],
    lagging_etfs: list[str],
) -> str:
    """Classify a trade idea as with-trend / counter-trend / neutral
    based on its sector ETF + direction vs the current rotation
    quadrant set.

    Returns one of: "with_trend" | "counter_trend" | "neutral"

    - LONG idea on a Leading-quadrant sector ETF -> with_trend
    - LONG idea on a Lagging-quadrant sector ETF -> counter_trend
    - SHORT idea on a Lagging-quadrant sector ETF -> with_trend
    - SHORT idea on a Leading-quadrant sector ETF -> counter_trend
    - Anything else / non-sector / Improving/Weakening -> neutral
    """
    etf = (idea_sector_etf or "").upper()
    direction = (idea_direction or "long").lower()
    if not etf:
        return "neutral"
    if direction in ("long", "bullish"):
        if etf in leading_etfs:
            return "with_trend"
        if etf in lagging_etfs:
            return "counter_trend"
    elif direction in ("short", "bearish"):
        if etf in lagging_etfs:
            return "with_trend"
        if etf in leading_etfs:
            return "counter_trend"
    return "neutral"


def annotate_trade_idea(
    idea: dict,
    rotation_snapshot: Optional[dict] = None,
) -> dict:
    """Apply rotation-aware annotations to a trade idea in-place.

    Adds:
      - rotation_stance       — with_trend / counter_trend / neutral
      - rotation_pacing       — full pacing_plan() output
      - breadth_veto          — {vetoed: bool, reason: str}
      - rotation_quadrant     — Leading / Improving / Weakening / Lagging / None

    No-op if rotation_snapshot is None (load via runtime.intelligence
    .rotation_tracker.load_latest_rotation in the caller — keeping this
    function pure for testability).
    """
    if rotation_snapshot is None:
        idea.setdefault("rotation_stance", "neutral")
        return idea

    by_quad = (rotation_snapshot or {}).get("by_quadrant") or {}
    leading = list(by_quad.get("Leading") or [])
    lagging = list(by_quad.get("Lagging") or [])
    improving = list(by_quad.get("Improving") or [])
    weakening = list(by_quad.get("Weakening") or [])
    breadth_pct = ((rotation_snapshot or {}).get("breadth") or {}).get("pct")

    etf = (idea.get("sector_etf") or "").upper()
    quadrant = None
    if etf in leading:
        quadrant = "Leading"
    elif etf in improving:
        quadrant = "Improving"
    elif etf in weakening:
        quadrant = "Weakening"
    elif etf in lagging:
        quadrant = "Lagging"

    stance = classify_stance(
        idea.get("sector_etf"),
        idea.get("direction"),
        leading_etfs=leading,
        lagging_etfs=lagging,
    )
    pacing = pacing_plan(
        idea.get("ticker") or "",
        quadrant=quadrant,
        days_in_quadrant=idea.get("days_in_quadrant"),
    )
    vetoed, reason = breadth_veto_check(breadth_pct)

    idea["rotation_quadrant"] = quadrant
    idea["rotation_stance"] = stance
    idea["rotation_pacing"] = pacing
    idea["breadth_veto"] = {"vetoed": vetoed, "reason": reason}
    return idea
