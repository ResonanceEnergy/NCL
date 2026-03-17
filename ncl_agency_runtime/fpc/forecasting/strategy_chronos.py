"""Chronos-2 strategy — Amazon's zero-shot time-series foundation model."""

import logging
from collections.abc import Sequence

import pandas as pd

from .base import ForecastResult, ModelStrategy

logger = logging.getLogger(__name__)


class ChronosStrategy(ModelStrategy):
    """Zero-shot forecasting via Amazon Chronos-2 (Chronos-Bolt).

    Install: ``pip install chronos-forecasting torch``
    Models: amazon/chronos-t5-{tiny,mini,small,base,large}
            amazon/chronos-bolt-{tiny,mini,small,base}
    """

    name = "chronos_zero_shot"

    def __init__(self, model_id: str = "amazon/chronos-bolt-small", device: str = "cpu"):
        self.model_id = model_id
        self.device = device
        self._pipeline = None
        self._series: pd.Series | None = None

    def _load_pipeline(self):
        if self._pipeline is None:
            from chronos import ChronosPipeline  # type: ignore[import-untyped]
            self._pipeline = ChronosPipeline.from_pretrained(
                self.model_id,
                device_map=self.device,
            )
            logger.info("Chronos pipeline loaded: %s", self.model_id)

    def fit(
        self,
        df: pd.DataFrame,
        freq: str,
        target_col: str = "y",
        time_col: str = "ds",
        id_col: str = "unique_id",
        **kwargs,
    ):
        self._load_pipeline()
        uid = df[id_col].iloc[0]
        sdf = df[df[id_col] == uid].sort_values(time_col)
        self._series = sdf[target_col].reset_index(drop=True)

    def predict(
        self, h: int, quantiles: Sequence[float] | None = None
    ) -> ForecastResult:
        import torch

        self._load_pipeline()
        if self._series is None or self._pipeline is None:
            raise RuntimeError("Call fit() before predict()")
        context = torch.tensor(self._series.values, dtype=torch.float32)
        forecast = self._pipeline.predict(context, prediction_length=h)

        # forecast shape: (num_samples, h) — take median
        median = forecast.median(dim=0).values.numpy()
        yhat = pd.Series(median, name="yhat")

        q_dict = {}
        if quantiles:
            for q in quantiles:
                q_dict[q] = pd.Series(
                    torch.quantile(forecast.float(), q, dim=0).numpy(),
                    name=f"q{q}",
                )

        return ForecastResult(
            yhat=yhat,
            q=q_dict,
            meta={"impl": "Chronos", "model_id": self.model_id},
        )
