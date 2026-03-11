"""Causal — EconML heterogeneous treatment effect panel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class CATEResult:
    cate_values: np.ndarray = field(default_factory=lambda: np.array([]))
    ate: float = 0.0
    ci_lower: np.ndarray | None = None
    ci_upper: np.ndarray | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def estimate_cate(
    df: pd.DataFrame,
    treatment: str,
    outcome: str,
    features: list[str],
    method: str = "dml",
) -> CATEResult:
    """Estimate CATE using EconML.

    method: 'dml' (Double ML) | 'forest' (Causal Forest)
    """
    from sklearn.linear_model import LassoCV  # type: ignore[import-untyped]

    Y = df[outcome].values
    T = df[treatment].values
    X = df[features].values

    if method == "forest":
        from econml.dml import CausalForestDML  # type: ignore[import-untyped]

        est = CausalForestDML(model_y=LassoCV(), model_t=LassoCV(), n_estimators=100)
    else:
        from econml.dml import LinearDML  # type: ignore[import-untyped]

        est = LinearDML(model_y=LassoCV(), model_t=LassoCV())

    est.fit(Y, T, X=X)
    cate = est.effect(X)
    ci = est.effect_interval(X, alpha=0.05)

    return CATEResult(
        cate_values=np.asarray(cate).flatten(),
        ate=float(np.mean(cate)),
        ci_lower=np.asarray(ci[0]).flatten() if ci else None,
        ci_upper=np.asarray(ci[1]).flatten() if ci else None,
        meta={"method": method, "features": features, "n_obs": len(df)},
    )
