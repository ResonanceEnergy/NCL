# Agent Design

Define the purpose, inputs, outputs, and capabilities of a new NCL agent.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| User | Conversation or brief | Agent concept | What the agent should do |
| Agent registry | `../../../ncl_agency_runtime/agents/` | Module list | Avoid duplication |
| NCC Doctrine | `../../../NCC_Master_Doctrine_v2.0.md` | "Agent Standards" | Design constraints |
| Super OpenClaw spec | `../../../NCL_SUPER_OPENCLAW_SPEC.md` | Full file | Agent architecture |

## Process

1. Define the agent's single responsibility (one agent, one job)
2. List the agent's required inputs (data sources, config, context)
3. Define the agent's outputs (artifacts, side effects, logs)
4. Identify which existing agents it interacts with
5. Write the agent design document to output/

## Checkpoints

| After Step | Agent Presents | Human Decides |
|------------|---------------|---------------|
| 3 | Agent spec with inputs/outputs | Approve scope or adjust |

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Agent design doc | output/[agent-name]-design.md | Markdown spec |
