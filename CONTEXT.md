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
| Monitor sources | sources.md | Stream X (5m) / YouTube (10m) / Reddit feeds | Real-time signals |
| Collect intel | signals/ | 6 collectors: Google Trends, Polymarket, News, Crypto, Options, Reddit | Raw signal records |
| Detect anomalies | signals/ | Ensemble forecast (Grok/Gemini/Perplexity) | Alert if confidence > threshold |
| Log anomaly | alerts/ | Append to signals/ with context | Anomaly record |
| Synthesize brief | signals/ | LLM-synthesized brief → push to iPhone | Intel brief |
---

### Signal Processing
**Path**: `intelligence-scan/signals/` (unified pipeline)
**Agent**: SignalProcessor (autonomous)
| Task | Trigger | Execution | Destination |
|------|---------|-----------|-------------|
| Normalize + dedup signals | Any incoming signal | Score and deduplicate | Pipeline |
| Route to memory | Score ≥ 50 | Write to MemoryStore | memory-processing/long-term/ |
| Route to context | Score ≥ 75 | Inject into WorkingContext | memory-processing/working/ |
| Push to iPhone | Score ≥ 80 | Notifications SSE → FirstStrike | Push alert |
| Buffer for prediction | Any signal | Enqueue in prediction buffer | Prediction Engine |
| Archive | All signals | Append to JSONL | intelligence-scan/signals/ |
---

### Intelligence Engine
**Path**: `intelligence-scan/` + `runtime/scheduler/`
**Agent**: Awarebot-FPC + Autonomous Scheduler
| Loop | Cadence | Output |
|------|---------|--------|
| Scanner — X + YouTube | X: 5m, YT: 10m | Real-time signal feed |
| Intel Collection — 6 collectors | Continuous | Structured signal records |
| Intel Brief — LLM synthesis | On collection | Brief pushed to iPhone |
| Morning Brief | 6am ET daily | Strategic day-start summary |
| Weekly Strategy Review | 7-day cycle | Doctrine adjustment candidates |
| Prediction Engine — ensemble multi-model | Continuous | Forecasts + confidence scores |
| Council Auto-Spawn | 3+ converging signals OR 4hr elapsed | Council deliberation session |
---

### Autonomous Scheduler
**Path**: `runtime/scheduler/`
**Agent**: Autonomous (15 background loops)
| # | Loop | Cadence | Output |
|---|------|---------|--------|
| 1 | Scanner (Awarebot) — X + YouTube | X: 5m, YT: 10m | Signal feed |
| 2 | Prediction Engine | Continuous | Forecasts |
| 3 | Council Auto-Spawn | Event-driven (signals or 4hr) | Council session |
| 4 | Memory Consolidation — decay + prune + cluster + merge | 1hr | Compacted MemoryStore |
| 5 | AAC War Room Sync | 15m | Capital signal handoff |
| 6 | Workspace Health | 30m | Health report |
| 7 | Mandate Purge | 6hr | Expired mandate cleanup |
| 8 | Feedback Synthesis | 5m | Mandate adjustment queue |
| 9 | Heartbeat | 60s | API liveness ping |
| 10 | Working Context — assembly / refresh / EOD | 6am / noon / 11pm | WorkingContext update |
| 11 | Intel Collection — 6 collectors | Continuous | Raw signal records |
| 12 | Intel Brief — LLM synthesis + push | On collection | iPhone push notification |
| 13 | Morning Brief | 6am ET daily | Day-start brief |
| 14 | Weekly Strategy Review | 7-day cycle | Strategy candidates |
| 15 | Journal Reflection — LLM synthesis | 10pm ET daily | Reflection entry → WorkingContext |
---

### Memory Processing
**Path**: `memory-processing/`
**Agent**: Memory & Context
| Task | Input Folder | Execution | Output Folder |
|------|--------------|-----------|---------------|
| Store memory | long-term/ | Index and tag in MemoryStore (10K units, ChromaDB) | Memory record |
| Recall context | working/ | Vector search + retrieve relevant memories | Context brief |
| Decay old memories | long-term/ → decay/ | Exponential decay + prune + cluster + merge | Compacted store |
| Compact store | long-term/ | File compaction at 200MB threshold | Compacted JSONL |
| Working context assembly | working/ | 6am assembly, noon refresh, 11pm EOD | WorkingContext snapshot |
---

### Journal System
**Path**: `runtime/journal/`
**Agent**: Journal & Reflection
| Task | Trigger | Execution | Output |
|------|---------|-----------|--------|
| Create entry | `journal` keyword or API | Write to JournalStore (JSONL) | Entry record |
| Search entries | Query | Full-text + tag filter search | Matching entries |
| Memory bridge | On write | High-importance entries → MemoryStore | Memory record |
| Context injection | Importance ≥ 60 | Inject into WorkingContext | Context update |
| Daily reflection | 10pm ET cron | ReflectionEngine LLM synthesis | Reflection entry |
| Tips | On demand | ContextAwareTips (builtin + personal library) | Tip delivered |

**Entry Types**: `note`, `research`, `decision`, `technique`, `observation`, `reflection`, `question`, `lesson`, `best_practice`
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
- **Owner**: Awarebot-FPC + SignalProcessor
- **Cadence**: Real-time (X: 5m, YT: 10m, 6 intel collectors: continuous)
- **Success Metric**: Anomaly detected before market moves 50% of spread; brief pushed within 60s of collection

### memory-processing/
- **Owner**: Memory & Context agent
- **Cadence**: Continuous writes; consolidation 1hr; WorkingContext 3x daily
- **Success Metric**: MemoryStore under 10K units; recall latency < 500ms

### runtime/journal/
- **Owner**: Journal & Reflection agent
- **Cadence**: On-demand entries; 10pm ET reflection cron
- **Success Metric**: Reflection synthesized and injected into WorkingContext by 10:05pm ET

### runtime/scheduler/
- **Owner**: Autonomous Scheduler (15 loops)
- **Cadence**: Per-loop schedule (see table above)
- **Success Metric**: All loops running; heartbeat green; no loop drift > 2x cadence

### feedback-synthesis/
- **Owner**: Strategy & Doctrine agent
- **Cadence**: 5m synthesis loop; on-demand ingestion
- **Success Metric**: Mandate adjustment queue populated within 10m of report arrival
<!-- MWP ≤80 lines — extended for runtime system documentation -->
