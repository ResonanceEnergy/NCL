# Daily Action

Dispatch follow-up missions based on the daily brief's recommended actions.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Previous stage | `../03-brief/output/` | "Recommended Actions" | Actions to dispatch |
| Mission ops | `../../mission-ops/CONTEXT.md` | Full file | Mission pipeline routing |
| Agent registry | `../../../ncl_agency_runtime/agents/` | Module list | Available agents |

## Process

1. Read recommended actions from 03-brief/output/
2. For each approved action, create a mission definition
3. Route each mission to the mission-ops workspace intake stage
4. Log dispatched missions to output/
5. Update the daily brief with dispatch status

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Action log | output/[date]-actions.json | JSON with dispatched missions |
