# NARTIX Copilot House Rules

These persistent instructions are loaded by GitHub Copilot (Claude Opus 4.6) in VS Code Agent Mode.
They apply to every coding task across the NARTIX ecosystem.

## Identity

You are coding inside the NARTIX ecosystem — Resonance Energy studio. Supreme Commander: NATRIX.
Machine: Mac Mini M4 Pro, 64GB, macOS Sequoia. Apple Silicon — use Metal/MPS, not CUDA.

## Code Standards

### Python (3.12+)
- Type hints on all function signatures and return types
- Docstrings on all public functions (Google-style)
- pytest for testing, pyproject.toml for config
- Use pathlib over os.path
- async/await for I/O-bound operations
- Structured logging (not print statements in production)
- pydantic for data validation, pydantic-settings for config
- httpx for HTTP clients (async preferred)

### TypeScript (strict mode)
- Functional React with hooks, no class components
- Vite for bundling
- Zod for runtime validation
- Explicit return types on exported functions
- Use const assertions where applicable
- Prefer `import type` for type-only imports

### C# (Unity)
- Assembly definitions for modularity
- ScriptableObjects for data-driven design
- Coroutines or async for long operations
- Namespace everything under ResonanceEnergy.*

### Swift (SwiftUI)
- SwiftUI preferred for all new iOS work
- @MainActor for UI-bound classes
- Structured concurrency (async/await, Task groups)
- Combine for reactive data flows

## Architecture Rules
- Every project gets: README.md, CHANGELOG.md, .gitignore
- CI/CD via GitHub Actions
- Doctrine-based: significant projects get mandate, roadmap, mission specs
- MWP folder structure for multi-stage workflows
- JSON for machine-readable artifacts, Markdown for human-readable
- Paperclip on port 3100 for agent orchestration

## Error Handling
- Never swallow exceptions silently
- Structured error types over string messages
- Graceful degradation — partial results beat total failure
- Log context: what was attempted, what failed, what data was involved
- Use `return_exceptions=True` with `asyncio.gather` for resilient parallel ops

## Performance (Apple Silicon)
- Prefer Metal compute shaders and MPS acceleration for ML
- Use Neural Engine (CoreML) for inference where possible
- Keep Docker resource limits reasonable (8GB max)
- Ollama at localhost:11434 for local LLM inference (qwen3:8b fast, qwen3:32b strong)

## Security
- Never commit secrets, API keys, or credentials
- Use environment variables or keychain for sensitive config
- Validate all external input (Pydantic models at API boundaries)
- Sandbox Computer Use operations
- Token-bucket rate limiting on public endpoints

## NARTIX Service Ports
- Relay (FirstStrike): 8787 (HTTPS)
- NCL Brain: 8800
- NCC Server: 8765
- AAC WAR Room: 8080
- BRS Server: 8000
- Paperclip: 3100
- Ollama: 11434

## Prompt Techniques (When Claude Builds Prompts for Copilot)

When operating inside the Claude→Copilot hybrid loop, structure prompts using these techniques:

### Outcome + Constraints + Examples
```
// Goal: {what to build}
// Requirements: {tech stack, patterns, constraints}
// Example input: {sample data}
// Expected output: {what success looks like}
```

### Context Puck
```
// CONTEXT PUCK: Relevant files for this task
// From {file}: {key detail}
// Task: {what to do}
// Constraints: {backward compat, performance, etc.}
```

### Acceptance Criteria
```
// Acceptance criteria:
// 1. {testable condition}
// 2. {testable condition}
// 3. {testable condition}
```

### Debugging Loop
```
// Previous implementation has {exact bug}.
// Fix exactly that while preserving {what to keep}.
// Add comments explaining each change.
```
