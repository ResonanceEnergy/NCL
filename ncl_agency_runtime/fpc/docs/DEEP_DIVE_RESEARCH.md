# Deep Dive Research — Future Predictor Models, Protocols, Techniques & APIs

> Comprehensive landscape scan of the forecasting ecosystem.  
> Generated from internet research covering 25+ projects, models, and APIs.  
> Each section maps to integration opportunities in **future-predictor-council**.

---

## Table of Contents

1. [Nixtla Ecosystem (statsforecast family)](#1-nixtla-ecosystem)
2. [Foundation Models (Zero-Shot / Pretrained)](#2-foundation-models-zero-shot--pretrained)
3. [Comprehensive Frameworks](#3-comprehensive-frameworks)
4. [Classical / Additive Models](#4-classical--additive-models)
5. [Causal Inference & Counterfactual](#5-causal-inference--counterfactual)
6. [Explainability / XAI](#6-explainability--xai)
7. [Ensemble & Council Techniques](#7-ensemble--council-techniques)
8. [Real-Time Data Sources & APIs](#8-real-time-data-sources--apis)
9. [Prediction Markets & Crowd Forecasting](#9-prediction-markets--crowd-forecasting)
10. [Integration Roadmap](#10-integration-roadmap)

---

## 1. Nixtla Ecosystem

The Nixtla team maintains a modular suite that directly extends what we already use (`statsforecast`).

| Library | Stars | Version | What It Adds |
| --- | --- | --- | --- |
| **statsforecast** | 4.5k+ | ≥2.0 | AutoARIMA, AutoETS, AutoCES, AutoTheta, AutoMFLES, AutoTBATS, GARCH/ARCH, MSTL, sparse/intermittent models. **500× faster than Prophet, 20× faster than pmdarima.** Spark/Dask/Ray backends. |
| **neuralforecast** | 4k+ | 3.1.5 | 30+ neural architectures — NBEATS, NHITS, TFT, PatchTST, iTransformer, TimesNet, DeepAR, TSMixer, TimeLLM. Probabilistic forecasting, auto HPO (Ray/Optuna). |
| **mlforecast** | 1.2k+ | 1.0.31 | Scalable ML-based forecasting (LightGBM, XGBoost, sklearn). Feature engineering (lags, transforms, date features), conformal prediction intervals. |
| **hierarchicalforecast** | 737+ | 1.5.1 | Reconciliation methods — BottomUp, TopDown, MiddleOut, MinTrace, ERM. Probabilistic coherent methods (Bootstrap, PERMBU, Conformal). |
| **utilsforecast** | — | 0.2.15 | Evaluation (MAPE, MASE, MSSE, RMSSE), plotting, preprocessing (fill_gaps), synthetic data generation. |

### Nixtla Integration Opportunities

- **neuralforecast** → Add as `NeuralForecastStrategy` alongside existing `StatsForecastStrategy`. Support NBEATS, NHITS, PatchTST as council members.
- **mlforecast** → Add as `MLForecastStrategy` for tree-based ensemble approaches (LightGBM/XGBoost).
- **hierarchicalforecast** → Apply reconciliation when forecasting hierarchical categories (sector → subsector → company).
- **utilsforecast** → Replace/augment `src/eval/metrics.py` with standardized MAPE/MSSE/RMSSE from Nixtla.

---

## 2. Foundation Models (Zero-Shot / Pretrained)

These are pretrained on massive time-series corpora and can forecast without fine-tuning.

| Model | Origin | Stars | Params | Key Feature |
| --- | --- | --- | --- | --- |
| **Chronos-2** | Amazon | 4.9k | 9M–710M | Univariate + multivariate + covariates. Chronos-Bolt: 250× faster, 20× more memory efficient. `pip install chronos-forecasting` |
| **TimesFM 2.5** | Google | 10k | 200M | Decoder-only, 16k context length, continuous quantile forecasts up to 1k horizon. Available in BigQuery. `pip install timesfm` |
| **MOMENT** | CMU (ICML 2024) | 720 | S/B/L | Multi-task: forecasting, classification, anomaly detection, imputation. Patch-based. `pip install momentfm` |
| **Moirai / Moirai-MoE / Moirai-2** | Salesforce (ICML 2024 Oral) | 1.4k | S/B/L | Universal time series transformer. MoE variant, fine-tuning support. `pip install uni2ts` |
| **Lag-Llama** | Open-source (first TS foundation model) | 1.6k | — | LLaMA-based decoder for probabilistic TS forecasting. Zero-shot + fine-tuning. RoPE scaling for variable context. |
| **Granite-TSFM / TinyTimeMixer** | IBM | 806 | — | PatchTST, PatchTSMixer, TTM. HuggingFace transformers integration. MCP server included. `pip install tsfm_public` |

### Foundation Model Integration Opportunities

- **Chronos-2** → Add as `ChronosStrategy` — zero-shot forecasting council member. No training data needed.
- **TimesFM 2.5** → Add as `TimesFMStrategy` — Google's foundation model, excellent for long-horizon forecasts.
- **MOMENT** → Multi-task strategy: can also detect anomalies in signal data.
- **Foundation Model Council Member** → Each foundation model becomes a "council advisor" that votes without training. The council aggregates their probabilistic forecasts.

---

## 3. Comprehensive Frameworks

Full-stack libraries covering multiple tasks under unified APIs.

| Framework | Stars | Scope |
| --- | --- | --- |
| **Darts** (Unit8) | 9.2k | 50+ models from ARIMA to transformers. Built-in Chronos2Model, TimesFM2p5Model wrappers. NaiveEnsembleModel, RegressionEnsembleModel, ConformalNaiveModel. Anomaly detection, hierarchical reconciliation, SHAP explainability. |
| **sktime** | 9.6k | Unified interface: forecasting, classification, clustering, anomaly detection, changepoint detection. 527+ contributors. sklearn-compatible. |
| **Merlion** (Salesforce) | 4.5k | Forecasting + anomaly detection + change point detection. DefaultDetector, DefaultForecaster, AutoML, ensembles, exogenous regressors, PySpark backend. |

### Framework Integration Opportunities

- **Darts** → Use as the orchestration layer for multi-model ensembles. Built-in NaiveEnsembleModel could power council aggregation logic.
- **sktime** → Use as the common interface layer — all strategies wrapped as sktime forecasters for interoperability.
- **Merlion** → Add anomaly detection and change point detection to the signal processing pipeline.

---

## 4. Classical / Additive Models

| Model | Stars | Notes |
| --- | --- | --- |
| **Prophet** (Meta/Facebook) | 20.1k | Additive model: trend + seasonality + holidays. v1.3.0 (Jan 2026). Stan-based. The original "forecasting at scale." |
| **NeuralProphet** | 4.3k | PyTorch successor to Prophet. AR-Net, lagged/future regressors, events, global modeling, quantile regression. Human-in-the-loop design. |

### Classical Model Integration Opportunities

- **Prophet** → Add as `ProphetStrategy` for human-interpretable baseline. Strong seasonality + holiday handling.
- **NeuralProphet** → Add as `NeuralProphetStrategy` for iterative human-in-the-loop refinement.

---

## 5. Causal Inference & Counterfactual

Understanding *why* predictions change and what *causes* outcomes.

| Library | Stars | Creator | Capabilities |
| --- | --- | --- | --- |
| **DoWhy** | 8k | Microsoft/PyWhy | End-to-end causal inference. 4-step workflow: Model → Identify → Estimate → Refute. Graphical causal models (GCM), root cause analysis, counterfactual estimation, interventional distributions. |
| **EconML** | 4.5k | Microsoft/PyWhy | Heterogeneous treatment effect estimation. Double ML, Causal Forests, Orthogonal Random Forests, Meta-Learners, DeepIV. SHAP integration for CATE models. |
| **CausalNex** | 2k+ | QuantumBlack/McKinsey | Bayesian network structure learning and inference. |

### Causal Integration Opportunities

- **DoWhy** → Power the `CAUSAL_GUIDE.md` workflow. Build structural causal models (SCM) from prediction data. "What caused this prediction to change?" → root cause attribution.
- **EconML** → Estimate treatment effects of events on forecasts. "What was the causal effect of the interest rate hike on our crypto price forecast?"
- **Causal Council Member** → A specialized council member that runs causal queries before voting.

---

## 6. Explainability / XAI

Making predictions interpretable and trustworthy.

| Library | Stars | Approach |
| --- | --- | --- |
| **SHAP** | 25.1k | Shapley values — game-theoretic credit allocation. TreeExplainer (exact, fast), DeepExplainer, KernelExplainer (model-agnostic), GradientExplainer. Interaction values. |
| **LIME** | — | Local Interpretable Model-Agnostic Explanations. Perturb inputs, fit local linear model. |
| **Darts Explainability** | (in Darts) | Built-in SHAP integration for forecasting models. |

### XAI Integration Opportunities

- **SHAP** → Power the `XAI_GUIDE.md` workflow. After every council prediction, run SHAP to explain which features drove the forecast. Waterfall plots, beeswarm plots.
- **Per-model explanations** → Each council member provides SHAP values for its prediction. The council deliberation includes explainability data.
- **Confidence calibration** → Use SHAP to identify when models disagree *because of different feature sensitivities* vs. noise.

---

## 7. Ensemble & Council Techniques

Methods for combining multiple forecasters — the core of our "council" concept.

### a) Standard Ensemble Methods

| Method | Where | Description |
| --- | --- | --- |
| **NaiveEnsembleModel** | Darts | Simple average/median of multiple model forecasts. |
| **RegressionEnsembleModel** | Darts | Learned combination weights via a regression model. |
| **Forecast Combinations** | statsforecast | Weighted averaging with optimal weight selection (Bates-Granger). |
| **Stacking** | mlforecast/sklearn | Train a meta-learner on cross-validated predictions from base models. |
| **Conformal Prediction** | Darts, mlforecast | Distribution-free uncertainty quantification for ensembles. |

### b) Council / Multi-Agent Patterns

| Pattern | Description |
| --- | --- |
| **Delphi Method** | Iterative expert panel: predict → share → revise → converge. Our council's adversarial debate maps to this. |
| **Wisdom of Crowds** | Independent diverse forecasts + aggregation outperforms individuals. Requires diversity + independence + decentralization. |
| **Adversarial Validation** | Detect distribution shift between train and live data — alerts the council when models may be stale. |
| **Hierarchical Reconciliation** | Ensure forecasts at different granularities are coherent (hierarchicalforecast). |

### Ensemble Integration Opportunities

- **RegressionEnsembleModel** → Replace simple averaging in `src/council.py` with learned weights.
- **Conformal Prediction** → Add prediction intervals to every council decision.
- **Delphi rounds** → Implement multi-round council deliberation: models forecast → see each other's forecasts → revise → final vote.

---

## 8. Real-Time Data Sources & APIs

### Economic & Financial

| API | Data | Access |
| --- | --- | --- |
| **FRED** (Federal Reserve) | Economic indicators, interest rates, GDP, CPI, employment | Free API key, `fredapi` Python package |
| **Alpha Vantage** | Stocks, forex, crypto, economic indicators, technical indicators | Free tier (25 req/day), premium tiers |
| **Yahoo Finance** | Stock prices, earnings, options | `yfinance` package (unofficial but widely used) |
| **CoinGecko** | Crypto prices, market cap, volume, DeFi data | Free tier, Pro tier (already in our ecosystem) |
| **World Bank** | Development indicators, climate, health data | Free, `wbdata` package |
| **Quandl/Nasdaq Data Link** | Commodity futures, alternative data | `nasdaqdatalink` package |

### News & Signals

| API | Data | Access |
| --- | --- | --- |
| **NewsAPI** | Real-time news headlines across 150k sources | Free dev tier (100 req/day) |
| **GDELT** | Global event data, sentiment, themes | Free, massive scale |
| **RSS Feeds** | Already implemented in `src/ingestion.py` | Free |
| **Reddit API** | Subreddit sentiment, emerging trends | Free dev |
| **X/Twitter API** | Trend detection, sentiment | Paid tiers |

### Geopolitical & Events

| Source | Data | Notes |
| --- | --- | --- |
| **ACLED** | Armed conflict, protest events | Academic access |
| **EMDAT** | Natural disasters | Open access |
| **UN OCHA ReliefWeb** | Crisis data, humanitarian events | Free API |

### Data Source Integration Opportunities

- **FRED + Alpha Vantage** → Add as ingestion sources alongside existing RSS/CSV. Economic indicators as covariates for forecasting models.
- **GDELT** → Event-driven triggers for council convening. "Major geopolitical event detected — convene emergency council."
- **Sentiment pipeline** → NewsAPI/Reddit → NLP sentiment → feed as exogenous regressors to forecasters.

---

## 9. Prediction Markets & Crowd Forecasting

| Platform | What | API |
| --- | --- | --- |
| **Metaculus** | Community forecasting on science, tech, geopolitics | Public API with question data, community predictions |
| **Polymarket** | Blockchain-based prediction markets (crypto, elections, events) | Public API (resolving markets, order books) |
| **Manifold Markets** | Play-money prediction markets | Free API |
| **Good Judgment Open** | Superforecaster platform (IARPA-backed) | Limited |

### Prediction Market Integration Opportunities

- **Metaculus API** → Ingest crowd forecasts as a "council member" — the collective prediction market view.
- **Polymarket** → Track real-money prediction market odds for calibration and as a signal source.
- **Superforecasting calibration** → Compare our council's accuracy against prediction market odds to measure quality.

---

## 10. Integration Roadmap

Priority-ordered integration plan for future-predictor-council:

### Phase 1 — Quick Wins (v0.3.0)

| Item | Effort | Impact |
| --- | --- | --- |
| Add `ChronosStrategy` (zero-shot, no training data needed) | Low | High — instant new council member |
| Add `TimesFMStrategy` (Google's foundation model) | Low | High — long-horizon forecasting |
| Add FRED/Alpha Vantage data ingestion | Medium | High — real economic data |
| Replace averaging with RegressionEnsembleModel | Medium | Medium — better council aggregation |

### Phase 2 — Model Expansion (v0.4.0)

| Item | Effort | Impact |
| --- | --- | --- |
| Add `NeuralForecastStrategy` (NBEATS/NHITS/PatchTST) | Medium | High — neural diversity |
| Add `MLForecastStrategy` (LightGBM/XGBoost) | Medium | High — tree-based perspective |
| Add `ProphetStrategy` baseline | Low | Medium — interpretable baseline |
| Implement SHAP explanations per-prediction | Medium | High — XAI compliance |

### Phase 3 — Advanced Intelligence (v0.5.0)

| Item | Effort | Impact |
| --- | --- | --- |
| DoWhy causal analysis in council deliberation | High | Very High — "why" behind predictions |
| Metaculus/Polymarket crowd signal ingestion | Medium | High — wisdom of crowds |
| Conformal prediction intervals on all forecasts | Medium | High — calibrated uncertainty |
| Multi-round Delphi deliberation protocol | High | Very High — council quality leap |

### Phase 4 — Full Stack (v1.0.0)

| Item | Effort | Impact |
| --- | --- | --- |
| Anomaly detection (Merlion/MOMENT) on signals | High | High — early warning system |
| Hierarchical reconciliation (hierarchicalforecast) | Medium | Medium — coherent multi-level forecasts |
| GDELT/NewsAPI event-driven triggers | High | High — reactive council |
| Adversarial validation & model staleness detection | Medium | Medium — self-monitoring |
| Full SHAP dashboard + causal graph visualization | High | Very High — complete transparency |

---

## Summary Statistics

| Category | Projects Researched | Top Candidates |
| --- | --- | --- |
| Statistical/ML Forecasting | 5 (Nixtla suite) | neuralforecast, mlforecast |
| Foundation Models | 6 | Chronos-2, TimesFM 2.5, MOMENT |
| Comprehensive Frameworks | 3 | Darts, sktime, Merlion |
| Classical Models | 2 | Prophet, NeuralProphet |
| Causal Inference | 3 | DoWhy, EconML |
| Explainability | 2 | SHAP, LIME |
| Data APIs | 10+ | FRED, Alpha Vantage, GDELT, NewsAPI |
| Prediction Markets | 4 | Metaculus, Polymarket |

**Total: 35+ tools, models, and APIs surveyed.**
