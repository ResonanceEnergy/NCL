# Mission Operations

Four-stage pipeline for processing missions through the NCL Agency Runtime.
Takes a mission definition from intake through dispatch, execution, and reporting.

## Task Routing

| Task                          | Go To                              |
|-------------------------------|------------------------------------|
| Receive and validate a mission | `stages/01-intake/CONTEXT.md`     |
| Route mission to an agent      | `stages/02-dispatch/CONTEXT.md`   |
| Execute the mission            | `stages/03-execute/CONTEXT.md`    |
| Generate mission report        | `stages/04-report/CONTEXT.md`     |

## Stage Handoffs

```
  [01-intake]  ------>  [02-dispatch]  ------>  [03-execute]  ------>  [04-report]
```

Each stage writes to its `output/` folder. The next stage reads from there.
## Code Implementation

| Stage | Primary Code | Key Functions |
|-------|-------------|---------------|
| 01-intake | `ncl_agency_runtime/missions/queue/` | Mission JSON files, `MissionStatus.record()` |
| 02-dispatch | `ncl_agency_runtime/runtime/mission_runner.py` | `route_mission()`, `MISSION_HANDLERS` dict |
| 03-execute | `ncl_agency_runtime/runtime/mission_runner.py` | `run_with_retry()`, `_execute_daily_brief()` |
| 04-report | `ncl_agency_runtime/runtime/mission_runner.py` | `make_daily_brief()`, `make_weekly_brief()` |

Cross-pillar dispatch: `ncl_agency_runtime/runtime/ncc_orchestrator.py` → `route_to_pillar()`
## Shared Resources

| Resource | Location | What It Provides |
|----------|----------|-----------------|
| Mission schemas | `../../schemas/ncl.iphone.v1/` | Validation rules |
| Agent registry | `../../ncl_agency_runtime/agents/` | Available agents |
| Runtime config | `../../ncl_agency_runtime/config/` | Dispatch rules |
| NCC Doctrine | `../../NCC_Master_Doctrine_v2.0.md` | Governance authority |
