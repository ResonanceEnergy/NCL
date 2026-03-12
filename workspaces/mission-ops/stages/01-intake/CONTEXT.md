# Mission Intake

Receive a mission definition, validate it against the schema, and prepare it for dispatch.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| User or automation | Mission JSON payload | Full file | The mission to process |
| Schema catalog | `../../schemas/ncl.iphone.v1/index.json` | Mission schema | Validation rules |
| Mission queue | `../../ncl_agency_runtime/missions/queue/` | Full directory | Check for duplicates |

## Process

1. Receive the mission definition (JSON payload or file path)
2. Validate against the mission schema using jsonschema
3. Check the mission queue for duplicates (same objective within 24h)
4. Assign a mission ID if not present (format: `mission-YYYYMMDD-HHMMSS`)
5. Tag with priority level (critical, high, normal, low) based on mission type
6. Write the validated mission to output/

## Audit

| Check | Pass Condition |
|-------|---------------|
| Schema valid | jsonschema validation passes with zero errors |
| No duplicate | No matching mission in queue within 24h window |
| Priority tagged | Mission has a priority field with valid value |

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Validated mission | output/[mission-id]-intake.json | JSON with metadata |
