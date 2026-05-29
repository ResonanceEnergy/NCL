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
from typing import Optional


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
            rows.append(
                {
                    "ticker": ticker,
                    "last": round(last, 2),
                    "prev": round(prev, 2),
                    "pct": round(pct, 2),
                }
            )
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
                if not any(
                    k in (category + source).lower()
                    for k in ("news", "headline", "reuters", "bloomberg", "rss", "x_twitter")
                ):
                    continue
                title = (getattr(s, "title", "") or "")[:200]
                if not title or title.lower() in seen_titles:
                    continue
                seen_titles.add(title.lower())
                out.append(
                    {
                        "title": title,
                        "source": source,
                        "sig_id": (getattr(s, "signal_id", "") or "")[:8],
                        "captured_at": str(ts) if ts else None,
                    }
                )
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
                {
                    "ticker": r.get("ticker"),
                    "score": r.get(f"{scanner}_score"),
                    "price": r.get("price"),
                }
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
                leading.append(
                    {
                        "title": (getattr(s, "title", "") or "")[:140],
                        "yes_price": getattr(s, "yes_price", None),
                        "no_price": getattr(s, "no_price", None),
                        "volume_24h": getattr(s, "volume_24h", None),
                        "sig_id": (getattr(s, "signal_id", "") or "")[:8],
                    }
                )
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
    """Pull live WC items. The actual WorkingContext lives on the
    autonomous scheduler at `autonomous._working_context`, NOT on brain.
    `get_current()` returns the assembled DailyContext."""
    try:
        wc = None
        # Try a few places — autonomous scheduler is the source of truth
        try:
            from runtime.api.routes import _autonomous as _auton

            if _auton is not None:
                wc = getattr(_auton, "_working_context", None)
        except Exception:
            pass
        if wc is None and brain is not None:
            wc = getattr(brain, "_working_context_ref", None) or getattr(
                brain, "working_context", None
            )
        if wc is None:
            return {}

        # The DailyContext object — produced by .assemble() and cached
        ctx = wc.get_current() if hasattr(wc, "get_current") else None
        if ctx is None:
            # Try assembling now if nothing cached
            if hasattr(wc, "assemble"):
                try:
                    ctx = await wc.assemble()
                except Exception:
                    ctx = None
        if ctx is None:
            return {}

        # ctx.items is list[ContextItem]; .themes is list[str]
        raw_items = getattr(ctx, "items", []) or []
        themes = getattr(ctx, "themes", []) or []
        snap = {
            "themes": list(themes),
            "items": [it.to_dict() for it in raw_items if hasattr(it, "to_dict")],
        }
        items = snap.get("items") or []
        # Pinned bucket — those explicitly flagged
        pinned = [
            {"text": (i.get("content") or "")[:200], "category": i.get("category", "")}
            for i in items
            if (i.get("category") == "pinned" or i.get("kind") == "pinned")
        ][:8]
        # Top items by salience as fallback "what's on the brain right now"
        top_items = sorted(
            items,
            key=lambda i: float(i.get("salience_score", 0) or 0),
            reverse=True,
        )[:10]
        top_payload = [
            {
                "text": (i.get("content") or "")[:200],
                "category": i.get("category", ""),
                "salience": round(float(i.get("salience_score", 0) or 0), 3),
            }
            for i in top_items
        ]
        return {
            "themes": snap.get("themes", [])[:8],
            "pinned_priorities": pinned,
            "top_by_salience": top_payload,
            "total_items": len(items),
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
        pass  # type: ignore
    except Exception:
        return out
    try:
        # Use the cached map if available
        from runtime.stocks.enrichments import _EARNINGS_CACHE_KEY, _cache_get  # type: ignore

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
    """Live broker portfolio ONLY. No paper fallback.

    Per NATRIX 2026-05-27: do NOT fall back to paper engine here — PORTFOLIO
    must reflect the REAL multi-broker book. If brokers are offline, surface
    a clear error so the operator knows the broker stack is down and can
    inspect /portfolio/summary directly.
    """
    out: dict = {"connected": False}
    try:
        from runtime.portfolio.portfolio_manager import get_portfolio_manager

        pm = get_portfolio_manager()
        if pm is None:
            return {
                "connected": False,
                "error": "portfolio_manager not initialized — check broker adapter "
                         "boot in start-all.sh + IBKR/Moomoo/SnapTrade env vars",
            }
        summary = pm.get_summary() if hasattr(pm, "get_summary") else {}
        total_val = summary.get("total_equity_cad", 0) or summary.get("total_equity_usd", 0)
        if not total_val or total_val <= 0:
            return {
                "connected": False,
                "error": "broker adapters returned NAV=0 — likely IBKR/Moomoo "
                         "disconnect or SnapTrade auth expired. Check "
                         "/portfolio/accounts for per-broker status.",
                "raw_summary_keys": list(summary.keys())[:10],
            }
        out.update(
            {
                "connected": True,
                "mode": "live_broker",
                "total_value_cad": summary.get("total_equity_cad", 0),
                "total_value_usd": summary.get("total_equity_usd", 0),
                "fx_rate_usd_cad": summary.get("fx_rate_usd_cad"),
                "positions_count": summary.get("positions_count", 0),
                "daily_pl": summary.get("daily_pl"),
                "daily_pl_pct": summary.get("daily_pl_pct"),
                "quotes_failed": summary.get("quotes_failed", 0),
            }
        )
        return out
    except Exception as e:
        log.warning("[brief_prep] portfolio snapshot failed: %s", e)
        return {"connected": False, "error": f"portfolio_manager exception: {e}"}


async def _collect_agent_snapshot(brain) -> dict:
    """Auto-trader state, top strategies, recent closes."""
    try:
        from runtime.portfolio.auto_trader import get_bandit, get_state

        s = await get_state()
        bandit = get_bandit()
        top_strats = (
            bandit.ranked_by_credible_lower_bound()[:5]
            if bandit and hasattr(bandit, "ranked_by_credible_lower_bound")
            else []
        )
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
    """Latest options-flow from agent_signals.jsonl (source=='options_flow').

    Pulls last 24h, groups by ticker, ranks by total premium. Mirrors the
    parse the /portfolio/options-flow endpoint uses so the brief shows the
    same numbers the iOS OPTIONS tab does.
    """
    import re as _re
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from datetime import timezone as _tz
    from pathlib import Path as _Path

    _TITLE_RE = _re.compile(
        r"^([A-Z][A-Z0-9.]{0,8})\s+flow alert:\s*\$?([\d,]+)\s*\(\s*(\d+)\s*contracts?\)",
        _re.IGNORECASE,
    )

    try:
        sig_file = _Path(NCL_BASE) / "data" / "intelligence" / "agent_signals.jsonl"
        if not sig_file.exists():
            return {"count": 0, "rows": [], "source": "agent_signals.jsonl missing"}

        cutoff = _dt.now(_tz.utc) - _td(hours=24)
        # Tail last ~4MB for perf
        with sig_file.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 4 * 1024 * 1024))
            if size > 4 * 1024 * 1024:
                f.readline()
            lines = f.read().decode("utf-8", errors="ignore").splitlines()

        per_ticker: dict[str, dict] = {}
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                sig = json.loads(line)
            except Exception:
                continue
            if sig.get("source") != "options_flow":
                continue
            ts_str = sig.get("timestamp") or ""
            if ts_str:
                try:
                    ts = _dt.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except Exception:
                    pass
            m = _TITLE_RE.match(sig.get("title") or "")
            if not m:
                continue
            ticker = m.group(1).upper()
            try:
                premium = float(m.group(2).replace(",", ""))
                contracts = int(m.group(3))
            except Exception:
                continue
            row = per_ticker.setdefault(
                ticker,
                {
                    "ticker": ticker,
                    "total_premium": 0.0,
                    "trade_count": 0,
                    "contracts": 0,
                    "top_premium": 0.0,
                    "dir": sig.get("direction", "neutral"),
                },
            )
            row["total_premium"] += premium
            row["trade_count"] += 1
            row["contracts"] += contracts
            row["top_premium"] = max(row["top_premium"], premium)

        rows = sorted(per_ticker.values(), key=lambda r: r["total_premium"], reverse=True)[:10]
        return {
            "count": len(per_ticker),
            "lookback_hours": 24,
            "rows": [
                {
                    "ticker": r["ticker"],
                    "total_premium": round(r["total_premium"], 0),
                    "trade_count": r["trade_count"],
                    "contracts": r["contracts"],
                    "top_single_premium": round(r["top_premium"], 0),
                    "direction": r["dir"],
                }
                for r in rows
            ],
        }
    except Exception as e:
        return {"count": 0, "rows": [], "error": str(e)}


