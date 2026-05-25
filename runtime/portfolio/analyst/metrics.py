"""
Deterministic portfolio metrics — pure Python, no LLM.

Every number in the nightly report has its source-of-truth here.
Functions are stateless and side-effect-free; they take a list of
position dicts (whatever shape PortfolioManager exposes) and return
typed metric objects.

Key invariant: the LLM never computes these. It only narrates them.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

from .schema import Concentration, CorrelationBreak, RiskMetrics, SectorWeight


# Defensive helpers — positions come from multiple brokers and sometimes
# have missing fields. Coerce to floats or skip cleanly.


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _market_value(p: dict) -> float:
    """Pick the most reliable market-value field from a position dict."""
    for key in ("market_value_usd", "market_value", "value_usd", "value"):
        v = p.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    # Fallback: qty × last_price
    qty = _f(p.get("quantity") or p.get("qty"))
    px = _f(p.get("last_price") or p.get("current_price") or p.get("price"))
    return qty * px


def _ticker(p: dict) -> str:
    return (
        p.get("symbol")
        or p.get("ticker")
        or p.get("underlying")
        or "?"
    )


def _sector(p: dict) -> str:
    return p.get("sector") or p.get("industry_sector") or "Unknown"


# ── Concentration ───────────────────────────────────────────────────────


def compute_concentration(positions: list[dict]) -> Concentration:
    """Herfindahl-Hirschman index + top-1, top-5, sector weights.

    HHI bands (rule of thumb):
      < 0.10  diversified
      0.10-0.18  moderate concentration
      0.18-0.25  concentrated — watch
      > 0.25  dangerous — defensive trims warranted

    Weights are computed against the sum of market values of LONG
    positions only. Short positions are reported in sector weights but
    don't count toward HHI (they don't compound single-name blow-up
    risk the same way).
    """
    if not positions:
        return Concentration()

    long_values = []
    sector_totals: dict[str, float] = {}
    total = 0.0

    for p in positions:
        mv = _market_value(p)
        if mv <= 0:
            # Short or zero — track in sector totals via abs value but
            # skip for HHI weight.
            sector_totals[_sector(p)] = sector_totals.get(_sector(p), 0.0) + abs(mv)
            continue
        long_values.append((_ticker(p), mv))
        sector_totals[_sector(p)] = sector_totals.get(_sector(p), 0.0) + mv
        total += mv

    if total <= 0:
        return Concentration()

    weights = sorted(((t, v / total) for t, v in long_values), key=lambda kv: -kv[1])
    hhi = sum(w * w for _, w in weights)
    top1 = weights[0][1] if weights else 0.0
    top5 = sum(w for _, w in weights[:5])

    sector_total = sum(sector_totals.values()) or 1.0
    sectors = sorted(
        (SectorWeight(sector=s, weight=v / sector_total) for s, v in sector_totals.items()),
        key=lambda sw: -sw.weight,
    )

    return Concentration(
        hhi=hhi,
        top1_weight=top1,
        top5_weight=top5,
        by_sector=sectors,
    )


# ── Risk metrics ────────────────────────────────────────────────────────


def compute_risk(
    positions: list[dict],
    daily_returns: list[float] | None = None,
    nav_usd: float = 0.0,
    beta: float | None = None,
    drawdown_30d_pct: float | None = None,
    drawdown_ytd_pct: float | None = None,
    cash_pct: float | None = None,
) -> RiskMetrics:
    """Compose a RiskMetrics object from whatever inputs are available.

    daily_returns: list of portfolio daily-return percents (e.g. -0.012)
        for VaR/CVaR via historical simulation. If empty or short
        (<60 entries), VaR/CVaR are left None.
    nav_usd: needed to convert percent-returns into USD VaR figures.
    beta: pre-computed beta to SPY (caller supplies; we don't fetch SPY).
    drawdown_*: percent values (e.g. -8.5).
    cash_pct: 0.0-1.0 cash-as-fraction-of-NAV.

    leverage = gross_exposure / net_liq when both available.
    """
    m = RiskMetrics(beta_to_spy=beta, max_drawdown_30d_pct=drawdown_30d_pct,
                    max_drawdown_ytd_pct=drawdown_ytd_pct, cash_pct=cash_pct)

    # VaR / CVaR via historical simulation at 95%
    if daily_returns and len(daily_returns) >= 60 and nav_usd > 0:
        sorted_returns = sorted(daily_returns)
        # 5th percentile loss
        idx = max(0, int(len(sorted_returns) * 0.05) - 1)
        var_pct = sorted_returns[idx]  # likely negative
        # CVaR = average of returns at or below VaR
        tail = sorted_returns[: idx + 1] or [var_pct]
        cvar_pct = sum(tail) / len(tail)
        m.var_95_1d_usd = round(abs(var_pct) * nav_usd, 2)
        m.cvar_95_1d_usd = round(abs(cvar_pct) * nav_usd, 2)

    # Leverage: gross / net
    gross = sum(abs(_market_value(p)) for p in positions)
    if nav_usd > 0:
        m.leverage = round(gross / nav_usd, 2)

    return m


# ── Correlation breaks ──────────────────────────────────────────────────


def detect_correlation_breaks(
    return_series: dict[str, list[float]],
    delta_threshold: float = 0.2,
) -> list[CorrelationBreak]:
    """Flag pairs whose 30d correlation has drifted >threshold from 60d.

    return_series: {ticker -> list of daily returns, ordered oldest→newest}
    Each list must have at least 60 entries; we take last 30 for short
    and full 60 for long.

    A break in either direction matters:
      - corr_60d high + corr_30d low: diversification opened up (good)
      - corr_60d low + corr_30d high: things now move together (risk)
    The LLM consumer interprets the sign.
    """
    breaks: list[CorrelationBreak] = []
    tickers = [t for t, s in return_series.items() if len(s) >= 60]
    for i, a in enumerate(tickers):
        for b in tickers[i + 1:]:
            r60_a = return_series[a][-60:]
            r60_b = return_series[b][-60:]
            r30_a = return_series[a][-30:]
            r30_b = return_series[b][-30:]
            c60 = _pearson(r60_a, r60_b)
            c30 = _pearson(r30_a, r30_b)
            if c60 is None or c30 is None:
                continue
            if abs(c30 - c60) >= delta_threshold:
                breaks.append(
                    CorrelationBreak(
                        a=a,
                        b=b,
                        corr_60d=round(c60, 3),
                        corr_30d=round(c30, 3),
                        note=(
                            "diversification opened up" if c30 < c60
                            else "co-movement increased"
                        ),
                    )
                )
    # Surface the most significant breaks first
    breaks.sort(key=lambda cb: -abs(cb.corr_30d - cb.corr_60d))
    return breaks[:10]


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


# ── Options Greeks aggregation ──────────────────────────────────────────


def aggregate_options_greeks(option_positions: Iterable[dict]) -> dict[str, float]:
    """Sum delta, gamma, vega, theta across all option positions.

    Each position dict must expose 'delta', 'gamma', 'vega', 'theta',
    'quantity'. Long calls/puts contribute positive sign; short positions
    contribute negative (assumed by `quantity` sign convention).
    """
    totals = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
    for p in option_positions:
        qty = _f(p.get("quantity"))
        for k in totals:
            totals[k] += _f(p.get(k)) * qty
    return {k: round(v, 3) for k, v in totals.items()}
