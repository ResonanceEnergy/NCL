# BRIEF MANDATE — 5-Lane Daily Brief

**Authority**: NATRIX (absolute)
**Codified**: 2026-05-29 (Wave 14Y) — supersedes Wave 14W-F single-format mandate
**Status**: LAW. Every NCL brief follows this structure. No exceptions.

---

## The Mandate

Every NCL brief is an **accumulation of all five iOS tabs**, summarized **twice a day**, organized in this **fixed order**:

```
1. PORTFOLIO     paper account, auto-trader activity, scanner picks, rotation
2. INTEL         YTC, Reddit, X (paused), Predictions, Polymarket, cross-ref
3. CALENDAR      today's events, lunar phase, market events, watchlist to-dos
4. JOURNAL       morning quiz, today's focus, yesterday's lesson, posture
5. MEMORY        pinned working-context items, top-salience, active themes
```

**No section may be reordered, merged, renamed, or omitted.** If a lane has no data, render the section with the lane's narrative set to "Lane quiet today" (or similar honest one-liner) and structured fields as `[]` — but the section still appears.

---

## Why this format

NATRIX's diagnosis (2026-05-29):

> "the morning brief got really weak and lost its format... its supposed to be an accumulation of all tabs summerized twice a day, centered around 1. Portfolio 2. Intel 3. Calendar 4 Journal 5. memory"

