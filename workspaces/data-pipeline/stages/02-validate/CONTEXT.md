# Data Validate

Validate captured events against the NCL JSON Schema catalog (43+ event types).

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| Previous stage | `../01-capture/output/` | Full file | Raw captured events |
| Schema catalog | `../../../schemas/ncl.iphone.v1/index.json` | Full file | Schema index |
| Schema files | `../../../schemas/ncl.iphone.v1/` | Event-specific schema | Validation rules |
| Validation tool | `../../../tools/validate_events.py` | Full file | Validation logic |

## Process

1. Read raw events from 01-capture/output/
2. For each event, look up the matching schema from the catalog by event type
3. Run jsonschema validation against the matched schema
4. Events that pass: write to output/ as validated
5. Events that fail: write to quarantine (`../../../data/quarantine/`) with error details
6. Log validation summary (pass count, fail count, error types)

## Audit

| Check | Pass Condition |
|-------|---------------|
| All processed | Every file in 01-capture/output/ was attempted |
| Quarantine logged | Failed events have error details in quarantine |
| Schema matched | Every event type resolved to a schema (no unknown types) |

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Validated events | output/[event-type]-validated.json | JSON, schema-conformant |
| Validation summary | output/validation-summary.md | Markdown report |
