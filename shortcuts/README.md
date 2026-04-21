# NCL Shortcuts Pack v1

iOS Shortcuts for interacting with the NCL Brain pipeline from iPhone.

## Setup

1. Set your Mac Mini's local IP or Tailscale hostname in the shortcut variables
2. Set your `STRIKE_AUTH_TOKEN` (from NCL startup logs or `.env`)
3. Import the shortcuts via the JSON definitions below or use the `/shortcuts/config` endpoint

## Shortcuts

| Shortcut | Trigger | Description |
|----------|---------|-------------|
| NCL Pump | "Hey Siri, pump NCL" | Send a pump prompt to NCL Brain |
| NCL Status | "Hey Siri, NCL status" | Check pipeline health and pending items |
| NCL Approve | "Hey Siri, approve pump" | Review and approve pending pump prompts |
| NCL Council | "Hey Siri, run council" | Trigger an intelligence council session |
| NCL Search | "Hey Siri, search NCL" | Full-text search across NCL data |
| NCL Intel | "Hey Siri, NCL intel" | Get latest intelligence brief, generate fresh, or escalate to STRIKE-POINT |
| NCL Signal Action | "Hey Siri, NCL signal" | Act on a specific signal — acknowledge, investigate, or escalate |

## Configuration Endpoint

```bash
curl http://YOUR_NCL_HOST:8800/shortcuts/config
```

Returns JSON with all shortcut definitions and your current auth token.
