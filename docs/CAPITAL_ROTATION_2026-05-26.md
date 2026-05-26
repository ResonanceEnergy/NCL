# Capital Rotation — Mechanics, NCL Integration, Roadmap

**Date**: 2026-05-26
**Audit**: P22 (live web research + NCL codebase grep)
**Purpose**: explain what capital rotation is, why NCL monitors it, where it shows up in the current stack today, what's missing, and how to use it tactically.

---

## What "capital rotation" actually means

Capital rotation is **money flowing between asset classes, sectors, styles, geographies, or market caps in response to changing macro conditions**. It's not one trade — it's a regime shift that can take days, weeks, or months to play out. Five distinct rotations to watch:

| Type | What rotates | Trigger | Tactical implication |
|---|---|---|---|
| **Asset-class** | Equities ↔ bonds ↔ commodities ↔ cash | Fed policy, recession signals, inflation | Long-term portfolio tilt |
| **Sector** | XLK ↔ XLE ↔ XLF ↔ XLV ↔ XLU etc. | Business cycle phase (early/mid/late/recession) | 1-4 week swing trades |
| **Style** | Growth ↔ Value, Quality ↔ Cyclical | Rate expectations, earnings cycle | 1-6 month positioning |
| **Market cap** | Large-cap (SPY) ↔ Small-cap (IWM) | Risk-on / risk-off, credit conditions | 1-12 month positioning |
| **Geographic** | US ↔ EM ↔ Europe ↔ China | Dollar strength, trade flows, geo events | Quarterly tilts |

**Real-world example from this week**: The Great Rotation of 2026 is happening RIGHT NOW. Per market reporting: small-cap + value + defensive are each beating large-cap + growth + cyclical by ~10pp YTD. IWM +6.8% vs SPY -0.1%. Energy +21%, Materials +17%, Staples +15%, Industrials +12%. Tech cooling after the AI run.

---

## Why we monitor it — five reasons it matters for NATRIX

1. **Early regime detection.** When tech is getting put-hammered while healthcare sees heavy call buying, you're watching sector rotation happen in real time. Often visible in options flow 24-48 hours BEFORE it shows on charts.

2. **Trade idea direction.** Knowing "money is flowing INTO energy and OUT of tech" tells you which direction your trade ideas should bias — long XOM-flavored names, short tech-flavored names.

3. **Risk filter.** A trade idea that lines up with rotation is a higher-conviction setup. A trade idea fighting rotation needs a much stronger thesis to be worth taking.

4. **Portfolio drift.** If NATRIX is long tech and rotation accelerates, the held-positions check should flag it as "concentration risk vs current flow regime."

5. **Macro confirmation.** Rotation IS the market's verdict on the business cycle phase. ISM PMI <50, yield-curve flattening, defensive leadership — these confirm where the cycle is, beyond what any single ticker says.

---

## How rotation is measured (the standard toolkit)

### 1. Relative Rotation Graph (RRG) — the visual
The canonical sector-rotation tool. Each sector ETF is plotted on a 4-quadrant grid measuring relative strength vs SPY (X-axis) and relative momentum (Y-axis):

```
              MOMENTUM ↑
                 │
   IMPROVING     │     LEADING
   (low RS,      │     (high RS,
    high mom)    │     high mom)
                 │
                 ├──────────────  RELATIVE STRENGTH →
                 │
   LAGGING       │     WEAKENING
   (low RS,      │     (high RS,
    low mom)     │     low mom)
                 │
```

Sectors rotate **clockwise**: Improving → Leading → Weakening → Lagging → Improving. Catch them entering Leading (institutional accumulation), exit when they enter Weakening (distribution starting).

### 2. Sector breadth — how many participating
% of the 11 sector ETFs above their 50-day SMA. >70% = broad uptrend. <30% = broad downtrend. Divergence (price rising but breadth falling) is a top warning.

### 3. Equal-weight vs cap-weight (RSP vs SPY)
When equal-weight outperforms cap-weight, money is rotating OUT of mega-caps INTO the broader market. Often early sign of a regime change.

### 4. Style ratios
- IWM/SPY — small-cap vs large-cap risk appetite
- IWD/IWF — value vs growth tilt
- XLU/SPY — defensive leadership signal
- ARKK/SPY — speculative risk appetite

