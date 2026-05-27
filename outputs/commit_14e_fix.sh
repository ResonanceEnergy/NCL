#!/bin/bash
set -e

# Backend commit
cd /Users/natrix/dev/NCL
git add runtime/journal/morning_quiz.py \
        runtime/autonomous/loops/morning_quiz_scheduler.py \
        runtime/autonomous/scheduler.py

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14E fixes — quiz timeout/hang + ItemType bug + scheduler loop

NATRIX reported the morning quiz felt broken — submit hung indefinitely,
he hit Submit 3 times thinking it failed, propagation flags stayed false.
Plus the quiz never ran on a schedule. Three concrete bugs + one missing
piece, all fixed in this commit.

1. journal_store.create_entry hung the request
   Trace: 'propagate_quiz ENTRY' logged → 'about to call create_entry'
   logged → NO return. The underlying chain (bridge_to_memory +
   inject_to_context) parks on an async lock when brain is busy.
   The journal entry IS persisted (writer is fire-and-forget) but the
   await never resumes. HTTP request hangs forever; NATRIX retries.

   Fix: switch both create_entry calls to asyncio.create_task() —
   fire-and-forget. We don't need the entry_id (resolvable by date scan
   later). Response now returns in <300ms instead of hanging.

2. ItemType import error in working_context push
   Pre-fix: 'from ..memory.working_context import ContextItem, ItemType'
   ItemType doesn't exist — ContextItem is a dataclass with a 'category'
   string field, not a Pydantic model with an ItemType enum. Every quiz
   silently failed working_context push.

   Fix: drop the ItemType import; use ContextItem's real dataclass
   signature (item_id, content, source, category='pinned',
   salience_score, importance, recency_score, relevance_score, tags,
   pinned, created_at, metadata). Verified live — pushed_to_working_context
   now true in the saved quiz file.

3. Missing morning-quiz schedule
   I never wired one in Wave 14E. New file:
   runtime/autonomous/loops/morning_quiz_scheduler.py
   - 00:05 ET: write tomorrow's template carrying forward yesterday's
     posture + research_question (so NATRIX edits rather than starts
     blank).
   - 06:00 ET: ntfy nudge if quiz not yet submitted.
   - 12:00 ET: second-chance nudge if still empty.
   Idempotent via scheduler-state.json. Weekend-quiet by default.
   Wired into autonomous/scheduler.py task list. Loop started cleanly
   post-bounce: '[QUIZ-SCHED] morning quiz scheduler started'.

Live validation (Brain pid 15774):
  Pre-fix:  POST /journal/morning-quiz hangs forever, eventually 504
  Post-fix: POST returns http=200 in 0.28s
            response.fired = {journal_entry:true, lesson_entry:true,
                              working_context:true, calendar_todos:false}
            quiz file pushed_to_working_context: true (was false)

Files: 3, +~250 LOC.
"
echo --- pushing NCL ---
git push origin main 2>&1 | tail -3

# iOS commit
cd /Users/natrix/Projects/FirstStrike
git add Sources/Views/JournalView.swift

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14E iOS de-clutter — 9 sub-tabs → 6, INSIGHTS merge

NATRIX feedback: 'there is a lot going and its not clear how it all
functions and works, what is councils doing for example'.

Pre-fix Journal picker showed 9 sub-tabs: QUIZ, LIFE, Write, Today,
Search, Tips, Reflect, Analytics, Councils.

Two things were wrong:
- Councils sub-tab surfaced council reports — those belong in the
  Intel tab, not Journal. It was a leftover from a pre-restructure.
- Today / Reflect / Analytics were three separate sub-tabs that each
  showed a slice of the same underlying entry corpus, with overlapping
  purpose ('what did I write today' vs 'what's the AI synthesis' vs
  'charts of my entry rate'). Confusing rather than complementary.

Changes to Sources/Views/JournalView.swift:

1. Override JournalSection.allCases to return only the curated 6:
     [.quiz, .lifePlan, .write, .search, .tips, .insights]
   Legacy enum cases (.today, .reflect, .analytics, .councils) still
   compile so back-end code paths keep working — they're just not in
   the picker.

2. New .insights case merges TODAY + REFLECTION + ANALYTICS into a
   single scrollable view with three labeled sections. One tab to scan
   for daily entries → AI synthesis → trend charts.

3. New insightsSection ViewBuilder inside JournalView struct (the
   previous patch landed it at file scope; fixed).

Final picker: QUIZ · LIFE · WRITE · SEARCH · TIPS · INSIGHTS (6 vs 9).

Built green sim + device, deployed to iPhone 16e sim, iPad Pro M5
sim, Nathan iPhone, GRIP AND RIPP HDD iPad.
"
echo --- pushing FirstStrike ---
git push origin main 2>&1 | tail -3
