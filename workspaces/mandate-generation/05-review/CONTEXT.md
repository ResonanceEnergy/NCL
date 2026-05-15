# Stage 05: Review

Human approval gate - NATRIX sign-off required before mandate activation.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Stage 04 | `/dev/NCL/mandates/drafts/{timestamp}.yaml` | Full mandate draft | Human review package |
| Stage 03 | `/dev/NCL/council/{timestamp}_synthesis.md` | Council reasoning | Transparent justification |

## Process

1. Package mandate + synthesis + execution plan for NATRIX review
2. Send via Grok App notification (iPhone)
3. Wait for NATRIX approval or revision request
4. If approved: move to approved registry and notify NCC
5. If rejected: route feedback to 02-analysis for rework

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Approved Mandate | `/dev/NCL/mandates/approved/{timestamp}.yaml` | YAML |
| Activation Notice | `/dev/NCL/mandates/approved/{timestamp}_notice.txt` | Plain text |
| NCC Work Order | `/Projects/NCC-Doctrine/work_orders/{timestamp}.yaml` | YAML |
