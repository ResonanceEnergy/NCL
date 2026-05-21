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

import asyncio
import json
import logging
import os
import re
from typing import Optional

log = logging.getLogger("ncl.memory.entity_extractor")

# ── Fast extraction patterns ──────────────────────────────────────────

# Named entity patterns (company names, tickers, people, products)
_TICKER_RE = re.compile(r'(?:\$([A-Z]{1,5})\b|\b([A-Z]{1,5})\b(?=\s+(?:stock|shares|price|earnings|revenue|market|cap|rally|drop|surge|crash|dividend|valuation|PE|p/e)))')
_PERSON_RE = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b')
_URL_DOMAIN_RE = re.compile(r'https?://(?:www\.)?([a-zA-Z0-9.-]+)')
_HASHTAG_RE = re.compile(r'#([a-zA-Z0-9_]+)')

# Relationship patterns
_RELATION_PATTERNS = [
    # "X decided to Y"
    (re.compile(r'(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+decided\s+to\s+(.+?)(?:\.|$)', re.I),
     "DECIDED"),
    # "X approved Y"
    (re.compile(r'(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+approved\s+(.+?)(?:\.|$)', re.I),
     "APPROVED"),
    # "X uses Y"
    (re.compile(r'(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:uses?|using)\s+(.+?)(?:\.|,|$)', re.I),
     "USES"),
    # "X depends on Y"
    (re.compile(r'(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+depends?\s+on\s+(.+?)(?:\.|,|$)', re.I),
     "DEPENDS_ON"),
    # "X reported Y"
    (re.compile(r'(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+reported\s+(.+?)(?:\.|$)', re.I),
     "REPORTED"),
    # "X acquired Y"
    (re.compile(r'(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+acquired\s+(.+?)(?:\.|$)', re.I),
     "ACQUIRED"),
    # "X partnered with Y"
    (re.compile(r'(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+partnered\s+with\s+(.+?)(?:\.|,|$)', re.I),
     "PARTNERED_WITH"),
    # "X launched Y"
    (re.compile(r'(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+launched\s+(.+?)(?:\.|,|$)', re.I),
     "LAUNCHED"),
]

# Stop words to filter from entity names
_STOP_ENTITIES = {
    "the", "a", "an", "this", "that", "it", "they", "we", "he", "she",
    "url", "http", "https", "www", "com", "org", "net",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    "today", "yesterday", "tomorrow", "last", "next", "new", "old",
}


def fast_extract_entities(content: str) -> list[str]:
    """
    Extract entity names from content using regex patterns.
    Fast (~1ms), no LLM needed. Returns deduplicated list.
    """
    entities = set()

    # Stock tickers ($AAPL format or AAPL followed by stock-related context words)
    for match in _TICKER_RE.finditer(content):
        ticker = match.group(1) or match.group(2)  # group(1) = $AAPL, group(2) = contextual
        if ticker and len(ticker) >= 2:  # Skip single letters
            entities.add(f"${ticker}")

    # Person/company names (capitalized multi-word sequences)
    for match in _PERSON_RE.finditer(content):
        name = match.group(0).strip()
        # Filter out stop phrases and very short names
        if name.lower().split()[0] not in _STOP_ENTITIES and len(name) > 3:
            entities.add(name)

    # URL domains as entities
    for match in _URL_DOMAIN_RE.finditer(content):
        domain = match.group(1)
        if "." in domain:
            entities.add(domain)

    # Hashtags
    for match in _HASHTAG_RE.finditer(content):
        tag = match.group(1)
        if len(tag) > 2:
            entities.add(f"#{tag}")

    return sorted(entities)[:20]  # Cap at 20 entities per unit


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

            if (subject.lower().split()[0] not in _STOP_ENTITIES
                and len(subject) > 2 and len(obj) > 2):
                relationships.append({
                    "subject": subject,
                    "predicate": predicate,
                    "object": obj,
                })

    return relationships[:10]  # Cap at 10 relationships per unit


async def llm_extract_entities(
    content: str,
    source: str = "",
    timeout: float = 5.0,
) -> Optional[dict]:
    """
    Use Claude Haiku to extract entities and relationships from content.

    Returns dict with 'entities' (list[str]) and 'relationships' (list[dict])
    or None if LLM call fails.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

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
- Only include clear, confident extractions"""

    try:
        import httpx
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 300,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            text = data.get("content", [{}])[0].get("text", "")
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
        llm_result = await llm_extract_entities(content, source)
        if llm_result:
            # Merge LLM entities with regex entities (deduplicated)
            entity_set = set(entities)
            for e in llm_result.get("entities", []):
                entity_set.add(e)
            entities = sorted(entity_set)[:20]

            # Add LLM relationships (deduplicated by subject+predicate+object)
            seen = {(r["subject"], r["predicate"], r["object"]) for r in relationships}
            for r in llm_result.get("relationships", []):
                key = (r.get("subject", ""), r.get("predicate", ""), r.get("object", ""))
                if key not in seen and all(key):
                    relationships.append(r)
                    seen.add(key)

    return {
        "entities": entities,
        "relationships": relationships[:10],
    }
