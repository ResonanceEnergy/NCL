# NCL Task Router

This is the entry point for all NCL operations. Read this file to determine which
workspace handles your task.

## Task Routing

| Task Type                                | Go To                                          |
|------------------------------------------|-------------------------------------------------|
| Receive, validate, dispatch a mission    | `workspaces/mission-ops/CONTEXT.md`             |
| iPhone data capture, validation, CODE    | `workspaces/data-pipeline/CONTEXT.md`           |
| Design, build, test, harden an agent     | `workspaces/agent-dev/CONTEXT.md`               |
| Daily brief, collect, analyze, act       | `workspaces/daily-ops/CONTEXT.md`               |
| Schema validation or migration           | `schemas/` (run `tools/validate_events.py`)     |
| Golden task evaluation                   | `evaluation/golden_tasks/` (run `evaluation_harness.py`) |
| System health diagnostics                | `tools/system_health_check.py`                  |
| Research and fractal experiments         | `fractal_future/README.md`                      |
| Future prediction council                | `future_predictor_council/README.md`            |

## Workspace Overview

### mission-ops
Four-stage pipeline for mission lifecycle management.
Intake -> Dispatch -> Execute -> Report.

### data-pipeline
Four-stage pipeline for iPhone data processing.
Capture -> Validate -> Process -> Synthesize.

### agent-dev
Four-stage pipeline for agent development lifecycle.
Design -> Implement -> Test -> Harden.

### daily-ops
Four-stage pipeline for daily intelligence operations.
Collect -> Analyze -> Brief -> Action.

## Stage Handoff Convention

Every stage writes its output to `stages/NN-name/output/`. The next stage reads
from the previous stage's `output/` folder. A human can edit any intermediate
output and the next stage picks up the edited version.
