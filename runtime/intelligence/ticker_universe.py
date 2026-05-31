"""Wave 14CM (2026-05-31) — known-good ticker universe for XREF + trend tracker.

NATRIX trial-run: XREF was firing on NOW / REST / THIS / FREE / OS / NEED / YOUR /
WILL / GREAT / etc. — common English words the bare-uppercase regex misidentifies.
Stop-word filtering alone is impossible (English has too many 2-5 letter ALL-CAPS
abbreviations that overlap real symbols).

Fix: only accept bare-uppercase candidates that appear in a known-good ticker
universe. The `$TICKER` notation stays always-trusted (operators wouldn't
prefix a stop word with $). Bare matches go through `is_valid_ticker()` which
checks against this curated universe.

Universe = S&P 500 large-cap + major ETFs (SPY/QQQ/IWM family + sector ETFs)
+ popular meme/retail stocks (GME/AMC/PLTR/HOOD/etc.) + top 50 crypto + a
handful of NATRIX-relevant individual names. ~700 symbols. Updates land here
by hand; for autoupdate add a yfinance pull job later.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


# ── S&P 100 (mega-cap subset of S&P 500) ─────────────────────────────
_SP100 = {
    "AAPL", "MSFT", "NVDA", "GOOG", "GOOGL", "AMZN", "META", "TSLA",
    "BRK", "AVGO", "JPM", "WMT", "LLY", "ORCL", "V", "MA", "XOM",
    "UNH", "JNJ", "PG", "HD", "COST", "ABBV", "BAC", "NFLX", "KO",
    "CRM", "CVX", "TMO", "ADBE", "MRK", "PEP", "CSCO", "WFC", "ABT",
    "MCD", "ACN", "AMD", "DIS", "LIN", "GE", "TXN", "DHR", "VZ", "NEE",
    "INTC", "PM", "IBM", "QCOM", "AMGN", "PFE", "CMCSA", "CAT", "RTX",
    "T", "MS", "SPGI", "GS", "INTU", "LOW", "HON", "UBER", "AXP",
    "PYPL", "BLK", "BKNG", "PLTR", "SBUX", "ISRG", "VRTX", "NOW",
    "AMAT", "GILD", "DE", "BA", "SYK", "MDT", "MU", "ELV", "TJX",
    "ADP", "REGN", "BSX", "MMC", "MDLZ", "ETN", "C", "CB", "ZTS",
    "LMT", "PGR", "CI", "FI", "TMUS", "SO", "DUK", "BX",
    "SCHW", "PANW", "ANET", "SHOP", "MELI", "EQIX", "KKR",
}

# ── ETFs (sector + thematic + leveraged) ─────────────────────────────
_ETFS = {
    # Broad market
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "VOOG", "VOOV", "VEA", "VWO",
    "EFA", "EEM", "IEMG", "IXUS",
    # Sector SPDRs
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLB", "XLU", "XLC", "XLRE",
    # Bond / yield
    "TLT", "IEF", "SHY", "BND", "LQD", "HYG", "JNK", "TIP", "AGG",
    # Volatility / leverage
    "VXX", "UVXY", "SVXY", "SQQQ", "TQQQ", "SOXL", "SOXS", "TMF", "TMV",
    # Commodities / metals
    "GLD", "SLV", "USO", "UNG", "DBC", "PPLT", "PALL", "WEAT", "CORN", "SOYB",
    "URA", "URNM", "COPX", "CPER",
    # Crypto-related
    "BITO", "BITX", "IBIT", "FBTC", "ARKB", "BRRR", "BTCO", "ETHA", "FETH",
    # Sector / thematic
    "ARKK", "ARKW", "ARKG", "SMH", "SOXX", "ICLN", "TAN", "LIT", "JETS", "XOP",
    "OIH", "GDX", "GDXJ", "SIL", "WGMI", "MAGS",
    # Country / region
    "EWJ", "EWZ", "EWG", "EWU", "FXI", "MCHI", "INDA", "EWY", "EWA", "EWC",
    # Dividend / value
    "SCHD", "VYM", "VIG", "DGRO", "NOBL", "JEPI", "JEPQ", "RSP",
}

# ── Popular retail / meme / NATRIX-watch individual names ────────────
_RETAIL_AND_WATCH = {
    "GME", "AMC", "BB", "BBBY", "PLTR", "HOOD", "SOFI", "AFRM", "RIOT", "MARA",
    "CLSK", "HUT", "CIFR", "BTBT", "WULF", "BITF", "GLXY", "MSTR",
    "RBLX", "U", "DKNG", "PENN", "MGM", "WYNN", "CZR",
    "F", "GM", "RIVN", "LCID", "NIO", "XPEV", "LI", "FSR",
    "SPCE", "JOBY", "ACHR", "RKLB", "ASTS",
    "DJT", "RUM",
    "NKE", "LULU", "LVMH", "ABNB", "DASH", "GRUB",
    "ROKU", "SPOT", "ZG", "Z",
    "COIN", "SQ", "BLOCK", "PYPL",
    "CRWD", "ZS", "OKTA", "DDOG", "NET", "SNOW", "TEAM", "WDAY", "VEEV",
    "DELL", "HPE", "NTAP", "WDC", "STX",
    "OXY", "DVN", "EOG", "FANG", "MRO", "APA",
    "MO", "PM", "KHC", "BMY",
    "TER", "ENPH", "SEDG", "FSLR", "SPWR", "RUN", "PLUG", "BE", "BLDP",
    "BIDU", "BABA", "JD", "PDD", "TCEHY", "NTES", "TME",
    "QS", "MP",
    # Index / futures abbrev shown without slash
    "ES", "NQ", "YM", "RTY", "CL", "GC", "SI", "HG", "NG", "ZC", "ZS", "ZW",
    "VIX", "VXN", "RVX",
    # Forex pairs commonly mentioned
    "DXY", "JPY", "EUR", "GBP", "CAD", "AUD", "CHF", "MXN", "BRL", "INR", "CNY",
}

# ── Top 50 crypto by market cap (symbols) ────────────────────────────
_CRYPTO = {
    "BTC", "ETH", "USDT", "BNB", "SOL", "XRP", "USDC", "ADA", "DOGE", "AVAX",
    "TRX", "LINK", "DOT", "MATIC", "POL", "LTC", "ICP", "SHIB", "DAI", "TON",
    "ATOM", "XLM", "BCH", "ETC", "FIL", "APT", "ARB", "OP", "NEAR", "VET",
    "INJ", "GRT", "RUNE", "ALGO", "QNT", "AAVE", "MKR", "STX", "IMX", "FTM",
    "SAND", "MANA", "AXS", "FLOW", "EOS", "XTZ", "EGLD", "KAS", "ROSE", "ZEC",
    "DASH", "XMR", "SUI", "SEI", "TIA", "PYTH", "JTO", "BONK", "PEPE", "WIF",
    "FLOKI", "POPCAT", "BOME", "MOG", "FET", "RNDR", "AGIX",
}

# ── Commodity / index / macro tickers commonly referenced ────────────
_MACRO = {
    "WTI", "BRENT", "NIFTY", "DJI", "SPX", "NDX", "RUT", "FTSE", "DAX", "CAC",
    "HSI", "N225", "SX5E",
}


def _project_universe_file() -> Path:
    base = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    return base / "data" / "tickers" / "universe.txt"


_RUNTIME_UNIVERSE: Optional[set[str]] = None


def get_universe() -> set[str]:
    """Return the cached ticker universe. Loads from optional project file
    (one-symbol-per-line at data/tickers/universe.txt) ∪ built-in seed.
    """
    global _RUNTIME_UNIVERSE
    if _RUNTIME_UNIVERSE is not None:
        return _RUNTIME_UNIVERSE
    base: set[str] = set()
    base.update(_SP100)
    base.update(_ETFS)
    base.update(_RETAIL_AND_WATCH)
    base.update(_CRYPTO)
    base.update(_MACRO)
    # Merge any operator-supplied additions
    user_file = _project_universe_file()
    if user_file.exists():
        try:
            for line in user_file.read_text().splitlines():
                tkr = line.strip().upper()
                if tkr and not tkr.startswith("#"):
                    base.add(tkr)
        except Exception:
            pass
    _RUNTIME_UNIVERSE = base
    return base


def is_valid_ticker(candidate: str) -> bool:
    """True iff candidate is in the universe. Case-insensitive."""
    if not candidate:
        return False
    return candidate.upper() in get_universe()


def reload_universe() -> int:
    """Force-reload (e.g. after editing data/tickers/universe.txt).
    Returns new universe size."""
    global _RUNTIME_UNIVERSE
    _RUNTIME_UNIVERSE = None
    u = get_universe()
    return len(u)


__all__ = ["get_universe", "is_valid_ticker", "reload_universe"]