def _yf_crypto_blocking() -> dict:
    """Direct yfinance fetch of 10 major crypto pairs — CoinGecko-free.

    Awarebot's crypto scanner is disabled per CLAUDE.md (CoinGecko rate
    limits caused 60s+ delays), so we go to yfinance directly with the
    same fast_info path the futures collector uses.
    """
    out: list[dict] = []
    try:
        import yfinance as yf
    except ImportError:
        return {"count": 0, "items": [], "source": "yfinance missing"}

    pairs = [
        ("BTC-USD", "Bitcoin"),
        ("ETH-USD", "Ethereum"),
        ("SOL-USD", "Solana"),
        ("BNB-USD", "BNB"),
        ("XRP-USD", "XRP"),
        ("DOGE-USD", "Dogecoin"),
        ("ADA-USD", "Cardano"),
        ("AVAX-USD", "Avalanche"),
        ("LINK-USD", "Chainlink"),
        ("MATIC-USD", "Polygon"),
    ]
    for sym, name in pairs:
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="2d")
            if hist.empty or len(hist) < 2:
                continue
            last = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2])
            if prev <= 0:
                continue
            pct = ((last - prev) / prev) * 100
            vol = float(hist["Volume"].iloc[-1]) if "Volume" in hist.columns else 0.0
            out.append(
                {
                    "symbol": sym,
                    "name": name,
                    "last": round(last, 2 if last >= 1 else 4),
                    "pct_24h": round(pct, 2),
                    "volume_24h_usd": round(vol, 0),
                }
            )
        except Exception:
            continue
    # Sort by |%change| desc — surface the biggest movers
    out.sort(key=lambda r: abs(r["pct_24h"]), reverse=True)
    return {"count": len(out), "items": out[:8], "source": "yfinance"}


