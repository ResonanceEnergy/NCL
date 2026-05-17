# NCL (NUREALCORTEXLINK) — Brain & Think Pillar

**Codename**: NCL (NUREALCORTEXLINK)
**Pillar**: Think, research, plan, remember, decide
**Analogy**: The Brain of Resonance Energy
**Authority**: Receives directives from NATRIX (absolute) → Sets mandates for NCC/BRS/AAC
**Integration**: Orchestrated via Paperclip agent framework

---

## Identity
NCL is the canonical brain cortex of the NARTIX ecosystem. It receives pump prompts from NATRIX via Grok on iPhone, chairs councils (Claude chairs; Grok, Gemini, Perplexity, GPT as members), produces mandates, manages institutional memory, and synthesizes feedback from NCC, BRS, and AAC.

**Key Role**: NCL interprets NATRIX intent → runs research/council → produces doctrine → generates mandates for downstream pillars.

---

## Workspace Map (MWP Layer 0)

```
NCL/
├── CLAUDE.md (this file)
├── CONTEXT.md (routing table)
├── run-councils.sh (YouTube + X intelligence council launcher)
├── _core/
│   └── CONVENTIONS.md (NCL-specific patterns + ICM/MWP reference)
├── setup/
│   └── questionnaire.md (onboarding)
├── mandate-generation/
│   ├── LOG.md (handoff log — read first on cold start)
│   ├── input/ (pump prompts from NATRIX via Grok)
│   ├── council/ (council deliberation artifacts)
│   └── output/ (finalized mandates)
├── research-pipeline/
│   ├── LOG.md (handoff log)
│   ├── queue/ (research requests)
│   ├── active/ (ongoing research via UNI)
│   └── archive/ (completed findings)
├── intelligence-scan/
│   ├── LOG.md (handoff log)
│   ├── sources.md (X, YouTube, Reddit subscriptions)
│   ├── alerts/ (real-time anomalies from Awarebot-FPC)
│   ├── signals/ (processed intelligence — unified SignalProcessor output)
│   └── council-reports/ (YouTube + X council output: .md + .json)
├── memory-processing/
│   ├── LOG.md (handoff log)
│   ├── long-term/ (institutional knowledge — MemoryStore, 10K units, ChromaDB)
│   ├── working/ (current context — 6am assembly, noon refresh, 11pm EOD)
│   └── decay/ (archived, low-confidence memories)
├── feedback-synthesis/
│   ├── LOG.md (handoff log)
│   ├── ncc-reports/ (execution truth)
│   ├── brs-reports/ (economic signals)
│   ├── aac-reports/ (capital performance)
│   └── synthesis/ (integrated interpretation)
├── runtime/
│   ├── councils/ (YouTube + X intelligence council engines)
│   ├── journal/ (daily journal store — JSONL persistence, 9 entry types)
│   └── scheduler/ (15 autonomous background loops)
└── shared/
    ├── doctrine/
    │   ├── active-mandates.md
    │   ├── roadmap.md
    │   ├── AGENTS.md (council + operational agent definitions)
    │   ├── paperclip.config.json (adapter + workflow config)
    │   └── NARTIX-Ecosystem-Build-Plan.md
    ├── contracts/
    │   ├── ncl-ncc-contract.md
    │   ├── ncl-feedback-contract.md
    │   └── ncl-paperclip-contract.md
    └── intelligence/
        ├── market-signals.md
        └── anomaly-log.md
```

---

## Runtime System

NCL Brain API runs as a **FastAPI service on port 8800** (Mac Studio M1 Ultra 64GB, Tailscale IP 100.72.223.123) with 176+ endpoints across 20 categories. The runtime layer is autonomous and persistent.

### API Endpoint Categories
Health, Pump (Strike Point), Council (v1+v2 runner), Mandates, Memory (14 endpoints, ChromaDB vector search), Intelligence (24 endpoints), Autonomous (9 endpoints), Chat, LDE (10 endpoints), Governance (11 endpoints), Telemetry, Availability, Evaluation, Review Queue, UNI Research, Deployment, Swarm, Shortcuts, Search, Notifications SSE, Dashboard/PWA, Feedback, Journal (15 endpoints)

### Autonomous Scheduler — 15 Background Loops
| # | Loop | Cadence |
|---|------|---------|
| 1 | Scanner (Awarebot) — X + YouTube | X: 5m, YT: 10m |
| 2 | Prediction Engine — ensemble multi-model forecasting | continuous |
| 3 | Council Auto-Spawn — 3+ converging signals or 4hr strategic review | event-driven |
| 4 | Memory Consolidation — decay + prune + cluster + merge | 1hr |
| 5 | AAC War Room Sync | 15m |
| 6 | Workspace Health | 30m |
| 7 | Mandate Purge | 6hr |
| 8 | Feedback Synthesis | 5m |
| 9 | Heartbeat | 60s |
| 10 | Working Context — assembly, refresh, EOD | 6am / noon / 11pm |
| 11 | Intel Collection — Google Trends, Polymarket, News, Crypto, Options, Reddit | continuous |
| 12 | Intel Brief — LLM-synthesized briefs with push to iPhone | on collect |
| 13 | Morning Brief | 6am ET daily |
| 14 | Weekly Strategy Review | 7-day cycle |
| 15 | Journal Reflection — LLM synthesis | 10pm ET daily |

