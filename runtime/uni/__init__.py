"""UNI Research Cortex — Deep research agent for NCL brain.

The UNI Cortex complements Awarebot's surface scanning with deep,
multi-step research intelligence. It plans, gathers, analyzes, and
synthesizes findings from multiple source types.

Core Components:
  - ResearchCortex: Main orchestrator
  - ResearchPlanner: Query decomposition and planning
  - ResearchGatherer: Multi-source collection
  - ResearchSynthesizer: Analysis and synthesis

Models:
  - ResearchTask: Input task specification
  - ResearchResult: Complete research output
  - ResearchBrief: Executive summary
  - ResearchDepth, ResearchStatus, SourceType: Enums
"""

from .cortex import ResearchCortex
from .models import (
    Finding,
    ResearchBrief,
    ResearchDepth,
    ResearchResult,
    ResearchStats,
    ResearchStatus,
    ResearchTask,
    SourceResult,
    SourceType,
)


__all__ = [
    "ResearchCortex",
    "ResearchTask",
    "ResearchResult",
    "ResearchBrief",
    "ResearchDepth",
    "ResearchStatus",
    "ResearchStats",
    "SourceType",
    "SourceResult",
    "Finding",
]
