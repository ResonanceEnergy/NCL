"""
NCL Portfolio Manager
=====================

Central portfolio aggregator that coordinates all broker adapters (IBKR, Moomoo,
SnapTrade). Provides unified views of positions, accounts, performance, and
allocation across the entire portfolio with automatic FX conversion.

Created once at Brain startup. Background sync every 60 seconds during market
hours, every 5 minutes outside hours.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import aiohttp
from dotenv import load_dotenv

from .ibkr_adapter import IBKRAdapter
from .memory_bridge import init_bridge as _init_bridge
from .metamask_adapter import MetaMaskAdapter
from .moomoo_adapter import MoomooAdapter
from .ndax_adapter import NDAXAdapter
from .polymarket_adapter import PolymarketAdapter
from .snaptrade_adapter import SnapTradeAdapter


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH)

logger = logging.getLogger("ncl.portfolio")

# Snapshot persistence
_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "portfolio"
_SNAPSHOT_FILE = _DATA_DIR / "snapshots.jsonl"

# FX cache duration
_FX_CACHE_SECONDS = 86_400  # 24 h
_FX_FALLBACK_RATE = 1.3750  # USD→CAD fallback if Bank of Canada API fails

# Bank of Canada Valet API for USD/CAD
_FX_URL = "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent=1"

# US Eastern Time offset from UTC (standard = -5, daylight = -4)
_ET_OFFSET_STD = timedelta(hours=-5)
_ET_OFFSET_DST = timedelta(hours=-4)

# Background sync intervals (seconds)
_SYNC_INTERVAL_MARKET = 60
_SYNC_INTERVAL_OFF = 300


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_et() -> datetime:
    """Return current time in US Eastern (approximate DST: Mar-Nov)."""
    utc_now = _now_utc()
    month = utc_now.month
    # Rough DST: second Sunday of March through first Sunday of November
    is_dst = (
        3 < month < 11 or (month == 3 and utc_now.day >= 8) or (month == 11 and utc_now.day <= 7)
    )
    offset = _ET_OFFSET_DST if is_dst else _ET_OFFSET_STD
    return utc_now + offset


def _is_market_open() -> bool:
    """Check if US equity markets are open (M-F 09:30-16:00 ET)."""
    et = _now_et()
    if et.weekday() >= 5:  # Sat/Sun
        return False
    t = et.hour * 60 + et.minute
    return 570 <= t < 960  # 09:30 = 570 min, 16:00 = 960 min


def _today_str() -> str:
    return _now_utc().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# PortfolioManager
# ---------------------------------------------------------------------------


class PortfolioManager:
    """
    Singleton-style portfolio aggregator.

    Coordinates IBKR, Moomoo, and SnapTrade adapters. Caches positions,
    accounts, and FX rates in memory. Persists daily snapshots to JSONL.
    """

    def __init__(self) -> None:
        # Adapters
        self._ibkr = IBKRAdapter()
        self._moomoo = MoomooAdapter()
        self._snaptrade = SnapTradeAdapter()
        # Crypto + prediction-market adapters (added 2026-05-22 EOD)
        self._ndax = NDAXAdapter()
        self._metamask = MetaMaskAdapter()
        self._polymarket = PolymarketAdapter()
        self._adapters = [
            ("ibkr", self._ibkr),
            ("moomoo", self._moomoo),
            ("snaptrade", self._snaptrade),
            ("ndax", self._ndax),
            ("metamask", self._metamask),
            ("polymarket", self._polymarket),
        ]

        # Cached data
        self._accounts: list[dict] = []
        self._positions: list[dict] = []
        self._last_sync: Optional[str] = None
        self._last_snapshot_date: Optional[str] = None

        # FX cache
        self._fx_rate_usd_cad: float = _FX_FALLBACK_RATE
        self._fx_fetched_at: float = 0.0

        # Concurrency
        self._sync_lock = asyncio.Lock()
        self._bg_task: Optional[asyncio.Task] = None
        self._running = False

        # Ensure data dir
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Memory bridge — emits portfolio:* memory units after each sync.
        # Defensive: never let a bridge failure break the manager.
        try:
            self._memory_bridge = _init_bridge(_DATA_DIR)
        except Exception:
            logger.exception("Memory bridge init failed — portfolio events disabled")
            self._memory_bridge = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect all adapters in parallel and begin background sync.

        Previously this was a sequential ``for`` loop, so a slow IBKR retry
        storm (15s connect timeout × N attempts) could block Wealthsimple +
        Moomoo + paper adapters behind it and stall lifespan for 10+ minutes
        on a degraded TWS/Gateway. Parallel ``asyncio.gather`` lets each
        adapter fail or succeed independently with bounded wall-clock cost.
        """
        logger.info(
            "PortfolioManager starting — connecting %d adapters in parallel", len(self._adapters)
        )
        self._rotate_snapshots()

        names = [name for name, _ in self._adapters]
        results = await asyncio.gather(
            *(adapter.connect() for _, adapter in self._adapters),
            return_exceptions=True,
        )
        for name, result in zip(names, results):
            if isinstance(result, BaseException):
                # Log per-adapter failure but keep the manager alive — broker
                # sync runs in a background loop and will retry these later.
                logger.warning(
                    "Adapter %s failed to connect: %s — continuing without it",
                    name,
                    result,
                )
            else:
                logger.info("Adapter %s connected", name)

        # Wave 14V V2 — launch background loop FIRST so the 20s lifespan
        # timeout that kills start() (when initial sync is slow) can't
        # prevent the bg sync from ever running. The bg loop is the only
        # thing keeping positions/quotes fresh; without it Portfolio tab
        # shows $0 indefinitely.
        self._running = True
        self._bg_task = asyncio.create_task(self._background_sync_loop())
        logger.info(
            "PortfolioManager bg loop launched — %d adapters active",
            self._connected_count(),
        )

        # Initial sync — best-effort; do not let a failing sync abort startup
        try:
            await self.sync()
        except Exception:
            logger.exception("Initial portfolio sync failed — background loop will retry")

        logger.info("PortfolioManager started — %d adapters active", self._connected_count())

    async def stop(self) -> None:
        """Disconnect all adapters and cancel background sync."""
        logger.info("PortfolioManager stopping")
        self._running = False
        if self._bg_task and not self._bg_task.done():
            self._bg_task.cancel()
            try:
                await self._bg_task
            except asyncio.CancelledError:
                pass
        for name, adapter in self._adapters:
            try:
                await adapter.disconnect()
                logger.info("Adapter %s disconnected", name)
            except Exception:
                logger.exception("Adapter %s failed to disconnect", name)
        logger.info("PortfolioManager stopped")

    def _connected_count(self) -> int:
        return sum(1 for _, a in self._adapters if a.connected)

    # ------------------------------------------------------------------
    # Background sync
    # ------------------------------------------------------------------

    async def _background_sync_loop(self) -> None:
        """Periodically call sync(). Faster during market hours."""
        logger.info("Background sync loop started")
        while self._running:
            interval = _SYNC_INTERVAL_MARKET if _is_market_open() else _SYNC_INTERVAL_OFF
            await asyncio.sleep(interval)
            if not self._running:
                break
            try:
                await self.sync()
            except Exception:
                logger.exception("Background sync failed")
        logger.info("Background sync loop exited")

    # ------------------------------------------------------------------
    # Core sync
    # ------------------------------------------------------------------

    async def sync(self) -> None:
        """
        Refresh positions and accounts from all connected adapters.
        Also refresh FX rate if cache expired. Persist snapshot if new day.
        """
        async with self._sync_lock:
            t0 = time.monotonic()
            await self._refresh_fx_rate()

            accounts: list[dict] = []
            positions: list[dict] = []

            # Reconnect disconnected adapters before syncing
            for name, adapter in self._adapters:
                if not adapter.connected:
                    try:
                        await adapter.connect()
                        if adapter.connected:
                            logger.info("Reconnected adapter %s", name)
                    except Exception:
                        logger.debug("Adapter %s still unavailable", name)
                    if not adapter.connected:
                        continue
                try:
                    broker_accounts = await adapter.get_accounts()
                    for acct in broker_accounts:
                        acct.setdefault("broker", name)
                    accounts.extend(broker_accounts)
                except Exception:
                    logger.exception("Failed to fetch accounts from %s", name)

                try:
                    broker_positions = await adapter.get_positions()
                    for pos in broker_positions:
                        pos.setdefault("broker", name)
                    positions.extend(broker_positions)
                except Exception:
                    logger.exception("Failed to fetch positions from %s", name)

            self._accounts = accounts
            # Fill missing/zero quotes via market-data fallback (yfinance) so
            # iOS doesn't show last_price=0 and absurd daily_pl_pct values
            # when adapters don't return a current price (e.g. Moomoo options
            # outside RTH, SnapTrade nightly sync).
            await self._fill_missing_quotes(positions)
            self._positions = positions
            self._last_sync = _now_utc().isoformat()

            elapsed = time.monotonic() - t0
            logger.info(
                "Sync complete: %d accounts, %d positions (%.2fs)",
                len(accounts),
                len(positions),
                elapsed,
            )

            # Snapshot persistence
            self._maybe_write_snapshot()

            # Memory bridge: emit memory units for snapshots + events.
            # Runs OUTSIDE the read paths and is fully defensive — never
            # raises back into the sync loop. Build a summary + positions
            # view first (same shape the API hands out).
            if self._memory_bridge is not None:
                try:
                    bridge_summary = self.get_summary(base_currency="CAD")
                    bridge_positions = self.get_positions(account_filter="all")
                    # Augment account dicts with buying_power so the
                    # bridge's BP-risk rule has the data it needs (the
                    # /summary endpoint elides it).
                    raw_accts = self.get_accounts()
                    bp_by_id = {a.get("account_id"): a.get("buying_power", 0.0) for a in raw_accts}
                    for a in bridge_summary.get("accounts", []) or []:
                        aid = a.get("account_id")
                        if aid in bp_by_id:
                            a["buying_power"] = bp_by_id[aid]
                    await self._memory_bridge.on_sync(bridge_summary, bridge_positions)
                except Exception:
                    logger.exception("Memory bridge on_sync failed (continuing)")

    # ------------------------------------------------------------------
    # Quote fallback
    # ------------------------------------------------------------------

    async def _fill_missing_quotes(self, positions: list[dict]) -> None:
        """
        For every position without a real current_price, fetch a quote via
        IBKRMarketData (which falls back to yfinance when IBKR isn't
        connected). Options positions are skipped — yfinance doesn't quote
        option contracts and IBKR option quoting needs a fully-built
        Option contract, which is out of scope here.

        Defensive: any failure leaves the position untouched.
        """
        needy: list[dict] = []
        for pos in positions:
            price = pos.get("current_price") or pos.get("last_price") or 0
            try:
                price = float(price)
            except (TypeError, ValueError):
                price = 0.0
            if price > 0:
                continue
            if pos.get("asset_class") in ("option", "future", "forex", "crypto", "prediction"):
                continue
            sym = pos.get("symbol") or ""
            # Skip option-encoded symbols (e.g. SLV270115C65000)
            if not sym or len(sym) > 8 or any(c.isdigit() for c in sym):
                continue
            needy.append(pos)

        if not needy:
            return

        try:
            from .ibkr_market_data import IBKRMarketData

            provider = IBKRMarketData(self._ibkr if self._ibkr.connected else None)
            symbols = sorted({p["symbol"] for p in needy})
            quotes = await provider.get_quotes(symbols)
        except Exception:
            logger.debug("Quote fallback skipped (provider unavailable)", exc_info=True)
            return

        filled = 0
        for pos in needy:
            q = quotes.get(pos["symbol"]) or {}
            price = q.get("price") or 0
            try:
                price = float(price)
            except (TypeError, ValueError):
                price = 0.0
            if price <= 0:
                continue
            pos["current_price"] = price
            qty = pos.get("quantity") or 0
            avg = pos.get("avg_cost") or 0
            if qty and avg and not pos.get("market_value"):
                pos["market_value"] = price * qty
            # If adapter didn't set daily_pl_pct, take it from the quote
            if not pos.get("daily_pl_pct"):
                pos["daily_pl_pct"] = q.get("change_pct") or 0.0
            filled += 1

        if filled:
            logger.info("Filled %d / %d missing quotes via %s", filled, len(needy), provider.source)

    # ------------------------------------------------------------------
    # FX conversion
    # ------------------------------------------------------------------

    async def _refresh_fx_rate(self) -> None:
        """Fetch USD/CAD from Bank of Canada Valet API. Cache for 24h."""
        if time.time() - self._fx_fetched_at < _FX_CACHE_SECONDS:
            return  # cache still fresh

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(_FX_URL) as resp:
                    if resp.status != 200:
                        logger.warning("FX API returned %d — using fallback", resp.status)
                        return
                    data = await resp.json(content_type=None)
                    observations = data.get("observations", [])
                    if observations:
                        # The rate is in FXUSDCAD → value of 1 USD in CAD
                        rate_str = observations[-1].get("FXUSDCAD", {}).get("v")
                        if rate_str:
                            self._fx_rate_usd_cad = float(rate_str)
                            self._fx_fetched_at = time.time()
                            logger.info("FX rate updated: 1 USD = %.4f CAD", self._fx_rate_usd_cad)
                            return
            logger.warning("FX API response missing rate data — using fallback")
        except Exception:
            logger.exception("FX rate fetch failed — using fallback %.4f", self._fx_rate_usd_cad)

    def _to_cad(self, value: float, currency: str) -> float:
        """Convert a value to CAD."""
        if currency.upper() == "CAD":
            return value
        if currency.upper() == "USD":
            return value * self._fx_rate_usd_cad
        # Unknown currency — treat as USD
        logger.warning("Unknown currency %s — treating as USD for conversion", currency)
        return value * self._fx_rate_usd_cad

    def _to_base(self, value: float, currency: str, base: str) -> float:
        """Convert value from *currency* to *base* (CAD or USD)."""
        if currency.upper() == base.upper():
            return value
        if base.upper() == "CAD":
            return self._to_cad(value, currency)
        if base.upper() == "USD":
            # Convert to CAD first, then to USD
            cad_val = self._to_cad(value, currency)
            return cad_val / self._fx_rate_usd_cad if self._fx_rate_usd_cad else cad_val
        return value

    # ------------------------------------------------------------------
    # Snapshot persistence
    # ------------------------------------------------------------------

    def _maybe_write_snapshot(self) -> None:
        """Append a daily snapshot line during market hours if date changed."""
        if not _is_market_open():
            return
        today = _today_str()
        if today == self._last_snapshot_date:
            return

        total_usd = self._total_value("USD")
        total_cad = self._total_value("CAD")
        snapshot = {
            "date": today,
            "total_value_usd": round(total_usd, 2),
            "total_value_cad": round(total_cad, 2),
            "positions_count": len(self._positions),
            "timestamp": _now_utc().isoformat(),
        }
        try:
            with open(_SNAPSHOT_FILE, "a") as f:
                f.write(json.dumps(snapshot) + "\n")
            self._last_snapshot_date = today
            logger.info("Snapshot written for %s", today)
        except Exception:
            logger.exception("Failed to write snapshot")

    def _load_snapshots(self) -> list[dict]:
        """Load all snapshots from JSONL file."""
        snapshots: list[dict] = []
        if not _SNAPSHOT_FILE.exists():
            return snapshots
        try:
            with open(_SNAPSHOT_FILE) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        snapshots.append(json.loads(line))
        except Exception:
            logger.exception("Failed to load snapshots")
        return snapshots

    def _rotate_snapshots(self, keep_days: int = 90) -> None:
        """Remove snapshot entries older than *keep_days*. Runs at startup."""
        if not _SNAPSHOT_FILE.exists():
            return
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        kept: list[str] = []
        removed = 0
        try:
            with open(_SNAPSHOT_FILE) as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        snap = json.loads(stripped)
                        if snap.get("date", "") >= cutoff:
                            kept.append(stripped)
                        else:
                            removed += 1
                    except json.JSONDecodeError:
                        # Keep malformed lines to avoid silent data loss
                        kept.append(stripped)
            if removed > 0:
                with open(_SNAPSHOT_FILE, "w") as f:
                    for entry in kept:
                        f.write(entry + "\n")
                logger.info(
                    "Snapshot rotation: removed %d entries older than %s, kept %d",
                    removed,
                    cutoff,
                    len(kept),
                )
            else:
                logger.info(
                    "Snapshot rotation: all %d entries within %d-day window", len(kept), keep_days
                )
        except Exception:
            logger.exception("Snapshot rotation failed — file left intact")

    # ------------------------------------------------------------------
    # Aggregation helpers
    # ------------------------------------------------------------------

    def _total_value(self, base: str = "CAD") -> float:
        """Sum market_value of all positions in base currency."""
        total = 0.0
        for pos in self._positions:
            mv = pos.get("market_value", 0.0)
            cur = pos.get("currency", "USD")
            total += self._to_base(mv, cur, base)
        # Add cash from accounts
        for acct in self._accounts:
            cash = acct.get("cash_balance", 0.0)
            cur = acct.get("currency", "USD")
            total += self._to_base(cash, cur, base)
        return total

    def _total_cash(self, base: str = "CAD") -> float:
        total = 0.0
        for acct in self._accounts:
            cash = acct.get("cash_balance", 0.0)
            cur = acct.get("currency", "USD")
            total += self._to_base(cash, cur, base)
        return total

    def _daily_pl(self, base: str = "CAD") -> tuple[float, float]:
        """Return (daily_pl, daily_pl_pct) across all positions."""
        total_pl = 0.0
        total_prev = 0.0
        for pos in self._positions:
            dpl = pos.get("daily_pl", 0.0)
            mv = pos.get("market_value", 0.0)
            cur = pos.get("currency", "USD")
            total_pl += self._to_base(dpl, cur, base)
            prev = mv - dpl
            total_prev += self._to_base(prev, cur, base)
        pct = (total_pl / total_prev * 100) if total_prev else 0.0
        return total_pl, pct

    def _total_pl(self, base: str = "CAD") -> tuple[float, float]:
        """Return (total_pl, total_pl_pct) across all positions.

        Audit 2026-05-22 P0 fix: cost_basis was missing on adapter-returned
        positions, falling back to 0 → divide-by-zero → pct always 0.0
        despite total_pl having real value. Now derives cost_basis from
        avg_cost * qty * multiplier (defaulting multiplier=100 for options).
        """
        total_pl = 0.0
        total_cost = 0.0
        for pos in self._positions:
            upl = pos.get("unrealized_pl", 0.0)
            cost = pos.get("cost_basis", 0.0)
            # Fallback: derive cost_basis if adapter didn't set it.
            if not cost or cost <= 0:
                qty = pos.get("quantity", 0.0) or 0.0
                avg_cost = pos.get("avg_cost", 0.0) or 0.0
                multiplier = pos.get("multiplier")
                if multiplier is None:
                    # Default ×100 for options, ×1 for everything else
                    asset_class = (pos.get("asset_class") or "").lower()
                    multiplier = 100 if asset_class == "option" else 1
                cost = abs(qty) * avg_cost * multiplier
            cur = pos.get("currency", "USD")
            total_pl += self._to_base(upl, cur, base)
            total_cost += self._to_base(cost, cur, base)
        pct = (total_pl / total_cost * 100) if total_cost else 0.0
        return total_pl, pct

    def _allocation_by(self, key: str, base: str = "CAD") -> list[dict]:
        """Group positions by *key* and return allocation breakdown."""
        groups: dict[str, float] = {}
        for pos in self._positions:
            label = pos.get(key, "Unknown")
            mv = pos.get("market_value", 0.0)
            cur = pos.get("currency", "USD")
            groups[label] = groups.get(label, 0.0) + self._to_base(mv, cur, base)

        total = sum(groups.values()) or 1.0
        result = []
        for label, value in sorted(groups.items(), key=lambda x: -x[1]):
            result.append(
                {
                    "label": label,
                    "value": round(value, 2),
                    "weight_pct": round(value / total * 100, 2),
                }
            )
        return result

    # ------------------------------------------------------------------
    # Public data methods
    # ------------------------------------------------------------------

    def get_summary(self, base_currency: str = "CAD") -> dict[str, Any]:
        """
        Full portfolio summary with totals, P&L, allocation, FX rate,
        and connected broker info.
        """
        base = base_currency.upper()
        total_value = self._total_value(base)
        cash_total = self._total_cash(base)
        daily_pl, daily_pl_pct = self._daily_pl(base)
        total_pl, total_pl_pct = self._total_pl(base)

        # Account summary — net_liquidation from adapters is cash only for some
        # brokers (e.g. SnapTrade).  Add position market values per account.
        _pos_by_acct: dict[str, float] = {}
        for pos in self._positions:
            aid = pos.get("account_id", "")
            mv = self._to_base(pos.get("market_value", 0.0), pos.get("currency", "USD"), base)
            _pos_by_acct[aid] = _pos_by_acct.get(aid, 0.0) + mv

        # Audit 2026-05-22 P0 fix: Moomoo's net_liquidation already includes
        # position market value (total_assets from SDK). SnapTrade's
        # net_liquidation is cash-only and needs positions added back.
        # Previous code added positions to BOTH unconditionally → Moomoo
        # accounts showed 2.7× over-counted balances in iOS account switcher.
        account_summaries = []
        for acct in self._accounts:
            aid = acct.get("account_id", "")
            broker = (acct.get("broker") or "").upper()
            net_liq = self._to_base(
                acct.get("net_liquidation", 0.0), acct.get("currency", "USD"), base
            )
            pos_val = _pos_by_acct.get(aid, 0.0)
            if broker == "MOOMOO":
                # net_liq IS total assets; positions already counted
                acct_value = net_liq
            else:
                # SnapTrade / IBKR: net_liq is cash-equivalent; add positions
                acct_value = net_liq + pos_val
            account_summaries.append(
                {
                    "account_id": acct.get("account_id", ""),
                    "broker": acct.get("broker", ""),
                    "label": acct.get("name", ""),
                    "type": acct.get("account_type", ""),
                    "value": round(acct_value, 2),
                    "positions_count": len(
                        [p for p in self._positions if p.get("account_id") == aid]
                    ),
                    "currency": acct.get("currency", "USD"),
                }
            )

        quotes_failed = sum(
            1
            for p in self._positions
            if not (p.get("current_price") or p.get("last_price") or 0) > 0
        )

        return {
            "total_value": round(total_value, 2),
            "base_currency": base,
            "daily_pl": round(daily_pl, 2),
            "daily_pl_pct": round(daily_pl_pct, 2),
            "total_pl": round(total_pl, 2),
            "total_pl_pct": round(total_pl_pct, 2),
            "cash_total": round(cash_total, 2),
            "positions_count": len(self._positions),
            "quotes_failed": quotes_failed,
            "accounts": account_summaries,
            "allocation": {
                "by_sector": self._allocation_by("sector", base),
                "by_account": self._allocation_by("broker", base),
                "by_asset_class": self._allocation_by("asset_class", base),
            },
            "fx_rate_usd_cad": round(self._fx_rate_usd_cad, 4),
            "last_sync": self._last_sync,
            "market_open": _is_market_open(),
            "brokers_connected": [name for name, a in self._adapters if a.connected],
        }

    def get_positions(self, account_filter: str = "all") -> list[dict[str, Any]]:
        """
        Return all positions, optionally filtered by broker name.
        Each position includes weight_pct relative to total portfolio.
        Sorted by market_value descending.
        """
        total = self._total_value("CAD") or 1.0

        positions = []
        for pos in self._positions:
            broker = pos.get("broker", "")
            if account_filter != "all" and broker.lower() != account_filter.lower():
                continue

            mv_cad = self._to_base(
                pos.get("market_value", 0.0),
                pos.get("currency", "USD"),
                "CAD",
            )

            # Quote pipeline: adapters write `current_price`; older code looked
            # for `last_price`, which is why every position showed 0 and
            # daily_pl_pct printed nonsense like -1272%. Read both, prefer
            # whichever is non-zero. If both are zero, surface as None and
            # zero-out the % so the iOS card shows "--" instead of garbage.
            qty = pos.get("quantity", 0) or 0
            avg_cost = pos.get("avg_cost", 0.0) or 0.0
            raw_price = pos.get("current_price", 0.0) or pos.get("last_price", 0.0) or 0.0
            quote_ok = bool(raw_price and raw_price > 0)

            if quote_ok:
                last_price: Optional[float] = float(raw_price)
                daily_pl_pct = pos.get("daily_pl_pct", 0.0) or 0.0
                # Bound sanity: 1-day move > 100% on a real quote is almost
                # always a synthetic divide-by-tiny-cost. Clamp.
                if not isinstance(daily_pl_pct, (int, float)) or abs(daily_pl_pct) > 100:
                    daily_pl_pct = 0.0
            else:
                # Stale / missing quote: don't fabricate. Fall back to avg_cost
                # so the value display isn't visually broken; emit None for
                # the price field so the UI can show "--".
                last_price = None
                daily_pl_pct = 0.0

            cost_basis = pos.get("cost_basis", 0.0)
            if not cost_basis and qty and avg_cost:
                cost_basis = abs(qty * avg_cost)

            entry = {
                "symbol": pos.get("symbol", ""),
                "name": pos.get("name", ""),
                "broker": broker,
                "account_id": pos.get("account_id", ""),
                "quantity": qty,
                "avg_cost": avg_cost,
                "last_price": last_price,
                "quote_ok": quote_ok,
                "market_value": pos.get("market_value", 0.0),
                "market_value_cad": round(mv_cad, 2),
                "currency": pos.get("currency", "USD"),
                "daily_pl": pos.get("daily_pl", 0.0) if quote_ok else 0.0,
                "daily_pl_pct": daily_pl_pct,
                "unrealized_pl": pos.get("unrealized_pl", 0.0),
                "unrealized_pl_pct": pos.get("unrealized_pl_pct", 0.0),
                "cost_basis": cost_basis,
                "sector": pos.get("sector", "Unknown"),
                "asset_class": pos.get("asset_class", "Equity"),
                "weight_pct": round(mv_cad / total * 100, 2),
            }
            positions.append(entry)

        positions.sort(key=lambda p: p.get("market_value_cad", 0), reverse=True)
        return positions

    def get_accounts(self) -> list[dict[str, Any]]:
        """Return all accounts from all connected brokers.

        positions_count is computed live from `self._positions` keyed by
        account_id — adapters don't supply it, and the previous
        implementation always emitted 0.
        """
        # Bucket positions by account_id once
        pos_by_acct: dict[str, int] = {}
        for pos in self._positions:
            aid = pos.get("account_id", "")
            if aid:
                pos_by_acct[aid] = pos_by_acct.get(aid, 0) + 1

        result = []
        for acct in self._accounts:
            aid = acct.get("account_id", "")
            result.append(
                {
                    "account_id": aid,
                    "broker": acct.get("broker", ""),
                    "label": acct.get("name", ""),
                    "type": acct.get("account_type", ""),
                    "total_value": acct.get("net_liquidation", 0.0),
                    "cash": acct.get("cash_balance", 0.0),
                    "buying_power": acct.get("buying_power", 0.0),
                    "currency": acct.get("currency", "USD"),
                    "positions_count": pos_by_acct.get(aid, 0),
                }
            )
        return result

    def get_performance(self, range: str = "1M") -> dict[str, Any]:
        """
        Return performance data points for charting.

        Ranges: 1D, 1W, 1M, 3M, YTD, 1Y, ALL
        Data comes from daily snapshots in snapshots.jsonl.
        """
        snapshots = self._load_snapshots()
        if not snapshots:
            return {
                "range": range,
                "data_points": [],
                "start_value": 0,
                "end_value": 0,
                "change": 0,
                "change_pct": 0,
            }

        # Determine cutoff date
        today = datetime.now(timezone.utc).date()
        range_upper = range.upper()
        cutoff_map = {
            "1D": today - timedelta(days=1),
            "1W": today - timedelta(weeks=1),
            "1M": today - timedelta(days=30),
            "3M": today - timedelta(days=90),
            "YTD": today.replace(month=1, day=1),
            "1Y": today - timedelta(days=365),
            "ALL": None,
        }
        cutoff = cutoff_map.get(range_upper)

        # Filter snapshots
        filtered = []
        for snap in snapshots:
            try:
                snap_date = datetime.strptime(snap["date"], "%Y-%m-%d").date()
            except (KeyError, ValueError):
                continue
            if cutoff and snap_date < cutoff:
                continue
            filtered.append(
                {
                    "date": snap["date"],
                    "value_usd": snap.get("total_value_usd", 0),
                    "value_cad": snap.get("total_value_cad", 0),
                }
            )

        # Sort by date
        filtered.sort(key=lambda x: x["date"])

        # Compute change
        if len(filtered) >= 2:
            start_val = filtered[0]["value_cad"]
            end_val = filtered[-1]["value_cad"]
        elif len(filtered) == 1:
            start_val = end_val = filtered[0]["value_cad"]
        else:
            start_val = end_val = 0

        change = end_val - start_val
        change_pct = (change / start_val * 100) if start_val else 0

        return {
            "range": range_upper,
            "data_points": filtered,
            "start_value": round(start_val, 2),
            "end_value": round(end_val, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
        }

    # ------------------------------------------------------------------
    # Status / health
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Return health/status info for Brain health endpoint."""
        # Quote feed health — how many positions have no live price.
        # Driven off the same `current_price`-or-`last_price` check as
        # get_positions(); a high count means TWS is down or the
        # yfinance fallback isn't firing.
        quotes_failed = 0
        for pos in self._positions:
            raw_price = pos.get("current_price", 0.0) or pos.get("last_price", 0.0) or 0.0
            if not raw_price or raw_price <= 0:
                quotes_failed += 1
        quote_status = "ok"
        if self._positions and quotes_failed >= len(self._positions):
            quote_status = "down"
        elif quotes_failed > 0:
            quote_status = "degraded"

        return {
            "status": "ok" if self._connected_count() > 0 else "degraded",
            "adapters": {
                name: {"connected": adapter.connected} for name, adapter in self._adapters
            },
            "positions_cached": len(self._positions),
            "accounts_cached": len(self._accounts),
            "quotes_failed": quotes_failed,
            "quotes_total": len(self._positions),
            "quote_feed_status": quote_status,
            "last_sync": self._last_sync,
            "fx_rate_usd_cad": self._fx_rate_usd_cad,
            "market_open": _is_market_open(),
            "background_sync": self._running,
        }


# ── Wave 14V V2 — module-level accessor for brief_prep + auto-trader ──

def get_portfolio_manager() -> Optional["PortfolioManager"]:
    """Return the live PortfolioManager singleton (or None pre-lifespan).

    brief_prep + auto-trader use this instead of constructing their own
    PortfolioManager (which would not be connected). The singleton is
    set by the FastAPI lifespan in runtime/api/routes.py.
    """
    try:
        from runtime.api.routers.portfolio import _portfolio_manager as _pm
        return _pm
    except Exception:
        return None
