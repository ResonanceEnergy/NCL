# Full Loop Simulation — First Strike → Strike Point → NCL → Claude → VS Code → Claude → First Strike

**Date**: 2026-04-06
**Type**: Pipeline trace simulation with gap analysis
**Scope**: Complete round-trip from iPhone pump prompt through coding execution to notification return

---

## Simulation: "Build a health check dashboard for all NARTIX services"

### Stage 1: FIRST STRIKE (iPhone → Mac Mini)

**What happens**: NATRIX opens Grok on iPhone, types "Build a health check dashboard for all NARTIX services". Grok formats it as a pump prompt. iOS Shortcut fires to `POST https://<tailscale-ip>:8443/pump` on Mac Mini.

**Files involved**:
- `FirstStrike/relay-pump-endpoint.py` — receives HTTP POST
- `FirstStrike/Sources/Network/RelayClient.swift` — iOS client
- `FirstStrike/certs/relay.pem` — TLS encryption

**What EXISTS**: Relay server, iOS client, TLS certs, plist service, health endpoint.

**STATUS**: ✅ OPERATIONAL — 13 pump prompts already in queue, 2 relay files (RLY-*.json) confirmed delivered.

**HANDOFF**: Relay writes atomic JSON to `NCL/mandate-generation/input/pump-{date}-{seq}.json`

---

### Stage 2: STRIKE POINT (NCL Brain receives pump)

**What happens**: NCL Brain API (`POST /pump`) receives the pump prompt. Strike token authenticates. If `auto_flow=true`, it spawns a council session.

**Files involved**:
- `NCL/runtime/api/routes.py` — `/pump` endpoint (line 111)
- `NCL/runtime/ncl_brain/brain.py` — `receive_pump_prompt()` (line 198)
- `NCL/runtime/ncl_brain/models.py` — PumpPrompt model

**What EXISTS**: Full API with auth, council spawning, approval gate, pending/review/approve/reject endpoints.

**STATUS**: ✅ OPERATIONAL — endpoints defined, brain initializes with all API keys.

**HANDOFF**: Brain stores pump → spawns council → produces mandate → waits at approval gate.

---

### Stage 3: NCL COUNCIL (Claude chairs debate)

**What happens**: Claude chairs a council session. Grok, Gemini, Perplexity, GPT debate the pump prompt. Council produces consensus + proposed mandates.

**Files involved**:
- `NCL/runtime/ncl_brain/brain.py` — council spawning logic
- `NCL/shared/doctrine/paperclip.config.json` — agent definitions
- `NCL/shared/doctrine/AGENTS.md` — council protocol

**What EXISTS**: Council session model, consensus scoring, synthesis output, mandate extraction.

**STATUS**: ⚠️ PARTIALLY OPERATIONAL — council sessions exist in output (council-session-20260402-001.json, council-session-20260403-001.json) but the multi-LLM debate may not be calling all 4 external APIs yet. Need to verify live API calls to Grok/Gemini/Perplexity/GPT.

**HANDOFF**: Council output → `_pending_dispatches` dict → NATRIX approval gate

---

### Stage 4: NATRIX APPROVAL GATE (Human-in-the-Loop)

**What happens**: NATRIX reviews proposed mandates via `GET /pump/pending` and `GET /pump/review/{pump_id}`. Approves with `POST /pump/approve/{pump_id}`.

**Files involved**:
- `NCL/runtime/api/routes.py` — lines 153-311 (pending/review/approve/reject)
- `NCL/runtime/ncl_brain/brain.py` — `approve_and_dispatch()` (line 341)

**What EXISTS**: Full approval flow — list pending, review details, approve all/some, modify-and-approve, reject with reason.

**STATUS**: ✅ OPERATIONAL — code exists and mandate MANDATE-2026-008 shows "APPROVED" status.

**GAP**: ❌ **No push notification to iPhone when approval is needed.** NATRIX has to poll `/pump/pending` manually or check the API. There's no webhook/push that says "hey, 3 mandates need your review."

