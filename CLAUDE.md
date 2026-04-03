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
├── _core/
│   └── CONVENTIONS.md (NCL-specific patterns + MWP reference)
├── setup/
│   └── questionnaire.md (onboarding)
├── mandate-generation/
│   ├── input/ (pump prompts from NATRIX via Grok)
│   ├── council/ (council deliberation artifacts)
│   └── output/ (finalized mandates)
├── research-pipeline/
│   ├── queue/ (research requests)
│   ├── active/ (ongoing research via UNI)
│   └── archive/ (completed findings)
├── intelligence-scan/
│   ├── sources.md (X, YouTube, Reddit subscriptions)
│   ├── alerts/ (real-time anomalies from Awarebot-FPC)
│   └── signals/ (processed intelligence)
├── memory-processing/
│   ├── long-term/ (institutional knowledge)
│   ├── working/ (current context)
│   └── decay/ (archived, low-confidence memories)
├── feedback-synthesis/
│   ├── ncc-reports/ (execution truth)
│   ├── brs-reports/ (economic signals)
│   ├── aac-reports/ (capital performance)
│   └── synthesis/ (integrated interpretation)
└── shared/
    ├── doctrine/
    │   ├── active-mandates.md
    │   └── roadmap.md
    ├── contracts/
    │   ├── ncl-ncc-contract.md
    │   ├── ncl-feedback-contract.md
    │   └── ncl-paperclip-contract.md
    └── intelligence/
        ├── market-signals.md
        └── anomaly-log.md
```

---

## Routing Table

| Task Type | Workspace | Trigger | Output |
|-----------|-----------|---------|--------|
| New pump prompt | mandate-generation/input | `NATRIX` message | mandate package |
| Council run | mandate-generation/council | `council` keyword | deliberation log + decision |
| Research request | research-pipeline/queue | `research` keyword | research plan → UNI execution |
| Intelligence scan | intelligence-scan/alerts | `scan` keyword + cron | signal report |
| Memory recall | memory-processing/working | `recall` keyword | context brief |
| Feedback processing | feedback-synthesis | `feedback` keyword | mandate adjustments |
| Mandate status | shared/doctrine/active-mandates.md | `status` keyword | current state table |

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

---

## Integration: Paperclip Agent Orchestration

NCL registers as a **company** in Paperclip with sub-divisions as **agents**:
- **UNI** — Research cortex agent (runs deep science + alt-science investigations)
- **Awarebot-FPC** — Intelligence scanner + predictor agent (X/YouTube/Reddit + ensemble forecasting)
- **Strategy & Doctrine** — Mandate generation agent (turns council output into directives)
- **Memory & Context** — Institutional memory agent (long-term storage + decay management)

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

## Next Steps
1. Run `setup` trigger to initialize via questionnaire
2. Load `/Projects/RESONANCE-ENERGY-CONTEXT.md` for full ecosystem context
3. See CONTEXT.md (Layer 1) for detailed routing
4. See _core/CONVENTIONS.md for NCL-specific patterns
