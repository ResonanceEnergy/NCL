# Mission Report

Generate a structured report from mission execution results and log to the audit trail.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Previous stage | `../03-execute/output/` | Full file | Execution results |
| Intake record | `../01-intake/output/` | Full file | Original mission definition |
| Audit log | `../../../data/event_log/` | Recent entries | Historical context |

## Process

1. Read execution results from 03-execute/output/
2. Read the original mission definition from 01-intake/output/
3. Generate a mission report: objective, agent assigned, outcome, duration, errors
4. Calculate success metrics (completion rate, time vs. deadline)
5. Append summary to the audit trail in data/event_log/
6. Write the final report to output/

## Audit

| Check | Pass Condition |
|-------|---------------|
| Complete | Report contains all required sections (objective, outcome, metrics) |
| Logged | Audit trail entry written to data/event_log/ |

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Mission report | output/[mission-id]-report.md | Markdown summary |
