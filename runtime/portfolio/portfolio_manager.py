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
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import aiohttp
from dotenv import load_dotenv

from .ibkr_adapter import IBKRAdapter
from .moomoo_adapter import MoomooAdapter
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
    is_dst = 3 < month < 11 or (month == 3 and utc_now.day >= 8) or (month == 11 and utc_now.day <= 7)
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
        self._adapters = [
            ("ibkr", self._ibkr),
            ("moomoo", self._moomoo),
            ("snaptrade", self._snaptrade),
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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect all adapters and begin background sync."""
        logger.info("PortfolioManager starting — connecting adapters")
        self._rotate_snapshots()
        for name, adapter in self._adapters:
            try:
                await adapter.connect()
                logger.info("Adapter %s connected", name)
            except Exception:
                logger.exception("Adapter %s failed to connect — continuing", name)

        # Initial sync
        await self.sync()

        # Start background loop
        self._running = True
        self._bg_task = asyncio.create_task(self._background_sync_loop())
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

            for name, adapter in self._adapters:
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
            self._positions = positions
            self._last_sync = _now_utc().isoformat()

            elapsed = time.monotonic() - t0
            logger.info(
                "Sync complete: %d accounts, %d positions (%.2fs)",
                len(accounts), len(positions), elapsed,
            )

            # Snapshot persistence
            self._maybe_write_snapshot()

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
                    removed, cutoff, len(kept),
                )
            else:
                logger.info("Snapshot rotation: all %d entries within %d-day window", len(kept), keep_days)
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
            cash = acct.get("cash", 0.0)
            cur = acct.get("currency", "USD")
            total += self._to_base(cash, cur, base)
        return total

    def _total_cash(self, base: str = "CAD") -> float:
        total = 0.0
        for acct in self._accounts:
            cash = acct.get("cash", 0.0)
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
        """Return (total_pl, total_pl_pct) across all positions."""
        total_pl = 0.0
        total_cost = 0.0
        for pos in self._positions:
            upl = pos.get("unrealized_pl", 0.0)
            cost = pos.get("cost_basis", 0.0)
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
            result.append({
                "label": label,
                "value": round(value, 2),
                "weight_pct": round(value / total * 100, 2),
            })
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

        # Account summary
        account_summaries = []
        for acct in self._accounts:
            acct_value = self._to_base(acct.get("total_value", 0.0), acct.get("currency", "USD"), base)
            account_summaries.append({
                "account_id": acct.get("account_id", ""),
                "broker": acct.get("broker", ""),
                "label": acct.get("label", ""),
                "type": acct.get("type", ""),
                "value": round(acct_value, 2),
                "currency": acct.get("currency", "USD"),
            })

        return {
            "total_value": round(total_value, 2),
            "base_currency": base,
            "daily_pl": round(daily_pl, 2),
            "daily_pl_pct": round(daily_pl_pct, 2),
            "total_pl": round(total_pl, 2),
            "total_pl_pct": round(total_pl_pct, 2),
            "cash_total": round(cash_total, 2),
            "positions_count": len(self._positions),
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
            entry = {
                "symbol": pos.get("symbol", ""),
                "name": pos.get("name", ""),
                "broker": broker,
                "account_id": pos.get("account_id", ""),
                "quantity": pos.get("quantity", 0),
                "avg_cost": pos.get("avg_cost", 0.0),
                "last_price": pos.get("last_price", 0.0),
                "market_value": pos.get("market_value", 0.0),
                "market_value_cad": round(mv_cad, 2),
                "currency": pos.get("currency", "USD"),
                "daily_pl": pos.get("daily_pl", 0.0),
                "daily_pl_pct": pos.get("daily_pl_pct", 0.0),
                "unrealized_pl": pos.get("unrealized_pl", 0.0),
                "unrealized_pl_pct": pos.get("unrealized_pl_pct", 0.0),
                "cost_basis": pos.get("cost_basis", 0.0),
                "sector": pos.get("sector", "Unknown"),
                "asset_class": pos.get("asset_class", "Equity"),
                "weight_pct": round(mv_cad / total * 100, 2),
            }
            positions.append(entry)

        positions.sort(key=lambda p: p.get("market_value_cad", 0), reverse=True)
        return positions

    def get_accounts(self) -> list[dict[str, Any]]:
        """Return all accounts from all connected brokers."""
        result = []
        for acct in self._accounts:
            result.append({
                "account_id": acct.get("account_id", ""),
                "broker": acct.get("broker", ""),
                "label": acct.get("label", ""),
                "type": acct.get("type", ""),
                "total_value": acct.get("total_value", 0.0),
                "cash": acct.get("cash", 0.0),
                "buying_power": acct.get("buying_power", 0.0),
                "currency": acct.get("currency", "USD"),
                "positions_count": acct.get("positions_count", 0),
            })
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
            filtered.append({
                "date": snap["date"],
                "value_usd": snap.get("total_value_usd", 0),
                "value_cad": snap.get("total_value_cad", 0),
            })

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
        return {
            "status": "ok" if self._connected_count() > 0 else "degraded",
            "adapters": {
                name: {"connected": adapter.connected}
                for name, adapter in self._adapters
            },
            "positions_cached": len(self._positions),
            "accounts_cached": len(self._accounts),
            "last_sync": self._last_sync,
            "fx_rate_usd_cad": self._fx_rate_usd_cad,
            "market_open": _is_market_open(),
            "background_sync": self._running,
        }
