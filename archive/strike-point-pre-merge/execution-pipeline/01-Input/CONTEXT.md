# 01-Input — Pump Prompt Intake

## Purpose
Receives pump prompts from the FirstStrike relay. Each pump arrives as a JSON file written by the relay server or forwarded by NCL Brain.

## Source
- `NCL/mandate-generation/input/pump-*.json` (relay writes here)
- Copied here by the pump-watcher service when processing begins

## File Format
```json
{
  "pump_id": "PUMP-20260403-001",
  "relay_id": "RLY-...",
  "prompt": {
    "raw_intent": "...",
    "formatted_prompt": "...",
    "target_pillar": "NCL|NCC|BRS|AAC|GAMES",
    "priority": "P0|P1|P2|P3"
  }
}
```

## Routing
- Read pump → extract task type and pillar
- Copy to 02-Planning/ with status `pending`
- If pump is P0/critical: flag for immediate council
