"""
Auto-Trader options recipe library — Wave 14L L3

Recipe-based multi-leg builders. The auto-trader no longer emits just
"long single option" — it can construct proper option structures:

  lottery_calls_short_dated   — 1 leg, 5-delta OTM, <30 DTE
  lottery_puts_short_dated    — 1 leg, 5-delta OTM put, <30 DTE
  leaps_long_dated            — 1 leg, deep ITM call/put, 6-18mo
  pmcc                        — 2 legs: long ITM LEAP + short OTM monthly
  vertical_bull_call          — 2 legs: long ATM call + short OTM call
  vertical_bear_put           — 2 legs: long ATM put + short OTM put
  iron_condor_low_vol         — 4 legs: short put spread + short call spread
  straddle_earnings           — 2 legs: long ATM call + long ATM put
  calendar_vol_term           — 2 legs: short front-month + long back-month
  covered_call_income         — 1 leg: short 30-45 DTE OTM call (on owned stock)
  csp_income                  — 1 leg: short 30-45 DTE OTM put (cash-secured)
  whale_copy_options_flow     — 1 leg: mirror whale strike/expiry

Each `build_legs(...)` returns a list of OptionLeg dicts. The loop
attaches the legs to scanner_data.legs on emit; iOS + observability
chains can render the multi-leg structure.

NOTE: This module ONLY builds the structure. The auto-trader's paper
engine uses single-instrument fills today; multi-leg payloads are
recorded for display + future live-promotion bridging but executed as
the dominant leg (longest-dated long position) in paper.

Tunables (env):
  NCL_AT_LOTTERY_DELTA=0.10        (target delta for short-dated calls)
  NCL_AT_LEAPS_DELTA=0.80          (target delta for LEAPS = deep ITM)
  NCL_AT_VERTICAL_WIDTH_PCT=5      (call spread width as % of underlying)
  NCL_AT_IC_WING_WIDTH_PCT=5       (iron-condor wing width)
  NCL_AT_IC_BODY_PCT=10            (iron-condor body width from spot)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.options_recipes")

LOTTERY_DELTA = float(os.getenv("NCL_AT_LOTTERY_DELTA", "0.10"))
LEAPS_DELTA = float(os.getenv("NCL_AT_LEAPS_DELTA", "0.80"))
VERTICAL_WIDTH_PCT = float(os.getenv("NCL_AT_VERTICAL_WIDTH_PCT", "5"))
IC_WING_WIDTH_PCT = float(os.getenv("NCL_AT_IC_WING_WIDTH_PCT", "5"))
IC_BODY_PCT = float(os.getenv("NCL_AT_IC_BODY_PCT", "10"))


@dataclass
class OptionLeg:
    """Single option leg in a multi-leg structure."""

    side: str             # "long" | "short"
    option_type: str      # "call" | "put"
    strike: float
    dte_target: int       # target days-to-expiry; engine picks closest available
    qty: int = 1
    action: str = "buy_to_open"  # "buy_to_open" | "sell_to_open"
    delta_target: Optional[float] = None  # for delta-based recipes
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OptionStructure:
    """Full multi-leg structure returned by a recipe builder."""

    recipe_name: str
    underlying: str
    legs: list  # list[OptionLeg]
    direction: str        # net direction: long / short / neutral
    max_risk_per_share: float  # for R-multiple math (premium paid or width-credit)
    max_reward_per_share: float
    target_dte_min: int
    target_dte_max: int
    vol_regime_target: str = "any"  # "high_iv" | "low_iv" | "any"
    notes: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["legs"] = [l.to_dict() if hasattr(l, "to_dict") else l for l in self.legs]
        return d


# ─────────────────────────────────────────────────────────────────────
# Helper: round strike to typical option-strike spacing
# ─────────────────────────────────────────────────────────────────────

def _round_strike(price: float) -> float:
    """Round to typical strike spacing: $0.50 below $25, $1 below $200, $5 above."""
    if price <= 0:
        return 0
    if price < 25:
        return round(price * 2) / 2
    if price < 200:
        return round(price)
    return round(price / 5) * 5


# ─────────────────────────────────────────────────────────────────────
# Recipe builders
# ─────────────────────────────────────────────────────────────────────

def build_lottery_calls(*, underlying: str, underlying_price: float,
                         dte_target: int = 14) -> OptionStructure:
    """Short-dated OTM call lottery. Cheap, lottery-ticket payoff."""
    # ~10-delta OTM ≈ +5% strike for short DTE
    strike = _round_strike(underlying_price * 1.05)
    # Premium estimate: ~$0.50-1.50 per share for OTM short-dated
    est_premium = max(0.50, underlying_price * 0.01)
    return OptionStructure(
        recipe_name="lottery_calls_short_dated",
        underlying=underlying,
        legs=[OptionLeg(
            side="long", option_type="call", strike=strike,
            dte_target=dte_target, qty=1, action="buy_to_open",
            delta_target=LOTTERY_DELTA,
            description=f"OTM call ${strike} ({dte_target}d)",
        )],
        direction="long",
        max_risk_per_share=est_premium,
        max_reward_per_share=est_premium * 10,  # 10x potential
        target_dte_min=max(3, dte_target - 7),
        target_dte_max=min(30, dte_target + 7),
        vol_regime_target="any",
        notes="OTM call lottery on momentum catalyst; full premium at risk",
    )


def build_lottery_puts(*, underlying: str, underlying_price: float,
                       dte_target: int = 14) -> OptionStructure:
    """Short-dated OTM put lottery for bearish catalysts."""
    strike = _round_strike(underlying_price * 0.95)
    est_premium = max(0.50, underlying_price * 0.01)
    return OptionStructure(
        recipe_name="lottery_puts_short_dated",
        underlying=underlying,
        legs=[OptionLeg(
            side="long", option_type="put", strike=strike,
            dte_target=dte_target, qty=1, action="buy_to_open",
            delta_target=-LOTTERY_DELTA,
            description=f"OTM put ${strike} ({dte_target}d)",
        )],
        direction="short",
        max_risk_per_share=est_premium,
        max_reward_per_share=est_premium * 10,
        target_dte_min=max(3, dte_target - 7),
        target_dte_max=min(30, dte_target + 7),
        vol_regime_target="any",
        notes="OTM put lottery on bearish catalyst",
    )


def build_leaps(*, underlying: str, underlying_price: float, direction: str = "long",
                dte_target: int = 270) -> OptionStructure:
    """Deep-ITM LEAP for swing exposure. ~80-delta call (or put for short)."""
    if direction == "long":
        # 80-delta call ≈ 15-20% ITM
        strike = _round_strike(underlying_price * 0.83)
        option_type = "call"
        est_premium = underlying_price * 0.22  # rough ITM + time-value est
    else:
        strike = _round_strike(underlying_price * 1.17)
        option_type = "put"
        est_premium = underlying_price * 0.22
    return OptionStructure(
        recipe_name="leaps_long_dated",
        underlying=underlying,
        legs=[OptionLeg(
            side="long", option_type=option_type, strike=strike,
            dte_target=dte_target, qty=1, action="buy_to_open",
            delta_target=LEAPS_DELTA if direction == "long" else -LEAPS_DELTA,
            description=f"Deep-ITM {option_type} ${strike} ({dte_target}d ≈ 9mo)",
        )],
        direction=direction,
        max_risk_per_share=est_premium,
        max_reward_per_share=est_premium * 1.5,  # LEAPS slow movers, ~150% upside
        target_dte_min=max(120, dte_target - 60),
        target_dte_max=min(540, dte_target + 90),
        vol_regime_target="low_iv",  # cheaper to enter when IV is low
        notes="Deep-ITM LEAP for swing exposure on conviction names",
    )


def build_pmcc(*, underlying: str, underlying_price: float) -> OptionStructure:
    """Poor Man's Covered Call: long ITM LEAP + short OTM monthly.
    Cheaper than covered call; same exposure profile."""
    leap_strike = _round_strike(underlying_price * 0.83)
    short_strike = _round_strike(underlying_price * 1.05)
    leap_premium = underlying_price * 0.22
    short_premium = max(0.50, underlying_price * 0.015)
    net_debit = leap_premium - short_premium
    return OptionStructure(
        recipe_name="pmcc",
        underlying=underlying,
        legs=[
            OptionLeg(
                side="long", option_type="call", strike=leap_strike,
                dte_target=270, qty=1, action="buy_to_open",
                delta_target=LEAPS_DELTA,
                description=f"Long ITM LEAP call ${leap_strike} (270d)",
            ),
            OptionLeg(
                side="short", option_type="call", strike=short_strike,
                dte_target=30, qty=1, action="sell_to_open",
                delta_target=0.30,
                description=f"Short OTM monthly call ${short_strike} (30d)",
            ),
        ],
        direction="long",
        max_risk_per_share=net_debit,
        max_reward_per_share=(short_strike - leap_strike) - net_debit,
        target_dte_min=60,
        target_dte_max=540,
        vol_regime_target="any",
        notes="PMCC — long LEAP synthetic-stock + short monthly premium harvest",
    )


def build_vertical_bull_call(*, underlying: str, underlying_price: float,
                              dte_target: int = 30) -> OptionStructure:
    """Bull call spread: long ATM call + short OTM call."""
    width_dollars = underlying_price * (VERTICAL_WIDTH_PCT / 100.0)
    long_strike = _round_strike(underlying_price)
    short_strike = _round_strike(underlying_price + width_dollars)
    est_debit = (short_strike - long_strike) * 0.40  # rough
    return OptionStructure(
        recipe_name="vertical_bull_call",
        underlying=underlying,
        legs=[
            OptionLeg(
                side="long", option_type="call", strike=long_strike,
                dte_target=dte_target, qty=1, action="buy_to_open",
                description=f"Long ATM call ${long_strike}",
            ),
            OptionLeg(
                side="short", option_type="call", strike=short_strike,
                dte_target=dte_target, qty=1, action="sell_to_open",
                description=f"Short OTM call ${short_strike}",
            ),
        ],
        direction="long",
        max_risk_per_share=est_debit,
        max_reward_per_share=(short_strike - long_strike) - est_debit,
        target_dte_min=14, target_dte_max=60,
        vol_regime_target="any",
        notes=f"Bull call vertical, ${width_dollars:.0f} wide; defined risk",
    )


def build_vertical_bear_put(*, underlying: str, underlying_price: float,
                             dte_target: int = 30) -> OptionStructure:
    """Bear put spread: long ATM put + short OTM put."""
    width_dollars = underlying_price * (VERTICAL_WIDTH_PCT / 100.0)
    long_strike = _round_strike(underlying_price)
    short_strike = _round_strike(underlying_price - width_dollars)
    est_debit = (long_strike - short_strike) * 0.40
    return OptionStructure(
        recipe_name="vertical_bear_put",
        underlying=underlying,
        legs=[
            OptionLeg(
                side="long", option_type="put", strike=long_strike,
                dte_target=dte_target, qty=1, action="buy_to_open",
                description=f"Long ATM put ${long_strike}",
            ),
            OptionLeg(
                side="short", option_type="put", strike=short_strike,
                dte_target=dte_target, qty=1, action="sell_to_open",
                description=f"Short OTM put ${short_strike}",
            ),
        ],
        direction="short",
        max_risk_per_share=est_debit,
        max_reward_per_share=(long_strike - short_strike) - est_debit,
        target_dte_min=14, target_dte_max=60,
        vol_regime_target="any",
        notes=f"Bear put vertical, ${width_dollars:.0f} wide",
    )


def build_iron_condor(*, underlying: str, underlying_price: float,
                       dte_target: int = 45) -> OptionStructure:
    """4-leg iron condor: short put spread + short call spread.
    High-IVR entry, 50% credit exit."""
    body_dollars = underlying_price * (IC_BODY_PCT / 100.0)
    wing_dollars = underlying_price * (IC_WING_WIDTH_PCT / 100.0)
    short_put_strike = _round_strike(underlying_price - body_dollars)
    long_put_strike = _round_strike(short_put_strike - wing_dollars)
    short_call_strike = _round_strike(underlying_price + body_dollars)
    long_call_strike = _round_strike(short_call_strike + wing_dollars)
    est_credit = wing_dollars * 0.35  # rough credit estimate
    return OptionStructure(
        recipe_name="iron_condor_low_vol",
        underlying=underlying,
        legs=[
            OptionLeg(
                side="long", option_type="put", strike=long_put_strike,
                dte_target=dte_target, qty=1, action="buy_to_open",
                description=f"Long put ${long_put_strike} (wing)",
            ),
            OptionLeg(
                side="short", option_type="put", strike=short_put_strike,
                dte_target=dte_target, qty=1, action="sell_to_open",
                description=f"Short put ${short_put_strike} (body)",
            ),
            OptionLeg(
                side="short", option_type="call", strike=short_call_strike,
                dte_target=dte_target, qty=1, action="sell_to_open",
                description=f"Short call ${short_call_strike} (body)",
            ),
            OptionLeg(
                side="long", option_type="call", strike=long_call_strike,
                dte_target=dte_target, qty=1, action="buy_to_open",
                description=f"Long call ${long_call_strike} (wing)",
            ),
        ],
        direction="neutral",
        max_risk_per_share=wing_dollars - est_credit,
        max_reward_per_share=est_credit,
        target_dte_min=30, target_dte_max=60,
        vol_regime_target="high_iv",
        notes=(
            f"Iron condor: ±${body_dollars:.0f} body, ${wing_dollars:.0f} wings; "
            f"high-IVR entry, 50% credit exit"
        ),
    )


def build_straddle(*, underlying: str, underlying_price: float,
                    dte_target: int = 7) -> OptionStructure:
    """ATM straddle: long ATM call + long ATM put. Earnings vol play."""
    strike = _round_strike(underlying_price)
    est_premium_each = underlying_price * 0.04  # rough ATM premium
    total_premium = est_premium_each * 2
    return OptionStructure(
        recipe_name="straddle_earnings",
        underlying=underlying,
        legs=[
            OptionLeg(
                side="long", option_type="call", strike=strike,
                dte_target=dte_target, qty=1, action="buy_to_open",
                description=f"Long ATM call ${strike}",
            ),
            OptionLeg(
                side="long", option_type="put", strike=strike,
                dte_target=dte_target, qty=1, action="buy_to_open",
                description=f"Long ATM put ${strike}",
            ),
        ],
        direction="neutral",
        max_risk_per_share=total_premium,
        max_reward_per_share=total_premium * 2,
        target_dte_min=2, target_dte_max=14,
        vol_regime_target="low_iv",
        notes="ATM straddle into earnings on low-IV entry",
    )


def build_calendar(*, underlying: str, underlying_price: float,
                    dte_target_short: int = 21,
                    dte_target_long: int = 60) -> OptionStructure:
    """Calendar spread: short front-month + long back-month, same strike."""
    strike = _round_strike(underlying_price)
    short_premium = underlying_price * 0.015
    long_premium = underlying_price * 0.025
    net_debit = long_premium - short_premium
    return OptionStructure(
        recipe_name="calendar_vol_term",
        underlying=underlying,
        legs=[
            OptionLeg(
                side="short", option_type="call", strike=strike,
                dte_target=dte_target_short, qty=1, action="sell_to_open",
                description=f"Short ATM call ${strike} ({dte_target_short}d)",
            ),
            OptionLeg(
                side="long", option_type="call", strike=strike,
                dte_target=dte_target_long, qty=1, action="buy_to_open",
                description=f"Long ATM call ${strike} ({dte_target_long}d)",
            ),
        ],
        direction="neutral",
        max_risk_per_share=net_debit,
        max_reward_per_share=net_debit * 2,
        target_dte_min=21, target_dte_max=90,
        vol_regime_target="any",
        notes="Calendar spread — vol term-structure play",
    )


def build_covered_call(*, underlying: str, underlying_price: float,
                        owned_shares: int = 100,
                        dte_target: int = 30) -> OptionStructure:
    """Short OTM call on stock you already own. Snapshot positions can
    use this to harvest premium on long-held positions."""
    strike = _round_strike(underlying_price * 1.05)
    est_premium = max(0.50, underlying_price * 0.015)
    contracts = max(1, owned_shares // 100)
    return OptionStructure(
        recipe_name="covered_call_income",
        underlying=underlying,
        legs=[OptionLeg(
            side="short", option_type="call", strike=strike,
            dte_target=dte_target, qty=contracts, action="sell_to_open",
            delta_target=0.30,
            description=f"Short OTM call ${strike} on {owned_shares} owned shares",
        )],
        direction="short",
        max_risk_per_share=(strike - underlying_price) - est_premium,
        max_reward_per_share=est_premium,
        target_dte_min=21, target_dte_max=45,
        vol_regime_target="any",
        notes=(
            f"Covered call on {owned_shares} owned shares ({contracts} contracts); "
            f"collect ${est_premium * 100 * contracts:.0f} total premium"
        ),
    )


def build_csp(*, underlying: str, underlying_price: float,
               dte_target: int = 30) -> OptionStructure:
    """Cash-secured put on stock you'd buy. Wheel-strategy entry."""
    strike = _round_strike(underlying_price * 0.95)
    est_premium = max(0.50, underlying_price * 0.015)
    return OptionStructure(
        recipe_name="csp_income",
        underlying=underlying,
        legs=[OptionLeg(
            side="short", option_type="put", strike=strike,
            dte_target=dte_target, qty=1, action="sell_to_open",
            delta_target=-0.30,
            description=f"Short OTM put ${strike} (cash-secured)",
        )],
        direction="long",  # net long — happy to be assigned
        max_risk_per_share=strike - est_premium,  # full put if assigned
        max_reward_per_share=est_premium,
        target_dte_min=21, target_dte_max=45,
        vol_regime_target="any",
        notes=(
            f"CSP ${strike} — collect premium OR get assigned at "
            f"${strike} (effective cost ${strike - est_premium:.2f})"
        ),
    )


