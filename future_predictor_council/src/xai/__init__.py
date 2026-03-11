"""XAI — TimeSHAP sequential feature attribution panel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class TimeSHAPResult:
    event_level: pd.DataFrame = field(default_factory=pd.DataFrame)
    feature_level: pd.DataFrame = field(default_factory=pd.DataFrame)
    cell_level: pd.DataFrame = field(default_factory=pd.DataFrame)
    meta: dict[str, Any] = field(default_factory=dict)


def run_timeshap(
    model_fn: Any,
    data: pd.DataFrame,
    baseline: pd.DataFrame | None = None,
    pruning_idx: int = 50,
    nsamples: int = 1000,
) -> TimeSHAPResult:
    """Run TimeSHAP attribution on a sequence model.

    Requires timeshap package (pip install timeshap).
    """
    from timeshap.explainer import local_report  # type: ignore[import-untyped]

    if baseline is None:
        baseline = pd.DataFrame(np.zeros((1, data.shape[1])), columns=data.columns)

    report = local_report(
        f=model_fn,
        data=data,
        pruning_idx=pruning_idx,
        nsamples=nsamples,
        baseline=baseline,
    )

    return TimeSHAPResult(
        event_level=report.get("event_level", pd.DataFrame()),
        feature_level=report.get("feature_level", pd.DataFrame()),
        cell_level=report.get("cell_level", pd.DataFrame()),
        meta={"pruning_idx": pruning_idx, "nsamples": nsamples},
    )
