"""PatchTST strategy via NeuralForecast — strong LTSF baseline."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from .base import ForecastResult, ModelStrategy


class PatchTSTStrategy(ModelStrategy):
    name = "patchtst"

    def __init__(self, input_size: int = 96, max_steps: int = 200) -> None:
        self._input_size = input_size
        self._max_steps = max_steps
        self._nf: Any = None
        self._h: int = 14

    def fit(
        self,
        df: pd.DataFrame,
        freq: str,
        target_col: str = "y",
        time_col: str = "ds",
        id_col: str = "unique_id",
        **kwargs: Any,
    ) -> None:
        from neuralforecast import NeuralForecast
        from neuralforecast.models import PatchTST

        self._h = kwargs.get("h", 14)
        panel = df[[id_col, time_col, target_col]].rename(
            columns={id_col: "unique_id", time_col: "ds", target_col: "y"}
        )
        model = PatchTST(
            h=self._h,
            input_size=self._input_size,
            max_steps=self._max_steps,
        )
        self._nf = NeuralForecast(models=[model], freq=freq)
        self._nf.fit(df=panel)

    def predict(
        self, h: int, quantiles: Sequence[float] | None = None
    ) -> ForecastResult:
        fcst = self._nf.predict()
        yhat = fcst.groupby("unique_id")["PatchTST"].last()
        return ForecastResult(yhat=yhat, meta={"impl": "NeuralForecast/PatchTST"})
