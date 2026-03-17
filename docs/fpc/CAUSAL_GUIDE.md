# Causal Inference Guide — DoWhy + EconML

## Overview

The council uses two causal inference frameworks:
- **DoWhy** — Causal DAG → Identify → Estimate → Refute (ATE)
- **EconML** — Heterogeneous treatment effects (CATE)

## DoWhy — Average Treatment Effect

### Step 1: Build a Causal DAG
Define the causal relationships in your domain:

```
Promo → Demand ← Price
  ↑               ↑
Season          Competition
```

### Step 2: Estimate ATE

```python
from src.causal import run_causal_estimate

result = run_causal_estimate(
    df=panel_df,
    treatment="promo",
    outcome="demand",
    common_causes=["season", "competition", "price"],
    refute=True,
)
# result.estimate: ATE (e.g., "promo increases demand by 12.5 units on average")
# result.refutation_passed: True if placebo test passes
```

### Step 3: Refutation Tests

Refutations check if the causal estimate is robust:

| Test | What it Checks | Pass Criteria |
|---|---|---|
| Placebo treatment | Random treatment has no effect | Placebo ATE ≈ 0 |
| Random common cause | Adding a random confounder doesn't change estimate | Estimate stable |
| Data subset | Effect consistent across data subsets | Similar ATE in subsets |

**If any refutation fails**, the causal estimate may be spurious. Investigate data quality
and DAG structure before trusting the result.

## EconML — Heterogeneous Treatment Effects (CATE)

### When to Use
ATE tells you the AVERAGE effect. CATE tells you how the effect VARIES:
- "Promos work better on weekdays than weekends"
- "Price sensitivity is higher in segment A than segment B"

### Estimate CATE

```python
from src.causal.econml_panel import estimate_cate

result = estimate_cate(
    df=panel_df,
    treatment="promo",
    outcome="demand",
    features=["segment", "day_of_week", "price_tier"],
    method="dml",  # or "forest" for Causal Forest
)
# result.cate_values: per-observation treatment effect
# result.ate: average across all observations
# result.ci_lower, result.ci_upper: confidence intervals
```

### Method Selection

| Method | Best For | Interpretability |
|---|---|---|
| `dml` (LinearDML) | Linear heterogeneity | High — coefficients interpretable |
| `forest` (CausalForestDML) | Non-linear heterogeneity | Medium — feature importance available |

## What-If Scenarios

Combine causal estimates with the council forecast:

1. **Baseline forecast**: Council predicts demand for next 28 days
2. **Intervention**: "What if we increase promo by 10%?"
3. **Causal estimate**: DoWhy/EconML estimates the treatment effect
4. **Adjusted forecast**: Baseline + estimated treatment effect
5. **Writeback preview**: Show the diff before committing

## Best Practices

1. **DAG first** — always start with a causal DAG, not just correlations
2. **Refute everything** — never trust an unrefuted estimate
3. **Domain experts review DAGs** — causal structure needs domain knowledge
4. **CATE for segmented decisions** — if the intervention should vary by segment, use EconML
5. **Confidence intervals matter** — wide CIs mean high uncertainty about the effect
6. **Iterate** — add confounders, test alternative DAGs, refine
