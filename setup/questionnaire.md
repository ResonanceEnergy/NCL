# NCL Onboarding Questionnaire

**Purpose**: Initialize NCL configuration on first setup.
**Format**: Interactive questionnaire following MWP {{PLACEHOLDER}} conventions.
**Triggered By**: `setup` keyword in CLAUDE.md
**Output**: Config files written to setup/ and shared/

---

## Section 1: Identity & Authority

### Q1.1 — NATRIX Configuration

```
Q: Who is the NATRIX (Supreme Commander)?
A: {{NATRIX_NAME}}
   Display name: {{NATRIX_DISPLAY_NAME}}
   Identity confirmation: (Yes / No) {{NATRIX_CONFIRMED}}

Example:
  NATRIX_NAME = "Nathan Christopher Ludwig"
  NATRIX_DISPLAY_NAME = "NATRIX"
  NATRIX_CONFIRMED = "Yes"
```

### Q1.2 — NCL Authority Level

```
Q: Confirm NCL authority level in Resonance Energy?
A: {{NCL_AUTHORITY_LEVEL}}

Options:
  - "directive" (issues mandates, overrides NCC/BRS/AAC strategy)
  - "advisory" (recommends, NCC decides)

Recommended: "directive" (per CLAUDE.md)

Selection: {{NCL_AUTHORITY_LEVEL}}
```

### Q1.3 — Paperclip Integration

```
Q: Is Paperclip agent orchestration enabled?
A: {{PAPERCLIP_ENABLED}}

If Yes:
  - Paperclip host: {{PAPERCLIP_HOST}} (default: localhost)
  - Paperclip port: {{PAPERCLIP_PORT}} (default: 8765)
  - Paperclip API key: {{PAPERCLIP_API_KEY}}
  - NCL company ID in Paperclip: {{PAPERCLIP_NCL_COMPANY_ID}} (default: "ncl")

If No:
  - Fallback: File-based manifest tracking (no real-time sync)

Recommended: Yes (enables mandate approval gates + budget tracking)

Current selection: {{PAPERCLIP_ENABLED}}
```

---

## Section 2: API Keys & Credentials

### Q2.1 — Anthropic Claude API

```
Q: Provide Anthropic Claude API key (for council chair).
A: {{ANTHROPIC_API_KEY}}

Purpose:
  - Claude chairs councils (debates NCC/BRS/AAC strategy)
  - Generates mandates (complex reasoning)
  - Synthesizes feedback (multi-pillar signals)

Obtain at: https://console.anthropic.com/

Configuration:
  - Model: claude-opus-4-1 (best reasoning)
  - Rate limit: 100K tokens/min (standard)
  - Monthly budget: $400 (estimate for NCL ops)

Key: {{ANTHROPIC_API_KEY}}
Confirmed: (Yes / No) {{ANTHROPIC_KEY_CONFIRMED}}
```

### Q2.2 — xAI Grok API

```
Q: Provide xAI Grok API key (for intelligence scanning + council member).
A: {{XAI_API_KEY}}

Purpose:
  - Grok is council member (alternative perspectives)
  - Awarebot-FPC uses Grok for X/Twitter feed intelligence
  - Real-time anomaly detection (geopolitical, market signals)

Obtain at: https://api.x.ai/ (requires X Premium subscription)

Configuration:
  - Model: grok-2
  - Rate limit: 100K tokens/min
  - Monthly budget: $150 (estimate for intelligence scanning)

Key: {{XAI_API_KEY}}
Confirmed: (Yes / No) {{XAI_KEY_CONFIRMED}}
```

### Q2.3 — Google Gemini API

```
Q: Provide Google Gemini API key (for intelligence + research).
A: {{GOOGLE_API_KEY}}

Purpose:
  - Gemini is council member (research synthesis)
  - YouTube channel monitoring (via Gemini API)
  - Large context window for document analysis

Obtain at: https://makersuite.google.com/app/apikey

Configuration:
  - Model: gemini-2.0-pro (best for analysis)
  - Rate limit: 100 req/min (free tier) or higher (paid)
  - Monthly budget: $100 (estimate)

Key: {{GOOGLE_API_KEY}}
Confirmed: (Yes / No) {{GOOGLE_KEY_CONFIRMED}}
```

### Q2.4 — Perplexity API

```
Q: Provide Perplexity API key (for fact-checking + research).
A: {{PERPLEXITY_API_KEY}}

Purpose:
  - Perplexity is council member (real-time fact-checking)
  - Validates market signals against current data
  - Identifies contradictions in intelligence

Obtain at: https://www.perplexity.ai/api

Configuration:
  - Model: sonar-pro
  - Rate limit: 10 req/min (free), 100+ (pro)
  - Monthly budget: $50 (estimate)

Key: {{PERPLEXITY_API_KEY}}
Confirmed: (Yes / No) {{PERPLEXITY_KEY_CONFIRMED}}
```