**HANDOFF**: Approved mandates → `_dispatch_to_ncc()` → HTTP POST to `localhost:8765/mandate/intake`

---

### Stage 5: NCC DISPATCH (Mandate → Execution)

**What happens**: NCL dispatches approved mandates to NCC server via `POST /mandate/intake`. NCC receives and queues for execution.

**Files involved**:
- `NCL/runtime/ncl_brain/brain.py` — `_dispatch_to_ncc()` (line 667)
- `ncc-server/ncc_master.py` — master orchestrator

**What EXISTS**: Dispatch function with httpx client, NCC master server running.

**STATUS**: ⚠️ PARTIALLY VERIFIED — dispatch code exists and NCC server exists, but need to confirm NCC has a `/mandate/intake` endpoint that matches what NCL sends.

**HANDOFF**: NCC receives mandate → triggers execution pipeline

---

### Stage 6: EXECUTION PIPELINE (Claude → VS Code/Copilot → Claude)

**What happens**: Execution loop reads the mandate, loads council output, builds a precise coding prompt, writes it to `03-Execution/current-copilot-prompt.md`. Claude Desktop (or human) copies it to VS Code Copilot Agent Mode. Copilot (Claude Opus 4.6) executes. Output reviewed in `04-Review/`. Up to 3 iterations.

**Files involved**:
- `NCL/runtime/execution_loop.py` — full pipeline processor
- `NCL/workspaces/execution-pipeline/03-Execution/CONTEXT.md` — prompting techniques
- `NCL/_core/templates/copilot-execution-prompt.md` — prompt template
- `NCL/.github/copilot-instructions.md` — VS Code house rules

**What EXISTS**: Execution loop with `load_task_plan()`, `load_council_output()`, `run_execution_loop()`, `run_sign_off()`. Working files directory. Copilot prompt template. House rules.

**STATUS**: ✅ OPERATIONAL — test artifacts exist: `working-files/nartix_health.py`, `current-copilot-prompt.md`, `signed-off.md`, verification report in 04-Review, final artifact in 05-Output.

**GAP**: ❌ **The Claude→Copilot handoff is manual.** `execution_loop.py` WRITES the prompt to a file, but someone has to OPEN VS Code, PASTE the prompt into Copilot Agent Mode, and COPY the output back. There's no automated bridge between Claude Desktop and VS Code Copilot.

**GAP**: ❌ **No automated trigger from NCC dispatch to execution_loop.py.** The execution loop is CLI-driven (`python3 -m runtime.execution_loop <pump-id>`). NCC dispatches via HTTP, but nothing auto-launches the execution loop.

**HANDOFF**: Execution output → `05-Output/artifacts-{id}/` + `feedback-{id}.json`

---

### Stage 7: REVIEW & FEEDBACK (Claude reviews Copilot output)

**What happens**: Claude reviews the coded output against acceptance criteria. If it passes, signs off. If not, generates a fix prompt for another iteration.

**Files involved**:
- `NCL/runtime/execution_loop.py` — `run_sign_off()` function
- `NCL/workspaces/execution-pipeline/04-Review/` — verification reports

**What EXISTS**: Sign-off function, verification report JSON format, iteration tracking.

**STATUS**: ✅ OPERATIONAL — `verification-report-CODING-TEST-001.json` exists with pass/fail data.

**HANDOFF**: Signed-off output → feedback report → NCL feedback-synthesis pipeline

---

### Stage 8: FEEDBACK RETURN (Output → NCL → First Strike)

**What happens**: Execution feedback flows back to NCL. NCL processes it through feedback-synthesis/. Results should somehow reach NATRIX on iPhone.

**Files involved**:
- `NCL/workspaces/execution-pipeline/05-Output/feedback-{id}.json`
- `NCL/feedback-synthesis/ncc-reports/` — where NCC reports should land

**What EXISTS**: Feedback report YAML schema defined, synthesis pipeline documented.

**GAP**: ❌ **No automated feedback relay back to iPhone.** The loop ends at `05-Output/feedback-{id}.json`. There's no reverse relay that pushes a notification or summary back to NATRIX's iPhone. The feedback sits on the Mac Mini until NATRIX checks manually.

