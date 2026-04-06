"""
X (Twitter) Council — Full Intelligence Sweep Scanner

Monitors X/Twitter across three vectors:
1. Tracked accounts — specific handles you follow for signal
2. Keyword/hashtag search — terms relevant to NARTIX operations
3. Trending topics — what's breaking in your interest areas

Uses X API v2 (Bearer Token) for structured data access.
Falls back to Grok API for X-integrated intelligence when available.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..shared.models import XPost

log = logging.getLogger("ncl.councils.xai.scanner")

# X API config
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")

# Default tracked accounts
DEFAULT_ACCOUNTS: list[str] = [
    "NathansMRE",
    "elikiingz",        # NATRIX personal
    "DeItaone",          # Breaking news
    "unusual_whales",    # Options flow
    "wallaborealissys",  # Alt-science
    "EndWokeness",       # Culture signal
    "MarioNawfal",       # News aggregation
    "ABOREALISSYS",      # Alt-research
]

# Default keyword searches
DEFAULT_KEYWORDS: list[str] = [
    "first strike ration",
    "MRE review",
    "AI agent framework",
    "Claude Opus",
    "Grok API",
    "geopolitical risk",
    "prediction market",
    "dubstep production",
    "unity game dev",
    "Apple Silicon ML",
]

# Trending topic categories of interest
TRENDING_CATEGORIES: list[str] = [
    "technology",
    "entertainment",
    "business",
    "science",
]

# Lookback window
DEFAULT_LOOKBACK_HOURS = 24
MAX_POSTS_PER_ACCOUNT = 100
MAX_POSTS_PER_KEYWORD = 50


def get_tracked_accounts() -> list[str]:
    """Get tracked accounts from env or defaults."""
    env_accounts = os.getenv("X_COUNCIL_ACCOUNTS", "")
    if env_accounts:
        return [a.strip().lstrip("@") for a in env_accounts.split(",") if a.strip()]
    return DEFAULT_ACCOUNTS


def get_keywords() -> list[str]:
    """Get search keywords from env or defaults."""
    env_kw = os.getenv("X_COUNCIL_KEYWORDS", "")
    if env_kw:
        return [k.strip() for k in env_kw.split(",") if k.strip()]
    return DEFAULT_KEYWORDS


async def full_sweep(
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
) -> dict[str, list[XPost]]:
    """
    Run a full intelligence sweep across all three vectors.

    Returns dict with keys: 'accounts', 'keywords', 'trending'
    """
    results: dict[str, list[XPost]] = {
        "accounts": [],
        "keywords": [],
        "trending": [],
    }

    since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    # Vector 1: Tracked accounts
    accounts = get_tracked_accounts()
    log.info(f"Scanning {len(accounts)} tracked accounts...")
    for handle in accounts:
        posts = await scan_account(handle, since)
        results["accounts"].extend(posts)

    # Vector 2: Keyword search
    keywords = get_keywords()
    log.info(f"Searching {len(keywords)} keyword sets...")
    for keyword in keywords:
        posts = await search_keyword(keyword, since)
        results["keywords"].extend(posts)

    # Vector 3: Trending topics
    log.info("Scanning trending topics...")
    trending = await scan_trending(since)
    results["trending"] = trending

    total = sum(len(v) for v in results.values())
    log.info(
        f"Full sweep complete: {total} posts "
        f"({len(results['accounts'])} from accounts, "
        f"{len(results['keywords'])} from keywords, "
        f"{len(results['trending'])} from trending)"
    )
    return results


async def scan_account(
    handle: str,
    since: datetime,
    max_posts: int = MAX_POSTS_PER_ACCOUNT,
) -> list[XPost]:
    """Scan a specific X account for recent posts."""

    # Try X API v2 first
    if X_BEARER_TOKEN:
        return await _scan_account_api(handle, since, max_posts)

    # Fallback: use Grok for X intelligence
    if XAI_API_KEY:
        return await _scan_account_grok(handle, since, max_posts)

    log.warning(f"No X API or Grok key — cannot scan @{handle}")
    return []


async def search_keyword(
    keyword: str,
    since: datetime,
    max_posts: int = MAX_POSTS_PER_KEYWORD,
) -> list[XPost]:
    """Search X for posts matching a keyword/hashtag."""

    if X_BEARER_TOKEN:
        return await _search_keyword_api(keyword, since, max_posts)

    if XAI_API_KEY:
        return await _search_keyword_grok(keyword, since, max_posts)

    log.warning(f"No X API or Grok key — cannot search '{keyword}'")
    return []


async def scan_trending(since: datetime) -> list[XPost]:
    """Get posts from trending topics in configured categories."""

    if X_BEARER_TOKEN:
        return await _scan_trending_api(since)

    if XAI_API_KEY:
        return await _scan_trending_grok(since)

    log.warning("No X API or Grok key — cannot scan trending")
    return []


# ── X API v2 implementations ───────────────────────────────────────────

async def _scan_account_api(
    handle: str,
    since: datetime,
    max_posts: int,
) -> list[XPost]:
    """Scan account using X API v2."""
    try:
        import httpx
    except ImportError:
        return []

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # First get user ID from handle
            user_resp = await client.get(
                f"https://api.twitter.com/2/users/by/username/{handle}",
                headers={"Authorization": f"Bearer {X_BEARER_TOKEN}"},
            )
            user_resp.raise_for_status()
            user_id = user_resp.json()["data"]["id"]
            user_name = user_resp.json()["data"].get("name", handle)

            # Get recent tweets
            since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
            tweets_resp = await client.get(
                f"https://api.twitter.com/2/users/{user_id}/tweets",
                headers={"Authorization": f"Bearer {X_BEARER_TOKEN}"},
                params={
                    "max_results": min(max_posts, 100),
                    "start_time": since_str,
                    "tweet.fields": "created_at,public_metrics,entities,referenced_tweets",
                    "expansions": "attachments.media_keys",
                    "media.fields": "url,preview_image_url",
                },
            )
            tweets_resp.raise_for_status()
            data = tweets_resp.json()

            posts = []
            for tweet in data.get("data", []):
                metrics = tweet.get("public_metrics", {})
                entities = tweet.get("entities", {})
                refs = tweet.get("referenced_tweets", [])

                posts.append(XPost(
                    post_id=tweet["id"],
                    author_handle=handle,
                    author_name=user_name,
                    text=tweet.get("text", ""),
                    created_at=tweet.get("created_at", ""),
                    url=f"https://x.com/{handle}/status/{tweet['id']}",
                    retweet_count=metrics.get("retweet_count", 0),
                    like_count=metrics.get("like_count", 0),
                    reply_count=metrics.get("reply_count", 0),
                    quote_count=metrics.get("quote_count", 0),
                    impression_count=metrics.get("impression_count", 0),
                    is_retweet=any(r.get("type") == "retweeted" for r in refs),
                    is_reply=any(r.get("type") == "replied_to" for r in refs),
                    hashtags=[h["tag"] for h in entities.get("hashtags", [])],
                    mentioned_users=[m["username"] for m in entities.get("mentions", [])],
                ))

            log.info(f"@{handle}: {len(posts)} posts via X API")
            return posts

    except Exception as e:
        log.warning(f"X API scan failed for @{handle}: {e}")
        return []


async def _search_keyword_api(
    keyword: str,
    since: datetime,
    max_posts: int,
) -> list[XPost]:
    """Search using X API v2 recent search."""
    try:
        import httpx
    except ImportError:
        return []

    try:
        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "https://api.twitter.com/2/tweets/search/recent",
                headers={"Authorization": f"Bearer {X_BEARER_TOKEN}"},
                params={
                    "query": f"{keyword} -is:retweet lang:en",
                    "max_results": min(max_posts, 100),
                    "start_time": since_str,
                    "tweet.fields": "created_at,public_metrics,author_id,entities",
                    "expansions": "author_id",
                    "user.fields": "username,name",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            # Build user lookup
            users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}

            posts = []
            for tweet in data.get("data", []):
                author = users.get(tweet.get("author_id", ""), {})
                handle = author.get("username", "unknown")
                metrics = tweet.get("public_metrics", {})
                entities = tweet.get("entities", {})

                posts.append(XPost(
                    post_id=tweet["id"],
                    author_handle=handle,
                    author_name=author.get("name", handle),
                    text=tweet.get("text", ""),
                    created_at=tweet.get("created_at", ""),
                    url=f"https://x.com/{handle}/status/{tweet['id']}",
                    retweet_count=metrics.get("retweet_count", 0),
                    like_count=metrics.get("like_count", 0),
                    reply_count=metrics.get("reply_count", 0),
                    quote_count=metrics.get("quote_count", 0),
                    impression_count=metrics.get("impression_count", 0),
                    hashtags=[h["tag"] for h in entities.get("hashtags", [])],
                    mentioned_users=[m["username"] for m in entities.get("mentions", [])],
                ))

            log.info(f"Keyword '{keyword}': {len(posts)} posts via X API")
            return posts

    except Exception as e:
        log.warning(f"X API search failed for '{keyword}': {e}")
        return []


async def _scan_trending_api(since: datetime) -> list[XPost]:
    """Scan trending topics via X API v2. Returns top posts from trends."""
    # X API v2 trending endpoint requires elevated access — use search as proxy
    trending_queries = [
        "AI agent",
        "prediction market Polymarket",
        "geopolitical",
        "game dev indie",
    ]
    posts: list[XPost] = []
    for query in trending_queries:
        batch = await _search_keyword_api(query, since, max_posts=20)
        posts.extend(batch)
    return posts


# ── Grok-powered fallbacks ──────────────────────────────────────────────

async def _scan_account_grok(
    handle: str,
    since: datetime,
    max_posts: int,
) -> list[XPost]:
    """Use Grok API to get intelligence about an X account's recent activity."""
    try:
        import httpx
    except ImportError:
        return []

    prompt = (
        f"What has @{handle} posted about on X/Twitter in the last 24 hours? "
        f"Give me their key posts with approximate engagement numbers. "
        f"Format each as: POST: [content] | LIKES: [n] | RTs: [n] | TIME: [approx time]"
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {XAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "grok-4",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 2000,
                },
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]

            # Parse Grok's response into XPost objects
            posts = _parse_grok_posts(text, handle)
            log.info(f"@{handle}: {len(posts)} posts via Grok")
            return posts

    except Exception as e:
        log.warning(f"Grok scan failed for @{handle}: {e}")
        return []


