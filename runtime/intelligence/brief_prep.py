"""Wave 14H — Morning Brief Pro: NightWatch prep stage.

Runs nightly at 02:30 ET. Collects every data block the Council needs to
write tomorrow's brief without making LLM calls. The output is a JSON
context pack stored at data/morning-brief-prep/YYYY-MM-DD.json.

Blocks collected (each is best-effort — empty blocks don't fail the pack):
    futures              ES/NQ/RTY/YM overnight quotes + % change
    overnight_movers     top 20 pre-market gainers + losers
    headlines            last 12h Awarebot RSS, dedup'd, importance-sorted
    options_flow         yesterday's GOAT/BRAVO + flow ledger summary
    economic_calendar    today's macro releases (consensus + prior)
    earnings_today       tickers reporting before/after open
    geopolitical         active leading Polymarket events
    vix_term_structure   ^VIX / ^VIX9D / ^VIX3M curve shape
    working_context      NATRIX's pinned priorities + research questions
    held_positions       current book for tactical context
    night_watch_summary  last data/night-watch/daily-*.md
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ncl.intel.brief_prep")

NCL_BASE = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
PREP_DIR = NCL_BASE / "data" / "morning-brief-prep"

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="brief-prep-")


# ─────────────────────────────────────────────────────────────────────────
# Block collectors — each returns a dict, never raises
# ─────────────────────────────────────────────────────────────────────────


def _yf_futures_blocking() -> dict:
    """Fetch overnight futures quotes via yfinance."""
    out: dict[str, dict] = {}
    try:
        import yfinance as yf
    except ImportError:
        return out
    symbols = {
        "ES=F": "S&P 500 e-mini",
        "NQ=F": "Nasdaq 100 e-mini",
        "RTY=F": "Russell 2000 e-mini",
        "YM=F": "Dow Jones e-mini",
    }
    for sym, label in symbols.items():
        try:
            t = yf.Ticker(sym)
            info = t.fast_info
            last = (
                getattr(info, "last_price", None)
                or (info.get("last_price") if hasattr(info, "get") else None)
                or 0
            )
            prev = (
                getattr(info, "previous_close", None)
                or (info.get("previous_close") if hasattr(info, "get") else None)
                or 0
            )
            if not (last and prev):
                hist = t.history(period="2d")
                if not hist.empty:
                    last = float(hist["Close"].iloc[-1])
                    prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else last
            if last and prev:
                pct = ((last - prev) / prev) * 100 if prev else 0
                out[sym] = {
                    "label": label,
                    "last": round(float(last), 2),
                    "prev": round(float(prev), 2),
                    "pct_change": round(float(pct), 2),
                }
        except Exception as e:
            log.debug("futures fetch %s failed: %s", sym, e)
    return out


def _yf_vix_blocking() -> dict:
    """Fetch VIX term structure."""
    out: dict[str, float] = {}
    try:
        import yfinance as yf
    except ImportError:
        return out
    for sym in ("^VIX", "^VIX9D", "^VIX3M"):
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="2d")
            if not hist.empty:
                out[sym] = round(float(hist["Close"].iloc[-1]), 2)
        except Exception:
            pass
    # Derive shape
    v9d = out.get("^VIX9D")
    v30 = out.get("^VIX")
    v3m = out.get("^VIX3M")
    shape = "unknown"
    if v9d and v30 and v3m:
        if v9d > v30 > v3m:
            shape = "backwardation (stress)"
        elif v9d < v30 < v3m:
            shape = "contango (calm)"
        else:
            shape = "mixed"
    out["_shape"] = shape
    return out


def _yf_overnight_movers_blocking(watchlist: list[str]) -> dict:
    """Pre-market % change for each ticker in watchlist; return top 20 gainers + 20 losers."""
    rows: list[dict] = []
    try:
        import yfinance as yf
    except ImportError:
        return {"gainers": [], "losers": []}
    for ticker in watchlist[:120]:  # cap for sanity
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="2d", prepost=True)
            if hist.empty or len(hist) < 2:
                continue
            last = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2])
            if prev <= 0:
                continue
            pct = ((last - prev) / prev) * 100
            rows.append({"ticker": ticker, "last": round(last, 2),
                         "prev": round(prev, 2), "pct": round(pct, 2)})
        except Exception:
            continue
    rows.sort(key=lambda r: r["pct"], reverse=True)
    return {
        "gainers": rows[:20],
        "losers": list(reversed(rows[-20:])),
    }


async def _collect_yf_block(name: str, func, *args) -> Optional[dict]:
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(_executor, func, *args)
    except Exception as e:
        log.warning("[brief_prep] %s collector failed: %s", name, e)
        return None


async def collect_headlines(brain) -> list[dict]:
    """Top 25 headlines from last 12h, dedup'd via Awarebot signal feed."""
    if brain is None:
        return []
    try:
        awarebot = getattr(brain, "_awarebot", None)
        if awarebot is None:
            return []
        # Pull recent signals + filter to news category
        signals = getattr(awarebot, "_recent_signals", None) or []
        cutoff_ts = time.time() - (12 * 3600)
        out: list[dict] = []
        seen_titles: set[str] = set()
        for s in signals:
            try:
                ts = getattr(s, "captured_at", None)
                if ts:
                    try:
                        from datetime import datetime as _dt
                        dt = _dt.fromisoformat(str(ts).replace("Z", "+00:00"))
                        if dt.timestamp() < cutoff_ts:
                            continue
                    except Exception:
                        pass
                category = getattr(s, "category", "")
                source = getattr(getattr(s, "source", None), "value", "") or ""
                if not any(k in (category + source).lower() for k in
                           ("news", "headline", "reuters", "bloomberg", "rss", "x_twitter")):
                    continue
                title = (getattr(s, "title", "") or "")[:200]
                if not title or title.lower() in seen_titles:
                    continue
                seen_titles.add(title.lower())
                out.append({
                    "title": title,
                    "source": source,
                    "sig_id": (getattr(s, "signal_id", "") or "")[:8],
                    "captured_at": str(ts) if ts else None,
                })
                if len(out) >= 25:
                    break
            except Exception:
                continue
        return out
    except Exception as e:
        log.debug("[brief_prep] headlines collector failed: %s", e)
        return []


