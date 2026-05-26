# Morning Brief Pro — Architecture (Wave 14H, 2026-05-26)

**Trigger**: NATRIX — "I want the nightwatch agent to prep morning brief and send it to council to do the research and presentation brief. Include a detailed plan for market open and what to watch for and indicators for movement direction and momentum. The morning brief is one of flagships of app so I want full effort and full performance and focused effort so I can make the most informed decisions and make profitable trades."

## Three-stage flow

```
┌──────────────────────────────┐    ┌──────────────────────────────┐    ┌──────────────────────────────┐
│   NightWatch PREP (02:30 ET)  │ →  │    COUNCIL RESEARCH (05:00)  │ →  │    PRESENTATION (05:30)      │
│  collect overnight market    │    │  multi-LLM panel, 4 domains  │    │  NATRIX-format brief +       │
│  data into context pack      │    │  each emits section findings │    │  Market Open Plan section    │
└──────────────────────────────┘    └──────────────────────────────┘    └──────────────────────────────┘
```

## Stage 1 — NightWatch Prep (02:30 ET, ~5 min)

**Module**: `runtime/intelligence/brief_prep.py`
**Output**: `data/morning-brief-prep/YYYY-MM-DD.json`

Collects + structures everything the Council needs:

| Block | Source | Detail |
|---|---|---|
| `futures` | yfinance | ES=F, NQ=F, RTY=F, YM=F overnight quotes + % change |
| `overnight_movers` | yfinance pre-market | top 20 gainers + 20 losers vs prior close |
| `headlines` | Awarebot RSS feed last 12h | dedup, source-tagged, top 25 by importance |
| `options_flow_yesterday` | data/scanners/goat-{yesterday}.jsonl + flow ledger | dollar flow summary by ticker |
| `economic_calendar` | Finnhub or fallback | today's releases with consensus + prior |
| `earnings_today` | get_earnings_map | tickers reporting before/after open |
| `geopolitical` | Awarebot + Polymarket active leading | top 5 active market-moving events |
| `vix_term_structure` | yfinance ^VIX, ^VIX9D, ^VIX3M | curve shape (backwardation/contango) |
| `working_context` | brain.working_context.assemble() | NATRIX's pinned priorities + research questions |
| `held_positions` | portfolio_mgr.get_positions() | current book for tactical context |
| `night_watch_summary` | last `data/night-watch/daily-*.md` | overnight system observations |

## Stage 2 — Council Research (05:00 ET, ~3 min)

**Module**: `runtime/intelligence/brief_council.py`
**Pattern**: Delphi-MAD style — 4 LLM members + 1 chair

Each member receives the FULL prep pack but is assigned ONE domain to write up. Member output is JSON: section + key claims + signal citations + confidence.

| Member | Model | Domain | Output |
|---|---|---|---|
| **Macro Analyst** | Claude Sonnet 4 | macro + cross-asset + futures + VIX | Direction read on indexes, rates, FX, commodities |
| **Real-Time Pulse** | Grok 4 | X/news sentiment + breaking events + Polymarket | What changed overnight, geopolitical risk, narrative shifts |
| **Flow Detective** | Gemini 2.5 Pro | options flow + dark pool + GEX + unusual whales | Where institutional money positioned for today's open |
| **Technical Tactician** | GPT-5 | per-ticker setups + momentum + breakout candidates | Specific entry/stop/target ideas from charts |
| **Chair** | Claude Opus 4 (or Sonnet ext-thinking) | synthesis | Resolve contradictions, write executive summary, finalize trade ideas |

### Member contracts

Each member emits:
```json
{
  "domain": "macro",
  "section_text": "string with id= inline citations",
  "key_findings": [{"text": "...", "citations": ["sig_id"]}],
  "trade_idea_seeds": [{"ticker": "NVDA", "rationale": "...", "type": "stock|options"}],
  "watch_list": ["TICKER", ...],
  "confidence": 0.0-1.0,
  "contradictions_with_other_members": ["short string of contradicting thesis", ...]
}
```

Chair receives all 4 member outputs + resolves contradictions via JSON synthesis. Chair also applies the rule 7a ETF quota + date recency + price sanity checks (lifted from the existing Phase 14D critic) BEFORE writing.

## Stage 3 — Presentation (05:30 ET, ~30s render)

**Module**: `runtime/intelligence/brief_presenter.py`

Renders the chair's synthesis into NATRIX's preferred format. Adds the new **MARKET OPEN PLAN** section with four sub-blocks:

### MARKET OPEN PLAN (new section)

