# ICM Integration: Jake Van Clief's Interpretable Context Methodology

## What Was Done

Integrated Jake Van Clief's **Interpretable Context Methodology** (ICM/MWP) into
NCL. Source: [github.com/RinDig/Interpreted-Context-Methdology](https://github.com/RinDig/Interpreted-Context-Methdology)
(89 stars, MIT License).

ICM replaces framework-level orchestration with **filesystem structure**. Numbered
folders are stages. Markdown files are prompts and context. The folder structure IS
the architecture.

---

## Five-Layer Architecture (Mapped to NCL)

```
Layer 0: CLAUDE.md           -> NCL system map + agent routing      (root)
Layer 1: CONTEXT.md          -> Task routing table                  (root)
Layer 2: Stage CONTEXT.md    -> Stage contracts (Inputs/Process/Outputs)
Layer 3: Reference material  -> docs/, schemas/, ncl_config.json, doctrine
Layer 4: Working artifacts   -> data/, stage output/ folders
```

---

## New File Structure

```
NCL/
├── CLAUDE.md                    <- Layer 0: "Where am I?" (~800 tokens)
├── CONTEXT.md                   <- Layer 1: "Where do I go?" (~300 tokens)
├── _config/
│   ├── CONVENTIONS.md           <- Source of truth for all ICM patterns
│   └── templates/
│       └── stage-context-template.md
├── workspaces/
│   ├── mission-ops/             <- Mission lifecycle pipeline
│   │   ├── CONTEXT.md
│   │   ├── shared/
│   │   ├── setup/
│   │   └── stages/
│   │       ├── 01-intake/       <- Receive + validate missions
│   │       │   ├── CONTEXT.md
│   │       │   ├── references/
│   │       │   └── output/
│   │       ├── 02-dispatch/     <- Route to agent
│   │       │   ├── CONTEXT.md
│   │       │   ├── references/
│   │       │   └── output/
│   │       ├── 03-execute/      <- Run the mission
│   │       │   ├── CONTEXT.md
│   │       │   ├── references/
│   │       │   └── output/
│   │       └── 04-report/       <- Generate report + audit log
│   │           ├── CONTEXT.md
│   │           ├── references/
│   │           └── output/
│   ├── data-pipeline/           <- iPhone data processing
│   │   ├── CONTEXT.md
│   │   └── stages/
│   │       ├── 01-capture/      <- Ingest raw events
│   │       ├── 02-validate/     <- Schema validation (43+ types)
│   │       ├── 03-process/      <- CODE methodology
│   │       └── 04-synthesize/   <- Knowledge graph integration
│   ├── agent-dev/               <- Agent creation + hardening
│   │   ├── CONTEXT.md
│   │   └── stages/
│   │       ├── 01-design/       <- Define purpose, I/O, capabilities
│   │       ├── 02-implement/    <- Write code + tests
│   │       ├── 03-test/         <- Golden task evaluation
│   │       └── 04-harden/       <- Security, errors, production
│   └── daily-ops/               <- Daily intelligence cycle
│       ├── CONTEXT.md
│       └── stages/
│           ├── 01-collect/      <- Gather from all sources
│           ├── 02-analyze/      <- Pattern + anomaly detection
│           ├── 03-brief/        <- Generate daily brief
│           └── 04-action/       <- Dispatch follow-up missions
└── [existing NCL structure unchanged]
```

---

## Key ICM Patterns Applied

### Stage Contracts
Every stage CONTEXT.md has: **Inputs** (what to load, from where, which section),
**Process** (numbered steps), **Outputs** (what goes where, in what format).

### Stage Handoffs
Stage N writes to `output/`. Stage N+1 reads from it. A human can edit any
intermediate output and the next stage picks up the edited version.

### Selective Section Routing
CONTEXT.md tables specify not just which file to read but which section. Keeps
token cost low.

### Checkpoints
Creative stages (dispatch, process, analyze) include checkpoints where the agent
pauses and the human steers.

### Audits
Critical stages (intake, validate, execute, test, harden) include audit checklists
the agent runs before writing to output/.

### Trigger Keywords
- `setup` -- starts onboarding for whatever workspace you are in
- `status` -- shows pipeline completion (which stages have output)

---

## How to Use

### Navigate to a workspace
```
cd workspaces/mission-ops
# Read CONTEXT.md to see the task routing table
```

### Run a pipeline stage
Read the stage's CONTEXT.md. It tells you exactly what to load, what to do, and
where to put the output.

### Check pipeline status
Type `status` in any workspace. The agent scans `stages/*/output/` and shows
which stages are complete vs. pending.

### Build a new workspace
Copy `_config/templates/stage-context-template.md` for each stage. Follow
`_config/CONVENTIONS.md` for all patterns.

---

## Health Check

The system health check (`tools/system_health_check.py`) now validates:
- All 4 workspaces exist with CONTEXT.md files
- All 16 stages have CONTEXT.md and output/ directories
- Root CLAUDE.md, CONTEXT.md, and _config/CONVENTIONS.md exist

---

## Attribution

Based on Jake Van Clief's Interpretable Context Methodology (ICM).
GitHub: [RinDig/Interpreted-Context-Methdology](https://github.com/RinDig/Interpreted-Context-Methdology)
License: MIT
