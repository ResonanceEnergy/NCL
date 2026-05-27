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


# ── Wave 14S — new collectors for the 12-block enriched brief ─────────

async def _collect_portfolio_snapshot(brain) -> dict:
    """Live portfolio aggregate (multi-broker, paper-only when offline)."""
    try:
        from runtime.portfolio.portfolio_manager import get_portfolio_manager
        pm = get_portfolio_manager()
        if pm is None:
            return {"connected": False}
        summary = pm.get_summary() if hasattr(pm, "get_summary") else {}
        return {
            "connected": True,
            "total_value_cad": summary.get("total_equity_cad", 0),
            "total_value_usd": summary.get("total_equity_usd", 0),
            "fx_rate_usd_cad": summary.get("fx_rate_usd_cad"),
            "positions_count": summary.get("positions_count", 0),
            "daily_pl": summary.get("daily_pl"),
            "daily_pl_pct": summary.get("daily_pl_pct"),
            "quotes_failed": summary.get("quotes_failed", 0),
        }
    except Exception as e:
        log.debug("[brief_prep] portfolio snapshot failed: %s", e)
        return {"error": str(e)}


async def _collect_agent_snapshot(brain) -> dict:
    """Auto-trader state, top strategies, recent closes."""
    try:
        from runtime.portfolio.auto_trader import get_state, get_bandit
        s = await get_state()
        bandit = get_bandit()
        top_strats = bandit.ranked_by_credible_lower_bound()[:5] \
            if bandit and hasattr(bandit, "ranked_by_credible_lower_bound") else []
        return {
            "active": s.active,
            "paused_by": s.paused_by,
            "ideas_today": {
                "evaluated": s.ideas_evaluated_today,
                "opened": s.ideas_opened_today,
                "rejected": s.ideas_rejected_today,
            },
            "top_strategies_lcb": top_strats,
            "last_loop_tick_iso": s.last_loop_tick_iso,
        }
    except Exception as e:
        log.debug("[brief_prep] agent snapshot failed: %s", e)
        return {"error": str(e)}


async def _collect_goat_top(watchlist: list) -> dict:
    """Latest persisted GOAT scan + top 5 candidates."""
    return _load_latest_scanner_jsonl("goat", "goat_score", k=5)


async def _collect_bravo_top(watchlist: list) -> dict:
    """Latest persisted BRAVO scan + top 5 candidates."""
    return _load_latest_scanner_jsonl("bravo", "bravo_score", k=5)


def _load_latest_scanner_jsonl(name: str, score_key: str, k: int = 5) -> dict:
    """Read the most recent scanners/{name}-YYYY-MM-DD.jsonl + return top-k."""
    try:
        from pathlib import Path as _Path
        scan_dir = _Path(NCL_BASE) / "data" / "scanners"
        if not scan_dir.exists():
            return {"count": 0, "items": [], "scan_date": None}
        files = sorted(scan_dir.glob(f"{name}-*.jsonl"), reverse=True)
        if not files:
            return {"count": 0, "items": [], "scan_date": None}
        items = []
        with files[0].open() as f:
            for ln in f:
                try:
                    items.append(json.loads(ln))
                except Exception:
                    continue
        items.sort(key=lambda r: r.get(score_key, 0), reverse=True)
        return {
            "count": len(items),
            "scan_date": files[0].stem.split("-", 1)[-1],
            "items": [
                {
                    "ticker": r.get("ticker"),
                    "score": r.get(score_key),
                    "price": r.get("price"),
                    "stop_loss": r.get("stop_loss"),
                    "target_1": r.get("target_1"),
                    "signal": r.get("signal_label"),
                    "rotation_aligned": r.get("rotation_aligned"),
                    "sector": r.get("sector"),
                }
                for r in items[:k]
            ],
        }
    except Exception as e:
        log.debug("[brief_prep] scanner load %s failed: %s", name, e)
        return {"count": 0, "items": [], "error": str(e)}


