"""
NCL Tax Compliance Layer — Wave 14J Phase 5 (J4a + J4c + J4d)

Three pieces with a shared theme: tax-aware portfolio decisions that
no single broker can flag because they require cross-broker context.

  J4a — Wash-sale ledger (CROSS-ACCOUNT, 61-day window)
        Every loss-sale records (symbol, account, broker, date,
        loss_amount). Every NEW open on the same symbol within 61
        days flagged regardless of which broker/account it's in. Two
        brokers + an IRA = three accounts the IRS lumps together.

  J4c — LT-qualification alert
        Daily scan: any held position with cost-basis age in
        (340, 366) days raises "approaching long-term holding" hint.
        Suggest hold-through unless thesis is broken.

  J4d — Earnings-proximity sizer
        Lookup days-to-next-earnings. Apply size modifier to any
        proposed trade:
          within 2d  -> halve long-premium; cap short-premium counts
          within 7d  -> trim long-premium 25%; flag for review
          beyond 7d  -> no modifier

DELIBERATELY does NOT compute tax owed, propose lot selection at sale,
or replace a CPA. This is signal-generation only — surface to the
operator at decision time so they can pick the legally-correct lot or
defer the harvest.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ncl.portfolio.tax_compliance")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio"
WASH_FILE = DATA_DIR / "wash_sale_ledger.jsonl"

WASH_WINDOW_DAYS = int(os.getenv("NCL_WASH_WINDOW_DAYS", "61"))
LT_CLIFF_MIN_DAYS = int(os.getenv("NCL_LT_CLIFF_MIN_DAYS", "340"))
LT_CLIFF_MAX_DAYS = int(os.getenv("NCL_LT_CLIFF_MAX_DAYS", "366"))


# ── J4a: Wash-sale ledger ──────────────────────────────────────────

@dataclass
class WashSaleEntry:
    ts: str               # ISO recording time
    symbol: str           # uppercase
    broker: str
    account_id: str
    loss_date: str        # YYYY-MM-DD of the loss-realization
    loss_amount: float    # USD loss (positive = $ lost)
    notes: str = ""


class WashSaleLedger:
    """Append-only JSONL ledger of realized losses + scan helper.

    A wash sale = realized loss on security X, then buying back X (or
    substantially identical) within 30 days BEFORE or AFTER the loss.
    The 30+30+1 = 61-day window is what we scan.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            self._initialized = True

    async def record_loss(
        self,
        *,
        symbol: str,
        broker: str,
        account_id: str,
        loss_date: str,
        loss_amount: float,
        notes: str = "",
    ) -> dict:
        """Record a realized loss. loss_date in YYYY-MM-DD.
        loss_amount is positive USD (the $ value lost on the sale)."""
        await self.initialize()
        entry = WashSaleEntry(
            ts=datetime.now(timezone.utc).isoformat(),
            symbol=symbol.upper(),
            broker=broker,
            account_id=account_id,
            loss_date=loss_date,
            loss_amount=float(loss_amount),
            notes=notes,
        )
        async with self._lock:
            try:
                with open(WASH_FILE, "a") as f:
                    f.write(json.dumps(asdict(entry)) + "\n")
            except Exception as e:
                log.error("[WASH] write failed: %s", e)
        return asdict(entry)

    async def check_open(
        self,
        *,
        symbol: str,
        as_of: Optional[str] = None,
        window_days: int = WASH_WINDOW_DAYS,
    ) -> list[dict]:
        """Return list of recent losses on `symbol` that would trigger
        wash-sale disallowance if we open a NEW position on this
        symbol today. Cross-account (broker + account_id don't matter
        for the IRS — same taxpayer controlling all accounts).
        """
        await self.initialize()
        as_of_dt = (
            datetime.fromisoformat(as_of).date()
            if as_of else datetime.now(timezone.utc).date()
        )
        cutoff = (as_of_dt - timedelta(days=window_days)).strftime("%Y-%m-%d")
        ahead_cutoff = (as_of_dt + timedelta(days=30)).strftime("%Y-%m-%d")
        sym = symbol.upper()
        out: list[dict] = []
        if not WASH_FILE.exists():
            return out
        try:
            with open(WASH_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if row.get("symbol", "").upper() != sym:
                        continue
                    loss_date = row.get("loss_date", "")
                    if not (cutoff <= loss_date <= ahead_cutoff):
                        continue
                    out.append(row)
        except Exception as e:
            log.warning("[WASH] read failed: %s", e)
        return out


# ── Singleton ─────────────────────────────────────────────────────

_WASH_LEDGER: Optional[WashSaleLedger] = None
_WASH_LOCK = asyncio.Lock()


async def get_wash_sale_ledger() -> WashSaleLedger:
    global _WASH_LEDGER
    if _WASH_LEDGER is not None:
        await _WASH_LEDGER.initialize()
        return _WASH_LEDGER
    async with _WASH_LOCK:
        if _WASH_LEDGER is None:
            _WASH_LEDGER = WashSaleLedger()
            await _WASH_LEDGER.initialize()
    return _WASH_LEDGER


# ── J4c: LT-qualification alert ──────────────────────────────────

def lt_cliff_scan(positions: list[dict], today: Optional[datetime] = None) -> list[dict]:
    """Scan positions for ones approaching long-term holding cliff.

    Positions need a `cost_basis_date` field (ISO YYYY-MM-DD) for this
    to fire. Broker adapters that don't provide it will simply be
    skipped — no false alarms.

    Returns positions with `days_held` in (LT_CLIFF_MIN_DAYS, LT_CLIFF_MAX_DAYS],
    sorted ascending by days_to_lt (smallest first = most urgent).

    Notes vary by tier:
      - if days_held in (340, 360]: "T-15-25 days to LT — consider hold"
      - if days_held in (360, 366]: "T-0-6 days to LT — sell triggers ordinary tax"
    """
    today = today or datetime.now(timezone.utc)
    today_d = today.date()
    out = []
    for p in positions:
        cb = p.get("cost_basis_date")
        if not cb:
            continue
        try:
            cb_d = datetime.fromisoformat(str(cb)).date()
        except ValueError:
            continue
        days_held = (today_d - cb_d).days
        if not (LT_CLIFF_MIN_DAYS <= days_held <= LT_CLIFF_MAX_DAYS):
            continue
        days_to_lt = 366 - days_held
        tier = "near" if days_to_lt > 5 else "imminent"
        out.append({
            "symbol": p.get("symbol"),
            "account_id": p.get("account_id"),
            "broker": p.get("broker"),
            "cost_basis_date": cb,
            "days_held": days_held,
            "days_to_lt_qualified": max(0, days_to_lt),
            "tier": tier,
            "recommendation": (
                f"Hold for {days_to_lt}d more to qualify for LT cap-gains "
                f"(currently ST: ordinary income rate). Sell only if thesis broken."
                if days_to_lt > 0
                else "LT qualified — taxable status now favorable on sale."
            ),
        })
    return sorted(out, key=lambda r: r["days_to_lt_qualified"])


# ── J4d: Earnings-proximity sizer ────────────────────────────────

@dataclass
class EarningsSizeModifier:
    days_to_earnings: int
    long_premium_mult: float       # multiply long-option proposals by this
    short_premium_mult: float      # multiply short-option proposals by this
    stock_mult: float              # equity-trade multiplier
    notes: str


def earnings_size_modifier(days_to_earnings: Optional[int]) -> EarningsSizeModifier:
    """Return sizing multipliers based on proximity to next earnings.

    Within 2d:  long-prem halved (IV crush risk), short-prem capped at 0.5,
                stock cut 25% (one-day-only volatility risk).
    Within 7d:  long-prem 0.75, short-prem 1.0 (preferred), stock 1.0.
    Beyond 7d:  all at 1.0.

    days_to_earnings == None means we couldn't look it up — no modifier.
    """
    if days_to_earnings is None:
        return EarningsSizeModifier(
            days_to_earnings=-1,
            long_premium_mult=1.0,
            short_premium_mult=1.0,
            stock_mult=1.0,
            notes="No earnings data — no modifier applied",
        )
    d = int(days_to_earnings)
    if 0 <= d <= 2:
        return EarningsSizeModifier(
            days_to_earnings=d,
            long_premium_mult=0.5,
            short_premium_mult=0.5,
            stock_mult=0.75,
            notes=(
                f"Within {d}d of earnings: long-premium HALVED (IV-crush risk), "
                f"short-premium capped at 0.5R per cycle, stock cut 25%."
            ),
        )
    if d <= 7:
        return EarningsSizeModifier(
            days_to_earnings=d,
            long_premium_mult=0.75,
            short_premium_mult=1.0,
            stock_mult=1.0,
            notes=(
                f"Within {d}d of earnings: long-premium 25% smaller; "
                f"short-premium preferred play (collect rising IV)."
            ),
        )
    return EarningsSizeModifier(
        days_to_earnings=d,
        long_premium_mult=1.0,
        short_premium_mult=1.0,
        stock_mult=1.0,
        notes=f"{d}d to earnings — no modifier",
    )
