"""
LDE Data Models — Pydantic schemas for the Living Doctrine Engine.

Core entities:
    - TradingInsight: a single extracted signal from any URL source
    - DoctrineRule: a living rule in the trading doctrine
    - DoctrineSignal: an active signal being monitored
    - TrendMonitor: a trend the doctrine is tracking
    - LivingDoctrine: the full doctrine state (rules + signals + trends + history)
    - SandboxEntry: a single entry in the current-affairs sandbox
    - LDEEvent: event record for the LDE pipeline
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class InsightCategory(str, Enum):
    """Categories of trading insights."""

    MACRO = "macro"  # Macro-economic signals (GDP, rates, inflation)
    COMPANY = "company"  # Company-specific (earnings, guidance, management)
    SENTIMENT = "sentiment"  # Market sentiment shifts
    RISK = "risk"  # Identified risk factors
    OPPORTUNITY = "opportunity"  # Identified alpha opportunities
    GEOPOLITICAL = "geopolitical"  # Geopolitical events affecting markets
    SECTOR = "sector"  # Sector-level rotation / momentum
    TECH = "tech"  # Technology / AI / infrastructure
    TECHNICAL = "technical"  # Technical / flow signals
    REGULATORY = "regulatory"  # Regulatory / policy changes
    CORRELATION = "correlation"  # Cross-asset correlation shifts


class Urgency(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RuleStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class TradingInsight(BaseModel):
    """A single trading-relevant insight extracted from a URL source."""

    insight_id: str = Field(default_factory=lambda: f"ins-{_uuid.uuid4().hex[:12]}")
    title: str = Field(..., description="Concise insight headline")
    signal: str = Field(..., description="What was observed — raw signal")
    analysis: str = Field(default="", description="Why this matters for trading")
    category: InsightCategory = Field(..., description="Signal category")
    confidence: float = Field(ge=0.0, le=10.0, description="Confidence 0-10")
    urgency: Urgency = Field(default=Urgency.MEDIUM)
    tickers: list[str] = Field(default_factory=list, description="Relevant tickers")
    sectors: list[str] = Field(default_factory=list, description="Relevant sectors")
    tags: list[str] = Field(default_factory=list)
    source_url: str = Field(default="")
    source_type: str = Field(default="", description="youtube, article, earnings, interview")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    superseded_by: Optional[str] = Field(
        default=None, description="ID of newer insight that replaces this"
    )


class DoctrineRule(BaseModel):
    """A living rule in the trading doctrine — evolves with new data."""

    rule_id: str = Field(default_factory=lambda: f"rule-{_uuid.uuid4().hex[:8]}")
    title: str = Field(..., description="Rule headline")
    description: str = Field(..., description="Full rule description + rationale")
    category: InsightCategory = Field(...)
    strength: float = Field(ge=0.0, le=10.0, default=5.0, description="How strongly supported 0-10")
    status: RuleStatus = Field(default=RuleStatus.ACTIVE)
    supporting_insights: list[str] = Field(
        default_factory=list, description="Insight IDs that support this rule"
    )
    contradicting_insights: list[str] = Field(
        default_factory=list, description="Insight IDs that challenge this rule"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = Field(
        default=None, description="When this rule should be re-evaluated"
    )
    tickers: list[str] = Field(default_factory=list)
    action: str = Field(default="", description="What to do based on this rule")


class DoctrineSignal(BaseModel):
    """An active signal the doctrine is monitoring."""

    signal_id: str = Field(default_factory=lambda: f"sig-{_uuid.uuid4().hex[:8]}")
    name: str = Field(...)
    description: str = Field(default="")
    category: InsightCategory = Field(...)
    direction: str = Field(default="neutral", description="bullish, bearish, neutral")
    strength: float = Field(ge=0.0, le=10.0, default=5.0)
    tickers: list[str] = Field(default_factory=list)
    first_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_confirmed: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confirmation_count: int = Field(default=1)
    source_insights: list[str] = Field(default_factory=list)


class TrendMonitor(BaseModel):
    """A trend the doctrine is actively tracking."""

    trend_id: str = Field(default_factory=lambda: f"trend-{_uuid.uuid4().hex[:8]}")
    name: str = Field(...)
    description: str = Field(default="")
    category: InsightCategory = Field(...)
    direction: str = Field(
        default="emerging", description="emerging, accelerating, peaking, declining, reversing"
    )
    confidence: float = Field(ge=0.0, le=10.0, default=5.0)
    tickers: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    data_points: int = Field(default=1, description="How many inputs have confirmed this trend")
    first_detected: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    watch_triggers: list[str] = Field(
        default_factory=list, description="Conditions that should trigger action"
    )


class RiskThreshold(BaseModel):
    """A risk threshold that triggers alerts."""

    name: str
    category: str
    current_level: float = Field(ge=0.0, le=10.0, default=5.0)
    alert_level: float = Field(ge=0.0, le=10.0, default=7.0)
    description: str = ""
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LivingDoctrine(BaseModel):
    """
    The Living Trading Doctrine — single source of truth.

    Evolves after every URL input. Contains rules, signals, trends,
    risk thresholds, and full history of how the doctrine changed.
    """

    version: str = Field(default="1.0")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    urls_processed: int = Field(default=0)
    total_insights_extracted: int = Field(default=0)

    # Living components
    core_rules: list[DoctrineRule] = Field(default_factory=list)
    active_signals: list[DoctrineSignal] = Field(default_factory=list)
    monitored_trends: list[TrendMonitor] = Field(default_factory=list)
    risk_thresholds: list[RiskThreshold] = Field(default_factory=list)

    # Evolution history
    history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Chronological record of every doctrine update",
    )

    # Metadata
    top_tickers: list[str] = Field(
        default_factory=list, description="Most frequently referenced tickers"
    )
    market_bias: str = Field(
        default="neutral", description="Overall doctrine bias: bullish, bearish, neutral, mixed"
    )
    confidence_score: float = Field(
        default=5.0, ge=0.0, le=10.0, description="Overall doctrine confidence"
    )


class SandboxEntry(BaseModel):
    """A single entry in the persistent current-affairs sandbox."""

    entry_id: str = Field(default_factory=lambda: f"sb-{_uuid.uuid4().hex[:12]}")
    source_url: str
    source_type: str = ""
    insights: list[TradingInsight] = Field(default_factory=list)
    raw_transcript: str = Field(default="", description="Truncated transcript/text")
    analysis_output: str = Field(default="", description="Analyzer engine output")
    doctrine_changes: str = Field(default="", description="What changed in the doctrine")
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)
