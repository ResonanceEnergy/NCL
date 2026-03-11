"""XAI — SHAP global/local feature importance panel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class SHAPResult:
    shap_values: np.ndarray = field(default_factory=lambda: np.array([]))
    base_value: float = 0.0
    feature_names: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def compute_shap(
    model: Any,
    X: pd.DataFrame,
    method: str = "tree",
    nsamples: int = 100,
) -> SHAPResult:
    """Compute SHAP values for tabular/tree models.

    method: 'tree' | 'kernel' | 'linear'
    """
    import shap  # type: ignore[import-untyped]

    if method == "tree":
        explainer = shap.TreeExplainer(model)
    elif method == "linear":
        explainer = shap.LinearExplainer(model, X)
    else:
        explainer = shap.KernelExplainer(model.predict, shap.sample(X, min(nsamples, len(X))))

    sv = explainer.shap_values(X)
    ev = explainer.expected_value
    base = float(ev) if np.isscalar(ev) else float(ev[0])

    return SHAPResult(
        shap_values=np.asarray(sv),
        base_value=base,
        feature_names=list(X.columns),
        meta={"method": method, "n_samples": len(X)},
    )
