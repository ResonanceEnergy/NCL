# Research Skill

Claude skill for dispatching and managing UNI research tasks.

## Triggers
- `research {topic}` — Queue a new research request
- `research status` — Show active research tasks
- `research archive {id}` — Retrieve completed research

## Behavior

1. Parses the topic and extracts keywords
2. Checks for existing research on the same topic (dedup)
3. Creates a research request JSON in `research-pipeline/queue/`
4. Returns confirmation with request ID and estimated completion time

## Integration

- Reads from: `research-pipeline/archive/` (for dedup and context)
- Writes to: `research-pipeline/queue/` (new requests)
- Calls: UNI agent via Paperclip API for execution
