# Active Mandates — NCL Doctrine Tracker

**Updated**: 2026-05-14
**Owner**: Strategy & Doctrine agent
**Authority**: NATRIX (absolute) → NCL (directive)

> **STATE RESET 2026-05-14** — Runtime had drifted to 22,388 phantom mandates
> (22,387 stuck `pending_approval`) due to an unbounded accumulation bug.
> On-disk state archived to
> `~/NCL/data/mandates.json.corrupt-22388-*.bak` and reset to the single
> remaining `active` mandate. The April 2026 mandate roster below was never
> reflected in runtime state — treat it as historical / aspirational until
> re-issued through the pump pipeline.

---

## Current Mandates (live runtime state)

| Mandate ID | Pillar | Priority | Title | Status | Notes |
|-----------|--------|----------|-------|--------|-------|
| d1ccd7ad-…-21f0d22 | — | — | "Directive: test pump endpoint fix" | active | Test artifact; review for completion/cancellation |

No production mandates currently active. Re-issue via pump → council → approve.

---

## Status Legend

- **draft** — Awaiting council deliberation
- **pending_approval** — Council complete, awaiting NATRIX approval gate
- **approved** — Approved, ready for NCC handoff
- **active** — NCC actively working
- **blocked** — Blocked by external dependency
- **completed** — Delivered + verified
- **cancelled** — Withdrawn or rejected
- **archived** — Historical record, no longer active

---

## Historical Roster (April 2026 — never executed)

These mandates were drafted in `shared/doctrine/` but never made it into
runtime brain state. Re-evaluate before reissuing.

| Mandate ID | Pillar | Priority | Title | Original Deadline |
|-----------|--------|----------|-------|-------------------|
| MANDATE-2026-001 | BRS | P1 | Launch Revenue Scanner — DIGITAL-LABOUR Automation | 2026-04-30 |
| MANDATE-2026-002 | BRS | P1 | Ship Crimson Compass (Spy Thriller Game) | 2026-06-30 |
| MANDATE-2026-003 | BRS | P2 | DUBFORGE: Dubstep Engine + Browser UI | 2026-05-31 |
| MANDATE-2026-004 | NCC | P1 | QUASAR IDE v0.1 — Electron Workspace Framework | 2026-05-15 |
| MANDATE-2026-005 | AAC | P1 | War Room Scenario Engine — Geopolitical Options Trading | 2026-06-01 |
| MANDATE-2026-006 | NCL | P2 | UNI Research Cortex — Auto-Research + Convergence Detection | 2026-07-01 |
| MANDATE-2026-007 | NCL | P2 | Awarebot-FPC: Intelligence Scanner + Predictor | 2026-07-15 |
| MANDATE-2026-008 | NCL/NCC | P1 | STRIKE-POINT: Full Pipeline — iPhone to NCL Brain Cortex | 2026-04-20 |

---

## Feedback Loop Status (live)

### NCC → NCL
Real exec reports landing in `feedback-synthesis/ncc-reports/`:
- `exec-report-CODING-TEST-001-20260506.json` (2026-05-06)

### Intelligence pipeline
Producer healthy — 146 briefs in `notifications/intelligence/` since 2026-05-06.
Consumer dormant: no signals or council reports being generated.

### Paperclip
Currently disconnected (port 3100 not listening). Brain reports
`paperclip_connected: false`. All cost / approval / activity logging is
no-op until restored.

---

## Notes

- **Update Frequency**: This file is reconciled against runtime state weekly,
  or after any state-reset event.
- **Approval Authority**: Only NATRIX can approve P1 mandates; NCL approves P2–P4.
- **Source of Truth**: `~/NCL/data/mandates.json` (runtime). This document is
  the human-readable projection.
