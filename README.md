# NCL — NuRealCortexLink

NATRIX's second brain. The strategic thinking, intelligence, and command layer for the Resonance Energy portfolio.

Think, Research, Plan, Decide, Monitor.

**Part of the Resonance Energy portfolio. See `RESONANCE_ENERGY_SOT.md` for system boundaries and architecture.**

## Overview

NCL is the top of the hierarchy. It:

- **Receives NATRIX's intent** via pump prompts (iPhone → Grok → NCL)
- **Spawns council sessions** with Claude, Grok, Gemini, Perplexity, GPT for multi-AI debate
- **Generates mandates** for downstream projects (Bit Rage Labour, AAC)
- **Monitors all projects** via their APIs — Bit Rage on Railway, AAC (future)
- **Manages institutional memory** with episodic→semantic consolidation and decay
- **Scans intelligence sources** (X, YouTube, Reddit) via Awarebot-FPC
- **Coordinates with Paperclip** for issue tracking and cost accounting
- **Runs 24/7** on Mac Mini M4 Pro as a headless service

## Architecture

```
NATRIX (iPhone → Grok)
    ↓ pump_prompt
NCL Brain (FastAPI on 0.0.0.0:8800)
    ├─ Council Engine (Claude as chair + Grok/Gemini/Perplexity/GPT)
    ├─ Memory Store (three-phase lifecycle, decay/reinforcement)
    ├─ Awarebot Scanner (X, YouTube, Reddit signals)
    ├─ Future Predictor (ensemble forecasts)
    ├─ Digital Labour Bridge (NCL → Bit Rage API)
    └─ Paperclip Adapter (issue creation, activity logging, cost tracking)

Downstream Projects (monitored via API):
    ├─ Bit Rage Labour → Railway (bitrage-labour-api-production.up.railway.app)
    └─ AAC → TBD
```

## Installation

### Requirements

- Python 3.12+
- Mac Mini M4 Pro (Apple Silicon)
- Ollama running locally (localhost:11434)
- Anthropic API key
- Optional: xAI, Google, Perplexity, OpenAI API keys
- Optional: X, YouTube, Reddit API credentials

### Setup

```bash
cd ~/dev/NCL

# Create venv
python3.12 -m venv venv
source venv/bin/activate

# Install
pip install -e ".[dev]"

# Create config
ncl-create-config
# Edit ~/NCL/config/ncl.yaml with your API keys

# Run
ncl
```

Or via Docker:

```bash
docker build -t ncl-brain .
docker run -p 8800:8800 \
  -e NCL_ANTHROPIC_API_KEY=sk-... \
  -e NCL_XAI_API_KEY=xai-... \
  ncl-brain
```

## Configuration

Configuration loads from (priority order):

1. Environment variables (`NCL_*`)
2. `~/NCL/config/ncl.yaml`
3. Defaults

Example `ncl.yaml`:

```yaml
service_name: ncl-brain
port: 8800
debug: false

anthropic_api_key: sk-ant-...
xai_api_key: xai-...
google_api_key: ...
perplexity_api_key: ...
openai_api_key: sk-...

x_bearer_token: ...
youtube_api_key: ...

ollama_host: localhost:11434

paperclip_host: localhost
paperclip_port: 8765

x_scan_interval: 300
youtube_scan_interval: 600
prediction_interval: 1800
```

## API Endpoints

### Health & Status

- `GET /health` — Service health check
- `GET /` — Service info

### Pump Prompts (from Grok)

- `POST /pump` — Receive pump prompt from iPhone

### Council Sessions

- `POST /council/spawn` — Spawn council debate session
- `GET /council/session/{session_id}` — Get session details

### Mandates

- `POST /mandates` — Create mandate
- `GET /mandates` — List mandates (filters: pillar, status)
- `GET /mandates/{mandate_id}` — Get mandate details
- `POST /mandates/{mandate_id}/complete` — Mark complete

### Memory

- `GET /memory/query` — Query memory (filters: tags, importance, days_back)

### Feedback

- `POST /feedback` — Receive feedback from downstream pillar

### Awarebot

- `POST /awarebot/scan` — Run intelligence scan (queries: list[str])

### Prediction

- `POST /prediction` — Run ensemble forecast (topic: str)

## Example Usage

### Create Pump Prompt

```bash
curl -X POST http://localhost:8800/pump \
  -H "Content-Type: application/json" \
  -d '{
    "prompt_id": "pump-001",
    "source": "grok-iphone",
    "intent": "Evaluate market entry for DIGITAL-LABOUR in Asia",
    "context": {"region": "Asia", "urgency": "high"},
    "urgency": "high"
  }'
```

### Spawn Council Session

```bash
curl -X POST http://localhost:8800/council/spawn \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "Geopolitical impact on BRS revenue",
    "prompt": "Based on recent signals, assess if geopolitical tensions will impact DIGITAL-LABOUR adoption in Q2 2026"
  }'
```