### 5. Options flow divergence
**The leading indicator.** If SPY makes new highs but net call premium is declining, institutions are hedging at the top. If XLE call buying surges while XLK gets put-hammered, rotation is starting BEFORE price confirms.

### 6. Dark pool prints
~40% of US equity volume executes in dark pools. Repeated block accumulation in a sector ETF over multiple days = institutions building positions silently. Cross-asset (XLF accumulation + TLT distribution) often precedes major moves by 24-48 hours.

### 7. Business cycle position
The umbrella over all of the above. Determines which sectors SHOULD lead:

| Cycle phase | Leaders | Laggards |
|---|---|---|
| Early expansion | Cyclicals, financials, small-caps, industrials | Defensives, utilities |
| Mid-cycle | Tech, comms, consumer disc, energy | Materials, staples |
| Late-cycle peak | Energy, materials, defensives starting to bid | Tech rolling over |
| Recession | Staples, utilities, healthcare, bonds | Cyclicals, small-caps, financials |

ISM PMI dropping below 50 OR yield-curve flattening usually precedes the growth → defensive shift.

---

## What NCL captures TODAY (audited 2026-05-26)

### ✅ Already captured

| Surface | Where | Detail |
|---|---|---|
| Per-sector signal aggregation | `runtime/intelligence/models.py::SectorSnapshot` | direction + signal_count + avg_confidence + top_signals per sector. Already feeds into the morning brief's `key_movements`. |
| Sector ETF tracking in watchlist | `runtime/stocks/watchlist.py` | XLF/XLK/XLE/XLV/XLI/XLP/XLY/XLB/XLU/XLC/XLRE present in WATCHLIST_MAP with sector field. |
| Sector ETF flow surfacing in briefs | `brief_pipeline.py::_format_signals` + `__init__.py::_lane()` | OIL/ENERGY lane keyword filters route XLE-tagged signals to the brief's macro_landscape section. |
| Rule 7a — ETF cap on trade ideas | `brief_pipeline.py::_local_critique` | At most 1 of 4-6 trade ideas may be a broad/sector ETF. This is exactly the "don't over-weight rotation ETFs in NATRIX's tactical book" guardrail. |
| Sector chip in Macro Analyst prompt | `intelligence/brief_council.py::_macro_prompt` | Council Macro member sees `vix_term_structure` + `futures` + `polymarket_leading` and is asked for direction call. Today it can write sector rotation theses from the prep pack. |
| Direction indicators in Market Open Plan | `brief_presenter.py` MARKET OPEN PLAN section | Chair includes ES futures, VIX shape, breadth read — the regime indicators. |
| Per-signal sector tag | `runtime/awarebot/agent.py::_extract_sectors` | Each ingested signal gets tagged with the sectors it touches (extracted from text). Feeds the SectorSnapshot aggregation. |
| Awarebot category routing | `runtime/awarebot/agent.py::categorize_event` | Energy / tech / financials etc. categories tag signals at ingest. |
| Sector populated on scanner results | (Wave 14G P19-B fix) | GOAT/BRAVO results now carry `sector` field from WATCHLIST_MAP join — was missing before tonight. |

### ❌ Missing — the gaps that matter

