# NARTIX Copilot House Rules
# These persistent instructions are loaded by GitHub Copilot (Claude Opus 4.6) in VS Code Agent Mode.

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

### TypeScript (strict mode)
- Functional React with hooks, no class components
- Vite for bundling
- Zod for runtime validation
- Explicit return types on exported functions
- Use const assertions where applicable

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

## Error Handling
- Never swallow exceptions silently
- Structured error types over string messages
- Graceful degradation — partial results beat total failure
- Log context: what was attempted, what failed, what data was involved

## Performance (Apple Silicon)
- Prefer Metal compute shaders and MPS acceleration for ML
- Use Neural Engine (CoreML) for inference where possible
- Keep Docker resource limits reasonable (8GB max)
- Ollama at localhost:11434 for local LLM inference

## Security
- Never commit secrets, API keys, or credentials
- Use environment variables or keychain for sensitive config
- Validate all external input
- Sandbox Computer Use operations
