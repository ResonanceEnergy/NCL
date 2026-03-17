"""StatsForecast strategy — fast CPU baselines (AutoARIMA / ETS / Theta)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from .base import ForecastResult, ModelStrategy


class StatsForecastStrategy(ModelStrategy):
    name = "statsforecast_auto"

    def __init__(self, season_length: int = 7) -> None:
        self._season_length = season_length
        self._sf: Any = None
        self._freq: str = "D"

    def fit(
        self,
        df: pd.DataFrame,
        freq: str,
        target_col: str = "y",
        time_col: str = "ds",
        id_col: str = "unique_id",
        **kwargs: Any,
    ) -> None:
        from statsforecast import StatsForecast
        from statsforecast.models import AutoARIMA, AutoETS, AutoTheta

        self._freq = freq
        panel = df[[id_col, time_col, target_col]].rename(
            columns={id_col: "unique_id", time_col: "ds", target_col: "y"}
        )
        models = [
            AutoARIMA(season_length=self._season_length),
            AutoETS(season_length=self._season_length),
            AutoTheta(season_length=self._season_length),
        ]
        self._sf = StatsForecast(models=models, freq=freq)
        self._sf.fit(panel)

    def predict(
        self, h: int, quantiles: Sequence[float] | None = None
    ) -> ForecastResult:
        fcst = self._sf.predict(h=h)
        # Use AutoARIMA point forecast as primary
        col = "AutoARIMA" if "AutoARIMA" in fcst.columns else fcst.columns[-1]
        yhat = fcst.groupby("unique_id")[col].last()
        return ForecastResult(yhat=yhat, meta={"impl": "StatsForecast"})