| Gap | Why it matters | Build cost |
|---|---|---|
| **No relative-strength time series** | Can't detect "XLE rising while SPY falls" as a 5-day trend. Each scan is point-in-time. | ~150 LOC: `runtime/intelligence/rotation_tracker.py` — daily snapshot of XL?/SPY ratio change. |
| **No breadth indicator** | Can't say "8/11 sectors above 50-day SMA = broad rally" or "3/11 above = narrow tape". | ~50 LOC: daily yfinance pull of 11 sectors, compute SMA crossings. |
| **No RRG-style 4-quadrant classification** | Can't auto-tag a sector as Leading / Weakening / Lagging / Improving. | ~100 LOC: compute JdK RS-Ratio + RS-Momentum vs SPY benchmark, plot quadrant. |
| **No style-ratio tracking** | IWM/SPY, IWD/IWF, XLU/SPY ratios are the cleanest regime gauges. None currently logged. | ~80 LOC: add 4 ratios to brief_prep `vix_term_structure` block, persist daily. |
| **No equal-weight vs cap-weight** | RSP vs SPY divergence is a top early-warning rotation signal. Not tracked. | ~20 LOC: add RSP/SPY to futures collector. |
| **No business cycle phase classification** | Without it, the brief can't say "we're late-cycle, energy + defensives should lead" — only reactive observation. | ~120 LOC: pull ISM PMI + yield curve (10y-2y) + unemployment trend + credit spreads → 4-state classifier. |
| **No flow divergence detector** | Can't auto-detect "SPY hitting highs but net call premium falling = top warning." | ~80 LOC: nightly comparison of price vs premium 5-day deltas. |
| **No cross-asset rotation alerts** | XLF accumulation + TLT distribution = institutional rotation. Currently each tracked separately, not paired. | ~100 LOC: rule-engine for cross-asset divergence patterns. |
| **No NCL "rotation regime" persisted state** | Each brief reads the day point-in-time; rotation context doesn't persist as a tracked variable like cost or budget does. | ~60 LOC: `data/rotation/regime-state.json` with current regime + last shift date. |

---

## Tips, tricks, techniques for using rotation tactically

### For NATRIX (retail trader perspective)

**Tip 1: Don't fight the regime.** If everything in the brief is screaming "small-cap value leadership", don't take a 4-day swing long on a large-cap growth name unless the catalyst is overwhelming. The rotation is what 40% of dark-pool flow is doing — that's the elephant.

**Tip 2: Trade the rotation, not the rotated asset.** When energy rotates IN, the trade isn't always XLE itself. It's the individual stocks INSIDE energy with the cleanest setups (XOM / SLB / FANG individual). Rule 7a forces this discipline at the brief level.

**Tip 3: Watch the 12-15-25 trio.** Russell 2000 / S&P MidCap 400 / S&P 500 % changes over 5 days. If small-caps are leading by 1%+ on a 5-day basis, the rotation INTO risk is real. If they're lagging by 1%+, the rotation OUT of risk is real.

**Tip 4: Style ratios trump sector picks during regime shifts.** Knowing "value is winning by 2% this week" is more useful than chasing the specific XLE breakout. The ratio change reveals positioning before any single name breaks out.

**Tip 5: Use sector breadth as a brakes-on signal.** When the brief shows 3/11 sectors above 50-day SMA, it doesn't matter what looks good — the tape is narrow and a single bad print can take down everything. Cut size.

**Tip 6: Cross-asset confirmation beats single-asset signal.** If you see XLU bidding AND TLT bidding, that's both stock-side and bond-side defensive positioning. Single-asset signals (just XLU bidding) can be noise; cross-asset agreement is a regime shift.

