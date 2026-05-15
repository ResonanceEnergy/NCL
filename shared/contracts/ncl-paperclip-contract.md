# NCL ↔ Paperclip Integration Contract

**Purpose**: Formal integration between NCL (brain cortex) and Paperclip (agent orchestration framework).
**Framework**: Paperclip "company" (NCL) + "agents" (UNI, Awarebot-FPC, Strategy, Memory) + issues/activities/budget.

---

## Overview

| Paperclip Construct | NCL Mapping | Purpose |
|-------------------|-------------|---------|
| Company | NCL (NUREALCORTEXLINK) | Canonical brain entity in Paperclip |
| Agent | UNI, Awarebot-FPC, Strategy & Doctrine, Memory & Context | Sub-division responsibilities |
| Issue | Mandate (MANDATE-*.yaml) | Work order with approval gates |
| Activity | Feedback report (NCC/BRS/AAC-*.yaml) | Pillar signal logged to audit |
| Budget | Monthly API + compute costs | Tracked per agent + pillar |
| Integration | MWP + Tailscale + Ollama | Technical bridge |

---

## Paperclip Company: NCL

**Company Name**: NUREALCORTEXLINK (NCL)
**Company Type**: Brain / Think Pillar
**Authority Level**: Directive (sets mandates for NCC, BRS, AAC)
**Status**: Active (operational 2026-03-01)

```yaml
# Paperclip Company Registration
company:
  id: "ncl"
  name: "NUREALCORTEXLINK"
  codename: "NCL"
  pillar: "Think"
  authority_level: "directive"
  parent_authority: "NATRIX"
  status: "active"

  # Integration endpoints
  endpoints:
    mandate_queue: "file:///dev/NCL/mandate-generation/output/"
    feedback_inbox: "file:///dev/NCL/feedback-synthesis/"
    memory_store: "file:///dev/NCL/memory-processing/long-term/"
    intelligence_feed: "file:///dev/NCL/intelligence-scan/signals/"

  # Governance
  approval_authority:
    p1_mandates: "NATRIX"
    p2_mandates: "NCL"
    p3_mandates: "NCL"
    p4_mandates: "NCL / Strategy Agent"

  # Communication
  alerts:
    channel: "Telegram"
    bot_token: "{{TELEGRAM_BOT_TOKEN}}"
    chat_id: "{{TELEGRAM_CHAT_ID}}"
    alert_triggers: ["P1 mandate blocked", "Signal contradiction", "UNI research anomaly"]
```

---

## Paperclip Agents (Sub-divisions)

### Agent 1: UNI (Research Cortex)

```yaml
agent:
  id: "uni"
  name: "UNI"
  full_name: "Universal Research Intelligence"
  parent_company: "ncl"
  responsibility: "Deep science research + alt-science investigations"

  workspace: "file:///dev/NCL/research-pipeline/"

  capabilities:
    - "Literature mining (arXiv, PubMed, etc.)"
    - "Convergence detection (multi-source signal alignment)"
    - "Hypothesis testing + validation"
    - "Long-horizon research (weeks to months)"

  execution_environment:
    inference_model: "qwen3:32b (Ollama, localhost:11434)"
    gpu_allocation: "Metal (Apple Silicon)"
    monthly_budget: 120  # USD (Ollama compute, minimal cost)

  kpis:
    - "Research reports delivered on deadline"
    - "Convergence detection accuracy (>80%)"
    - "Recommendation adoption rate (by Strategy)"

  input_queue:
    folder: "research-pipeline/queue/"
    polling_interval: 15  # minutes

  output_archive:
    folder: "research-pipeline/archive/"
    retention: 180  # days
```

### Agent 2: Awarebot-FPC (Intelligence Scanner + Predictor)

