"""
NCL Tax Lot Ledger — Wave 14J J4b (spec-ID at sale time)

Per-position tax-lot ledger so the operator can request specific-lot
identification (vs default FIFO) at sale time. The actual order-side
tagging is per-broker:

  IBKR        - order-level tax-lot ID supported (FIFO, LIFO, HIFO,
                MaxLossLIFO, MinLossFIFO, AverageCost, or specific lot
                with `OrderRef`/`tag` fields). We surface the recommended
                method; the operator routes the order.
  Moomoo      - limited; FIFO is the default; spec-ID is account-tier
                dependent. Surface as advisory only.
  SnapTrade   - depends on underlying broker; advisory only.
  NDAX/MetaMask/Polymarket - n/a (crypto basis tracked separately
                              in on_chain_journal.py).

What this module does:
  - Record incoming lots: every buy/open creates one or more
    TaxLot rows (qty, cost_basis_per_share, acquisition_date, lot_id).
  - At sale time: recommend_lot_selection(symbol, qty_to_sell,
    objective) returns which lot(s) to specify to the broker for the
    requested objective (HIFO max loss, LIFO min loss, FIFO default,
    LT-qualified only).
  - Track consumption: record_sale() decrements lots in the order the
    operator confirmed (typically the order we recommended).

Storage: data/portfolio/tax_lots.jsonl (append-only audit) +
         data/portfolio/tax_lots_state.json (current open lots).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.tax_lot_ledger")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio"
LOTS_FILE = DATA_DIR / "tax_lots.jsonl"
STATE_FILE = DATA_DIR / "tax_lots_state.json"

LT_DAYS = 366  # IRS long-term threshold


VALID_OBJECTIVES = {
    "fifo",         # first-in, first-out (broker default; usually worst)
    "lifo",         # last-in, first-out
    "hifo",         # highest cost-basis first (maximize loss)
    "lofo",         # lowest cost-basis first (defer gain / harvest gain)
    "lt_only",      # only lots already qualified for long-term cap gains
    "st_only",      # only short-term lots (e.g. to realize loss inside window)
    "max_loss",     # alias for HIFO
    "min_loss",     # alias for LOFO
}


@dataclass
class TaxLot:
    lot_id: str
    symbol: str           # uppercase
    broker: str
    account_id: str
    qty: float            # SIGNED — positive = long, negative = short
    cost_basis_per_share: float
    acquisition_date: str  # YYYY-MM-DD
    qty_remaining: float   # decremented at sale
    notes: str = ""
    metadata: dict = field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _days_held(acq: str, as_of: Optional[str] = None) -> int:
    try:
        a = datetime.fromisoformat(acq).date()
    except ValueError:
        return 0
    b = (datetime.fromisoformat(as_of).date()
         if as_of else datetime.now(timezone.utc).date())
    return (b - a).days


class TaxLotLedger:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._lots: dict[str, TaxLot] = {}
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            await self._load()
            self._initialized = True
            log.info(
                "[TAX-LOT] initialized — %d open lots loaded",
                sum(1 for l in self._lots.values() if l.qty_remaining != 0),
            )

    async def _load(self) -> None:
        if not STATE_FILE.exists():
            return
        try:
            raw = json.loads(STATE_FILE.read_text())
            if not isinstance(raw, dict):
                return
            field_names = {f for f in TaxLot.__dataclass_fields__}  # type: ignore[attr-defined]
            for lid, payload in raw.items():
                if not isinstance(payload, dict):
                    continue
                kept = {k: v for k, v in payload.items() if k in field_names}
                kept.setdefault("lot_id", lid)
                try:
                    self._lots[lid] = TaxLot(**kept)
                except Exception as e:
                    log.warning("[TAX-LOT] skip malformed %s: %s", lid, e)
        except Exception as e:
            log.warning("[TAX-LOT] load failed: %s", e)

    async def _persist(self) -> None:
        snap = {lid: asdict(lot) for lid, lot in self._lots.items()}
        tmp = STATE_FILE.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(snap, indent=2, sort_keys=True))
            tmp.replace(STATE_FILE)
        except Exception as e:
            log.error("[TAX-LOT] persist failed: %s", e)

    def _append_audit(self, action: str, lot: TaxLot, extra: Optional[dict] = None) -> None:
        row = {"ts": _now(), "action": action, "lot": asdict(lot), "extra": extra or {}}
        try:
            with open(LOTS_FILE, "a") as f:
                f.write(json.dumps(row) + "\n")
        except Exception as e:
            log.warning("[TAX-LOT] audit append failed: %s", e)

    # ── Public API ────────────────────────────────────────────────

    async def record_open(
        self,
        *,
        symbol: str,
        broker: str,
        account_id: str,
        qty: float,
        cost_basis_per_share: float,
        acquisition_date: Optional[str] = None,
        notes: str = "",
        metadata: Optional[dict] = None,
        lot_id: Optional[str] = None,
    ) -> dict:
        """Record a new lot opened (buy or short-sell).
        qty SIGNED (positive long, negative short)."""
        await self.initialize()
        lot = TaxLot(
            lot_id=lot_id or uuid.uuid4().hex[:16],
            symbol=symbol.upper(),
            broker=broker,
            account_id=account_id,
            qty=float(qty),
            cost_basis_per_share=float(cost_basis_per_share),
            acquisition_date=acquisition_date or _today(),
            qty_remaining=float(qty),
            notes=notes,
            metadata=metadata or {},
        )
        async with self._lock:
            self._lots[lot.lot_id] = lot
            await self._persist()
            self._append_audit("open", lot)
        return asdict(lot)

    async def open_lots_for(
        self, symbol: str, broker: Optional[str] = None, account_id: Optional[str] = None,
    ) -> list[dict]:
        await self.initialize()
        sym = symbol.upper()
        async with self._lock:
            out = []
            for lot in self._lots.values():
                if lot.symbol != sym or lot.qty_remaining == 0:
                    continue
                if broker and lot.broker.lower() != broker.lower():
                    continue
                if account_id and lot.account_id != account_id:
                    continue
                d = asdict(lot)
                d["days_held"] = _days_held(lot.acquisition_date)
                d["is_lt_qualified"] = d["days_held"] >= LT_DAYS
                out.append(d)
            return sorted(out, key=lambda l: l["acquisition_date"])

    async def recommend_lot_selection(
        self,
        *,
        symbol: str,
        qty_to_sell: float,
        objective: str = "hifo",
        broker: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> dict:
        """Return the lot-selection sequence that satisfies `objective`
        for selling `qty_to_sell` shares of `symbol`.

        Returns:
          {
            objective, qty_requested, qty_satisfied, qty_short,
            selection: [{lot_id, qty_consumed, cost_basis_per_share,
                         acquisition_date, days_held, is_lt_qualified,
                         realized_per_share_at_current_price}],
            method_hint: broker-specific spec-ID method string
                        (e.g. "IBKR: OrderRef='SPEC:lot_id1,lot_id2'"),
            notes
          }
        """
        objective_l = objective.lower().strip()
        if objective_l == "max_loss":
            objective_l = "hifo"
        if objective_l == "min_loss":
            objective_l = "lofo"
        if objective_l not in VALID_OBJECTIVES:
            raise ValueError(f"objective must be in {sorted(VALID_OBJECTIVES)}")

        lots = await self.open_lots_for(symbol, broker=broker, account_id=account_id)
        # Only consider lots on the same side (long lots for selling-long;
        # short lots for buy-to-close-short)
        lots = [l for l in lots if (l["qty_remaining"] > 0) == (qty_to_sell > 0)]
        if not lots:
            return {
                "objective": objective_l,
                "qty_requested": qty_to_sell,
                "qty_satisfied": 0,
                "qty_short": qty_to_sell,
                "selection": [],
                "method_hint": "",
                "notes": "No open lots match — cannot satisfy.",
            }

        # Sort by objective
        if objective_l == "fifo":
            ordered = sorted(lots, key=lambda l: l["acquisition_date"])
        elif objective_l == "lifo":
            ordered = sorted(lots, key=lambda l: l["acquisition_date"], reverse=True)
        elif objective_l == "hifo":
            ordered = sorted(lots, key=lambda l: -l["cost_basis_per_share"])
        elif objective_l == "lofo":
            ordered = sorted(lots, key=lambda l: l["cost_basis_per_share"])
        elif objective_l == "lt_only":
            qualified = [l for l in lots if l["is_lt_qualified"]]
            ordered = sorted(qualified, key=lambda l: -l["cost_basis_per_share"])
        elif objective_l == "st_only":
            short_term = [l for l in lots if not l["is_lt_qualified"]]
            ordered = sorted(short_term, key=lambda l: -l["cost_basis_per_share"])
        else:
            ordered = lots

        remaining = abs(qty_to_sell)
        selection = []
        for lot in ordered:
            if remaining <= 0:
                break
            avail = abs(lot["qty_remaining"])
            take = min(remaining, avail)
            selection.append({
                "lot_id": lot["lot_id"],
                "qty_consumed": take,
                "cost_basis_per_share": lot["cost_basis_per_share"],
                "acquisition_date": lot["acquisition_date"],
                "days_held": lot["days_held"],
                "is_lt_qualified": lot["is_lt_qualified"],
            })
            remaining -= take
        qty_satisfied = abs(qty_to_sell) - remaining

        # Broker hint
        broker_l = (broker or "").lower()
        if broker_l == "ibkr":
            ids = ",".join(s["lot_id"] for s in selection)
            method_hint = (
                f"IBKR: use OrderRef='SPEC:{ids}' and configure tax-lot method "
                f"'SpecificLots'. ib_insync: order.tag='SpecificLots'."
            )
        elif broker_l == "moomoo":
            method_hint = (
                "Moomoo: spec-ID limited; if account tier doesn't support, "
                "use sequential single-lot sales to approximate selection."
            )
        elif broker_l in ("snaptrade", "wealthsimple"):
            method_hint = (
                "SnapTrade: spec-ID depends on underlying broker. Surface as "
                "advisory; operator may need to call broker directly."
            )
        else:
            method_hint = (
                f"{broker or 'unknown broker'}: advisory only; verify spec-ID "
                f"support before submitting."
            )

        return {
            "objective": objective_l,
            "qty_requested": qty_to_sell,
            "qty_satisfied": qty_satisfied,
            "qty_short": remaining,
            "selection": selection,
            "method_hint": method_hint,
            "notes": (
                f"Selected {len(selection)} lot(s) for {qty_satisfied:.0f}/"
                f"{abs(qty_to_sell):.0f} shares via {objective_l}."
            ),
        }

    async def record_sale(
        self,
        *,
        symbol: str,
        lot_consumption: list[dict],
        sale_price_per_share: float,
        sale_date: Optional[str] = None,
        broker: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> dict:
        """After the operator confirms the sale order, decrement lot
        quantities and emit a per-lot realized P&L breakdown.

        lot_consumption is a list of {lot_id, qty_consumed}.
        """
        await self.initialize()
        sale_date_s = sale_date or _today()
        total_realized = 0.0
        breakdown = []
        async with self._lock:
            for entry in lot_consumption:
                lid = entry.get("lot_id")
                qty_c = float(entry.get("qty_consumed", 0))
                lot = self._lots.get(lid)
                if lot is None:
                    breakdown.append({"lot_id": lid, "error": "lot not found"})
                    continue
                if abs(lot.qty_remaining) < qty_c:
                    qty_c = abs(lot.qty_remaining)  # clamp
                signed = qty_c if lot.qty_remaining > 0 else -qty_c
                realized = (sale_price_per_share - lot.cost_basis_per_share) * abs(signed)
                if lot.qty_remaining < 0:
                    # short -> reverse sign convention
                    realized = (lot.cost_basis_per_share - sale_price_per_share) * abs(signed)
                lot.qty_remaining -= signed
                total_realized += realized
                days = _days_held(lot.acquisition_date, sale_date_s)
                is_lt = days >= LT_DAYS
                breakdown.append({
                    "lot_id": lid,
                    "qty_consumed": qty_c,
                    "cost_basis_per_share": lot.cost_basis_per_share,
                    "sale_price_per_share": sale_price_per_share,
                    "realized_pl": round(realized, 4),
                    "is_lt_qualified": is_lt,
                    "days_held": days,
                })
                self._append_audit("sale", lot, extra={
                    "qty_consumed": qty_c,
                    "sale_price_per_share": sale_price_per_share,
                    "sale_date": sale_date_s,
                    "is_lt_qualified": is_lt,
                })
            await self._persist()
        return {
            "symbol": symbol.upper(),
            "sale_date": sale_date_s,
            "total_realized": round(total_realized, 4),
            "breakdown": breakdown,
        }


_LEDGER: Optional[TaxLotLedger] = None
_LEDGER_LOCK = asyncio.Lock()


async def get_tax_lot_ledger() -> TaxLotLedger:
    global _LEDGER
    if _LEDGER is not None:
        await _LEDGER.initialize()
        return _LEDGER
    async with _LEDGER_LOCK:
        if _LEDGER is None:
            _LEDGER = TaxLotLedger()
            await _LEDGER.initialize()
    return _LEDGER
