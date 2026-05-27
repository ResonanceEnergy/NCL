"""
Auto-Trader strategy registry — Wave 14L L1

Today's risk_governor knows 6 budget buckets (goat / bravo / options /
polymarket / manual / unknown). That's too coarse for a multi-function
hedge-fund-in-training agent.

This module ships a registry of ~20 NAMED RECIPES, each with the
metadata the loop + governor + brief executor need to:
  - validate a trade idea against the recipe's contract (asset_type,
    DTE bounds, direction, vol_regime, leg_count)
  - look up per-recipe heat cap (separate from the broader bucket
    budget) so each recipe can be tuned without re-tuning the bucket
  - emit a brief executor prompt block listing what's *available*
    instead of having to memorize the list
  - feed the profit-ladder meta-strategy (L4) which needs to know
    which recipes are "short-dated lottery" and which are "long-dated
    swing"

The registry maps each recipe → a budget_bucket name that maps into
the existing risk_governor budget table. Backward-compatible — every
existing strategy_tag still works.

Storage:
  data/portfolio/auto_trader/strategy_registry_state.json  (operator overrides)

Tunables (env):
  NCL_AT_REGISTRY_FILE=...   (override default path)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.strategy_registry")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
STATE_FILE = Path(
    os.getenv(
        "NCL_AT_REGISTRY_FILE",
        str(NCL_BASE / "data" / "portfolio" / "auto_trader" / "strategy_registry_state.json"),
    )
)


@dataclass
class StrategyRecipe:
    """Single named strategy recipe with full contract metadata."""

    name: str
    bucket: str  # maps to risk_governor budget bucket (back-compat)
    asset_type: str  # "stock" | "options" | "futures" | "crypto" | "polymarket"
    direction: str  # "long" | "short" | "neutral" | "either"
    vol_regime: str = "any"  # "high_iv" | "low_iv" | "any"
    dte_min: Optional[int] = None  # days-to-expiry lower bound (options only)
    dte_max: Optional[int] = None  # days-to-expiry upper bound (options only)
    leg_count: int = 1  # 1 = single instrument; 2+ = spread/condor/etc
    max_R_pct_nav: float = 1.0  # per-recipe cap as % NAV (defensive default)
    typical_hold_days: int = 5
    profit_target_R: float = 2.0  # default R-target for profit-ladder trigger
    description: str = ""
    tags: list = field(default_factory=list)
    enabled: bool = True

    def is_short_dated_lottery(self) -> bool:
        """Profit-ladder source: short-dated long options taken for outsized
        return-on-premium. These are the wins we roll into LEAPS."""
        return (
            self.asset_type == "options"
            and self.leg_count == 1
            and self.direction in ("long", "either")
            and (self.dte_max is None or self.dte_max <= 45)
            and "lottery" in self.tags
        )

    def is_long_dated_swing(self) -> bool:
        """Profit-ladder destination: 6-12mo+ LEAPS for swing exposure."""
        return (
            self.asset_type == "options"
            and self.direction in ("long", "either")
            and (self.dte_min is None or self.dte_min >= 120)
            and "leaps" in self.tags
        )


# ─────────────────────────────────────────────────────────────────────
# DEFAULT REGISTRY — 20+ named recipes
# ─────────────────────────────────────────────────────────────────────

DEFAULT_RECIPES: list[StrategyRecipe] = [
    # ── Stock directional ──────────────────────────────────────────
    StrategyRecipe(
        name="momentum_breakout",
        bucket="goat", asset_type="stock", direction="long",
        leg_count=1, max_R_pct_nav=3.0, typical_hold_days=3,
        profit_target_R=2.5,
        description="GOAT-style momentum + 150SMA gate + ATR stop",
        tags=["momentum", "breakout", "trend_following"],
    ),
    StrategyRecipe(
        name="swing_pullback",
        bucket="bravo", asset_type="stock", direction="long",
        leg_count=1, max_R_pct_nav=2.0, typical_hold_days=10,
        profit_target_R=2.0,
        description="BRAVO-style pullback-to-200SMA swing, two-tier exit",
        tags=["swing", "pullback", "mean_reversion_soft"],
    ),
    StrategyRecipe(
        name="mean_reversion_oversold",
        bucket="bravo", asset_type="stock", direction="long",
        leg_count=1, max_R_pct_nav=1.5, typical_hold_days=4,
        profit_target_R=1.5,
        description="RSI<30 + Bollinger lower band touch on uptrending stock",
        tags=["mean_reversion", "rsi", "bollinger"],
    ),
    # Wave 14S — auto-emitted by the GOAT scanner (Felix Friends 6-rule trend)
    # when goat_score >= NCL_SCANNER_AUTO_EMIT_MIN_GOAT (default 80).
    StrategyRecipe(
        name="goat_trend",
        bucket="goat", asset_type="stock", direction="long",
        leg_count=1, max_R_pct_nav=2.5, typical_hold_days=60,
        profit_target_R=2.0,
        description="GOAT Academy 6-rule trend-following: above 150-SMA + 50-SMA rising + RSI 40-70 + volume surge + breakout",
        tags=["trend_following", "goat_academy", "scanner_emit"],
    ),
    # Wave 14S — auto-emitted by the BRAVO scanner (Johnny Bravo / Stenzel)
    # when bravo_score >= NCL_SCANNER_AUTO_EMIT_MIN_BRAVO (default 75).
    StrategyRecipe(
        name="bravo_swing",
        bucket="bravo", asset_type="stock", direction="long",
        leg_count=1, max_R_pct_nav=2.0, typical_hold_days=15,
        profit_target_R=2.0,
        description="Johnny Bravo MA-stack swing: SMA-9 > EMA-20 > SMA-180 aligned, green candle above SMA-9",
        tags=["swing", "bravo", "ma_stack", "scanner_emit"],
    ),
    StrategyRecipe(
        name="gap_fill",
        bucket="goat", asset_type="stock", direction="either",
        leg_count=1, max_R_pct_nav=1.5, typical_hold_days=2,
        profit_target_R=1.5,
        description="Gap >2% pre-market, fade back to gap-fill zone",
        tags=["intraday", "gap", "fade"],
    ),
    StrategyRecipe(
        name="pead_drift",
        bucket="bravo", asset_type="stock", direction="long",
        leg_count=1, max_R_pct_nav=2.0, typical_hold_days=20,
        profit_target_R=2.5,
        description="Post-earnings drift: long surprise winners, ride 20d momentum",
        tags=["pead", "earnings_momentum"],
    ),
    StrategyRecipe(
        name="pairs_stat_arb",
        bucket="bravo", asset_type="stock", direction="neutral",
        leg_count=2, max_R_pct_nav=1.5, typical_hold_days=10,
        profit_target_R=1.5,
        description="Cointegrated pair z-score > 2 entry; mean-revert exit",
        tags=["stat_arb", "pairs", "neutral"],
    ),
    StrategyRecipe(
        name="sector_rotation",
        bucket="bravo", asset_type="stock", direction="long",
        leg_count=1, max_R_pct_nav=2.5, typical_hold_days=30,
        profit_target_R=2.5,
        description="Rotate into RRG Leading-quadrant sector ETF, exit on quadrant flip",
        tags=["rotation", "sector_etf", "long_only"],
    ),

    # ── Options — short-dated lottery (profit-ladder SOURCE) ──────
    StrategyRecipe(
        name="lottery_calls_short_dated",
        bucket="options", asset_type="options", direction="long",
        vol_regime="any", dte_min=3, dte_max=30, leg_count=1,
        max_R_pct_nav=1.0, typical_hold_days=5, profit_target_R=3.0,
        description="OTM call lottery on momentum/catalyst; <30 DTE; 3R+ target",
        tags=["lottery", "directional", "short_dated"],
    ),
    StrategyRecipe(
        name="lottery_puts_short_dated",
        bucket="options", asset_type="options", direction="short",
        vol_regime="any", dte_min=3, dte_max=30, leg_count=1,
        max_R_pct_nav=1.0, typical_hold_days=5, profit_target_R=3.0,
        description="OTM put lottery on bearish catalyst; <30 DTE",
        tags=["lottery", "directional", "short_dated"],
    ),

    # ── Options — long-dated swing (profit-ladder DESTINATION) ────
    StrategyRecipe(
        name="leaps_long_dated",
        bucket="options", asset_type="options", direction="either",
        vol_regime="low_iv", dte_min=120, dte_max=540, leg_count=1,
        max_R_pct_nav=3.0, typical_hold_days=180, profit_target_R=2.5,
        description="6-18mo LEAPS for swing exposure on conviction names",
        tags=["leaps", "long_dated", "swing", "directional"],
    ),
    StrategyRecipe(
        name="pmcc",
        bucket="options", asset_type="options", direction="long",
        vol_regime="any", dte_min=60, dte_max=540, leg_count=2,
        max_R_pct_nav=2.5, typical_hold_days=90, profit_target_R=2.0,
        description="Poor Man's Covered Call: long ITM LEAP + short OTM monthly",
        tags=["pmcc", "spread", "income", "directional"],
    ),

    # ── Options — defined-risk spreads ────────────────────────────
    StrategyRecipe(
        name="vertical_bull_call",
        bucket="options", asset_type="options", direction="long",
        vol_regime="any", dte_min=14, dte_max=60, leg_count=2,
        max_R_pct_nav=1.5, typical_hold_days=21, profit_target_R=1.5,
        description="Bull call vertical spread; defined risk + reward",
        tags=["vertical", "spread", "directional"],
    ),
    StrategyRecipe(
        name="vertical_bear_put",
        bucket="options", asset_type="options", direction="short",
        vol_regime="any", dte_min=14, dte_max=60, leg_count=2,
        max_R_pct_nav=1.5, typical_hold_days=21, profit_target_R=1.5,
        description="Bear put vertical spread; defined risk + reward",
        tags=["vertical", "spread", "directional"],
    ),
    StrategyRecipe(
        name="iron_condor_low_vol",
        bucket="options", asset_type="options", direction="neutral",
        vol_regime="high_iv", dte_min=30, dte_max=60, leg_count=4,
        max_R_pct_nav=2.0, typical_hold_days=21, profit_target_R=0.5,
        description="4-leg neutral; high-IVR entry; 50% credit exit",
        tags=["iron_condor", "theta", "neutral", "high_ivr"],
    ),
    StrategyRecipe(
        name="straddle_earnings",
        bucket="options", asset_type="options", direction="neutral",
        vol_regime="low_iv", dte_min=2, dte_max=14, leg_count=2,
        max_R_pct_nav=1.0, typical_hold_days=1, profit_target_R=1.5,
        description="ATM straddle into earnings on low-IV setup",
        tags=["straddle", "earnings", "vol_play"],
    ),
    StrategyRecipe(
        name="calendar_vol_term",
        bucket="options", asset_type="options", direction="neutral",
        vol_regime="any", dte_min=21, dte_max=90, leg_count=2,
        max_R_pct_nav=1.0, typical_hold_days=21, profit_target_R=1.0,
        description="Sell front-month, buy back-month — exploit term structure",
        tags=["calendar", "vol_term", "spread"],
    ),

    # ── Options — income ──────────────────────────────────────────
    StrategyRecipe(
        name="covered_call_income",
        bucket="options", asset_type="options", direction="short",
        vol_regime="any", dte_min=21, dte_max=45, leg_count=1,
        max_R_pct_nav=2.0, typical_hold_days=30, profit_target_R=0.5,
        description="Sell 30-45 DTE OTM call on stock you own; collect premium",
        tags=["income", "covered_call", "theta"],
    ),
    StrategyRecipe(
        name="csp_income",
        bucket="options", asset_type="options", direction="long",
        vol_regime="any", dte_min=21, dte_max=45, leg_count=1,
        max_R_pct_nav=2.0, typical_hold_days=30, profit_target_R=0.5,
        description="Cash-secured put on stock you'd buy anyway; collect premium",
        tags=["income", "csp", "theta", "wheel"],
    ),

    # ── Copy + alt ────────────────────────────────────────────────
    StrategyRecipe(
        name="whale_copy_options_flow",
        bucket="options", asset_type="options", direction="either",
        vol_regime="any", dte_min=7, dte_max=180, leg_count=1,
        max_R_pct_nav=1.5, typical_hold_days=14, profit_target_R=2.0,
        description="Copy big-money options flow from Unusual Whales; size-capped",
        tags=["copy", "whale", "options_flow"],
    ),
    StrategyRecipe(
        name="polymarket_kelly",
        bucket="polymarket", asset_type="polymarket", direction="long",
        leg_count=1, max_R_pct_nav=1.0, typical_hold_days=14,
        profit_target_R=1.0,
        description="Polymarket positions sized by Kelly criterion; must be positive Kelly",
        tags=["polymarket", "kelly", "prediction"],
    ),
    StrategyRecipe(
        name="crypto_carry",
        bucket="unknown", asset_type="crypto", direction="long",
        leg_count=1, max_R_pct_nav=1.0, typical_hold_days=30,
        profit_target_R=1.5,
        description="Funding-rate carry on perp/spot basis; flatten on flip",
        tags=["crypto", "carry", "basis"],
    ),

    # ── Special ──────────────────────────────────────────────────
    StrategyRecipe(
        name="snapshot",
        bucket="manual", asset_type="stock", direction="either",
        leg_count=1, max_R_pct_nav=20.0, typical_hold_days=365,
        description="Live portfolio mirror (Wave 14K post-build harness)",
        tags=["snapshot", "live_mirror"],
        enabled=True,
    ),
    StrategyRecipe(
        name="manual",
        bucket="manual", asset_type="stock", direction="either",
        leg_count=1, max_R_pct_nav=3.0, typical_hold_days=14,
        description="Operator-initiated manual trade",
        tags=["manual"],
    ),
]


_REGISTRY: dict[str, StrategyRecipe] = {}
_LOCK = asyncio.Lock()
_LOADED = False


def _load_registry() -> None:
    """Build the registry from defaults + persist + apply operator overrides."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    # Seed with defaults
    for r in DEFAULT_RECIPES:
        _REGISTRY[r.name] = r
    # Apply operator overrides from disk (additive — overrides don't replace defaults)
    if STATE_FILE.exists():
        try:
            raw = json.loads(STATE_FILE.read_text())
            if isinstance(raw, dict):
                field_names = {f for f in StrategyRecipe.__dataclass_fields__}  # type: ignore[attr-defined]
                for name, payload in raw.items():
                    if not isinstance(payload, dict):
                        continue
                    kept = {k: v for k, v in payload.items() if k in field_names}
                    kept.setdefault("name", name)
                    try:
                        _REGISTRY[name] = StrategyRecipe(**kept)
                    except Exception as e:
                        log.warning("[REGISTRY] skipping malformed override %s: %s", name, e)
        except Exception as e:
            log.warning("[REGISTRY] override load failed: %s", e)


