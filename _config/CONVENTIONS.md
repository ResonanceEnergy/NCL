# NCL Conventions

The rules for building and maintaining NCL workspaces. This is the canonical source.
Every workspace follows these patterns. Adapted from Jake Van Clief's Interpretable
Context Methodology (ICM/MWP).

---

## Five-Layer Routing Architecture

Agents read down the layers. They stop as soon as they have what they need.

```
Layer 0: CLAUDE.md           -> "Where am I?"          (always loaded, ~800 tokens)
Layer 1: CONTEXT.md          -> "Where do I go?"        (read on entry, ~300 tokens)
Layer 2: Stage CONTEXT.md    -> "What do I do?"          (read per-task, ~200-500 tokens)
Layer 3: Reference material  -> "What rules apply?"      (loaded selectively, varies)
Layer 4: Working artifacts   -> "What am I working with?" (loaded selectively, varies)
```

**Layer 0 -- CLAUDE.md** contains the folder map, naming conventions, and a routing
table. One per workspace. Always loaded.

**Layer 1 -- Top-level CONTEXT.md** contains a task routing table that maps task
types to specific stage folders. One per workspace. Read on entry.

**Layer 2 -- Stage CONTEXT.md files** live inside each stage folder. They contain
the scope definition, what-to-load tables, and step-by-step process. One per stage.
Layer 2 is the control point -- its Inputs table determines exactly which files
from Layers 3 and 4 the agent loads.

**Layer 3 -- Reference material** is persistent context: doctrine, schemas, voice
rules, design systems, skill files. Configured once, stable across runs. Lives in
`references/` folders, `shared/`, `_config/`, and `docs/`.

**Layer 4 -- Working artifacts** are per-run context: previous stage outputs,
user-provided source material. Produced and consumed during execution. Lives in
`output/` folders.

Every token of irrelevant context is a token of diluted attention. Workspace
CLAUDE.md files should map each task to its minimal required files.

---

## Pattern 1: Stage Contracts

Every stage CONTEXT.md follows the same three-section shape:

```markdown
## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| ... | ... | ... | ... |

## Process

1. Step one
2. Step two
3. Step three

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| ... | ... | ... |
```

This is the contract. Simple enough that a non-technical user can read it.
Structured enough that an agent can follow it reliably.

---

## Pattern 2: Stage Handoffs via Output Folders

Every stage has an `output/` subfolder. The agent writes its artifact there. The
next stage reads from the previous stage's `output/` folder.

- Stage N produces: `stages/0N-name/output/artifact-name.md`
- Stage N+1's CONTEXT.md says: "Read `../0N-name/output/artifact-name.md` as your input"

A human can open the output file, edit it, and the next stage picks up the
edited version.

File naming in output folders: `[topic-slug]-[stage-artifact].md`

---

## Pattern 3: One-Way Cross-References

Every folder points outward to what it needs. No folder points back. This prevents
reference growth from going N-squared as the system scales.

---

## Pattern 4: Selective Section Routing

CONTEXT.md Inputs tables specify not just which file to read but which section.

```
| File | Section to Load | Why |
|------|----------------|-----|
| doctrine.md | "Mission Governance" through "Escalation" | Dispatch rules |
```

When a full file is needed, write "Full file" in the Section/Scope column.

---

## Pattern 5: Canonical Sources

Every piece of information has ONE home. Other files point there. They do not
duplicate it. In NCL, canonical sources are:

- `ncl_config.json` -- system configuration
- `schemas/ncl.iphone.v1/` -- event type definitions
- `docs/` -- doctrine and strategic guidance
- `NCC_Master_Doctrine_v2.0.md` -- supreme governance

---

## Pattern 6: CONTEXT.md = Routing, Not Content

CONTEXT.md files answer three questions:
1. What is this folder?
2. What do I load?
3. What is the process?

They never contain the actual reference material. Keep them under 80 lines.

---

## Pattern 7: Tool Prerequisites

Setup guides for tools live in the `references/` folder of the stage that uses
them. Written for someone who has never installed the tool.

NCL tool prerequisites:
- Python 3.9+ with jsonschema, referencing, pytest, fastapi, uvicorn
- iOS device with Shortcuts app (for data-pipeline workspace)
- Obsidian or Notion (for knowledge graph synthesis)

---

## Pattern 8: Checkpoints

Creative stages should include at least one checkpoint where the agent pauses and
the human steers. Checkpoints go between process steps, not within them.

```
| After Step | Agent Presents | Human Decides |
|------------|---------------|---------------|
| [step #] | [what to show] | [what to choose] |
```

---

## Pattern 9: Stage Audits

Creative and build stages should include an Audit section: a checklist the agent
runs after completing its process but before writing to output/.

```
| Check | Pass Condition |
|-------|---------------|
| [Check name] | [What "passing" looks like] |
```

If any check fails, the agent revises before saving to output/.

---

## Pattern 10: Docs Over Outputs

Reference docs (doctrine, schemas, design rules) are the authoritative source.
Previous stage outputs are artifacts, not templates. Agents should not read other
outputs to learn patterns.

---

## Naming Conventions

- Folders and files: `lowercase-with-hyphens`
- Stage folders: zero-padded number prefix: `01-`, `02-`, `03-`, `04-`
- Output artifacts: `[topic-slug]-[artifact-type].md`
- No spaces in file or folder names

---

## Trigger Keywords

**`setup`** -- Starts onboarding for the current workspace.

**`status`** -- Shows pipeline completion. Scans all `stages/*/output/` folders:

```
Pipeline Status: [workspace-name]

  [01-stage]  ------>  [02-stage]  ------>  [03-stage]  ------>  [04-stage]
   COMPLETE              PENDING              PENDING              PENDING
 (artifact.md)           (empty)              (empty)              (empty)
```

---

## Quality Guardrails

- CONTEXT.md files: under 80 lines
- Reference files: under 200 lines (split if longer)
- Use plain English. Avoid jargon.
- Every empty folder that should persist gets a `.gitkeep` file
- Every markdown file readable by someone who understands markdown and git basics
