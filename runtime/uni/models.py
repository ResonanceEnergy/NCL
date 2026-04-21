"""UNI Research Cortex — deep research agent models.

The UNI Cortex handles multi-step, deep research tasks that go beyond
surface-level scanning. It plans research strategies, decomposes queries,
synthesizes findings, and produces structured research briefs.

Research Architecture:
  PLANNER    — Decomposes query into sub-questions, creates execution plan
  GATHERER   — Collects sources from web, academic, internal, market data
  SYNTHESIZER — Analyzes sources, extracts findings, produces consensus
  CORTEX     — Orchestrates the full pipeline, manages task lifecycle

Depth Modes:
  QUICK (1-2)      → Fast validation of a claim (5-10 min)
  STANDARD (3-5)   → Balanced research (15-30 min)
  DEEP (5-10)      → Comprehensive analysis (30-60 min)
  EXHAUSTIVE (10+) → Exhaustive coverage (60+ min)
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid as _uuid

from pydantic import BaseModel, Field


# ────────────────────────────────────────────────────────────────────────────
# Enums
# ────────────────────────────────────────────────────────────────────────────


class SourceType(str, Enum):
    """Source type for research gathering."""

    WEB = "web"                    # General web search results
    ACADEMIC = "academic"          # Peer-reviewed papers, scholarly sources
    NEWS = "news"                  # News articles, journalistic sources
    SOCIAL = "social"              # Social media, forums, discussions
    INTERNAL = "internal"          # NCL memory, internal documents
    MARKET_DATA = "market_data"    # Market research, financial data


class ResearchDepth(str, Enum):
    """Research depth/scope level."""

    QUICK = "quick"            # 1-2 sources, minimal analysis
    STANDARD = "standard"      # 3-5 sources, balanced coverage
    DEEP = "deep"              # 5-10 sources, comprehensive analysis
    EXHAUSTIVE = "exhaustive"  # 10+ sources, exhaustive coverage


class ResearchStatus(str, Enum):
    """Research task lifecycle status."""

    QUEUED = "queued"
    PLANNING = "planning"
    GATHERING = "gathering"
    ANALYZING = "analyzing"
    SYNTHESIZING = "synthesizing"
    COMPLETE = "complete"
    FAILED = "failed"


# ────────────────────────────────────────────────────────────────────────────
# Task & Input Models
# ────────────────────────────────────────────────────────────────────────────


class ResearchTask(BaseModel):
    """Research task request with planning constraints."""

    task_id: str = Field(
        default_factory=lambda: str(_uuid.uuid4()),
        description="Unique task identifier",
    )
    query: str = Field(..., description="Research query / question to investigate")
    depth: ResearchDepth = Field(
        default=ResearchDepth.STANDARD,
        description="Research depth level (quick/standard/deep/exhaustive)",
    )
    sources_requested: list[SourceType] = Field(
        default_factory=lambda: [SourceType.WEB, SourceType.ACADEMIC, SourceType.NEWS],
        description="Preferred source types to prioritize",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Rich context data (domain, industry, time period, etc.)",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Research constraints (e.g., 'exclude opinion pieces', 'focus on 2024+', 'US market only')",
    )
    deadline: Optional[datetime] = Field(
        default=None,
        description="Optional deadline for research completion",
    )
    priority: int = Field(
        default=5, ge=1, le=10,
        description="Priority level 1-10 (10 = urgent)",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Task creation timestamp",
    )
    status: ResearchStatus = Field(
        default=ResearchStatus.QUEUED,
        description="Current status in research pipeline",
    )


# ────────────────────────────────────────────────────────────────────────────
# Source & Finding Models
# ────────────────────────────────────────────────────────────────────────────


class SourceResult(BaseModel):
    """Single research source with quality scores."""

    source_id: str = Field(
        default_factory=lambda: str(_uuid.uuid4()),
        description="Unique source identifier",
    )
    source_type: SourceType = Field(..., description="Type of source")
    url: Optional[str] = Field(
        default=None,
        description="Source URL (if applicable)",
    )
    title: str = Field(..., description="Source title")
    content: str = Field(..., description="Source content / summary")
    relevance_score: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="Relevance to query (0-1, higher = more relevant)",
    )
    credibility_score: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="Source credibility (0-1, higher = more trustworthy)",
    )
    extracted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this source was extracted",
    )


class Finding(BaseModel):
    """Extracted finding from research sources."""

    finding_id: str = Field(
        default_factory=lambda: str(_uuid.uuid4()),
        description="Unique finding identifier",
    )
    claim: str = Field(..., description="Core claim or insight")
    evidence: list[str] = Field(
        default_factory=list,
        description="Supporting evidence snippets from sources",
    )
    confidence: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="Confidence in this finding (0-1)",
    )
    sources: list[str] = Field(
        default_factory=list,
        description="Source IDs supporting this finding",
    )
    contradictions: list[str] = Field(
        default_factory=list,
        description="Contradicting claims from other sources",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Semantic tags (e.g., 'risk', 'opportunity', 'trend')",
    )


# ────────────────────────────────────────────────────────────────────────────
# Output Models
# ────────────────────────────────────────────────────────────────────────────


class ResearchResult(BaseModel):
    """Complete research result with findings and synthesis."""

    task_id: str = Field(..., description="Originating task ID")
    query: str = Field(..., description="Original research query")
    status: ResearchStatus = Field(..., description="Final status")
    findings: list[Finding] = Field(
        default_factory=list,
        description="Extracted findings from research",
    )
    synthesis: str = Field(
        default="",
        description="Synthesized narrative explaining findings and implications",
    )
    key_takeaways: list[str] = Field(
        default_factory=list,
        description="Key takeaways (3-5 main points)",
    )
    sources_consulted: list[SourceResult] = Field(
        default_factory=list,
        description="All sources gathered and analyzed",
    )
    confidence_score: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="Overall confidence in research (0-1)",
    )
    research_plan: dict[str, Any] = Field(
        default_factory=dict,
        description="Execution plan used (sub_questions, source_strategy, etc.)",
    )
    duration_ms: int = Field(
        default=0, ge=0,
        description="Total research duration in milliseconds",
    )
    model_used: str = Field(
        default="claude",
        description="Primary AI model used for synthesis",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Research start time",
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Research completion time",
    )


class ResearchBrief(BaseModel):
    """Executive brief distilled from research result."""

    brief_id: str = Field(
        default_factory=lambda: str(_uuid.uuid4()),
        description="Unique brief identifier",
    )
    title: str = Field(..., description="Brief title")
    executive_summary: str = Field(
        ..., description="1-paragraph executive summary",
    )
    findings: list[Finding] = Field(
        default_factory=list,
        description="Key findings (condensed)",
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Actionable recommendations (3-5)",
    )
    risk_factors: list[str] = Field(
        default_factory=list,
        description="Key risks and uncertainties",
    )
    confidence: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="Overall confidence level",
    )
    sources_count: int = Field(
        default=0, ge=0,
        description="Number of sources consulted",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Brief creation timestamp",
    )


# ────────────────────────────────────────────────────────────────────────────
# Statistics Models
# ────────────────────────────────────────────────────────────────────────────


class ResearchStats(BaseModel):
    """Aggregate research statistics."""

    total_tasks: int = Field(default=0, ge=0)
    avg_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    avg_duration_ms: int = Field(default=0, ge=0)
    source_type_distribution: dict[str, int] = Field(default_factory=dict)
    depth_distribution: dict[str, int] = Field(default_factory=dict)
    success_rate: float = Field(default=0.5, ge=0.0, le=1.0)