### Q2.5 — OpenAI GPT API (Optional)

```
Q: Provide OpenAI GPT API key? (Optional for council member)
A: {{OPENAI_API_KEY}}

Purpose:
  - GPT is optional council member (creative problem-solving)
  - Not required for core NCL functionality

Obtain at: https://platform.openai.com/api/keys

Key (if provided): {{OPENAI_API_KEY}}
Enabled: (Yes / No) {{OPENAI_ENABLED}}
```

### Q2.6 — Ollama Endpoint (Local Inference)

```
Q: Ollama running on Mac Mini? (UNI research cortex uses qwen3:32b)
A: {{OLLAMA_ENABLED}}

If Yes:
  - Ollama host: {{OLLAMA_HOST}} (default: localhost)
  - Ollama port: {{OLLAMA_PORT}} (default: 11434)
  - Models installed:
    * {{OLLAMA_MODEL_1}} (default: qwen3:32b)
    * {{OLLAMA_MODEL_2}} (optional: qwen3:8b)
  - GPU acceleration: Metal (Apple Silicon) / CUDA (NVIDIA)

If No:
  - UNI research uses Claude API as fallback (higher cost)
  - Memory embedding uses Anthropic API (higher latency)

Recommended: Yes (lower cost, faster inference)

Current setting: {{OLLAMA_ENABLED}}
```

---

## Section 3: Intelligence Scanning

### Q3.1 — Awarebot-FPC Sources

```
Q: Configure Awarebot-FPC intelligence scanning sources.
A: {{AWAREBOT_SOURCES}}

Scanning includes:
  - X (Twitter) feed monitoring
  - YouTube channel tracking
  - Reddit subreddit monitoring

For each source type:

X HANDLES (comma-separated):
  {{X_HANDLES}}
  Example: @NATRIX, @naval, @ViperReport

YouTube CHANNELS (comma-separated):
  {{YOUTUBE_CHANNELS}}
  Example: @WSJ, @MrBeast, @AI_RESEARCH

Reddit SUBREDDITS (comma-separated):
  {{REDDIT_SUBREDDITS}}
  Example: r/investing, r/MachineLearning, r/geopolitics

Polling frequency (minutes):
  {{AWAREBOT_POLLING_INTERVAL}} (default: 5 minutes)

Alert confidence threshold:
  {{AWAREBOT_CONFIDENCE_THRESHOLD}} (default: 0.75, range 0.5–0.95)
  (Only signals above this confidence trigger Telegram alerts)
```

### Q3.2 — Anomaly Detection

```
Q: Configure anomaly detection sensitivity.
A: {{ANOMALY_SENSITIVITY}}

Sensitivity levels:
  - "high" (flag any signal > 0.75 confidence, more false positives)
  - "medium" (flag signals > 0.80 confidence, balanced)
  - "low" (flag only signals > 0.90 confidence, fewer alerts)

Recommended: "medium"

Selection: {{ANOMALY_SENSITIVITY}}

False positive tolerance:
  {{ANOMALY_FALSE_POSITIVE_TOLERANCE}} (default: 0.20, 20% acceptable)
```

---

## Section 4: Memory & Context

### Q4.1 — Memory Decay Parameters

```
Q: Configure memory decay policy.
A: {{MEMORY_DECAY_CONFIG}}

Memory decay settings:
  - Decay frequency: {{MEMORY_DECAY_FREQUENCY}} (default: weekly)
  - Confidence threshold: {{MEMORY_CONFIDENCE_THRESHOLD}} (default: 0.7)
    (Memories below 0.7 confidence moved to archive after decay)
  - Access-based archival: {{MEMORY_ARCHIVAL_DAYS}} days without access
    (default: 60, archive if not accessed in 60 days)
  - Retention policy: {{MEMORY_RETENTION_MONTHS}} months
    (default: 12, completely delete after 12 months)

Recommended defaults: Keep as-is (conservative decay)

Current selection: {{MEMORY_DECAY_CONFIG}}
```

### Q4.2 — Memory Indexing

