"""PlanktonXD scoring math ported from AAC.

Source: ``~/dev/AAC/strategies/planktonxd_prediction_harvester.py`` (the
``PlanktonXDPredictionHarvester`` class). This module strips out the AAC
strategy framework / audit logger / communication wiring and keeps just
the deterministic scoring + sizing math.

Concept
-------
Emulates the wallet ``0x4ffe49ba2a4cae123536a8af4fda48faeb609f71`` which
turned ~$1k → $106k in a year on Polymarket. Five pillars:

1. Deep OTM Harvesting   — buy outcomes priced 0.1¢–3¢
2. Spread Market-Making  — both sides of thin order books
3. Multi-market diversification
4. Antifragile sizing    — $5–$25 per bet, never all-in
5. Liquidity Desert Sniping — thin books, cheap shares from panic

Categories
----------
SPORTS | POLITICS | CRYPTO | ESPORTS | WEATHER | ECONOMICS |
ENTERTAINMENT | SCIENCE

Public entry point: :func:`score_market` returns a dict that's safe to
serialize as part of the ``/portfolio/polymarket/planktonxd/opportunities``
response.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ── Calibrated constants (mirrors AAC PlanktonXDPredictionHarvester) ──
MIN_BET_USD = 5.0
MAX_BET_USD = 25.0
ABSOLUTE_MAX_BET_USD = 50.0

DEEP_OTM_MAX_PRICE = 0.03
DEEP_OTM_MIN_PRICE = 0.001
TAIL_BET_MAX_PRICE = 0.01

MIN_EDGE_DEEP_OTM = 0.005
MIN_EDGE_CONTRARIAN = 0.02


# Keyword → category map. Word-boundary matched (see classify_category).
# Ordering matters: more-specific buckets first so a title like
# "FIFA World Cup" doesn't fall through to crypto, and "Carolina Hurricanes"
# (NHL) hits sports before weather.
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "sports": [
        "nba",
        "nfl",
        "mlb",
        "nhl",
        "soccer",
        "premier",
        "champion",
        "playoff",
        "world cup",
        "fifa",
        "ufc",
        "tennis",
        "golf",
        "f1",
        "formula",
        "boxing",
        "super bowl",
        "stanley cup",
        "hurricanes",
        "warriors",
        "celtics",
        "valkyries",
        "fever",
        "knicks",
        "lakers",
        "yankees",
        "dodgers",
    ],
    "esports": [
        "esports",
        "valorant",
        "league of legends",
        "csgo",
        "dota",
        "overwatch",
        "fortnite",
        "rocket league",
    ],
    "politics": [
        "election",
        "trump",
        "biden",
        "senate",
        "vote",
        "politics",
        "president",
        "primary",
        "congress",
        "governor",
        "republican",
        "democrat",
        "presidential nomination",
        "house seat",
    ],
    "economics": [
        "fed",
        "inflation",
        "cpi",
        "gdp",
        "fomc",
        "unemployment",
        "recession",
        "yield curve",
        "interest rate",
    ],
    "weather": [
        "weather",
        "rain",
        "snow",
        "temperature",
        "hurricane",
        "tornado",
        "drought",
        "climate",
        "storm",
        "wind",
        "hail",
        "earthquake",
        "tropical",
        "blizzard",
        "heat wave",
        "cold front",
        "wildfire",
        "flood",
        "monsoon",
        "typhoon",
    ],
    "entertainment": [
        "movie",
        "oscar",
        "grammy",
        "emmy",
        "box office",
        "album",
        "spotify",
        "billboard",
        "netflix",
        "hbo",
    ],
    "science": ["spacex", "nasa", "openai", "anthropic", "vaccine", "fusion"],
    "crypto": [
        "bitcoin",
        "ethereum",
        "btc",
        "eth",
        "sol",
        "doge",
        "crypto",
        "xrp",
        "ada",
        "altcoin",
        "stablecoin",
    ],
}


def classify_category(title: str, tags: Optional[list] = None) -> str:
    """Best-effort category classification from the market title (+ optional tags).

    Returns the lowercase category key (one of CATEGORY_KEYWORDS) or "other".

    Uses whole-word matching so 3-letter crypto tickers ("ada", "sol", "btc")
    don't accidentally match inside words like "Canada" or "soldier".
    """
    import re

    t = (title or "").lower()
    tag_str = " ".join((tags or [])).lower() if tags else ""
    hay = f"{t} {tag_str}"
    # Prefer category-by-category in CATEGORY_KEYWORDS iteration order so
    # sports/politics specific keywords win over the broad crypto bucket
    # when both fire.
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            # If the keyword contains a space already, plain substring is fine
            # (no risk of accidental matches mid-word).
            if " " in kw:
                if kw in hay:
                    return cat
            else:
                if re.search(rf"\b{re.escape(kw)}\b", hay):
                    return cat
    return "other"


# ── True probability estimators (category-aware) ──────────────────────


def _crypto_true_prob(p: float) -> float:
    """Crypto markets: extreme moves underpriced 5x at <1¢, 2.5x at 1-3¢."""
    if p < 0.01:
        return p * 5.0
    if p < 0.03:
        return p * 2.5
    return p * 1.3


def _esports_true_prob(p: float) -> float:
    """Esports sub-leagues: arbitrage paradise — up to 8x at <0.5¢."""
    if p < 0.005:
        return p * 8.0
    if p < 0.02:
        return p * 3.0
    return p * 1.5


def _sports_true_prob(p: float) -> float:
    if p < 0.01:
        return p * 2.5
    return p * 1.2


def _weather_true_prob(p: float) -> float:
    """Weather: '0 earthquakes worldwide' $15→$1,330 type events. 4x at <1¢."""
    if p < 0.01:
        return p * 4.0
    return p * 1.5


def _politics_true_prob(p: float) -> float:
    if p < 0.01:
        return p * 3.0
    return p * 1.3


def _default_true_prob(p: float) -> float:
    if p < 0.01:
        return p * 3.0
    if p < 0.03:
        return p * 1.5
    return p


_TRUE_PROB_FNS = {
    "crypto": _crypto_true_prob,
    "esports": _esports_true_prob,
    "sports": _sports_true_prob,
    "weather": _weather_true_prob,
    "politics": _politics_true_prob,
}


def estimate_true_probability(market_price: float, category: str) -> float:
    """Estimate true probability of an outcome resolving Yes.

    PlanktonXD's edge: the market systematically underprices tail events.
    A 1¢ price implies 1% probability; many events have true probability
    closer to 3-5%.
    """
    fn = _TRUE_PROB_FNS.get(category, _default_true_prob)
    return min(fn(market_price), 1.0)


# ── Sizing ────────────────────────────────────────────────────────────


def suggested_bet_size(edge: float, bet_type: str = "deep_otm") -> float:
    """$5-$25 bet sized by edge magnitude. Mirrors AAC.calculate_bet_size."""
    base = MIN_BET_USD
    if bet_type == "deep_otm":
        bet = base + edge * 200.0  # edge 0.05 → $15
    elif bet_type == "contrarian":
        bet = base + edge * 300.0
    elif bet_type == "liquidity_snipe":
        bet = base + edge * 150.0
    else:
        bet = base
    return round(max(min(bet, MAX_BET_USD), MIN_BET_USD), 2)


# ── Scoring ───────────────────────────────────────────────────────────


@dataclass
class ScoredMarket:
    """Result of scoring a single Polymarket market for the PlanktonXD strategy.

    All fields are JSON-safe — callers can ``vars(scored)`` and pass to
    FastAPI directly.
    """

    market_id: str
    slug: str
    title: str
    category: str
    yes_price: float
    no_price: float
    volume_24h: float
    end_date: str
    bet_type: str  # deep_otm | contrarian | liquidity_snipe
    outcome: str  # "Yes" | "No"
    entry_price: float
    edge: float  # true_prob - entry_price
    implied_probability: float
    estimated_true_probability: float
    implied_payoff_multiple: float  # 1 / entry_price, capped at 1000x display
    suggested_size_usd: float
    confidence: float  # 0-1, capped at 1.0
    edge_score: float  # composite ranking metric
    days_until_resolve: Optional[float]


def _days_until(end_date: str) -> Optional[float]:
    if not end_date:
        return None
    try:
        from datetime import datetime, timezone

        if end_date.endswith("Z"):
            end_date = end_date.replace("Z", "+00:00")
        dt = datetime.fromisoformat(end_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = dt - datetime.now(timezone.utc)
        return max(delta.total_seconds() / 86400.0, 0.0)
    except (TypeError, ValueError):
        return None


def score_market(
    market_id: str,
    slug: str,
    title: str,
    yes_price: float,
    no_price: float,
    volume_24h: float,
    end_date: str = "",
    tags: Optional[list] = None,
    liquidity: float = 0.0,
) -> Optional[ScoredMarket]:
    """Score a single Polymarket market for PlanktonXD-style opportunity.

    Returns ``None`` when the market doesn't pass the deep-OTM filter
    (i.e. neither outcome is priced inside [0.001, 0.03] with sufficient
    edge).

    The "best" outcome is selected as the side with the highest edge.
    """
    category = classify_category(title, tags)

    candidates: list[tuple[str, float, str]] = []
    # Iterate both outcomes; both may qualify (rare, but possible on degenerate
    # markets) — keep the one with the larger edge.
    for outcome_name, price in (("Yes", yes_price), ("No", no_price)):
        if not (DEEP_OTM_MIN_PRICE <= price <= DEEP_OTM_MAX_PRICE):
            continue
        true_prob = estimate_true_probability(price, category)
        edge = true_prob - price
        bet_type = "deep_otm" if price <= TAIL_BET_MAX_PRICE else "contrarian"
        min_edge = MIN_EDGE_DEEP_OTM if bet_type == "deep_otm" else MIN_EDGE_CONTRARIAN
        # Liquidity desert snipe override: thin book, low vol, true_prob >>
        # 2x price always passes regardless of bet_type edge floor.
        if liquidity and liquidity < 500.0 and volume_24h < 100.0 and true_prob > price * 2:
            bet_type = "liquidity_snipe"
            min_edge = 0.0
        if edge < min_edge:
            continue
        candidates.append((outcome_name, price, bet_type))

    if not candidates:
        return None

    # Pick highest-edge outcome
    def _outcome_edge(c: tuple[str, float, str]) -> float:
        _, p, _ = c
        return estimate_true_probability(p, category) - p

    outcome, entry_price, bet_type = max(candidates, key=_outcome_edge)
    true_prob = estimate_true_probability(entry_price, category)
    edge = true_prob - entry_price
    payoff = 1.0 / entry_price if entry_price > 0 else 0.0
    size = suggested_bet_size(edge, bet_type=bet_type)
    days = _days_until(end_date)

    # Composite edge_score for ranking the opportunities list.
    # Higher edge, higher payoff, higher volume → better.
    # Volume floor at 1 so log doesn't blow up.
    import math

    vol_factor = math.log10(max(volume_24h, 1.0))  # 0..7 range
    edge_score = edge * payoff * (1.0 + vol_factor / 7.0)

    # Confidence: clamp edge*10 (mirrors AAC TradingSignal.confidence)
    confidence = min(edge * 10.0, 1.0)

    return ScoredMarket(
        market_id=str(market_id),
        slug=str(slug),
        title=str(title),
        category=category,
        yes_price=float(yes_price),
        no_price=float(no_price),
        volume_24h=float(volume_24h),
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
