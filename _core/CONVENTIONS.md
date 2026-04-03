# NCL Conventions — MWP Patterns + NCL-Specific Extensions

**Reference**: Jake Van Clief's MWP (Model Workspace Protocol) provides 15 core patterns.
**Extension**: NCL adds 4 patterns specific to the brain/think pillar: Mandate Lifecycle, Council Protocol, Memory Decay, Feedback Validation.

---

## MWP Core Patterns (Reference)

1. **Layer 0** (CLAUDE.md) — Identity, folder map, routing table, triggers
2. **Layer 1** (CONTEXT.md) — Task routing, workspace matrix, data flow
3. **Folder Naming** — Verb-based (setup/, input/, council/, archive/, etc.)
4. **Trigger Keywords** — Single words that route to workspaces
5. **{{PLACEHOLDER}}** — Template syntax for dynamic config
6. **YAML Task Schemas** — Structured input/output contracts
7. **Artifact Naming** — timestamp_tasktype_identifier.md
8. **Atomic Writes** — One workspace change at a time
9. **Caching Strategy** — active/ for hot data, archive/ for cold
10. **Error Handling** — Explicit fail folders, retry logic
11. **Audit Trail** — activity.log per workspace
12. **Version Control** — Git-friendly folder structure
13. **API Integration** — Contract validation at boundary
14. **Concurrency Model** — Serial by workspace, parallel across
15. **Feedback Loop** — Output folder becomes next workspace's input

---

## NCL-Specific Patterns

### 1. Mandate Lifecycle

**States**: Draft → Council Review → Approved → Executing → Completed → Archived

**Folder Progression**:
```
mandate-generation/
├── input/
│   └── 2026-04-01_pump-prompt_grok-strike.md
├── council/
│   ├── draft/
│   │   └── 2026-04-01_mandate_brs-revenue-engine.md
│   ├── deliberation/
│   │   └── 2026-04-01_council-log_claude-chairs.md
│   └── approved/
│       └── 2026-04-01_mandate_APPROVED_brs-revenue.yaml
└── output/
    └── active/
        └── MANDATE-2026-001.yaml (signed + active)
```

**Contract Fields** (YAML):
```yaml
mandate_id: MANDATE-2026-001
created_at: "2026-04-01T09:30:00Z"
pillar: BRS  # NCC, BRS, or AAC
priority: P1  # P1 (critical), P2 (high), P3 (medium), P4 (low)
title: "Launch Revenue Scanner - DIGITAL-LABOUR Automation"
description: "Ship automated freelance task detection + execution for bit-rage-labour.com"
author: "NCL / Strategy & Doctrine"
approver: "NATRIX"
deadline: "2026-04-30"
success_metrics:
  - "Revenue generated >= $500/month"
  - "Automation coverage >= 50 task types"
  - "Execution latency < 30 seconds"
status: "executing"  # draft, approved, executing, completed, archived
ncc_work_order: "NCC-WO-2026-001"
```

**Memory**:
- Active mandates stored in `shared/doctrine/active-mandates.md`
- Completed mandates moved to `shared/doctrine/archive/`
- Mandate feedback loop: NCC execution report → feedback-synthesis → mandate adjustment

---

### 2. Council Protocol

**Participants**:
- **Chair**: Claude (Anthropic) — Moderator, final decision maker
- **Members**: Grok (xAI), Gemini (Google), Perplexity, GPT (OpenAI)
- **Input**: Pump prompt from NATRIX via Grok iPhone app
- **Duration**: 15–30 min deliberation
- **Output**: Decision log + consensus mandate

**Deliberation Structure**:
```markdown
# Council Log: {{MANDATE_TITLE}}
Date: {{TIMESTAMP}}
Chair: Claude (Anthropic)
Members: Grok, Gemini, Perplexity, GPT

## Round 1: Context (Claude frames problem)
[5 min]

## Round 2: Analysis (Each member contributes)
- Grok: [intelligence signal perspective]
- Gemini: [research synthesis perspective]
- Perplexity: [fact-checking, edge cases]
- GPT: [creative alternatives]
[10 min]

## Round 3: Critique (Members challenge each other)
[5 min]

## Round 4: Synthesis (Claude builds consensus)
[5 min]

## Decision
- Primary recommendation: [mandate direction]
- Alternative paths: [if primary fails]
- Risks: [known unknowns]
- Confidence: [70–95%]

## Approved By
- Chair signature: Claude at {{TIMESTAMP}}
```

**API Cost Tracking** (Paperclip):
- Council cost = 4 API calls × average price
- Budget tracked per month + per pillar

---

### 3. Memory Decay

**Long-term Memory Schema**:
```yaml
memory_id: MEM-2026-001
created_at: "2026-04-01T10:00:00Z"
content: "BRS revenue baseline for DIGITAL-LABOUR: $200/month (February 2026)"
tags: [BRS, DIGITAL-LABOUR, revenue, baseline]
confidence: 0.92  # High = > 0.8
source: "BRS feedback report BRS-2026-002"
last_accessed: "2026-04-01T14:30:00Z"
access_count: 3
```

