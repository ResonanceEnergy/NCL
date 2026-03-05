# NCL Super OpenClaw Agent — Integration Specification
**Version:** 1.0.0  
**Status:** ACTIVE  
**Author:** NCL Agency Runtime (AZ_PRIME authorised)  
**Date:** 2025-07-11

---

## 1. Overview

The **NCL Super OpenClaw Agent** bridges the NCL cognitive augmentation platform
(NUREALCORTEXLINK v3.0) with the [OpenClaw](https://github.com/openclaw/openclaw)
personal AI assistant pattern — skills-based dispatch, persistent memory,
multi-channel messaging, and proactive second-brain retrieval.

**OpenClaw** is the fastest-growing open-source personal AI assistant framework
(238k+ GitHub stars) with an ecosystem of 18k+ repos covering skills, memory
systems, agent orchestration, and multi-channel connectors (Discord, Telegram,
WhatsApp, Signal, Slack).

### Key Resources Discovered

| Source | Key Insight |
|--------|-------------|
| `openclaw/openclaw` (GitHub) | Core personal AI — skills-based, own-your-data, 238k stars |
| `VoltAgent/awesome-openclaw-skills` | 22k+ stars, curated skill directory |
| `hesamsheikh/awesome-openclaw-usecases` | 12k+ stars, community use cases |
| `NevaMind-AI/memU` | 11k+ stars — persistent memory for 24/7 proactive agents |
| `MemTensor/MemOS` | AI memory OS for persistent skill memory + cross-task reuse |
| `volcengine/OpenViking` | Context database — memory, resources, skills via filesystem |
| `ComposioHQ/secure-openclaw` | Multi-channel (Telegram, WhatsApp, Signal, iMessage) |
| `BlockRunAI/ClawRouter` | Agent-native LLM router |
| r/openclaw (Reddit) | 118K weekly visitors — inbox mgmt, calendar, flight check-ins |
| r/openclawsetup | Local LLM setups — Ollama, LM Studio, privacy-first |
| r/crowdstrike discussion | Enterprise security concerns → "IronClaw" concept |

---

## 2. Architecture — Living Organism × OpenClaw Mapping

```
╔═══════════════╦════════════════════╦═══════════════════════════════════╗
║ NCL Organ     ║ OpenClaw Concept   ║ Implementation                    ║
╠═══════════════╬════════════════════╬═══════════════════════════════════╣
║ Senses        ║ Connectors         ║ DiscordConnector, TelegramConnector║
║ Brain         ║ Skill Router       ║ SkillRouter (trigger-keyword match)║
║ Nervous       ║ Event Bus          ║ EventBus (async pub/sub)           ║
║ Muscles       ║ Skill execution    ║ Skill.execute() → SkillResult      ║
║ Immune        ║ Policy Kernel      ║ PolicyGate (Faraday Fortress)      ║
║ Memory        ║ MemOS / memU       ║ ncl_memory VectorIndex + MemMgr   ║
║ Regeneration  ║ Self-heal / molts  ║ HealthMonitor (heartbeat)          ║
╚═══════════════╩════════════════════╩═══════════════════════════════════╝
```

### Data Flow

```
[Discord / Telegram / CLI]        ← SENSES (Ingest)
        │
        ▼
    InboundMessage (normalised)
        │
        ▼
    PolicyGate.evaluate()         ← IMMUNE (Faraday Fortress)
        │  kill_switch → sender_allowlist → risk_tier
        ▼
    EventBus.publish("msg.in")    ← NERVOUS SYSTEM
        │
        ▼
    SkillRouter.route()           ← BRAIN (dispatch)
        │  trigger matching → best skill
        ▼
    Skill.execute()               ← MUSCLES (action)
        │
        ├──→ ncl_memory search/store  ← MEMORY (second brain)
        │
        ▼
    SkillResult → reply
        │
        ▼
    Channel.send()                ← SENSES (Outbound)
        │
        ▼
    HealthMonitor heartbeat       ← REGENERATION
```

---

## 3. Files Created

| File | Purpose |
|------|---------|
| `ncl_agency_runtime/agents/__init__.py` | Package marker |
| `ncl_agency_runtime/agents/super_openclaw_agent.py` | Core agent engine — EventBus, PolicyGate, SkillRouter, 7 built-in skills, memory integration, CLI mode |
| `ncl_agency_runtime/agents/discord_connector.py` | Discord bot connector — `!ncl` prefix, channel filtering, attachment capture |
| `ncl_agency_runtime/agents/telegram_connector.py` | Telegram bot connector — `/ncl` commands, inline keyboards, group chat support |
| `ncl_agency_runtime/agents/launch.py` | Unified launcher — `--discord --telegram --cli --all` |
| `NCL_SUPER_OPENCLAW_SPEC.md` | This specification document |

---

## 4. Built-in Skills (OpenClaw Pattern)

| Skill | Triggers | Description |
|-------|----------|-------------|
| `memory_search` | "remember", "recall", "search memory" | Semantic search across NCL second brain |
| `memory_store` | "remember this", "store memory", "note this" | Store new episodic memory |
| `doctrine` | "doctrine", "living organism", "agent corps" | Surface NCC Master Doctrine v2.0 concepts |
| `brain_map` | "brain map", "mind map", "knowledge map" | Text-based cognitive landscape overview |
| `status` | "status", "health", "ping" | Agent uptime, skills, channels, memory status |
| `help` | "help", "commands", "skills" | List all available skills and triggers |
| `learn` | "learn", "consolidate", "reflect" | Trigger learning cycle — consolidation + patterns |

---

## 5. Discord Setup

```bash
# 1. Create bot at https://discord.com/developers/applications
# 2. Enable MESSAGE_CONTENT intent
# 3. Invite bot to server with appropriate permissions

export NCL_DISCORD_TOKEN="your_bot_token"
export NCL_DISCORD_CHANNELS="123456789,987654321"  # optional

# Run
python -m ncl_agency_runtime.agents.launch --discord
```

**Commands in Discord:**
- `!ncl help` — list skills
- `!ncl brain map` — show cognitive landscape
- `!ncl remember this: NCL v3 uses Living Organism framework`
- `!ncl search memory cortex` — semantic search
- `!ncl doctrine` — show doctrine concepts
- `@BotName status` — via mention

---

## 6. Telegram Setup

```bash
# 1. Talk to @BotFather → /newbot → copy token
# 2. Optionally set commands via /setcommands:
#    ncl - Run NCL Super OpenClaw command

export NCL_TELEGRAM_TOKEN="your_bot_token"
export NCL_TELEGRAM_ALLOWED="12345678"  # optional user ID filter

# Run
python -m ncl_agency_runtime.agents.launch --telegram
```

**Commands in Telegram:**
- `/start` — Welcome message with inline keyboard buttons
- `/ncl brain map` — cognitive overview
- `/ncl remember this: AZ reviews weekly`
- Any plain text message → auto-routed to skills
- Inline buttons: Brain Map, Status, Doctrine, Help

---

## 7. Dependencies

Added to `requirements-dev.txt`:
```
discord.py>=2.3.0
python-telegram-bot>=20.0
```

Install:
```bash
pip install discord.py python-telegram-bot
```

---

## 8. Config Changes

Added `openclaw` section to `ncl_config.json`:
```json
{
  "openclaw": {
    "enabled": true,
    "agent_id_prefix": "ncl-openclaw",
    "default_channels": ["cli"],
    "discord": {
      "enabled": false,
      "token_env": "NCL_DISCORD_TOKEN",
      "prefix": "!ncl"
    },
    "telegram": {
      "enabled": false,
      "token_env": "NCL_TELEGRAM_TOKEN",
      "prefix": "/ncl"
    },
    "skills": {
      "builtin": ["memory_search", "memory_store", "doctrine",
                   "brain_map", "status", "help", "learn"],
      "custom_skills_path": "~/NCL/skills"
    }
  }
}
```

---

## 9. Security (Faraday Fortress Compliance)

- **PolicyGate** enforces zero-trust for every inbound message
- **Kill switch** can halt all processing instantly
- **Sender allow-list** — AZ_PRIME always allowed; others configurable
- **Rate limiting** inherited from relay_server.py infrastructure
- **No API keys stored in code** — all tokens via environment variables
- **Memory is local-only** — no cloud sync unless explicitly configured
- **Audit trail** — every message → EventBus → logged

---

## 10. OpenClaw Use Cases Applied to NCL

Based on research from GitHub + Reddit:

| Use Case (OpenClaw Community) | NCL Implementation |
|-------------------------------|-------------------|
| Inbox triage / email management | `memory_search` + mission_runner weekly_brief |
| Calendar & scheduling | Doctrine skill → Operating Rhythm daily/weekly/monthly |
| Knowledge capture from chat | `memory_store` → episodic memory → VectorIndex |
| Second brain navigation | `brain_map` skill → cognitive landscape overview |
| Multi-channel presence | Discord + Telegram + CLI + iOS CompanionApp |
| Local-first / privacy | Local memory, no cloud by default, PolicyKernel |
| Agent skill extensibility | `Skill` base class → register custom skills at runtime |
| Proactive health monitoring | `HealthMonitor` heartbeat → degradation detection |
| Cross-task memory reuse (MemOS) | VectorIndex semantic search across all memory types |

---

## 11. Extending with Custom Skills

```python
from ncl_agency_runtime.agents.super_openclaw_agent import (
    Skill, SkillResult, InboundMessage, SuperOpenClawAgent, create_agent
)

class WeatherSkill(Skill):
    name = "weather"
    triggers = ["weather", "forecast", "temperature"]
    description = "Check the weather (example custom skill)"

    async def execute(self, msg, agent):
        return SkillResult(
            success=True,
            reply="Weather skill not yet connected to an API.",
            skill_name=self.name
        )

# Register
agent = create_agent(extra_skills=[WeatherSkill()])
```

---

## 12. Next Steps

- [ ] Connect to real LLM backend (OpenAI / Ollama) for natural language understanding
- [ ] Add WhatsApp connector (Twilio / Baileys)
- [ ] Implement proactive memory surfacing (scheduled insight delivery)
- [ ] Add voice channel support for Discord
- [ ] Build iOS Shortcuts integration that routes through the agent pipeline
- [ ] Create a web dashboard (FastAPI + HTMX) for agent management
- [ ] Implement OpenClaw ClawHub skill marketplace compatibility

---

*Authorised by AZ_PRIME — NCL Super OpenClaw v1.0.0*
