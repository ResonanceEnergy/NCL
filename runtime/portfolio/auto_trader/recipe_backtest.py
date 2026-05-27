"""
Auto-Trader recipe backtest harness — Wave 14L M3

Replays a strategy recipe against historical OHLCV bars and computes
trade-by-trade stats: hit_rate, expectancy_R, profit_factor, max_dd,
Sharpe-like ratio. Lets the operator (or the auto-trader itself in a
future self-research loop) evaluate a recipe BEFORE paper-deploying it
to live ticks.

Each recipe needs a `signal_fn(bars, idx) → "long" | "short" | None`
that maps to its entry rule. The harness loops through bars, calls
signal_fn, when it returns a direction it simulates a trade until
stop/target/time-exit, records R-multiple.

Currently supports the equity recipes that have well-defined signal
logic (momentum_breakout, swing_pullback, mean_reversion_oversold,
gap_fill, pead_drift — same logic used in the live scanners). Option
recipes return a 'not_supported' result (would need real option chain
historical data which we don't have).

Storage:
  data/portfolio/auto_trader/backtest_runs.jsonl  (audit)

Tunables (env):
  NCL_AT_BACKTEST_ENABLED=1
  NCL_AT_BACKTEST_DEFAULT_DAYS=180
  NCL_AT_BACKTEST_STOP_PCT=8        (% below entry for default stop)
  NCL_AT_BACKTEST_TARGET_PCT=20     (% above entry for default target)
  NCL_AT_BACKTEST_MAX_HOLD_BARS=20  (auto-exit after N bars)
"""

from __future__ import annotations

import json
import logging
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.recipe_backtest")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio" / "auto_trader"
AUDIT_FILE = DATA_DIR / "backtest_runs.jsonl"

ENABLED = os.getenv("NCL_AT_BACKTEST_ENABLED", "1") not in ("0", "false", "False")
DEFAULT_DAYS = int(os.getenv("NCL_AT_BACKTEST_DEFAULT_DAYS", "180"))
STOP_PCT = float(os.getenv("NCL_AT_BACKTEST_STOP_PCT", "8"))
TARGET_PCT = float(os.getenv("NCL_AT_BACKTEST_TARGET_PCT", "20"))
MAX_HOLD_BARS = int(os.getenv("NCL_AT_BACKTEST_MAX_HOLD_BARS", "20"))


# ─────────────────────────────────────────────────────────────────────
# Signal functions per recipe
# ─────────────────────────────────────────────────────────────────────

def _rsi(closes: list, period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if len(closes) > period + 1:
        for i in range(period + 1, len(closes)):
            change = closes[i] - closes[i - 1]
            avg_gain = (avg_gain * (period - 1) + max(change, 0)) / period
            avg_loss = (avg_loss * (period - 1) + max(-change, 0)) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _signal_momentum_breakout(closes: list, idx: int) -> Optional[str]:
    """Long when close breaks above 50-day high + 150-SMA filter."""
    if idx < 150:
        return None
    window = closes[idx - 50:idx]
    sma150 = sum(closes[idx - 150:idx]) / 150
    last = closes[idx]
    if last > max(window) and last > sma150:
        return "long"
    return None


def _signal_swing_pullback(closes: list, idx: int) -> Optional[str]:
    """Long on pullback to 50-SMA inside a 200-SMA uptrend."""
    if idx < 200:
        return None
    sma50 = sum(closes[idx - 50:idx]) / 50
    sma200 = sum(closes[idx - 200:idx]) / 200
    last = closes[idx]
    # Pullback: prev close was above sma50, current touches/below it,
    # still above sma200
    prev = closes[idx - 1]
    if prev > sma50 and last <= sma50 * 1.01 and last > sma200:
        return "long"
    return None


def _signal_mean_reversion(closes: list, idx: int) -> Optional[str]:
    """RSI<30 + price below 20-day mean - 2σ, but above 50-day SMA."""
    if idx < 50:
        return None
    window = closes[idx - 20:idx]
    mid = sum(window) / 20
    variance = sum((c - mid) ** 2 for c in window) / 20
    std = variance ** 0.5
    bb_lower = mid - 2 * std
    rsi = _rsi(closes[:idx + 1])
    if rsi is None:
        return None
    sma50 = sum(closes[idx - 50:idx]) / 50
    last = closes[idx]
    if rsi < 30 and last <= bb_lower * 1.02 and last > sma50:
        return "long"
    return None


def _signal_gap_fill(closes: list, idx: int, opens: Optional[list] = None) -> Optional[str]:
    """Gap > 2% from prev close → fade. Approximate without open data:
    use prev close vs this close as gap proxy."""
    if idx < 2:
        return None
    prev_close = closes[idx - 1]
    last = closes[idx]
    gap_pct = (last - prev_close) / prev_close * 100
    if gap_pct > 2.0:
        return "short"  # fade gap up
    if gap_pct < -2.0:
        return "long"   # fade gap down
    return None


def _signal_pead_drift(closes: list, idx: int) -> Optional[str]:
    """Approximate without earnings dates: look for +3%+ 1d ROC after
    a 20d consolidation (low realized vol)."""
    if idx < 21:
        return None
    roc_1d = (closes[idx] - closes[idx - 1]) / closes[idx - 1] * 100
    if roc_1d < 3.0:
        return None
    # Low-vol consolidation: realized std over prior 20 bars < 1.5%
    prior = closes[idx - 21:idx - 1]
    rets = [
        (prior[i] - prior[i - 1]) / prior[i - 1] * 100
        for i in range(1, len(prior))
    ]
    if not rets:
        return None
    realized_std = statistics.pstdev(rets)
    if realized_std > 1.5:
        return None
    return "long"


_SIGNAL_FNS = {
    "momentum_breakout": _signal_momentum_breakout,
    "swing_pullback": _signal_swing_pullback,
    "mean_reversion_oversold": _signal_mean_reversion,
    "gap_fill": _signal_gap_fill,
    "pead_drift": _signal_pead_drift,
}


# ─────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────

def _fetch_history_sync(ticker: str, days: int = 180):
    """Synchronous yfinance fetch — caller wraps in to_thread."""
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period=f"{days}d", interval="1d")
        if hist is None or hist.empty:
            return []
        return [(idx.strftime("%Y-%m-%d"), float(row["Close"]))
                for idx, row in hist.iterrows()]
    except Exception as e:
        log.debug("[BACKTEST] yf fetch failed for %s: %s", ticker, e)
        return []


