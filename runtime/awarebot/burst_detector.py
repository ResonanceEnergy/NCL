"""
Kleinberg 2-state burst detection for Awarebot signal streams.

Implements the lightweight (k=2) variant of Kleinberg's automaton
("Bursty and Hierarchical Structure in Streams", KDD 2002) over signal
arrival times grouped by topic cluster. A topic is treated as a Poisson
process; we maintain a two-state finite automaton — BASE (λ0 baseline
arrival rate) and BURST (λ1 = burst_rate_multiplier × λ0). On each new
arrival we pick the state sequence that minimizes:

    sum( -ln(P(gap_i | λ_state_i)) ) + γ * (number of state transitions)

where γ is `transition_cost`. Higher γ → fewer/longer bursts (more
conservative). With only two states a full forward Viterbi pass is
O(N) per topic so we can run it cheaply on every ingest.

WHY THIS BEATS THE EXISTING "3+ FLAGGED SIGNALS" RULE
─────────────────────────────────────────────────────
Today `scheduler._council_auto_loop` triggers when the council_flags
JSONL has ≥3 entries. That is a *level* threshold and it misses two
classes of stories:

  1. Real bursts that don't quite hit 3 importance-≥75 flags but show
     a clear rate anomaly (e.g. 4 medium signals about the same ticker
     all landing within 8 minutes after a quiet 20-hour baseline).
  2. Slow-burn level-3 backlogs that are NOT bursts (3 unrelated
     signals stacked over 18 hours) and don't deserve a $0.30
     Sonnet+Grok+Gemini deliberation.

Replacing the level rule with a burst-onset rule catches "X just
happened" stories without arbitrary thresholds and saves council
budget on stale backlogs.

INTEGRATION (`runtime/autonomous/scheduler.py` — `_council_auto_loop`)
─────────────────────────────────────────────────────────────────────
Today:

    council_flags = await self._get_council_flags()
    if len(council_flags) >= self.council_min_signals:
        council_needed = True
        council_trigger = "accumulated_signals"
        ...

Replace with (or run in parallel for A/B):

    from runtime.awarebot.burst_detector import BurstDetector, BurstState

    # In __init__: self._burst_detector = BurstDetector(
    #     base_rate_window_hours=24.0,
    #     burst_rate_multiplier=3.0,
    #     min_burst_signals=5,
    #     transition_cost=1.0,
    # )

    # Feed every council flag in (cheap — O(1) per signal):
    for flag in council_flags:
        data = flag.get("data", {}) or {}
        topic = (data.get("tags") or ["misc"])[0]
        source = data.get("source") or flag.get("source") or "unknown"
        ts = datetime.fromisoformat(flag.get("timestamp"))
        self._burst_detector.feed(topic, ts, source)

    bursts = self._burst_detector.get_active_bursts()
    new_bursts = [b for b in bursts
                  if b.triggered_at >= self._last_burst_check]
    self._last_burst_check = now

    if new_bursts:
        council_needed = True
        council_trigger = f"burst:{new_bursts[0].topic}"
        b = new_bursts[0]
        council_prompt = (
            f"AUTONOMOUS COUNCIL — Kleinberg burst detected on '{b.topic}'. "
            f"{b.n_signals} signals across {len(b.sources_in_burst)} sources "
            f"in {(b.end_ts or b.start_ts) - b.start_ts:.0f}s "
            f"(intensity {b.burst_intensity:.2f}). "
            f"Analyze, assess implications, recommend actions."
        )
    elif len(council_flags) >= self.council_min_signals:
        # Keep the level rule as a safety net for slow-burn convergence.
        ...

ASSUMPTIONS / CAVEATS
─────────────────────
  * State is in-process and not persisted. A Brain restart loses
    baseline λ0 estimates — first hour after boot will be noisy and
    bursts may either over- or under-trigger. Acceptable given the
    scheduler restarts itself ~rarely outside deploys.
  * Topic grouping is the caller's responsibility — pass a single
    canonical tag, ticker, or cluster id. If you pass raw signal IDs
    every topic is a singleton and nothing ever bursts.
  * Per-topic state is capped at `max_topics` (default 5000) with LRU
    eviction so a long-running brain doesn't leak memory if every
    incoming signal coins a new tag.
"""

