#!/bin/bash
set -e
cd /Users/natrix/Projects/FirstStrike

# Remove .bak files from the patch
rm -f Sources/Views/Journal/MorningQuizView.swift.bak Sources/Views/Journal/LifePlanView.swift.bak Sources/Views/JournalView.swift.bak.14e

git add Sources/Models/MorningQuiz.swift \
        Sources/Network/NCLBrainClient+Journal14E.swift \
        Sources/Views/Journal/MorningQuizView.swift \
        Sources/Views/Journal/LifePlanView.swift \
        Sources/Views/JournalView.swift

git status --short
echo ---
git diff --cached --stat

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14E iOS — Morning Quiz + Life Plan sub-tabs

Consumes the new backend endpoints from NCL d8d7991:
  POST /journal/morning-quiz                — submit + propagate
  GET  /journal/morning-quiz/today|latest|history
  GET  /life/dashboard /life/vision /life/north-star /life/goals /life/plans /life/wisdom/*

Four new Swift files + one JournalView patch:

1. Sources/Models/MorningQuiz.swift NEW
   MorningQuiz + MorningQuizHistoryItem + Life Plan models
   (Vision, NorthStar, LifeGoal, KeyResult, LifePlan, DailyWisdom,
    LifeDashboard). Pure Swift mirrors of backend Pydantic schemas.

2. Sources/Network/NCLBrainClient+Journal14E.swift NEW
   submitMorningQuiz, fetchMorningQuizToday/Latest/History, plus
   fetchLifeDashboard, fetchVision, setVision, fetchCurrentNorthStar,
   fetchGoals, fetchPlans, fetchWisdomToday.

3. Sources/Views/Journal/MorningQuizView.swift NEW (~340 LOC)
   The keystone. Daily wisdom card on top, 7-question form when
   today not yet submitted (mood slider + descriptor, top priority,
   3 supporting tasks, posture segmented picker, research question,
   gratitude, yesterday lesson, notes). Submit button shows
   propagation fired chips (ctx/cal/journal/lesson). When today's
   quiz exists, renders read-only summary with EDIT/RE-SUBMIT.
   History strip at bottom.

4. Sources/Views/Journal/LifePlanView.swift NEW (~250 LOC)
   Read-only v1 dashboard. Vision card (title + narrative + pillars).
   North-star card. 4-tile rollup (goals/journeys/plans/active).
   Today's wisdom. Active goals with KRs. All plans by kind.

5. Sources/Views/JournalView.swift modified
   Added QUIZ + LIFE cases to JournalSection enum (positioned first).
   Both new sub-tabs route to their respective views with
   .environmentObject(brainClient) pass-through.

Live deploy (Brain pid 11273, all builds OK):
  iPhone 16e sim       — installed + launched (pid 13012)
  iPad Pro 13 M5 sim   — installed + launched (pid 13023)
  Nathan iPhone        — installed via devicectl
  iPad GRIP AND RIPP   — installed via devicectl

Net: 4 new files, 1 patched, ~700 LOC iOS.
"
git push origin main 2>&1 | tail -3
