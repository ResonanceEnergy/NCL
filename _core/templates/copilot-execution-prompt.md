# Copilot Prompt — {PUMP_ID} (iteration {N})

```
// NARTIX EXECUTION — Iteration {N}/3
// Pump: {PUMP_ID}
// Pillar: {PILLAR} | Priority: {PRIORITY}

// === GOAL ===
// {What to build — clear, one-paragraph description}

// === COUNCIL DECISION ===
// {Key decisions from council output — tech stack, architecture, approach}

// === CONTEXT PUCK ===
// {Relevant file snippets, types, interfaces — only include if modifying existing code}

// === ACCEPTANCE CRITERIA ===
// 1. {Testable condition — be specific and measurable}
// 2. {Testable condition}
// 3. {Testable condition}
// 4. {Testable condition}

// === CONSTRAINTS ===
// - {Language: Python 3.12+ with type hints / TypeScript strict / C# Unity / Swift}
// - {Error handling: structured types, graceful degradation}
// - {Performance: response time targets, memory limits}
// - {Security: input validation, no secrets in code}
// - Works on Mac Mini M4 Pro with {runtime}

// === EXAMPLE I/O (if applicable) ===
// Input: {sample data}
// Expected output: {what success looks like}
```

---

## Usage

1. Replace all `{PLACEHOLDER}` values with actual content from the council output and task plan
2. Save as `current-copilot-prompt.md` in `03-Execution/`
3. Send to Copilot via Computer Use or manual copy-paste
4. If iterating on a fix, add a `// === FIX FROM ITERATION {N-1} ===` section describing the exact bug and required change
