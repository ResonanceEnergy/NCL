"""Causal — DoWhy causal inference panel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class CausalResult:
    estimate: float = 0.0
    p_value: float | None = None
    ci_lower: float | None = None
    ci_upper: float | None = None
    refutation_passed: bool = False
    refutation_details: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


def run_causal_estimate(
    df: pd.DataFrame,
    treatment: str,
    outcome: str,
    common_causes: list[str] | None = None,
    graph: str | None = None,
    refute: bool = True,
) -> CausalResult:
    """Run DoWhy causal estimate: identify → estimate → refute.

    Returns CausalResult with ATE and optional refutation.
    """
    import dowhy  # type: ignore[import-untyped]

    model = dowhy.CausalModel(
        data=df,
        treatment=treatment,
        outcome=outcome,
        common_causes=common_causes,
        graph=graph,
    )

    identified = model.identify_effect(proceed_when_unidentifiable=True)
    estimate = model.estimate_effect(
        identified,
        method_name="backdoor.linear_regression",
    )

    result = CausalResult(
        estimate=float(estimate.value),
        meta={"method": "backdoor.linear_regression", "treatment": treatment, "outcome": outcome},
    )

    if refute:
        # Placebo treatment refutation
        refutation = model.refute_estimate(
            identified,
            estimate,
            method_name="placebo_treatment_refuter",
            placebo_type="permute",
            num_simulations=100,
        )
        result.refutation_passed = refutation.estimated_effect is not None
        result.refutation_details = {
            "placebo_effect": float(refutation.new_effect) if refutation.new_effect is not None else None,
            "original_effect": float(estimate.value),
        }

    return result
