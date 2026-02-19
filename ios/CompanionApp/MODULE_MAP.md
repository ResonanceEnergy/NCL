NCL iOS Companion — Module Map & TODOs

Purpose
- Complete module-level map for the Minimal iOS App (Option 2). Use this as the single-source blueprint for engineers, QA, and reviewers.

Top-level folders (inside ios/CompanionApp)
- Sources/CompanionApp/
  - PolicyKernel.swift         — authorization logic (single choke point)
  - ActionRouter.swift         — single execution entry; calls PolicyKernel
  - KillSwitchService.swift    — persistent hard-stop state
  - AuditLedger.swift          — append-only audit trail (local)
  - IncidentLedger.swift       — append-only incident store (local)
  - ProvenanceService.swift    — builds/validates provenance graphs
  - EventStore.swift           — SQLite + FTS index, sensitivity filters
  - ShortcutsHandler.swift     — Intents / App Group import plumbing
  - CouncilRunner.swift        — runs Planner/Skeptic/Risk agents
  - ConsentReceiptService.swift— local signed receipts for sensitive flows
  - TelemetryEmitter.swift     — counts/latency/availability only
  - EvaluationHarness.swift    — arena + golden tasks harness
  - SystemMode.swift           — NORMAL / SUGGEST_ONLY / LOCKDOWN
  - FeatureFlags.swift         — staged rollout support
  - BackgroundScheduler.swift  — micro-batching, charge/idle rules
  - UI files: ReviewQueueView.swift, CouncilView.swift, IncidentView.swift, SettingsView.swift
  - Tests/*                    — unit + integration tests for kernels, ledger, arena

Key invariants (enforced by modules)
- PolicyKernel is the only authorization engine. Every Execute must pass it.
- ActionRouter is the only path that can perform side effects.
- KillSwitch persists and cannot be auto-reenabled.
- Telemetry emits counts only; no raw payloads.
- neural_intent_signal remains hard-off by default.

Module responsibilities & TODOs (priority order)
1) PolicyKernel.swift — core enforcement (P0)
   - Responsibility: enforce tiers, kill switch, provenance, council gating, consent receipts.
   - TODOs:
     - [P0] Implement authorize(action, context) with Decision object
     - [P0] Unit tests for: deny-without-provenance, killswitch-block, risk-tier → council requirement
     - [P0] Integrate with CI gate (policy kernel tests)

2) ActionRouter.swift — single execution choke (P0)
   - Responsibility: centralize side-effects, call PolicyKernel, write AuditLedger/IncidentLedger
   - TODOs:
     - [P0] Implement execute(action) flow that calls PolicyKernel.authorize()
     - [P0] Add AuditLedger.append on allow/deny
     - [P0] Add unit/integration tests mocking PolicyKernel

3) KillSwitchService.swift (P0)
   - Responsibility: persistent kill state, UI toggle only for AZ PRIME identity
   - TODOs:
     - [P0] Implement persistent storage + status API
     - [P0] Ensure re-enable endpoint requires AZ PRIME auth
     - [P0] Add drill scripts and tests

4) AuditLedger & IncidentLedger (P0)
   - Responsibility: append-only evidence stores; linkable to provenance
   - TODOs:
     - [P0] Implement local encrypted append-only store (SQLite table + signature)
     - [P0] Provide export for forensics (local only)

5) EventStore + FTS Index (P0)
   - Responsibility: store events, respect sensitivity, offline search
   - TODOs:
     - [P0] Define schema v1 migration stubs
     - [P0] Implement FTS queries + latency budget
     - [P0] Add offline contract tests

6) ShortcutsHandler + Capture UX (P0)
   - Responsibility: capture fast paths (Shortcuts + widgets), write canonical event envelope
   - TODOs:
     - [P0] Implement Intent handler / App Groups receiver
     - [P0] Validate sample Shortcuts templates

7) EvaluationHarness (Arena + Golden Tasks) (P0)
   - Responsibility: run golden tasks locally/CI; score/rank candidate outputs
   - TODOs:
     - [P0] Implement Golden Task runner + baseline 50 tasks
     - [P0] Implement Arena scorer (utility, risk, accuracy)

8) CouncilRunner (P0/P1)
   - Responsibility: run 3 agents in parallel, produce deterministic transcript
   - TODOs:
     - [P1] Implement lightweight Planner/Skeptic/Risk agents (start with deterministic heuristics)
     - [P1] Transcript formatting + provenance links

9) ConsentReceiptService (P1)
   - Responsibility: local signed consent receipts for sensitive flows
   - TODOs:
     - [P1] Implement receipt object, signing with local secure key
     - [P1] UI for consent review & revoke

10) TelemetryEmitter & Observability (P0)
    - Responsibility: counts/latency/availability/error classes only
    - TODOs:
      - [P0] Implement emitter with schema validation
      - [P0] Add dashboard hooks for availability/error alerts

11) SystemMode & Auto‑Downgrade (P1)
    - Responsibility: SUGGEST_ONLY / NORMAL / LOCKDOWN transitions
    - TODOs:
      - [P1] Implement metrics monitor triggers
      - [P1] Auto‑downgrade behavior + AZ PRIME restore path

12) BackgroundScheduler (P1)
    - Responsibility: micro-batching, run heavy tasks on charge/idle
    - TODOs:
      - [P1] Implement scheduling policies (battery, network, user settings)

UI TODOs (early UX)
- ReviewQueueView: primary; must show provenance links and "undo" for last Execute
- CouncilView: compare outputs + show "why" + pick/export
- IncidentView: internal incident drill runner and export
- SettingsView: feature flag controls (AZ PRIME-only UI hidden by role)

Testing TODOs
- Unit tests for PolicyKernel and ActionRouter (P0)
- Golden Task CI integration (P0)
- Offline contract tests with network disabled (P0)
- Red-team regression harness (P1)

Integration checklist (pre-PR)
- All P0 unit tests pass
- Golden tasks run locally and in CI
- KillSwitch persisted state validated across restarts
- Offline contracts verified on at least two device classes

Notes
- Keep modules small and highly testable. PolicyKernel must be pure logic and have no network calls.
- Any new side-effecting path must call ActionRouter.execute() or it will be flagged in CI.

Suggested next steps
1. Implement PolicyKernel + ActionRouter skeleton (Sprint 1 tasks).
2. Add AuditLedger + KillSwitch (Sprint 2).
3. Deliver capture Shortcuts + basic Review UI (Sprint 3).


