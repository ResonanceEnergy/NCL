"""StatsForecast strategy — AutoARIMA, AutoETS, AutoTheta ensemble."""

import pandas as pd
from statsforecast import StatsForecast
from statsforecast.models import AutoARIMA, AutoETS, AutoTheta

from .base import ForecastResult, ModelStrategy


class StatsForecastStrategy(ModelStrategy):
    """Ensemble of AutoARIMA + AutoETS + AutoTheta via Nixtla statsforecast."""

    name = "statsforecast_auto"

    def __init__(self, models=None, season_length: int = 7):
        self.models = models or [
            AutoARIMA(season_length=season_length),
            AutoETS(season_length=season_length),
            AutoTheta(season_length=season_length),
        ]
        self.sf = None
        self.freq = None

    def fit(
        self,
        df: pd.DataFrame,
        freq: str,
        target_col: str = "y",
        time_col: str = "ds",
        id_col: str = "unique_id",
        **kwargs,
    ):
        self.freq = freq
        Y = df[[id_col, time_col, target_col]].rename(  # type: ignore[call-overload]
            columns={id_col: "unique_id", time_col: "ds", target_col: "y"}
        )
        self.sf = StatsForecast(models=self.models, freq=freq)
        self.sf.fit(Y)

    def predict(self, h: int, quantiles=None) -> ForecastResult:
        if self.sf is None:
            raise RuntimeError("Call fit() before predict()")
        fcst = self.sf.predict(h=h)
        cols = [c for c in fcst.columns if c not in ("unique_id", "ds")]
        main = "AutoARIMA" if "AutoARIMA" in cols else cols[-1]
        yhat = fcst.groupby("unique_id")[main].tail(h).groupby(level=0).last()
        return ForecastResult(yhat=yhat, meta={"impl": "StatsForecast"})