async def _search_keyword_grok(
    keyword: str,
    since: datetime,
    max_posts: int,
) -> list[XPost]:
    """Use Grok to search X for keyword-relevant posts."""
    try:
        import httpx
    except ImportError:
        return []

    prompt = (
        f"Search X/Twitter for the most significant posts about '{keyword}' "
        f"from the last 24 hours. Give me the top {min(max_posts, 10)} posts "
        f"with author, content, and engagement. "
        f"Format: @handle: [content] | LIKES: [n] | RTs: [n]"
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {XAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "grok-4",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 2000,
                },
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]

            posts = _parse_grok_posts(text, f"search:{keyword}")
            log.info(f"Keyword '{keyword}': {len(posts)} posts via Grok")
            return posts

    except Exception as e:
        log.warning(f"Grok search failed for '{keyword}': {e}")
        return []


async def _scan_trending_grok(since: datetime) -> list[XPost]:
    """Use Grok to get trending topic intelligence."""
    try:
        import httpx
    except ImportError:
        return []

    prompt = (
        "What are the top trending topics on X/Twitter right now in these areas: "
        "AI/tech, geopolitics, markets, gaming, music? "
        "For each trend, give me the key posts driving it. "
        "Format: TREND: [topic] | @handle: [content] | LIKES: [n]"
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {XAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "grok-4",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 3000,
                },
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]

            posts = _parse_grok_posts(text, "trending")
            log.info(f"Trending: {len(posts)} posts via Grok")
            return posts

    except Exception as e:
        log.warning(f"Grok trending scan failed: {e}")
        return []