```
── WHAT TO WATCH (3-5 specific catalysts) ─────────────
1. 08:30 ET — Initial Jobless Claims (consensus 225K, prior 222K)
   • Above 240K → bond bid + tech bid; below 215K → rate hike re-pricing
2. NVDA 09:30 open — gap up 2.3% on $AMZN deal headlines (test of $145 ATH)
3. POWELL 14:00 Jackson Hole prep speech — keyword "patient" vs "vigilant"

── DIRECTION INDICATORS (read these in order at open) ──
1. ES futures @ ${es_close} — above 4585 = bullish open, below 4570 = risk-off
2. /VX term structure: VIX9D vs VIX1M — backwardation = stress signal
3. ${qqq_pre_pct}% NQ vs ${es_pre_pct}% ES — divergence > 0.5% = sector rotation
4. SPY put/call ratio overnight — if > 1.2, hedging > positioning
5. ARKK vs SPY pre-market — small-cap risk appetite gauge

── MOMENTUM SIGNALS (first 30 min watch) ───────────────
• Gap-up watch list (>2%, vol >1.5x avg): TICKER, TICKER, TICKER
• Gap-down reversal candidates: TICKER, TICKER (oversold + dark pool support)
• RVOL > 3x list: institutional accumulation candidates
• 1-min ORB candidates: tickers consolidating overnight with options flow

── RISK FLAGS ──────────────────────────────────────────
• Earnings before open: TICKER (consensus EPS X.XX, watch reaction)
• Headlines to watch: <specific developing stories>
• Polymarket leading shift overnight: <event> moved from X% to Y%
• Cross-asset: DXY at __ — strong dollar = USD-revenue tech tailwind
```

This is the **flagship section**. Comes first in the brief so NATRIX sees the plan before the analytical narrative.

## Plus the existing brief surfaces

Below the Market Open Plan, the existing structure remains (refined):

- **EXECUTIVE SUMMARY** — chair's 2-paragraph synthesis
- **KEY MOVEMENTS** — 5-7 bullet points with citations
- **EMERGING OPPORTUNITIES & RISKS** — forward-looking 3-5 items
- **PRE-MARKET TRADE IDEAS** — 4-6 ideas (rule 7a: max 1 ETF)
- **POLYMARKET WATCH** — active leading markets only
- **TOP POTENTIAL DAILY MOVERS** — Council Technical Tactician's ranked list
- **TODAY'S RESEARCH TOPICS** — questions for tonight's Night Watch

## Scheduling

| Task | When | Loop name |
|---|---|---|
| Brief Prep | 02:30 ET nightly | `ncl-brief-prep` |
| Council Research | 05:00 ET nightly | `ncl-brief-council` |
| Brief Presentation | 05:30 ET nightly | `ncl-brief-render` |
| Existing 06:00 ntfy nudge | unchanged | (morning_quiz_scheduler.py) |

If prep fails, Council runs against last-good prep (degraded mode). If Council fails, fall through to the existing Phase 14D planner+executor pipeline.

## Cost envelope

- Prep stage: zero LLM cost (data collection only)
- Council research: 4 members × ~2500 tokens output × Sonnet/Grok/Gemini/GPT pricing → ~$0.20/run
- Chair synthesis: 1 × ~3000 tokens Opus/Sonnet → ~$0.06/run
- Total: ~$0.26/morning brief vs ~$0.045 current Phase 14D pipeline

5× cost increase, but this is the flagship feature. Daily anthropic cap stays at $25 with plenty of headroom.

## API surface

| Endpoint | Purpose |
|---|---|
| `GET /intelligence/morning-brief/pro` | Return today's pro brief (most recent successful render) |
| `GET /intelligence/morning-brief/pro/prep` | Raw prep pack (for ops/debug) |
| `GET /intelligence/morning-brief/pro/council` | Raw council member outputs (debug) |
| `POST /intelligence/morning-brief/pro/fire` | Manually trigger end-to-end run (authed) |
| `GET /intelligence/morning-brief/pro/history?days=N` | List last N briefs |
| Existing `GET /intelligence/morning-brief` | Phase 14D pipeline, kept as fallback |

## iOS surface

BriefRenderer extended to handle the new `market_open_plan` field. If absent (older briefs), renders as before. New section sits at top of the brief.

## Operator runbook

```
# Manual fire
curl -X POST -H "Authorization: Bearer $TOKEN" \
  https://brain.tail.../intelligence/morning-brief/pro/fire

# Get latest
curl -H "Authorization: Bearer $TOKEN" \
  https://brain.tail.../intelligence/morning-brief/pro

# Inspect prep pack
curl -H "Authorization: Bearer $TOKEN" \
  https://brain.tail.../intelligence/morning-brief/pro/prep
```

## Failure modes + degradation

| If | Then |
|---|---|
| Prep stage 100% fails | Council runs with empty context — brief degrades to current Phase 14D output |
| One Council member errors | Chair receives 3-of-4 → still synthesizes, notes missing domain in pipeline_meta |
| Chair errors | Fall back to Phase 14D pipeline entirely |
| All members error | Fall back to Phase 14D pipeline entirely |

The Phase 14D pipeline (planner → executor → critic) remains the safety net.
