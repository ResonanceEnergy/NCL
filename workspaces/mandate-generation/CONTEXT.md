# Mandate Generation Workspace

Convert pump prompts from NATRIX into formal NCL mandates via council debate and synthesis.

## Stages

| Stage | Name | Purpose |
|-------|------|---------|
| 01 | Intake | Receive and validate pump prompt from NATRIX |
| 02 | Analysis | Decompose intent, extract constraints and opportunities |
| 03 | Synthesis | Run council debate (Claude, Grok, Gemini, Perplexity, GPT) |
| 04 | Mandate Draft | Produce mandate YAML with objectives, KPIs, authority chain |
| 05 | Review | Human approval gate - NATRIX sign-off required |

## Key Artifacts

- **Input**: Pump prompt (rich, from Grok on iPhone)
- **Intermediate**: Analysis document, council debate transcript, draft YAML
- **Output**: Approved mandate YAML file (stored in mandate registry)

## Authority

Only NCL updates mandates. NATRIX approves. NCC executes.

## Execution Model

Sequential: 01 → 02 → 03 → 04 → 05. Stage 03 runs parallel council (async debate, 5-10 min synthesis window).

## Storage

- Pump prompts: `/dev/NCL/prompts/intake/`
- Draft mandates: `/dev/NCL/mandates/drafts/`
- Approved mandates: `/dev/NCL/mandates/approved/` (YAML, dated, versioned)
