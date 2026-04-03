# NCL ↔ NCC Data Contract

**Purpose**: Formal interface between NCL (brain/think) and NCC (operational/execute).
**Authority**: NATRIX → NCL issues mandates → NCC executes work orders.
**Validation**: Pydantic models + JSON Schema on both sides.

---

## Overview

| Direction | Artifact | Sender | Receiver | Frequency |
|-----------|----------|--------|----------|-----------|
| NCL → NCC | Mandate Package | NCL (Strategy & Doctrine) | NCC | On-demand (< 4 hrs after council decision) |
| NCC → NCL | Execution Report | NCC | NCL (Strategy & Doctrine) | Daily (morning + EOD) |

---

## Schema 1: Mandate Package (NCL → NCC)

**Purpose**: Directive from NCL to NCC. Binding instruction with success criteria.
**Format**: YAML + optional attachments (research docs, council logs)
**Location**: `mandate-generation/output/active/MANDATE-*.yaml`
**Signed By**: NCL Strategy & Doctrine agent (cryptographic signature optional for audit)

```yaml
# Mandate Package Header
mandate_id: MANDATE-2026-001
version: "1.0"
created_at: "2026-04-01T09:30:00Z"
signed_by: "NCL / Strategy & Doctrine"
approved_by: "NATRIX"

# Targeting
pillar: BRS  # NCC, BRS, AAC, or NCL (self-directive)
priority: P1  # P1 (critical, block other work), P2 (high), P3 (medium), P4 (low)

# Narrative
title: "Launch Revenue Scanner — DIGITAL-LABOUR Automation"
description: |
  Ship automated freelance task detection + execution system for bit-rage-labour.com.
  System should detect incoming freelance job postings, classify by task type,
  execute eligible tasks via API or browser automation, and generate invoice.
  Target: 50 supported task types, $500/month MRR by 2026-05-31.
rationale: |
  Council consensus (confidence 0.88): DIGITAL-LABOUR revenue flatlined at $200/month.
  Market opportunity: Freelance automation is undersaturated. Competitor moves likely
  in Q2. Early-mover advantage critical for market capture.

# Deliverables
deliverables:
  - "Task detection module: 20 task types by 2026-04-15 (alpha)"
  - "Task detection module: 50 task types by 2026-04-30 (beta)"
  - "Execution engine: API calls + browser RPA"
  - "Invoice generation: Automated customer billing"
  - "Dashboard: Real-time task monitoring UI"
  - "Documentation: API + deployment guide"

# Success Metrics (hard requirements)
success_metrics:
  - metric: "Monthly recurring revenue"
    target: 500  # USD
    measurement: "BRS monthly report"
    weight: 0.4
  - metric: "Task type coverage"
    target: 50
    measurement: "Task registry in DIGITAL-LABOUR backend"
    weight: 0.3
  - metric: "Execution latency"
    target: 30  # seconds per task
    measurement: "Execution log p95 latency"
    weight: 0.2
  - metric: "Customer satisfaction"
    target: 4.2  # out of 5
    measurement: "Post-execution survey"
    weight: 0.1

# Timeline & Dependencies
deadline: "2026-04-30"
milestones:
  - date: "2026-04-15"
    deliverable: "Alpha v0.1: 20 task types"
    success_criteria: "5 customers, $50 MRR, <1% error rate"
  - date: "2026-04-23"
    deliverable: "Beta v0.2: 40 task types"
    success_criteria: "20 customers, $250 MRR, <0.5% error rate"
  - date: "2026-04-30"
    deliverable: "GA v1.0: 50 task types"
    success_criteria: "All success metrics met"

dependencies:
  - "NCC must allocate 2 engineers (50% FTE each)"
  - "BRS must establish payment processor integration (Stripe/PayPal)"
  - "UNI research: Task classification taxonomy (already complete, available in research-pipeline/archive/)"

# Constraints
constraints:
  - "Use existing NCC infrastructure (Paperclip, MWP, Tailscale)"
  - "Leverage AAC war room signals for geopolitical task opportunity detection"
  - "Do NOT modify core QUASAR IDE (NCC priority mandate)"
  - "Cost budget: $800 (API + infra) — tracked in Paperclip"

# Risk & Fallback
risks:
  - risk: "Market saturation by Q2 from competitor"
    probability: 0.3
    impact: "Revenue ceiling at $300/month instead of $500"
    mitigation: "Launch by 2026-04-15 alpha; expand feature set early"
  - risk: "Task classification accuracy < 80%"
    probability: 0.2
    impact: "Customer churn, poor LTV"
    mitigation: "Use ensemble model (Grok + Gemini); human review fallback"

fallback_path: |
  If $500 MRR target unreachable by 2026-05-15, pivot to:
  1. Contract directly with freelance platforms (Upwork, Fiverr) for volume
  2. Simplify to 20 core task types + subscription pricing model
  3. Recommend closure if MRR < $100

# Council Context
council_decision:
  date: "2026-04-01T09:30:00Z"
  chair: "Claude (Anthropic)"
  participants: ["Grok (xAI)", "Gemini (Google)", "Perplexity", "GPT (OpenAI)"]
  confidence: 0.88  # high
  consensus: "Green light to execute; high market timing confidence"
  dissent: "None recorded"

# Reference Material
attached_documents:
  - "council-log-2026-04-01.md"
  - "uni-research-task-taxonomy.md"
  - "brs-market-analysis.md"

# Status & Tracking
status: "executing"  # draft, approved, executing, completed, archived
ncc_work_order: "NCC-WO-2026-001"
assigned_to: "NCC / CTO"
feedback_report_id: "NCC-2026-002"  # Link to latest execution report

# Footer
---
## Validation Rules (Receiver - NCC)

1. **Mandate ID Format**: `MANDATE-YYYY-###` (globally unique)
2. **Priority Valid**: P1, P2, P3, or P4
3. **Deadline >= Now**: Signature timestamp must be before deadline
4. **Approver Present**: Must include approver identity (NATRIX, NCL, etc.)
5. **Success Metrics**: At least 1 measurable metric required
6. **Pillar Valid**: NCC, BRS, AAC, or NCL

If validation fails: Return REJECT with reason to NCL within 15 minutes. NCL re-issues or escalates to NATRIX.

## Execution Acknowledgment (NCC Response)

```yaml
acknowledgment:
  mandate_id: MANDATE-2026-001
  ncc_work_order: NCC-WO-2026-001
  received_at: "2026-04-01T10:00:00Z"
  assigned_to: "NCC / CTO (Engineer A, Engineer B)"
  estimated_start: "2026-04-02"
  capacity_impact: "Engineer A: 50% FTE, Engineer B: 50% FTE (2 weeks)"
  blockers: "None"
  status: "ACCEPTED"
```
