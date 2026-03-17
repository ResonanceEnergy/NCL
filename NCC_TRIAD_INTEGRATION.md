# NCC Triad Integration — Complete Architecture
**Version:** 1.0.0  
**Status:** ACTIVE  
**Date:** 2026-03-08  
**Authority:** NCC (Natrix Command & Control)

---

## 1. Overview

This document codifies the integration of all five pillars of the Resonance Energy ecosystem under NCC governance:

| Pillar | ID | Role | Description |
|--------|-----|------|-------------|
| **NCC** | `ncc` | Governance | Supreme command & control — orchestrates the triad |
| **NCL** | `ncl` | Brain | Cognitive augmentation, second brain, memory, learning |
| **AAC** | `aac` | Bank | Algorithmic Asset Command — trading, portfolio, 8 exchanges |
| **BRS (Bit Rage Systems)** | `sa` | Agency | Agent workforce orchestration, multi-agent coordination |
| **Digital Labour** | `dl` | Labour | Autonomous worker pool executing tasks for all pillars |

### The Resonance Energy Equation
```
NCC governs → NCL (Brain) + AAC (Bank) + BRS (Agency/Workforce)
              ═══════════════════════════════════════════════════════════════════════════════
              = Compounding feedback loop = RESONANCE
```

---

## 2. Architecture

### 2.1 Component Map

```
┌───────────────────────────────────────────────────┐
│                 NCC ORCHESTRATOR                   │
│          Supreme Governance (PDCA Loop)            │
│   ┌─────────────────────────────────────────────┐ │
│   │         PILLAR REGISTRY                      │ │
│   │   NCC | NCL | AAC | SA | DL                  │ │
│   │   Capabilities • Health • Discovery          │ │
│   └─────────────────────────────────────────────┘ │
│   ┌─────────────────────────────────────────────┐ │
│   │       INTER-PILLAR MESSAGE BUS              │ │
│   │   Request/Response • Events • Commands      │ │
│   │   Heartbeats • Alerts • Task Assignment     │ │
│   │   Audit Trail • Dead-Letter Queue           │ │
│   └─────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────┘
        │              │              │           │
   ┌────▼────┐   ┌─────▼─────┐  ┌────▼─────┐ ┌──▼───────────┐
   │   NCL   │   │    AAC    │  │  SUPER   │ │   DIGITAL    │
   │  Brain  │   │   Bank    │  │  AGENCY  │ │   LABOUR     │
   │         │   │           │  │          │ │              │
   │ Memory  │   │ Trading   │  │ Agents   │ │ Workers      │
   │ Events  │   │ Portfolio │  │ Tasks    │ │ Reports      │
   │ Learning│   │ Risk      │  │ Research │ │ Processing   │
   │ Briefs  │   │ Signals   │  │ Entropy  │ │ Analysis     │
   └─────────┘   └───────────┘  └──────────┘ └──────────────┘
```

### 2.2 Data Flow

```
1. NCC boots → bootstrap_registry() populates all pillars
2. InterPillarBus starts → async message dispatch loop
3. DigitalLabourPool starts → worker coroutines pull tasks
4. Pillars send heartbeats → NCC tracks health
5. Cross-pillar requests flow via typed PillarMessage envelopes
6. PDCA governance cycle runs periodically (Plan→Do→Check→Act)
```

---

## 3. Modules

### 3.1 Pillar Registry (`runtime/pillar_registry.py`)
- `PillarID` — Canonical enum: `ncc`, `ncl`, `aac`, `sa`, `dl`
- `PillarRegistration` — Name, role, capabilities, status, endpoint
- `PillarRegistry` — Singleton registry with discovery, health, triad checks
- `bootstrap_registry()` — Populates all default pillar registrations

### 3.2 Inter-Pillar Bus (`runtime/inter_pillar_bus.py`)
- `PillarMessage` — Typed envelope with source/target/trace_id/correlation_id
- `MessageType` — REQUEST, RESPONSE, EVENT, COMMAND, HEARTBEAT, ALERT, TASK_*
- `InterPillarBus` — Async pub/sub with topic routing, dead-letter, audit log
- Supports sync dispatch for non-async contexts

### 3.3 Digital Labour (`runtime/digital_labour.py`)
- `LabourTask` — Work unit with type, priority, retry, timeout
- `TaskHandler` — Base class for pluggable task executors
- Built-in handlers: Report, DataProcessing, Research, Analysis, Monitoring
- `DigitalLabourPool` — Worker pool with queue, lifecycle, bus integration

### 3.4 NCC Orchestrator (`runtime/ncc_orchestrator.py`)
- `PDCACycle` — Plan-Do-Check-Act governance tracker
- `NCCOrchestrator` — Wires registry + bus + labour, handles commands/alerts
- Cross-pillar routing helpers: `ncl_memory_search`, `aac_portfolio_status`, etc.
- `run_pdca_cycle()` — Full governance cycle execution

---

## 4. Message Contract

