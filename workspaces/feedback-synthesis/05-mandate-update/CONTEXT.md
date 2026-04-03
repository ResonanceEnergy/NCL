# Stage 05: Mandate Update

Apply approved mandate amendments, version control, and notify affected pillars.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Stage 04 | `/Projects/NCL/feedback/amendments_{date}.json` | Recommended amendments | Update source |
| Approval Gate | Grok app notification | NATRIX sign-off | Approval required |

## Process

1. Format amendment list for NATRIX review (via Grok app)
2. Wait for approval (y/n on each amendment)
3. For approved amendments: load mandate YAML, apply changes
4. Increment mandate version, record change log
5. Notify NCC/BRS/AAC of mandate changes via work orders

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Updated Mandates | `/Projects/NCL/mandates/approved/{id}_v{n}.yaml` | YAML (versioned) |
| Change Log | `/Projects/NCL/mandates/changelog_{date}.md` | Markdown (amendments applied) |
| Work Orders | `/Projects/NCC-Doctrine/work_orders/` | YAML (notify of changes) |
