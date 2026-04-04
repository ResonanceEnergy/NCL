# Research Queue

Incoming research requests from NATRIX pump prompts, council outputs, or intelligence scan triggers.

## File Format

Each request is a JSON file named `research-{YYYYMMDD}-{topic_slug}.json`:

```json
{
  "request_id": "research-20260404-quantum-tunneling",
  "topic": "Quantum tunneling at macro scale",
  "requester": "NATRIX | council | awarebot-fpc",
  "priority": "HIGH | MEDIUM | LOW",
  "context": "Brief description of why this research is needed",
  "keywords": ["quantum", "tunneling", "macro"],
  "related_mandates": ["MANDATE-2026-xxx"],
  "created_at": "2026-04-04T12:00:00Z",
  "deadline": null,
  "assigned_to": null
}
```

## Processing

UNI research cortex polls this directory. When a request is picked up:
1. File moves to `../active/{request_id}.json` with `assigned_to` and `started_at` added
2. UNI executes multi-source research (Perplexity, Gemini, local models)
3. On completion, findings go to `../archive/{request_id}/` as a folder with report + sources