from __future__ import annotations

import logging
import math
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


logger = logging.getLogger(__name__)


class BurstState(Enum):
    """2-state Kleinberg automaton state."""

    BASE = 0  # Normal arrival rate (λ0)
    BURST = 1  # Elevated arrival rate (λ1 = multiplier × λ0)


@dataclass
class BurstEvent:
    """A contiguous run of arrivals classified as BURST.

    `end_ts` is None while the burst is still open. `burst_intensity` is
    the ratio of in-burst arrival rate over the baseline, normalised to
    [0,1] by `1 - exp(-(rate_ratio - 1) / multiplier)`. Useful for
    sorting which burst gets the council slot when several are open.
    """

    topic: str
    start_ts: float
    end_ts: float | None
    n_signals: int
    burst_intensity: float  # 0-1
    sources_in_burst: set[str] = field(default_factory=set)
    triggered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class _TopicState:
    """Per-topic rolling state — kept tiny so the LRU cap is honored."""

    state: BurstState = BurstState.BASE
    # Arrival timestamps as unix-epoch floats, oldest first.
    arrivals: deque = field(default_factory=lambda: deque(maxlen=512))
    # Sources seen in the *current* burst (or last burst if closed).
    sources_in_burst: set[str] = field(default_factory=set)
    # Open burst, if any.
    open_burst: BurstEvent | None = None
    # Last-completed burst (most recent), bounded to 1 to keep memory flat.
    last_closed_burst: BurstEvent | None = None


