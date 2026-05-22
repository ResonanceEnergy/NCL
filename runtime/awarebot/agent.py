"""
Awarebot Unified Agent
======================

Single-class intelligence agent implementing the ReAct pattern:
    Perceive → Reason → Act → Observe

Consolidates:
    - runtime/awarebot/scanner.py (social media scanning)
    - runtime/awarebot/predictor.py (ensemble predictions)
    - runtime/intelligence/engine.py (intel brief generation)
    - runtime/intelligence/collectors.py (6 data collectors)
    - runtime/autonomous/signal_processor.py (signal routing)
    - Parts of runtime/autonomous/scheduler.py (scheduling loops)

Design principles:
    1. ReAct loop: perceive/reason/act/observe per cycle
    2. Tiered context management: Write/Select/Compress/Isolate
    3. Deterministic signal scoring with step-function thresholds
    4. Backpressure via bounded asyncio.Queue per source
    5. Token bucket rate limiting per platform
    6. Pure scoring functions (no side effects, fully testable)
    7. LLM reasoning only for ambiguous signals (0.30-0.55 zone)
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import logging
import math
import os
import re
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import aiofiles
import httpx

# ── Existing imports from NCL runtime ────────────────────────────────────
from ..awarebot.scanner import Scanner
from ..awarebot.predictor import FuturePredictor, PredictionOutput
# Collector classes accessed via intelligence_engine instance, not directly
# from ..intelligence.collectors import (...)
from ..intelligence.engine import IntelligenceEngine, SignalCorrelator
from ..intelligence.models import (
    IntelSignal,
    SignalDirection,
    SourceType,
)
from ..ncl_brain.models import InsightSignal
from ..memory.store import MemoryStore
from ..memory.working_context import DailyContextWindow
from ..journal.store import JournalStore
from ..governance.emergency_stop import EMERGENCY_STOP_EVENT

log = logging.getLogger("ncl.awarebot.agent")

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

# Scoring weights — 6 factors (must sum to 1.0)
W_CONTEXT_RELEVANCE = 0.30   # Mandate + watch query + working context match
W_FRESHNESS = 0.20           # How recent
W_CROSS_SOURCE = 0.15        # Multi-source confirmation
W_SOURCE_CONFIDENCE = 0.15   # Source authority
W_ACTIONABILITY = 0.10       # Can NATRIX act on this
W_NOVELTY = 0.10             # New information vs seen before

# Routing thresholds (step-function)
THRESHOLD_CRITICAL = 0.75
THRESHOLD_HIGH = 0.55
THRESHOLD_MEDIUM = 0.30
# Below THRESHOLD_MEDIUM = LOW → log only

# Queue sizes per source (backpressure) — unused, queues removed
# SOURCE_QUEUE_SIZE = 100

# LLM reasoning budget — max calls per scan cycle to control cost
# DeepSeek via local Ollama = $0/day (completely free)
# After dedup warmup, typical cycles have ~11 ambiguous signals so this rarely caps
MAX_LLM_CALLS_PER_CYCLE = int(os.getenv("NCL_AGENT_MAX_LLM_CALLS", "10"))

# Ollama endpoint for local DeepSeek reasoning
OLLAMA_BASE_URL = os.getenv("NCL_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("NCL_AGENT_REASONING_MODEL", "deepseek-coder-v2:16b")
# Fallback: if deepseek-coder-v2:16b isn't pulled, try qwen3:32b which is confirmed available

# Dedup window
DEDUP_WINDOW_SIZE = 10_000

# Context windows
CONTEXT_TOP10_SIZE = 10
CONTEXT_24H_MAX = 200
CONTEXT_7D_MAX = 500

# Default intervals (seconds) — overridable via config
DEFAULT_SCAN_INTERVAL = 300         # 5 min
DEFAULT_BRIEF_INTERVAL = 14400     # 4 hours
DEFAULT_PREDICTION_INTERVAL = 1800  # 30 min
DEFAULT_CONTEXT_INTERVAL = 600      # 10 min
DEFAULT_JOURNAL_INTERVAL = 3600     # 1 hour

# Rate limits per source (requests per minute)
RATE_LIMITS = {
    "x": 15,
    "youtube": 30,
    "reddit": 10,
    "google_trends": 5,
    "polymarket": 20,
    "news": 15,
    # CryptoCollector disabled — re-enable when rate limiting resolved
    # "crypto": 30,
    "unusual_whales": 10,
}


# ═══════════════════════════════════════════════════════════════════════════
# SIGNAL DATA MODEL
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class Signal:
    """Unified signal representation flowing through the agent pipeline."""

    signal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: str = ""              # x, youtube, reddit, google_trends, polymarket, etc.
    title: str = ""
    content: str = ""
    url: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Raw factor scores (0.0 - 1.0)
    relevance: float = 0.0
    actionability: float = 0.0
    novelty: float = 0.0
    authority: float = 0.0

    # Computed composite score (0.0 - 1.0)
    composite_score: float = 0.0

    # Routing outcome
    route_level: str = ""         # CRITICAL, HIGH, MEDIUM, LOW
    routed: bool = False

    # Metadata
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    direction: str = "neutral"
    category: str = ""
    confidence: float = 0.0
    change_pct: Optional[float] = None
    volume: Optional[float] = None

    # LLM reasoning (only for ambiguous signals)
    llm_reasoning: Optional[str] = None
    llm_adjusted_score: Optional[float] = None

    def fingerprint(self) -> str:
        """Generate dedup fingerprint from content + source."""
        raw = f"{self.source}:{self.title[:100]}:{self.content[:200]}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON persistence."""
        return {
            "signal_id": self.signal_id,
            "source": self.source,
            "title": self.title,
            "content": self.content[:500],
            "url": self.url,
            "timestamp": self.timestamp.isoformat(),
            "relevance": self.relevance,
            "actionability": self.actionability,
            "novelty": self.novelty,
            "authority": self.authority,
            "composite_score": self.composite_score,
            "route_level": self.route_level,
            "tags": self.tags,
            "direction": self.direction,
            "category": self.category,
            "confidence": self.confidence,
        }

    @classmethod
    def from_intel_signal(cls, sig: IntelSignal) -> "Signal":
        """Convert an IntelSignal from collectors into unified Signal."""
        importance = sig.importance_score()  # 0-100
        normalized = importance / 100.0

        return cls(
            signal_id=sig.signal_id,
            source=sig.source.value if hasattr(sig.source, "value") else str(sig.source),
            title=sig.title,
            content=sig.content,
            url=sig.url,
            timestamp=sig.timestamp,
            relevance=min(1.0, normalized * 1.1),
            actionability=min(1.0, sig.confidence * 0.7) if sig.direction != SignalDirection.NEUTRAL else sig.confidence * 0.4,
            novelty=0.8 if sig.direction == SignalDirection.EMERGING else 0.3,
            authority=sig.confidence * 0.9,
            tags=sig.tags,
            direction=sig.direction.value if hasattr(sig.direction, "value") else str(sig.direction),
            category=sig.category,
            confidence=sig.confidence,
            change_pct=sig.change_pct,
            volume=sig.volume,
            metadata=sig.metadata,
        )

    @classmethod
    def from_insight_signal(cls, sig: InsightSignal) -> "Signal":
        """Convert legacy InsightSignal (scanner) into unified Signal."""
        return cls(
            signal_id=sig.signal_id,
            source=sig.source_platform,
            title=sig.content[:80],
            content=sig.content,
            url=sig.url,
            timestamp=sig.timestamp,
            relevance=sig.relevance,
            actionability=sig.actionability,
            novelty=sig.novelty,
            authority=sig.source_authority,
            tags=sig.tags,
            confidence=(sig.relevance + sig.actionability + sig.novelty) / 3.0,
        )


# ═══════════════════════════════════════════════════════════════════════════
# TOKEN BUCKET RATE LIMITER
# ═══════════════════════════════════════════════════════════════════════════


