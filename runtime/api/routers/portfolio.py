"""Portfolio endpoints (/portfolio/*) extracted from ``runtime.portfolio.portfolio_routes``.

Owns the FirstStrike Portfolio tab surface — multi-broker aggregation,
options flow, paper-trading lifecycle hand-offs, and the Awarebot-derived
options events:

  Core read
    GET   /portfolio/summary                       — aggregated NLV / P&L / FX
    GET   /portfolio/positions                     — list positions (account filter)
    GET   /portfolio/accounts                      — connected brokerage accounts
    GET   /portfolio/performance                   — historical perf series
    GET   /portfolio/health                        — adapter / cache / FX health
    GET   /portfolio/bridge-state                  — in-memory bridge peek

  Connect / mutate
    POST  /portfolio/connect/ibkr                  — patch IBKR creds + reconnect
    POST  /portfolio/probe/ibkr                    — TCP-probe common IBKR ports
    POST  /portfolio/connect/ndax                  — patch NDAX creds + reconnect
    POST  /portfolio/connect/metamask              — patch wallet + reconnect
    POST  /portfolio/connect/polymarket            — patch Polymarket creds
    POST  /portfolio/sync                          — manual sync trigger

  Options surfaces
    GET   /portfolio/options-flow                  — unusual options flow rollup
    GET   /portfolio/options/strategies            — static strategy library
    GET   /portfolio/options/positions/with-strategy  — held options enriched

  Crypto / prediction-markets
    GET   /portfolio/crypto                        — NDAX + MetaMask combined
    GET   /portfolio/polymarket                    — Polymarket exposure

  Portfolio-event memory units
    GET   /portfolio/events                        — recent portfolio:* units
    GET   /portfolio/significant-moves             — position / portfolio moves

All endpoints are gated by ``verify_strike_token_dep`` (DI factory in
:mod:`runtime.api.deps`). The ``PortfolioManager`` singleton arrives via
``Depends(get_portfolio_mgr)``; the underlying ``NCLBrain`` (for the
memory-store events queries) arrives via ``Depends(get_brain)``.

W10C-3 (2026-05-24): Converted from the legacy
``from runtime.api.routes import STRIKE_TOKEN`` + module-global injection
pattern in ``runtime/portfolio/portfolio_routes.py`` to FastAPI
``Depends()`` injection. Mirrors W10C-2 (routers/memory.py) /
W10B-3 (routers/journal.py, routers/mandate.py). The new
``get_portfolio_mgr`` DI factory in ``runtime.api.deps`` reads through
to the existing injection point in
``runtime.portfolio.portfolio_routes._portfolio_manager`` so the lifespan
handler's ``set_portfolio_manager(_portfolio_mgr)`` call still works
unchanged. Behavior is byte-identical to the pre-conversion endpoints.
"""

from __future__ import annotations  # noqa: I001

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...config import flags
from ..deps import (
    get_brain,
    get_portfolio_mgr,
    verify_strike_token_dep,
)


log = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


# ── SQLite units-index fast path (W6-A) ───────────────────────────────────
#
# When ``NCL_UNITS_INDEX_SQLITE=true``, try the SQLite ``units_index`` table
# first (W4-14, store.py:_search_units_via_sqlite_index) so portfolio events
# queries (default 30d window) don't full-scan the 200MB units.jsonl. Falls
# back to the canonical ``search_units`` path on flag-off or ANY failure —
# flag-off behavior is bit-identical to before this retrofit.
async def _maybe_indexed_search(memory_store, **kwargs):
    """Drop-in replacement for ``memory_store.search_units(**kwargs)``."""
    if flags.units_index_sqlite():
        try:
            unit_ids = await memory_store._search_units_via_sqlite_index(**kwargs)
            if unit_ids:
                units_by_id = await memory_store._load_units_batch(set(unit_ids))
                return [units_by_id[uid] for uid in unit_ids if uid in units_by_id]
        except Exception as e:
            log.debug("[PORTFOLIO-ROUTES] sqlite index search failed (%s) — falling back", e)
    return await memory_store.search_units(**kwargs)


def _require_manager(pm):
    """Raise 503 if the manager wasn't injected (pre-lifespan or import failure)."""
    if pm is None:
        raise HTTPException(
            status_code=503,
            detail="Portfolio manager not initialized",
        )
    return pm