# ─────────────────────────────────────────────────────────────────────
# Dispatcher
# ─────────────────────────────────────────────────────────────────────

_BUILDERS = {
    "lottery_calls_short_dated": build_lottery_calls,
    "lottery_puts_short_dated": build_lottery_puts,
    "leaps_long_dated": build_leaps,
    "pmcc": build_pmcc,
    "vertical_bull_call": build_vertical_bull_call,
    "vertical_bear_put": build_vertical_bear_put,
    "iron_condor_low_vol": build_iron_condor,
    "straddle_earnings": build_straddle,
    "calendar_vol_term": build_calendar,
    "covered_call_income": build_covered_call,
    "csp_income": build_csp,
}


def build_structure(
    recipe_name: str,
    *,
    underlying: str,
    underlying_price: float,
    **extra_kwargs,
) -> Optional[OptionStructure]:
    """Build the multi-leg structure for a named recipe. Returns None if
    the recipe has no builder (e.g. equity-only recipes)."""
    builder = _BUILDERS.get(recipe_name)
    if builder is None:
        return None
    try:
        return builder(
            underlying=underlying,
            underlying_price=underlying_price,
            **extra_kwargs,
        )
    except Exception as e:
        log.warning(
            "[OPTIONS-RECIPES] builder failed for %s: %s", recipe_name, e,
        )
        return None


def list_builders() -> list[str]:
    """Names of all available recipe builders."""
    return sorted(_BUILDERS.keys())


def builder_count() -> int:
    return len(_BUILDERS)
