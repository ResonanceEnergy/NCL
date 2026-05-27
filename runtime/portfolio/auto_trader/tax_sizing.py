"""
Auto-Trader tax-aware sizing — Wave 14L M1

Wires the existing runtime/portfolio/tax_compliance helpers into the
auto-trader sizing chain:

  1. WASH SALE — before opening, check WashSaleLedger.check_open(symbol)
     for realized losses on this ticker in the 30-day window. If a
     wash-sale conflict exists, OPTIONALLY block (NCL_AT_WASH_BLOCK=1
     default) — the IRS disallows the loss, but operator may still
     want the position. Emit informational MemUnit either way.

  2. EARNINGS PROXIMITY SIZING — call earnings_size_modifier with
     days-to-earnings looked up via calendar_gate's earnings fetcher.
     Apply the appropriate multiplier (long_premium / short_premium /
     stock) based on the trade idea's asset_type + direction:
       within 2d: long-premium HALVED, stock cut 25%
       within 7d: long-premium 0.75, short-premium preferred
       beyond 7d: no modifier

  3. RECORDING — when outcome_attributor sees a losing close, it now
     records the realized loss into WashSaleLedger so the NEXT open
     on that ticker checks correctly.

Tunables (env):
  NCL_AT_TAX_SIZING_ENABLED=1
  NCL_AT_WASH_BLOCK=1                  (1 = block; 0 = warn-only)
  NCL_AT_TAX_RECORD_LOSSES=1           (auto-record realized losses)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.tax_sizing")

ENABLED = os.getenv("NCL_AT_TAX_SIZING_ENABLED", "1") not in ("0", "false", "False")
WASH_BLOCK = os.getenv("NCL_AT_WASH_BLOCK", "1") not in ("0", "false", "False")
RECORD_LOSSES = os.getenv("NCL_AT_TAX_RECORD_LOSSES", "1") not in ("0", "false", "False")


def _classify_asset(idea: dict) -> tuple[str, str]:
    """Returns (sizing_bucket, direction) where sizing_bucket is one of
    long_premium / short_premium / stock."""
    asset_type = (idea.get("type") or idea.get("asset_type") or "stock").lower()
    direction = (idea.get("direction") or "long").lower()
    if asset_type == "options":
        # Long premium = buyer of an option (long call/put). Short premium =
        # seller of an option (covered call, CSP, condor, etc.)
        if direction == "long":
            return "long_premium", direction
        return "short_premium", direction
    return "stock", direction


async def apply_tax_sizing(
    *,
    idea: dict,
    proposed_qty: float,
    proposed_R_dollars: float,
    brain=None,
) -> dict:
    """Returns:
      {
        approved: bool,
        block_reason: str,            # only set if approved=False
        size_multiplier: float,       # 1.0 = no change
        adjusted_qty: float,
        adjusted_R_dollars: float,
        wash_sale_warnings: list,
        earnings_modifier_notes: str,
      }
    Never raises. Disabled flag → pass-through returns approved with mult=1.0.
    """
    out = {
        "approved": True,
        "block_reason": "",
        "size_multiplier": 1.0,
        "adjusted_qty": proposed_qty,
        "adjusted_R_dollars": proposed_R_dollars,
        "wash_sale_warnings": [],
        "earnings_modifier_notes": "",
    }
    if not ENABLED:
        out["earnings_modifier_notes"] = "tax sizing disabled (NCL_AT_TAX_SIZING_ENABLED=0)"
        return out

    symbol = (idea.get("ticker") or "").upper()
    if not symbol:
        return out

    # 1. Wash-sale check (cross-account, 30-day window)
    try:
        from ..tax_compliance import get_wash_sale_ledger
        ledger = await get_wash_sale_ledger()
        warnings = await ledger.check_open(symbol=symbol)
        if warnings:
            out["wash_sale_warnings"] = warnings
            total_disallowed = sum(w.get("loss_amount", 0) for w in warnings)
            if WASH_BLOCK:
                out["approved"] = False
                out["block_reason"] = (
                    f"WASH SALE: {len(warnings)} realized loss(es) on {symbol} "
                    f"in 30d window (total ${total_disallowed:.2f} would be "
                    f"IRS-disallowed). Set NCL_AT_WASH_BLOCK=0 to allow."
                )
                # Emit informational MemUnit
                if brain:
                    try:
                        mem = getattr(brain, "memory_store", None)
                        if mem and hasattr(mem, "create_unit"):
                            await mem.create_unit(
                                content=(
                                    f"TAX SIZING blocked {symbol} open due to wash sale: "
                                    f"{len(warnings)} realized loss(es) in 30d window."
                                ),
                                source="portfolio:tax:wash_sale_block",
                                importance=70.0,
                                tags=["portfolio", "tax", "wash_sale",
                                      f"ticker:{symbol}"],
                                memory_type="episodic",
                                metadata={"warnings": warnings,
                                          "total_disallowed": total_disallowed},
                            )
                    except Exception as e:
                        log.debug("[TAX] wash MemUnit skipped: %s", e)
                return out
            else:
                log.warning(
                    "[TAX] wash sale warning on %s (NCL_AT_WASH_BLOCK=0, "
                    "allowing): %d losses, $%.2f total disallowed",
                    symbol, len(warnings), total_disallowed,
                )
    except Exception as e:
        log.debug("[TAX] wash sale check failed for %s (continuing): %s", symbol, e)

    # 2. Earnings proximity sizing
    try:
        from ..tax_compliance import earnings_size_modifier
        from .calendar_gate import _fetch_earnings_dates, _parse_iso_date

        dates = await _fetch_earnings_dates(symbol) or []
        days_to_earnings = None
        today = datetime.now(timezone.utc).date()
        for ds in dates:
            d = _parse_iso_date(ds)
            if d is None:
                continue
            delta = (d - today).days
            if delta >= 0:
                if days_to_earnings is None or delta < days_to_earnings:
                    days_to_earnings = delta

        modifier = earnings_size_modifier(days_to_earnings)
        bucket, direction = _classify_asset(idea)
        if bucket == "long_premium":
            mult = modifier.long_premium_mult
        elif bucket == "short_premium":
            mult = modifier.short_premium_mult
        else:
            mult = modifier.stock_mult
        if mult != 1.0:
            out["size_multiplier"] = mult
            out["adjusted_qty"] = round(proposed_qty * mult, 4)
            out["adjusted_R_dollars"] = round(proposed_R_dollars * mult, 2)
            out["earnings_modifier_notes"] = (
                f"Earnings in {days_to_earnings}d ({bucket} {direction}): "
                f"mult={mult:.2f} → qty {proposed_qty:.2f}→{out['adjusted_qty']:.2f}; "
                f"R ${proposed_R_dollars:.0f}→${out['adjusted_R_dollars']:.0f}. "
                f"{modifier.notes}"
            )
            log.info("[TAX] %s sized down for earnings: %s", symbol, out["earnings_modifier_notes"])
        else:
            out["earnings_modifier_notes"] = (
                f"No earnings sizing modifier "
                f"(days_to_earnings={days_to_earnings}, bucket={bucket})"
            )
    except Exception as e:
        log.debug("[TAX] earnings sizing skipped: %s", e)

    return out


async def record_realized_loss(
    *,
    symbol: str,
    broker: str,
    account_id: str,
    loss_amount: float,
    notes: str = "",
) -> None:
    """Called by outcome_attributor on losing closes. loss_amount > 0
    (positive USD). Pushes into WashSaleLedger so next open checks
    correctly."""
    if not ENABLED or not RECORD_LOSSES:
        return
    if loss_amount <= 0:
        return  # only record actual losses
    try:
        from ..tax_compliance import get_wash_sale_ledger
        ledger = await get_wash_sale_ledger()
        await ledger.record_loss(
            symbol=symbol,
            broker=broker or "paper",
            account_id=account_id or "auto_trader",
            loss_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            loss_amount=loss_amount,
            notes=notes,
        )
        log.info(
            "[TAX] recorded realized loss: %s $%.2f → wash sale ledger",
            symbol, loss_amount,
        )
    except Exception as e:
        log.warning("[TAX] record_realized_loss failed: %s", e)
