"""
NCL Auto-Trader Agent — Wave 14K

PAPER TRADING ONLY. NCL never places live orders. See
docs/AUTO_TRADER_AGENT_2026-05-26.md for the full architecture.

Package layout (built across Phases 1-8):

Phase 1 (this commit):
    state.py            - shared mutable state (paused/active, drawdown_pause_reason)
    policy.py           - entry-criteria policy (which ideas pass auto-bar)
    observability.py    - per-trade reasoning chain capture

Phase 2:
    loop.py             - main scheduler loop (poll -> policy -> open)

Phase 3:
    price_feed.py       - live-quote feeder for open paper symbols
    outcome_attributor.py - paper close -> trade_idea_tracker.update_outcome

Phase 4:
    strategy_bandit.py  - Thompson sampling over strategies

Phase 5:
    self_research.py    - SHAP attribution feedback into brief prompts

Phase 6:
    drift_detector.py   - ADDM on per-strategy hit-rate
    graduation_gate.py  - multi-criteria promotion gate

Phase 7:
    friction_profile.py - per-strategy slippage calibration

Phase 8:
    tests/              - tests + docs
"""

from .state import (  # noqa: F401
    AutoTraderState,
    get_state,
    is_active,
    pause,
    resume,
)
from .policy import (  # noqa: F401
    AutoTraderPolicy,
    default_policy,
    get_policy,
    update_policy,
    auto_open_eligible,
)
from .observability import (  # noqa: F401
    record_reasoning_chain,
    get_reasoning_chain,
    list_recent_chains,
)
from .loop import auto_trader_loop  # noqa: F401

__all__ = [
    "AutoTraderState", "get_state", "is_active", "pause", "resume",
    "AutoTraderPolicy", "default_policy", "get_policy", "update_policy",
    "auto_open_eligible",
    "record_reasoning_chain", "get_reasoning_chain", "list_recent_chains",
    "auto_trader_loop",
]