**GAP**: ❌ **No webhook from execution completion → NCL Brain API.** When execution_loop.py finishes, it writes files but doesn't call `POST /feedback` on the NCL API. The brain doesn't know the task is done.

---

## Intelligence Council Integration Point

### Stage 2.5: COUNCIL INTELLIGENCE FEED (parallel)

**What happens**: YouTube + X councils run on schedule (every 6 hours) or on-demand. Reports feed into War Room. War Room directives auto-route to `mandate-generation/input/` as `RLY-WAR-ROOM-*.json`.

**Files involved**:
- `NCL/runtime/councils/runner.py` — orchestrator
- `NCL/runtime/councils/shared/war_room_bridge.py` — synthesis + routing
- `NCL/intelligence-scan/council-reports/` — output

**What EXISTS**: Full pipeline — scraper, transcriber, analyzer, scanner, War Room bridge, directive routing to mandate input, AAC relay.

**GAP**: ⚠️ **Council sweep scheduling not wired.** `paperclip.config.json` defines `council_sweep` on a 6-hour cron, but there's no actual cron job or launchd plist running `./run-councils.sh` on schedule. It's manual-only right now.

---

## GAP SUMMARY

### CRITICAL (Pipeline Breaks Without These)

| # | Gap | Stage | Impact | Fix Complexity |
|---|-----|-------|--------|----------------|
| 1 | **No push notification to iPhone for approval** | 4 | NATRIX doesn't know mandates need review | Medium — add Apple Push Notification or Pushover webhook |
| 2 | **No automated NCC → execution_loop trigger** | 6 | Mandates approved but nothing starts coding | Medium — NCC calls execution_loop.py via subprocess or HTTP |
| 3 | **No feedback return to iPhone** | 8 | NATRIX doesn't know tasks are done | Medium — reverse relay endpoint on FirstStrike |

### IMPORTANT (Pipeline Works But Manually)

| # | Gap | Stage | Impact | Fix Complexity |
|---|-----|-------|--------|----------------|
| 4 | **Claude→Copilot handoff is manual** | 6 | Human must copy prompt to VS Code | Hard — requires Computer Use or VS Code extension API |
| 5 | **execution_loop.py doesn't POST feedback to NCL API** | 8 | Brain doesn't know task finished | Easy — add httpx call at end of run_sign_off() |
| 6 | **Council sweep not scheduled** | 2.5 | Intelligence only runs when manually triggered | Easy — add launchd plist or cron entry |

### NICE-TO-HAVE (Polish)

| # | Gap | Stage | Impact | Fix Complexity |
|---|-----|-------|--------|----------------|
| 7 | **AAC War Room directory doesn't exist** | 2.5 | Market signals saved locally instead of reaching AAC | Easy — mkdir + AAC integration |
| 8 | **Multi-LLM council API calls unverified** | 3 | May only use Claude, not all 4 debaters | Medium — test each API key, add connection check |
| 9 | **No relay web dashboard** | 1 | Phase 3 of MANDATE-2026-008 (M3.4) | Medium — Streamlit or FastAPI static page |

---

## Recommended Fix Order

1. **Gap 5** (Easy): Add feedback POST to execution_loop.py → NCL brain knows when tasks complete
2. **Gap 6** (Easy): Create `com.resonanceenergy.council-sweep.plist` for scheduled intelligence
3. **Gap 7** (Easy): Create `AAC-v2/war-room/intelligence/` directory
4. **Gap 2** (Medium): Wire NCC dispatch to auto-launch execution_loop
5. **Gap 1** (Medium): Add Pushover or APNS notification on mandate pending
6. **Gap 3** (Medium): Add reverse relay for completion notifications
7. **Gap 4** (Hard): Automate Claude→Copilot via Computer Use or extension

---

*Generated by NCL Pipeline Simulation | 2026-04-06*
*Pipeline: First Strike → Strike Point → NCL → Council → Approval → NCC → Execution → Review → Feedback*
