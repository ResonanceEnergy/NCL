"""
Entity Extraction for Knowledge Graph
=======================================

Extracts entity-relationship-entity triples from memory content to build
a knowledge graph. Two modes:

1. Fast extraction: regex + NLP patterns (no LLM, ~1ms)
2. LLM extraction: Claude Haiku for complex relationship extraction (~2s)

Extracted triples are stored on MemUnit.entities and MemUnit.relationships
and periodically synced to the knowledge graph store.
"""

import json
import logging
import re
from typing import Optional


log = logging.getLogger("ncl.memory.entity_extractor")

# ── Fast extraction patterns ──────────────────────────────────────────

# Named entity patterns (company names, tickers, people, products)
# Ticker priority (2026-05-22 audit fix): $TICKER is the strongest signal.
# Bare tickers require trailing stock-context for low false-positive rate.
_TICKER_RE = re.compile(
    r"(?:\$([A-Z]{1,5})\b|\b([A-Z]{1,5})\b(?=\s+(?:stock|shares|price|earnings|revenue|market|cap|rally|drop|surge|crash|dividend|valuation|PE|p/e)))"
)
_PERSON_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
_URL_DOMAIN_RE = re.compile(r"https?://(?:www\.)?([a-zA-Z0-9.-]+)")
_HASHTAG_RE = re.compile(r"#([a-zA-Z0-9_]+)")

# 2026-05-22 entity-quality audit: KG top entities were polluted with URL
# stems (reddit.com=8495, trends.google.com, polymarket.com, preview.redd.it,
# twitter.com) and yfinance sector buckets ("Communication Services",
# "Consumer Cyclical") classified as person_or_org. These are attributes
# of an entity, not entities themselves.

# Domain-name shape (any token containing a known TLD). Used to reject
# both bare domains like "reddit.com" and subdomains like "preview.redd.it".
# `.it` was added explicitly because preview.redd.it (Reddit image CDN) was
# leaking 600+ noise mentions per the 2026-05-22 audit.
_DOMAIN_TLD_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9\-\.]*\.(com|org|net|io|ly|app|co|gov|edu|ai|tv|me|us|uk|ca|it|de|fr|jp|cn|ru|au|nz|in|br|be|se|no|fi|nl|es|pl)$",
    re.IGNORECASE,
)

# yfinance sector strings — these are categories, not entities. Lowercased
# membership check.
_YFINANCE_SECTORS = frozenset(
    s.lower()
    for s in [
        "Communication Services",
        "Consumer Cyclical",
        "Consumer Defensive",
        "Energy",
        "Financial Services",
        "Healthcare",
        "Industrials",
        "Real Estate",
        "Technology",
        "Utilities",
        "Basic Materials",
    ]
)

# Common tickers that should ALWAYS classify as ticker even when the regex
# missed the trailing-context heuristic (e.g. "TSLA disabled" with no
# stock/shares trigger word). Bumped in the 2026-05-22 audit because TSLA
# never made it into the KG despite being mentioned constantly.
_KNOWN_TICKERS = frozenset(
    [
        "TSLA",
        "AAPL",
        "MSFT",
        "NVDA",
        "GOOG",
        "GOOGL",
        "META",
        "AMZN",
        "SPY",
        "QQQ",
        "VIX",
        "BTC",
        "ETH",
        "AMD",
        "TSM",
        "AVGO",
        "ASML",
        "BABA",
        "JPM",
        "BAC",
        "WFC",
        "GS",
        "MS",
        "V",
        "MA",
        "PYPL",
        "SQ",
        "F",
        "GM",
        "BA",
        "GE",
        "IBM",
        "ORCL",
        "CRM",
        "ADBE",
        "INTC",
        "DIS",
        "NFLX",
        "SHOP",
        "UBER",
        "LYFT",
        "ABNB",
        "COIN",
        "HOOD",
        "PLTR",
        "SNOW",
        "AI",
        "PATH",
        "RBLX",
        "DASH",
        "DKNG",
        "MARA",
        "RIOT",
        "MSTR",
        "GME",
        "AMC",
        "BBBY",
    ]
)


def _is_blacklisted_entity(text: str) -> bool:
    """Return True if `text` looks like a URL stem, sector name, or other
    noise that should NEVER be persisted as a knowledge-graph entity.
    """
    if not text:
        return True
    t = text.strip()
    if not t:
        return True
    low = t.lower()
    # Domain shape — reject any token that matches xxx.tld
    if _DOMAIN_TLD_RE.match(low):
        return True
    # yfinance sector bucket
    if low in _YFINANCE_SECTORS:
        return True
    # Trailing TLD anywhere in the string (catches "Visit reddit.com today")
    if re.search(
        r"\b\w+\.(com|org|net|io|ly|app|co|gov|edu|ai|tv|me|us|uk|ca|it|de|fr|jp|cn|ru|au|nz|in|br|be|se|no|fi|nl|es|pl)\b",
        low,
    ):
        return True
    return False


