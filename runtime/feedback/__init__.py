"""Feedback subsystem — two distinct concerns share this package.

1. Pillar-feedback synthesis cortex (scanner.py / models.py):
   NCC drops reports into feedback-synthesis/ncc-reports/. The
   scanner consumes them on a 5-minute interval, validates against schema,
   and writes synthesis output to feedback-synthesis/synthesis/. See
   feedback-synthesis/SCHEMA.md for the report contract.
   (BRS/AAC pillars were retired 2026-05-23; their report dirs are no
    longer scanned.)

2. iOS user-action event recorder (recorder.py / feedback_routes.py):
   Append-only JSONL stream of user actions on signals/predictions/briefs
   (view, expand, pin, unpin, dismiss, council_request, paper_trade, share,
   outcome_*). Backs the FirstStrike iOS feedback endpoints.
"""

from .recorder import FeedbackRecorder


__all__ = ["FeedbackRecorder"]
