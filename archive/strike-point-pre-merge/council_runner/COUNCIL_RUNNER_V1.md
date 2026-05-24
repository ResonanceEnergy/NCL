# Council Runner v1 — Planner/Skeptic/Risk Parallel Agents

**RESONANCE ENERGY / NARTIX Component** for the NCL brain pipeline (FastAPI port 8800).

## Overview

Council Runner v1 implements a specialized 3-agent parallel architecture that runs concurrent AI agents with distinct reasoning lenses:

- **PLANNER**: Strategic planning and execution roadmaps (Claude, temp 0.3)
- **SKEPTIC**: Challenge assumptions, identify weaknesses (Grok, temp 0.5)
- **RISK**: Risk quantification, mitigation strategies (Grok, temp 0.4)

All three agents receive the same prompt, run in parallel via `asyncio.gather()`, and their outputs merge into a single consensus result with provenance tracking and deterministic replay capability.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ run_parallel_council(topic, prompt, context)                │
└─────────────────────┬───────────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
    [asyncio.gather]
        │             │             │
    ┌───▼──┐      ┌──▼──┐      ┌──▼──┐
    │PLANNER│      │SKEPTIC    │RISK │
    │(Claude)      │(Grok)     │(Grok)
    └───┬──┘      └──┬──┘      └──┬──┘
        │ AgentOutput │ AgentOutput │
        └─────────────┼─────────────┘
                      │
        ┌─────────────▼─────────────┐
        │ _synthesize_consensus()   │
        └─────────────┬─────────────┘
                      │
        ┌─────────────▼──────────────────┐
        │ CouncilRunRecord               │
        │ ├─ agent_outputs (3)           │
        │ ├─ consensus (merged)          │
        │ ├─ provenance (full audit)     │
        │ ├─ replay_seed (deterministic) │
        │ └─ snapshot (state replay)     │
        └────────────────────────────────┘
```

## File Structure

```
council_runner/
├── __init__.py           # Public exports
├── models.py             # Pydantic v2 models (~5.5KB)
├── agents.py             # Agent configs, execution, synthesis (~17KB)
├── replay.py             # Deterministic replay engine (~6.4KB)
├── store.py              # JSONL + JSON persistence (~6.3KB)
├── example_usage.py      # Demo script with all features
└── COUNCIL_RUNNER_V1.md  # This documentation
```

## Models (models.py)

### AgentRole Enum
```python
class AgentRole(str, Enum):
    PLANNER = "planner"
    SKEPTIC = "skeptic"
    RISK = "risk"
```

### AgentConfig
Configuration for a single agent:
```python
@dataclass
class AgentConfig:
    role: AgentRole
    system_prompt: str
    model_preference: str  # "claude", "grok", "ollama"
    temperature: float
    max_tokens: int
```

### AgentOutput
Result from a single agent's execution:
```python
@dataclass
class AgentOutput:
    role: AgentRole
    response_text: str
    confidence: float  # 0-1
    key_points: list[str]
    dissent_notes: list[str]
    risks_identified: list[str]
    duration_ms: int
    model_used: str
    token_count: int
    timestamp: str
```

### ConsensusResult
Merged output from all three agents:
```python
@dataclass
class ConsensusResult:
    consensus_text: str
    consensus_score: int  # 0-100
    agreement_areas: list[str]
    dissent_areas: list[str]
    risk_flags: list[str]
    recommendations: list[str]
```

### CouncilRunRecord
Complete execution record with provenance:
```python
@dataclass
class CouncilRunRecord:
    run_id: str
    topic: str
    prompt: str
    timestamp: str
    agent_outputs: list[AgentOutput]
    consensus: Optional[ConsensusResult]
    provenance: dict[str, Any]
    replay_seed: str
    snapshot: dict[str, Any]  # For deterministic replay
    total_duration_ms: int
```

### ReplayConfig
Configuration for deterministic replay:
```python
@dataclass
class ReplayConfig:
    run_id: str
    replay_seed: str
    force_models: dict[str, str]  # role → model override
    temperature_override: Optional[float]
```

## API (agents.py)

### get_agent_configs() → dict[AgentRole, AgentConfig]
Returns the three pre-configured agent definitions.

### async run_agent(config: AgentConfig, prompt: str, context: dict = None, replay_seed: str = None) → AgentOutput
Execute a single agent:
- Calls the LLM via Claude → Grok → Ollama fallback chain
- Parses JSON response for structured outputs
- Records duration, model used, token count
- Returns `AgentOutput` with all metadata

### async run_parallel_council(topic: str, prompt: str, context: dict = None, replay_config: ReplayConfig = None) → CouncilRunRecord
Execute all three agents in parallel:
- Runs via `asyncio.gather()`
- Merges outputs via `_synthesize_consensus()`
- Records full provenance and snapshot
- Supports deterministic replay via `replay_seed`
- Returns complete `CouncilRunRecord`

### _synthesize_consensus(outputs: list[AgentOutput]) → ConsensusResult
Merge three agent outputs:
- **Agreement areas**: Points appearing in 2+ agents
- **Dissent areas**: Points unique to one agent
- **Risk flags**: All risks identified by Risk agent
- **Consensus score**: Based on confidence overlap + agreement ratio (0-100)
- **Recommendations**: Deduped from all agents

## Replay & Persistence

### ReplayEngine (replay.py)
```python
engine = ReplayEngine(data_dir="./data")

