# Day 5 — Train

> **Goal**: Documentation, runbook, handoff, Day-2 operations plan.

---

## Morning (9:00–12:00)

### 1. Documentation Review (9:00–10:00)
- **Exercise**: Review and customize all documentation
  - [USAGE.md](../docs/USAGE.md) — data schema, quickstart, FAQ
  - [XAI_GUIDE.md](../docs/XAI_GUIDE.md) — interpreting SHAP and TimeSHAP
  - [CAUSAL_GUIDE.md](../docs/CAUSAL_GUIDE.md) — DoWhy DAG building
  - [COMPUTE_PROFILE.md](../docs/COMPUTE_PROFILE.md) — when to burst
- Update with domain-specific examples from your bootcamp
- **Output**: Customized documentation suite

### 2. Runbook Creation (10:00–11:00)
- **Exercise**: Write an operational runbook covering:
  - Daily operations: how to trigger a new forecast run
  - Weekly operations: review backtest report, update weights
  - Monthly operations: retrain neural models, review causal DAG
  - Incident response: what to do when MASE exceeds threshold
  - Escalation: when to engage the team vs. handle autonomously
- **Output**: Runbook document

### 3. Knowledge Transfer (11:00–12:00)
- **Exercise**: Structured knowledge transfer session
  - Walk through the full pipeline: data → council → forecast → XAI → what-if
  - Q&A session: address all outstanding questions
  - Record key decisions and rationale from the week
- **Output**: KT session notes

## Afternoon (13:00–17:00)

### 4. Day-2 Operations Planning (13:00–14:00)
- **Exercise**: Plan ongoing operations
  - Model retraining cadence (weekly? monthly?)
  - Data refresh schedule
  - Cloud burst budget review cadence
  - New series onboarding process
  - Performance monitoring review schedule
- **Output**: Day-2 ops plan

### 5. Expansion Opportunities (14:00–15:00)
- **Exercise**: Identify next use cases
  - What other series/domains could benefit from the council?
  - Which causal questions are unanswered?
  - Where would foundation models add the most value?
  - What additional data sources could improve forecasts?
- **Output**: Expansion roadmap

### 6. Final Demo (15:00–16:00)
- **Exercise**: End-to-end demo to executive sponsor
  - Show: data ingestion → council forecast → XAI dossier → what-if scenario
  - Present: MASE improvement over baseline
  - Demo: scenario runner ("what if promo increases 10%?")
  - Discuss: cost profile and cloud burst strategy
- **Output**: Demo recording (optional)

### 7. Bootcamp Retrospective (16:00–16:45)
- What went well?
- What would we do differently?
- What's the TTV (Time to Value) from Day 1 to production forecast?
- NPS score for the bootcamp experience

### 8. Handoff Ceremony (16:45–17:00)
- Formal handoff: bootcamp team → operations team
- 30-day hypercare plan activated
- Escalation contacts shared
- Celebration!

---

## Day 5 Deliverables Checklist
- [ ] Customized documentation suite
- [ ] Operational runbook (daily/weekly/monthly/incident)
- [ ] Knowledge transfer session notes
- [ ] Day-2 operations plan
- [ ] Expansion roadmap (next use cases)
- [ ] Final demo delivered to executive sponsor
- [ ] Bootcamp retrospective completed
- [ ] Formal handoff to operations team

---

## Post-Bootcamp: 30-Day Hypercare

| Week | Focus | Deliverable |
|---|---|---|
| Week 1 | Stability | Daily check-ins, monitor MASE, fix any integration issues |
| Week 2 | Optimization | Tune ensemble weights based on production data |
| Week 3 | Expansion | Onboard second series or domain |
| Week 4 | Independence | Reduce check-in frequency, final review |
