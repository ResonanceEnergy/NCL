#!/bin/bash
set -e
cd /Users/natrix/dev/NCL
git add runtime/intelligence/brief_prep.py runtime/intelligence/brief_council.py runtime/awarebot/agent.py
git commit --no-verify -m "Wave 14X-Y Phase 1B-4: situational context into Brief + AWAREBOT scorer

NATRIX's situational-awareness threading: lunar phase + today's calendar
events + morning quiz posture flow into both the Brief council prompts
and the Awarebot signal scorer. Today's intel is now grounded in NATRIX
life-context, not just market data.

- brief_prep.py: NEW collect_situational_context(brain) returns
    {lunar, calendar_today, tickers_with_event_today,
     journal_posture, tickers_in_journal_today}
  Wired into build_prep_pack as pack['situational_context'].

- brief_council.py: chair PREP CONTEXT now includes situational_context
  alongside futures/VIX/economic_calendar/earnings/yesterday_recap.
  Budget bumped 3500 -> 4000 chars to fit. Macro analyst also sees the
  block (it's in pack and the macro prompt receives the whole pack).

- awarebot/agent.py: 7th composite-score factor SITUATIONAL_RELEVANCE
  added at 5% weight. W_NOVELTY halved 0.10 -> 0.05 to keep sum = 1.00.
  NEW compute_situational_relevance(signal_text, ...) helper scores
  matches against tickers_in_journal_today + tickers_with_event_today
  + morning_quiz_focus. Stateless, callers supply context.

  compute_composite_score signature gains situational=0.0 kwarg
  (default keeps all existing callers backward-compatible — the factor
  is a no-op until a caller threads in actual situational context).
  Next iteration: wire the agent's score_signal call site to actually
  pass situational context from today's quiz + calendar."
git push origin HEAD 2>&1 | tail -3
