# Mission Dispatch

Route a validated mission to the appropriate agent based on mission type and agent capabilities.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Previous stage | `../01-intake/output/` | Full file | The validated mission |
| Agent registry | `../../../ncl_agency_runtime/agents/` | Module docstrings | Agent capabilities |
| Runtime config | `../../../ncl_agency_runtime/config/` | Dispatch rules | Routing logic |
| NCC Doctrine | `../../../NCC_Master_Doctrine_v2.0.md` | "Mission Governance" | Authority rules |

## Process

1. Read the validated mission from 01-intake/output/
2. Identify the mission type and required capabilities
3. Query the agent registry for agents matching those capabilities
4. If multiple agents match, select based on priority and current load
5. Create a dispatch manifest: agent ID, mission ID, parameters, deadline
6. Write the dispatch manifest to output/

## Checkpoints

| After Step | Agent Presents | Human Decides |
|------------|---------------|---------------|
| 4 | List of candidate agents with capability scores | Which agent to assign |

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Dispatch manifest | output/[mission-id]-dispatch.json | JSON with agent assignment |
