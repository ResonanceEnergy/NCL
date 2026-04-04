# Resonance Energy — Master Roadmap

**Updated**: 2026-04-03
**Owner**: NCL Strategy & Doctrine
**Authority**: NATRIX (absolute) → NCL (directive)

---

## Active Roadmaps by Mandate

### MANDATE-2026-008: STRIKE-POINT Pipeline (P1)
**Goal**: Make STRIKE-POINT the operational nervous system — zero-friction pipeline from iPhone to NCL brain cortex in under 5 seconds.

| Phase | Name | Deadline | Status | Key Milestones |
|-------|------|----------|--------|----------------|
| 1 | Make It Work | 2026-04-05 | **IN PROGRESS** | Relay → NCL file drop, /health endpoint, Tailscale on iPhone, E2E test |
| 2 | Make It Reliable | 2026-04-12 | Pending | launchd service, logging, retry logic, schema validation, alerts |
| 3 | Make It Fast + Polish | 2026-04-20 | Pending | Priority queue, delivery confirmation, Siri shortcut, web dashboard, docs |

**Phase 1 Progress** (as of 2026-04-03 22:00 UTC) — COMPLETE:
- [x] STRIKE-POINT repo created on GitHub
- [x] FirstStrike repo created on GitHub
- [x] Relay v2.0 with NCL file writer (atomic writes)
- [x] /health endpoint with system diagnostics
- [x] /status web dashboard
- [x] STRIKE-POINT CLAUDE.md context file
- [x] Mandate artifacts (pump, council, mandate JSON)
- [x] Tailscale connected — iPhone hitting relay
- [x] Port reconciliation: Relay :8787, NCL Brain :8800
- [x] Relay → NCL Brain API forwarding
- [x] Pump Watcher daemon (filesystem fallback)
- [x] launchd plists for all 3 services
- [x] Master install-services.command
- [x] E2E test suite

**Phase 2 Progress** (as of 2026-04-03 22:00 UTC) — IN PROGRESS:
- [x] launchd service plists (relay, brain, watcher)
- [x] install-services.command master installer
- [ ] Run installer on Mac Mini
- [ ] Run E2E test
- [ ] Verify council fires on pump receipt
- [ ] Retry logic in FirstStrike iOS app
- [ ] Alert on pump delivery failure

---

### MANDATE-2026-001: DIGITAL-LABOUR Revenue Scanner (P1)
**Deadline**: 2026-04-30
**Status**: Executing — 70% progress
**Next**: Alpha v0.1 by 2026-04-15

### MANDATE-2026-002: Ship Crimson Compass (P1)
**Deadline**: 2026-06-30
**Status**: Executing — blocked by asset optimization
**Next**: Vertical slice on itch.io

### MANDATE-2026-003: DUBFORGE Dubstep Engine (P2)
**Deadline**: 2026-05-31
**Status**: Queued — waiting for CC revenue earmark

### MANDATE-2026-004: QUASAR IDE v0.1 (P1)
**Deadline**: 2026-05-15
**Status**: Executing — UX milestone hit, performance optimization
**Next**: Beta launch 2026-05-01

### MANDATE-2026-005: AAC War Room (P1)
**Deadline**: 2026-06-01
**Status**: Executing — v0.2 deployed, 74% model accuracy
**Next**: Live trading by 2026-04-30

### MANDATE-2026-006: UNI Research Cortex (P2)
**Deadline**: 2026-07-01
**Status**: Queued

### MANDATE-2026-007: Awarebot-FPC Intelligence (P2)
**Deadline**: 2026-07-15
**Status**: Queued

---

## Priority Stack (Current Order)

1. **MANDATE-2026-008** — STRIKE-POINT Pipeline (infrastructure-critical, gates everything)
2. **MANDATE-2026-005** — AAC War Room (live capital deployment imminent)
3. **MANDATE-2026-001** — DIGITAL-LABOUR Revenue (first revenue stream)
4. **MANDATE-2026-004** — QUASAR IDE (developer tooling)
5. **MANDATE-2026-002** — Crimson Compass (game revenue)
6. **MANDATE-2026-003** — DUBFORGE (creative tool)
7. **MANDATE-2026-006** — UNI Research (long-horizon)
8. **MANDATE-2026-007** — Awarebot-FPC (intelligence, long-horizon)

---

## Strategic Notes

- STRIKE-POINT is the gating infrastructure. Until it works end-to-end, all other mandates depend on manual prompt delivery.
- AAC War Room approaching live trading — risk management review needed before capital deployment.
- DIGITAL-LABOUR is the first real revenue generator — critical for self-funding the ecosystem.
- QUASAR IDE supports all development work — invest here to accelerate everything else.
