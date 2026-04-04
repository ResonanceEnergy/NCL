# Working Memory

Active context for current sessions, councils, and mandate processing.

## Purpose

Working memory holds the state needed by NCL's current cognitive tasks:
- Active council deliberation context
- Current mandate drafts and revisions
- Recent intelligence briefings being acted on
- Temporary associations between concepts

## File Format

Each working memory entry is a JSON file: `ctx-{session_id}.json`

```json
{
  "session_id": "council-20260404-war-room",
  "type": "council | mandate | research | general",
  "created_at": "2026-04-04T12:00:00Z",
  "expires_at": "2026-04-04T18:00:00Z",
  "context": {
    "topic": "War Room scenario evaluation",
    "participants": ["claude", "grok", "gemini"],
    "key_facts": [],
    "decisions_made": [],
    "pending_questions": []
  },
  "linked_memories": ["mem-20260404-geopolitical-001"],
  "linked_mandates": ["MANDATE-2026-010"]
}
```

## Lifecycle

Working memory entries expire after their session ends. On expiration:
1. Important insights are extracted and promoted to long-term memory
2. Decision records are archived in the relevant mandate folder
3. The working entry is deleted
