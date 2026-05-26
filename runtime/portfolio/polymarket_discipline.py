"""
NCL Polymarket Discipline — Wave 14J Phase 6 (J6a + J6b + J6c)

Three rules layered on top of the existing planktonxd + weatherbetter
scorers in polymarket_strategies.py. Treat prediction-market exposure
with the same risk-engineering rigor as equities + options:

  J6a — Fractional Kelly + resolution-time discount
        Bet size = bankroll * fractional_kelly * (1 / sqrt(days_to_resolution))
        Default fractional_kelly = 0.25 (quarter-Kelly).
        Capital locked in a long-dated market has opportunity cost;
        time-discount accounts for it.

  J6b — resolution_cluster_id
        Multiple markets on the same underlying event (e.g. "Trump
        wins 2028" + "Trump wins GOP nomination" + state-by-state
        markets) belong to the same cluster. Aggregate exposure cap
        per cluster prevents concentration.

  J6c — Liquidity cap
        Position size <= 10% of resting opposite-side orderbook
        liquidity in thin markets. Sizing math reads orderbook depth.

Public surface:
  - kelly_size(prob_estimated, prob_market, bankroll_usd,
               days_to_resolution, fractional=0.25) -> dict
  - cluster_id_from_metadata(market_meta) -> str
  - liquidity_cap(orderbook_depth_usd, side='opposite',
                  cap_pct=10.0) -> float
"""

from __future__ import annotations

import math
import logging
import os
import re
from typing import Optional

log = logging.getLogger("ncl.portfolio.polymarket_discipline")

DEFAULT_FRACTIONAL = float(os.getenv("NCL_POLY_FRACTIONAL_KELLY", "0.25"))
DEFAULT_LIQ_CAP_PCT = float(os.getenv("NCL_POLY_LIQ_CAP_PCT", "10.0"))


def kelly_size(
    *,
    prob_estimated: float,
    prob_market: float,
    bankroll_usd: float,
    days_to_resolution: Optional[int] = None,
    fractional: float = DEFAULT_FRACTIONAL,
) -> dict:
    """Fractional Kelly bet sizing with resolution-time discount.

    Standard Kelly fraction:
      f* = (p * b - q) / b
      where:
        p = estimated probability of YES
        q = 1 - p
        b = decimal odds payout per unit = (1/prob_market - 1)

    We then scale by `fractional` (default 0.25) because:
      - Estimated probabilities are themselves uncertain
      - Full Kelly maximizes log growth but produces ~50% drawdowns
        in practice; fractional Kelly cuts variance dramatically

    Then time-discount by 1/sqrt(days_to_resolution) when known —
    a 12-month market has 1/sqrt(365) ~= 0.052x sizing vs a 30-day
    market's 1/sqrt(30) ~= 0.18x, because locked capital has
    opportunity cost.

    Returns:
      {
        "edge": float,            # p - prob_market (your supposed alpha)
        "kelly_fraction": float,  # raw f*; CAN be negative (means bet NO)
        "fractional_kelly": float,# kelly_fraction * fractional
        "time_discount": float,   # 1/sqrt(days)
        "size_usd": float,        # final $ bet
        "side": "YES"|"NO"|"PASS",
        "reasons": [str, ...],
      }
    """
    if not (0 < prob_estimated < 1) or not (0 < prob_market < 1):
        return _empty_result("invalid prob inputs (must be in (0,1))")
    if bankroll_usd <= 0:
        return _empty_result("bankroll <= 0")
    edge = prob_estimated - prob_market
    if abs(edge) < 0.01:  # < 1pp edge -> too thin
        return _empty_result(f"edge {edge:+.3f} too thin (< 1pp)")
    # Decimal odds payout per unit for the cheaper side
    if edge > 0:
        # We think YES is underpriced
        side = "YES"
        b = (1.0 / prob_market) - 1.0
        p = prob_estimated
        q = 1.0 - p
    else:
        # We think NO is underpriced
        side = "NO"
        b = (1.0 / (1.0 - prob_market)) - 1.0
        p = 1.0 - prob_estimated
        q = 1.0 - p
    kf = (p * b - q) / b if b > 0 else 0.0
    if kf <= 0:
        return _empty_result(f"kelly <= 0 ({kf:.4f}) despite edge {edge:+.3f}")
    fk = kf * fractional
    if days_to_resolution is not None and days_to_resolution > 0:
        time_discount = 1.0 / math.sqrt(days_to_resolution)
    else:
        time_discount = 1.0
    size_usd = bankroll_usd * fk * time_discount
    return {
        "edge": round(edge, 4),
        "kelly_fraction": round(kf, 4),
        "fractional_kelly": round(fk, 4),
        "time_discount": round(time_discount, 4),
        "size_usd": round(size_usd, 2),
        "side": side,
        "reasons": [
            f"{side} edge: estimated {prob_estimated:.2%} vs market {prob_market:.2%} "
            f"({edge:+.2%} pp).",
            f"Kelly fraction {kf:.4f}, fractional ({fractional}x) = {fk:.4f}.",
            (
                f"Time discount 1/sqrt({days_to_resolution}d) = {time_discount:.4f}."
                if days_to_resolution else "No time discount applied."
            ),
        ],
    }


