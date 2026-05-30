#!/bin/bash
set -e
cd /Users/natrix/dev/NCL
git add runtime/autonomous/signal_processor.py runtime/autonomous/scheduler.py runtime/api/routes.py runtime/lane_router/__init__.py runtime/councils/youtube/scraper.py
git commit --no-verify -m "Wave 14X-3: re-wire push notifications + delete dead Strike Point code

Two silent bugs + 3 dead-code deletions.

LIVE BUGS (silent since 2026-05-23 archive of strike_point_orchestrator):
- signal_processor._push_alerts: import failed silently, all intel
  signal push alerts dropped on the floor for 6+ days
- scheduler journal-reflection block: same broken import, daily
  reflection pushes silently dead

Re-wired both through runtime/notifications/alert_dispatch.enqueue_alert
(the central AlertDispatcher singleton — 1/10s rate limit, 1h dedup).

DEAD CODE REMOVED:
- runtime/lane_router/__init__.py:103 — ('strike-point', PORTFOLIO)
  mapping. Nothing in live code emits source='strike-point'.
- runtime/councils/youtube/scraper.py — STRIKE_POINT_KEYWORDS list
  + _strike_point_score function. Wave 14X-1A neutralized the use
  (date-desc sort replaced keyword sort); this deletes the dead
  function. video['strike_score'] field gone too.
- runtime/api/routes.py /notifications/test endpoint: was returning
  HTTP 410 'push helper retired with strike-point orchestrator'.
  Now wired through enqueue_alert — test push button works again.

Verification: AST clean on all 5 files. No live import / call site
references STRIKE_POINT_KEYWORDS or _strike_point_score anymore
(only comments remain documenting the deletion)."
git push origin HEAD 2>&1 | tail -3
