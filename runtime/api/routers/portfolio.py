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
