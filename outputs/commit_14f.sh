#!/bin/bash
set -e

# Backend commit (NCL)
cd /Users/natrix/dev/NCL
git add runtime/life_plan/goal_synthesis.py \
        runtime/life_plan/vision_board.py \
        runtime/journal/review_wizards.py \
        runtime/api/routers/life_plan.py \
        runtime/api/routers/journal.py

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14F backend — LLM goal synth + vision board + review wizards

Four new feature areas from the wave-14E follow-up list:

1. LLM goal synthesis
   runtime/life_plan/goal_synthesis.py
   POST /life/goal/{goal_id}/synthesize-weekly
   Takes a quarterly Goal (OKR) and asks Sonnet 4 to generate 4-6 SMART
   weekly tasks anchored to its KRs. Each weekly task becomes its own
   Goal record (scope=week, parent_goal_id pointing to the source) so
   weekly progress can be tracked via single-KR Goals. Replaces prior
   weekly children of the same parent (marks them superseded). Budget-
   gated against the anthropic daily cap.

2. Vision board image generation
   runtime/life_plan/vision_board.py
   POST /life/vision/board/generate     -> calls OpenAI gpt-image-1
   GET  /life/vision/board/latest       -> base64 PNG of newest
   GET  /life/vision/board/history      -> list all boards
   Builds a vision-board prompt from the active Vision's title +
   narrative + pillars + horizon. 1024x1024 high quality (~\$0.04 per
   gen). Stored at data/life_plan/vision-boards/{vision_id}-{ts}.png.

3. Weekly + Yearly review wizards
   runtime/journal/review_wizards.py
   POST /journal/weekly-review          + GET /journal/weekly-review/latest
   POST /journal/yearly-review          + GET /journal/yearly-review/{year}
   Weekly: 7 questions (3 wins, biggest miss + lesson, energy/focus/mood
   scores, needle moved + top KR, next week focus, open threads, notes).
   Persisted to data/journal/weekly-review/{ISO-week}.json.
   Yearly: 7 questions (wins, hard lesson, would-change, north-star
   progress, next year themes, open question, notes). Persisted to
   data/journal/yearly-review/{year}.json.
   Both fire a JournalEntry (type=reflection) via fire-and-forget so
   the ReflectionEngine consumes them tonight + memory bridge happens.
   importance=80 (weekly), 95 (yearly).

Files: 5, ~+~700 LOC.
"
git push origin main 2>&1 | tail -3

# iOS commit (FirstStrike)
cd /Users/natrix/Projects/FirstStrike
git add Sources/Views/Journal/LifePlanEditors.swift \
        Sources/Views/Journal/LifePlanView.swift \
        Sources/Views/JournalView.swift

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14F iOS — Editors + review wizards + vision board sheet

New file Sources/Views/Journal/LifePlanEditors.swift (570 LOC) with
six sheets:

  VisionEditorSheet      — title + narrative + pillars + horizon
  GoalEditorSheet        — scope + objective + 1-many KRs + dates + confidence
  PlanEditorSheet        — title + kind picker + target date + budget + checklist
  WeeklyReviewSheet      — 7-question Sunday wizard
  YearlyReviewSheet      — 7-question Dec-28 wizard
  VisionBoardSheet       — \"Generate Board\" button + base64 PNG display

LifePlanView.swift patched:
  - Added @State for showVisionEditor / showGoalEditor / showPlanEditor /
    showVisionBoard
  - New horizontal actionBar with 4 buttons: + VISION, + GOAL, + PLAN,
    VISION BOARD
  - .sheet modifiers route each button to its editor

JournalView.swift patched:
  - Added @State for showWeeklyReview / showYearlyReview
  - INSIGHTS sub-tab now has WEEKLY REVIEW + YEARLY REVIEW buttons at
    the top
  - .sheet modifiers route to the review wizards

Built green for sim + device, deployed to iPhone 16e sim, iPad Pro
13-inch M5 sim, Nathan iPhone (15 Pro Max), GRIP AND RIPP HDD iPad
(Pro 11-inch).
"
git push origin main 2>&1 | tail -3
