# Research Pipeline Workspace

UNI research cortex - deep science, alt-science, long-horizon research with convergence detection.

## Stages

| Stage | Name | Purpose |
|-------|------|---------|
| 01 | Source Scan | Fetch from arXiv, web, GitHub repos, papers |
| 02 | Extraction | Parse and extract key findings, claims, data |
| 03 | Analysis | Cross-reference findings, validate assertions |
| 04 | Convergence | Detect patterns across domains (UNI intelligence) |
| 05 | Archive | Store in memory system and convergence index |

## Key Artifacts

- **Input**: Research briefs, topic lists (from mandates or standing research)
- **Intermediate**: Source catalog, extraction summaries, cross-ref matrix
- **Output**: Convergence reports, archived MemUnits (memory system)

## Authority

NCL directs research focus. UNI autonomously executes source scan to archive.

## Execution Model

Stages 01-02 run daily (autonomous feed). Stages 03-04 run on-demand or weekly aggregation. Stage 05 continuous (archive ingestion).

## Storage

- Sources: `/dev/NCL/research/sources/`
- Extractions: `/dev/NCL/research/extractions/`
- Convergence reports: `/dev/NCL/research/convergence/`
- Memory archive: `/dev/NCL/memory/units/`