async def _collect_crypto_movers() -> dict:
    """Top crypto movers via yfinance (CoinGecko fallback removed)."""
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, _yf_crypto_blocking)
    except Exception as e:
        return {"count": 0, "items": [], "error": str(e)}


async def _collect_polymarket_edges() -> dict:
    """Wave 14R polymarket-agent edge engine output (predictions vs market).

    If the edge engine returns 0 (no edges meet threshold today), fall back
    to surfacing the top-5 highest-volume active polymarket signals from
    agent_signals.jsonl so the brief always has some polymarket context.
    """
    edges_data = []
    market_cache_count = 0
    edge_engine_error = None
    try:
        from runtime.portfolio.polymarket_agent.collector_loop import read_today_cache
        from runtime.portfolio.polymarket_agent.edge_engine import compute_edges

        markets = read_today_cache()
        market_cache_count = len(markets) if markets else 0
        edges = compute_edges(markets) if markets else []
        edges_data = [
            {
                "market_question": e.market_question[:80],
                "side": e.side,
                "edge_pp": e.edge_pp,
                "market_yes_price": e.market_yes_price,
                "days_to_resolution": e.days_to_resolution,
                "prediction_title": (e.prediction_title or "")[:80],
            }
            for e in edges[:5]
        ]
    except Exception as e:
        edge_engine_error = str(e)

    # Fallback: top active polymarket signals from agent_signals.jsonl
    fallback_items = []
    if not edges_data:
        try:
            from datetime import datetime as _dt
            from datetime import timedelta as _td
            from datetime import timezone as _tz
            from pathlib import Path as _Path

            sig_file = _Path(NCL_BASE) / "data" / "intelligence" / "agent_signals.jsonl"
            if sig_file.exists():
                cutoff = _dt.now(_tz.utc) - _td(hours=24)
                # tail last 4MB
                with sig_file.open("rb") as f:
                    f.seek(0, 2)
                    size = f.tell()
                    f.seek(max(0, size - 4 * 1024 * 1024))
                    if size > 4 * 1024 * 1024:
                        f.readline()
                    lines = f.read().decode("utf-8", errors="ignore").splitlines()
                poly_signals = []
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        sig = json.loads(line)
                    except Exception:
                        continue
                    if sig.get("source") != "polymarket":
                        continue
                    ts_str = sig.get("timestamp") or ""
                    if ts_str:
                        try:
                            ts = _dt.fromisoformat(ts_str.replace("Z", "+00:00"))
                            if ts < cutoff:
                                continue
                        except Exception:
                            pass
                    meta = sig.get("metadata") or {}
                    # Skip resolved/dead markets
                    lc = (meta.get("lifecycle_status") or "").lower()
                    if lc == "resolved":
                        continue
                    poly_signals.append(sig)
                # Sort by importance (which factors volume) desc
                poly_signals.sort(key=lambda s: s.get("importance", 0) or 0, reverse=True)
                fallback_items = [
                    {
                        "market_question": (s.get("title") or "")[:90],
                        "lifecycle": (s.get("metadata") or {}).get("lifecycle_status", "active"),
                        "importance": s.get("importance"),
                        "url": s.get("url"),
                    }
                    for s in poly_signals[:5]
                ]
        except Exception as e:
            edge_engine_error = (edge_engine_error or "") + f" | fallback: {e}"

    return {
        "count": len(edges_data) if edges_data else len(fallback_items),
        "market_cache_count": market_cache_count,
        "mode": "edges" if edges_data else ("fallback_signals" if fallback_items else "empty"),
        "items": edges_data if edges_data else fallback_items,
        "error": edge_engine_error,
    }


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
            reports.append(
                {
                    "filename": p.name,
                    "modified_iso": datetime.fromtimestamp(
                        p.stat().st_mtime, tz=timezone.utc
                    ).isoformat(),
                    "size_bytes": p.stat().st_size,
                }
            )
            if len(reports) >= 8:
                break
        return {"count": len(reports), "items": reports}
    except Exception as e:
        return {"count": 0, "items": [], "error": str(e)}


