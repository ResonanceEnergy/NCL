"""NeuralForecast strategy — Nixtla's 30+ neural architectures."""

import logging
from collections.abc import Sequence

import pandas as pd

from .base import ForecastResult, ModelStrategy

logger = logging.getLogger(__name__)


class NeuralForecastStrategy(ModelStrategy):
    """Neural ensemble via Nixtla neuralforecast.

    Install: ``pip install neuralforecast``
    Default models: NBEATS + NHITS (auto-configured).
    """

    name = "neuralforecast_ensemble"

    def __init__(self, models=None, max_steps: int = 100):
        self._model_specs = models
        self._max_steps = max_steps
        self._nf = None
        self._freq = "D"

    def fit(
        self,
        df: pd.DataFrame,
        freq: str,
        target_col: str = "y",
        time_col: str = "ds",
        id_col: str = "unique_id",
        **kwargs,
    ):
        from neuralforecast import NeuralForecast  # type: ignore[import-untyped]
        from neuralforecast.models import NBEATS, NHITS  # type: ignore[import-untyped]

        h = kwargs.get("h", 14)
        self._freq = freq

        Y = df[[id_col, time_col, target_col]].rename(  # type: ignore[call-overload]
            columns={id_col: "unique_id", time_col: "ds", target_col: "y"}
        )

        models = self._model_specs or [
            NBEATS(input_size=2 * h, h=h, max_steps=self._max_steps),
            NHITS(input_size=2 * h, h=h, max_steps=self._max_steps),
        ]

        self._nf = NeuralForecast(models=models, freq=freq)
        self._nf.fit(df=Y)
        logger.info("NeuralForecast fitted with %d models", len(models))

    def predict(
        self, h: int, quantiles: Sequence[float] | None = None
    ) -> ForecastResult:
        if self._nf is None:
            raise RuntimeError("Call fit() before predict()")
        fcst = self._nf.predict()
        cols = [c for c in fcst.columns if c not in ("unique_id", "ds")]
        main = cols[0] if cols else "NBEATS"
        yhat = fcst[main].tail(h).reset_index(drop=True)

        return ForecastResult(
            yhat=yhat,
            meta={"impl": "NeuralForecast", "models": cols},
        )