### Signal Processing
Unified **SignalProcessor** pipeline: normalize → dedup → rank → route to 5 destinations:
- Memory store (score ≥ 50)
- Working context (score ≥ 75)
- Push notification to iPhone (score ≥ 80)
- Prediction buffer
- JSONL archive

### Memory System
**MemoryStore**: 10K unit capacity, ChromaDB vector search, exponential decay, tag-based clustering, reader-writer locking, file compaction at 200MB.

### Journal System
Full daily journal with 9 entry types: `note`, `research`, `decision`, `technique`, `observation`, `reflection`, `question`, `lesson`, `best_practice`.
- **JournalStore**: JSONL persistence, full-text search, tag filtering
- **ReflectionEngine**: LLM synthesis at 10pm ET daily
- **ContextAwareTips**: builtin + personal tips library
- **Memory bridge**: entries → MemoryStore
- **Context injection**: entries with importance ≥ 60 → WorkingContext

### Council System
Multi-LLM debate engine with mandate extraction, governance pipeline, v2 runner with RAG + replay.

### Governance
PolicyKernel, Emergency Stop, mandate approval gates.

---

## Routing Table

| Task Type | Workspace | Trigger | Output |
|-----------|-----------|---------|--------|
| New pump prompt | mandate-generation/input | `NATRIX` message | mandate package |
| Council run | mandate-generation/council | `council` keyword | deliberation log + decision |
| Research request | research-pipeline/queue | `research` keyword | research plan → UNI execution |
| Intelligence scan | intelligence-scan/alerts | `scan` keyword + cron | signal report |
| Signal processing | intelligence-scan/signals | auto (SignalProcessor) | routed to memory/context/push/JSONL |
| Memory recall | memory-processing/working | `recall` keyword | context brief |
| Journal entry | runtime/journal/ | `journal` keyword | JSONL record + optional memory bridge |
| Journal reflection | runtime/journal/ | 10pm ET cron | LLM synthesis → WorkingContext |
| Feedback processing | feedback-synthesis | `feedback` keyword | mandate adjustments |
| Mandate status | shared/doctrine/active-mandates.md | `status` keyword | current state table |
| Autonomous task | runtime/scheduler/ | cron / event-driven | per-loop output |

---

## Trigger Keywords

- `setup` — Run questionnaire, initialize NCL config
- `status` — Show active mandates and pillar feedback
- `council` — Convene cloud council (Claude chairs debate)
- `mandate` — Generate/review directive for NCC/BRS/AAC
- `scan` — Run intelligence scanner (Awarebot-FPC)
- `recall` — Retrieve institutional memory
- `feedback` — Process downstream reports + adjust mandates
- `research` — Dispatch to UNI research cortex
- `journal` — Create/query daily journal entries
- `predict` — Trigger prediction engine ensemble run
- `brief` — Request intelligence or morning brief

---

## Integration: Paperclip Agent Orchestration

NCL registers as a **company** in Paperclip with sub-divisions as **agents**:
- **UNI** — Research cortex agent (runs deep science + alt-science investigations)
- **Awarebot-FPC** — Intelligence scanner + predictor agent (X/YouTube/Reddit + ensemble forecasting)
- **Strategy & Doctrine** — Mandate generation agent (turns council output into directives)
- **Memory & Context** — Institutional memory agent (long-term storage + decay management)
- **Journal & Reflection** — Daily synthesis agent (entry logging, 10pm reflection, context injection)

**Mandate Approval Gates**: Mandates flow from council → Strategy agent → Paperclip issue creation → approval queue → NCC execution
**Feedback Audit Log**: All feedback reports logged in Paperclip activities with synthesis notes
**Budget Tracking**: API costs (Anthropic Claude, xAI Grok, Ollama compute) tracked per agent per month

---

## Authority Chain

```
NATRIX (absolute)
  ↓
NCL (directive, mandates, doctrine updates)
  ↓
NCC (operational execution)
BRS (tactical revenue)
AAC (tactical capital investment)
  ↓
Feedback ↑ (interpreted only, never raw data)
```

**Key Rule**: Only NCL updates doctrine, mandates, roadmaps, and context files. NCC/BRS/AAC never set strategy—only execute work orders.

---

## Infrastructure

- **Host**: Mac Studio M1 Ultra 64GB
- **Tailscale IP**: 100.72.223.123
- **Brain API port**: 8800 (FastAPI, 176+ endpoints)
- **Relay port**: 8787 (fire-and-forget pump delivery)
- **FirstStrike iOS**: 72+ commands across 9 categories, Brain Direct + Relay dual-mode

---

## Next Steps
1. Run `setup` trigger to initialize via questionnaire
2. Load `/Projects/RESONANCE-ENERGY-CONTEXT.md` for full ecosystem context
3. See CONTEXT.md (Layer 1) for detailed routing
4. See _core/CONVENTIONS.md for NCL-specific patterns