def _classify_entity(text: str) -> str:
    """Classify a (non-blacklisted) entity by shape. Used as the canonical
    entity-type assignment for KG nodes.
    """
    if not text:
        return "concept"
    t = text.strip()
    # Tickers (with or without $)
    if t.startswith("$"):
        return "ticker"
    if t.upper() in _KNOWN_TICKERS:
        return "ticker"
    if re.fullmatch(r"[A-Z]{1,5}", t) and t in _KNOWN_TICKERS:
        return "ticker"
    if t.startswith("#"):
        return "hashtag"
    if t[0].isupper() and " " in t:
        return "person_or_org"
    return "concept"


# Relationship patterns
_RELATION_PATTERNS = [
    # "X decided to Y"
    (
        re.compile(r"(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+decided\s+to\s+(.+?)(?:\.|$)", re.I),
        "DECIDED",
    ),
    # "X approved Y"
    (
        re.compile(r"(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+approved\s+(.+?)(?:\.|$)", re.I),
        "APPROVED",
    ),
    # "X uses Y"
    (
        re.compile(r"(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:uses?|using)\s+(.+?)(?:\.|,|$)", re.I),
        "USES",
    ),
    # "X depends on Y"
    (
        re.compile(r"(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+depends?\s+on\s+(.+?)(?:\.|,|$)", re.I),
        "DEPENDS_ON",
    ),
    # "X reported Y"
    (
        re.compile(r"(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+reported\s+(.+?)(?:\.|$)", re.I),
        "REPORTED",
    ),
    # "X acquired Y"
    (
        re.compile(r"(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+acquired\s+(.+?)(?:\.|$)", re.I),
        "ACQUIRED",
    ),
    # "X partnered with Y"
    (
        re.compile(
            r"(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+partnered\s+with\s+(.+?)(?:\.|,|$)", re.I
        ),
        "PARTNERED_WITH",
    ),
    # "X launched Y"
    (
        re.compile(r"(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+launched\s+(.+?)(?:\.|,|$)", re.I),
        "LAUNCHED",
    ),
]

# Stop words to filter from entity names
_STOP_ENTITIES = {
    "the",
    "a",
    "an",
    "this",
    "that",
    "it",
    "they",
    "we",
    "he",
    "she",
    "url",
    "http",
    "https",
    "www",
    "com",
    "org",
    "net",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "today",
    "yesterday",
    "tomorrow",
    "last",
    "next",
    "new",
    "old",
}


def fast_extract_entities(content: str) -> list[str]:
    """
    Extract entity names from content using regex patterns.
    Fast (~1ms), no LLM needed. Returns deduplicated list.

    2026-05-22 audit: applies the domain/sector blacklist and bumps
    ticker recognition so $TSLA / TSLA-with-context always classify as
    tickers (not 'person_or_org'). URL domains are NO LONGER extracted
    as entities — they were producing 8,495 reddit.com mentions and
    drowning real entities out of the top-N list.
    """
    entities: set[str] = set()

    # Stock tickers ($AAPL format or AAPL followed by stock-related context words)
    for match in _TICKER_RE.finditer(content):
        ticker = match.group(1) or match.group(2)
        if ticker and len(ticker) >= 2:
            entities.add(f"${ticker}")

    # Known-ticker fast path (catches "TSLA disabled", "MSTR is dumping",
    # i.e. bare tickers WITHOUT a trailing stock-context trigger word).
    for tok in re.findall(r"\b([A-Z]{2,5})\b", content):
        if tok in _KNOWN_TICKERS:
            entities.add(f"${tok}")

    # Person/company names (capitalized multi-word sequences)
    for match in _PERSON_RE.finditer(content):
        name = match.group(0).strip()
        # Filter out stop phrases and very short names
        if name.lower().split()[0] not in _STOP_ENTITIES and len(name) > 3:
            if not _is_blacklisted_entity(name):
                entities.add(name)

    # URL domains are NOT extracted as entities (2026-05-22 audit fix).
    # They were producing 8,495 reddit.com / 600+ preview.redd.it noise
    # mentions in the KG. Domains belong as URL metadata on the source unit,
    # not as first-class graph nodes.

    # Hashtags
    for match in _HASHTAG_RE.finditer(content):
        tag = match.group(1)
        if len(tag) > 2:
            entities.add(f"#{tag}")

    # Final blacklist pass — anything that slipped through the per-rule
    # filters above gets dropped here.
    cleaned = {e for e in entities if not _is_blacklisted_entity(e)}
    return sorted(cleaned)[:20]  # Cap at 20 entities per unit


