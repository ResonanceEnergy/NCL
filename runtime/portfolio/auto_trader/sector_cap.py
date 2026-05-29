"""
Auto-Trader per-sector exposure cap — Wave 14U-2/8

Maps every open position to its sector ETF (XLK/XLF/XLE/...), sums
exposure per sector, and gates new opens that would push any single
sector beyond NCL_SECTOR_CAP_PCT (default ±20%) of NAV.

Catches the "5 tech longs accidentally diversified" failure mode where
the operator owns AAPL/MSFT/NVDA/GOOG/TSM and thinks they're picking
stocks but really has a 5-position concentrated bet on XLK.

This is a CORRELATION cap, distinct from the beta cap (which catches
market exposure regardless of sector). A momentum bot can pass the
beta cap (beta=1.0 on average) but still be 80% in tech — that's the
case this cap blocks.

Uses the same TICKER_TO_SECTOR_ETF map as factor_attribution to keep
the two consistent. Unmapped tickers default to "SPY" bucket.

Tunables (env):
  NCL_SECTOR_CAP_PCT           default 20.0 (±20% NAV per sector)
  NCL_SECTOR_CAP_DISABLED      "1"/"0" default "0"
"""

from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.sector_cap")

MAX_SECTOR_PCT = float(os.getenv("NCL_SECTOR_CAP_PCT", "20.0"))
DISABLED = os.getenv("NCL_SECTOR_CAP_DISABLED", "0") == "1"


def _sector_for(ticker: str) -> str:
    """Map ticker to sector ETF using shared factor_attribution map."""
    try:
        from .factor_attribution import TICKER_TO_SECTOR_ETF
        return TICKER_TO_SECTOR_ETF.get((ticker or "").upper(), "SPY")
    except Exception:
        return "SPY"


def compute_sector_exposure(
    open_positions: list[dict],
    *,
    proposed_ticker: Optional[str] = None,
    proposed_notional: float = 0.0,
    proposed_direction: str = "long",
) -> dict:
    """Sum signed notional per sector ETF.

    Returns:
      {
        sectors: {"XLK": {"long": $X, "short": $Y, "net": $Z}, ...},
        proposed_sector: str | None,
        proposed_added: float (signed delta into proposed sector)
      }
    """
    sectors: dict[str, dict] = {}

    def _bump(sector: str, notional: float, direction: str) -> None:
        s = sectors.setdefault(sector, {"long": 0.0, "short": 0.0, "net": 0.0})
        if direction == "long":
            s["long"] += notional
            s["net"] += notional
        else:
            s["short"] += notional
            s["net"] -= notional

    for p in open_positions or []:
        ticker = str(p.get("ticker") or "")
        notional = float(p.get("notional") or 0)
        direction = str(p.get("direction") or "long").lower()
        sec = _sector_for(ticker)
        _bump(sec, notional, direction)

    proposed_sector = None
    proposed_added = 0.0
    if proposed_ticker and proposed_notional > 0:
        proposed_sector = _sector_for(proposed_ticker)
        proposed_added = (
            float(proposed_notional)
            if proposed_direction == "long"
            else -float(proposed_notional)
        )
        _bump(proposed_sector,
              float(proposed_notional), proposed_direction)

    # Round for display
    for s, vals in sectors.items():
        for k in vals:
            vals[k] = round(vals[k], 2)

    return {
        "sectors": sectors,
        "proposed_sector": proposed_sector,
        "proposed_added": round(proposed_added, 2),
    }


def check_proposed_open_against_sector_cap(
    *,
    proposed_ticker: str,
    proposed_notional: float,
    proposed_direction: str = "long",
    open_positions: Optional[list[dict]] = None,
    nav_cad: float = 36000.0,
) -> dict:
    """Gate: allow or block based on whether the proposed open would push
    any single sector beyond the configured cap."""
    if DISABLED:
        return {"allowed": True, "disabled": True}
    if not nav_cad or nav_cad <= 0:
        return {"allowed": True, "reason": "no_nav_available"}

    exposure = compute_sector_exposure(
        open_positions=open_positions or [],
        proposed_ticker=proposed_ticker,
        proposed_notional=proposed_notional,
        proposed_direction=proposed_direction,
    )
    proposed_sector = exposure["proposed_sector"]
    cap_dollars = nav_cad * (MAX_SECTOR_PCT / 100.0)
    breach_sectors = []
    for sec, vals in exposure["sectors"].items():
        net_abs = abs(vals["net"])
        net_pct = (net_abs / nav_cad * 100.0)
        if net_abs > cap_dollars:
            breach_sectors.append({
                "sector": sec,
                "net": vals["net"],
                "net_pct": round(net_pct, 2),
                "cap_pct": MAX_SECTOR_PCT,
                "breach_amount": round(net_abs - cap_dollars, 2),
            })

    if not breach_sectors:
        return {
            "allowed": True,
            "reason": (
                f"sector exposure within ±{MAX_SECTOR_PCT:.0f}% cap "
                f"(proposed adds to {proposed_sector or '?'})"
            ),
            "details": exposure,
        }
    return {
        "allowed": False,
        "reason": (
            f"sector cap breach: {', '.join(b['sector'] for b in breach_sectors)} "
            f"would exceed ±{MAX_SECTOR_PCT:.0f}% NAV"
        ),
        "breach_sectors": breach_sectors,
        "details": exposure,
    }


__all__ = [
    "check_proposed_open_against_sector_cap",
    "compute_sector_exposure",
    "MAX_SECTOR_PCT",
]
