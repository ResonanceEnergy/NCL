# NCL Intel Lane Mandate v1.0

**Effective**: 2026-05-28
**Operator**: NATRIX
**Authority**: NATRIX-tier (importance 95, procedural memory)
**Lane**: INTEL — show NATRIX what is happening outside his portfolio that he should know about today.
**Owns**: `data/intelligence/`, `data/rotation/`, `data/morning-brief-pro/`, `data/predictions/`

---

## 1. Identity

Intel is the **time-bounded outside-world feed**. It is NOT long-term memory (that's Memory lane), NOT portfolio state (that's Portfolio lane), and NOT calendar-anchored events (that's Calendar lane). Intel's job is to say: *"Today, here is what changed in the world that you and the agent should know."*

The lane is action-oriented and decays fast. Yesterday's Intel becomes today's Memory only if it earned promotion (Section 5).

## 2. Producers

| Producer | Cadence | Output |
|---|---|---|
| Awarebot | 5min per-source scan | Scored signals routed to focused/micro/macro tiers |
| Rotation tracker | Daily 17:00 ET | Sector RRG + breadth + leadership |
| Style ratios | Daily 17:00 ET | IWM/SPY, IWD/IWF, XLU/SPY, RSP/SPY, ARKK/SPY |
| Cycle phase | Daily 17:00 ET | early / mid / late / recession classification |
| Brief Pro | 02:30 prep → 05:00 council → 05:30 render | Synthesized morning brief with 12 DAILY CONTEXT blocks |
| IntelligenceEngine | On-demand | Forecast predictions with confidence + direction |
| YTC | Hourly + 3am nightshift | Per-video council reports + cross-video rollup |

## 3. Active sources (Awarebot)

| Source | Status | Rationale |
|---|---|---|
| reddit | LIVE | retail sentiment, breaking discussion |
| options_flow (Unusual Whales) | LIVE | institutional positioning |
| youtube (council + scraper) | LIVE | analyst views + macro commentary |
| polymarket | LIVE | event-conditional probability |
| google_trends | LIVE, **authority capped at 0.4** | popularity signal only, NOT editorial |
| news | **RETIRED Wave 14W** | was derivative fan-out from other sources; structurally inflated cross-source |
| x_twitter | DISABLED (402) | needs subscription renewal |
| crypto/coingecko | DISABLED | rate-limited; replaced by direct yfinance in CRYPTO brief block |
| city_events | **MOVED TO CALENDAR LANE Wave 14W** | community events are not intel |

## 4. Pre-gate rules (write-time)

Every Awarebot signal passes through these filters BEFORE it lands in any storage:

1. **Score ≥ 0.30** (LOW band dropped at ingest, not just demoted)
2. **HIGH band threshold: 0.65** (was 0.55 pre-14W; restored discrimination)
3. **CRITICAL band threshold: 0.75**
4. **Authority cap on popularity sources**: google_trends ≤ 0.4
5. **News-fan-out forbidden**: source must have its own watch queries, not re-broadcast another's
6. **City events forbidden in Intel**: route to Calendar lane (`data/calendar/city-*.json`)
7. **Dedup window**: 24h SimHash with fingerprint = source + title[:100] + content_summary (NOT raw content body, so daily-settlement Polymarket events stop double-counting)

A signal that fails any of these is dropped at ingest (not stored, not surfaced).

## 5. Promotion to Memory

The default is **no promotion**. Intel signals stay in the Intel lane (`agent_signals.jsonl` rotation + 3-deque in-memory). A signal earns promotion to Memory only when ONE OF:

- **CRITICAL** (composite ≥ 0.75)
- **Cross-source ≥ 2** (confirmed by independent producers)
- **Operator pin** via `POST /memory/working-context/pin`
- **Agent reasoning chain** references the signal as a citation in an open trade idea

This cuts MemoryStore growth ~10x and stops the 88%-awarebot-exhaust problem.

## 6. Consumer contracts

### 6.1 iOS Intel tab
- **RIGHT NOW** (digest) ← `GET /intelligence/digest` — single unified read, no fragmenting across 9 sub-tabs
- **AGENDA** (working context) ← `GET /memory/working-context` (lane border crossing; UI-only convenience)
- **BRIEF** ← `GET /intelligence/morning-brief/pro`
- **PREDICTIONS** ← `GET /predictions`
- **YTC** ← `GET /youtube/reports/recent`
- **ROTATION LIVE FEED** (only the streaming RRG update; the resident widget moves to Portfolio lane)
- **Drill-down sources** (Reddit / Polymarket / Trends) ← under Brief, not as peer tabs

### 6.2 Trading agent
- **Push (passive)**: `brief_context_packet` injected into the next morning brief prompt
- **Pull (active, NEW Wave 14W-E)**: `intel_request("awarebot.scan_now", focus=..., urgency=...)` returns a scoped fresh scan within the tick budget
- **Pull**: `intel_request("brief.regenerate_focus", focus_ticker=..., reason=...)` triggers an out-of-cycle brief rebuild

### 6.3 Morning brief (self-reads its own production)
- `brief_prep` consumes Intel cache directly via `brain._awarebot._recent_signals`
- After Wave 14W-C, brief_prep reads through `lane_router.recent_intel(lane='intel', max_age_h=12)` so it stops being a third-independent reader

## 7. Cadence

| Task | When |
|---|---|
| Awarebot per-source scan | 5min per source (rate-limited per RATE_LIMITS) |
| Brief Pro prep | 02:30 ET daily |
| Brief Pro council | 05:00 ET daily |
| Brief Pro render | 05:30 ET daily |
| Rotation snapshot | 17:00 ET daily |
| YTC dedicated | hourly during YouTube active hours |
| YTC nightshift rollup | 03:00 local time |
| Brief context packet refresh | on every brief fire |

## 8. Governance

| Action | Authority | Mechanism |
|---|---|---|
| Add/remove watch query | NATRIX | `POST /focus/queries` (moves to Settings→Watch Plan in Wave 14W-D) |
| Add/remove subreddit | NATRIX | `POST /focus/subreddits` |
| Tune scoring thresholds | NATRIX | env vars `NCL_AWAREBOT_*` |
| Fire brief manually | NATRIX | `POST /intelligence/morning-brief/pro/fire` |
| Fire rotation refresh | NATRIX or trading agent (Wave 14W-E) | `POST /intelligence/rotation/fire` |
| Disable a source | NATRIX | env var `<SOURCE>_SCANNER_ENABLED=false` |

## 9. Audit + Self-* obligations

The Intel lane IS:
- **Self-observing**: every scored signal carries score components, source confidence, novelty fingerprint
- **Self-learning**: SourceAuthorityLearner (Beta-Bernoulli) updates source authority weights from prediction outcomes (closes back via Wave 14K K4a)
- **Self-aging**: focused tier auto-decays past 4h; micro past 24h; macro past 7d
- **Self-deduping**: 24h fingerprint window stops re-ingesting the same item

The Intel lane IS NOT:
- A memory store (promotion to Memory is gated, not default)
- A decision-maker (the trading agent owns decisions; Intel just informs)
- An archive (use Memory for anything that needs retrieval beyond 7 days)

## 10. Coherent goal (one sentence)

> Show NATRIX (and the trading agent) what is happening outside his portfolio that he should know about today.

If something is older than 7 days, it belongs in Memory. If it is portfolio state, it belongs in Portfolio. If it is a time-anchored event, it belongs in Calendar. Intel is the present-tense outside-world feed.

## 11. Version + audit

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-05-28 | NATRIX + NCL Wave 14W-A | Initial Intel lane mandate codification |

Ingested as procedural memory at importance 95 (NATRIX tier) on every Brain boot.
