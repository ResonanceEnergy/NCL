"""Data models for NCL Intelligence Engine.

Structured signal and brief types that carry quantitative data,
not just text blobs with static importance scores.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
import uuid


class SourceType(str, Enum):
    """Intelligence data source types."""
    GOOGLE_TRENDS = "google_trends"
    POLYMARKET = "polymarket"
    NEWS = "news"
    X_SOCIAL = "x"
    YOUTUBE = "youtube"
    REDDIT = "reddit"
    MARKET_DATA = "market_data"
    OPTIONS_FLOW = "options_flow"
    CRYPTO = "crypto"
    ONCHAIN = "onchain"


class SignalDirection(str, Enum):
    """Directional signal."""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    EXPANDING = "expanding"    # Market/sector growing
    CONTRACTING = "contracting"  # Market/sector shrinking
    EMERGING = "emerging"      # New trend detected


class IntelSignal(BaseModel):
    """
    A single structured intelligence signal from any source.

    Unlike the old InsightSignal which had hardcoded relevance scores,
    this carries actual quantitative data from the source.
    """
    signal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: SourceType
    category: str = ""  # e.g. "crypto", "ai", "politics", "macro"
    title: str = ""
    content: str = ""
    direction: SignalDirection = SignalDirection.NEUTRAL

    # Quantitative data (source-specific)
    value: Optional[float] = None          # e.g. trend score, probability, price
    change_pct: Optional[float] = None     # % change over period
    volume: Optional[float] = None         # trading volume, search volume, etc.
    confidence: float = 0.0                # 0-1, how reliable is this signal

    # Context
    url: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def importance_score(self) -> float:
        """
        Dynamic importance scoring based on actual signal data.

        Not a static weight — computed from the signal's own quantitative properties.
        """
        score = 0.0

        # Large moves are important
        if self.change_pct is not None:
            abs_change = abs(self.change_pct)
            if abs_change > 50:
                score += 40
            elif abs_change > 20:
                score += 30
            elif abs_change > 10:
                score += 20
            elif abs_change > 5:
                score += 10

        # High confidence signals matter more
        score += self.confidence * 25

        # Non-neutral direction signals are more actionable
        if self.direction not in (SignalDirection.NEUTRAL,):
            score += 15

        # Emerging trends get a novelty bonus
        if self.direction == SignalDirection.EMERGING:
            score += 10

        # Volume-backed signals carry more weight
        if self.volume and self.volume > 0:
            score += 10

        return min(100.0, max(0.0, score))


class TrendSignal(IntelSignal):
    """Google Trends specific signal."""
    search_term: str = ""
    trend_direction: str = ""  # "rising", "breakout", "stable", "declining"
    related_queries: list[str] = Field(default_factory=list)
    geo: str = "US"


class PredictionMarketSignal(IntelSignal):
    """Polymarket / prediction market signal."""
    market_question: str = ""
    yes_price: float = 0.5
    no_price: float = 0.5
    market_volume: float = 0.0
    volume_24h: float = 0.0
    price_change_24h: Optional[float] = None


class MarketSignal(IntelSignal):
    """Market/crypto price signal."""
    symbol: str = ""
    current_price: float = 0.0
    high_period: float = 0.0
    low_period: float = 0.0
    market_cap: Optional[float] = None
    rsi: Optional[float] = None
    macd_histogram: Optional[float] = None


class NewsSignal(IntelSignal):
    """News article signal."""
    headline: str = ""
    source_name: str = ""
    published_at: Optional[datetime] = None
    sentiment: float = 0.0  # -1 to 1


class SocialSignal(IntelSignal):
    """Social media signal (X, Reddit, YouTube)."""
    platform: str = ""
    engagement: int = 0  # likes + shares + comments
    author_followers: int = 0
    sentiment: float = 0.0  # -1 to 1


class SectorSnapshot(BaseModel):
    """Snapshot of a sector/theme across all data sources."""
    sector: str
    direction: SignalDirection
    signal_count: int = 0
    avg_confidence: float = 0.0
    top_signals: list[IntelSignal] = Field(default_factory=list)
    summary: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IntelBrief(BaseModel):
    """
    Daily/periodic intelligence brief — the final output product.

    This is what NATRIX actually reads. Not raw signals,
    but synthesized, ranked, actionable intelligence.
    """
    brief_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    brief_type: str = "daily"  # "daily", "alert", "strategic_review"

    # Executive summary (LLM-generated)
    executive_summary: str = ""

    # Sector snapshots
    sectors: list[SectorSnapshot] = Field(default_factory=list)

    # Top actionable signals (ranked)
    top_signals: list[IntelSignal] = Field(default_factory=list)

    # Predictions with crowd probabilities
    predictions: list[dict[str, Any]] = Field(default_factory=list)

    # What's hot / trending
    trending: list[dict[str, Any]] = Field(default_factory=list)

    # Market expansion/contraction signals
    market_movements: list[dict[str, Any]] = Field(default_factory=list)

    # Risk alerts
    risk_alerts: list[str] = Field(default_factory=list)

    # Source stats
    source_counts: dict[str, int] = Field(default_factory=dict)
    total_signals_processed: int = 0

    def to_text(self) -> str:
        """Format brief as readable text for NATRIX."""
        lines = []
        lines.append("=" * 64)
        lines.append(f"  NCL INTELLIGENCE BRIEF — {self.timestamp.strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append(f"  Type: {self.brief_type.upper()} | Signals processed: {self.total_signals_processed}")
        lines.append("=" * 64)
        lines.append("")

        if self.executive_summary:
            lines.append("── EXECUTIVE SUMMARY ──────────────────────────────────")
            lines.append(self.executive_summary)
            lines.append("")

        if self.trending:
            lines.append("── WHAT'S HOT ─────────────────────────────────────────")
            for t in self.trending[:8]:
                name = t.get("term", t.get("title", ""))
                score = t.get("score", t.get("change_pct", ""))
                direction = t.get("direction", "")
                lines.append(f"  {name:30s}  {direction:12s}  {score}")
            lines.append("")

        if self.predictions:
            lines.append("── PREDICTION MARKETS ─────────────────────────────────")
            for p in self.predictions[:8]:
                q = p.get("question", "")[:55]
                prob = p.get("probability", 0)
                vol = p.get("volume", 0)
                lines.append(f"  {q:55s}  {prob:5.1%}  vol=${vol:,.0f}")
            lines.append("")

        if self.market_movements:
            lines.append("── MARKET MOVEMENTS ───────────────────────────────────")
            for m in self.market_movements[:10]:
                sym = m.get("symbol", "")
                change = m.get("change_pct", 0)
                arrow = "+" if change > 0 else ""
                price = m.get("price", 0)
                lines.append(f"  {sym:12s}  ${price:>10,.2f}  {arrow}{change:.1f}%")
            lines.append("")

        if self.sectors:
            lines.append("── SECTOR ANALYSIS ────────────────────────────────────")
            for s in self.sectors[:6]:
                lines.append(f"  {s.sector:20s}  {s.direction.value:12s}  "
                             f"signals={s.signal_count}  conf={s.avg_confidence:.0%}")
                if s.summary:
                    lines.append(f"    {s.summary}")
            lines.append("")

        if self.risk_alerts:
            lines.append("── RISK ALERTS ────────────────────────────────────────")
            for alert in self.risk_alerts:
                lines.append(f"  [!] {alert}")
            lines.append("")

        lines.append("── SOURCES ────────────────────────────────────────────")
        for src, count in sorted(self.source_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {src:20s}  {count} signals")
        lines.append("")
        lines.append("=" * 64)

        return "\n".join(lines)
