# Usage Guide

## Data Format

The council expects panel data in CSV format with these columns:

| Column | Type | Description |
|---|---|---|
| `unique_id` | string | Series identifier (e.g., `store_001`, `sku_ABC`) |
| `ds` | date | Timestamp (ISO 8601: `YYYY-MM-DD`) |
| `y` | float | Target variable (demand, revenue, etc.) |

Optional exogenous columns can be added (e.g., `promo`, `price`, `day_of_week`).

### Example
```csv
unique_id,ds,y
series_A,2022-01-01,120.5
series_A,2022-01-02,132.1
series_B,2022-01-01,85.2
series_B,2022-01-02,91.8
```

## Quickstart

### 1. Install
```bash
pip install -e .                    # Base (StatsForecast + FastAPI)
pip install -e ".[neural]"          # + PatchTST, TFT
pip install -e ".[xai]"             # + SHAP
pip install -e ".[causal]"          # + DoWhy, EconML
pip install -e ".[foundation]"      # + TimesFM, Chronos-2
pip install -e ".[dev]"             # + pytest, ruff, mypy
```

### 2. Run a backtest
```bash
python -m src.cli --data data/raw/example.csv --freq D --h 14 --windows 5
```

### 3. Enable foundation models
```bash
python -m src.cli --data data/raw/example.csv --freq D --h 14 --foundation on
```

### 4. Start the API server
```bash
uvicorn src.serve:app --host 0.0.0.0 --port 8000
```

### 5. Query the API
```bash
curl -X POST http://localhost:8000/forecast \
  -H "Content-Type: application/json" \
  -d '{"data": [...], "freq": "D", "h": 14}'
```

## Configuration

Edit `config/steering.json` for the 5% human steering knobs:

| Knob | Default | Description |
|---|---|---|
| `metric_gate` | `MASE` | Primary evaluation metric |
| `secondary_metric` | `sMAPE` | Secondary metric |
| `causal_interventions` | `["promo", "price"]` | Which levers to model |
| `cloud` | `AWS` | Cloud provider for burst |
| `budget_weekly_usd` | `50` | Weekly cloud budget cap |
| `gpu_max_hourly` | `1.20` | Max hourly GPU cost |
| `foundation_default` | `off` | Include foundation models by default |

## FAQ

**Q: My MASE is > 1.0. Is that bad?**
A: MASE > 1 means your model is worse than a seasonal naive baseline. Check data quality, feature engineering, and consider adding more training data.

**Q: How much RAM do I need for TimesFM?**
A: TimesFM 2.5 requires ~32 GB RAM to load. Use cloud burst (r6i.2xlarge, 64 GB) — it won't fit on a 16 GB machine.

**Q: Can I run Chronos-2 on CPU?**
A: Technically yes, but inference is ~10x slower. Use a GPU instance (g5.xlarge with A10G) for practical inference times.
