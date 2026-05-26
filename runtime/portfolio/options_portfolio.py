"""
NCL Options Portfolio — Wave 14J Phase 3 (J2a + J2c + J2d)

Three pieces wrapped in one module because they share the same input
(held option positions) and the same Greek-derivation logic:

  J2a — Portfolio-level Greeks aggregation
    Net delta / gamma / theta / vega across the entire options book,
    grouped by underlying. Budgets:
      net delta:   +/- 0.30 / $NAV          (NCL_GREEKS_DELTA_PCT)
      net vega:    +/- $200 per IV-pt change (NCL_GREEKS_VEGA_BUDGET)
      net theta:   $100-300/day premium-sell target
      net gamma:   +/- 0.20 / $NAV
    Surfaces over/under budget flags for the operator.

  J2c — 21-DTE management trigger + pin-risk scanner
    21-DTE: any SHORT option (sold premium) with <= 21 DTE flagged for
    "close or roll" review. Gamma acceleration overwhelms theta benefit
    inside this window for short-premium structures.
    Pin-risk: any SHORT option within 0.5% of strike on the Friday it
    expires gets a force-review flag. Assignment ambiguity is highest
    here and retail traders most often discover unwanted Monday-morning
    long/short stock positions from this band.

  J2d — SPY -> SPX substitution prompt (executor-prompt rule)
    Lives in brief_pipeline.py prompt edits, not here. Reference:
    Section 1256 60/40 tax treatment cuts effective rate ~37% (ordinary)
    to ~27% (blended) on identical exposure.

Greeks data source: positions returned by PortfolioManager.get_positions()
that are asset_class == "option". If a broker adapter provides Greeks
(IBKR ib_insync has them on Position objects), we use those directly.
Otherwise we use a small black-scholes-ish approximation that's good
enough for portfolio-level aggregation:
  delta_proxy: 0.5 for ATM, scaled by moneyness toward 0/1
  gamma_proxy: highest at ATM, decays away
  theta_proxy: proportional to -extrinsic / DTE for short positions
  vega_proxy:  proportional to extrinsic * sqrt(DTE/365)

The proxy is intentionally simple — for portfolio risk we need
order-of-magnitude correct (is my book delta-neutral? is my theta
budget within target?), not pricing-engine accurate.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .options_strategies import parse_option_symbol, days_to_expiry

log = logging.getLogger("ncl.portfolio.options_portfolio")


# Budgets — % of NAV unless noted
DEFAULT_DELTA_BUDGET_PCT = float(os.getenv("NCL_GREEKS_DELTA_PCT", "30"))      # +/- 0.30/NAV
DEFAULT_GAMMA_BUDGET_PCT = float(os.getenv("NCL_GREEKS_GAMMA_PCT", "20"))      # +/- 0.20/NAV
DEFAULT_VEGA_BUDGET_DOLLARS = float(os.getenv("NCL_GREEKS_VEGA_BUDGET", "200"))  # $ per IV pt
DEFAULT_THETA_MIN_DAILY = float(os.getenv("NCL_GREEKS_THETA_MIN", "100"))
DEFAULT_THETA_MAX_DAILY = float(os.getenv("NCL_GREEKS_THETA_MAX", "300"))

DTE_WARN_THRESHOLD = int(os.getenv("NCL_DTE_WARN", "21"))
PIN_RISK_PCT = float(os.getenv("NCL_PIN_RISK_PCT", "0.5"))  # 0.5% of strike


# ── Greek proxy ──────────────────────────────────────────────────────

def _approx_greeks(
    *,
    spot: float,
    strike: float,
    dte: int,
    right: str,
    qty: float,
    extrinsic: Optional[float] = None,
    iv_pct: Optional[float] = None,
) -> dict[str, float]:
    """Black-Scholes-ish portfolio-level proxy.

    Inputs:
      spot     - current underlying price
      strike   - option strike
      dte      - days to expiry (clipped at 1)
      right    - 'C' or 'P'
      qty      - signed contracts; SHORT positions are negative
      extrinsic- extrinsic value per share (if known from broker); used
                 to scale theta + vega
      iv_pct   - implied vol (decimal, e.g. 0.30) if broker supplied;
                 used to scale vega

    Returns dict with delta/gamma/theta/vega per CONTRACT, then scaled by
    qty * 100 (standard equity-option multiplier) inside the caller.

    Numbers are intentionally coarse but the right SIGN and the right
    ORDER OF MAGNITUDE so portfolio-level aggregations make sense.
    """
    if spot <= 0 or strike <= 0:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    t = max(1, dte) / 365.0
    iv = iv_pct if iv_pct is not None and iv_pct > 0 else 0.30
    # Moneyness
    m = math.log(spot / strike) / (iv * math.sqrt(t))
    # Approximate cumulative normal via 1 / (1 + e^-1.7*x) — good enough for sign + magnitude
    N = lambda x: 1.0 / (1.0 + math.exp(-1.7 * x))
    Npdf = lambda x: math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)
    right_u = right.upper()
    if right_u == "C":
        delta = N(m)
        theta_dir = -1
    elif right_u == "P":
        delta = N(m) - 1
        theta_dir = -1
    else:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    gamma = Npdf(m) / (spot * iv * math.sqrt(t))
    # Theta (per day, per CONTRACT, scaled at caller). Sign reflects that
    # being long an option costs theta — we'll multiply by qty (signed)
    # at the caller so SHORT positions correctly show positive theta.
    if extrinsic is not None and extrinsic > 0:
        # Per-day theta proxy: extrinsic decays linearly per DTE
        theta_per_share = -(extrinsic / max(1, dte))
        theta_per_contract = theta_per_share * 100
    else:
        # Fall back to BS-ish: theta ~ -spot * IV * Npdf(m) / (2 * sqrt(T)) / 365
        theta_per_contract = (-spot * iv * Npdf(m) / (2 * math.sqrt(t))) / 365 * 100
    # Vega (per 1 vol-point move per CONTRACT)
    vega_per_contract = spot * Npdf(m) * math.sqrt(t) * 100 * 0.01  # 1 vol pt
    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta_per_contract": round(theta_per_contract, 4),
        "vega_per_contract": round(vega_per_contract, 4),
    }


def _scale_to_position(greeks_per_contract: dict, qty: float) -> dict:
    """Scale per-contract greeks by qty (signed) and 100-share multiplier."""
    return {
        "delta": round(greeks_per_contract.get("delta", 0.0) * qty * 100, 4),
        "gamma": round(greeks_per_contract.get("gamma", 0.0) * qty * 100, 6),
        "theta": round(greeks_per_contract.get("theta_per_contract", 0.0) * qty, 4),
        "vega": round(greeks_per_contract.get("vega_per_contract", 0.0) * qty, 4),
    }


# ── Public API ────────────────────────────────────────────────────────

def _is_option(pos: dict) -> bool:
    if not isinstance(pos, dict):
        return False
    ac = (pos.get("asset_class") or "").lower()
    if ac in ("option", "options", "opt"):
        return True
    parsed = parse_option_symbol(pos.get("symbol") or "")
    return parsed is not None


@dataclass
class PositionGreeks:
    symbol: str
    underlying: str
    right: str  # C / P
    strike: float
    expiry: str  # ISO date
    dte: int
    qty: float
    spot: Optional[float]
    is_short: bool
    delta: float
    gamma: float
    theta: float
    vega: float
    broker_greeks: bool = False  # True if broker supplied Greeks directly


def compute_position_greeks(positions: list[dict], spot_lookup: Optional[dict] = None) -> list[PositionGreeks]:
    """Walk option positions and return per-position Greeks.

    spot_lookup is an optional {underlying_ticker: spot_price} map; if
    not provided, we use the position's own current_price field as a
    proxy (which is wrong for the OPTION price but better than 0 for
    fully-stale positions; the right thing is to pass spot_lookup).
    """
    spot_lookup = spot_lookup or {}
    out: list[PositionGreeks] = []
    for p in positions:
        if not _is_option(p):
            continue
        parsed = parse_option_symbol(p.get("symbol") or "")
        if not parsed:
            continue
        qty = float(p.get("quantity") or 0)
        if qty == 0:
            continue
        underlying = parsed["underlying"]
        spot = spot_lookup.get(underlying)
        if spot is None:
            # Fall back: if the position holds underlying spot already, use it
            spot = float(p.get("underlying_price") or 0)
        if spot <= 0:
            # Last-resort: skip — Greek computation needs a spot
            continue
        right = parsed["right"]
        strike = float(parsed["strike"])
        dte_val = days_to_expiry(parsed["expiry"])
        if dte_val is None:
            dte_val = 0
        # Prefer broker-supplied Greeks if present
        broker = bool(p.get("greeks"))
        if broker:
            g = p["greeks"]
            scaled = {
                "delta": float(g.get("delta", 0.0)) * qty * 100,
                "gamma": float(g.get("gamma", 0.0)) * qty * 100,
                "theta": float(g.get("theta", 0.0)) * qty,
                "vega": float(g.get("vega", 0.0)) * qty,
            }
        else:
            per = _approx_greeks(
                spot=spot,
                strike=strike,
                dte=dte_val,
                right=right,
                qty=qty,
                extrinsic=p.get("extrinsic"),
                iv_pct=p.get("implied_vol"),
            )
            scaled = _scale_to_position(per, qty)
        out.append(
            PositionGreeks(
                symbol=p.get("symbol", ""),
                underlying=underlying,
                right=right,
                strike=strike,
                expiry=str(parsed["expiry"]),
                dte=dte_val,
                qty=qty,
                spot=spot,
                is_short=qty < 0,
                delta=round(scaled["delta"], 4),
                gamma=round(scaled["gamma"], 6),
                theta=round(scaled["theta"], 4),
                vega=round(scaled["vega"], 4),
                broker_greeks=broker,
            )
        )
    return out


def aggregate_greeks(per_position: list[PositionGreeks], nav_cad: float = 0.0) -> dict:
    """Sum per-position greeks; tag against budgets."""
    if not per_position:
        return {
            "net": {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0},
            "by_underlying": {},
            "budgets": _budget_envelope(nav_cad),
            "flags": [],
            "position_count": 0,
        }
    net = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    by_u: dict[str, dict[str, float]] = {}
    for g in per_position:
        net["delta"] += g.delta
        net["gamma"] += g.gamma
        net["theta"] += g.theta
        net["vega"] += g.vega
        u = g.underlying
        b = by_u.setdefault(u, {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0})
        b["delta"] += g.delta
        b["gamma"] += g.gamma
        b["theta"] += g.theta
        b["vega"] += g.vega
    # Round
    for k in net:
        net[k] = round(net[k], 4)
    for u in by_u:
        for k in by_u[u]:
            by_u[u][k] = round(by_u[u][k], 4)
    budgets = _budget_envelope(nav_cad)
    flags = _budget_flags(net, budgets)
    return {
        "net": net,
        "by_underlying": by_u,
        "budgets": budgets,
        "flags": flags,
        "position_count": len(per_position),
    }


def _budget_envelope(nav_cad: float) -> dict:
    nav = max(nav_cad, 1000.0)  # floor; otherwise % gives microscopic envelopes
    return {
        "delta_max_abs": round(nav * DEFAULT_DELTA_BUDGET_PCT / 100.0, 2),
        "gamma_max_abs": round(nav * DEFAULT_GAMMA_BUDGET_PCT / 100.0, 4),
        "vega_max_abs": DEFAULT_VEGA_BUDGET_DOLLARS,
        "theta_min_daily": DEFAULT_THETA_MIN_DAILY,
        "theta_max_daily": DEFAULT_THETA_MAX_DAILY,
    }


def _budget_flags(net: dict, budgets: dict) -> list[str]:
    flags = []
    if abs(net["delta"]) > budgets["delta_max_abs"]:
        flags.append(
            f"NET DELTA breach: {net['delta']:+.2f} vs +/- {budgets['delta_max_abs']:.2f} budget"
        )
    if abs(net["gamma"]) > budgets["gamma_max_abs"]:
        flags.append(
            f"NET GAMMA breach: {net['gamma']:+.4f} vs +/- {budgets['gamma_max_abs']:.4f} budget"
        )
    if abs(net["vega"]) > budgets["vega_max_abs"]:
        flags.append(
            f"NET VEGA breach: ${net['vega']:+.2f} vs +/- ${budgets['vega_max_abs']:.0f} budget"
        )
    if 0 < net["theta"] < budgets["theta_min_daily"]:
        flags.append(
            f"theta below floor: ${net['theta']:+.2f}/day vs ${budgets['theta_min_daily']:.0f} min target"
        )
    if net["theta"] > budgets["theta_max_daily"]:
        flags.append(
            f"theta above ceiling: ${net['theta']:+.2f}/day vs ${budgets['theta_max_daily']:.0f} max"
        )
    return flags


# ── 21-DTE + pin-risk scanners ───────────────────────────────────────

def dte_watchlist(positions: list[dict], threshold: int = DTE_WARN_THRESHOLD) -> list[dict]:
    """SHORT options within `threshold` days of expiry. Gamma acceleration
    overwhelms theta inside this window for short-premium structures —
    operator should consider close-or-roll.

    Returns sorted ascending by DTE.
    """
    out: list[dict] = []
    for p in positions:
        if not _is_option(p):
            continue
        qty = float(p.get("quantity") or 0)
        if qty >= 0:
            continue  # only short positions
        parsed = parse_option_symbol(p.get("symbol") or "")
        if not parsed:
            continue
        dte_val = days_to_expiry(parsed["expiry"])
        if dte_val is None or dte_val > threshold:
            continue
        out.append({
            "symbol": p.get("symbol"),
            "underlying": parsed["underlying"],
            "right": parsed["right"],
            "strike": float(parsed["strike"]),
            "expiry": parsed["expiry"].isoformat() if hasattr(parsed["expiry"], "isoformat") else str(parsed["expiry"]),
            "dte": dte_val,
            "qty": qty,
            "recommendation": (
                "close — gamma cliff" if dte_val <= 7
                else "close or roll — inside 21-DTE management window"
            ),
        })
    return sorted(out, key=lambda r: r["dte"])


def _coerce_expiry_date(expiry: Any):
    """parse_option_symbol returns expiry as a *string* in some code
    paths and as a datetime.date in others. Normalize to a date so
    weekday() / subtraction always work."""
    if hasattr(expiry, "weekday") and not isinstance(expiry, str):
        return expiry
    try:
        return datetime.fromisoformat(str(expiry)).date()
    except (TypeError, ValueError):
        return None


def pin_risk_watchlist(
    positions: list[dict],
    spot_lookup: dict,
    pct: float = PIN_RISK_PCT,
    today: Optional[datetime] = None,
) -> list[dict]:
    """SHORT options expiring on a Friday and within `pct` % of strike.

    Pin risk = the price closes so close to the strike that assignment
    decisions become ambiguous; retail most often discovers an unwanted
    Monday morning position from this band.

    spot_lookup is {underlying: spot_price} — REQUIRED here because
    pin-risk is purely a price-vs-strike comparison.
    """
    today = today or datetime.now(timezone.utc)
    out: list[dict] = []
    for p in positions:
        if not _is_option(p):
            continue
        qty = float(p.get("quantity") or 0)
        if qty >= 0:
            continue
        parsed = parse_option_symbol(p.get("symbol") or "")
        if not parsed:
            continue
        expiry = _coerce_expiry_date(parsed["expiry"])
        if expiry is None:
            continue
        if expiry.weekday() != 4:  # 4 = Friday
            continue
        # Pin risk only matters within 7d of expiry
        days_until = (expiry - today.date()).days
        if not (0 <= days_until <= 7):
            continue
        spot = spot_lookup.get(parsed["underlying"])
        if spot is None or spot <= 0:
            continue
        strike = float(parsed["strike"])
        gap_pct = abs(spot - strike) / strike * 100.0
        if gap_pct > pct:
            continue
        out.append({
            "symbol": p.get("symbol"),
            "underlying": parsed["underlying"],
            "right": parsed["right"],
            "strike": strike,
            "expiry": expiry.isoformat(),
            "spot": round(spot, 4),
            "gap_pct": round(gap_pct, 3),
            "days_until_expiry": days_until,
            "qty": qty,
            "recommendation": (
                f"force review: spot ${spot:.2f} within {gap_pct:.2f}% of strike "
                f"${strike:.2f} on expiry Friday — assignment ambiguity high"
            ),
        })
    return sorted(out, key=lambda r: (r["days_until_expiry"], r["gap_pct"]))
