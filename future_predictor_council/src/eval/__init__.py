"""Evaluation metrics — MASE (primary) and sMAPE (secondary)."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt


def mase(
    y_true: npt.ArrayLike,
    y_pred: npt.ArrayLike,
    y_insample: npt.ArrayLike,
    seasonality: int = 1,
) -> float:
    """Mean Absolute Scaled Error.

    MASE < 1 → beats seasonal naive baseline.
    """
    y_t = np.asarray(y_true, dtype=float)
    y_p = np.asarray(y_pred, dtype=float)
    y_in = np.asarray(y_insample, dtype=float)

    mae_pred = np.mean(np.abs(y_t - y_p))
    mae_naive = np.mean(np.abs(y_in[seasonality:] - y_in[:-seasonality]))
    if mae_naive == 0:
        return float("inf")
    return float(mae_pred / mae_naive)


def smape(y_true: npt.ArrayLike, y_pred: npt.ArrayLike) -> float:
    """Symmetric Mean Absolute Percentage Error (0-200 scale)."""
    y_t = np.asarray(y_true, dtype=float)
    y_p = np.asarray(y_pred, dtype=float)
    denom = np.abs(y_t) + np.abs(y_p)
    # Avoid division by zero where both are zero
    mask = denom > 0
    if not np.any(mask):
        return 0.0
    return float(np.mean(2.0 * np.abs(y_p[mask] - y_t[mask]) / denom[mask]) * 100)