def collect_options_flow_yesterday() -> dict:
    """Read yesterday's GOAT/BRAVO JSONLs + summarize."""
    from datetime import timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    out = {"goat": [], "bravo": [], "flow_summary": {}}
    for scanner in ("goat", "bravo"):
        p = NCL_BASE / "data" / "scanners" / f"{scanner}-{yesterday}.jsonl"
        if not p.exists():
            continue
        try:
            rows = []
            with open(p) as f:
                for line in f:
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
            rows.sort(key=lambda r: r.get(f"{scanner}_score", 0), reverse=True)
            out[scanner] = [
                {"ticker": r.get("ticker"), "score": r.get(f"{scanner}_score"),
                 "price": r.get("price")}
                for r in rows[:10]
            ]
        except Exception:
            pass
    return out


async def collect_polymarket_leading(brain) -> list[dict]:
    """Active leading markets only (P17-D lifecycle tagging)."""
    if brain is None:
        return []
    try:
        awarebot = getattr(brain, "_awarebot", None)
        if awarebot is None:
            return []
        signals = getattr(awarebot, "_recent_signals", None) or []
        leading: list[dict] = []
        for s in signals:
            try:
                source = getattr(getattr(s, "source", None), "value", "") or ""
                if "polymarket" not in source.lower():
                    continue
                meta = getattr(s, "metadata", None) or {}
                lifecycle = (meta.get("lifecycle_status") or "").lower()
                if lifecycle != "leading":
                    continue
                leading.append({
                    "title": (getattr(s, "title", "") or "")[:140],
                    "yes_price": getattr(s, "yes_price", None),
                    "no_price": getattr(s, "no_price", None),
                    "volume_24h": getattr(s, "volume_24h", None),
                    "sig_id": (getattr(s, "signal_id", "") or "")[:8],
                })
                if len(leading) >= 8:
                    break
            except Exception:
                continue
        return leading
    except Exception:
        return []


async def collect_held_positions(brain) -> list[dict]:
    if brain is None:
        return []
    try:
        # Try a few common shapes
        for attr in ("portfolio_manager", "_portfolio_manager", "portfolio"):
            mgr = getattr(brain, attr, None)
            if mgr is not None:
                getter = getattr(mgr, "get_positions", None) or getattr(mgr, "positions", None)
                if getter:
                    res = await getter() if asyncio.iscoroutinefunction(getter) else getter()
                    return list(res or [])[:50]
        return []
    except Exception:
        return []


async def collect_working_context(brain) -> dict:
    if brain is None:
        return {}
    try:
        wc = getattr(brain, "working_context", None)
        if wc is None:
            return {}
        snap = wc.snapshot() if hasattr(wc, "snapshot") else {}
        return {
            "themes": snap.get("themes", [])[:8],
            "pinned_priorities": [
                {"text": (i.get("content") or "")[:200]}
                for i in (snap.get("items") or [])[:10]
                if (i.get("category") == "pinned" or i.get("kind") == "pinned")
            ][:8],
        }
    except Exception:
        return {}


def collect_night_watch_summary() -> Optional[str]:
    """Read last data/night-watch/daily-*.md."""
    p = NCL_BASE / "data" / "night-watch"
    if not p.exists():
        return None
    try:
        files = sorted(p.glob("daily-*.md"), reverse=True)
        if not files:
            return None
        return files[0].read_text()[:5000]
    except Exception:
        return None


def collect_earnings_today() -> list[dict]:
    """yfinance + cached earnings map → tickers reporting today."""
    today = date.today().isoformat()
    out: list[dict] = []
    try:
        from runtime.stocks import enrichments as enr  # type: ignore
    except Exception:
        return out
    try:
        # Use the cached map if available
        from runtime.stocks.enrichments import _cache_get, _EARNINGS_CACHE_KEY  # type: ignore
        cached = _cache_get(_EARNINGS_CACHE_KEY)
        if cached:
            for ticker, dt_str in cached.items():
                if dt_str == today:
                    out.append({"ticker": ticker, "date": dt_str})
    except Exception:
        pass
    return out


