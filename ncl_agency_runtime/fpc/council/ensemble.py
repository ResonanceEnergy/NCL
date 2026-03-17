"""Weighted ensemble — averages council members by configurable weights."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from .base import ForecastResult, ModelStrategy


class WeightedEnsemble(ModelStrategy):
    name = "ensemble"

    def __init__(self, strategies: list[ModelStrategy], weights: list[float] | None = None) -> None:
        self._strategies = strategies
        if weights is None:
            weights = [1.0 / len(strategies)] * len(strategies)
        total = sum(weights)
        self._weights = [w / total for w in weights]

    def fit(
        self,
        df: pd.DataFrame,
        freq: str,
        target_col: str = "y",
        time_col: str = "ds",
        id_col: str = "unique_id",
        **kwargs: Any,
    ) -> None:
        for strategy in self._strategies:
            strategy.fit(df, freq, target_col, time_col, id_col, **kwargs)

    def predict(
        self, h: int, quantiles: Sequence[float] | None = (0.1, 0.5, 0.9)
    ) -> ForecastResult:
        results = [s.predict(h, quantiles) for s in self._strategies]

        # Weighted average of point forecasts
        stacked = np.column_stack([r.yhat.values for r in results])
        weights_arr = np.array(self._weights)
        yhat = pd.Series((stacked * weights_arr).sum(axis=1), name="yhat")

        # Weighted average of quantiles
        q_dict: dict[float, pd.Series] = {}
        if quantiles:
            for qv in quantiles:
                q_vals = []
                w_active: list[float] = []
                for r, w in zip(results, self._weights, strict=False):
                    if qv in r.quantiles:
                        q_vals.append(r.quantiles[qv].values)
                        w_active.append(w)
                if q_vals:
                    w_norm = np.array(w_active) / sum(w_active)
                    q_stack = np.column_stack(q_vals)
                    q_dict[qv] = pd.Series((q_stack * w_norm).sum(axis=1), name=f"q{qv}")

        members = [s.name for s in self._strategies]
        return ForecastResult(yhat=yhat, quantiles=q_dict, meta={"members": members, "weights": self._weights})
