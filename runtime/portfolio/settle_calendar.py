"""
NCL Trade-Date / Settle-Date Calendar — Wave 14J J8d

Two parallel views over the position cache:
  trade-date  : what you traded today (immediate; brokers show this)
  settle-date : when the cash actually arrives in available BP

Settlement timing (US):
  equities + ETFs   T+1   (since 2024 — was T+2)
  options           T+1
  futures           T+0
  US Treasuries     T+1
  Mutual funds      T+1 (most)
  Crypto custodial  T+0 (NDAX et al)
  Crypto on-chain   T+0 (block-time)
  Polymarket        T+resolution (no settle until market resolves)

Skip-day rules: settle never lands on weekend or US market holiday;
slides to next business day.

Public surface:
  - settle_date(asset_class, trade_date_str) -> str (ISO date)
  - cash_view(trades) -> {trade_date_total, settled_today,
                          unsettled, by_class}
  - bp_view(summary, trades) -> {trade_date_bp, settled_bp,
                                  unsettled_inflow, unsettled_outflow}
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

# US market holidays 2026-2027 (NYSE). Add years as needed.
US_MARKET_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
    "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26",
    "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06",
    "2027-11-25", "2027-12-24",
}

SETTLE_DAYS = {
    "equity": 1,
    "stock": 1,
    "etf": 1,
    "option": 1,
    "future": 0,
    "treasury": 1,
    "mutual_fund": 1,
    "crypto": 0,         # custodial (NDAX, Coinbase)
    "onchain": 0,        # block-time
    "polymarket": None,  # at resolution; not date-driven
}


def _is_business_day(d: datetime.date) -> bool:
    if d.weekday() >= 5:
        return False
    if d.isoformat() in US_MARKET_HOLIDAYS:
        return False
    return True


def _next_business_day(d: datetime.date) -> datetime.date:
    nxt = d + timedelta(days=1)
    while not _is_business_day(nxt):
        nxt += timedelta(days=1)
    return nxt


def settle_date(
    asset_class: str,
    trade_date_str: str,
    custom_days: Optional[int] = None,
) -> Optional[str]:
    """ISO settle date or None for polymarket (no calendar-driven settle)."""
    ac = (asset_class or "").lower().strip()
    days = custom_days if custom_days is not None else SETTLE_DAYS.get(ac)
    if days is None:
        return None
    try:
        td = datetime.fromisoformat(trade_date_str).date()
    except ValueError:
        return None
    # T+0 = same day if business; else next business day
    sd = td
    biz_added = 0
    while biz_added < days:
        sd = _next_business_day(sd)
        biz_added += 1
    # Even T+0 should slide if it landed on a non-biz day (rare for
    # the asset classes here, but safe).
    while not _is_business_day(sd):
        sd = _next_business_day(sd)
    return sd.isoformat()


def cash_view(trades: list[dict], as_of: Optional[str] = None) -> dict:
    """Given a list of trades [{asset_class, trade_date, cash_delta, ...}],
    return a settled vs unsettled cash view as of `as_of`.

    Each trade contributes to:
      settled_today : cash_delta whose settle_date <= as_of
      unsettled     : cash_delta whose settle_date > as_of

    The trade-date total is the simple sum across all trades (gross flow).
    """
    as_of_d = (
        datetime.fromisoformat(as_of).date()
        if as_of else datetime.now(timezone.utc).date()
    )
    trade_total = 0.0
    settled = 0.0
    unsettled_inflow = 0.0
    unsettled_outflow = 0.0
    by_class = {}
    for t in trades:
        delta = float(t.get("cash_delta", 0.0))
        trade_total += delta
        ac = (t.get("asset_class") or "").lower()
        sd_iso = settle_date(ac, str(t.get("trade_date", "")))
        if sd_iso is None:
            # Polymarket / unknown — treat as unsettled until further notice
            if delta >= 0:
                unsettled_inflow += delta
            else:
                unsettled_outflow += delta
            by_class.setdefault(ac, {"settled": 0.0, "unsettled": 0.0})
            by_class[ac]["unsettled"] += delta
            continue
        sd_d = datetime.fromisoformat(sd_iso).date()
        bucket = by_class.setdefault(ac, {"settled": 0.0, "unsettled": 0.0})
        if sd_d <= as_of_d:
            settled += delta
            bucket["settled"] += delta
        else:
            if delta >= 0:
                unsettled_inflow += delta
            else:
                unsettled_outflow += delta
            bucket["unsettled"] += delta
    # Round
    for ac in by_class:
        for k in by_class[ac]:
            by_class[ac][k] = round(by_class[ac][k], 2)
    return {
        "as_of": as_of_d.isoformat(),
        "trade_date_total": round(trade_total, 2),
        "settled_today": round(settled, 2),
        "unsettled_inflow": round(unsettled_inflow, 2),
        "unsettled_outflow": round(unsettled_outflow, 2),
        "unsettled_net": round(unsettled_inflow + unsettled_outflow, 2),
        "by_class": by_class,
    }


def bp_view(
    summary: dict,
    trades: list[dict],
    as_of: Optional[str] = None,
) -> dict:
    """Compute trade-date BP (broker-reported, includes unsettled) vs
    settled-only BP (only includes cash that has actually landed).

    summary = output of PortfolioManager.get_summary(); the keys we
    need are `total_cash` (or `cash`) and `buying_power`.
    """
    cv = cash_view(trades, as_of=as_of)
    cash = float(summary.get("total_cash") or summary.get("cash") or 0.0)
    bp = float(summary.get("buying_power") or 0.0)
    # The broker BP already reflects unsettled cash. Settled-only BP
    # subtracts unsettled inflow (you can't deploy it yet) but does NOT
    # add unsettled outflow back (you DID spend it).
    settled_bp = bp - cv["unsettled_inflow"]
    return {
        "as_of": cv["as_of"],
        "trade_date_bp": round(bp, 2),
        "settled_bp": round(max(settled_bp, 0.0), 2),
        "total_cash_reported": round(cash, 2),
        "unsettled_inflow": cv["unsettled_inflow"],
        "unsettled_outflow": cv["unsettled_outflow"],
        "cash_view": cv,
    }
