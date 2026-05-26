# Portfolio Manager Audit — Wave 14J Prep

**Date**: 2026-05-26
**Author**: Wave 14J audit pass (NCL Brain side + external best-practice deep-dive)
**Scope**: NCL's portfolio manager subsystem — code, responsibilities, schedule, and gap analysis against institutional + sophisticated-retail best practice

---

## TL;DR

NCL's portfolio manager is structurally sound as a **polling aggregator** across 6 adapters (IBKR / Moomoo / SnapTrade / NDAX / MetaMask / Polymarket). It does the boring stuff well: parallel adapter fetch, FX normalization, quote fallback chain, daily snapshot persistence, memory-bridge event emission, and a clean REST surface for iOS.

What it does NOT do — and what every sophisticated retail trader's system eventually has to — is the **risk and execution layer**: there is no unified risk-unit (R) ledger, no per-strategy heat cap, no tiered drawdown throttle, no portfolio-level Greeks budget, no wash-sale cross-account check, no T+1 settled-cash awareness, no programmatic tail-hedge, no pacing rules on rotation signals, and no cost ledger for trading costs (the LLM cost ledger exists; the trading-cost mirror does not). The analyst agent applies fixed policy thresholds but those thresholds aren't enforced by any executor — they're surfaced as report items, not blocked at the order surface.

Wave 14J should focus on the **risk + execution layer**, not on more adapters or more data. The measurement quality is already at institutional grade (RRG, cycle phase, breadth, style ratios, GOAT/BRAVO scanners, council confidence). The leak is between "what the system knows" and "what the system does with it."

---

## 1. What the portfolio manager IS today

### 1.1 Module map (`runtime/portfolio/`)

| File | LOC | Purpose |
|------|-----|---------|
| `portfolio_manager.py` | 910 | Central orchestrator — singleton `PortfolioManager` class; coordinates 6 adapters; background sync loop; FX conversion; snapshot persistence |
| `memory_bridge.py` | 811 | Portfolio→Memory bridge — emits `portfolio:*` MemUnits on sync; diffs state; detects open/close/qty-change/significant-move/BP-risk events at importance 70–95 |
| `paper_trading.py` | 750 | Paper trading engine — simulated trades, P&L tracking, strategy tag enrichment, scoped to FirstStrike paper tab |
| `polymarket_strategies.py` | 608 | Polymarket opportunity scanners — planktonxd + weatherbetter scoring (cherry-picked from retired AAC repo) |
| `moomoo_adapter.py` | 537 | Moomoo broker adapter — FX detection, native-currency handling, real-time quote feed |
| `ibkr_adapter.py` | 503 | IBKR adapter — ib_insync async wrapper (ports 7496/7497/4001/4002), circuit-breaker pattern, event-driven quotes |
| `snaptrade_adapter.py` | 498 | SnapTrade (Wealthsimple) adapter — multi-exchange account support, position + quote refresh |
| `options_strategies.py` | 487 | Options library — 18 strategy definitions, DTE calc, position→strategy matcher, enricher |
| `ndax_adapter.py` | 416 | NDAX Canadian crypto exchange — account + balance + position fetch |
| `ibkr_market_data.py` | 406 | yfinance-backed quote fallback when broker feeds missing |
| `metamask_adapter.py` | 360 | MetaMask wallet — Ethereum self-custody holdings (native ETH + ERC-20 via Etherscan) |
| `polymarket_adapter.py` | 299 | Polymarket prediction markets — position + price + payout odds |
| `paper_routes.py` | 294 | Paper trading routes shim (W10C-3 DI migration) |
| `_setup_snaptrade.py` | 172 | SnapTrade OAuth setup helper |
| `analyst/` (subdir) | — | Nightly portfolio report agent + schema + thesis evaluator |
| `strategies/` (subdir) | — | planktonxd + weatherbetter scorers |

Total: ~6,500 LOC of portfolio code, none of it covered by tests (zero `test_portfolio*.py` in `tests/`).

### 1.2 PortfolioManager — public surface

