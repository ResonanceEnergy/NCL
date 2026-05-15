# NCL ROADMAP

**Last updated**: 2026-05-14
**Owner**: NATRIX
**Status**: Active development

---

## Current State (v1.0)

NCL is operational as the brain cortex of Resonance Energy. Core subsystems running on Mac Mini M4 Pro, port 8800:

- **Council Engine**: 6-member multi-LLM debate (Claude chair + Grok, Gemini, Perplexity, GPT, Copilot). Ollama fallback for unconfigured keys.
- **Agent Swarm**: 17-file multi-agent system with orchestrator, 7 specialist agents, LLM router, blackboard, cost gate, task graph.
- **Memory Store**: JSONL-based persistence with decay, reinforcement, consolidation. ChromaDB vector search available when installed.
- **Intelligence Engine**: Signal collection from X, Reddit, YouTube, news APIs. Automated briefing pipeline.
- **Autonomous Scheduler**: Background loops for council triggers, intelligence sweeps, memory consolidation.
- **API**: ~140 FastAPI endpoints with rate limiting (slowapi), CORS, versioned gateway (/v1).
- **Governance**: Policy kernel, action router, emergency stop, consent tracking.
- **Telemetry**: Collector + availability tracker for uptime monitoring.
- **Strike-Point Pipeline**: iOS shortcut integration for pump prompts from iPhone.

---

## Phase 1 — Hardening (In Progress)

Priority: Make what exists production-grade.

- [x] Fix .gitignore — track all swarm source files
- [x] Fix research_cortex wiring in brain.__init__
- [x] Add rate limiting (slowapi) to all endpoints
- [x] Add API versioning (/v1 prefix)
- [x] Add vector DB (ChromaDB) for semantic memory search
- [x] Write swarm tests (101 tests)
- [x] Write intelligence engine tests (48 tests)
- [x] Write UNI cortex tests (28 tests)
- [x] Add council API key availability logging
- [x] Close INCIDENT_LOG follow-ups
- [x] Create this ROADMAP
- [ ] Add integration tests (full pipeline pump → council → mandate)
- [ ] Add CI/CD pipeline (GitHub Actions)
- [ ] Add structured error codes for all API responses
- [ ] Health check dashboard with Grafana/Prometheus metrics

## Phase 2 — Scale & Performance

Priority: Handle 10x current load without degradation.

- [ ] Replace JSONL memory with SQLite or PostgreSQL for units > 10K
- [ ] Add Redis caching layer for hot memory queries
- [ ] Implement connection pooling for LLM API clients
- [ ] Add request queuing for council sessions (prevent thundering herd)
- [ ] Benchmark and optimize council round-trip time (target: < 30s for 3-round debate)
- [ ] Add WebSocket support for real-time council streaming
- [ ] Implement sharded blackboard for concurrent swarm tasks

## Phase 3 — Intelligence Expansion

Priority: Make NCL the best-informed brain possible.

- [ ] Add SEC EDGAR filing scanner (10-K, 10-Q, 8-K)
- [ ] Add patent filing monitor (USPTO, EPO)
- [ ] Add academic paper scanner (arXiv, SSRN)
- [ ] Build cross-source correlation engine (detect same signal across 3+ sources)
- [ ] Add prediction market integration (Polymarket, Kalshi) for calibration
- [ ] Build intelligence confidence scoring with historical accuracy tracking
- [ ] Add geopolitical risk monitor (ACLED, GDELT)

## Phase 4 — Autonomy

Priority: Reduce NATRIX intervention to strategic decisions only.

- [ ] Auto-spawn councils when intelligence signals exceed threshold
- [ ] Auto-dispatch mandates to NCC/BRS/AAC based on council consensus > 85%
- [ ] Build self-healing: detect failed mandates, auto-retry with adjusted parameters
- [ ] Add autonomous budget allocation across LLM providers (cost vs. quality optimization)
- [ ] Implement learning loop: council accuracy feedback improves future prompt engineering
- [ ] Build autonomous weekly strategy reports with trend analysis

## Phase 5 — Multi-Brain Federation

Priority: NCL coordinates with other Resonance Energy brains.

- [ ] Define inter-brain protocol (brain-to-brain mandate passing)
- [ ] Build BRS brain cortex (economic intelligence)
- [ ] Build AAC brain cortex (capital allocation intelligence)
- [ ] Implement consensus across brains for enterprise-level decisions
- [ ] Add brain health monitoring and automatic failover

---

## Non-Goals

These are explicitly out of scope for NCL:

- **Code execution**: NCL thinks and decides; NCC executes code
- **Financial transactions**: NCL advises; AAC manages capital
- **UI/frontend**: NCL exposes APIs; dashboards are separate concerns
- **User authentication**: NCL trusts its API gateway for auth

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-14 | ChromaDB for vector search | Lightweight, embedded, no server needed. Fallback to keyword search if not installed. |
| 2026-05-14 | slowapi for rate limiting | FastAPI-native, simple, sufficient for single-server deployment. |
| 2026-05-14 | Versioned gateway (mount under /v1) | Zero-change migration for existing clients. All routes work at root AND /v1/. |
| 2026-05-14 | Council Ollama fallback | Graceful degradation > hard failure. Log warnings so NATRIX knows to configure keys. |