async def _collect_todo_7day(brain) -> dict:
    """Calendar watchlist for next 7 days — pulls from CalendarAgent.

    build_watchlist returns [] without moon_phase/cycle_context/brain_client
    — the moon block produces no todos and every brain-call branch is
    short-circuited. Supply all three so we get real items.
    """
    try:
        from runtime.calendar.lunar import get_cycle_context, get_moon_phase
        from runtime.calendar.watchlist import build_watchlist

        # Moon + cycle don't need brain — pure ephemeris.
        try:
            moon_phase = get_moon_phase()
        except Exception:
            moon_phase = None
        try:
            cycle_context = get_cycle_context()
        except Exception:
            cycle_context = None

        # Brain-internal HTTP client — watchlist's _sync_brain_call
        # builds the actual httpx wrapper, it just needs a truthy obj
        # to short-circuit the "no client" branches.
        brain_client_proxy = brain  # truthy; downstream uses STRIKE_TOKEN

        todos = await build_watchlist(
            brain_client=brain_client_proxy,
            moon_phase=moon_phase,
            cycle_context=cycle_context,
        )
        if isinstance(todos, list):
            # Sort by priority desc (5=highest in this module), then urgency
            urgency_order = {"now": 0, "today": 1, "this_week": 2}
            todos.sort(
                key=lambda t: (
                    -t.get("priority", 0),
                    urgency_order.get(t.get("urgency", "today"), 1),
                )
            )
            return {
                "items": todos[:15],
                "count": len(todos),
                "moon_phase": (moon_phase or {}).get("phase_name"),
                "energy_mode": (moon_phase or {}).get("energy_mode"),
            }
        return {"items": [], "count": 0}
    except Exception as e:
        return {"items": [], "count": 0, "error": str(e)}


