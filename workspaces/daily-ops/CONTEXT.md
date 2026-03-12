# Daily Operations

Four-stage pipeline for daily intelligence operations. Collects data from all
NCL sources, analyzes for patterns and anomalies, generates a daily brief, and
dispatches follow-up actions.

## Task Routing

| Task                        | Go To                              |
|-----------------------------|------------------------------------|
| Gather data from all sources | `stages/01-collect/CONTEXT.md`    |
| Pattern detection and flags  | `stages/02-analyze/CONTEXT.md`   |
| Generate the daily brief     | `stages/03-brief/CONTEXT.md`     |
| Dispatch follow-up missions  | `stages/04-action/CONTEXT.md`    |

## Stage Handoffs

```
  [01-collect]  ------>  [02-analyze]  ------>  [03-brief]  ------>  [04-action]
```

Each stage writes to its `output/` folder. The next stage reads from there.

## Code Implementation

| Stage | Primary Code | Key Functions |
|-------|-------------|---------------|
| 01-collect | `ncl_agency_runtime/runtime/autonomous_daemon.py` | `DaemonPhase`, event log loading, relay health polling |
| 02-analyze | `ncl_agency_runtime/runtime/autonomous_daemon.py` | `_handle_drift()`, `_scan_roadmap_gaps()`, `_scan_config_completeness()` |
| 03-brief | `ncl_agency_runtime/runtime/mission_runner.py` | `make_daily_brief()`, `make_weekly_brief()` |
| 04-action | `ncl_agency_runtime/runtime/ncc_orchestrator.py` | `dispatch_labour()`, `route_to_pillar()` |

Labour pool: `ncl_agency_runtime/runtime/digital_labour.py` → `DigitalLabourPool.submit_task()`

## Shared Resources

| Resource | Location | What It Provides |
|----------|----------|-----------------|
| Event log | `../../data/event_log/` | Raw event history |
| Derived data | `../../data/derived/` | Processed insights |
| Agent runtime | `../../ncl_agency_runtime/` | Mission dispatch |
| YouTube digest | `../../data/youtube_digest.ndjson` | Content intake |
