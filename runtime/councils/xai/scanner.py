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
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..shared.models import XPost


log = logging.getLogger("ncl.councils.xai.scanner")

# X API config — lazy-read functions so env vars set after import (e.g. by
# keychain helper) are picked up.  The old module-level constants
# X_BEARER_TOKEN / XAI_API_KEY are kept as thin wrappers for any external
# code that still references them, but internal callsites use the functions.


def _get_x_bearer_token() -> str:
    """Return the current X bearer token (re-reads env on every call)."""
    return os.getenv("X_BEARER_TOKEN", "")


def _get_xai_api_key() -> str:
    """Return the current xAI API key (re-reads env on every call)."""
    return os.getenv("XAI_API_KEY", "")


# ── Rate limiters ─────────────────────────────────────────────────────────
# X API v2 (app-level): 300 requests per 15-minute window for /tweets/search/recent
# and user timeline endpoints.
# Grok API: conservative 60/min default (no published rate documented).


class _SlidingWindowLimiter:
    """Thread-safe sliding-window rate limiter for use with asyncio.

    Calculates wait time under the lock, releases before sleeping so
    other coroutines aren't blocked during the wait.
    """

    _init_lock = threading.Lock()  # Protects lazy creation of the asyncio.Lock

    def __init__(self, calls: int, window_seconds: float) -> None:
        self._calls = calls
        self._window = window_seconds
        self._timestamps: list[float] = []
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            with _SlidingWindowLimiter._init_lock:
                if self._lock is None:
                    self._lock = asyncio.Lock()
        return self._lock

    async def acquire(self) -> None:
        wait = 0.0
        async with self._get_lock():
            now = time.monotonic()
            self._timestamps = [t for t in self._timestamps if now - t < self._window]
            if len(self._timestamps) >= self._calls:
                wait = self._window - (now - self._timestamps[0])

        # Sleep outside the lock so other coroutines aren't blocked
        if wait > 0:
            await asyncio.sleep(wait)

        # Record timestamp after waiting
        async with self._get_lock():
            self._timestamps.append(time.monotonic())


# Module-level rate limiters shared across all scanner functions
_x_api_limiter = _SlidingWindowLimiter(calls=300, window_seconds=900)  # X: 300/15 min
_grok_limiter = _SlidingWindowLimiter(calls=60, window_seconds=60)  # Grok: 60/min (conservative)


class _CircuitBreaker:
    """Trips open after N consecutive failures; skips requests for a cooldown period.

    States: CLOSED (normal) → OPEN (tripped, rejecting) → HALF_OPEN (testing one request)
    """

    def __init__(self, name: str, failure_threshold: int = 3, cooldown_seconds: float = 120.0):
        self.name = name
        self._failure_threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._consecutive_failures = 0
        self._last_failure_time: float = 0.0
        self._state = "closed"  # closed | open | half_open

    @property
    def is_open(self) -> bool:
        if self._state == "closed":
            return False
        if self._state == "open":
            # Check if cooldown has passed → transition to half_open
            if time.monotonic() - self._last_failure_time >= self._cooldown:
                self._state = "half_open"
                log.info(f"Circuit breaker [{self.name}]: HALF_OPEN — allowing test request")
                return False
            return True
        return False  # half_open allows one request through

    def record_success(self) -> None:
        if self._state != "closed":
            log.info(f"Circuit breaker [{self.name}]: CLOSED — service recovered")
        self._consecutive_failures = 0
        self._state = "closed"

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        self._last_failure_time = time.monotonic()
        if self._consecutive_failures >= self._failure_threshold:
            if self._state != "open":
                log.warning(
                    f"Circuit breaker [{self.name}]: OPEN — "
                    f"{self._consecutive_failures} consecutive failures, "
                    f"cooling down for {self._cooldown}s"
                )
            self._state = "open"


# Circuit breakers for external services
_x_api_breaker = _CircuitBreaker("X-API", failure_threshold=3, cooldown_seconds=120)
_grok_breaker = _CircuitBreaker("Grok", failure_threshold=3, cooldown_seconds=60)
_twscrape_breaker = _CircuitBreaker("twscrape", failure_threshold=5, cooldown_seconds=300)

