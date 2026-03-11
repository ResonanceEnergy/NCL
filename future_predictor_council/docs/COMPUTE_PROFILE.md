# Compute Profile

## Local Machine

| Component | Spec |
|---|---|
| CPU | AMD Ryzen 5 7530U (6C/12T, 2.0–4.5 GHz) |
| RAM | 16 GB DDR5 |
| GPU | AMD Radeon Graphics (integrated, 2 CUs) |
| Storage | NVMe SSD |
| OS | Windows 11 |

## Model Tiering

### GREEN — Runs comfortably on local hardware
| Model | CPU Time | RAM Usage | Notes |
|---|---|---|---|
| StatsForecast (AutoARIMA/ETS/Theta) | <1 min for 1K series | ~500 MB | Highly optimized C/Rust core |
| Silverkite (Greykite) | ~2 min for 1K series | ~1 GB | Ridge regression + changepoints |
| DoWhy (causal estimation) | <30s | ~200 MB | Linear regression backend |
| EconML (LinearDML) | <1 min | ~500 MB | Scikit-learn backend |

### YELLOW — Runs locally but slowly
| Model | CPU Time | RAM Usage | Notes |
|---|---|---|---|
| PatchTST (NeuralForecast) | ~10 min/100 steps | ~4 GB | PyTorch on CPU, reduce max_steps |
| TFT (NeuralForecast) | ~15 min/100 steps | ~4 GB | More parameters than PatchTST |
| EconML (CausalForest) | ~5 min | ~2 GB | Random forest under the hood |
| SHAP (KernelExplainer) | ~10 min | ~2 GB | Model-agnostic but slow |

### RED — Requires cloud burst
| Model | Min RAM | Min GPU | Recommended Instance | Hourly Cost |
|---|---|---|---|---|
| TimesFM 2.5 | 32 GB | — | r6i.2xlarge (64 GB) | $0.504 |
| Chronos-2 | 16 GB | A10G (24 GB) | g5.xlarge | $1.006 |

## Weekly Cost Projections

| Scenario | Local Hours | Cloud Hours | Weekly Cost |
|---|---|---|---|
| Baselines only | ~2h | 0 | $0 |
| + Neural (local) | ~5h | 0 | $0 |
| + TimesFM burst | ~5h | 0.5h | ~$0.25 |
| + Chronos-2 burst | ~5h | 0.5h | ~$0.50 |
| Full council | ~5h | 1h | ~$0.75 |
| Heavy experimentation | ~10h | 5h | ~$4.50 |

All scenarios well within the $50/week budget cap.
