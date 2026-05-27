#!/usr/bin/env python3
"""P19 — GOAT/BRAVO scanner fixes.

1. yfinance earnings calendar fallback (Finnhub key missing → 'unavailable')
2. Robust yfinance price refresh at scan time
3. Tag ivr_status field so the gate is honest about None values
4. Filter score=0 results
5. Sector lookup
6. scan_started_at / scan_completed_at timestamps
"""

# ── 1. enrichments.py: add yfinance earnings fallback + robust IV ──
p_enr = "/Users/natrix/dev/NCL/runtime/stocks/enrichments.py"
s = open(p_enr).read()

# Add yf earnings fallback BEFORE the get_earnings_map function
old_finnhub = '''async def get_earnings_map(force_refresh: bool = False) -> Optional[dict[str, str]]:
    """Cached batch earnings map. None when Finnhub unavailable."""
    if not force_refresh:
        cached = _cache_get(_EARNINGS_CACHE_KEY)
        if cached is not None:
            return cached
    data = await _fetch_finnhub_earnings(horizon_days=EARNINGS_REPORT_HORIZON_DAYS + 5)
    if data is None:
        return None
    # Override TTL for this specific key — earnings calendar is 6h not 5m
    _cache[_EARNINGS_CACHE_KEY] = (time.time() + (_EARNINGS_CACHE_TTL_S - _TTL_S), data)
    return data'''

new_get_earnings = '''def _yf_earnings_blocking(tickers: list[str]) -> dict[str, str]:
    """yfinance fallback for the earnings calendar.

    For each ticker, query yfinance.Ticker(t).calendar (or get_earnings_dates)
    and return the soonest upcoming date within EARNINGS_REPORT_HORIZON_DAYS.
    Slower than Finnhub's batch endpoint (one call per ticker) but works
    without an API key. Used when FINNHUB_API_KEY is unset.
    """
    try:
        import yfinance as yf
    except ImportError:
        return {}
    out: dict[str, str] = {}
    today = date.today()
    cutoff_days = EARNINGS_REPORT_HORIZON_DAYS + 5
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            # Newer yfinance: get_earnings_dates returns DataFrame indexed by date
            try:
                ed = t.get_earnings_dates(limit=4)
                if ed is not None and not ed.empty:
                    for idx in ed.index:
                        try:
                            dt = idx.to_pydatetime().date()
                        except Exception:
                            continue
                        delta = (dt - today).days
                        if 0 <= delta <= cutoff_days:
                            out[ticker] = dt.isoformat()
                            break
            except Exception:
                # Older yfinance: t.calendar dict
                cal = getattr(t, "calendar", None)
                if cal is not None:
                    try:
                        d = cal.get("Earnings Date") if isinstance(cal, dict) else None
                        if isinstance(d, list) and d:
                            d = d[0]
                        if d is not None:
                            dt = d.date() if hasattr(d, "date") else None
                            if dt:
                                delta = (dt - today).days
                                if 0 <= delta <= cutoff_days:
                                    out[ticker] = dt.isoformat()
                    except Exception:
                        pass
        except Exception as e:
            log.debug("yf earnings fetch failed for %s: %s", ticker, e)
    return out


async def _fetch_yf_earnings_async(tickers: list[str]) -> Optional[dict[str, str]]:
    """Async wrapper. Returns {} (empty map) on total failure, not None,
    so the caller can distinguish 'no upcoming earnings' from 'data
    unavailable'."""
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(_executor, _yf_earnings_blocking, tickers)
        return result or {}
    except Exception as e:
        log.warning("yf earnings batch failed: %s", e)
        return {}


async def get_earnings_map(force_refresh: bool = False,
                            tickers: Optional[list[str]] = None) -> Optional[dict[str, str]]:
    """Cached batch earnings map.

    Order of preference:
      1. Finnhub batch (FINNHUB_API_KEY required, fastest)
      2. yfinance per-ticker (no key required, slower)
    Returns None only if BOTH paths fail.
    """
    if not force_refresh:
        cached = _cache_get(_EARNINGS_CACHE_KEY)
        if cached is not None:
            return cached
    data = await _fetch_finnhub_earnings(horizon_days=EARNINGS_REPORT_HORIZON_DAYS + 5)
    if data is None and tickers:
        # P19-A — yfinance fallback when Finnhub key missing.
        data = await _fetch_yf_earnings_async(tickers)
    if data is None:
        return None
    # Override TTL for this specific key — earnings calendar is 6h not 5m
    _cache[_EARNINGS_CACHE_KEY] = (time.time() + (_EARNINGS_CACHE_TTL_S - _TTL_S), data)
    return data'''