# Shared HTTP client — reused across all scanner calls to avoid connection pool exhaustion.
# Lazily created; call close_scanner_client() on shutdown.
_shared_client: Optional["httpx.AsyncClient"] = None  # noqa: F821
_client_lock: Optional[asyncio.Lock] = None
_client_init_lock = threading.Lock()


def _get_scanner_lock() -> asyncio.Lock:
    global _client_lock
    if _client_lock is None:
        with _client_init_lock:
            if _client_lock is None:
                _client_lock = asyncio.Lock()
    return _client_lock


async def _get_shared_client() -> "httpx.AsyncClient":  # noqa: F821
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
    "agentbravo069",  # NATRIX primary X handle
    "elikiingz",  # NATRIX personal
    "DeItaone",  # Breaking news
    "unusual_whales",  # Options flow
    "WatcherGuru",  # Market news
    "tier10k",  # Breaking intelligence
    "MarioNawfal",  # News aggregation
    "wallaborealissys",  # Alt-science
    "ABOREALISSYS",  # Alt-research
    "EndWokeness",  # Culture signal
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

    # ── Cross-vector deduplication ─────────────────────────────────
    # A post from a tracked account may also match a keyword search.
    # Deduplicate by post_id, keeping the first occurrence.
    seen_ids: set[str] = set()
    pre_dedup = sum(len(v) for v in results.values())
    for key in ("accounts", "keywords", "trending"):
        deduped: list[XPost] = []
        for post in results[key]:
            pid = post.post_id
            if pid.startswith("grok-") or pid not in seen_ids:
                # Always keep Grok posts (synthetic IDs, can't dedup)
                seen_ids.add(pid)
                deduped.append(post)
        results[key] = deduped

    total = sum(len(v) for v in results.values())
    log.info(
        f"Full sweep complete: {total} posts (deduped from {pre_dedup}) "
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


# Reuse a single twscrape API instance to avoid per-call SQLite connection overhead
_twscrape_api: Optional[object] = None


def _get_twscrape_api():
    """Return shared twscrape API instance (lazy-init)."""
    global _twscrape_api
    if _twscrape_api is None:
        from twscrape import API

        _twscrape_api = API()
    return _twscrape_api


async def scan_account(
    handle: str,
    since: datetime,
    max_posts: int = MAX_POSTS_PER_ACCOUNT,
) -> list[XPost]:
    """Scan a specific X account for recent posts.

    Fallback chain: X API v2 → twscrape → Grok
    Circuit breakers skip services that are consistently failing.
    """

    # Try X API v2 first (structured, reliable with Bearer Token)
    if _get_x_bearer_token() and not _x_api_breaker.is_open:
        try:
            posts = await _scan_account_api(handle, since, max_posts)
            # Empty results from a quiet account are NOT failures — don't trip breaker
            _x_api_breaker.record_success()
            if posts:
                return posts
        except Exception as e:
            log.warning(f"X API scan_account error for @{handle}: {e}")
            _x_api_breaker.record_failure()

    # Fallback 2: twscrape (no API key needed, uses logged-in accounts)
    if _twscrape_available() and not _twscrape_breaker.is_open:
        try:
            posts = await _scan_account_twscrape(handle, since, max_posts)
            _twscrape_breaker.record_success()
            if posts:
                return posts
        except Exception as e:
            log.warning(f"twscrape scan_account error for @{handle}: {e}")
            _twscrape_breaker.record_failure()

    # Fallback 3: Grok for X intelligence
    if _get_xai_api_key() and not _grok_breaker.is_open:
        try:
            posts = await _scan_account_grok(handle, since, max_posts)
            _grok_breaker.record_success()
            return posts
        except Exception as e:
            log.warning(f"Grok scan_account error for @{handle}: {e}")
            _grok_breaker.record_failure()

    log.warning(f"No X API, twscrape, or Grok key — cannot scan @{handle}")
    return []


async def search_keyword(
    keyword: str,
    since: datetime,
    max_posts: int = MAX_POSTS_PER_KEYWORD,
) -> list[XPost]:
    """Search X for posts matching a keyword/hashtag.

    Fallback chain: X API v2 → twscrape → Grok
    Circuit breakers skip services that are consistently failing.
    """

    if _get_x_bearer_token() and not _x_api_breaker.is_open:
        try:
            posts = await _search_keyword_api(keyword, since, max_posts)
            _x_api_breaker.record_success()
            if posts:
                return posts
        except Exception as e:
            log.warning(f"X API keyword search error for '{keyword}': {e}")
            _x_api_breaker.record_failure()

    if _twscrape_available() and not _twscrape_breaker.is_open:
        try:
            posts = await _search_keyword_twscrape(keyword, since, max_posts)
            _twscrape_breaker.record_success()
            if posts:
                return posts
        except Exception as e:
            log.warning(f"twscrape keyword search error for '{keyword}': {e}")
            _twscrape_breaker.record_failure()

    if _get_xai_api_key() and not _grok_breaker.is_open:
        try:
            posts = await _search_keyword_grok(keyword, since, max_posts)
            _grok_breaker.record_success()
            return posts
        except Exception as e:
            log.warning(f"Grok keyword search error for '{keyword}': {e}")
            _grok_breaker.record_failure()

    log.warning(f"No X API, twscrape, or Grok key — cannot search '{keyword}'")
    return []


async def scan_trending(since: datetime) -> list[XPost]:
    """Get posts from trending topics in configured categories.

    Fallback chain: X API v2 → Grok (twscrape has no trending endpoint)
    Circuit breakers skip services that are consistently failing.
    """

    if _get_x_bearer_token() and not _x_api_breaker.is_open:
        try:
            posts = await _scan_trending_api(since)
            _x_api_breaker.record_success()
            if posts:
                return posts
        except Exception as e:
            log.warning(f"X API trending scan error: {e}")
            _x_api_breaker.record_failure()

    # twscrape doesn't have a trending endpoint — skip to Grok
    if _get_xai_api_key() and not _grok_breaker.is_open:
        try:
            posts = await _scan_trending_grok(since)
            _grok_breaker.record_success()
            return posts
        except Exception as e:
            log.warning(f"Grok trending scan error: {e}")
            _grok_breaker.record_failure()

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
        import httpx  # noqa: F401
    except ImportError:
        return []

    try:
        client = await _get_shared_client()
        # First get user ID from handle (consumes 1 rate-limit slot)
        await _x_api_limiter.acquire()
        user_resp = await client.get(
            f"https://api.twitter.com/2/users/by/username/{handle}",
            headers={"Authorization": f"Bearer {_get_x_bearer_token()}"},
            params={"user.fields": "verified,public_metrics"},
        )
        user_resp.raise_for_status()
        user_data = user_resp.json()["data"]
        user_id = user_data["id"]
        user_name = user_data.get("name", handle)
        user_verified = user_data.get("verified", False)

        # Get recent tweets (another rate-limit slot)
        await _x_api_limiter.acquire()
        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        tweets_resp = await client.get(
            f"https://api.twitter.com/2/users/{user_id}/tweets",
            headers={"Authorization": f"Bearer {_get_x_bearer_token()}"},
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

            posts.append(
                XPost(
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
                    verified=user_verified,
                )
            )

        log.info(f"@{handle}: {len(posts)} posts via X API")
        return posts

    except Exception as e:
        log.warning(f"X API scan failed for @{handle}: {e}")
        raise


async def _search_keyword_api(
    keyword: str,
    since: datetime,
    max_posts: int,
) -> list[XPost]:
    """Search using X API v2 recent search."""
    try:
        import httpx  # noqa: F401
    except ImportError:
        return []

    try:
        await _x_api_limiter.acquire()
        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        client = await _get_shared_client()
        resp = await client.get(
            "https://api.twitter.com/2/tweets/search/recent",
            headers={"Authorization": f"Bearer {_get_x_bearer_token()}"},
            params={
                "query": f"{keyword} -is:retweet lang:en",
                "max_results": min(max_posts, 100),
                "start_time": since_str,
                "tweet.fields": "created_at,public_metrics,author_id,entities",
                "expansions": "author_id",
                "user.fields": "username,name,verified",
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

            posts.append(
                XPost(
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
                    verified=author.get("verified", False),
                )
            )

        log.info(f"Keyword '{keyword}': {len(posts)} posts via X API")
        return posts

    except Exception as e:
        log.warning(f"X API search failed for '{keyword}': {e}")
        raise


# Configurable trending proxy queries — used when X API v2 trending
# endpoint is unavailable (requires elevated access).  Override via
# X_COUNCIL_TRENDING_QUERIES env var (comma-separated).
DEFAULT_TRENDING_QUERIES: list[str] = [
    "AI agent",
    "prediction market Polymarket",
    "geopolitical risk",
    "game dev indie",
    "breaking news markets",
    "crypto regulation",
]


def get_trending_queries() -> list[str]:
    """Get trending proxy queries from env or defaults."""
    env_val = os.getenv("X_COUNCIL_TRENDING_QUERIES", "")
    if env_val:
        return [q.strip() for q in env_val.split(",") if q.strip()]
    return DEFAULT_TRENDING_QUERIES


async def _scan_trending_api(since: datetime) -> list[XPost]:
    """Scan trending topics via X API v2. Returns top posts from trends.

    NOTE: X API v2 trending endpoint requires elevated access, so this
    actually runs keyword searches using hardcoded proxy queries. Results
    are tagged with ``synthetic_trending=True`` so downstream consumers
    know this is *not* real trending data — it's topic-based search.
    """
    trending_queries = get_trending_queries()
    posts: list[XPost] = []
    for query in trending_queries:
        batch = await _search_keyword_api(query, since, max_posts=20)
        for post in batch:
            post.synthetic_trending = True
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
        from twscrape import gather as tw_gather
    except ImportError:
        return []

    try:
        api = _get_twscrape_api()
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

            posts.append(
                XPost(
                    post_id=str(tweet.id),
                    author_handle=handle,
                    author_name=getattr(tweet.user, "name", handle)
                    if hasattr(tweet, "user")
                    else handle,
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
                )
            )

        log.info(f"@{handle}: {len(posts)} posts via twscrape")
        return posts

    except Exception as e:
        log.warning(f"twscrape scan failed for @{handle}: {e}")
        raise


async def _search_keyword_twscrape(
    keyword: str,
    since: datetime,
    max_posts: int,
) -> list[XPost]:
    """Search using twscrape."""
    try:
        from twscrape import gather as tw_gather
    except ImportError:
        return []

    try:
        api = _get_twscrape_api()
        since_str = since.strftime("%Y-%m-%d")
        query = f"{keyword} since:{since_str} lang:en"
        tweets = await tw_gather(api.search(query, limit=max_posts))

        posts = []
        for tweet in tweets:
            handle = (
                getattr(tweet.user, "username", "unknown") if hasattr(tweet, "user") else "unknown"
            )
            posts.append(
                XPost(
                    post_id=str(tweet.id),
                    author_handle=handle,
                    author_name=getattr(tweet.user, "name", handle)
                    if hasattr(tweet, "user")
                    else handle,
                    text=tweet.rawContent if hasattr(tweet, "rawContent") else str(tweet),
                    created_at=str(tweet.date) if hasattr(tweet, "date") else "",
                    url=f"https://x.com/{handle}/status/{tweet.id}",
                    like_count=getattr(tweet, "likeCount", 0) or 0,
                    retweet_count=getattr(tweet, "retweetCount", 0) or 0,
                    reply_count=getattr(tweet, "replyCount", 0) or 0,
                    impression_count=getattr(tweet, "viewCount", 0) or 0,
                    hashtags=[h.get("tag", "") for h in (getattr(tweet, "hashtags", []) or [])],
                )
            )

        log.info(f"Keyword '{keyword}': {len(posts)} posts via twscrape")
        return posts

    except Exception as e:
        log.warning(f"twscrape search failed for '{keyword}': {e}")
        raise


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
                "Authorization": f"Bearer {_get_xai_api_key()}",
                "Content-Type": "application/json",
            },
            json={
                "model": "grok-4",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2000,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]

        # Track cost
        try:
            from ...cost_tracker import record_cost

            usage = data.get("usage", {})
            input_t = usage.get("prompt_tokens", 0)
            output_t = usage.get("completion_tokens", 0)
            cost_usd = (input_t * 2.0 + output_t * 10.0) / 1_000_000
            await record_cost(
                "xai",
                cost_usd,
                "x_scan",
                f"grok account scan @{handle} in={input_t} out={output_t}",
            )
        except Exception:
            pass

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
                "Authorization": f"Bearer {_get_xai_api_key()}",
                "Content-Type": "application/json",
            },
            json={
                "model": "grok-4",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2000,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]

        # Track cost
        try:
            from ...cost_tracker import record_cost

            usage = data.get("usage", {})
            input_t = usage.get("prompt_tokens", 0)
            output_t = usage.get("completion_tokens", 0)
            cost_usd = (input_t * 2.0 + output_t * 10.0) / 1_000_000
            await record_cost(
                "xai",
                cost_usd,
                "x_scan",
                f"grok keyword search '{keyword}' in={input_t} out={output_t}",
            )
        except Exception:
            pass

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
                "Authorization": f"Bearer {_get_xai_api_key()}",
                "Content-Type": "application/json",
            },
            json={
                "model": "grok-4",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 3000,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]

        # Track cost
        try:
            from ...cost_tracker import record_cost

            usage = data.get("usage", {})
            input_t = usage.get("prompt_tokens", 0)
            output_t = usage.get("completion_tokens", 0)
            cost_usd = (input_t * 2.0 + output_t * 10.0) / 1_000_000
            await record_cost(
                "xai", cost_usd, "x_scan", f"grok trending scan in={input_t} out={output_t}"
            )
        except Exception:
            pass

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

    Hardened: filters boilerplate lines, validates handle extraction,
    caps output at 20 posts to avoid noise flood from verbose Grok responses.
    """
    import re

    posts: list[XPost] = []
    now = datetime.now(timezone.utc).isoformat()

    # Skip common Grok preamble/disclaimer patterns
    skip_patterns = [
        r"^(here|below|i found|i'll|let me|sure|okay|certainly)",
        r"^(note:|disclaimer:|caveat:)",
        r"^(---+|===+|\*\*\*+)",
    ]
    skip_re = re.compile("|".join(skip_patterns), re.IGNORECASE)

    # Valid X handle: 1-15 alphanumeric + underscore chars
    handle_re = re.compile(r"^[A-Za-z0-9_]{1,15}$")

    for line in text.split("\n"):
        if len(posts) >= 20:  # Cap at 20 posts per Grok parse
            break

        line = line.strip()
        if not line or len(line) < 25:
            continue

        # Skip boilerplate
        if skip_re.match(line):
            continue

        # Try to extract handle
        handle = default_handle
        if "@" in line:
            parts = line.split("@")
            for part in parts[1:]:
                candidate = part.split(":")[0].split(" ")[0].split("|")[0].strip()
                if candidate and handle_re.match(candidate):
                    handle = candidate
                    break

        # Extract engagement numbers (best effort)
        likes = _extract_number(line, ["LIKES:", "likes:", "❤️", "♥"])
        rts = _extract_number(line, ["RTs:", "retweets:", "🔁", "RT:"])

        # Extract actual content (strip format prefixes)
        content = line
        for prefix in ["POST:", "TREND:", f"@{handle}:"]:
            if content.startswith(prefix):
                content = content[len(prefix) :].strip()
                break
        # Strip trailing engagement markers
        if "|" in content:
            content = content.split("|")[0].strip()

        posts.append(
            XPost(
                post_id=f"grok-{uuid.uuid4().hex[:12]}",
                author_handle=handle,
                author_name=handle,
                text=content[:500],
                created_at=now,
                url="",  # Grok doesn't provide direct URLs
                like_count=likes,
                retweet_count=rts,
                synthetic=True,  # Grok-generated data — engagement numbers are approximate
            )
        )

    return posts


def _extract_number(text: str, prefixes: list[str]) -> int:
    """Extract a number following any of the given prefixes.

    Handles suffixes like K/M and decimal points (e.g. "1.5K" → 1500).
    """
    for prefix in prefixes:
        if prefix in text:
            after = text.split(prefix)[1].strip()
            num_str = ""
            for ch in after:
                if ch.isdigit():
                    num_str += ch
                elif ch == "." and "." not in num_str:
                    # Allow one decimal point for values like "1.5K"
                    num_str += ch
                elif ch in ",_":
                    continue
                elif ch in "kK" and num_str:
                    return int(float(num_str) * 1000)
                elif ch in "mM" and num_str:
                    return int(float(num_str) * 1_000_000)
                else:
                    break
            if num_str:
                return int(float(num_str))
    return 0