**Decay Policy**:
- Every 30 days, memories with confidence < 0.7 are moved to `memory-processing/decay/`
- Memories accessed in last 7 days are kept in `long-term/`
- Memories with 0 accesses for 60 days are archived
- Decay log updated weekly

**Recall Mechanism**:
- Query for tag + confidence threshold
- Return top N results ranked by (confidence × recency)
- Latency target: < 500ms

---

### 4. Feedback Validation

**Feedback Report Schemas**:

#### NCC → NCL (Execution Truth)
```yaml
report_id: NCC-2026-002
source: NCC
created_at: "2026-04-01T17:00:00Z"
mandate_id: MANDATE-2026-001
status: "executing"
progress:
  - "Task 1 completed on time"
  - "Task 2 blocked by dependency X"
  - "Task 3 70% complete"
blockers:
  - "Dependency X requires re-prioritization"
  - "Resource Y unavailable until 2026-04-05"
signals:
  - "UNI research suggests path B is faster"
  - "NCC confidence in timeline: 0.75"
recommended_adjustments:
  - "Extend deadline by 2 days"
  - "Spike on dependency resolution"
```

#### BRS → NCL (Economic Signals)
```yaml
report_id: BRS-2026-003
source: BRS
created_at: "2026-04-01T18:00:00Z"
period: "2026-03"
revenue: 250  # USD
costs: 80  # API + infra
gross_margin: 0.68
customers: 12
conversion_rate: 0.15
churn: 0.08
market_signals:
  - "DIGITAL-LABOUR demand growing 3% week-over-week"
  - "Competitor launched similar service"
recommended_adjustments:
  - "Increase marketing spend to 50% of revenue"
  - "Launch 5 new automation task types"
```

#### AAC → NCL (Capital Performance)
```yaml
report_id: AAC-2026-001
source: AAC
created_at: "2026-04-01T19:00:00Z"
period: "2026-03"
pnl: 1200  # USD profit/loss
capital_deployed: 5000
roi: 0.24  # 24% monthly
positions:
  - "BTC long 0.5 BTC (entry: $65k)"
  - "TSLA call spreads, theta decay positive"
  - "Geopolitical war bonds (AAC war room scenario)"
market_intelligence:
  - "Fed signals hike cycle pivot in Q2"
  - "China volatility presenting opportunity"
recommended_adjustments:
  - "Increase BTC allocation to 1 BTC"
  - "Close short TSLA, wait for next signal"
```

**Validation Rules**:
1. Report must include source + timestamp (immutable)
2. All numeric fields validated against historical range ± 3σ
3. Signal confidence must be explicit (0.0–1.0)
4. Contradictions with previous reports must be flagged
5. Paperclip audit log entry created on receipt

**Synthesis Workflow**:
1. Ingest report → Validate schema
2. Compare signals against memory (MEM-*)
3. Flag contradictions or anomalies
4. Integrate all signals (NCC + BRS + AAC)
5. Generate mandate adjustments if needed
6. Log synthesis + send updated mandate back to NCC

---

## Data Contracts (YAML Schemas)

All inter-pillar communication uses YAML for strict validation.

**Contract Location**: `shared/contracts/`
**Validation**: Pydantic models in NCL service layer

---

## Naming Conventions

**Artifacts**: `{{TIMESTAMP}}_{{TASK_TYPE}}_{{IDENTIFIER}}.{{EXT}}`

Examples:
- `2026-04-01_pump-prompt_grok-strike.md`
- `2026-04-01_council-log_claude-chairs.md`
- `2026-04-01_mandate_brs-revenue-engine.yaml`
- `2026-04-01_feedback_ncc-execution-truth.yaml`

**Folders**: Verb-based, snake_case
- `input/`, `council/`, `output/`, `archive/`, `decay/`, `active/`, `queue/`

---

## Activity Logging

Every workspace has `activity.log` (append-only):
```
2026-04-01 09:30:00 | INPUT | Pump prompt received from Grok | grok-strike.md
2026-04-01 09:35:00 | COUNCIL | Deliberation started | claude-chairs
2026-04-01 09:55:00 | APPROVED | Mandate signed | MANDATE-2026-001.yaml
2026-04-01 10:00:00 | OUTPUT | Sent to NCC | ncc-work-order
```

---

## Integration Checklist

- [ ] Paperclip connection configured (host, port, API key)
- [ ] All 5 workspaces created with activity.log
- [ ] YAML schemas in shared/contracts/ validated
- [ ] API cost tracking enabled in Paperclip
- [ ] Memory decay cron job scheduled
- [ ] Feedback report ingestion pipeline running
- [ ] Intelligence scan sources configured
- [ ] Council participant APIs active (Anthropic, xAI, Google, Perplexity, OpenAI)