```yaml
agent:
  id: "awarebot-fpc"
  name: "Awarebot-FPC"
  full_name: "Awareness Bot — Future Predictor Council"
  parent_company: "ncl"
  responsibility: "Real-time intelligence scanning + ensemble forecasting"

  workspace: "file:///dev/NCL/intelligence-scan/"

  capabilities:
    - "X feed monitoring (NATRIX subscriptions)"
    - "YouTube channel tracking"
    - "Reddit subreddit scanning"
    - "Ensemble forecasting (Grok + Gemini + Perplexity)"
    - "Anomaly detection (> confidence threshold alert)"

  execution_environment:
    models:
      - "Grok (xAI API, api.x.ai)"
      - "Gemini (Google API)"
      - "Perplexity (API)"
    monthly_budget: 300  # USD (API calls)

  kpis:
    - "Anomaly detection latency (goal: < 15 min)"
    - "Signal accuracy (% of alerts that materialize)"
    - "False positive rate (< 20%)"

  input_sources:
    - "sources.md (X handles, YouTube channels, Reddit subs)"
    - "polling_frequency: 5 minutes"

  output_alerts:
    folder: "intelligence-scan/alerts/"
    threshold_confidence: 0.75  # Only log signals > 75% confidence
    alert_channel: "Telegram + Paperclip activity log"
```

### Agent 3: Strategy & Doctrine

```yaml
agent:
  id: "strategy-doctrine"
  name: "Strategy & Doctrine"
  full_name: "Strategy & Doctrine Engine"
  parent_company: "ncl"
  responsibility: "Mandate generation + council facilitation + feedback synthesis"

  workspace: "file:///dev/NCL/mandate-generation/ + feedback-synthesis/"

  capabilities:
    - "Council orchestration (chairs via Claude, invites Grok/Gemini/Perplexity/GPT)"
    - "Mandate drafting + approval workflow"
    - "Feedback synthesis (integrate NCC/BRS/AAC signals)"
    - "Doctrine updates (roadmap, principles)"

  execution_environment:
    models:
      - "Claude (Anthropic, chairs council)"
      - "Grok, Gemini, Perplexity, GPT (council members)"
    monthly_budget: 600  # USD (Claude chair + member queries)

  kpis:
    - "Mandate approval time (< 4 hours from pump prompt)"
    - "Council decision confidence (target > 0.8)"
    - "Feedback synthesis latency (< 2 hours)"

  workflows:
    council:
      trigger: "council" keyword
      participants: ["Claude (chair)", "Grok", "Gemini", "Perplexity", "GPT"]
      duration: 15–30 min
      output_folder: "mandate-generation/council/deliberation/"

    mandate_drafting:
      input_folder: "mandate-generation/input/"
      output_folder: "mandate-generation/approved/"
      approval_required: true

    feedback_synthesis:
      input_folders: ["feedback-synthesis/ncc-reports/", "brs-reports/", "aac-reports/"]
      output_folder: "feedback-synthesis/synthesis/"
      cadence: "daily (morning 09:00 UTC, EOD 18:00 UTC)"
```

### Agent 4: Memory & Context

```yaml
agent:
  id: "memory-context"
  name: "Memory & Context"
  full_name: "Institutional Memory & Context Engine"
  parent_company: "ncl"
  responsibility: "Long-term memory storage + decay management + context retrieval"

  workspace: "file:///dev/NCL/memory-processing/"

  capabilities:
    - "Memory indexing + tagging"
    - "Recall by tag + confidence threshold"
    - "Memory decay (archive low-confidence memories)"
    - "Context brief generation"

  execution_environment:
    storage: "Local YAML (long-term/), SQLite for indexing (optional)"
    inference: "Ollama qwen3:8b (for embedding + similarity)"
    monthly_budget: 50  # USD (minimal)

  kpis:
    - "Recall latency (< 500ms target)"
    - "Memory decay accuracy (no critical memories archived prematurely)"
    - "Context brief relevance (measured by Strategy agent usage)"

  memory_schema:
    folder: "memory-processing/long-term/"
    fields:
      - "memory_id (MEM-YYYY-###)"
      - "created_at, last_accessed, access_count"
      - "content, tags, confidence (0.0–1.0)"
      - "source (feedback report ID or research ID)"

  decay_policy:
    frequency: "Weekly"
    criteria: "confidence < 0.7 OR access_count == 0 for 60 days"
    action: "Move to memory-processing/decay/"
    log: "decay-log.md (append-only)"

  recall_interface:
    trigger: "recall" keyword
    query_format: "tags: [tag1, tag2, ...], confidence_min: 0.7"
    output: "context-brief.md in memory-processing/working/"
```

---