**Tip 7: Treat the RRG quadrant as a stoplight.** Sectors in the LEADING quadrant = green (own them). IMPROVING = yellow (start accumulating). WEAKENING = orange (start trimming). LAGGING = red (don't add). Stay sector-aligned with the lights.

### For LLM councils (what to feed the Macro Analyst)

The Macro Analyst in `brief_council.py::_macro_prompt` currently sees `futures`, `vix_term_structure`, `economic_calendar`, `polymarket_leading`, `headlines`, and `night_watch_summary`. Add for rotation-aware briefs:

- Daily sector ratio % changes (XLF/SPY, XLE/SPY, ... × 11)
- 5-day relative strength rank per sector
- Breadth % (sectors above 50d SMA)
- IWM/SPY + IWD/IWF + XLU/SPY style ratios
- Equal-weight vs cap-weight (RSP/SPY)
- Business cycle phase classification

That gives the Macro Analyst enough to write **"we're late-cycle with breadth narrowing — defensives bidding, cyclicals rolling over, recommend tactical caution despite single-name strength"** instead of just **"futures green"**.

---

## How rotation integrates with current NCL functions

```
┌────────────────────────────────────────────────────────────────────────┐
│                          ROTATION SIGNAL FLOW                          │
└────────────────────────────────────────────────────────────────────────┘

  AWAREBOT INGEST (8 sources)
       │
       ├─ Per-signal sector tag (already)
       ├─ Per-signal category (already)
       └─ Signal scoring with cross-source weight (already)
              │
              ▼
  SECTOR-AGGREGATED SNAPSHOTS (already, models.py::SectorSnapshot)
       │
       │  ────  GAP: no daily relative-strength persistence  ────
       │
       ▼
  MORNING BRIEF PRO PREP STAGE (02:30 ET)
       │
       │  Today: futures, VIX shape, movers, headlines, polymarket
       │  Add (proposed):
       │     rotation_snapshot:
       │       sector_ratios:   {XLF/SPY: +0.4%, XLE/SPY: +1.2%, ...}
       │       breadth_50d_pct: 64%
       │       style_ratios:    {IWM/SPY: -0.3%, IWD/IWF: +0.8%, XLU/SPY: +0.5%}
       │       eq_vs_cap:       RSP/SPY +0.2%
       │       cycle_phase:     "late-cycle"  (ISM 48.2, 10y-2y +0.3, claims rising)
       │       leading_quadrant: ["XLE", "XLP", "XLU"]
       │       weakening_quadrant: ["XLK", "XLY"]
       │
       ▼
  COUNCIL RESEARCH (05:00 ET)
       │
       │  Macro Analyst reads rotation_snapshot → writes direction call
       │  Flow Detective cross-checks options flow vs rotation regime
       │  Technical Tactician aligns trade ideas with leading sectors
       │
       ▼
  CHAIR SYNTHESIS (05:30 ET)
       │
       │  Rule 7a holds ETF cap
       │  NEW: rotation alignment check — trade ideas should mostly
       │       lean WITH the leading sectors. Flag any that fight it.
       │
       ▼
  MARKET OPEN PLAN
       │
       │  DIRECTION INDICATORS section gains:
       │     • Sector leadership: XLE/XLP/XLU leading (energy + defensive)
       │     • Breadth: 64% sectors above 50d (broadening)
       │     • Style: small-cap underperforming today (-0.4% IWM/SPY)
       │     • Cycle: late-cycle — caution on cyclicals
       │
       ▼
  TRADE IDEAS
       │
       │  Each idea now has implicit alignment score with current rotation.
       │  Backtest: high-alignment ideas should have better hit rate.
       │
       ▼
  GOAT / BRAVO SCANNERS
       │
       │  Existing sector field (P19-B fix) can be cross-referenced with
       │  current Leading-quadrant sectors. Surface "rotation-aligned"
       │  setups at the top.
       │
       ▼
  AUTHORITY LEARNER (FuturePredictor)
       │
       │  Sources that called rotation correctly (e.g. specific Polymarket
       │  events, specific Twitter accounts) get authority boosted.
       │  Sources that fight rotation get demoted.

╔════════════════════════════════════════════════════════════════════════╗
║              CALENDAR + JOURNAL + LIFE PLAN INTEGRATION                ║
╚════════════════════════════════════════════════════════════════════════╝

  CALENDAR WATCHLIST  ←  rotation regime drives "what's worth watching"
                         today (e.g. FOMC + rotation context together)

  MORNING QUIZ        ←  Q2 (top priority) can be pre-seeded by rotation
                         (e.g. "size down — late-cycle defensives bidding")

  LIFE PLAN GOALS     ←  Quarterly OKR "diversify into commodities" gets
                         tactical urgency when rotation confirms the thesis

  WORKING CONTEXT     ←  "current rotation regime: late-cycle defensive"
                         becomes a pinned context item the brain consults
                         on every chat / brief / decision
```

---

## Proposed roadmap (Wave 14I — "Rotation-Aware Brain")

| Order | Module | Effort | Outcome |
|---|---|---|---|
| 1 | `runtime/intelligence/rotation_tracker.py` | ~250 LOC | Daily snapshot of 11 sector ETFs vs SPY: ratio % change, RS-Ratio (4-week ROC), RS-Momentum (1-week ROC), 4-quadrant classification, breadth %, persisted to `data/rotation/YYYY-MM-DD.json` |
| 2 | `runtime/intelligence/style_ratios.py` | ~80 LOC | IWM/SPY, IWD/IWF, XLU/SPY, RSP/SPY tracked daily; same persistence model |
| 3 | `runtime/intelligence/cycle_phase.py` | ~150 LOC | ISM PMI + 10y-2y yield + jobless claims + credit spreads → early/mid/late/recession classifier |
| 4 | Wire into `brief_prep.py` | ~30 LOC | Add `rotation` block to the prep pack |
| 5 | Add to `_macro_prompt` in council | ~10 LOC | Macro Analyst sees rotation data in every brief |
| 6 | Chair rule 7d (rotation alignment) | ~50 LOC | Critic flags trade ideas that fight current Leading sectors |
| 7 | Surface in Market Open Plan | ~40 LOC | New sub-block "ROTATION REGIME" in the brief renderer |
| 8 | GOAT/BRAVO rotation tag | ~30 LOC | Scanner results carry `rotation_aligned: bool` |
| 9 | Working context pin | ~20 LOC | Current regime auto-pinned to working_context every 6hr |
| 10 | iOS Intel tab — RRG widget | ~200 LOC SwiftUI | Visual 4-quadrant sector RRG for quick read |

Total: ~860 LOC backend + ~200 LOC iOS, deliverable as Wave 14I.

---

## Bottom line

NCL already has the **plumbing** for rotation awareness — sector tags, SectorSnapshot aggregation, sector-ETF watchlist, ETF-quota rule 7a, Council Macro Analyst, the brief's macro_landscape section.

What's missing is the **time series**: relative-strength persistence, breadth, style ratios, business cycle classification. Without those, every brief is a snapshot; with them, the brief speaks regime.

The fastest path to "rotation-aware" is the Wave 14I module above. The Macro Analyst is the bottleneck — give it rotation data and the chair's synthesis becomes regime-coherent automatically.

---

## Sources

- [Sector Rotation and Business Cycle: 2026 Investing — Alphaex Capital](https://www.alphaexcapital.com/stocks/fundamental-analysis-of-stocks/sector-and-industry-analysis/sector-rotation-and-business-cycle)
- [The Great Sector Rotation of 2026 — FinancialContent](https://markets.financialcontent.com/stocks/article/marketminute-2026-2-5-the-great-sector-rotation-of-2026-why-capital-is-fleeing-ai-tech-for-the-old-economy)
- [The 2026 Market Rotation — FXCM](https://www.fxcm.com/markets/insights/the-2026-market-rotation-suggests-a-quiet-shift-with-loud-implications/)
- [Sector Rotation Guide — Investing.com](https://www.investing.com/analysis/sector-rotation-a-guide-to-the-sp-500-momentum-status-200675903)
- [RRG Charts — ChartSchool](https://chartschool.stockcharts.com/table-of-contents/chart-analysis/chart-types/relative-rotation-graphs-rrg-charts)
- [Visualizing Breadth and Rotation Using RRG — StockCharts](https://articles.stockcharts.com/article/visualizing-breadth-and-rotation-using-rrg/)
- [Relative Rotation Graphs — Interactive Brokers](https://www.interactivebrokers.com/campus/glossary-terms/relative-rotation-graphs/)
- [Dark Pool Options Flow — AI FlowTrader](https://www.aiflowtrader.com/blog/dark-pool-options-flow-what-you-need-to-know)
- [Pineify Market Insights — real-time flow + dark pool](https://pineify.app/resources/blog/pineify-market-insights-options-flow-dark-pool-congress-trading-market-tide)
- [Sweep vs Block vs Dark Pool — ProfitBuilders](https://profitbuilders.io/blog/sweep-vs-block-vs-dark-pool)
- [The Great Rotation 2026: Small-Cap Surge — Intellectia.ai](https://intellectia.ai/blog/great-rotation-small-cap-stocks-2026)
- [The Odd Couple of 2026: Cyclicals + Defensives — BlackRock](https://www.blackrock.com/us/individual/insights/cyclicals-vs-defensive)
- [Small-Cap Rotation — Ainvest](https://www.ainvest.com/news/small-cap-rotation-2026-reversal-2027-warning-2602/)
- [Market Rotation Out of Big Tech — Morgan Stanley](https://www.morganstanley.com/insights/articles/magnificent-seven-rotation-portfolio-strategies-2026)