class TokenBucket:
    """Async token bucket rate limiter with per-source limits."""

    def __init__(self, tokens_per_minute: int):
        self.rate = tokens_per_minute / 60.0  # tokens per second
        self.max_tokens = tokens_per_minute
        self._tokens = float(tokens_per_minute)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a token is available, then consume one."""
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self.max_tokens, self._tokens + elapsed * self.rate)
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # Calculate wait time
                wait = (1.0 - self._tokens) / self.rate

            await asyncio.sleep(wait)


# ═══════════════════════════════════════════════════════════════════════════
# SCORING FUNCTIONS (pure, deterministic, no side effects)
# ═══════════════════════════════════════════════════════════════════════════


def compute_composite_score(
    relevance: float,
    actionability: float,
    novelty: float,
    authority: float,
    freshness: float = 0.5,
    cross_source: float = 0.0,
) -> float:
    """
    Compute weighted composite score from six factors.

    Pure function — no side effects, fully deterministic.

    Weights: context_relevance 30%, freshness 20%, cross_source 15%,
             source_confidence 15%, actionability 10%, novelty 10%

    Returns:
        Composite score in [0.0, 1.0]
    """
    score = (
        W_CONTEXT_RELEVANCE * min(1.0, max(0.0, relevance))
        + W_FRESHNESS * min(1.0, max(0.0, freshness))
        + W_CROSS_SOURCE * min(1.0, max(0.0, cross_source))
        + W_SOURCE_CONFIDENCE * min(1.0, max(0.0, authority))
        + W_ACTIONABILITY * min(1.0, max(0.0, actionability))
        + W_NOVELTY * min(1.0, max(0.0, novelty))
    )
    return round(min(1.0, max(0.0, score)), 4)


def classify_route_level(composite_score: float) -> str:
    """Step-function classification based on composite score."""
    if composite_score >= THRESHOLD_CRITICAL:
        return "CRITICAL"
    elif composite_score >= THRESHOLD_HIGH:
        return "HIGH"
    elif composite_score >= THRESHOLD_MEDIUM:
        return "MEDIUM"
    else:
        return "LOW"


def is_ambiguous(composite_score: float) -> bool:
    """Signals in the 0.30-0.55 zone need LLM reasoning."""
    return THRESHOLD_MEDIUM <= composite_score < THRESHOLD_HIGH


# ── Cross-Source & Context Keyword Helpers ──────────────────────────────


# ── BM25 Relevance Scoring ──────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """Word-boundary tokenizer for BM25. Strips punctuation, lowercases."""
    import re
    return re.findall(r'\b[a-z0-9]{2,}\b', text.lower())


def compute_relevance_bm25(
    content: str, watch_queries: list[str],
    k1: float = 1.5, b: float = 0.5, avg_dl: float = 30.0,
) -> float:
    """
    BM25 text relevance scoring against watch queries.

    Uses word-boundary tokenization (not substring matching), term frequency
    saturation (k1=1.5), and document length normalization (b=0.5).

    Args:
        content: Signal text content
        watch_queries: List of watch query strings
        k1: Term frequency saturation parameter
        b: Length normalization (0=no normalization, 1=full)
        avg_dl: Average document length in tokens

    Returns:
        Relevance score 0.0-1.0 (normalized via sigmoid)
    """
    if not content or not watch_queries:
        return 0.0

    doc_tokens = _tokenize(content)
    dl = len(doc_tokens)
    if dl == 0:
        return 0.0

    # Build term frequency map
    tf_map: dict[str, int] = {}
    for t in doc_tokens:
        tf_map[t] = tf_map.get(t, 0) + 1

    # Collect unique query terms across all watch queries
    query_terms: set[str] = set()
    for query in watch_queries:
        query_terms.update(_tokenize(query))

    if not query_terms:
        return 0.0

    # Approximate IDF: treat each query term as appearing in ~30% of docs
    # (conservative estimate since we don't have a corpus)
    N = max(len(watch_queries), 10)  # pseudo document count
    n_containing = max(1, int(N * 0.3))
    idf = math.log((N - n_containing + 0.5) / (n_containing + 0.5) + 1.0)

    bm25_score = 0.0
    for term in query_terms:
        tf = tf_map.get(term, 0)
        if tf > 0:
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * dl / avg_dl)
            bm25_score += idf * numerator / denominator

    # Normalize to 0-1 via sigmoid: score of 5.0 ≈ 0.85
    normalized = 2.0 / (1.0 + math.exp(-bm25_score * 0.4)) - 1.0
    return round(min(1.0, max(0.0, normalized)), 4)


# ── SimHash Near-Duplicate Detection ────────────────────────────────────

def _simhash64(text: str) -> int:
    """Compute 64-bit SimHash fingerprint for near-duplicate detection.

    Uses character 3-grams and a simple hash function. Two documents
    with hamming distance ≤ 3 are considered near-duplicates.
    """
    tokens = _tokenize(text)
    if not tokens:
        return 0
    # Also include 3-grams for phrase-level similarity
    ngrams = tokens[:]
    for i in range(len(tokens) - 2):
        ngrams.append(f"{tokens[i]}_{tokens[i+1]}_{tokens[i+2]}")

    v = [0] * 64
    for token in ngrams:
        h = hash(token) & 0xFFFFFFFFFFFFFFFF  # 64-bit
        for i in range(64):
            if h & (1 << i):
                v[i] += 1
            else:
                v[i] -= 1

    fingerprint = 0
    for i in range(64):
        if v[i] > 0:
            fingerprint |= (1 << i)
    return fingerprint


def _hamming_distance(a: int, b: int) -> int:
    """Count differing bits between two 64-bit integers."""
    return bin(a ^ b).count('1')


def compute_novelty_decay(
    signal: Signal,
    seen_hashes: dict[str, tuple[int, float]],
    lambda_decay: float = 0.1,
    simhash_threshold: int = 3,
) -> float:
    """
    Compute novelty using exponential decay + SimHash near-duplicate detection.

    Instead of binary 0.7/0.1, uses:
    - Exponential decay: e^(-λ * hours_since_last_similar)
    - SimHash 64-bit fingerprint with hamming distance ≤ 3 for near-dupes

    Args:
        signal: Signal to score
        seen_hashes: Dict mapping fingerprint → (simhash, timestamp) for recent signals
        lambda_decay: Decay rate (0.1 = half-life ~7 hours)
        simhash_threshold: Max hamming distance for near-duplicate

    Returns:
        Novelty score 0.0-1.0 (1.0 = completely novel, 0.0 = exact duplicate)
    """
    content = f"{signal.title} {signal.content[:300]}"
    sig_hash = _simhash64(content)
    now = signal.timestamp.timestamp() if signal.timestamp else time.time()

    # Check for near-duplicates via SimHash
    min_distance = 64  # max possible
    closest_time = 0.0
    for fp, (stored_hash, stored_time) in seen_hashes.items():
        dist = _hamming_distance(sig_hash, stored_hash)
        if dist < min_distance:
            min_distance = dist
            closest_time = stored_time

    if min_distance <= simhash_threshold and closest_time > 0:
        # Near-duplicate found — apply exponential decay
        hours_since = max(0, (now - closest_time) / 3600.0)
        novelty = 1.0 - math.exp(-lambda_decay * hours_since)
        # Floor at 0.05 for exact dupes seen recently
        return round(max(0.05, novelty), 4)

    # Truly novel content
    return 0.9


def compute_freshness(signal: Signal) -> float:
    """
    HN-gravity freshness decay: score / (age_hours + 2)^1.8

    Newer signals get higher freshness. Signals older than 48h
    decay to near-zero freshness.

    Returns:
        Freshness score 0.0-1.0
    """
    now = datetime.now(timezone.utc)
    age = now - signal.timestamp
    age_hours = max(0, age.total_seconds() / 3600.0)
    # Gravity formula: 1 / (age + 2)^1.8, scaled so age=0 → ~0.85
    raw = 1.0 / ((age_hours + 2) ** 1.8)
    # Scale so 0-hour signal ≈ 0.85, 1-hour ≈ 0.55, 6-hour ≈ 0.15
    return round(min(1.0, raw * 10.0), 4)


def compute_authority(source: str, metadata: dict[str, Any]) -> float:
    """
    Compute source authority score using real engagement data when available.

    Blends base platform authority with actual engagement metrics
    (followers, verified status, engagement_score from scanner).

    Reddit gets a tier-based boost: Tier 1 subs (+0.15), Tier 2 (+0.08)
    to reflect their higher signal quality for financial intelligence.
    """
    base_authority = {
        "google_trends": 0.8,
        "polymarket": 0.85,
        "crypto": 0.6,
        "unusual_whales": 0.75,
        "news": 0.7,
        "x": 0.4,
        "youtube": 0.45,
        "reddit": 0.45,  # Raised from 0.35 — Reddit is a primary intel source
    }
    base = base_authority.get(source, 0.35)

    # Blend with real engagement score from scanner if available
    engagement = metadata.get("engagement_score", 0.0)
    if engagement > 0:
        # 60% engagement, 40% base platform authority
        base = 0.4 * base + 0.6 * engagement

    # Reddit: boost based on upvote volume (high-engagement posts are high authority)
    if source == "reddit":
        upvotes = metadata.get("upvotes", 0)
        comments = metadata.get("comments", 0)
        if upvotes > 0:
            # Log-scale upvote boost: 1000 upvotes ≈ +0.12, 10K ≈ +0.18
            upvote_boost = min(0.20, math.log1p(upvotes) / math.log1p(50_000) * 0.20)
            base = min(1.0, base + upvote_boost)
        if comments > 50:
            # High-comment threads signal active discussion
            comment_boost = min(0.10, math.log1p(comments) / math.log1p(5_000) * 0.10)
            base = min(1.0, base + comment_boost)

    # Boost for verified accounts (X/Twitter)
    if metadata.get("verified"):
        base = min(1.0, base + 0.15)

    # Follower boost (log-scale, 100k followers ≈ +0.1)
    followers = metadata.get("followers", 0)
    if followers > 0:
        follower_boost = min(0.15, math.log1p(followers) / math.log1p(1_000_000) * 0.15)
        base = min(1.0, base + follower_boost)

    return round(base, 4)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN AGENT CLASS
# ═══════════════════════════════════════════════════════════════════════════


class Awarebot:
    """
    Unified intelligence agent — single intake, reasoning gate, smart routing.

    Implements the ReAct loop:
        1. PERCEIVE: Scan all sources in parallel with rate limiting
        2. REASON: Score signals, apply LLM reasoning for ambiguous ones
        3. ACT: Route signals to memory/context/alerts based on score
        4. OBSERVE: Generate reports, briefs, predictions from accumulated context

    All timing is managed internally. External callers just call run().
    """

    def __init__(
        self,
        config: Any = None,
        memory_store: Optional[MemoryStore] = None,
        working_context: Optional[DailyContextWindow] = None,
        journal_store: Optional[JournalStore] = None,
        intelligence_engine: Optional[IntelligenceEngine] = None,
        predictor: Optional[FuturePredictor] = None,
        scanner: Optional[Scanner] = None,
        push_callback: Optional[Any] = None,
        disable_internal_ytc: bool = False,
    ):
        """
        Initialize the unified Awarebot agent.

        Args:
            config: NCL Settings object (for API keys, intervals, etc.)
            memory_store: MemoryStore instance for long-term memory
            working_context: DailyContextWindow for operator visibility
            journal_store: JournalStore for journal integration
            intelligence_engine: IntelligenceEngine with all collectors
            predictor: FuturePredictor for ensemble predictions
            scanner: Scanner for X/YouTube/Reddit social scanning
            push_callback: Async callable for push notifications
            disable_internal_ytc: When True, skip spawning the internal
                ``awarebot-ytc`` sub-task. The scheduler-level
                ``ncl-ytc-dedicated`` loop owns YTC instead. Default False
                preserves backward compatibility.
        """
        self.config = config
        self.disable_internal_ytc = disable_internal_ytc
        self.memory_store = memory_store
        self.working_context = working_context
        self.journal_store = journal_store
        self.intelligence_engine = intelligence_engine
        self.predictor = predictor
        self.scanner = scanner
        self.push_callback = push_callback

        # ── Configuration from ncl.yaml ──────────────────────────────
        self._data_dir = Path(
            getattr(config, "data_dir", "~/dev/NCL/data")
        ).expanduser()
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._scan_interval = getattr(config, "x_scan_interval", DEFAULT_SCAN_INTERVAL)
        self._brief_interval = getattr(config, "strategic_review_interval", DEFAULT_BRIEF_INTERVAL)
        self._prediction_interval = getattr(config, "prediction_interval", DEFAULT_PREDICTION_INTERVAL)
        self._context_interval = DEFAULT_CONTEXT_INTERVAL
        self._journal_interval = DEFAULT_JOURNAL_INTERVAL

        # ── Watch queries (topics to monitor) ────────────────────────
        self._watch_queries = self._load_watch_queries()

        # ── Tiered subreddit rotation state ─────────────────────────
        # Tier 3 subs rotate 5 per cycle to spread load
        self._tier3_offset = 0
        self._tier3_batch_size = 5

        # ── Rate limiters (token bucket per source) ──────────────────
        self._rate_limiters: dict[str, TokenBucket] = {
            source: TokenBucket(rpm) for source, rpm in RATE_LIMITS.items()
        }

        # NOTE: Backpressure queues were removed — collectors feed directly
        # into scan_cycle results. Per-source queues can be re-added if an
        # async producer/consumer pattern is needed in the future.

        # ── Deduplication ────────────────────────────────────────────
        self._seen_fingerprints: deque[str] = deque(maxlen=DEDUP_WINDOW_SIZE)
        self._seen_set: set[str] = set()  # Fast O(1) lookup mirror

        # ── SimHash index for near-duplicate detection ───────────────
        # Maps fingerprint → (simhash_64bit, unix_timestamp)
        self._simhash_index: dict[str, tuple[int, float]] = {}

        # ── Context windows ──────────────────────────────────────────
        self._context_top10: deque[Signal] = deque(maxlen=CONTEXT_TOP10_SIZE)
        self._context_24h: deque[Signal] = deque(maxlen=CONTEXT_24H_MAX)
        self._context_7d: deque[Signal] = deque(maxlen=CONTEXT_7D_MAX)

        # ── Signal correlator ────────────────────────────────────────
        self._correlator = SignalCorrelator()

        # ── Stats tracking ───────────────────────────────────────────
        self._stats = {
            "started_at": None,
            "cycles_completed": 0,
            "signals_ingested": 0,
            "signals_scored": 0,
            "signals_routed": 0,
            "signals_deduped": 0,
            "signals_by_source": defaultdict(int),
            "signals_by_level": defaultdict(int),
            "llm_reasoning_calls": 0,
            "briefs_generated": 0,
            "predictions_generated": 0,
            "source_errors": defaultdict(int),
            "last_scan_at": None,
            "last_brief_at": None,
            "last_prediction_at": None,
            "ytc_runs": 0,
        }

        # ── Internal state ───────────────────────────────────────────
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._http_client = httpx.AsyncClient(timeout=60.0)

        # ── Push alert throttling (max 3 per 15 minutes) ─────────────
        self._alert_timestamps: deque[float] = deque(maxlen=20)
        self._max_alerts_per_window = 3
        self._alert_window_seconds = 900  # 15 minutes

        # ── Signal accumulator for predictions ───────────────────────
        self._prediction_buffer: deque[Signal] = deque(maxlen=500)

        # ── Context keyword cache for mandate/watch-query relevance ──
        self._context_keywords: set[str] = set()
        self._keywords_loaded_at: float = 0.0

        # ── Persistence ──────────────────────────────────────────────
        self._signals_file = self._data_dir / "intelligence" / "agent_signals.jsonl"
        self._signals_file.parent.mkdir(parents=True, exist_ok=True)

        log.info("[AGENT] Awarebot agent initialized")

    # ═══════════════════════════════════════════════════════════════════
    # WARM START
    # ═══════════════════════════════════════════════════════════════════

    def _warm_start_buffers(self):
        """
        Populate context deques from persisted signal archive on startup.

        Reads agent_signals.jsonl from the end (most recent first), loads
        signals from the last 48 hours, and routes them into the three
        context buffers using the same threshold logic as route_signal().

        This prevents empty context windows after a Brain restart.
        """
        if not self._signals_file.exists():
            log.info("[AGENT:WARMSTART] No signal archive found — starting cold")
            return

        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
        loaded = 0
        skipped_old = 0
        errors = 0

        # Read all lines — we process in reverse (most recent first)
        # but append to deques in chronological order so the deque order is correct.
        signals_to_load: list[Signal] = []

        try:
            with open(self._signals_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        ts_str = data.get("timestamp")
                        if not ts_str:
                            continue
                        ts = datetime.fromisoformat(ts_str)
                        # Ensure timezone-aware
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        if ts < cutoff:
                            skipped_old += 1
                            continue

                        sig = Signal(
                            signal_id=data.get("signal_id", str(uuid.uuid4())),
                            source=data.get("source", ""),
                            title=data.get("title", ""),
                            content=data.get("content", ""),
                            url=data.get("url"),
                            timestamp=ts,
                            relevance=data.get("relevance", 0.0),
                            actionability=data.get("actionability", 0.0),
                            novelty=data.get("novelty", 0.0),
                            authority=data.get("authority", 0.0),
                            composite_score=data.get("composite_score", 0.0),
                            route_level=data.get("route_level", ""),
                            tags=data.get("tags", []),
                            direction=data.get("direction", "neutral"),
                            category=data.get("category", ""),
                            confidence=data.get("confidence", 0.0),
                        )
                        signals_to_load.append(sig)
                    except (json.JSONDecodeError, KeyError, ValueError):
                        errors += 1
                        continue
        except Exception as e:
            log.warning(f"[AGENT:WARMSTART] Failed to read signal archive: {e}")
            return

        # Sort chronologically so deque ordering is correct (oldest first)
        signals_to_load.sort(key=lambda s: s.timestamp)

        for sig in signals_to_load:
            score = sig.composite_score
            if score >= THRESHOLD_CRITICAL:
                self._context_top10.append(sig)
                self._context_24h.append(sig)
                self._context_7d.append(sig)
            elif score >= THRESHOLD_HIGH:
                self._context_24h.append(sig)
                self._context_7d.append(sig)
            elif score >= THRESHOLD_MEDIUM:
                self._context_7d.append(sig)
            # Below MEDIUM: skip (same as route_signal LOW behavior)

            # Also populate prediction buffer
            self._prediction_buffer.append(sig)
            loaded += 1

        log.info(
            f"[AGENT:WARMSTART] Loaded {loaded} signals from archive "
            f"(skipped {skipped_old} old, {errors} errors). "
            f"Buffers: top10={len(self._context_top10)}, "
            f"24h={len(self._context_24h)}, 7d={len(self._context_7d)}"
        )

    # ═══════════════════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════════════════

    async def run(self):
        """
        Main event loop with task restart supervisor.

        Spawns concurrent tasks and monitors them. If any task crashes
        (not cancelled), it is restarted after a 5-second delay with
        a max of 3 restarts per task to prevent infinite crash loops.
        """
        self._running = True
        self._stats["started_at"] = datetime.now(timezone.utc).isoformat()

        # Warm-start context buffers from persisted signals before loops begin
        self._warm_start_buffers()

        log.info("[AGENT] Starting main event loop with supervisor")

        # Task definitions: (coroutine_factory, name)
        task_defs = [
            (self._scan_loop, "awarebot-scan"),
            (self._brief_loop, "awarebot-brief"),
            (self._prediction_loop, "awarebot-predict"),
            (self._context_loop, "awarebot-context"),
            (self._journal_loop, "awarebot-journal"),
            (self._ytc_loop, "awarebot-ytc"),
            (self._x_liked_loop, "awarebot-x-liked"),
        ]
        if self.disable_internal_ytc:
            task_defs = [(f, n) for (f, n) in task_defs if n != "awarebot-ytc"]
            log.info(
                "[AGENT] Internal YTC sub-task disabled — "
                "scheduler 'ncl-ytc-dedicated' loop owns YouTube Council"
            )
        restart_counts: dict[str, int] = {name: 0 for _, name in task_defs}
        max_restarts = 3

        self._tasks = [
            asyncio.create_task(factory(), name=name)
            for factory, name in task_defs
        ]

        try:
            while self._running:
                # Wait for any task to complete
                done, _ = await asyncio.wait(
                    self._tasks, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    name = task.get_name()
                    if task.cancelled():
                        log.info(f"[AGENT:SUPERVISOR] Task {name} cancelled")
                        continue

                    exc = task.exception()
                    if exc:
                        log.error(
                            f"[AGENT:SUPERVISOR] Task {name} crashed: {exc}",
                            exc_info=exc,
                        )
                        # Restart if under budget
                        if restart_counts.get(name, 0) < max_restarts:
                            restart_counts[name] = restart_counts.get(name, 0) + 1
                            log.warning(
                                f"[AGENT:SUPERVISOR] Restarting {name} "
                                f"(attempt {restart_counts[name]}/{max_restarts})"
                            )
                            await asyncio.sleep(5)
                            # Find the matching factory
                            for factory, tname in task_defs:
                                if tname == name:
                                    new_task = asyncio.create_task(factory(), name=name)
                                    self._tasks = [
                                        t for t in self._tasks if t is not task
                                    ]
                                    self._tasks.append(new_task)
                                    break
                        else:
                            log.error(
                                f"[AGENT:SUPERVISOR] Task {name} exceeded "
                                f"max restarts ({max_restarts}) — not restarting"
                            )
                            self._tasks = [t for t in self._tasks if t is not task]
                    else:
                        # Task completed normally (shouldn't happen for loops)
                        log.info(f"[AGENT:SUPERVISOR] Task {name} completed normally")
                        self._tasks = [t for t in self._tasks if t is not task]

                # If all tasks are dead, stop
                if not self._tasks:
                    log.warning("[AGENT:SUPERVISOR] All tasks dead — stopping")
                    break

        except asyncio.CancelledError:
            log.info("[AGENT] Event loop cancelled")
        finally:
            self._running = False
            log.info("[AGENT] Event loop stopped")

    async def stop(self):
        """Graceful shutdown — cancel all tasks and close resources."""
        log.info("[AGENT] Stopping...")
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._http_client.aclose()
        if self.scanner:
            await self.scanner.close()
        if self.predictor:
            await self.predictor.close()
        log.info("[AGENT] Stopped")

    def is_running(self) -> bool:
        """Check if agent is currently running."""
        return self._running

    def get_stats(self) -> dict[str, Any]:
        """Return agent statistics for the /autonomous/status API."""
        return {
            **self._stats,
            "signals_by_source": dict(self._stats["signals_by_source"]),
            "signals_by_level": dict(self._stats["signals_by_level"]),
            "source_errors": dict(self._stats["source_errors"]),
            "running": self._running,
            "context_top10_size": len(self._context_top10),
            "context_24h_size": len(self._context_24h),
            "context_7d_size": len(self._context_7d),
            "prediction_buffer_size": len(self._prediction_buffer),
            "dedup_window_size": len(self._seen_set),
            "emergency_stopped": EMERGENCY_STOP_EVENT.is_set(),
        }

    # ═══════════════════════════════════════════════════════════════════
    # INTAKE (PERCEIVE) — replaces Scanner + 6 Collectors
    # ═══════════════════════════════════════════════════════════════════

    async def scan_cycle(self) -> list[Signal]:
        """
        Run all sources in parallel with per-source rate limiting.

        Returns all new (non-duplicate) signals from this cycle.
        Graceful degradation: if any source fails, log and continue.
        """
        log.info("[AGENT:SCAN] Starting scan cycle")
        all_signals: list[Signal] = []

        # Run all source collectors concurrently.
        # All sources enabled — Awarebot is the single scorer with 6-factor
        # composite (context_relevance, freshness, cross_source, source_confidence,
        # actionability, novelty) and tier routing. Low-value signals are filtered
        # by the scoring thresholds, not by disabling sources.
        tasks = [
            self._collect_social(),             # X + Reddit + YouTube
            self._collect_google_trends(),      # Google Trends
            self._collect_polymarket(),         # Prediction markets
            self._collect_news(),               # NewsAPI / GNews / RSS
            # self._collect_crypto(),           # DISABLED — CoinGecko rate limiting
            self._collect_unusual_whales(),     # Options flow / dark pool / congress
            self._collect_council_reports(),     # council report ingestion
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            source_names = ["social", "google_trends", "polymarket", "news", "unusual_whales", "council"]
            if isinstance(result, Exception):
                source_name = source_names[i] if i < len(source_names) else f"source_{i}"
                log.warning(f"[AGENT:SCAN] Source '{source_name}' failed: {result}")
                self._stats["source_errors"][source_name] += 1
            elif isinstance(result, list):
                all_signals.extend(result)

        # Deduplicate
        new_signals = self._deduplicate(all_signals)
        self._stats["signals_deduped"] += len(all_signals) - len(new_signals)
        self._stats["signals_ingested"] += len(new_signals)
        self._stats["last_scan_at"] = datetime.now(timezone.utc).isoformat()

        log.info(
            f"[AGENT:SCAN] Cycle complete: {len(all_signals)} raw, "
            f"{len(new_signals)} new (deduped {len(all_signals) - len(new_signals)})"
        )
        return new_signals

    async def _collect_social(self) -> list[Signal]:
        """Collect from X, YouTube, Reddit via existing Scanner."""
        signals = []
        if not self.scanner:
            return signals

        # X queries — ON HOLD per NATRIX directive (May 19, 2026)
        # X API subscription expired (402). Scanner disabled to stop wasting cycles.
        # Re-enable by setting X_SCANNER_ENABLED=true in .env
        x_enabled = os.getenv("X_SCANNER_ENABLED", "false").lower() == "true"
        if x_enabled:
            for query in self._watch_queries.get("x", []):
                try:
                    await self._rate_limiters["x"].acquire()
                    raw = await self.scanner.scan_x(query, max_results=10)
                    for sig in raw:
                        s = Signal.from_insight_signal(sig)
                        s.tags.append("scan:x")
                        signals.append(s)
                        self._stats["signals_by_source"]["x"] += 1
                except Exception as e:
                    log.warning(f"[AGENT:SCAN:X] Query '{query}' failed: {e}")
                    self._stats["source_errors"]["x"] += 1
        else:
            log.warning("[AGENT:SCAN:X] X scanner disabled (X_SCANNER_ENABLED != true)")

        # YouTube queries
        for query in self._watch_queries.get("youtube", []):
            try:
                await self._rate_limiters["youtube"].acquire()
                raw = await self.scanner.scan_youtube(query, max_results=10)
                for sig in raw:
                    s = Signal.from_insight_signal(sig)
                    s.tags.append("scan:youtube")
                    signals.append(s)
                    self._stats["signals_by_source"]["youtube"] += 1
            except Exception as e:
                log.warning(f"[AGENT:SCAN:YT] Query '{query}' failed: {e}")
                self._stats["source_errors"]["youtube"] += 1

        # NOTE: Awarebot uses lightweight Reddit collection (no sentiment/flair) for speed. Full analysis is in councils/reddit/.
        # Reddit search via RSS (no API credentials needed)
        for query in self._watch_queries.get("reddit", []):
            try:
                await self._rate_limiters["reddit"].acquire()
                # Treat watch_queries entries as search terms (prefix with "search:")
                search_query = query if query.startswith("search:") else f"search:{query}"
                raw = await self.scanner.scan_reddit(search_query, max_results=10)
                for sig in raw:
                    s = Signal.from_insight_signal(sig)
                    s.tags.append("scan:reddit")
                    signals.append(s)
                    self._stats["signals_by_source"]["reddit"] += 1
            except Exception as e:
                log.warning(f"[AGENT:SCAN:REDDIT] Query '{query}' failed: {e}")
                self._stats["source_errors"]["reddit"] += 1

        # ── Reddit subreddit scanning (tiered) ──────────────────────
        # Tier 1: every cycle, Tier 2: every cycle, Tier 3: rotated batch
        subreddit_config = self._watch_queries.get("reddit_subreddits", {})
        tier1 = subreddit_config.get("tier1", [])
        tier2 = subreddit_config.get("tier2", [])
        tier3 = subreddit_config.get("tier3", [])

        # Tier 1 — full scan every cycle (core alpha sources)
        for sub in tier1:
            try:
                await self._rate_limiters["reddit"].acquire()
                raw = await self.scanner.scan_reddit(sub, max_results=10)
                for sig in raw:
                    s = Signal.from_insight_signal(sig)
                    s.tags.extend(["scan:reddit", "tier:1", f"r/{sub}"])
                    signals.append(s)
                    self._stats["signals_by_source"]["reddit"] += 1
            except Exception as e:
                log.warning(f"[AGENT:SCAN:REDDIT:T1] r/{sub} failed: {e}")
                self._stats["source_errors"]["reddit"] += 1

        # Tier 2 — every cycle, hot only (supporting intel)
        for sub in tier2:
            try:
                await self._rate_limiters["reddit"].acquire()
                raw = await self.scanner.scan_reddit(sub, max_results=5)
                for sig in raw:
                    s = Signal.from_insight_signal(sig)
                    s.tags.extend(["scan:reddit", "tier:2", f"r/{sub}"])
                    signals.append(s)
                    self._stats["signals_by_source"]["reddit"] += 1
            except Exception as e:
                log.warning(f"[AGENT:SCAN:REDDIT:T2] r/{sub} failed: {e}")
                self._stats["source_errors"]["reddit"] += 1

        # Tier 3 — rotated batch of 5 per cycle (broader context)
        if tier3:
            batch = []
            for i in range(self._tier3_batch_size):
                idx = (self._tier3_offset + i) % len(tier3)
                batch.append(tier3[idx])
            self._tier3_offset = (self._tier3_offset + self._tier3_batch_size) % len(tier3)

            for sub in batch:
                try:
                    await self._rate_limiters["reddit"].acquire()
                    raw = await self.scanner.scan_reddit(sub, max_results=5)
                    for sig in raw:
                        s = Signal.from_insight_signal(sig)
                        s.tags.extend(["scan:reddit", "tier:3", f"r/{sub}"])
                        signals.append(s)
                        self._stats["signals_by_source"]["reddit"] += 1
                except Exception as e:
                    log.warning(f"[AGENT:SCAN:REDDIT:T3] r/{sub} failed: {e}")
                    self._stats["source_errors"]["reddit"] += 1

            log.info(f"[AGENT:SCAN:REDDIT] Tier scan: T1={len(tier1)} T2={len(tier2)} T3={len(batch)}/{len(tier3)} (offset {self._tier3_offset})")

        return signals

    async def _collect_google_trends(self) -> list[Signal]:
        """Collect from Google Trends via IntelligenceEngine collector."""
        signals = []
        if not self.intelligence_engine:
            return signals

        try:
            await self._rate_limiters["google_trends"].acquire()
            trends = await self.intelligence_engine._trends.collect_daily_trends()
            for sig in trends:
                s = Signal.from_intel_signal(sig)
                s.tags.append("scan:google_trends")
                signals.append(s)
                self._stats["signals_by_source"]["google_trends"] += 1
        except Exception as e:
            log.warning(f"[AGENT:SCAN:GTRENDS] Failed: {e}")
            self._stats["source_errors"]["google_trends"] += 1

        return signals

    async def _collect_polymarket(self) -> list[Signal]:
        """Collect from Polymarket prediction markets."""
        signals = []
        if not self.intelligence_engine:
            return signals

        try:
            await self._rate_limiters["polymarket"].acquire()
            raw = await self.intelligence_engine._polymarket.collect_trending_markets()
            for sig in raw:
                s = Signal.from_intel_signal(sig)
                s.tags.append("scan:polymarket")
                signals.append(s)
                self._stats["signals_by_source"]["polymarket"] += 1
        except Exception as e:
            log.warning(f"[AGENT:SCAN:POLYMARKET] Failed: {e}")
            self._stats["source_errors"]["polymarket"] += 1

        return signals

    async def _collect_news(self) -> list[Signal]:
        """Collect from NewsAPI/GNews."""
        signals = []
        if not self.intelligence_engine:
            return signals

        # Combine all watch queries into news topics
        all_queries = []
        for source_queries in self._watch_queries.values():
            if isinstance(source_queries, list):
                all_queries.extend(source_queries[:3])  # Top 3 from each

        for query in all_queries[:5]:  # Max 5 news queries per cycle
            try:
                await self._rate_limiters["news"].acquire()
                raw = await self.intelligence_engine._news.collect_topic_news(query=query)
                for sig in raw:
                    s = Signal.from_intel_signal(sig)
                    s.tags.append("scan:news")
                    signals.append(s)
                    self._stats["signals_by_source"]["news"] += 1
            except Exception as e:
                log.warning(f"[AGENT:SCAN:NEWS] Query '{query}' failed: {e}")
                self._stats["source_errors"]["news"] += 1

        return signals

    # CryptoCollector disabled — re-enable when rate limiting resolved
    # async def _collect_crypto(self) -> list[Signal]:
    #     """Collect crypto market data from CoinGecko."""
    #     signals = []
    #     if not self.intelligence_engine:
    #         return signals
    #     try:
    #         await self._rate_limiters["crypto"].acquire()
    #         raw = await self.intelligence_engine._crypto.collect_market_data()
    #         for sig in raw:
    #             s = Signal.from_intel_signal(sig)
    #             s.tags.append("scan:crypto")
    #             signals.append(s)
    #             self._stats["signals_by_source"]["crypto"] += 1
    #     except Exception as e:
    #         log.warning(f"[AGENT:SCAN:CRYPTO] Failed: {e}")
    #         self._stats["source_errors"]["crypto"] += 1
    #     return signals

    async def _collect_unusual_whales(self) -> list[Signal]:
        """Collect options flow from Unusual Whales."""
        signals = []
        if not self.intelligence_engine:
            return signals

        try:
            await self._rate_limiters["unusual_whales"].acquire()
            raw = await self.intelligence_engine._unusual_whales.collect_flow_alerts()
            for sig in raw:
                s = Signal.from_intel_signal(sig)
                s.tags.append("scan:unusual_whales")
                signals.append(s)
                self._stats["signals_by_source"]["unusual_whales"] += 1
        except Exception as e:
            log.warning(f"[AGENT:SCAN:UW] Failed: {e}")
            self._stats["source_errors"]["unusual_whales"] += 1

        return signals

    async def _collect_council_reports(self) -> list[Signal]:
        """Collect insights from YouTube Council and X Council reports.

        Reads report JSONs from intelligence-scan/council-reports/ and
        intelligence-scan/signals/signals-{date}.jsonl written by the
        council pipeline. Only reads reports from the last 48 hours.
        """
        signals = []
        ncl_base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
        cutoff = time.time() - 48 * 3600  # 48 hours ago

        # ── Read council report JSONs ────────────────────────────────
        report_dirs = [
            ncl_base / "intelligence-scan" / "council-reports",
            ncl_base / "intelligence-scan" / "youtube-reports",
        ]
        loop = asyncio.get_running_loop()
        for report_dir in report_dirs:
            if not report_dir.exists():
                continue
            try:
                json_files = await loop.run_in_executor(
                    None, lambda d=report_dir: sorted(d.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:10]
                )
            except Exception:
                json_files = []
            for json_file in json_files:
                try:
                    mtime = await loop.run_in_executor(None, lambda f=json_file: f.stat().st_mtime)
                    if mtime < cutoff:
                        continue
                    raw_text = await loop.run_in_executor(None, json_file.read_text)
                    data = json.loads(raw_text)
                    # Determine source from filename
                    source = "youtube" if "youtube" in json_file.name.lower() or "ytc" in json_file.name.lower() else "x"

                    # Extract insights from report
                    insights = data.get("insights", [])
                    summary = data.get("summary", data.get("title", ""))

                    if summary:
                        s = Signal(
                            signal_id=f"council-{json_file.stem}",
                            source=source,
                            title=f"Council Report: {data.get('title', json_file.stem)}",
                            content=summary[:1000],
                            url="",
                            composite_score=0.0,
                            route_level="",
                            timestamp=datetime.now(timezone.utc),
                            tags=[f"council:{source}", "council_report"],
                        )
                        s.relevance = 0.7  # Council reports are pre-filtered for relevance
                        s.actionability = 0.6
                        s.authority = 0.8  # Council analysis = high authority
                        signals.append(s)
                        self._stats["signals_by_source"][f"council_{source}"] += 1

                    for insight in insights[:5]:  # Top 5 insights per report
                        content = insight if isinstance(insight, str) else insight.get("text", insight.get("content", str(insight)))
                        confidence = insight.get("confidence", 0.7) if isinstance(insight, dict) else 0.7
                        s = Signal(
                            signal_id=f"council-insight-{uuid.uuid4().hex[:8]}",
                            source=source,
                            title=f"Council Insight ({source.upper()})",
                            content=str(content)[:500],
                            url="",
                            composite_score=0.0,
                            route_level="",
                            timestamp=datetime.now(timezone.utc),
                            tags=[f"council:{source}", "council_insight"],
                        )
                        s.relevance = 0.65
                        s.actionability = confidence
                        s.authority = 0.75
                        signals.append(s)
                        self._stats["signals_by_source"][f"council_{source}"] += 1

                except Exception as e:
                    log.warning(f"[AGENT:SCAN:COUNCIL] Failed to read {json_file.name}: {e}")

        # ── Read signals JSONL files ─────────────────────────────────
        signals_dir = ncl_base / "intelligence-scan" / "signals"
        if signals_dir.exists():
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
            for date_str in [today, yesterday]:
                jsonl_path = signals_dir / f"signals-{date_str}.jsonl"
                if not jsonl_path.exists():
                    continue
                try:
                    loop = asyncio.get_running_loop()
                    raw_text = await loop.run_in_executor(None, jsonl_path.read_text)
                    lines = raw_text.strip().split("\n")
                    for line in lines[-20:]:  # Last 20 entries
                        if not line.strip():
                            continue
                        entry = json.loads(line)
                        source = entry.get("source", "unknown")
                        s = Signal(
                            signal_id=entry.get("signal_id", f"council-sig-{uuid.uuid4().hex[:8]}"),
                            source=source,
                            title=entry.get("title", "Council Signal"),
                            content=entry.get("content", "")[:500],
                            url=entry.get("url", ""),
                            composite_score=0.0,
                            route_level="",
                            timestamp=datetime.now(timezone.utc),
                            tags=[f"council:{source}", "council_signal"],
                        )
                        s.relevance = 0.6
                        s.actionability = entry.get("confidence", 0.6)
                        s.authority = 0.7
                        signals.append(s)
                        self._stats["signals_by_source"][f"council_{source}"] += 1
                except Exception as e:
                    log.warning(f"[AGENT:SCAN:COUNCIL] Failed to read {jsonl_path.name}: {e}")

        if signals:
            log.info(f"[AGENT:SCAN:COUNCIL] Collected {len(signals)} council signals")
        return signals

    # ═══════════════════════════════════════════════════════════════════
    # SCORING (deterministic, pure functions applied to signals)
    # ═══════════════════════════════════════════════════════════════════

    def score_signal(self, signal: Signal) -> Signal:
        """
        Apply multi-factor scoring to a signal using data-driven algorithms.

        Uses BM25 relevance, exponential-decay novelty with SimHash
        near-duplicate detection, real engagement authority, HN-gravity
        freshness decay, and a 5-factor weighted composite.

        Scanner-provided scores are BLENDED (not max'd) with computed
        scores to prevent hardcoded values from bypassing the scoring engine.

        Args:
            signal: Signal to score (modified in-place and returned)

        Returns:
            The scored Signal with composite_score and route_level set.
        """
        # ── RELEVANCE: BM25 word-boundary matching ──────────────────
        all_queries = []
        for source_queries in self._watch_queries.values():
            if isinstance(source_queries, list):
                all_queries.extend(source_queries)
        text = f"{signal.title} {signal.content}"
        bm25_relevance = compute_relevance_bm25(text, all_queries)
        # Blend: 70% BM25, 30% scanner-provided (if any)
        relevance = 0.7 * bm25_relevance + 0.3 * signal.relevance

        # Add mandate/working-context keyword boost
        context_keywords = self._get_context_keywords()
        if context_keywords:
            signal_text = f"{signal.title} {signal.content} {' '.join(signal.tags)}"
            signal_tokens = set(t.lower() for t in re.findall(r'\b[a-zA-Z0-9]{3,}\b', signal_text))
            matches = len(signal_tokens & context_keywords)
            keyword_score = min(matches / 5.0, 1.0)  # 0=0, 1=0.2, 2=0.4, 3=0.6, 4=0.8, 5+=1.0
            relevance = 0.5 * relevance + 0.5 * keyword_score  # Blend BM25 with keyword match

        signal.relevance = relevance

        # ── NOVELTY: Exponential decay + SimHash near-dupe ──────────
        decay_novelty = compute_novelty_decay(signal, self._simhash_index)
        signal.novelty = decay_novelty

        # Update SimHash index for future signals
        content_for_hash = f"{signal.title} {signal.content[:300]}"
        fp = signal.fingerprint()
        sig_hash = _simhash64(content_for_hash)
        now_ts = signal.timestamp.timestamp() if signal.timestamp else time.time()
        self._simhash_index[fp] = (sig_hash, now_ts)
        # Bound index size to prevent memory leak — prune 20% when over limit
        # to avoid re-sorting on every subsequent signal
        if len(self._simhash_index) > DEDUP_WINDOW_SIZE:
            prune_count = len(self._simhash_index) // 5  # 20%
            oldest_keys = sorted(
                self._simhash_index.keys(),
                key=lambda k: self._simhash_index[k][1]
            )[:prune_count]
            for k in oldest_keys:
                del self._simhash_index[k]

        # ── AUTHORITY: Real engagement + platform base ──────────────
        computed_authority = compute_authority(signal.source, signal.metadata)
        # Blend: 80% computed, 20% scanner-provided
        signal.authority = 0.8 * computed_authority + 0.2 * signal.authority

        # ── ACTIONABILITY: engagement + directional signals ─────────
        base_actionability = signal.actionability  # from scanner engagement
        if signal.direction not in ("neutral", "") and signal.confidence > 0.6:
            base_actionability = max(base_actionability, 0.6 + signal.confidence * 0.2)
        if signal.change_pct is not None and abs(signal.change_pct) > 10:
            base_actionability = max(base_actionability, 0.7)
        signal.actionability = base_actionability

        # ── FRESHNESS: HN-gravity time decay ────────────────────────
        freshness = compute_freshness(signal)

        # ── CROSS-SOURCE: multi-source confirmation ─────────────────
        cross_source = self._compute_cross_source(
            f"{signal.title} {signal.content}", signal.source
        )

        # ── COMPOSITE: 6-factor weighted blend ──────────────────────
        signal.composite_score = compute_composite_score(
            signal.relevance,
            signal.actionability,
            signal.novelty,
            signal.authority,
            freshness,
            cross_source=cross_source,
        )

        # Store score factors in metadata
        signal.metadata["score_factors"] = {
            "context_relevance": round(signal.relevance * 100, 1),
            "freshness": round(freshness * 100, 1),
            "cross_source": round(cross_source * 100, 1),
            "source_confidence": round(signal.authority * 100, 1),
            "actionability": round(signal.actionability * 100, 1),
            "novelty": round(signal.novelty * 100, 1),
        }

        # Classify route level
        signal.route_level = classify_route_level(signal.composite_score)

        self._stats["signals_scored"] += 1
        return signal

    def score_signals(self, signals: list[Signal]) -> list[Signal]:
        """Score a batch of signals. Returns them sorted by composite score descending."""
        scored = [self.score_signal(s) for s in signals]
        scored.sort(key=lambda s: s.composite_score, reverse=True)
        return scored

    # ═══════════════════════════════════════════════════════════════════
    # REASONING GATE (LLM only for ambiguous signals)
    # ═══════════════════════════════════════════════════════════════════

    async def reason_about_signal(self, signal: Signal) -> Signal:
        """
        LLM reasoning for ambiguous signals in the 0.30-0.55 composite zone.

        Injects top-5 recent signals as context so the LLM can make
        comparative decisions. Clamps adjusted_score to [0, 1].

        Args:
            signal: An ambiguous signal (composite 0.30-0.55)

        Returns:
            Signal with potentially adjusted score and route_level
        """
        if not is_ambiguous(signal.composite_score):
            return signal

        self._stats["llm_reasoning_calls"] += 1

        # Inject top-5 recent context signals for comparative reasoning
        recent_context = ""
        if self._context_top10:
            recent_items = list(self._context_top10)[:5]
            context_lines = [
                f"  - [{s.source}] {s.title[:60]} (score={s.composite_score:.2f})"
                for s in recent_items
            ]
            recent_context = "\nRecent HIGH/CRITICAL signals for comparison:\n" + "\n".join(context_lines)

        prompt = f"""Analyze this intelligence signal and decide if it warrants HIGH priority routing.

Signal:
- Source: {signal.source}
- Title: {signal.title}
- Content: {signal.content[:300]}
- Current composite score: {signal.composite_score:.3f}
- Tags: {', '.join(signal.tags[:5])}
- Direction: {signal.direction}
{recent_context}

Context: This signal scored in the ambiguous zone (0.30-0.55). Deterministic scoring couldn't confidently classify it.

Question: Should this signal be promoted to HIGH priority (>= 0.55)?
Consider: Is there actionable intelligence here that NATRIX should see immediately?
Compare against recent signals above — is this MORE or LESS important?

Respond with ONLY a JSON object:
{{"promote": true/false, "adjusted_score": 0.0-1.0, "reasoning": "one sentence"}}"""

        try:
            response = await self._http_client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 150, "temperature": 0.3},
                },
                timeout=120.0,
            )
            if response.status_code != 200:
                log.warning(
                    f"[AGENT:REASON] Ollama returned {response.status_code}: {response.text[:200]}"
                )
                return signal
            data = response.json()
            if "response" not in data or not data["response"]:
                log.warning(f"[AGENT:REASON] Empty response from Ollama: {data.get('error', 'unknown')}")
                return signal
            text = data["response"]

            # Parse JSON response — strip markdown fences if present
            clean = text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            result = json.loads(clean)
            signal.llm_reasoning = result.get("reasoning", "")

            # CLAMP adjusted_score to [0.0, 1.0] — LLMs sometimes return >1.0
            raw_adjusted = float(result.get("adjusted_score", signal.composite_score))
            adjusted = min(1.0, max(0.0, raw_adjusted))
            signal.llm_adjusted_score = adjusted

            original_score = signal.composite_score
            if result.get("promote") and adjusted >= THRESHOLD_HIGH:
                signal.composite_score = adjusted
                signal.route_level = classify_route_level(adjusted)
                log.info(
                    f"[AGENT:REASON] Signal promoted to {signal.route_level}: "
                    f"{signal.title[:60]} (was {original_score:.3f} → {adjusted:.3f})"
                )
            else:
                log.debug(f"[AGENT:REASON] Signal kept at MEDIUM: {signal.title[:60]}")

        except Exception as e:
            log.warning(f"[AGENT:REASON] LLM reasoning failed ({type(e).__name__}): {e}")

        return signal

    # ═══════════════════════════════════════════════════════════════════
    # ROUTING (ACT)
    # ═══════════════════════════════════════════════════════════════════

    async def route_signal(self, signal: Signal):
        """
        Route signal based on composite score thresholds.

        >= 0.75 CRITICAL: Context + Memory + Push alert + Council flag
        >= 0.55 HIGH:     Context + Memory + Source report
        >= 0.30 MEDIUM:   Memory + maybe Context (after LLM reasoning)
        <  0.30 LOW:      Log only, skip storage
        """
        level = signal.route_level
        self._stats["signals_routed"] += 1
        self._stats["signals_by_level"][level] += 1

        if level == "CRITICAL":
            await self._route_critical(signal)
        elif level == "HIGH":
            await self._route_high(signal)
        elif level == "MEDIUM":
            await self._route_medium(signal)
        else:
            # LOW — log only
            log.debug(f"[AGENT:ROUTE:LOW] Skipping: {signal.title[:60]} ({signal.composite_score:.3f})")

        # Always add to prediction buffer regardless of level
        self._prediction_buffer.append(signal)

        # Persist to JSONL
        await self._persist_signal(signal)

    async def _route_critical(self, signal: Signal):
        """CRITICAL routing: full distribution + push alert."""
        log.warning(
            f"[AGENT:ROUTE:CRITICAL] {signal.source} | {signal.title[:80]} "
            f"(score={signal.composite_score:.3f})"
        )

        # Add to all context windows
        self._context_top10.append(signal)
        self._context_24h.append(signal)
        self._context_7d.append(signal)

        # Store in long-term memory
        await self._store_to_memory(signal, importance=85.0)

        # Inject into working context
        await self._inject_working_context(signal)

        # Push alert to NATRIX
        await self._push_alert(signal)

        # Flag for council consideration
        signal.tags.append("council_flagged")

    async def _route_high(self, signal: Signal):
        """HIGH routing: context + memory + source report."""
        log.info(
            f"[AGENT:ROUTE:HIGH] {signal.source} | {signal.title[:80]} "
            f"(score={signal.composite_score:.3f})"
        )

        # Add to context windows
        self._context_24h.append(signal)
        self._context_7d.append(signal)

        # Store in memory
        await self._store_to_memory(signal, importance=65.0)

        # Inject into working context
        await self._inject_working_context(signal)

    async def _route_medium(self, signal: Signal):
        """MEDIUM routing: memory only (context after LLM reasoning promotes)."""
        log.debug(
            f"[AGENT:ROUTE:MEDIUM] {signal.source} | {signal.title[:60]} "
            f"(score={signal.composite_score:.3f})"
        )

        # Store in memory with moderate importance
        await self._store_to_memory(signal, importance=45.0)

        # Add to 7d window only
        self._context_7d.append(signal)

    async def _store_to_memory(self, signal: Signal, importance: float):
        """Persist signal to MemoryStore with typed collection routing and entity extraction."""
        if not self.memory_store:
            return

        try:
            content = f"[{signal.source}] {signal.title}\n{signal.content[:400]}"
            if signal.url:
                content += f"\nURL: {signal.url}"

            # Determine memory type from signal characteristics
            memory_type = "signal"  # Default for awarebot signals
            source_lower = signal.source.lower()
            if "council" in source_lower:
                memory_type = "semantic"
            elif "prediction" in source_lower:
                memory_type = "episodic"
            elif any(t in signal.tags for t in ["decision", "commitment", "approved"]):
                memory_type = "decision"

            # Fast entity extraction (regex only, no LLM cost)
            entities = []
            relationships = []
            try:
                from ..memory.entity_extractor import fast_extract_entities, fast_extract_relationships
                entities = fast_extract_entities(content)
                relationships = fast_extract_relationships(content)
            except Exception:
                pass  # Entity extraction is optional

            unit = await self.memory_store.create_unit(
                content=content,
                source=f"awarebot:{signal.source}",
                importance=importance,
                tags=signal.tags[:10],
                memory_type=memory_type,
            )

            # Attach entities and relationships to the unit if extraction succeeded
            if entities or relationships:
                try:
                    unit.entities = entities
                    unit.relationships = relationships
                    # Persist the updated unit (async, non-blocking)
                    asyncio.create_task(self.memory_store.index_unit(unit))
                except Exception:
                    pass

        except Exception as e:
            log.warning(f"[AGENT:MEMORY] Failed to store signal: {e}")

    async def _inject_working_context(self, signal: Signal):
        """Inject signal into DailyContextWindow for operator visibility."""
        if not self.working_context:
            return

        try:
            # DailyContextWindow expects specific format — adapt
            await self.working_context.inject_signal(
                content=f"[{signal.source.upper()}] {signal.title}",
                source=f"awarebot:{signal.source}",
                importance=signal.composite_score * 100,
                tags=signal.tags[:5],
            )
        except AttributeError:
            # Working context might not have inject_signal — use add_item if available
            try:
                await self.working_context.add_item(
                    content=f"[{signal.source.upper()}] {signal.title}",
                    source=f"awarebot:{signal.source}",
                    importance=signal.composite_score * 100,
                )
            except Exception as inner_e:
                log.debug(f"[AGENT:CONTEXT] Working context add_item also failed: {inner_e}")
        except Exception as e:
            log.debug(f"[AGENT:CONTEXT] Working context injection failed: {e}")

    # ═══════════════════════════════════════════════════════════════════
    # CROSS-SOURCE & CONTEXT KEYWORD SCORING
    # ═══════════════════════════════════════════════════════════════════

    def _compute_cross_source(self, signal_text: str, signal_source: str) -> float:
        """Cross-source confirmation score (0-1). Checks if other sources report similar content."""
        if not signal_text or len(signal_text) < 20:
            return 0.0
        tokens = set(t.lower() for t in re.findall(r'\b[a-zA-Z0-9]{3,}\b', signal_text))
        if len(tokens) < 3:
            return 0.0
        confirming_sources = set()
        for other in self._context_7d:
            other_source = getattr(other, 'source', '') or ''
            if other_source == signal_source:
                continue
            other_text = getattr(other, 'content', '') or getattr(other, 'title', '') or ''
            if not other_text:
                continue
            other_tokens = set(t.lower() for t in re.findall(r'\b[a-zA-Z0-9]{3,}\b', other_text))
            if not other_tokens:
                continue
            overlap = len(tokens & other_tokens) / min(len(tokens), len(other_tokens))
            if overlap > 0.30:
                confirming_sources.add(other_source)
        count = len(confirming_sources)
        if count == 0: return 0.0
        if count == 1: return 0.40
        if count == 2: return 0.70
        return 1.0

    def _load_context_keywords(self) -> set[str]:
        """Load context keywords from mandates, watch queries, and working context."""
        keywords = set()
        base = self._data_dir.parent  # NCL root

        # Watch queries
        wq_file = base / "config" / "watch_queries.json"
        if not wq_file.exists():
            wq_file = base / "data" / "watch_queries.json"
        if wq_file.exists():
            try:
                wq = json.loads(wq_file.read_text())
                for source_queries in wq.values():
                    if isinstance(source_queries, list):
                        for q in source_queries:
                            if isinstance(q, str):
                                keywords.update(t.lower() for t in re.findall(r'\b[a-zA-Z0-9]{3,}\b', q))
                            elif isinstance(q, dict):
                                for v in q.values():
                                    if isinstance(v, str):
                                        keywords.update(t.lower() for t in re.findall(r'\b[a-zA-Z0-9]{3,}\b', v))
            except Exception:
                pass

        # Mandates
        mandates_file = base / "data" / "mandates.json"
        if not mandates_file.exists():
            mandates_file = base / "data" / "mandates" / "mandates.json"
        if mandates_file.exists():
            try:
                mandates = json.loads(mandates_file.read_text())
                if isinstance(mandates, dict):
                    mandates = mandates.get("mandates", mandates.get("items", []))
                if isinstance(mandates, list):
                    for m in mandates:
                        if not isinstance(m, dict):
                            continue
                        status = m.get("status", "").lower()
                        if status not in ("active", "in_progress", "pending", "approved", ""):
                            continue
                        for field in ("title", "description", "objective"):
                            val = m.get(field, "")
                            if isinstance(val, str):
                                keywords.update(t.lower() for t in re.findall(r'\b[a-zA-Z0-9]{3,}\b', val))
                        for tag in m.get("tags", []):
                            if isinstance(tag, str) and len(tag) >= 3:
                                keywords.add(tag.lower())
            except Exception:
                pass

        # Working context themes
        wc_file = base / "data" / "working_context" / "today.json"
        if wc_file.exists():
            try:
                wc = json.loads(wc_file.read_text())
                themes = wc.get("themes", wc.get("topics", wc.get("keywords", [])))
                if isinstance(themes, list):
                    for t in themes:
                        if isinstance(t, str) and len(t) >= 3:
                            keywords.add(t.lower())
                elif isinstance(themes, dict):
                    for v in themes.values():
                        if isinstance(v, str):
                            keywords.update(t.lower() for t in re.findall(r'\b[a-zA-Z0-9]{3,}\b', v))
            except Exception:
                pass

        return keywords

    def _get_context_keywords(self) -> set[str]:
        """Get context keywords, refreshing every 10 minutes."""
        now = time.time()
        if now - self._keywords_loaded_at > 600:
            self._context_keywords = self._load_context_keywords()
            self._keywords_loaded_at = now
        return self._context_keywords

    # ═══════════════════════════════════════════════════════════════════
    # TIER ROUTING (Focused / Micro / Macro)
    # ═══════════════════════════════════════════════════════════════════

    def route_to_tiers(self) -> dict:
        """Route buffered signals into Focused/Micro/Macro tiers. Single-pass, exclusive assignment."""
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)

        # Gather all signals from deques, deduplicate
        seen_ids = set()
        all_signals = []
        for sig in itertools.chain(self._context_top10, self._context_24h, self._context_7d):
            sig_id = getattr(sig, 'signal_id', None) or getattr(sig, 'id', id(sig))
            if sig_id in seen_ids:
                continue
            seen_ids.add(sig_id)
            all_signals.append(sig)

        focused, micro, macro, claimed = [], [], [], set()

        # Pass 1: FOCUSED — score >= 0.75, age < 4h
        for sig in sorted(all_signals, key=lambda s: (
            -(s.metadata.get("score_factors", {}).get("cross_source", 0)),
            -s.composite_score
        )):
            if len(focused) >= 10:
                break
            age_h = (now - sig.timestamp).total_seconds() / 3600 if hasattr(sig, 'timestamp') and sig.timestamp else 999
            if sig.composite_score >= 0.75 and age_h < 4:
                focused.append(sig)
                claimed.add(id(sig))

        # Pass 2: MICRO — score >= 0.50, age < 24h, not claimed
        for sig in sorted(all_signals, key=lambda s: -s.composite_score):
            if len(micro) >= 10:
                break
            if id(sig) in claimed:
                continue
            age_h = (now - sig.timestamp).total_seconds() / 3600 if hasattr(sig, 'timestamp') and sig.timestamp else 999
            if sig.composite_score >= 0.50 and age_h < 24:
                micro.append(sig)
                claimed.add(id(sig))

        # Pass 3: MACRO — persistent narratives, not claimed
        narrative_sources = {"council", "journal", "mandate", "morning_brief", "brief"}
        for sig in sorted(all_signals, key=lambda s: -s.composite_score):
            if len(macro) >= 10:
                break
            if id(sig) in claimed:
                continue
            if sig.composite_score < 0.30:
                continue
            age_h = (now - sig.timestamp).total_seconds() / 3600 if hasattr(sig, 'timestamp') and sig.timestamp else 999
            source_lower = (getattr(sig, 'source', '') or '').lower()
            is_narrative = any(ns in source_lower for ns in narrative_sources)
            if age_h > 24 or is_narrative:
                macro.append(sig)
                claimed.add(id(sig))
            elif sig.composite_score >= 0.60:
                macro.append(sig)
                claimed.add(id(sig))

        def sig_to_dict(s):
            d = {
                "signal_id": getattr(s, 'signal_id', None) or str(id(s)),
                "title": getattr(s, 'title', '') or '',
                "content": getattr(s, 'content', '') or '',
                "source": getattr(s, 'source', '') or '',
                "tags": getattr(s, 'tags', []) or [],
                "composite_score": getattr(s, 'composite_score', 0),
                "unified_score": round(getattr(s, 'composite_score', 0) * 100, 1),
                "route_level": getattr(s, 'route_level', ''),
                "direction": getattr(s, 'direction', 'neutral'),
                "url": getattr(s, 'url', ''),
            }
            if hasattr(s, 'timestamp') and s.timestamp:
                d["timestamp"] = s.timestamp.isoformat()
            if hasattr(s, 'metadata') and isinstance(s.metadata, dict):
                d["score_factors"] = s.metadata.get("score_factors", {})
                d["id"] = s.metadata.get("id", d["signal_id"])
            return d

        return {
            "focused": {"signals": [sig_to_dict(s) for s in focused], "count": len(focused), "tier": "focused"},
            "micro": {"signals": [sig_to_dict(s) for s in micro], "count": len(micro), "tier": "micro"},
            "macro": {"signals": [sig_to_dict(s) for s in macro], "count": len(macro), "tier": "macro"},
        }

    async def _push_alert(self, signal: Signal):
        """Send push notification for critical signals with throttling.

        Rate-limited to max 3 alerts per 15-minute window to prevent
        alert fatigue during high-activity periods.
        """
        if not self.push_callback:
            log.debug("[AGENT:PUSH] No push callback configured — skipping alert")
            return

        # Throttle check: max N alerts per window
        now = time.monotonic()
        # Purge old timestamps outside window
        while (self._alert_timestamps and
               now - self._alert_timestamps[0] > self._alert_window_seconds):
            self._alert_timestamps.popleft()

        if len(self._alert_timestamps) >= self._max_alerts_per_window:
            log.info(
                f"[AGENT:PUSH] Alert throttled (>{self._max_alerts_per_window}"
                f"/{self._alert_window_seconds}s): {signal.title[:60]}"
            )
            return

        try:
            await self.push_callback({
                "type": "critical_signal",
                "source": signal.source,
                "title": signal.title[:100],
                "score": signal.composite_score,
                "url": signal.url,
                "timestamp": signal.timestamp.isoformat(),
            })
            self._alert_timestamps.append(now)
            log.info(f"[AGENT:PUSH] Alert sent: {signal.title[:60]}")
        except Exception as e:
            log.warning(f"[AGENT:PUSH] Failed to send alert: {e}")

    # ═══════════════════════════════════════════════════════════════════
    # CONTEXT MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════

    async def update_context(self):
        """
        Maintain three context windows: top10, 24h, 7d.

        Prunes expired signals and re-ranks top10 by composite score.
        Implements the Select/Compress phases of tiered context management.
        """
        now = datetime.now(timezone.utc)

        # Prune 24h window
        self._context_24h = deque(
            (s for s in self._context_24h if now - s.timestamp < timedelta(hours=24)),
            maxlen=CONTEXT_24H_MAX,
        )

        # Prune 7d window
        self._context_7d = deque(
            (s for s in self._context_7d if now - s.timestamp < timedelta(days=7)),
            maxlen=CONTEXT_7D_MAX,
        )

        # Re-rank top10 from 24h window
        sorted_24h = sorted(self._context_24h, key=lambda s: s.composite_score, reverse=True)
        self._context_top10 = deque(sorted_24h[:CONTEXT_TOP10_SIZE], maxlen=CONTEXT_TOP10_SIZE)

        log.debug(
            f"[AGENT:CONTEXT] Updated: top10={len(self._context_top10)}, "
            f"24h={len(self._context_24h)}, 7d={len(self._context_7d)}"
        )

    def get_context_summary(self) -> dict[str, Any]:
        """Get current context state for API/chat."""
        return {
            "top10": [s.to_dict() for s in self._context_top10],
            "context_24h_count": len(self._context_24h),
            "context_7d_count": len(self._context_7d),
            "top_sources": self._get_top_sources(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _get_top_sources(self) -> dict[str, int]:
        """Count signals by source in the 24h window."""
        counts: dict[str, int] = defaultdict(int)
        for s in self._context_24h:
            counts[s.source] += 1
        return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True)[:5])

    # ═══════════════════════════════════════════════════════════════════
    # SOURCE REPORTS
    # ═══════════════════════════════════════════════════════════════════

    async def generate_source_report(self, source: str) -> dict[str, Any]:
        """
        Generate per-source digest (X report, YouTube report, etc.).

        Aggregates signals from the 24h window for the specified source,
        identifies themes, and produces a structured report.

        Args:
            source: Source name (x, youtube, reddit, crypto, etc.)

        Returns:
            Structured report dict with themes, top signals, stats
        """
        source_signals = [s for s in self._context_24h if s.source == source]

        if not source_signals:
            return {
                "source": source,
                "signal_count": 0,
                "status": "no_signals",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        # Sort by score
        ranked = sorted(source_signals, key=lambda s: s.composite_score, reverse=True)

        # Extract themes from tags
        tag_counts: dict[str, int] = defaultdict(int)
        for s in source_signals:
            for tag in s.tags:
                if not tag.startswith("scan:"):
                    tag_counts[tag] += 1
        top_themes = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        # Direction analysis
        direction_counts: dict[str, int] = defaultdict(int)
        for s in source_signals:
            direction_counts[s.direction] += 1

        return {
            "source": source,
            "signal_count": len(source_signals),
            "avg_composite_score": round(
                sum(s.composite_score for s in source_signals) / len(source_signals), 3
            ),
            "top_signals": [s.to_dict() for s in ranked[:20]],
            "themes": [{"theme": t, "count": c} for t, c in top_themes],
            "direction_breakdown": dict(direction_counts),
            "critical_count": sum(1 for s in source_signals if s.route_level == "CRITICAL"),
            "high_count": sum(1 for s in source_signals if s.route_level == "HIGH"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ═══════════════════════════════════════════════════════════════════
    # BRIEFS (OBSERVE)
    # ═══════════════════════════════════════════════════════════════════

    async def generate_brief(self) -> dict[str, Any]:
        """
        4-hour consolidation: synthesize context into executive brief.

        Correlates signals across sources, identifies sector themes,
        ranks by combined importance, and produces a structured brief.

        Returns:
            Executive brief dict with sectors, top signals, recommendations
        """
        log.info("[AGENT:BRIEF] Generating executive brief")
        self._stats["briefs_generated"] += 1
        self._stats["last_brief_at"] = datetime.now(timezone.utc).isoformat()

        # Collect signals from 24h window
        signals_24h = list(self._context_24h)

        if not signals_24h:
            return {
                "brief_id": str(uuid.uuid4()),
                "status": "no_signals",
                "message": "No signals collected in the last 24 hours",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        # Convert to IntelSignal for correlator compatibility
        intel_signals = self._signals_to_intel(signals_24h)

        # Correlate into sectors
        sectors = self._correlator.correlate(intel_signals)

        # Build sector summaries
        sector_summaries = []
        for sector in sectors[:8]:  # Top 8 sectors
            sector_summaries.append({
                "sector": sector.sector,
                "signal_count": sector.signal_count,
                "avg_confidence": sector.avg_confidence,
                "direction": sector.direction.value if hasattr(sector.direction, "value") else str(sector.direction),
                "summary": sector.summary,
            })

        # Top signals across all sources
        top_signals = sorted(signals_24h, key=lambda s: s.composite_score, reverse=True)[:10]

        # Generate executive summary via LLM if available
        executive_summary = await self._generate_executive_summary(top_signals, sector_summaries)

        brief = {
            "brief_id": str(uuid.uuid4()),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "time_window": "24h",
            "total_signals": len(signals_24h),
            "critical_count": sum(1 for s in signals_24h if s.route_level == "CRITICAL"),
            "high_count": sum(1 for s in signals_24h if s.route_level == "HIGH"),
            "sectors": sector_summaries,
            "top_signals": [s.to_dict() for s in top_signals],
            "executive_summary": executive_summary,
            "source_breakdown": self._get_top_sources(),
        }

        # Persist brief
        await self._persist_brief(brief)

        return brief

    async def _generate_executive_summary(
        self,
        top_signals: list[Signal],
        sectors: list[dict],
    ) -> str:
        """Generate LLM executive summary from top signals and sectors."""
        if not top_signals:
            return "No significant intelligence to report."

        signals_text = "\n".join(
            f"- [{s.source}] {s.title} (score={s.composite_score:.2f}, dir={s.direction})"
            for s in top_signals[:8]
        )
        sectors_text = "\n".join(
            f"- {s['sector']}: {s['signal_count']} signals, direction={s['direction']}"
            for s in sectors[:5]
        )

        prompt = f"""Synthesize this intelligence into a 3-4 sentence executive brief for NATRIX.

Top Signals:
{signals_text}

Active Sectors:
{sectors_text}

Be concise, actionable, and highlight the most important developments.
Focus on what requires attention or action."""

        try:
            response = await self._http_client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": getattr(self.config, "claude_api_key", os.getenv("ANTHROPIC_API_KEY", "")),
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": os.getenv("NCL_AGENT_SUMMARY_MODEL", "claude-sonnet-4-20250514"),
                    "max_tokens": 300,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

            # Track cost
            try:
                from ..cost_tracker import record_cost
                usage = data.get("usage", {})
                input_t = usage.get("input_tokens", 0)
                output_t = usage.get("output_tokens", 0)
                cost_usd = (input_t * 3.0 + output_t * 15.0) / 1_000_000
                await record_cost("anthropic", cost_usd, "awarebot_brief",
                                  f"executive summary in={input_t} out={output_t}")
            except Exception:
                pass  # Cost tracking should never break the primary flow

            return data["content"][0]["text"]
        except Exception as e:
            log.warning(f"[AGENT:BRIEF] LLM summary generation failed: {e}")
            # Fallback: simple text summary
            return (
                f"Intelligence brief: {len(top_signals)} significant signals detected. "
                f"Top sector: {sectors[0]['sector'] if sectors else 'unknown'}. "
                f"Highest-scoring signal: {top_signals[0].title[:80] if top_signals else 'none'}."
            )

    # ═══════════════════════════════════════════════════════════════════
    # PREDICTIONS (OBSERVE)
    # ═══════════════════════════════════════════════════════════════════

    async def generate_predictions(self, signals: Optional[list[Signal]] = None) -> dict[str, Any]:
        """
        Ensemble prediction on high-signal clusters.

        Groups signals by category/topic, identifies clusters with enough
        convergent signals, and runs the FuturePredictor ensemble.

        Args:
            signals: Optional signal list (defaults to prediction_buffer)

        Returns:
            Prediction results dict with topics, consensus, confidence
        """
        if not self.predictor:
            return {"status": "predictor_not_configured", "predictions": []}

        buffer = signals or list(self._prediction_buffer)
        if not buffer:
            return {"status": "no_signals", "predictions": []}

        self._stats["predictions_generated"] += 1
        self._stats["last_prediction_at"] = datetime.now(timezone.utc).isoformat()

        # Cluster signals by category
        clusters: dict[str, list[Signal]] = defaultdict(list)
        for s in buffer:
            category = s.category or "general"
            clusters[category].append(s)

        # Only predict on clusters with 3+ signals
        predictions = []
        for topic, cluster_signals in clusters.items():
            if len(cluster_signals) < 3:
                continue

            # Convert to InsightSignal for predictor compatibility
            insight_signals = self._signals_to_insight(cluster_signals)

            try:
                output: PredictionOutput = await self.predictor.predict(insight_signals, topic)
                pred_record = {
                    "prediction_id": output.prediction_id,
                    "topic": output.topic,
                    "consensus": output.consensus_prediction,
                    "confidence": output.confidence,
                    "component_count": len(output.component_predictions),
                    "convergence": output.convergence_signals,
                    "warnings": output.warnings,
                    "signal_count": len(cluster_signals),
                    "timestamp": output.timestamp.isoformat(),
                }
                predictions.append(pred_record)

                # ── Side effect 1: Memory storage ──────────────────
                if self.memory_store:
                    try:
                        await self.memory_store.create_unit(
                            content=(
                                f"Prediction on '{topic}': "
                                f"{output.consensus_prediction or 'inconclusive'}"
                            ),
                            source="awarebot:predictor",
                            importance=min(100.0, output.confidence * 100),
                            tags=["prediction", "autonomous", "ensemble", topic],
                        )
                    except Exception as mem_err:
                        log.warning(f"[AGENT:PREDICT] Memory storage failed: {mem_err}")

                # ── Side effect 2: Disk persistence ────────────────
                try:
                    pred_dir = self._data_dir / "predictions"
                    pred_dir.mkdir(parents=True, exist_ok=True)
                    pred_file = pred_dir / f"pred-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
                    pred_data = {
                        "topic": topic,
                        "consensus": output.consensus_prediction,
                        "confidence": output.confidence,
                        "convergence": output.convergence_signals if output.convergence_signals else [],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "signal_count": len(cluster_signals),
                    }
                    pred_file.write_text(json.dumps(pred_data, indent=2, default=str))
                except Exception as disk_err:
                    log.warning(f"[AGENT:PREDICT] Disk persistence failed: {disk_err}")

                # ── Side effect 3: Push notification for high-confidence ──
                if output.confidence >= 0.6 and self.push_callback:
                    try:
                        await self.push_callback({
                            "type": "prediction_alert",
                            "title": f"Prediction [{topic}]",
                            "consensus": output.consensus_prediction or "inconclusive",
                            "confidence": output.confidence,
                            "signal_count": len(cluster_signals),
                            "timestamp": output.timestamp.isoformat(),
                        })
                    except Exception:
                        pass  # Don't crash loop on push failure

                # ── Side effect 4: Council flagging for convergent predictions ──
                if output.convergence_signals and output.confidence >= 0.8:
                    try:
                        # Tag convergent prediction for council review
                        if self.memory_store:
                            await self.memory_store.create_unit(
                                content=(
                                    f"[COUNCIL FLAG] High-confidence convergent prediction on '{topic}': "
                                    f"{output.consensus_prediction or 'inconclusive'} "
                                    f"(confidence={output.confidence:.0%}, "
                                    f"convergence_signals={output.convergence_signals})"
                                ),
                                source="awarebot:predictor:council_flag",
                                importance=min(100.0, output.confidence * 100),
                                tags=["prediction", "convergent", "council_flagged", topic],
                            )
                        log.info(
                            f"[AGENT:PREDICT] Flagged convergent prediction for council: "
                            f"topic={topic}, confidence={output.confidence:.2f}"
                        )
                    except Exception as council_err:
                        log.warning(f"[AGENT:PREDICT] Council flagging failed: {council_err}")

            except Exception as e:
                log.warning(f"[AGENT:PREDICT] Prediction failed for topic '{topic}': {e}")

        # ── Side effect 5: Drain prediction buffer after successful generation ──
        if predictions and not signals:
            # Only drain when using the internal buffer (not a caller-provided list).
            # Use popleft() to preserve signals that arrived during prediction.
            drain_count = min(len(buffer), len(self._prediction_buffer))
            for _ in range(drain_count):
                try:
                    self._prediction_buffer.popleft()
                except IndexError:
                    break
            log.debug(f"[AGENT:PREDICT] Drained {drain_count} signals from prediction buffer")

        log.info(f"[AGENT:PREDICT] Generated {len(predictions)} predictions from {len(clusters)} clusters")

        return {
            "status": "completed",
            "predictions": predictions,
            "clusters_analyzed": len(clusters),
            "clusters_predicted": len(predictions),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ═══════════════════════════════════════════════════════════════════
    # JOURNAL INTEGRATION
    # ═══════════════════════════════════════════════════════════════════

    async def process_journal(self):
        """
        Pull journal entries into context, find patterns.

        Reads recent journal entries and cross-references with active
        signals to identify convergence between operator observations
        and automated intelligence.
        """
        if not self.journal_store:
            return

        try:
            # Get today's entries
            today = datetime.now(timezone.utc).date()
            entries = await self.journal_store.get_entries(date_from=today, date_to=today)

            if not entries:
                log.debug("[AGENT:JOURNAL] No journal entries for today")
                return

            # Extract themes from journal entries
            journal_themes: set[str] = set()
            for entry in entries:
                if hasattr(entry, "tags"):
                    journal_themes.update(entry.tags)
                if hasattr(entry, "content"):
                    # Simple keyword extraction
                    words = entry.content.lower().split()
                    journal_themes.update(w for w in words if len(w) > 5)

            # Cross-reference with signal context
            convergent_signals = []
            for signal in self._context_24h:
                signal_text = f"{signal.title} {signal.content}".lower()
                overlap = sum(1 for theme in journal_themes if theme in signal_text)
                if overlap >= 2:
                    convergent_signals.append(signal)

            if convergent_signals:
                log.info(
                    f"[AGENT:JOURNAL] Found {len(convergent_signals)} signals "
                    f"convergent with journal themes"
                )
                # Boost convergent signals
                for s in convergent_signals:
                    s.composite_score = min(1.0, s.composite_score * 1.1)
                    s.tags.append("journal_convergent")

        except Exception as e:
            log.warning(f"[AGENT:JOURNAL] Processing failed: {e}")

    # ═══════════════════════════════════════════════════════════════════
    # SCHEDULER (owns all timing)
    # ═══════════════════════════════════════════════════════════════════

    async def _scan_loop(self):
        """Periodic scan cycle with emergency stop check."""
        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[AGENT:SCAN] Emergency stop active — halting scan loop")
                break

            try:
                # PERCEIVE
                new_signals = await self.scan_cycle()

                # SCORE (REASON — deterministic pass)
                scored_signals = self.score_signals(new_signals)

                # REASON — LLM pass for the most ambiguous signals only
                # Sort ambiguous signals by proximity to the HIGH threshold (0.55)
                # to prioritize signals most likely to be promoted
                ambiguous = [s for s in scored_signals if is_ambiguous(s.composite_score)]
                ambiguous.sort(key=lambda s: abs(s.composite_score - THRESHOLD_HIGH))
                llm_budget = min(MAX_LLM_CALLS_PER_CYCLE, len(ambiguous))
                if len(ambiguous) > llm_budget:
                    log.info(
                        f"[AGENT:REASON] {len(ambiguous)} ambiguous signals, "
                        f"budget={llm_budget} — routing {len(ambiguous) - llm_budget} deterministically"
                    )
                for signal in ambiguous[:llm_budget]:
                    await self.reason_about_signal(signal)

                # ACT — route all signals
                for signal in scored_signals:
                    await self.route_signal(signal)

                self._stats["cycles_completed"] += 1

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"[AGENT:SCAN] Cycle error: {e}", exc_info=True)

            # Wait for next cycle
            await self._interruptible_sleep(self._scan_interval)

    async def _brief_loop(self):
        """Periodic brief generation.

        Initial-delay policy:
          - If warm-start populated >=20 signals in the 24h buffer, the brief
            can fire almost immediately (60s settling delay) — no need to
            wait the full 2h half-interval. This fixes the "brief never
            fires across rapid restarts" problem where the loop kept resetting
            its 2h sleep on every Brain restart.
          - Otherwise (cold start with empty buffer), keep the original
            half-interval delay so signals can accumulate from scan_cycle.
        """
        # Adaptive initial delay
        prewarmed = len(self._context_24h)
        if prewarmed >= 20:
            initial_delay = 60  # 1 minute settle
            log.info(
                f"[AGENT:BRIEF] Loop started — warm-start has {prewarmed} signals, "
                f"first brief in {initial_delay}s, then every {self._brief_interval}s"
            )
        else:
            initial_delay = self._brief_interval // 2
            log.info(
                f"[AGENT:BRIEF] Loop started — cold start ({prewarmed} signals), "
                f"first brief in {initial_delay}s, then every {self._brief_interval}s"
            )
        await self._interruptible_sleep(initial_delay)

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[AGENT:BRIEF] Emergency stop active — halting brief loop")
                break

            try:
                log.info(
                    f"[AGENT:BRIEF] Firing scheduled brief "
                    f"(context_24h={len(self._context_24h)} signals)"
                )
                await self.generate_brief()
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("[AGENT:BRIEF] Generation error — see traceback")

            await self._interruptible_sleep(self._brief_interval)

    async def _prediction_loop(self):
        """Periodic prediction generation."""
        # Initial delay
        await self._interruptible_sleep(self._prediction_interval // 2)

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[AGENT:PREDICT] Emergency stop active — halting prediction loop")
                break

            try:
                await self.generate_predictions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"[AGENT:PREDICT] Generation error: {e}", exc_info=True)

            await self._interruptible_sleep(self._prediction_interval)

    async def _context_loop(self):
        """Periodic context window maintenance."""
        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                break

            try:
                await self.update_context()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"[AGENT:CONTEXT] Update error: {e}", exc_info=True)

            await self._interruptible_sleep(self._context_interval)

    async def _journal_loop(self):
        """Periodic journal processing."""
        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                break

            try:
                await self.process_journal()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"[AGENT:JOURNAL] Processing error: {e}", exc_info=True)

            await self._interruptible_sleep(self._journal_interval)

    async def _ytc_loop(self):
        """YouTube Council run — scrape, transcribe, analyze, report.

        Runs every 12 hours. Scraper lookback is 72h so channels that post
        every 2-3 days still get caught. Dedup via previously-analyzed IDs
        prevents reprocessing.
        Initial delay of 10 minutes to let scan loops warm up first.
        """
        # Initial delay — let scan loops stabilize before heavy YTC work
        await self._interruptible_sleep(600)  # 10 min

        ytc_interval = 1800  # 30 minutes

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[AGENT:YTC] Emergency stop active — halting YTC loop")
                break

            try:
                session_id = f"ytc-auto-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
                log.info(f"[AGENT:YTC] Starting automatic YouTube Council run: {session_id}")

                from ..councils.runner import run_youtube_council
                report = await run_youtube_council(session_id)

                if report:
                    # Save rollup + per-video reports to youtube-reports/
                    ncl_base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
                    json_dir = ncl_base / "intelligence-scan" / "youtube-reports"
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(
                        None, lambda: json_dir.mkdir(parents=True, exist_ok=True)
                    )

                    # Save per-video reports if available
                    per_video = getattr(report, "_per_video_reports", [])
                    for vid_report in per_video:
                        vid_data = vid_report.to_dict()
                        vid_data.update({
                            "status": "complete",
                            "completed_at": datetime.now(timezone.utc).isoformat(),
                            "auto_triggered": True,
                            "report_type": "per_video",
                        })
                        vid_path = json_dir / f"{vid_report.session_id}.json"
                        vid_json = json.dumps(vid_data, default=str, indent=2)
                        async with aiofiles.open(vid_path, "w") as f:
                            await f.write(vid_json)

                    # Save rollup report
                    out_path = json_dir / f"{session_id}.json"
                    report_data = report.to_dict()
                    report_data.update({
                        "session_id": session_id,
                        "status": "complete",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "auto_triggered": True,
                        "report_type": "rollup",
                        "per_video_count": len(per_video),
                    })
                    report_json = json.dumps(report_data, default=str, indent=2)
                    async with aiofiles.open(out_path, "w") as f:
                        await f.write(report_json)

                    log.info(
                        f"[AGENT:YTC] Auto council run complete: {session_id} "
                        f"({len(per_video)} per-video + 1 rollup)"
                    )
                    self._stats["ytc_runs"] += 1
                else:
                    log.info(f"[AGENT:YTC] Auto council run produced no report: {session_id}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"[AGENT:YTC] Auto council run failed: {e}", exc_info=True)

            await self._interruptible_sleep(ytc_interval)

    async def _x_liked_loop(self):
        """Periodic X liked-video scan — fetch likes, download, transcribe, analyze.

        Runs every 6 hours. Only active when X_USER_ACCESS_TOKEN is set
        (requires OAuth 2.0 user authentication).
        Initial delay of 45 minutes.
        """
        liked_interval = 6 * 3600  # 6 hours
        await self._interruptible_sleep(2700)  # 45-minute initial delay

        while not self._shutdown_event.is_set():
            # Only run if OAuth token is available
            token = os.getenv("X_USER_ACCESS_TOKEN", "")
            if not token:
                # Try loading from saved tokens
                try:
                    from ..councils.xai.x_oauth import load_access_token
                    token = load_access_token()
                except Exception:
                    pass

            if not token:
                log.debug("[AGENT:X-LIKED] No X_USER_ACCESS_TOKEN — skipping liked-video scan")
                await self._interruptible_sleep(liked_interval)
                continue

            try:
                session_id = f"xliked-auto-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
                log.info(f"[AGENT:X-LIKED] Starting automatic liked-video scan: {session_id}")

                from ..councils.xai.liked_scanner import run_liked_video_scan
                reports = await run_liked_video_scan(session_id=session_id)

                if reports:
                    log.info(f"[AGENT:X-LIKED] Scan complete: {len(reports)} video reports")
                    self._stats["x_liked_scans"] = self._stats.get("x_liked_scans", 0) + 1
                else:
                    log.info(f"[AGENT:X-LIKED] Scan produced no new reports")

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"[AGENT:X-LIKED] Scan failed: {e}", exc_info=True)

            await self._interruptible_sleep(liked_interval)

    # ═══════════════════════════════════════════════════════════════════
    # INTERNAL UTILITIES
    # ═══════════════════════════════════════════════════════════════════

    def _deduplicate(self, signals: list[Signal]) -> list[Signal]:
        """
        Remove duplicate signals using rolling fingerprint window.

        Maintains a bounded set of seen fingerprints (last DEDUP_WINDOW_SIZE)
        for O(1) lookup. The deque auto-evicts oldest on append when full;
        we pre-evict the corresponding entry from the set to stay in sync.
        """
        unique = []
        for signal in signals:
            fp = signal.fingerprint()
            if fp not in self._seen_set:
                # If deque is full, the next append will silently drop the oldest.
                # Remove that oldest fingerprint from the set BEFORE appending.
                if len(self._seen_fingerprints) >= DEDUP_WINDOW_SIZE:
                    evicted = self._seen_fingerprints[0]  # will be dropped by append
                    self._seen_set.discard(evicted)

                self._seen_set.add(fp)
                self._seen_fingerprints.append(fp)
                unique.append(signal)

        return unique

    def _load_watch_queries(self) -> dict:
        """Load watch queries from config file.

        Returns dict with keys: x, youtube, reddit (lists of search strings)
        and reddit_subreddits (dict with tier1/tier2/tier3 sub lists).
        """
        # Try multiple paths
        candidates = [
            Path(getattr(self.config, "config_dir", "~/dev/NCL/config")).expanduser() / "watch_queries.json",
            Path("~/dev/NCL/runtime/autonomous/watch_queries.json").expanduser(),
            Path("~/dev/NCL/config/watch_queries.json").expanduser(),
        ]

        for path in candidates:
            if path.exists():
                try:
                    data = json.loads(path.read_text())
                    # Filter out _meta and _comment keys only
                    queries = {k: v for k, v in data.items() if not k.startswith("_")}
                    subs = queries.get("reddit_subreddits", {})
                    t1 = len(subs.get("tier1", []))
                    t2 = len(subs.get("tier2", []))
                    t3 = len(subs.get("tier3", []))
                    log.info(f"[AGENT] Loaded watch queries from {path} — subreddits T1={t1} T2={t2} T3={t3}")
                    return queries
                except Exception as e:
                    log.warning(f"[AGENT] Failed to load watch_queries from {path}: {e}")

        log.warning("[AGENT] No watch_queries.json found — using empty queries")
        return {"x": [], "youtube": [], "reddit": [], "reddit_subreddits": {}}

    def reload_watch_queries(self):
        """Hot-reload watch queries from disk without restarting."""
        self._watch_queries = self._load_watch_queries()
        query_count = sum(len(v) for v in self._watch_queries.values() if isinstance(v, list))
        log.info(f"[AGENT] Watch queries reloaded: {query_count} queries across {len(self._watch_queries)} sources")

    def _signals_to_intel(self, signals: list[Signal]) -> list[IntelSignal]:
        """Convert unified Signals to IntelSignal for correlator compatibility."""
        intel_signals = []
        for s in signals:
            try:
                source_type = SourceType(s.source) if s.source in [e.value for e in SourceType] else SourceType.NEWS
            except (ValueError, KeyError):
                source_type = SourceType.NEWS

            try:
                direction = SignalDirection(s.direction) if s.direction in [e.value for e in SignalDirection] else SignalDirection.NEUTRAL
            except (ValueError, KeyError):
                direction = SignalDirection.NEUTRAL

            intel_signals.append(IntelSignal(
                signal_id=s.signal_id,
                source=source_type,
                category=s.category,
                title=s.title,
                content=s.content[:500],
                direction=direction,
                value=s.volume,
                change_pct=s.change_pct,
                volume=s.volume,
                confidence=s.confidence,
                url=s.url,
                tags=s.tags,
                metadata=s.metadata,
                timestamp=s.timestamp,
            ))
        return intel_signals

    def _signals_to_insight(self, signals: list[Signal]) -> list[InsightSignal]:
        """Convert unified Signals to InsightSignal for predictor compatibility."""
        insight_signals = []
        for s in signals:
            insight_signals.append(InsightSignal(
                signal_id=s.signal_id,
                source_platform=s.source,
                content=s.content[:500],
                url=s.url,
                importance_score=s.composite_score * 100,
                relevance=s.relevance,
                novelty=s.novelty,
                actionability=s.actionability,
                source_authority=s.authority,
                time_sensitivity=min(1.0, s.composite_score),
                timestamp=s.timestamp,
                tags=s.tags,
            ))
        return insight_signals

    async def _persist_signal(self, signal: Signal):
        """Append signal to JSONL file for persistence."""
        try:
            line = json.dumps(signal.to_dict(), default=str) + "\n"
            async with aiofiles.open(self._signals_file, "a") as f:
                await f.write(line)
        except Exception as e:
            log.debug(f"[AGENT:PERSIST] Failed to write signal: {e}")

    async def _persist_brief(self, brief: dict[str, Any]):
        """Append brief to JSONL file."""
        try:
            briefs_file = self._data_dir / "intelligence" / "agent_briefs.jsonl"
            line = json.dumps(brief, default=str) + "\n"
            async with aiofiles.open(briefs_file, "a") as f:
                await f.write(line)
        except Exception as e:
            log.debug(f"[AGENT:PERSIST] Failed to write brief: {e}")

    async def _interruptible_sleep(self, seconds: float):
        """Sleep that can be interrupted by stop or emergency stop."""
        try:
            # Sleep in chunks so we can check emergency stop
            remaining = seconds
            chunk = min(5.0, seconds)
            while remaining > 0 and self._running and not EMERGENCY_STOP_EVENT.is_set():
                await asyncio.sleep(min(chunk, remaining))
                remaining -= chunk
        except asyncio.CancelledError:
            raise

    # ═══════════════════════════════════════════════════════════════════
    # PUBLIC API (for external callers / HTTP endpoints)
    # ═══════════════════════════════════════════════════════════════════

    async def on_demand_scan(self) -> dict[str, Any]:
        """Trigger an immediate scan cycle (for /scan_now endpoint)."""
        signals = await self.scan_cycle()
        scored = self.score_signals(signals)

        # Apply same LLM budget cap as _scan_loop to prevent runaway calls
        ambiguous = [s for s in scored if is_ambiguous(s.composite_score)]
        ambiguous.sort(key=lambda s: abs(s.composite_score - THRESHOLD_HIGH))
        llm_budget = min(MAX_LLM_CALLS_PER_CYCLE, len(ambiguous))
        if len(ambiguous) > llm_budget:
            log.info(
                f"[AGENT:ON_DEMAND] {len(ambiguous)} ambiguous, budget={llm_budget}"
            )
        for signal in ambiguous[:llm_budget]:
            await self.reason_about_signal(signal)

        for signal in scored:
            await self.route_signal(signal)

        return {
            "signals_collected": len(signals),
            "signals_scored": len(scored),
            "by_level": {
                "critical": sum(1 for s in scored if s.route_level == "CRITICAL"),
                "high": sum(1 for s in scored if s.route_level == "HIGH"),
                "medium": sum(1 for s in scored if s.route_level == "MEDIUM"),
                "low": sum(1 for s in scored if s.route_level == "LOW"),
            },
        }

    async def on_demand_brief(self, force_refresh: bool = False) -> dict[str, Any]:
        """Return the latest cached brief, or generate a new one if stale/missing.

        The brief tab in FirstStrike calls this — it should show the latest
        cached brief instantly instead of regenerating every time (which wastes
        LLM tokens and makes the user wait).

        A brief is considered "fresh" if it was generated within the last 4 hours.
        """
        if not force_refresh:
            # Try to return cached brief
            cached = await self._load_latest_brief()
            if cached:
                gen_at = cached.get("generated_at", "")
                if gen_at:
                    try:
                        gen_time = datetime.fromisoformat(gen_at.replace("Z", "+00:00"))
                        age_hours = (datetime.now(timezone.utc) - gen_time).total_seconds() / 3600
                        if age_hours < 4.0:
                            cached["cached"] = True
                            cached["age_hours"] = round(age_hours, 1)
                            return cached
                    except Exception:
                        pass

        # Generate fresh
        return await self.generate_brief()

    async def _load_latest_brief(self) -> dict[str, Any] | None:
        """Load the most recent brief from the JSONL file."""
        try:
            briefs_file = self._data_dir / "intelligence" / "agent_briefs.jsonl"
            if not briefs_file.exists():
                return None
            # Read last line (most recent brief)
            last_line = None
            async with aiofiles.open(briefs_file, "r") as f:
                async for line in f:
                    stripped = line.strip()
                    if stripped:
                        last_line = stripped
            if last_line:
                return json.loads(last_line)
        except Exception as e:
            log.debug(f"[AGENT:BRIEF] Failed to load cached brief: {e}")
        return None

    async def on_demand_predictions(self) -> dict[str, Any]:
        """Trigger immediate predictions."""
        return await self.generate_predictions()

    def get_source_health(self) -> dict[str, Any]:
        """Return health status for all sources."""
        health = {}
        for source in RATE_LIMITS:
            errors = self._stats["source_errors"].get(source, 0)
            signals = self._stats["signals_by_source"].get(source, 0)
            health[source] = {
                "signals_collected": signals,
                "errors": errors,
                "status": "healthy" if errors == 0 else (
                    "degraded" if errors < 5 else "failing"
                ),
            }

        # Add intel engine health if available
        if self.intelligence_engine:
            try:
                health["google_trends_detail"] = self.intelligence_engine._trends.health_status()
            except Exception:
                pass

        return health

    def get_prediction_accuracy(self) -> dict[str, Any]:
        """Return prediction accuracy stats."""
        if not self.predictor:
            return {"status": "predictor_not_configured"}
        return self.predictor.accuracy_stats()

    def record_prediction_outcome(self, prediction_id: str, correct: bool):
        """Record ground truth for a prediction."""
        if self.predictor:
            self.predictor.record_outcome(prediction_id, correct)