```
Q: Memory storage backend?
A: {{MEMORY_BACKEND}}

Options:
  - "yaml" (simple, no indexing, slower recalls)
  - "sqlite" (indexed, fast recalls < 500ms)
  - "vector_db" (Weaviate, Pinecone — requires extra setup)

Recommended: "sqlite" (good balance)

Selection: {{MEMORY_BACKEND}}

If SQLite:
  - Database path: {{MEMORY_DB_PATH}} (default: shared/memory.db)
  - Embedding model: {{MEMORY_EMBEDDING_MODEL}} (default: qwen3:8b via Ollama)
```

---

## Section 5: Research Pipeline (UNI)

### Q5.1 — Research Domains

```
Q: What domains should UNI focus research on?
A: {{UNI_RESEARCH_DOMAINS}}

Select one or more (comma-separated):
  - "alt-science" (non-mainstream but rigorous research)
  - "deep-science" (frontier physics, neuroscience, AI safety)
  - "market-research" (financial systems, commodities)
  - "geopolitics" (signals for AAC war room)
  - "technology" (AI trends, infrastructure)
  - "custom" (specify: {{CUSTOM_RESEARCH_DOMAIN}})

Recommended: "alt-science", "deep-science", "market-research", "geopolitics"

Current selection: {{UNI_RESEARCH_DOMAINS}}
```

### Q5.2 — Research Output Requirements

```
Q: What research output format?
A: {{UNI_OUTPUT_FORMAT}}

Options:
  - "brief" (2-3 page summary, quick turnaround)
  - "comprehensive" (10+ page report, 2–4 week research cycle)
  - "both" (brief + comprehensive, flexible deadline)

Recommended: "both"

Selection: {{UNI_OUTPUT_FORMAT}}

Convergence detection (auto-tag signals that align across domains)?
  {{UNI_CONVERGENCE_DETECTION}} (Yes / No, default: Yes)
```

---

## Section 6: Feedback Loop

### Q6.1 — Feedback Report Cadence

```
Q: How often should feedback reports be synthesized?
A: {{FEEDBACK_SYNTHESIS_CADENCE}}

Options:
  - "continuous" (as reports arrive, < 30 min latency)
  - "daily" (morning 09:00 + evening 18:00 UTC)
  - "weekly" (Monday morning, less responsive)

Recommended: "daily" (operational balance)

Selection: {{FEEDBACK_SYNTHESIS_CADENCE}}
```

### Q6.2 — Mandate Adjustment Thresholds

```
Q: When should mandates be automatically re-evaluated?
A: {{MANDATE_ADJUSTMENT_THRESHOLDS}}

Trigger adjustments if:
  - NCC progress drops below: {{MANDATE_PROGRESS_THRESHOLD}} %
    (default: 10% slip triggers review)
  - BRS revenue signal contradicts forecast by: {{BRS_REVENUE_VARIANCE}} %
    (default: 20% variance)
  - AAC P&L variance exceeds: {{AAC_PNL_VARIANCE}} %
    (default: 15% variance)
  - New signal confidence > {{NEW_SIGNAL_THRESHOLD}} (default: 0.85)
    (high-confidence signals trigger mandate review)

Recommended defaults: Keep as-is

Current selection: {{MANDATE_ADJUSTMENT_THRESHOLDS}}
```

---

## Section 7: Alerts & Notifications

### Q7.1 — Telegram Bot Setup

```
Q: Enable Telegram alerts for NCL events?
A: {{TELEGRAM_ENABLED}}

If Yes:
  - Telegram Bot Token: {{TELEGRAM_BOT_TOKEN}}
    (Create bot via @BotFather on Telegram)
  - Telegram Chat ID: {{TELEGRAM_CHAT_ID}}
    (Your personal chat ID or group chat)
  - Alert types to enable:
    * P1 mandate blocked: {{ALERT_P1_BLOCKED}} (Yes / No, default: Yes)
    * Signal contradiction detected: {{ALERT_CONTRADICTION}} (default: Yes)
    * UNI research anomaly: {{ALERT_UNI_ANOMALY}} (default: Yes)
    * Feedback synthesis complete: {{ALERT_SYNTHESIS_DONE}} (default: No)
    * Budget threshold exceeded: {{ALERT_BUDGET}} (default: Yes)

Recommended: Yes (real-time awareness of critical events)

Current setting: {{TELEGRAM_ENABLED}}
```

### Q7.2 — Logging Level

```
Q: Activity logging verbosity?
A: {{LOG_LEVEL}}

Options:
  - "DEBUG" (very verbose, all events logged)
  - "INFO" (normal, important events only)
  - "WARN" (quiet, warnings + errors only)

Recommended: "INFO"

Selection: {{LOG_LEVEL}}

Log retention (days):
  {{LOG_RETENTION_DAYS}} (default: 90 days, then archive)
```

---

## Section 8: Review & Confirmation

