# 03-Execution — Hybrid Claude→Copilot Coding Loop

## Purpose

Claude Desktop Max reads the council output and task plan, builds precise coding prompts, and sends them to GitHub Copilot (Claude Opus 4.6) in VS Code Agent Mode. Claude then reviews the output and iterates until the code meets all acceptance criteria.

## Process

1. Read `council-output-{PUMP_ID}.md` + `task-plan-{PUMP_ID}.md` from 02-Planning
2. Build high-quality prompt using the techniques below
3. Write prompt to `current-copilot-prompt.md` or send via Computer Use directly to VS Code
4. Copilot (Opus 4.6) generates code in `working-files/`
5. Claude Code reviews, runs tests, checks acceptance criteria
6. If issues: build targeted fix prompt → repeat (max 3 iterations)
7. If good: commit, create `signed-off.md`, move artifacts to 04-Review

## Files

- `council-output-{PUMP_ID}.md` — input from 02-Planning (debate log + decision)
- `task-plan-{PUMP_ID}.md` — input from 02-Planning (decomposed tasks + acceptance criteria)
- `current-copilot-prompt.md` — the prompt Claude builds for Copilot (overwritten each iteration)
- `working-files/` — where Copilot writes code
- `signed-off.md` — Claude's sign-off when execution is complete

## Budget

- Max 3 coding iterations per task (Paperclip enforcement)
- If 3 iterations fail: escalate to NATRIX with diagnostic summary
- Cost per iteration tracked via Paperclip cost events

## Delivery Modes

### Mode A: Computer Use (Fully Automated)
Claude uses Computer Use to:
1. Open VS Code
2. Navigate to the target file in `working-files/`
3. Open Copilot Chat panel
4. Type the prompt and submit
5. Wait for Copilot to generate
6. Read the output and evaluate

Best for: hands-off execution on Mac Mini when NATRIX is on iPhone.

### Mode B: Manual-Assisted
Claude writes the prompt to `current-copilot-prompt.md`. NATRIX (or a VS Code task) copy-pastes it into Copilot Chatbot. Copilot generates. Claude reads the result from `working-files/`.

Best for: interactive sessions where NATRIX is at the Mac Mini.

## Advanced Copilot Prompting Techniques

### Technique 1: Outcome + Constraints + Examples

Structure every prompt with clear goal, requirements, and expected I/O:

```
// NARTIX EXECUTION — Iteration {N}/3
// Pump: {PUMP_ID}
// Pillar: {PILLAR} | Priority: {PRIORITY}

// === GOAL ===
// {What to build — clear, one-paragraph description}

// === COUNCIL DECISION ===
// {Key decisions from council output — tech stack, architecture, approach}

// === ACCEPTANCE CRITERIA ===
// 1. {Testable condition}
// 2. {Testable condition}
// 3. {Testable condition}

// === CONSTRAINTS ===
// - {Language version, type hints, etc.}
// - {Error handling requirements}
// - {Performance targets}

// === EXAMPLE I/O ===
// Input: {sample data}
// Expected output: {what success looks like}
```

### Technique 2: Context Puck

When the task involves modifying existing code, inject relevant file snippets:

```
// CONTEXT PUCK: Relevant files for this task
// From src/core/panel-system.ts (lines 45-60): panels use React + dragula
// From src/types/index.ts: Panel interface has { id, title, content, position }
//
// Task: {What to do with this context}
// Constraints: {Backward compatibility, naming conventions, etc.}
```

### Technique 3: Agent Mode Task with Acceptance Criteria

For complex multi-file tasks, use Agent Mode with explicit acceptance criteria:

```
"Implement the {feature}. This requires changes to:
1. {file1} — {what to change}
2. {file2} — {what to change}
3. {file3} — {what to change}

Acceptance criteria:
- {criterion 1}
- {criterion 2}
- Running `{test command}` passes with 0 failures"
```

### Technique 4: Debugging Loop Prompt

When iterating on a failed attempt:

```
// ITERATION {N}/3 — Fix from previous attempt
// Bug: {exact error message or behavior}
// Root cause: {Claude's diagnosis}
// Fix: {exactly what to change}
// Preserve: {what must NOT change}
// Add comments explaining each change.
```

### Technique 5: Persistent House Rules

Always ensure `.github/copilot-instructions.md` is present in the repo. Copilot loads it automatically and applies NARTIX code standards to every generation.

## Prompt Template

Use `_core/templates/copilot-execution-prompt.md` for a ready-to-fill template. The template includes all 5 techniques and the correct header format.

## Sign-Off Format

When execution is complete, `signed-off.md` must contain:

```markdown
# Execution Sign-Off

**Pump:** {PUMP_ID}
**Status:** Complete
**Iterations:** {N}/3
**Summary:** {One-line description of what was built}
**Signed Off:** Claude Desktop Max
**Timestamp:** {ISO8601}

{JSON block with: pump_id, status, iterations, files_generated, acceptance_criteria_met, extra_features}
```
