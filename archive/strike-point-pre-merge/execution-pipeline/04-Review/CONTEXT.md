# 04-Review — Verification Protocol

## Purpose
Automated verification of execution output against the original pump prompt and council requirements. Max 2 auto-fix rounds before escalation.

## Process
1. Parse `signed-off.md` from 03-Execution
2. Run test suite if applicable
3. Compare output against pump prompt acceptance criteria
4. Generate `verification-report.json`

## Output Format
```json
{
  "success": true|false,
  "issues": ["..."],
  "diffs": ["..."],
  "logs": ["..."],
  "fixPlan": null|"..."
}
```

## Routing
- If success → move to 05-Output
- If fixable issues (round 1-2) → send fix back to 03-Execution
- If round 3+ or unfixable → escalate to NATRIX via relay /responses
