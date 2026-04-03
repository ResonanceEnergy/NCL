# Stage 04: Recommendation

Propose mandate adjustments and doctrine refinements based on detected patterns.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Stage 03 | `/Projects/NCL/feedback/patterns_{date}.json` | All patterns + trends | Recommendation source |
| Mandates | `/Projects/NCL/mandates/approved/` | Active mandates | Amendment target mapping |

## Process

1. For each pattern: trace to affected mandate(s)
2. Assess impact (KPI trending wrong direction? blocker recurring?)
3. Generate recommendation (adjust KPI target, add resource, pivot strategy)
4. Score recommendation strength (pattern frequency, mandate vulnerability)
5. Create recommendation document with approval criteria

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Recommendations | `/Projects/NCL/feedback/recommendations_{date}.md` | Markdown (recommendation + rationale) |
| Amendment List | `/Projects/NCL/feedback/amendments_{date}.json` | JSON (mandate_id, change, strength) |

## Checkpoints

- Each recommendation tied to specific pattern(s)
- Mandate impact assessment documented
- Approval criteria clear (e.g., "requires NATRIX sign-off")

## Audit

- Recommendation generation timestamp
- Source patterns cited
- Strength derivation (pattern frequency + KPI status)