def _simulate_trade(
    closes: list, entry_idx: int, direction: str,
    stop_pct: float, target_pct: float, max_hold: int,
) -> dict:
    """Walk forward from entry_idx until stop / target / time-exit.
    Returns {exit_idx, exit_price, R_multiple, days_held, exit_reason}."""
    entry_price = closes[entry_idx]
    if direction == "long":
        stop = entry_price * (1 - stop_pct / 100)
        target = entry_price * (1 + target_pct / 100)
    else:
        stop = entry_price * (1 + stop_pct / 100)
        target = entry_price * (1 - target_pct / 100)
    risk = abs(entry_price - stop)
    if risk == 0:
        return {"exit_idx": entry_idx, "exit_price": entry_price,
                "R_multiple": 0, "days_held": 0, "exit_reason": "zero_risk"}
    for offset in range(1, min(max_hold + 1, len(closes) - entry_idx)):
        px = closes[entry_idx + offset]
        if direction == "long":
            if px <= stop:
                return {
                    "exit_idx": entry_idx + offset, "exit_price": px,
                    "R_multiple": round((px - entry_price) / risk, 3),
                    "days_held": offset, "exit_reason": "stop",
                }
            if px >= target:
                return {
                    "exit_idx": entry_idx + offset, "exit_price": px,
                    "R_multiple": round((px - entry_price) / risk, 3),
                    "days_held": offset, "exit_reason": "target",
                }
        else:  # short
            if px >= stop:
                return {
                    "exit_idx": entry_idx + offset, "exit_price": px,
                    "R_multiple": round((entry_price - px) / risk, 3),
                    "days_held": offset, "exit_reason": "stop",
                }
            if px <= target:
                return {
                    "exit_idx": entry_idx + offset, "exit_price": px,
                    "R_multiple": round((entry_price - px) / risk, 3),
                    "days_held": offset, "exit_reason": "target",
                }
    # Time exit
    final_idx = min(entry_idx + max_hold, len(closes) - 1)
    final_px = closes[final_idx]
    if direction == "long":
        R = (final_px - entry_price) / risk
    else:
        R = (entry_price - final_px) / risk
    return {
        "exit_idx": final_idx, "exit_price": final_px,
        "R_multiple": round(R, 3),
        "days_held": final_idx - entry_idx, "exit_reason": "time",
    }


