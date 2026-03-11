"""Explainability — SHAP-based forecast explanation engine.

This module extends the simpler ``xai/shap_panel.py`` with auto-detection
of model type and human-readable summary generation.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ForecastExplainer:
    """Generate SHAP explanations for forecast model predictions.

    Install: ``pip install shap``

    Supports tree-based (LightGBM/XGBoost via TreeExplainer),
    deep learning (DeepExplainer), and model-agnostic (KernelExplainer).
    """

    def __init__(self, method: str = "auto"):
        self.method = method
        self._explainer = None

    def explain(
        self,
        model: Any,
        X,
        feature_names: Optional[List[str]] = None,
        max_samples: int = 100,
    ) -> Dict[str, Any]:
        """Compute SHAP values for predictions on ``X``."""
        import shap  # type: ignore[import-untyped]
        import numpy as np

        method = self.method

        if method == "auto":
            model_type = type(model).__name__.lower()
            if any(t in model_type for t in ("lgbm", "xgb", "random", "gradient", "forest")):
                method = "tree"
            else:
                method = "kernel"

        if method == "tree":
            self._explainer = shap.TreeExplainer(model)
            shap_values = self._explainer.shap_values(X)
        elif method == "deep":
            self._explainer = shap.DeepExplainer(model, X[:max_samples])
            shap_values = self._explainer.shap_values(X)
        else:
            background = shap.sample(X, min(max_samples, len(X)))
            self._explainer = shap.KernelExplainer(model.predict, background)
            shap_values = self._explainer.shap_values(X)

        if isinstance(shap_values, list):
            shap_values = shap_values[0]

        mean_abs = np.abs(shap_values).mean(axis=0)
        names = feature_names or [f"f{i}" for i in range(len(mean_abs))]
        importance = sorted(
            zip(names, mean_abs), key=lambda x: x[1], reverse=True
        )

        result = {
            "shap_values": shap_values,
            "base_value": float(getattr(self._explainer, "expected_value", 0)),
            "feature_importance": [
                {"feature": name, "importance": float(val)} for name, val in importance
            ],
            "method": method,
        }

        logger.info(
            "SHAP explanation generated (%s): top feature = %s (%.4f)",
            method,
            importance[0][0] if importance else "N/A",
            importance[0][1] if importance else 0.0,
        )
        return result

    @staticmethod
    def summary_text(explanation: Dict[str, Any], top_k: int = 5) -> str:
        """Convert a SHAP explanation into a human-readable summary."""
        lines = [f"Explainability method: {explanation.get('method', 'unknown')}"]
        lines.append(f"Base value: {explanation.get('base_value', 0):.4f}")
        lines.append(f"Top {top_k} features:")
        for item in explanation.get("feature_importance", [])[:top_k]:
            lines.append(f"  - {item['feature']}: {item['importance']:.4f}")
        return "\n".join(lines)
