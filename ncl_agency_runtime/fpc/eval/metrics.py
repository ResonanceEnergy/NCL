"""Forecast accuracy metrics."""

import numpy as np


def mase(y_true, y_pred, y_insample, m: int = 1) -> float:
    """Mean Absolute Scaled Error.

    Uses naive seasonal baseline (lag *m*) from the in-sample series.
    """
    if len(y_insample) > m:
        scale = np.mean(np.abs(y_insample[m:] - y_insample[:-m]))
    else:
        scale = 1.0
    return float(np.mean(np.abs(y_true - y_pred)) / (scale + 1e-12))


def smape(y_true, y_pred) -> float:
    """Symmetric Mean Absolute Percentage Error (0–2 scale)."""
    return float(
        np.mean(
            2 * np.abs(y_pred - y_true) / (np.abs(y_true) + np.abs(y_pred) + 1e-12)
        )
    )
