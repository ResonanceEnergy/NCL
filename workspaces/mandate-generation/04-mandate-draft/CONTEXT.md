# Stage 04: Mandate Draft

Produce mandate YAML with objectives, KPIs, authority chain, and success metrics.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Stage 03 | `/Projects/NCL/council/{timestamp}_synthesis.md` | Synthesis + tradeoffs | Mandate design foundation |
| Doctrine | `/Projects/NCC_CONTEXT.md` | Authority chain, pillar roles | Template and authority mapping |

## Process

1. Create mandate YAML skeleton (id, title, owner, timeline)
2. Populate objectives from council synthesis
3. Define KPIs with target values and measurement method
4. Map execution to NCC, BRS, AAC (authority delegation)
5. Set approval gates and escalation thresholds

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Mandate YAML | `/Projects/NCL/mandates/drafts/{timestamp}.yaml` | YAML |
| Execution Plan | `/Projects/NCL/mandates/drafts/{timestamp}_exec.md` | Markdown |

## Checkpoints

- All objectives mapped to measurable KPIs
- Authority chain spans NCC/BRS/AAC appropriately
- Timeline feasible given resource constraints

## Audit

- Mandate version, author (Claude), timestamp
- Tradeoff justifications documented
- Success criteria threshold values approved