## Issue Workflow: Mandates

**Paperclip Issue Type**: Mandate
**Lifecycle**: Draft → Approved → Executing → Completed

```yaml
issue:
  # Header
  id: "MANDATE-2026-001"
  type: "mandate"
  title: "Launch Revenue Scanner — DIGITAL-LABOUR Automation"

  # NCL Integration
  ncl_agent: "strategy-doctrine"
  ncl_mandate_file: "file:///dev/NCL/mandate-generation/output/active/MANDATE-2026-001.yaml"

  # Workflow
  status: "executing"
  status_history:
    - date: "2026-04-01T09:30:00Z"
      status: "draft"
      actor: "Strategy & Doctrine"
    - date: "2026-04-01T09:55:00Z"
      status: "approved"
      actor: "NATRIX"
      approval_notes: "Council consensus (0.88 confidence). Green light to execute."
    - date: "2026-04-01T10:00:00Z"
      status: "executing"
      actor: "NCC"
      ncc_work_order: "NCC-WO-2026-001"

  # Pillar + Priority
  pillar: "BRS"
  priority: "P1"

  # Success Criteria (from mandate package)
  success_metrics:
    - "Monthly recurring revenue >= $500"
    - "Task type coverage >= 50"
    - "Execution latency < 30 sec"
    - "Customer satisfaction >= 4.2/5"

  # Timeline
  created_at: "2026-04-01T09:30:00Z"
  deadline: "2026-04-30"
  milestones:
    - date: "2026-04-15"
      name: "Alpha v0.1"
      description: "20 task types, $50 MRR"
    - date: "2026-04-23"
      name: "Beta v0.2"
      description: "40 task types, $250 MRR"
    - date: "2026-04-30"
      name: "GA v1.0"
      description: "50 task types, $500 MRR"

  # Approvals
  approval_gates:
    - gate: "NCL council decision"
      approver: "Claude (Anthropic)"
      status: "APPROVED"
      date: "2026-04-01T09:55:00Z"

    - gate: "NATRIX sign-off"
      approver: "NATRIX"
      status: "APPROVED"
      date: "2026-04-01T10:00:00Z"

    - gate: "NCC capacity confirmation"
      approver: "NCC / CTO"
      status: "APPROVED"
      date: "2026-04-01T10:15:00Z"

  # Feedback Loop
  feedback_reports:
    - report_id: "NCC-2026-002"
      date: "2026-04-01T17:00:00Z"
      status: "executing"
      progress: "70%"

  # Linked Resources
  related_documents:
    - "council-log-2026-04-01.md"
    - "uni-research-task-taxonomy.md"
    - "brs-market-analysis.md"
```

---

## Activity Workflow: Feedback Reports

**Paperclip Activity Type**: Feedback Report
**Linked to**: Mandate issue

```yaml
activity:
  id: "NCC-2026-002"
  type: "feedback_report"
  report_type: "execution_truth"
  source: "NCC"
  created_at: "2026-04-01T17:00:00Z"

  # Link to Mandate
  mandate_id: "MANDATE-2026-001"
  mandate_link: "file:///dev/NCL/feedback-synthesis/ncc-reports/NCC-2026-002.yaml"

  # Validation
  schema_validation: "PASS"
  contradiction_flags: []  # None detected

  # Status
  status: "progress"
  progress_pct: 70
  on_track: true
  timeline_health: "green"

  # NCL Processing
  ncl_synthesis:
    processed_at: "2026-04-01T17:30:00Z"
    processed_by: "Strategy & Doctrine"
    synthesis_status: "complete"
    synthesis_notes: |
      MANDATE-2026-001 progressing well. Task detection 18/20 (90% of MVP).
      Competitor entry detected (Awarebot signal). Recommend accelerate to 50 types.
      No mandate adjustment needed at this time; staying on plan.
    signal_integration: "Competitor move aligns with BRS market signal (confidence 0.88)."
    action_items: []  # No changes needed

  # Audit Trail
  audit_log:
    - timestamp: "2026-04-01T17:00:00Z"
      event: "Report received"
      actor: "NCC"
    - timestamp: "2026-04-01T17:10:00Z"
      event: "Schema validated"
      status: "PASS"
    - timestamp: "2026-04-01T17:30:00Z"
      event: "Synthesized by Strategy"
      actor: "Strategy & Doctrine"
```

