"""Rolling backtest — sliding-window cross-validation for time series."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import pandas as pd

from ..council.base import ModelStrategy
from . import mase, smape


@dataclass
class BacktestResult:
    windows: list[dict[str, float]] = field(default_factory=list)
    avg_mase: float = 0.0
    avg_smape: float = 0.0


def rolling_backtest(
    strategy: ModelStrategy,
    df: pd.DataFrame,
    h: int,
    n_windows: int = 5,
    freq: str = "D",
    target_col: str = "y",
    time_col: str = "ds",
    id_col: str = "unique_id",
    seasonality: int = 7,
    quantiles: Sequence[float] = (0.1, 0.5, 0.9),
) -> BacktestResult:
    """Sliding-window CV: refit on expanding window, forecast h steps, score."""
    sid = df[id_col].iloc[0]
    series = df[df[id_col] == sid].sort_values(time_col).reset_index(drop=True)
    n = len(series)
    min_train = max(2 * h, 30)

    if n < min_train + h:
        raise ValueError(f"Series too short ({n} rows) for h={h}, min_train={min_train}")

    step = max(1, (n - min_train - h) // max(n_windows - 1, 1))
    result = BacktestResult()

    for i in range(n_windows):
        split = min_train + i * step
        if split + h > n:
            break

        train = series.iloc[:split]
        test = series.iloc[split : split + h]

        strategy.fit(train, freq, target_col, time_col, id_col, h=h)
        forecast = strategy.predict(h, quantiles)

        y_true = test[target_col].values
        y_pred = forecast.yhat.values[:h]
        y_insample = train[target_col].values

        w = {
            "window": i,
            "split_idx": split,
            "mase": mase(y_true, y_pred, y_insample, seasonality),
            "smape": smape(y_true, y_pred),
        }
        result.windows.append(w)

    if result.windows:
        result.avg_mase = sum(w["mase"] for w in result.windows) / len(result.windows)
        result.avg_smape = sum(w["smape"] for w in result.windows) / len(result.windows)

    return result