### Q8.1 — Configuration Summary

```
CONFIGURATION SUMMARY
=====================

Identity:
  NATRIX: {{NATRIX_NAME}}
  NCL Authority: {{NCL_AUTHORITY_LEVEL}}
  Paperclip: {{PAPERCLIP_ENABLED}}

APIs:
  Anthropic Claude: {{ANTHROPIC_KEY_CONFIRMED}}
  xAI Grok: {{XAI_KEY_CONFIRMED}}
  Google Gemini: {{GOOGLE_KEY_CONFIRMED}}
  Perplexity: {{PERPLEXITY_KEY_CONFIRMED}}
  Ollama: {{OLLAMA_ENABLED}}

Intelligence:
  X Handles: {{X_HANDLES}}
  YouTube Channels: {{YOUTUBE_CHANNELS}}
  Reddit Subreddits: {{REDDIT_SUBREDDITS}}
  Anomaly Sensitivity: {{ANOMALY_SENSITIVITY}}

Memory:
  Backend: {{MEMORY_BACKEND}}
  Decay Frequency: {{MEMORY_DECAY_FREQUENCY}}

Research (UNI):
  Domains: {{UNI_RESEARCH_DOMAINS}}
  Output Format: {{UNI_OUTPUT_FORMAT}}

Feedback:
  Synthesis Cadence: {{FEEDBACK_SYNTHESIS_CADENCE}}

Alerts:
  Telegram: {{TELEGRAM_ENABLED}}
  Log Level: {{LOG_LEVEL}}

---

CONFIRM ALL SETTINGS? (Yes / No)
{{CONFIRM_ALL}}

If No: Go back to section number {{SECTION_TO_REVIEW}}
If Yes: Proceed to write configuration files
```

### Q8.2 — File Generation

```
If confirmed, the following files will be created:

  1. setup/config.yaml
     - All {{PLACEHOLDER}} values replaced
     - Machine-readable NCL configuration
     - Loaded on every startup

  2. setup/env.local
     - API keys (ANTHROPIC_API_KEY, XAI_API_KEY, etc.)
     - NOT checked into git
     - Source this before running NCL

  3. setup/sources.md
     - X handles, YouTube channels, Reddit subs
     - Used by Awarebot-FPC for polling

  4. shared/doctrine/roadmap.md
     - Generated from research domains + feedback cadence
     - Shows quarterly objectives for NCL

  5. Paperclip registration (if enabled)
     - NCL company created
     - 4 agents registered (UNI, Awarebot, Strategy, Memory)
     - Budget tracking initialized

---

PROCEED WITH FILE CREATION? (Yes / No)
{{PROCEED_CREATION}}
```

---

## Output: Generated Files

### setup/config.yaml

