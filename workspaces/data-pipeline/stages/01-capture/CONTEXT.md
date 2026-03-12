# Data Capture

Ingest raw events from iPhone sensors and Shortcuts into the NCL data pipeline.

## Inputs

| Source | File/Location | Section/Scope | Why |
|--------|--------------|---------------|-----|
| iPhone | HTTP POST or file drop | Raw JSON payload | Source data |
| Data contract | `../../../docs/ncl_iphone_data_contract_v1.md` | "Event Types" | Expected formats |
| Import tool | `../../../tools/import_data.py` | Full file | Ingestion logic |

## Process

1. Receive raw event data (HTTP endpoint, file drop, or Shortcut webhook)
2. Parse the JSON payload and extract the event type field
3. Assign a receipt timestamp and ingestion ID
4. Check for basic structural validity (has required top-level fields)
5. Write the raw event with metadata to output/

## Outputs

| Artifact | Location | Format |
|----------|----------|--------|
| Raw event | output/[event-type]-[timestamp].json | JSON with ingestion metadata |
