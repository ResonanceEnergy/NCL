# NCL Workspaces - Layer 2 CONTEXT Files

Complete index of all 30 CONTEXT.md files (5 workspace-level + 25 stage-level) for NCL Layer 2 workspaces.

## Workspace-Level CONTEXT Files (5)

| Workspace | Path | Purpose |
|-----------|------|---------|
| 1. Mandate Generation | `/dev/NCL/workspaces/mandate-generation/CONTEXT.md` | Convert pump prompts → formal mandates via council |
| 2. Research Pipeline | `/dev/NCL/workspaces/research-pipeline/CONTEXT.md` | UNI research cortex (deep science, convergence detection) |
| 3. Intelligence Scan | `/dev/NCL/workspaces/intelligence-scan/CONTEXT.md` | Awarebot-FPC (X/YouTube/Reddit → insights) |
| 4. Memory Processing | `/dev/NCL/workspaces/memory-processing/CONTEXT.md` | Living context (episodic → semantic → retrieval) |
| 5. Feedback Synthesis | `/dev/NCL/workspaces/feedback-synthesis/CONTEXT.md` | Process feedback → mandate updates |

## Stage-Level CONTEXT Files (25)

### Mandate Generation Stages (5)

| Stage | Path | Name |
|-------|------|------|
| 01 | `/dev/NCL/workspaces/mandate-generation/01-intake/CONTEXT.md` | Intake |
| 02 | `/dev/NCL/workspaces/mandate-generation/02-analysis/CONTEXT.md` | Analysis |
| 03 | `/dev/NCL/workspaces/mandate-generation/03-synthesis/CONTEXT.md` | Synthesis (council debate) |
| 04 | `/dev/NCL/workspaces/mandate-generation/04-mandate-draft/CONTEXT.md` | Mandate Draft |
| 05 | `/dev/NCL/workspaces/mandate-generation/05-review/CONTEXT.md` | Review (human approval) |

### Research Pipeline Stages (5)

| Stage | Path | Name |
|-------|------|------|
| 01 | `/dev/NCL/workspaces/research-pipeline/01-source-scan/CONTEXT.md` | Source Scan |
| 02 | `/dev/NCL/workspaces/research-pipeline/02-extraction/CONTEXT.md` | Extraction |
| 03 | `/dev/NCL/workspaces/research-pipeline/03-analysis/CONTEXT.md` | Analysis |
| 04 | `/dev/NCL/workspaces/research-pipeline/04-convergence/CONTEXT.md` | Convergence (UNI intelligence) |
| 05 | `/dev/NCL/workspaces/research-pipeline/05-archive/CONTEXT.md` | Archive (memory ingestion) |

### Intelligence Scan Stages (5)

| Stage | Path | Name |
|-------|------|------|
| 01 | `/dev/NCL/workspaces/intelligence-scan/01-source-ingest/CONTEXT.md` | Source Ingest |
| 02 | `/dev/NCL/workspaces/intelligence-scan/02-signal-extraction/CONTEXT.md` | Signal Extraction |
| 03 | `/dev/NCL/workspaces/intelligence-scan/03-importance-scoring/CONTEXT.md` | Importance Scoring |
| 04 | `/dev/NCL/workspaces/intelligence-scan/04-insight-synthesis/CONTEXT.md` | Insight Synthesis |
| 05 | `/dev/NCL/workspaces/intelligence-scan/05-distribution/CONTEXT.md` | Distribution (routing) |

### Memory Processing Stages (5)

| Stage | Path | Name |
|-------|------|------|
| 01 | `/dev/NCL/workspaces/memory-processing/01-episodic-intake/CONTEXT.md` | Episodic Intake |
| 02 | `/dev/NCL/workspaces/memory-processing/02-semantic-extraction/CONTEXT.md` | Semantic Extraction |
| 03 | `/dev/NCL/workspaces/memory-processing/03-consolidation/CONTEXT.md` | Consolidation (dedup + merge) |
| 04 | `/dev/NCL/workspaces/memory-processing/04-decay-reinforcement/CONTEXT.md` | Decay Reinforcement |
| 05 | `/dev/NCL/workspaces/memory-processing/05-retrieval-indexing/CONTEXT.md` | Retrieval Indexing |

### Feedback Synthesis Stages (5)

| Stage | Path | Name |
|-------|------|------|
| 01 | `/dev/NCL/workspaces/feedback-synthesis/01-report-intake/CONTEXT.md` | Report Intake |
| 02 | `/dev/NCL/workspaces/feedback-synthesis/02-validation/CONTEXT.md` | Validation (Claude-verified) |
| 03 | `/dev/NCL/workspaces/feedback-synthesis/03-pattern-detection/CONTEXT.md` | Pattern Detection |
| 04 | `/dev/NCL/workspaces/feedback-synthesis/04-recommendation/CONTEXT.md` | Recommendation (amendments) |
| 05 | `/dev/NCL/workspaces/feedback-synthesis/05-mandate-update/CONTEXT.md` | Mandate Update (versioned) |

## Format Compliance

All files follow MWP (Model Workspace Protocol) stage contract format:
- Workspace files: < 80 lines, stages table, key artifacts, execution model, storage paths
- Stage files: < 40 lines, Inputs table, Process steps, Outputs table
- Creative/synthesis stages (03, 04): include Checkpoints and Audit sections

## Key Architectural Points

1. **Sequential Execution**: Each workspace flows 01 → 02 → 03 → 04 → 05
2. **Checkpoints & Audit**: Stages 03-04 (synthesis/creative) include validation
3. **Authority Chain**: NCL directs, NCC executes, BRS earns, AAC invests
4. **Memory System**: Episodic → Semantic → Consolidated → Indexed (fast recall)
5. **Feedback Loop**: Observation → MemUnit → Index → Synthesis → Mandate Update

## Related Context Files

- Master context: `/Projects/CLAUDE.md`
- NCC doctrine: `/Projects/NCC_CONTEXT.md`
- BRS doctrine: `/Projects/BRS_CONTEXT.md`
- AAC doctrine: `/Projects/AAC_CONTEXT.md`
- NCL context: `/dev/NCL_CONTEXT.md` (if exists)
