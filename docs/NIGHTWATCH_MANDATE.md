# NIGHTWATCH_MANDATE — Intel→Night Watch sub-tab

**Status**: Wave 14W-F mandate, 2026-05-29.

The Night Watch sub-tab is the **operations health log** for what
happened while NATRIX slept. It is the rendered output of the 2am ET
5-phase maintenance cycle (`ncl-night-watch`).

## Goal

Operator health-check on autonomous infrastructure. First thing to check
on a day where something feels "off." Decision: do I need to intervene
before trusting today's brief?

## What it should be

- Status pill — RED / YELLOW / GREEN
- KEY FINDINGS — what went wrong or was discovered overnight
- RECOMMENDATIONS — numbered, actionable, ranked by Sonnet 4
- SYSTEM HEALTH — Brain pid + scheduler loops + memory stats
- COST REPORT — last 24h spend by source (Anthropic/xAI/OpenAI/Google)
- Collapsible RAW DIAGNOSTICS drawer for power-debugging
- "Generated N hours ago" footer

## What it should NOT be

- Not market intel — overnight market summary belongs in Brief→KEY MOVEMENTS
- Not the live scheduler view — that's behind Settings/Ops
- Not a place to post user-facing trading recommendations — Brief or Agenda
- One brief per day, anchored to date, NOT a streaming console

## Decision it enables

"Do I trust today's brief?" RED status with "Diagnose the Anthropic 404"
as a recommendation is the literal use case that surfaced and fixed a
model-id bug in Wave 14A.

## Good state

- GREEN status
- ≤3 KEY FINDINGS, most "informational"
- Cost under daily cap
- Freshness FRESH (generated within last 4h of opening)
- All ~35 scheduler loops green
- Recommendations either empty (truly green) or specific + actionable

## Bad state

- Empty card — Brain hasn't produced a brief (fresh install, path issue)
- RED with no Recommendations populated
- Stale brief (>24h old, freshness chip should say STALE)
- Cost report showing budget cap breached without a corresponding
  RECOMMENDATION to address it
- Generic recommendations ("check the logs") rather than specific
  ("the prediction loop has stalled — restart it")

## Header subtitle (canonical)

> "Operations health log — what happened overnight, status, findings,
> and recommendations from the 2am ET cycle."

## Backend contract

`GET /intelligence/night-watch/latest` returns:
- `status` — red / yellow / green
- `key_findings` — list of strings
- `recommendations` — numbered list
- `system_health` — Brain pid, loops state, memory stats
- `cost_report` — yesterday's spend by source
- `markdown_full` — full markdown for the raw drawer
- `generated_at` — ISO timestamp

## Producer constraints

- Loop runs at 2am ET via `ncl-night-watch` scheduler task
- 5 phases: M1=dedup (now in its own loop), M2=GC,
  M3=consolidation, M4=cost-rollup, M5=analyst-brief
- Analyst-brief MUST use `claude-sonnet-4-20250514` (the 4.6 alias
  returned HTTP 404 in Wave 13)
- Freshness chip: warn if `generated_at` > 24h old
