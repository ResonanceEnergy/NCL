"""Wave 14AH (2026-05-30) — Free data-source fetchers.

Pure read-only adapters for free APIs that extend NCL's data substrate
without adding ongoing cost:

  - CCXT (`fetch_ccxt_tickers`)      — crypto spot prices via Binance/Coinbase
                                       public endpoints (no auth needed)
  - Federal Reserve RSS              — speeches + press releases + statistical
    (`fetch_fed_speeches`, `fetch_fed_press_releases`) — replaces the
    hardcoded FOMC date list in calendar/events.py with a self-updating feed
  - CFTC Commitments of Traders      — weekly futures positioning (Tue data,
    (`fetch_cftc_cot`)                 Fri release) for the rotation tracker
  - Open-Meteo extended              — air quality + UV index + pollen for
    (`fetch_open_meteo_air_quality`)   the Calendar lane ambient context
  - Edmonton + Calgary open-data     — Socrata-backed event feeds for
    (`fetch_edmonton_events`,          NATRIX's two home cities
     `fetch_calgary_events`)

Every function is async, uses a shared httpx client, returns plain dict/list
shapes, and degrades gracefully (returns []  or {} on failure). All free
forever; no keys required.

Consumers wire each fetcher in the appropriate place:
  - awarebot/agent.py             → fetch_ccxt_tickers
  - calendar/events.py            → fetch_fed_speeches + fed_press_releases
  - intelligence/rotation_tracker → fetch_cftc_cot
  - calendar/local_events.py      → fetch_open_meteo_air_quality
                                  → fetch_edmonton_events + fetch_calgary_events
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from xml.etree import ElementTree as ET

import httpx


log = logging.getLogger("ncl.intelligence.free_sources")


# ── Module-level HTTP client + small TTL cache ─────────────────────────

_client: Optional[httpx.AsyncClient] = None
_cache: dict[str, tuple[float, object]] = {}  # key -> (expiry_ts, payload)


async def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=20.0)
    return _client


def _cache_get(key: str) -> object | None:
    item = _cache.get(key)
    if item is None:
        return None
    expiry, payload = item
    if time.time() > expiry:
        _cache.pop(key, None)
        return None
    return payload


def _cache_put(key: str, payload: object, ttl_s: int) -> None:
    _cache[key] = (time.time() + ttl_s, payload)


# ═══════════════════════════════════════════════════════════════════════
# CCXT — free crypto spot prices (no auth needed for public endpoints)
# ═══════════════════════════════════════════════════════════════════════


_CCXT_DEFAULT_SYMBOLS = (
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "DOGE/USDT",
    "AVAX/USDT",
    "MATIC/USDT",
    "LINK/USDT",
    "XRP/USDT",
    "ADA/USDT",
    "DOT/USDT",
)


async def fetch_ccxt_tickers(
    symbols: tuple[str, ...] = _CCXT_DEFAULT_SYMBOLS,
    exchange: str = "binance",
) -> list[dict]:
    """Spot price + 24h volume + 24h % change for each symbol.

    Uses CCXT's async exchange wrapper. `binance` public REST is the most
    reliable free endpoint; `coinbase`, `kraken`, and `kucoin` also work
    with no auth. Returns [] on any failure (does not raise).

    Output rows: {symbol, last_usd, volume_24h, pct_change_24h, source}.
    """
    cache_key = f"ccxt:{exchange}:{','.join(symbols)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)  # type: ignore[arg-type]

    try:
        import ccxt.async_support as ccxt  # type: ignore
    except Exception as e:
        log.warning("[ccxt] import failed: %s — install with: pip install ccxt", e)
        return []

    ex_cls = getattr(ccxt, exchange, None)
    if ex_cls is None:
        log.warning("[ccxt] unknown exchange %r", exchange)
        return []
    ex = ex_cls({"enableRateLimit": True})
    rows: list[dict] = []
    try:
        # Batched fetch_tickers is cheaper than per-symbol round trips.
        tickers = await ex.fetch_tickers(list(symbols))
        for sym, t in (tickers or {}).items():
            if not isinstance(t, dict):
                continue
            last = t.get("last") or t.get("close") or 0
            rows.append(
                {
                    "symbol": sym,
                    "last_usd": float(last) if last else 0.0,
                    "volume_24h": float(t.get("quoteVolume") or 0),
                    "pct_change_24h": float(t.get("percentage") or 0),
                    "source": f"ccxt:{exchange}",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
            )
    except Exception as e:
        log.warning("[ccxt] fetch_tickers failed on %s: %s", exchange, e)
    finally:
        try:
            await ex.close()
        except Exception:
            pass

    if rows:
        _cache_put(cache_key, rows, ttl_s=120)  # 2 min cache
    return rows


# ═══════════════════════════════════════════════════════════════════════
# FEDERAL RESERVE RSS — self-updating FOMC + speeches + releases
# ═══════════════════════════════════════════════════════════════════════


# Public RSS feeds, no key, no quota.
_FED_RSS_SPEECHES = "https://www.federalreserve.gov/feeds/speeches.xml"
_FED_RSS_PRESS = "https://www.federalreserve.gov/feeds/press_all.xml"
_FED_RSS_STAT_RELEASES = "https://www.federalreserve.gov/feeds/h41.xml"


async def _fetch_rss(url: str) -> list[dict]:
    """Fetch + parse an RSS 2.0 / Atom feed, return list of item dicts."""
    try:
        client = await _http()
        resp = await client.get(url, headers={"User-Agent": "NCL/1.0 (personal AI)"})
        resp.raise_for_status()
        body = resp.text
    except Exception as e:
        log.warning("[fed-rss] fetch failed %s: %s", url, e)
        return []
    items: list[dict] = []
    try:
        root = ET.fromstring(body)
        # Try RSS 2.0 first: rss > channel > item
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            desc = (item.findtext("description") or "").strip()
            if title:
                items.append({"title": title, "url": link, "published": pub, "description": desc[:500]})
        # If empty, try Atom
        if not items:
            ns = {"a": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("a:entry", ns):
                title_el = entry.find("a:title", ns)
                link_el = entry.find("a:link", ns)
                pub_el = entry.find("a:updated", ns) or entry.find("a:published", ns)
                items.append(
                    {
                        "title": (title_el.text or "").strip() if title_el is not None else "",
                        "url": link_el.get("href", "") if link_el is not None else "",
                        "published": pub_el.text if pub_el is not None else "",
                        "description": "",
                    }
                )
    except ET.ParseError as e:
        log.warning("[fed-rss] parse failed %s: %s", url, e)
    return items


async def fetch_fed_speeches(limit: int = 15) -> list[dict]:
    """Recent Federal Reserve speeches with date + speaker (from title)."""
    cache_key = "fed:speeches"
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)[:limit]  # type: ignore[arg-type]
    items = await _fetch_rss(_FED_RSS_SPEECHES)
    _cache_put(cache_key, items, ttl_s=3600)  # 1h cache
    return items[:limit]


async def fetch_fed_press_releases(limit: int = 20) -> list[dict]:
    """Recent Federal Reserve press releases — includes FOMC decisions."""
    cache_key = "fed:press"
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)[:limit]  # type: ignore[arg-type]
    items = await _fetch_rss(_FED_RSS_PRESS)
    _cache_put(cache_key, items, ttl_s=1800)  # 30min cache (faster on FOMC days)
    return items[:limit]


# ═══════════════════════════════════════════════════════════════════════
# CFTC COMMITMENTS OF TRADERS — weekly futures positioning
# ═══════════════════════════════════════════════════════════════════════


# CFTC Traders-in-Financial-Futures (TFF), Aggregated. Verified live
# 2026-05-30: dataset id gpe5-46if has current weekly drops (last:
# 2026-05-26). Columns differ from the legacy CIT reports — see schema
# probe in outputs/_probe_schemas.py.
_CFTC_DATASET = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"

# Verified 2026-05-30 against the live gpe5-46if dataset — exact strings.
# The TFF dataset covers FINANCIAL futures only (equity, rates, FX,
# crypto). Commodity futures (GC, SI, CL, NG) live in the Disaggregated
# Commodities report and aren't included here.
# Verified 2026-05-30 against the live gpe5-46if dataset. The CFTC
# rolled the legacy E-MINI S&P 500 + S&P 500 STOCK INDEX entries into
# "S&P 500 Consolidated" in 2022; same for NASDAQ-100. Use the
# Consolidated names — they're the only ones with current 2026 data.
# Russell 2000 active futures live on the MICRO CME contract; the ICE
# variant was discontinued 2018.
_CFTC_MARKET_MAP = {
    "ES": "S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE",
    "NQ": "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE",
    "RTY": "MICRO E-MINI RUSSELL 2000 INDX - CHICAGO MERCANTILE EXCHANGE",
    "MES": "MICRO E-MINI S&P 500 INDEX - CHICAGO MERCANTILE EXCHANGE",
    "MNQ": "MICRO E-MINI NASDAQ-100 INDEX - CHICAGO MERCANTILE EXCHANGE",
    "BTC": "BITCOIN - CHICAGO MERCANTILE EXCHANGE",
}


async def fetch_cftc_cot(
    markets: Optional[tuple[str, ...]] = None,
    limit_per_market: int = 4,
) -> list[dict]:
    """Latest 4 weekly COT prints per market (16 weeks of history each).

    Returns rows: {ticker, market_name, report_date, leveraged_long,
    leveraged_short, leveraged_net, asset_mgr_long, asset_mgr_short,
    asset_mgr_net, dealer_long, dealer_short, dealer_net}.

    The 'net' fields are computed from raw long-short. Useful for the
    rotation tracker: large negative leveraged_net = hedge funds heavily
    short; flip-of-sign = positioning rotation.
    """
    if markets is None:
        markets = tuple(_CFTC_MARKET_MAP.keys())

    cache_key = f"cftc:{','.join(markets)}:{limit_per_market}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)  # type: ignore[arg-type]

    client = await _http()
    out: list[dict] = []
    for tkr in markets:
        market_name = _CFTC_MARKET_MAP.get(tkr)
        if not market_name:
            continue
        try:
            # Exact match — the LIKE pattern caught stale legacy entries
            # (e.g. "S&P 500 STOCK INDEX" with 2022 dates vs the active
            # "E-MINI S&P 500 STOCK INDEX").
            params = {
                "$where": f"market_and_exchange_names = '{market_name}'",
                "$order": "report_date_as_yyyy_mm_dd DESC",
                "$limit": str(limit_per_market),
            }
            r = await client.get(_CFTC_DATASET, params=params)
            r.raise_for_status()
            rows = r.json() or []
        except Exception as e:
            log.warning("[cftc] fetch failed for %s: %s", tkr, e)
            continue
        for row in rows:
            try:
                # Schema verified 2026-05-30 against gpe5-46if. Note: the
                # asset_mgr and lev_money columns do NOT have a "_all"
                # suffix in this dataset; the dealer columns DO.
                lev_long = int(row.get("lev_money_positions_long", 0) or 0)
                lev_short = int(row.get("lev_money_positions_short", 0) or 0)
                am_long = int(row.get("asset_mgr_positions_long", 0) or 0)
                am_short = int(row.get("asset_mgr_positions_short", 0) or 0)
                dl_long = int(row.get("dealer_positions_long_all", 0) or 0)
                dl_short = int(row.get("dealer_positions_short_all", 0) or 0)
                out.append(
                    {
                        "ticker": tkr,
                        "market_name": row.get("market_and_exchange_names", market_name),
                        "report_date": (row.get("report_date_as_yyyy_mm_dd") or "")[:10],
                        "leveraged_long": lev_long,
                        "leveraged_short": lev_short,
                        "leveraged_net": lev_long - lev_short,
                        "asset_mgr_long": am_long,
                        "asset_mgr_short": am_short,
                        "asset_mgr_net": am_long - am_short,
                        "dealer_long": dl_long,
                        "dealer_short": dl_short,
                        "dealer_net": dl_long - dl_short,
                        "source": "cftc:cot",
                    }
                )
            except Exception as e:
                log.debug("[cftc] row parse skipped: %s", e)

    if out:
        _cache_put(cache_key, out, ttl_s=3600 * 6)  # 6h — COT is weekly anyway
    return out


# ═══════════════════════════════════════════════════════════════════════
# OPEN-METEO EXTENDED — air quality + UV + pollen
# ═══════════════════════════════════════════════════════════════════════


# Edmonton + Calgary + Panama City + San Salvador + Montevideo + Asuncion + Oaxaca
_CITY_COORDS = {
    "edmonton": (53.5461, -113.4938),
    "calgary": (51.0447, -114.0719),
    "panama_city": (8.9824, -79.5199),
    "san_salvador": (13.6929, -89.2182),
    "montevideo": (-34.9011, -56.1645),
    "asuncion": (-25.2637, -57.5759),
    "oaxaca": (17.0731, -96.7266),
}


async def fetch_open_meteo_air_quality(city: str = "edmonton") -> dict:
    """UV index + PM2.5 + PM10 + ozone + pollen for a city.

    Returns {} on failure or unknown city. Otherwise dict with:
      city, lat, lon, fetched_at,
      uv_index_now, uv_index_max_today,
      pm2_5_now, pm10_now, ozone_now, no2_now, so2_now, co_now,
      alder_pollen, birch_pollen, grass_pollen, mugwort_pollen,
      olive_pollen, ragweed_pollen,
      aqi_us (US EPA scale)
    """
    coords = _CITY_COORDS.get(city.lower())
    if not coords:
        return {}
    lat, lon = coords

    cache_key = f"air:{city}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return dict(cached)  # type: ignore[arg-type]

    client = await _http()
    out: dict = {"city": city, "lat": lat, "lon": lon}
    try:
        # Air quality endpoint (free, no key)
        r = await client.get(
            "https://air-quality-api.open-meteo.com/v1/air-quality",
            params={
                "latitude": str(lat),
                "longitude": str(lon),
                "current": "pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone,uv_index,alder_pollen,birch_pollen,grass_pollen,mugwort_pollen,olive_pollen,ragweed_pollen,us_aqi",
                "timezone": "auto",
            },
        )
        r.raise_for_status()
        data = r.json()
        cur = (data or {}).get("current") or {}
        out.update(
            {
                "uv_index_now": cur.get("uv_index"),
                "pm2_5_now": cur.get("pm2_5"),
                "pm10_now": cur.get("pm10"),
                "ozone_now": cur.get("ozone"),
                "no2_now": cur.get("nitrogen_dioxide"),
                "so2_now": cur.get("sulphur_dioxide"),
                "co_now": cur.get("carbon_monoxide"),
                "alder_pollen": cur.get("alder_pollen"),
                "birch_pollen": cur.get("birch_pollen"),
                "grass_pollen": cur.get("grass_pollen"),
                "mugwort_pollen": cur.get("mugwort_pollen"),
                "olive_pollen": cur.get("olive_pollen"),
                "ragweed_pollen": cur.get("ragweed_pollen"),
                "aqi_us": cur.get("us_aqi"),
            }
        )
        # Today's UV max from the forecast endpoint
        r2 = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": str(lat),
                "longitude": str(lon),
                "daily": "uv_index_max,uv_index_clear_sky_max",
                "timezone": "auto",
                "forecast_days": "1",
            },
        )
        r2.raise_for_status()
        daily = (r2.json() or {}).get("daily") or {}
        uv_max = (daily.get("uv_index_max") or [None])[0]
        out["uv_index_max_today"] = uv_max
    except Exception as e:
        log.warning("[open-meteo:aq] %s failed: %s", city, e)
        return {}

    out["fetched_at"] = datetime.now(timezone.utc).isoformat()
    _cache_put(cache_key, out, ttl_s=3600)  # 1h cache
    return out


# ═══════════════════════════════════════════════════════════════════════
# EDMONTON + CALGARY OPEN DATA (Socrata)
# ═══════════════════════════════════════════════════════════════════════


_EDMONTON_EVENTS_DATASET = "https://data.edmonton.ca/resource/64u3-c7bh.json"
# "Public Events Calendar Listings"

# Calgary doesn't publish a curated event-listings dataset on the Socrata
# portal (the obvious ids point at building permits / community
# development — see outputs/_probe_schemas.py). Wave 14AH leaves this as
# a stub that returns []; future work should try the City of Calgary's
# Tourism Calgary or `visitcalgary.com` event RSS instead.
_CALGARY_EVENTS_DATASETS: tuple[str, ...] = ()


async def fetch_edmonton_events(days_ahead: int = 14, limit: int = 50) -> list[dict]:
    """Public events from data.edmonton.ca for the next N days.

    Schema verified 2026-05-30: actual columns are `begins`, `ends`,
    `event_type`, `event_venue`, `start_time`, `end_time`, `title` —
    NOT the `event_start_date` / `event_name` pattern other Socrata
    instances use.
    """
    cache_key = f"edm:events:{days_ahead}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)[:limit]  # type: ignore[arg-type]

    client = await _http()
    start = datetime.now(timezone.utc).date()
    end = start + timedelta(days=days_ahead)
    try:
        params = {
            "$where": f"begins >= '{start.isoformat()}T00:00:00' AND begins <= '{end.isoformat()}T23:59:59'",
            "$order": "begins ASC",
            "$limit": str(limit),
        }
        r = await client.get(_EDMONTON_EVENTS_DATASET, params=params)
        r.raise_for_status()
        rows = r.json() or []
    except Exception as e:
        log.warning("[edmonton-events] fetch failed: %s", e)
        return []

    out: list[dict] = []
    for row in rows:
        title = row.get("title") or ""
        if not title:
            continue
        out.append(
            {
                "title": title,
                "category": (row.get("event_type") or "local").lower(),
                "date": (row.get("begins") or "")[:10],
                "end_date": (row.get("ends") or "")[:10],
                "start_time": row.get("start_time", ""),
                "end_time": row.get("end_time", ""),
                "venue": row.get("event_venue") or "",
                "city": "edmonton",
                "source": "data.edmonton.ca",
                "url": "",
                "description": "",
            }
        )

    _cache_put(cache_key, out, ttl_s=3600 * 2)  # 2h cache
    return out[:limit]


async def fetch_calgary_events(days_ahead: int = 14, limit: int = 50) -> list[dict]:
    """Public events from data.calgary.ca for the next N days."""
    cache_key = f"cal:events:{days_ahead}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)[:limit]  # type: ignore[arg-type]

    client = await _http()
    start = datetime.now(timezone.utc).date()
    end = start + timedelta(days=days_ahead)
    out: list[dict] = []
    for ds in _CALGARY_EVENTS_DATASETS:
        try:
            params = {
                "$where": f"start_date >= '{start.isoformat()}' AND start_date <= '{end.isoformat()}'",
                "$order": "start_date ASC",
                "$limit": str(limit),
            }
            r = await client.get(ds, params=params)
            r.raise_for_status()
            rows = r.json() or []
        except Exception as e:
            log.debug("[calgary-events] fetch failed for %s: %s", ds, e)
            continue
        for row in rows:
            title = row.get("name") or row.get("event_name") or ""
            if not title:
                continue
            out.append(
                {
                    "title": title,
                    "category": (row.get("category") or row.get("event_type") or "local").lower(),
                    "date": row.get("start_date") or row.get("event_start_date") or "",
                    "end_date": row.get("end_date") or row.get("event_end_date") or "",
                    "venue": row.get("venue") or row.get("location") or "",
                    "city": "calgary",
                    "source": "data.calgary.ca",
                    "url": row.get("url") or row.get("link") or "",
                    "description": (row.get("description") or "")[:300],
                }
            )
        if out:
            break

    _cache_put(cache_key, out, ttl_s=3600 * 2)
    return out[:limit]


# ═══════════════════════════════════════════════════════════════════════
# SEC EDGAR — Wave 14AM (2026-05-30): earnings calendar + Form 4 insider
# ═══════════════════════════════════════════════════════════════════════
#
# Free, no key required. SEC enforces a 10 req/sec hard cap across all
# *.sec.gov domains with mandatory User-Agent: name email@addr header.
# Replaces the flaky yfinance earnings-calendar fallback NCL has been
# using since Wave 14G P19, and adds insider-trade signal NCL doesn't
# have today.

_SEC_UA = "NCL personal-AI nate@gripandripphdd.com"
_SEC_HEADERS = {"User-Agent": _SEC_UA, "Accept-Encoding": "gzip, deflate"}

# Company-facts API (XBRL); used to resolve ticker → CIK for Form 4.
_SEC_TICKER_LOOKUP = "https://www.sec.gov/files/company_tickers.json"
_sec_ticker_cik_cache: Optional[dict[str, str]] = None


async def _sec_load_ticker_cik_map() -> dict[str, str]:
    """Cache the ticker → 10-digit CIK map (refreshed daily-ish)."""
    global _sec_ticker_cik_cache
    if _sec_ticker_cik_cache is not None:
        return _sec_ticker_cik_cache
    cached = _cache_get("sec:ticker_cik")
    if cached is not None:
        _sec_ticker_cik_cache = cached  # type: ignore[assignment]
        return cached  # type: ignore[return-value]
    try:
        client = await _http()
        r = await client.get(_SEC_TICKER_LOOKUP, headers=_SEC_HEADERS)
        r.raise_for_status()
        data = r.json() or {}
    except Exception as e:
        log.warning("[sec] ticker_cik map fetch failed: %s", e)
        return {}
    # File shape: {"0": {"cik_str": 320193, "ticker": "AAPL", ...}, ...}
    out: dict[str, str] = {}
    for v in data.values():
        if not isinstance(v, dict):
            continue
        sym = str(v.get("ticker") or "").upper()
        cik = v.get("cik_str")
        if sym and cik is not None:
            out[sym] = str(cik).zfill(10)
    _cache_put("sec:ticker_cik", out, ttl_s=3600 * 24)  # 24h
    _sec_ticker_cik_cache = out
    return out


async def fetch_sec_earnings_calendar(
    tickers: Optional[tuple[str, ...] | list[str]] = None,
    days_back: int = 14,
    days_ahead: int = 14,
    limit_per_ticker: int = 5,
) -> list[dict]:
    """Recent earnings-related 8-K filings (Item 2.02 = Results of Ops).

    Per-ticker walk of EDGAR submissions JSON — same pattern as Form 4
    fetcher. Looks for 8-K filings in the window, captures dates, and
    flags those with item 2.02 ("Results of Operations and Financial
    Condition") which is the standard earnings-release item code.

    If ``tickers`` is None we walk a small default watchlist of S&P
    high-volume names; callers should pass NATRIX's held + watchlist
    tickers for full coverage.

    Returns rows: {ticker, company, date, accession, items, form, url,
    is_earnings}. Sorted by date desc.
    """
    if not tickers:
        tickers = (
            "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO",
            "JPM", "V", "MA", "BRK-B", "XOM", "JNJ", "WMT", "PG", "UNH",
            "HD", "BAC", "SPY",
        )
    cache_key = f"sec:earnings:{','.join(tickers)}:{days_back}:{days_ahead}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)  # type: ignore[arg-type]

    map_ = await _sec_load_ticker_cik_map()
    if not map_:
        return []
    today = datetime.now(timezone.utc).date()
    window_start = today - timedelta(days=days_back)
    window_end = today + timedelta(days=days_ahead)

    client = await _http()
    out: list[dict] = []
    for t in tickers:
        cik = map_.get(t.upper())
        if not cik:
            continue
        try:
            r = await client.get(
                f"https://data.sec.gov/submissions/CIK{cik}.json",
                headers=_SEC_HEADERS,
                timeout=20.0,
            )
            r.raise_for_status()
            j = r.json() or {}
        except Exception as e:
            log.debug("[sec] earnings submissions for %s failed: %s", t, e)
            continue
        recent = (j.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        dates = recent.get("filingDate") or []
        accessions = recent.get("accessionNumber") or []
        primary_docs = recent.get("primaryDocument") or []
        items_list = recent.get("items") or []
        company = j.get("name", "")
        kept = 0
        for i, form in enumerate(forms):
            if form not in ("8-K", "8-K/A", "10-Q", "10-K"):
                continue
            d_str = dates[i] if i < len(dates) else ""
            try:
                d = datetime.fromisoformat(d_str).date()
            except Exception:
                continue
            if not (window_start <= d <= window_end):
                continue
            items = items_list[i] if i < len(items_list) else ""
            is_earnings = (
                "2.02" in (items or "") or form in ("10-Q", "10-K")
            )
            acc = accessions[i] if i < len(accessions) else ""
            doc = primary_docs[i] if i < len(primary_docs) else ""
            acc_nodashes = acc.replace("-", "")
            url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                f"{acc_nodashes}/{doc}"
            )
            out.append(
                {
                    "ticker": t.upper(),
                    "company": company,
                    "date": d.isoformat(),
                    "form": form,
                    "items": items,
                    "is_earnings": is_earnings,
                    "accession": acc,
                    "url": url,
                    "source": "sec:edgar",
                }
            )
            kept += 1
            if kept >= limit_per_ticker:
                break

    out.sort(key=lambda r: r["date"], reverse=True)
    _cache_put(cache_key, out, ttl_s=3600 * 4)
    return out


async def fetch_sec_form4_insider(
    tickers: tuple[str, ...] | list[str],
    days_back: int = 14,
    limit_per_ticker: int = 10,
) -> list[dict]:
    """Form 4 insider transactions for the given tickers in the last N days.

    Returns rows: {ticker, company, reporter, role, transaction_date,
    transaction_code, shares, price, url, accession}. Empty list on
    failure. Cached 1h.
    """
    if not tickers:
        return []
    cache_key = f"sec:form4:{','.join(tickers)}:{days_back}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)  # type: ignore[arg-type]

    map_ = await _sec_load_ticker_cik_map()
    if not map_:
        return []

    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days_back)
    client = await _http()
    out: list[dict] = []
    for t in tickers:
        cik = map_.get(t.upper())
        if not cik:
            continue
        try:
            r = await client.get(
                f"https://data.sec.gov/submissions/CIK{cik}.json",
                headers=_SEC_HEADERS,
                timeout=20.0,
            )
            r.raise_for_status()
            j = r.json() or {}
        except Exception as e:
            log.debug("[sec] form4 submissions for %s failed: %s", t, e)
            continue
        recent = (j.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        dates = recent.get("filingDate") or []
        accessions = recent.get("accessionNumber") or []
        primary_docs = recent.get("primaryDocument") or []
        company = j.get("name", "")
        added_for_ticker = 0
        for i, form in enumerate(forms):
            if form != "4":
                continue
            d_str = dates[i] if i < len(dates) else ""
            try:
                d = datetime.fromisoformat(d_str).date()
            except Exception:
                continue
            if not (start <= d <= today):
                continue
            acc = accessions[i] if i < len(accessions) else ""
            doc = primary_docs[i] if i < len(primary_docs) else ""
            acc_nodashes = acc.replace("-", "")
            url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                f"{acc_nodashes}/{doc}"
            )
            out.append(
                {
                    "ticker": t.upper(),
                    "company": company,
                    "transaction_date": d.isoformat(),
                    "accession": acc,
                    "url": url,
                    "source": "sec:edgar:form4",
                }
            )
            added_for_ticker += 1
            if added_for_ticker >= limit_per_ticker:
                break

    # Sort by date desc so the freshest insider activity surfaces first.
    out.sort(key=lambda r: r["transaction_date"], reverse=True)
    _cache_put(cache_key, out, ttl_s=3600)
    return out


# ═══════════════════════════════════════════════════════════════════════
# GDELT 2.0 — Wave 14AM: geopolitical-event signal NCL doesn't have today
# ═══════════════════════════════════════════════════════════════════════
#
# GDELT's DOC 2.0 API is free, no key, soft per-IP throttling. Returns
# events from the last 15-minute slice with CAMEO actor-action codes.


async def fetch_gdelt_events_today(
    keywords: tuple[str, ...] = (
        "OPEC",
        "Fed Reserve",
        "ECB",
        "BOJ",
        "China stimulus",
        "Taiwan strait",
        "Ukraine ceasefire",
        "Middle East",
        "sanctions",
        "tariff",
    ),
    max_per_keyword: int = 10,
) -> list[dict]:
    """Recent GDELT-tagged events for a curated keyword list.

    GDELT's free DOC 2.0 API allows up to ~30s wall on busy IPs;
    soft-throttles at ~5 r/s. Each call gets the last 24h of articles
    matching the keyword. Returns rows: {title, url, seendate, domain,
    keyword, source}.
    """
    cache_key = f"gdelt:{','.join(keywords)}:{max_per_keyword}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)  # type: ignore[arg-type]

    client = await _http()
    out: list[dict] = []
    for kw in keywords:
        try:
            r = await client.get(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params={
                    "query": kw,
                    "mode": "ArtList",
                    "format": "json",
                    "timespan": "24h",
                    "maxrecords": str(max_per_keyword),
                    "sort": "DateDesc",
                },
                timeout=15.0,
            )
            if r.status_code != 200:
                continue
            data = r.json() or {}
        except Exception as e:
            log.debug("[gdelt] keyword %r failed: %s", kw, e)
            continue
        for art in (data.get("articles") or [])[:max_per_keyword]:
            out.append(
                {
                    "title": (art.get("title") or "")[:200],
                    "url": art.get("url") or "",
                    "seendate": art.get("seendate") or "",
                    "domain": art.get("domain") or "",
                    "language": art.get("language") or "",
                    "keyword": kw,
                    "country": art.get("sourcecountry") or "",
                    "source": "gdelt:doc",
                }
            )
    _cache_put(cache_key, out, ttl_s=900)  # 15 min — GDELT updates each 15 min
    return out


# ═══════════════════════════════════════════════════════════════════════
# TRADIER SANDBOX — Wave 14AM: options chains + Greeks (no fee)
# ═══════════════════════════════════════════════════════════════════════
#
# Free sandbox account from developer.tradier.com — no brokerage needed.
# Sandbox data is delayed/simulated but Greeks (delta/gamma/theta/vega/rho)
# refresh hourly and the chain structure is identical to the live API.
# TRADIER_API_KEY hydrated from macOS Keychain (Wave 14AG config update).


async def fetch_tradier_options_chain(
    symbol: str,
    expiration: Optional[str] = None,
    greeks: bool = True,
) -> dict:
    """Options chain + Greeks for one symbol/expiration.

    Returns {symbol, expiration, calls: [...], puts: [...]} where each
    contract row carries strike, bid/ask, volume, open_interest, and
    (when greeks=True) delta/gamma/theta/vega/rho.

    Returns {} on missing TRADIER_API_KEY or any HTTP failure.
    """
    import os as _os

    api_key = _os.getenv("TRADIER_API_KEY")
    if not api_key:
        log.debug("[tradier] TRADIER_API_KEY missing — skipping")
        return {}

    cache_key = f"tradier:chain:{symbol}:{expiration or 'next'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return dict(cached)  # type: ignore[arg-type]

    client = await _http()
    # Sandbox base; live uses api.tradier.com without /v1/ change.
    base = "https://sandbox.tradier.com/v1/markets/options"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    # If no expiration provided, ask Tradier for the next one available.
    if not expiration:
        try:
            r0 = await client.get(
                f"{base}/expirations",
                params={"symbol": symbol, "includeAllRoots": "true"},
                headers=headers,
                timeout=15.0,
            )
            r0.raise_for_status()
            edata = r0.json() or {}
            dates = (((edata.get("expirations") or {}).get("date")) or [])
            if isinstance(dates, str):
                dates = [dates]
            if not dates:
                return {}
            expiration = dates[0]
        except Exception as e:
            log.warning("[tradier] expirations fetch failed for %s: %s", symbol, e)
            return {}

    try:
        r = await client.get(
            f"{base}/chains",
            params={
                "symbol": symbol,
                "expiration": expiration,
                "greeks": "true" if greeks else "false",
            },
            headers=headers,
            timeout=20.0,
        )
        r.raise_for_status()
        data = r.json() or {}
    except Exception as e:
        log.warning("[tradier] chain fetch failed for %s/%s: %s", symbol, expiration, e)
        return {}

    options = ((data.get("options") or {}).get("option")) or []
    calls: list[dict] = []
    puts: list[dict] = []
    for opt in options:
        if not isinstance(opt, dict):
            continue
        row = {
            "strike": opt.get("strike"),
            "bid": opt.get("bid"),
            "ask": opt.get("ask"),
            "last": opt.get("last"),
            "volume": opt.get("volume"),
            "open_interest": opt.get("open_interest"),
            "implied_volatility": opt.get("greeks", {}).get("mid_iv") if isinstance(opt.get("greeks"), dict) else None,
        }
        gr = opt.get("greeks") if isinstance(opt.get("greeks"), dict) else None
        if gr:
            row["delta"] = gr.get("delta")
            row["gamma"] = gr.get("gamma")
            row["theta"] = gr.get("theta")
            row["vega"] = gr.get("vega")
            row["rho"] = gr.get("rho")
        if (opt.get("option_type") or "").lower() == "call":
            calls.append(row)
        else:
            puts.append(row)

    out = {
        "symbol": symbol.upper(),
        "expiration": expiration,
        "calls": calls,
        "puts": puts,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "tradier:sandbox",
    }
    _cache_put(cache_key, out, ttl_s=1800)  # 30 min — sandbox refreshes hourly
    return out


# ═══════════════════════════════════════════════════════════════════════
# Cleanup
# ═══════════════════════════════════════════════════════════════════════


async def aclose() -> None:
    """Close the shared HTTP client. Idempotent."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


__all__ = [
    "fetch_ccxt_tickers",
    "fetch_fed_speeches",
    "fetch_fed_press_releases",
    "fetch_cftc_cot",
    "fetch_open_meteo_air_quality",
    "fetch_edmonton_events",
    # Wave 14AM additions
    "fetch_sec_earnings_calendar",
    "fetch_sec_form4_insider",
    "fetch_gdelt_events_today",
    "fetch_tradier_options_chain",
    "fetch_calgary_events",
    "aclose",
]
