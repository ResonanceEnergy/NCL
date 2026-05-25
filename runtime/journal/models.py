"""Journal data models — Pydantic schemas for entries, reflections, and insights."""

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class EntryType(str, Enum):
    """Types of journal entries."""

    NOTE = "note"  # Quick thought, observation
    RESEARCH = "research"  # Deep research findings
    DECISION = "decision"  # Decision made + rationale
    TECHNIQUE = "technique"  # Tip, trick, procedure learned
    OBSERVATION = "observation"  # Market/signal observation
    REFLECTION = "reflection"  # Daily reflection (auto-generated)
    QUESTION = "question"  # Open question to investigate
    LESSON = "lesson"  # Lesson learned from outcome
    BEST_PRACTICE = "best_practice"  # Documented best practice
    MORNING_QUIZ = "morning_quiz"  # Wave 14E — daily structured intention (~90s)


class JournalEntry(BaseModel):
    """A single journal entry — the operator's knowledge capture."""

    entry_id: str = Field(default_factory=lambda: f"journal-{uuid4().hex[:12]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    entry_type: EntryType = EntryType.NOTE
    title: str = ""
    content: str  # Main body text
    tags: list[str] = Field(default_factory=list)
    related_signals: list[str] = Field(default_factory=list)  # Signal IDs that prompted this
    related_briefs: list[str] = Field(default_factory=list)  # Brief IDs referenced
    source_context: str = ""  # What triggered this entry (chat, brief, alert, manual)
    importance: float = Field(default=50.0, ge=0.0, le=100.0)

    # Auto-extracted by LLM on creation
    key_insights: list[str] = Field(default_factory=list)  # Extracted actionable insights
    research_topics: list[str] = Field(default_factory=list)  # Topics to research further
    linked_sectors: list[str] = Field(default_factory=list)  # Sectors this relates to

    # Metadata
    word_count: int = 0
    has_research: bool = False  # Was deep research triggered from this?
    reinforcement_count: int = 0  # Times this entry was referenced/accessed

    def model_post_init(self, __context) -> None:
        if not self.word_count:
            self.word_count = len(self.content.split())
        if not self.title and self.content:
            # Auto-generate title from first line
            first_line = self.content.strip().split("\n")[0]
            self.title = first_line[:120].rstrip(".")


class DailyReflection(BaseModel):
    """Auto-generated end-of-day synthesis of journal + intel + context."""

    reflection_id: str = Field(default_factory=lambda: f"reflection-{uuid4().hex[:8]}")
    date: str  # YYYY-MM-DD
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Synthesized content
    summary: str = ""  # LLM-generated day summary
    patterns_noticed: list[str] = Field(default_factory=list)
    questions_raised: list[str] = Field(default_factory=list)
    research_queue: list[str] = Field(default_factory=list)  # Topics for tomorrow
    decisions_made: list[str] = Field(default_factory=list)
    lessons_learned: list[str] = Field(default_factory=list)

    # Stats
    entries_count: int = 0
    signals_referenced: int = 0
    sectors_touched: list[str] = Field(default_factory=list)

    # Carry-forward
    open_questions: list[str] = Field(default_factory=list)  # Unanswered from today
    tomorrow_focus: list[str] = Field(default_factory=list)  # Suggested focus areas


class JournalInsight(BaseModel):
    """Pattern detected across multiple journal entries over time."""

    insight_id: str = Field(default_factory=lambda: f"insight-{uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    pattern: str  # Description of the pattern
    evidence: list[str] = Field(default_factory=list)  # Entry IDs supporting this
    frequency: int = 1  # How many times this pattern appeared
    confidence: float = 0.5  # How confident in this pattern
    actionable: bool = False  # Is this something to act on?
    recommendation: str = ""  # What to do about it


class TipEntry(BaseModel):
    """A tip, trick, technique, or best practice — searchable knowledge base."""

    tip_id: str = Field(default_factory=lambda: f"tip-{uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    category: str = "general"  # trading, research, operations, coding, etc.
    title: str
    content: str  # The tip/technique itself
    tags: list[str] = Field(default_factory=list)
    source: str = ""  # Where this came from (journal entry, research, etc.)
    times_referenced: int = 0  # Usage tracking
    effectiveness_score: float = Field(default=50.0, ge=0.0, le=100.0)