async def collect_situational_context(brain) -> dict:
    """Wave 14X-Y Phase 1B-4 (2026-05-29) — assemble NATRIX's situational
    awareness for the morning brief + AWAREBOT scoring.

    Returns:
      {
        "lunar": {phase_name, energy_mode, day_of_cycle},
        "calendar_today": [...],       # events on today's calendar
        "tickers_with_event_today": [...],
        "journal_posture": {            # from morning quiz
            "priority": str, "research_question": str, "lesson": str
        },
        "tickers_in_journal_today": [...],
      }

    Never raises — degrades to empty blocks if subsystems are missing.
    """
    import re as _re

    out: dict = {
        "lunar": {},
        "calendar_today": [],
        "tickers_with_event_today": [],
        "journal_posture": {},
        "tickers_in_journal_today": [],
    }

    # Lunar (pure ephemeris)
    try:
        from runtime.calendar.lunar import get_moon_phase
        moon = get_moon_phase() or {}
        out["lunar"] = {
            "phase_name": moon.get("phase_name"),
            "energy_mode": moon.get("energy_mode"),
            "day_of_cycle": moon.get("day_of_cycle"),
        }
    except Exception as e:
        log.debug("[brief_prep] lunar collector failed: %s", e)

    # Today's calendar events (FOMC, OPEX, earnings) — read via watchlist
    try:
        from runtime.calendar.watchlist import build_watchlist
        todos = await build_watchlist(brain_client=brain) or []
        today_iso = date.today().isoformat()
        today_events = [
            t for t in todos
            if isinstance(t, dict) and (t.get("date", "") or "").startswith(today_iso)
        ][:10]
        out["calendar_today"] = [
            {"title": t.get("title", ""), "category": t.get("category", "")}
            for t in today_events
        ]
        # Ticker extraction from event titles
        tx: set[str] = set()
        for t in today_events:
            for m in _re.finditer(r"\$([A-Z]{1,5})", t.get("title", "")):
                tx.add(m.group(1))
        out["tickers_with_event_today"] = sorted(tx)
    except Exception as e:
        log.debug("[brief_prep] calendar today collector failed: %s", e)

    # Today's morning quiz (NATRIX's stated posture)
    try:
        from runtime.journal.morning_quiz import load_today_quiz
        q = load_today_quiz() or {}
        if q:
            out["journal_posture"] = {
                "priority": q.get("top_priority", ""),
                "research_question": q.get("research_question", ""),
                "lesson": q.get("lesson_from_yesterday", ""),
            }
            # Ticker extraction from quiz text
            txt = " ".join([
                q.get("top_priority", ""),
                q.get("research_question", ""),
                q.get("lesson_from_yesterday", ""),
                q.get("posture", ""),
            ])
            tj: set[str] = set()
            for m in _re.finditer(r"\$?([A-Z]{2,5})\b", txt):
                tok = m.group(1)
                if tok not in {"THE", "AND", "USD", "ETF", "VIX", "CPI", "FOMC"}:
                    tj.add(tok)
            out["tickers_in_journal_today"] = sorted(tj)
    except Exception as e:
        log.debug("[brief_prep] journal posture collector failed: %s", e)

    return out


async def collect_local_events(city: str = "edmonton") -> dict:
    """Wave 14AA-2: pull Ticketmaster + holidays + curated local events
    from the calendar backend for NATRIX's primary city. Default Edmonton.
    Returns {today: [], week: []}. Never raises.
    """
    from datetime import timedelta
    out = {"today": [], "week": []}
    try:
        from runtime.calendar.local_events import get_local_events  # type: ignore
        start = date.today()
        end = start + timedelta(days=7)
        events = await get_local_events(city, start, end) or []
        today_str = start.isoformat()

        def _event_date_str(e: dict) -> str:
            d = e.get("date")
            if d is None:
                return ""
            # Normalize date / datetime / string to YYYY-MM-DD.
            if hasattr(d, "isoformat"):
                return d.isoformat()[:10]
            return str(d)[:10]

        out["today"] = [e for e in events if _event_date_str(e) == today_str]
        # Stringify date on every event before persistence (JSON will
        # otherwise choke on date objects during pack save).
        for e in events:
            if hasattr(e.get("date"), "isoformat"):
                e["date"] = e["date"].isoformat()[:10]
        out["week"] = events
    except Exception as e:
        log.warning("[brief_prep] local_events collector failed: %s", e)
    return out