def collect_economic_calendar() -> list[dict]:
    """Best-effort macro calendar — Finnhub if key set, otherwise empty."""
    try:
        import os
        api_key = os.environ.get("FINNHUB_API_KEY", "")
        if not api_key:
            return []
        import httpx
        today = date.today().isoformat()
        url = f"https://finnhub.io/api/v1/calendar/economic?from={today}&to={today}&token={api_key}"
        r = httpx.get(url, timeout=10.0)
        if r.status_code == 200:
            d = r.json() or {}
            events = d.get("economicCalendar", [])
            return [
                {
                    "time": e.get("time"),
                    "event": e.get("event"),
                    "country": e.get("country"),
                    "impact": e.get("impact"),
                    "actual": e.get("actual"),
                    "estimate": e.get("estimate"),
                    "prev": e.get("prev"),
                }
                for e in (events or [])[:20]
            ]
    except Exception as e:
        log.debug("economic calendar fetch failed: %s", e)
    return []


# ─────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────


async def build_prep_pack(
    brain,
    watchlist_tickers: Optional[list[str]] = None,
) -> dict:
    """Collect all blocks. Returns prep pack dict + persists to disk."""
    PREP_DIR.mkdir(parents=True, exist_ok=True)
    started = time.time()

    if watchlist_tickers is None:
        try:
            from runtime.api.routes import WATCHLIST_TICKERS  # type: ignore
            watchlist_tickers = list(WATCHLIST_TICKERS or [])
        except Exception:
            watchlist_tickers = []

    # Fire all yfinance + I/O collectors concurrently
    futures_task = _collect_yf_block("futures", _yf_futures_blocking)
    vix_task = _collect_yf_block("vix", _yf_vix_blocking)
    movers_task = _collect_yf_block("movers", _yf_overnight_movers_blocking, watchlist_tickers)
    headlines_task = collect_headlines(brain)
    polymarket_task = collect_polymarket_leading(brain)
    held_task = collect_held_positions(brain)
    wc_task = collect_working_context(brain)

    # Wave 14I — Capital Rotation block: sector quadrants + breadth +
    # style ratios + cycle phase. Each collector is independently
    # fallable; empty blocks don't fail the pack.
    async def _rotation_task():
        try:
            from .rotation_tracker import build_rotation_snapshot
            return await build_rotation_snapshot()
        except Exception as e:
            log.warning("[brief_prep] rotation snapshot failed: %s", e)
            return None

    async def _style_task():
        try:
            from .style_ratios import build_style_snapshot
            return await build_style_snapshot()
        except Exception as e:
            log.warning("[brief_prep] style ratios failed: %s", e)
            return None

    async def _cycle_task():
        try:
            from .cycle_phase import build_cycle_phase_snapshot
            return await build_cycle_phase_snapshot()
        except Exception as e:
            log.warning("[brief_prep] cycle phase failed: %s", e)
            return None

    futures, vix, movers, headlines, polymarket, held, wc, rotation, style, cycle = await asyncio.gather(
        futures_task, vix_task, movers_task, headlines_task,
        polymarket_task, held_task, wc_task,
        _rotation_task(), _style_task(), _cycle_task(),
        return_exceptions=False,
    )

    pack = {
        "date": date.today().isoformat(),
        "built_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": None,  # filled at end
        "futures": futures or {},
        "vix_term_structure": vix or {},
        "overnight_movers": movers or {"gainers": [], "losers": []},
        "headlines": headlines or [],
        "options_flow_yesterday": collect_options_flow_yesterday(),
        "economic_calendar": collect_economic_calendar(),
        "earnings_today": collect_earnings_today(),
        "polymarket_leading": polymarket or [],
        "held_positions": held or [],
        "working_context": wc or {},
        "night_watch_summary": collect_night_watch_summary(),
        # Wave 14I — Capital Rotation block.
        "rotation_snapshot": rotation,
        "style_ratios": style,
        "cycle_phase": cycle,
    }
    pack["elapsed_s"] = round(time.time() - started, 1)

    # Persist
    path = PREP_DIR / f"{pack['date']}.json"
    try:
        path.write_text(json.dumps(pack, indent=2, default=str))
        log.info("[brief_prep] wrote %s (%d bytes, elapsed %.1fs)",
                 path, path.stat().st_size, pack["elapsed_s"])
    except Exception as e:
        log.warning("[brief_prep] persist failed: %s", e)

    return pack


def load_latest_prep_pack() -> Optional[dict]:
    """Return today's prep pack if it exists."""
    today = date.today().isoformat()
    path = PREP_DIR / f"{today}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


__all__ = ["build_prep_pack", "load_latest_prep_pack", "PREP_DIR"]