```yaml
# NCL Configuration — Auto-generated by questionnaire
# Generated: {{TIMESTAMP}}

identity:
  natrix_name: "{{NATRIX_NAME}}"
  natrix_confirmed: {{NATRIX_CONFIRMED}}
  ncl_authority_level: "{{NCL_AUTHORITY_LEVEL}}"
  paperclip_enabled: {{PAPERCLIP_ENABLED}}

paperclip:
  host: "{{PAPERCLIP_HOST}}"
  port: {{PAPERCLIP_PORT}}
  api_key: "{{PAPERCLIP_API_KEY}}"
  ncl_company_id: "{{PAPERCLIP_NCL_COMPANY_ID}}"

apis:
  anthropic:
    api_key: "{{ANTHROPIC_API_KEY}}"  # Loaded from env.local
    model: "claude-opus-4-1"
    monthly_budget_usd: 400

  xai:
    api_key: "{{XAI_API_KEY}}"  # Loaded from env.local
    model: "grok-2"
    monthly_budget_usd: 150

  google:
    api_key: "{{GOOGLE_API_KEY}}"  # Loaded from env.local
    model: "gemini-2.0-pro"
    monthly_budget_usd: 100

  perplexity:
    api_key: "{{PERPLEXITY_API_KEY}}"  # Loaded from env.local
    model: "sonar-pro"
    monthly_budget_usd: 50

  openai:
    api_key: "{{OPENAI_API_KEY}}"  # Loaded from env.local (optional)
    enabled: {{OPENAI_ENABLED}}

ollama:
  enabled: {{OLLAMA_ENABLED}}
  host: "{{OLLAMA_HOST}}"
  port: {{OLLAMA_PORT}}
  models:
    - "{{OLLAMA_MODEL_1}}"
    - "{{OLLAMA_MODEL_2}}"

awarebot:
  x_handles: "{{X_HANDLES}}"
  youtube_channels: "{{YOUTUBE_CHANNELS}}"
  reddit_subreddits: "{{REDDIT_SUBREDDITS}}"
  polling_interval_minutes: {{AWAREBOT_POLLING_INTERVAL}}
  confidence_threshold: {{AWAREBOT_CONFIDENCE_THRESHOLD}}
  sensitivity: "{{ANOMALY_SENSITIVITY}}"

memory:
  backend: "{{MEMORY_BACKEND}}"
  db_path: "{{MEMORY_DB_PATH}}"
  embedding_model: "{{MEMORY_EMBEDDING_MODEL}}"
  decay:
    frequency: "{{MEMORY_DECAY_FREQUENCY}}"
    confidence_threshold: {{MEMORY_CONFIDENCE_THRESHOLD}}
    archival_days: {{MEMORY_ARCHIVAL_DAYS}}
    retention_months: {{MEMORY_RETENTION_MONTHS}}

research:
  domains: "{{UNI_RESEARCH_DOMAINS}}"
  output_format: "{{UNI_OUTPUT_FORMAT}}"
  convergence_detection: {{UNI_CONVERGENCE_DETECTION}}

feedback:
  synthesis_cadence: "{{FEEDBACK_SYNTHESIS_CADENCE}}"
  progress_threshold_pct: {{MANDATE_PROGRESS_THRESHOLD}}
  brs_variance_threshold_pct: {{BRS_REVENUE_VARIANCE}}
  aac_variance_threshold_pct: {{AAC_PNL_VARIANCE}}
  signal_confidence_threshold: {{NEW_SIGNAL_THRESHOLD}}

alerts:
  telegram_enabled: {{TELEGRAM_ENABLED}}
  telegram_bot_token: "{{TELEGRAM_BOT_TOKEN}}"  # Loaded from env.local
  telegram_chat_id: "{{TELEGRAM_CHAT_ID}}"
  alert_types:
    p1_blocked: {{ALERT_P1_BLOCKED}}
    contradiction: {{ALERT_CONTRADICTION}}
    uni_anomaly: {{ALERT_UNI_ANOMALY}}
    synthesis_done: {{ALERT_SYNTHESIS_DONE}}
    budget_exceeded: {{ALERT_BUDGET}}

logging:
  level: "{{LOG_LEVEL}}"
  retention_days: {{LOG_RETENTION_DAYS}}
```

### setup/env.local (Git-ignored)

```bash
# NCL Environment Variables — NEVER commit to git
# Created: {{TIMESTAMP}}

export ANTHROPIC_API_KEY="{{ANTHROPIC_API_KEY}}"
export XAI_API_KEY="{{XAI_API_KEY}}"
export GOOGLE_API_KEY="{{GOOGLE_API_KEY}}"
export PERPLEXITY_API_KEY="{{PERPLEXITY_API_KEY}}"
export OPENAI_API_KEY="{{OPENAI_API_KEY}}"
export TELEGRAM_BOT_TOKEN="{{TELEGRAM_BOT_TOKEN}}"
export PAPERCLIP_API_KEY="{{PAPERCLIP_API_KEY}}"

# Usage: source setup/env.local before running NCL
```

---

## Next Steps (Post-Setup)

1. **Review generated files**
   - `cat setup/config.yaml` to confirm all values
   - `source setup/env.local` to load API keys

2. **Create MWP folder structure**
   - `mkdir -p mandate-generation/input council output`
   - `mkdir -p research-pipeline/queue active archive`
   - `mkdir -p intelligence-scan/sources alerts signals`
   - `mkdir -p memory-processing/long-term working decay`
   - `mkdir -p feedback-synthesis/ncc-reports brs-reports aac-reports synthesis`

3. **Register with Paperclip**
   - If PAPERCLIP_ENABLED, Paperclip registration runs automatically
   - Verify NCL company + 4 agents visible in Paperclip UI

4. **Test API connections**
   - Run health check: `python -m ncl.health_check`
   - Verify all API keys valid
   - Test Ollama endpoint (if enabled)

5. **Start monitoring**
   - Awarebot-FPC begins scanning sources
   - Watch Telegram for first alerts
   - Review intelligence-scan/signals/ folder

6. **Load context files**
   - Run `source setup/env.local` in every terminal session
   - Or add to ~/.zshrc: `source {{NCL_PROJECT_PATH}}/setup/env.local`

---

## Support

For issues or questions:
- Check CLAUDE.md (Layer 0 overview)
- Check CONTEXT.md (Layer 1 routing)
- Check _core/CONVENTIONS.md (NCL-specific patterns)
- Contact: NATRIX (absolute authority)