async def collect_yesterday_recap() -> dict:
    """Wave 14X-1B: NATRIX's closed-loop fix for "the Brief got weak".

    Reads yesterday's auto-trader EOD summary + reads yesterday's brief
    output to find how many trade ideas the chair gave vs how many
    actually closed. Returns a structured recap the chair can synthesize
    into a 1-paragraph YESTERDAY'S RECAP block at the top of today's
    brief — so NATRIX can see "yesterday I was told X, here's what
    happened" before being told today's plan.

    Empty fallback (never raises) — if data is missing the recap simply
    has no data and the chair will omit the block.
    """
    out: dict = {
        "date": None,
        "ideas_given": None,
        "closes_today": 0,
        "winners": 0,
        "losers": 0,
        "scratches": 0,
        "total_r": 0.0,
        "tickers_closed": [],
        "drift_signals": [],
        "agent_narrative": "",
        "lesson": None,
    }

    try:
        eod_path = NCL_BASE / "data" / "portfolio" / "auto_trader" / "eod_summaries.jsonl"
        if eod_path.exists():
            # Walk last 30 lines, pick most-recent entry whose date < today
            today_iso = date.today().isoformat()
            with open(eod_path, "r") as fh:
                lines = fh.readlines()
            for raw in reversed(lines[-30:]):
                try:
                    d = json.loads(raw.strip())
                except json.JSONDecodeError:
                    continue
                if d.get("date") and d["date"] < today_iso:
                    out["date"] = d.get("date")
                    out["closes_today"] = d.get("closes_today", 0)
                    out["winners"] = d.get("winners", 0)
                    out["losers"] = d.get("losers", 0)
                    out["scratches"] = d.get("scratches", 0)
                    out["total_r"] = d.get("total_r_today", 0.0)
                    out["tickers_closed"] = d.get("tickers_closed", [])
                    out["drift_signals"] = d.get("drift_signals", [])
                    out["agent_narrative"] = d.get("narrative", "")
                    break
    except Exception as e:
        log.warning("[brief_prep] yesterday_recap eod read failed: %s", e)

    try:
        # Also try to read yesterday's brief output to count ideas given.
        out_dir = NCL_BASE / "data" / "morning-brief-pro"
        if out_dir.exists():
            files = sorted(out_dir.glob("*.json"), reverse=True)
            today_iso = date.today().isoformat()
            for f in files[:10]:
                if today_iso in f.name:
                    continue  # skip today's own brief
                try:
                    bd = json.loads(f.read_text())
                    synth = bd.get("synthesis") if isinstance(bd, dict) else None
                    ideas = synth.get("trade_ideas", []) if isinstance(synth, dict) else []
                    out["ideas_given"] = len(ideas) if isinstance(ideas, list) else 0
                    break
                except Exception:
                    continue
    except Exception as e:
        log.warning("[brief_prep] yesterday_recap brief read failed: %s", e)

    # Tiny derived lesson — if drift fired or total_r negative we surface it.
    if out["drift_signals"]:
        drifters = ", ".join(d.get("strategy", "?") for d in out["drift_signals"])[:80]
        out["lesson"] = f"Drift detected on {drifters} — review before re-enabling."
    elif (out["total_r"] or 0) < -0.5:
        out["lesson"] = f"Net losing day ({out['total_r']:+.2f}R) — check sizing + entry timing."
    elif (out["total_r"] or 0) > 1.0:
        out["lesson"] = f"Strong day ({out['total_r']:+.2f}R) — what worked? Replicate the setup."

    return out


# ─────────────────────────────────────────────────────────────────────────
# Wave 14Y — 5-lane aggregators
#
# NATRIX's mandate: every brief is exactly 5 sections in fixed order:
#   1. PORTFOLIO  — paper NAV, open positions, auto-trader activity,
#                   scanner picks, rotation alignment
#   2. INTEL      — top YTC + Reddit + X + Predictions + cross-ref
#                   promotions, ranked
#   3. CALENDAR   — today's events, lunar phase, market events,
#                   watchlist to-dos
#   4. JOURNAL    — yesterday's quiz, today's prompt, last reflection,
#                   lesson learned
#   5. MEMORY     — pinned working-context items, fresh high-importance
#                   memories, narrative threads
#
# Each lane aggregator is pure dict-reshape — never raises, returns
# {} on missing data. Chair prompt loops over this in fixed order.
# ─────────────────────────────────────────────────────────────────────────


def _as_list(x) -> list:
    """Coerce a value into a list. Handles list / dict-with-results / None."""
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        # Common scanner shapes: {results: [...]}, {data: [...]}, {items: [...]}
        for k in ("results", "data", "items", "gainers", "losers", "movers", "edges"):
            v = x.get(k)
            if isinstance(v, list):
                return v
        return []
    return []


def _lane_portfolio(pack: dict) -> dict:
    """PORTFOLIO lane: TRADERAGENT camp state."""
    agent = (pack.get("AGENT") or {}).get("data") or {}
    portfolio = (pack.get("PORTFOLIO") or {}).get("data") or {}
    goat = _as_list((pack.get("GOAT") or {}).get("data"))
    bravo = _as_list((pack.get("BRAVO") or {}).get("data"))
    options = _as_list((pack.get("OPTIONS") or {}).get("data"))
    rotation = pack.get("rotation_snapshot") or {}
    return {
        "paper_account": agent.get("status", {}) if isinstance(agent, dict) else {},
        "auto_trader_today": {
            "ideas_evaluated": agent.get("ideas_evaluated_today"),
            "opens_today": agent.get("opens_today"),
            "closes_today": agent.get("closes_today"),
            "current_streak": agent.get("current_streak"),
        } if isinstance(agent, dict) else {},
        "open_positions_summary": portfolio.get("positions_summary", {}) if isinstance(portfolio, dict) else {},
        "held_positions": pack.get("held_positions", []),
        "scanner_goat_top": goat[:5],
        "scanner_bravo_top": bravo[:5],
        "options_flow_top": options[:5],
        "rotation_leading_sectors": rotation.get("leading_quadrant", []) if isinstance(rotation, dict) else [],
        "rotation_breadth_pct": rotation.get("breadth_pct") if isinstance(rotation, dict) else None,
        "yesterday_recap": pack.get("yesterday_recap", {}),
    }