The prior Brief Pro format (Yesterday's Recap / Market Open Plan / Trade Ideas / Executive Summary / Rotation Regime / Research Topics) was portfolio-leaning. Calendar / Journal / Memory weren't first-class sections. The brief was a market-commentary product, not a personal-AI synthesis.

The 5-lane format **mirrors the iOS bottom-tab structure** exactly. Every brief is "what's in your 5 tabs right now, told as a daily story."

---

## Cadence

| Anchor       | Time      | Endpoint                                       |
|--------------|-----------|------------------------------------------------|
| AM Brief     | 05:30 ET  | `POST /intelligence/morning-brief/pro/fire`    |
| PM Debrief   | 16:30 ET  | `POST /intelligence/afternoon-debrief/fire`    |

Both fire from `ncl-brief-render` + `ncl-afternoon-debrief` scheduled loops. The Afternoon Debrief mirrors the AM Brief structure exactly — same 5 lanes, same order — but the narrative shifts from forward-looking ("what to watch") to retrospective ("what happened, what to carry into tomorrow").

---

## Per-lane spec

### 1. PORTFOLIO

| Field                       | Type            | What it contains                              |
|-----------------------------|-----------------|-----------------------------------------------|
| `narrative`                 | string          | 2-3 sentence synthesis with id= citations    |
| `yesterday_recap`           | dict            | headline, scoreboard, lesson, drift_flags     |
| `paper_state`               | dict            | balance_usd, open_positions, today_closes, today_realized_r |
| `trade_ideas`               | list of dict    | type, ticker, thesis, entry, stop, target, timeframe, sources |
| `rotation_regime`           | dict            | current_phase, leading_sectors, weakening_sectors, breadth_pct, one_liner |
| `risk_flags`                | list of dict    | text, severity (low/med/high)                 |

**Producer constraints carried forward from Wave 14W-F:**
- **Rule 7a** ETF quota — ≥1 ETF in trade ideas fails the critic
- **Rule 7b** Date recency — no pre-2026 dates framed as forward catalysts
- **Rule 7d** Rotation alignment — trade ideas lean WITH Leading-quadrant sectors (or labeled counter-trend with justification)
- **Rule 7e** Price sanity — claimed ticker prices must be in 52w range ± 2%
- Every trade idea must have entry/stop/target/sources
- `trade_idea_count_target` ≥ 4 when generating ideas

### 2. INTEL

| Field                          | Type            | What it contains                          |
|--------------------------------|-----------------|-------------------------------------------|
| `narrative`                    | string          | 2-3 sentence synthesis                    |
| `top_signals`                  | list of dict    | text, source (ytc/reddit/x/predictions/polymarket/news), sig_id |
| `predictions_watch`            | list of dict    | text, direction, confidence_pct, citations |
| `polymarket_watch`             | list of dict    | text, citations                           |
| `cross_reference_promotions`   | list of dict    | text, tickers (from Cross-Reference Engine convergence rules) |

**Source priority** (per AWAREBOT_MANDATE):
1. YTC (council-grade)
2. Reddit
3. X (paused for credits)
4. Markets + Polymarket (merged ambient context)
5. News, Trends (verifier-only)

**Rule 7c** — Polymarket lifecycle: prefer `active+leading` over `resolved`.

### 3. CALENDAR

| Field                          | Type            | What it contains                          |
|--------------------------------|-----------------|-------------------------------------------|
| `narrative`                    | string          | 2-3 sentence synthesis                    |
| `today_events`                 | list of dict    | text, time_et, category (macro/earnings/geopolitical/lunar/market_event) |
| `lunar_phase`                  | dict            | phase, energy, one_liner                  |
| `tickers_with_event_today`     | list            | tickers that have a calendar event today  |
| `next_7_days_to_watch`         | list of dict    | date, text                                |

### 4. JOURNAL

| Field                          | Type            | What it contains                          |
|--------------------------------|-----------------|-------------------------------------------|
| `narrative`                    | string          | 2-3 sentence synthesis                    |
| `today_focus_from_quiz`        | string          | Q2 of morning quiz — today's #1 thing     |
| `yesterday_quiz_posture`       | dict            | mood, risk_appetite, priority             |
| `yesterday_lesson`             | string          | Carried-forward lesson                    |
| `tickers_in_journal_today`     | list            | Tickers NATRIX mentioned in today's quiz  |

**If today's quiz not yet submitted**: `today_focus_from_quiz` is null and narrative says so. Don't fabricate.

### 5. MEMORY

| Field                          | Type            | What it contains                          |
|--------------------------------|-----------------|-------------------------------------------|
| `narrative`                    | string          | 2-3 sentence synthesis                    |
| `pinned_priorities`            | list of dict    | text, importance (NATRIX's pinned items)  |
| `top_salience_items`           | list of dict    | text, tier, salience                      |
| `active_themes`                | list of dict    | text, why_relevant_today                  |

---

## Pipeline

```
                                ┌────────────────────────┐
                                │  brief_prep            │
                                │  build_prep_pack()     │
                                │  _build_5_lanes()      │
                                └───────────┬────────────┘
                                            │
                                            v
                                ┌────────────────────────┐
                                │  brief_council         │
                                │  4 members + chair     │
                                │  Claude → Grok → GPT   │
                                │     → Gemini fallback  │
                                │  emits 5-key JSON      │
                                └───────────┬────────────┘
                                            │
                                            v
                                ┌────────────────────────┐
                                │  brief_presenter       │
                                │  render_pro_brief()    │
                                │  5 fixed sections      │
                                │  envelope.lanes = {…}  │
                                └───────────┬────────────┘
                                            │
                                            v
                                ┌────────────────────────┐
                                │  iOS BriefLandingCard  │
                                │  5 drillable tiles     │
                                │  Dashboard top         │
                                └────────────────────────┘
```

**File contracts:**
- `data/morning-brief-prep/YYYY-MM-DD.json` → has top-level `lanes: {portfolio, intel, calendar, journal, memory}`
- `data/morning-brief-council/YYYY-MM-DD.json` → chair emits the 5-key synthesis
- `data/morning-brief-pro/YYYY-MM-DD.json` → envelope with `full_brief` (text) + `lanes` (dict)

**iOS contracts:**
- `BriefLandingCard.TileKind` enum has exactly 5 cases — `portfolio`, `intel`, `calendar`, `journal`, `memory`
- `tile.laneKey` maps to the JSON key in `envelope.lanes`
- `BriefSectionDetailSheet` reads `synthesis["lanes"][tile.laneKey]` then renders narrative + lane-specific structured content

---

## Anti-patterns (do not violate)

1. **Do not change the order.** PORTFOLIO is always 1/5. MEMORY is always 5/5.
2. **Do not merge sections.** If JOURNAL is quiet and MEMORY is quiet, render both empty sections — don't combine.
3. **Do not add a sixth section.** If something doesn't fit, it belongs in one of the 5 lanes' structured fields.
4. **Do not fabricate.** If a lane has no data, the narrative says so. Empty arrays render as empty — the section header still appears with a "Lane quiet today" note.
5. **Do not regress to the old format.** The legacy `POST /intelligence/morning-brief` endpoint (TOPIC/WHY/INVESTIGATE stubs) is deprecated. The "Morning Brief" Quick Action on iOS Dashboard has been retired. Only the BriefLandingCard with 5 tiles is the user-facing path.
6. **Do not change the council member roster** without updating the chair prompt's `members_succeeded` list. Current roster: Macro Analyst (Claude Opus 4) · Pulse (Grok-4) · Flow Detective (Gemini 2.5 Flash) · Technical Tactician (GPT-4o) · Chair (Claude Opus 4).

---

## How to read this brief

Every brief begins with a header:

```
NCL DAILY BRIEF — YYYY-MM-DD
Generated: ISO timestamp
PORTFOLIO · INTEL · CALENDAR · JOURNAL · MEMORY
```

Then 5 sections, each delimited by `═══` block characters and numbered `1 / 5` through `5 / 5`. Each section opens with the chair's narrative paragraph, followed by lane-specific structured fields rendered with `──` sub-headers.

On iOS, the BriefLandingCard at the top of the Dashboard shows the AM/PM picker plus 5 tappable tiles. Each tile shows the lane's narrative (first sentence) as a preview. Tapping a tile opens a sheet with the full lane content.

---

## Decision the brief enables

The AM Brief is read between 05:30 and market open (09:30 ET). It tells NATRIX:
- **PORTFOLIO**: where the paper account stands, what the auto-trader closed yesterday + plans today
- **INTEL**: what the signal pool is saying — what to pay attention to today
- **CALENDAR**: what time-bound catalysts (events, earnings, lunar) shape today
- **JOURNAL**: NATRIX's own posture entering the day — focus, mood, lessons
- **MEMORY**: what background context (pinned, themes) shapes today's decisions

The PM Debrief at 16:30 ET tells the inverse story — what happened today across the same 5 lanes, what carries forward to tomorrow.

Together, the two daily anchors form a closed loop: posture-in (AM) → market action → results + lesson-out (PM) → carry into next AM.

---

## Related mandates

- `AWAREBOT_MANDATE.md` — what feeds the INTEL lane (Wave 14X-Y Phase 5)
- `AUTO_TRADER_MANDATE.md` (TRADERAGENT) — what feeds the PORTFOLIO lane
- `CROSS_REFERENCE_MANDATE.md` — what populates `cross_reference_promotions` in INTEL
- `LANE_ARCHITECTURE.md` — the broader 5-lane structure that the iOS tabs follow (this brief mirrors it)
- `CALENDAR_MANDATE.md` / `JOURNAL_MANDATE.md` / `MEMORY_MANDATE.md` — per-lane source-of-truth specifications

---

## Wave history

- **Wave 14W-F** (2026-05-29 morning) — first BRIEF_MANDATE.md, single-format (MARKET_OPEN_PLAN-led)
- **Wave 14X** (2026-05-29 mid-day) — Brief Pro 3-stage pipeline live, Yesterday's Recap binding, situational context
- **Wave 14Y** (2026-05-29 afternoon) — **5-lane restructure**. This document. NATRIX called the regression: "got really weak and lost its format". Backend brief_prep / brief_council / brief_presenter all rewritten to emit PORTFOLIO/INTEL/CALENDAR/JOURNAL/MEMORY in fixed order. iOS BriefLandingCard tiles reduced from 6 to 5. Legacy Quick Action retired.
