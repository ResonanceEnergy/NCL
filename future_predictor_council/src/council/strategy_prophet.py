"""Prophet strategy — Meta's additive forecasting model."""

import logging
from collections.abc import Sequence

import pandas as pd

from .base import ForecastResult, ModelStrategy

logger = logging.getLogger(__name__)


class ProphetStrategy(ModelStrategy):
    """Classical additive model via Meta Prophet.

    Install: ``pip install prophet``
    Strong seasonality + holiday handling, human-interpretable components.
    """

    name = "prophet_additive"

    def __init__(self, **prophet_kwargs):
        self._kwargs = prophet_kwargs
        self._model = None
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
        from prophet import Prophet  # type: ignore[import-untyped]

        self._freq = freq
        uid = df[id_col].iloc[0]
        sdf = df[df[id_col] == uid].sort_values(time_col)
        train = sdf[[time_col, target_col]].rename(
            columns={time_col: "ds", target_col: "y"}
        )

        self._model = Prophet(**self._kwargs)
        self._model.fit(train)
        logger.info("Prophet model fitted with %d observations", len(train))

    def predict(
        self, h: int, quantiles: Sequence[float] | None = None
    ) -> ForecastResult:
        if self._model is None:
            raise RuntimeError("Call fit() before predict()")
        future = self._model.make_future_dataframe(periods=h, freq=self._freq)
        fcst = self._model.predict(future)
        tail = fcst.tail(h)
        yhat = tail["yhat"].reset_index(drop=True)

        q_dict = {}
        if quantiles:
            for q in quantiles:
                if q < 0.5:
                    q_dict[q] = tail["yhat_lower"].reset_index(drop=True)
                else:
                    q_dict[q] = tail["yhat_upper"].reset_index(drop=True)

        return ForecastResult(
            yhat=yhat,
            quantiles=q_dict,
            meta={"impl": "Prophet"},
        )
