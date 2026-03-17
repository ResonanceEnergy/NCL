"""Chronos-2 strategy — Amazon probabilistic TS foundation model (optional/flagged)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from .base import ForecastResult, ModelStrategy


class ChronosStrategy(ModelStrategy):
    name = "chronos2"

    def __init__(self, model_id: str = "amazon/chronos-2-base", device: str = "cpu") -> None:
        self._model_id = model_id
        self._device = device
        self._pipe: Any = None
        self._context_df: pd.DataFrame | None = None

    def fit(
        self,
        df: pd.DataFrame,
        freq: str,
        target_col: str = "y",
        time_col: str = "ds",
        id_col: str = "unique_id",
        **kwargs: Any,
    ) -> None:
        from chronos import Chronos2Pipeline  # type: ignore[import-untyped]

        self._pipe = Chronos2Pipeline.from_pretrained(self._model_id, device_map=self._device)
        self._context_df = df.rename(columns={time_col: "timestamp", target_col: "target", id_col: "item_id"})

    def predict(
        self, h: int, quantiles: Sequence[float] | None = (0.1, 0.5, 0.9)
    ) -> ForecastResult:
        if self._pipe is None or self._context_df is None:
            raise RuntimeError("Call fit() before predict()")

        q_levels = list(quantiles) if quantiles else [0.1, 0.5, 0.9]
        pred = self._pipe.predict_df(
            self._context_df,
            prediction_length=h,
            quantile_levels=q_levels,
        )
        yhat = pred["median"] if "median" in pred.columns else pred.iloc[:, 0]
        q_dict = {}
        for qv in q_levels:
            col = f"q{qv}"
            if col in pred.columns:
                q_dict[qv] = pred[col].reset_index(drop=True)

        return ForecastResult(
            yhat=pd.Series(yhat.values, name="yhat"),
            quantiles=q_dict,
            meta={"impl": "Chronos-2", "model_id": self._model_id},
        )