# Save a run
await engine.save_run(record)

# Load a run
record = await engine.load_run(run_id)

# Replay with same seed (optionally override models/temperature)
replayed = await engine.replay(
    run_id,
    force_models={"planner": "grok"},
    temperature_override=0.2
)

# Compare two runs
diff = await engine.compare_runs(run_id_a, run_id_b)

# List recent runs
runs = await engine.list_runs(limit=50)
```

### CouncilRunStore (store.py)
```python
store = CouncilRunStore(data_dir="./data")

# Save a run (JSONL + individual JSON)
await store.save_run(record)

# Retrieve a run
record = await store.get_run(run_id)

# List with pagination
runs = await store.list_runs(limit=50, offset=0)

# Search by topic/prompt
results = await store.search_runs("AI integration", limit=20)

# Get aggregate stats
stats = await store.get_stats()

# Get full provenance for a run
prov = await store.get_provenance(run_id)
```

## Usage Example

```python
import asyncio
from council_runner import run_parallel_council, CouncilRunStore

async def main():
    # Run the council
    record = await run_parallel_council(
        topic="AI Integration Strategy",
        prompt="How should we integrate AI into our product?",
        context={"budget_millions": 2, "timeline_months": 6}
    )

    # Save to disk
    store = CouncilRunStore()
    await store.save_run(record)

    # Display results
    print(f"Consensus Score: {record.consensus.consensus_score}/100")
    print(f"Agreement Areas: {record.consensus.agreement_areas}")
    print(f"Risk Flags: {record.consensus.risk_flags}")

    # Replay with different models
    from council_runner import ReplayEngine
    engine = ReplayEngine()
    replayed = await engine.replay(
        record.run_id,
        force_models={"planner": "grok"}
    )

asyncio.run(main())
```

## Integration with NCL Brain

The Council Runner v1 is designed to integrate into the NCL brain FastAPI service (port 8800):

```python
# In brain.py or api.py
from council_runner import run_parallel_council, CouncilRunStore

@app.post("/api/council/run")
async def run_council_debate(
    topic: str,
    prompt: str,
    context: dict = None
) -> dict:
    record = await run_parallel_council(topic, prompt, context)

    # Store and return
    store = CouncilRunStore(data_dir=DATA_DIR)
    await store.save_run(record)

    return record.model_dump()
```

## Model API Configuration

The system uses a fallback chain: Claude → Grok → Ollama. Set environment variables:

```bash
# Anthropic Claude
export ANTHROPIC_API_KEY="sk-ant-..."

# xAI Grok
export XAI_API_KEY="..."

# Ollama (local)
export OLLAMA_HOST="localhost:11434"
```

## Deterministic Replay

Replay ensures reproducible council runs:

1. **Seed Generation**: Hash of prompt + timestamp
2. **Snapshot**: Records models, temperatures, context at execution time
3. **Re-execution**: Same seed + constraints produce consistent outputs
4. **Diff Report**: Compares original vs replay (score delta, new risks, etc.)

Use case: A/B testing different model preferences or temperature overrides.

## Data Directory Structure

```
./data/
└── council_runner/
    ├── runs.jsonl                  # Lightweight index (one JSON per line)
    ├── runs/
    │   ├── {run_id_1}.json         # Full record
    │   ├── {run_id_2}.json
    │   └── ...
    └── replays/
        ├── {run_id_1}.json         # Replay records
        └── ...
```

## Performance

Typical execution:
- **Per Agent**: 2-5 seconds (LLM API call)
- **All Three (Parallel)**: 5-8 seconds total (not 6-15)
- **Consensus Synthesis**: <100ms
- **Full Record Save**: <50ms

Total `total_duration_ms` in `CouncilRunRecord` includes LLM latency + synthesis + serialization.

## Error Handling

- **Model unavailable**: Fallback chain handles gracefully (Claude → Grok → Ollama)
- **JSON parse failure**: Logs warning, extracts what it can, continues
- **API errors**: Raises exception with context (caught in caller)
- **Replay not found**: `FileNotFoundError` raised, check `run_id`

## Future Extensions

- [ ] Cache agent responses per (topic, prompt) hash
- [ ] Streaming outputs (SSE to WebSocket)
- [ ] Multi-language support (system prompts)
- [ ] Custom agent roles (dynamic role definitions)
- [ ] Integration with governance/approval workflows
- [ ] Metrics/telemetry pipeline

## Testing

Run the example:
```bash
cd /sessions/focused-clever-mccarthy/mnt/dev/NCL/runtime
python3 -m council_runner.example_usage
```

Requires valid API keys for Claude, Grok, or Ollama.

## License & Attribution

Part of **RESONANCE ENERGY** (Nartix ecosystem).
NCL Brain component for multi-agent consensus via parallel council deliberation.
