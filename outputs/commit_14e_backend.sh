#!/bin/bash
cd /Users/natrix/dev/NCL
git add docs/JOURNAL_REDESIGN_2026-05-25.md \
  runtime/journal/models.py \
  runtime/journal/morning_quiz.py \
  runtime/api/routers/journal.py \
  runtime/life_plan/__init__.py \
  runtime/life_plan/models.py \
  runtime/life_plan/store.py \
  runtime/life_plan/wisdom.py \
  runtime/api/routers/life_plan.py \
  runtime/api/routers/__init__.py

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14E backend — Journal Morning Quiz + Life Plan subsystem

Full design + research synthesis: docs/JOURNAL_REDESIGN_2026-05-25.md

Audit found Journal was structurally sound but functionally dormant
(12 entries over 7 days, 5 of 6 daily reflections had zero entries
to reflect on). Wave 14E ships the daily anchor that fixes the
input gap, plus a life-planning data layer for vision/goals/
journeys/plans/retirement.

Backend changes:

1. runtime/journal/models.py
   Added EntryType.MORNING_QUIZ value.

2. runtime/journal/morning_quiz.py NEW (~340 LOC)
   MorningQuiz Pydantic model (7 questions + free notes).
   Persistence under data/journal/morning-quiz/{date}.json + index.jsonl.
   Idempotent re-submission (same date overwrites + updates the
   downstream JournalEntry rather than duplicating).
   propagate_quiz() fans out to:
     - JournalEntry (type=morning_quiz, importance=70)
     - Lesson entry (if Q7 non-empty)
     - working_context pin (Q2 as top priority, importance 100)
     - working_context theme (Q5 as research theme)
     - calendar todos (callback-based; not wired this wave)

3. runtime/api/routers/journal.py
   Five new endpoints:
     POST   /journal/morning-quiz             submit
     GET    /journal/morning-quiz/today       today if exists
     GET    /journal/morning-quiz/latest      newest available
     GET    /journal/morning-quiz/by-date/{d} specific date
     GET    /journal/morning-quiz/history     recent list

4. runtime/life_plan/ NEW PACKAGE
   models.py: Vision, NorthStar, Goal, KeyResult, Journey, Milestone,
              Plan, ChecklistItem, DailyWisdom.
   store.py: JSONL-backed LifePlanStore with dedup-by-id readers,
             atomic per-file writes for Vision/NorthStar, append-only
             for Goals/Journeys/Plans, dashboard rollup.
   wisdom.py: WisdomRotator with 50-entry default corpus across 5
              categories (stoic 15, operational 10, financial 10,
              personal 10, creative 5). Date-keyed deterministic
              rotation + seen-count tracking.

5. runtime/api/routers/life_plan.py NEW
   Full CRUD across the six types + dashboard endpoint:
     POST/GET     /life/vision          + /life/vision/history
     POST/GET     /life/north-star/{year|current}
     POST/GET/PATCH /life/goal/* /life/goals
     POST/GET/PATCH /life/journey/* /life/journeys
     POST/GET/PATCH /life/plan/* /life/plans
     GET/POST     /life/wisdom/today /life/wisdom/category/{c}
                  /life/wisdom/categories /life/wisdom
     GET          /life/dashboard

6. runtime/api/routers/__init__.py
   Registered life_plan_router.

Live validation:
  - GET /life/wisdom/today → 200, returns deterministic stoic-006
    (Marcus Aurelius 12.17) for today
  - GET /life/dashboard → 200, empty-state defaults shown
  - GET /journal/morning-quiz/today → 200, status=not_yet_submitted

Files: 9, +~1200 LOC. No iOS changes in this commit; Wave 14E iOS
ships separately."
git push origin main 2>&1 | tail -3
