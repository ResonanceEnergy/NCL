# Agent Harden

Production-harden the agent: error handling, edge cases, security, and documentation.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Previous stage | `../03-test/output/` | Full file | Test report with failures |
| Agent code | `../../../ncl_agency_runtime/agents/[agent].py` | Full file | Code to harden |
| Hardening pack | `../../../docs/2100_HARDENING_PACK.md` | Full file | Hardening checklist |

## Process

1. Read the test report from 03-test/output/ for any failures or weak areas
2. Address each test failure or low-scoring golden task
3. Add input validation at system boundaries
4. Add timeout enforcement for external calls
5. Add structured logging (no print statements)
6. Write module docstring and inline comments for non-obvious logic
7. Run full test suite again to confirm fixes
8. Write hardening report to output/

## Audit

| Check | Pass Condition |
|-------|---------------|
| All tests pass | Zero test failures after hardening |
| Input validated | All user/external inputs validated |
| Timeouts set | All HTTP/external calls have timeouts |
| Logging present | Uses logging module, not print |

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Hardening report | output/[agent-name]-hardened.md | Markdown checklist |
