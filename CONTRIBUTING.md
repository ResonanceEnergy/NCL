# Contributing to NUREALCORTEXLINK

Thank you for your interest in making NCL better. This guide covers the
workflow, standards, and conventions used across the project.

---

## Getting Started

```bash
git clone https://github.com/ResonanceEnergy/NCL.git
cd NCL
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest tests/ -v          # Confirm tests pass
```

---

## Branch Strategy

| Branch | Purpose |
|---|---|
| `main` | Stable — protected, requires PR review |
| `dev` | Integration branch for feature work |
| `feat/*` | Feature branches (fork from `dev`) |
| `fix/*` | Bug-fix branches |

Create your branch:

```bash
git checkout dev && git pull
git checkout -b feat/my-feature
```

---

## Development Workflow

1. **Write tests first** — every new feature needs a test in `tests/`.
2. **Implement the feature** — keep changes focused.
3. **Lint** — `ruff check .` (config in `ruff.toml`).
4. **Type check** — `mypy ncl_memory.py ncl_agency_runtime/runtime/ tools/`.
5. **Run the full suite** — `python -m pytest tests/ -v`.
6. **Open a PR** against `dev` with a clear description.

---

## Code Standards

### Python

- **Style**: PEP 8 + Ruff (line length 120).
- **Type hints**: All public function signatures.
- **Docstrings**: Google-style for modules, classes, and public functions.
- **Imports**: Use `isort` (handled by Ruff `I` rules).
- **Error handling**: No bare `except:`; always catch specific exceptions.
- **SQLite**: Use `with sqlite3.connect(...) as conn:` context managers.

### Swift (iOS Companion)

- **Targets**: iOS 16+, macOS 13+.
- **Build**: `swift build` must pass from `ios/CompanionApp/`.
- **Tests**: XCTest in `ios/CompanionApp/Tests/`.
- **Concurrency**: Types shared across actors should be `Sendable`.

### JSON / Config

- Schema files follow JSON Schema Draft 2020-12.
- Event schemas live in `ncl_agency_runtime/schemas/`.
- `ncl_config.json` is the single source of truth for runtime config.

---

## Testing

```bash
# Full suite
python -m pytest tests/ -v

# Single file
python -m pytest tests/test_memory_system.py -v

# With coverage
python -m pytest --cov=. tests/
```

### Golden Tasks

Golden task JSON files in `evaluation/golden_tasks/` are validated in CI.
Each file must have: `id`, `name`, `input`, `expected`.

---

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add lazy index rebuild option
fix: mask token in Telegram bot logs
test: add migration round-trip tests
docs: update README venv instructions
chore: add ruff + mypy configs
```

---

## CI / GitHub Actions

Every PR triggers:

- **Lint & Test** — Python 3.10–3.12, Ruff, mypy, pytest.
- **Schema Validation** — ensures all JSON schemas parse.
- **Swift Build** — `swift build && swift test` on macOS.
- **Policy Kernel Gate** — blocks PRs touching `ios/` without passing tests.

See `.github/workflows/ci.yml` for details.

---

## Security

- Never commit secrets or API tokens.
- PII fields are stripped by `tools/export.py` before export.
- Relay server binds to `127.0.0.1` by default.
- API keys required by default (`api_keys_required: true`).

---

## Questions?

Open an issue on the repo or reach out to the project maintainer.
