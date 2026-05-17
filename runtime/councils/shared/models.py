"""
Shared data models for YouTube and X councils.

All council output flows into NCL intelligence-scan/ as structured data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


class CouncilSource(str, Enum):
    YOUTUBE = "youtube"
    X_TWITTER = "x"


class SignalCategory(str, Enum):
    CONTENT = "content"
    MARKET = "market"
    GEOPOLITICAL = "geopolitical"
    TECH = "tech"
    MUSIC = "music"
    CULTURE = "culture"
    ALT_SCIENCE = "alt-science"
    GAMING = "gaming"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class VideoMeta:
    """Metadata for a scraped YouTube video."""
    video_id: str
    title: str
    channel: str
    channel_id: str
    upload_date: str
    duration_seconds: int
    url: str
    description: str = ""
    view_count: int = 0
    like_count: int = 0
    tags: list[str] = field(default_factory=list)
    thumbnail_url: str = ""


@dataclass
class TranscriptSegment:
    """A timestamped segment of a transcript."""
    start: float
    end: float
    text: str

    @property
    def timestamp(self) -> str:
        """Format as [MM:SS]."""
        m, s = divmod(int(self.start), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"[{h}:{m:02d}:{s:02d}]"
        return f"[{m:02d}:{s:02d}]"


@dataclass
class Transcript:
    """Full transcript of a video."""
    video_id: str
    segments: list[TranscriptSegment] = field(default_factory=list)
    language: str = "en"
    model_used: str = "whisper-large-v3"

    @property
    def full_text(self) -> str:
        return " ".join(seg.text for seg in self.segments)

    @property
    def timestamped_text(self) -> str:
        return "\n".join(f"{seg.timestamp} {seg.text}" for seg in self.segments)

    @property
    def duration_seconds(self) -> float:
        if not self.segments:
            return 0.0
        return self.segments[-1].end


@dataclass
class XPost:
    """A scraped X/Twitter post."""
    post_id: str
    author_handle: str
    author_name: str
    text: str
    created_at: str
    url: str
    retweet_count: int = 0
    like_count: int = 0
    reply_count: int = 0
    quote_count: int = 0
    impression_count: int = 0
    is_retweet: bool = False
    is_reply: bool = False
    media_urls: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    mentioned_users: list[str] = field(default_factory=list)
    thread_id: Optional[str] = None
    synthetic: bool = False  # True when data is AI-generated (e.g. Grok fallback)


@dataclass
class Insight:
    """A single extracted insight from council analysis."""
    title: str
    description: str
    category: SignalCategory
    confidence: float  # 0.0 - 1.0
    tags: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)  # video IDs or post IDs
    actionable: bool = False
    action_suggestion: str = ""


@dataclass
class CouncilReport:
    """Output from a council session — saved as .md and .json."""
    council_type: CouncilSource
    session_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    period_hours: int = 24
    sources_processed: int = 0
    total_duration_hours: float = 0.0
    insights: list[Insight] = field(default_factory=list)
    summary: str = ""
    raw_analysis: str = ""
    videos: list[VideoMeta] = field(default_factory=list)
    posts: list[XPost] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def save_json(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str))
        return path