async def _collect_options_flow_now(brain) -> dict:
    """Latest options-flow snapshot from /portfolio/options-flow source."""
    try:
        # The options-flow endpoint reads from awarebot Unusual Whales signal cache
        from pathlib import Path as _Path
        of_dir = _Path(NCL_BASE) / "data" / "intelligence" / "options_flow"
        if not of_dir.exists():
            return {"count": 0, "rows": []}
        files = sorted(of_dir.glob("*.json"), reverse=True)
        if not files:
            return {"count": 0, "rows": []}
        data = json.loads(files[0].read_text())
        rows = data if isinstance(data, list) else data.get("rows", [])
        return {"count": len(rows), "rows": rows[:5]}
    except Exception as e:
        return {"count": 0, "rows": [], "error": str(e)}


async def _collect_crypto_movers() -> dict:
    """Top crypto movers from awarebot crypto signals (CoinGecko/Coinpaprika)."""
    try:
        from pathlib import Path as _Path
        agent_jsonl = _Path(NCL_BASE) / "data" / "intelligence" / "agent_signals.jsonl"
        if not agent_jsonl.exists():
            return {"count": 0, "items": []}
        crypto_signals = []
        with agent_jsonl.open() as f:
            for ln in f:
                try:
                    sig = json.loads(ln)
                    src = (sig.get("source") or "").lower()
                    if "crypto" in src or "coingecko" in src or "coinpaprika" in src:
                        crypto_signals.append(sig)
                except Exception:
                    continue
        crypto_signals.sort(key=lambda s: s.get("composite_score", 0), reverse=True)
        return {
            "count": len(crypto_signals),
            "items": [
                {
                    "title": s.get("title") or s.get("content", "")[:80],
                    "source": s.get("source"),
                    "score": s.get("composite_score"),
                }
                for s in crypto_signals[:5]
            ],
        }
    except Exception as e:
        return {"count": 0, "items": [], "error": str(e)}


async def _collect_polymarket_edges() -> dict:
    """Wave 14R polymarket-agent edge engine output (predictions vs market)."""
    try:
        from runtime.portfolio.polymarket_agent.collector_loop import read_today_cache
        from runtime.portfolio.polymarket_agent.edge_engine import compute_edges
        markets = read_today_cache()
        edges = compute_edges(markets) if markets else []
        return {
            "count": len(edges),
            "market_cache_count": len(markets),
            "items": [
                {
                    "market_question": e.market_question[:80],
                    "side": e.side,
                    "edge_pp": e.edge_pp,
                    "market_yes_price": e.market_yes_price,
                    "days_to_resolution": e.days_to_resolution,
                    "prediction_title": (e.prediction_title or "")[:80],
                }
                for e in edges[:5]
            ],
        }
    except Exception as e:
        return {"count": 0, "items": [], "error": str(e)}


async def _collect_predictions_top() -> dict:
    """Top predictions sorted by confidence (Wave 14Q stated_probability)."""
    try:
        from pathlib import Path as _Path
        pred_dir = _Path(NCL_BASE) / "data" / "predictions"
        if not pred_dir.exists():
            return {"count": 0, "items": []}
        # Look at last 48h of prediction files
        cutoff = time.time() - (48 * 3600)
        preds = []
        for f in pred_dir.glob("pred-*.json"):
            if f.stat().st_mtime < cutoff:
                continue
            try:
                d = json.loads(f.read_text())
                if isinstance(d, dict):
                    preds.append(d)
                elif isinstance(d, list):
                    preds.extend(d)
            except Exception:
                continue
        preds.sort(
            key=lambda p: (p.get("confidence", 0) or p.get("stated_probability", 0) or 0),
            reverse=True,
        )
        return {
            "count": len(preds),
            "items": [
                {
                    "title": p.get("title") or p.get("description", "")[:80],
                    "confidence": p.get("confidence"),
                    "stated_probability": p.get("stated_probability"),
                    "direction": p.get("direction"),
                    "forecast_window_days": p.get("forecast_window_days"),
                    "topic": p.get("topic"),
                }
                for p in preds[:5]
            ],
        }
    except Exception as e:
        return {"count": 0, "items": [], "error": str(e)}


