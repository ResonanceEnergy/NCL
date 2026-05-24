# NARTIX Council Agents

Canonical agent definitions for the NARTIX AI council and operational agents. These map to Paperclip agent registrations and define roles within the ecosystem.

## Council Agents (Multi-LLM)

### Claude-Chair
- **Role**: Permanent council moderator
- **Adapter**: claude_local (Claude Desktop Max)
- **Model**: Claude Opus 4.6
- **Pillar**: NCL
- **Responsibilities**:
  - Chair all council deliberations using advanced multi-LLM collaboration strategies
  - Synthesize debate into mandates
  - Run the Claude→Copilot hybrid coding loop in 03-Execution
  - Enforce MWP folder conventions
  - Sign off completed executions
  - Produce feedback synthesis reports

### Researcher (UNI)
- **Role**: Investigation and fact-checking
- **Adapter**: Perplexity API (sonar-pro)
- **Pillar**: NCL (UNI sub-division)
- **Responsibilities**:
  - Deep research with sourced citations
  - Fact-checking council claims
  - Convergence detection across research domains
  - Multi-source verification (2+ independent sources required)

### TrendsAnalyst
- **Role**: YouTube, Google Trends, News monitoring
- **Adapter**: Gemini API (gemini-3-pro)
- **Pillar**: NCL (Awarebot-FPC)
- **Responsibilities**:
  - YouTube channel monitoring and transcript analysis
  - Google Trends anomaly detection
  - News aggregation and sentiment analysis
  - Large-context document analysis

### IntelScanner (Awarebot-FPC)
- **Role**: Real-time intelligence scanning
- **Adapter**: Grok API (grok-4) + X integration
- **Pillar**: NCL (Awarebot-FPC)
- **Responsibilities**:
  - X/Twitter feed monitoring (5-minute intervals)
  - Reddit signal extraction
  - Polymarket probability drift detection
  - Importance scoring and convergence alerting
  - CRITICAL alert escalation to NCL

## Intelligence Council Agents

### YouTubeCouncil
- **Role**: YouTube intelligence gathering and analysis
- **Adapter**: claude_local (primary) → grok → ollama_local (fallback chain)
- **Pillar**: NCL (Awarebot-FPC)
- **Pipeline**: Scrape → Download → Transcribe → Analyze
- **Responsibilities**:
  - Scrape configured YouTube channels via yt-dlp (default: @NathansMRE, @substandard5858)
  - Download and cache audio from last 24 hours of uploads
  - Transcribe via faster-whisper (CPU int8) → mlx-whisper (Apple Silicon) → OpenAI API fallback
  - AI analysis for content, market, geopolitical, tech, music, culture, alt-science, gaming signals
  - Produce structured CouncilReport with insights, confidence scores, and actionability flags
  - Write reports to `intelligence-scan/council-reports/`, signals to `intelligence-scan/signals/`, alerts to `intelligence-scan/alerts/`

### XCouncil
- **Role**: X (Twitter) full intelligence sweep and analysis
- **Adapter**: claude_local (primary) → grok → ollama_local (fallback chain)
- **Pillar**: NCL (Awarebot-FPC)
- **Pipeline**: Full Sweep (3 vectors) → Analyze
- **Responsibilities**:
  - Vector 1 — Account monitoring: track key accounts (NathansMRE, elikiingz, DeItaone, unusual_whales, etc.)
  - Vector 2 — Keyword intelligence: search domain-relevant terms (AI agent framework, geopolitical risk, etc.)
  - Vector 3 — Trending analysis: capture breaking topics
  - X API v2 primary with Grok-powered fallback for each vector
  - AI analysis for sentiment landscape, convergence signals, risk alerts
  - Produce structured CouncilReport with same output pipeline as YouTubeCouncil

## Operational Agents

### Engineer (NCC)
- **Role**: Execution and deployment support
- **Adapter**: claude_local + Computer Use
- **Pillar**: NCC
- **Responsibilities**:
  - Service deployment and management
  - Infrastructure health monitoring
  - Automated code review in 04-Review
  - Execution truth reporting to NCL

### WarRoomAnalyst (AAC)
- **Role**: Scenario analysis and position sizing
- **Adapter**: claude_local
- **Pillar**: AAC
- **Responsibilities**:
  - Geopolitical scenario evaluation
  - Kelly criterion position sizing
  - Doctrine state management (NORMAL → CAUTION → SAFE_MODE → HALT)
  - Capital performance reporting

### RevenueAgent (BRS)
- **Role**: Revenue operations
- **Adapter**: claude_local
- **Pillar**: BRS
- **Responsibilities**:
  - DIGITAL-LABOUR lead management and NERVE scoring
  - Proposal and pitch generation
  - Revenue tracking and conversion analysis
  - Economic signal reporting to NCL

## Multi-LLM Collaboration Strategies

Claude-Chair selects from these strategies in 02-Planning based on task complexity:

1. **Hierarchical Delegation** — Claude delegates sub-problems to specialized sub-councils
2. **Debate Tournament with Elimination** — Models compete on proposals; Claude scores and eliminates weakest
3. **Meta-Reasoning Loop** — Models critique their own and others' responses before final synthesis
4. **Simulated Annealing** — Start with creative/divergent ideas, gradually converge to optimal solution
5. **Cross-Model Knowledge Distillation** — Generate broad knowledge, distill to core insights, re-expand with specifics
6. **Uncertainty-Aware Voting** — Each model includes confidence scores and risk assessments with their vote
7. **Escalation with Human-in-the-Loop** — Package unresolvable questions for NATRIX with options + recommendations

## Budget Tracking

All agent API costs are tracked via Paperclip cost events. Monthly caps per agent are configured in `paperclip.config.json`. When any agent reaches 80% of monthly budget, Paperclip flags for review. At 100%, hard stop applies.
