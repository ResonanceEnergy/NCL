"""Base interfaces for the model council."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class ForecastResult:
    """Container for a single model's forecast output."""

    yhat: pd.Series
    quantiles: dict[float, pd.Series] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


class ModelStrategy(ABC):
    """Strategy interface — every model in the council implements this."""

    name: str = "base"

    @abstractmethod
    def fit(
        self,
        df: pd.DataFrame,
        freq: str,
        target_col: str = "y",
        time_col: str = "ds",
        id_col: str = "unique_id",
        **kwargs: Any,
    ) -> None: ...

    @abstractmethod
    def predict(
        self, h: int, quantiles: Sequence[float] | None = None
    ) -> ForecastResult: ...

    def explain(self, **kwargs: Any) -> dict[str, Any]:
        """Return model-specific explanations (optional override)."""
        return {}
