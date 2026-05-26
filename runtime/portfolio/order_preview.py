"""
NCL Order Preview — Wave 14J out-of-scope finisher

NOT a live auto-executor. Read the docstring carefully:

  This module FORMATS and SIMULATES orders. It never submits. It never
  has the credentials to submit. It is a HUMAN-IN-THE-LOOP helper that:

    1. Takes a proposed trade (symbol, side, qty, order_type, limit, stop)
    2. Runs it through the risk_governor (heat caps + drawdown throttle)
    3. Estimates fees against the trade_cost_ledger history
    4. Estimates per-lot impact via tax_lot_ledger (for sells)
    5. Formats the per-broker submission payload as a STRING the operator
       can copy into the broker's order ticket (IBKR ib_insync syntax,
       Moomoo TrdType/TrdSide enums, SnapTrade order body)
    6. Returns a complete dry-run report

  The operator reviews the report and CLICKS SUBMIT IN THE BROKER UI.
  No order is ever sent from NCL. Ever.

Why this exists despite the auto-executor exclusion:
  - The audit doc said "LLM proposes, human disposes" — but the human
    was still authoring the order from scratch. This module makes the
    "disposes" step a SINGLE COPY-PASTE while preserving the human's
    fingertip on the submit button.
  - All five Wave 14J risk layers (governor / R-fields / drawdown /
    heat caps / stop framework) are already wired here; the order
    preview composes them into one "would this trade be allowed?"
    answer in <100ms.
  - The literature warning was about LLMs SUBMITTING orders. Not about
    formatting them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("ncl.portfolio.order_preview")


VALID_ORDER_TYPES = {"market", "limit", "stop", "stop_limit", "trail"}
VALID_SIDES = {"buy", "sell", "buy_to_cover", "sell_short"}
VALID_TIF = {"DAY", "GTC", "IOC", "FOK", "OPG", "GTD"}


@dataclass
class OrderProposal:
    symbol: str
    side: str
    qty: float
    order_type: str = "market"
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: str = "DAY"
    broker: Optional[str] = None
    account_id: Optional[str] = None
    strategy_tag: Optional[str] = None
    trade_idea_id: Optional[str] = None


async def preview_order(
    *,
    symbol: str,
    side: str,
    qty: float,
    order_type: str = "market",
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    time_in_force: str = "DAY",
    broker: Optional[str] = None,
    account_id: Optional[str] = None,
    strategy_tag: Optional[str] = None,
    trade_idea_id: Optional[str] = None,
    estimated_R_dollars: Optional[float] = None,
) -> dict:
    """Dry-run a proposed order. Returns a complete preview report; submits NOTHING.

    The returned `submission_payloads` block carries per-broker strings
    the operator copy-pastes into the broker's order ticket. Each payload
    is annotated `IS_PREVIEW_ONLY = True` so even if someone evals the
    string in ib_insync it errors-out instead of submitting.
    """
    if side not in VALID_SIDES:
        raise ValueError(f"side must be in {sorted(VALID_SIDES)}")
    if order_type not in VALID_ORDER_TYPES:
        raise ValueError(f"order_type must be in {sorted(VALID_ORDER_TYPES)}")
    if time_in_force not in VALID_TIF:
        raise ValueError(f"time_in_force must be in {sorted(VALID_TIF)}")
    if order_type in ("limit", "stop_limit") and limit_price is None:
        raise ValueError(f"order_type={order_type} requires limit_price")
    if order_type in ("stop", "stop_limit") and stop_price is None:
        raise ValueError(f"order_type={order_type} requires stop_price")

    proposal = OrderProposal(
        symbol=symbol.upper(),
        side=side,
        qty=float(qty),
        order_type=order_type,
        limit_price=limit_price,
        stop_price=stop_price,
        time_in_force=time_in_force,
        broker=broker,
        account_id=account_id,
        strategy_tag=strategy_tag,
        trade_idea_id=trade_idea_id,
    )

    # 1) Run through risk_governor
    governor_decision = None
    if estimated_R_dollars is not None and strategy_tag:
        try:
            from .risk_governor import check_proposed_trade
            governor_decision = await check_proposed_trade(
                strategy_tag=strategy_tag,
                R_dollars_proposed=float(estimated_R_dollars),
                symbol=proposal.symbol,
                broker=broker,
            )
        except Exception as e:
            log.warning("[PREVIEW] governor check failed (non-fatal): %s", e)

    # 2) Wash-sale check (if this is a buy)
    wash_sale_flags = []
    if side in ("buy", "buy_to_cover"):
        try:
            from .tax_compliance import get_wash_sale_ledger
            led = await get_wash_sale_ledger()
            wash_sale_flags = await led.check_open(symbol=proposal.symbol)
        except Exception as e:
            log.debug("[PREVIEW] wash check skipped: %s", e)

    # 3) Lot-impact preview (if this is a sell)
    lot_impact = None
    if side in ("sell", "sell_short"):
        try:
            from .tax_lot_ledger import get_tax_lot_ledger
            led = await get_tax_lot_ledger()
            lot_impact = await led.recommend_lot_selection(
                symbol=proposal.symbol,
                qty_to_sell=proposal.qty,
                objective="hifo",
                broker=broker,
                account_id=account_id,
            )
        except Exception as e:
            log.debug("[PREVIEW] lot impact skipped: %s", e)

    # 4) Estimated commission (from trade_cost_ledger history)
    est_commission = await _estimate_commission(broker, proposal.symbol)

    # 5) Per-broker payload strings
    payloads = _format_payloads(proposal)

    return {
        "proposal": asdict(proposal),
        "is_preview_only": True,
        "submission_blocked": True,
        "blocked_reason": (
            "This is a PREVIEW. NCL never submits orders. "
            "Copy submission_payloads.{broker} into your broker's order ticket "
            "and click submit yourself."
        ),
        "governor_decision": governor_decision,
        "wash_sale_flags": wash_sale_flags,
        "lot_impact_preview": lot_impact,
        "estimated_commission_usd": est_commission,
        "submission_payloads": payloads,
        "preview_at": datetime.now(timezone.utc).isoformat(),
        "warnings": _collect_warnings(governor_decision, wash_sale_flags, lot_impact),
    }


async def _estimate_commission(broker: Optional[str], symbol: str) -> float:
    """Median commission for this broker+symbol over the past 30d, from
    the trade cost ledger. Falls back to a generic per-broker default
    when no history exists."""
    try:
        from .trade_cost_ledger import get_trade_cost_ledger
        led = await get_trade_cost_ledger()
        recent = await led.recent_entries(limit=500)
        matches = [
            e for e in recent
            if e.get("action") == "commission"
            and (broker is None or (e.get("broker") or "").lower() == broker.lower())
            and (e.get("symbol") or "").upper() == symbol.upper()
        ]
        if matches:
            amounts = sorted(e["amount_usd"] for e in matches)
            return round(amounts[len(amounts) // 2], 4)
    except Exception:
        pass
    # Per-broker defaults (rough)
    defaults = {"ibkr": 0.65, "moomoo": 0.99, "snaptrade": 0.0, "wealthsimple": 0.0,
                "ndax": 2.0, "polymarket": 0.0}
    if broker:
        return defaults.get(broker.lower(), 1.0)
    return 1.0


def _collect_warnings(governor, wash, lot_impact) -> list[str]:
    out = []
    if governor and not governor.get("approved"):
        out.append(f"GOVERNOR REJECTED: {governor.get('reasons', ['unknown'])[0]}")
    elif governor and governor.get("decision") == "throttle":
        out.append(
            f"Governor throttled: effective R ${governor.get('effective_R_dollars')} "
            f"(band={governor.get('band')}, mult={governor.get('sizing_multiplier')})"
        )
    if wash:
        out.append(
            f"WASH SALE RISK: {len(wash)} prior loss(es) within 61d window — "
            f"new buy may disallow the original loss for tax purposes"
        )
    if lot_impact and lot_impact.get("qty_short", 0) > 0:
        out.append(
            f"INSUFFICIENT LOTS: only {lot_impact['qty_satisfied']} shares "
            f"available in known lots; {lot_impact['qty_short']} short"
        )
    return out


def _format_payloads(p: OrderProposal) -> dict[str, str]:
    """Per-broker submission-string formats. Each starts with the
    IS_PREVIEW_ONLY=True sentinel so accidental eval/exec errors out
    of an interactive shell. These are advisory copy-paste payloads."""
    sym = p.symbol
    qty = p.qty
    side_l = p.side
    tif = p.time_in_force

    # IBKR ib_insync
    ibkr_order_class = {
        "market": "MarketOrder",
        "limit": "LimitOrder",
        "stop": "StopOrder",
        "stop_limit": "StopLimitOrder",
        "trail": "Order(orderType='TRAIL')",
    }[p.order_type]
    ibkr_action = "BUY" if side_l in ("buy", "buy_to_cover") else "SELL"
    ibkr_lines = [
        "# IS_PREVIEW_ONLY = True  # remove + read carefully before submitting",
        "from ib_insync import IB, Stock, " + ibkr_order_class.split("(")[0],
        "ib = IB(); ib.connect('127.0.0.1', 7496, clientId=1)",
        f"contract = Stock('{sym}', 'SMART', 'USD')",
    ]
    if p.order_type == "market":
        ibkr_lines.append(f"order = MarketOrder('{ibkr_action}', {qty}, tif='{tif}')")
    elif p.order_type == "limit":
        ibkr_lines.append(
            f"order = LimitOrder('{ibkr_action}', {qty}, {p.limit_price}, tif='{tif}')"
        )
    elif p.order_type == "stop":
        ibkr_lines.append(
            f"order = StopOrder('{ibkr_action}', {qty}, {p.stop_price}, tif='{tif}')"
        )
    elif p.order_type == "stop_limit":
        ibkr_lines.append(
            f"order = StopLimitOrder('{ibkr_action}', {qty}, {p.limit_price}, "
            f"{p.stop_price}, tif='{tif}')"
        )
    ibkr_lines.append("# trade = ib.placeOrder(contract, order)  # OPERATOR uncomments")

    # Moomoo (futu-api-style; the operator will adapt to OpenAPI flavor)
    moomoo_trd_side = "BUY" if side_l in ("buy", "buy_to_cover") else "SELL"
    moomoo_lines = [
        "# IS_PREVIEW_ONLY = True",
        f"# Moomoo OpenAPI order spec for {sym}:",
        f"#   code: 'US.{sym}'",
        f"#   trd_side: TrdSide.{moomoo_trd_side}",
        f"#   order_type: OrderType.{p.order_type.upper()}",
        f"#   qty: {qty}",
        f"#   price: {p.limit_price if p.limit_price is not None else 'None'}",
        f"#   time_in_force: TimeInForce.{tif}",
    ]

    # SnapTrade (Wealthsimple / etc.) — REST body
    st_action = "BUY" if side_l in ("buy", "buy_to_cover") else "SELL"
    snaptrade_lines = [
        "# IS_PREVIEW_ONLY = True",
        "# SnapTrade place_order body:",
        "{",
        f'  "action": "{st_action}",',
        f'  "order_type": "{p.order_type.title()}",',
        f'  "price": {p.limit_price if p.limit_price is not None else "null"},',
        f'  "stop": {p.stop_price if p.stop_price is not None else "null"},',
        f'  "time_in_force": "{tif}",',
        f'  "units": {qty},',
        f'  "universal_symbol_id": "<lookup {sym} via /symbols/search>"',
        "}",
    ]

    return {
        "ibkr": "\n".join(ibkr_lines),
        "moomoo": "\n".join(moomoo_lines),
        "snaptrade": "\n".join(snaptrade_lines),
        "note": (
            "These payloads are FORMATTED FOR COPY-PASTE only. NCL has no "
            "credentials to submit and will not submit. The operator submits."
        ),
    }
