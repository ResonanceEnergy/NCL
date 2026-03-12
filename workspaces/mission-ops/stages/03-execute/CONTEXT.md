# Mission Execute

Run the dispatched mission through the assigned agent and capture results.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Previous stage | `../02-dispatch/output/` | Full file | Dispatch manifest |
| Agent code | `../../../ncl_agency_runtime/agents/` | Assigned agent module | Execution logic |
| Runtime engine | `../../../ncl_agency_runtime/runtime/` | Executor module | Run infrastructure |

## Process

1. Read the dispatch manifest from 02-dispatch/output/
2. Load the assigned agent module
3. Initialize the agent with mission parameters
4. Execute the mission with timeout enforcement
5. Capture agent output, logs, and any errors
6. Write execution results to output/

## Audit

| Check | Pass Condition |
|-------|---------------|
| Completed | Agent returned a result (success or failure) within timeout |
| No crash | No unhandled exceptions during execution |
| Output valid | Result conforms to expected output schema |

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Execution result | output/[mission-id]-result.json | JSON with agent output and metadata |