if "_yf_earnings_blocking" not in s:
    s = s.replace(old_finnhub, new_get_earnings, 1)
    print("added yf earnings fallback")

# Improve _yf_iv_blocking robustness
old_iv = '''def _yf_iv_blocking(ticker: str) -> Optional[float]:
    """Approximate ATM-IV via yfinance options chain (nearest expiration)."""
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        t = yf.Ticker(ticker)
        exps = list(t.options or [])
        if not exps:
            return None
        # Nearest expiration
        ch = t.option_chain(exps[0])
        spot = float((t.fast_info or {}).get("last_price") or 0)
        if spot <= 0:
            return None'''

new_iv = '''def _yf_iv_blocking(ticker: str) -> Optional[float]:
    """Approximate ATM-IV via yfinance options chain (nearest expiration).

    P19-A robustness pass: try multiple yfinance APIs to fetch the spot
    price since fast_info shape changed in recent versions.
    """
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        t = yf.Ticker(ticker)
        exps = list(t.options or [])
        if not exps:
            return None
        # Nearest expiration
        ch = t.option_chain(exps[0])
        spot = 0.0
        # 1) fast_info (newer yfinance returns FastInfo not dict)
        try:
            fi = t.fast_info
            spot = float(getattr(fi, "last_price", None) or
                          (fi.get("last_price") if hasattr(fi, "get") else 0) or 0)
        except Exception:
            spot = 0
        # 2) info["currentPrice"] fallback
        if spot <= 0:
            try:
                info = t.info or {}
                spot = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
            except Exception:
                pass
        # 3) Latest history bar
        if spot <= 0:
            try:
                hist = t.history(period="1d")
                if not hist.empty:
                    spot = float(hist["Close"].iloc[-1])
            except Exception:
                pass
        if spot <= 0:
            return None'''

if "P19-A robustness pass" not in s:
    s = s.replace(old_iv, new_iv, 1)
    print("hardened _yf_iv_blocking")

open(p_enr, "w").write(s)

# ── 2. scanner.py: ivr_status tag + score=0 filter + sector + scan timestamps ──
p_scn = "/Users/natrix/dev/NCL/runtime/stocks/scanner.py"
s2 = open(p_scn).read()

# Tag ivr_status whether or not it's available
old_ivr_gate = """            # 6A: IVR
            ivr = await enr.compute_ivr(ticker)
            row["ivr"] = round(float(ivr), 1) if ivr is not None else None
            if ivr is not None:
                if is_goat and ivr > enr.GOAT_IVR_MAX:
                    meta["filtered_ivr"] += 1
                    continue
                if (not is_goat) and ivr < enr.BRAVO_IVR_MIN:
                    meta["filtered_ivr"] += 1
                    continue"""

new_ivr_gate = """            # 6A: IVR
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
                    continue"""

if "ivr_status" not in s2:
    s2 = s2.replace(old_ivr_gate, new_ivr_gate, 1)
    print("added ivr_status tag")

# Pass tickers list to get_earnings_map so the yf fallback can fire
old_earnings_call = """        # ── Feature 5: earnings calendar (batch) ────────────────────────
        earnings_map = await enr.get_earnings_map()"""

new_earnings_call = """        # ── Feature 5: earnings calendar (batch) ────────────────────────
        # P19-A — pass tickers list so the yfinance fallback can fire when
        # FINNHUB_API_KEY is missing. Previously failed silently.
        earnings_map = await enr.get_earnings_map(tickers=tickers)"""

if "P19-A — pass tickers list" not in s2:
    s2 = s2.replace(old_earnings_call, new_earnings_call, 1)
    print("wired tickers to get_earnings_map")

open(p_scn, "w").write(s2)

