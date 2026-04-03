# NCL Feedback Contract — Pillar Reporting Interface

**Purpose**: Formal schemas for feedback flowing from NCC, BRS, and AAC back to NCL.
**Authority**: Feedback is interpreted by NCL, never executes automatic actions.
**Validation**: JSON Schema + semantic validation (contradiction detection).

---

## Overview

| Report Type | Source | Receiver | Frequency | Purpose |
|-----------|--------|----------|-----------|---------|
| Execution Report | NCC | NCL | 2x daily (morning + EOD) | Ground truth on mandate progress |
| Economic Report | BRS | NCL | Daily | Revenue, cost, conversion, churn signals |
| Capital Report | AAC | NCL | Daily | P&L, ROI, position status, market signals |

---

## Schema 1: NCC Execution Report (NCC → NCL)

**Format**: YAML
**Location**: `feedback-synthesis/ncc-reports/NCC-*.yaml`
**Validation**: Submitted report → NCL validation layer → acceptance or REJECT

```yaml
# Header
report_id: NCC-2026-002
report_type: "execution_truth"
source: "NCC"
created_at: "2026-04-01T17:00:00Z"
period: "2026-04-01 (morning to EOD)"

# Mandate Tracking
mandates_active: 4
mandates_detail:
  - mandate_id: MANDATE-2026-001
    title: "Launch Revenue Scanner — DIGITAL-LABOUR"
    status: "executing"
    progress_pct: 70
    progress_detail:
      - "Task detection module: 18/20 task types complete (MVP phase)"
      - "Execution engine: Browser RPA prototype working, API integration 40% done"
      - "Dashboard: Wireframes done, React components 30% done"
    on_track: true
    timeline_health: "green"  # green, yellow, red
    blockers: []
    risks:
      - "API rate limiting from freelance platforms (Upwork) may slow integration"
    next_milestone: "Alpha delivery 2026-04-15 (on track)"
    confidence: 0.82

  - mandate_id: MANDATE-2026-002
    title: "Ship Crimson Compass (Spy Thriller Game)"
    status: "executing"
    progress_pct: 45
    progress_detail:
      - "Asset optimization: In progress (2-day slip from original timeline)"
      - "Gameplay mechanics: 95% complete"
      - "Multiplayer networking: 70% complete"
    on_track: false
    timeline_health: "yellow"  # 2-day slip expected
    blockers:
      - "Asset optimization taking longer than estimated (GPU compression complexity)"
    risks:
      - "May slip into May if optimization not resolved"
    next_milestone: "Closure of optimization blocker (2026-04-05, revised)"
    confidence: 0.70

  - mandate_id: MANDATE-2026-004
    title: "QUASAR IDE v0.1"
    status: "executing"
    progress_pct: 65
    progress_detail:
      - "UX milestone hit early (3 days ahead)"
      - "Now in performance optimization phase"
      - "MWP integration reduces onboarding time 40% vs baseline"
    on_track: true
    timeline_health: "green"
    blockers: []
    risks: []
    next_milestone: "Beta launch 2026-05-01 (tracking ahead)"
    confidence: 0.90

  - mandate_id: MANDATE-2026-005
    title: "AAC War Room Scenario Engine"
    status: "executing"
    progress_pct: 55
    progress_detail:
      - "v0.2 deployed and tested on 3 geopolitical scenarios"
      - "Model accuracy: 74% (above 70% threshold)"
      - "Ready for capital deployment (risk-limited)"
    on_track: true
    timeline_health: "green"
    blockers: []
    risks: []
    next_milestone: "Live trading 2026-04-30 (on track)"
    confidence: 0.78

# Resource Utilization
team_status:
  total_fte: 8.5
  by_mandate:
    MANDATE-2026-001: 2.0  # Engineer A (50%), Engineer B (50%)
    MANDATE-2026-002: 3.0  # Game team
    MANDATE-2026-004: 2.0  # IDE team
    MANDATE-2026-005: 1.5  # AAC/trading team
  available_capacity: 0.0  # All hands allocated

# Infrastructure & Cost
costs_this_period: 180  # USD (API calls, compute)
cost_budget: 800  # per-month budget from NCL
cost_burn_rate: 0.22  # monthly burn of budget (sustainable)

# Signals & Insights
signals:
  - signal: "UNI research suggests path B is faster for task classification"
    source: "UNI feedback"
    confidence: 0.75
    recommendation: "Consider pivot to path B for MANDATE-2026-001"

  - signal: "Competitor entered market with 15 task types (less than our 20)"
    source: "Awarebot-FPC intelligence scan"
    confidence: 0.88
    recommendation: "Accelerate to 50 task types ASAP to establish market lead"

  - signal: "GPU compression bottleneck resolved with vendor library"
    source: "NCC engineering team"
    confidence: 0.92
    recommendation: "MANDATE-2026-002 timeline can recover"

# Recommended Actions (for NCL synthesis)
recommended_adjustments:
  - "Extend MANDATE-2026-002 deadline by 2 days (2026-07-02)"
  - "Spike UNI research into task classification path B (1-week effort)"
  - "Increase marketing spend for DIGITAL-LABOUR (coordinate with BRS)"
  - "Greenlight AAC capital deployment for geopolitical scenarios"

# Validation Fields
ncc_confidence: 0.78  # NCC self-assessed confidence in this report
approved_by: "NCC / CTO"
```

