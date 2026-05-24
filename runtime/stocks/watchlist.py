"""Default watchlist — NATRIX 67-ticker universe organized by sector.

This is the server-side mirror of WatchlistItem.defaultWatchlist in the iOS app.
The Brain API uses this list when scanning and fetching bulk quotes.
"""

from dataclasses import dataclass
from typing import List


@dataclass
class WatchlistTicker:
    ticker: str
    name: str
    sector: str = "Other"
    currency: str = "USD"
    is_position: bool = False


# ── NATRIX Full Watchlist (67 tickers) ─────────────────────────────────────

DEFAULT_WATCHLIST: List[WatchlistTicker] = [
    # Semiconductors / AI
    WatchlistTicker("NVDA", "NVIDIA Corp", "Semis/AI"),
    WatchlistTicker("AMD", "Advanced Micro Devices", "Semis/AI"),
    WatchlistTicker("TSM", "Taiwan Semiconductor", "Semis/AI"),
    WatchlistTicker("MU", "Micron Technology", "Semis/AI"),
    WatchlistTicker("INTC", "Intel Corporation", "Semis/AI"),
    WatchlistTicker("QCOM", "Qualcomm", "Semis/AI"),
    WatchlistTicker("PLTR", "Palantir Technologies", "Semis/AI"),
    WatchlistTicker("AI", "C3.ai", "Semis/AI"),
    WatchlistTicker("NBIS", "Nebius Group NV", "Semis/AI"),
    WatchlistTicker("BBAI", "BigBear.ai", "Semis/AI"),
    WatchlistTicker("PDYN", "Palladyne AI", "Semis/AI"),
    WatchlistTicker("GRRR", "Gorilla Technology", "Semis/AI"),
    WatchlistTicker("QUBT", "Quantum Computing", "Semis/AI"),
    # Energy
    WatchlistTicker("XLE", "Energy Select SPDR", "Energy", is_position=True),
    WatchlistTicker("SU", "Suncor Energy", "Energy", "CAD"),
    WatchlistTicker("CNQ", "Canadian Natural Resources", "Energy", "CAD"),
    WatchlistTicker("CVE", "Cenovus Energy", "Energy", "CAD"),
    WatchlistTicker("TRP", "TC Energy Corp", "Energy", "CAD"),
    WatchlistTicker("PPL", "Pembina Pipeline", "Energy", "CAD"),
    WatchlistTicker("CRGY", "Crescent Energy", "Energy"),
    WatchlistTicker("WCP.TO", "Whitecap Resources", "Energy", "CAD"),
    WatchlistTicker("SHLE.TO", "Source Energy Services", "Energy", "CAD"),
    WatchlistTicker("BE", "Bloom Energy", "Energy"),
    WatchlistTicker("OKLO", "Oklo Inc", "Energy"),
    WatchlistTicker("NNE", "Nano Nuclear Energy", "Energy"),
    WatchlistTicker("UEC", "Uranium Energy Corp", "Energy"),
    WatchlistTicker("SMR", "NuScale Power", "Energy"),
    # Tech / Software
    WatchlistTicker("MSFT", "Microsoft", "Tech"),
    WatchlistTicker("AMZN", "Amazon", "Tech"),
    WatchlistTicker("TSLA", "Tesla", "Tech", is_position=True),
    WatchlistTicker("SOFI", "SoFi Technologies", "Tech"),
    WatchlistTicker("U", "Unity Software", "Tech"),
    WatchlistTicker("PATH", "UiPath", "Tech"),
    WatchlistTicker("SYM", "Symbotic", "Tech"),
    WatchlistTicker("ONDS", "Ondas Holdings", "Tech"),
    WatchlistTicker("APLD", "Applied Digital", "Tech"),
    WatchlistTicker("LAES", "Sealsq Corp", "Tech"),
    WatchlistTicker("BB", "BlackBerry", "Tech", "CAD"),
    # Defense / Drones / Robotics
    WatchlistTicker("RCAT", "Red Cat Holdings", "Defense"),
    WatchlistTicker("SERV", "Serve Robotics", "Defense"),
    WatchlistTicker("ARBE", "Arbe Robotics", "Defense"),
    WatchlistTicker("UMAC", "Unusual Machines", "Defense"),
    WatchlistTicker("JOBY", "Joby Aviation", "Defense"),
    WatchlistTicker("ACHR", "Archer Aviation", "Defense"),
    WatchlistTicker("KOSS", "Koss Corp", "Defense"),
    # Biotech / Healthcare
    WatchlistTicker("ISRG", "Intuitive Surgical", "Biotech"),
    WatchlistTicker("UNH", "UnitedHealth Group", "Biotech"),
    WatchlistTicker("NVAX", "Novavax", "Biotech"),
    WatchlistTicker("HUMA", "Humacyte", "Biotech"),
    WatchlistTicker("SPRY", "ARS Pharmaceuticals", "Biotech"),
    WatchlistTicker("ABCL", "AbCellera Biologics", "Biotech"),
    WatchlistTicker("ILMN", "Illumina", "Biotech"),
    # ETFs
    WatchlistTicker("QQQ", "Invesco QQQ Trust", "ETFs"),
    WatchlistTicker("VGT", "Vanguard Info Tech ETF", "ETFs"),
    WatchlistTicker("XRT", "SPDR S&P Retail ETF", "ETFs"),
    WatchlistTicker("MSOS", "AdvisorShares Cannabis", "ETFs"),
    # Metals / Mining
    WatchlistTicker("SLV", "iShares Silver Trust", "Metals", is_position=True),
    WatchlistTicker("GLD", "SPDR Gold Trust", "Metals", is_position=True),
    WatchlistTicker("ALB", "Albemarle Corp", "Metals"),
    WatchlistTicker("NXE", "NexGen Energy", "Metals", "CAD"),
    WatchlistTicker("SCD", "Scandium Canada", "Metals", "CAD"),
    WatchlistTicker("DNG.TO", "Dynacor Group", "Metals", "CAD"),
    WatchlistTicker("PNG.TO", "Kraken Robotics", "Metals", "CAD"),
    # Financials
    WatchlistTicker("APO", "Apollo Global Mgmt", "Finance"),
    WatchlistTicker("ARCC", "Ares Capital Corp", "Finance"),
    WatchlistTicker("RILY", "B. Riley Financial", "Finance"),
    # Other
    WatchlistTicker("GME", "GameStop", "Other"),
    WatchlistTicker("BA", "Boeing", "Other"),
    WatchlistTicker("SONY", "Sony Group", "Other"),
    WatchlistTicker("RIVN", "Rivian Automotive", "Other"),
    WatchlistTicker("NIO", "NIO Inc", "Other"),
    WatchlistTicker("DJT", "Trump Media", "Other"),
    WatchlistTicker("ASTS", "AST SpaceMobile", "Other"),
]

# Quick lookup by ticker (both raw and display forms)
WATCHLIST_MAP = {t.ticker: t for t in DEFAULT_WATCHLIST}
WATCHLIST_TICKERS = [t.ticker for t in DEFAULT_WATCHLIST]


# Display ticker → yfinance ticker mapping
# Canadian stocks on TSX need .TO suffix for Yahoo Finance
# The iOS app uses short form (WCP, DNG, etc.) — the API strips .TO on response
def display_ticker(yf_ticker: str) -> str:
    """Strip exchange suffix for display (WCP.TO → WCP)."""
    return yf_ticker.split(".")[0]


def yf_ticker(display: str) -> str:
    """Add exchange suffix if needed for yfinance lookup."""
    meta = WATCHLIST_MAP.get(display) or WATCHLIST_MAP.get(f"{display}.TO")
    if meta and ".TO" in meta.ticker:
        return meta.ticker
    return display


# Display-form lookup (iOS sends WCP, we need to find WCP.TO)
DISPLAY_MAP = {display_ticker(t.ticker): t for t in DEFAULT_WATCHLIST}
