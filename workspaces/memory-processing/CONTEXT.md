# Memory Processing Workspace

Living context memory system - episodic → semantic → reconstructive memory pipeline.

## Stages

| Stage | Name | Purpose |
|-------|------|---------|
| 01 | Episodic Intake | Ingest raw observations (feedback, research, signals) |
| 02 | Semantic Extraction | Extract MemUnits (atomic facts + metadata) |
| 03 | Consolidation | Merge related units, resolve conflicts |
| 04 | Decay Reinforcement | Apply time decay, boost reinforced facts |
| 05 | Retrieval Indexing | Build searchable indices for fast recall |

## Key Artifacts

- **Input**: Observations from all NCL workspaces (feedback, research, intelligence)
- **Intermediate**: Raw MemUnits, consolidation log, decay map
- **Output**: Consolidated memory index (queryable by context, recency, confidence)

## Authority

Memory system is autonomous under NCL oversight. Used by all pillars for context retrieval.

## Execution Model

Stages 01-02 continuous (event-driven). Stages 03-04 run daily (consolidation + decay). Stage 05 continuous (index rebuild on ingestion).

## Storage

- Episodic events: `/dev/NCL/memory/episodic/`
- MemUnits: `/dev/NCL/memory/units/`
- Consolidated index: `/dev/NCL/memory/index_consolidated.json`
- Retrieval indices: `/dev/NCL/memory/indices/`