class BurstDetector:
    """Kleinberg 2-state burst automaton over per-topic signal streams.

    Thread-safe (sync `feed()` is called from both async loops and
    synchronous scanner callbacks). All public methods take a lock.
    """

    # Eviction cap on `_topics` to keep memory bounded.
    DEFAULT_MAX_TOPICS = 5_000
    # Window of "recent" completed bursts surfaced by stats().
    COMPLETED_WINDOW_SECONDS = 24 * 3600

    def __init__(
        self,
        base_rate_window_hours: float = 24.0,
        burst_rate_multiplier: float = 3.0,
        min_burst_signals: int = 5,
        transition_cost: float = 1.0,
        max_topics: int = DEFAULT_MAX_TOPICS,
        min_baseline_signals: int = 3,
    ):
        """Initialise.

        Args:
            base_rate_window_hours: How far back to estimate λ0 per topic.
                Older arrivals are ignored when computing the baseline.
            burst_rate_multiplier: λ1 = multiplier × λ0. Default 3×.
            min_burst_signals: Don't *report* a burst until at least
                this many arrivals have accumulated inside it (kills
                noise from two-signal coincidences). The automaton
                still tracks the state internally.
            transition_cost: γ in Kleinberg. Higher = more conservative
                state switches. 1.0 is a reasonable middle value.
            max_topics: LRU cap on per-topic state dicts.
            min_baseline_signals: We need at least this many historical
                arrivals before we can estimate λ0. Below that we stay
                in BASE no matter what.
        """
        if base_rate_window_hours <= 0:
            raise ValueError("base_rate_window_hours must be > 0")
        if burst_rate_multiplier <= 1.0:
            raise ValueError("burst_rate_multiplier must be > 1.0")

        self.base_rate_window_seconds = base_rate_window_hours * 3600.0
        self.burst_rate_multiplier = float(burst_rate_multiplier)
        self.min_burst_signals = int(min_burst_signals)
        self.transition_cost = float(transition_cost)
        self.max_topics = int(max_topics)
        self.min_baseline_signals = int(min_baseline_signals)

        # OrderedDict for O(1) LRU bookkeeping.
        self._topics: "OrderedDict[str, _TopicState]" = OrderedDict()
        self._closed_bursts: deque[BurstEvent] = deque(maxlen=1024)
        self._lock = threading.Lock()

    # ── Internal helpers (lock-free; callers hold _lock) ───────────
    def _ensure_topic(self, topic: str) -> _TopicState:
        ts = self._topics.get(topic)
        if ts is None:
            ts = _TopicState()
            self._topics[topic] = ts
            # Evict oldest if we overflowed.
            while len(self._topics) > self.max_topics:
                evicted_topic, evicted_state = self._topics.popitem(last=False)
                if evicted_state.open_burst is not None:
                    evicted_state.open_burst.end_ts = (
                        evicted_state.arrivals[-1]
                        if evicted_state.arrivals
                        else evicted_state.open_burst.start_ts
                    )
                    self._closed_bursts.append(evicted_state.open_burst)
        else:
            self._topics.move_to_end(topic)
        return ts

    def _estimate_baseline_rate(self, arrivals: deque, now_ts: float) -> float | None:
        """λ0 in arrivals-per-second from the last `window` seconds.

        Returns None when we don't have enough historical signal to
        trust the estimate.
        """
        if not arrivals:
            return None
        window_start = now_ts - self.base_rate_window_seconds
        recent = [t for t in arrivals if t >= window_start]
        if len(recent) < self.min_baseline_signals:
            return None
        # Time span of the window — use full window so the rate isn't
        # inflated by a short observation period right after boot.
        span = max(self.base_rate_window_seconds, recent[-1] - recent[0])
        # Floor to avoid div-by-zero in pathological "all timestamps
        # identical" cases.
        span = max(span, 1.0)
        return len(recent) / span

    def _viterbi_state(
        self,
        gaps: list[float],
        lambda0: float,
        lambda1: float,
        prior_state: BurstState,
    ) -> BurstState:
        """Pick the optimal current state for the last gap via 2-state
        Viterbi against the Kleinberg cost function.

        Cost of a gap g at rate λ:  -ln( λ exp(-λg) ) = -ln(λ) + λ·g
        Transition cost γ added when consecutive states differ.

        Returns just the current (final) state — that's all the public
        API needs. Full path reconstruction would be O(N) memory and
        we don't need it for the trigger decision.
        """
        if not gaps:
            return prior_state
        # Initialize DP with prior state (no transition cost for the
        # state we're already in).
        # Cost vector indexed by [BASE, BURST].
        prev_cost = [math.inf, math.inf]
        prev_cost[prior_state.value] = 0.0

        for g in gaps:
            g = max(g, 1e-6)  # avoid -ln(0) blowups
            # Emission costs at this gap for each state.
            emit = [
                -math.log(lambda0) + lambda0 * g,
                -math.log(lambda1) + lambda1 * g,
            ]
            new_cost = [math.inf, math.inf]
            for cur in (0, 1):
                best = math.inf
                for prev in (0, 1):
                    trans = 0.0 if prev == cur else self.transition_cost
                    c = prev_cost[prev] + trans + emit[cur]
                    if c < best:
                        best = c
                new_cost[cur] = best
            prev_cost = new_cost

        return BurstState.BURST if prev_cost[1] < prev_cost[0] else BurstState.BASE

    # ── Public API ─────────────────────────────────────────────────
    def feed(
        self,
        topic: str,
        timestamp: datetime,
        source: str,
    ) -> BurstState:
        """Ingest one arrival; return the topic's current state.

        Args:
            topic: Cluster key (tag, ticker, narrative id, ...). All
                arrivals sharing a topic share burst state.
            timestamp: Arrival time. Naive datetimes are interpreted as
                UTC.
            source: Source name (reddit, x, youtube, ...) — accumulated
                onto the open burst's `sources_in_burst` set so the
                council prompt can cite cross-source confirmation.
        """
        if not topic:
            return BurstState.BASE
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        ts = timestamp.timestamp()

        with self._lock:
            tstate = self._ensure_topic(topic)
            tstate.arrivals.append(ts)
            prior_state = tstate.state

            lambda0 = self._estimate_baseline_rate(tstate.arrivals, ts)
            if lambda0 is None or lambda0 <= 0:
                # Not enough data — clamp to BASE.
                tstate.state = BurstState.BASE
                return tstate.state

            lambda1 = lambda0 * self.burst_rate_multiplier
            # Build gap list from the most recent arrivals (up to the
            # last 64 — Viterbi cost is O(N) but we only need a short
            # tail for the current-state decision).
            tail = list(tstate.arrivals)[-64:]
            gaps = [tail[i] - tail[i - 1] for i in range(1, len(tail))]
            new_state = self._viterbi_state(gaps, lambda0, lambda1, prior_state)
            tstate.state = new_state

            # State machine: open/close BurstEvent objects.
            if new_state == BurstState.BURST and prior_state != BurstState.BURST:
                # Burst onset — open a new event.
                tstate.sources_in_burst = {source}
                rate_ratio = lambda1 / lambda0 if lambda0 > 0 else 1.0
                intensity = 1.0 - math.exp(-(rate_ratio - 1.0) / self.burst_rate_multiplier)
                tstate.open_burst = BurstEvent(
                    topic=topic,
                    start_ts=ts,
                    end_ts=None,
                    n_signals=1,
                    burst_intensity=max(0.0, min(1.0, intensity)),
                    sources_in_burst=set(tstate.sources_in_burst),
                    triggered_at=datetime.now(timezone.utc),
                )
            elif new_state == BurstState.BURST and tstate.open_burst is not None:
                # In-burst arrival — accumulate counters.
                tstate.open_burst.n_signals += 1
                tstate.sources_in_burst.add(source)
                tstate.open_burst.sources_in_burst = set(tstate.sources_in_burst)
            elif new_state == BurstState.BASE and prior_state == BurstState.BURST:
                # Burst over — close the event.
                if tstate.open_burst is not None:
                    tstate.open_burst.end_ts = ts
                    tstate.last_closed_burst = tstate.open_burst
                    self._closed_bursts.append(tstate.open_burst)
                tstate.open_burst = None
                tstate.sources_in_burst = set()

            return new_state

    def get_active_bursts(self) -> list[BurstEvent]:
        """All topics currently in BURST state, gated by min_burst_signals.

        Returned events are *live references* — callers should not
        mutate them. Sorted by intensity descending so the highest-rank
        burst is at index 0.
        """
        out: list[BurstEvent] = []
        with self._lock:
            for topic, tstate in self._topics.items():
                if tstate.state == BurstState.BURST and tstate.open_burst is not None:
                    if tstate.open_burst.n_signals >= self.min_burst_signals:
                        out.append(tstate.open_burst)
        out.sort(key=lambda b: b.burst_intensity, reverse=True)
        return out

    def stats(self) -> dict:
        """Lightweight snapshot for `/system/health/rollup`.

        Keys:
          topics_tracked       — count of distinct topics in state
          bursts_active        — current open bursts above min_burst_signals
          bursts_active_total  — current open bursts ignoring gate
          bursts_completed_24h — closed bursts in last 24h
        """
        with self._lock:
            now_ts = datetime.now(timezone.utc).timestamp()
            cutoff = now_ts - self.COMPLETED_WINDOW_SECONDS
            active_gated = 0
            active_total = 0
            for tstate in self._topics.values():
                if tstate.state == BurstState.BURST and tstate.open_burst is not None:
                    active_total += 1
                    if tstate.open_burst.n_signals >= self.min_burst_signals:
                        active_gated += 1
            completed_24h = sum(1 for b in self._closed_bursts if (b.end_ts or 0.0) >= cutoff)
            return {
                "topics_tracked": len(self._topics),
                "bursts_active": active_gated,
                "bursts_active_total": active_total,
                "bursts_completed_24h": completed_24h,
                "config": {
                    "base_rate_window_hours": self.base_rate_window_seconds / 3600.0,
                    "burst_rate_multiplier": self.burst_rate_multiplier,
                    "min_burst_signals": self.min_burst_signals,
                    "transition_cost": self.transition_cost,
                    "max_topics": self.max_topics,
                },
            }


__all__ = ["BurstState", "BurstEvent", "BurstDetector"]
