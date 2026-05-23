"""
Portfolio API routes for NCL Brain.

Provides endpoints for portfolio summary, positions, accounts,
performance history, and manual sync triggers.
"""

import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request

log = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

# Module-level reference — injected by Brain startup via set_portfolio_manager()
_portfolio_manager = None


def set_portfolio_manager(pm) -> None:
    """Called by Brain startup to inject the PortfolioManager singleton."""
    global _portfolio_manager
    _portfolio_manager = pm


def _get_strike_token() -> str:
    """Lazily resolve the strike token — reads at call time, not import time."""
    try:
        from runtime.api.routes import STRIKE_TOKEN
        return STRIKE_TOKEN
    except ImportError:
        return os.getenv("STRIKE_AUTH_TOKEN", "")


def _verify_strike_token(authorization: str):
    """Verify the strike point auth token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.replace("Bearer ", "").strip()
    strike_token = _get_strike_token()
    if not strike_token or not secrets.compare_digest(token, strike_token):
        raise HTTPException(status_code=403, detail="Invalid strike token")


def _require_manager():
    """Return the portfolio manager or raise 503 if not initialized."""
    if _portfolio_manager is None:
        raise HTTPException(
            status_code=503,
            detail="Portfolio manager not initialized",
        )
    return _portfolio_manager


# ─────────────────────────────────────────────────────────────────────────────
# GET /portfolio/summary
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/summary")
async def portfolio_summary(
    base_currency: str = Query(default="CAD"),
    authorization: str = Header(default=""),
) -> dict:
    """
    Aggregated portfolio snapshot across all brokerage accounts.

    Returns total value, daily/total P&L, cash totals, allocation
    breakdown, FX rate, sync timestamp, and market-open flag.
    """
    _verify_strike_token(authorization)
    pm = _require_manager()

    try:
        summary = pm.get_summary(base_currency=base_currency)
        return {
            "total_value": summary.get("total_value", 0),
            "base_currency": summary.get("base_currency", base_currency),
            "daily_pl": summary.get("daily_pl", 0),
            "daily_pl_pct": summary.get("daily_pl_pct", 0),
            "total_pl": summary.get("total_pl", 0),
            "total_pl_pct": summary.get("total_pl_pct", 0),
            "cash_total": summary.get("cash_total", 0),
            "positions_count": summary.get("positions_count", 0),
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
    authorization: str = Header(default=""),
) -> dict:
    """
    List positions, optionally filtered by brokerage account.
    """
    _verify_strike_token(authorization)
    pm = _require_manager()

    if account not in VALID_ACCOUNTS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid account filter '{account}'. Must be one of: {', '.join(sorted(VALID_ACCOUNTS))}",
        )

    try:
        positions = pm.get_positions(account_filter=account)
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
    authorization: str = Header(default=""),
) -> dict:
    """
    List all connected brokerage accounts with metadata.
    """
    _verify_strike_token(authorization)
    pm = _require_manager()

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
    authorization: str = Header(default=""),
) -> dict:
    """
    Historical performance data for charting.

    Returns data points, start/end values, and absolute/percentage change
    over the requested time range.
    """
    _verify_strike_token(authorization)
    pm = _require_manager()

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
    authorization: str = Header(default=""),
) -> dict:
    """
    Portfolio system health — adapter connection status, cache info, FX rate.
    """
    _verify_strike_token(authorization)
    pm = _require_manager()
    return pm.health()


# ─────────────────────────────────────────────────────────────────────────────
# POST /portfolio/connect/ibkr   (2026-05-22 audit fix)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/connect/ibkr")
async def portfolio_connect_ibkr(
    request: Request,
    authorization: str = Header(default=""),
) -> dict:
    """Patch IBKR adapter settings (host/port/client_id) and (re)connect.

    Body: {"host": "127.0.0.1", "port": 7497, "client_id": 1}
    Returns: {"connected": bool, "error": str|null, "accounts": int}
    """
    _verify_strike_token(authorization)
    pm = _require_manager()
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
            from .ibkr_adapter import IBKRAdapter
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
        except Exception:
            pass
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
            except Exception:
                pass
        return {
            "connected": bool(ok),
            "error": None if ok else (
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
            hint = " — TWS accepted the socket but never completed the handshake. Check API settings + Trusted IPs."
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
    authorization: str = Header(default=""),
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
    _verify_strike_token(authorization)
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
    authorization: str = Header(default=""),
) -> dict:
    """
    Trigger an immediate sync of all brokerage accounts.
    """
    _verify_strike_token(authorization)
    pm = _require_manager()

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
    authorization: str = Header(default=""),
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
    _verify_strike_token(authorization)
    pm = _require_manager()

    # Resolve the agent_signals.jsonl path — same root the agent uses.
    data_root = Path(os.getenv("NCL_DATA_DIR", "data"))
    if not data_root.is_absolute():
        # PortfolioRoutes are imported from runtime/portfolio so anchor on NCL root
        data_root = Path(__file__).resolve().parents[2] / data_root
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
        g = grouped.setdefault(t, {
            "ticker": t,
            "total_premium_usd": 0.0,
            "call_premium": 0.0,
            "put_premium": 0.0,
            "trade_count": 0,
            "latest_at": "",
            "trades": [],
        })
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
        ratio = (g["call_premium"] / put) if put else (g["call_premium"] / 1.0 if g["call_premium"] else 0.0)
        # Top 5 trades by premium for drill-in
        top_trades = sorted(g["trades"], key=lambda r: r["premium"], reverse=True)[:5]
        rows.append({
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
        })

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
    authorization: str = Header(default=""),
) -> dict:
    """
    Static library of the three named options strategies (0DTE, 5-Day
    Swing, Long Call). Used by the iOS OPTIONS sub-tab → STRATEGIES mode.

    Pure read — no manager required.
    """
    _verify_strike_token(authorization)
    from .options_strategies import all_strategies_payload
    return {
        "strategies": all_strategies_payload(),
        "count": 3,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/options/positions/with-strategy")
async def portfolio_options_positions_with_strategy(
    account: str = Query(default="all"),
    authorization: str = Header(default=""),
) -> dict:
    """
    Held option positions enriched with ``matched_strategy`` +
    parsed OCC fields (underlying, expiry, strike, right, DTE).

    Non-option positions are filtered out — this endpoint is the data
    source for the iOS OPTIONS → HELD sub-mode.
    """
    _verify_strike_token(authorization)
    pm = _require_manager()

    if account not in VALID_ACCOUNTS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid account filter '{account}'. Must be one of: {', '.join(sorted(VALID_ACCOUNTS))}",
        )

    from .options_strategies import enrich_position_with_strategy

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
        created = u.created_at.isoformat() if hasattr(u.created_at, "isoformat") else str(u.created_at)
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
    source: Optional[str] = Query(default=None, description="Filter by portfolio:* source (snapshot, position_opened, etc.)"),
    authorization: str = Header(default=""),
) -> dict:
    """
    Recent portfolio:* memory units, newest first.

    Each unit is one event written by the portfolio memory bridge —
    snapshots, position open/close, significant moves, account drift,
    buying-power risk, quantity changes.
    """
    _verify_strike_token(authorization)

    try:
        # Re-fetch module each call to dodge stale-global capture.
        import runtime.api.routes as _routes
        _brain = getattr(_routes, "brain", None)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Brain unavailable: {exc}")

    if _brain is None or not getattr(_brain, "memory_store", None):
        raise HTTPException(status_code=503, detail="Memory store not initialised")

    try:
        units = await _brain.memory_store.search_units(
            tags=["portfolio"],
            importance_threshold=0.0,
            days_back=30,
        )
    except Exception as e:
        log.exception("Portfolio events search failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Portfolio events error: {e}")

    # Newest first
    try:
        from datetime import datetime, timezone
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
    authorization: str = Header(default=""),
) -> dict:
    """
    Peek at the in-memory portfolio bridge state.

    Returns the freshest cached summary + position count + when the
    bridge last saw a sync. Used for verifying the chat-context portfolio
    injector has live data without having to hit the (potentially slow)
    create_unit path.
    """
    _verify_strike_token(authorization)
    try:
        from .memory_bridge import get_bridge
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
    authorization: str = Header(default=""),
) -> dict:
    """
    Portfolio:significant_move events in the requested window.

    Returns position-level AND portfolio-level moves unless scope is
    constrained. Sorted newest first.
    """
    _verify_strike_token(authorization)

    try:
        # Re-fetch module each call to dodge stale-global capture.
        import runtime.api.routes as _routes
        _brain = getattr(_routes, "brain", None)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Brain unavailable: {exc}")

    if _brain is None or not getattr(_brain, "memory_store", None):
        raise HTTPException(status_code=503, detail="Memory store not initialised")

    try:
        units = await _brain.memory_store.search_units(
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
        from datetime import datetime, timezone
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


@router.get("/crypto")
async def portfolio_crypto(
    authorization: str = Header(default=""),
) -> dict:
    """
    Combined NDAX + MetaMask view.

    Returns per-broker sections so iOS can render them as two collapsible
    cards. Each holding mirrors the standard PortfolioPosition shape so the
    existing iOS row/code can be reused for rendering if desired.
    """
    _verify_strike_token(authorization)
    pm = _require_manager()

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
            meta_accounts = await meta.get_accounts()
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
    authorization: str = Header(default=""),
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
    _verify_strike_token(authorization)
    pm = _require_manager()

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
    authorization: str = Header(default=""),
) -> dict:
    """Patch NDAX adapter creds and reconnect.

    Body: ``{"api_key": ..., "api_secret": ..., "user_id": ...}``
    Empty fields are ignored (keep the existing value).
    """
    _verify_strike_token(authorization)
    pm = _require_manager()
    try:
        body = await request.json()
    except Exception:
        body = {}

    adapter = _find_adapter(pm, "ndax")
    if adapter is None:
        try:
            from .ndax_adapter import NDAXAdapter
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
    authorization: str = Header(default=""),
) -> dict:
    """Patch MetaMask adapter wallet address and reconnect.

    Body: ``{"address": "0x..."}``
    """
    _verify_strike_token(authorization)
    pm = _require_manager()
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
            from .metamask_adapter import MetaMaskAdapter
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
    authorization: str = Header(default=""),
) -> dict:
    """Patch Polymarket adapter creds and reconnect.

    Body: ``{"private_key": ..., "funder_address": ...}`` — private key is
    stored on the adapter for future trade flows but not used for read-only
    position fetches. Funder address is the wallet that owns USDC + open
    positions.
    """
    _verify_strike_token(authorization)
    pm = _require_manager()
    try:
        body = await request.json()
    except Exception:
        body = {}

    adapter = _find_adapter(pm, "polymarket")
    if adapter is None:
        try:
            from .polymarket_adapter import PolymarketAdapter
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