**Validation Rules**:
1. `report_id` format: `NCC-YYYY-###`
2. All `mandate_id` must exist in active-mandates.md
3. `progress_pct`: 0–100 integer
4. `confidence` and all signal confidence: 0.0–1.0 float
5. `timeline_health`: green, yellow, red only
6. `costs_this_period` must be positive number

---

## Schema 2: BRS Economic Report (BRS → NCL)

**Format**: YAML
**Location**: `feedback-synthesis/brs-reports/BRS-*.yaml`
**Validation**: Revenue/cost must be >= 0, rates must be 0.0–1.0

```yaml
# Header
report_id: BRS-2026-003
report_type: "economic_signals"
source: "BRS"
created_at: "2026-04-01T18:00:00Z"
period: "2026-03"  # March 2026

# Revenue & Profitability
revenue: 250  # USD (monthly recurring + one-time)
revenue_by_source:
  - product: "DIGITAL-LABOUR"
    revenue: 200
  - product: "Game royalties (Archive of Echoes)"
    revenue: 50
costs: 80  # USD (API, infrastructure, customer acquisition)
gross_profit: 170  # revenue - costs
gross_margin: 0.68  # 68% margin
net_income: 150  # after other SG&A
net_margin: 0.60

# Customer Metrics
customers_total: 12
customers_active: 11
customers_acquired_mtd: 2
customers_churned_mtd: 0
nrr: 1.04  # Net Revenue Retention (104% — some customers paying more)

# Conversion & Activation
visitors: 850
conversions: 127
conversion_rate: 0.15  # 15%
conversion_rate_target: 0.20  # Our goal

# Churn
churn_rate_mtd: 0.08  # 8% (within acceptable range 5–10%)
ltv_estimate: 180  # Customer Lifetime Value in USD
payback_period: 0.4  # months (cost per customer / monthly LTV)

# Market Signals
market_signals:
  - signal: "DIGITAL-LABOUR demand growing 3% week-over-week"
    confidence: 0.85
    source: "Customer feedback + web analytics"

  - signal: "Competitor launched similar automation service"
    confidence: 0.92
    source: "Awarebot-FPC market scan"

  - signal: "Upwork/Fiverr raising rates → pushes more users to automation"
    confidence: 0.78
    source: "Market research (Perplexity query)"

# Recommended Product Actions
recommended_actions:
  - "Increase task type coverage ASAP (hit 50 types to block competitor)"
  - "Launch premium tier ($49/month) for power users"
  - "A/B test pricing ($9 vs $15/month) to optimize conversion"
  - "Add referral program (predict 30% conversion boost)"

# Budget & Spend
marketing_spend: 20  # USD
marketing_roi: 5.0  # $20 spend → $100 incremental revenue
customer_acquisition_cost: 15  # USD per customer
burn_rate_acceptable: true  # Burn is sustainable

# Forecast (90-day outlook)
forecast_q2:
  revenue_target: 800  # Q2 total ($250/mo baseline + growth)
  customers_target: 35
  churn_risk: "low"  # Confidence in forecast

# Signals for NCL Strategy
for_ncl_strategy:
  - "Recommend prioritize MANDATE-2026-001 (revenue scaling opportunity)"
  - "Market window closing; competitor moves fast"
  - "Churn is low; product-market fit improving"
  - "Suggest increase marketing spend to 50% of revenue"

# Approval
brs_confidence: 0.82
approved_by: "BRS / VP Revenue"
```

**Validation Rules**:
1. `report_id` format: `BRS-YYYY-###`
2. All revenue/cost fields >= 0
3. All rates (churn, conversion, margin, NRR): 0.0–1.0 float
4. `revenue >= costs` (unprofitable is allowed but flagged)
5. `nrr` should be > 1.0 for healthy business (optional)

---

## Schema 3: AAC Capital Report (AAC → NCL)

**Format**: YAML
**Location**: `feedback-synthesis/aac-reports/AAC-*.yaml`
**Validation**: P&L numbers, ROI %, positions tracked

