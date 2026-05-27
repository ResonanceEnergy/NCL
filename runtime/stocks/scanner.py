"""GOAT Academy + Johnny Bravo strategy scanners.

GOAT Academy (Felix Friends):
  Primary gate: 150-day SMA (price must be above)
  Secondary: 50-day SMA rising, RSI 40-70 (ideal 50-65), volume surge, breakout
  Risk: VIX contango filter, 5% max single position, 25% max sector
  Profit: Graduated targets at 10%/15%/25%, 1:2 risk-reward minimum

Johnny Bravo (Bill Stenzel):
  MA Stack: SMA 9 > EMA 20 > SMA 180 (all rising)
  Trend: 200-day SMA as macro filter
  Entry: candle close above SMA 9 (green candle preferred)
  Exit: Two-tier — SMA 9 breach = CAUTION, EMA 20 breach = EXIT
  GoGo Juice: VWAP crosses above EMA 20
  Squeeze: Bollinger Band contraction

Data source: yfinance (free, no API key) with optional Alpaca upgrade.
Technical indicators: computed with numpy/pandas (no ta-lib dependency).

Usage:
    scanner = StockScanner()
    quotes = await scanner.fetch_quotes(["NVDA", "AMD", "TSLA"])
    goat_results = await scanner.run_goat_scan(["NVDA", "AMD", "TSLA"])
    bravo_results = await scanner.run_bravo_scan(["NVDA", "AMD", "TSLA"])
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


log = logging.getLogger("ncl.stocks.scanner")

# Thread pool for blocking yfinance calls
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="stock-data")

# VIX cache — refreshed every 15 minutes
_vix_cache: Dict[str, Any] = {"value": None, "ts": None}


# ── Technical Indicator Helpers ────────────────────────────────────────────


def sma(prices: np.ndarray, period: int) -> np.ndarray:
    """Simple Moving Average."""
    if len(prices) < period:
        return np.full_like(prices, np.nan)
    kernel = np.ones(period) / period
    result = np.convolve(prices, kernel, mode="full")[: len(prices)]
    result[: period - 1] = np.nan
    return result


def ema(prices: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average."""
    if len(prices) < period:
        return np.full_like(prices, np.nan)
    result = np.empty_like(prices)
    result[:] = np.nan
    # Seed with SMA
    result[period - 1] = np.mean(prices[:period])
    multiplier = 2.0 / (period + 1)
    for i in range(period, len(prices)):
        result[i] = prices[i] * multiplier + result[i - 1] * (1 - multiplier)
    return result


def rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index (Wilder's smoothing)."""
    if len(prices) < period + 1:
        return np.full_like(prices, np.nan)
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    result = np.full(len(prices), np.nan)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100.0 - (100.0 / (1.0 + rs))

    return result


def bollinger_bands(
    prices: np.ndarray, period: int = 20, num_std: float = 2.0
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (upper, middle, lower) Bollinger Bands."""
    middle = sma(prices, period)
    std = np.full_like(prices, np.nan)
    for i in range(period - 1, len(prices)):
        std[i] = np.std(prices[i - period + 1 : i + 1], ddof=0)
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def vwap(prices: np.ndarray, volumes: np.ndarray) -> np.ndarray:
    """Volume-Weighted Average Price (cumulative, intraday-style reset daily).
    For daily bars we compute rolling 20-period VWAP as proxy."""
    period = 20
    result = np.full_like(prices, np.nan)
    for i in range(period - 1, len(prices)):
        window_p = prices[i - period + 1 : i + 1]
        window_v = volumes[i - period + 1 : i + 1]
        total_vol = np.sum(window_v)
        if total_vol > 0:
            result[i] = np.sum(window_p * window_v) / total_vol
        else:
            result[i] = window_p[-1]
    return result


def is_rising(ma_values: np.ndarray, lookback: int = 5) -> bool:
    """Check if the last `lookback` MA values are generally rising."""
    recent = ma_values[-lookback:]
    recent = recent[~np.isnan(recent)]
    if len(recent) < 3:
        return False
    # Rising = positive slope over the window
    x = np.arange(len(recent))
    slope = np.polyfit(x, recent, 1)[0]
    return slope > 0


def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Average True Range — used for stop-loss placement and position sizing."""
    if len(closes) < period + 1:
        return np.full_like(closes, np.nan)
    tr = np.empty(len(closes))
    tr[0] = highs[0] - lows[0]
    for i in range(1, len(closes)):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    result = np.full_like(closes, np.nan)
    result[period] = np.mean(tr[1 : period + 1])
    for i in range(period + 1, len(closes)):
        result[i] = (result[i - 1] * (period - 1) + tr[i]) / period
    return result


def find_recent_support(lows: np.ndarray, lookback: int = 20) -> float:
    """Find recent support level from the lowest low in the lookback period."""
    recent = lows[-lookback:]
    recent = recent[~np.isnan(recent)]
    if len(recent) == 0:
        return 0.0
    return float(np.min(recent))


def _fetch_vix() -> Optional[float]:
    """Fetch current VIX value. Cached for 15 minutes."""
    now = datetime.utcnow()
    if (
        _vix_cache["value"] is not None
        and _vix_cache["ts"] is not None
        and now - _vix_cache["ts"] < timedelta(minutes=15)
    ):
        return _vix_cache["value"]
    try:
        import yfinance as yf

        vix = yf.Ticker("^VIX")
        hist = vix.history(period="5d")
        if hist.empty:
            return _vix_cache.get("value")
        val = float(hist["Close"].iloc[-1])
        _vix_cache["value"] = val
        _vix_cache["ts"] = now
        log.debug("VIX fetched: %.2f", val)
        return val
    except Exception as e:
        log.debug("VIX fetch failed: %s", e)
        return _vix_cache.get("value")


def vix_risk_level(vix_value: Optional[float]) -> str:
    """Classify VIX into risk levels.

    GOAT Academy approach:
    - VIX < 15: Low vol, risk-on → full positions
    - VIX 15-20: Normal → standard positions
    - VIX 20-30: Elevated → reduce position sizes by 50%
    - VIX > 30: High fear → defensive, reduce by 75%
    """
    if vix_value is None:
        return "unknown"
    if vix_value < 15:
        return "low"  # risk-on
    if vix_value < 20:
        return "normal"  # standard
    if vix_value < 30:
        return "elevated"  # reduce exposure
    return "high"  # defensive


def position_size_modifier(vix_level: str) -> float:
    """Return position size multiplier based on VIX risk level."""
    return {"low": 1.0, "normal": 1.0, "elevated": 0.5, "high": 0.25}.get(vix_level, 1.0)


# ── Data Fetching ──────────────────────────────────────────────────────────


def _fetch_yfinance_batch(tickers: List[str], period: str = "6mo") -> Dict[str, Any]:
    """Blocking call — runs in thread pool. Returns dict of ticker → DataFrame."""
    try:
        import yfinance as yf
    except ImportError:
        log.error("yfinance not installed — run: pip install yfinance")
        return {}

    results = {}
    # yfinance supports batch downloads
    try:
        data = yf.download(
            tickers=" ".join(tickers),
            period=period,
            group_by="ticker",
            auto_adjust=True,
            threads=True,
            progress=False,
        )
        if data.empty:
            log.warning("yfinance returned empty DataFrame for %s", tickers)
            return {}

        if len(tickers) == 1:
            # Single ticker — still grouped by ticker with MultiIndex columns
            # Extract the ticker's sub-DataFrame to get flat column names
            try:
                results[tickers[0]] = data[tickers[0]].dropna(how="all")
            except (KeyError, TypeError):
                results[tickers[0]] = data
        else:
            for ticker in tickers:
                try:
                    ticker_data = data[ticker].dropna(how="all")
                    if not ticker_data.empty:
                        results[ticker] = ticker_data
                except (KeyError, TypeError):
                    log.debug("No data for %s", ticker)
                    continue
    except Exception as e:
        log.error("yfinance batch download failed: %s", e)
        # Fallback: fetch one by one
        for ticker in tickers:
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period=period, auto_adjust=True)
                if not hist.empty:
                    results[ticker] = hist
            except Exception as ex:
                log.debug("Failed to fetch %s: %s", ticker, ex)

    return results


class StockScanner:
    """Stateless scanner — create per request or cache for a few minutes."""

    def __init__(
        self,
        alpaca_key: Optional[str] = None,
        alpaca_secret: Optional[str] = None,
        async_writer=None,
        portfolio_manager=None,
    ):
        self.alpaca_key = alpaca_key
        self.alpaca_secret = alpaca_secret
        # Cache keyed by period to avoid short-period data poisoning scanner lookbacks
        self._cache: Dict[str, Dict[str, Any]] = {}  # {period: {ticker: DataFrame}}
        self._cache_ts: Dict[str, datetime] = {}  # {period: timestamp}
        self._cache_ttl = timedelta(minutes=5)
        # 2026-05-22 EOD: injected by Brain lifespan for persistence + dedup
        self.async_writer = async_writer
        self.portfolio_manager = portfolio_manager

    def attach_async_writer(self, async_writer) -> None:
        """Late-bind the AsyncMemoryWriter (Brain may finish wiring after StockScanner __init__)."""
        self.async_writer = async_writer

    def attach_portfolio_manager(self, pm) -> None:
        """Late-bind the PortfolioManager singleton for portfolio dedup."""
        self.portfolio_manager = pm

    def _cache_valid(self, period: str) -> bool:
        ts = self._cache_ts.get(period)
        return (
            ts is not None
            and datetime.utcnow() - ts < self._cache_ttl
            and bool(self._cache.get(period))
        )

    async def fetch_historical(self, tickers: List[str], period: str = "6mo") -> Dict[str, Any]:
        """Fetch historical OHLCV data for tickers. Returns {ticker: DataFrame}."""
        period_cache = self._cache.get(period, {})
        if self._cache_valid(period):
            missing = [t for t in tickers if t not in period_cache]
            if not missing:
                return {t: period_cache[t] for t in tickers if t in period_cache}
        else:
            missing = tickers

        loop = asyncio.get_event_loop()

        # Batch into groups of 20 to avoid URL length limits
        batch_size = 20
        all_results = {}
        for i in range(0, len(missing), batch_size):
            batch = missing[i : i + batch_size]
            batch_results = await loop.run_in_executor(
                _executor, _fetch_yfinance_batch, batch, period
            )
            all_results.update(batch_results)

        if period not in self._cache:
            self._cache[period] = {}
        self._cache[period].update(all_results)
        self._cache_ts[period] = datetime.utcnow()

        period_cache = self._cache[period]
        return {t: period_cache[t] for t in tickers if t in period_cache}

    # ── Enrichment + Dedup pipeline (Features 2, 4, 5, 6) ─────────────

    async def _enrich_and_filter(
        self,
        results: List[Dict[str, Any]],
        scanner_name: str,
        *,
        include_held: bool = False,
        include_earnings_risk: bool = False,
        run_persistence: bool = True,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Apply Features 2/4/5/6 to a raw scan result list.

        Order matters — cheap filters first so we don't pay for UW/yf round-trips
        on doomed candidates.

        1. Portfolio dedup (Feature 2) — annotate held_in_portfolio, drop if not include_held
        2. Earnings filter (Feature 5) — drop if days_to_earnings <= 7
        3. Liquidity gate (Feature 4) — drop if ADV/mcap/option-OI under threshold
        4. IVR gate (Feature 6A) — GOAT rejects >70, BRAVO rejects <20
        5. Flow confirmation (Feature 6B) — annotate, never drop
        6. Dark pool support (Feature 6C) — refine stop_loss
        7. Persist to JSONL + memory enqueue (Feature 1)

        Returns ``(filtered_results, _meta)``.
        """
        from . import (
            enrichments as enr,  # local import — keeps scanner.py importable without enrichments
        )
        from . import persistence as pers

        is_goat = "goat" in scanner_name
        min_adv = enr.GOAT_MIN_ADV if is_goat else enr.BRAVO_MIN_ADV

        meta: Dict[str, Any] = {
            "scanner": scanner_name,
            "raw_count": len(results),
            "filtered_held": 0,
            "filtered_earnings": 0,
            "filtered_liquidity": 0,
            "filtered_ivr": 0,
            "include_held": include_held,
            "include_earnings_risk": include_earnings_risk,
        }

        # ── Feature 2: portfolio dedup ─────────────────────────────────
        held_map: Dict[str, Dict[str, Any]] = {}
        try:
            if self.portfolio_manager is not None:
                for pos in self.portfolio_manager.get_positions(account_filter="all"):
                    sym = (pos.get("symbol") or "").upper().strip()
                    if not sym:
                        continue
                    # Bias toward the largest matching position when a symbol
                    # is split across accounts.
                    cur = held_map.get(sym)
                    if cur is None or float(pos.get("market_value", 0) or 0) > float(
                        cur.get("market_value", 0) or 0
                    ):
                        held_map[sym] = pos
        except Exception as e:
            log.debug("portfolio dedup probe failed: %s", e)

        # ── Feature 5: earnings calendar (batch) ────────────────────────
        # P19-A — pass tickers list so the yfinance fallback can fire when
        # FINNHUB_API_KEY is missing. Previously failed silently.
        # Wave 14R fix — extract from results (this fn takes `results` not
        # `tickers`; prior code referenced an undefined `tickers` var
        # and the whole scanner raised NameError on every call).
        scan_tickers = sorted({
            (r.get("ticker") or "").upper().strip()
            for r in results
            if r.get("ticker")
        })
        earnings_map = await enr.get_earnings_map(tickers=scan_tickers)
        if earnings_map is None:
            meta["earnings_source"] = "unavailable"
        else:
            meta["earnings_source"] = "finnhub"

        # ── Feature 6B: load flow map once ─────────────────────────────
        try:
            flow_map = await enr.get_flow_map()
        except Exception as e:
            log.debug("flow map load failed: %s", e)
            flow_map = {}

        out: List[Dict[str, Any]] = []
        for row in results:
            ticker = (row.get("ticker") or "").upper().strip()
            if not ticker:
                continue
            row = dict(row)  # never mutate caller's dict

            # 2: portfolio dedup
            pos = held_map.get(ticker)
            if pos is not None:
                row["held_in_portfolio"] = True
                row["position_value_usd"] = float(pos.get("market_value") or 0)
                row["position_account"] = pos.get("account_id") or pos.get("broker", "")
                if not include_held:
                    meta["filtered_held"] += 1
                    continue
            else:
                row["held_in_portfolio"] = False

            # 5: earnings filter
            edate = (earnings_map or {}).get(ticker)
            d2e = enr.days_until(edate)
            row["days_to_earnings"] = d2e
            if d2e is not None and d2e <= enr.EARNINGS_HORIZON_DAYS and not include_earnings_risk:
                meta["filtered_earnings"] += 1
                continue

            # 4: liquidity — ADV-20 already computed by the scanner from its
            # own OHLCV (avg_daily_volume field). yfinance probe still needed
            # for market cap + option open interest.
            adv = row.get("avg_daily_volume")
            try:
                adv_f = float(adv) if adv is not None else None
            except (TypeError, ValueError):
                adv_f = None
            liq = await enr.check_liquidity(
                ticker,
                avg_daily_volume=adv_f,
                min_adv=min_adv,
                require_options_oi=True,
            )
            row.update(liq.to_dict())
            if not liq.pass_liquidity:
                meta["filtered_liquidity"] += 1
                continue

            # 6A: IVR
            ivr = await enr.compute_ivr(ticker)
            row["ivr"] = round(float(ivr), 1) if ivr is not None else None
            # P19-A — tag the gate status so consumers know whether IVR was
            # actually evaluated (False) or silently passed through (True
            # because data was missing). Was previously silently
            # bypassing — UI showed "rejects IVR >70" but never enforced.
            row["ivr_status"] = "available" if ivr is not None else "unavailable"
            if ivr is not None:
                if is_goat and ivr > enr.GOAT_IVR_MAX:
                    meta["filtered_ivr"] += 1
                    continue
                if (not is_goat) and ivr < enr.BRAVO_IVR_MIN:
                    meta["filtered_ivr"] += 1
                    continue

            # 6B: options flow confirmation
            # Bullish-setup detection: GOAT is always long-bias; BRAVO entry signals are bullish.
            bullish = (
                True if is_goat else bool(row.get("entry_signal") and not row.get("exit_signal"))
            )
            flow = enr.summarize_flow(ticker, flow_map, bullish_setup=bullish)
            row.update(flow.to_dict())

            # 6C: dark pool support (refines stop_loss if found)
            try:
                dp = await enr.fetch_dark_pool_support(ticker, float(row.get("price") or 0))
                row.update(dp.to_dict())
                if dp.price is not None and dp.price > 0:
                    # Move stop just BELOW the dark pool level (0.5% below the print).
                    # Only override if the new stop is tighter than ATR stop *and* still
                    # leaves a sane risk distance.
                    refined = round(dp.price * 0.995, 2)
                    cur_stop = float(row.get("stop_loss") or 0)
                    price = float(row.get("price") or 0)
                    if refined > 0 and refined < price and refined > cur_stop:
                        row["stop_loss_atr_only"] = cur_stop
                        row["stop_loss"] = refined
                        # Recompute risk_reward (GOAT-only field; BRAVO has risk_pct)
                        if is_goat and row.get("target_1"):
                            risk = price - refined
                            reward = float(row["target_1"]) - price
                            row["risk_reward"] = round(reward / risk, 2) if risk > 0 else 0.0
            except Exception as e:
                log.debug("dark pool refine failed for %s: %s", ticker, e)
                row.setdefault("dark_pool_support", None)
                row.setdefault("dark_pool_volume", None)
                row.setdefault("dark_pool_date", None)

            out.append(row)

        # ── Feature 1: persist + memory enqueue ────────────────────────
        if run_persistence and out:
            try:
                persist_meta = await pers.persist_and_enqueue(
                    scanner_name,
                    out,
                    async_writer=self.async_writer,
                )
                meta.update(persist_meta)
            except Exception as e:
                log.warning("scanner persistence failed (%s): %s", scanner_name, e)
                meta["persistence_error"] = str(e)
        else:
            meta["jsonl_path"] = None
            meta["persisted"] = 0
            meta["enqueued_memory"] = 0

        meta["returned_count"] = len(out)

        # ── Wave 14S: auto-emit high-score results to trade_idea_tracker ──
        # GOAT scores >= NCL_SCANNER_AUTO_EMIT_MIN_GOAT (default 80)
        # or BRAVO scores >= NCL_SCANNER_AUTO_EMIT_MIN_BRAVO (default 75)
        # become trade_ideas that flow through the same auto-trader gate
        # chain as quant/brief/scout ideas. Idempotent per ticker per day
        # (the tracker's emission dedup handles repeat triggers).
        try:
            import os as _os
            auto_emit_enabled = _os.getenv(
                "NCL_SCANNER_AUTO_EMIT_ENABLED", "1",
            ) not in ("0", "false", "False")
            if auto_emit_enabled and out:
                min_goat = float(_os.getenv("NCL_SCANNER_AUTO_EMIT_MIN_GOAT", "80"))
                min_bravo = float(_os.getenv("NCL_SCANNER_AUTO_EMIT_MIN_BRAVO", "75"))
                emit_threshold = min_goat if is_goat else min_bravo
                score_key = "goat_score" if is_goat else "bravo_score"
                strategy_tag = "goat_trend" if is_goat else "bravo_swing"
                from runtime.portfolio.trade_idea_tracker import (
                    get_trade_idea_tracker,
                )
                tracker = await get_trade_idea_tracker()
                emitted_count = 0
                emitted_ids: list[str] = []
                for row in out:
                    score = float(row.get(score_key, 0) or 0)
                    if score < emit_threshold:
                        continue
                    # Skip rows we just dropped because they're already held
                    if row.get("held_in_portfolio") and not include_held:
                        continue
                    try:
                        entry = float(row.get("price") or 0)
                        stop = float(row.get("stop_loss") or 0)
                        target = float(row.get("target_1") or row.get("target") or 0)
                        if not (entry > 0 and stop > 0 and target > 0):
                            continue
                        R_per_share = abs(entry - stop)
                        if R_per_share <= 0:
                            continue
                        rec = await tracker.record_emission(
                            source=scanner_name,
                            strategy=strategy_tag,
                            ticker=row.get("ticker"),
                            direction="long",
                            entry_price=entry,
                            stop_price=stop,
                            target_price=target,
                            R_per_share=round(R_per_share, 4),
                            stop_type="atr_2x" if is_goat else "ma_break",
                            stop_basis=(
                                "GOAT: 2x ATR below entry"
                                if is_goat
                                else "BRAVO: 1.5x ATR below SMA-9"
                            ),
                            target_basis=(
                                f"GOAT target_1 +{round((target/entry - 1) * 100, 1)}%"
                                if is_goat
                                else "BRAVO target = first prior swing high"
                            ),
                            thesis=(
                                f"{strategy_tag.upper()} score={score:.0f} "
                                f"sector={row.get('sector', '?')}"
                            ),
                            metadata={
                                "scanner": scanner_name,
                                "score": score,
                                "score_key": score_key,
                                "rotation_aligned": row.get("rotation_aligned"),
                                "sector_etf": row.get("sector_etf"),
                                "wave": "14S-S1",
                            },
                        )
                        tid = rec.get("trade_idea_id") if rec else None
                        if tid:
                            emitted_count += 1
                            emitted_ids.append(tid)
                    except Exception as e:
                        log.debug("auto-emit %s failed: %s", row.get("ticker"), e)
                meta["auto_emitted_count"] = emitted_count
                meta["auto_emitted_ids"] = emitted_ids
                meta["auto_emit_threshold"] = emit_threshold
                if emitted_count:
                    log.info(
                        "[SCANNER-EMIT] %s sent %d high-score ideas to auto-trader "
                        "(threshold=%s)",
                        scanner_name, emitted_count, emit_threshold,
                    )
        except Exception as e:
            log.warning("scanner auto-emit pass failed (%s): %s", scanner_name, e)
            meta["auto_emit_error"] = str(e)

        return out, meta

    async def fetch_quotes(self, tickers: List[str]) -> List[Dict[str, Any]]:
        """Fetch current quotes for all tickers. Returns list of quote dicts."""
        data = await self.fetch_historical(tickers, period="5d")
        quotes = []
        for ticker in tickers:
            df = data.get(ticker)
            if df is None or df.empty:
                continue
            try:
                last = df.iloc[-1]
                prev = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
                close = float(last["Close"])
                prev_close = float(prev["Close"])
                change = close - prev_close
                change_pct = (change / prev_close * 100) if prev_close != 0 else 0
                vol = int(last.get("Volume", 0))
                quotes.append(
                    {
                        "ticker": ticker,
                        "price": round(close, 2),
                        "change": round(change, 2),
                        "change_pct": round(change_pct, 2),
                        "volume": vol,
                    }
                )
            except (IndexError, KeyError, TypeError) as e:
                log.debug("Quote parse error for %s: %s", ticker, e)
        return quotes

    # ── GOAT Scanner ───────────────────────────────────────────────────────

    async def run_goat_scan(self, tickers: List[str]) -> List[Dict[str, Any]]:
        """Run GOAT Academy strategy scanner (aligned with Felix Friends methodology).

        PRIMARY GATE (must pass or score caps at 30):
        1. Price > 150-day SMA — the trend filter. This is THE rule.

        SECONDARY RULES:
        2. Price > 50-day SMA — intermediate trend confirmation
        3. 50-day SMA is rising (positive slope over 5 days)
        4. RSI 40-70 (momentum sweet spot, ideal bonus 50-65)
        5. Volume > 1.5× 20-day average (volume surge confirmation)
        6. Price > 20-day high (breakout above resistance)

        RISK MANAGEMENT (new):
        - VIX risk filter: reduces position sizing at elevated volatility
        - ATR-based stop loss: 2× ATR below entry
        - Graduated profit targets: +10%, +15%, +25%
        - Position sizing: 5% max single, adjusted by VIX level
        - Risk-reward: minimum 1:2 (stop to first target)
        """
        data = await self.fetch_historical(tickers, period="1y")

        # Fetch VIX for risk overlay
        loop = asyncio.get_event_loop()
        vix_value = await loop.run_in_executor(_executor, _fetch_vix)
        vix_level = vix_risk_level(vix_value)
        pos_modifier = position_size_modifier(vix_level)

        results = []

        for ticker in tickers:
            df = data.get(ticker)
            if df is None or len(df) < 150:
                continue

            try:
                closes = df["Close"].values.astype(float)
                highs = df["High"].values.astype(float)
                lows = df["Low"].values.astype(float)
                volumes = df["Volume"].values.astype(float)
                current_price = closes[-1]
                prev_price = closes[-2] if len(closes) >= 2 else closes[-1]

                # Compute indicators
                sma50 = sma(closes, 50)
                sma150 = sma(closes, 150)
                rsi_values = rsi(closes, 14)
                atr_values = atr(highs, lows, closes, 14)

                # Current values
                current_sma50 = sma50[-1]
                current_sma150 = sma150[-1]
                current_rsi = rsi_values[-1]
                current_atr = atr_values[-1] if not np.isnan(atr_values[-1]) else 0.0

                # Volume analysis
                vol_20_avg = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes)
                current_vol = volumes[-1]
                vol_ratio = current_vol / vol_20_avg if vol_20_avg > 0 else 1.0

                # 20-day high (excluding today for breakout detection)
                high_20 = np.max(highs[-21:-1]) if len(df) >= 21 else np.max(highs[:-1])

                # ── 6 Rules ──
                # Rule 1: PRIMARY GATE — 150-day SMA
                rule_above_sma150 = not np.isnan(current_sma150) and current_price > current_sma150

                # Rule 2-6: Secondary
                rule_above_sma50 = not np.isnan(current_sma50) and current_price > current_sma50
                rule_sma50_rising = is_rising(sma50, lookback=5)
                rule_rsi_zone = not np.isnan(current_rsi) and 40 <= current_rsi <= 70
                rule_vol_surge = vol_ratio >= 1.5
                rule_breakout = current_price > high_20

                rules_hit = sum(
                    [
                        rule_above_sma150,
                        rule_above_sma50,
                        rule_sma50_rising,
                        rule_rsi_zone,
                        rule_vol_surge,
                        rule_breakout,
                    ]
                )

                # ── GOAT Score (weighted, 150 SMA is gate) ──
                score = 0

                if rule_above_sma150:
                    score += 25  # PRIMARY gate — biggest weight
                if rule_above_sma50:
                    score += 15  # Intermediate trend
                if rule_sma50_rising:
                    score += 15  # Trend acceleration
                if rule_rsi_zone:
                    score += 15  # Momentum sweet spot
                if rule_vol_surge:
                    score += 15  # Volume confirmation
                if rule_breakout:
                    score += 15  # Catalyst / resistance clear

                # Bonus points for strength
                if not np.isnan(current_rsi) and 50 <= current_rsi <= 65:
                    score = min(100, score + 5)  # Ideal RSI range bonus
                if vol_ratio >= 2.0:
                    score = min(100, score + 5)  # Strong volume bonus

                # GATE PENALTY: if below 150 SMA, cap score at 30
                # GOAT Academy: "The 150-day is your north star. If price is below it, you're fighting the trend."  # noqa: E501
                if not rule_above_sma150:
                    score = min(score, 30)

                # ── Risk Management ──
                # Stop loss: 2× ATR below current price
                stop_loss = (
                    round(float(current_price - 2 * current_atr), 2) if current_atr > 0 else 0.0
                )

                # Audit 2026-05-22 P0: Prior code used fixed +10/+15/+25%
                # targets which produced R:R < 1.0 on every high-vol name
                # (where 2×ATR stop > 5% drop). Stated strategy is 1:2
                # minimum — ATR-based targets keep R:R ≥ 1.5R / 2.5R / 3.5R.
                if current_atr > 0:
                    target_1 = round(float(current_price + 3 * current_atr), 2)
                    target_2 = round(float(current_price + 5 * current_atr), 2)
                    target_3 = round(float(current_price + 7 * current_atr), 2)
                else:
                    # Defensive fallback if ATR unavailable
                    target_1 = round(float(current_price * 1.10), 2)
                    target_2 = round(float(current_price * 1.15), 2)
                    target_3 = round(float(current_price * 1.25), 2)

                # Risk-reward ratio (stop to first target)
                risk = current_price - stop_loss if stop_loss > 0 else current_atr * 2
                reward = target_1 - current_price
                risk_reward = round(float(reward / risk), 2) if risk > 0 else 0.0

                # Position size: 5% of portfolio, adjusted by VIX
                base_position_pct = 5.0
                adjusted_position_pct = round(base_position_pct * pos_modifier, 1)

                # Support level for context
                support = round(float(find_recent_support(lows, 20)), 2)

                change_pct = (
                    ((current_price - prev_price) / prev_price * 100) if prev_price != 0 else 0
                )

                results.append(
                    {
                        "ticker": ticker,
                        "price": round(float(current_price), 2),
                        "change_pct": round(float(change_pct), 2),
                        "goat_score": int(min(100, score)),
                        # Rule flags
                        "above_sma50": bool(rule_above_sma50),
                        "above_sma150": bool(rule_above_sma150),
                        "sma50_rising": bool(rule_sma50_rising),
                        "rsi_in_zone": bool(rule_rsi_zone),
                        "rsi": round(float(current_rsi), 1) if not np.isnan(current_rsi) else 50.0,
                        "volume_surge": bool(rule_vol_surge),
                        "volume_ratio": round(float(vol_ratio), 2),
                        "avg_daily_volume": int(vol_20_avg) if vol_20_avg > 0 else 0,
                        "breakout": bool(rule_breakout),
                        "rules_hit": int(rules_hit),
                        # Risk management (new)
                        "stop_loss": float(stop_loss),
                        "target_1": float(target_1),
                        "target_2": float(target_2),
                        "target_3": float(target_3),
                        "risk_reward": float(risk_reward),
                        "atr": round(float(current_atr), 2),
                        "position_size_pct": float(adjusted_position_pct),
                        "support": float(support),
                        # VIX overlay
                        "vix": round(float(vix_value), 2) if vix_value else None,
                        "vix_risk": vix_level,
                    }
                )

            except Exception as e:
                log.warning("GOAT scan error for %s: %s", ticker, e)
                continue

        # Sort by score descending
        results.sort(key=lambda x: x["goat_score"], reverse=True)
        return results

    # ── Bravo Swing Scanner ────────────────────────────────────────────────

    async def run_bravo_scan(self, tickers: List[str]) -> List[Dict[str, Any]]:
        """Run Johnny Bravo / Bill Stenzel swing scanner (fully aligned).

        Core System:
        - MA Stack: SMA 9 > EMA 20 > SMA 180 (bullish alignment)
        - Macro Filter: Price > 200-day SMA (added — long-term trend)
        - All MAs sloping up
        - Entry: candle close above SMA 9 (green candle preferred over red)
        - Exit: Two-tier system:
            * SMA 9 breach = CAUTION (warning, not immediate sell)
            * EMA 20 breach = EXIT (hard sell signal)
            * Red candle below SMA 9 = stronger sell than green candle below
        - GoGo Juice: VWAP crosses above EMA 20
        - Bollinger Squeeze: bands contracting (pending breakout)
        - Position sizing: 1-2% risk per trade based on ATR stop
        """
        data = await self.fetch_historical(tickers, period="1y")
        results = []

        for ticker in tickers:
            df = data.get(ticker)
            if df is None or len(df) < 200:  # Need 200 days for SMA 200
                continue

            try:
                closes = df["Close"].values.astype(float)
                opens = df["Open"].values.astype(float)
                highs = df["High"].values.astype(float)
                lows = df["Low"].values.astype(float)
                volumes = df["Volume"].values.astype(float)
                current_price = closes[-1]
                current_open = opens[-1]
                prev_price = closes[-2] if len(closes) >= 2 else closes[-1]

                # Compute MAs
                sma9 = sma(closes, 9)
                ema20 = ema(closes, 20)
                sma180 = sma(closes, 180)
                sma200 = sma(closes, 200)  # NEW: macro trend filter
                rsi_values = rsi(closes, 14)
                atr_values = atr(highs, lows, closes, 14)

                # VWAP (rolling 20-period)
                vwap_values = vwap(closes, volumes)

                # Bollinger Bands
                bb_upper, bb_middle, bb_lower = bollinger_bands(closes, 20, 2.0)

                # Current values
                current_sma9 = sma9[-1]
                current_ema20 = ema20[-1]
                current_sma180 = sma180[-1]
                current_sma200 = sma200[-1]
                current_rsi = rsi_values[-1]
                current_vwap = vwap_values[-1]
                current_atr = atr_values[-1] if not np.isnan(atr_values[-1]) else 0.0

                # Previous VWAP + EMA for crossover detection
                prev_vwap = vwap_values[-2] if len(vwap_values) >= 2 else np.nan
                prev_ema20 = ema20[-2] if len(ema20) >= 2 else np.nan

                # Check NaN on essential MAs
                any_nan = any(np.isnan(v) for v in [current_sma9, current_ema20, current_sma180])
                if any_nan:
                    continue

                # ── Candle Color Analysis (new) ──
                # Green candle = close > open, Red candle = close < open
                is_green_candle = current_price >= current_open

                # ── Bravo Rules ──

                # Macro trend: price above 200 SMA (new)
                above_sma200 = not np.isnan(current_sma200) and current_price > current_sma200

                # MA Alignment: SMA 9 > EMA 20 > SMA 180
                ma_aligned = current_sma9 > current_ema20 > current_sma180

                # All MAs sloping up
                sma9_rising = is_rising(sma9, 5)
                ema20_rising = is_rising(ema20, 5)
                sma180_rising = is_rising(sma180, 10)
                all_sloping_up = sma9_rising and ema20_rising and sma180_rising

                # Entry: last bar closed above SMA 9
                entry_signal = current_price > current_sma9

                # Two-tier exit system (new):
                # Tier 1: price below SMA 9 = CAUTION (warning)
                # Tier 2: price below EMA 20 = EXIT (hard sell)
                below_sma9 = current_price < current_sma9
                below_ema20 = current_price < current_ema20

                # Candle color nuance for exits:
                # Red candle below SMA 9 = stronger sell signal
                # Green candle below SMA 9 = just caution, might bounce
                caution_signal = below_sma9 and not below_ema20
                exit_signal = below_ema20  # Hard exit

                # GoGo Juice: VWAP crossed above EMA 20 recently
                gogo_juice = False
                if (
                    not np.isnan(current_vwap)
                    and not np.isnan(prev_vwap)
                    and not np.isnan(prev_ema20)
                ):
                    gogo_juice = prev_vwap <= prev_ema20 and current_vwap > current_ema20
                    # Also check if VWAP is above EMA 20 and was recently below (within 3 bars)
                    if not gogo_juice and current_vwap > current_ema20:
                        for lookback_i in range(2, min(5, len(vwap_values))):
                            v = vwap_values[-lookback_i]
                            e = ema20[-lookback_i]
                            if not np.isnan(v) and not np.isnan(e) and v <= e:
                                gogo_juice = True
                                break

                # Bollinger Squeeze: bandwidth contracting
                bb_width_current = (
                    (bb_upper[-1] - bb_lower[-1]) / bb_middle[-1]
                    if not np.isnan(bb_middle[-1]) and bb_middle[-1] != 0
                    else 0
                )
                bb_width_prev = (
                    np.nanmean(
                        [
                            (bb_upper[i] - bb_lower[i]) / bb_middle[i]
                            for i in range(-20, -1)
                            if not np.isnan(bb_middle[i]) and bb_middle[i] != 0
                        ]
                    )
                    if len(closes) >= 40
                    else bb_width_current
                )
                bollinger_squeeze = bb_width_current < bb_width_prev * 0.8  # 20% contraction

                # ── Bravo Score ──
                score = 0
                if ma_aligned:
                    score += 22
                if all_sloping_up:
                    score += 18
                if above_sma200:
                    score += 12  # NEW: macro trend bonus
                if entry_signal and not exit_signal and not caution_signal:
                    score += 18
                elif entry_signal and not exit_signal:
                    score += 10  # Reduced if caution
                if gogo_juice:
                    score += 15
                if bollinger_squeeze:
                    score += 8
                if not np.isnan(current_rsi) and 40 <= current_rsi <= 70:
                    score += 7

                # Penalties
                if caution_signal:
                    # Red candle below SMA 9 = bigger penalty
                    if not is_green_candle:
                        score = max(0, score - 25)  # Red candle: strong warning
                    else:
                        score = max(0, score - 15)  # Green candle: milder
                if exit_signal:
                    score = max(0, score - 35)
                if not above_sma200:
                    score = min(score, 50)  # Cap if below 200 SMA

                # ── Risk Management ──
                # Stop loss: 1.5× ATR below SMA 9 (Bravo uses tighter stops)
                stop_loss = (
                    round(float(current_sma9 - 1.5 * current_atr), 2) if current_atr > 0 else 0.0
                )

                # Risk per trade: 1-2% of portfolio
                risk_per_share = current_price - stop_loss if stop_loss > 0 else current_atr * 1.5
                risk_pct = (
                    round(float(risk_per_share / current_price * 100), 2)
                    if current_price > 0
                    else 0.0
                )

                change_pct = (
                    ((current_price - prev_price) / prev_price * 100) if prev_price != 0 else 0
                )

                # Signal label with two-tier system
                signal_label = self._bravo_signal_label(
                    entry=bool(entry_signal),
                    exit_=bool(exit_signal),
                    caution=bool(caution_signal),
                    gogo=bool(gogo_juice),
                    aligned=bool(ma_aligned),
                    sloping=bool(all_sloping_up),
                    green_candle=bool(is_green_candle),
                )

                results.append(
                    {
                        "ticker": ticker,
                        "price": round(float(current_price), 2),
                        "change_pct": round(float(change_pct), 2),
                        "bravo_score": int(min(100, score)),
                        "sma9": round(float(current_sma9), 2),
                        "ema20": round(float(current_ema20), 2),
                        "sma180": round(float(current_sma180), 2),
                        "sma200": round(float(current_sma200), 2)
                        if not np.isnan(current_sma200)
                        else None,
                        "ma_aligned": bool(ma_aligned),
                        "all_sloping_up": bool(all_sloping_up),
                        "above_sma200": bool(above_sma200),
                        "entry_signal": bool(entry_signal),
                        "exit_signal": bool(exit_signal),
                        "caution_signal": bool(caution_signal),
                        "is_green_candle": bool(is_green_candle),
                        "gogo_juice": bool(gogo_juice),
                        "bollinger_squeeze": bool(bollinger_squeeze),
                        "rsi": round(float(current_rsi), 1) if not np.isnan(current_rsi) else 50.0,
                        "signal_label": signal_label,
                        # Risk management (new)
                        "stop_loss": float(stop_loss),
                        "risk_pct": float(risk_pct),
                        "atr": round(float(current_atr), 2),
                        "avg_daily_volume": int(np.mean(volumes[-20:]))
                        if len(volumes) >= 20
                        else 0,
                    }
                )

            except Exception as e:
                log.warning("Bravo scan error for %s: %s", ticker, e)
                continue

        results.sort(key=lambda x: x["bravo_score"], reverse=True)
        return results

    # ── Enriched wrappers (Features 1, 2, 4, 5, 6) ─────────────────────

    async def run_goat_scan_enriched(
        self,
        tickers: List[str],
        *,
        include_held: bool = False,
        include_earnings_risk: bool = False,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """GOAT scan + portfolio dedup + earnings + liquidity + IVR + flow + dark pool + persist."""
        raw = await self.run_goat_scan(tickers)
        return await self._enrich_and_filter(
            raw,
            "scanner:goat",
            include_held=include_held,
            include_earnings_risk=include_earnings_risk,
        )

    async def run_bravo_scan_enriched(
        self,
        tickers: List[str],
        *,
        include_held: bool = False,
        include_earnings_risk: bool = False,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """BRAVO scan + portfolio dedup + earnings + liquidity + IVR + flow + dark pool + persist."""  # noqa: E501
        raw = await self.run_bravo_scan(tickers)
        return await self._enrich_and_filter(
            raw,
            "scanner:bravo",
            include_held=include_held,
            include_earnings_risk=include_earnings_risk,
        )

    @staticmethod
    def _bravo_signal_label(
        entry: bool,
        exit_: bool,
        caution: bool,
        gogo: bool,
        aligned: bool,
        sloping: bool,
        green_candle: bool,
    ) -> str:
        """Two-tier signal labeling with candle color nuance."""
        if exit_:
            return "EXIT"
        if caution:
            # Below SMA 9 but above EMA 20
            if not green_candle:
                return "SELL"  # Red candle below SMA 9 = sell
            return "CAUTION"  # Green candle below SMA 9 = might bounce
        if entry and gogo:
            return "GOGO BUY"
        if entry:
            return "BUY"
        if aligned and sloping:
            return "SETUP"
        return "WATCH"