def _parse_grok_posts(text: str, default_handle: str) -> list[XPost]:
    """
    Best-effort parse of Grok's natural language response into XPost objects.

    Grok doesn't return structured data, so we extract what we can.
    The analysis layer will make sense of the content regardless.
    """
    posts: list[XPost] = []
    now = datetime.now(timezone.utc).isoformat()

    for i, line in enumerate(text.split("\n")):
        line = line.strip()
        if not line or len(line) < 20:
            continue

        # Try to extract handle
        handle = default_handle
        if "@" in line:
            parts = line.split("@")
            for part in parts[1:]:
                candidate = part.split(":")[0].split(" ")[0].split("|")[0].strip()
                if candidate and candidate.isidentifier():
                    handle = candidate
                    break

        # Extract engagement numbers (best effort)
        likes = _extract_number(line, ["LIKES:", "likes:", "❤️", "♥"])
        rts = _extract_number(line, ["RTs:", "retweets:", "🔁", "RT:"])

        posts.append(XPost(
            post_id=f"grok-{default_handle}-{i:03d}",
            author_handle=handle,
            author_name=handle,
            text=line[:500],
            created_at=now,
            url="",  # Grok doesn't provide direct URLs reliably
            like_count=likes,
            retweet_count=rts,
        ))

    return posts


def _extract_number(text: str, prefixes: list[str]) -> int:
    """Extract a number following any of the given prefixes."""
    for prefix in prefixes:
        if prefix in text:
            after = text.split(prefix)[1].strip()
            num_str = ""
            for ch in after:
                if ch.isdigit():
                    num_str += ch
                elif ch in ",._":
                    continue
                elif ch in "kK" and num_str:
                    return int(float(num_str) * 1000)
                elif ch in "mM" and num_str:
                    return int(float(num_str) * 1_000_000)
                else:
                    break
            if num_str:
                return int(num_str)
    return 0