### Create Mandate

```bash
curl -X POST http://localhost:8800/mandates \
  -H "Content-Type: application/json" \
  -d '{
    "pillar": "ncc",
    "priority": 8,
    "title": "Deploy Asia Market Intelligence Pipeline",
    "objective": "Stand up automated market analysis for 5 Asian markets",
    "success_criteria": [
      "Pipeline scans 10 sources per day",
      "Daily forecasts generated",
      "Zero data quality issues"
    ],
    "deadline": "2026-05-01T00:00:00"
  }'
```

### Query Memory

```bash
curl "http://localhost:8800/memory/query?tags=geopolitical&tags=risk&importance_threshold=60"
```

### Run Awarebot Scan

```bash
curl -X POST http://localhost:8800/awarebot/scan \
  -H "Content-Type: application/json" \
  -d '{
    "queries": [
      "Asia market regulation 2026",
      "US-China tech competition",
      "AI startup funding trends"
    ]
  }'
```

### Run Prediction

```bash
curl -X POST http://localhost:8800/prediction \
  -H "Content-Type: application/json" \
  -d '{"topic": "Asia market adoption of AI automation"}'
```

## Data Storage

All data lives in `~/NCL/data/`:

- `events.ndjson` — Event log (pump prompts, council sessions, mandates, feedback)
- `mandates.json` — Current mandates state
- `memory/units.jsonl` — Memory units with decay/reinforcement
- `state.json` — Service state snapshot

## Memory System

NCL uses a three-phase memory lifecycle:

1. **Episodic Traces** — Raw pump prompts, council responses, feedback
2. **Semantic MemUnits** — Consolidated knowledge units with importance scoring
3. **Reconstructive Recollection** — Retrieve and reinforce on access

Memory units decay exponentially: `importance *= decay_rate^(days_since_access)`

Each access reinforces: `importance *= 1.2`

Query by tags, importance threshold, date range.

## Council Engine

Multi-AI debate system:

- Claude (Anthropic) as permanent chair
- Grok (xAI), Gemini (Google), Perplexity, GPT (OpenAI) as members
- Fallback to local Ollama models (qwen3:32b, deepseek-coder) if APIs unavailable
- Async debate protocol: chair poses → members respond → chair synthesizes

## Awarebot-FPC

Awarebot consists of:

- **Scanner**: Collects InsightSignals from X, YouTube, Reddit
- **Future Predictor Council**: Ensemble prediction with convergence detection

Importance formula:
```
importance = (relevance × 0.3) + (novelty × 0.25) + (actionability × 0.25)
           + (source_authority × 0.1) + (time_sensitivity × 0.1)
```

## Paperclip Integration

NCL registers with Paperclip as a company with sub-agents:

- **NCL** — Brain (think, plan, decide)
- **UNI** — Research cortex
- **Awarebot-FPC** — Scanner + predictor
- **Strategy** — Mandate generation
- **Memory** — Living context

Logs activities, creates/updates issues from mandates, tracks API costs.

## Testing

```bash
pytest tests/ -v

# With async support
pytest tests/ -v --asyncio-mode=auto

# Coverage
pytest tests/ --cov=runtime --cov-report=html
```

## Deployment

### Local (Mac Mini)

```bash
# Start service
ncl &

# Or via launchd (24/7 daemon)
cat > ~/Library/LaunchAgents/com.resonance-energy.ncl.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.resonance-energy.ncl</string>
    <key>ProgramArguments</key>
    <array>
      <string>/usr/local/bin/python3.12</string>
      <string>-m</string>
      <string>uvicorn</string>
      <string>runtime.api.routes:versioned_app</string>
      <string>--host</string>
      <string>0.0.0.0</string>
      <string>--port</string>
      <string>8800</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/natrix/dev/NCL</string>
    <key>StandardOutPath</key>
    <string>/var/log/ncl-brain.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/ncl-brain.error.log</string>
    <key>KeepAlive</key>
    <true/>
  </dict>
</plist>
EOF

launchctl load ~/Library/LaunchAgents/com.resonance-energy.ncl.plist
```

### Docker

```bash
docker build -t resonance-energy/ncl-brain .
docker run -d \
  --name ncl-brain \
  --restart always \
  -p 8800:8800 \
  -v ~/NCL/data:/app/data \
  -v ~/NCL/config:/app/config \
  -e NCL_ANTHROPIC_API_KEY=sk-... \
  resonance-energy/ncl-brain
```

## Monitoring

Monitor service health:

```bash
# Health check
curl http://localhost:8800/health | jq

# Watch events
tail -f ~/NCL/data/events.ndjson | jq

# Monitor mandates
curl http://localhost:8800/mandates | jq
```

## Architecture Docs

See `RESONANCE_ENERGY_SOT.md` for the system-wide source of truth.
See `STRUCTURE.md` for the NCL file manifest and core classes.

## License

Proprietary - RESONANCE ENERGY