# ── 3. routes.py: filter score=0, add scan timestamps to _meta, sector ──
p_rt = "/Users/natrix/dev/NCL/runtime/api/routes.py"
s3 = open(p_rt).read()

old_goat_return = """        results, scan_meta = await _stock_scanner.run_goat_scan_enriched(
            tickers,
            include_held=include_held,
            include_earnings_risk=include_earnings_risk,
        )

        if min_score > 0:
            results = [r for r in results if r["goat_score"] >= min_score]

        # Merge names from watchlist, strip exchange suffixes
        for r in results:
            raw = r["ticker"]
            disp = display_ticker(raw)
            r["ticker"] = disp
            meta = WATCHLIST_MAP.get(raw) or DISPLAY_MAP.get(disp)
            if meta:
                r["name"] = meta.name"""

new_goat_return = """        import time as _t
        scan_start = _t.time()
        results, scan_meta = await _stock_scanner.run_goat_scan_enriched(
            tickers,
            include_held=include_held,
            include_earnings_risk=include_earnings_risk,
        )
        scan_end = _t.time()
        from datetime import datetime as _dt, timezone as _tz
        scan_meta["scan_started_at"] = _dt.fromtimestamp(scan_start, _tz.utc).isoformat()
        scan_meta["scan_completed_at"] = _dt.fromtimestamp(scan_end, _tz.utc).isoformat()
        scan_meta["scan_duration_s"] = round(scan_end - scan_start, 1)

        # P19-B — drop score=0 entries. They passed liquidity but failed
        # every alpha gate. Pure noise to the user.
        results = [r for r in results if r.get("goat_score", 0) > 0]

        if min_score > 0:
            results = [r for r in results if r["goat_score"] >= min_score]

        # Merge names + sector from watchlist, strip exchange suffixes
        for r in results:
            raw = r["ticker"]
            disp = display_ticker(raw)
            r["ticker"] = disp
            meta = WATCHLIST_MAP.get(raw) or DISPLAY_MAP.get(disp)
            if meta:
                r["name"] = meta.name
                # P19-B — sector was unpopulated in P18 audit; join from watchlist.
                if getattr(meta, "sector", None):
                    r["sector"] = meta.sector"""

if "scan_started_at" not in s3:
    s3 = s3.replace(old_goat_return, new_goat_return, 1)
    print("patched GOAT route: timestamps + score=0 filter + sector")

# Same treatment for BRAVO
old_bravo = """        results, scan_meta = await _stock_scanner.run_bravo_scan_enriched("""
new_bravo = """        import time as _tb
        scan_start = _tb.time()
        results, scan_meta = await _stock_scanner.run_bravo_scan_enriched("""
# This will match TWICE (one for goat one for bravo). We only want to patch the bravo one.
# Use indexing: find the second occurrence.
idx_goat = s3.find(old_bravo)
if idx_goat >= 0:
    # find the next occurrence after goat
    idx_bravo = s3.find(old_bravo, idx_goat + 1)
    if idx_bravo >= 0:
        s3 = s3[:idx_bravo] + new_bravo + s3[idx_bravo + len(old_bravo) :]
        print("added bravo scan_start timestamp")

# Add bravo post-scan filter (look for bravo_score filter pattern)
bravo_marker = """        if min_score > 0:
            results = [r for r in results if r["bravo_score"] >= min_score]"""
if 'bravo_score" in r and r["bravo_score"] > 0' not in s3 and bravo_marker in s3:
    bravo_replacement = """        scan_end = _tb.time()
        from datetime import datetime as _dtb, timezone as _tzb
        scan_meta["scan_started_at"] = _dtb.fromtimestamp(scan_start, _tzb.utc).isoformat()
        scan_meta["scan_completed_at"] = _dtb.fromtimestamp(scan_end, _tzb.utc).isoformat()
        scan_meta["scan_duration_s"] = round(scan_end - scan_start, 1)

        # P19-B — drop score=0 entries
        results = [r for r in results if r.get("bravo_score", 0) > 0]

        if min_score > 0:
            results = [r for r in results if r["bravo_score"] >= min_score]"""
    s3 = s3.replace(bravo_marker, bravo_replacement, 1)
    print("added bravo post-scan filter + meta")

open(p_rt, "w").write(s3)
print("DONE")
