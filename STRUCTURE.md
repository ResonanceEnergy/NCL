# NCL Brain Service - Project Structure

## File Manifest

```
NCL/
├── pyproject.toml                          # Python package config (deps, scripts, tooling)
├── README.md                               # Service documentation
├── .gitignore                              # Git ignore rules
├── STRUCTURE.md                            # This file
└── runtime/
    ├── __init__.py                         # Runtime package init
    │
    ├── ncl_brain/                          # Core brain logic
    │   ├── __init__.py
    │   ├── models.py                       # Pydantic models (all data types)
    │   ├── brain.py                        # Main NCLBrain class (orchestrator)
    │   └── council.py                      # Council debate engine
    │
    ├── awarebot/                           # Intelligence subsystem
    │   ├── __init__.py
    │   ├── scanner.py                      # Scans X, YouTube, Reddit
    │   └── predictor.py                    # Future Predictor Council (FPC)
    │
    ├── memory/                             # Memory system
    │   ├── __init__.py
    │   └── store.py                        # MemoryStore (episodic→semantic)
    │
    ├── paperclip_adapter/                  # Paperclip integration
    │   ├── __init__.py
    │   └── client.py                       # PaperclipClient
    │
    └── api/                                # FastAPI service layer
        ├── __init__.py
        ├── config.py                       # Configuration management
        └── routes.py                       # FastAPI app and endpoints
```

## Core Classes

### ncl_brain/brain.py
```
NCLBrain
├── __init__(data_dir, api_keys, ...)
├── init() → startup (Paperclip registration)
├── receive_pump_prompt(prompt) → pump_id
├── spawn_council_session(topic, prompt, members) → CouncilSession
├── create_mandate(...) → Mandate
├── get_mandate(mandate_id) → Mandate | None
├── list_mandates(pillar?, status?) → list[Mandate]
├── complete_mandate(mandate_id, notes)
├── receive_feedback(feedback) → report_id
├── query_memory(tags?, importance?, days?) → dict
├── run_awarebot_scan(queries) → dict
├── run_prediction(topic) → dict
├── health_check() → dict
└── shutdown() → cleanup subsystems
```

### ncl_brain/council.py
```
CouncilEngine
├── __init__(claude_key, xai_key, google_key, ...)
├── spawn_session(topic, prompt, members?) → CouncilSession
├── run_debate(session) → session with responses + synthesis
├── _get_member_response(member, prompt) → str
├── _call_claude(prompt) → str
├── _call_grok(prompt) → str
├── _call_gemini(prompt) → str
├── _call_perplexity(prompt) → str
├── _call_gpt(prompt) → str
├── _get_ollama_response(member, prompt) → str (fallback)
├── _synthesize_responses(session) → synthesis
└── _extract_insights(session) → (consensus, recommendations, dissents)
```

### awarebot/scanner.py
```
Scanner
├── __init__(x_token, youtube_key, reddit_creds)
├── scan_x(query, max_results) → list[InsightSignal]
├── scan_youtube(query, max_results) → list[InsightSignal]
├── scan_reddit(subreddit, max_results) → list[InsightSignal]
└── _compute_importance(signal) → float (weighted formula)
```

### awarebot/predictor.py
```
FuturePredictor
├── __init__(claude_key, ollama_host, war_room_url)
├── predict(signals, topic) → PredictionOutput
├── _predict_claude(signals, topic) → dict
├── _predict_ollama(signals, topic, model) → dict
├── _detect_convergence(predictions) → list[str]
├── _synthesize_consensus(predictions) → str
├── _compute_confidence(predictions, convergence) → float
└── _query_war_room(signals, topic) → str | None
```

### memory/store.py
```
MemoryStore
├── __init__(data_dir)
├── create_unit(content, source, importance, tags) → MemUnit
├── get_unit(unit_id) → MemUnit | None (with reinforcement)
├── search_units(tags?, importance?, days?) → list[MemUnit]
├── consolidate() → (background task)
├── _apply_decay(unit) → float (importance *= decay_rate^days)
├── _persist_unit(unit) → (NDJSON append)
├── _load_unit(unit_id) → MemUnit | None
└── _load_all_units() → list[MemUnit]
```

### paperclip_adapter/client.py
```
PaperclipClient
├── __init__(host, port, api_key?)
├── register_company(name) → company_id
├── register_agent(name, description, role) → agent_id
├── create_issue_from_mandate(mandate) → issue_id
├── update_issue_status(issue_id, status, notes)
├── log_activity(type, description, agent, metadata) → activity_id
├── track_cost(type, amount, currency, provider, metadata) → cost_id
├── heartbeat() → bool
└── _build_headers() → dict
```

### api/routes.py
```
FastAPI App (ncl-brain)
├── Lifespan manager (startup/shutdown)
├── GET  /health
├── POST /pump
├── POST /council/spawn
├── GET  /council/session/{id}
├── POST /mandates
├── GET  /mandates
├── GET  /mandates/{id}
├── POST /mandates/{id}/complete
├── GET  /memory/query
├── POST /feedback
├── POST /awarebot/scan
├── POST /prediction
├── GET  /
└── Exception handler
```