Constructor `__init__()` initializes 6 adapter instances (`_ibkr`, `_moomoo`, `_snaptrade`, `_ndax`, `_metamask`, `_polymarket`), empty caches, FX rate cache, memory bridge (defensive — bridge failure doesn't break manager).

| Method | Returns | Behavior |
|--------|---------|----------|
| `async start()` | None | Connects 6 adapters in parallel via `asyncio.gather(..., return_exceptions=True)`; initial `sync()`; starts background loop |
| `async stop()` | None | Cancels background sync task; disconnects all adapters |
| `async sync()` | None | Reconnect dropped adapters → fetch accounts + positions → refresh FX → fill missing quotes via IBKRMarketData fallback → cache → daily snapshot → emit memory units. Guarded by `_sync_lock` |
| `get_summary(base_currency="CAD")` | dict | total_value, daily/total P&L (pct), cash, positions_count, allocation by broker/sector, FX rate, last_sync, market_open. Wave 10C-3 added `quotes_failed` |
| `get_positions(account_filter="all")` | list[dict] | symbol + qty + broker + account_id + current_price + daily_pl + daily_pl_pct + asset_class + quote_ok |
| `get_accounts()` | list[dict] | broker + account_id + account_name + buying_power + cash + nav + daily_pl + daily_pl_pct |
| `get_performance(range="1M")` | dict | yfinance-backed NAV history ("1M"/"3M"/"1Y"/"YTD") |
| `health()` | dict | adapter connectivity, positions_cached, accounts_cached, quotes_failed, quote_feed_status, FX rate, market_open, background_sync flag |

### 1.3 Sync cadence

- **Market hours** (M-F 09:30–16:00 ET): 60s
- **Off hours**: 300s
- **Daily snapshot**: written on UTC date change to `data/portfolio/snapshots.jsonl`
- **Snapshot rotation**: pruned to 90 days at startup (`_rotate_snapshots`)

### 1.4 Adapter inventory

| Adapter | Status | Data | Refresh | Notes |
|---------|--------|------|---------|-------|
| **IBKR** | depends on TWS/Gateway | accounts, positions, options Greeks | event stream | ib_insync deferred import (W13 fix); circuit-breaker 3-fail → 10m skip |
| **Moomoo** | API-tier dependent | accounts, positions, FX-native | async batch | USD→CNY fallback via getquote symbol on rate-limit |
| **SnapTrade** | OAuth-token dependent | accounts (15+ brokers), positions, quotes | REST polling | Multi-exchange aggregation (TSX/NYSE/NASDAQ) |
| **NDAX** | API key-based | crypto balances + holdings | REST polling | Holdings snapshot only — no deposit/withdraw tracking |
| **MetaMask** | wallet address only | native ETH + ERC-20 via Etherscan | REST polling | Self-custody; gas-adjusted value; no L2 aggregation |
| **Polymarket** | API v2 public | positions, contract prices, payout odds | REST polling | AMM-style; no order book; flow separately via `polymarket_strategies.py` |

Current state (2026-05-26 snapshots.jsonl tail): `positions_count: 0` across all adapters — no live broker integrations active. CLAUDE.md health rollup row showed `portfolio.status: yellow` with `ndax/metamask/polymarket: red` — those three were red as of the audit cap.

### 1.5 REST surface (`runtime/api/routers/portfolio.py`, 1,278 LOC)

Prefix `/portfolio/`, every route gated by `verify_strike_token_dep()`.

**Read endpoints**:
- `GET /summary` — aggregated portfolio snapshot (with `quotes_failed` per Wave 10)
- `GET /positions?account=all|IBKR|MOOMOO|WEALTHSIMPLE`
- `GET /accounts`
- `GET /performance?range=1M|3M|1Y|YTD`
- `GET /health`
- `GET /bridge-state` — in-memory snapshot peek for debugging
- `GET /options-flow` — Wave 8 EOD addition: top-20 unusual flow grouped by ticker, premium splits, call/put ratio, `is_held_in_portfolio` flag
- `GET /options/strategies` — 18-strategy library payload
- `GET /options/positions/with-strategy` — held options enriched with matched strategy + DTE + recommendation
- `GET /crypto` — NDAX + MetaMask combined
- `GET /polymarket` — positions + current odds + payout probabilities
- `GET /events?days=30` — recent `portfolio:*` MemUnits (uses SQLite units_index fast path per W13)
- `GET /significant-moves` — positions/portfolio breaching configured thresholds

**Write/admin endpoints**:
- `POST /sync` — manual sync trigger
- `POST /connect/{ibkr,ndax,metamask,polymarket}` — patch creds + reconnect
- `POST /probe/ibkr` — TCP probe of common IBKR ports

### 1.6 Cross-system integrations

| Consumer | Path | What it gets | When |
|----------|------|--------------|------|
| Morning Brief Pro (`brief_prep.py:272-283`) | `collect_held_positions(brain)` → `portfolio_mgr.get_positions()` | held positions array (symbol, qty, current_price, daily_pl, broker) | 02:30 ET nightly |
| GOAT/BRAVO scanners (`routes.py:4907-5133`) | Late-bind via `_stock_scanner.attach_portfolio_manager(_pm)` | `is_held_in_portfolio` filter + `sector_etf` tagging | On scanner request |
| Night Watch portfolio council (`ncl-night-watch` Phase 6) | `_nw_collect_portfolio_data()` → summary + positions + 1W perf | thesis eval + risk review against held theses | 23:00 ET nightly |
| Health rollup (`ncl-health-rollup`) | `portfolio_mgr.health()` | per-adapter status + quote feed health | 60s |
| iOS FirstStrike Portfolio tab (PortfolioView.swift) | `/portfolio/{summary,positions,accounts}` REST | view rendering, broker chip row, sub-tabs | on view load + refresh |
| Memory subsystem | `memory_bridge.on_sync()` → AsyncMemoryWriter | `portfolio:{snapshot,open,close,quantity_change,significant_move,bp_risk}` MemUnits at NATRIX tier | every sync + 1h/6h snapshot windows |

### 1.7 Persistence

- `data/portfolio/snapshots.jsonl` — daily portfolio summary (one JSON-object-per-line, 31 entries since 2026-05-20)
- `data/portfolio/analyst/reports/portfolio-YYYY-MM-DD.json` — nightly analyst output
- No SQLite double-write — portfolio doesn't participate in W10 mandates/cost-ledger/units-index gates beyond the MemUnits the bridge emits (which write through AsyncMemoryWriter to units.jsonl + SQLite units_index)

### 1.8 Cost integration

Portfolio sync itself calls **no paid APIs**: yfinance (free public via 3rd-party), Bank of Canada Valet (free), Etherscan (free tier ~5M/day), broker APIs (included in account), Polymarket public.

LLM costs: analyst agent fires one Sonnet 4 call nightly (~$0.05, gated at $0.10/run against the `anthropic` daily budget). Falls back to deterministic-only report when budget blocked. No cost_ledger entries from sync paths (verified via grep).

### 1.9 Mandates pulled from `data/mandates.json` + `CLAUDE.md`

NATRIX's overall portfolio mandate (verbatim from `analyst/portfolio_analyst_agent.py:4-8`):

> maximize capital flow IN, limit capital flow OUT
> + research positions and watchlist
> + every position has entry, exit, goal/mandate, watch-for
> + defend or invalidate position theses with evidence
> + escalate broken theses to council

Live mandates touching portfolio (sample):
- "Rebalance crypto holdings toward stablecoins and blue-chip assets while maintaining 10% exposure to short-term volatility plays" (target: crypto vol -30%, stablecoin allocation 40%)
- "Asymmetric Positioning Protocol — execute pre-positioning strategy on 2-3 non-obvious AI winners identified through intelligence system within 90 days"
- "Assume signal validation returns positive, map the specific enterprise verticals driving AI automation search interest"

### 1.10 Schedule / cadence summary

| Loop | Cadence | What it does | Status |
|------|---------|--------------|--------|
| Background sync (autonomous, not a named scheduler task) | 60s mkt / 300s off | 6-adapter fetch → cache → snapshot → bridge | Running 24/7 (current state: 0 connected) |
| Memory bridge (inline to sync) | every sync + 3600s/21600s snapshot windows | emit `portfolio:*` MemUnits | Running |
| Portfolio analyst agent (`ncl-night-watch` Phase 6) | 03:15 ET | thesis eval + 18-catalyst rank + Sonnet 4 narrative + ntfy on high-severity | Implemented |
| Health rollup (`ncl-health-rollup`) | 5m | per-adapter status to `data/health/current.json` | Live |
| Night Watch portfolio council (`ncl-night-watch` Phase 6 sub-step) | 23:00 ET | 4-LLM council on holdings + risk → night watch report | Implemented |

### 1.11 Drift between docs and code

- CLAUDE.md describes "35 unique ncl-* task names" — actual count via grep is 42 (Wave 14E added `ncl-morning-quiz`, Wave 14G Phase 1 added `ncl-ops-monitor`, Wave 14H added `ncl-brief-{prep,council,render}`, Wave 14F additions). The doc is one wave behind on the table.
- Wave 14C noted portfolio snapshots had a path drift bug (`~/dev/NCL/data/...` vs `~/NCL/data/...`). Brief pipeline switched to `get_positions()` in-process; verified. Current snapshot path: `/Users/natrix/dev/NCL/data/portfolio/snapshots.jsonl` ✓
- Wave 8 EOD `current_price` vs `last_price` field rename — both fields coexist; quote-fill logic checks both; no latent breakage. iOS PortfolioPosition codable maps to `lastPrice` at encode time.
- No TODO/FIXME/XXX in `runtime/portfolio/` (verified via grep). Code is tidy.

---

## 2. Best-practice gap analysis (institutional + sophisticated retail)

### 2.1 Multi-broker portfolio reconciliation

**Best practice (institutional)**: maintain an internal Book of Record (IBOR) — your own canonical position ledger; treat broker reports as evidence, not truth. Run trade-date and settle-date books in parallel. Normalize instrument identifiers across adapters (same option = different OCC symbols at IBKR vs Moomoo). Reconciliation breaks are first-class entities with severity and aging, not "silently overwrite the lower number."

**NCL state**: ONE adapter writes to ONE cache; last-writer-wins. No internal canonical ledger. No trade-date / settle-date split. Same NVDA contract from two brokers would compare by symbol-string (which is broker-encoded). No `Break` entity surfaced when adapters disagree.

**Sources**:
- [Multi-Asset Trading with Institutional Infrastructure (Knight Markets)](https://www.knightmarkets.com/post/multi-asset-trading-institutional-infrastructure)
- [Position and Trade Reconciliation Case Study (Devexperts)](https://devexperts.com/case-studies/position-and-trade-reconciliation-subsystem-for-a-retail-broker/)
- [Cash and Position Reconciliation Guide (Limina)](https://www.limina.com/blog/cash-position-reconciliation-guide)
- [Trade Date vs Settlement Date (LegalClarity)](https://legalclarity.org/what-is-the-difference-between-trade-date-and-settlement-date/)

### 2.2 Position sizing + risk management

**Best practice**: fractional Kelly (¼ or ½) — full Kelly produces ~50% drawdowns. Express everything in R-units (one R = the dollar risk per trade). Per-strategy risk budgets, not per-trade caps. Correlation-aware sizing: marginal new R adjusted for correlation to existing book. Hard concentration limits (single-name 8%, sector 25%, strategy 30%) that **block orders**, not warn.

**NCL state**: analyst agent has fixed thresholds in `portfolio_analyst_agent.py` (max_single_name_pct 10%, max_sector_pct 25%, daily_loss_circuit_breaker -3.5%, drawdown_trim_trigger -12%) but these are policy thresholds for **reporting**, not order-side enforcement. There is no R-ledger. There is no per-strategy heat budget. Correlation isn't computed.

**Sources**:
- [Kelly Criterion Practical Portfolio Optimization (Carl)](https://investwithcarl.com/learning-center/investment-basics/dynamic-adaptive-kelly-criterion-bridging-theory-and-practice-for-modern-portfolio-optimization)
- [Portfolio Heat Management (Pro Trader Dashboard)](https://protraderdashboard.com/blog/portfolio-heat-management/)
- [Measuring Factor Exposures (AQR)](https://www.aqr.com/-/media/AQR/Documents/Insights/White-Papers/JAI_Summer_2017_AQR.PDF)
- [Quantifying Portfolio Concentration Risk (Moody's)](https://www.moodys.com/web/en/us/insights/resources/quantifying-decomposing-and-managing-portfolio-concentration-risk.pdf)

### 2.3 Drawdown discipline + stop logic

**Best practice**: three stop types per trade (price / volatility / time), all computed at entry, exit on whichever fires first. Trailing stops by phase (fixed → break-even → ATR-trailing). Tiered drawdown protocol — down 5% cut risk-per-trade 25%; down 10–15% cut 50% and A-setups only; down 15%+ halt 24–72h. Per-strategy cooldowns: 5 consecutive losses → strategy quarantined for 24h. Catastrophic loss circuit breakers: hard stop all new orders at portfolio -X% intra-day.

**NCL state**: no stop framework. Trade ideas come out of morning brief with directional theses but no entry/exit/stop fields. No drawdown bucket. No system-wide kill switch. Per-strategy expectancy isn't tracked at all (GOAT vs BRAVO performance comparison would require new instrumentation).

**Sources**:
- [Drawdown Management 3-Tier Protocol (Tradezella)](https://www.tradezella.com/blog/drawdown-management)
- [De-gross During Drawdown (Wall Street Oasis)](https://www.wallstreetoasis.com/forum/hedge-fund/de-gross-during-drawdown-question)
- [Volatility Stop Indicator (LuxAlgo)](https://www.luxalgo.com/blog/volatility-stop-indicator-volatility-based-trailing-stop-strategy/)
- [Trading Circuit Breakers (Bookmap)](https://bookmap.com/blog/trading-circuit-breakers-and-halts-how-they-protect-markets-and-what-traders-should-know)

### 2.4 Options portfolio construction

**Best practice**: Greeks are portfolio-level, not per-position. Net delta ±0.30/$ NAV, aggregate gamma ±0.20, theta target $100–$300/day for small premium-selling book. Vega budget tied to IV regime (smaller when VIX in lowest decile). Sell premium when IV rank > 50 **AND** IV percentile > 50; buy / calendar when IV rank < 30. 21-DTE management rule (close or roll short premium at 21 DTE because gamma acceleration overwhelms theta benefit). Pin risk auto-flag at 0.5% of strike on expiration Friday. Migrate SPY → SPX for Section 1256 60/40 tax treatment.

**NCL state**: `options_strategies.py` has 18 strategy definitions and an enricher that matches **held positions to strategies retrospectively**. There is no portfolio-level Greeks aggregation. No IV rank/percentile gating. No 21-DTE management trigger. No pin-risk scanner on expiration Fridays. No SPY → SPX auto-substitution suggestion.

**Sources**:
- [Reading the Greeks (Hedgepoint Global)](https://hedgepointglobal.com/en/blog/options-greeks-from-delta-to-theta)
- [IV Rank Explained (CivolatilityVolatility)](https://www.civolatility.com/p/iv-rank-explained-a-complete-guide)
- [Pin Risk by DTE Phase (Days to Expiry)](https://www.daystoexpiry.com/blog/pin-risk-in-options-managing-expiration-uncertainty-by-dte-phase)
- [Strategic Tail-Risk Hedging (Resonanz Capital)](https://resonanzcapital.com/insights/strategic-tail-risk-hedging-building-antifragility-into-institutional-portfolios)
- [Managing Tail Risk with Options (Hedge Fund Journal)](https://thehedgefundjournal.com/managing-tail-risk-with-options-products/)

### 2.5 Sector rotation execution (turning RRG into action)

**Best practice**: pace into rotation signals (1/3 initial, 1/3 on 5d confirmation of Leading, 1/3 on retest). ETF first then graduate to top 2–3 single names after 5+ days of confirmed Leading status. Counter-trend P&L tracked separately from with-trend (retail systematically over-rates its counter-trend hit rate). Breadth < 40% above 50d SMA = veto the Leading call (narrow leadership). Cycle-phase playbooks: late-cycle → XLE/XLB/XLP/XLU + cash-secured puts on quality cyclicals.

**NCL state**: NCL HAS the measurement (Wave 14I rotation_tracker + style_ratios + cycle_phase; breadth %; Leading/Improving/Weakening/Lagging quadrants; rule 7d in chair). The morning brief surfaces this as a `ROTATION REGIME` sub-block and tags GOAT/BRAVO results with `rotation_aligned`. What's missing is the **execution layer**: there's no pacing rule per signal, no separate counter-trend P&L bucket, no "Improving but breadth-vetoed" flag in trade ideas. Operator still has to apply pacing manually.

**Sources**:
- [Relative Rotation Graphs / ChartSchool (StockCharts)](https://chartschool.stockcharts.com/table-of-contents/chart-analysis/chart-types/relative-rotation-graphs-rrg-charts)
- [Sector Rotation, what the RRG is telling us (IBKR)](https://www.interactivebrokers.com/campus/traders-insight/securities/macro/chart-advisor-sector-rotation-what-the-rrg-is-telling-us/)
- [Visualizing Breadth and Rotation Using RRG](https://articles.stockcharts.com/article/visualizing-breadth-and-rotation-using-rrg/)

### 2.6 Earnings + corporate-event risk

**Best practice**: long premium into earnings → max 0.5R (half-normal) because IV crush. Short premium into earnings is the volatility-seller play; cap per-cycle (e.g., max 5 strangles, each ≤ 0.5R). Calendar-aware trimming ahead of FOMC/CPI/NFP. Lockup-expiry tracking (T+180 from IPO = forced-seller event). Dividend ex-dates: auto-close ITM short calls if extrinsic < dividend. M&A targets get fixed risk-arb sizing.

**NCL state**: Awarebot Intel + Calendar already track earnings events. Morning Brief uses earnings calendar data. **There is no automated position sizing modifier tied to earnings proximity.** No lockup-expiry calendar source. No dividend ex-date auto-close hint for short calls. M&A handling not formalized.

**Sources**:
- [The Mechanics of Implied Volatility Crush (Schaeffer's)](https://www.schaeffersresearch.com/content/education/2025/12/19/the-mechanics-of-implied-volatility-crush-in-options-trading)
- [IV Crush Explained (SpotGamma)](https://support.spotgamma.com/hc/en-us/articles/15249330755859-IV-Crush-Explained-Key-Concepts)
- [Understand Corporate Actions (Vanguard)](https://investor.vanguard.com/investor-resources-education/online-trading/corporate-actions)
- [Automate Corporate Action Processing (Finantrix)](https://www.finantrix.com/articles/how-to-automate-corporate-action-processing-dividends-splits-mergers)

### 2.7 Tax-aware portfolio management (US trader)

**Best practice**: wash sale check across ALL controlled accounts (taxpayer + spouse + IRAs + 401k), 61-day window. Specific-lot identification at sale (default broker = FIFO; spec-ID lets you harvest highest-cost lot for losses, defer lowest-cost for potential LT). Long-term holding cliff awareness — alert at T-10 days from LT qualification. Section 1256 60/40 opportunity — SPX/NDX/RUT/VIX options qualify regardless of holding period; SPY does NOT (37% ordinary → ~27% blended). Opportunistic harvest > calendar-driven.

**NCL state**: ZERO tax-awareness in current code. No wash-sale ledger. No spec-ID at sale time. No LT-qualification alert. No SPY → SPX substitution prompts in the morning brief. The system writes daily snapshots but doesn't tag lots, so any retroactive harvest analysis requires broker statements.

**Sources**:
- [Wash Sale Rule Guide 2026 (CountryTaxCalc)](https://www.countrytaxcalc.com/tax-guides/usa/wash-sale-rule-guide-2026/)
- [Wash Sale Rule (Fidelity Learning Center)](https://www.fidelity.com/learning-center/personal-finance/wash-sales-rules-tax)
- [Tax-Loss Harvesting Part II: Wash Sales (ASKramer Law)](https://www.askramerlaw.com/publications/tax-loss-harvesting-part-ii)
- [Section 1256 Contracts (Green Trader Tax)](https://greentradertax.com/trader-tax-center/tax-treatment/section-1256-contracts/)
- [60/40 Tax Treatment for Futures Traders (QuantVPS)](https://www.quantvps.com/blog/60-40-tax-treatment-futures-traders)

### 2.8 Crypto + DeFi specifics

**Best practice**: on-chain wallets carry no cost-basis — maintain parallel transaction journal indexed by tx-hash. Custodial (NDAX) vs self-custody (MetaMask) as separate sub-portfolios. LP positions = current FMV underlying + accumulated fees − impermanent loss. Liquid-staking tokens require dual-price (stETH:ETH ratio × ETH:USD). Gas as cost-basis adjustment (failed txns = pure losses). Network-level aggregation: same MetaMask address across L1/L2 (Ethereum / Arbitrum / Base / Polygon / Optimism).

**NCL state**: MetaMask adapter pulls **balance only** — no tx history, no cost basis. NDAX similar (holdings snapshot, no trades). LP positions and liquid-staking tokens not handled. Gas accounting absent. No multi-chain aggregation (MetaMask adapter is ETH-mainnet-only based on the audit reading).

**Sources**:
- [DeFi Tax Guide 2026 (CryptoFolio AI)](https://cryptofolio.ai/blog/defi-tax-guide)
- [DeFi Accounting Practical Guide (Beancount.io)](https://beancount.io/blog/2026/04/01/defi-accounting-guide-tax-compliance-decentralized-finance)
- [Track MetaMask Wallet Performance 2026 (Chain Glance)](https://chainglance.com/blog/track-metamask-wallet-performance-2026/)
- [Liquid Staking vs Restaking (Three Sigma)](https://threesigma.xyz/blog/lrt's/liquid-staking-vs-restaking-lsts-vs-lrts)

### 2.9 Prediction-market specifics (Polymarket)

**Best practice**: edge = (your prob) − (market implied prob); size with fractional Kelly because probability estimates are themselves uncertain. Risk-adjust sizing by 1/(days_to_resolution) — locked capital has opportunity cost. Aggregate exposure cap per resolution event (multiple markets on same election = one trade). Inventory cap: position ≤ ~10% of resting opposite-side liquidity in thin markets. Never exit same-day unless catalyst-driven.

**NCL state**: `polymarket_strategies.py` (planktonxd + weatherbetter scorers) computes opportunity scores. Polymarket P17-D lifecycle tagging (resolved/leading/active) is in place. **No Kelly sizing**, no resolution-time discounting, no resolution_cluster_id field, no inventory/liquidity cap.

**Sources**:
- [Polymarket Kelly Criterion Position Sizing (ManageBankroll)](https://managebankroll.com/blog/polymarket-kelly-criterion-position-sizing)
- [Polymarket Complete Guide 2026 (Prevayo)](https://www.prevayo.com/blog/polymarket-complete-guide-2026-strategies-tips-how-to-win)

### 2.10 Telemetry + observability

**Best practice (the metrics that actually matter)**:
- **Expectancy stack per strategy**: hit rate, avg win/loss (in $ and R), expectancy, profit factor (>1.75 good, >2.0 keep), system quality number (SQN)
- **Risk-adjusted stack**: Sharpe, Sortino (downside-only — more honest), Calmar (return / max DD)
- **Drawdown decomposition**: max DD, current DD, DD duration, recovery factor
- **Slippage breakdown**: arrival slippage (vs price at order submit) AND VWAP slippage (vs benchmark over fill window)
- **Cost ledger for trading**: commissions + financing + borrow + assignment fees + gas + exchange fees
- **Turnover** — annualized

**NCL state**: NONE of these are computed. The portfolio analyst agent emits qualitative narrative ("XLK has held up well") but the quantitative scorecard is absent. The `cost_ledger` exists for LLM API calls only — there's no equivalent trade-cost mirror despite the architectural symmetry being trivial.

**Sources**:
- [Performance, Risk Metrics & Strategy Optimisation (QuantInsti)](https://blog.quantinsti.com/performance-metrics-risk-metrics-optimization/)
- [Sharpe, Sortino, Calmar Ratios & Expectancy (iTrader)](https://www.itrader.com/en/blog/sharpe-sortino-calmar-ratios-and-expectancy-measuring-real-alpha-in-trading)
- [Implementation Shortfall (Quantitative Brokers)](https://www.quantitativebrokers.com/blog/a-brief-history-of-implementation-shortfall)
- [Execution Insights TCA (Talos)](https://www.talos.com/insights/execution-insights-through-transaction-cost-analysis-tca-benchmarks-and-slippage)

### 2.11 Operational hygiene

**Best practice**: drift alerts (3-5% asset-class, 1-2% position) — opportunistic rebalancing on threshold beats calendar rebalancing (Kitces, FA Magazine). Stale-quote detection with per-asset thresholds (equities 60s RTH, crypto 30s, on-chain hourly, Polymarket 5min). Auth-token expiry tracked in a single secrets manifest with proactive refresh 24–48h before expiry. Multi-broker resilience: parallel hedging (fire to primary + secondary simultaneously) for time-critical orders; circuit-breaker per adapter.

**NCL state**: `quote_ok` flag exists but there's no `stale_age_seconds` metric. No target-weight per slice (so no drift detection possible). Auth tokens live in `.env` with manual rotation. Multi-broker is for reach, not resilience — there's no "broker A is down, route to B" pattern.

**Sources**:
- [Optimal Rebalancing with Tolerance Bands (Kitces)](https://www.kitces.com/blog/best-opportunistic-rebalancing-frequency-time-horizons-vs-tolerance-band-thresholds/)
- [Optimal Rebalancing (FA-Mag)](https://www.fa-mag.com/news/optimal-rebalancing-with-tolerance-bands-29623.html)
- [Broker Outages (EMAC Intl)](https://emacintl.com/broker-outages-what-to-do-when-platforms-go-down)
- [Seamless API Failover Systems (Zuplo)](https://zuplo.com/learning-center/implementing-seamless-api-failover-systems)

### 2.12 AI / LLM augmentation patterns

**Best practice**:
- **Safe LLM territory**: idea generation, regime detection from news flow, contradiction surfacing across analysts (NCL's chair pattern), summarization, anomaly highlighting in P&L attribution
- **Dangerous LLM territory**: position sizing (LLMs systematically miscalibrated on probabilities), stop-level setting, tax-lot selection, order-routing decisions
- **Pattern**: LLM proposes, human disposes; deterministic-rule-as-executor; verbalized confidence treated as ranking signal, NOT for sizing
- **Council pattern**: multi-LLM debate with chair as variance reducer (NCL does this)
- **Audit trail**: every LLM recommendation persists prompt + model + version + response + sources + confidence + eventual outcome

**NCL state**: The architectural pattern is **correct** — LLM-augmented morning brief, council-based deliberation, human-in-the-loop trade execution. What's missing is the **outcome tracking**: trade ideas come out of the brief, but there's no closed loop to record which ones were taken, how they performed, and which model/source produced the alpha. Verbalized confidence isn't Brier-scored. The audit trail per recommendation is partial (the brief is persisted; the per-idea outcome isn't).

**Sources**:
- [LLMs in Equity Markets (Frontiers AI)](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2025.1608365/full)
- [Can LLM-based Financial Investing Outperform Long Run? (arXiv)](https://arxiv.org/html/2505.07078v5)
- [Trading-R1: Financial Trading with LLM Reasoning (arXiv)](https://arxiv.org/pdf/2509.11420)
- [Application of LLMs in Portfolio Management (QuantInsti)](https://blog.quantinsti.com/application-llm-portfolio-management-thematic-index/)

---

## 3. Top 10 actionable gaps

Phrased as "if NCL doesn't already do X, it should consider Y because Z." Each item ends with the highest-leverage source pulled during research.

1. **Maintain a unified R-ledger across all 6 adapters.** Every position records (entry, stop, R_dollars). P&L queryable in R-multiples. Without it, comparing an IBKR options trade to a Polymarket bet on raw $ is meaningless and per-strategy expectancy can't be computed. — [Portfolio Heat Management](https://protraderdashboard.com/blog/portfolio-heat-management/)

2. **Enforce hard per-strategy heat caps with order blocking, not warning.** Allocate total portfolio heat (10% typical) across strategies (GOAT 3%, BRAVO 2%, Polymarket 1%, on-chain 4%). Hard caps block new entries; soft caps warn and get ignored. — [Pro Trader Dashboard Heat Management](https://protraderdashboard.com/blog/portfolio-heat-management/)

3. **Run a tiered drawdown protocol that throttles ALL autonomous loops simultaneously.** Down 5% → cut sizing 25%; down 10–15% → cut 50% and A-setups only; down 15%+ → halt 24–72h. Apply globally — the GOAT scanner, the BRAVO scanner, the morning brief trade ideas, and the Polymarket strategy scorers all need to read the same drawdown bucket. — [Tradezella drawdown management](https://www.tradezella.com/blog/drawdown-management)

4. **Aggregate portfolio Greeks (net delta / vega / theta / gamma) updated on every fill.** Options book P&L is dominated by Greeks at the portfolio level, not per-trade. Budgets per book: delta ±0.30/$NAV, gamma ±0.20, theta $100–$300/day premium-selling, vega regime-conditioned. — [Hedgepoint Greeks](https://hedgepointglobal.com/en/blog/options-greeks-from-delta-to-theta)

5. **Cross-account wash-sale checker.** A loss-sale in IBKR + a rebuy in Moomoo or an IRA within 61 days disallows the loss. NCL has 6 adapters across taxable + tax-advantaged — the cross-check has to live at the portfolio layer, not in any individual adapter. — [ASKramer Law wash-sale](https://www.askramerlaw.com/publications/tax-loss-harvesting-part-ii)

6. **Auto-substitute SPY-style ETF options with SPX-style index options for premium-selling.** Section 1256 60/40 treatment cuts effective tax rate from 37% (ordinary) to ~27% (blended) on identical economic exposure. The morning brief surface is the obvious place to recommend this substitution. — [Green Trader Tax Section 1256](https://greentradertax.com/trader-tax-center/tax-treatment/section-1256-contracts/)

7. **Pace into RRG-rotation signals — 1/3 initial, 1/3 on 5d confirmation of Leading, 1/3 on retest.** The moment a quadrant change prints is the worst risk/reward entry. NCL has the rotation data; what's missing is the pacing rule baked into trade ideas. — [IBKR Traders Insight on RRG](https://www.interactivebrokers.com/campus/traders-insight/securities/macro/chart-advisor-sector-rotation-what-the-rrg-is-telling-us/)

8. **Auto-flag and force-review short options within 0.5% of strike on expiration Friday.** Pin risk + assignment ambiguity in this band is where retail traders most often discover unwanted Monday-morning positions. — [Pin Risk by DTE Phase](https://www.daystoexpiry.com/blog/pin-risk-in-options-managing-expiration-uncertainty-by-dte-phase)

9. **Programmatic tail-hedge (0.5–1% NAV/yr to far-OTM SPX puts, monthly tranches).** Retail systems treat tail-hedging as opportunistic and therefore never own it when needed. The "3 C's" (Cost, Correlation, Convexity) is the institutional discipline; run as a program, not a reaction. — [Resonanz Capital tail-risk hedging](https://resonanzcapital.com/insights/strategic-tail-risk-hedging-building-antifragility-into-institutional-portfolios)

10. **Separate trade-date and settle-date books; surface available buying power against settled cash.** Under T+1, capital "made" yesterday may not be redeployable today. A system that hides this distinction will mis-size on Day 2 of a rapid-turnover sequence. — [Limina Cash & Position Reconciliation](https://www.limina.com/blog/cash-position-reconciliation-guide)

---

## 4. Recommended roadmap — Wave 14J

Prioritized by ratio of (expected risk-leak reduction) / (implementation effort). Each row produces a discrete deliverable so the wave can be split across sessions.

### Tier 0 — Foundation (build first; everything else depends on it)

| Item | Effort | Risk-leak reduction | Notes |
|------|--------|---------------------|-------|
| **J0a — Trading cost ledger** | S (1-2d) | M | Mirror the existing LLM cost_ledger pattern for trading costs (commissions + financing + borrow + assignment + gas + exchange fees). Same JSONL + SQLite double-write. Per-strategy + per-asset-class rollups. Unblocks all telemetry. |
| **J0b — Unified position model with R-fields** | M (2-3d) | H | Add `risk_per_share`, `stop`, `R_dollars`, `R_basis` fields to PositionModel. Adapter boundary computes these; cache stores them; all consumers (brief, scanner, analyst, iOS) read them. Foundation for J1/J2/J3. |
| **J0c — Drawdown bucket as global state** | S (1d) | H | Single source of truth for current portfolio drawdown band (`green` / `caution` / `warning` / `halt`). Computed continuously from snapshots. All 35+ autonomous loops read this before sizing or proposing new ideas. |

### Tier 1 — Risk + execution (the actual gap)

| Item | Effort | Risk-leak reduction | Notes |
|------|--------|---------------------|-------|
| **J1a — Per-strategy heat caps with order-side enforcement** | M (2-3d) | H | Config: total_heat=10%, per-strategy budgets. New endpoint `POST /portfolio/check-order` that scanners + brief + paper-trading + future executor all call before proposing/executing. Hard reject when budget exhausted. |
| **J1b — Tiered drawdown throttle** | S (1-2d) | H | Read J0c bucket → scale sizing multiplier (1.0 / 0.75 / 0.50 / 0.0). Applied in J1a. Brief, GOAT, BRAVO, polymarket scorers respect it. |
| **J1c — Stop framework on every trade idea** | M (2-3d) | M | Every trade idea (brief, scanner, paper) carries price stop + time stop + volatility stop. Renderer emits them. Future executor blocks orders without all three. |
| **J1d — Per-strategy expectancy tracker** | S-M (2d) | M | Trade outcome → strategy attribution. Compute hit rate, profit factor, expectancy in R, SQN. Surface in nightly analyst report + iOS dashboard. Strategy cooldown after N losses. |

### Tier 2 — Options portfolio Greeks

| Item | Effort | Risk-leak reduction | Notes |
|------|--------|---------------------|-------|
| **J2a — Portfolio-level Greeks aggregation** | M (2d) | H | Sum per-position Greeks → net delta/vega/theta/gamma. Cache on every sync. New endpoint `GET /portfolio/greeks`. Configurable per-book budgets. |
| **J2b — IV rank + percentile gating** | S (1d) | M | Pull yfinance/IBKR IV history per held symbol → compute IV rank/percentile. Premium-sell suggestions in brief gated to rank>50 AND pctile>50. Buy/calendar suggestions to rank<30. |
| **J2c — 21-DTE management trigger + pin-risk scanner** | S (1d) | M | Daily scan of held options. Trigger 1: short premium at 21 DTE → "close or roll" candidate. Trigger 2: any short option within 0.5% of strike on Friday → force-review. ntfy on both. |
| **J2d — SPY → SPX substitution prompts** | XS (4h) | L (but high $) | Brief surface adds "consider SPX equivalent" annotation whenever a SPY-options trade idea hits 0.5R+ size. Easy win on tax efficiency. |

### Tier 3 — Sector rotation execution

| Item | Effort | Risk-leak reduction | Notes |
|------|--------|---------------------|-------|
| **J3a — Pacing rule in trade ideas** | S (1d) | M | Trade ideas tied to RRG quadrant get a `pacing_stage` field (1/3-initial, 1/3-confirm, 1/3-retest) + a corresponding sized portion. Brief renderer surfaces all 3 stages with conditions. |
| **J3b — Breadth veto** | XS (2h) | M | Whenever rotation signal would generate a trade idea but breadth < 40% above 50d SMA, suppress the idea or downgrade to "watch-only". Already have breadth data. |
| **J3c — Counter-trend P&L bucket** | S (1d) | L | Tag every trade as with-trend or counter-trend at entry (based on quadrant). Separate expectancy tracking. Calibrates the operator's intuition. |

### Tier 4 — Tax + corporate-event

| Item | Effort | Risk-leak reduction | Notes |
|------|--------|---------------------|-------|
| **J4a — Cross-account wash-sale ledger** | M (2-3d) | M | Append-only wash-sale log: every loss-sale records (symbol, account, date, loss_amount). Every rebuy (any account) within 61 days flagged. Surface in brief + analyst. Critical for tax-efficient harvest. |
| **J4b — Spec-ID at sale time** | M (2d) | L | Per-adapter spec-ID order-tag. Where supported (IBKR yes, Moomoo limited, SnapTrade depends on broker). At minimum surface lot composition for manual selection. |
| **J4c — LT-qualification alert** | XS (2h) | L | Daily scan: positions with cost-basis date in (340, 366) days → "approaching LT" alert. Suggest hold-through if no thesis-break. |
| **J4d — Earnings-proximity sizer** | S (1d) | M | Lookup days-to-earnings per ticker. Brief + scanners apply: long-premium ≤ 0.5R within 7d of earnings; short-premium capped per-cycle. |

### Tier 5 — Crypto + DeFi

| Item | Effort | Risk-leak reduction | Notes |
|------|--------|---------------------|-------|
| **J5a — On-chain transaction journal** | M-L (3-4d) | M | MetaMask adapter pulls Etherscan tx history, indexes per wallet, computes per-position cost basis at block-time price. Gas-spend tracked as cost-basis adjustment. |
| **J5b — Multi-chain aggregation** | S (1-2d) | L | Same wallet across L1/L2 (Arbitrum/Base/Polygon/Optimism via Alchemy or per-chain block explorer). Rollup view. |
| **J5c — LP + liquid-staking valuation** | M (2-3d) | L | Detect Uniswap LP tokens, Aave deposits, stETH/rETH; price-with-yield correctly. Surface as separate `asset_class: "lp"` / `"liquid_staked"`. |

### Tier 6 — Polymarket discipline

| Item | Effort | Risk-leak reduction | Notes |
|------|--------|---------------------|-------|
| **J6a — Kelly sizing from existing scorer + resolution-time discount** | S (1d) | M | planktonxd / weatherbetter scores already compute implied vs estimated probability. Add fractional Kelly sizer with 1/days_to_resolution adjustment. Cap at heat budget from J1a. |
| **J6b — resolution_cluster_id tagging** | XS (3h) | L | Multiple markets on same election or topic cluster get a shared ID. Aggregate exposure cap per cluster. |
| **J6c — Liquidity cap** | XS (2h) | L | Position ≤ 10% of resting opposite-side liquidity. Sizing math reads orderbook depth. |

### Tier 7 — Telemetry + observability (cross-cuts)

| Item | Effort | Risk-leak reduction | Notes |
|------|--------|---------------------|-------|
| **J7a — Trade outcome closed loop** | M (2-3d) | H | Every trade idea from brief/scanners gets a stable `trade_idea_id`. When a position closes, attribute to the idea. Populates J1d expectancy tracker. Backbone of model selection. |
| **J7b — Risk-adjusted return computation** | S (1-2d) | L | Sharpe/Sortino/Calmar/recovery-factor from snapshots.jsonl. Persist to dashboard. |
| **J7c — Slippage tracker (arrival + VWAP)** | M (2d) | L | When a fill comes in: capture quote-at-submit price → compare to fill price (arrival). Capture VWAP over fill window → compare. Per-strategy slippage analysis. |
| **J7d — Drift alerts vs target weights** | S (1d) | M | First require target weights (config). Then daily scan: deviation > tolerance band → suggest rebalance trade in next brief. |

### Tier 8 — Hygiene + resilience

| Item | Effort | Risk-leak reduction | Notes |
|------|--------|---------------------|-------|
| **J8a — Stale-quote detection with per-asset thresholds** | XS (3h) | L | Extend `quote_ok` to `stale_age_seconds` + per-asset thresholds. Quarantine stale positions from sizing math. |
| **J8b — Auth-token expiry tracking** | S (1d) | L | SnapTrade/IBKR/Moomoo/Polymarket token expiries in a single manifest. ntfy 48h before expiry. |
| **J8c — Per-adapter circuit breaker** | XS (2h) | L | N consecutive fails → quarantine adapter X minutes. IBKR already has this; generalize to all 6. |
| **J8d — Trade-date / settle-date split** | M (2-3d) | M | Two views on the position cache: trade-date (immediate) and settle-date (T+1 for equities/options, T+0 crypto, on-resolution Polymarket). iOS shows both. |

### Tier 9 — Tests + ground truth

| Item | Effort | Risk-leak reduction | Notes |
|------|--------|---------------------|-------|
| **J9a — `test_portfolio_manager.py`** | M (2d) | M | Adapter mock, sync loop, quote fallback chain, memory bridge event shapes, FX conversion. The single biggest test gap in the codebase. |
| **J9b — Reconciliation break entities** | M (2d) | L | When two adapters report same symbol with different qty, surface as `PositionBreak` with severity + aging. Don't silently overwrite. |

---

## 5. Suggested wave structure

A pragmatic split (each ≈ a coherent session):

- **Wave 14J Phase 1** (foundation): J0a + J0b + J0c → trading cost ledger + R-fields + drawdown bucket. After this, every other tier has a substrate to bind to.
- **Wave 14J Phase 2** (risk + execution): J1a + J1b + J1c + J1d → heat caps + drawdown throttle + stop framework + per-strategy expectancy. Single biggest risk-leak reduction.
- **Wave 14J Phase 3** (options Greeks): J2a + J2b + J2c + J2d → portfolio Greeks + IV gating + 21-DTE/pin scanner + SPY→SPX prompts.
- **Wave 14J Phase 4** (rotation execution): J3a + J3b + J3c → pacing + breadth veto + counter-trend bucket. Builds on the Wave 14I rotation backend.
- **Wave 14J Phase 5** (tax + corporate-event): J4a + J4d + J4c → wash-sale ledger + earnings-proximity sizer + LT cliff alert. J4b deferred (spec-ID has per-adapter complexity).
- **Wave 14J Phase 6** (crypto + polymarket): J5a + J6a + J6b + J6c → on-chain tx journal + Kelly+resolution sizer + cluster_id + liquidity cap. J5b/J5c deferred to Phase 7 if scope permits.
- **Wave 14J Phase 7** (telemetry): J7a + J7b + J7d → trade outcome loop + risk-adjusted returns + drift alerts. J7c slippage deferred (needs live execution which NCL doesn't have).
- **Wave 14J Phase 8** (hygiene + tests): J8a + J8b + J8c + J8d + J9a → operational polish + test backbone.

Total estimated effort: ~25–35 dev-days across 8 phases. Same arc shape as Wave 14G (desktop, 13 phases) and Wave 14H (Morning Brief Pro, 3 stages + scheduler).

---

## 6. Out of scope for Wave 14J

These are surfaces that came up during the research but are explicitly **NOT** recommended for this wave:

1. **Auto-executor / order routing.** The literature (Trading-R1, Frontiers AI survey, QuantInsti's LLM-portfolio paper) is unanimous: LLM-augmented systems should keep order placement on the human-in-the-loop side. NCL's current pattern (LLM proposes, human disposes) is correct. Building an executor introduces a class of risk that Wave 14J should not absorb.
2. **Backtest harness.** Useful but orthogonal — Wave 14J is about live-portfolio risk management, not strategy R&D. Punt to Wave 15 if needed.
3. **More brokers.** 6 adapters is already coverage-saturated for the operator's needs. Effort goes further into hardening the existing 6 than into adding a 7th.
4. **Market data feed upgrade.** yfinance fallback works; IBKR provides real-time when connected. A dedicated Polygon/IEX subscription would be premature without proven need.
5. **Streaming WebSocket positions.** Polling at 60s is fine for current scale. Move to streaming if J7c slippage analysis indicates the polling lag matters.

---

## 7. Appendix — Sources referenced

A consolidated list of the 18 sources pulled in the deep-dive research, organized by section:

**Multi-broker reconciliation**
- https://www.knightmarkets.com/post/multi-asset-trading-institutional-infrastructure
- https://devexperts.com/case-studies/position-and-trade-reconciliation-subsystem-for-a-retail-broker/
- https://www.limina.com/blog/cash-position-reconciliation-guide
- https://legalclarity.org/what-is-the-difference-between-trade-date-and-settlement-date/
- https://www.finra.org/investors/insights/understanding-settlement-cycles

**Position sizing + risk**
- https://investwithcarl.com/learning-center/investment-basics/dynamic-adaptive-kelly-criterion-bridging-theory-and-practice-for-modern-portfolio-optimization
- https://medium.com/@tmapendembe_28659/kelly-criterion-vs-fixed-fractional-which-risk-model-maximizes-long-term-growth-972ecb606e6c
- https://protraderdashboard.com/blog/portfolio-heat-management/
- https://www.aqr.com/-/media/AQR/Documents/Insights/White-Papers/JAI_Summer_2017_AQR.PDF
- https://www.moodys.com/web/en/us/insights/resources/quantifying-decomposing-and-managing-portfolio-concentration-risk.pdf

**Drawdown discipline + stops**
- https://www.tradezella.com/blog/drawdown-management
- https://www.wallstreetoasis.com/forum/hedge-fund/de-gross-during-drawdown-question
- https://www.luxalgo.com/blog/volatility-stop-indicator-volatility-based-trailing-stop-strategy/
- https://arxiv.org/pdf/1701.03960
- https://bookmap.com/blog/trading-circuit-breakers-and-halts-how-they-protect-markets-and-what-traders-should-know

**Options portfolio construction**
- https://hedgepointglobal.com/en/blog/options-greeks-from-delta-to-theta
- https://tradefundrr.com/options-greeks-analysis/
- https://www.civolatility.com/p/iv-rank-explained-a-complete-guide
- https://www.daystoexpiry.com/blog/pin-risk-in-options-managing-expiration-uncertainty-by-dte-phase
- https://resonanzcapital.com/insights/strategic-tail-risk-hedging-building-antifragility-into-institutional-portfolios
- https://thehedgefundjournal.com/managing-tail-risk-with-options-products/

**Sector rotation execution**
- https://chartschool.stockcharts.com/table-of-contents/chart-analysis/chart-types/relative-rotation-graphs-rrg-charts
- https://www.interactivebrokers.com/campus/traders-insight/securities/macro/chart-advisor-sector-rotation-what-the-rrg-is-telling-us/
- https://articles.stockcharts.com/article/visualizing-breadth-and-rotation-using-rrg/
- https://cmtassociation.org/chartadvisor/sector-rotation-what-the-rrg-is-telling-us/

**Earnings + corporate-event**
- https://www.schaeffersresearch.com/content/education/2025/12/19/the-mechanics-of-implied-volatility-crush-in-options-trading
- https://www.moomoo.com/us/learn/detail-approaching-post-earnings-iv-crush-with-options-117911-250480037
- https://support.spotgamma.com/hc/en-us/articles/15249330755859-IV-Crush-Explained-Key-Concepts
- https://investor.vanguard.com/investor-resources-education/online-trading/corporate-actions
- https://www.finantrix.com/articles/how-to-automate-corporate-action-processing-dividends-splits-mergers

**Tax-aware**
- https://www.countrytaxcalc.com/tax-guides/usa/wash-sale-rule-guide-2026/
- https://www.fidelity.com/learning-center/personal-finance/wash-sales-rules-tax
- https://www.askramerlaw.com/publications/tax-loss-harvesting-part-ii
- https://greentradertax.com/trader-tax-center/tax-treatment/section-1256-contracts/
- https://www.terms.law/Trading-Legal/guides/section-1256-contracts.html
- https://www.quantvps.com/blog/60-40-tax-treatment-futures-traders

**Crypto + DeFi**
- https://cryptofolio.ai/blog/defi-tax-guide
- https://beancount.io/blog/2026/04/01/defi-accounting-guide-tax-compliance-decentralized-finance
- https://chainglance.com/blog/track-metamask-wallet-performance-2026/
- https://www.bpm.com/insights/defi-accounting/
- https://threesigma.xyz/blog/lrt's/liquid-staking-vs-restaking-lsts-vs-lrts

**Prediction markets**
- https://managebankroll.com/blog/polymarket-kelly-criterion-position-sizing
- https://www.prevayo.com/blog/polymarket-complete-guide-2026-strategies-tips-how-to-win
- https://web3.bitget.com/en/academy/polymarket-trading-strategies-how-to-make-money-on-polymarket

**Telemetry + observability**
- https://blog.quantinsti.com/performance-metrics-risk-metrics-optimization/
- https://www.itrader.com/en/blog/sharpe-sortino-calmar-ratios-and-expectancy-measuring-real-alpha-in-trading
- https://www.dakotaridgecapital.com/fearless-investor/portfolio-risk-ratios-sharpe-sortino-calmar
- https://www.quantitativebrokers.com/blog/a-brief-history-of-implementation-shortfall
- https://www.talos.com/insights/execution-insights-through-transaction-cost-analysis-tca-benchmarks-and-slippage
- https://www.thetradenews.com/thought-leadership/vwap-arrival-a-dynamic-approach-to-reducing-arrival-slippage/

**Operational hygiene**
- https://www.kitces.com/blog/best-opportunistic-rebalancing-frequency-time-horizons-vs-tolerance-band-thresholds/
- https://www.fa-mag.com/news/optimal-rebalancing-with-tolerance-bands-29623.html
- https://emacintl.com/broker-outages-what-to-do-when-platforms-go-down
- https://zuplo.com/learning-center/implementing-seamless-api-failover-systems
- https://zuplo.com/learning-center/api-gateway-resilience-fault-tolerance

**AI / LLM augmentation**
- https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2025.1608365/full
- https://arxiv.org/html/2505.07078v5
- https://arxiv.org/pdf/2509.11420
- https://www.researchgate.net/publication/394826084_Integrating_LLM-Based_Time_Series_and_Regime_Detection_with_RAG_for_Adaptive_Trading_Strategies_and_Portfolio_Management
- https://blog.quantinsti.com/application-llm-portfolio-management-thematic-index/
