"""Base classes for forecasting strategies."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

import pandas as pd


class ForecastResult:
    """Container for forecast outputs with optional quantiles."""

    def __init__(
        self,
        yhat: pd.Series,
        q: dict[float, pd.Series] | None = None,
        meta: dict[str, Any] | None = None,
    ):
        self.yhat = yhat
        self.q = q or {}
        self.meta = meta or {}


class ModelStrategy(ABC):
    """Abstract base for pluggable forecast models."""

    name: str

    @abstractmethod
    def fit(
        self,
        df: pd.DataFrame,
        freq: str,
        target_col: str = "y",
        time_col: str = "ds",
        id_col: str = "unique_id",
        **kwargs,
    ):
        ...

    @abstractmethod
    def predict(
        self, h: int, quantiles: Sequence[float] | None = None
    ) -> ForecastResult:
        ...
