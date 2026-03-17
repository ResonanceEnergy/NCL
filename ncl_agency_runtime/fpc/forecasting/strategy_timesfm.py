"""TimesFM 2.5 strategy — Google's decoder-only time-series foundation model."""

import logging
from collections.abc import Sequence

import pandas as pd

from .base import ForecastResult, ModelStrategy

logger = logging.getLogger(__name__)


class TimesFMStrategy(ModelStrategy):
    """Zero-shot forecasting via Google TimesFM 2.5.

    Install: ``pip install timesfm``
    Supports up to 16k context length and 1k prediction horizon.
    """

    name = "timesfm_zero_shot"

    def __init__(self, model_id: str = "google/timesfm-2.0-500m-pytorch", freq_type: str = "D"):
        self.model_id = model_id
        self.freq_type = freq_type
        self._model = None
        self._series: pd.Series | None = None

    def _load_model(self):
        if self._model is None:
            import timesfm  # type: ignore[import-untyped]
            self._model = timesfm.TimesFm(
                hparams=timesfm.TimesFmHparams(
                    per_core_batch_size=1,
                    horizon_len=128,
                ),
                checkpoint=timesfm.TimesFmCheckpoint(
                    huggingface_repo_id=self.model_id,
                ),
            )
            logger.info("TimesFM model loaded: %s", self.model_id)

    def fit(
        self,
        df: pd.DataFrame,
        freq: str,
        target_col: str = "y",
        time_col: str = "ds",
        id_col: str = "unique_id",
        **kwargs,
    ):
        self._load_model()
        uid = df[id_col].iloc[0]
        sdf = df[df[id_col] == uid].sort_values(time_col)
        self._series = sdf[target_col].reset_index(drop=True)
        # map pandas freq to timesfm freq code
        freq_map = {"D": 0, "W": 1, "M": 2, "Q": 3, "Y": 4, "H": 5, "T": 6, "S": 7}
        self.freq_type = freq_map.get(freq.upper().rstrip("S"), 0)

    def predict(
        self, h: int, quantiles: Sequence[float] | None = None
    ) -> ForecastResult:

        self._load_model()
        if self._model is None or self._series is None:
            raise RuntimeError("Call fit() before predict()")
        point, intervals = self._model.forecast(
            [self._series.values],
            freq=[self.freq_type],
        )
        yhat = pd.Series(point[0][:h], name="yhat")

        q_dict = {}
        if quantiles and intervals is not None:
            lo = intervals[0][:h, 0]
            hi = intervals[0][:h, 1]
            for q in quantiles:
                interp = lo + (hi - lo) * q
                q_dict[q] = pd.Series(interp, name=f"q{q}")

        return ForecastResult(
            yhat=yhat,
            q=q_dict,
            meta={"impl": "TimesFM", "model_id": self.model_id},
        )
