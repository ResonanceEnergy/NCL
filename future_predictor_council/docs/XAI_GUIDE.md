# XAI Guide — Explainability for the Future Predictor Council

## Overview

The council uses two complementary XAI approaches:
- **SHAP** — Global and local feature importance for tabular/tree models
- **TimeSHAP** — Sequential attribution for neural time series models

## SHAP (SHapley Additive exPlanations)

### Global Feature Importance
Shows which features matter most across ALL predictions:

```python
from src.xai.shap_panel import compute_shap

result = compute_shap(model, X_test, method="tree")
# result.shap_values: array of SHAP values per feature per sample
# result.feature_names: list of feature names
```

**Interpretation**: Features with higher mean |SHAP value| have more influence on predictions.

### Local Feature Importance
Shows which features drove a SPECIFIC prediction:

```python
import shap
shap.force_plot(result.base_value, result.shap_values[0], X_test.iloc[0])
```

**Interpretation**: Red features push the prediction up; blue features push it down.

### Method Selection
| Method | Best For | Speed |
|---|---|---|
| `tree` | Tree-based models (XGBoost, LightGBM) | Fast |
| `linear` | Linear models | Fast |
| `kernel` | Any model (model-agnostic) | Slow |

## TimeSHAP

### Sequential Attribution
For neural models (PatchTST, TFT), TimeSHAP explains which TIME STEPS and FEATURES at those steps influenced the forecast:

```python
from src.xai import run_timeshap

result = run_timeshap(
    model_fn=model.predict,  # Callable
    data=input_sequence,     # DataFrame of the input window
    pruning_idx=50,          # How far back to look
    nsamples=1000,           # SHAP sampling budget
)
# result.event_level: which time steps mattered
# result.feature_level: which features at each step
# result.cell_level: internal model state attribution
```

### Interpretation Guide

**Event-level**: "The last 3 days of data drove 70% of the forecast" — useful for
understanding how much history the model actually uses.

**Feature-level**: "Promo on Day -3 had the largest positive attribution" — useful
for understanding which features at which time steps influenced the forecast.

**Cell-level**: "Hidden state neuron #42 captured the weekly seasonal pattern" —
useful for model debugging (advanced).

## Best Practices

1. **Always explain alongside forecasts** — a prediction without explanation is a liability
2. **Compare SHAP global vs. local** — global shows general patterns; local shows edge cases
3. **Validate against domain knowledge** — if SHAP says "temperature" matters for indoor sales, investigate
4. **Use SHAP for model selection** — models that rely on sensible features are more trustworthy
5. **TimeSHAP for temporal models only** — don't use on StatsForecast
