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

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..shared.models import XPost

log = logging.getLogger("ncl.councils.xai.scanner")

# X API config
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")

# ── Rate limiters ─────────────────────────────────────────────────────────
# X API v2 (app-level): 300 requests per 15-minute window for /tweets/search/recent
# and user timeline endpoints.
# Grok API: conservative 60/min default (no published rate documented).


class _SlidingWindowLimiter:
    """Thread-safe sliding-window rate limiter for use with asyncio.

    Calculates wait time under the lock, releases before sleeping so
    other coroutines aren't blocked during the wait.
    """

    def __init__(self, calls: int, window_seconds: float) -> None:
        self._calls = calls
        self._window = window_seconds
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        wait = 0.0
        async with self._lock:
            now = time.monotonic()
            self._timestamps = [t for t in self._timestamps if now - t < self._window]
            if len(self._timestamps) >= self._calls:
                wait = self._window - (now - self._timestamps[0])

        # Sleep outside the lock so other coroutines aren't blocked
        if wait > 0:
            await asyncio.sleep(wait)

        # Record timestamp after waiting
        async with self._lock:
            self._timestamps.append(time.monotonic())


# Module-level rate limiters shared across all scanner functions
_x_api_limiter = _SlidingWindowLimiter(calls=300, window_seconds=900)   # X: 300/15 min
_grok_limiter = _SlidingWindowLimiter(calls=60, window_seconds=60)       # Grok: 60/min (conservative)

# Shared HTTP client — reused across all scanner calls to avoid connection pool exhaustion.
# Lazily created; call close_scanner_client() on shutdown.
_shared_client: Optional["httpx.AsyncClient"] = None
_client_lock: Optional[asyncio.Lock] = None


def _get_scanner_lock() -> asyncio.Lock:
    global _client_lock
    if _client_lock is None:
        _client_lock = asyncio.Lock()
    return _client_lock


async def _get_shared_client() -> "httpx.AsyncClient":
    """Return (and lazily create) the module-level shared httpx client."""
    global _shared_client
    import httpx
    if _shared_client is None or _shared_client.is_closed:
        async with _get_scanner_lock():
            if _shared_client is None or _shared_client.is_closed:
                _shared_client = httpx.AsyncClient(timeout=60.0)
    return _shared_client


async def close_scanner_client() -> None:
    """Close the shared HTTP client. Call on application shutdown."""
    global _shared_client
    if _shared_client is not None:
        await _shared_client.aclose()
        _shared_client = None

# Default tracked accounts
DEFAULT_ACCOUNTS: list[str] = [
    "NathansMRE",
    "agentbravo069",     # NATRIX primary X handle
    "elikiingz",         # NATRIX personal
    "DeItaone",          # Breaking news
    "unusual_whales",    # Options flow
    "WatcherGuru",       # Market news
    "tier10k",           # Breaking intelligence
    "MarioNawfal",       # News aggregation
    "wallaborealissys",  # Alt-science
    "ABOREALISSYS",      # Alt-research
    "EndWokeness",       # Culture signal
]