# ─────────────────────────────────────────────────────────────────────────────
# GET /portfolio/summary
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/summary")
async def portfolio_summary(
    base_currency: str = Query(default="CAD"),
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Aggregated portfolio snapshot across all brokerage accounts.

    Returns total value, daily/total P&L, cash totals, allocation
    breakdown, FX rate, sync timestamp, and market-open flag.
    """
    pm = _require_manager(pm)

    try:
        summary = pm.get_summary(base_currency=base_currency)
        # Count positions whose quote lookup failed (quote_ok == False) so
        # iOS PortfolioSummary.quotesFailed can render "--" badges without
        # a second roundtrip to /portfolio/positions. (Wave 13 P0-3)
        quotes_failed = 0
        try:
            positions = pm.get_positions(account_filter="all") or []
            for p in positions:
                if isinstance(p, dict) and p.get("quote_ok") is False:
                    quotes_failed += 1
        except Exception as _qe:
            log.debug(f"[portfolio.summary] quote_ok rollup skipped: {_qe}")
        return {
            "total_value": summary.get("total_value", 0),
            "base_currency": summary.get("base_currency", base_currency),
            "daily_pl": summary.get("daily_pl", 0),
            "daily_pl_pct": summary.get("daily_pl_pct", 0),
            "total_pl": summary.get("total_pl", 0),
            "total_pl_pct": summary.get("total_pl_pct", 0),
            "cash_total": summary.get("cash_total", 0),
            "positions_count": summary.get("positions_count", 0),
            "quotes_failed": quotes_failed,
            "accounts": summary.get("accounts", []),
            "allocation": summary.get("allocation", {}),
            "fx_rate_usd_cad": summary.get("fx_rate_usd_cad", 1.0),
            "last_sync": summary.get("last_sync"),
            "market_open": summary.get("market_open", False),
            "brokers_connected": summary.get("brokers_connected", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Portfolio summary failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Portfolio summary error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# GET /portfolio/positions
# ─────────────────────────────────────────────────────────────────────────────

VALID_ACCOUNTS = {"all", "IBKR", "MOOMOO", "WEALTHSIMPLE"}


@router.get("/positions")
async def portfolio_positions(
    account: str = Query(default="all"),
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    List positions, optionally filtered by brokerage account.
    """
    pm = _require_manager(pm)

    if account not in VALID_ACCOUNTS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid account filter '{account}'. Must be one of: {', '.join(sorted(VALID_ACCOUNTS))}",  # noqa: E501
        )

    try:
        positions = pm.get_positions(account_filter=account)
        # Wave 14J J0b: enrich with operator-set R-fields (entry/stop/
        # R_dollars/target/thesis/risk_status/position_key). Non-destructive;
        # missing R-fields surface as risk_status='unset', R_dollars=null.
        try:
            from ...portfolio.position_risk_state import enrich_positions_with_risk
            positions = await enrich_positions_with_risk(positions)
        except Exception as e:
            log.warning("[positions] R-field enrichment failed (non-fatal): %s", e)
        return {
            "positions": positions,
            "total_positions": len(positions),
            "last_sync": pm._last_sync,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Portfolio positions failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Portfolio positions error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# GET /portfolio/accounts
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/accounts")
async def portfolio_accounts(
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    List all connected brokerage accounts with metadata.
    """
    pm = _require_manager(pm)

    try:
        accounts = pm.get_accounts()
        return {"accounts": accounts}
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Portfolio accounts failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Portfolio accounts error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# GET /portfolio/performance
# ─────────────────────────────────────────────────────────────────────────────

VALID_RANGES = {"1D", "1W", "1M", "3M", "YTD", "1Y", "ALL"}


@router.get("/performance")
async def portfolio_performance(
    range: str = Query(default="1M", alias="range"),
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Historical performance data for charting.

    Returns data points, start/end values, and absolute/percentage change
    over the requested time range.
    """
    pm = _require_manager(pm)

    if range not in VALID_RANGES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid range '{range}'. Must be one of: {', '.join(sorted(VALID_RANGES))}",
        )

    try:
        perf = pm.get_performance(range=range)
        return {
            "range": range,
            "data_points": perf.get("data_points", []),
            "start_value": perf.get("start_value", 0),
            "end_value": perf.get("end_value", 0),
            "change": perf.get("change", 0),
            "change_pct": perf.get("change_pct", 0),
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Portfolio performance failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Portfolio performance error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# GET /portfolio/health
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/health")
async def portfolio_health(
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Portfolio system health — adapter connection status, cache info, FX rate.
    """
    pm = _require_manager(pm)
    return pm.health()


# ─────────────────────────────────────────────────────────────────────────────
# POST /portfolio/connect/ibkr   (2026-05-22 audit fix)
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/connect/ibkr")
async def portfolio_connect_ibkr(
    request: Request,
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Patch IBKR adapter settings (host/port/client_id) and (re)connect.

    Body: {"host": "127.0.0.1", "port": 7497, "client_id": 1}
    Returns: {"connected": bool, "error": str|null, "accounts": int}
    """
    pm = _require_manager(pm)
    try:
        body = await request.json()
    except Exception:
        body = {}
    host = body.get("host") or "127.0.0.1"
    port = int(body.get("port") or 7497)
    client_id = int(body.get("client_id") or 1)
    # Find the IBKR adapter on the manager
    adapter = None
    for a in getattr(pm, "_adapters", []) or []:
        if (getattr(a, "broker", "") or "").upper() == "IBKR":
            adapter = a
            break
    if adapter is None:
        # Brand-new adapter — instantiate
        try:
            from ...portfolio.ibkr_adapter import IBKRAdapter

            adapter = IBKRAdapter(host=host, port=port, client_id=client_id)
            if not hasattr(pm, "_adapters"):
                pm._adapters = []
            pm._adapters.append(adapter)
        except Exception as e:
            return {"connected": False, "error": f"adapter unavailable: {e}", "accounts": 0}
    else:
        # Patch existing settings
        try:
            adapter.host = host
            adapter.port = port
            adapter.client_id = client_id
        except Exception as e:
            log.warning("[PORTFOLIO] IBKR adapter settings patch swallowed: %s", e)
    # Pre-flight TCP probe so we can return a clearer error than ib_insync's
    # opaque "TimeoutError" when nothing is listening at all.
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    port_open = False
    try:
        sock.connect((host, port))
        port_open = True
    except Exception:
        port_open = False
    finally:
        try:
            sock.close()
        except Exception:
            pass

    if not port_open:
        return {
            "connected": False,
            "error": (
                f"Nothing listening on {host}:{port}. "
                f"Launch TWS or IB Gateway and confirm the API port matches. "
                f"Common ports: 7497 (TWS paper), 7496 (TWS live), "
                f"4002 (IBG paper), 4001 (IBG live)."
            ),
            "error_code": "port_closed",
            "host": host,
            "port": port,
            "client_id": client_id,
            "accounts": 0,
        }

    # Attempt connect
    try:
        ok = await adapter.connect() if hasattr(adapter, "connect") else False
        accounts = 0
        if ok:
            try:
                accs = await adapter.get_accounts()
                accounts = len(accs or [])
            except Exception as e:
                log.warning("[PORTFOLIO] IBKR get_accounts swallowed: %s", e)
        return {
            "connected": bool(ok),
            "error": None
            if ok
            else (
                f"Port {port} accepted the connection but the IBKR API rejected it. "
                f"In TWS: Edit > Global Configuration > API > Settings, enable "
                f"'Enable ActiveX and Socket Clients', verify port {port}, "
                f"and add 127.0.0.1 to Trusted IPs. Also confirm Client ID "
                f"{client_id} isn't already in use by another session."
            ),
            "error_code": None if ok else "api_disabled",
            "host": host,
            "port": port,
            "client_id": client_id,
            "accounts": accounts,
        }
    except Exception as e:
        msg = str(e)
        # ib_insync raises generic Exceptions; surface the most actionable
        # hint we can infer from common substrings.
        hint = ""
        low = msg.lower()
        if "client id" in low or "already in use" in low:
            hint = f" — Client ID {client_id} is already in use. Try another integer."
        elif "timeout" in low:
            hint = " — TWS accepted the socket but never completed the handshake. Check API settings + Trusted IPs."  # noqa: E501
        return {
            "connected": False,
            "error": f"{msg}{hint}",
            "error_code": "exception",
            "host": host,
            "port": port,
            "client_id": client_id,
            "accounts": 0,
        }


# ─────────────────────────────────────────────────────────────────────────────
# POST /portfolio/probe/ibkr   (2026-05-22 EOD swarm)
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/probe/ibkr")
async def portfolio_probe_ibkr(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """TCP-probe the common IBKR ports on 127.0.0.1 and return the first
    one that accepts a socket connection.

    Used by the iOS "Detect TWS" button so the user doesn't have to guess
    whether they're running TWS paper (7497), TWS live (7496), IB Gateway
    paper (4002), or IB Gateway live (4001).

    NOTE: A successful TCP connect does NOT mean the API is enabled — TWS
    can be running with the socket open but with "Enable ActiveX and Socket
    Clients" disabled, in which case the actual IBKR connect() will still
    fail. That's why this is a SEPARATE endpoint from /connect/ibkr — the
    UI uses probe to suggest a port, then calls connect to actually try it.
    """
    import socket

    candidates = [
        (7497, "TWS Paper"),
        (7496, "TWS Live"),
        (4002, "IB Gateway Paper"),
        (4001, "IB Gateway Live"),
    ]
    results = []
    detected = None
    for port, label in candidates:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.4)
        try:
            sock.connect(("127.0.0.1", port))
            results.append({"port": port, "label": label, "open": True})
            if detected is None:
                detected = {"port": port, "label": label}
        except Exception:
            results.append({"port": port, "label": label, "open": False})
        finally:
            try:
                sock.close()
            except Exception:
                pass
    return {
        "detected": detected,
        "candidates": results,
        "host": "127.0.0.1",
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /portfolio/sync
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/sync")
async def portfolio_sync(
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Trigger an immediate sync of all brokerage accounts.
    """
    pm = _require_manager(pm)

    try:
        await pm.sync()
        return {
            "status": "ok",
            "accounts_synced": len(pm._accounts),
            "positions_count": len(pm._positions),
            "last_sync": pm._last_sync,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Portfolio sync failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Portfolio sync error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# GET /portfolio/options-flow
# ─────────────────────────────────────────────────────────────────────────────

# Pre-compiled — title looks like "TSLA flow alert: $137,277 (165 contracts)"
_FLOW_TITLE_RE = re.compile(
    r"^([A-Z][A-Z0-9.]{0,8})\s+flow alert:\s*\$?([\d,]+)\s*\(\s*(\d+)\s*contracts?\)",
    re.IGNORECASE,
)
# Content like "TSLA — ask $69,265 / bid $68,012 | size 165 | OI 97 | sector Technology"
_FLOW_CONTENT_RE = re.compile(
    r"ask\s+\$?([\d,]+).*?bid\s+\$?([\d,]+)",
    re.IGNORECASE | re.DOTALL,
)


def _parse_options_flow_signal(sig: dict) -> Optional[dict]:
    """
    Pull ticker/premium/contracts/direction out of an Awarebot options_flow
    signal dict (one line of data/intelligence/agent_signals.jsonl).

    Returns None when the signal doesn't match the unusual_whales shape.
    """
    if sig.get("source") != "options_flow":
        return None
    title = sig.get("title") or ""
    m = _FLOW_TITLE_RE.match(title)
    if not m:
        return None
    ticker = m.group(1).upper()
    try:
        premium = float(m.group(2).replace(",", ""))
        contracts = float(m.group(3))
    except (TypeError, ValueError):
        return None

    ask = bid = 0.0
    c = _FLOW_CONTENT_RE.search(sig.get("content") or "")
    if c:
        try:
            ask = float(c.group(1).replace(",", ""))
            bid = float(c.group(2).replace(",", ""))
        except (TypeError, ValueError):
            pass

    direction = (sig.get("direction") or "neutral").lower()
    # Cheap calls-vs-puts split: ask-side dollars on bullish dir count as
    # call premium; bearish counts as put premium; neutral splits 50/50.
    if direction == "bullish":
        call_prem, put_prem = ask or premium, bid
    elif direction == "bearish":
        call_prem, put_prem = bid, ask or premium
    else:
        call_prem = put_prem = premium / 2.0

    return {
        "signal_id": sig.get("signal_id"),
        "ticker": ticker,
        "premium": premium,
        "contracts": contracts,
        "ask_premium": ask,
        "bid_premium": bid,
        "call_premium": call_prem,
        "put_premium": put_prem,
        "direction": direction,
        "timestamp": sig.get("timestamp"),
        "score": sig.get("composite_score", 0.0),
        "tags": sig.get("tags") or [],
    }


@router.get("/options-flow")
async def portfolio_options_flow(
    limit: int = Query(default=20, ge=1, le=100),
    min_premium: float = Query(default=100_000, ge=0),
    hours: int = Query(default=24, ge=1, le=168),
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Top unusual-options-flow tickers from Awarebot's agent_signals.jsonl,
    grouped by ticker, ranked by total premium.

    Filters
    -------
    * `min_premium` — drop trades below this dollar threshold (default $100k)
    * `hours` — lookback window (default last 24h)

    Each row tags `is_held_in_portfolio: true` when the ticker matches an
    open position so the iOS UI can highlight it.
    """
    pm = _require_manager(pm)

    # Resolve the agent_signals.jsonl path — same root the agent uses.
    data_root = Path(os.getenv("NCL_DATA_DIR", "data"))
    if not data_root.is_absolute():
        # Anchor on NCL root — this router lives in runtime/api/routers so
        # walk up three levels (routers → api → runtime → NCL root).
        data_root = Path(__file__).resolve().parents[3] / data_root
    signals_file = data_root / "intelligence" / "agent_signals.jsonl"

    if not signals_file.exists():
        return {
            "rows": [],
            "_meta": {
                "filter_applied": {"min_premium": min_premium, "hours": hours},
                "raw_count": 0,
                "filtered_count": 0,
                "dedup_count": 0,
                "reason": "agent_signals.jsonl not found",
            },
        }

    # Tail the file — last N lines suffice; we don't need to read everything.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    raw_lines: list[str] = []
    try:
        with open(signals_file, "rb") as f:
            # Cheap tail — read last 4MB; enough for ~10k signals
            try:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 4 * 1024 * 1024))
                if size > 4 * 1024 * 1024:
                    f.readline()  # drop partial first line
                raw_lines = f.read().decode("utf-8", errors="ignore").splitlines()
            except OSError:
                f.seek(0)
                raw_lines = f.read().decode("utf-8", errors="ignore").splitlines()
    except Exception as e:
        log.exception("options-flow read failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Read failure: {e}")

    raw_count = 0
    parsed: list[dict] = []
    seen_signal_ids: set[str] = set()
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            sig = json.loads(line)
        except json.JSONDecodeError:
            continue
        if sig.get("source") != "options_flow":
            continue
        raw_count += 1
        ts_str = sig.get("timestamp") or ""
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                continue
        except (TypeError, ValueError):
            pass

        sid = sig.get("signal_id")
        if sid and sid in seen_signal_ids:
            continue
        if sid:
            seen_signal_ids.add(sid)

        row = _parse_options_flow_signal(sig)
        if not row:
            continue
        if row["premium"] < min_premium:
            continue
        parsed.append(row)

    dedup_count = raw_count - len(parsed)

    # Group by ticker
    portfolio_tickers: set[str] = set()
    # Match underlying tickers for both straight stock positions AND
    # option-encoded holdings (e.g. SLV270115C65000 → SLV).
    option_underlying_re = re.compile(r"^([A-Z]{1,6})\d{6}[CP]\d+$")
    try:
        for p in pm._positions:
            sym = (p.get("symbol") or "").upper()
            if not sym:
                continue
            m = option_underlying_re.match(sym)
            if m:
                portfolio_tickers.add(m.group(1))
                continue
            if len(sym) <= 8 and not any(ch.isdigit() for ch in sym):
                portfolio_tickers.add(sym)
    except Exception:
        pass

    grouped: dict[str, dict] = {}
    for row in parsed:
        t = row["ticker"]
        g = grouped.setdefault(
            t,
            {
                "ticker": t,
                "total_premium_usd": 0.0,
                "call_premium": 0.0,
                "put_premium": 0.0,
                "trade_count": 0,
                "latest_at": "",
                "trades": [],
            },
        )
        g["total_premium_usd"] += row["premium"]
        g["call_premium"] += row["call_premium"]
        g["put_premium"] += row["put_premium"]
        g["trade_count"] += 1
        if (row["timestamp"] or "") > g["latest_at"]:
            g["latest_at"] = row["timestamp"] or ""
        g["trades"].append(row)

    rows: list[dict] = []
    for t, g in grouped.items():
        put = g["put_premium"]
        ratio = (
            (g["call_premium"] / put)
            if put
            else (g["call_premium"] / 1.0 if g["call_premium"] else 0.0)
        )
        # Top 5 trades by premium for drill-in
        top_trades = sorted(g["trades"], key=lambda r: r["premium"], reverse=True)[:5]
        rows.append(
            {
                "ticker": t,
                "total_premium_usd": round(g["total_premium_usd"], 2),
                "call_premium": round(g["call_premium"], 2),
                "put_premium": round(g["put_premium"], 2),
                "call_put_ratio": round(ratio, 2),
                "trade_count": g["trade_count"],
                "latest_at": g["latest_at"],
                "is_held_in_portfolio": t in portfolio_tickers,
                "top_trades": [
                    {
                        "signal_id": tr["signal_id"],
                        "premium": round(tr["premium"], 2),
                        "contracts": tr["contracts"],
                        "direction": tr["direction"],
                        "timestamp": tr["timestamp"],
                    }
                    for tr in top_trades
                ],
            }
        )

    rows.sort(key=lambda r: r["total_premium_usd"], reverse=True)
    rows = rows[:limit]

    return {
        "rows": rows,
        "_meta": {
            "filter_applied": {
                "min_premium": min_premium,
                "hours": hours,
                "limit": limit,
            },
            "raw_count": raw_count,
            "filtered_count": len(parsed),
            "dedup_count": dedup_count,
            "ticker_count": len(grouped),
            "portfolio_match_count": sum(1 for r in rows if r["is_held_in_portfolio"]),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /portfolio/options/strategies
# GET /portfolio/options/positions/with-strategy
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/options/strategies")
async def portfolio_options_strategies(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Static library of the three named options strategies (0DTE, 5-Day
    Swing, Long Call). Used by the iOS OPTIONS sub-tab → STRATEGIES mode.

    Pure read — no manager required.
    """
    from ...portfolio.options_strategies import all_strategies_payload

    return {
        "strategies": all_strategies_payload(),
        "count": 3,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/options/positions/with-strategy")
async def portfolio_options_positions_with_strategy(
    account: str = Query(default="all"),
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Held option positions enriched with ``matched_strategy`` +
    parsed OCC fields (underlying, expiry, strike, right, DTE).

    Non-option positions are filtered out — this endpoint is the data
    source for the iOS OPTIONS → HELD sub-mode.
    """
    pm = _require_manager(pm)

    if account not in VALID_ACCOUNTS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid account filter '{account}'. Must be one of: {', '.join(sorted(VALID_ACCOUNTS))}",  # noqa: E501
        )

    from ...portfolio.options_strategies import enrich_position_with_strategy

    try:
        positions = pm.get_positions(account_filter=account)
    except Exception as e:
        log.exception("Options positions fetch failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Positions error: {e}")

    enriched: list[dict] = []
    strategy_counts: dict[str, int] = {"0DTE": 0, "5DAY": 0, "LONGCALL": 0, "Other": 0}
    total_mv = 0.0
    total_day_pl = 0.0

    for p in positions:
        if (p.get("asset_class") or "").lower() != "option":
            continue
        row = enrich_position_with_strategy(p)
        enriched.append(row)
        s = row.get("matched_strategy") or "Other"
        strategy_counts[s] = strategy_counts.get(s, 0) + 1
        try:
            total_mv += float(row.get("market_value") or 0)
            total_day_pl += float(row.get("daily_pl") or 0)
        except (TypeError, ValueError):
            pass

    def _sort_key(r: dict):
        s = r.get("matched_strategy") or "Other"
        urgency = {"0DTE": 0, "5DAY": 1, "LONGCALL": 2, "Other": 3}.get(s, 9)
        dte = r.get("option_dte") if r.get("option_dte") is not None else 9999
        return (urgency, dte, -float(r.get("market_value") or 0))

    enriched.sort(key=_sort_key)

    return {
        "positions": enriched,
        "count": len(enriched),
        "total_market_value": round(total_mv, 2),
        "total_daily_pl": round(total_day_pl, 2),
        "strategy_counts": strategy_counts,
        "account_filter": account,
        "last_sync": pm._last_sync,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /portfolio/events
# ─────────────────────────────────────────────────────────────────────────────


def _serialize_portfolio_unit(u) -> dict:
    """Render a MemUnit as a compact JSON payload for the events endpoints."""
    try:
        created = (
            u.created_at.isoformat() if hasattr(u.created_at, "isoformat") else str(u.created_at)
        )
    except Exception:
        created = ""
    meta = getattr(u, "metadata", None) or {}
    return {
        "unit_id": u.unit_id,
        "source": u.source,
        "content": u.content,
        "importance": u.importance,
        "tags": u.tags,
        "memory_type": getattr(u, "memory_type", "episodic"),
        "memory_tier": getattr(u, "memory_tier", "SML"),
        "authority_tier": meta.get("authority_tier"),
        "created_at": created,
        "metadata": {k: v for k, v in meta.items() if k != "authority_tier"},
    }


@router.get("/events")
async def portfolio_events(
    limit: int = Query(default=20, ge=1, le=200),
    source: Optional[str] = Query(
        default=None, description="Filter by portfolio:* source (snapshot, position_opened, etc.)"
    ),
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Recent portfolio:* memory units, newest first.

    Each unit is one event written by the portfolio memory bridge —
    snapshots, position open/close, significant moves, account drift,
    buying-power risk, quantity changes.
    """
    if brain is None or not getattr(brain, "memory_store", None):
        raise HTTPException(status_code=503, detail="Memory store not initialised")

    try:
        units = await _maybe_indexed_search(
            brain.memory_store,
            tags=["portfolio"],
            importance_threshold=0.0,
            days_back=30,
        )
    except Exception as e:
        log.exception("Portfolio events search failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Portfolio events error: {e}")

    # Newest first
    try:
        units.sort(
            key=lambda u: getattr(u, "created_at", datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True,
        )
    except Exception:
        pass

    if source:
        # Normalize to portfolio:<event> form if caller passed a bare name
        wanted = source if source.startswith("portfolio:") else f"portfolio:{source}"
        units = [u for u in units if u.source == wanted]

    events = [_serialize_portfolio_unit(u) for u in units[:limit]]
    return {
        "events": events,
        "count": len(events),
        "filter_source": source,
        "limit": limit,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /portfolio/significant-moves
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/bridge-state")
async def portfolio_bridge_state(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Peek at the in-memory portfolio bridge state.

    Returns the freshest cached summary + position count + when the
    bridge last saw a sync. Used for verifying the chat-context portfolio
    injector has live data without having to hit the (potentially slow)
    create_unit path.
    """
    try:
        from ...portfolio.memory_bridge import get_bridge

        bridge = get_bridge()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bridge import failed: {e}")
    if bridge is None:
        return {"bridge_initialized": False}

    summary = bridge.latest_summary() or {}
    positions = bridge.latest_positions() or []
    latest_at = bridge.latest_at()
    return {
        "bridge_initialized": True,
        "latest_at": latest_at.isoformat() if latest_at else None,
        "summary_keys": sorted(summary.keys()),
        "nlv": summary.get("total_value"),
        "base_currency": summary.get("base_currency"),
        "day_pl": summary.get("daily_pl"),
        "day_pl_pct": summary.get("daily_pl_pct"),
        "position_count": len(positions),
        "top_positions": [
            {
                "symbol": p.get("symbol"),
                "market_value_cad": p.get("market_value_cad"),
                "daily_pl_pct": p.get("daily_pl_pct"),
            }
            for p in positions[:5]
        ],
    }


@router.get("/significant-moves")
async def portfolio_significant_moves(
    days: int = Query(default=7, ge=1, le=90),
    scope: Optional[str] = Query(default=None, description="position | portfolio"),
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Portfolio:significant_move events in the requested window.

    Returns position-level AND portfolio-level moves unless scope is
    constrained. Sorted newest first.
    """
    if brain is None or not getattr(brain, "memory_store", None):
        raise HTTPException(status_code=503, detail="Memory store not initialised")

    try:
        units = await _maybe_indexed_search(
            brain.memory_store,
            tags=["portfolio:significant_move"],
            importance_threshold=0.0,
            days_back=days,
        )
    except Exception as e:
        log.exception("Portfolio significant-moves search failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Significant-moves error: {e}")

    if scope:
        scope_tag = f"scope:{scope}"
        units = [u for u in units if scope_tag in (u.tags or [])]

    try:
        units.sort(
            key=lambda u: getattr(u, "created_at", datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True,
        )
    except Exception:
        pass

    moves = [_serialize_portfolio_unit(u) for u in units]
    return {
        "moves": moves,
        "count": len(moves),
        "window_days": days,
        "scope_filter": scope,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /portfolio/crypto  (added 2026-05-22 EOD)
# GET /portfolio/polymarket
# POST /portfolio/connect/{ndax,metamask,polymarket}
# ─────────────────────────────────────────────────────────────────────────────


def _find_adapter(pm, name: str):
    """Return the adapter on the manager matching *name* (case-insensitive).

    Manager stores `_adapters` as list of (name, adapter) tuples — we walk
    it instead of poking the private attributes so this stays robust if a
    future refactor changes the layout.
    """
    name_l = name.lower()
    for entry in getattr(pm, "_adapters", []) or []:
        if isinstance(entry, tuple) and len(entry) == 2:
            n, adapter = entry
            if str(n).lower() == name_l:
                return adapter
        else:
            # Defensive — handle a flat list of adapters too.
            broker = getattr(entry, "broker", "") or ""
            if str(broker).lower() == name_l:
                return entry
    # Fallback to typed attributes set in __init__.
    for attr in (f"_{name_l}",):
        a = getattr(pm, attr, None)
        if a is not None:
            return a
    return None


# ──────────────────────────────────────────────────────────────────────
# Wave 14K Phase 1 — Auto-trader foundation endpoints
# PAPER TRADING ONLY. Auto-trader proposes + opens paper trades; never
# touches live capital. See docs/AUTO_TRADER_AGENT_2026-05-26.md.
# ──────────────────────────────────────────────────────────────────────

@router.get("/auto-trader/status")
async def auto_trader_status(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Current auto-trader state: active flag, pause reason, day counters."""
    from ...portfolio.auto_trader import get_state, is_active
    state = await get_state()
    return {
        "is_active": await is_active(),
        "state": {
            "active": state.active,
            "paused_by": state.paused_by,
            "pause_reason": state.pause_reason,
            "paused_at_iso": state.paused_at_iso,
            "drawdown_halt_pause": state.drawdown_halt_pause,
            "drawdown_halt_band": state.drawdown_halt_band,
            "drawdown_halt_at_iso": state.drawdown_halt_at_iso,
            "last_loop_tick_iso": state.last_loop_tick_iso,
            "last_seen_trade_idea_id": state.last_seen_trade_idea_id,
            "ideas_evaluated_today": state.ideas_evaluated_today,
            "ideas_opened_today": state.ideas_opened_today,
            "ideas_rejected_today": state.ideas_rejected_today,
            "counters_date_utc": state.counters_date_utc,
        },
    }


@router.get("/auto-trader/policy")
async def auto_trader_policy_get(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Current entry-criteria policy (operator-tunable)."""
    from ...portfolio.auto_trader import get_policy
    from dataclasses import asdict
    p = await get_policy(force_reload=True)
    return asdict(p)


@router.patch("/auto-trader/policy")
async def auto_trader_policy_patch(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """PATCH the policy. Only listed fields change; rest preserved.
    Example body: {"min_R_R_ratio": 2.0, "max_opens_per_day": 20}"""
    from ...portfolio.auto_trader import update_policy
    from dataclasses import asdict
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(status_code=400, detail="Empty PATCH body")
    try:
        p = await update_policy(payload, updated_by="rest")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    return asdict(p)


@router.post("/auto-trader/pause")
async def auto_trader_pause(
    payload: Optional[dict] = None,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Manual pause. Optional body {reason: str}. Default reason
    'operator manual pause'."""
    from ...portfolio.auto_trader import pause
    reason = (payload or {}).get("reason", "operator manual pause")
    state = await pause(str(reason), by="operator")
    return {"paused_by": state.paused_by, "pause_reason": state.pause_reason,
            "paused_at_iso": state.paused_at_iso}


@router.post("/auto-trader/resume")
async def auto_trader_resume(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Resume from manual pause. Drawdown-halt auto-pause is NOT cleared
    here; that resolves automatically when drawdown_bucket band moves
    back to non-halt."""
    from ...portfolio.auto_trader import resume
    state = await resume()
    return {"active": state.active, "paused_by": state.paused_by,
            "drawdown_halt_pause": state.drawdown_halt_pause}


@router.post("/auto-trader/eligibility-check")
async def auto_trader_eligibility_check(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Run a hypothetical trade idea through the auto-bar without
    opening anything. Useful for the operator to preview whether a
    given brief idea would pass.

    Body: {idea: {...trade_idea fields...},
           governor_decision: {...optional...}}

    Returns: {eligible: bool, reason: str, policy_rev: int}"""
    from ...portfolio.auto_trader import auto_open_eligible, get_policy
    if "idea" not in payload:
        raise HTTPException(status_code=400, detail="Missing 'idea' field")
    p = await get_policy()
    eligible, reason = await auto_open_eligible(
        payload["idea"],
        payload.get("governor_decision"),
        policy=p,
    )
    return {"eligible": eligible, "reason": reason, "policy_rev": p.revision}


@router.get("/auto-trader/reasoning-chains")
async def auto_trader_reasoning_chains(
    limit: int = Query(default=50, ge=1, le=500),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """List most-recent reasoning chains captured at open time
    (newest first). Each chain is the audit trail for one trade idea."""
    from ...portfolio.auto_trader import list_recent_chains
    items = await list_recent_chains(limit=limit)
    return {"count": len(items), "chains": items}


@router.get("/auto-trader/reasoning-chains/{trade_idea_id}")
async def auto_trader_reasoning_chain_one(
    trade_idea_id: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Fetch one reasoning chain by trade_idea_id."""
    from ...portfolio.auto_trader import get_reasoning_chain
    chain = await get_reasoning_chain(trade_idea_id)
    if chain is None:
        raise HTTPException(
            status_code=404,
            detail=f"No reasoning chain for trade_idea_id={trade_idea_id}",
        )
    return chain


# ── Wave 14K Phase 4 — bandit + SHAP endpoints ──────────────────

@router.get("/auto-trader/bandit/posteriors")
async def auto_trader_bandit_all(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """All strategy posteriors with mean + 95% credible interval +
    avg R per trade."""
    from ...portfolio.auto_trader import get_bandit
    bandit = await get_bandit()
    return {"posteriors": await bandit.all_posteriors()}


@router.get("/auto-trader/bandit/posteriors/{strategy}")
async def auto_trader_bandit_one(
    strategy: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """One strategy's posterior."""
    from ...portfolio.auto_trader import get_bandit
    bandit = await get_bandit()
    p = await bandit.posterior(strategy)
    if p is None:
        raise HTTPException(status_code=404, detail=f"No posterior for {strategy}")
    return p


@router.post("/auto-trader/bandit/sample-arm")
async def auto_trader_bandit_sample(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Thompson-sample one strategy from a list of candidates. Body:
    {candidates: [str, ...]}"""
    from ...portfolio.auto_trader import get_bandit
    candidates = (payload or {}).get("candidates") or []
    if not candidates:
        raise HTTPException(status_code=400, detail="Missing candidates list")
    bandit = await get_bandit()
    pick = await bandit.sample_arm(candidates)
    return {"picked": pick, "candidates": candidates}


@router.get("/auto-trader/bandit/ranked")
async def auto_trader_bandit_ranked(
    ci: float = Query(default=0.95, ge=0.5, le=0.99),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Strategies ranked by lower 95% CI on win rate (conservative
    ranking). Brief pipeline can use this to bias trade-idea
    allocation toward strategies with proven edge."""
    from ...portfolio.auto_trader import get_bandit
    bandit = await get_bandit()
    return {"ci": ci, "ranked": await bandit.ranked_by_credible_lower_bound(ci=ci)}


@router.post("/auto-trader/bandit/record-result")
async def auto_trader_bandit_record(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Manually record a win/loss for a strategy (for backfilling +
    operator overrides). Auto-trader does this automatically on every
    paper close — this endpoint is for manual entry only.
    Body: {strategy, win, R_multiple?, trade_idea_id?}"""
    from ...portfolio.auto_trader import get_bandit
    if "strategy" not in payload or "win" not in payload:
        raise HTTPException(status_code=400, detail="Need strategy + win")
    bandit = await get_bandit()
    return await bandit.record_result(
        strategy=str(payload["strategy"]),
        win=bool(payload["win"]),
        R_multiple=float(payload.get("R_multiple") or 0),
        trade_idea_id=payload.get("trade_idea_id"),
    )


@router.post("/auto-trader/attribution/run")
async def auto_trader_attribution_run(
    payload: dict,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Manually trigger SHAP-style attribution for one strategy
    (auto-triggers every N closed trades; this endpoint is for
    operator-on-demand). Body: {strategy: str}"""
    from ...portfolio.auto_trader import run_attribution_for_strategy
    strategy = (payload or {}).get("strategy")
    if not strategy:
        raise HTTPException(status_code=400, detail="Missing 'strategy'")
    return await run_attribution_for_strategy(brain=brain, strategy=str(strategy))


# ── Wave 14K Phase 5 — self-research endpoints ───────────────────

@router.get("/auto-trader/research/topics")
async def auto_trader_research_topics(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Open research topics — losing-trade clusters the system is
    failing on. Each topic is a 'what we don't understand' that the
    next morning brief should help resolve."""
    from ...portfolio.auto_trader import list_open_research_topics
    topics = list_open_research_topics()
    return {"count": len(topics), "topics": topics}


@router.post("/auto-trader/research/topics/generate")
async def auto_trader_research_topics_generate(
    payload: Optional[dict] = None,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Manually trigger topic-cluster generation. Auto-fires after each
    SHAP attribution; this endpoint is for on-demand. Body: {lookback_days?}"""
    from ...portfolio.auto_trader import generate_research_topics
    lookback = int((payload or {}).get("lookback_days", 14))
    new_topics = await generate_research_topics(lookback_days=lookback)
    return {"new_topics": new_topics, "lookback_days": lookback}


@router.post("/auto-trader/research/topics/{topic_id}/resolve")
async def auto_trader_research_topic_resolve(
    topic_id: str,
    payload: Optional[dict] = None,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Mark a research topic resolved or dismissed.
    Body: {resolution_notes?: str, dismiss?: bool}"""
    from ...portfolio.auto_trader import resolve_research_topic
    notes = (payload or {}).get("resolution_notes", "")
    dismiss = bool((payload or {}).get("dismiss", False))
    result = await resolve_research_topic(
        topic_id, resolution_notes=notes, dismiss=dismiss,
    )
    if result is None:
        raise HTTPException(status_code=404, detail=f"Topic {topic_id} not found")
    return result


@router.get("/auto-trader/brief-context-packet")
async def auto_trader_brief_packet(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Preview the text packet the brief executor prepends — bandit
    rankings + recent SHAP findings + open research topics."""
    from ...portfolio.auto_trader import brief_context_packet
    packet = await brief_context_packet()
    return {"packet": packet, "char_count": len(packet)}


# ── Wave 14K Phase 6 — drift + graduation endpoints ────────────────

@router.get("/auto-trader/drift")
async def auto_trader_drift_all(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Per-strategy Page-Hinkley drift detector state. Each entry shows
    n_observed, running_mean hit rate, m_down/m_up cumulative statistics,
    recent-window hit rate, last drift signal timestamp + reason."""
    from ...portfolio.auto_trader import drift_all_states
    states = await drift_all_states()
    return {"count": len(states), "strategies": states}


@router.get("/auto-trader/drift/{strategy}")
async def auto_trader_drift_one(
    strategy: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Single-strategy drift state."""
    from ...portfolio.auto_trader import drift_get_state
    state = await drift_get_state(strategy)
    if state is None:
        raise HTTPException(status_code=404, detail=f"No drift state for {strategy}")
    return state


@router.post("/auto-trader/drift/{strategy}/reset")
async def auto_trader_drift_reset(
    strategy: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Operator reset (after intentional re-spec). Clears PH statistics +
    window but preserves lifetime drift counters in the events JSONL."""
    from ...portfolio.auto_trader import drift_reset_strategy
    cleared = await drift_reset_strategy(strategy)
    if not cleared:
        raise HTTPException(status_code=404, detail=f"No drift state for {strategy}")
    return {"strategy": strategy, "reset": True}


@router.get("/auto-trader/graduation")
async def auto_trader_graduation_all(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Run graduation gate over every strategy known to trade_idea_tracker.
    Returns one report per strategy + a _summary block listing which are
    graduated / failing."""
    from ...portfolio.auto_trader import graduation_evaluate_all
    return await graduation_evaluate_all()


@router.get("/auto-trader/graduation/{strategy}")
async def auto_trader_graduation_one(
    strategy: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Multi-criteria graduation report for a single strategy.

    Wave 14K NEVER auto-promotes — this is decision support for the
    operator. A 'graduated:true' report means all criteria pass and the
    strategy is a candidate for review, not an instruction to go live."""
    from ...portfolio.auto_trader import graduation_evaluate
    return await graduation_evaluate(strategy)


# ── Wave 14K Phase 7 — friction profile + rollup endpoints ─────────

@router.get("/auto-trader/friction")
async def auto_trader_friction_all(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Per-strategy friction profiles (slippage_bps + partial-fill model).
    Empty {} until at least one paper trade has been opened or an
    operator override has been recorded."""
    from ...portfolio.auto_trader import friction_all_profiles
    profiles = await friction_all_profiles()
    return {"count": len(profiles), "profiles": profiles}


@router.get("/auto-trader/friction/{strategy}")
async def auto_trader_friction_one(
    strategy: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Single-strategy friction profile (creates default if missing)."""
    from ...portfolio.auto_trader import friction_get_profile
    from dataclasses import asdict
    p = await friction_get_profile(strategy)
    return asdict(p)


@router.post("/auto-trader/friction/{strategy}")
async def auto_trader_friction_update(
    strategy: str,
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Operator override of a strategy's friction profile.
    Body: {slippage_bps?, partial_fill_prob?, partial_fill_min_pct?, asset_type?}."""
    from ...portfolio.auto_trader import friction_update_profile
    from dataclasses import asdict
    p = await friction_update_profile(
        strategy,
        slippage_bps=payload.get("slippage_bps"),
        partial_fill_prob=payload.get("partial_fill_prob"),
        partial_fill_min_pct=payload.get("partial_fill_min_pct"),
        asset_type=payload.get("asset_type"),
    )
    return asdict(p)


@router.post("/auto-trader/friction/{strategy}/calibrate")
async def auto_trader_friction_calibrate(
    strategy: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """On-demand re-calibration from closed paper trades. Normally fires
    every NCL_FRICTION_CALIB_EVERY_N closes automatically."""
    from ...portfolio.auto_trader import friction_calibrate_from_closes
    result = await friction_calibrate_from_closes(strategy)
    if result is None:
        return {"strategy": strategy, "calibrated": False,
                "reason": "no closed trades to sample"}
    result["calibrated"] = True
    return result


@router.get("/auto-trader/circuit-breakers")
async def auto_trader_circuit_breakers(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """K7a: status of the auto-trader's per-dep circuit breakers
    (drawdown_bucket, risk_governor, trade_idea_tracker, paper_engine).
    Each shows fails count, open/closed, remaining quarantine seconds."""
    from ...portfolio.hygiene import all_breaker_statuses
    all_breakers = all_breaker_statuses()
    # Filter to auto_trader: prefix to keep the response focused
    at_breakers = [b for b in all_breakers
                   if b.get("name", "").startswith("auto_trader:")]
    return {"count": len(at_breakers), "breakers": at_breakers}


@router.get("/auto-trader/calendar")
async def auto_trader_calendar(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Calendar awareness snapshot — upcoming FOMC/OPEX/VIX/earnings events
    + which are currently inside the auto-trader's blocking window."""
    from ...portfolio.auto_trader import calendar_summary
    return await calendar_summary()


@router.get("/auto-trader/strategies")
async def auto_trader_strategies_list(
    asset_type: Optional[str] = None,
    enabled_only: bool = True,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """List all named strategy recipes. Optional filters: asset_type, enabled_only.
    20+ recipes spanning stock/options/polymarket/crypto."""
    from ...portfolio.auto_trader import list_recipes
    from dataclasses import asdict
    recipes = await list_recipes(asset_type=asset_type, enabled_only=enabled_only)
    return {
        "count": len(recipes),
        "recipes": [asdict(r) for r in recipes],
    }


@router.get("/auto-trader/strategies/{name}")
async def auto_trader_strategy_get(
    name: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Single recipe lookup."""
    from ...portfolio.auto_trader import get_recipe
    from dataclasses import asdict
    r = await get_recipe(name)
    if r is None:
        raise HTTPException(status_code=404, detail=f"Recipe {name} not found")
    return asdict(r)


@router.patch("/auto-trader/strategies/{name}")
async def auto_trader_strategy_patch(
    name: str,
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Operator override of a recipe. Body: any subset of StrategyRecipe fields."""
    from ...portfolio.auto_trader import update_recipe
    from dataclasses import asdict
    try:
        r = await update_recipe(name, **payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if r is None:
        raise HTTPException(status_code=404, detail=f"Recipe {name} not found")
    return asdict(r)


@router.get("/auto-trader/ladder")
async def auto_trader_ladder_status(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Profit-ladder snapshot — config + recent 10 emissions + cumulative
    realized/laddered $."""
    from ...portfolio.auto_trader import ladder_summary
    return await ladder_summary()


@router.post("/auto-trader/eod-summary")
async def auto_trader_eod_summary_trigger(
    payload: Optional[dict] = None,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Manual trigger for the EOD summary. Normally fires at 21:55 ET
    automatically via ncl-auto-trader-eod scheduler task. Body: {force?: bool}."""
    from ...portfolio.auto_trader import emit_eod_summary
    force = bool((payload or {}).get("force", False))
    result = await emit_eod_summary(force=force)
    if result is None:
        return {"emitted": False, "reason": "already emitted today (pass force=true to override)"}
    return {"emitted": True, "summary": result}


@router.get("/auto-trader/working-context")
async def auto_trader_working_context(
    ticker: Optional[str] = None,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Working-context gate snapshot. With ?ticker=NVDA, also returns
    the per-ticker check (blocked, contradicted_by, aligned_with)."""
    from ...portfolio.auto_trader import (
        working_context_summary, check_working_context,
    )
    summary = await working_context_summary()
    if ticker:
        summary["ticker_check"] = await check_working_context(ticker)
    return summary


@router.get("/auto-trader/dashboard")
async def auto_trader_dashboard(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """One-shot rollup for the iOS Auto-Trader card. Aggregates:
      - operator state (active/paused/drawdown_halt/counters)
      - top-5 strategies by Bayesian LCB hit rate
      - drift signals (count by status across all strategies)
      - graduation summary (graduated:[..], failing:[..])
      - open research topics (count)
      - 5 most-recent closed paper trades w/ R_multiple
      - friction profile count
    """
    from ...portfolio.auto_trader import (
        get_state, get_bandit, drift_all_states,
        graduation_evaluate_all, list_open_research_topics,
        friction_all_profiles, calendar_summary,
        working_context_summary, registry_summary, ladder_summary,
    )
    from ...portfolio.trade_idea_tracker import get_trade_idea_tracker
    from dataclasses import asdict

    state = await get_state()
    state_dict = asdict(state)

    # Top strategies by LCB
    try:
        bandit = await get_bandit()
        top_strategies = await bandit.ranked_by_credible_lower_bound(ci=0.95)
        top_strategies = top_strategies[:5]
    except Exception as e:
        top_strategies = []
        state_dict["top_strategies_error"] = str(e)

    # Drift roll-up
    try:
        drift_states = await drift_all_states()
        drift_counts = {"STABLE": 0, "DRIFT_DOWN": 0, "DRIFT_UP": 0}
        for s in drift_states.values():
            drift_counts[s.get("last_status", "STABLE")] = drift_counts.get(
                s.get("last_status", "STABLE"), 0
            ) + 1
        drift_summary = {"counts": drift_counts, "total": len(drift_states)}
    except Exception as e:
        drift_summary = {"error": str(e)}

    # Graduation summary
    try:
        grad = await graduation_evaluate_all()
        grad_summary = grad.get("_summary", {})
    except Exception as e:
        grad_summary = {"error": str(e)}

    # Open research topics
    try:
        topics = list_open_research_topics()
        topic_summary = {"count": len(topics),
                         "top_5": [t.get("title", "") for t in topics[:5]]}
    except Exception as e:
        topic_summary = {"error": str(e)}

    # Recent closes (last 5)
    try:
        tracker = await get_trade_idea_tracker()
        all_ideas = await tracker.list_by_strategy(None)
        recent_closes = sorted(
            [i for i in all_ideas if i.get("closed_at_iso")],
            key=lambda i: i.get("closed_at_iso", ""), reverse=True,
        )[:5]
        recent = [
            {"trade_idea_id": i.get("trade_idea_id"),
             "ticker": i.get("ticker"),
             "strategy": i.get("strategy"),
             "outcome": i.get("outcome"),
             "R_multiple": i.get("R_multiple"),
             "closed_at_iso": i.get("closed_at_iso")}
            for i in recent_closes
        ]
    except Exception as e:
        recent = []
        state_dict["recent_closes_error"] = str(e)

    # Friction summary
    try:
        profiles = await friction_all_profiles()
        friction_summary = {"count": len(profiles),
                            "strategies": list(profiles.keys())}
    except Exception as e:
        friction_summary = {"error": str(e)}

    # Calendar summary (Wave 14K hardening #1)
    try:
        calendar = await calendar_summary()
    except Exception as e:
        calendar = {"error": str(e)}

    # Working-context summary (Wave 14K hardening #3)
    try:
        wc = await working_context_summary()
    except Exception as e:
        wc = {"error": str(e)}

    # Strategy registry summary (Wave 14L L1)
    try:
        registry = await registry_summary()
    except Exception as e:
        registry = {"error": str(e)}

    # Profit-ladder summary (Wave 14L L4)
    try:
        ladder = await ladder_summary()
    except Exception as e:
        ladder = {"error": str(e)}

    return {
        "state": state_dict,
        "top_strategies": top_strategies,
        "drift": drift_summary,
        "graduation": grad_summary,
        "research_topics": topic_summary,
        "recent_closes": recent,
        "friction": friction_summary,
        "calendar": calendar,
        "working_context": wc,
        "registry": registry,
        "ladder": ladder,
        "wave": "14L-L1+L4",
    }


# ──────────────────────────────────────────────────────────────────────
# Wave 14J out-of-scope finisher endpoints
# Order PREVIEW (dry-run only — NCL never submits) + backtest replay +
# manual-entry adapter + quote-source chain stats.
# ──────────────────────────────────────────────────────────────────────

@router.post("/orders/preview")
async def portfolio_orders_preview(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Dry-run a proposed order. Returns governor decision + per-broker
    payload strings for the OPERATOR to copy into their broker UI.
    NCL does not submit. Submission is operator-only."""
    from ...portfolio.order_preview import preview_order
    required = ("symbol", "side", "qty")
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing: {missing}")
    try:
        return await preview_order(
            symbol=str(payload["symbol"]),
            side=str(payload["side"]),
            qty=float(payload["qty"]),
            order_type=str(payload.get("order_type", "market")),
            limit_price=(
                float(payload["limit_price"])
                if payload.get("limit_price") is not None else None
            ),
            stop_price=(
                float(payload["stop_price"])
                if payload.get("stop_price") is not None else None
            ),
            time_in_force=str(payload.get("time_in_force", "DAY")),
            broker=payload.get("broker"),
            account_id=payload.get("account_id"),
            strategy_tag=payload.get("strategy_tag"),
            trade_idea_id=payload.get("trade_idea_id"),
            estimated_R_dollars=(
                float(payload["estimated_R_dollars"])
                if payload.get("estimated_R_dollars") is not None else None
            ),
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve


@router.get("/backtest/replay")
async def portfolio_backtest_replay(
    lookback_days: int = Query(default=90, ge=1, le=365),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Replay historical trade ideas through CURRENT risk_governor
    config. Counter-factual: what would heat caps + drawdown bands
    have done if today's config had been in place?"""
    from ...portfolio.backtest_harness import replay_window
    return await replay_window(lookback_days=lookback_days)


@router.get("/manual/positions")
async def portfolio_manual_positions(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """List positions from the manual-entry adapter (cold storage etc.)."""
    from ...portfolio.manual_adapter import get_manual_adapter
    m = await get_manual_adapter()
    positions = await m.fetch_positions()
    accounts = await m.fetch_accounts()
    return {
        "accounts": accounts,
        "positions": positions,
        "health": m.health(),
    }


@router.post("/manual/position")
async def portfolio_manual_add_position(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Add a position to the manual-entry adapter."""
    from ...portfolio.manual_adapter import get_manual_adapter
    required = ("symbol", "account_id", "quantity")
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing: {missing}")
    m = await get_manual_adapter()
    return await m.add_position(payload)


@router.delete("/manual/position/{symbol}")
async def portfolio_manual_remove_position(
    symbol: str,
    account_id: Optional[str] = Query(default=None),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Remove all positions matching symbol [+ optional account_id]."""
    from ...portfolio.manual_adapter import get_manual_adapter
    m = await get_manual_adapter()
    removed = await m.remove_position(symbol, account_id=account_id)
    return {"symbol": symbol, "account_id": account_id, "removed": removed}


@router.put("/manual/account")
async def portfolio_manual_upsert_account(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Upsert a manual-entry account."""
    from ...portfolio.manual_adapter import get_manual_adapter
    m = await get_manual_adapter()
    try:
        return await m.set_account(payload)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve


@router.get("/quote-source/stats")
async def portfolio_quote_source_stats(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Stats from the default quote chain — which sources are serving,
    miss counts, top-10 most-missed symbols."""
    from ...portfolio.quote_source import default_quote_chain
    chain = default_quote_chain()
    return chain.stats()


# ──────────────────────────────────────────────────────────────────────
# Wave 14J deferred-items finisher endpoints
# J4b spec-ID + J5a/b/c on-chain journal + J7c slippage + J8d settle.
# ──────────────────────────────────────────────────────────────────────

@router.post("/tax/lot-record")
async def portfolio_tax_lot_record(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J4b: Record a new tax lot opened (buy or short-sell)."""
    from ...portfolio.tax_lot_ledger import get_tax_lot_ledger
    required = ("symbol", "broker", "account_id", "qty", "cost_basis_per_share")
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing: {missing}")
    led = await get_tax_lot_ledger()
    return await led.record_open(
        symbol=str(payload["symbol"]),
        broker=str(payload["broker"]),
        account_id=str(payload["account_id"]),
        qty=float(payload["qty"]),
        cost_basis_per_share=float(payload["cost_basis_per_share"]),
        acquisition_date=payload.get("acquisition_date"),
        notes=str(payload.get("notes", "")),
        metadata=payload.get("metadata"),
    )


@router.get("/tax/lots/{symbol}")
async def portfolio_tax_lots(
    symbol: str,
    broker: Optional[str] = Query(default=None),
    account_id: Optional[str] = Query(default=None),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J4b: List open lots for a symbol (optionally filtered)."""
    from ...portfolio.tax_lot_ledger import get_tax_lot_ledger
    led = await get_tax_lot_ledger()
    lots = await led.open_lots_for(symbol, broker=broker, account_id=account_id)
    return {"symbol": symbol.upper(), "count": len(lots), "lots": lots}


@router.post("/tax/lot-recommend")
async def portfolio_tax_lot_recommend(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J4b: Recommend lot-selection sequence for a planned sale.
    Body: {symbol, qty_to_sell, objective (fifo|lifo|hifo|lofo|lt_only|
            st_only|max_loss|min_loss), broker?, account_id?}"""
    from ...portfolio.tax_lot_ledger import get_tax_lot_ledger
    required = ("symbol", "qty_to_sell")
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing: {missing}")
    led = await get_tax_lot_ledger()
    try:
        return await led.recommend_lot_selection(
            symbol=str(payload["symbol"]),
            qty_to_sell=float(payload["qty_to_sell"]),
            objective=str(payload.get("objective", "hifo")),
            broker=payload.get("broker"),
            account_id=payload.get("account_id"),
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve


@router.post("/tax/lot-sale")
async def portfolio_tax_lot_sale(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J4b: After operator confirms sale, decrement lots and emit
    per-lot realized P&L breakdown.
    Body: {symbol, lot_consumption: [{lot_id, qty_consumed}],
           sale_price_per_share, sale_date?}"""
    from ...portfolio.tax_lot_ledger import get_tax_lot_ledger
    required = ("symbol", "lot_consumption", "sale_price_per_share")
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing: {missing}")
    led = await get_tax_lot_ledger()
    return await led.record_sale(
        symbol=str(payload["symbol"]),
        lot_consumption=list(payload["lot_consumption"]),
        sale_price_per_share=float(payload["sale_price_per_share"]),
        sale_date=payload.get("sale_date"),
    )


@router.post("/onchain/tx-record")
async def portfolio_onchain_record(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J5a: Record an on-chain transaction. Idempotent on (chain, tx_hash)."""
    from ...portfolio.on_chain_journal import get_on_chain_journal
    required = ("tx_hash", "chain", "wallet", "timestamp_iso", "category",
                "asset_symbol", "qty")
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing: {missing}")
    j = await get_on_chain_journal()
    try:
        return await j.record_tx(
            tx_hash=str(payload["tx_hash"]),
            chain=str(payload["chain"]),
            wallet=str(payload["wallet"]),
            timestamp_iso=str(payload["timestamp_iso"]),
            category=str(payload["category"]),
            asset_symbol=str(payload["asset_symbol"]),
            qty=float(payload["qty"]),
            price_at_block_usd=payload.get("price_at_block_usd"),
            block_number=payload.get("block_number"),
            contract_address=payload.get("contract_address"),
            gas_paid_usd=float(payload.get("gas_paid_usd", 0.0)),
            counterparty=payload.get("counterparty"),
            notes=str(payload.get("notes", "")),
            metadata=payload.get("metadata"),
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve


@router.get("/onchain/positions")
async def portfolio_onchain_positions(
    wallet: Optional[str] = Query(default=None),
    chain: Optional[str] = Query(default=None),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J5a/b: Open on-chain positions, optionally filtered."""
    from ...portfolio.on_chain_journal import get_on_chain_journal
    j = await get_on_chain_journal()
    positions = await j.positions_for(wallet=wallet, chain=chain)
    return {"count": len(positions), "positions": positions}


@router.get("/onchain/multichain/{wallet}")
async def portfolio_onchain_multichain(
    wallet: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J5b: Multi-chain rollup for one wallet — total qty per symbol
    across all chains."""
    from ...portfolio.on_chain_journal import get_on_chain_journal
    j = await get_on_chain_journal()
    return await j.aggregate_multichain(wallet)


@router.post("/slippage/fill-record")
async def portfolio_slippage_record(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J7c: Record a fill with arrival + VWAP benchmarks."""
    from ...portfolio.slippage_tracker import get_slippage_tracker
    required = ("fill_id", "symbol", "side", "qty", "fill_price")
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing: {missing}")
    tr = await get_slippage_tracker()
    return await tr.record_fill(
        fill_id=str(payload["fill_id"]),
        symbol=str(payload["symbol"]),
        side=str(payload["side"]),
        qty=float(payload["qty"]),
        fill_price=float(payload["fill_price"]),
        arrival_price=(
            float(payload["arrival_price"])
            if payload.get("arrival_price") is not None else None
        ),
        vwap_benchmark_price=(
            float(payload["vwap_benchmark_price"])
            if payload.get("vwap_benchmark_price") is not None else None
        ),
        timestamp_iso=payload.get("timestamp_iso"),
        broker=payload.get("broker"),
        strategy=payload.get("strategy"),
        trade_idea_id=payload.get("trade_idea_id"),
        notes=str(payload.get("notes", "")),
        metadata=payload.get("metadata"),
    )


@router.get("/slippage/by-strategy")
async def portfolio_slippage_by_strategy(
    lookback_days: int = Query(default=90, ge=1, le=365),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J7c: Per-strategy slippage rollup (arrival + VWAP, mean/median/p90)."""
    from ...portfolio.slippage_tracker import get_slippage_tracker
    tr = await get_slippage_tracker()
    rollup = await tr.by_strategy(lookback_days=lookback_days)
    return {"lookback_days": lookback_days, "by_strategy": rollup}


@router.get("/settle/calendar")
async def portfolio_settle_calendar(
    asset_class: str = Query(...),
    trade_date: str = Query(...),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J8d: settle_date(asset_class, trade_date)."""
    from ...portfolio.settle_calendar import settle_date
    sd = settle_date(asset_class, trade_date)
    return {
        "asset_class": asset_class,
        "trade_date": trade_date,
        "settle_date": sd,
    }


@router.post("/settle/cash-view")
async def portfolio_settle_cash_view(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J8d: Compute settled-vs-unsettled cash view from a trade list.
    Body: {trades: [{asset_class, trade_date, cash_delta}], as_of?}"""
    from ...portfolio.settle_calendar import cash_view
    if "trades" not in payload:
        raise HTTPException(status_code=400, detail="Missing: trades[]")
    return cash_view(payload["trades"], as_of=payload.get("as_of"))


@router.get("/settle/bp-view")
async def portfolio_settle_bp_view(
    as_of: Optional[str] = Query(default=None),
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J8d: trade-date BP vs settled-only BP for the portfolio.
    Uses the live PortfolioManager summary + an empty trades list
    (POST trades to /settle/cash-view for fuller breakdown)."""
    from ...portfolio.settle_calendar import bp_view
    pm = _require_manager(pm)
    summary = pm.get_summary("CAD")
    return bp_view(summary, trades=[], as_of=as_of)


# ──────────────────────────────────────────────────────────────────────
# Wave 14J Phase 4-8 endpoints (rotation execution, tax, polymarket,
# telemetry, hygiene). All read-only / advisory.
# ──────────────────────────────────────────────────────────────────────

@router.get("/rotation/pacing/{ticker}")
async def portfolio_rotation_pacing(
    ticker: str,
    sector_etf: Optional[str] = Query(default=None),
    days_in_quadrant: Optional[int] = Query(default=None),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J3a: Pacing plan + breadth veto + stance for a single ticker."""
    from ...portfolio.rotation_execution import annotate_trade_idea
    try:
        from runtime.intelligence.rotation_tracker import load_latest_rotation
        snap = load_latest_rotation()
    except Exception:
        snap = None
    idea = {
        "ticker": ticker.upper(),
        "sector_etf": sector_etf,
        "days_in_quadrant": days_in_quadrant,
        "direction": "long",
    }
    return annotate_trade_idea(idea, rotation_snapshot=snap)


@router.get("/tax/wash-sale-check/{symbol}")
async def portfolio_tax_wash_check(
    symbol: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J4a: Check for recent realized losses on `symbol` that would
    trigger wash-sale disallowance if a new position opens today."""
    from ...portfolio.tax_compliance import get_wash_sale_ledger
    led = await get_wash_sale_ledger()
    flagged = await led.check_open(symbol=symbol)
    return {"symbol": symbol.upper(), "flagged": len(flagged), "entries": flagged}


@router.post("/tax/wash-sale-record")
async def portfolio_tax_wash_record(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J4a: Record a realized loss in the cross-account wash-sale ledger."""
    from ...portfolio.tax_compliance import get_wash_sale_ledger
    required = ("symbol", "broker", "account_id", "loss_date", "loss_amount")
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing: {missing}")
    led = await get_wash_sale_ledger()
    return await led.record_loss(
        symbol=str(payload["symbol"]),
        broker=str(payload["broker"]),
        account_id=str(payload["account_id"]),
        loss_date=str(payload["loss_date"]),
        loss_amount=float(payload["loss_amount"]),
        notes=str(payload.get("notes", "")),
    )


@router.get("/tax/lt-cliff")
async def portfolio_tax_lt_cliff(
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J4c: Positions approaching the long-term holding cliff (>= 340 days)."""
    from ...portfolio.tax_compliance import lt_cliff_scan
    pm = _require_manager(pm)
    positions = pm.get_positions(account_filter="all")
    flagged = lt_cliff_scan(positions)
    return {"count": len(flagged), "positions": flagged}


@router.post("/tax/earnings-sizer")
async def portfolio_tax_earnings_sizer(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J4d: Get size modifier given days_to_earnings.
    Body: {days_to_earnings: int|null}."""
    from ...portfolio.tax_compliance import earnings_size_modifier
    from dataclasses import asdict
    d = payload.get("days_to_earnings")
    m = earnings_size_modifier(d if d is None else int(d))
    return asdict(m)


@router.post("/polymarket/kelly")
async def portfolio_polymarket_kelly(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J6a: Fractional-Kelly size with resolution-time discount."""
    from ...portfolio.polymarket_discipline import kelly_size
    required = ("prob_estimated", "prob_market", "bankroll_usd")
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing: {missing}")
    return kelly_size(
        prob_estimated=float(payload["prob_estimated"]),
        prob_market=float(payload["prob_market"]),
        bankroll_usd=float(payload["bankroll_usd"]),
        days_to_resolution=(
            int(payload["days_to_resolution"])
            if payload.get("days_to_resolution") is not None else None
        ),
        fractional=float(payload.get("fractional", 0.25)),
    )


@router.post("/polymarket/cluster-id")
async def portfolio_polymarket_cluster_id(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J6b: Derive a resolution_cluster_id from market metadata."""
    from ...portfolio.polymarket_discipline import cluster_id_from_metadata
    return {"cluster_id": cluster_id_from_metadata(payload or {})}


@router.post("/polymarket/liquidity-cap")
async def portfolio_polymarket_liquidity_cap(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J6c: Cap proposed size at N% of opposite-side liquidity."""
    from ...portfolio.polymarket_discipline import liquidity_cap
    required = ("proposed_size_usd", "orderbook_depth_usd")
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing: {missing}")
    return liquidity_cap(
        proposed_size_usd=float(payload["proposed_size_usd"]),
        orderbook_depth_usd=float(payload["orderbook_depth_usd"]),
        cap_pct=float(payload.get("cap_pct", 10.0)),
    )


@router.get("/telemetry/risk-adjusted")
async def portfolio_telemetry_risk_adjusted(
    lookback_days: int = Query(default=365, ge=2, le=3650),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J7b: Sharpe / Sortino / Calmar / Recovery Factor from snapshots."""
    from ...portfolio.telemetry import risk_adjusted_returns
    return risk_adjusted_returns(lookback_days=lookback_days)


@router.get("/telemetry/drift")
async def portfolio_telemetry_drift(
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J7d: Target-weight drift alerts vs current allocation."""
    from ...portfolio.telemetry import drift_alerts, load_target_weights
    pm = _require_manager(pm)
    summary = pm.get_summary("CAD")
    target = load_target_weights()
    alerts = drift_alerts(summary, target=target)
    return {"target": target, "alerts": alerts, "count": len(alerts)}


@router.put("/telemetry/target-weights")
async def portfolio_telemetry_set_target(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J7d: Persist operator-set target weights."""
    from ...portfolio.telemetry import save_target_weights
    return save_target_weights(payload)


@router.get("/hygiene/stale-quotes")
async def portfolio_hygiene_stale(
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J8a: Tag every position with staleness metadata."""
    from ...portfolio.hygiene import stale_quote_check
    pm = _require_manager(pm)
    positions = pm.get_positions(account_filter="all")
    out = []
    for p in positions:
        s = stale_quote_check(p)
        s["symbol"] = p.get("symbol")
        out.append(s)
    return {"count": len(out), "positions": out}


@router.get("/hygiene/auth-expiry")
async def portfolio_hygiene_auth_expiry(
    warn_hours: int = Query(default=48, ge=1, le=720),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J8b: Tokens expiring within `warn_hours` (+ already-expired)."""
    from ...portfolio.hygiene import auth_expiry_alerts
    alerts = auth_expiry_alerts(warn_hours=warn_hours)
    return {"warn_hours": warn_hours, "count": len(alerts), "alerts": alerts}


@router.get("/hygiene/circuit-breakers")
async def portfolio_hygiene_breakers(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """J8c: Per-adapter circuit-breaker statuses."""
    from ...portfolio.hygiene import all_breaker_statuses
    return {"breakers": all_breaker_statuses()}


# ──────────────────────────────────────────────────────────────────────
# Wave 14J Phase 3 (J2a + J2c) — Options portfolio Greeks + DTE / pin risk
# Net delta/gamma/theta/vega across the entire options book, plus 21-DTE
# management triggers and Friday pin-risk scanner.
# Backed by runtime/portfolio/options_portfolio.py.
# ──────────────────────────────────────────────────────────────────────

def _spot_lookup_from_positions(positions: list[dict]) -> dict[str, float]:
    """Build {underlying: spot_price} from any equity rows in the position
    cache. Best-effort — options positions don't carry their underlying
    spot, so the operator may need to refresh portfolio sync first."""
    out: dict[str, float] = {}
    for p in positions:
        if not isinstance(p, dict):
            continue
        ac = (p.get("asset_class") or "").lower()
        if ac in ("equity", "stock", "etf"):
            sym = (p.get("symbol") or "").upper()
            px = p.get("last_price") or p.get("current_price")
            if sym and px:
                try:
                    out[sym] = float(px)
                except (TypeError, ValueError):
                    pass
    return out


@router.get("/options/greeks")
async def portfolio_options_greeks(
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Portfolio-level Greeks aggregation across held options.

    Returns:
      net: {delta, gamma, theta, vega}
      by_underlying: {ticker: {delta, gamma, theta, vega}}
      budgets: {delta_max_abs, gamma_max_abs, vega_max_abs,
                theta_min_daily, theta_max_daily}
      flags: [human-readable budget-breach strings]
      position_count: int
    """
    from ...portfolio.options_portfolio import (
        compute_position_greeks, aggregate_greeks,
    )
    pm = _require_manager(pm)
    positions = pm.get_positions(account_filter="all")
    spot = _spot_lookup_from_positions(positions)
    per = compute_position_greeks(positions, spot_lookup=spot)
    summary = pm.get_summary("CAD")
    nav_cad = float(summary.get("total_value", 0) or 0)
    agg = aggregate_greeks(per, nav_cad=nav_cad)
    return {
        "as_of": summary.get("last_sync"),
        "nav_cad": nav_cad,
        **agg,
        "by_position": [
            {
                "symbol": g.symbol, "underlying": g.underlying,
                "right": g.right, "strike": g.strike, "expiry": g.expiry,
                "dte": g.dte, "qty": g.qty, "is_short": g.is_short,
                "delta": g.delta, "gamma": g.gamma,
                "theta": g.theta, "vega": g.vega,
                "broker_greeks": g.broker_greeks,
            }
            for g in per
        ],
    }


@router.get("/options/dte-watch")
async def portfolio_options_dte_watch(
    threshold: int = Query(default=21, ge=1, le=90),
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """SHORT options within N days of expiry (default 21). Inside this
    window gamma acceleration overwhelms theta benefit for short-premium
    structures — close-or-roll review recommended."""
    from ...portfolio.options_portfolio import dte_watchlist
    pm = _require_manager(pm)
    positions = pm.get_positions(account_filter="all")
    candidates = dte_watchlist(positions, threshold=threshold)
    return {
        "threshold_days": threshold,
        "count": len(candidates),
        "candidates": candidates,
    }


@router.get("/options/pin-risk")
async def portfolio_options_pin_risk(
    pct: float = Query(default=0.5, ge=0.1, le=5.0),
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """SHORT options expiring on a Friday within `pct`% of strike. Pin
    risk = spot close to strike makes assignment ambiguous; force-review
    these so the operator can decide before the close."""
    from ...portfolio.options_portfolio import pin_risk_watchlist
    pm = _require_manager(pm)
    positions = pm.get_positions(account_filter="all")
    spot = _spot_lookup_from_positions(positions)
    flagged = pin_risk_watchlist(positions, spot_lookup=spot, pct=pct)
    return {
        "pct_threshold": pct,
        "count": len(flagged),
        "candidates": flagged,
    }


# ──────────────────────────────────────────────────────────────────────
# Wave 14J Phase 2 (J1d) — Trade idea tracker / per-strategy expectancy
# Closed loop: every brief/scanner-emitted idea has a stable trade_idea_id;
# operator records outcomes; tracker computes hit rate / profit factor /
# expectancy in R / SQN per strategy.
# ──────────────────────────────────────────────────────────────────────

@router.get("/trade-ideas")
async def trade_ideas_list(
    strategy: Optional[str] = Query(default=None),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """List all tracked trade ideas, newest first. Optional strategy filter."""
    from ...portfolio.trade_idea_tracker import get_trade_idea_tracker
    tracker = await get_trade_idea_tracker()
    ideas = await tracker.list_by_strategy(strategy=strategy)
    return {"count": len(ideas), "strategy_filter": strategy, "ideas": ideas}


@router.get("/trade-ideas/expectancy")
async def trade_ideas_expectancy(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Per-strategy expectancy stats — the J1d closed-loop scorecard.
    Returns one block per strategy + an "_all" rollup with:
    n_emitted, n_closed, n_winners, n_losers, hit_rate,
    avg_win_R, avg_loss_R, profit_factor, expectancy_R, sqn,
    avg_holding_days, total_R_realized."""
    from ...portfolio.trade_idea_tracker import get_trade_idea_tracker
    tracker = await get_trade_idea_tracker()
    return await tracker.expectancy_by_strategy()


@router.get("/trade-ideas/{trade_idea_id}")
async def trade_idea_get(
    trade_idea_id: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Fetch a single trade idea by id."""
    from ...portfolio.trade_idea_tracker import get_trade_idea_tracker
    tracker = await get_trade_idea_tracker()
    idea = await tracker.get(trade_idea_id)
    if idea is None:
        raise HTTPException(status_code=404, detail=f"Trade idea {trade_idea_id} not found")
    return idea


@router.post("/trade-ideas/{trade_idea_id}/outcome")
async def trade_idea_outcome(
    trade_idea_id: str,
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Record outcome attribution.

    Required: outcome (one of: taken | stopped_out | target_hit |
              manually_closed | expired | not_taken | superseded).
    Optional: exit_price (for R_multiple computation on closed trades),
              notes."""
    from ...portfolio.trade_idea_tracker import get_trade_idea_tracker
    if "outcome" not in payload:
        raise HTTPException(status_code=400, detail="Missing required field: outcome")
    tracker = await get_trade_idea_tracker()
    try:
        result = await tracker.update_outcome(
            trade_idea_id,
            outcome=str(payload["outcome"]),
            exit_price=(float(payload["exit_price"]) if payload.get("exit_price") is not None else None),
            notes=str(payload.get("notes", "")),
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    if result is None:
        raise HTTPException(status_code=404, detail=f"Trade idea {trade_idea_id} not found")
    return result


# ──────────────────────────────────────────────────────────────────────
# Wave 14J Phase 2 (J1a + J1b) — Risk governor endpoints
# Single gate composing per-strategy heat caps with the drawdown
# multiplier. Every consumer (scanners, brief executor, paper trading,
# iOS dashboard) calls this before proposing new risk.
# Backed by runtime/portfolio/risk_governor.py.
# ──────────────────────────────────────────────────────────────────────

@router.get("/risk-governor/heat")
async def portfolio_risk_governor_heat(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Current heat utilization (% of cap used) by strategy + total.
    Shape: nav_cad, band, sizing_multiplier, budgets_pct, total (current_R,
    cap_R, utilization, remaining_R), by_strategy (same shape per bucket).
    """
    from ...portfolio.risk_governor import heat_summary
    return await heat_summary()


@router.post("/risk-governor/check")
async def portfolio_risk_governor_check(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Submit a hypothetical trade for governor approval.

    Required: strategy_tag, R_dollars_proposed.
    Optional: symbol, broker, nav_cad_override (testing).

    Returns approved/decision/reasons + effective_R_dollars (after
    drawdown multiplier) + full heat snapshot. Caller decides what to
    do with the answer — the governor is advisory at the REST surface;
    scanners + executors call check_proposed_trade() directly + treat
    `approved=False` as a hard block.
    """
    from ...portfolio.risk_governor import check_proposed_trade
    required = ("strategy_tag", "R_dollars_proposed")
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required: {missing}")
    try:
        return await check_proposed_trade(
            strategy_tag=str(payload["strategy_tag"]),
            R_dollars_proposed=float(payload["R_dollars_proposed"]),
            symbol=payload.get("symbol"),
            broker=payload.get("broker"),
            nav_cad_override=(
                float(payload["nav_cad_override"])
                if payload.get("nav_cad_override") is not None
                else None
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"check failed: {e}") from e


# ──────────────────────────────────────────────────────────────────────
# Wave 14J Phase 1 (J0c) — Global drawdown bucket endpoints
# Single-source-of-truth drawdown band; read by all autonomous loops +
# scanners + brief pipeline + paper trading BEFORE proposing new sizing.
# Backed by runtime/portfolio/drawdown_bucket.py.
# ──────────────────────────────────────────────────────────────────────

@router.get("/drawdown")
async def portfolio_drawdown(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Current portfolio drawdown state. Returns:
       - current_nav_cad, peak_nav_cad, peak_date
       - drawdown_pct (negative = below peak)
       - band ('green'|'caution'|'warning'|'halt')
       - sizing_multiplier (1.00 / 0.75 / 0.50 / 0.00)
       - last_transition_at / last_transition_from
       - manual_peak_override (operator-pinned HWM, optional)
       - sample_count (snapshots replayed in the lookback window)
    """
    from ...portfolio.drawdown_bucket import get_drawdown_state
    return await get_drawdown_state()


@router.post("/drawdown/recompute")
async def portfolio_drawdown_recompute(
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Force an immediate recompute against the current portfolio NAV.
    Useful for /sync follow-up or operator-initiated state refresh
    between the 60s scheduler ticks."""
    from ...portfolio.drawdown_bucket import get_drawdown_bucket
    pm = _require_manager(pm)
    summary = pm.get_summary("CAD")
    current_nav = float(summary.get("total_value", 0) or 0)
    bucket = await get_drawdown_bucket()
    return await bucket.compute(current_nav)


@router.post("/drawdown/peak-override")
async def portfolio_drawdown_peak_override(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Operator override — pin the trailing high-water mark to a specific
    CAD value. Set `peak_nav_cad` to a number to pin; set to null (or
    omit) to clear the override and revert to snapshot-replayed peak.

    Use case: known deliberate withdrawal or capital injection that
    would otherwise make the drawdown calculation misleading."""
    from ...portfolio.drawdown_bucket import get_drawdown_bucket
    peak_val = payload.get("peak_nav_cad")
    if peak_val is not None:
        try:
            peak_val = float(peak_val)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="peak_nav_cad must be a number or null")
    note = str(payload.get("note", ""))
    bucket = await get_drawdown_bucket()
    return await bucket.set_manual_peak(peak_val, note=note)


# ──────────────────────────────────────────────────────────────────────
# Wave 14J Phase 1 (J0b) — Position risk state (R-fields) endpoints
# Operator-set entry/stop/R_dollars/target/thesis per position-key.
# Backed by runtime/portfolio/position_risk_state.py.
# ──────────────────────────────────────────────────────────────────────

@router.get("/risk-state")
async def portfolio_risk_state(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """All position-keys with R-fields set, plus portfolio-level aggregations
    (total_R_at_risk, by_strategy, by_broker). Drives J1a heat-cap math
    in Wave 14J Phase 2."""
    from ...portfolio.position_risk_state import get_risk_store
    store = await get_risk_store()
    keys = await store.all_keys()
    state_by_key = await store.get_many(keys)
    aggregate = await store.aggregate()
    return {
        "positions": state_by_key,
        "aggregate": aggregate,
    }


@router.get("/risk-state/{position_key:path}")
async def portfolio_risk_state_one(
    position_key: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """R-fields for a single position-key (broker:account:symbol)."""
    from ...portfolio.position_risk_state import get_risk_store
    store = await get_risk_store()
    risk = await store.get(position_key)
    if risk is None:
        raise HTTPException(status_code=404, detail=f"No risk state for {position_key}")
    return risk


@router.patch("/risk-state")
async def portfolio_risk_state_patch(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Set or update R-fields for a position. Partial updates allowed.

    Required: broker, account_id, symbol.
    Optional: qty, entry_price, stop_price, stop_type
              (price|atr|volatility|time|thesis_break), stop_basis,
              target_price, target_basis, thesis, risk_status
              (unset|at_risk|break_even|profit|stopped_out|closed),
              metadata (free-form dict; reserve `strategy_tag` for J1a).

    Auto-computes R_dollars = |entry_price - stop_price| * |qty| when all
    three are present. Auto-flips risk_status from 'unset' to 'at_risk'
    on first set of entry+stop."""
    from ...portfolio.position_risk_state import get_risk_store
    required = ("broker", "account_id", "symbol")
    missing = [k for k in required if not payload.get(k)]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required: {missing}")
    store = await get_risk_store()
    try:
        result = await store.set(
            broker=str(payload["broker"]),
            account_id=str(payload["account_id"]),
            symbol=str(payload["symbol"]),
            qty=payload.get("qty"),
            entry_price=payload.get("entry_price"),
            stop_price=payload.get("stop_price"),
            stop_type=payload.get("stop_type"),
            stop_basis=payload.get("stop_basis"),
            target_price=payload.get("target_price"),
            target_basis=payload.get("target_basis"),
            thesis=payload.get("thesis"),
            risk_status=payload.get("risk_status"),
            metadata=payload.get("metadata"),
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"set failed: {e}") from e
    return result


@router.delete("/risk-state/{position_key:path}")
async def portfolio_risk_state_delete(
    position_key: str,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Remove R-fields for a position-key (e.g. position closed +
    archived). Use PATCH with risk_status='closed' instead if you want
    to keep the record for audit / expectancy attribution."""
    from ...portfolio.position_risk_state import get_risk_store
    store = await get_risk_store()
    ok = await store.clear(position_key)
    if not ok:
        raise HTTPException(status_code=404, detail=f"No risk state for {position_key}")
    return {"status": "cleared", "position_key": position_key}


# ──────────────────────────────────────────────────────────────────────
# Wave 14J Phase 1 (J0a) — Trading cost ledger endpoints
# Mirror of the existing /system/costs surface but for trading costs
# (commissions, financing, borrow, assignment, gas, exchange, slippage,
# regulatory). Source module: runtime/portfolio/trade_cost_ledger.py
# ──────────────────────────────────────────────────────────────────────

@router.get("/trade-costs/today")
async def trade_costs_today(
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Today's trading-cost rollup. Mirrors the in-memory summary held
    by TradeCostLedger; resets at UTC midnight."""
    from ...portfolio.trade_cost_ledger import get_trade_cost_ledger
    ledger = await get_trade_cost_ledger()
    return await ledger.summary_today()


@router.get("/trade-costs/history")
async def trade_costs_history(
    days: int = Query(default=30, ge=1, le=365),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Last N days of trading-cost rollups, newest first."""
    from ...portfolio.trade_cost_ledger import get_trade_cost_ledger
    ledger = await get_trade_cost_ledger()
    rows = await ledger.history(days=days)
    return {"days": days, "entries": rows}


@router.get("/trade-costs/ledger")
async def trade_costs_ledger(
    limit: int = Query(default=100, ge=1, le=1000),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Raw recent entries from the JSONL ledger (audit / debug)."""
    from ...portfolio.trade_cost_ledger import get_trade_cost_ledger
    ledger = await get_trade_cost_ledger()
    rows = await ledger.recent_entries(limit=limit)
    return {"limit": limit, "count": len(rows), "entries": rows}


@router.post("/trade-costs/record")
async def trade_costs_record(
    payload: dict,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Manual record entrypoint. Adapter fill-handlers should call
    `runtime.portfolio.trade_cost_ledger.record_trade_cost(...)` directly;
    this endpoint exists so the iOS app + dashboards can backfill
    historical commissions from broker statements."""
    from ...portfolio.trade_cost_ledger import record_trade_cost
    required = ("broker", "action", "amount_usd")
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required fields: {missing}",
        )
    try:
        await record_trade_cost(
            broker=str(payload["broker"]),
            action=str(payload["action"]),
            amount_usd=float(payload["amount_usd"]),
            symbol=payload.get("symbol"),
            asset_class=payload.get("asset_class"),
            account_id=payload.get("account_id"),
            strategy_tag=payload.get("strategy_tag"),
            currency=str(payload.get("currency", "USD")),
            fx_rate=(float(payload["fx_rate"]) if payload.get("fx_rate") is not None else None),
            metadata=payload.get("metadata"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"record failed: {e}") from e
    return {"status": "ok"}


@router.get("/crypto")
async def portfolio_crypto(
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Combined NDAX + MetaMask view.

    Returns per-broker sections so iOS can render them as two collapsible
    cards. Each holding mirrors the standard PortfolioPosition shape so the
    existing iOS row/code can be reused for rendering if desired.
    """
    pm = _require_manager(pm)

    ndax = _find_adapter(pm, "ndax")
    meta = _find_adapter(pm, "metamask")

    ndax_positions: list = []
    ndax_accounts: list = []
    if ndax is not None and getattr(ndax, "connected", False):
        try:
            ndax_positions = await ndax.get_positions()
            ndax_accounts = await ndax.get_accounts()
        except Exception as exc:
            log.exception("NDAX fetch failed: %s", exc)

    meta_positions: list = []
    meta_accounts: list = []
    if meta is not None and getattr(meta, "connected", False):
        try:
            meta_positions = await meta.get_positions()
            meta_accounts = await meta.get_accounts()  # noqa: F841
        except Exception as exc:
            log.exception("MetaMask fetch failed: %s", exc)

    ndax_value = sum(float(p.get("market_value") or 0) for p in ndax_positions)
    meta_value = sum(float(p.get("market_value") or 0) for p in meta_positions)
    ndax_cad_balance = sum(float(a.get("cash_balance") or 0) for a in ndax_accounts)

    return {
        "ndax": {
            "connected": ndax is not None and getattr(ndax, "connected", False),
            "mode": getattr(ndax, "_mode", "disconnected") if ndax else "disconnected",
            "cad_balance": round(ndax_cad_balance, 2),
            "total_value_cad": round(ndax_value, 2),
            "holdings": ndax_positions,
        },
        "metamask": {
            "connected": meta is not None and getattr(meta, "connected", False),
            "address": getattr(meta, "address", "") if meta else "",
            "total_value_usd": round(meta_value, 2),
            "holdings": meta_positions,
        },
        "totals": {
            "holdings_count": len(ndax_positions) + len(meta_positions),
        },
        "last_sync": pm._last_sync,
    }


@router.get("/polymarket")
async def portfolio_polymarket(
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """
    Polymarket positions + USDC balance + open markets.

    Returns:
        {
          "connected": bool,
          "funder_address": "0x...",
          "usdc_balance": float,
          "positions": [PortfolioPosition...],
          "open_positions_count": int,
          "total_exposure_usd": float,
        }
    """
    pm = _require_manager(pm)

    poly = _find_adapter(pm, "polymarket")
    if poly is None or not getattr(poly, "connected", False):
        return {
            "connected": False,
            "funder_address": getattr(poly, "funder_address", "") if poly else "",
            "usdc_balance": 0.0,
            "positions": [],
            "open_positions_count": 0,
            "total_exposure_usd": 0.0,
            "last_sync": pm._last_sync,
        }

    try:
        positions = await poly.get_positions()
        accounts = await poly.get_accounts()
    except Exception as exc:
        log.exception("Polymarket fetch failed: %s", exc)
        positions = []
        accounts = []

    usdc = float(accounts[0].get("cash_balance", 0.0)) if accounts else 0.0
    exposure = sum(float(p.get("market_value") or 0) for p in positions)

    return {
        "connected": True,
        "funder_address": getattr(poly, "funder_address", ""),
        "usdc_balance": round(usdc, 2),
        "positions": positions,
        "open_positions_count": len(positions),
        "total_exposure_usd": round(exposure, 2),
        "last_sync": pm._last_sync,
    }


@router.post("/connect/ndax")
async def portfolio_connect_ndax(
    request: Request,
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Patch NDAX adapter creds and reconnect.

    Body: ``{"api_key": ..., "api_secret": ..., "user_id": ...}``
    Empty fields are ignored (keep the existing value).
    """
    pm = _require_manager(pm)
    try:
        body = await request.json()
    except Exception:
        body = {}

    adapter = _find_adapter(pm, "ndax")
    if adapter is None:
        try:
            from ...portfolio.ndax_adapter import NDAXAdapter

            adapter = NDAXAdapter()
            pm._adapters.append(("ndax", adapter))
            pm._ndax = adapter
        except Exception as e:
            return {"connected": False, "error": f"adapter unavailable: {e}"}

    if body.get("api_key"):
        adapter.api_key = str(body["api_key"])
    if body.get("api_secret"):
        adapter.api_secret = str(body["api_secret"])
    if body.get("user_id"):
        adapter.user_id = str(body["user_id"])

    try:
        ok = await adapter.connect()
        return {
            "connected": bool(ok),
            "mode": getattr(adapter, "_mode", "disconnected"),
            "broker": "NDAX",
        }
    except Exception as e:
        return {"connected": False, "error": str(e), "broker": "NDAX"}


@router.post("/connect/metamask")
async def portfolio_connect_metamask(
    request: Request,
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Patch MetaMask adapter wallet address and reconnect.

    Body: ``{"address": "0x..."}``
    """
    pm = _require_manager(pm)
    try:
        body = await request.json()
    except Exception:
        body = {}

    address = str(body.get("address", "")).strip()
    if not address:
        return {"connected": False, "error": "address is required"}

    adapter = _find_adapter(pm, "metamask")
    if adapter is None:
        try:
            from ...portfolio.metamask_adapter import MetaMaskAdapter

            adapter = MetaMaskAdapter(address=address)
            pm._adapters.append(("metamask", adapter))
            pm._metamask = adapter
        except Exception as e:
            return {"connected": False, "error": f"adapter unavailable: {e}"}
    else:
        adapter.address = address

    try:
        ok = await adapter.connect()
        return {
            "connected": bool(ok),
            "address": adapter.address,
            "broker": "METAMASK",
        }
    except Exception as e:
        return {"connected": False, "error": str(e), "broker": "METAMASK"}


@router.post("/connect/polymarket")
async def portfolio_connect_polymarket(
    request: Request,
    pm=Depends(get_portfolio_mgr),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Patch Polymarket adapter creds and reconnect.

    Body: ``{"private_key": ..., "funder_address": ...}`` — private key is
    stored on the adapter for future trade flows but not used for read-only
    position fetches. Funder address is the wallet that owns USDC + open
    positions.
    """
    pm = _require_manager(pm)
    try:
        body = await request.json()
    except Exception:
        body = {}

    adapter = _find_adapter(pm, "polymarket")
    if adapter is None:
        try:
            from ...portfolio.polymarket_adapter import PolymarketAdapter

            adapter = PolymarketAdapter()
            pm._adapters.append(("polymarket", adapter))
            pm._polymarket = adapter
        except Exception as e:
            return {"connected": False, "error": f"adapter unavailable: {e}"}

    if body.get("private_key"):
        adapter.private_key = str(body["private_key"])
    if body.get("funder_address"):
        adapter.funder_address = str(body["funder_address"]).strip()

    try:
        ok = await adapter.connect()
        return {
            "connected": bool(ok),
            "funder_address": adapter.funder_address,
            "broker": "POLYMARKET",
        }
    except Exception as e:
        return {"connected": False, "error": str(e), "broker": "POLYMARKET"}
