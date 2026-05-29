# FOCUS_MANDATE — Intel→Focus sub-tab

**Status**: Wave 14W-F mandate, 2026-05-29.

The Focus sub-tab is the **scored, time-windowed scanner surface** —
three modes over the same Awarebot pool partitioned by age and confidence.

## Goal

Operator drill-down. When Agenda flags something, Focus is where NATRIX
scrolls at higher detail and pins items to working context. The
scrollable counterpart to Agenda's single-screen read.

## What it should be

Three modes over the same Awarebot pool:

- **FOCUS** — last 4h with composite score ≥ 0.75 ("act now")
- **MICRO** — last 24h velocity, optionally grouped by sector / ticker /
  flat to surface narrative convergence (multi-source first)
- **MACRO** — persistent narratives (>24h) and high cross-source items

Each mode renders rich `IntelSignalCard` rows with:
- Score, sectors, tickers, source
- PIN-to-working-context chip
- COUNCIL-this chip
- PAPER-TRADE chip
- DETAIL → sheet

A gear icon opens `FocusContextView` for editing watch queries +
subreddit tiers (also reachable from Settings→Watch Plan in Wave 14W-D).

## What it should NOT be

- Not Agenda's condensed read — Focus is for browsing and drill-down
- Not a re-sorted projection of what Agenda shows — must be additive
- Not the watch-query editor itself — that's the gear sheet
- Must not be "the configuration tab" — visible content is intel, not config

## Decision it enables

Confirm a signal cluster (e.g., 4 XLE-sector cards all surfacing
together), then pin to Memory or fire a research card to bring the
auto-trader's attention onto it.

## Good state

- FOCUS mode shows 3-10 cards with cross-source ≥ 2 highlighted
- MICRO has 2-3 sector clusters with 3-4 cards each
- MACRO shows persistent narratives spanning multiple days
- Pinning fires and the card immediately updates its pin state on re-render
- Pin chip count badge stays in sync with `/memory/working-context`

## Bad state

- FOCUS empty for hours (scanner stalled)
- MICRO monoculture — one source (e.g. `awarebot:city_events`)
  dominating after the Wave 14B per-source diversity cap regressed
- Pinning fires but the card never updates the pin state
- No clear difference between the three modes — defeats the picker
- Gear icon hidden when both Settings→Watch Plan AND gear should be entry points

## Header subtitle (canonical)

> "Scored signal stream — three time windows (act-now, today,
> persistent). Tap the gear to edit watch queries."

## Backend contract

- `GET /context/focused` — top 10 active-now signals
- `GET /context/micro` — last 24h scored signals (optionally
  grouped by `?group_by=sector|ticker|flat`)
- `GET /context/macro` — persistent / cross-source ≥ 2 signals
- `GET /focus/queries` — watch queries per source
- `GET /focus/subreddits` — subreddit tiers
- `POST /memory/working-context/pin` `{item_id}` — pin
- `DELETE /memory/working-context/pin?item_id=...` — unpin

## Producer constraints

- Awarebot ticks every 30 min (X/scanners) — Focus must refresh on
  pull-to-refresh
- Cross-source ≥ 2 items surface first within each mode
- HIGH threshold = 0.65 (raised from 0.55 in Wave 14W-B for discrimination)
- Per-source diversity cap = 5 per tier (Wave 14B) so no single source
  monopolizes any mode
- Pin operations are optimistic with rollback on 4xx