def _lane_intel(pack: dict) -> dict:
    """INTEL lane: AWAREBOT camp surfaces."""
    ytc = _as_list((pack.get("YTC") or {}).get("data"))
    predictions = _as_list((pack.get("PREDICTIONS") or {}).get("data"))
    poly = _as_list((pack.get("POLYMARKET") or {}).get("data"))
    crypto = (pack.get("CRYPTO") or {}).get("data") or {}
    headlines = _as_list(pack.get("headlines"))
    poly_leading = _as_list(pack.get("polymarket_leading"))
    return {
        "ytc_recent_top": ytc[:5],
        "predictions_active_top": predictions[:5],
        "headlines_top": headlines[:8],
        "polymarket_active_leading": poly_leading[:5],
        "polymarket_edges": poly[:5],
        "crypto_movers": crypto if isinstance(crypto, dict) else {},
        "futures": pack.get("futures", {}),
        "vix_term_structure": pack.get("vix_term_structure", {}),
        "overnight_movers": pack.get("overnight_movers", {}),
    }


def _lane_calendar(pack: dict) -> dict:
    """CALENDAR lane: time-bound context per NATRIX directive:
    Ticketmaster + local events + holidays + market events + lunar — NOT
    just financial calendar. The calendar IS NATRIX's life schedule, not
    earnings only.
    """
    sit = pack.get("situational_context") or {}
    todo = _as_list((pack.get("TODO_7DAY") or {}).get("data"))
    local = pack.get("local_events_today") or {}
    local_today = _as_list(local.get("today"))
    local_week = _as_list(local.get("week"))
    # Split local events by category for clearer rendering.
    concerts = [e for e in local_today if (e.get("category") or "").lower() in ("concert", "music")]
    sports = [e for e in local_today if (e.get("category") or "").lower() in ("sports",)]
    other_local = [e for e in local_today if e not in concerts and e not in sports]
    headlines = _as_list(pack.get("headlines"))
    # Cherry-pick general news headlines for CALENDAR (not market/ticker
    # signals — those go to INTEL). Heuristic: headlines without a stock
    # source tag are general news.
    general_news = [h for h in headlines if not str(h.get("source", "")).startswith("market:")][:6]
    return {
        # NATRIX-life events (the original mandate)
        "ticketmaster_today": concerts[:6],
        "sports_today": sports[:4],
        "local_events_today": other_local[:6],
        "local_events_week": local_week[:10],
        # General news / cultural
        "general_news": general_news,
        # Financial calendar (still useful, secondary)
        "earnings_today": _as_list(pack.get("earnings_today"))[:6],
        "economic_calendar": _as_list(pack.get("economic_calendar"))[:6],
        # Time / energy
        "lunar_phase": sit.get("lunar", {}),
        "tickers_with_event_today": _as_list(sit.get("tickers_with_event_today")),
        # NATRIX's correlated watchlist (Calendar TODO)
        "todo_7day": todo[:10],
        # Legacy field — keep for back-compat
        "today_events": _as_list(sit.get("calendar_today")),
    }


def _lane_journal(pack: dict) -> dict:
    """JOURNAL lane: NATRIX's morning quiz + posture + recent reflections."""
    sit = pack.get("situational_context") or {}
    return {
        "morning_quiz_posture": sit.get("journal_posture", {}),
        "morning_quiz_focus": sit.get("morning_quiz_focus", ""),
        "tickers_in_journal_today": sit.get("tickers_in_journal_today", []),
        # Yesterday's recap "lesson" line — bridges journal → portfolio
        "yesterday_lesson": (pack.get("yesterday_recap") or {}).get("lesson", ""),
    }


