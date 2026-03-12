# Data Pipeline

Four-stage pipeline for processing iPhone data through the NCL system.
Captures raw events, validates against schemas, processes with CODE methodology,
and synthesizes into the knowledge graph.

## Task Routing

| Task                           | Go To                                 |
|--------------------------------|---------------------------------------|
| Ingest raw iPhone events       | `stages/01-capture/CONTEXT.md`        |
| Validate against schemas       | `stages/02-validate/CONTEXT.md`       |
| Apply CODE methodology         | `stages/03-process/CONTEXT.md`        |
| Integrate into knowledge graph | `stages/04-synthesize/CONTEXT.md`     |

## Stage Handoffs

```
  [01-capture]  ------>  [02-validate]  ------>  [03-process]  ------>  [04-synthesize]
```

Each stage writes to its `output/` folder. The next stage reads from there.

## Code Implementation

| Stage | Primary Code | Key Functions |
|-------|-------------|---------------|
| 01-capture | `ncl_agency_runtime/runtime/relay_server.py` | `do_POST()`, `_store_single_event()`, `RateLimiter` |
| 02-validate | `tools/validate_events.py` | `validate_instance()`, `load_catalog()` |
| 03-process | `ncl_agency_runtime/runtime/relay_server.py` | `validate_minimal()`, dedup by `event_id` |
| 04-synthesize | `ncl_memory.py` | `MemoryManager`, `MemoryIndex`, consolidation pipeline |

Relay server: `http://localhost:8787/event` (POST), authenticated via Bearer token

## Shared Resources

| Resource | Location | What It Provides |
|----------|----------|-----------------|
| Schema catalog | `../../schemas/ncl.iphone.v1/` | 43+ event type definitions |
| Data contract | `../../docs/ncl_iphone_data_contract_v1.md` | Field specs |
| Event log | `../../data/event_log/` | Historical events |
| Quarantine | `../../data/quarantine/` | Failed validations |
