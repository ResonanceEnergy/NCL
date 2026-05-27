"""
NCL Polymarket Agent — Wave 14R

Autonomous paper-betting agent for Polymarket prediction markets. Mirrors
the Wave 14K auto-trader pattern but specialized for binary 0/1 outcomes
with hard resolution deadlines.

Architecture:
  R1 — state.py            operator-controlled active/paused
       capability_registry polymarket entry (in capability_registry.py)
  R2 — collector_loop.py   ncl-poly-collector (15min) persists Gamma feed
  R3 — edge_engine.py      joins predictions ↔ markets, computes edge_pp
  R4 — paper_engine.py     binary 0/1 paper betting + endDate resolution
  R5 — loop.py             5min decision loop (edge → kelly → bet)
       outcome_attributor  on resolution → bandit + drift + calibration
  R6 — eod_summary.py      daily attribution journal entry
       routes.py           REST endpoints under /polymarket-agent/*
  R7 — iOS PolymarketAgentView

HARD CONSTRAINT: paper bets only, never live money. The agent provides
decision support for the operator who can place real bets manually.
"""

from .state import (
    PolymarketAgentState,
    get_state,
    update_state,
    is_active,
    set_paused,
    set_resumed,
)
from .paper_engine import PolymarketPaperBet, PolymarketPaperEngine, get_engine
from .edge_engine import compute_edges, EdgeOpportunity
from .collector_loop import poly_collector_loop
from .loop import poly_decision_loop, poly_resolution_loop
from .eod_summary import build_eod_summary

__all__ = [
    "PolymarketAgentState",
    "get_state",
    "update_state",
    "is_active",
    "set_paused",
    "set_resumed",
    "PolymarketPaperBet",
    "PolymarketPaperEngine",
    "get_engine",
    "compute_edges",
    "EdgeOpportunity",
    "poly_collector_loop",
    "poly_decision_loop",
    "poly_resolution_loop",
    "build_eod_summary",
]
