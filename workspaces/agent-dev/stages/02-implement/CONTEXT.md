# Agent Implement

Write the agent code based on the design document from the previous stage.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Previous stage | `../01-design/output/` | Full file | Agent design spec |
| Agent base | `../../../ncl_agency_runtime/agents/__init__.py` | Base classes | Inheritance pattern |
| Existing agents | `../../../ncl_agency_runtime/agents/` | All modules | Code patterns |
| lib_ncl | `../../../lib_ncl.py` | Full file | Shared utilities |

## Process

1. Read the agent design document from 01-design/output/
2. Create the agent module following existing patterns in ncl_agency_runtime/agents/
3. Implement the core logic (process method, input handling, output generation)
4. Add proper error handling and logging
5. Write accompanying test file following patterns in tests/
6. Write implementation files to output/

## Audit

| Check | Pass Condition |
|-------|---------------|
| Follows base class | Agent inherits from correct base class |
| Has tests | Test file exists with at least 3 test cases |
| No hardcoded paths | All paths use config or relative references |

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Agent module | output/[agent-name].py | Python module |
| Test file | output/test-[agent-name].py | pytest test file |
