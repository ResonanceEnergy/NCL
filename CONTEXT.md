# NCL — Routing Table (Layer 1 MWP)
**Purpose**: Route tasks to specific workspace folders and execution agents.
**Format**: Task type → Workspace path → Agent responsibility
---

## Task Routing Matrix

### Mandate Generation
**Path**: `mandate-generation/`
**Agent**: Strategy & Doctrine
| Task | Input Folder | Execution | Output Folder |
|------|--------------|-----------|---------------|
| Receive pump prompt | input/ | Parse NATRIX intent | Mandate draft |
| Convene council | council/ | Claude chairs debate (Grok/Gemini/Perplexity/GPT) | Decision log + consensus |
| Finalize mandate | council/ → output/ | Validate against doctrine + Paperclip approval | Signed mandate package |
---

### Research Pipeline
**Path**: `research-pipeline/`
**Agent**: UNI (Research Cortex)
| Task | Input Folder | Execution | Output Folder |
|------|--------------|-----------|---------------|
| Queue research | queue/ | Log request + assign to UNI | Research plan |
| Monitor progress | active/ | Track UNI execution (milestones) | Status updates |
| Archive findings | active/ → archive/ | Synthesize into institutional knowledge | Research report + tags |
---

### Intelligence Scan
**Path**: `intelligence-scan/`
**Agent**: Awarebot-FPC (Scanner + Predictor)
| Task | Input Folder | Execution | Output Folder |
|------|--------------|-----------|---------------|
| Monitor sources | sources.md | Stream X/YouTube/Reddit feeds | Real-time signals |
| Detect anomalies | signals/ | Ensemble forecast (Grok/Gemini/Perplexity) | Alert if confidence > threshold |
| Log anomaly | alerts/ | Append to signals/ with context | Anomaly record |
---

### Memory Processing
**Path**: `memory-processing/`
**Agent**: Memory & Context
| Task | Input Folder | Execution | Output Folder |
|------|--------------|-----------|---------------|
| Store memory | long-term/ | Index and tag institutional knowledge | Memory record |
| Recall context | working/ | Retrieve relevant memories for current task | Context brief |
| Decay old memories | long-term/ → decay/ | Archive low-confidence or outdated memories | Decay log |
---

### Feedback Synthesis
**Path**: `feedback-synthesis/`
**Agent**: Strategy & Doctrine
| Task | Input Folder | Execution | Output Folder |
|------|--------------|-----------|---------------|
| Ingest NCC report | ncc-reports/ | Validate against execution contract | Truth signal |
| Ingest BRS report | brs-reports/ | Validate against economic contract | Market signal |
| Ingest AAC report | aac-reports/ | Validate against capital contract | Performance signal |
| Ingest Games report | ncc-reports/ | Via NCC synthesis (see ncl-games-routing.md) | Games signal |
| Synthesize | synthesis/ | Integrate signals + adjust mandates | Updated mandate queue |
---

## Workspace Responsibilities

### mandate-generation/
- **Owner**: Strategy & Doctrine agent
- **Cadence**: On-demand (triggered by NATRIX pump prompt)
- **Success Metric**: Mandate approved and signed within 2 hours

### research-pipeline/
- **Owner**: UNI research cortex
- **Cadence**: Weekly sprint
- **Success Metric**: Research report delivered with convergence tags

### intelligence-scan/
- **Owner**: Awarebot-FPC
- **Cadence**: Real-time (sources.md defines polling frequency)
- **Success Metric**: Anomaly detected before market moves 50% of spread

### memory-processing/
- **Owner**: Memory & Context agent
- **Cadence**: Continuous (on write/recall + weekly decay)
<!-- MWP ≤80 lines -->
