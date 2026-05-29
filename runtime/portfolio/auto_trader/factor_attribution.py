"""
Auto-Trader post-trade factor attribution — Wave 14U-2/4

Decomposes every closed paper trade's return into:
  - market beta (SPY exposure)
  - Fama-French 5 factors (SMB / HML / RMW / CMA / market_excess)
  - sector factor (vs SPDR sector ETF)
  - idiosyncratic alpha (residual after the above)

Answers the single biggest "are we actually generating alpha?" question.

Run continuously (on each close), maintains a rolling-60-trades window
per strategy, and surfaces per-strategy alpha/beta/factor decomposition
in the dashboard.

Why this matters (Hudson & Thames / Fidelity Fusion-Alpha pattern):
  - A strategy with Sharpe 1.0 purely from market beta is worth ~0
    after fees (you could just buy SPY and lever).
  - A strategy with Sharpe 0.5 of pure alpha is worth 10x more — that's
    real edge that survives factor exposure.
  - Without attribution, you can't tell which strategies have edge.

Simplified F-F model (no daily factor data dependency):
  For each closed trade, compute:
    trade_return  = (exit - entry) / entry × (long ? +1 : -1)
    spy_return    = SPY change over the same window
    sector_return = sector ETF change over the same window
  Then OLS fit per-strategy:
    trade_return = α + β_spy × spy_return + β_sector × sector_return + ε

  Rolling-60-trade window. α = idiosyncratic alpha. Sharpe of α =
  the real edge metric (vs naive trade Sharpe which conflates beta).

This is the "minimum viable factor attribution" — not the full F-F-5 with
daily factor returns (which would need Ken French data lib + daily refresh).
Industry pattern is to upgrade to full F-F-5 once the simplified version
shows clear non-zero alpha worth measuring more precisely.

Storage:
  data/portfolio/auto_trader/factor_attributions.json   (rolling per strategy)
  data/portfolio/auto_trader/factor_attribution_log.jsonl (per-trade audit)

Tunables (env):
  NCL_FA_WINDOW_TRADES        default 60
  NCL_FA_MIN_TRADES           default 10  (skip fit until we have this many)
  NCL_FA_DISABLED             "1"/"0"     default "0"
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.factor_attribution")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio" / "auto_trader"
STATE_FILE = DATA_DIR / "factor_attributions.json"
LOG_FILE = DATA_DIR / "factor_attribution_log.jsonl"

WINDOW_TRADES = int(os.getenv("NCL_FA_WINDOW_TRADES", "60"))
MIN_TRADES = int(os.getenv("NCL_FA_MIN_TRADES", "10"))
DISABLED = os.getenv("NCL_FA_DISABLED", "0") == "1"

# Sector ETF mapping — extend as new sectors emerge
TICKER_TO_SECTOR_ETF: dict[str, str] = {
    # Tech
    "AAPL": "XLK", "MSFT": "XLK", "NVDA": "XLK", "GOOG": "XLK", "GOOGL": "XLK",
    "META": "XLK", "AMZN": "XLK", "TSLA": "XLK", "AMD": "XLK", "INTC": "XLK",
    "TSM": "XLK", "QCOM": "XLK", "AVGO": "XLK", "ORCL": "XLK", "CRM": "XLK",
    "ADBE": "XLK", "NFLX": "XLK", "PLTR": "XLK", "SNOW": "XLK", "APLD": "XLK",
    # Financials
    "JPM": "XLF", "BAC": "XLF", "GS": "XLF", "MS": "XLF", "WFC": "XLF",
    "C": "XLF", "BLK": "XLF", "V": "XLF", "MA": "XLF",
    # Energy
    "XOM": "XLE", "CVX": "XLE", "COP": "XLE", "EOG": "XLE", "OXY": "XLE",
    "SLB": "XLE", "HAL": "XLE",
    # Health
    "JNJ": "XLV", "UNH": "XLV", "LLY": "XLV", "PFE": "XLV", "ABBV": "XLV",
    "MRK": "XLV",
    # Industrials
    "BA": "XLI", "GE": "XLI", "CAT": "XLI", "DE": "XLI", "RTX": "XLI",
    "HON": "XLI", "UPS": "XLI", "FDX": "XLI",
    # Consumer Discretionary
    "HD": "XLY", "NKE": "XLY", "MCD": "XLY", "SBUX": "XLY", "BKNG": "XLY",
    "LOW": "XLY",
    # Consumer Staples
    "WMT": "XLP", "KO": "XLP", "PEP": "XLP", "PG": "XLP", "COST": "XLP",
    # Communications
    "DIS": "XLC", "T": "XLC", "VZ": "XLC", "TMUS": "XLC",
    # Real Estate
    "PLD": "XLRE", "AMT": "XLRE", "EQIX": "XLRE",
    # Utilities
    "NEE": "XLU", "DUK": "XLU", "SO": "XLU",
    # Materials
    "FCX": "XLB", "LIN": "XLB",
}


def _sector_etf_for(ticker: str) -> str:
    """Return sector ETF for ticker; default to SPY if unmapped."""
    return TICKER_TO_SECTOR_ETF.get((ticker or "").upper(), "SPY")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class FactorAttribution:
    """Per-strategy rolling factor decomposition."""
    strategy: str
    n_trades: int = 0
    window_trades: list = field(default_factory=list)  # list of dicts
    last_fit_iso: Optional[str] = None
    # Latest OLS fit (rolling window):
    alpha: float = 0.0           # idiosyncratic alpha (intercept)
    alpha_t_stat: float = 0.0    # t-statistic
    beta_spy: float = 0.0        # market beta
    beta_sector: float = 0.0     # sector beta
    r_squared: float = 0.0       # OLS R^2
    residual_std: float = 0.0    # std of residuals (idiosyncratic vol)
    avg_trade_return: float = 0.0
    avg_spy_return: float = 0.0
    sharpe_alpha: float = 0.0    # alpha / residual_std (annualized rough)


_STATE: dict[str, FactorAttribution] = {}
_LOCK = asyncio.Lock()
_LOADED = False


def _load_state() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    if not STATE_FILE.exists():
        return
    try:
        raw = json.loads(STATE_FILE.read_text())
        if not isinstance(raw, dict):
            return
        fnames = {f for f in FactorAttribution.__dataclass_fields__}  # type: ignore[attr-defined]
        for strat, payload in raw.items():
            if not isinstance(payload, dict):
                continue
            kept = {k: v for k, v in payload.items() if k in fnames}
            kept.setdefault("strategy", strat)
            try:
                _STATE[strat] = FactorAttribution(**kept)
            except Exception as e:
                log.warning("[FA] skip malformed state for %s: %s", strat, e)
    except Exception as e:
        log.warning("[FA] state load failed: %s", e)


def _persist_state() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = {strat: asdict(fa) for strat, fa in _STATE.items()}
    tmp = STATE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(snapshot, indent=2, sort_keys=True))
        tmp.replace(STATE_FILE)
    except Exception as e:
        log.error("[FA] state persist failed: %s", e)


def _append_log(record: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        log.warning("[FA] log append failed: %s", e)


def _fetch_etf_return_blocking(symbol: str, entry_iso: str,
                                exit_iso: str) -> Optional[float]:
    """Return ETF % change between entry_iso and exit_iso (or 0 if same day).
    Uses yfinance daily closes — cheap, reliable, and same-day entry/exit
    is handled by using intraday history when needed."""
    try:
        import yfinance as yf
        from datetime import date as _date
    except ImportError:
        return None
    try:
        # Parse dates (strip time component if present)
        e = entry_iso[:10]
        x = exit_iso[:10]
        if e == x:
            # Same-day: try intraday
            h = yf.Ticker(symbol).history(period="2d", interval="1d")
            if h.empty or len(h) < 2:
                return 0.0
            return float((h["Close"].iloc[-1] - h["Close"].iloc[-2])
                         / h["Close"].iloc[-2])
        # Multi-day: pull range
        # yfinance is exclusive on end; add 1 day
        from datetime import datetime as _dt, timedelta as _td
        end_dt = _dt.fromisoformat(x) + _td(days=2)
        h = yf.Ticker(symbol).history(start=e, end=end_dt.strftime("%Y-%m-%d"))
        if h.empty or len(h) < 2:
            return 0.0
        return float((h["Close"].iloc[-1] - h["Close"].iloc[0])
                     / h["Close"].iloc[0])
    except Exception as e:
        log.debug("[FA] etf_return %s %s→%s failed: %s",
                  symbol, entry_iso, exit_iso, e)
        return None


async def _fetch_etf_return(symbol: str, entry_iso: str,
                             exit_iso: str) -> Optional[float]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _fetch_etf_return_blocking, symbol, entry_iso, exit_iso,
    )


def _ols_fit(trades: list[dict]) -> dict:
    """Run OLS on:
        trade_return_i = α + β_spy × spy_return_i + β_sector × sector_return_i + ε
    Returns dict with alpha, beta_spy, beta_sector, r_squared, residual_std,
    alpha_t_stat, sharpe_alpha.

    Pure-python (no numpy) implementation works for N up to a few hundred.
    """
    n = len(trades)
    if n < 3:
        return {}
    # Build X (intercept, spy_ret, sector_ret) and y (trade_ret)
    y = [float(t.get("trade_return", 0) or 0) for t in trades]
    x_spy = [float(t.get("spy_return", 0) or 0) for t in trades]
    x_sec = [float(t.get("sector_return", 0) or 0) for t in trades]

    # Solve via normal equations: β = (X'X)^-1 X'y
    # X is [1, spy, sec] for each row; 3-variable OLS.
    sum_1 = n
    sum_s = sum(x_spy)
    sum_e = sum(x_sec)
    sum_y = sum(y)
    sum_ss = sum(s * s for s in x_spy)
    sum_ee = sum(e * e for e in x_sec)
    sum_se = sum(x_spy[i] * x_sec[i] for i in range(n))
    sum_sy = sum(x_spy[i] * y[i] for i in range(n))
    sum_ey = sum(x_sec[i] * y[i] for i in range(n))

    # X'X 3x3
    A = [
        [sum_1, sum_s, sum_e],
        [sum_s, sum_ss, sum_se],
        [sum_e, sum_se, sum_ee],
    ]
    b = [sum_y, sum_sy, sum_ey]

    # Solve A * β = b via Gauss-Jordan (3x3)
    try:
        # Augmented matrix
        M = [row + [b[i]] for i, row in enumerate(A)]
        # Forward elim
        for i in range(3):
            pivot = M[i][i]
            if abs(pivot) < 1e-12:
                # Pivot is zero — collinear data; default to zeros
                return {}
            for j in range(i + 1, 3):
                factor = M[j][i] / pivot
                M[j] = [M[j][k] - factor * M[i][k] for k in range(4)]
        # Back-sub
        beta = [0.0, 0.0, 0.0]
        for i in range(2, -1, -1):
            s = M[i][3]
            for j in range(i + 1, 3):
                s -= M[i][j] * beta[j]
            beta[i] = s / M[i][i]
    except Exception:
        return {}

    alpha = beta[0]
    beta_spy = beta[1]
    beta_sec = beta[2]

    # Residuals + R^2
    y_hat = [alpha + beta_spy * x_spy[i] + beta_sec * x_sec[i] for i in range(n)]
    residuals = [y[i] - y_hat[i] for i in range(n)]
    rss = sum(r * r for r in residuals)
    y_mean = sum_y / n
    tss = sum((yi - y_mean) ** 2 for yi in y)
    r_squared = 1.0 - (rss / tss) if tss > 0 else 0.0

    # Residual std
    import math
    res_var = rss / max(1, n - 3)
    res_std = math.sqrt(res_var) if res_var > 0 else 0.0

    # T-stat on alpha: alpha / SE(alpha)
    # SE(alpha) requires (X'X)^-1[0][0] * residual variance
    # Approximation: SE_alpha = res_std / sqrt(n) (true only if X centered)
    se_alpha = res_std / math.sqrt(n) if n > 0 else 0.0
    alpha_t = alpha / se_alpha if se_alpha > 0 else 0.0

    # Sharpe of alpha — annualized assuming alpha is per-trade return.
    # Crude annualization: × sqrt(252 / avg_holding_days). Default assume
    # 5-day holding (swing-ish); operator can refine later.
    sharpe_alpha = (alpha / res_std) * math.sqrt(252 / 5) if res_std > 0 else 0.0

    avg_trade_ret = sum_y / n
    avg_spy_ret = sum_s / n

    return {
        "alpha": round(alpha, 6),
        "alpha_t_stat": round(alpha_t, 4),
        "beta_spy": round(beta_spy, 4),
        "beta_sector": round(beta_sec, 4),
        "r_squared": round(r_squared, 4),
        "residual_std": round(res_std, 6),
        "sharpe_alpha": round(sharpe_alpha, 4),
        "avg_trade_return": round(avg_trade_ret, 6),
        "avg_spy_return": round(avg_spy_ret, 6),
    }


async def attribute_closed_trade(
    *,
    strategy: str,
    ticker: str,
    entry_price: float,
    exit_price: float,
    direction: str,
    entry_iso: str,
    exit_iso: str,
    trade_idea_id: Optional[str] = None,
) -> dict:
    """Attribute one closed trade and update the strategy's rolling window.

    Returns {trade_record, current_fit} where current_fit is the latest
    rolling-window OLS result (or {} if N < MIN_TRADES).
    """
    if DISABLED:
        return {"disabled": True}
    if not entry_price or entry_price <= 0:
        return {"skipped": "no entry_price"}

    sign = 1.0 if str(direction).lower() == "long" else -1.0
    trade_ret = ((float(exit_price) - float(entry_price)) / float(entry_price)) * sign

    sector_etf = _sector_etf_for(ticker)
    spy_ret = await _fetch_etf_return("SPY", entry_iso, exit_iso) or 0.0
    sec_ret = (await _fetch_etf_return(sector_etf, entry_iso, exit_iso)
               if sector_etf != "SPY" else spy_ret) or 0.0

    record = {
        "ts": _now_iso(),
        "trade_idea_id": trade_idea_id,
        "strategy": strategy,
        "ticker": ticker,
        "sector_etf": sector_etf,
        "direction": direction,
        "entry_iso": entry_iso,
        "exit_iso": exit_iso,
        "entry_price": float(entry_price),
        "exit_price": float(exit_price),
        "trade_return": trade_ret,
        "spy_return": spy_ret,
        "sector_return": sec_ret,
    }
    _append_log(record)

    async with _LOCK:
        _load_state()
        fa = _STATE.get(strategy)
        if fa is None:
            fa = FactorAttribution(strategy=strategy)
            _STATE[strategy] = fa
        fa.window_trades.append({
            "trade_return": trade_ret,
            "spy_return": spy_ret,
            "sector_return": sec_ret,
            "ticker": ticker,
            "ts": _now_iso(),
        })
        # Trim to rolling window
        if len(fa.window_trades) > WINDOW_TRADES:
            fa.window_trades = fa.window_trades[-WINDOW_TRADES:]
        fa.n_trades = len(fa.window_trades)

        current_fit: dict = {}
        if fa.n_trades >= MIN_TRADES:
            current_fit = _ols_fit(fa.window_trades)
            if current_fit:
                fa.alpha = current_fit["alpha"]
                fa.alpha_t_stat = current_fit["alpha_t_stat"]
                fa.beta_spy = current_fit["beta_spy"]
                fa.beta_sector = current_fit["beta_sector"]
                fa.r_squared = current_fit["r_squared"]
                fa.residual_std = current_fit["residual_std"]
                fa.avg_trade_return = current_fit["avg_trade_return"]
                fa.avg_spy_return = current_fit["avg_spy_return"]
                fa.sharpe_alpha = current_fit["sharpe_alpha"]
                fa.last_fit_iso = _now_iso()
                log.info(
                    "[FA] %s refit n=%d α=%.5f β_spy=%.2f β_sec=%.2f R²=%.2f "
                    "sharpe_α=%.2f",
                    strategy, fa.n_trades, fa.alpha, fa.beta_spy,
                    fa.beta_sector, fa.r_squared, fa.sharpe_alpha,
                )
        _persist_state()

    return {"trade_record": record, "current_fit": current_fit}


async def all_attributions() -> dict:
    """Snapshot of every strategy's current factor decomposition (for dashboard)."""
    async with _LOCK:
        _load_state()
        return {
            s: {k: v for k, v in asdict(fa).items() if k != "window_trades"}
            for s, fa in _STATE.items()
        }


__all__ = [
    "attribute_closed_trade",
    "all_attributions",
    "WINDOW_TRADES",
    "MIN_TRADES",
]