async def _collect_ytc_recent() -> dict:
    """Recent YouTube Council reports."""
    try:
        from pathlib import Path as _Path
        ytc_dir = _Path(NCL_BASE) / "intelligence-scan" / "council-reports"
        if not ytc_dir.exists():
            return {"count": 0, "items": []}
        cutoff = time.time() - (36 * 3600)
        reports = []
        # Per-date subfolders
        for p in sorted(ytc_dir.rglob("*.md"), reverse=True):
            if p.stat().st_mtime < cutoff:
                continue
            reports.append({
                "filename": p.name,
                "modified_iso": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
                "size_bytes": p.stat().st_size,
            })
            if len(reports) >= 8:
                break
        return {"count": len(reports), "items": reports}
    except Exception as e:
        return {"count": 0, "items": [], "error": str(e)}


async def _collect_todo_7day(brain) -> dict:
    """Calendar watchlist for next 7 days — pulls from CalendarAgent."""
    try:
        from runtime.calendar.watchlist import build_watchlist
        wl = await build_watchlist(window_days=7) if callable(build_watchlist) else {}
        return wl if isinstance(wl, dict) else {"items": []}
    except Exception as e:
        # Fallback: read calendar/watchlist endpoint output if persisted
        try:
            from pathlib import Path as _Path
            cal_dir = _Path(NCL_BASE) / "data" / "calendar"
            files = sorted(cal_dir.glob("watchlist-*.json"), reverse=True) if cal_dir.exists() else []
            if files:
                return json.loads(files[0].read_text())
        except Exception:
            pass
        return {"items": [], "error": str(e)}


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

    # Wave 14S — 12 new collectors in parallel for richer brief context
    futures, vix, movers, headlines, polymarket, held, wc, rotation, style, cycle, \
        portfolio_snap, agent_snap, goat_top, bravo_top, options_flow_now, \
        crypto_movers, poly_edges, predictions_top, ytc_recent, todo_7day = await asyncio.gather(
        futures_task, vix_task, movers_task, headlines_task,
        polymarket_task, held_task, wc_task,
        _rotation_task(), _style_task(), _cycle_task(),
        _collect_portfolio_snapshot(brain),
        _collect_agent_snapshot(brain),
        _collect_goat_top(watchlist_tickers),
        _collect_bravo_top(watchlist_tickers),
        _collect_options_flow_now(brain),
        _collect_crypto_movers(),
        _collect_polymarket_edges(),
        _collect_predictions_top(),
        _collect_ytc_recent(),
        _collect_todo_7day(brain),
        return_exceptions=False,
    )

    now_iso = datetime.now(timezone.utc).isoformat()

    def _block(name: str, data, endpoint: str, count_key: str = None):
        """Wrap a block with timestamp + provenance for the brief executor.
        Hallucination guard: every claim in the brief should cite a
        block_id that exists in this prep pack."""
        return {
            "block_id": name,
            "data": data,
            "generated_at_iso": now_iso,
            "source_endpoint": endpoint,
            "item_count": (
                len(data) if isinstance(data, list)
                else (data.get(count_key) if isinstance(data, dict) and count_key else 1)
                if isinstance(data, dict) else 0
            ),
        }

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
        # ── Wave 14S — 12 new context blocks for the full daily picture ─
        "PORTFOLIO": _block("PORTFOLIO", portfolio_snap, "/portfolio/summary"),
        "AGENT": _block("AGENT", agent_snap, "/portfolio/auto-trader/dashboard"),
        "ROTATION": _block("ROTATION", rotation, "/intelligence/rotation"),
        "GOAT": _block("GOAT", goat_top, "/stocks/scanner/goat", "count"),
        "BRAVO": _block("BRAVO", bravo_top, "/stocks/scanner/bravo", "count"),
        "OPTIONS": _block("OPTIONS", options_flow_now, "/portfolio/options-flow"),
        "CRYPTO": _block("CRYPTO", crypto_movers, "intelligence/crypto"),
        "POLYMARKET": _block(
            "POLYMARKET", poly_edges, "/portfolio/polymarket-agent/edges"
        ),
        "PREDICTIONS": _block(
            "PREDICTIONS", predictions_top, "/predictions?sort=confidence"
        ),
        "YTC": _block("YTC", ytc_recent, "/youtube/reports/recent"),
        "CONTEXT": _block(
            "CONTEXT", (wc or {}).get("items", [])[:10], "/memory/working-context"
        ),
        "TODO_7DAY": _block("TODO_7DAY", todo_7day, "/calendar/watchlist"),
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
