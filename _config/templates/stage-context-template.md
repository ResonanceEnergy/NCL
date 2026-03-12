# [Stage Name]

[One sentence: what this stage does]

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| [Previous stage or user] | [path] | [section or "Full file"] | [reason] |

## Process

<!-- Numbered steps. Each step is one concrete action. Be specific enough that
     two different agents following these steps would produce structurally similar
     outputs. -->

1. [Step one]
2. [Step two]
3. [Step three]

## Checkpoints

<!-- Optional. Points where the agent pauses for human input before continuing.
     Not every stage needs checkpoints. Linear stages (validate, render)
     often run straight through. Creative stages benefit from at least one. -->

| After Step | Agent Presents | Human Decides |
|------------|---------------|---------------|
| [step #] | [what to show] | [what to choose] |

## Audit

<!-- Optional. Quality checks before output is considered done.
     If any check fails, revise before saving to output/. -->

| Check | Pass Condition |
|-------|---------------|
| [Check name] | [What "passing" looks like] |

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| [Name] | output/[filename].md | [Description] |
