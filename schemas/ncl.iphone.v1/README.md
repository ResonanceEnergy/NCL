# NCL iPhone JSON Schemas — v1

Location: `schemas/ncl.iphone.v1/`

What this folder contains
- `envelope.json` — canonical event envelope (required fields + metadata)
- Per-event JSON Schema files for the top-20 insights listed in the doctrine.
- `index.json` — catalog mapping `event_type` → schema file.

Quick usage
- Validate an event locally with `jsonschema` (Python) or `ajv` (Node):
  - Python example: `pip install jsonschema` then:
    ```py
    from jsonschema import validate, RefResolver, Draft7Validator
    import json
    schema = json.load(open('schemas/ncl.iphone.v1/screentime.session.json'))
    event = json.load(open('examples/payloads.json'))
    validate(instance=event, schema=schema)
    ```

Notes
- All schemas are intentionally metadata-first (no content fields).  
- `privacy_level` and `retention_tier` are required at the envelope level.
- A CI validator was added: `tools/validate_events.py` + GitHub Actions workflow `.github/workflows/validate-events.yml` — it validates example events and Shortcuts-emitted JSON on PRs.  
- If you want additional stream schemas generated (top-50), tell me which ones and I’ll add them.