def fast_extract_relationships(content: str) -> list[dict]:
    """
    Extract entity-relationship-entity triples using regex patterns.
    Fast (~1ms), no LLM needed.

    Returns list of {"subject": str, "predicate": str, "object": str}
    """
    relationships = []

    for pattern, predicate in _RELATION_PATTERNS:
        for match in pattern.finditer(content):
            subject = match.group(1).strip()[:100]
            obj = match.group(2).strip()[:100]

            if (
                subject.lower().split()[0] not in _STOP_ENTITIES
                and len(subject) > 2
                and len(obj) > 2
            ):
                relationships.append(
                    {
                        "subject": subject,
                        "predicate": predicate,
                        "object": obj,
                    }
                )

    return relationships[:10]  # Cap at 10 relationships per unit


async def llm_extract_entities(
    content: str,
    source: str = "",
    timeout: float = 30.0,
    model: str = "claude-sonnet-4-20250514",
) -> Optional[dict]:
    """
    Use Claude Sonnet to extract entities and relationships from content.

    Returns dict with 'entities' (list[str]) and 'relationships' (list[dict])
    or None if LLM call fails.

    Routed through ``runtime.llm.chat`` — the facade owns retry+jitter,
    circuit-breaker, budget gating, and cost recording. This function
    just builds the prompt and parses the JSON reply.
    """
    prompt = f"""Extract named entities and relationships from this text.

Text:
{content[:800]}

Respond with ONLY a JSON object:
{{
  "entities": ["Entity1", "Entity2", ...],
  "relationships": [
    {{"subject": "Entity1", "predicate": "VERB", "object": "Entity2"}},
    ...
  ]
}}

Rules:
- Entities: people, companies, products, tickers, technologies, concepts
- Predicates: USES, DECIDED, APPROVED, REPORTED, ACQUIRED, LAUNCHED, DEPENDS_ON, PARTNERED_WITH, AFFECTS, PREDICTS
- Max 10 entities, 5 relationships
- Only include clear, confident extractions"""  # noqa: E501

    try:
        from runtime.llm import chat

        result = await chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            budget_key="anthropic",
            timeout_s=timeout,
        )
        text = result.text
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)

        parsed = json.loads(text.strip())
        return {
            "entities": parsed.get("entities", [])[:10],
            "relationships": parsed.get("relationships", [])[:5],
        }
    except Exception as e:
        log.debug(f"LLM entity extraction failed: {e}")
        return None


async def extract_entities_and_relationships(
    content: str,
    source: str = "",
    use_llm: bool = False,
    model: str = "claude-sonnet-4-20250514",
) -> dict:
    """
    Extract entities and relationships from memory content.

    Uses fast regex extraction by default. LLM extraction for
    high-importance or complex content when use_llm=True.

    Returns:
        Dict with 'entities' (list[str]) and 'relationships' (list[dict])
    """
    # Always do fast extraction first
    entities = fast_extract_entities(content)
    relationships = fast_extract_relationships(content)

    # Optionally enhance with LLM
    if use_llm:
        llm_result = await llm_extract_entities(content, source, model=model)
        if llm_result:
            # Merge LLM entities with regex entities (deduplicated + blacklisted)
            entity_set = set(entities)
            for e in llm_result.get("entities", []):
                if e and not _is_blacklisted_entity(e):
                    entity_set.add(e)
            entities = sorted(entity_set)[:20]

            # Add LLM relationships (deduplicated by subject+predicate+object).
            # Drop edges whose subject OR object is a blacklisted entity —
            # those create the noise like (Apple -> reported -> reddit.com).
            seen = {(r["subject"], r["predicate"], r["object"]) for r in relationships}
            for r in llm_result.get("relationships", []):
                subj = r.get("subject", "")
                obj = r.get("object", "")
                pred = r.get("predicate", "")
                if not (subj and obj and pred):
                    continue
                if _is_blacklisted_entity(subj) or _is_blacklisted_entity(obj):
                    continue
                key = (subj, pred, obj)
                if key not in seen:
                    relationships.append(r)
                    seen.add(key)

    return {
        "entities": entities,
        "relationships": relationships[:10],
    }