def _empty_result(reason: str) -> dict:
    return {
        "edge": 0.0,
        "kelly_fraction": 0.0,
        "fractional_kelly": 0.0,
        "time_discount": 0.0,
        "size_usd": 0.0,
        "side": "PASS",
        "reasons": [reason],
    }


# ── J6b: cluster_id from market metadata ─────────────────────────

_CLUSTER_KEY_PATTERNS = [
    # election clusters — match year + office
    (r"\b(20[2-9]\d)\b.*\b(president|presidential|potus)\b", "election_potus_{0}"),
    (r"\b(president|presidential|potus)\b.*\b(20[2-9]\d)\b", "election_potus_{1}"),
    (r"\b(20[2-9]\d)\b.*\b(senate|house|congress)\b", "election_congress_{0}"),
    # central bank rate decision clusters
    (r"\b(fomc|fed funds|fed rate)\b.*\b(20[2-9]\d)\b", "fed_rates_{1}"),
    (r"\b(20[2-9]\d)\s*(q[1-4])\b", "calendar_{0}_{1}"),
    # nominal sports leagues + season year
    (r"\b(nfl|nba|mlb|nhl)\b.*\b(20[2-9]\d)\b", "sports_{0}_{1}"),
    # AI/tech milestones
    (r"\b(gpt-?5|gpt-?6|agi|asi)\b", "ai_milestone_{0}"),
    # crypto milestones — match coin + price level
    (r"\b(btc|bitcoin)\b.*\$?([0-9]{3}k|[0-9]00,000)\b", "btc_price_{1}"),
    (r"\b(eth|ethereum)\b.*\$?([0-9],?[0-9]{3,4})\b", "eth_price_{1}"),
]


def cluster_id_from_metadata(market_meta: dict) -> str:
    """Derive a cluster_id from market metadata.

    Looks at: title, question, slug, category, end_date_year.

    Returns a stable lowercased string. Falls back to "uncategorized:<slug>"
    if nothing matches.

    Example: 5 different 2028-US-president markets all map to
    'election_potus_2028' so the exposure cap fires correctly.
    """
    fields = []
    for k in ("title", "question", "slug", "category", "description"):
        v = market_meta.get(k)
        if v:
            fields.append(str(v).lower())
    text = " | ".join(fields)
    if not text:
        return f"uncategorized:{market_meta.get('id', 'unknown')}"
    for pattern, template in _CLUSTER_KEY_PATTERNS:
        m = re.search(pattern, text)
        if m:
            try:
                return template.format(*m.groups()).lower().replace(" ", "_")
            except (IndexError, KeyError):
                continue
    # No pattern match — use slug or first 32 chars of title as fallback
    slug = market_meta.get("slug") or text[:32]
    return f"uncategorized:{str(slug).lower()[:48]}"


# ── J6c: liquidity cap ───────────────────────────────────────────

def liquidity_cap(
    *,
    proposed_size_usd: float,
    orderbook_depth_usd: float,
    cap_pct: float = DEFAULT_LIQ_CAP_PCT,
) -> dict:
    """Cap proposed_size at cap_pct% of resting opposite-side liquidity.

    A position larger than that drags market price against the operator
    on entry AND on exit, doubling slippage. For Polymarket's AMM-style
    thin tails this is a real cost — the spread can widen 5x for a
    single oversized bid.

    Returns:
      {
        "approved_size_usd": float,    # min(proposed, cap)
        "throttled": bool,             # True if proposed > cap
        "cap_size_usd": float,         # cap_pct% of liquidity
        "reason": str
      }
    """
    cap_size = max(0.0, orderbook_depth_usd * cap_pct / 100.0)
    if proposed_size_usd <= cap_size:
        return {
            "approved_size_usd": round(proposed_size_usd, 2),
            "throttled": False,
            "cap_size_usd": round(cap_size, 2),
            "reason": (
                f"Within liquidity cap: ${proposed_size_usd:.2f} <= "
                f"{cap_pct:.1f}% of ${orderbook_depth_usd:.2f} = ${cap_size:.2f}."
            ),
        }
    return {
        "approved_size_usd": round(cap_size, 2),
        "throttled": True,
        "cap_size_usd": round(cap_size, 2),
        "reason": (
            f"Liquidity cap throttle: proposed ${proposed_size_usd:.2f} > "
            f"{cap_pct:.1f}% of ${orderbook_depth_usd:.2f} ({cap_size:.2f}). "
            f"Sized down to ${cap_size:.2f} to avoid >5x spread blowout on entry/exit."
        ),
    }
