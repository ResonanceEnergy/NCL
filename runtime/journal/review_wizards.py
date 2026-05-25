"""Weekly + Yearly review wizards — Wave 14F (2026-05-25).

Same shape as the morning quiz (data/journal/weekly-review/{YYYY-Www}.json,
data/journal/yearly-review/{YYYY}.json) but with deeper questions tuned
to the review cadence:

WEEKLY (Sundays 8pm ET):
  1. Top 3 wins this week
  2. Top 1 miss + lesson
  3. Energy / focus / mood 1-10
  4. Did I move the needle on my quarterly goals? Which KR moved most?
  5. What's the SINGLE focus for next week?
  6. What am I carrying into next week (open thread)?
  7. Free notes

YEARLY (Dec 28 8pm ET, configurable date):
  1. 3 wins of the year
  2. 1 hard lesson
  3. 1 thing I'd change about the year
  4. North-star progress: where am I vs vision?
  5. Top 3 themes for next year
  6. Open question to carry into the new year
  7. Free notes

Both submit to /journal/{weekly,yearly}-review endpoints, create a
JournalEntry (type=reflection, importance=80), and bridge into memory.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field

log = logging.getLogger("ncl.journal.reviews")


def _root() -> Path:
    base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    return base / "data" / "journal"


def _weekly_file(yyyy_ww: str) -> Path:
    return _root() / "weekly-review" / f"{yyyy_ww}.json"


def _yearly_file(year: int) -> Path:
    return _root() / "yearly-review" / f"{year}.json"


class WeeklyReview(BaseModel):
    review_id: str = Field(default_factory=lambda: f"wr-{uuid4().hex[:10]}")
    iso_week: str = Field(..., description="YYYY-Www, e.g. 2026-W22")
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    wins: list[str] = Field(default_factory=list, max_length=5)
    biggest_miss: str = Field(default="", max_length=500)
    miss_lesson: str = Field(default="", max_length=500)
    energy_score: int = Field(default=7, ge=1, le=10)
    focus_score: int = Field(default=7, ge=1, le=10)
    mood_score: int = Field(default=7, ge=1, le=10)
    needle_moved: str = Field(default="", max_length=500)
    top_kr_movement: str = Field(default="", max_length=300)
    next_week_focus: str = Field(default="", min_length=1, max_length=300)
    open_threads: list[str] = Field(default_factory=list, max_length=5)
    notes: str = Field(default="", max_length=2000)
    journal_entry_id: str = ""


class YearlyReview(BaseModel):
    review_id: str = Field(default_factory=lambda: f"yr-{uuid4().hex[:10]}")
    year: int
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    wins: list[str] = Field(default_factory=list, max_length=10)
    hard_lesson: str = Field(default="", max_length=2000)
    would_change: str = Field(default="", max_length=2000)
    north_star_progress: str = Field(default="", max_length=2000)
    next_year_themes: list[str] = Field(default_factory=list, max_length=5)
    open_question: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=4000)
    journal_entry_id: str = ""


# ── Persistence ──────────────────────────────────────────────────────────

def _persist_weekly(r: WeeklyReview) -> Path:
    p = _weekly_file(r.iso_week)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(r.model_dump_json(indent=2))
    os.replace(str(tmp), str(p))
    return p


def _persist_yearly(r: YearlyReview) -> Path:
    p = _yearly_file(r.year)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(r.model_dump_json(indent=2))
    os.replace(str(tmp), str(p))
    return p


def load_weekly(yyyy_ww: str) -> Optional[WeeklyReview]:
    p = _weekly_file(yyyy_ww)
    if not p.exists():
        return None
    try:
        return WeeklyReview.model_validate_json(p.read_text())
    except Exception as e:
        log.warning("[REVIEWS] weekly parse %s failed: %s", p, e)
        return None


def load_yearly(year: int) -> Optional[YearlyReview]:
    p = _yearly_file(year)
    if not p.exists():
        return None
    try:
        return YearlyReview.model_validate_json(p.read_text())
    except Exception as e:
        log.warning("[REVIEWS] yearly parse %s failed: %s", p, e)
        return None


# ── Renderers (for journal entry body) ───────────────────────────────────

def _render_weekly(r: WeeklyReview) -> str:
    parts = [
        f"WEEKLY REVIEW — {r.iso_week}",
        "",
        f"Energy/Focus/Mood: {r.energy_score} / {r.focus_score} / {r.mood_score}",
        "",
        "WINS:",
    ]
    for w in r.wins:
        parts.append(f"  - {w}")
    parts += [
        "",
        f"BIGGEST MISS: {r.biggest_miss or '-'}",
        f"LESSON: {r.miss_lesson or '-'}",
        "",
        f"NEEDLE MOVED: {r.needle_moved or '-'}",
        f"TOP KR MOVEMENT: {r.top_kr_movement or '-'}",
        "",
        f"NEXT WEEK FOCUS: {r.next_week_focus}",
    ]
    if r.open_threads:
        parts += ["", "OPEN THREADS:"]
        for t in r.open_threads:
            parts.append(f"  - {t}")
    if r.notes:
        parts += ["", "NOTES:", r.notes]
    return "\n".join(parts)


def _render_yearly(r: YearlyReview) -> str:
    parts = [
        f"YEARLY REVIEW — {r.year}",
        "",
        "WINS:",
    ]
    for w in r.wins:
        parts.append(f"  - {w}")
    parts += [
        "",
        "HARD LESSON:",
        r.hard_lesson or "-",
        "",
        "WOULD CHANGE:",
        r.would_change or "-",
        "",
        "NORTH STAR PROGRESS:",
        r.north_star_progress or "-",
        "",
        "NEXT YEAR THEMES:",
    ]
    for t in r.next_year_themes:
        parts.append(f"  - {t}")
    parts += [
        "",
        f"OPEN QUESTION: {r.open_question or '-'}",
    ]
    if r.notes:
        parts += ["", "NOTES:", r.notes]
    return "\n".join(parts)


# ── Public submit functions ──────────────────────────────────────────────

async def submit_weekly_review(
    review: WeeklyReview,
    *,
    journal_store=None,
    timeout_per_step: float = 5.0,
) -> dict:
    _persist_weekly(review)
    fired: dict = {"journal_entry": False}
    if journal_store is not None:
        body = _render_weekly(review)
        try:
            coro = journal_store.create_entry(
                content=body,
                entry_type="reflection",
                title=f"Weekly Review {review.iso_week}: {review.next_week_focus[:60]}",
                tags=["weekly_review", review.iso_week, "reflection"],
                importance=80.0,
                source_context="weekly_review_submit",
            )
            task = asyncio.create_task(coro)
            task.add_done_callback(
                lambda t: log.warning("[REVIEWS] weekly entry bg failed: %r", t.exception())
                if (not t.cancelled() and t.exception()) else None
            )
            fired["journal_entry"] = True
        except Exception as e:
            log.warning("[REVIEWS] weekly entry creation failed: %s", e)
    return fired


async def submit_yearly_review(
    review: YearlyReview,
    *,
    journal_store=None,
    timeout_per_step: float = 5.0,
) -> dict:
    _persist_yearly(review)
    fired: dict = {"journal_entry": False}
    if journal_store is not None:
        body = _render_yearly(review)
        try:
            coro = journal_store.create_entry(
                content=body,
                entry_type="reflection",
                title=f"Yearly Review {review.year}",
                tags=["yearly_review", str(review.year), "reflection"],
                importance=95.0,
                source_context="yearly_review_submit",
            )
            task = asyncio.create_task(coro)
            task.add_done_callback(
                lambda t: log.warning("[REVIEWS] yearly entry bg failed: %r", t.exception())
                if (not t.cancelled() and t.exception()) else None
            )
            fired["journal_entry"] = True
        except Exception as e:
            log.warning("[REVIEWS] yearly entry creation failed: %s", e)
    return fired