def _lane_memory(pack: dict) -> dict:
    """MEMORY lane: working context + pinned + themes."""
    wc = pack.get("working_context") or {}
    if not isinstance(wc, dict):
        wc = {}
    ctx = (pack.get("CONTEXT") or {}).get("data") or {}
    pinned = _as_list(wc.get("pinned_priorities"))
    salience = _as_list(wc.get("top_by_salience"))
    themes = _as_list(wc.get("themes"))
    return {
        "pinned_priorities": pinned[:10],
        "top_by_salience": salience[:10],
        "themes": themes[:8],
        "total_items": wc.get("total_items", 0) if isinstance(wc, dict) else 0,
        "context_summary": ctx if isinstance(ctx, dict) else {},
    }


def _build_5_lanes(pack: dict) -> dict:
    """Aggregate raw blocks into NATRIX's 5-lane structure.
    Returns a dict with keys: portfolio, intel, calendar, journal, memory.
    Every value is a dict — empty {} if data missing. Pure reshape, no I/O.
    """
    return {
        "portfolio": _lane_portfolio(pack),
        "intel": _lane_intel(pack),
        "calendar": _lane_calendar(pack),
        "journal": _lane_journal(pack),
        "memory": _lane_memory(pack),
    }


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
    (
        futures,
        vix,
        movers,
        headlines,
        polymarket,
        held,
        wc,
        rotation,
        style,
        cycle,
        portfolio_snap,
        agent_snap,
        goat_top,
        bravo_top,
        options_flow_now,
        crypto_movers,
        poly_edges,
        predictions_top,
        ytc_recent,
        todo_7day,
    ) = await asyncio.gather(
        futures_task,
        vix_task,
        movers_task,
        headlines_task,
        polymarket_task,
        held_task,
        wc_task,
        _rotation_task(),
        _style_task(),
        _cycle_task(),
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
                len(data)
                if isinstance(data, list)
                else (data.get(count_key) if isinstance(data, dict) and count_key else 1)
                if isinstance(data, dict)
                else 0
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
        "POLYMARKET": _block("POLYMARKET", poly_edges, "/portfolio/polymarket-agent/edges"),
        "PREDICTIONS": _block("PREDICTIONS", predictions_top, "/predictions?sort=confidence"),
        "YTC": _block("YTC", ytc_recent, "/youtube/reports/recent"),
        "CONTEXT": _block(
            "CONTEXT",
            {
                "pinned": (wc or {}).get("pinned_priorities", [])[:5],
                "top_by_salience": (wc or {}).get("top_by_salience", [])[:8],
                "themes": [{"text": t} for t in (wc or {}).get("themes", [])[:5]],
                "total_items": (wc or {}).get("total_items", 0),
            },
            "/memory/working-context",
        ),
        "TODO_7DAY": _block("TODO_7DAY", todo_7day, "/calendar/watchlist"),
        # Wave 14X-1B — closed-loop fix: yesterday's outcomes feed back
        # into today's brief as a YESTERDAY'S RECAP block. NATRIX's "Brief
        # got weak" diagnosis was structural — the system never showed
        # "here's what happened to yesterday's calls" before giving today's.
        "yesterday_recap": await collect_yesterday_recap(),
        # Wave 14X-Y Phase 1B-4 — situational awareness: lunar + today's
        # calendar events + NATRIX's morning quiz posture. Both chair and
        # macro analyst use this so today's brief is grounded in NATRIX's
        # current life context, not just market data.
        "situational_context": await collect_situational_context(brain),
        # Wave 14AA-2 — Ticketmaster + holidays + local events for NATRIX's
        # primary city. The CALENDAR lane should be his LIFE schedule, not
        # just financial calendar (per his directive).
        "local_events_today": await collect_local_events("edmonton"),
    }
    # Wave 14Y — 5-lane aggregators. NATRIX's vision: every brief is
    # PORTFOLIO / INTEL / CALENDAR / JOURNAL / MEMORY in that fixed order.
    # These five functions re-shape the raw blocks above into lane-
    # organized buckets the chair consumes directly.
    pack["lanes"] = _build_5_lanes(pack)
    pack["elapsed_s"] = round(time.time() - started, 1)

    # Persist
    path = PREP_DIR / f"{pack['date']}.json"
    try:
        path.write_text(json.dumps(pack, indent=2, default=str))
        log.info(
            "[brief_prep] wrote %s (%d bytes, elapsed %.1fs)",
            path,
            path.stat().st_size,
            pack["elapsed_s"],
        )
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
