# Day 2 — Build

> **Goal**: Data contracts, baselines, first council run.

---

## Morning (9:00–12:00)

### 1. Data Ingestion (9:00–10:00)
- **Exercise**: Load your panel dataset into the council framework
  ```bash
  python -m src.cli --data data/raw/your_data.csv --freq D --h 14
  ```
- Validate schema: `unique_id`, `ds`, `y` columns present
- Check data quality: missing values, duplicates, frequency gaps
- **Output**: Clean, validated dataset ready for modeling

### 2. Baseline Models (10:00–12:00)
- **Exercise**: Run StatsForecast baselines
  - AutoARIMA — automatic differencing and seasonal ARIMA
  - ETS — exponential smoothing with trend/seasonal decomposition
  - Theta — robust to outliers and structural breaks
- Run first backtest:
  ```bash
  python -m src.cli --data data/raw/your_data.csv --freq D --h 14 --windows 5
  ```
- **Output**: Baseline MASE and sMAPE scores

## Afternoon (13:00–17:00)

### 3. Neural Models (13:00–14:30)
- **Exercise**: Add PatchTST to the council (if training time permits on CPU)
  - Adjust `max_steps` for CPU training (start with 100)
  - Compare against baselines
- Note: If CPU training is too slow, document expected performance and plan for cloud burst

### 4. First Council Run (14:30–16:00)
- **Exercise**: Run the weighted ensemble
  - Start with equal weights
  - Compare ensemble MASE vs. individual model MASE
  - Does the council beat the best individual? (It should.)
- **Output**: Council backtest report

### 5. Feature Engineering (16:00–16:45)
- **Exercise**: Add exogenous features to the panel
  - Calendar features (day of week, month, holidays)
  - Lag features (y_lag7, y_lag14, y_lag28)
  - Rolling statistics (rolling_mean_7, rolling_std_7)
- Re-run backtest with features

### 6. Day 2 Retrospective (16:45–17:00)
- Review MASE scores: Are we below 1.0? (Beating naive)
- Identify which models contribute most to ensemble
- Plan Day 3: XAI deep-dive

---

## Day 2 Deliverables Checklist
- [ ] Validated panel dataset loaded
- [ ] StatsForecast baselines with MASE scores
- [ ] PatchTST results (or documented plan for cloud burst)
- [ ] First council ensemble backtest report
- [ ] Feature engineering applied and retested
- [ ] Initial weight tuning based on individual performance
