# NCL Strategic Doctrine — Three Pillars of Mastery

## Origin: Sun Tzu × Greene × Covey → NCL Living Organism

This document maps principles from **The Art of War** (Sun Tzu), **The 48 Laws of Power** (Robert Greene), and **The 7 Habits of Highly Effective People** (Stephen Covey) into the NCL cognitive augmentation architecture. Every subsystem embodies these teachings.

---

## Pillar 1 — The Art of War (Strategic Supremacy)

### Mapped to NCL Architecture

| Sun Tzu Principle | NCL Subsystem | Implementation |
|---|---|---|
| **Know yourself, know your enemy** | Memory + Drift Investigation | Continuous self-assessment via memory analytics; drift detection reveals blind spots |
| **All warfare is based on deception** | PolicyGate (Immune) | Zero-trust posture; never reveal internal state to untrusted channels |
| **Supreme excellence: win without fighting** | Proactive Briefs | Daily/weekly briefs anticipate problems before they escalate |
| **Speed is the essence of war** | RateLimiter + SkillRouter | Fast routing, throttled resources; act decisively within constraints |
| **The terrain dictates strategy** | Adaptive Mission Runner | Route missions based on context; terrain = current event landscape |
| **Attack where unprepared, appear where unexpected** | Learning Engine pattern detection | Surface non-obvious insights from data; find signal in noise |
| **In the midst of chaos, there is opportunity** | Overload Investigation | High signal density = opportunity for insight extraction |
| **Let your plans be dark and impenetrable** | Auth + TLS + Faraday Fortress | Encrypted channels, API key enforcement, kill switch |
| **Move swift as the wind, steady as a forest** | EventBus + batch processing | High-throughput event ingestion with stable, ordered processing |
| **Every battle is won before it is fought** | Schema validation + golden tasks | Pre-validate all inputs; test all scenarios before deployment |

### The Five Factors (NCL Mapping)

1. **The Moral Law (Dao / 道)** → Prime Directive + consent registry — the cause that unites all agents
2. **Heaven (Tian / 天)** → Time-awareness: hourly distribution analysis, circadian patterns, seasonal planning
3. **Earth (Di / 地)** → Terrain: event landscape, data topology, schema geography
4. **The Commander (Jiang / 將)** → AZ_PRIME: wisdom, sincerity, benevolence, courage, strictness
5. **Method & Discipline (Fa / 法)** → PDCA loop, SOP enforcement, audit cadence, evidence trails

---

## Pillar 2 — The 48 Laws of Power (Influence Architecture)

### Mapped to NCL Architecture

| Law | NCL Principle | Where |
|---|---|---|
| **1 — Never outshine the master** | Agent deference to AZ_PRIME | PolicyGate: `AZ_PRIME` always allowed; agents serve the commander |
| **3 — Conceal your intentions** | Zero-trust, opaque error messages | Relay returns generic errors; never leak internals to callers |
| **4 — Always say less than necessary** | Minimal API responses | `_send()` returns only what's needed; no verbose stack traces |
| **6 — Court attention at all cost** | Proactive surface of insights | BrainMap, status reports, daily briefs push information proactively |
| **9 — Win through actions, not argument** | Evidence-based decisions | `Evidence or it didn't happen` — audit trails, NDJSON logs |
| **11 — Learn to keep people dependent on you** | Indispensable second brain | NCL as irreplaceable cognitive extension; transactive memory |
| **15 — Crush your enemy totally** | Dead-letter queue + full retry | Exhaust all retries; dead-letter ensures no mission silently fails |
| **17 — Keep others in suspended terror** | Kill switch + lockdown mode | System can instantly lock down; uncertainty deters abuse |
| **20 — Do not commit to anyone** | Channel-agnostic architecture | Works across Discord, Telegram, CLI, iOS, relay — no single dependency |
| **25 — Re-create yourself** | Self-healing + memory consolidation | HealthMonitor + consolidation worker: continuous self-renewal |
| **28 — Enter action with boldness** | Decisive mission execution | `run_with_retry` commits fully; no half-measures |
| **29 — Plan all the way to the end** | Mission lifecycle tracking | Queued → Running → Completed/Failed → Dead-letter: full lifecycle |
| **33 — Discover each person's thumbscrew** | Personalised learning | Memory importance scoring adapts to individual usage patterns |
| **35 — Master the art of timing** | Rate limiting + circadian awareness | Events per minute enforcement; hourly distribution analysis |
| **36 — Disdain things you cannot have** | Graceful degradation | Memory offline? Proceed without it. No numpy? Skip vector search. |
| **40 — Despise the free lunch** | Earned trust model | API keys required; consent flows; no anonymous access in production |
| **46 — Never appear too perfect** | Honest health reporting | HealthMonitor reports degraded states truthfully |
| **48 — Assume formlessness** | Flexible skill routing + plugin architecture | New skills register dynamically; system shape adapts to needs |

