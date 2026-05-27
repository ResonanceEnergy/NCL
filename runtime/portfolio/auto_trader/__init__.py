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
from .price_feed import price_feed_loop  # noqa: F401
from .outcome_attributor import (  # noqa: F401
    attribute_close, attribute_batch, trigger_to_outcome,
)
from .strategy_bandit import (  # noqa: F401
    StrategyBandit, StrategyPosterior, get_bandit,
)
from .shap_attribution import (  # noqa: F401
    maybe_run_attribution, run_attribution_for_strategy,
)
from .self_research import (  # noqa: F401
    apply_shap_to_authority_learner,
    generate_research_topics,
    resolve_research_topic,
    list_open_research_topics,
    brief_context_packet,
)
from .drift_detector import (  # noqa: F401
    update as drift_update,
    get_strategy_state as drift_get_state,
    all_states as drift_all_states,
    reset_strategy as drift_reset_strategy,
    maybe_auto_pause as drift_maybe_auto_pause,
    STABLE, DRIFT_DOWN, DRIFT_UP,
)
from .graduation_gate import (  # noqa: F401
    evaluate as graduation_evaluate,
    evaluate_all as graduation_evaluate_all,
    list_graduated_strategies,
)
from .friction_profile import (  # noqa: F401
    FrictionProfile,
    get_profile as friction_get_profile,
    update_profile as friction_update_profile,
    all_profiles as friction_all_profiles,
    apply_friction_to_payload,
    calibrate_from_closes as friction_calibrate_from_closes,
    maybe_calibrate as friction_maybe_calibrate,
)
from .calendar_gate import (  # noqa: F401
    check_calendar_block,
    calendar_summary,
)
from .working_context_gate import (  # noqa: F401
    check_working_context,
    working_context_summary,
)
from .council_check import (  # noqa: F401
    check_high_r_open,
)
from .eod_summary import (  # noqa: F401
    emit_eod_summary,
    eod_summary_loop,
)
from .strategy_registry import (  # noqa: F401
    StrategyRecipe,
    get_recipe,
    list_recipes,
    list_short_dated_lottery_recipes,
    list_long_dated_swing_recipes,
    update_recipe,
    normalize_strategy_via_registry,
    registry_summary,
)
from .profit_ladder import (  # noqa: F401
    maybe_ladder_from_close,
    ladder_summary,
)
from .options_recipes import (  # noqa: F401
    OptionLeg, OptionStructure,
    build_structure, list_builders, builder_count,
)
from .scout import (  # noqa: F401
    scout_tick, scout_loop, scout_summary,
)
from .capability_registry import (  # noqa: F401
    check_capability, check_and_request,
    list_capabilities, list_gaps, refresh_all as capability_refresh_all,
    capability_summary,
)
from .quant_scanners import (  # noqa: F401
    quant_scan_tick, quant_scan_loop, quant_scan_summary,
)

__all__ = [
    "AutoTraderState", "get_state", "is_active", "pause", "resume",
    "AutoTraderPolicy", "default_policy", "get_policy", "update_policy",
    "auto_open_eligible",
    "record_reasoning_chain", "get_reasoning_chain", "list_recent_chains",
    "auto_trader_loop",
    "price_feed_loop",
    "attribute_close", "attribute_batch", "trigger_to_outcome",
    "StrategyBandit", "StrategyPosterior", "get_bandit",
    "maybe_run_attribution", "run_attribution_for_strategy",
    "apply_shap_to_authority_learner",
    "generate_research_topics", "resolve_research_topic",
    "list_open_research_topics", "brief_context_packet",
    # Wave 14K Phase 6 (K5a/b/c/d)
    "drift_update", "drift_get_state", "drift_all_states",
    "drift_reset_strategy", "drift_maybe_auto_pause",
    "STABLE", "DRIFT_DOWN", "DRIFT_UP",
    "graduation_evaluate", "graduation_evaluate_all",
    "list_graduated_strategies",
    # Wave 14K Phase 7 (K6a/b/c)
    "FrictionProfile",
    "friction_get_profile", "friction_update_profile",
    "friction_all_profiles", "apply_friction_to_payload",
    "friction_calibrate_from_closes", "friction_maybe_calibrate",
    # Wave 14K hardening — calendar + working-context awareness
    "check_calendar_block", "calendar_summary",
    "check_working_context", "working_context_summary",
    # Wave 14K gap-closes — council quorum + EOD summary
    "check_high_r_open", "emit_eod_summary", "eod_summary_loop",
    # Wave 14L L1 — strategy registry (20+ named recipes)
    "StrategyRecipe", "get_recipe", "list_recipes",
    "list_short_dated_lottery_recipes", "list_long_dated_swing_recipes",
    "update_recipe", "normalize_strategy_via_registry", "registry_summary",
    # Wave 14L L4 — profit ladder
    "maybe_ladder_from_close", "ladder_summary",
    # Wave 14L L3 — options recipe library (multi-leg builders)
    "OptionLeg", "OptionStructure", "build_structure",
    "list_builders", "builder_count",
    # Wave 14L L6 — pro-active scout loop
    "scout_tick", "scout_loop", "scout_summary",
    # Wave 14L L5 — capability registry + tool-request
    "check_capability", "check_and_request",
    "list_capabilities", "list_gaps", "capability_refresh_all",
    "capability_summary",
    # Wave 14L L2 — quant scanner suite
    "quant_scan_tick", "quant_scan_loop", "quant_scan_summary",
]
