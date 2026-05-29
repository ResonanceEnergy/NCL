# BRIEF_MANDATE — Intel→Brief sub-tab

**Status**: Wave 14W-F mandate, 2026-05-29.

The Brief sub-tab is the **morning synthesized read** — NATRIX's flagship
feature ("full effort, full performance, focused effort so I can make
profitable trades"). It is the 05:30 ET rendered output of the Brief
Pro 3-stage pipeline (Night Watch prep → 4-LLM council → presenter).

## Goal

Decision-grade pre-market document. Built around a MARKET OPEN PLAN
pinned at the top, with 6 PRE_MARKET_TRADE_IDEAS (max 1 ETF) each citing
their source signals. This is what NATRIX trades against.

## What it should be

- MARKET OPEN PLAN at top — 4 sub-blocks:
  - WHAT TO WATCH (3-5 catalysts with reaction triggers)
  - DIRECTION INDICATORS (ES futures, VIX shape, breadth, SPY put/call)
  - MOMENTUM SIGNALS (gap-up watch, gap-down reversal, RVOL >3x, ORB)
  - RISK FLAGS (severity-tagged)
- EXECUTIVE SUMMARY (3-5 paragraphs)
- KEY MOVEMENTS section (overnight)
- EMERGING OPPORTUNITIES & RISKS (themes)
- PRE-MARKET TRADE IDEAS (max 6, ≤1 ETF per rule 7a, every idea cites
  `signal_id`s, every idea has entry/stop/target/R)
- POLYMARKET WATCH (active leading edges only — per P17-D)
- TODAY'S RESEARCH TOPICS (open self_research clusters)
- ROTATION REGIME sub-block (cycle phase + leading/weakening sectors +
  breadth %)

## What it should NOT be

- Not Agenda — Agenda is the condensed 1-screen read
- Not a scanner dump — every paragraph must trace to signal_ids
- Not "yesterday's brief by default" — Past lives behind a sub-mode
- Not the council debate transcript — Council briefs sit behind their
  own sub-mode
- Not "today's news" — News source retired Wave 14W backend-side

## Decision it enables

Pre-market trading. Should NATRIX take any of the 6 PRE_MARKET_TRADE_IDEAS
with the supplied entry/stop/target/R, and what's the regime context?

## Good state

- `critic_score ≥ 90`
- `regenerated_count == 0`
- `trade_ideas_emitted ≥ 4`
- Every trade idea has SOURCES line citing signal_ids
- Zero markdown leaks (no `**`, no leading `#`, no backticks)
- ROTATION REGIME block populated
- Polymarket events tagged with lifecycle (no stale resolved events
  framed as forward catalysts)

## Bad state

- `trade_ideas_emitted == 0` (planner went short-mode on a normal market day)
- ETF-dominated ideas (rule 7a violation: >1 ETF ticker)
- Stale Polymarket-resolved events cited as forward catalysts
- "Signals quiet" stub paragraphs (Wave 14C A3 retired these)
- Pre-2026 dates framed as forward catalysts (rule 7b)
- Hallucinated ticker prices (rule 7e — outside 52w range ± 2%)

## Header subtitle (canonical)

> "Morning synthesized read — market open plan, executive summary,
> and pre-market trade ideas with citations."

## Backend contract

`GET /intelligence/morning-brief` returns the full pro brief JSON +
rendered text. `POST /intelligence/morning-brief/fire` triggers end-to-end.

Pipeline meta surfaces:
- `pipeline_meta.plan_mode` — short / full / no-edge
- `pipeline_meta.trade_idea_target` — required min (Wave 14D iter)
- `pipeline_meta.trade_ideas_emitted` — actual count
- `pipeline_meta.critic_score` — 0-100
- `pipeline_meta.regenerated` — bool
- `pipeline_meta.critic_reasons` — list of fixable issues

## Producer constraints (lift load-bearing rules from existing docs)

- **Rule 7a** — ETF quota: ≥1 ETF in trade ideas fails the critic
- **Rule 7b** — Date recency: no pre-2026 dates framed as forward
- **Rule 7c** — Polymarket lifecycle: prefer `active+leading` over `resolved`
- **Rule 7d** — Rotation-aligned: trade ideas should lean WITH Leading-quadrant sectors
- **Rule 7e** — Price sanity: claimed ticker prices must be in 52w range ± 2%
- **Planner mode bias** — `mode=full` for any normal market day with
  ≥2 sources + ≥30 signals (Wave 14G P17-C)
- **trade_idea_count_target** — ≥4 when `PRE_MARKET_TRADE_IDEAS` is in
  `include_sections` (Wave 14D iter)
