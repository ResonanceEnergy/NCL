"""One-shot: append NATRIX-tier mandate MemUnit to units.jsonl."""

import json
import uuid
from datetime import datetime, timezone


units_path = "/Users/natrix/dev/NCL/data/memory/units.jsonl"

now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
unit = {
    "unit_id": str(uuid.uuid4()),
    "content": (
        "MANDATE — NCL Hedge Fund Manager in Training. As of 2026-05-26, "
        "NCL operates a paper-trading account that mirrors NATRIX's live "
        "portfolio: starting NAV $36,149 CAD across 22 positions (21 "
        "from live snapshot + 1 baseline) spanning IBKR, Moomoo, and "
        "Wealthsimple. Mandate: MAXIMIZE CAPITAL through stocks + options "
        "trading using self-research, self-learning, self-analysis, and "
        "self-management. Risk per trade: 5% NAV (~$1,800). Max 8 opens "
        "per day, 2 per tick. Counter-trend trades blocked by default. "
        "The auto-trader runs the full Wave 14K closed loop: brief emits "
        "ideas → friction-injected paper opens → mark-to-market → outcome "
        "attribution → Beta-Bernoulli bandit + SHAP + Page-Hinkley drift "
        "→ self-research generates topics → brief context packet biases "
        "next-day allocation → graduation gate publishes readiness. "
        "ABSOLUTE CONSTRAINT: NCL never places live orders. Paper-only. "
        "Graduation = decision support; promotion to live = operator-only. "
        "Strategies tagged 'snapshot' are the baseline being benchmarked."
    ),
    "source": "natrix:mandate:hedge_fund_in_training",
    "importance": 100.0,
    "decay_rate": 0.999,  # LML — facts/mandates decay slowly
    "last_accessed": now,
    "reinforcement_count": 0,
    "tags": [
        "natrix",
        "mandate",
        "auto_trader",
        "hedge_fund_training",
        "wave_14K",
        "paper_only",
        "maximize_capital",
    ],
    "created_at": now,
    "related_units": [],
    "memory_type": "procedural",  # mandate = procedural rule
    "memory_tier": "LML",
    "llm_importance_score": None,
    "entities": ["NCL", "NATRIX", "PaperTradingEngine", "Wave 14K"],
    "relationships": [],
    "consolidated_from": [],
    "reflection_quality": 1.0,
    "metadata": {
        "wave": "14K",
        "authority_tier": "NATRIX",
        "authority_weight": 100,
        "starting_nav_cad": 36148.86,
        "starting_positions": 22,
        "risk_per_trade_pct": 5.0,
        "max_opens_per_day": 8,
        "max_opens_per_tick": 2,
        "operator_set_at_iso": now,
    },
}

with open(units_path, "a") as f:
    f.write(json.dumps(unit) + "\n")

print(f"OK appended mandate unit {unit['unit_id']}")
print(f"   source={unit['source']}")
print(f"   importance={unit['importance']}")
print(f"   tags={unit['tags']}")
