# AGENDA_MANDATE — Intel→Agenda sub-tab

**Status**: Wave 14W-F mandate, 2026-05-29.

The Agenda sub-tab is the single place that answers **"what needs my
attention in the next hour."** It is the morning-of, the half-asleep
06:00 read.

## Goal

Collapse the 11 Intel sub-tabs + the working-context pool into one
glance-able read. Give NATRIX (and the auto-trader) the same canonical
answer to "what's first." Cut the cost of opening Intel from
"horizontally scroll 11 chips + 4 fetches" to "one tap, one fetch, one
ranked list."

## What it should be

- One short headline (the day's `RIGHT NOW` line from `/intelligence/digest`)
- Top of working context (pinned items + top-N unpinned by salience)
- ≤5 KEY SIGNALS deduped against working context, every one with a source
- ≤5 RISK items (only those that crossed CRITICAL)
- Pulled from a single backend read (`GET /intelligence/digest`)

## What it should NOT be

- It is not Brief — Brief is the long-form 05:30 ET synthesis
- It is not Focus — Focus is the scrollable scanner pool
- It is not a fourth projection of raw scanner output — dedup against WC
- It must never look like a copy of Focus's FOCUS mode

## Decision it enables

"Where should I point my attention next?" — open Brief, drill into Focus,
fire a chat, or close the app and trust the auto-trader.

## Good state

- Headline present, 3-5 KEY SIGNALS each with one source
- 1-3 RISK items
- FROM CONTEXT non-empty (working context loaded)
- No duplication between KEY SIGNALS and FROM CONTEXT

## Bad state

- Empty digest with stale WC strip (current empty-state copy)
- Duplicated rows that already appear in Focus (no dedup)
- Stale WC items from yesterday still showing in FROM CONTEXT
- Headline pulled from a brief older than 4 hours

## Header subtitle (canonical)

> "What to attend to in the next hour — working-context items, top
> signals, and risk."

## Backend contract

`GET /intelligence/digest` returns:
- `headline: str` — one-line summary
- `key_signals: list[{title, source, score}]` — top 5
- `risk_alerts: list[{title, text}]` — critical only
- `working_context_top: list[WCItem]` — pinned + top-N unpinned
- `night_watch_status: str` — RED/YELLOW/GREEN
- `source_breakdown: dict` — per-source signal count

## Producer constraints

- Backend MUST dedup `key_signals` against `working_context_top` (token
  Jaccard ≥ 0.6) so the same datum doesn't appear twice
- Backend MUST filter `key_signals` to authority tier ≥ SCANNER (per
  Wave 14A `NCL_BRIEF_MIN_AUTHORITY` env knob)
- iOS MUST cap each section at 5 items even if the response carries more
