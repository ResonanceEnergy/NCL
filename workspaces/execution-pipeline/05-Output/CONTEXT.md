# 05-Output — Final Artifacts + Feedback

## Purpose
Final verified artifacts ready for deployment or delivery. Feedback payload prepared for iPhone pump-back.

## Contents
- Final code/artifacts from 03-Execution (verified by 04-Review)
- `verification-report.json` from 04-Review
- `feedback-payload.json` — structured summary for iPhone

## Feedback Payload Format
```json
{
  "pump_id": "PUMP-20260403-001",
  "status": "complete|partial|failed",
  "summary": "Brief description of what was accomplished",
  "artifacts": ["list of output files"],
  "metrics": {
    "council_rounds": 1,
    "coding_iterations": 2,
    "review_rounds": 1,
    "total_time_seconds": 120
  },
  "next_steps": ["optional follow-up actions"]
}
```

## Routing
- Push feedback to relay /responses/{session_id} for iPhone delivery
- Archive pump + all stage artifacts to NCL/mandate-generation/processed/
- Update NCL institutional memory if significant