def _persist_overrides_only(overrides: dict[str, dict]) -> None:
    """Only operator overrides go on disk — defaults stay code-resident."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(overrides, indent=2, sort_keys=True))
        tmp.replace(STATE_FILE)
    except Exception as e:
        log.error("[REGISTRY] persist failed: %s", e)


async def get_recipe(name: str) -> Optional[StrategyRecipe]:
    """Look up a recipe by name. Returns None if unknown."""
    async with _LOCK:
        _load_registry()
        return _REGISTRY.get(name)


async def list_recipes(
    *,
    asset_type: Optional[str] = None,
    enabled_only: bool = True,
) -> list[StrategyRecipe]:
    async with _LOCK:
        _load_registry()
        recipes = list(_REGISTRY.values())
    if enabled_only:
        recipes = [r for r in recipes if r.enabled]
    if asset_type:
        recipes = [r for r in recipes if r.asset_type == asset_type]
    return sorted(recipes, key=lambda r: (r.bucket, r.name))


async def list_short_dated_lottery_recipes() -> list[str]:
    """Profit-ladder SOURCE names — closes from these trigger ladder rolls."""
    recipes = await list_recipes()
    return [r.name for r in recipes if r.is_short_dated_lottery()]


async def list_long_dated_swing_recipes() -> list[str]:
    """Profit-ladder DESTINATION names — what we roll wins INTO."""
    recipes = await list_recipes()
    return [r.name for r in recipes if r.is_long_dated_swing()]


async def update_recipe(name: str, **patches) -> Optional[StrategyRecipe]:
    """Operator override of a recipe. Persisted to disk."""
    async with _LOCK:
        _load_registry()
        if name not in _REGISTRY:
            return None
        current = _REGISTRY[name]
        field_names = {f for f in StrategyRecipe.__dataclass_fields__}  # type: ignore[attr-defined]
        unknown = [k for k in patches if k not in field_names]
        if unknown:
            raise ValueError(f"Unknown recipe fields: {unknown}")
        for k, v in patches.items():
            setattr(current, k, v)
        # Persist all overrides (not just the changed one) so the file is full state
        overrides = {n: asdict(r) for n, r in _REGISTRY.items()}
        _persist_overrides_only(overrides)
        log.info("[REGISTRY] %s patched: %s", name, list(patches.keys()))
        return current


async def normalize_strategy_via_registry(tag: Optional[str]) -> str:
    """Returns the budget bucket for a strategy name. Falls back to the
    existing risk_governor._normalize_strategy if the name isn't in the
    registry (backward compat)."""
    if not tag:
        return "unknown"
    recipe = await get_recipe(str(tag).lower().strip())
    if recipe:
        return recipe.bucket
    # Fallback to risk_governor's aliasing
    try:
        from ..risk_governor import _normalize_strategy
        return _normalize_strategy(tag)
    except Exception:
        return "unknown"


async def registry_summary() -> dict:
    """Snapshot for /dashboard rollup."""
    recipes = await list_recipes(enabled_only=False)
    by_bucket: dict[str, int] = {}
    by_asset: dict[str, int] = {}
    for r in recipes:
        by_bucket[r.bucket] = by_bucket.get(r.bucket, 0) + 1
        by_asset[r.asset_type] = by_asset.get(r.asset_type, 0) + 1
    return {
        "total_recipes": len(recipes),
        "enabled_count": sum(1 for r in recipes if r.enabled),
        "by_bucket": by_bucket,
        "by_asset_type": by_asset,
        "short_dated_lottery": await list_short_dated_lottery_recipes(),
        "long_dated_swing": await list_long_dated_swing_recipes(),
    }
