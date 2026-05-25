"""
Portfolio Analyst Agent — runs nightly inside Night Watch.

Mandate: maximize capital inflow into NATRIX's accounts, limit capital
outflow. Deterministic-first (all numeric metrics computed in Python),
LLM-narrated (Sonnet 4 produces trim/add recommendations + capital-flow
prose). Output is one ``nightly_report.json`` artifact consumed by the
Morning Brief as primary context.

See design brief in tasks #147/#148 for the full architecture and the
research that informed it.

Public surface
--------------
    from runtime.portfolio.analyst import PortfolioAnalystAgent

    agent = PortfolioAnalystAgent(
        portfolio_manager=portfolio_manager,
        memory_store=memory_store,
        cost_tracker=cost_tracker,
        data_dir=Path("~/dev/NCL/data"),
    )
    report = await agent.run()  # -> NightlyReport
"""

from __future__ import annotations

from .agent import PortfolioAnalystAgent
from .schema import NightlyReport
from .theses import (
    Evidence,
    EvidenceKind,
    ExitPlan,
    Mandate,
    PositionThesis,
    ThesisEvaluationResult,
    ThesisStatus,
    WatchItem,
)
from .thesis_evaluator import apply_evaluation, evaluate as evaluate_thesis
from .thesis_store import ThesisStore

__all__ = [
    "PortfolioAnalystAgent",
    "NightlyReport",
    "PositionThesis",
    "Mandate",
    "ThesisStatus",
    "ExitPlan",
    "WatchItem",
    "Evidence",
    "EvidenceKind",
    "ThesisEvaluationResult",
    "ThesisStore",
    "evaluate_thesis",
    "apply_evaluation",
]
