"""
Watchlist store — Brain-as-source-of-truth.

Persists at: data/watchlist/watchlist.json

Prior to this module, the watchlist lived in TWO places:
  - runtime/stocks/watchlist.py:DEFAULT_WATCHLIST (Python module constant)
  - Sources/Models/StockModels.swift:defaultWatchlist (iOS Swift mirror)
They were manually kept in sync by hand-editing both files — every time
NATRIX wanted to add a ticker, two repos needed a commit.

Now the JSON file is canonical. The Python ``DEFAULT_WATCHLIST`` becomes
a one-time seed (loaded into the JSON on first boot if no file exists).
iOS fetches via ``GET /stocks/watchlist``, caches, and can edit via
``POST /stocks/watchlist`` + ``DELETE``. The Swift mirror is removed in
the iOS-side commit.

Atomic write: tmp + fsync + replace. Concurrent edits are guarded by
an asyncio.Lock; the store is a singleton per process.

Schema (one file, list of entries):
  {
    "schema_version": 1,
    "updated_at": "2026-05-25T...",
    "tickers": [
      {
        "ticker": "NVDA",
        "display": "NVDA",        # iOS-side label (strip .TO etc)
        "name": "NVIDIA Corp",
        "sector": "Semis/AI",
        "currency": "USD",
        "is_position": false,
        "notes": "",               # NATRIX-editable free text
        "added_at": "2026-05-25T...",
        "source": "default_seed"   # default_seed | manual | tv_import | scanner_pin
      },
      ...
    ]
  }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .watchlist import DEFAULT_WATCHLIST, WatchlistTicker


log = logging.getLogger("ncl.stocks.watchlist_store")


SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WatchlistStore:
    """Persistent JSON-backed watchlist with CRUD + import."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.watchlist_dir = self.data_dir / "watchlist"
        self.watchlist_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.watchlist_dir / "watchlist.json"
        self._lock = asyncio.Lock()
        self._cache: Optional[list[dict]] = None  # warmed on first read

    # ── public CRUD ───────────────────────────────────────────────────

    async def get_all(self) -> list[dict]:
        """Return the full watchlist as a list of ticker dicts."""
        async with self._lock:
            if self._cache is None:
                self._cache = await self._load_or_seed()
            return list(self._cache)

    async def add(
        self,
        ticker: str,
        *,
        name: str = "",
        sector: str = "Other",
        currency: str = "USD",
        is_position: bool = False,
        notes: str = "",
        source: str = "manual",
    ) -> dict:
        """Add or upsert a ticker. Returns the stored entry."""
        async with self._lock:
            if self._cache is None:
                self._cache = await self._load_or_seed()
            ticker_u = ticker.strip().upper()
            if not ticker_u:
                raise ValueError("ticker required")
            entry = self._find(ticker_u)
            if entry:
                # Upsert: only overwrite non-blank incoming fields
                if name:
                    entry["name"] = name
                if sector and sector != "Other":
                    entry["sector"] = sector
                if currency and currency != "USD":
                    entry["currency"] = currency
                if notes:
                    entry["notes"] = notes
                entry["is_position"] = is_position
                entry["updated_at"] = _now()
            else:
                entry = {
                    "ticker": ticker_u,
                    "display": _display_ticker(ticker_u),
                    "name": name,
                    "sector": sector,
                    "currency": currency,
                    "is_position": is_position,
                    "notes": notes,
                    "added_at": _now(),
                    "updated_at": _now(),
                    "source": source,
                }
                self._cache.append(entry)
            await self._persist()
            return dict(entry)

    async def remove(self, ticker: str) -> bool:
        """Remove a ticker. Returns True if removed."""
        async with self._lock:
            if self._cache is None:
                self._cache = await self._load_or_seed()
            ticker_u = ticker.strip().upper()
            before = len(self._cache)
            self._cache = [
                t for t in self._cache
                if t["ticker"].upper() != ticker_u
                and t.get("display", "").upper() != ticker_u
            ]
            if len(self._cache) == before:
                return False
            await self._persist()
            return True

    async def patch(self, ticker: str, **updates: Any) -> Optional[dict]:
        """Partial update of one entry. Returns the updated entry or None."""
        ticker_u = ticker.strip().upper()
        async with self._lock:
            if self._cache is None:
                self._cache = await self._load_or_seed()
            entry = self._find(ticker_u)
            if not entry:
                return None
            for k, v in updates.items():
                if k in ("ticker",):  # immutable
                    continue
                if v is not None:
                    entry[k] = v
            entry["updated_at"] = _now()
            await self._persist()
            return dict(entry)

    async def import_tradingview_txt(
        self, text: str, *, replace: bool = False
    ) -> dict[str, Any]:
        """Ingest a TradingView watchlist export.

        TV export format is one symbol per line, prefixed with the
        exchange (NASDAQ:NVDA, NYSE:F, BATS:SPY, TSX:WCP, etc.). Comma-
        separated also works for single-line exports.

        Args:
            text: the raw .txt contents
            replace: if True, wipe existing entries first; if False, merge

        Returns:
            ``{"added": int, "skipped": int, "total": int, "tickers": [...]}``
        """
        # Split on commas and newlines; strip whitespace
        raw_symbols = re.split(r"[,\n\r]+", text)
        parsed: list[tuple[str, str]] = []  # (exchange, ticker)
        for sym in raw_symbols:
            sym = sym.strip()
            if not sym:
                continue
            if ":" in sym:
                exchange, ticker = sym.split(":", 1)
                exchange = exchange.strip().upper()
                ticker = ticker.strip().upper()
            else:
                exchange = ""
                ticker = sym.strip().upper()
            if not ticker:
                continue
            parsed.append((exchange, ticker))

        async with self._lock:
            if self._cache is None:
                self._cache = await self._load_or_seed()

            if replace:
                self._cache = []

            added = 0
            skipped = 0
            tickers_out: list[str] = []
            for exchange, ticker in parsed:
                # Map TV exchange → currency + suffix
                currency = "USD"
                stored_ticker = ticker
                if exchange in ("TSX", "TSXV"):
                    currency = "CAD"
                    # iOS expects .TO suffix for TSX names on yfinance
                    if not stored_ticker.endswith(".TO"):
                        stored_ticker = f"{ticker}.TO"
                elif exchange in ("LSE", "LON"):
                    currency = "GBP"
                elif exchange in ("HKEX", "SEHK"):
                    currency = "HKD"
                elif exchange in ("TSE", "JPX"):
                    currency = "JPY"
                elif exchange in ("CRYPTO", "COINBASE", "BINANCE", "KRAKEN"):
                    currency = ticker.split("USD")[-1] if "USD" in ticker else "USD"

                if self._find(stored_ticker):
                    skipped += 1
                    continue

                self._cache.append(
                    {
                        "ticker": stored_ticker,
                        "display": _display_ticker(stored_ticker),
                        "name": "",  # TV doesn't export the long name
                        "sector": "TV Import",
                        "currency": currency,
                        "is_position": False,
                        "notes": f"Imported from TradingView ({exchange})" if exchange else "Imported from TradingView",
                        "added_at": _now(),
                        "updated_at": _now(),
                        "source": "tv_import",
                    }
                )
                added += 1
                tickers_out.append(stored_ticker)

            await self._persist()

            return {
                "added": added,
                "skipped": skipped,
                "total": len(self._cache),
                "tickers": tickers_out,
                "parsed": len(parsed),
            }

    # ── internals ─────────────────────────────────────────────────────

    def _find(self, ticker_u: str) -> Optional[dict]:
        """Lookup by ticker or display, case-insensitive."""
        for t in self._cache or []:
            if t.get("ticker", "").upper() == ticker_u:
                return t
            if t.get("display", "").upper() == ticker_u:
                return t
        return None

    async def _load_or_seed(self) -> list[dict]:
        """Load from disk; if no file exists, seed from DEFAULT_WATCHLIST."""
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                tickers = raw.get("tickers", [])
                if isinstance(tickers, list):
                    log.info(
                        "[WATCHLIST-STORE] loaded %d tickers from %s",
                        len(tickers),
                        self.path,
                    )
                    return tickers
            except Exception as exc:
                log.warning("[WATCHLIST-STORE] load failed (%s) — re-seeding", exc)

        # Seed from the Python defaults
        seeded: list[dict] = []
        for t in DEFAULT_WATCHLIST:
            seeded.append(
                {
                    "ticker": t.ticker,
                    "display": _display_ticker(t.ticker),
                    "name": t.name,
                    "sector": t.sector,
                    "currency": t.currency,
                    "is_position": t.is_position,
                    "notes": "",
                    "added_at": _now(),
                    "updated_at": _now(),
                    "source": "default_seed",
                }
            )
        log.info("[WATCHLIST-STORE] seeded %d default tickers", len(seeded))
        # Write the seed so next boot loads from disk
        self._cache = seeded
        await self._persist()
        return list(seeded)

    async def _persist(self) -> None:
        """Atomic write: serialize off the event loop, then tmp + fsync + replace."""
        payload = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": _now(),
            "tickers": self._cache or [],
        }
        tmp = self.path.with_suffix(".json.tmp")

        def _do_write() -> None:
            text = json.dumps(payload, indent=2, default=str)
            tmp.write_text(text, encoding="utf-8")
            with open(tmp, "rb+") as f:
                os.fsync(f.fileno())
            os.replace(str(tmp), str(self.path))

        await asyncio.to_thread(_do_write)


# ── helpers ─────────────────────────────────────────────────────────────


def _display_ticker(ticker: str) -> str:
    """Strip exchange suffix for display (WCP.TO → WCP)."""
    return ticker.split(".")[0]


# Module-level singleton — set at Brain boot via init_store()
_STORE: Optional[WatchlistStore] = None


def init_store(data_dir: Path) -> WatchlistStore:
    """Idempotent — call from Brain startup. Returns the singleton."""
    global _STORE
    if _STORE is None:
        _STORE = WatchlistStore(data_dir)
    return _STORE


def get_store() -> WatchlistStore:
    """Get the initialized singleton. Raises if init_store() wasn't called."""
    if _STORE is None:
        raise RuntimeError(
            "WatchlistStore not initialized — Brain startup must call init_store(data_dir)"
        )
    return _STORE