### 4.1 PillarMessage Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source` | PillarID | Yes | Sending pillar |
| `target` | PillarID | Yes | Receiving pillar |
| `msg_type` | MessageType | Yes | Message category |
| `payload` | dict | Yes | Typed payload (varies by msg_type) |
| `priority` | Priority | No | LOW / NORMAL / HIGH / CRITICAL |
| `msg_id` | str | Auto | Unique message identifier |
| `correlation_id` | str | No | Links request → response |
| `trace_id` | str | Auto | End-to-end trace across pillars |
| `ttl_seconds` | int | No | Expiry window (default 300s) |
| `attempt` | int | Auto | Current retry attempt |

### 4.2 Standard Payloads

**NCC Command — Health Check:**
```json
{"action": "health_check"}
→ Response: {"total_pillars": 5, "online": 3, ...}
```

**NCC Command — Triad Status:**
```json
{"action": "triad_status"}
→ Response: {"triad": {"ncl": "online", "aac": "online", "sa": "bootstrapping", "dl": "online"}}
```

**Task Assignment (to Digital Labour):**
```json
{"task_type": "report_generation", "title": "Daily Brief", "task_payload": {"report_type": "daily"}}
→ Response: {"task_id": "dl-abc123", "status": "queued"}
```

**Alert (to NCC):**
```json
{"severity": "critical", "message": "Portfolio drawdown exceeds 5%"}
→ Response: {"acknowledged": true, "severity": "critical"}
```

---

## 5. Governance: PDCA Loop

```
    ┌─────────┐
    │  PLAN   │ ← Gather health summaries, identify issues
    └────┬────┘
         │
    ┌────▼────┐
    │   DO    │ ← Dispatch corrective tasks via Digital Labour
    └────┬────┘
         │
    ┌────▼────┐
    │  CHECK  │ ← Verify task results, bus/labour stats
    └────┬────┘
         │
    ┌────▼────┐
    │   ACT   │ ← Update doctrine, advance cycle counter
    └────┬────┘
         │
         └──────→ Back to PLAN (continuous improvement)
```

---

## 6. Usage

### 6.1 Bootstrap the Ecosystem

```python
from ncl_agency_runtime.runtime.ncc_orchestrator import NCCOrchestrator

orch = NCCOrchestrator.get_instance()
status = orch.bootstrap()
# → All 5 pillars registered, NCC ONLINE
```

### 6.2 Start Async Services

```python
import asyncio

async def main():
    orch = NCCOrchestrator.get_instance()
    orch.bootstrap()
    await orch.start()  # Starts bus + labour pool
    
    # Dispatch work
    task_id = await orch.dispatch_labour(
        TaskType.REPORT_GENERATION,
        "Generate Daily Brief",
        {"report_type": "daily", "data": {"events": 42}},
    )
    
    # Query triad
    print(orch.full_status())
    
    await orch.stop()
```

### 6.3 Send Cross-Pillar Messages

```python
from ncl_agency_runtime.runtime.inter_pillar_bus import *
from ncl_agency_runtime.runtime.pillar_registry import PillarID

bus = InterPillarBus.get_instance()

# NCL → AAC: request portfolio status
msg = PillarMessage(
    source=PillarID.NCL,
    target=PillarID.AAC,
    msg_type=MessageType.REQUEST,
    payload={"action": "portfolio_status"},
)
response = await bus.request(msg)
```

### 6.4 Register Custom Labour Handler

```python
from ncl_agency_runtime.runtime.digital_labour import *

class MyCustomHandler(TaskHandler):
    task_type = TaskType.CONTENT_CREATION
    name = "content_creator"
    
    async def execute(self, task: LabourTask) -> dict:
        # Your custom logic
        return {"content": "Generated content", "success": True}

pool = DigitalLabourPool.get_instance()
pool.register_handler(MyCustomHandler())
```

---

## 7. Test Coverage

**54 tests across 6 test classes:**

| Class | Tests | Coverage |
|-------|-------|----------|
| TestPillarRegistry | 15 | Registration, discovery, health, triad |
| TestInterPillarBus | 10 | Subscribe, dispatch, routing, expiry |
| TestDigitalLabour | 10 | Tasks, handlers, lifecycle, bus integration |
| TestPDCACycle | 3 | Phase advancement, evidence trail |
| TestNCCOrchestrator | 9 | Bootstrap, commands, alerts, PDCA |
| TestEndToEndIntegration | 7 | Full flow, cross-pillar routing, capability discovery |

---

## 8. Doctrine Alignment

| Doctrine | Application |
|----------|-------------|
| Art of War: "Know yourself, know your enemy" | PillarRegistry discovers all capabilities |
| Art of War: "Speed is the essence" | Async bus, non-blocking dispatch |
| Law 9: "Win through actions, not argument" | Every message has audit trail |
| Law 29: "Plan all the way to the end" | TTL, retries, dead-letter, PDCA |
| Habit 2: "Begin with the end in mind" | trace_id spans entire cross-pillar flow |
| Habit 6: "Synergize" | Pillars amplify each other through the bus |
| Habit 7: "Sharpen the Saw" | PDCA governance cycle, continuous improvement |
| Nate B Jones: "Systems Over Tactics" | The orchestrator IS the system |
| Dario Amodei: "Interpretability" | Every message is traceable and auditable |
| Tom Bilyeu: "Radical Accountability" | Every task has an owner and outcome |
| NCC Doctrine: "If it isn't governed, it isn't real" | PDCA enforces governance |