async def backtest_recipe(
    recipe_name: str,
    ticker: str,
    *,
    days: int = DEFAULT_DAYS,
    stop_pct: float = STOP_PCT,
    target_pct: float = TARGET_PCT,
    max_hold_bars: int = MAX_HOLD_BARS,
) -> dict:
    """Run the recipe's signal_fn over `days` of history for `ticker`.
    Returns a summary dict with per-trade list + aggregate stats."""
    import asyncio
    if not ENABLED:
        return {"error": "backtest disabled (NCL_AT_BACKTEST_ENABLED=0)"}
    signal_fn = _SIGNAL_FNS.get(recipe_name)
    if signal_fn is None:
        return {
            "recipe": recipe_name,
            "ticker": ticker.upper(),
            "supported": False,
            "reason": (
                f"no signal_fn for '{recipe_name}'. Supported: "
                f"{sorted(_SIGNAL_FNS.keys())}"
            ),
        }
    bars = await asyncio.to_thread(_fetch_history_sync, ticker, days)
    if not bars or len(bars) < 30:
        return {"recipe": recipe_name, "ticker": ticker.upper(),
                "error": f"insufficient bars ({len(bars) if bars else 0})"}

    closes = [b[1] for b in bars]
    trades: list[dict] = []
    in_trade_until_idx = -1
    for i in range(len(closes)):
        if i <= in_trade_until_idx:
            continue
        direction = signal_fn(closes, i)
        if direction is None:
            continue
        sim = _simulate_trade(closes, i, direction, stop_pct, target_pct, max_hold_bars)
        trades.append({
            "entry_date": bars[i][0], "entry_price": closes[i],
            "direction": direction, **sim,
            "exit_date": bars[sim["exit_idx"]][0]
                          if sim["exit_idx"] < len(bars) else None,
        })
        in_trade_until_idx = sim["exit_idx"]

    if not trades:
        return {
            "recipe": recipe_name, "ticker": ticker.upper(),
            "supported": True, "days": days, "bars": len(bars),
            "trades": [], "n_trades": 0,
            "reason": "no signals fired in window",
        }

    Rs = [t["R_multiple"] for t in trades]
    winners = [r for r in Rs if r > 0]
    losers = [r for r in Rs if r < 0]
    n = len(Rs)
    n_w = len(winners)
    hit_rate = n_w / n if n else 0
    avg_win = sum(winners) / n_w if n_w else 0
    avg_loss = sum(losers) / len(losers) if losers else 0
    profit_factor = (
        sum(winners) / abs(sum(losers)) if losers and sum(losers) != 0
        else (float("inf") if winners else 0)
    )
    expectancy = sum(Rs) / n if n else 0
    # SQN
    mean_R = sum(Rs) / n
    var = sum((r - mean_R) ** 2 for r in Rs) / n if n else 0
    std_R = var ** 0.5
    sqn = (mean_R / std_R) * (n ** 0.5) if std_R > 0 else 0
    # Max drawdown in R-space (cumulative)
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in Rs:
        cum += r
        peak = max(peak, cum)
        dd = peak - cum
        max_dd = max(max_dd, dd)
    avg_hold = sum(t["days_held"] for t in trades) / n if n else 0

    result = {
        "recipe": recipe_name,
        "ticker": ticker.upper(),
        "supported": True,
        "days": days,
        "bars_fetched": len(bars),
        "n_trades": n,
        "winners": n_w,
        "losers": len(losers),
        "hit_rate": round(hit_rate, 4),
        "avg_win_R": round(avg_win, 3),
        "avg_loss_R": round(avg_loss, 3),
        "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else None,
        "expectancy_R": round(expectancy, 3),
        "sqn": round(sqn, 3),
        "max_drawdown_R": round(max_dd, 3),
        "total_R": round(sum(Rs), 3),
        "avg_hold_days": round(avg_hold, 1),
        "trades": trades,
        "config": {
            "stop_pct": stop_pct, "target_pct": target_pct,
            "max_hold_bars": max_hold_bars,
        },
        "computed_at_iso": datetime.now(timezone.utc).isoformat(),
    }

    # Append to audit
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        # Strip trades list from audit to keep file lean
        audit_row = {k: v for k, v in result.items() if k != "trades"}
        with open(AUDIT_FILE, "a") as f:
            f.write(json.dumps(audit_row) + "\n")
    except Exception as e:
        log.warning("[BACKTEST] audit write failed: %s", e)

    log.info(
        "[BACKTEST] %s on %s: %d trades, hit %.0f%%, expectancy %.2fR, "
        "PF %.2f, total %.1fR",
        recipe_name, ticker, n, hit_rate * 100, expectancy,
        profit_factor if profit_factor != float("inf") else 999,
        sum(Rs),
    )
    return result


def list_supported_recipes() -> list[str]:
    return sorted(_SIGNAL_FNS.keys())


async def backtest_summary() -> dict:
    """Snapshot for /dashboard rollup — recent 10 runs."""
    recent = []
    if AUDIT_FILE.exists():
        try:
            with open(AUDIT_FILE) as f:
                rows = [json.loads(line) for line in f if line.strip()]
            recent = rows[-10:]
        except Exception:
            pass
    return {
        "enabled": ENABLED,
        "supported_recipes": list_supported_recipes(),
        "default_days": DEFAULT_DAYS,
        "default_stop_pct": STOP_PCT,
        "default_target_pct": TARGET_PCT,
        "recent_10_runs": recent,
    }