# Default keyword searches
DEFAULT_KEYWORDS: list[str] = [
    "first strike ration",
    "first-strike",
    "FSR",
    "24 hour ration",
    "MRE review",
    "AI agent framework",
    "Claude Opus",
    "Grok API",
    "geopolitical risk",
    "prediction market",
    "dubstep production",
    "bass music",
    "substandard bass",
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

    # Vector 1: Tracked accounts — parallel with semaphore to cap concurrency
    accounts = get_tracked_accounts()
    log.info(f"Scanning {len(accounts)} tracked accounts (parallel, max 3 concurrent)...")
    account_semaphore = asyncio.Semaphore(3)

    async def _scan_account_limited(handle: str) -> list[XPost]:
        async with account_semaphore:
            return await scan_account(handle, since)

    account_results = await asyncio.gather(
        *[_scan_account_limited(h) for h in accounts],
        return_exceptions=True,
    )
    for r in account_results:
        if isinstance(r, list):
            results["accounts"].extend(r)
        elif isinstance(r, Exception):
            log.warning(f"Account scan error: {r}")

    # Vector 2: Keyword search — parallel with semaphore
    keywords = get_keywords()
    log.info(f"Searching {len(keywords)} keyword sets (parallel, max 3 concurrent)...")
    keyword_semaphore = asyncio.Semaphore(3)

    async def _search_keyword_limited(keyword: str) -> list[XPost]:
        async with keyword_semaphore:
            return await search_keyword(keyword, since)

    keyword_results = await asyncio.gather(
        *[_search_keyword_limited(k) for k in keywords],
        return_exceptions=True,
    )
    for r in keyword_results:
        if isinstance(r, list):
            results["keywords"].extend(r)
        elif isinstance(r, Exception):
            log.warning(f"Keyword search error: {r}")

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


def _twscrape_available() -> bool:
    """Check if twscrape is installed."""
    try:
        import twscrape  # noqa: F401
        return True
    except ImportError:
        return False


async def scan_account(
    handle: str,
    since: datetime,
    max_posts: int = MAX_POSTS_PER_ACCOUNT,
) -> list[XPost]:
    """Scan a specific X account for recent posts.

    Fallback chain: X API v2 → twscrape → Grok
    """

    # Try X API v2 first (structured, reliable with Bearer Token)
    if X_BEARER_TOKEN:
        posts = await _scan_account_api(handle, since, max_posts)
        if posts:
            return posts

    # Fallback 2: twscrape (no API key needed, uses logged-in accounts)
    if _twscrape_available():
        posts = await _scan_account_twscrape(handle, since, max_posts)
        if posts:
            return posts

    # Fallback 3: Grok for X intelligence
    if XAI_API_KEY:
        return await _scan_account_grok(handle, since, max_posts)

    log.warning(f"No X API, twscrape, or Grok key — cannot scan @{handle}")
    return []


async def search_keyword(
    keyword: str,
    since: datetime,
    max_posts: int = MAX_POSTS_PER_KEYWORD,
) -> list[XPost]:
    """Search X for posts matching a keyword/hashtag.

    Fallback chain: X API v2 → twscrape → Grok
    """

    if X_BEARER_TOKEN:
        posts = await _search_keyword_api(keyword, since, max_posts)
        if posts:
            return posts

    if _twscrape_available():
        posts = await _search_keyword_twscrape(keyword, since, max_posts)
        if posts:
            return posts

    if XAI_API_KEY:
        return await _search_keyword_grok(keyword, since, max_posts)

    log.warning(f"No X API, twscrape, or Grok key — cannot search '{keyword}'")
    return []


async def scan_trending(since: datetime) -> list[XPost]:
    """Get posts from trending topics in configured categories.

    Fallback chain: X API v2 → twscrape → Grok
    """

    if X_BEARER_TOKEN:
        posts = await _scan_trending_api(since)
        if posts:
            return posts

    # twscrape doesn't have a trending endpoint — skip to Grok
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
        client = await _get_shared_client()
        # First get user ID from handle (consumes 1 rate-limit slot)
        await _x_api_limiter.acquire()
        user_resp = await client.get(
            f"https://api.twitter.com/2/users/by/username/{handle}",
            headers={"Authorization": f"Bearer {X_BEARER_TOKEN}"},
        )
        user_resp.raise_for_status()
        user_id = user_resp.json()["data"]["id"]
        user_name = user_resp.json()["data"].get("name", handle)

        # Get recent tweets (another rate-limit slot)
        await _x_api_limiter.acquire()
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
        await _x_api_limiter.acquire()
        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        client = await _get_shared_client()
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


# ── twscrape fallbacks ─────────────────────────────────────────────────

async def _scan_account_twscrape(
    handle: str,
    since: datetime,
    max_posts: int,
) -> list[XPost]:
    """Scan account using twscrape (no API key, uses logged-in pool)."""
    try:
        from twscrape import API, gather as tw_gather
    except ImportError:
        return []

    try:
        api = API()
        # twscrape user_tweets wants a user ID — look up first
        user = await api.user_by_login(handle)
        if not user:
            log.warning(f"twscrape: user @{handle} not found")
            return []

        tweets = await tw_gather(api.user_tweets(user.id, limit=max_posts))

        posts = []
        for tweet in tweets:
            created = tweet.date if hasattr(tweet, "date") else None
            if created and created.replace(tzinfo=timezone.utc) < since:
                continue

            posts.append(XPost(
                post_id=str(tweet.id),
                author_handle=handle,
                author_name=getattr(tweet.user, "name", handle) if hasattr(tweet, "user") else handle,
                text=tweet.rawContent if hasattr(tweet, "rawContent") else str(tweet),
                created_at=str(created) if created else "",
                url=f"https://x.com/{handle}/status/{tweet.id}",
                like_count=getattr(tweet, "likeCount", 0) or 0,
                retweet_count=getattr(tweet, "retweetCount", 0) or 0,
                reply_count=getattr(tweet, "replyCount", 0) or 0,
                quote_count=getattr(tweet, "quoteCount", 0) or 0,
                impression_count=getattr(tweet, "viewCount", 0) or 0,
                hashtags=[h.get("tag", "") for h in (getattr(tweet, "hashtags", []) or [])],
                media_urls=[
                    m.url or m.previewUrl
                    for m in (getattr(tweet, "media", []) or [])
                    if hasattr(m, "url")
                ],
            ))

        log.info(f"@{handle}: {len(posts)} posts via twscrape")
        return posts

    except Exception as e:
        log.warning(f"twscrape scan failed for @{handle}: {e}")
        return []


async def _search_keyword_twscrape(
    keyword: str,
    since: datetime,
    max_posts: int,
) -> list[XPost]:
    """Search using twscrape."""
    try:
        from twscrape import API, gather as tw_gather
    except ImportError:
        return []

    try:
        api = API()
        since_str = since.strftime("%Y-%m-%d")
        query = f"{keyword} since:{since_str} lang:en"
        tweets = await tw_gather(api.search(query, limit=max_posts))

        posts = []
        for tweet in tweets:
            handle = getattr(tweet.user, "username", "unknown") if hasattr(tweet, "user") else "unknown"
            posts.append(XPost(
                post_id=str(tweet.id),
                author_handle=handle,
                author_name=getattr(tweet.user, "name", handle) if hasattr(tweet, "user") else handle,
                text=tweet.rawContent if hasattr(tweet, "rawContent") else str(tweet),
                created_at=str(tweet.date) if hasattr(tweet, "date") else "",
                url=f"https://x.com/{handle}/status/{tweet.id}",
                like_count=getattr(tweet, "likeCount", 0) or 0,
                retweet_count=getattr(tweet, "retweetCount", 0) or 0,
                reply_count=getattr(tweet, "replyCount", 0) or 0,
                impression_count=getattr(tweet, "viewCount", 0) or 0,
                hashtags=[h.get("tag", "") for h in (getattr(tweet, "hashtags", []) or [])],
            ))

        log.info(f"Keyword '{keyword}': {len(posts)} posts via twscrape")
        return posts

    except Exception as e:
        log.warning(f"twscrape search failed for '{keyword}': {e}")
        return []


# ── Grok-powered fallbacks ──────────────────────────────────────────────

async def _scan_account_grok(
    handle: str,
    since: datetime,
    max_posts: int,
) -> list[XPost]:
    """Use Grok API to get intelligence about an X account's recent activity."""
    prompt = (
        f"What has @{handle} posted about on X/Twitter in the last 24 hours? "
        f"Give me their key posts with approximate engagement numbers. "
        f"Format each as: POST: [content] | LIKES: [n] | RTs: [n] | TIME: [approx time]"
    )

    try:
        await _grok_limiter.acquire()
        client = await _get_shared_client()
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
    prompt = (
        f"Search X/Twitter for the most significant posts about '{keyword}' "
        f"from the last 24 hours. Give me the top {min(max_posts, 10)} posts "
        f"with author, content, and engagement. "
        f"Format: @handle: [content] | LIKES: [n] | RTs: [n]"
    )

    try:
        await _grok_limiter.acquire()
        client = await _get_shared_client()
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
    prompt = (
        "What are the top trending topics on X/Twitter right now in these areas: "
        "AI/tech, geopolitics, markets, gaming, music? "
        "For each trend, give me the key posts driving it. "
        "Format: TREND: [topic] | @handle: [content] | LIKES: [n]"
    )

    try:
        await _grok_limiter.acquire()
        client = await _get_shared_client()
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
            post_id=f"grok-{uuid.uuid4().hex[:12]}",
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
