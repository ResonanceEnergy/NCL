"""Morning Quiz — Wave 14E (2026-05-25).

The daily anchor that turns Journal from a scratch pad into an
intentional knowledge system. Once-per-morning 7-question protocol;
on submit, propagates the answers to working_context, calendar todos,
and a structured JournalEntry that the existing ReflectionEngine
synthesizes at 10pm ET.

Full design + research synthesis: docs/JOURNAL_REDESIGN_2026-05-25.md

Data layout
-----------
data/journal/morning-quiz/{YYYY-MM-DD}.json   per-day snapshot
data/journal/morning-quiz/index.jsonl         append-only index for history

Propagation effects on submit
-----------------------------
1. Persists the quiz to disk
2. Creates a JournalEntry (type=MORNING_QUIZ, importance=70) so the
   reflection engine sees structured content tonight
3. If Q7 (yesterday_lesson) is non-empty, creates a separate LESSON
   JournalEntry that the tips corpus auto-ingests
4. Pins Q2 (top_priority) to working_context as morning_quiz:priority
   with importance 100 (above scanner signals)
5. Adds Q5 (research_question) to working_context themes
6. Drops Q2 + Q3 items into the calendar todo list with appropriate
   priority levels (high / medium)
7. Rotates the daily-wisdom corpus so today's wisdom is marked seen

Idempotency
-----------
Submitting twice on the same day overwrites the day's quiz file but
does NOT create duplicate downstream entries — propagation tracking
fields gate re-writes. Re-submission updates the existing journal
entry's content rather than appending a new one.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

log = logging.getLogger("ncl.journal.morning_quiz")


# ── Paths ────────────────────────────────────────────────────────────────


def _quiz_dir() -> Path:
    """data/journal/morning-quiz under the configured data root."""
    root = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    return root / "data" / "journal" / "morning-quiz"


def _quiz_file(date_str: str) -> Path:
    return _quiz_dir() / f"{date_str}.json"


def _index_file() -> Path:
    return _quiz_dir() / "index.jsonl"


# ── Model ────────────────────────────────────────────────────────────────


_POSTURE_CHOICES = {"aggressive", "neutral", "defensive", "cash"}


class MorningQuiz(BaseModel):
    """A single morning quiz submission.

    Schema designed to be short to fill (~90s on phone) but rich enough
    that the reflection engine can synthesize trends + the morning brief
    can absorb the operator's intent without further LLM calls.
    """

    quiz_id: str = Field(default_factory=lambda: f"mq-{uuid4().hex[:10]}")
    date: str = Field(..., description="YYYY-MM-DD operator-local")
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Q1 — mood
    mood_score: int = Field(..., ge=1, le=10, description="1=worst, 10=best")
    mood_word: str = Field(default="", max_length=40)

    # Q2 — single top priority
    # Wave 14S: dropped min_length=1 — the daily template ships with
    # top_priority="" (operator fills it on submit). The submission
    # endpoint enforces non-empty separately so the operator can't
    # submit a blank quiz. Without this fix, every fresh template
    # raised ValidationError on read.
    top_priority: str = Field(default="", max_length=300)
    is_template: bool = Field(default=False, description="True if this is an un-submitted template")
    carried_forward_from: str = Field(default="", description="Date this template carried context from")

    # Q3 — 0-3 supporting tasks
    supporting_tasks: list[str] = Field(default_factory=list, max_length=5)

    # Q4 — market posture
    market_posture: str = Field(default="neutral")

    # Q5 — one research question for the day
    research_question: str = Field(default="", max_length=300)

    # Q6 — gratitude
    gratitude: str = Field(default="", max_length=300)

    # Q7 — yesterday's lesson
    yesterday_lesson: str = Field(default="", max_length=500)

    # Free-form notes
    notes: str = Field(default="", max_length=2000)

    # Downstream propagation tracking — set by the propagator, not the client
    journal_entry_id: str = Field(default="")
    lesson_entry_id: str = Field(default="")
    pushed_to_working_context: bool = False
    pushed_to_calendar_todos: bool = False
    pushed_to_morning_brief: bool = False
    wisdom_id_shown: str = Field(default="", description="Daily wisdom id that was on the quiz screen")

    @field_validator("market_posture")
    @classmethod
    def _validate_posture(cls, v: str) -> str:
        v = (v or "").strip().lower()
        return v if v in _POSTURE_CHOICES else "neutral"

    @field_validator("supporting_tasks")
    @classmethod
    def _trim_tasks(cls, v: list[str]) -> list[str]:
        return [t.strip() for t in (v or []) if t and t.strip()][:5]

    @field_validator("mood_word")
    @classmethod
    def _normalize_word(cls, v: str) -> str:
        return (v or "").strip().split()[0][:40] if v and v.strip() else ""


# ── Persistence ──────────────────────────────────────────────────────────


def _persist_quiz(quiz: MorningQuiz) -> Path:
    """Atomic per-day file write + append to index."""
    nw = _quiz_dir()
    nw.mkdir(parents=True, exist_ok=True)
    target = _quiz_file(quiz.date)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(quiz.model_dump_json(indent=2))
    os.replace(str(tmp), str(target))
    # Append to index (append-only — duplicates allowed; readers de-dup by quiz_id)
    idx = _index_file()
    with idx.open("a", encoding="utf-8") as f:
        f.write(quiz.model_dump_json() + "\n")
    return target


def load_quiz_by_date(date_str: str) -> Optional[MorningQuiz]:
    f = _quiz_file(date_str)
    if not f.exists():
        return None
    try:
        return MorningQuiz.model_validate_json(f.read_text())
    except Exception as e:
        log.warning("[MORNING-QUIZ] failed to parse %s: %s", f, e)
        return None


def load_quiz_history(limit: int = 30) -> list[MorningQuiz]:
    """Lightweight history — newest first, dedup by quiz_id."""
    idx = _index_file()
    if not idx.exists():
        return []
    seen: dict[str, MorningQuiz] = {}
    try:
        with idx.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    q = MorningQuiz.model_validate_json(line)
                    seen[q.quiz_id] = q  # last-write-wins per quiz_id
                except Exception:
                    continue
    except Exception as e:
        log.warning("[MORNING-QUIZ] history read failed: %s", e)
        return []
    items = sorted(seen.values(), key=lambda q: q.submitted_at, reverse=True)
    return items[:limit]


# ── Downstream propagation ───────────────────────────────────────────────


def _render_quiz_for_journal(quiz: MorningQuiz) -> str:
    """Render the quiz as plain-text body for the JournalEntry."""
    lines = [
        f"MORNING QUIZ — {quiz.date}",
        "",
        f"Mood: {quiz.mood_score}/10 ({quiz.mood_word or '-'})",
        "",
        f"TOP PRIORITY: {quiz.top_priority}",
    ]
    if quiz.supporting_tasks:
        lines.append("SUPPORTING TASKS:")
        for t in quiz.supporting_tasks:
            lines.append(f"  - {t}")
    lines += [
        "",
        f"Market posture: {quiz.market_posture}",
        "",
        f"Research question: {quiz.research_question or '-'}",
        "",
        f"Gratitude: {quiz.gratitude or '-'}",
        "",
        f"Yesterday's lesson: {quiz.yesterday_lesson or '-'}",
    ]
    if quiz.notes:
        lines += ["", "NOTES:", quiz.notes]
    return "\n".join(lines)


async def propagate_quiz(
    quiz: MorningQuiz,
    *,
    journal_store=None,
    working_context=None,
    calendar_todos_callback=None,
    timeout_per_step: float = 5.0,
) -> dict:
    """Fan the quiz out to the rest of the brain — bounded by per-step timeout.

    Wave 14E (2026-05-25) post-ship fix: the original implementation awaited
    journal_store.create_entry() unbounded. That call cascades into
    memory_store.create_unit + working_context.add_item which can park on
    async locks indefinitely when the brain is busy. The HTTP request never
    returned; NATRIX hit Submit 3 times thinking the first try failed.

    Fix: every awaitable step is wrapped in asyncio.wait_for(step,
    timeout=timeout_per_step). On timeout the in-progress work continues
    in the background (the journal entry still lands on disk because the
    underlying writer is fire-and-forget) but the propagate_quiz loop
    moves on so the response can return promptly. The final _persist_quiz
    ALWAYS runs so the quiz file at least matches the user's submission.
    """
    log.info(
        "[MORNING-QUIZ] propagate ENTRY quiz_id=%s date=%s js=%s wc=%s",
        quiz.quiz_id, quiz.date, journal_store is not None, working_context is not None,
    )
    """Fan the quiz out to the rest of the brain.

    Each side-effect is best-effort and logs on failure — propagation
    must never block the API response. Returns a dict of which
    integrations actually fired so the response can surface them.

    Args:
        quiz: validated MorningQuiz instance
        journal_store: JournalStore — creates the structured entries
        working_context: DailyContextWindow — pins Q2 + adds Q5 theme
        calendar_todos_callback: optional async fn(text, priority, due_date)
            for dropping Q2/Q3 into calendar. None = skip calendar push.
    """
    fired: dict[str, Any] = {
        "journal_entry": False,
        "lesson_entry": False,
        "working_context": False,
        "calendar_todos": False,
    }

    # 1) Journal entry — structured content the ReflectionEngine consumes tonight.
    # Fire-and-forget: journal_store.create_entry takes 5-10s on a busy brain
    # because of its downstream bridge_to_memory + inject_to_context chain.
    # We don't need the return value (the entry_id can be resolved later by
    # scanning journal.jsonl), and blocking the HTTP response made NATRIX hit
    # Submit 3 times thinking the first try failed.
    if journal_store is not None:
        try:
            body = _render_quiz_for_journal(quiz)
            coro = journal_store.create_entry(
                content=body,
                entry_type="morning_quiz",
                title=f"Morning Quiz {quiz.date}: {quiz.top_priority[:80]}",
                tags=["morning_quiz", quiz.date, quiz.market_posture, f"mood:{quiz.mood_score}"],
                importance=70.0,
                source_context="morning_quiz_submit",
            )
            task = asyncio.create_task(coro)
            task.add_done_callback(
                lambda t: log.warning("[MORNING-QUIZ] journal entry bg task failed: %r", t.exception())
                if (not t.cancelled() and t.exception()) else None
            )
            fired["journal_entry"] = True
        except Exception as e:
            log.warning("[MORNING-QUIZ] journal entry creation failed: %s", e)

        # 2) Lesson entry — if Q7 non-empty. Fire-and-forget for the same
        # reason as journal entry.
        if quiz.yesterday_lesson:
            try:
                coro = journal_store.create_entry(
                    content=quiz.yesterday_lesson,
                    entry_type="lesson",
                    title=f"Lesson from {quiz.date}",
                    tags=["lesson", "morning_quiz_carry_forward", quiz.date],
                    importance=65.0,
                    source_context=f"morning_quiz:{quiz.quiz_id}",
                )
                task = asyncio.create_task(coro)
                task.add_done_callback(
                    lambda t: log.warning("[MORNING-QUIZ] lesson entry bg task failed: %r", t.exception())
                    if (not t.cancelled() and t.exception()) else None
                )
                fired["lesson_entry"] = True
            except Exception as e:
                log.warning("[MORNING-QUIZ] lesson entry creation failed: %s", e)

    # 3) Working context — pin Q2 + add Q5 as a theme.
    # ContextItem is a dataclass (not a Pydantic model); the real fields are:
    # item_id, content, source, category, salience_score, importance,
    # recency_score, relevance_score, tags, pinned, accessed_today,
    # access_count, created_at, assembled_at, metadata.
    # Pre-fix used Pydantic-style kwargs (item_type=ItemType.SIGNAL, salience=)
    # which doesn't exist — every quiz failed with `cannot import name 'ItemType'`.
    if working_context is not None and quiz.top_priority:
        try:
            from ..memory.working_context import ContextItem

            ctx = working_context.get_current()
            if ctx is not None:
                pin_item = ContextItem(
                    item_id=f"mq:priority:{quiz.date}",
                    content=f"TOP PRIORITY ({quiz.date}): {quiz.top_priority}",
                    source="morning_quiz",
                    category="pinned",
                    salience_score=1.0,
                    importance=100.0,
                    recency_score=1.0,
                    relevance_score=1.0,
                    tags=["morning_quiz", quiz.date, "top_priority"],
                    pinned=True,
                    created_at=quiz.submitted_at.isoformat() if hasattr(quiz.submitted_at, "isoformat") else str(quiz.submitted_at),
                    metadata={
                        "quiz_id": quiz.quiz_id,
                        "market_posture": quiz.market_posture,
                        "mood_score": quiz.mood_score,
                    },
                )
                # Replace prior-day mq:priority pins
                ctx.items = [
                    i for i in ctx.items
                    if not (
                        getattr(i, "item_id", "").startswith("mq:priority:")
                        and i.item_id != pin_item.item_id
                    )
                ]
                # Insert at top
                ctx.items.insert(0, pin_item)
                # DailyContext has pinned_ids on Wave 11+; defensively skip if missing
                if hasattr(ctx, "pinned_ids") and pin_item.item_id not in ctx.pinned_ids:
                    ctx.pinned_ids.append(pin_item.item_id)
                # Q5 -> themes
                if quiz.research_question:
                    theme = f"research:{quiz.research_question[:80]}"
                    if theme not in ctx.themes:
                        ctx.themes.insert(0, theme)
                # Persist (sync method; fire-and-forget inside if implementation is async)
                try:
                    working_context._persist()
                except Exception as inner_exc:
                    log.warning("[MORNING-QUIZ] working_context._persist failed: %s", inner_exc)
                fired["working_context"] = True
                quiz.pushed_to_working_context = True
        except Exception as e:
            log.warning("[MORNING-QUIZ] working_context push failed: %s", e)

    # 4) Calendar todos
    if calendar_todos_callback is not None:
        try:
            todos = [(quiz.top_priority, "high")]
            todos += [(t, "medium") for t in quiz.supporting_tasks if t]
            for text, priority in todos:
                await calendar_todos_callback(text, priority, quiz.date)
            fired["calendar_todos"] = True
            quiz.pushed_to_calendar_todos = True
        except Exception as e:
            log.warning("[MORNING-QUIZ] calendar push failed: %s", e)

    # Re-persist quiz with propagation tracking updated. Always runs even if
    # one of the propagation steps timed out so the file at least reflects
    # the user's intent + which integrations were attempted.
    try:
        _persist_quiz(quiz)
    except Exception as e:
        log.warning("[MORNING-QUIZ] re-persist after propagation failed: %s", e)

    log.info(
        "[MORNING-QUIZ] %s propagated: journal=%s lesson=%s wc=%s cal=%s",
        quiz.date, fired["journal_entry"], fired["lesson_entry"],
        fired["working_context"], fired["calendar_todos"],
    )
    return fired


# ── Public API ───────────────────────────────────────────────────────────


async def submit_quiz(
    quiz: MorningQuiz,
    *,
    journal_store=None,
    working_context=None,
    calendar_todos_callback=None,
) -> tuple[MorningQuiz, dict]:
    """End-to-end: persist + propagate. Returns (quiz, fired_dict)."""
    # Look up prior submission to inherit propagation IDs on re-submit
    prior = load_quiz_by_date(quiz.date)
    if prior is not None:
        # Inherit IDs so propagation updates rather than duplicates
        quiz.quiz_id = prior.quiz_id
        quiz.journal_entry_id = prior.journal_entry_id
        quiz.lesson_entry_id = prior.lesson_entry_id

    _persist_quiz(quiz)
    fired = await propagate_quiz(
        quiz,
        journal_store=journal_store,
        working_context=working_context,
        calendar_todos_callback=calendar_todos_callback,
    )
    return quiz, fired
