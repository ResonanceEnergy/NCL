"""WeatherBetter scorer — weather-themed Polymarket micro-bet scanner.

WeatherBetter was not found in AAC at port time (no
``weather_better``/``weatherbetter`` files); per the work order this is
treated as an extension of PlanktonXD's WEATHER category, scoped to
Polymarket markets whose title matches a weather keyword.

The scoring shape (``ScoredWeatherMarket``) is intentionally close to
PlanktonXD's :class:`ScoredMarket` so the iOS view can reuse the same
row layout.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .planktonxd_scorer import (
    _days_until,
    estimate_true_probability,
    suggested_bet_size,
)


WEATHER_KEYWORDS = [
    "rain",
    "snow",
    "temperature",
    "hurricane",
    "tornado",
    "drought",
    "weather",
    "climate",
    "storm",
    "wind",
    "hail",
    "tropical",
    "blizzard",
    "heat wave",
    "cold front",
    "earthquake",
    "flood",
    "wildfire",
    "monsoon",
    "typhoon",
    "cyclone",
    "sleet",
    "frost",
    "humidity",
]

# Titles containing these substrings are treated as NOT weather markets even
# if a weather keyword fires. Lets a single string filter rule out the most
# common false positives without us needing tag-based classification.
NON_WEATHER_DISQUALIFIERS = [
    "hail mary",  # 'Project Hail Mary' movie
    "carolina hurricanes",  # NHL team
    "miami hurricanes",  # NCAA team
    "snowden",  # Edward Snowden
    "snow leopard",
    "rain man",
    "storm chasers",
    "storm trooper",
    "wind farm",
    "tailwind",
    "frosty",
]


def _is_disqualified(title: str) -> bool:
    t = (title or "").lower()
    return any(d in t for d in NON_WEATHER_DISQUALIFIERS)


def is_weather_market(title: str, tags: Optional[list] = None) -> bool:
    """True if the title (or tags) match any weather keyword on a word boundary.

    Word boundaries matter: "snow" must not match "Snowden", "rain" must not
    match "Ukraine", "wind" must not match "winding".
    """
    import re

    if _is_disqualified(title):
        return False
    hay = (title or "").lower()
    if tags:
        hay = f"{hay} {' '.join(tags).lower()}"
    for kw in WEATHER_KEYWORDS:
        if " " in kw:
            if kw in hay:
                return True
        else:
            if re.search(rf"\b{re.escape(kw)}\b", hay):
                return True
    return False


def derive_weather_event(title: str) -> str:
    """Best-effort label for the kind of weather event in this market title."""
    import re

    t = (title or "").lower()
    mapping = [
        ("hurricane", "hurricane"),
        ("typhoon", "typhoon"),
        ("cyclone", "cyclone"),
        ("tornado", "tornado"),
        ("blizzard", "snow"),
        ("snow", "snow"),
        ("rain", "rain"),
        ("flood", "flood"),
        ("wildfire", "wildfire"),
        ("drought", "drought"),
        ("temperature", "temperature"),
        ("heat wave", "heat"),
        ("cold front", "cold"),
        ("hail", "hail"),
        ("storm", "storm"),
        ("earthquake", "earthquake"),
        ("monsoon", "monsoon"),
        ("frost", "frost"),
        ("humidity", "humidity"),
        ("wind", "wind"),
    ]
    for kw, label in mapping:
        if " " in kw:
            if kw in t:
                return label
        else:
            if re.search(rf"\b{re.escape(kw)}\b", t):
                return label
    return "weather"


def derive_location(title: str) -> str:
    """Pull a probable city/region out of the title.

    Looks for the pattern 'in <Title-Cased Words>' since most Polymarket
    weather questions phrase themselves that way ('Will it rain in NYC',
    'Temperature in Phoenix > 110°F').
    """
    import re

    if not title:
        return ""
    m = re.search(r"\bin\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2})", title)
    if m:
        return m.group(1).strip()
    return ""


# ── Sizing thresholds (slightly more conservative than PlanktonXD) ──
WB_PRICE_FLOOR = 0.001
WB_PRICE_CEIL = 0.10  # WeatherBetter accepts a wider band — up to 10¢
WB_MIN_EDGE = 0.005


@dataclass
class ScoredWeatherMarket:
    """Scored weather market — iOS-renderable."""

    market_id: str
    slug: str
    title: str
    category: str  # always "weather"
    weather_event_type: str
    location: str
    yes_price: float
    no_price: float
    volume_24h: float
    liquidity: float
    end_date: str
    bet_type: str  # tail | contrarian
    outcome: str
    entry_price: float
    edge: float
    implied_probability: float
    estimated_true_probability: float
    implied_payoff_multiple: float
    suggested_size_usd: float
    confidence: float
    edge_score: float  # liquidity × edge × proximity-to-resolve
    days_until_resolve: Optional[float]


def score_weather_market(
    market_id: str,
    slug: str,
    title: str,
    yes_price: float,
    no_price: float,
    volume_24h: float,
    liquidity: float = 0.0,
    end_date: str = "",
    tags: Optional[list] = None,
) -> Optional[ScoredWeatherMarket]:
    """Score a single Polymarket weather market.

    Returns ``None`` when the market doesn't match weather keywords or
    no outcome is in [0.001, 0.10] with positive edge.
    """
    if not is_weather_market(title, tags):
        return None

    candidates: list[tuple[str, float, str, float]] = []
    for outcome_name, price in (("Yes", yes_price), ("No", no_price)):
        if not (WB_PRICE_FLOOR <= price <= WB_PRICE_CEIL):
            continue
        true_prob = estimate_true_probability(price, "weather")
        edge = true_prob - price
        if edge < WB_MIN_EDGE:
            continue
        bet_type = "tail" if price <= 0.02 else "contrarian"
        candidates.append((outcome_name, price, bet_type, edge))

    if not candidates:
        return None

    outcome, entry_price, bet_type, edge = max(candidates, key=lambda c: c[3])
    true_prob = estimate_true_probability(entry_price, "weather")
    payoff = 1.0 / entry_price if entry_price > 0 else 0.0
    # Reuse PlanktonXD sizing — bet_type "tail" → "deep_otm" curve
    size_key = "deep_otm" if bet_type == "tail" else "contrarian"
    size = suggested_bet_size(edge, bet_type=size_key)

    days = _days_until(end_date)

    # WeatherBetter ranking: liquidity × edge × proximity-to-resolve
    # Proximity-to-resolve: closer = higher (cap at 1.0 for >30 days out,
    # linear ramp 0.3-1.0 over [0..30] days).
    if days is None:
        proximity = 0.5
    elif days <= 0.5:
        proximity = 1.0
    elif days >= 30:
        proximity = 0.3
    else:
        proximity = 1.0 - (days / 30.0) * 0.7
    liq_factor = math.log10(max(liquidity, 1.0)) / 4.0  # 0..1 over [1, 10000]
    edge_score = edge * (1.0 + liq_factor) * proximity

    confidence = min(edge * 10.0, 1.0)

    return ScoredWeatherMarket(
        market_id=str(market_id),
        slug=str(slug),
        title=str(title),
        category="weather",
        weather_event_type=derive_weather_event(title),
        location=derive_location(title),
        yes_price=float(yes_price),
        no_price=float(no_price),
        volume_24h=float(volume_24h),
        liquidity=float(liquidity),
        end_date=str(end_date),
        bet_type=bet_type,
        outcome=outcome,
        entry_price=float(entry_price),
        edge=round(edge, 6),
        implied_probability=round(entry_price, 6),
        estimated_true_probability=round(true_prob, 6),
        implied_payoff_multiple=round(min(payoff, 10000.0), 1),
        suggested_size_usd=size,
        confidence=round(confidence, 4),
        edge_score=round(edge_score, 6),
        days_until_resolve=round(days, 2) if days is not None else None,
    )