---

## Budget Tracking

**Monthly Budget Allocation** (per agent, per month):

```yaml
budget:
  period: "2026-04"
  company: "ncl"

  agents:
    uni:
      allocation: 120  # USD
      description: "Ollama compute (qwen3:32b)"
      ytd_spend: 120
      burn_rate: "100% (on budget)"

    awarebot_fpc:
      allocation: 300  # USD
      description: "Grok, Gemini, Perplexity API calls"
      ytd_spend: 300
      burn_rate: "100% (on budget)"

    strategy_doctrine:
      allocation: 600  # USD
      description: "Claude (council chair), Grok/Gemini/Perplexity (members)"
      ytd_spend: 600
      burn_rate: "100% (on budget)"

    memory_context:
      allocation: 50  # USD
      description: "Ollama qwen3:8b (embedding), storage"
      ytd_spend: 50
      burn_rate: "100% (on budget)"

  total_allocation: 1070  # USD per month
  total_spend: 1070
  utilization: "100%"

  # Cost Attribution
  cost_allocation_by_pillar:
    ncc:
      benefit: "Mandate generation + approval gates"
      share: "30%"  # 321 USD
    brs:
      benefit: "Revenue mandate + economic signal synthesis"
      share: "40%"  # 428 USD
    aac:
      benefit: "Capital mandate + war room scenario"
      share: "20%"  # 214 USD
    ncl:
      benefit: "Self-directed research + intelligence"
      share: "10%"  # 107 USD
```

---

## API Integration Points

### Ollama (Local Inference)

```yaml
ollama:
  endpoint: "http://localhost:11434"
  models_used:
    - "qwen3:32b (UNI research, 32GB memory)"
    - "qwen3:8b (Memory & Context embedding)"
    - "deepseek-coder-v2:16b (optional, for code analysis)"
  request_format: "OpenAI-compatible /v1/chat/completions"
  cost: "Compute only (Mac Mini GPU time), no per-API cost"
```

### Anthropic Claude API

```yaml
anthropic:
  endpoint: "api.anthropic.com"
  models_used:
    - "claude-opus-4-1 (council chair, complex reasoning)"
    - "claude-sonnet-4 (synthesis, lower latency)"
  api_key: "{{ANTHROPIC_API_KEY}}"
  monthly_budget: "400 USD (council + synthesis)"
  rate_limits: "100K tokens/min (standard tier)"
```

### xAI Grok API

```yaml
xai:
  endpoint: "api.x.ai"
  model: "grok-2"
  api_key: "{{XAI_API_KEY}}"
  monthly_budget: "150 USD (intelligence scanning + council)"
  rate_limits: "100K tokens/min"
```

### Google Gemini API

```yaml
google:
  endpoint: "generativelanguage.googleapis.com"
  model: "gemini-2.0-pro"
  api_key: "{{GOOGLE_API_KEY}}"
  monthly_budget: "100 USD (intelligence + research synthesis)"
```

### Perplexity API

```yaml
perplexity:
  endpoint: "api.perplexity.ai"
  model: "sonar-pro"
  api_key: "{{PERPLEXITY_API_KEY}}"
  monthly_budget: "50 USD (fact-checking + intelligence)"
```

---

## Integration Checklist

- [ ] Paperclip instance running (host: {{PAPERCLIP_HOST}}, port: {{PAPERCLIP_PORT}})
- [ ] NCL company created in Paperclip
- [ ] 4 agents registered (UNI, Awarebot-FPC, Strategy, Memory)
- [ ] API keys configured (Anthropic, xAI, Google, Perplexity)
- [ ] Ollama endpoint accessible (localhost:11434)
- [ ] Mandate workflow automated (input → council → approved → issue → output)
- [ ] Feedback ingestion pipeline live (NCC/BRS/AAC reports → activities)
- [ ] Budget tracking enabled in Paperclip
- [ ] Telegram bot alerts configured
- [ ] MWP folder structure created + synced with Paperclip
- [ ] Tailscale or Cloudflare Tunnel bridging iPhone to Paperclip (optional, for remote access)
