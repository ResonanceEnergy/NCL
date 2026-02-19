# GitHub Issues — NCL‑First (90‑day P0/P1 tickets)

Copy/paste the markdown below into GitHub Issues. Each block is a ready‑to‑paste issue body with labels and sprint tags.

---

## T1.1.1 Define Event Schema v1 + Provenance Envelope
**Labels:** P0, epic:E1, sprint:1
**Assignee:** Principal Architect, Privacy Engineer

**Description:** Create a versioned canonical event envelope (ncl.iphone.v1) including provenance links, sensitivity, confidence, and versioning rules.

**Acceptance Criteria:**
- Event envelope includes: id, timestamp, source, confidence, sensitivity, provenance_links[]
- Supports payload references (photo_ref, audio_label_ref)
- Schema versioning and migration rules documented

**Definition of Done:** schema file added to `schemas/ncl.iphone.v1/envelope.json`, unit tests, and migration stub.

---

## T1.1.2 On‑Device Indexing/Search v1
**Labels:** P0, epic:E1, sprint:1
**Assignee:** Backend/Systems, iOS Platform

**Description:** Implement local SQLite storage with FTS index for events; support time/source/sensitivity filters and offline search.

**Acceptance Criteria:**
- Full-text search across event text fields
- Filter by time, source, sensitivity
- Latency targets defined and met on 2 device classes

**DoD:** EventStore implementation + benchmark script + CI gating

---

## T1.2.1 Shortcuts Pack v1 (Capture + Quick Actions)
**Labels:** P0, epic:E1, sprint:1
**Assignee:** iOS Product Eng, Automation Eng

**Description:** Deliver a Shortcuts pack (templates + JSON payloads) enabling capture flows (text, photo-ref, voice-label, quick tag) that write canonical event envelopes.

**Acceptance Criteria:**
- 10 shortcuts covering core capture flows
- Works offline and writes valid event envelopes to App Group / Files
- Sample dataset and walkthrough included

**DoD:** Shortcuts templates in `shortcuts_pack/v1/templates/` + README updates

---

## T3.1.1 Privacy‑Safe Telemetry Spec v1
**Labels:** P0, epic:E3, sprint:2
**Assignee:** Privacy Eng, Observability Eng

**Description:** Define telemetry schema and redaction rules: only counts, latency, availability, error classes allowed.

**Acceptance Criteria:**
- Telemetry schema file added and enforced in CI lint
- UI toggle exists and defaults to privacy-safe

**DoD:** Spec + CI telemetry lint rule + tests

---

## T3.2.1 Assistant Availability Tracker
**Labels:** P0, epic:E3, sprint:2
**Assignee:** Observability Eng, iOS Platform Eng

**Description:** Implement availability metrics for capture/search/review and offline success rate logging.

**Acceptance Criteria:**
- Dashboard shows availability per workflow
- Alerts for availability regression defined

**DoD:** Implementation + dashboard + alerting rules

---

## T4.1.1 Action Permission Model v1 (Suggest/Draft/Execute)
**Labels:** P0, epic:E4, sprint:2
**Assignee:** Security Lead, Principal Architect

**Description:** Implement a permission model classifying actions as Suggest, Draft, or Execute.

**Acceptance Criteria:**
- Action objects declare tier
- Execute requires explicit consent
- Enforcement in PolicyKernel with unit tests

**DoD:** PolicyKernel checks + tests + UI confirm flows

---

## T6.1.1 Golden Task Suite v1 (50 tasks)
**Labels:** P0, epic:E6, sprint:2
**Assignee:** Evaluation Eng, UX Research

**Description:** Create 50 deterministic "golden tasks" covering capture, summarize, plan, recall.

**Acceptance Criteria:**
- Each task has input, expected output, and failure conditions
- Runs in CI and blocks merge on regression

**DoD:** Golden tasks + CI integration

---

## T2.1.1 Review Queue UI v1 (Inbox triage)
**Labels:** P0, epic:E2, sprint:3
**Assignee:** Product Designer, iOS Product Eng

**Description:** Implement the primary Review Queue UI where users triage captured events and accept/dismiss suggestions.

**Acceptance Criteria:**
- Inbox list, batch tag, batch link, archive
- "Next action" suggestions are non-executing
- Usability tested with 5 scenarios

**DoD:** UI component + usability report

---

## T5.1.1 Council Runner v1 (Planner/Skeptic/Risk)
**Labels:** P0, epic:E5, sprint:4
**Assignee:** AI Lead, Automation Eng

**Description:** Implement a deterministic Council runner that executes 3 agents in parallel and stores a transcript.

**Acceptance Criteria:**
- Planner, Skeptic, Risk agents run in parallel
- Consensus + dissent notes stored as provenance
- Deterministic replay supported

**DoD:** CouncilRunner + transcript storage + tests

---

## T11.0.1 Emergency Stop (Kill Switch) for Execute Tier
**Labels:** P0, epic:E11, sprint:2
**Assignee:** Security Lead, iOS Platform Lead

**Description:** Implement a global Kill Switch that immediately disables all Execute-tier actions and persists until AZ PRIME re-enables.

**Acceptance Criteria:**
- One-tap STOP disables Execute actions
- STOP persists across restarts
- STOP logged in AuditLedger

**DoD:** KillSwitch implementation + drill + tests

---

(Additional P1 tickets and the full 90-day backlog can be pasted from the doctrine file if you want the rest.)
