"""Pydantic models for the Life Plan subsystem.

Six core types — Vision, NorthStar, Goal (with KeyResults), Journey
(with Milestones), Plan (with ChecklistItems), and DailyWisdom.
See docs/JOURNAL_REDESIGN_2026-05-25.md for the rationale.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ── Vision ───────────────────────────────────────────────────────────────


class Vision(BaseModel):
    """The 'why' — long-form narrative of the life you're building toward.

    ONE active at a time. Versioned via vision-history.jsonl on update.
    """

    vision_id: str = Field(default_factory=lambda: f"vision-{uuid4().hex[:10]}")
    title: str = Field(..., min_length=1, max_length=120)
    narrative: str = Field(default="", max_length=10000)
    horizon_years: int = Field(default=10, ge=1, le=50)
    pillars: list[str] = Field(default_factory=list, max_length=10)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_reviewed_at: Optional[datetime] = None
    active: bool = True


# ── North Star ───────────────────────────────────────────────────────────


class NorthStar(BaseModel):
    """Annual guiding metric tied to the Vision. One per year."""

    star_id: str = Field(default_factory=lambda: f"ns-{uuid4().hex[:10]}")
    year: int = Field(..., ge=2020, le=2100)
    title: str = Field(..., min_length=1, max_length=200)
    measurable: str = Field(default="", max_length=300)
    why: str = Field(default="", max_length=1000)
    quarterly_check_ins: list[dict] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Goals (OKR-style with SMART tasks) ───────────────────────────────────


class KeyResult(BaseModel):
    """A measurable Key Result under a Goal."""

    kr_id: str = Field(default_factory=lambda: f"kr-{uuid4().hex[:8]}")
    description: str = Field(..., min_length=1, max_length=300)
    target: float
    current: float = 0.0
    unit: str = Field(default="", max_length=20)
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def progress_pct(self) -> float:
        if self.target == 0:
            return 0.0
        return min(100.0, max(0.0, (self.current / self.target) * 100.0))


class Goal(BaseModel):
    """OKR-format goal at a scope (year / quarter / month / week)."""

    goal_id: str = Field(default_factory=lambda: f"goal-{uuid4().hex[:10]}")
    scope: str = Field(default="quarter")
    objective: str = Field(..., min_length=1, max_length=400)
    key_results: list[KeyResult] = Field(default_factory=list, max_length=10)
    parent_goal_id: Optional[str] = None
    starts_at: date = Field(default_factory=date.today)
    ends_at: date = Field(default_factory=date.today)
    status: str = Field(default="active")
    confidence: int = Field(default=7, ge=1, le=10)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def avg_progress_pct(self) -> float:
        if not self.key_results:
            return 0.0
        return sum(kr.progress_pct for kr in self.key_results) / len(self.key_results)


# ── Journeys ─────────────────────────────────────────────────────────────


class Milestone(BaseModel):
    """A waypoint on a Journey."""

    milestone_id: str = Field(default_factory=lambda: f"ms-{uuid4().hex[:8]}")
    title: str = Field(..., min_length=1, max_length=200)
    target_at: Optional[date] = None
    completed_at: Optional[datetime] = None
    reflection: str = Field(default="", max_length=2000)


class Journey(BaseModel):
    """Multi-year arc that doesn't fit calendar boundaries."""

    journey_id: str = Field(default_factory=lambda: f"jrn-{uuid4().hex[:10]}")
    title: str = Field(..., min_length=1, max_length=200)
    narrative: str = Field(default="", max_length=5000)
    started_at: date = Field(default_factory=date.today)
    expected_end_at: Optional[date] = None
    milestones: list[Milestone] = Field(default_factory=list)
    status: str = Field(default="active")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Plans (concrete projects, vacations, retirement) ─────────────────────


class ChecklistItem(BaseModel):
    """Single line item under a Plan."""

    item_id: str = Field(default_factory=lambda: f"item-{uuid4().hex[:8]}")
    text: str = Field(..., min_length=1, max_length=300)
    done: bool = False
    due_at: Optional[date] = None
    completed_at: Optional[datetime] = None


class Plan(BaseModel):
    """Concrete project / vacation / retirement / life-event plan."""

    plan_id: str = Field(default_factory=lambda: f"plan-{uuid4().hex[:10]}")
    title: str = Field(..., min_length=1, max_length=200)
    kind: str = Field(default="project")
    target_date: Optional[date] = None
    budget_usd: Optional[float] = None
    checklist: list[ChecklistItem] = Field(default_factory=list)
    narrative: str = Field(default="", max_length=5000)
    status: str = Field(default="planning")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Daily Wisdom ─────────────────────────────────────────────────────────


class DailyWisdom(BaseModel):
    """A single wisdom entry in the rotation corpus."""

    id: str = Field(..., min_length=1, max_length=50)
    category: str = Field(default="stoic")
    text: str = Field(..., min_length=1, max_length=1000)
    source: str = Field(default="", max_length=200)
    seen_count: int = 0
    last_seen: Optional[datetime] = None
