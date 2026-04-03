# Stage 01: Intake

Receive and validate pump prompt from NATRIX via Grok on iPhone.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| iPhone | Grok App | Pump Prompt JSON | First-strike intent from NATRIX |
| Tailscale | 0.0.0.0:6543 | POST /pump | Secure bridge delivery |

## Process

1. Receive pump prompt via Tailscale webhook
2. Validate JSON structure (required: intent, context, constraints)
3. Extract metadata (timestamp, NATRIX signature, priority)
4. Log intake in audit trail
5. Route to 02-analysis stage

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Validated Pump | `/Projects/NCL/prompts/intake/{timestamp}.json` | JSON |
| Audit Log | `/Projects/NCL/audit/intake.log` | TSV |