```yaml
# Header
report_id: AAC-2026-001
report_type: "capital_performance"
source: "AAC"
created_at: "2026-04-01T19:00:00Z"
period: "2026-03"  # March 2026

# Performance Summary
capital_deployed: 5000  # USD total deployed
pnl: 1200  # USD profit/loss (+$1200 profit)
roi: 0.24  # 24% monthly ROI
roi_annualized: 0.0  # 0% YTD (only one month of data)
win_rate: 0.67  # 67% of positions profitable
avg_holding_period: 8  # days

# Positions (Current Holdings)
positions:
  - ticker: "BTC"
    entry_price: 65000
    entry_date: "2026-03-15"
    current_price: 68000
    quantity: 0.5
    entry_value: 32500
    current_value: 34000
    pnl: 1500
    pnl_pct: 0.046
    thesis: "Macro: Fed pivot signaling lower rates in Q2. Geopolitical premium."
    confidence: 0.80
    position_sizing: "50% of portfolio"

  - ticker: "TSLA"
    entry_price: 245  # Call spread
    entry_date: "2026-03-20"
    current_price: 242
    quantity: 5  # 5 contracts
    entry_value: 1225
    current_value: 1100
    pnl: -125
    pnl_pct: -0.10
    thesis: "Mean reversion play; earnings volatility opportunity"
    confidence: 0.60
    position_sizing: "20% of portfolio"
    recommendation: "Close on next bounce; sentiment deteriorating"

  - ticker: "Geopolitical War Bonds"
    entry_price: 1.05
    entry_date: "2026-03-01"
    current_price: 1.12
    quantity: 2700  # Notional value
    entry_value: 1412
    current_value: 1500
    pnl: 88
    pnl_pct: 0.062
    thesis: "Geopolitical tail hedge; scenario engine 73% accuracy"
    confidence: 0.73
    position_sizing: "30% of portfolio"
    recommendation: "Hold; scenario probabilities unchanged"

# Market Intelligence
market_intelligence:
  - signal: "Fed signals hike cycle pivot in Q2 2026"
    confidence: 0.88
    source: "FOMC communication analysis (Gemini)"
    implication: "Bullish for risk assets; BTC beneficiary"

  - signal: "China volatility spike on trade tensions"
    confidence: 0.75
    source: "Market data + Grok news feed"
    implication: "Opportunity in Chinese tech stocks (BABA, PDD)"

  - signal: "Ukraine ceasefire negotiations faltering"
    confidence: 0.65
    source: "Intelligence feed (Awarebot-FPC)"
    implication: "War bond premium may expand further"

# Risk Assessment
portfolio_risk:
  var_95: 0.08  # 95% confidence max loss in 1 day: 8%
  sharpe_ratio: 2.1  # Risk-adjusted return quality
  max_drawdown_mtd: 0.04  # 4% max loss month-to-date
  correlation_to_market: 0.4  # Low correlation (diversified)

# Recommended Actions
recommended_actions:
  - "Close TSLA call spread on next rally (avoid theta decay beyond 5 days)"
  - "Increase BTC allocation to 1 BTC (thesis strengthening)"
  - "Investigate Chinese tech opportunity (BABA, PDD, Alibaba Cloud)"
  - "Maintain war bonds at current size (tail hedge value stable)"

# Budget & Cost
management_fee: 0  # AAC is internal (no external fund fees)
cost_of_capital: 0  # Internal capital (no interest)
total_overhead: 0

# Strategy for Next Month
april_outlook:
  macro_thesis: "Fed pivot + geopolitical premium → risk-on environment"
  portfolio_targets:
    btc: "0.7–1.0 BTC"
    equities: "20–30% (China tech focus)"
    bonds: "15–20% (war hedge)"
  cash_reserve: "10–20% for opportunity sizing"

# Approval
aac_confidence: 0.76
approved_by: "AAC / Chief Investment Officer"
```

**Validation Rules**:
1. `report_id` format: `AAC-YYYY-###`
2. All PnL numbers can be positive or negative
3. `roi`, `win_rate`, all confidence: 0.0–1.0 float
4. `pnl_pct` = pnl / entry_value
5. Sum of position_sizing should ≈ 1.0 (100% allocated)

---

## Feedback Synthesis Workflow (NCL Processing)

```
1. INGEST (feedback-synthesis/ncc-reports, brs-reports, aac-reports)
   ├─ Validate YAML schema
   ├─ Check for missing required fields
   └─ Flag contradictions with previous reports

2. ENRICH (cross-pillar signals)
   ├─ Cross-reference NCC blockers with BRS/AAC market signals
   ├─ Identify mandate-level insights (e.g., competitor move → accelerate)
   └─ Log signal convergence (when multiple pillars confirm same insight)

3. SYNTHESIZE (interpret for strategy)
   ├─ Integrate all signals into coherent narrative
   ├─ Flag risks and opportunities
   ├─ Recommend mandate adjustments
   └─ Update active-mandates.md with latest feedback

4. COMMUNICATE (back to NCC)
   ├─ Generate mandate adjustment package (if needed)
   ├─ Log synthesis in Paperclip audit trail
   ├─ Alert NATRIX if P1 mandate risk or opportunity
   └─ Update memory-processing/long-term with new insights
```

---

## Contradiction Detection

**NCL validation layer flags contradictions:**

Example:
- NCC reports: "MANDATE-2026-001 on track, 70% progress"
- BRS reports: "DIGITAL-LABOUR revenue flat, no growth from automation"
- **Flag**: "Progress reported but revenue unchanged. Possible mismeasurement. Ask NCC for execution details."

---

## Audit Trail

All feedback reports logged in Paperclip activities with:
- Report ID
- Timestamp received
- Validation status (PASS/FAIL)
- Synthesis notes
- Mandates affected
- Action items generated
