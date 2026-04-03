# Stage 03: Synthesis

Run council debate (Claude, Grok, Gemini, Perplexity, GPT) to explore mandate design.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Stage 02 | `/Projects/NCL/analysis/{timestamp}.md` | Full analysis | Council debate foundation |
| Council | Multi-model endpoints | API keys in vault | Parallel reasoning across models |

## Process

1. Spawn council session with 5-minute debate window
2. Each model proposes mandate approach (parallel)
3. Claude synthesizes proposals into coherent strategy
4. Generate debate transcript and consensus summary
5. Identify key tradeoffs and recommendations

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Debate Log | `/Projects/NCL/council/{timestamp}_debate.log` | JSON Lines |
| Synthesis | `/Projects/NCL/council/{timestamp}_synthesis.md` | Markdown |

## Checkpoints

- All 5 council members respond within window
- Claude synthesis achieves >80% coherence score
- Tradeoff matrix complete (objectives vs constraints)

## Audit

- Timestamp all model calls
- Log API latencies per model
- Track synthesis reasoning steps