### api/config.py
```
Settings (pydantic)
├── service_name, version, host, port, debug
├── data_dir, config_dir
├── API keys (anthropic, xai, google, perplexity, openai)
├── Social media tokens (x, youtube, reddit)
├── ollama_host
├── paperclip_host, paperclip_port
├── Scan intervals (x, youtube, reddit, prediction)
└── Memory parameters (threshold, decay_rate, batch_size)

Functions:
├── load_config() → Settings (env + yaml + defaults)
└── create_config_file(dir) → config file path
```

## Data Models

All defined in `ncl_brain/models.py`:

```
PumpPrompt
├── prompt_id: str
├── source: str
├── intent: str
├── context: dict[str, Any]
├── urgency: Literal["low", "normal", "high", "critical"]
└── timestamp: datetime

Mandate
├── mandate_id: str
├── pillar: PillarType (ncl, ncc, brs, aac)
├── priority: int (1-10)
├── title: str
├── objective: str
├── success_criteria: list[str]
├── deadline: datetime | None
├── status: MandateStatus (draft, active, in_progress, completed, etc.)
└── created_at, updated_at: datetime

CouncilSession
├── session_id: str
├── topic: str
├── chair: str ("claude")
├── members: list[CouncilMember]
├── status: CouncilStatus
├── prompt: str
├── responses: dict[str, str] (member → response)
├── synthesis: str | None
├── consensus: str | None
├── recommendations: list[str]
├── dissents: list[str]
└── created_at, completed_at: datetime

MemUnit
├── unit_id: str
├── content: str
├── source: str
├── importance: float (0-100)
├── decay_rate: float (0-1)
├── last_accessed: datetime
├── reinforcement_count: int
├── tags: list[str]
└── related_units: list[str]

InsightSignal
├── signal_id: str
├── source_platform: str ("x", "youtube", "reddit")
├── content: str
├── url: str | None
├── importance_score: float (0-100, computed)
├── relevance, novelty, actionability, authority, time_sensitivity: float (0-1 components)
├── trend: str | None ("rising", "stable", "declining")
├── timestamp: datetime
└── tags: list[str]

FeedbackReport
├── report_id: str
├── origin: PillarType
├── content: str
├── signals: dict[str, Any]
├── lessons: list[str]
├── recommendations: list[str]
└── related_mandates: list[str]
```

## Data Storage

In `~/NCL/data/`:

- **events.ndjson** — Event log (one JSON object per line)
- **mandates.json** — Current mandates state (JSON array)
- **memory/units.jsonl** — Memory units (one MemUnit per line)
- **state.json** — Service state snapshot

## Startup Sequence

1. Load config (env + yaml + defaults)
2. Create data directories
3. Initialize subsystems:
   - CouncilEngine (API clients ready)
   - MemoryStore (load existing units)
   - Scanner (credentials cached)
   - FuturePredictor (ready for prediction)
   - PaperclipClient (ready to connect)
4. Register with Paperclip (company + agents)
5. Load existing mandates from disk
6. FastAPI lifespan yields → app ready at 0.0.0.0:8800

## Request Flow Example: Pump → Council → Mandate

```
1. Grok sends pump_prompt to POST /pump
   ↓
2. Brain.receive_pump_prompt() logs event, stores in memory
   ↓
3. Client calls POST /council/spawn with topic from pump intent
   ↓
4. Council Engine runs debate:
   - Chair (Claude) poses prompt
   - Members (Grok, Gemini, etc) respond
   - Chair synthesizes → consensus + recommendations
   ↓
5. Client calls POST /mandates to create mandate from council output
   ↓
6. Brain.create_mandate() creates Mandate, logs event
   ↓
7. Paperclip adapter creates issue
   ↓
8. NCC picks up mandate from GET /mandates?pillar=ncc
   ↓
9. When done, NCC calls POST /mandates/{id}/complete
   ↓
10. Brain marks complete, logs to Paperclip
```

## Environment Variables

All use `NCL_` prefix:

- `NCL_ANTHROPIC_API_KEY` → anthropic_api_key
- `NCL_XAI_API_KEY` → xai_api_key
- `NCL_GOOGLE_API_KEY` → google_api_key
- `NCL_PERPLEXITY_API_KEY` → perplexity_api_key
- `NCL_OPENAI_API_KEY` → openai_api_key
- `NCL_X_BEARER_TOKEN` → x_bearer_token
- `NCL_YOUTUBE_API_KEY` → youtube_api_key
- `NCL_REDDIT_CLIENT_ID` → reddit_client_id
- `NCL_REDDIT_CLIENT_SECRET` → reddit_client_secret
- `NCL_OLLAMA_HOST` → ollama_host (default: localhost:11434)
- `NCL_PAPERCLIP_HOST` → paperclip_host
- `NCL_PAPERCLIP_PORT` → paperclip_port
- `NCL_PORT` → port (default: 8800)
- `NCL_DEBUG` → debug (true/false)

## Testing

Create `tests/` directory with:

- `test_brain.py` — Test NCLBrain class
- `test_council.py` — Test CouncilEngine
- `test_memory.py` — Test MemoryStore
- `test_scanner.py` — Test Scanner
- `test_routes.py` — Test FastAPI endpoints

Use pytest + pytest-asyncio for async test support.

## Next Steps

1. Install dependencies: `pip install -e ".[dev]"`
2. Set API keys in `~/NCL/config/ncl.yaml` or env
3. Run service: `ncl` or `uvicorn runtime.api.routes:app`
4. Test endpoints via curl or Postman
5. Integrate with NCC for mandate delivery
6. Set up launchd for 24/7 daemon on Mac Mini
