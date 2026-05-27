"""
Auto-Trader quant scanner suite — Wave 14L L2

Five named scanners that ORIGINATE trade ideas (parallel to the brief
pipeline). Each scanner:
  1. Checks its required capabilities via capability_registry — if
     missing, emits tool:capability_request MemUnit + returns empty.
  2. Runs its quant logic against a watchlist (env-configurable).
  3. Emits trade_ideas via trade_idea_tracker.record_emission so they
     flow into the same auto-trader loop the brief feeds.

Scanners:

  mean_reversion_scanner   — RSI<30 + Bollinger lower-band touch on
                              uptrending stock. Mean-reversion bounce play.
                              Recipe: mean_reversion_oversold (1d-4d hold).

  pead_scanner             — Post-earnings drift: ticker reported within
                              last 5d, surprise positive (1d ROC > 3%) →
                              long 20d drift. Recipe: pead_drift.

  factor_scanner           — Sector momentum rank from rotation_tracker:
                              Leading-quadrant sectors with positive 5d
                              ratio momentum → long. Recipe: sector_rotation.

  pairs_scanner            — Cointegrated ticker pair z-score > 2 on
                              60-day price ratio → market-neutral arb.
                              Recipe: pairs_stat_arb. (Stub if scipy unavail.)

  whale_flow_scanner       — Unusual Whales premium-concentration copy.
                              Recipe: whale_copy_options_flow. (Stub
                              without UNUSUAL_WHALES_API_KEY → emits
                              capability_request.)

Scheduler task ncl-auto-trader-quant-scan fires every 30 min in market
hours / 2hr off-hours. Each scanner is independently CB-wrapped.

Storage:
  data/portfolio/auto_trader/quant_scan_events.jsonl (audit)

Tunables (env):
  NCL_AT_QUANT_SCAN_ENABLED=1
  NCL_AT_QUANT_TICK_MARKET=1800     (30min)
  NCL_AT_QUANT_TICK_OFFHOURS=7200   (2hr)
  NCL_AT_QUANT_WATCHLIST=SPY,QQQ,IWM,NVDA,TSLA,AAPL,MSFT,AMD,GOOG,META,
                          AMZN,SLV,GLD,XLE,XLF,XLK
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.quant_scanners")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
DATA_DIR = NCL_BASE / "data" / "portfolio" / "auto_trader"
SCAN_AUDIT = DATA_DIR / "quant_scan_events.jsonl"

ENABLED = os.getenv("NCL_AT_QUANT_SCAN_ENABLED", "1") not in ("0", "false", "False")
TICK_MARKET = int(os.getenv("NCL_AT_QUANT_TICK_MARKET", "1800"))
TICK_OFFHOURS = int(os.getenv("NCL_AT_QUANT_TICK_OFFHOURS", "7200"))
WATCHLIST = [
    s.strip().upper() for s in os.getenv(
        "NCL_AT_QUANT_WATCHLIST",
        "SPY,QQQ,IWM,NVDA,TSLA,AAPL,MSFT,AMD,GOOG,META,AMZN,SLV,GLD,XLE,XLF,XLK",
    ).split(",") if s.strip()
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _is_market_open(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    et_hour = (now.hour - 4) % 24
    if now.weekday() >= 5:
        return False
    return (et_hour, now.minute) >= (9, 30) and et_hour < 16


def _append_audit(row: dict) -> None:
    _ensure_dir()
    try:
        with open(SCAN_AUDIT, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:
        log.warning("[QUANT] audit append failed: %s", e)


# ─────────────────────────────────────────────────────────────────────
# Shared helpers — yfinance-backed price fetch
# ─────────────────────────────────────────────────────────────────────

def _fetch_history(ticker: str, days: int = 60):
    """Fetch ohlcv bars for ticker. Returns list of (date, close)
    tuples or empty on failure. Synchronous — wrapped via to_thread."""
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period=f"{days}d", interval="1d")
        if hist is None or hist.empty:
            return []
        return [(idx.strftime("%Y-%m-%d"), float(row["Close"]))
                for idx, row in hist.iterrows()]
    except Exception as e:
        log.debug("[QUANT] yf history failed for %s: %s", ticker, e)
        return []


# ─────────────────────────────────────────────────────────────────────
# RSI helper (no scipy dep)
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
            gain = max(change, 0)
            loss = max(-change, 0)
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _bollinger(closes: list, period: int = 20, num_std: float = 2.0) -> Optional[dict]:
    """Returns {upper, mid, lower} or None."""
    if len(closes) < period:
        return None
    recent = closes[-period:]
    mid = sum(recent) / period
    variance = sum((c - mid) ** 2 for c in recent) / period
    std = variance ** 0.5
    return {
        "upper": mid + num_std * std,
        "mid": mid,
        "lower": mid - num_std * std,
    }


def _atr(highs: list, lows: list, closes: list, period: int = 14) -> Optional[float]:
    """Average True Range — needs separate H/L bars."""
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return sum(trs[-period:]) / period


# ─────────────────────────────────────────────────────────────────────
# SCANNER 1: mean_reversion_oversold
# ─────────────────────────────────────────────────────────────────────

async def scan_mean_reversion(*, brain=None) -> list[dict]:
    """RSI<30 + Bollinger lower-touch on uptrending name → long."""
    from .capability_registry import check_and_request
    cap = await check_and_request(
        "yfinance", brain=brain, requesting_module="quant:mean_reversion",
    )
    if not cap.get("available"):
        return []
    ideas = []
    for ticker in WATCHLIST:
        try:
            bars = await asyncio.to_thread(_fetch_history, ticker, 60)
            if not bars or len(bars) < 25:
                continue
            closes = [b[1] for b in bars]
            rsi = _rsi(closes)
            bb = _bollinger(closes)
            if rsi is None or bb is None:
                continue
            last = closes[-1]
            sma50 = sum(closes[-50:]) / min(50, len(closes))
            # Uptrending: last close above 50-day mean. Oversold: RSI<30 +
            # touch within 2% of lower BB.
            uptrending = last > sma50
            oversold = rsi < 30
            bb_touch = last <= bb["lower"] * 1.02
            if uptrending and oversold and bb_touch:
                stop = round(bb["lower"] * 0.97, 2)
                target = round(bb["mid"], 2)
                R = round(last - stop, 2)
                if R <= 0:
                    continue
                ideas.append({
                    "source": "quant:mean_reversion",
                    "strategy": "mean_reversion_oversold",
                    "ticker": ticker,
                    "direction": "long",
                    "entry_price": last,
                    "stop_price": stop,
                    "target_price": target,
                    "R_per_share": R,
                    "planned_qty": 0,  # sized by governor
                    "stop_type": "price",
                    "stop_basis": "below 2-sigma Bollinger lower",
                    "target_basis": "Bollinger middle band (mean)",
                    "thesis": (
                        f"{ticker} oversold: RSI={rsi:.1f}, "
                        f"BB lower=${bb['lower']:.2f} touched, "
                        f"still uptrending (last ${last:.2f} > 50d-SMA ${sma50:.2f}). "
                        f"Mean-revert long to mid-band ${bb['mid']:.2f}."
                    ),
                    "scanner_metadata": {
                        "rsi": round(rsi, 2),
                        "bb_upper": round(bb["upper"], 2),
                        "bb_mid": round(bb["mid"], 2),
                        "bb_lower": round(bb["lower"], 2),
                        "sma50": round(sma50, 2),
                    },
                })
        except Exception as e:
            log.debug("[QUANT:mean_rev] %s failed: %s", ticker, e)
    return ideas


# ─────────────────────────────────────────────────────────────────────
# SCANNER 2: pead_drift
# ─────────────────────────────────────────────────────────────────────

async def scan_pead(*, brain=None) -> list[dict]:
    """Post-earnings drift: ticker reported within last 5d + 1d ROC > +3%
    → long 20d drift. Skip if not enough data."""
    from .capability_registry import check_and_request
    cap_yf = await check_and_request(
        "yfinance", brain=brain, requesting_module="quant:pead",
    )
    cap_earn = await check_and_request(
        "earnings_calendar", brain=brain, requesting_module="quant:pead",
    )
    if not cap_yf.get("available") or not cap_earn.get("available"):
        return []
    ideas = []
    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=5)
    try:
        from runtime.stocks.enrichments import get_earnings_map
    except Exception as e:
        log.debug("[QUANT:pead] enrichments import failed: %s", e)
        return []
    try:
        emap = await asyncio.to_thread(get_earnings_map, tickers=WATCHLIST) or {}
    except Exception as e:
        log.debug("[QUANT:pead] earnings_map failed: %s", e)
        return []
    for ticker in WATCHLIST:
        try:
            earnings_rows = emap.get(ticker) or []
            recent_earnings = None
            for r in earnings_rows:
                d_raw = r.get("date") if isinstance(r, dict) else r
                if not d_raw:
                    continue
                try:
                    d = datetime.fromisoformat(str(d_raw)[:10]).date()
                except Exception:
                    continue
                if cutoff <= d <= today:
                    recent_earnings = d
                    break
            if recent_earnings is None:
                continue
            bars = await asyncio.to_thread(_fetch_history, ticker, 7)
            if not bars or len(bars) < 2:
                continue
            closes = [b[1] for b in bars]
            roc_1d = (closes[-1] - closes[-2]) / closes[-2] * 100
            if roc_1d < 3.0:
                continue  # only ride positive surprises
            last = closes[-1]
            stop = round(last * 0.93, 2)
            target = round(last * 1.20, 2)
            R = round(last - stop, 2)
            if R <= 0:
                continue
            ideas.append({
                "source": "quant:pead",
                "strategy": "pead_drift",
                "ticker": ticker,
                "direction": "long",
                "entry_price": last,
                "stop_price": stop,
                "target_price": target,
                "R_per_share": R,
                "planned_qty": 0,
                "stop_type": "price",
                "stop_basis": "7% below entry (earnings whip downside)",
                "target_basis": "20% drift target (4-week PEAD horizon)",
                "thesis": (
                    f"{ticker} PEAD: reported {recent_earnings.isoformat()} "
                    f"({(today - recent_earnings).days}d ago), "
                    f"+{roc_1d:.1f}% 1d ROC. Long 20d drift target."
                ),
                "scanner_metadata": {
                    "earnings_date": recent_earnings.isoformat(),
                    "days_since_earnings": (today - recent_earnings).days,
                    "roc_1d_pct": round(roc_1d, 2),
                },
            })
        except Exception as e:
            log.debug("[QUANT:pead] %s failed: %s", ticker, e)
    return ideas


# ─────────────────────────────────────────────────────────────────────
# SCANNER 3: factor_scanner (sector rotation Leading-quadrant)
# ─────────────────────────────────────────────────────────────────────

async def scan_factor(*, brain=None) -> list[dict]:
    """Long the Leading-quadrant sector ETFs from rotation_tracker with
    positive 5d ratio momentum."""
    from .capability_registry import check_and_request
    cap = await check_and_request(
        "rotation_snapshot", brain=brain, requesting_module="quant:factor",
    )
    if not cap.get("available"):
        return []
    ideas = []
    try:
        rot_dir = NCL_BASE / "data" / "rotation"
        files = sorted([p for p in rot_dir.glob("20*.json")
                        if "cycle-" not in p.name and "style-" not in p.name],
                       reverse=True)
        if not files:
            return []
        latest = json.loads(files[0].read_text())
    except Exception as e:
        log.debug("[QUANT:factor] rotation read failed: %s", e)
        return []

    sectors = (latest.get("rotation") or {}).get("sectors") or latest.get("sectors") or []
    leading = [
        s for s in sectors
        if (s.get("quadrant") or "").lower() == "leading"
        and (s.get("rs_momentum_5d") or 0) > 0
    ]
    for s in leading:
        ticker = (s.get("ticker") or s.get("etf") or "").upper()
        if not ticker:
            continue
        try:
            bars = await asyncio.to_thread(_fetch_history, ticker, 5)
            if not bars:
                continue
            last = bars[-1][1]
            stop = round(last * 0.94, 2)
            target = round(last * 1.10, 2)
            R = round(last - stop, 2)
            if R <= 0:
                continue
            ideas.append({
                "source": "quant:factor",
                "strategy": "sector_rotation",
                "ticker": ticker,
                "direction": "long",
                "entry_price": last,
                "stop_price": stop,
                "target_price": target,
                "R_per_share": R,
                "planned_qty": 0,
                "stop_type": "price",
                "stop_basis": "6% below entry (sector rotation invalidation)",
                "target_basis": "10% sector move target",
                "thesis": (
                    f"{ticker} Leading-quadrant sector ETF, "
                    f"5d RS momentum {s.get('rs_momentum_5d', 0):+.2f}%, "
                    f"ratio_pct_chg_20d {s.get('ratio_pct_chg_20d', 0):+.2f}%."
                ),
                "scanner_metadata": {
                    "quadrant": s.get("quadrant"),
                    "rs_momentum_5d": s.get("rs_momentum_5d"),
                    "ratio_pct_chg_20d": s.get("ratio_pct_chg_20d"),
                    "sector_name": s.get("name"),
                },
            })
        except Exception as e:
            log.debug("[QUANT:factor] %s failed: %s", ticker, e)
    return ideas


# ─────────────────────────────────────────────────────────────────────
# SCANNER 4: pairs_stat_arb (stub-aware)
# ─────────────────────────────────────────────────────────────────────

PAIRS_DEFAULT = [
    ("XLE", "XOM"),    # energy ETF vs largest constituent
    ("XLK", "MSFT"),   # tech ETF vs MSFT
    ("XLF", "JPM"),    # financials ETF vs JPM
    ("GLD", "SLV"),    # gold vs silver
    ("SPY", "QQQ"),    # broad vs growth
]


async def scan_pairs(*, brain=None) -> list[dict]:
    """Z-score > 2 entry on 60-day price-ratio pair → market neutral."""
    from .capability_registry import check_and_request
    cap = await check_and_request(
        "yfinance", brain=brain, requesting_module="quant:pairs",
    )
    if not cap.get("available"):
        return []
    pairs = [p for p in PAIRS_DEFAULT
             if p[0] in WATCHLIST or p[1] in WATCHLIST]
    ideas = []
    for a, b in pairs:
        try:
            bars_a = await asyncio.to_thread(_fetch_history, a, 60)
            bars_b = await asyncio.to_thread(_fetch_history, b, 60)
            if len(bars_a) < 30 or len(bars_b) < 30:
                continue
            # Align by date
            dates_a = {d: c for d, c in bars_a}
            dates_b = {d: c for d, c in bars_b}
            common = sorted(set(dates_a) & set(dates_b))[-60:]
            if len(common) < 30:
                continue
            ratios = [dates_a[d] / dates_b[d] for d in common]
            mean = sum(ratios) / len(ratios)
            var = sum((r - mean) ** 2 for r in ratios) / len(ratios)
            std = var ** 0.5
            if std == 0:
                continue
            last_ratio = ratios[-1]
            z = (last_ratio - mean) / std
            if abs(z) < 2.0:
                continue
            # z > 2: A is rich vs B → short A / long B
            # z < -2: A is cheap vs B → long A / short B
            short_leg, long_leg = (a, b) if z > 0 else (b, a)
            ideas.append({
                "source": "quant:pairs",
                "strategy": "pairs_stat_arb",
                "ticker": long_leg,
                "direction": "long",
                "entry_price": dates_a[common[-1]] if long_leg == a else dates_b[common[-1]],
                "stop_price": round(
                    (dates_a[common[-1]] if long_leg == a else dates_b[common[-1]]) * 0.95,
                    2,
                ),
                "target_price": round(
                    (dates_a[common[-1]] if long_leg == a else dates_b[common[-1]]) * 1.05,
                    2,
                ),
                "R_per_share": round(
                    (dates_a[common[-1]] if long_leg == a else dates_b[common[-1]]) * 0.05,
                    2,
                ),
                "planned_qty": 0,
                "stop_type": "thesis_break",
                "stop_basis": f"pair z-score returns inside ±0.5 (mean revert hit)",
                "target_basis": f"pair z-score returns to 0 (full mean revert)",
                "thesis": (
                    f"PAIRS {a}/{b}: z-score {z:+.2f}, ratio {last_ratio:.4f} "
                    f"vs mean {mean:.4f} (σ={std:.4f}). "
                    f"Long {long_leg} / short {short_leg} expected mean-revert. "
                    f"NOTE: paper engine opens long leg only; short leg tracked "
                    f"in metadata.short_leg for operator hedge."
                ),
                "scanner_metadata": {
                    "pair": [a, b],
                    "z_score": round(z, 2),
                    "ratio_mean": round(mean, 4),
                    "ratio_std": round(std, 4),
                    "ratio_last": round(last_ratio, 4),
                    "short_leg": short_leg,
                    "long_leg": long_leg,
                },
            })
        except Exception as e:
            log.debug("[QUANT:pairs] %s/%s failed: %s", a, b, e)
    return ideas


# ─────────────────────────────────────────────────────────────────────
# SCANNER 5: whale_flow (stub — needs Unusual Whales)
# ─────────────────────────────────────────────────────────────────────

async def scan_whale_flow(*, brain=None) -> list[dict]:
    """Copy big-money options flow from Unusual Whales. Stub until
    UNUSUAL_WHALES_API_KEY set + we add an httpx client."""
    from .capability_registry import check_and_request
    cap = await check_and_request(
        "unusual_whales", brain=brain, requesting_module="quant:whale_flow",
    )
    if not cap.get("available"):
        # The check_and_request already emitted a tool:capability_request
        # MemUnit. Return empty.
        return []
    # TODO: implement Unusual Whales fetch once key + adapter exist
    return []


# ─────────────────────────────────────────────────────────────────────
# Tick + loop
# ─────────────────────────────────────────────────────────────────────

_SCANNERS = [
    ("mean_reversion", scan_mean_reversion),
    ("pead", scan_pead),
    ("factor", scan_factor),
    ("pairs", scan_pairs),
    ("whale_flow", scan_whale_flow),
]


async def _emit_idea(idea: dict) -> Optional[str]:
    """Push a scanner idea into trade_idea_tracker. Returns trade_idea_id or None."""
    try:
        from ..trade_idea_tracker import get_trade_idea_tracker
        tracker = await get_trade_idea_tracker()
        result = await tracker.record_emission(
            source=idea["source"],
            strategy=idea["strategy"],
            ticker=idea["ticker"],
            direction=idea.get("direction"),
            entry_price=idea.get("entry_price"),
            stop_price=idea.get("stop_price"),
            target_price=idea.get("target_price"),
            R_per_share=idea.get("R_per_share"),
            planned_qty=idea.get("planned_qty"),
            stop_type=idea.get("stop_type"),
            stop_basis=idea.get("stop_basis"),
            target_basis=idea.get("target_basis"),
            thesis=idea.get("thesis"),
            metadata={
                "quant_scanner": True,
                "scanner_data": idea.get("scanner_metadata") or {},
                "wave": "14L-L2",
            },
        )
        return result.get("trade_idea_id")
    except Exception as e:
        log.error("[QUANT] emission failed for %s: %s", idea.get("ticker"), e)
        return None


async def quant_scan_tick(brain=None) -> dict:
    """One pass through all 5 scanners. Returns per-scanner counts."""
    summary = {
        "tick_at_iso": _now_iso(),
        "scanners": {},
        "total_ideas_emitted": 0,
        "watchlist_size": len(WATCHLIST),
    }
    for name, fn in _SCANNERS:
        try:
            ideas = await fn(brain=brain)
            emitted = 0
            for idea in ideas[:5]:  # cap per scanner per tick
                tid = await _emit_idea(idea)
                if tid:
                    emitted += 1
            summary["scanners"][name] = {
                "found": len(ideas), "emitted": emitted,
            }
            summary["total_ideas_emitted"] += emitted
        except Exception as e:
            log.warning("[QUANT] scanner %s failed: %s", name, e)
            summary["scanners"][name] = {"error": str(e)}
    _append_audit(summary)
    log.info(
        "[QUANT] tick done — %d ideas emitted across %d scanners",
        summary["total_ideas_emitted"], len(_SCANNERS),
    )
    return summary


async def quant_scan_loop(brain=None) -> None:
    """Long-running scheduler task. 30min market / 2hr off-hours."""
    if not ENABLED:
        log.info("[QUANT] disabled (NCL_AT_QUANT_SCAN_ENABLED=0)")
        while True:
            await asyncio.sleep(3600)
    log.info(
        "[QUANT] starting quant scan loop (market %ds / off-hours %ds) — "
        "watchlist: %s",
        TICK_MARKET, TICK_OFFHOURS, WATCHLIST,
    )
    while True:
        try:
            await quant_scan_tick(brain)
        except asyncio.CancelledError:
            log.info("[QUANT] cancelled")
            raise
        except Exception as e:
            log.error("[QUANT] tick error (continuing): %s", e, exc_info=True)
        cadence = TICK_MARKET if _is_market_open() else TICK_OFFHOURS
        await asyncio.sleep(cadence)


async def quant_scan_summary() -> dict:
    """Snapshot for /dashboard rollup."""
    recent = []
    if SCAN_AUDIT.exists():
        try:
            with open(SCAN_AUDIT) as f:
                rows = [json.loads(line) for line in f if line.strip()]
            recent = rows[-10:]
        except Exception:
            pass
    return {
        "enabled": ENABLED,
        "tick_market_s": TICK_MARKET,
        "tick_offhours_s": TICK_OFFHOURS,
        "watchlist": WATCHLIST,
        "scanner_names": [name for name, _ in _SCANNERS],
        "recent_10_ticks": recent,
        "last_tick_iso": recent[-1]["tick_at_iso"] if recent else None,
    }