---

## Pillar 3 — The 7 Habits (Effectiveness Engine)

### Mapped to NCL Architecture

| Habit | NCL Implementation | Where |
|---|---|---|
| **1 — Be Proactive** | Proactive health monitoring + daily briefs | HealthMonitor heartbeats; daily brief generated before user asks |
| **2 — Begin with the End in Mind** | Mission-first architecture | Every mission has `mission_type`, expected output, audit trail |
| **3 — Put First Things First** | Priority-based message processing | `MessagePriority` (LOW→CRITICAL); importance-weighted memory |
| **4 — Think Win-Win** | Synergistic memory consolidation | Short-term → long-term promotion benefits both speed and depth |
| **5 — Seek First to Understand** | Memory search before action | GeneralChatSkill searches memory before responding; context first |
| **6 — Synergize** | Multi-agent coordination + EventBus | Skills combine; EventBus enables cross-component amplification |
| **7 — Sharpen the Saw** | Learning cycles + consolidation + pruning | `LearningSkill` triggers consolidation; `prune_memories()` reclaims |

### The Maturity Continuum (NCL Agent Evolution)

1. **Dependence** (Habits 1-3) → Agent follows policy, processes missions, respects kill switch
2. **Independence** (Habits 4-5) → Agent searches memory, generates insights, adapts behaviour
3. **Interdependence** (Habits 6-7) → Multi-agent synergy, cross-domain learning, continuous growth

---

## Integration Constants

These constants are embedded in the codebase as the strategic compass:

```python
# ncl_agency_runtime/agents/super_openclaw_agent.py
STRATEGIC_PRINCIPLES = {
    "art_of_war": {
        "terrain_awareness": "Adapt strategy to current event landscape",
        "supreme_victory": "Anticipate problems; win without fighting",
        "five_factors": "Dao, Heaven, Earth, Commander, Discipline",
        "speed_decisiveness": "Act within rate limits but never hesitate",
        "deception_defense": "Zero-trust; never reveal internals",
    },
    "laws_of_power": {
        "formlessness": "Adapt to any channel, any input, any scale",
        "evidence_over_argument": "Audit trails prove everything",
        "bold_action": "Commit fully to missions; retry with conviction",
        "master_timing": "Rate limit, circadian awareness, batch wisely",
        "strategic_opacity": "Return only necessary information",
    },
    "seven_habits": {
        "proactive": "Monitor health; generate briefs before asked",
        "end_in_mind": "Every mission has clear outcome and audit",
        "first_things_first": "Priority queue; importance scoring",
        "win_win": "Consolidation benefits speed and depth",
        "understand_first": "Search memory before responding",
        "synergize": "EventBus enables cross-component amplification",
        "sharpen_saw": "Learning cycles; prune; consolidate; grow",
    },
}
```

---

## The NCL Way — Unified Doctrine

> **"Know the terrain, control the timing, sharpen the blade."**
>
> — Sun Tzu's awareness × Greene's timing × Covey's continuous improvement

Every NCL subsystem embodies all three pillars simultaneously:

| Layer | Art of War | 48 Laws | 7 Habits |
|---|---|---|---|
| **Senses** (Connectors) | Scout the terrain | Court attention | Be Proactive |
| **Brain** (SkillRouter) | Terrain dictates strategy | Assume formlessness | Begin with End in Mind |
| **Nervous** (EventBus) | Swift as wind | Conceal intentions | Synergize |
| **Muscles** (Skills) | Attack decisively | Enter with boldness | Put First Things First |
| **Immune** (PolicyGate) | All warfare is deception | Never appear too perfect | Think Win-Win |
| **Memory** (MemoryManager) | Know yourself | Discover thumbscrew | Seek First to Understand |
| **Regeneration** (Health) | Win before fighting | Re-create yourself | Sharpen the Saw |
