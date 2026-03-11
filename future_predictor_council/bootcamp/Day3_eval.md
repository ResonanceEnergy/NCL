# Day 3 — Eval

> **Goal**: XAI dossier, full backtest report, causal refuters.

---

## Morning (9:00–12:00)

### 1. SHAP Feature Importance (9:00–10:30)
- **Exercise**: Run SHAP analysis on the best-performing model
  - Global feature importance: which features matter most across all series?
  - Local importance: for a specific forecast, which features drove the prediction?
  - Generate SHAP summary plot and force plot
- **Output**: SHAP importance ranking

### 2. TimeSHAP Sequential Attribution (10:30–12:00)
- **Exercise**: Run TimeSHAP on a neural model forecast
  - Event-level: which time steps were most influential?
  - Feature-level: which features at which time steps mattered?
  - Cell-level: internal model dynamics
- **Output**: TimeSHAP attribution report
- Note: TimeSHAP requires a callable model function — may need adapter

## Afternoon (13:00–17:00)

### 3. Causal Analysis with DoWhy (13:00–14:30)
- **Exercise**: Build a causal DAG for your domain
  - Define treatment (e.g., promo, price change)
  - Define outcome (e.g., demand, revenue)
  - Identify common causes (confounders)
  - Run ATE estimation: "What is the average effect of a promo on demand?"
- **Output**: Causal DAG diagram + ATE estimate

### 4. Refutation Tests (14:30–15:30)
- **Exercise**: Run DoWhy refutation suite
  - Placebo treatment: does a random treatment show no effect? (Should be ~0)
  - Random common cause: does adding a random confounder change the estimate?
  - Subset validation: is the effect consistent across data subsets?
- **Output**: Refutation report (pass/fail for each test)

### 5. EconML Heterogeneous Effects (15:30–16:30)
- **Exercise**: Estimate CATE with EconML
  - "Does the promo effect vary by segment/region/season?"
  - Use LinearDML or CausalForestDML
  - Identify which segments respond most to the intervention
- **Output**: CATE distribution + segment analysis

### 6. XAI Dossier Assembly (16:30–17:00)
- **Exercise**: Compile all XAI outputs into a single dossier
  - SHAP global + local importance
  - TimeSHAP sequential attribution
  - DoWhy ATE + refutation results
  - EconML CATE distribution
- **Output**: Complete XAI dossier document

---

## Day 3 Deliverables Checklist
- [ ] SHAP global and local feature importance analysis
- [ ] TimeSHAP sequential attribution report (or plan if model adapter needed)
- [ ] DoWhy causal DAG + ATE estimate
- [ ] Refutation tests: placebo, random cause, subset (all should pass)
- [ ] EconML CATE analysis for heterogeneous effects
- [ ] Assembled XAI dossier combining all analyses
