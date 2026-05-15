# Stage 02: Analysis

Decompose intent, extract constraints and opportunities from pump prompt.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Stage 01 | `/dev/NCL/prompts/intake/{timestamp}.json` | Full pump object | Raw intent decomposition |

## Process

1. Parse intent statement - extract primary goal and sub-goals
2. Identify constraints (budget, timeline, resource limits)
3. Extract success criteria and KPI targets
4. Map to existing mandates - detect conflicts or dependencies
5. Produce structured analysis document

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Analysis Doc | `/dev/NCL/analysis/{timestamp}.md` | Markdown |
| Constraint Map | `/dev/NCL/analysis/{timestamp}_constraints.yaml` | YAML |
