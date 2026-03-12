# Agent Test

Run golden task evaluation and pytest suite against the new agent.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Previous stage | `../02-implement/output/` | Full file | Agent code and tests |
| Golden tasks | `../../../evaluation/golden_tasks/` | Full directory | Evaluation criteria |
| Eval harness | `../../../evaluation_harness.py` | Full file | Scoring engine |
| Test suite | `../../../tests/` | Relevant test files | Test patterns |

## Process

1. Copy agent module from 02-implement/output/ to ncl_agency_runtime/agents/
2. Copy test file from 02-implement/output/ to tests/
3. Run pytest on the new test file: `python -m pytest tests/test-[agent-name].py -v`
4. Run the evaluation harness against relevant golden tasks
5. Collect test results: pass/fail counts, coverage, golden task scores
6. Write test report to output/

## Audit

| Check | Pass Condition |
|-------|---------------|
| Tests pass | All pytest tests pass (zero failures) |
| Golden score | Golden task score >= 0.7 (70% threshold) |
| No regressions | Existing test suite still passes |

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Test report | output/[agent-name]-test-report.md | Markdown with scores |
