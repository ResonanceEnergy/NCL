"""TimesFM strategy — decoder-only TS foundation model (optional/flagged)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from .base import ForecastResult, ModelStrategy


class TimesFMStrategy(ModelStrategy):
    name = "timesfm"

    def __init__(self, max_context: int = 1024, max_horizon: int = 256) -> None:
        self._max_context = max_context
        self._max_horizon = max_horizon
        self._model: Any = None
        self._series: Any = None
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
        import timesfm

        self._model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
            "google/timesfm-2.5-200m-pytorch", torch_compile=True
        )
        self._model.compile(
            timesfm.ForecastConfig(
                max_context=self._max_context,
                max_horizon=self._max_horizon,
                normalize_inputs=True,
                use_continuous_quantile_head=True,
            )
        )
        sid = df[id_col].iloc[0]
        arr = df[df[id_col] == sid].sort_values(time_col)[target_col].to_numpy(dtype=float)
        self._series = arr
        self._h = kwargs.get("h", 14)

    def predict(
        self, h: int, quantiles: Sequence[float] | None = (0.1, 0.5, 0.9)
    ) -> ForecastResult:
        pt, qt = self._model.forecast(horizon=h or self._h, inputs=[self._series])
        yhat = pd.Series(pt[0], name="yhat")
        q = {}
        if quantiles and qt is not None:
            for idx, qv in enumerate(quantiles):
                if idx < qt.shape[2]:
                    q[qv] = pd.Series(qt[0, :, idx], name=f"q{qv}")
        return ForecastResult(yhat=yhat, quantiles=q, meta={"impl": "TimesFM-2.5"})
