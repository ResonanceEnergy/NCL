"""
NCL Autonomous Scheduler
========================

Background task scheduler that makes NCL a true autonomous second brain.
Spawns 17 long-running asyncio tasks (as of 2026-05-21):

  1. Awarebot agent           — unified intel pipeline (replaces scanner,
                                 prediction, intel collection, brief loops)
  2. Council Auto-Spawn       — fires Delphi-MAD debates on signal convergence
                                 or scheduled 4hr strategic review
  3. Memory Consolidation     — decay + dedup + prune + KG maintenance
  4. Workspace Health         — MWP pipeline stage observability
  5. Mandate Purge            — hygiene against state-leak (max 1k mandates)
  6. Feedback Synthesis       — consumes pillar reports → synthesis notes
  7. Heartbeat                — 60s liveness JSONL + watchdog ntfy alerts
  8. Working Context          — 6am assemble / noon refresh / 11pm EOD
  9. Journal Reflection       — 10pm ET LLM daily synthesis
 10. Night Watch              — 2-5am ET 5-phase digital cortex maintenance
 11. Calendar Agent           — lunar/market/local-event correlation
 12. Calendar Alerts          — pushes critical/high alerts via ntfy
 13. Health Roll-up           — 60s aggregated component status to data/health
 14. Cost Rollover            — UTC-midnight cost ledger close + reset
 15. Cache Warmer             — 5m cold-start latency mitigation for cal+ctx
 16. Alert Dispatch           — rate-limited+deduped centralized ntfy pump
 17. YTC Dedicated            — hourly YouTube Council (split from Awarebot)

Plus a supervisor task that monitors and restarts crashed loops up to 3x.

REMOVED 2026-05-21:
  - _aac_sync_loop (pillar polling; folded into Night Watch health audit)

All intervals are configurable via ncl.yaml or environment variables.
"""

import asyncio
import contextlib
import fcntl
import json
import logging
import os
import time
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import aiofiles

from ..api.middleware.correlation import loop_request_id, set_request_id
from ..awarebot.agent import Awarebot
from ..governance.emergency_stop import EMERGENCY_STOP_EVENT
from ..health.rollup import build_health_rollup, write_rollup_atomic
from ..journal.reflection_engine import ReflectionEngine
from ..journal.store import JournalStore
from ..memory.retrieval import BM25Index
from ..memory.working_context import DailyContextWindow
from ..notifications import enqueue_alert, get_alert_dispatcher
from .signal_processor import SignalProcessor


log = logging.getLogger("ncl.autonomous")

# W10B-12 — once-per-hour rate-limit for swallowed-exception warnings on hot paths.
_log_warned_at: dict[str, float] = {}


def _warn_once_per_hour(key: str, msg: str, *args) -> None:
    """Emit log.warning at most once per 3600s per ``key``."""
    import time as _t

    now = _t.time()
    last = _log_warned_at.get(key, 0.0)
    if now - last >= 3600.0:
        _log_warned_at[key] = now
        log.warning(msg, *args)


def _json_safe(obj: Any) -> Any:
    """Fallback for json.dumps(default=...). Handles sets, datetimes, Pydantic, Path."""
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            pass
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    return str(obj)


class AutonomousScheduler:
    """
    Background task scheduler for NCL autonomous operations.

    Spawns asyncio tasks on startup that run indefinitely,
    performing intelligence gathering, prediction, and council
    deliberation without requiring pump prompts from NATRIX.
    """

    def __init__(
        self,
        brain,  # NCLBrain instance
        config,  # Settings instance
        councils_runner=None,  # councils.runner module (optional)
        intelligence_engine=None,  # IntelligenceEngine instance (optional)
        emergency_stop=None,  # EmergencyStop instance (optional)
    ):
        self.brain = brain
        self.config = config
        self.councils_runner = councils_runner
        self.intelligence_engine = intelligence_engine
        self.emergency_stop = emergency_stop  # EmergencyStop instance

        self.data_dir = Path(config.data_dir).expanduser()
        self.signals_dir = self.data_dir / "autonomous_signals"
        self.signals_dir.mkdir(parents=True, exist_ok=True)

        # State tracking
        self._tasks: list[asyncio.Task] = []
        # _stop_event must be created before the _running property is accessed.
        # Starts as "set" (stopped state); start() clears it.
        self._stop_event: asyncio.Event = asyncio.Event()
        self._stop_event.set()  # initially stopped
        self._stats = {
            "scans_completed": 0,
            "predictions_run": 0,
            "councils_auto_spawned": 0,
            "memory_consolidations": 0,
            "high_signals_detected": 0,
            "started_at": None,
            "last_scan": None,
            "last_prediction": None,
            "last_council": None,
            "last_consolidation": None,
            "intel_briefs_generated": 0,
            "intel_collections_run": 0,
            "intel_alerts_pushed": 0,
            "last_intel_brief": None,
            "last_intel_collection": None,
            # ── Heartbeat / watchdog state ────────────────────────
            "last_heartbeat_at": None,
            "heartbeat_count": 0,
            "stale_loops": [],  # list of {loop, last_fire_at, age_s, threshold_s}
            # ── 2026-05-21 new loops ─────────────────────────────
            "last_health_rollup": None,
            "health_rollups_written": 0,
            "last_cost_rollover": None,
            "cost_rollovers_count": 0,
            "last_cache_warm": None,
            "cache_warms_count": 0,
            "last_alert_dispatch_tick": None,
            "last_ytc_dedicated": None,
            "ytc_dedicated_runs": 0,
            # ── Night Watch run tracking (added 2026-05-21) ──────
            # Drives startup-catchup decision in _night_watch_loop.
            # Persisted as ISO timestamps; restart loses these but the
            # loop also falls back to data/night-watch/ mtime scan.
            "last_night_watch": None,
            "last_night_watch_full": None,
            "last_night_watch_catchup": None,
            "night_watch_full_runs": 0,
            "night_watch_catchup_runs": 0,
        }

        # Heartbeat watchdog config — alert dedup + last alert-fired tracking
        self._heartbeat_alert_sent: dict[str, str] = {}  # loop_name -> ISO date last alerted
        self._heartbeat_dir = self.data_dir / "heartbeat"
        self._heartbeat_dir.mkdir(parents=True, exist_ok=True)
        # W8-A2 D8 (2026-05-24): monotonic timestamp updated on every
        # heartbeat tick; the stall-dumper watchdog reads this and panics
        # if the gap exceeds STALL_THRESHOLD_S (event loop is frozen).
        self._last_heartbeat_mono: float = 0.0
        self._stall_dump_dir = self.data_dir / "logs" / "stall-dumps"
        self._stall_dump_dir.mkdir(parents=True, exist_ok=True)
        self._last_stall_dump_at: float = 0.0  # monotonic, for dedup
        # W10B-10 (2026-05-24): stall-watchdog deadband for known-long awaits.
        # Loops in this set are permitted a relaxed threshold (300s) when any
        # of them have been actively marked via mark_long_running()/the
        # long_running_ctx() helper. Everything else still trips at 90s.
        self._long_running_tags: set[str] = {
            "ncl-ytc-dedicated",
            "ncl-ytc-nightshift",
            "ncl-night-watch",
            "ncl-memory-eval",
            "ncl-stocks-scan",
            "ncl-city-events",
        }
        # Reference-counted: same tag can be re-entered (e.g. nested phases).
        self._active_long_running: dict[str, int] = {}

        # Latest health rollup (overwritten by _health_rollup_loop each minute).
        # Persisted to data/health/current.json, but also kept in memory so
        # /system/health/rollup can answer in O(1) without a disk read.
        self._latest_health_rollup: Optional[dict] = None

        # Signal buffer — bounded deque to prevent unbounded accumulation
        # Capped at 1000 entries; oldest signals are dropped automatically
        self._signal_buffer: deque[dict] = deque(maxlen=1000)
        self._signal_lock = asyncio.Lock()
        self._last_collected_signals: list | None = None  # Cached for brief loop (C3 fix)
        self._working_context = None  # Initialized eagerly in start()
        self._journal_store: Optional[JournalStore] = None  # Initialized in start()
        self._reflection_engine = None

        # Supervisor state
        self._restart_counts: dict[str, int] = defaultdict(int)
        self._supervisor_task: Optional[asyncio.Task] = None
        # One-shot tasks — fire-once-and-exit. The supervisor must NOT log
        # WARNING+ERROR for these every 30s after they complete cleanly.
        # Added 2026-05-24 to fix supervisor noise on `ncl-startup-migrations`,
        # which was emitting ~2,880 log lines/day post-completion.
        self._one_shot_tasks: set[str] = {"ncl-startup-migrations"}
        # Names already logged as cleanly-completed so we log INFO once, not per cycle.
        self._one_shot_completed_logged: set[str] = set()

        # Council trigger threshold (importance score 0-100)
        self.council_trigger_threshold = 75.0
        # Minimum signals needed before auto-spawning a council
        self.council_min_signals = 3

        # Unified Signal Processor — central routing hub for all loops
        self.signal_processor = SignalProcessor(
            memory_store=brain.memory_store,
            working_context=None,  # Set in start() before tasks spawn
            signal_buffer=self._signal_buffer,
            signal_lock=self._signal_lock,
            data_dir=self.data_dir,
        )

        # ── Unified Awarebot Agent ─────────────────────────────────────
        # Awarebot runs its own event loop, handling all intelligence
        # scanning, predictions, briefs, and collection in one agent.
        self.awarebot: Optional[Awarebot] = None

    @property
    def _running(self) -> bool:
        """Derived from _stop_event for backward compat — True when NOT stopped."""
        return not self._stop_event.is_set()

    async def start(self) -> None:
        """Start all autonomous background loops."""
        if not self._stop_event.is_set() and self._tasks:
            log.warning("Autonomous scheduler already running")
            return

        self._stop_event.clear()
        self._stats["started_at"] = datetime.now(timezone.utc).isoformat()

        log.info("=" * 60)
        log.info("NCL AUTONOMOUS SCHEDULER — STARTING")
        log.info("=" * 60)
        log.info(
            f"  Scanner intervals: X={self.config.x_scan_interval}s, "
            f"YT={self.config.youtube_scan_interval}s"
        )
        log.info(f"  Prediction interval: {self.config.prediction_interval}s")
        log.info(f"  Memory consolidation: {self.config.memory_consolidation_interval}s")
        log.info(f"  Council trigger threshold: {self.council_trigger_threshold}")
        if self.intelligence_engine:
            log.info(f"  Intel brief interval: {self.config.intelligence_brief_interval}s")
            log.info(
                f"  Intel collection interval: {self.config.intelligence_collection_interval}s"
            )
        log.info("  Working context: 6am assembly, noon refresh, 11pm EOD")
        log.info("  Journal reflection: 10pm ET daily")
        log.info("=" * 60)

        # ── Initialize Working Context Window (eager) ────────────────
        # Must be created before Awarebot/JournalStore so they can
        # reference it immediately.  Eliminates the 30-second 503 window
        # that occurred when DailyContextWindow lived in the background loop.
        try:
            self._working_context = DailyContextWindow(
                data_dir=self.data_dir,
                memory_store=self.brain.memory_store,
            )
            self.signal_processor.working_context = self._working_context
            log.info("  Working context window: INITIALIZED (eager)")
        except Exception as e:
            log.error(f"  Working context window: FAILED to initialize: {e}", exc_info=True)
            # _working_context stays None; endpoints will 503 but scheduler won't crash

        # ── Initialize Awarebot Agent ─────────────────────────────────
        # Awarebot unifies: scanner, collectors, signal processor,
        # predictions, briefs, context management, journal processing.
        try:
            self.awarebot = Awarebot(
                config=self.config,
                scanner=getattr(self.brain, "scanner", None),
                predictor=getattr(self.brain, "predictor", None),
                intelligence_engine=self.intelligence_engine,
                memory_store=self.brain.memory_store if self.brain else None,
                working_context=self._working_context,
                journal_store=None,  # Set below after JournalStore init
                # YTC moved to scheduler-level ncl-ytc-dedicated loop (2026-05-21)
                # so it has its own cost cap and doesn't block the 30-min scan cycle.
                disable_internal_ytc=True,
            )
            log.info("  Awarebot agent: ACTIVE (unified intelligence pipeline)")
        except Exception as e:
            log.error(f"  Awarebot agent: FAILED to initialize: {e}")
            self.awarebot = None

        # ── Initialize Calendar Agent ─────────────────────────────────
        # Calendar agent runs lunar/market/local-event correlation and
        # emits critical alerts (Kp>=7, CME, prediction-due-today).
        try:
            from ..calendar.calendar_agent import get_calendar_agent

            self.calendar_agent = get_calendar_agent()
            log.info("[SCHEDULER] Calendar agent loaded")
        except Exception as e:
            self.calendar_agent = None
            log.warning("[SCHEDULER] Calendar agent unavailable: %s", e)

        # Dedup set for critical-alert push notifications
        self._pushed_calendar_alerts: set[str] = set()

        # Journal system
        try:
            self._journal_store = JournalStore(
                data_dir=str(self.data_dir),
                memory_store=self.brain.memory_store if self.brain else None,
                working_context=self._working_context,
            )
            # Inline Anthropic Haiku client so the autonomous reflection loop
            # generates real LLM synthesis (not template fallback) when
            # ANTHROPIC_API_KEY is set. Mirrors the client wired in
            # routes.lifespan for the manual /journal/reflect endpoint.
            _anth_key = os.environ.get("ANTHROPIC_API_KEY", "")
            _llm_client = None
            if _anth_key:

                class _AnthropicReflectionClient:
                    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
                        self.api_key = api_key
                        self.model = model

                    async def generate(self, prompt: str, system: str = "") -> str:
                        import httpx

                        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                            resp = await client.post(
                                "https://api.anthropic.com/v1/messages",
                                headers={
                                    "x-api-key": self.api_key,
                                    "anthropic-version": "2023-06-01",
                                    "content-type": "application/json",
                                },
                                json={
                                    "model": self.model,
                                    "max_tokens": 1200,
                                    "system": system
                                    or "You are a journaling synthesis assistant. Return valid JSON only.",  # noqa: E501
                                    "messages": [{"role": "user", "content": prompt}],
                                },
                            )
                            resp.raise_for_status()
                            data = resp.json()
                            try:
                                from ..cost_tracker import record_cost

                                usage = data.get("usage", {}) or {}
                                cost = (
                                    usage.get("input_tokens", 0) * 0.80
                                    + usage.get("output_tokens", 0) * 4.00
                                ) / 1_000_000
                                if cost > 0:
                                    await record_cost("anthropic", cost, "journal_reflection")
                            except Exception:
                                pass
                            return data["content"][0]["text"]

                _llm_client = _AnthropicReflectionClient(_anth_key)
                log.info("  Journal reflection LLM: Claude 3.5 Haiku")
            else:
                log.warning(
                    "  Journal reflection LLM: NONE (template fallback) — set ANTHROPIC_API_KEY"
                )
            self._reflection_engine = ReflectionEngine(self._journal_store, llm_client=_llm_client)
            # Wire journal store into Awarebot for cross-referencing
            if self.awarebot:
                self.awarebot.journal_store = self._journal_store
            log.info("  Journal reflection loop: 10pm ET daily")
        except ImportError:
            log.warning("Journal module not available — reflection loop disabled")

        # Spawn background tasks
        self._tasks = [
            asyncio.create_task(self._council_auto_loop(), name="ncl-council-auto"),
            asyncio.create_task(self._memory_consolidation_loop(), name="ncl-memory"),
            asyncio.create_task(self._workspace_health_loop(), name="ncl-workspace"),
            asyncio.create_task(self._mandate_purge_loop(), name="ncl-mandate-purge"),
            asyncio.create_task(self._feedback_synthesis_loop(), name="ncl-feedback-synth"),
            asyncio.create_task(self._heartbeat_loop(), name="ncl-heartbeat"),
            # W8-A2 D8 (2026-05-24): event-loop stall detector. Runs as a
            # peer task so a frozen heartbeat (issue #91 class) is caught
            # by an independent watchdog rather than waiting for the
            # heartbeat itself to recover.
            asyncio.create_task(self._stall_watchdog_loop(), name="ncl-stall-watchdog"),
            asyncio.create_task(self._working_context_loop(), name="ncl-working-ctx"),
        ]

        # Awarebot runs its own event loop (replaces scanner, intel, brief, prediction loops)
        if self.awarebot:
            self._tasks.append(asyncio.create_task(self.awarebot.run(), name="ncl-awarebot-agent"))

        # Calendar agent — class-based with .run() (same pattern as Awarebot)
        if self.calendar_agent:
            self._tasks.append(
                asyncio.create_task(self.calendar_agent.run(), name="ncl-calendar-agent")
            )
            self._tasks.append(
                asyncio.create_task(self._calendar_alert_check_loop(), name="ncl-calendar-alerts")
            )

        # Journal reflection task (needs _journal_store to exist)
        if self._journal_store and self._reflection_engine:
            self._tasks.append(
                asyncio.create_task(self._journal_reflection_loop(), name="ncl-journal-reflection")
            )

        # Night Watch — nightly 2am ET health audit
        self._tasks.append(asyncio.create_task(self._night_watch_loop(), name="ncl-night-watch"))

        # ── New autonomous loops (2026-05-21) ─────────────────────────
        # Loop 1: 60s rolled-up component status → data/health/current.json
        self._tasks.append(
            asyncio.create_task(self._health_rollup_loop(), name="ncl-health-rollup")
        )
        # Loop 2: UTC-midnight cost ledger close + counter reset
        self._tasks.append(
            asyncio.create_task(self._cost_rollover_loop(), name="ncl-cost-rollover")
        )
        # Loop 3: warm calendar + working-context caches every 5 min
        self._tasks.append(asyncio.create_task(self._cache_warmer_loop(), name="ncl-cache-warmer"))
        # Loop 4: centralized rate-limited ntfy dispatcher
        self._tasks.append(
            asyncio.create_task(self._alert_dispatch_loop(), name="ncl-alert-dispatch")
        )
        # Loop 5: dedicated YouTube Council — split from Awarebot, own budget
        self._tasks.append(
            asyncio.create_task(self._ytc_dedicated_loop(), name="ncl-ytc-dedicated")
        )
        # Loop 5b (W11-1, 2026-05-24): YTC nightshift — synthesizes one daily
        # rollup from prior-day per-video reports at 3am local. Companion to
        # the hourly per-video-only ``ncl-ytc-dedicated`` loop.
        self._tasks.append(
            asyncio.create_task(self._ytc_nightshift_loop(), name="ncl-ytc-nightshift")
        )
        # Loop 6: BM25 keyword index rebuild — backs FusedRetriever (Loop 11)
        self._tasks.append(asyncio.create_task(self._bm25_rebuild_loop(), name="ncl-bm25-rebuild"))
        # Wave 14X-Y Phase 1B-3 (2026-05-29): cross-reference promotion engine.
        # Every 5min, scans AWAREBOT signal stream for ticker / theme /
        # news+trends convergences and writes promoted candidates to
        # data/cross_reference/promotions.jsonl for TRADERAGENT pickup.
        self._tasks.append(
            asyncio.create_task(self._cross_reference_loop(), name="ncl-cross-reference")
        )
        # Wave 14X-Y Phase 2 (2026-05-29): Afternoon Debrief — fires daily
        # at 16:30 local, the post-close counterpart to the 05:30 ET
        # morning Brief Pro. Closes today's trading loop with a structured
        # reflection + seeds tonight's Night Watch focus.
        self._tasks.append(
            asyncio.create_task(self._afternoon_debrief_loop(), name="ncl-afternoon-debrief")
        )
        # Loop 7 (2026-05-22): per-city "fun finder" scanner — 1h cadence
        self._tasks.append(asyncio.create_task(self._city_events_loop(), name="ncl-city-events"))
        # Loop 8 (2026-05-22 EOD): stock scanner agent — GOAT + BRAVO every 4h
        # during NYSE hours. Persists hits, enqueues to memory, market-hours gated.
        self._tasks.append(asyncio.create_task(self._stocks_scan_loop(), name="ncl-stocks-scan"))

        # ── 2026-05-22 second batch: async writer, budget telemetry ──
        # Async write queue (Mem0 pattern) — fire-and-forget Awarebot writes
        try:
            from ..memory.async_writer import init_async_writer

            self._async_writer = init_async_writer(self.brain.memory_store)

            # Wrap .start() in a long-running supervisor so the task doesn't
            # complete immediately (start() spawns drainers and returns).
            async def _async_writer_supervisor():
                await self._async_writer.start()
                # Block forever while drainers run in the background.
                while self._running and not EMERGENCY_STOP_EVENT.is_set():
                    await asyncio.sleep(30)
                    # Periodically report queue health into stats
                    try:
                        s = self._async_writer.get_stats()
                        self._stats["last_async_writer_tick"] = datetime.now(
                            timezone.utc
                        ).isoformat()
                        self._stats["async_writer_queue_size"] = s.get("queue_size", 0)
                        self._stats["async_writer_drained"] = s.get("drained_total", 0)
                        self._stats["async_writer_dlq_size"] = s.get("dlq_size", 0)
                    except Exception as _stat_err:
                        _warn_once_per_hour(
                            "async_writer_stat_capture",
                            "[SCHEDULER] async-writer stat capture swallowed: %s",
                            _stat_err,
                        )

            self._async_writer_supervisor = _async_writer_supervisor
            self._tasks.append(
                asyncio.create_task(_async_writer_supervisor(), name="ncl-async-writer")
            )
        except Exception as e:
            log.warning(f"[SCHEDULER] async-writer disabled: {e}")
            self._async_writer = None

        # Memory budget telemetry — per-tier token spend, 15m rollup + ntfy.
        # Body carved out 2026-05-24 (W8-A13) to runtime/autonomous/loops/memory_budget.py.
        # Kept the closure shape so `_task_factories["ncl-memory-budget"]` below stays
        # a zero-arg coroutine factory (supervisor restarts call it with no args).
        try:
            from .loops.memory_budget import run as _memory_budget_run

            async def _memory_budget_loop():
                await _memory_budget_run(self)

            self._memory_budget_loop = _memory_budget_loop
            self._tasks.append(asyncio.create_task(_memory_budget_loop(), name="ncl-memory-budget"))
        except Exception as e:
            log.warning(f"[SCHEDULER] memory-budget loop disabled: {e}")

        # ── 2026-05-22 Memory Loops (Loops 2/4/5/6/9 from the memory swarm) ──
        # Loop 2: weekly memory eval harness (Sunday 3am ET internal gate)
        try:
            from ..memory.eval.loop import _memory_eval_loop

            self._tasks.append(
                asyncio.create_task(_memory_eval_loop(self.brain), name="ncl-memory-eval")
            )
        except Exception as e:
            log.warning(f"[SCHEDULER] memory-eval loop disabled: {e}")

        # Loop 4: ChromaDB garbage collection (hourly purge of ghost embeddings)
        try:
            from ..memory.chroma_gc import _chroma_gc_loop

            async def _chroma_gc_wrapper():
                await _chroma_gc_loop(
                    self.brain,
                    interval=3600,
                    threshold=50,
                    is_running=lambda: self._running,
                    emergency_stop=EMERGENCY_STOP_EVENT,
                    stats_dict=self._stats,
                )

            self._chroma_gc_wrapper = _chroma_gc_wrapper
            self._tasks.append(asyncio.create_task(_chroma_gc_wrapper(), name="ncl-chroma-gc"))
        except Exception as e:
            log.warning(f"[SCHEDULER] chroma-gc loop disabled: {e}")

        # Loop 5: conflict arbitration — adaptive cadence (5m burst / 10m
        # busy / 15m calm). Audit 2026-05-22 bumped per-cycle cap 5 -> 50
        # and added a quality filter (importance_divergence > 40 AND
        # >=3 shared entities) so we don't drown council in low-signal
        # contradictions.
        try:
            from ..memory.conflict_resolver import (
                BACKLOG_BURST,
                BACKLOG_BUSY,
                CADENCE_BURST_S,
                CADENCE_BUSY_S,
                CADENCE_CALM_S,
                ConflictResolver,
                run_conflict_arbitration_cycle,
            )

            self._conflict_resolver = ConflictResolver(
                self.brain.memory_store,
                knowledge_graph=getattr(self.brain, "knowledge_graph", None),
            )

            async def _conflict_arb_loop():
                cadence = CADENCE_CALM_S
                while self._running and not EMERGENCY_STOP_EVENT.is_set():
                    # W10B-7: fresh per-cycle correlation id.
                    set_request_id(loop_request_id("loop-confarb"))
                    try:
                        summary = await run_conflict_arbitration_cycle(
                            self.brain,
                            self._stats,
                        )
                        # Pick the next cadence from the backlog the cycle
                        # just reported. Burst when we're catching up.
                        backlog = (summary or {}).get("backlog", 0)
                        if backlog > BACKLOG_BURST:
                            cadence = CADENCE_BURST_S
                        elif backlog > BACKLOG_BUSY:
                            cadence = CADENCE_BUSY_S
                        else:
                            cadence = CADENCE_CALM_S
                        self._stats["conflict_arb_cadence_s"] = cadence
                        self._stats["conflict_arb_backlog"] = backlog
                    except Exception as e:
                        log.exception(f"[CONFLICT-ARB] cycle failed: {e}")
                    await asyncio.sleep(cadence)

            self._conflict_arb_loop = _conflict_arb_loop
            self._tasks.append(asyncio.create_task(_conflict_arb_loop(), name="ncl-conflict-arb"))
        except Exception as e:
            log.warning(f"[SCHEDULER] conflict-arb loop disabled: {e}")

        # Loop 6: staleness detector (6h — re-verify high-importance facts)
        try:
            from ..memory.staleness_detector import StalenessDetector, staleness_detector_loop

            self._staleness_detector = StalenessDetector(
                self.brain.memory_store,
                awarebot=self.awarebot,
            )
            self._tasks.append(
                asyncio.create_task(
                    staleness_detector_loop(self, self._staleness_detector),
                    name="ncl-staleness",
                )
            )
        except Exception as e:
            log.warning(f"[SCHEDULER] staleness loop disabled: {e}")

        # Loop 9: narrative threading (6h — link episodes across sessions)
        try:
            # Bind as bound method on this instance
            import types

            from ..memory.narrative_threads import _narrative_thread_loop

            self._narrative_thread_loop = types.MethodType(_narrative_thread_loop, self)
            self._tasks.append(
                asyncio.create_task(self._narrative_thread_loop(), name="ncl-narrative-threads")
            )
        except Exception as e:
            log.warning(f"[SCHEDULER] narrative-threads loop disabled: {e}")

        # CLAUDE.md refresh loop — 24h cadence. Keeps system-doc-derived
        # memory units fresh so the eval harness can find facts like
        # "why is X disabled". Idempotent via content_hash dedupe.
        try:
            from ..memory.claude_md_bootstrap import claude_md_refresh_loop

            self._claude_md_refresh_loop = lambda: claude_md_refresh_loop(self.brain)
            self._tasks.append(
                asyncio.create_task(
                    self._claude_md_refresh_loop(),
                    name="ncl-claude-md-refresh",
                )
            )
        except Exception as e:
            log.warning(f"[SCHEDULER] claude-md-refresh loop disabled: {e}")

        # Loop 10: sliding-window dedup scan (6h — replaces Night Watch M1)
        # Previously M1 walked the entire 9.7K-unit store in-line inside the
        # nightly cycle; the comparator double-counted pairs and timed out at
        # 30 minutes, blowing the entire Night Watch budget. Now lives in its
        # own loop with a 500-unit sliding window and a 200-merge cap.
        self._tasks.append(asyncio.create_task(self._dedup_scan_loop(), name="ncl-dedup-scan"))

        # ── Haiku A/B monitor (24h cadence — writes daily summary if A/B on) ──
        # Hoisted to runtime/autonomous/loops/haiku_ab_monitor.py (W10A-11)
        # mirroring the W8-A13 pattern. Keep the bound-method name so the
        # supervisor's task_factories registration below still resolves.
        from .loops.haiku_ab_monitor import run as _haiku_ab_monitor_run

        async def _haiku_ab_monitor_loop():
            await _haiku_ab_monitor_run(self)

        self._haiku_ab_monitor_loop = _haiku_ab_monitor_loop
        self._tasks.append(
            asyncio.create_task(_haiku_ab_monitor_loop(), name="ncl-haiku-ab-monitor")
        )

        # ── SQLite burn-in verifier (6h cadence) ───────────────────────────
        # Hoisted to runtime/autonomous/loops/sqlite_burnin.py (W10A-11)
        # mirroring the W8-A13 pattern. Keep the bound-method name so the
        # supervisor's task_factories registration below still resolves.
        from .loops.sqlite_burnin import run as _sqlite_burnin_run

        async def _sqlite_burnin_verify_loop():
            await _sqlite_burnin_run(self)

        self._sqlite_burnin_verify_loop = _sqlite_burnin_verify_loop
        self._tasks.append(
            asyncio.create_task(_sqlite_burnin_verify_loop(), name="ncl-sqlite-burnin-verify")
        )

        # ── Startup migrations (one-shot, idempotent, fire after first heartbeat) ──
        # Hoisted to runtime/autonomous/loops/startup_migrations.py (W10A-11)
        # mirroring the W8-A13 pattern. One-shot — clean exit is terminal,
        # supervisor does not restart it.
        from .loops.startup_migrations import run as _startup_migrations_run

        async def _startup_migrations():
            await _startup_migrations_run(self)

        self._tasks.append(
            asyncio.create_task(_startup_migrations(), name="ncl-startup-migrations")
        )

        # ── Morning Quiz scheduler (Wave 14E followup) ──
        # 00:05 ET — write tomorrow's template (carries forward posture + research_q)
        # 06:00 ET — ntfy nudge if quiz not yet submitted
        # 12:00 ET — second-chance nudge if still empty
        from .loops.morning_quiz_scheduler import run as _morning_quiz_run

        async def _morning_quiz():
            await _morning_quiz_run(self)

        self._tasks.append(
            asyncio.create_task(_morning_quiz(), name="ncl-morning-quiz")
        )

        # ── Ops monitor (Wave 14G — desktop) ──
        # 5s sampler writing into a 60-min ring buffer, fed via
        # /system/ops/{snapshot,history,stream}. Powers the menu-bar app
        # + OpsView window. Per docs/DESKTOP_OPTIONS_2026-05-25.md.
        from ..system_monitor.sampler import run as _ops_monitor_run

        async def _ops_monitor():
            await _ops_monitor_run(self)

        self._tasks.append(
            asyncio.create_task(_ops_monitor(), name="ncl-ops-monitor")
        )

        # ── Morning Brief Pro (Wave 14H) ──
        # 02:30 ET — ncl-brief-prep:    collect overnight data into pack
        # 05:00 ET — ncl-brief-council: 4-LLM panel (macro / pulse / flow /
        #                               technical) + chair synthesis
        # 05:30 ET — ncl-brief-render:  presentation + market open plan
        # Falls back to Phase 14D pipeline if any stage errors.
        from .loops.brief_pro_scheduler import (
            brief_prep_loop, brief_council_loop, brief_render_loop,
        )

        # P25 (2026-05-26): attribute is self.brain (set at __init__), NOT
        # self._brain. The underscore form raises AttributeError at task
        # start, the loop dies, and the supervisor can't restart because
        # these names weren't in _task_factories either. Both halves of
        # the bug fixed below — closures use self.brain and the names get
        # registered in _task_factories down at line ~789.
        async def _brief_prep():
            await brief_prep_loop(self.brain)

        async def _brief_council():
            await brief_council_loop(self.brain)

        async def _brief_render():
            await brief_render_loop(self.brain)

        self._tasks.append(asyncio.create_task(_brief_prep(), name="ncl-brief-prep"))
        self._tasks.append(asyncio.create_task(_brief_council(), name="ncl-brief-council"))
        self._tasks.append(asyncio.create_task(_brief_render(), name="ncl-brief-render"))

        # ── Wave 14J J0c — global drawdown bucket (60s) ──────────────
        # Single source of truth read by all autonomous loops + scanners
        # + brief pipeline + paper trading BEFORE proposing new sizing.
        # See runtime/portfolio/drawdown_bucket.py.
        from ..portfolio.drawdown_bucket import drawdown_bucket_loop

        async def _drawdown_bucket():
            await drawdown_bucket_loop(self.brain)

        self._tasks.append(
            asyncio.create_task(_drawdown_bucket(), name="ncl-drawdown-bucket")
        )

        # ── Wave 14K Phase 2 — auto-trader decision loop ─────────────
        # PAPER TRADING ONLY. Default state.active=False; the loop
        # idles until operator POST /portfolio/auto-trader/resume.
        # Cadence is internal (60s market / 300s off-hours).
        # See runtime/portfolio/auto_trader/loop.py.
        from ..portfolio.auto_trader.loop import auto_trader_loop

        # Wave 14U U2 — ingest AUTO_TRADER_MANDATE.md as procedural
        # memory at importance 95 (NATRIX tier) on every boot. Makes
        # the mandate visible to every Council/Brief/Chat caller +
        # auditable per CFTC Reg AT pattern.
        async def _ingest_mandate():
            """Wave 14W-A — ingest all 5 lane mandates (PORTFOLIO/INTEL/MEMORY/
            CALENDAR/JOURNAL) plus AUTO_TRADER_MANDATE as procedural memory
            at importance 95 on every Brain boot. Makes the coherent goal +
            governance + producer/consumer contracts of each lane visible
            to every Council/Brief/Chat caller + auditable per CFTC Reg AT
            pattern.

            Each mandate is idempotent — re-ingesting on bounce just creates
            a fresh procedural memory unit (the old ones age via SML decay
            and the dedup pass during consolidation handles overlap).
            """
            try:
                from pathlib import Path as _Path
                import os as _os
                base = _Path(_os.environ.get("NCL_BASE",
                                              str(_Path.home() / "dev" / "NCL")))
                mem = getattr(self.brain, "memory_store", None)
                if mem is None or not hasattr(mem, "create_unit"):
                    log.warning("[MANDATE] no memory_store — skipped")
                    return

                # Wave 14W-A — 5 lane mandates + auto-trader
                # (auto_trader is a portfolio-lane sub-mandate but ingested
                # separately because it predates the lane mandates and has
                # its own governance lineage)
                mandates = [
                    {
                        "name": "INTEL_MANDATE",
                        "path": "docs/INTEL_MANDATE.md",
                        "source": "intel:lane_mandate",
                        "summary": (
                            "INTEL lane mandate v1.0 — time-bounded "
                            "outside-world feed. Awarebot scans + scores + "
                            "tier-routes. HIGH band threshold 0.65, "
                            "google_trends auth capped 0.4, city_events "
                            "moved to Calendar lane. Memory promotion gated "
                            "(CRITICAL or x-source≥2 or pin)."
                        ),
                        "tags": ["intel", "lane_mandate", "procedural",
                                 "v1.0", "natrix_authority", "wave_14W_A"],
                    },
                    {
                        "name": "MEMORY_MANDATE",
                        "path": "docs/MEMORY_MANDATE.md",
                        "source": "memory:lane_mandate",
                        "summary": (
                            "MEMORY lane mandate v1.0 — permanent recall "
                            "substrate. Write-time gate (council, NATRIX, "
                            "CRITICAL, x-source≥2, pin, agent reasoning "
                            "chain, journal≥50, AT close, cycle change, "
                            "portfolio significant). 25K capacity. 7-tier "
                            "authority. WC is daily-rolling 50-item subset."
                        ),
                        "tags": ["memory", "lane_mandate", "procedural",
                                 "v1.0", "natrix_authority", "wave_14W_A"],
                    },
                    {
                        "name": "CALENDAR_MANDATE",
                        "path": "docs/CALENDAR_MANDATE.md",
                        "source": "calendar:lane_mandate",
                        "summary": (
                            "CALENDAR lane mandate v1.0 — time-anchored "
                            "future-facing feed. Every datum has ISO date + "
                            "impact + region + category. Quality filter on "
                            "city_cultural. Never auto-promotes to Memory "
                            "(except lunar phase + earnings day)."
                        ),
                        "tags": ["calendar", "lane_mandate", "procedural",
                                 "v1.0", "natrix_authority", "wave_14W_A"],
                    },
                    {
                        "name": "JOURNAL_MANDATE",
                        "path": "docs/JOURNAL_MANDATE.md",
                        "source": "journal:lane_mandate",
                        "summary": (
                            "JOURNAL lane mandate v1.0 — NATRIX's "
                            "first-person lane. Free-form writes always "
                            "pass. Importance≥50 echoes to Memory. Morning "
                            "quiz Q2 auto-pins at importance 100. Daily "
                            "ReflectionEngine nightly synthesis. LifePlan "
                            "Vision/Goal/KR/Plan structured."
                        ),
                        "tags": ["journal", "lane_mandate", "procedural",
                                 "v1.0", "natrix_authority", "wave_14W_A"],
                    },
                    {
                        "name": "AUTO_TRADER_MANDATE",
                        "path": "docs/AUTO_TRADER_MANDATE.md",
                        "source": "portfolio:auto_trader_mandate",
                        "summary": (
                            "AUTO_TRADER sub-mandate v1.0 (lives under "
                            "PORTFOLIO lane) — paper-trading-only "
                            "hedge-fund-manager-in-training. Hard line: "
                            "NCL never places live orders. 5%/8/2 mandate."
                        ),
                        "tags": ["portfolio", "auto_trader", "mandate",
                                 "procedural", "v1.0", "natrix_authority",
                                 "wave_14W_A"],
                    },
                    # ── Wave 14W-F — Intel sub-tab mandates ───────────────
                    # Lifts the per-sub-tab mandate into procedural memory so
                    # the agent + brief executor see the same canonical
                    # "what is each surface for" that iOS renders as the
                    # tab subtitle.
                    {
                        "name": "AGENDA_MANDATE",
                        "path": "docs/AGENDA_MANDATE.md",
                        "source": "intel:agenda_mandate",
                        "summary": (
                            "AGENDA sub-tab mandate — what to attend to in "
                            "the next hour. Working-context items + ≤5 key "
                            "signals + ≤5 risk items, fed by "
                            "/intelligence/digest. Decision: where to point "
                            "Focus/Brief/chat next."
                        ),
                        "tags": ["intel", "agenda", "sub_tab_mandate",
                                 "procedural", "v1.0", "wave_14W_F"],
                    },
                    {
                        "name": "BRIEF_MANDATE",
                        "path": "docs/BRIEF_MANDATE.md",
                        "source": "intel:brief_mandate",
                        "summary": (
                            "BRIEF sub-tab mandate — flagship pre-market "
                            "synthesized read with MARKET OPEN PLAN + 6 "
                            "trade ideas citing signal_ids. Rules 7a-7e + "
                            "trade_idea_count_target ≥ 4 enforce quality. "
                            "Decision: take any of the trade ideas."
                        ),
                        "tags": ["intel", "brief", "sub_tab_mandate",
                                 "procedural", "v1.0", "wave_14W_F"],
                    },
                    {
                        "name": "NIGHTWATCH_MANDATE",
                        "path": "docs/NIGHTWATCH_MANDATE.md",
                        "source": "intel:nightwatch_mandate",
                        "summary": (
                            "NIGHT WATCH sub-tab mandate — overnight ops "
                            "health log: status (R/Y/G), findings, "
                            "recommendations, system health, cost. "
                            "Decision: do I trust today's brief?"
                        ),
                        "tags": ["intel", "nightwatch", "sub_tab_mandate",
                                 "procedural", "v1.0", "wave_14W_F"],
                    },
                    {
                        "name": "FOCUS_MANDATE",
                        "path": "docs/FOCUS_MANDATE.md",
                        "source": "intel:focus_mandate",
                        "summary": (
                            "FOCUS sub-tab mandate — scored signal stream "
                            "in 3 time windows (FOCUS<4h, MICRO<24h, "
                            "MACRO>24h) over the Awarebot pool. "
                            "Decision: confirm a cluster, pin into Memory, "
                            "or fire a research card."
                        ),
                        "tags": ["intel", "focus", "sub_tab_mandate",
                                 "procedural", "v1.0", "wave_14W_F"],
                    },
                ]

                # Wave 14W-A — fire all 5 ingests in parallel via gather.
                # Serial awaits get starved by background loops (memory
                # consolidation, BM25 rebuild, narrative threads) that
                # take the same async lock — only 2 of 5 would complete
                # within 5 minutes. Parallel gather lets them all queue at
                # once and the asyncio.Condition writer-preference policy
                # interleaves them with the consumers.
                async def _ingest_one(mandate: dict) -> tuple[str, bool]:
                    try:
                        mandate_path = base / mandate["path"]
                        if not mandate_path.exists():
                            log.warning(
                                "[MANDATE] %s missing — skipped",
                                mandate_path,
                            )
                            return mandate["name"], False
                        text = mandate_path.read_text()
                        await mem.create_unit(
                            content=(
                                f"{mandate['name']} — {mandate['summary']}"
                                f"\n\n{text[:6000]}"
                            ),
                            source=mandate["source"],
                            importance=95.0,
                            tags=mandate["tags"],
                            memory_type="procedural",
                            metadata={
                                "mandate_name": mandate["name"],
                                "mandate_version": "1.0",
                                "mandate_path": str(mandate_path),
                                "wave": "14W-A",
                            },
                        )
                        log.info(
                            "[MANDATE] ingested %s v1.0 (importance 95)",
                            mandate["name"],
                        )
                        return mandate["name"], True
                    except Exception as e:
                        log.warning(
                            "[MANDATE] %s ingest failed (non-fatal): %s",
                            mandate["name"], e,
                        )
                        return mandate["name"], False

                results = await asyncio.gather(
                    *(_ingest_one(m) for m in mandates),
                    return_exceptions=False,
                )
                ingested = sum(1 for _, ok in results if ok)
                log.info(
                    "[MANDATE] Wave 14W-A complete — %d of %d lane "
                    "mandates ingested as procedural memory",
                    ingested, len(mandates),
                )
            except Exception as e:
                log.warning("[MANDATE] ingest pass failed (non-fatal): %s", e)

        async def _auto_trader():
            await _ingest_mandate()
            await auto_trader_loop(self.brain)

        self._tasks.append(
            asyncio.create_task(_auto_trader(), name="ncl-auto-trader-loop")
        )

        # ── Wave 14U-2/10 — monthly portfolio review ─────────────────
        # Fires on 1st of month at 10:00 UTC (06:00 ET). Builds the
        # strategy scorecard (Sharpe/Sortino/Calmar/alpha per sleeve),
        # writes JSON + Markdown to data/portfolio/auto_trader/
        # monthly_reviews/, emits memory unit at importance 90, and
        # creates a journal reflection entry.
        from ..portfolio.auto_trader.monthly_review import monthly_review_loop

        async def _auto_trader_monthly():
            await monthly_review_loop(self.brain)

        self._tasks.append(
            asyncio.create_task(_auto_trader_monthly(),
                                name="ncl-auto-trader-monthly-review")
        )

        # ── Wave 14K Phase 3 — auto-trader price feed ────────────────
        # Pulls quotes for open paper symbols (30s market / 300s off-
        # hours), applies to PaperTradingEngine.update_prices(), and
        # any triggered close events flow through outcome_attributor
        # back into trade_idea_tracker for expectancy attribution.
        # Runs even when auto-trader paused — pause stops NEW opens,
        # not mark-to-market of existing positions.
        # See runtime/portfolio/auto_trader/price_feed.py.
        from ..portfolio.auto_trader.price_feed import price_feed_loop

        async def _auto_trader_prices():
            await price_feed_loop(self.brain)

        self._tasks.append(
            asyncio.create_task(_auto_trader_prices(), name="ncl-auto-trader-prices")
        )

        # Wave 14K gap-close C — auto-trader EOD summary at 21:55 ET so the
        # 22:00 ET journal_reflection sees a daily rollup of the agent's day.
        from ..portfolio.auto_trader.eod_summary import eod_summary_loop

        async def _auto_trader_eod():
            await eod_summary_loop()

        self._tasks.append(
            asyncio.create_task(_auto_trader_eod(), name="ncl-auto-trader-eod")
        )

        # Wave 14L L6 — pro-active scout loop (5min market / 30min off-hours).
        # Originates trade ideas from open positions + holdings + regime
        # + earnings; emits MemUnits for ladder triggers, regime shifts,
        # covered-call opportunities, earnings-defensive flags.
        from ..portfolio.auto_trader.scout import scout_loop

        async def _auto_trader_scout():
            await scout_loop(self.brain)

        self._tasks.append(
            asyncio.create_task(_auto_trader_scout(), name="ncl-auto-trader-scout")
        )

        # Wave 14L L2 — quant scanner suite (30min market / 2hr off-hours).
        # 5 scanners (mean_reversion, pead, factor, pairs, whale_flow)
        # originate trade ideas in parallel to the morning brief.
        from ..portfolio.auto_trader.quant_scanners import quant_scan_loop

        async def _auto_trader_quant_scan():
            await quant_scan_loop(self.brain)

        self._tasks.append(
            asyncio.create_task(_auto_trader_quant_scan(), name="ncl-auto-trader-quant-scan")
        )

        # ── Wave 14R — Polymarket agent (3 loops, paper-bet only) ──────
        # ncl-poly-collector  : 15min  — Gamma feed → cache file
        # ncl-poly-loop       : 5min   — edge engine → kelly → paper bet
        # ncl-poly-resolution : 5min   — auto-close at endDate / market resolution
        from ..portfolio.polymarket_agent.collector_loop import poly_collector_loop
        from ..portfolio.polymarket_agent.loop import (
            poly_decision_loop, poly_resolution_loop,
        )

        async def _poly_collector():
            await poly_collector_loop(self.brain)

        async def _poly_loop():
            await poly_decision_loop(self.brain)

        async def _poly_resolution():
            await poly_resolution_loop(self.brain)

        self._tasks.append(
            asyncio.create_task(_poly_collector(), name="ncl-poly-collector")
        )
        self._tasks.append(
            asyncio.create_task(_poly_loop(), name="ncl-poly-loop")
        )
        self._tasks.append(
            asyncio.create_task(_poly_resolution(), name="ncl-poly-resolution")
        )

        # Attach a done-callback to every task so a silent crash (unobserved
        # task exception) gets logged instead of disappearing.
        def _task_done(task: asyncio.Task) -> None:
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                log.error(
                    f"[SCHEDULER] task '{task.get_name()}' DIED: " f"{type(exc).__name__}: {exc!r}",
                    exc_info=exc,
                )

        for t in self._tasks:
            t.add_done_callback(_task_done)

        # ── Task factory mapping for supervisor restarts ──────────────
        self._task_factories: dict[str, Any] = {
            "ncl-heartbeat": self._heartbeat_loop,
            "ncl-council-auto": self._council_auto_loop,
            "ncl-memory": self._memory_consolidation_loop,
            "ncl-workspace": self._workspace_health_loop,
            "ncl-mandate-purge": self._mandate_purge_loop,
            "ncl-feedback-synth": self._feedback_synthesis_loop,
            "ncl-working-ctx": self._working_context_loop,
            "ncl-night-watch": self._night_watch_loop,
            "ncl-journal-reflection": self._journal_reflection_loop,
            # New 2026-05-21 loops
            "ncl-health-rollup": self._health_rollup_loop,
            "ncl-cost-rollover": self._cost_rollover_loop,
            "ncl-cache-warmer": self._cache_warmer_loop,
            "ncl-alert-dispatch": self._alert_dispatch_loop,
            "ncl-ytc-dedicated": self._ytc_dedicated_loop,
            "ncl-ytc-nightshift": self._ytc_nightshift_loop,
            "ncl-bm25-rebuild": self._bm25_rebuild_loop,
            "ncl-city-events": self._city_events_loop,
            "ncl-stocks-scan": self._stocks_scan_loop,
            # W13 P1-A (2026-05-24): stall watchdog can die too. Without a
            # factory entry the supervisor logs "No factory for task
            # 'ncl-stall-watchdog' — cannot restart" and the watchdog
            # stays dead, meaning we lose detection of frozen
            # heartbeats / Rust HNSW deadlocks (the W12 incident class).
            "ncl-stall-watchdog": self._stall_watchdog_loop,
            # P25 (2026-05-26): Morning Brief Pro 3-stage loops. Without
            # these entries the supervisor logs "No factory for task
            # 'ncl-brief-prep' — cannot restart" the moment one of them
            # raises and stays dead until Brain restart. Wrap each in
            # a thunk binding self.brain at the call site so the closure
            # behaves identically to the in-line `_brief_prep` form above.
            "ncl-brief-prep": lambda: brief_prep_loop(self.brain),
            "ncl-brief-council": lambda: brief_council_loop(self.brain),
            "ncl-brief-render": lambda: brief_render_loop(self.brain),
            # Wave 14J J0c — global drawdown bucket. Supervisor restart
            # factory mirrors the brief-* lambda pattern.
            "ncl-drawdown-bucket": lambda: drawdown_bucket_loop(self.brain),
            # Wave 14K Phase 2 — auto-trader decision loop. Same lambda
            # pattern so supervisor can restart on crash.
            "ncl-auto-trader-loop": lambda: auto_trader_loop(self.brain),
            # Wave 14K Phase 3 — auto-trader price feed.
            "ncl-auto-trader-prices": lambda: price_feed_loop(self.brain),
            # Wave 14K gap-close C — auto-trader EOD summary (21:55 ET daily).
            "ncl-auto-trader-eod": lambda: __import__(
                "runtime.portfolio.auto_trader.eod_summary",
                fromlist=["eod_summary_loop"],
            ).eod_summary_loop(),
            # Wave 14L L6 — pro-active scout loop (5min market / 30min off).
            "ncl-auto-trader-scout": lambda: __import__(
                "runtime.portfolio.auto_trader.scout",
                fromlist=["scout_loop"],
            ).scout_loop(self.brain),
            # Wave 14L L2 — quant scanner suite (30min market / 2hr off).
            "ncl-auto-trader-quant-scan": lambda: __import__(
                "runtime.portfolio.auto_trader.quant_scanners",
                fromlist=["quant_scan_loop"],
            ).quant_scan_loop(self.brain),
            # ── Wave 14R — Polymarket agent (3 loops, paper-bet only) ──
            "ncl-poly-collector": lambda: __import__(
                "runtime.portfolio.polymarket_agent.collector_loop",
                fromlist=["poly_collector_loop"],
            ).poly_collector_loop(self.brain),
            "ncl-poly-loop": lambda: __import__(
                "runtime.portfolio.polymarket_agent.loop",
                fromlist=["poly_decision_loop"],
            ).poly_decision_loop(self.brain),
            "ncl-poly-resolution": lambda: __import__(
                "runtime.portfolio.polymarket_agent.loop",
                fromlist=["poly_resolution_loop"],
            ).poly_resolution_loop(self.brain),
        }
        # 2026-05-22 memory loops (factory registration — only if loaded above)
        try:
            from ..memory.eval.loop import _memory_eval_loop as _mem_eval

            self._task_factories["ncl-memory-eval"] = lambda: _mem_eval(self.brain)
        except Exception:
            pass
        if hasattr(self, "_chroma_gc_wrapper"):
            self._task_factories["ncl-chroma-gc"] = self._chroma_gc_wrapper
        if hasattr(self, "_conflict_arb_loop"):
            self._task_factories["ncl-conflict-arb"] = self._conflict_arb_loop
        if hasattr(self, "_staleness_detector"):
            try:
                from ..memory.staleness_detector import staleness_detector_loop

                self._task_factories["ncl-staleness"] = lambda: staleness_detector_loop(
                    self, self._staleness_detector
                )
            except Exception as _stale_reg_err:
                log.warning(
                    "[SCHEDULER] ncl-staleness factory register swallowed: %s",
                    _stale_reg_err,
                )
        if hasattr(self, "_narrative_thread_loop"):
            self._task_factories["ncl-narrative-threads"] = self._narrative_thread_loop
        # ncl-dedup-scan (replaces inline Night Watch M1)
        self._task_factories["ncl-dedup-scan"] = self._dedup_scan_loop
        # Haiku A/B monitor (daily summary; no-op when NCL_AB_HAIKU unset)
        if hasattr(self, "_haiku_ab_monitor_loop"):
            self._task_factories["ncl-haiku-ab-monitor"] = self._haiku_ab_monitor_loop
        if hasattr(self, "_sqlite_burnin_verify_loop"):
            self._task_factories["ncl-sqlite-burnin-verify"] = self._sqlite_burnin_verify_loop
        # ncl-claude-md-refresh (24h refresh of system-doc memory units)
        if hasattr(self, "_claude_md_refresh_loop"):
            self._task_factories["ncl-claude-md-refresh"] = self._claude_md_refresh_loop
        # 2026-05-22 batch 2
        if getattr(self, "_async_writer", None) is not None and hasattr(
            self, "_async_writer_supervisor"
        ):
            self._task_factories["ncl-async-writer"] = self._async_writer_supervisor
        if hasattr(self, "_memory_budget_loop"):
            self._task_factories["ncl-memory-budget"] = self._memory_budget_loop
        # Awarebot agent is restarted via its own .run() method
        if self.awarebot:
            self._task_factories["ncl-awarebot-agent"] = self.awarebot.run

        # Calendar agent + its alert-check sidecar
        if self.calendar_agent:
            self._task_factories["ncl-calendar-agent"] = self.calendar_agent.run
            self._task_factories["ncl-calendar-alerts"] = self._calendar_alert_check_loop

        # ── Spawn supervisor (not in self._tasks — supervises itself) ─
        self._restart_counts.clear()
        self._supervisor_task = asyncio.create_task(self._supervisor_loop(), name="ncl-supervisor")

        await self._log_autonomous_event(
            "scheduler_started",
            {
                "loops": [t.get_name() for t in self._tasks],
                "config": {
                    "x_scan_interval": self.config.x_scan_interval,
                    "youtube_scan_interval": self.config.youtube_scan_interval,
                    "reddit_scan_interval": self.config.reddit_scan_interval,
                    "prediction_interval": self.config.prediction_interval,
                    "memory_consolidation_interval": self.config.memory_consolidation_interval,
                    "council_trigger_threshold": self.council_trigger_threshold,
                },
            },
        )

    async def stop(self) -> None:
        """Gracefully stop all background loops.

        Sets _stop_event so loops break cleanly (the _running property
        derives from _stop_event — no separate flag to desync).
        Cancels all asyncio tasks and waits for them to finish.
        """
        log.warning("[SCHEDULER] stop() called — cancelling %d tasks", len(self._tasks))
        self._stop_event.set()
        # Cancel the supervisor first so it doesn't try to restart tasks we're stopping
        if self._supervisor_task and not self._supervisor_task.done():
            self._supervisor_task.cancel()
            await asyncio.gather(self._supervisor_task, return_exceptions=True)
            self._supervisor_task = None
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        log.info("[SCHEDULER] All tasks stopped")
        await self._log_autonomous_event("scheduler_stopped", self._stats)

    def _emergency_stop_active(self) -> bool:
        """Return True if the emergency stop kill switch is engaged.

        Delegates solely to EMERGENCY_STOP_EVENT (the single source of truth)
        so all loops—regardless of which check style they use—see the same state.
        The EmergencyStop instance is kept for activation/deactivation calls only.
        """
        return EMERGENCY_STOP_EVENT.is_set()

    def get_stats(self) -> dict:
        """Return scheduler statistics."""
        stats = {
            **self._stats,
            "running": self._running,
            "active_tasks": [t.get_name() for t in self._tasks if not t.done()],
            "signal_buffer_size": len(self._signal_buffer),
            "signal_processor": self.signal_processor.get_stats(),
            "supervisor": {
                "active": bool(self._supervisor_task and not self._supervisor_task.done()),
                "restart_counts": dict(self._restart_counts),
            },
        }
        if self.awarebot:
            stats["awarebot"] = self.awarebot.get_stats()
        if self._journal_store:
            stats["journal"] = self._journal_store.get_stats()
        return stats

    # ─── LOOP 3: Council Auto-Spawn ────────────────────────────

    async def _run_council_with_pack_or_fallback(
        self,
        *,
        topic: str,
        prompt: str,
        trigger: str,
    ):
        """Try the universal council_pack path; fall back to the legacy
        ``brain.spawn_council_session`` on any failure.

        The pack path provides: MMR-diversified evidence, temporal split,
        contradiction surfacing, position trick, 40% util cap, MapReduce
        compression, calibration preamble per member, and 3-tier write-back.

        If anything in that chain throws (missing dep, retriever crash,
        import error, etc.) we log the failure and use the original
        spawn_council_session so the autonomous loop NEVER regresses.

        Quorum pre-pass (W10B-8, gated by ``NCL_COUNCIL_QUORUM=true``):
        Before paying for the full 6-LLM debate, we run a Sonnet+Haiku
        2-model agreement check. When the two responses are similar enough
        (cosine >= 1 - threshold) we short-circuit and synthesize the
        Sonnet response into a minimal CouncilSession, saving 4-5 paid
        member calls (Grok / Gemini / Perplexity / GPT / Copilot) at
        ~$0.10/session. Pre-pass costs ~$0.001/session. On ANY pre-pass
        failure (missing keys, gate fail, HTTP error, disagreement) we
        fall through to the full pack-or-fallback path — never silently
        agree.

        This pre-pass is ONLY wired into the autonomous spawn path. The
        NATRIX-triggered pump path in ``brain.receive_pump_prompt`` runs
        the full 6 council unconditionally, preserving the high-stakes
        debate guarantee for user-initiated decisions.
        """
        # ── W10B-8: Quorum pre-pass (autonomous-only, feature-flagged) ──
        if os.environ.get("NCL_COUNCIL_QUORUM", "false").lower() in ("true", "1", "yes"):
            try:
                short_circuit_session = await self._try_quorum_short_circuit(
                    topic=topic, prompt=prompt, trigger=trigger
                )
                if short_circuit_session is not None:
                    return short_circuit_session
            except Exception as quorum_err:
                # Fail-open: any quorum failure falls through to the full council.
                log.warning(
                    "[COUNCIL-AUTO:QUORUM] pre-pass raised (%s) — falling through to "
                    "full council",
                    quorum_err,
                )

        # Try the pack path
        try:
            from runtime.council_pack import run_council_with_pack
            from runtime.memory.retrieval import BM25Index, FusedRetriever

            store = self.brain.memory_store
            if not getattr(store, "_bm25_index", None):
                store._bm25_index = BM25Index(store)
            fused = FusedRetriever(
                store,
                store._bm25_index,
                knowledge_graph=getattr(store, "_knowledge_graph", None),
            )

            # Best-effort acquire the awarebot Beta-Bernoulli learner so the
            # pack's effective_weight reflects empirical track record on top
            # of the static tier prior. None is fine — assembler treats it
            # as "no adjustment" (1.0).
            learner = getattr(getattr(self, "awarebot", None), "_authority_learner", None)

            result = await run_council_with_pack(
                council_engine=self.brain.council_engine,
                topic=topic,
                base_prompt=prompt,
                fused_retriever=fused,
                working_context=self._working_context,
                learner=learner,
                async_writer=self._async_writer,
                council_type=f"autonomous:{trigger}",
            )
            session = result["session"]

            # Mirror what spawn_council_session does: persist + log + insights.
            try:
                async with self.brain._council_sessions_lock:
                    if len(self.brain.council_sessions) >= self.brain._COUNCIL_SESSIONS_MAX:
                        self.brain._evict_oldest_council_sessions()
                    self.brain.council_sessions[session.session_id] = session
                    await self.brain._persist_council_sessions_unlocked()
            except Exception as persist_err:
                log.warning(
                    "[COUNCIL-AUTO] pack-path persist failed (%s) — session still complete",
                    persist_err,
                )

            log.info(
                "[COUNCIL-AUTO:PACK] %s session=%s pack_items=%d conflicts=%d cal_blocks=%d "
                "writeback_gist_chars=%d",
                trigger,
                session.session_id,
                result["pack"].get("pack_size_items", 0),
                len(result["pack"].get("surfaced_conflicts", []) or []),
                len(result.get("calibrations") or []),
                len((result.get("writeback") or {}).get("gist") or ""),
            )
            return session
        except Exception as pack_err:
            log.warning(
                "[COUNCIL-AUTO:PACK] pack path failed (%s) — falling back to legacy "
                "spawn_council_session",
                pack_err,
            )

        # Fallback — original behavior, unchanged.
        return await self.brain.spawn_council_session(
            topic=topic,
            prompt=prompt,
            members=None,
        )

    async def _try_quorum_short_circuit(
        self,
        *,
        topic: str,
        prompt: str,
        trigger: str,
    ):
        """W10B-8: Cheap Sonnet+Haiku pre-pass before the full council.

        Returns a populated ``CouncilSession`` when the two models agree
        within ``NCL_QUORUM_THRESHOLD`` (default 0.6), so the caller can
        skip the 4-5 extra paid member calls. Returns ``None`` on any
        outcome where the full council should still run:
            * disagreement above threshold
            * pre-pass error / budget gate fail
            * missing API key
            * synthesis below quality bar

        Estimated savings when ON: ~$0.10/session - ~$0.001/session
        pre-pass cost = ~$0.099/session recovered on agreement. Typical
        autonomous council cadence is ~14/day (signal-converge + 4hr
        strategic-review), giving roughly $1.38/day at the 34% agreement
        rate the quorum module documents.
        """
        try:
            from runtime.cost_tracker import get_tracker
            from runtime.councils.quorum import CouncilQuorum, QuorumDecision
        except Exception as exc:
            log.warning("[COUNCIL-AUTO:QUORUM] import failed: %s — skipping pre-pass", exc)
            return None

        try:
            tracker = await get_tracker()
        except Exception as exc:
            log.warning(
                "[COUNCIL-AUTO:QUORUM] cost tracker unavailable (%s) — skipping pre-pass", exc
            )
            return None

        # Re-use the brain's existing http client to avoid spinning up a
        # second connection pool. ``CouncilQuorum`` won't close a client
        # it didn't own (``_owns_http=False``).
        anthropic_client = getattr(getattr(self.brain, "council_engine", None), "http_client", None)
        quorum = CouncilQuorum(
            anthropic_client=anthropic_client,
            cost_gate_callable=tracker.can_spend,
        )

        result = await quorum.run_quorum(topic=topic, context="", prompt=prompt)

        if result.decision != QuorumDecision.AGREE_SHORT_CIRCUIT:
            log.info(
                "[COUNCIL-AUTO:QUORUM] %s — escalating to full council "
                "(similarity=%.3f, cost=$%.4f, dur=%.2fs)",
                result.decision.value,
                result.similarity,
                result.cost_usd,
                result.duration_s,
            )
            return None

        # Build a minimal CouncilSession that mirrors what the full debate
        # would have produced. The synthesis is just the Sonnet response;
        # consensus_score reflects the agreement we measured.
        try:
            import uuid as _uuid
            from datetime import datetime as _dt
            from datetime import timezone as _tz

            from runtime.ncl_brain.models import (
                ConsensusScore,
                CouncilMember,
                CouncilRole,
                CouncilSession,
                CouncilStatus,
                DebateRound,
            )

            session_id = str(_uuid.uuid4())
            session = CouncilSession(
                session_id=session_id,
                topic=topic,
                chair="claude",
                members=[CouncilMember.CLAUDE],  # quorum used Claude (Sonnet) + Haiku
                role_assignments={CouncilMember.CLAUDE.value: CouncilRole.CHAIR.value},
                status=CouncilStatus.COMPLETE,
                prompt=prompt,
                protocol="quorum-short-circuit",
                synthesis=result.sonnet_response,
                consensus=result.sonnet_response[:500],
                consensus_score=ConsensusScore(
                    agreement_pct=result.similarity * 100.0,
                    confidence_weighted=result.confidence * 100.0,
                    threshold_met=True,
                    unanimous=False,
                    reason=result.reason,
                ),
                rounds=[
                    DebateRound(
                        round_number=1,
                        round_type="quorum",
                        responses={
                            "claude": result.sonnet_response,
                            "haiku": result.haiku_response,
                        },
                        scores={
                            "claude": result.confidence * 100.0,
                            "haiku": result.confidence * 100.0,
                        },
                    )
                ],
                created_at=_dt.now(_tz.utc),
                completed_at=_dt.now(_tz.utc),
            )

            # Persist alongside other council sessions for the iOS UI.
            async with self.brain._council_sessions_lock:
                if len(self.brain.council_sessions) >= self.brain._COUNCIL_SESSIONS_MAX:
                    self.brain._evict_oldest_council_sessions()
                self.brain.council_sessions[session.session_id] = session
                await self.brain._persist_council_sessions_unlocked()

            log.info(
                "[COUNCIL-AUTO:QUORUM] short-circuit %s session=%s similarity=%.3f "
                "cost=$%.4f dur=%.2fs",
                trigger,
                session.session_id,
                result.similarity,
                result.cost_usd,
                result.duration_s,
            )
            return session
        except Exception as build_err:
            log.warning(
                "[COUNCIL-AUTO:QUORUM] session build failed (%s) — falling through to "
                "full council",
                build_err,
            )
            return None

    async def _council_auto_loop(self) -> None:
        """
        Monitor for conditions that warrant autonomous council deliberation.

        Triggers a council session when:
        - Multiple high-importance signals converge on a theme
        - Prediction ensemble detects convergence with high confidence
        - A critical signal exceeds the council trigger threshold
        - Scheduled strategic review interval is reached

        Councils run autonomously but mandates still require NATRIX approval.
        """
        # Strategic review interval (4 hours default)
        strategic_review_interval = 4 * 3600
        last_strategic_review = datetime.now(timezone.utc)

        # Wait for initial data gathering
        await asyncio.sleep(self.config.prediction_interval + 60)

        while self._running:
            # Halt council spawning on emergency stop
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[COUNCIL-AUTO] Emergency stop active — halting loop")
                break

            try:
                now = datetime.now(timezone.utc)
                council_needed = False
                council_prompt = ""
                council_trigger = ""

                # Check 1: Pending council flags from prediction/scanner
                council_flags = await self._get_council_flags()
                if len(council_flags) >= self.council_min_signals:
                    council_needed = True
                    council_trigger = "accumulated_signals"
                    themes = set()
                    for flag in council_flags:
                        themes.update(flag.get("data", {}).get("tags", []))
                    council_prompt = (
                        f"AUTONOMOUS COUNCIL — {len(council_flags)} high-priority signals detected. "  # noqa: E501
                        f"Themes: {', '.join(list(themes)[:10])}. "
                        f"Analyze these converging signals, assess implications for NARTIX operations, "  # noqa: E501
                        f"and recommend strategic actions or mandate adjustments."
                    )

                # Check 2: Scheduled strategic review
                elif (now - last_strategic_review).total_seconds() >= strategic_review_interval:
                    # W10C-12: skip-if-empty guard — don't burn $0.10/session
                    # on a 4h strategic review when there's nothing to debate.
                    # Counts signals in _signal_buffer with timestamp within
                    # the last 4h. If buffer is empty OR fewer than 3 recent
                    # signals, skip this cycle (last_strategic_review is NOT
                    # advanced, so we re-check on the next 5min poll and fire
                    # as soon as signal density returns).
                    recent_signal_cutoff = now - timedelta(seconds=strategic_review_interval)
                    recent_signal_count = 0
                    for sig in list(self._signal_buffer):
                        ts_raw = sig.get("timestamp")
                        if not ts_raw:
                            continue
                        try:
                            ts = (
                                ts_raw
                                if isinstance(ts_raw, datetime)
                                else datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                            )
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                        except (ValueError, TypeError):
                            continue
                        if ts >= recent_signal_cutoff:
                            recent_signal_count += 1

                    if recent_signal_count < 3:
                        log.info(
                            "[COUNCIL-AUTO] Skipping 4h strategic review — "
                            "only %d signals in last 4h (need >=3). "
                            "Buffer size=%d. Saving ~$0.10/session.",
                            recent_signal_count,
                            len(self._signal_buffer),
                        )
                        # Bump last_strategic_review forward by 1h so we
                        # re-evaluate in 1h rather than every 5min poll.
                        last_strategic_review = now - timedelta(
                            seconds=strategic_review_interval - 3600
                        )
                    else:
                        council_needed = True
                        council_trigger = "strategic_review"
                        council_prompt = (
                            "SCHEDULED STRATEGIC REVIEW — Conduct a periodic assessment of: "
                            "1) Active mandate progress and blockers, "
                            "2) Intelligence signals and emerging opportunities, "
                            "3) Resource allocation and budget status, "
                            "4) Risk factors and mitigation strategies. "
                            "Produce recommendations for NATRIX review."
                        )
                        last_strategic_review = now

                if council_needed:
                    log.info(f"[COUNCIL-AUTO] Spawning autonomous council: {council_trigger}")
                    try:
                        topic = f"autonomous:{council_trigger}"
                        # ── council_pack integration (added 2026-05-23 swarm) ──
                        # Try the universal pack path first: assemble pack with
                        # MMR + temporal split + conflict surfacing + position
                        # trick + 40% util cap + MapReduce, run debate with
                        # calibration preamble, then 3-tier write-back.
                        # On ANY failure (import error, retriever error, etc.)
                        # fall back to the original brain.spawn_council_session
                        # so we never make autonomous councils worse than they
                        # already are.
                        session = await self._run_council_with_pack_or_fallback(
                            topic=topic,
                            prompt=council_prompt,
                            trigger=council_trigger,
                        )

                        if session:
                            consensus_text = (session.consensus or "")[:500]
                            agreement_pct = (
                                session.consensus_score.agreement_pct
                                if session.consensus_score
                                else 0.0
                            )

                            # Store council output in memory
                            await self.brain.memory_store.create_unit(
                                content=(
                                    f"Autonomous council ({council_trigger}): " f"{consensus_text}"
                                ),
                                source=f"autonomous:council:{council_trigger}",
                                importance=90.0,
                                tags=["council", "autonomous", council_trigger],
                            )

                            # Clear processed flags
                            await self._clear_council_flags()

                            self._stats["councils_auto_spawned"] += 1
                            self._stats["last_council"] = now.isoformat()

                            log.info(
                                f"[COUNCIL-AUTO] Session complete — "
                                f"consensus={agreement_pct:.0f}% "
                                f"id={session.session_id}"
                            )

                            await self._log_autonomous_event(
                                "council_auto_spawned",
                                {
                                    "trigger": council_trigger,
                                    "session_id": session.session_id,
                                    "consensus_score": agreement_pct,
                                    "recommendations": len(session.recommendations or []),
                                },
                            )

                    except Exception as e:
                        log.error(f"[COUNCIL-AUTO] Council spawn failed: {e}", exc_info=True)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[COUNCIL-AUTO] Loop error: {e}", exc_info=True)

            # Check every 5 minutes
            await asyncio.sleep(300)

    # ─── LOOP 4: Memory Consolidation ──────────────────────────

    async def _memory_consolidation_loop(self) -> None:
        """
        Periodic memory maintenance: decay, consolidation, and cleanup.

        - Applies exponential decay to all memory units
        - Consolidates related units (merge duplicates)
        - Prunes units below importance threshold
        - Computes and logs memory statistics
        """
        await asyncio.sleep(60)  # Brief startup delay

        while self._running:
            # W10B-7: stamp a fresh per-cycle correlation id so every log
            # line emitted during this consolidation pass is tagged with
            # `[req=loop-memcons-<hex8>]`.
            set_request_id(loop_request_id("loop-memcons"))
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[MEMORY] Emergency stop active — halting loop")
                break
            try:
                log.info("[MEMORY] Starting consolidation cycle...")

                store = self.brain.memory_store
                stats_before = await store.stats()

                # Enhanced consolidation with reflection loop
                try:
                    if hasattr(self.brain.memory_store, "consolidate_v2"):
                        consolidation_result = await self.brain.memory_store.consolidate_v2()
                    else:
                        consolidation_result = await self.brain.memory_store.consolidate()
                except Exception as e:
                    log.warning(f"consolidate_v2 failed, using basic: {e}")
                    consolidation_result = await store.consolidate()

                stats_after = await store.stats()

                self._stats["memory_consolidations"] += 1
                self._stats["last_consolidation"] = datetime.now(timezone.utc).isoformat()

                pruned = consolidation_result.get("pruned", 0)
                merged = consolidation_result.get("merged", 0)
                log.info(
                    f"[MEMORY] Consolidation complete — "
                    f"before: {consolidation_result.get('total_before', 0)}, "
                    f"after: {consolidation_result.get('total_after', 0)}, "
                    f"pruned: {pruned}, merged: {merged}"
                )

                await self._log_autonomous_event(
                    "memory_consolidation",
                    {
                        "stats_before": stats_before,
                        "stats_after": stats_after,
                        "consolidation": consolidation_result,
                    },
                )

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[MEMORY] Consolidation error: {e}", exc_info=True)

            await asyncio.sleep(self.config.memory_consolidation_interval)

    # ─── LOOP 5 (REMOVED 2026-05-21): AAC War Room Sync ───────
    # _aac_sync_loop deleted per NATRIX directive. Polled BRS
    # dashboard stub + AAC health on a 15min cadence and produced
    # low-value "pillar sync" memory units (importance=40). AAC/BRS
    # health checks are now folded into the Night Watch deterministic
    # health audit (Phase 1) and the workspace health loop. Removed
    # from self._tasks, self._task_factories, and stats counters
    # (aac_syncs, last_aac_sync).

    # ─── LOOP 6: Workspace Health ──────────────────────────────

    async def _workspace_health_loop(self) -> None:
        """
        Monitor MWP workspace pipeline health.

        Checks each workspace stage for:
        - Stale artifacts (stuck in processing)
        - Empty stages (pipeline blockage)
        - Output accumulation (review backlog)
        """
        await asyncio.sleep(180)

        while self._running:
            try:
                workspaces = [
                    "mandate-generation",
                    "research-pipeline",
                    "intelligence-scan",
                    "memory-processing",
                    "feedback-synthesis",
                ]
                base = Path(self.config.data_dir).expanduser().parent / "workspaces"
                health = {}

                for ws in workspaces:
                    ws_path = base / ws / "stages"
                    if ws_path.exists():
                        stages = {}
                        for stage_dir in sorted(ws_path.iterdir()):
                            if stage_dir.is_dir():
                                artifacts = list(stage_dir.glob("*"))
                                stages[stage_dir.name] = {
                                    "artifact_count": len(artifacts),
                                    "newest": max(
                                        (f.stat().st_mtime for f in artifacts), default=0
                                    ),
                                }
                        health[ws] = stages

                if health:
                    await self._log_autonomous_event("workspace_health", health)
                    log.debug(f"[WORKSPACE] Health check: {len(health)} workspaces monitored")

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[WORKSPACE] Health check error: {e}", exc_info=True)

            # Check every 30 minutes
            await asyncio.sleep(1800)

    # ─── LOOP 7: Mandate State Hygiene ───────────────────────────

    async def _mandate_purge_loop(self) -> None:
        """
        Periodically purge stale mandates to prevent state explosion.

        Background: in May 2026 a watcher bug let pending_approval mandates
        accumulate to 22,388 entries before discovery. This loop ensures any
        future leak self-heals within hours instead of months.

        Targets:
          - cancelled / completed older than 30 days  → hard delete
          - pending_approval older than 7 days        → hard delete (orphans)
        """
        # Defer first run so we don't compete with startup
        await asyncio.sleep(600)

        from datetime import datetime as _dt
        from datetime import timezone as _tz

        from ..ncl_brain.models import MandateStatus

        purge_specs = [
            (MandateStatus.CANCELLED, 30 * 24),
            (MandateStatus.COMPLETED, 30 * 24),
            (MandateStatus.PENDING_APPROVAL, 7 * 24),
        ]

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[PURGE] Emergency stop active — halting loop")
                break
            try:
                purged_total = 0
                async with self.brain._mandates_lock:
                    now_ts = _dt.now(_tz.utc).timestamp()
                    for status, max_age_h in purge_specs:
                        cutoff = now_ts - (max_age_h * 3600)
                        victims = [
                            mid
                            for mid, m in self.brain.mandates.items()
                            if m.status == status and m.created_at.timestamp() < cutoff
                        ]
                        for mid in victims:
                            self.brain.mandates.pop(mid, None)
                        if victims:
                            log.info(
                                f"[PURGE] Removed {len(victims)} {status.value} mandates "
                                f"older than {max_age_h}h"
                            )
                            purged_total += len(victims)
                    if purged_total > 0:
                        await self.brain._persist_mandates_unlocked()

                # Health alarm: if total mandates exploded, log loud
                total = len(self.brain.mandates)
                if total > 1000:
                    log.error(
                        f"[PURGE] Mandate count high: {total} — possible state"
                        f" leak. Inspect mandates.json."
                    )

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[PURGE] loop error: {e}", exc_info=True)

            # Run every 6 hours
            await asyncio.sleep(6 * 3600)

    # ─── LOOP 8: Feedback Synthesis ───────────────────────────

    async def _feedback_synthesis_loop(self) -> None:
        """
        Consume pillar feedback reports → produce synthesis notes.

        Reads from feedback-synthesis/{ncc,brs,aac}-reports/, validates each
        report against FeedbackReport schema, moves processed → .consumed/,
        invalid → .quarantine/, and writes interpreted SynthesisNote into
        feedback-synthesis/synthesis/ for downstream council/mandate review.
        """
        # Loud entry log so we can prove the task was scheduled even if a later
        # step throws. (Previous silent-failure mode: import-after-warmup raised
        # under launchd's process environment and the task died with no trace.)
        log.info("[FEEDBACK] loop task spawned, warming up 15s...")
        try:
            await asyncio.sleep(15)  # short warmup so brain finishes other init
        except asyncio.CancelledError:
            raise

        # All imports + path resolution wrapped so any failure logs visibly
        # instead of dying as an unobserved task exception.
        try:
            import os

            from ..feedback.scanner import FeedbackScanner

            env_override = os.environ.get("NCL_FEEDBACK_DIR")
            candidates: list[Path] = []
            if env_override:
                candidates.append(Path(env_override).expanduser())
            # cwd is the launchd WorkingDirectory (NCL repo root) — preferred
            candidates.append(Path.cwd() / "feedback-synthesis")
            candidates.append(self.brain.data_dir.parent / "feedback-synthesis")

            def _is_real_feedback_root(p: Path) -> bool:
                return p.exists() and any(
                    (p / sub).exists() for sub in ("aac-reports", "brs-reports", "ncc-reports")
                )

            base = next((c for c in candidates if _is_real_feedback_root(c)), None)
            if base is None:
                log.warning(
                    f"[FEEDBACK] no valid feedback-synthesis dir "
                    f"(tried: {[str(c) for c in candidates]}) — loop will idle"
                )
                base = candidates[0]
            else:
                log.info(f"[FEEDBACK] watching {base} (cwd={Path.cwd()})")

            scanner = FeedbackScanner(base_dir=base)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception(f"[FEEDBACK] init failed; loop dying: {type(e).__name__}: {e!r}")
            return

        log.info("[FEEDBACK] loop entering scan cycle (interval=300s)")
        ticks = 0
        while self._running:
            ticks += 1
            try:
                # ── Wave-8 skip-if-empty guard (Q8 / 2026-05-24) ──
                # BRS/AAC/NCC pillars retired 2026-05-23 — the report dirs are
                # almost always empty now. Doing 288 no-op scans/day is pointless.
                # Sleep 1h between checks unless at least one report dir has a
                # non-hidden file present. Loop revives instantly if a future
                # pillar drops a report.
                report_dirs = [
                    base / "aac-reports",
                    base / "brs-reports",
                    base / "ncc-reports",
                ]
                has_reports = False
                if base.exists():
                    for rd in report_dirs:
                        if not rd.exists():
                            continue
                        try:
                            for entry in rd.iterdir():
                                if entry.name.startswith("."):
                                    continue
                                if entry.is_file():
                                    has_reports = True
                                    break
                        except OSError:
                            continue
                        if has_reports:
                            break

                if not has_reports:
                    if ticks % 24 == 1:  # log roughly once per day at 1h cadence
                        log.info(
                            f"[FEEDBACK] tick {ticks}: pillar report dirs empty "
                            f"(BRS/AAC/NCC retired) — backing off to 1h poll"
                        )
                    try:
                        await asyncio.sleep(3600)
                    except asyncio.CancelledError:
                        raise
                    continue

                if base.exists():
                    note = scanner.scan_once()
                    if note:
                        log.info(
                            f"[FEEDBACK] tick {ticks}: {note.reports_consumed} "
                            f"reports → {note.synthesis_id}"
                        )
                        await self._apply_synthesis_to_mandates(note)
                    elif ticks % 12 == 1:  # once per hour, prove we're alive
                        log.info(f"[FEEDBACK] tick {ticks}: no new reports")
                else:
                    log.warning(f"[FEEDBACK] base dir vanished: {base}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception(f"[FEEDBACK] tick {ticks} error: {type(e).__name__}: {e!r}")

            try:
                await asyncio.sleep(300)
            except asyncio.CancelledError:
                raise

    async def _apply_synthesis_to_mandates(self, note) -> None:
        """
        Convert a SynthesisNote into PENDING_APPROVAL mandate proposals.

        Authority chain: feedback is interpreted → drafted as mandate proposals
        → NATRIX must approve before dispatch. We do NOT create ACTIVE mandates
        from feedback automatically — that would let downstream pillars steer
        their own next directives, violating the chain of command.

        Heuristics:
          - Each open blocker → one proposal targeting the reporting pillar
            with priority 7 (high). Title prefix: "RESOLVE: ".
          - Each suggested_adjustment → one proposal at priority 5.
        """
        from ..ncl_brain.models import MandateStatus, PillarType

        # Map pillar string → enum
        pillar_lookup = {p.name: p for p in PillarType}

        proposals: list[tuple[PillarType, int, str, str]] = []

        for blocker in note.open_blockers:
            pillar_str = blocker.get("pillar", "")
            pillar = pillar_lookup.get(pillar_str)
            if not pillar:
                continue
            blk = blocker.get("blocker", "").strip()
            if not blk:
                continue
            mid = blocker.get("mandate_id", "") or "unattributed"
            proposals.append(
                (
                    pillar,
                    7,
                    f"RESOLVE: {blk[:80]}",
                    f"Blocker reported by {pillar_str} (source mandate: {mid}). "
                    f"Synthesis note {note.synthesis_id}. Resolve and report back.",
                )
            )

        for adj in note.suggested_adjustments:
            adj_clean = (adj or "").strip()
            if not adj_clean:
                continue
            # NCL is standalone (BRS/AAC/NCC retired 2026-05-23). Adjustments
            # without explicit pillar tagging target the Brain itself for
            # in-process persistence.
            proposals.append(
                (
                    PillarType.NCL,
                    5,
                    f"FEEDBACK: {adj_clean[:80]}",
                    f"Pillar-suggested adjustment from synthesis {note.synthesis_id}: "
                    f"{adj_clean}",
                )
            )

        if not proposals:
            return

        created = 0
        for pillar, priority, title, objective in proposals:
            try:
                m = await self.brain.create_mandate(
                    pillar=pillar,
                    priority=priority,
                    title=title,
                    objective=objective,
                    success_criteria=[
                        f"Source synthesis: {note.synthesis_id}",
                        "NATRIX review and approval required",
                    ],
                    status=MandateStatus.PENDING_APPROVAL,
                )
                created += 1
                log.info(
                    f"[FEEDBACK] proposal created: {m.mandate_id} → {pillar.value} "
                    f"P{priority}: {title}"
                )
            except Exception as e:
                log.error(
                    f"[FEEDBACK] failed to create proposal for {pillar.value}: "
                    f"{type(e).__name__}: {e!r}"
                )

        log.info(
            f"[FEEDBACK] synthesis {note.synthesis_id} → {created}/{len(proposals)} "
            f"PENDING_APPROVAL mandates queued"
        )

    # ─── LOOP: Journal Reflection (10pm ET daily) ────────────────────

    async def _journal_reflection_loop(self) -> None:
        """
        Daily journal reflection — synthesizes the day's entries with intel
        and working context into actionable patterns and research queues.

        Runs at 10pm ET (22:00). Generates reflection, extracts tips,
        detects cross-entry patterns, and pushes summary to iPhone.
        """
        try:
            import pytz

            tz = pytz.timezone("US/Eastern")
        except ImportError:
            from datetime import timezone as tz_mod

            tz = tz_mod(timedelta(hours=-5))

        reflection_hour = 22  # 10pm ET
        last_run_date = None

        # Initial delay — let other loops warm up
        await asyncio.sleep(120)

        log.info(f"[JOURNAL] Reflection loop started — will fire at {reflection_hour}:00 ET")

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[JOURNAL] Emergency stop active — halting loop")
                break
            try:
                now = datetime.now(tz)
                today = now.date()

                if now.hour >= reflection_hour and last_run_date != today:
                    last_run_date = today
                    log.info(f"[JOURNAL] Generating daily reflection for {today}")

                    try:
                        # Gather intel context
                        intel_brief_data = None
                        if self.intelligence_engine:
                            try:
                                latest = await self.intelligence_engine.get_latest_brief()
                                if latest:
                                    intel_brief_data = latest.model_dump()
                            except Exception as _intel_err:
                                _warn_once_per_hour(
                                    "reflection_intel_fetch",
                                    "[REFLECTION] intel brief fetch swallowed: %s",
                                    _intel_err,
                                )

                        # Gather working context
                        wc_data = None
                        if self._working_context:
                            try:
                                wc_data = self._working_context.get_current()
                            except Exception as _wc_err:
                                _warn_once_per_hour(
                                    "reflection_wc_fetch",
                                    "[REFLECTION] working_context fetch swallowed: %s",
                                    _wc_err,
                                )

                        # Generate reflection
                        reflection = await self._reflection_engine.generate_daily_reflection(
                            intel_brief=intel_brief_data,
                            working_context=wc_data,
                        )

                        self._stats["journal_reflections_generated"] = (
                            self._stats.get("journal_reflections_generated", 0) + 1
                        )
                        self._stats["last_journal_reflection"] = datetime.now(
                            timezone.utc
                        ).isoformat()

                        # Push summary to iPhone (Wave 14X-3: re-wired through
                        # central AlertDispatcher after strike_point_orchestrator
                        # was archived 2026-05-23; was silently dead since then)
                        try:
                            from ..notifications.alert_dispatch import enqueue_alert

                            summary_text = f"{reflection.summary}\n"
                            if reflection.patterns_noticed:
                                summary_text += (
                                    "Patterns: " + ", ".join(reflection.patterns_noticed[:3]) + "\n"
                                )
                            if reflection.tomorrow_focus:
                                summary_text += (
                                    "Tomorrow: " + ", ".join(reflection.tomorrow_focus[:3])
                                )

                            enqueue_alert(
                                title=f"📓 Daily Reflection — {today}",
                                body=summary_text,
                                priority="3",
                                tags="memo",
                                dedup_key=f"journal_reflection:{reflection.reflection_id}",
                                source="journal_reflection",
                            )
                            log.info(
                                f"[JOURNAL] Reflection pushed to iPhone: {reflection.reflection_id}"
                            )
                        except Exception as e:
                            log.warning(f"[JOURNAL] Push failed: {e}")

                        await self._log_autonomous_event(
                            "journal_reflection",
                            {
                                "entries_count": reflection.entries_count,
                                "patterns": len(reflection.patterns_noticed),
                                "research_topics": len(reflection.research_queue),
                                "date": str(today),
                            },
                        )

                        log.info(
                            f"[JOURNAL] Reflection complete: {reflection.entries_count} entries → "
                            f"{len(reflection.patterns_noticed)} patterns, "
                            f"{len(reflection.research_queue)} research topics"
                        )

                    except Exception as e:
                        log.error(f"[JOURNAL] Reflection generation failed: {e}", exc_info=True)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[JOURNAL] Loop error: {e}", exc_info=True)

            await asyncio.sleep(300)  # Check every 5 minutes

    # ─── LOOP 10: Working Context Window ─────────────────────────────

    async def _working_context_loop(self) -> None:
        """
        Daily Working Context Window — assembles a curated high-salience
        memory context each morning, refreshes mid-day, and runs EOD
        promote/demote at midnight.

        Schedule:
          6am ET  → Full assembly (pull memory, councils, signals, mandates)
          noon ET → Mid-day refresh (re-score, pull new high-priority items)
          11pm ET → End-of-day promote/demote cycle

        NOTE: DailyContextWindow is initialized eagerly in start() so the
        /memory/working-context endpoint is available immediately after
        restart (no 30-second 503 window).
        """
        import pytz

        if not self._working_context:
            log.error("[WORKING-CTX] DailyContextWindow not initialized — loop exiting")
            return

        tz = pytz.timezone(os.environ.get("NCL_TIMEZONE", "America/New_York"))
        morning_hour = int(os.environ.get("NCL_WORKING_CTX_HOUR", "6"))
        midday_hour = 12
        eod_hour = 23

        last_assembly_date = None
        last_midday_date = None
        last_eod_date = None

        # Initial assembly on startup — no delay; object already exists
        try:
            ctx = await self._working_context.assemble()
            last_assembly_date = datetime.now(tz).date()
            log.info(f"[WORKING-CTX] Initial assembly: {len(ctx.items)} items")
        except Exception as e:
            log.error(f"[WORKING-CTX] Initial assembly failed: {e}", exc_info=True)

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[WORKING-CTX] Emergency stop active — halting loop")
                break

            try:
                now = datetime.now(tz)
                today = now.date()

                # Morning assembly (6am)
                if now.hour >= morning_hour and last_assembly_date != today:
                    last_assembly_date = today
                    log.info(f"[WORKING-CTX] Morning assembly for {today}")
                    try:
                        ctx = await self._working_context.assemble()
                        self._stats["working_ctx_assemblies"] = (
                            self._stats.get("working_ctx_assemblies", 0) + 1
                        )
                        self._stats["last_working_ctx"] = datetime.now(timezone.utc).isoformat()

                        await self._log_autonomous_event(
                            "working_context_assembled",
                            {
                                "date": str(today),
                                "items": len(ctx.items),
                                "themes": ctx.themes[:10],
                                "stats": ctx.stats,
                            },
                        )
                    except Exception as e:
                        log.error(f"[WORKING-CTX] Morning assembly failed: {e}", exc_info=True)

                # Mid-day refresh (noon)
                elif now.hour >= midday_hour and last_midday_date != today:
                    last_midday_date = today
                    log.info("[WORKING-CTX] Mid-day refresh")
                    try:
                        ctx = await self._working_context.refresh()
                        log.info(f"[WORKING-CTX] Refreshed: {len(ctx.items)} items")
                    except Exception as e:
                        log.error(f"[WORKING-CTX] Mid-day refresh failed: {e}", exc_info=True)

                # End-of-day promote/demote (11pm)
                elif now.hour >= eod_hour and last_eod_date != today:
                    last_eod_date = today
                    log.info("[WORKING-CTX] End-of-day cycle")
                    try:
                        eod_stats = await self._working_context.end_of_day()
                        log.info(f"[WORKING-CTX] EOD: {eod_stats}")
                        await self._log_autonomous_event("working_context_eod", eod_stats)
                    except Exception as e:
                        log.error(f"[WORKING-CTX] EOD cycle failed: {e}", exc_info=True)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[WORKING-CTX] Loop error: {e}", exc_info=True)

            # Check every 5 minutes
            await asyncio.sleep(300)

    # ─── LOOP: Night Watch (2am ET nightly health audit) ────────────

    async def _night_watch_loop(self) -> None:
        """
        Nightly 2am ET health audit — checks all services, loops, staleness,
        costs, LLM connectivity, and disk space. Pushes summary via ntfy.

        Startup catchup (added 2026-05-21): on first iteration, check whether
        Night Watch fired within the last 24h. If not, run immediately — full
        if we're inside the 2-6am ET window, otherwise catchup mode (skips
        LLM-expensive Phase 4 council + Phase 5 Sonnet synthesis). This
        prevents the prior bug where ~10 Brain restarts/day kept resetting
        the 24h sleep target, leaving Night Watch dead in production.
        """
        import pytz

        et = pytz.timezone("US/Eastern")

        log.info("[NIGHT-WATCH] Loop started — will fire at 2:00 AM ET nightly")

        # ── Startup catchup decision (first iteration only) ─────────────
        try:
            last_run_age_h = self._night_watch_last_run_age_hours()
            now_et_start = datetime.now(et)
            in_window = 2 <= now_et_start.hour < 6  # 2am-6am ET window

            if last_run_age_h is None or last_run_age_h >= 24.0:
                age_str = "never" if last_run_age_h is None else f"{last_run_age_h:.1f}h ago"
                if in_window:
                    log.info(
                        "[NIGHT-WATCH] Startup catchup triggered — last run was %s "
                        "and we are inside 2-6am ET window: running FULL cycle now",
                        age_str,
                    )
                    await self._night_watch_run_cycle(catchup=False)
                else:
                    log.info(
                        "[NIGHT-WATCH] Startup catchup triggered — last run was %s; "
                        "running CATCHUP cycle (Phase 1-3 only, skipping LLM-heavy 4/5)",
                        age_str,
                    )
                    await self._night_watch_run_cycle(catchup=True)
            else:
                log.info(
                    "[NIGHT-WATCH] Last run within 24h (%.1fh ago), sleeping until 2am ET",
                    last_run_age_h,
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("[NIGHT-WATCH] Startup catchup check failed: %s", e, exc_info=True)

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[NIGHT-WATCH] Emergency stop active — halting loop")
                break

            try:
                # Calculate seconds until next 2am ET
                now_et = datetime.now(et)
                target = now_et.replace(hour=2, minute=0, second=0, microsecond=0)
                if now_et >= target:
                    target += timedelta(days=1)
                sleep_secs = (target - now_et).total_seconds()
                log.info(f"[NIGHT-WATCH] Next run at {target.isoformat()} ({sleep_secs:.0f}s)")
                await asyncio.sleep(sleep_secs)
            except asyncio.CancelledError:
                raise

            try:
                await self._night_watch_run_cycle(catchup=False)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("[NIGHT-WATCH] Run cycle crashed: %s", e, exc_info=True)

    # ─── LOOP: Sliding-Window Dedup Scan (6h — replaces Night Watch M1) ─

    async def _dedup_scan_loop(self) -> None:
        """
        ncl-dedup-scan — every 6h, run a 500-newest-unit dedup pass and merge
        semantic duplicates above 0.92 cosine similarity.

        This replaces the in-line M1 step that used to run inside Night Watch's
        Phase 2 memory cycle. M1 was:
          (a) scoped to ALL units (9.7K-strong, growing) — not just the
              change frontier;
          (b) counting each pair twice (both A→B and B→A queries fired); and
          (c) timing out at 30min, blowing the full Night Watch budget.

        The new loop runs independently with its own cadence and a per-cycle
        timeout, so M1 mishap can never wedge Night Watch again. Stats land
        in ``self._stats["last_dedup_scan"]``, ``dedup_scan_runs``,
        ``dedup_scan_merged``, ``dedup_scan_merged_24h``.
        """
        from ..memory.dedup_scanner import run_dedup_scan

        # Startup grace — let bootstrap complete + the first BM25 build finish
        await asyncio.sleep(120)

        log.info("[DEDUP-SCAN] Loop started — cadence 6h, window 500 newest units")
        # 24h rolling counter for the "merged_24h" stat (list of (iso_ts, count))
        rolling_24h: list[tuple[str, int]] = []

        while self._running and not EMERGENCY_STOP_EVENT.is_set():
            # W10B-7: fresh per-cycle correlation id so the dedup scan's
            # candidate-check + merge log lines all share one id.
            set_request_id(loop_request_id("loop-dedup"))
            try:
                result = await run_dedup_scan(
                    self.brain,
                    window_size=500,
                    max_merges=200,
                )

                now_iso = datetime.now(timezone.utc).isoformat()
                merged = int(result.get("merged", 0) or 0)
                self._stats["last_dedup_scan"] = now_iso
                self._stats["dedup_scan_runs"] = self._stats.get("dedup_scan_runs", 0) + 1
                self._stats["dedup_scan_merged"] = self._stats.get("dedup_scan_merged", 0) + merged
                self._stats["last_dedup_scan_candidates"] = int(
                    result.get("candidates_checked", 0) or 0
                )
                self._stats["last_dedup_scan_dupes_found"] = int(result.get("dupes_found", 0) or 0)
                self._stats["last_dedup_scan_duration_s"] = float(
                    result.get("duration_s", 0.0) or 0.0
                )

                # Maintain 24h rolling merged total
                rolling_24h.append((now_iso, merged))
                cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                rolling_24h[:] = [
                    (ts, c) for ts, c in rolling_24h if datetime.fromisoformat(ts) >= cutoff
                ]
                self._stats["last_dedup_scan_merged_24h"] = sum(c for _, c in rolling_24h)

                try:
                    if hasattr(self, "_log_autonomous_event"):
                        await self._log_autonomous_event("dedup_scan", result)
                except Exception:
                    pass

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("[DEDUP-SCAN] cycle error: %s", e, exc_info=True)

            # 6h cadence
            await asyncio.sleep(21600)

    # ─── NIGHT WATCH HELPERS: startup catchup support ───────────────

    def _night_watch_last_run_age_hours(self) -> Optional[float]:
        """
        Return hours since the most recent Night Watch run, or None if never.

        Checks two sources in priority order:
          1. self._stats["last_night_watch"] (in-memory; lost across restarts)
          2. mtime of newest file in data/night-watch/ (survives restarts)
        """
        candidates: list[datetime] = []

        # Source 1: in-memory stat (only useful within the same process)
        last_iso = self._stats.get("last_night_watch")
        if last_iso:
            try:
                dt = datetime.fromisoformat(last_iso.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                candidates.append(dt)
            except Exception:
                pass

        # Source 2: newest file under data/night-watch/ (survives restarts)
        nw_dir = self.data_dir / "night-watch"
        if nw_dir.exists():
            try:
                newest_mtime = 0.0
                for p in nw_dir.iterdir():
                    if p.is_file():
                        try:
                            mt = p.stat().st_mtime
                            if mt > newest_mtime:
                                newest_mtime = mt
                        except OSError:
                            continue
                if newest_mtime > 0:
                    candidates.append(datetime.fromtimestamp(newest_mtime, tz=timezone.utc))
            except Exception:
                pass

        if not candidates:
            return None

        most_recent = max(candidates)
        age = datetime.now(timezone.utc) - most_recent
        return age.total_seconds() / 3600.0

    async def _night_watch_run_cycle(self, *, catchup: bool = False) -> None:
        """
        Execute one full Night Watch cycle.

        When catchup=True:
          - Phase 1 (health audit)       — runs (cheap, deterministic)
          - Phase 2 (memory cycle)       — runs (operates on stored data)
          - Phase 3 (intel correlation)  — runs (read-only analysis)
          - Phase 4 (mini-councils)      — SKIPPED (LLM-expensive)
          - Phase 5 (Sonnet synthesis)   — SKIPPED (LLM-expensive)
        """
        mode = "CATCHUP" if catchup else "FULL"
        log.info("[NIGHT-WATCH] === Cycle start (%s mode) ===", mode)

        # ── Phase 1: Run all health checks ────────────────────────
        issues: list[str] = []
        critical = False

        try:
            await self._nw_run_checks(issues)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(f"[NIGHT-WATCH] Check suite crashed: {e}", exc_info=True)
            issues.append(f"CHECK SUITE CRASH: {type(e).__name__}: {e}")

        # Determine severity
        critical = any("CRITICAL" in i or "CRASH" in i or "DEAD" in i for i in issues)
        has_warnings = len(issues) > 0

        # ── Push notification via ntfy (full runs only) ────────────
        if not catchup:
            try:
                await self._nw_push_notification(issues, critical, has_warnings)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[NIGHT-WATCH] Push notification failed: {e}", exc_info=True)
        else:
            log.info("[NIGHT-WATCH] Skipping ntfy push (catchup mode)")

        await self._log_autonomous_event(
            "night_watch",
            {
                "issues_count": len(issues),
                "critical": critical,
                "issues": issues[:20],
                "catchup": catchup,
            },
        )

        # Phase 2: Memory maintenance cycle
        memory_report: dict = {}
        try:
            memory_report = await self._night_watch_memory_cycle()
        except Exception as exc:
            log.error("[NIGHT-WATCH] Memory cycle failed: %s", exc)
            memory_report = {"error": str(exc)}

        # Phase 2.5: Temporal KG rebuild (Loop 8) — adds bi-temporal edges
        try:
            from ..memory.temporal import run_temporal_rebuild

            memory_report["temporal_rebuild"] = await run_temporal_rebuild(self.brain)
        except Exception as exc:
            log.warning("[NIGHT-WATCH] Temporal rebuild failed: %s", exc)
            memory_report["temporal_rebuild"] = {"error": str(exc)}

        # Phase 2.6: Procedural distillation (Loop 7) — mine successful chains
        # into reusable procedural skills. Skip in catchup mode (LLM-expensive).
        if catchup:
            memory_report["procedural"] = {"skipped": "catchup_mode"}
        else:
            try:
                from ..memory.procedural import run_procedural_distillation

                memory_report["procedural"] = await run_procedural_distillation(self.brain)
            except Exception as exc:
                log.warning("[NIGHT-WATCH] Procedural distillation failed: %s", exc)
                memory_report["procedural"] = {"error": str(exc)}

        # Phase 3: Intelligence correlation cycle
        intel_report: dict = {}
        try:
            intel_report = await self._night_watch_intel_cycle()
        except Exception as exc:
            log.error("[NIGHT-WATCH] Intel cycle failed: %s", exc)
            intel_report = {"error": str(exc)}

        # Phase 4: Council sessions (skipped in catchup mode)
        council_report: dict = {}
        if catchup:
            log.info("[NIGHT-WATCH] Skipping Phase 4 council cycle (catchup mode)")
            council_report = {"skipped": "catchup_mode"}
        else:
            try:
                council_report = await self._night_watch_council_cycle(memory_report, intel_report)
            except Exception as exc:
                log.error("[NIGHT-WATCH] Council cycle failed: %s", exc)
                council_report = {"error": str(exc)}

        # Phase 5: LLM-powered analyst (skipped in catchup mode)
        if catchup:
            log.info("[NIGHT-WATCH] Skipping Phase 5 Sonnet synthesis (catchup mode)")
        else:
            try:
                await self._night_watch_analyst(
                    issues,
                    len(issues) > 0,
                    critical,
                    memory_report=memory_report,
                    intel_report=intel_report,
                    council_report=council_report,
                )
            except Exception as exc:
                log.error("[NIGHT-WATCH] Analyst phase failed: %s", exc)

        # Phase 6: Portfolio Analyst Agent (defends the book overnight).
        # Mandate (NATRIX, verbatim): maximize capital inflow, limit
        # capital outflow + defend/invalidate thesises + enforce entry/
        # exit/mandate/watch-for contract on every position.
        # Skipped in catchup mode — this phase makes a Sonnet 4 call with
        # extended thinking (~$0.15/run) and must not fire on every Brain
        # restart-catchup. Full cycles only.
        if catchup:
            log.info("[NIGHT-WATCH] Skipping Phase 6 Portfolio Analyst (catchup mode)")
        else:
            try:
                await self._night_watch_portfolio_analyst()
            except Exception as exc:
                log.error("[NIGHT-WATCH] Portfolio Analyst phase failed: %s", exc)

        # ── Tracking: stamp last-run after any successful cycle ──────
        now_iso = datetime.now(timezone.utc).isoformat()
        self._stats["last_night_watch"] = now_iso
        if catchup:
            self._stats["last_night_watch_catchup"] = now_iso
            self._stats["night_watch_catchup_runs"] = (
                self._stats.get("night_watch_catchup_runs", 0) + 1
            )
        else:
            self._stats["last_night_watch_full"] = now_iso
            self._stats["night_watch_full_runs"] = self._stats.get("night_watch_full_runs", 0) + 1

        log.info("[NIGHT-WATCH] === Cycle complete (%s mode) ===", mode)

    async def force_night_watch_run(self, catchup: bool = True) -> dict:
        """
        Manual trigger for Night Watch — used by one-shot test scripts.

        Runs a single Night Watch cycle synchronously and returns a small
        status dict. Defaults to catchup=True so test runs do not burn the
        full LLM budget (~$1/run for Phase 4+5).

        Usage (from a Python script):
            import asyncio
            from runtime.brain import Brain  # or however Brain is bootstrapped
            scheduler = brain.autonomous_scheduler
            asyncio.run(scheduler.force_night_watch_run(catchup=True))
        """
        log.info("[NIGHT-WATCH] force_night_watch_run invoked (catchup=%s)", catchup)
        t0 = datetime.now(timezone.utc)
        try:
            await self._night_watch_run_cycle(catchup=catchup)
            return {
                "ok": True,
                "catchup": catchup,
                "started_at": t0.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": (datetime.now(timezone.utc) - t0).total_seconds(),
            }
        except Exception as e:
            log.error("[NIGHT-WATCH] force_night_watch_run failed: %s", e, exc_info=True)
            return {
                "ok": False,
                "catchup": catchup,
                "error": f"{type(e).__name__}: {e}",
                "started_at": t0.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }

    # ─── NIGHT WATCH MEMORY CYCLE: Phase 2 memory maintenance ──────

    async def _night_watch_memory_cycle(self) -> dict:
        """Shim — carved-out body lives in `night_watch/memory_cycle.py` (W10C-7)."""
        from .night_watch.memory_cycle import run as _run

        return await _run(self)

    # ─── NIGHT WATCH INTEL CYCLE: Phase 3 intelligence correlation ──

    async def _night_watch_intel_cycle(self) -> dict:
        """Shim — carved-out body lives in `night_watch/intel_cycle.py` (W10C-8)."""
        from .night_watch.intel_cycle import run as _run

        return await _run(self)

    async def _nw_run_checks(self, issues: list[str]) -> None:
        """Run all Night Watch health checks, appending issues found."""
        import httpx

        auth_header = "Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU"

        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            # ── 1. Service health ──────────────────────────────────────
            try:
                resp = await client.get(
                    "http://localhost:8800/health",
                    headers={"Authorization": auth_header},
                )
                if resp.status_code != 200:
                    issues.append(f"CRITICAL: /health returned HTTP {resp.status_code}")
                else:
                    data = resp.json()
                    status = data.get("status", "unknown")
                    if status != "ok" and status != "healthy":
                        issues.append(f"WARNING: /health status={status}")
            except Exception as e:
                issues.append(f"CRITICAL: /health unreachable — {type(e).__name__}: {e}")

            # ── 2. Scheduler tasks alive ───────────────────────────────
            try:
                dead_tasks = [
                    t.get_name()
                    for t in self._tasks
                    if t.done() and t.get_name() != "ncl-night-watch"
                ]
                if dead_tasks:
                    issues.append(f"CRITICAL: DEAD scheduler tasks: {', '.join(dead_tasks)}")
            except Exception as e:
                issues.append(f"WARNING: Could not check scheduler tasks — {e}")

            # ── 3. Awarebot sub-tasks alive ────────────────────────────
            try:
                if self.awarebot and hasattr(self.awarebot, "_tasks"):
                    dead_ab = [t.get_name() for t in self.awarebot._tasks if t.done()]
                    if dead_ab:
                        issues.append(f"CRITICAL: DEAD awarebot sub-tasks: {', '.join(dead_ab)}")
                elif not self.awarebot:
                    issues.append("WARNING: Awarebot not initialized")
            except Exception as e:
                issues.append(f"WARNING: Could not check awarebot tasks — {e}")

            # ── 4. Staleness checks ────────────────────────────────────
            try:
                resp = await client.get(
                    "http://localhost:8800/autonomous/status",
                    headers={"Authorization": auth_header},
                )
                if resp.status_code == 200:
                    auto_data = resp.json()
                    now_utc = datetime.now(timezone.utc)

                    stale_checks = [
                        ("last_scan", 10 * 60, "Scan"),
                        ("last_prediction", 3600, "Prediction"),
                        ("last_intel_brief", 5 * 3600, "Brief"),
                    ]
                    for key, max_age_s, label in stale_checks:
                        ts_str = auto_data.get(key)
                        if not ts_str:
                            issues.append(f"WARNING: {label} timestamp missing (key={key})")
                            continue
                        try:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            age = (now_utc - ts).total_seconds()
                            if age > max_age_s:
                                issues.append(
                                    f"WARNING: {label} stale — last run {age / 60:.0f}m ago "
                                    f"(threshold {max_age_s / 60:.0f}m)"
                                )
                        except Exception:
                            pass
                else:
                    issues.append(f"WARNING: /autonomous/status returned HTTP {resp.status_code}")
            except Exception as e:
                issues.append(f"WARNING: Staleness check failed — {type(e).__name__}: {e}")

            # ── 5. Cost summary ────────────────────────────────────────
            try:
                from ..cost_tracker import get_tracker

                tracker = await get_tracker()
                summary = await tracker.get_daily_summary()
                for source, info in summary.get("sources", {}).items():
                    pct = info.get("percent_used", 0)
                    if pct >= 80:
                        issues.append(
                            f"WARNING: Cost budget {source} at {pct:.0f}% "
                            f"(${info.get('spent_usd', 0):.2f}/${info.get('budget_usd', 0):.2f})"
                        )
            except Exception as e:
                issues.append(f"WARNING: Cost check failed — {type(e).__name__}: {e}")

            # ── 6. LLM provider connectivity ───────────────────────────
            llm_endpoints = [
                ("Anthropic", "https://api.anthropic.com"),
                ("xAI", "https://api.x.ai"),
                ("Google", "https://generativelanguage.googleapis.com"),
            ]
            for name, url in llm_endpoints:
                try:
                    resp = await client.head(url)
                    # Any HTTP response means TCP connectivity is fine
                except Exception as e:
                    issues.append(f"WARNING: {name} API unreachable — {type(e).__name__}: {e}")

        # ── 7. Disk space ──────────────────────────────────────────
        try:
            data_path = Path.home() / "NCL" / "data"
            if not data_path.exists():
                data_path = self.data_dir
            st = os.statvfs(str(data_path))
            free_bytes = st.f_bavail * st.f_frsize
            free_gb = free_bytes / (1024**3)
            if free_gb < 1.0:
                issues.append(f"CRITICAL: Disk space low — {free_gb:.2f} GB free on data volume")
        except Exception as e:
            issues.append(f"WARNING: Disk check failed — {type(e).__name__}: {e}")

    async def _nw_push_notification(
        self, issues: list[str], critical: bool, has_warnings: bool
    ) -> None:
        """Push Night Watch results via ntfy."""
        import httpx

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        if not has_warnings:
            title = "Night Watch — All Clear"
            body = f"[{now_str}]\n✅ All systems healthy. No issues detected."
            priority = "3"
            tags = "brain,white_check_mark"
        elif critical:
            title = "Night Watch — CRITICAL"
            body = f"[{now_str}]\n\U0001f6a8 {len(issues)} issue(s) found:\n"
            body += "\n".join(f"  • {i}" for i in issues)
            priority = "5"
            tags = "brain,rotating_light"
        else:
            title = "Night Watch — Warnings"
            body = f"[{now_str}]\n⚠️ {len(issues)} issue(s) found:\n"
            body += "\n".join(f"  • {i}" for i in issues)
            priority = "4"
            tags = "brain,warning"

        # Truncate body if too long for ntfy (max ~4KB)
        if len(body) > 3800:
            body = body[:3800] + "\n  ... (truncated)"

        # Migrated 2026-05-21: enqueue via central AlertDispatcher.
        try:
            enqueue_alert(
                title=title,
                body=body,
                priority=priority,
                tags=tags,
                # Night Watch runs once per night — dedup by date so accidental
                # double-invocations within an hour collapse.
                dedup_key=f"night-watch:{datetime.now(timezone.utc).date().isoformat()}:{priority}",
                source="night_watch",
            )
            log.info(f"[NIGHT-WATCH] Push enqueued: {title} ({len(issues)} issues)")
            return
        except Exception as enq_err:
            log.warning(f"[NIGHT-WATCH] dispatcher unavailable, direct POST fallback: {enq_err}")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                resp = await client.post(
                    "https://ntfy.sh/ncl-natrix-intel-7x9k",
                    content=body.encode("utf-8"),
                    headers={
                        "Content-Type": "text/plain; charset=utf-8",
                        "Title": title.encode("ascii", "replace").decode("ascii"),
                        "Priority": priority,
                        "Tags": tags,
                    },
                )
                resp.raise_for_status()
                log.info(f"[NIGHT-WATCH] Push sent (fallback): {title} ({len(issues)} issues)")
        except Exception as e:
            log.error(f"[NIGHT-WATCH] ntfy push failed: {e}")

    # ─── NIGHT WATCH COUNCIL CYCLE: Phase 4 mini-councils ──────────

    async def _nw_collect_portfolio_data(self) -> dict:
        """Collect portfolio data for the Night Watch portfolio council."""
        data: dict = {
            "total_value": 0,
            "daily_pnl": 0,
            "positions_summary": [],
            "open_paper_trades": [],
            "paper_stats": {},
            "weekly_performance": {},
            "available": False,
        }

        try:
            from ..portfolio.paper_routes import _engine as _paper_engine
            from ..portfolio.portfolio_routes import _portfolio_manager

            if _portfolio_manager is not None:
                data["available"] = True
                summary = _portfolio_manager.get_summary()
                data["total_value"] = summary.get("total_value", 0)
                data["daily_pnl"] = summary.get("daily_pl", 0)
                data["accounts_summary"] = [
                    f"{a.get('broker', '?')}/{a.get('label', '?')}: ${a.get('value', 0):,.0f}"
                    for a in summary.get("accounts", [])
                ][:6]
                data["allocation"] = summary.get("allocation", {}).get("by_asset_class", {})

                # Top 5 positions by weight
                positions = _portfolio_manager.get_positions()
                data["positions_summary"] = [
                    {
                        "symbol": p.get("symbol", "?"),
                        "broker": p.get("broker", "?"),
                        "market_value": p.get("market_value", 0),
                        "daily_pl_pct": p.get("daily_pl_pct", 0),
                        "unrealized_pl_pct": p.get("unrealized_pl_pct", 0),
                        "weight_pct": p.get("weight_pct", 0),
                    }
                    for p in positions[:5]
                ]

                # Weekly performance
                try:
                    perf = _portfolio_manager.get_performance("1W")
                    data["weekly_performance"] = {
                        "change": perf.get("change", 0),
                        "change_pct": perf.get("change_pct", 0),
                        "data_points": len(perf.get("data_points", [])),
                    }
                except Exception:
                    pass

            if _paper_engine is not None:
                try:
                    data["paper_stats"] = _paper_engine.get_stats()
                    open_trades = _paper_engine.get_trades(status="open")
                    data["open_paper_trades"] = [
                        {
                            "symbol": t.get("symbol", "?"),
                            "direction": t.get("direction", "?"),
                            "strategy": t.get("strategy", "?"),
                            "entry_price": t.get("entry_price", 0),
                            "r_multiple": t.get("r_multiple", 0),
                            "unrealized_pl": t.get("unrealized_pl", 0),
                        }
                        for t in open_trades[:10]
                    ]
                except Exception:
                    pass

        except ImportError:
            data["error"] = "Portfolio modules not available"
        except Exception as e:
            data["error"] = str(e)

        return data

    async def _nw_collect_journal_data(self) -> dict:
        """Collect journal data for the Night Watch journal council."""
        data: dict = {
            "recent_entries_count": 0,
            "weekly_patterns": {},
            "research_queue": [],
            "open_questions": [],
            "analytics_summary": {},
            "available": False,
        }

        journal_store = self._journal_store or getattr(self.brain, "journal_store", None)
        if not journal_store:
            data["error"] = "Journal store not available"
            return data

        try:
            data["available"] = True

            # Recent reflections (7 days)
            reflections = await journal_store.get_recent_reflections(days=7)
            reflection_summaries = []
            for r in reflections[:5]:
                summary_text = ""
                if hasattr(r, "highlights") and r.highlights:
                    summary_text = "; ".join(r.highlights[:3])
                elif hasattr(r, "summary") and r.summary:
                    summary_text = r.summary[:200]
                elif hasattr(r, "content") and r.content:
                    summary_text = r.content[:200]
                reflection_summaries.append(
                    {
                        "date": getattr(r, "date", "?"),
                        "summary": summary_text,
                    }
                )
                # Extract research queue items
                if hasattr(r, "research_queue") and r.research_queue:
                    data["research_queue"].extend(r.research_queue[:3])
                if hasattr(r, "open_questions") and r.open_questions:
                    data["open_questions"].extend(r.open_questions[:3])
            data["weekly_patterns"] = reflection_summaries

            # 30-day analytics
            analytics = await journal_store.get_analytics(days=30)
            data["analytics_summary"] = {
                "total_entries": analytics.get("total_entries", 0),
                "total_words": analytics.get("total_words", 0),
                "current_streak": analytics.get("current_streak_days", 0),
                "top_tags": dict(list(analytics.get("top_tags", {}).items())[:10]),
                "entries_by_type": analytics.get("entries_by_type", {}),
                "avg_importance": round(analytics.get("avg_importance", 0), 1),
            }
            data["recent_entries_count"] = analytics.get("total_entries", 0)

            # Recent entries (last 20)
            entries = await journal_store.get_entries(limit=20)
            entry_titles = [
                f"[{e.entry_type.value}] {e.title}"
                for e in entries[:10]
                if hasattr(e, "title") and e.title
            ]
            data["recent_entry_titles"] = entry_titles

            # Quick stats
            stats = journal_store.get_stats()
            data["stats"] = stats

        except Exception as e:
            data["error"] = str(e)

        # Truncate lists to keep prompt size manageable
        data["research_queue"] = data["research_queue"][:5]
        data["open_questions"] = data["open_questions"][:5]
        return data

    async def _night_watch_council_cycle(
        self,
        memory_report: dict,
        intel_report: dict,
    ) -> dict:
        """
        Night Watch Phase 4 — Mini-Council Sessions.

        Runs 4 lightweight 2-model debates (Claude + Grok) on:
          1. Memory audit findings
          2. Intelligence correlation findings
          3. Portfolio risk assessment
          4. Journal & strategy review

        Each debate uses 3 sequential LLM calls:
          Claude analysis → Grok rebuttal → Claude synthesis

        Total budget: ~$0.50/night (~$0.10-0.15 per council).
        """
        import time

        import httpx

        from ..cost_tracker import get_tracker

        t0 = time.monotonic()
        report = {
            "councils_run": 0,
            "memory_council": None,
            "intel_council": None,
            "portfolio_council": None,
            "journal_council": None,
            "portfolio_data": {},
            "journal_data": {},
            "total_cost_usd": 0.0,
            "duration_seconds": 0.0,
            "errors": [],
        }

        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        xai_key = os.environ.get("XAI_API_KEY", "")
        if not anthropic_key:
            report["errors"].append("No ANTHROPIC_API_KEY — skipping councils")
            report["duration_seconds"] = time.monotonic() - t0
            return report
        if not xai_key:
            report["errors"].append("No XAI_API_KEY — councils will use Claude-only fallback")

        tracker = await get_tracker()
        COUNCIL_TIMEOUT = 300  # 5 minutes per council  # noqa: N806

        log.info("[NIGHT-WATCH/COUNCIL] Starting council cycle (4 mini-councils)")

        # ── Helper: 3-call debate pattern ────────────────────────────
        async def _run_mini_council(
            topic: str,
            prompt: str,
            label: str,
        ) -> tuple[str | None, float]:
            """
            Run a 3-call debate: Claude analysis → Grok rebuttal → Claude synthesis.
            Returns (synthesis_text, total_cost_usd).
            """
            total_cost = 0.0

            # Budget check for the full council (~$0.15)
            if not await tracker.can_spend("anthropic", 0.10):
                log.warning("[NIGHT-WATCH/COUNCIL] Anthropic budget exceeded — skipping %s", label)
                return None, 0.0

            anthropic_headers = {
                "x-api-key": anthropic_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }

            # Call 1: Claude Sonnet analysis
            claude_text = ""
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
                    resp = await client.post(
                        "https://api.anthropic.com/v1/messages",
                        headers=anthropic_headers,
                        json={
                            "model": "claude-sonnet-4",
                            "max_tokens": 1024,
                            "messages": [{"role": "user", "content": prompt}],
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    claude_text = data["content"][0]["text"]
                    usage = data.get("usage", {})
                    cost = (
                        usage.get("input_tokens", 0) * 3.00 + usage.get("output_tokens", 0) * 15.00
                    ) / 1_000_000
                    total_cost += cost
                    await tracker.record(
                        "anthropic",
                        cost,
                        "night_watch_council",
                        f"NW council {label} -- Sonnet analysis",
                        {"model": "claude-sonnet-4", "council": label, "step": "analysis"},
                    )
                    log.info(
                        "[NIGHT-WATCH/COUNCIL] %s -- Sonnet analysis done ($%.4f)", label, cost
                    )
            except Exception as e:
                log.error("[NIGHT-WATCH/COUNCIL] %s — Claude analysis failed: %s", label, e)
                return None, total_cost

            # Call 2: Grok rebuttal (skip if no xAI key)
            grok_text = ""
            if xai_key:
                try:
                    if not await tracker.can_spend("xai", 0.05):
                        log.warning(
                            "[NIGHT-WATCH/COUNCIL] xAI budget exceeded — skipping Grok rebuttal for %s",  # noqa: E501
                            label,
                        )
                    else:
                        grok_prompt = (
                            f"You are a contrarian analyst on the NCL Night Watch council. "
                            f"Topic: {topic}\n\n"
                            f"Another analyst (Claude) provided this assessment:\n\n"
                            f"{claude_text[:1500]}\n\n"
                            f"Your job: Challenge this analysis. What did they miss? "
                            f"What risks are they underestimating? What data would change "
                            f"the conclusions? Where is the reasoning weak? Be specific and "
                            f"constructive. 3-5 bullet points."
                        )
                        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                            resp = await client.post(
                                "https://api.x.ai/v1/chat/completions",
                                headers={
                                    "Authorization": f"Bearer {xai_key}",
                                    "Content-Type": "application/json",
                                },
                                json={
                                    "model": "grok-3",
                                    "max_tokens": 1024,
                                    "messages": [{"role": "user", "content": grok_prompt}],
                                },
                            )
                            resp.raise_for_status()
                            grok_data = resp.json()
                            grok_text = grok_data["choices"][0]["message"]["content"]
                            # Grok cost estimate: ~$5/1M input, ~$15/1M output
                            grok_usage = grok_data.get("usage", {})
                            grok_cost = (
                                grok_usage.get("prompt_tokens", 0) * 5.0
                                + grok_usage.get("completion_tokens", 0) * 15.0
                            ) / 1_000_000
                            total_cost += grok_cost
                            await tracker.record(
                                "xai",
                                grok_cost,
                                "night_watch_council",
                                f"NW council {label} — Grok rebuttal",
                                {"model": "grok-3", "council": label, "step": "rebuttal"},
                            )
                            log.info(
                                "[NIGHT-WATCH/COUNCIL] %s — Grok rebuttal done ($%.4f)",
                                label,
                                grok_cost,
                            )
                except Exception as e:
                    log.error("[NIGHT-WATCH/COUNCIL] %s — Grok rebuttal failed: %s", label, e)
                    grok_text = "(Grok rebuttal unavailable)"

            # Call 3: Claude Opus synthesis (top-tier reasoning for council chair)
            try:
                if not await tracker.can_spend("anthropic", 0.20):
                    log.warning(
                        "[NIGHT-WATCH/COUNCIL] Budget exceeded -- returning analysis without synthesis for %s",  # noqa: E501
                        label,
                    )
                    return claude_text, total_cost

                council_synthesis_prompt = (
                    f"You are the chair of the NCL Night Watch council. "
                    f"Synthesize these two perspectives on: {topic}\n\n"
                    f"=== ANALYST (Claude) ===\n{claude_text[:1200]}\n\n"
                    f"=== CONTRARIAN (Grok) ===\n{grok_text[:1200] if grok_text else '(No rebuttal available)'}\n\n"  # noqa: E501
                    f"Produce a synthesis:\n"
                    f"1. KEY FINDINGS (3-5 bullets -- what both agree on)\n"
                    f"2. CONTESTED POINTS (where they disagree and why it matters)\n"
                    f"3. BLIND SPOTS (what neither addressed)\n"
                    f"4. ACTION ITEMS (2-3 specific next steps for tomorrow)\n"
                    f"Be concise. Total response under 400 words."
                )

                async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                    resp = await client.post(
                        "https://api.anthropic.com/v1/messages",
                        headers=anthropic_headers,
                        json={
                            "model": "claude-opus-4-6",
                            "max_tokens": 1024,
                            "messages": [{"role": "user", "content": council_synthesis_prompt}],
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    synthesis = data["content"][0]["text"]
                    usage = data.get("usage", {})
                    cost = (
                        usage.get("input_tokens", 0) * 15.00 + usage.get("output_tokens", 0) * 75.00
                    ) / 1_000_000
                    total_cost += cost
                    await tracker.record(
                        "anthropic",
                        cost,
                        "night_watch_council",
                        f"NW council {label} -- Opus synthesis",
                        {"model": "claude-opus-4-6", "council": label, "step": "synthesis"},
                    )
                    log.info(
                        "[NIGHT-WATCH/COUNCIL] %s -- Opus synthesis done ($%.4f, total=$%.4f)",
                        label,
                        cost,
                        total_cost,
                    )
                    return synthesis, total_cost
            except Exception as e:
                log.error("[NIGHT-WATCH/COUNCIL] %s -- synthesis failed: %s", label, e)
                return claude_text, total_cost  # Fall back to raw Sonnet analysis

        # ── Collect supplemental data ────────────────────────────────
        portfolio_data = await self._nw_collect_portfolio_data()
        journal_data = await self._nw_collect_journal_data()
        report["portfolio_data"] = portfolio_data
        report["journal_data"] = journal_data

        # ── Council 1: Memory Review ─────────────────────────────────
        try:
            log.info("[NIGHT-WATCH/COUNCIL] Running memory council...")
            mem_summary_lines = []
            if memory_report.get("error"):
                mem_summary_lines.append(f"Memory cycle error: {memory_report['error']}")
            else:
                mem_summary_lines.append(
                    f"Duplicates found: {memory_report.get('duplicates_found', 0)}"
                )
                mem_summary_lines.append(
                    f"Units re-scored: {memory_report.get('units_rescored', 0)}"
                )
                mem_summary_lines.append(
                    f"Entities extracted: {memory_report.get('entities_extracted', 0)}"
                )
                mem_summary_lines.append(
                    f"Stale facts found: {memory_report.get('stale_facts_found', 0)}"
                )
                kg = memory_report.get("kg_stats", {})
                mem_summary_lines.append(
                    f"Knowledge graph: {kg.get('nodes', 0)} nodes, {kg.get('edges', 0)} edges, {kg.get('components', 0)} components"  # noqa: E501
                )
                mem_summary_lines.append(
                    f"Entity normalizations: {memory_report.get('normalizations', 0)}"
                )
                mem_summary_lines.append(
                    f"Cycle cost: ${memory_report.get('total_cost_usd', 0):.4f}"
                )
                errors = memory_report.get("errors", [])
                if errors:
                    mem_summary_lines.append(f"Errors: {'; '.join(errors[:3])}")

            mem_prompt = (
                "You are an AI memory systems analyst on the NCL Night Watch council. "
                "Review tonight's memory maintenance findings for an autonomous AI brain.\n\n"
                "MEMORY MAINTENANCE REPORT:\n" + "\n".join(mem_summary_lines) + "\n\n"
                "Questions to address:\n"
                "- What patterns do you see in the knowledge base health?\n"
                "- Are there concerning trends in duplicate rates or stale facts?\n"
                "- What knowledge gaps likely exist based on the entity/KG stats?\n"
                "- What should be prioritized for tomorrow's memory operations?\n"
                "Be concise — 5-8 bullet points."
            )

            synthesis, cost = await asyncio.wait_for(
                _run_mini_council("Night Watch Memory Audit", mem_prompt, "memory"),
                timeout=COUNCIL_TIMEOUT,
            )
            if synthesis:
                report["memory_council"] = synthesis
                report["councils_run"] += 1
            report["total_cost_usd"] += cost
        except asyncio.TimeoutError:
            report["errors"].append("Memory council timed out (5min)")
            log.error("[NIGHT-WATCH/COUNCIL] Memory council timed out")
        except Exception as e:
            report["errors"].append(f"Memory council failed: {e}")
            log.error("[NIGHT-WATCH/COUNCIL] Memory council failed: %s", e)

        # ── Council 2: Intel Review ──────────────────────────────────
        try:
            log.info("[NIGHT-WATCH/COUNCIL] Running intel council...")
            intel_summary_lines = []
            if intel_report.get("error"):
                intel_summary_lines.append(f"Intel cycle error: {intel_report['error']}")
            else:
                intel_summary_lines.append(
                    f"Missed correlations: {intel_report.get('missed_correlations', 0)}"
                )
                blind_spots = intel_report.get("blind_spots", [])
                if blind_spots:
                    intel_summary_lines.append(f"Blind spots: {', '.join(blind_spots[:8])}")
                intel_summary_lines.append(
                    f"Over-scored signals: {intel_report.get('over_scored_signals', 0)}"
                )
                intel_summary_lines.append(
                    f"Under-scored signals: {intel_report.get('under_scored_signals', 0)}"
                )
                intel_summary_lines.append(
                    f"Stale predictions: {intel_report.get('predictions_stale', 0)}"
                )
                pma = intel_report.get("per_model_accuracy", {})
                if pma:
                    intel_summary_lines.append(
                        "Per-model accuracy: " + ", ".join(f"{m}={a}" for m, a in pma.items())
                    )
                suggestions = intel_report.get("council_suggestions", [])
                if suggestions:
                    intel_summary_lines.append(f"Suggested topics: {'; '.join(suggestions[:3])}")
                cost_opt = intel_report.get("cost_optimization", "")
                if cost_opt:
                    intel_summary_lines.append(f"Cost optimization: {cost_opt[:150]}")

            intel_prompt = (
                "You are an intelligence analyst on the NCL Night Watch council. "
                "Review tonight's intelligence correlation findings for an autonomous AI brain.\n\n"
                "INTELLIGENCE CORRELATION REPORT:\n" + "\n".join(intel_summary_lines) + "\n\n"
                "Questions to address:\n"
                "- What intelligence are we missing? Where are the blind spots?\n"
                "- Which prediction models need calibration based on accuracy data?\n"
                "- What topics warrant a full council debate tomorrow?\n"
                "- Are signal scoring thresholds correctly calibrated?\n"
                "- What should we investigate tomorrow?\n"
                "Be concise — 5-8 bullet points."
            )

            synthesis, cost = await asyncio.wait_for(
                _run_mini_council("Night Watch Intelligence Review", intel_prompt, "intel"),
                timeout=COUNCIL_TIMEOUT,
            )
            if synthesis:
                report["intel_council"] = synthesis
                report["councils_run"] += 1
            report["total_cost_usd"] += cost
        except asyncio.TimeoutError:
            report["errors"].append("Intel council timed out (5min)")
            log.error("[NIGHT-WATCH/COUNCIL] Intel council timed out")
        except Exception as e:
            report["errors"].append(f"Intel council failed: {e}")
            log.error("[NIGHT-WATCH/COUNCIL] Intel council failed: %s", e)

        # ── Council 3: Portfolio Review ───────────────────────────────
        try:
            log.info("[NIGHT-WATCH/COUNCIL] Running portfolio council...")
            port_summary_lines = []
            if not portfolio_data.get("available"):
                port_summary_lines.append(
                    f"Portfolio not available: {portfolio_data.get('error', 'not initialized')}"
                )
            else:
                port_summary_lines.append(
                    f"Total portfolio value: ${portfolio_data.get('total_value', 0):,.2f}"
                )
                port_summary_lines.append(f"Daily P&L: ${portfolio_data.get('daily_pnl', 0):,.2f}")
                accts = portfolio_data.get("accounts_summary", [])
                if accts:
                    port_summary_lines.append(f"Accounts: {'; '.join(accts)}")
                positions = portfolio_data.get("positions_summary", [])
                if positions:
                    port_summary_lines.append("Top positions by weight:")
                    for p in positions:
                        port_summary_lines.append(
                            f"  {p.get('symbol', '?')} ({p.get('broker', '?')}): "
                            f"${p.get('market_value', 0):,.0f}, "
                            f"wt={p.get('weight_pct', 0):.1f}%, "
                            f"day={p.get('daily_pl_pct', 0):+.1f}%"
                        )
                alloc = portfolio_data.get("allocation", {})
                if alloc:
                    port_summary_lines.append(f"Asset allocation: {json.dumps(alloc)[:200]}")
                wp = portfolio_data.get("weekly_performance", {})
                if wp:
                    port_summary_lines.append(f"Weekly change: {wp.get('change_pct', 0):+.2f}%")
                paper = portfolio_data.get("paper_stats", {})
                if paper:
                    port_summary_lines.append(
                        f"Paper trading: {paper.get('total_trades', 0)} trades, "
                        f"win rate {paper.get('win_rate', 0):.0f}%, "
                        f"PF {paper.get('profit_factor', 0):.2f}"
                    )
                open_papers = portfolio_data.get("open_paper_trades", [])
                if open_papers:
                    port_summary_lines.append(f"Open paper trades: {len(open_papers)}")
                    for pt in open_papers[:5]:
                        port_summary_lines.append(
                            f"  {pt.get('symbol', '?')} {pt.get('direction', '?')} "
                            f"({pt.get('strategy', '?')}): R={pt.get('r_multiple', 0):+.1f}"
                        )

            portfolio_prompt = (
                "You are a risk analyst on the NCL Night Watch council. "
                "Review the current portfolio state for risk assessment and awareness. "
                "This is ANALYSIS ONLY — never suggest specific trades or financial actions.\n\n"
                "PORTFOLIO SNAPSHOT:\n" + "\n".join(port_summary_lines) + "\n\n"
                "Questions to address:\n"
                "- What is our current risk exposure? Any concentration risks?\n"
                "- Are any positions requiring immediate attention (large drawdowns, overweight)?\n"
                "- How are paper trades performing relative to graduation criteria?\n"
                "- What market signals or macro factors should we watch tomorrow?\n"
                "- Is position sizing appropriate across the portfolio?\n"
                "IMPORTANT: Analysis and risk assessment only. No trade recommendations.\n"
                "Be concise — 5-8 bullet points."
            )

            synthesis, cost = await asyncio.wait_for(
                _run_mini_council("Night Watch Portfolio Review", portfolio_prompt, "portfolio"),
                timeout=COUNCIL_TIMEOUT,
            )
            if synthesis:
                report["portfolio_council"] = synthesis
                report["councils_run"] += 1
            report["total_cost_usd"] += cost
        except asyncio.TimeoutError:
            report["errors"].append("Portfolio council timed out (5min)")
            log.error("[NIGHT-WATCH/COUNCIL] Portfolio council timed out")
        except Exception as e:
            report["errors"].append(f"Portfolio council failed: {e}")
            log.error("[NIGHT-WATCH/COUNCIL] Portfolio council failed: %s", e)

        # ── Council 4: Journal & Strategy Review ─────────────────────
        try:
            log.info("[NIGHT-WATCH/COUNCIL] Running journal council...")
            journal_summary_lines = []
            if not journal_data.get("available"):
                journal_summary_lines.append(
                    f"Journal not available: {journal_data.get('error', 'not initialized')}"
                )
            else:
                analytics = journal_data.get("analytics_summary", {})
                journal_summary_lines.append(f"Entries (30d): {analytics.get('total_entries', 0)}")
                journal_summary_lines.append(f"Words written: {analytics.get('total_words', 0):,}")
                journal_summary_lines.append(
                    f"Current streak: {analytics.get('current_streak', 0)} days"
                )
                journal_summary_lines.append(
                    f"Avg importance: {analytics.get('avg_importance', 0):.1f}"
                )
                top_tags = analytics.get("top_tags", {})
                if top_tags:
                    journal_summary_lines.append(
                        f"Top tags: {', '.join(list(top_tags.keys())[:8])}"
                    )
                by_type = analytics.get("entries_by_type", {})
                if by_type:
                    journal_summary_lines.append(f"Entry types: {json.dumps(by_type)}")

                reflections = journal_data.get("weekly_patterns", [])
                if reflections:
                    journal_summary_lines.append("\nRecent reflections:")
                    for r in reflections[:3]:
                        journal_summary_lines.append(
                            f"  [{r.get('date', '?')}]: {r.get('summary', 'N/A')[:150]}"
                        )

                rq = journal_data.get("research_queue", [])
                if rq:
                    journal_summary_lines.append(
                        f"\nResearch queue: {'; '.join(str(q) for q in rq[:5])}"
                    )
                oq = journal_data.get("open_questions", [])
                if oq:
                    journal_summary_lines.append(
                        f"Open questions: {'; '.join(str(q) for q in oq[:5])}"
                    )

                titles = journal_data.get("recent_entry_titles", [])
                if titles:
                    journal_summary_lines.append(f"\nRecent entries: {'; '.join(titles[:8])}")

            journal_prompt = (
                "You are a strategic thinking analyst on the NCL Night Watch council. "
                "Review this week's journal patterns, research queues, and decision history "
                "for an autonomous AI brain operator.\n\n"
                "JOURNAL & STRATEGY DATA:\n" + "\n".join(journal_summary_lines) + "\n\n"
                "Questions to address:\n"
                "- What themes are emerging across recent journal entries?\n"
                "- Which research questions remain unresolved and should be prioritized?\n"
                "- Are there blind spots in the operator's thinking?\n"
                "- What should be tomorrow's focus areas based on patterns?\n"
                "- Is the journal practice itself healthy (streak, frequency, depth)?\n"
                "Be concise — 5-8 bullet points."
            )

            synthesis, cost = await asyncio.wait_for(
                _run_mini_council(
                    "Night Watch Journal & Strategy Review", journal_prompt, "journal"
                ),
                timeout=COUNCIL_TIMEOUT,
            )
            if synthesis:
                report["journal_council"] = synthesis
                report["councils_run"] += 1
            report["total_cost_usd"] += cost
        except asyncio.TimeoutError:
            report["errors"].append("Journal council timed out (5min)")
            log.error("[NIGHT-WATCH/COUNCIL] Journal council timed out")
        except Exception as e:
            report["errors"].append(f"Journal council failed: {e}")
            log.error("[NIGHT-WATCH/COUNCIL] Journal council failed: %s", e)

        report["duration_seconds"] = round(time.monotonic() - t0, 1)

        log.info(
            "[NIGHT-WATCH/COUNCIL] Council cycle complete: %d/4 councils, $%.4f, %.1fs",
            report["councils_run"],
            report["total_cost_usd"],
            report["duration_seconds"],
        )

        await self._log_autonomous_event(
            "night_watch_council",
            {
                "councils_run": report["councils_run"],
                "total_cost_usd": report["total_cost_usd"],
                "duration_seconds": report["duration_seconds"],
                "errors": report["errors"],
            },
        )

        return report

    # ─── NIGHT WATCH ANALYST: LLM-powered nightly analysis ─────────

    async def _night_watch_analyst(
        self,
        deterministic_issues: list[str],
        has_warnings: bool,
        critical: bool,
        *,
        memory_report: dict | None = None,
        intel_report: dict | None = None,
        council_report: dict | None = None,
    ) -> None:
        """Shim — carved-out body lives in `night_watch/analyst.py` (W10B-14)."""
        from .night_watch.analyst import run as _run

        await _run(
            self,
            deterministic_issues,
            has_warnings,
            critical,
            memory_report=memory_report,
            intel_report=intel_report,
            council_report=council_report,
        )

    async def _night_watch_portfolio_analyst(self) -> None:
        """Phase 6 — run the Portfolio Analyst Agent and persist the report.

        Mandate (NATRIX): maximize capital inflow, limit capital outflow,
        defend/invalidate thesises with evidence, enforce entry/exit/mandate/
        watch-for contract on every position.

        Steps (delegated to PortfolioAnalystAgent.run()):
          1. Pull held positions from PortfolioManager (in-memory cache)
          2. Pull last-24h awarebot signals filtered to held tickers
          3. Pull last-24h council briefs
          4. Compute deterministic metrics (HHI, sector, VaR, leverage)
          5. Re-evaluate each PositionThesis against new evidence
          6. Detect immediate actions (broken thesis, stop breach,
             mandate drift, contract incomplete, imminent catalysts)
          7. Sonnet 4 + extended-thinking synthesis (~$0.15) — trim/add
             candidates + capital flow narrative + overall prose
          8. Persist nightly_report.json + latest.json pointer
          9. Ingest as MemoryUnit (BRAIN tier, importance 75)
         10. Dispatch ntfy push for any critical-severity action

        Failure-soft: any exception writes a degraded report with
        ``llm_narrative=null`` and the deterministic block still populated.
        """
        log.info("[NIGHT-WATCH-PORTFOLIO] starting Portfolio Analyst Agent run")
        try:
            from ..portfolio.analyst.agent import PortfolioAnalystAgent
        except ImportError as exc:
            log.warning("[NIGHT-WATCH-PORTFOLIO] analyst package unavailable: %s", exc)
            return

        portfolio_manager = getattr(self._brain, "portfolio_manager", None) if self._brain else None
        if portfolio_manager is None:
            try:
                from ..portfolio import portfolio_routes as _pr

                portfolio_manager = _pr._portfolio_manager
            except Exception:
                portfolio_manager = None
        if portfolio_manager is None:
            log.info(
                "[NIGHT-WATCH-PORTFOLIO] no portfolio_manager available — "
                "agent has nothing to analyze, skipping"
            )
            return

        # Build the agent with the live dependencies. Each one is
        # optional — agent degrades gracefully on missing inputs.
        agent = PortfolioAnalystAgent(
            portfolio_manager=portfolio_manager,
            memory_store=getattr(self._brain, "memory_store", None),
            cost_tracker=None,  # llm_synthesis imports the global tracker itself
            data_dir=self.data_dir,
            brain=self._brain,
        )

        try:
            report = await agent.run(dry_run=False)
            log.info(
                "[NIGHT-WATCH-PORTFOLIO] complete — positions=%d immediate=%d cost=$%.4f",
                report.positions_count,
                len(report.immediate_actions),
                report.cost_usd,
            )
        except Exception as exc:
            log.error("[NIGHT-WATCH-PORTFOLIO] agent.run() failed: %s", exc, exc_info=True)

    # ─── SUPERVISOR: Self-healing task monitor ─────────────────────

    async def _supervisor_loop(self) -> None:
        """
        Supervisor loop — monitors scheduler tasks every 30 seconds and
        restarts crashed ones up to max_restarts (3) per task.

        If a task exhausts its restart budget, sends an ntfy alert and
        leaves it dead. Also monitors Awarebot sub-tasks, but ONLY if
        the Awarebot's own internal supervisor (its run() method) is dead.
        """
        max_restarts = 3
        check_interval = 30

        log.info(
            "[SUPERVISOR] Supervisor loop started (check every %ds, max %d restarts/task)",
            check_interval,
            max_restarts,
        )

        while self._running:
            try:
                await asyncio.sleep(check_interval)

                if not self._running:
                    break

                # ── Check scheduler tasks ────────────────────────────
                for i, task in enumerate(list(self._tasks)):
                    if not task.done():
                        continue

                    name = task.get_name()

                    # Skip cancelled tasks (normal shutdown)
                    if task.cancelled():
                        continue

                    exc = task.exception()

                    # One-shot tasks (e.g. ncl-startup-migrations) are designed
                    # to fire once and exit. A clean completion is NOT an
                    # incident — log INFO once, then drop from the watch list
                    # so we don't burn 2,880 noise lines/day on supervisor
                    # cycles trying to restart them.
                    if name in self._one_shot_tasks and exc is None:
                        if name not in self._one_shot_completed_logged:
                            log.info(
                                "[SUPERVISOR] One-shot task '%s' completed cleanly — no restart needed",  # noqa: E501
                                name,
                            )
                            self._one_shot_completed_logged.add(name)
                        self._tasks = [t for t in self._tasks if t is not task]
                        continue

                    error_str = f"{type(exc).__name__}: {exc}" if exc else "completed unexpectedly"

                    log.warning("[SUPERVISOR] Task '%s' is dead: %s", name, error_str)

                    factory = self._task_factories.get(name)
                    if not factory:
                        log.error("[SUPERVISOR] No factory for task '%s' — cannot restart", name)
                        continue

                    if self._restart_counts[name] < max_restarts:
                        self._restart_counts[name] += 1
                        attempt = self._restart_counts[name]
                        log.warning(
                            "[SUPERVISOR] Restarting '%s' (attempt %d/%d) after 5s delay",
                            name,
                            attempt,
                            max_restarts,
                        )
                        await asyncio.sleep(5)

                        new_task = asyncio.create_task(factory(), name=name)

                        # Attach the same done-callback for logging
                        def _task_done(t: asyncio.Task) -> None:
                            if t.cancelled():
                                return
                            e = t.exception()
                            if e is not None:
                                log.error(
                                    "[SCHEDULER] task '%s' DIED: %s: %r",
                                    t.get_name(),
                                    type(e).__name__,
                                    e,
                                    exc_info=e,
                                )

                        new_task.add_done_callback(_task_done)

                        # Replace the dead task in the list
                        self._tasks = [t for t in self._tasks if t is not task]
                        self._tasks.append(new_task)

                        log.info(
                            "[SUPERVISOR] Task '%s' restarted successfully (attempt %d/%d)",
                            name,
                            attempt,
                            max_restarts,
                        )
                        await self._log_autonomous_event(
                            "supervisor_restart",
                            {
                                "task": name,
                                "attempt": attempt,
                                "max_restarts": max_restarts,
                                "error": error_str,
                            },
                        )
                    else:
                        log.error(
                            "[SUPERVISOR] Task '%s' has exhausted restart budget (%d/%d) "
                            "— permanently dead",
                            name,
                            self._restart_counts[name],
                            max_restarts,
                        )
                        await self._send_supervisor_alert(name, error_str)
                        await self._log_autonomous_event(
                            "supervisor_task_dead",
                            {
                                "task": name,
                                "restarts_used": self._restart_counts[name],
                                "error": error_str,
                            },
                        )
                        # Remove the dead task from the list
                        self._tasks = [t for t in self._tasks if t is not task]

                # ── Check Awarebot sub-tasks (only if its supervisor is dead) ─
                if self.awarebot and hasattr(self.awarebot, "_tasks") and self.awarebot._tasks:
                    # The Awarebot agent's run() method IS the supervisor.
                    # Find the ncl-awarebot-agent task to check if it's alive.
                    awarebot_agent_alive = any(
                        t.get_name() == "ncl-awarebot-agent" and not t.done() for t in self._tasks
                    )

                    if not awarebot_agent_alive:
                        # Awarebot supervisor is dead — check its sub-tasks
                        for sub_task in list(self.awarebot._tasks):
                            if not sub_task.done():
                                continue

                            sub_name = sub_task.get_name()
                            if sub_task.cancelled():
                                continue

                            sub_exc = sub_task.exception()
                            sub_error = (
                                f"{type(sub_exc).__name__}: {sub_exc}"
                                if sub_exc
                                else "completed unexpectedly"
                            )
                            log.warning(
                                "[SUPERVISOR] Awarebot sub-task '%s' dead (supervisor also dead): %s",  # noqa: E501
                                sub_name,
                                sub_error,
                            )
                            # We don't restart Awarebot sub-tasks individually —
                            # the ncl-awarebot-agent task (if restarted) will
                            # respawn them. Just log and alert.
                            if self._restart_counts[sub_name] == 0:
                                self._restart_counts[sub_name] = max_restarts  # Mark as exhausted
                                await self._send_supervisor_alert(
                                    f"{sub_name} (awarebot supervisor also dead)", sub_error
                                )

            except asyncio.CancelledError:
                log.info("[SUPERVISOR] Supervisor loop cancelled")
                return
            except Exception as e:
                log.error("[SUPERVISOR] Supervisor loop error: %s", e, exc_info=True)
                # Supervisor must not die — sleep and retry
                await asyncio.sleep(check_interval)

    async def _send_supervisor_alert(self, task_name: str, error: str) -> None:
        """Enqueue an urgent ntfy alert when a task exhausts its restart budget.

        Migrated 2026-05-21 to the centralized AlertDispatcher
        (rate-limited + deduped). Falls back to direct ntfy POST on
        any dispatcher import failure so we never silently swallow a
        supervisor death.
        """
        body = (
            f"Task '{task_name}' has crashed 3 times and will not be restarted.\n\n"
            f"Last error: {error}"
        )
        try:
            enqueue_alert(
                title="NCL Supervisor Alert",
                body=body,
                priority="5",
                tags="rotating_light",
                dedup_key=f"supervisor:{task_name}",
                source="supervisor",
            )
            log.info("[SUPERVISOR] ntfy alert enqueued for task '%s'", task_name)
            return
        except Exception as e:
            log.warning("[SUPERVISOR] dispatcher unavailable, direct POST fallback: %s", e)
        # Fallback path — only fires if AlertDispatcher import broke.
        try:
            import httpx

            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                await client.post(
                    "https://ntfy.sh/ncl-natrix-intel-7x9k",
                    content=body.encode(),
                    headers={
                        "Title": "NCL Supervisor Alert",
                        "Priority": "5",
                        "Tags": "rotating_light",
                    },
                )
            log.info("[SUPERVISOR] ntfy alert sent (fallback) for task '%s'", task_name)
        except Exception as e:
            log.warning("[SUPERVISOR] Failed to send ntfy alert: %s", e)

    # ─── Calendar Agent — Critical Alert Push Loop ───────────────────

    async def _calendar_alert_check_loop(self) -> None:
        """
        Poll the Calendar agent's critical_alerts.jsonl every 10 minutes.

        For each unprocessed alert with severity in {"critical", "high"},
        push it via ntfy. Dedup via self._pushed_calendar_alerts so the
        same alert isn't pushed twice across restarts of this loop.
        """
        import httpx

        check_interval = 600  # 10 minutes
        alerts_path = self.data_dir / "calendar" / "critical_alerts.jsonl"

        log.info(
            "[CALENDAR-ALERTS] Critical alert loop started (poll every %ds, file=%s)",
            check_interval,
            alerts_path,
        )

        # Brief initial delay so the calendar agent has time to spin up
        await asyncio.sleep(30)

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[CALENDAR-ALERTS] Emergency stop active — halting loop")
                break

            try:
                if not alerts_path.exists():
                    await asyncio.sleep(check_interval)
                    continue

                # Read JSONL append-only ledger
                try:
                    async with aiofiles.open(alerts_path, "r") as f:
                        raw = await f.read()
                except Exception as read_err:
                    log.warning("[CALENDAR-ALERTS] Failed to read %s: %s", alerts_path, read_err)
                    await asyncio.sleep(check_interval)
                    continue

                for line in raw.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        alert = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    severity = (alert.get("severity") or "").lower()
                    if severity not in ("critical", "high"):
                        continue

                    # Dedup key: prefer explicit id, otherwise compose from fields
                    alert_id = (
                        alert.get("id")
                        or alert.get("alert_id")
                        or f"{alert.get('timestamp','')}|{alert.get('type','')}|{alert.get('title','')}"  # noqa: E501
                    )
                    if not alert_id or alert_id in self._pushed_calendar_alerts:
                        continue

                    title = alert.get("title") or f"Calendar {severity.upper()} Alert"
                    body = (
                        alert.get("message")
                        or alert.get("body")
                        or json.dumps(alert, default=_json_safe)
                    )
                    priority = "5" if severity == "critical" else "4"
                    tags = "rotating_light" if severity == "critical" else "warning"

                    try:
                        # Migrated 2026-05-21: enqueue via central dispatcher
                        # (rate limit + dedup). Falls back to direct POST on
                        # dispatcher import failure.
                        try:
                            enqueue_alert(
                                title=str(title)[:200],
                                body=str(body)[:3500],
                                priority=priority,
                                tags=tags,
                                dedup_key=f"calendar:{alert_id}",
                                source="calendar_alerts",
                            )
                        except Exception as enq_err:
                            log.warning(
                                "[CALENDAR-ALERTS] dispatcher unavailable, direct POST: %s",
                                enq_err,
                            )
                            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                                await client.post(
                                    "https://ntfy.sh/ncl-natrix-intel-7x9k",
                                    content=str(body)[:3500].encode(),
                                    headers={
                                        "Title": str(title)[:200],
                                        "Priority": priority,
                                        "Tags": tags,
                                    },
                                )
                        self._pushed_calendar_alerts.add(alert_id)
                        log.info(
                            "[CALENDAR-ALERTS] Enqueued %s alert: %s",
                            severity,
                            title,
                        )
                    except Exception as push_err:
                        log.warning(
                            "[CALENDAR-ALERTS] Failed to push alert '%s': %s",
                            alert_id,
                            push_err,
                        )

            except asyncio.CancelledError:
                log.info("[CALENDAR-ALERTS] Loop cancelled")
                return
            except Exception as e:
                log.error("[CALENDAR-ALERTS] Loop error: %s", e, exc_info=True)

            await asyncio.sleep(check_interval)

    # ─── Helpers ───────────────────────────────────────────────

    # ─── LOOP 9: Heartbeat + Watchdog ──────────────────────────────

    # Watchdog: per-loop maximum staleness before WARN/ERROR/ntfy.
    # Keyed by the stats-dict key holding the loop's last-fire ISO timestamp.
    _WATCHDOG_THRESHOLDS = {
        # (stats_key, max_age_seconds, human_label)
        "last_scan": (15 * 60, "Awarebot scan"),
        "last_prediction": (90 * 60, "Prediction"),
        "last_consolidation": (2 * 3600, "Memory consolidation"),
        "last_intel_brief": (6 * 3600, "Intel brief"),
        "last_journal_reflection": (26 * 3600, "Journal reflection"),
        # last_aac_sync watchdog removed with _aac_sync_loop (2026-05-21)
    }

    def _build_heartbeat_record(self) -> dict:
        """Compose a single heartbeat JSONL record.
        Pulls timestamps from scheduler stats + awarebot stats so the ledger is
        a single source of truth for liveness across all loops."""
        now = datetime.now(timezone.utc)
        active = [t.get_name() for t in self._tasks if not t.done()]
        dead = [t.get_name() for t in self._tasks if t.done()]

        aware = {}
        if self.awarebot:
            try:
                aware = self.awarebot.get_stats() or {}
            except Exception:
                aware = {}

        # Pull last-fire timestamps from awarebot into scheduler stats so the
        # watchdog has a single dict to inspect.
        if aware.get("last_scan_at"):
            self._stats["last_scan"] = aware["last_scan_at"]
        if aware.get("last_prediction_at"):
            self._stats["last_prediction"] = aware["last_prediction_at"]
        if aware.get("last_brief_at"):
            self._stats["last_intel_brief"] = aware["last_brief_at"]

        return {
            "ts": now.isoformat(),
            "active_tasks": active,
            "dead_tasks": dead,
            "signal_buffer": len(self._signal_buffer),
            "scans": self._stats["scans_completed"],
            "predictions": self._stats["predictions_run"],
            "councils": self._stats["councils_auto_spawned"],
            "memory_consolidations": self._stats["memory_consolidations"],
            "aware_cycles": int(aware.get("cycles_completed", 0)),
            "last_scan_at": self._stats.get("last_scan"),
            "last_prediction_at": self._stats.get("last_prediction"),
            "last_consolidation_at": self._stats.get("last_consolidation"),
            "last_intel_brief_at": self._stats.get("last_intel_brief"),
            "last_journal_reflection_at": self._stats.get("last_journal_reflection"),
        }

    def _check_watchdog(self, record: dict) -> list[dict]:
        """Return list of stale-loop descriptors. Each item:
        {loop, last_fire_at, age_s, threshold_s}."""
        now = datetime.now(timezone.utc)
        stale: list[dict] = []
        for key, (max_age, label) in self._WATCHDOG_THRESHOLDS.items():
            ts_str = self._stats.get(key)
            if not ts_str:
                # Never fired — only stale if scheduler has been up long enough
                started = self._stats.get("started_at")
                if started:
                    try:
                        s = datetime.fromisoformat(started.replace("Z", "+00:00"))
                        if s.tzinfo is None:
                            s = s.replace(tzinfo=timezone.utc)
                        if (now - s).total_seconds() > max_age:
                            stale.append(
                                {
                                    "loop": label,
                                    "key": key,
                                    "last_fire_at": None,
                                    "age_s": int((now - s).total_seconds()),
                                    "threshold_s": max_age,
                                }
                            )
                    except Exception:
                        pass
                continue
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age = (now - ts).total_seconds()
                if age > max_age:
                    stale.append(
                        {
                            "loop": label,
                            "key": key,
                            "last_fire_at": ts_str,
                            "age_s": int(age),
                            "threshold_s": max_age,
                        }
                    )
            except Exception:
                continue
        return stale

    async def _heartbeat_push_alert(self, stale: list[dict]) -> None:
        """Push ntfy alert for stale loops, deduped to once per loop per UTC day.

        Migrated 2026-05-21 to use the central AlertDispatcher (which has
        its own 1-hour per-dedup-key cooldown). The per-day local dedup
        is kept as an extra safety net.
        """
        today = datetime.now(timezone.utc).date().isoformat()
        new_alerts = [s for s in stale if self._heartbeat_alert_sent.get(s["key"]) != today]
        if not new_alerts:
            return
        title = f"Heartbeat watchdog — {len(new_alerts)} stale loop(s)"
        body_lines = [f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}]"]
        for s in new_alerts:
            body_lines.append(
                f"  • {s['loop']}: {s['age_s'] // 60}m old "
                f"(threshold {s['threshold_s'] // 60}m)"
            )
        body = "\n".join(body_lines)
        # Preferred path: enqueue.
        try:
            keys = ",".join(sorted(s["key"] for s in new_alerts))
            enqueue_alert(
                title=title,
                body=body,
                priority="4",
                tags="brain,warning,zzz",
                dedup_key=f"heartbeat:{today}:{keys}",
                source="heartbeat",
            )
            for s in new_alerts:
                self._heartbeat_alert_sent[s["key"]] = today
            log.warning("[HEARTBEAT] ntfy alert enqueued for %d stale loop(s)", len(new_alerts))
            return
        except Exception as enq_err:
            log.warning("[HEARTBEAT] dispatcher unavailable, direct POST fallback: %s", enq_err)
        # Fallback path
        import httpx

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.post(
                    "https://ntfy.sh/ncl-natrix-intel-7x9k",
                    content=body.encode("utf-8"),
                    headers={
                        "Content-Type": "text/plain; charset=utf-8",
                        "Title": title.encode("ascii", "replace").decode("ascii"),
                        "Priority": "4",
                        "Tags": "brain,warning,zzz",
                    },
                )
                resp.raise_for_status()
            for s in new_alerts:
                self._heartbeat_alert_sent[s["key"]] = today
            log.warning("[HEARTBEAT] ntfy alert sent for %d stale loop(s)", len(new_alerts))
        except Exception as e:
            log.error("[HEARTBEAT] ntfy alert failed: %s", e)

    def _heartbeat_ledger_path(self) -> Path:
        """Daily-rotated ledger file: data/heartbeat/heartbeat-YYYY-MM-DD.jsonl."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._heartbeat_dir / f"heartbeat-{date_str}.jsonl"

    async def _heartbeat_loop(self) -> None:
        """Heartbeat + watchdog loop.

        Every 60s:
          - Build a JSON liveness record (tasks, counters, last-fire timestamps).
          - Append to data/heartbeat/heartbeat-YYYY-MM-DD.jsonl (rotated daily).
          - Run watchdog: detect loops exceeding their staleness threshold.
          - Log DEBUG every tick; one INFO summary every 10 minutes.
          - On stale-loop detection: log ERROR + (deduped) ntfy push.
        """
        # INFO throttle: emit on first tick + every 10 minutes thereafter so the
        # historical "[SCHEDULER][HEARTBEAT] alive" line format is preserved for
        # any downstream log scrapers, just at 10x lower frequency.
        info_interval_ticks = 10
        tick = 0
        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[HEARTBEAT] Emergency stop active — halting loop")
                break
            try:
                record = self._build_heartbeat_record()
                self._stats["last_heartbeat_at"] = record["ts"]
                self._stats["heartbeat_count"] += 1
                # W8-A2 D8: monotonic stamp used by the separate stall-dumper
                # watchdog. time.monotonic() doesn't go backwards even if NTP
                # adjusts wall-clock, so it's the right comparator for "loop
                # is frozen vs the loop never started".
                self._last_heartbeat_mono = time.monotonic()

                # Watchdog evaluation
                stale = self._check_watchdog(record)
                self._stats["stale_loops"] = stale
                record["stale_loops"] = stale

                # Write JSONL ledger (one tiny line per minute, rotated daily)
                try:
                    async with aiofiles.open(self._heartbeat_ledger_path(), "a") as f:
                        await f.write(json.dumps(record, default=_json_safe) + "\n")
                except Exception as werr:
                    log.warning("[HEARTBEAT] ledger write failed: %s", werr)

                # Per-tick DEBUG (silent unless DEBUG logging is enabled)
                log.debug(
                    "[SCHEDULER][HEARTBEAT] tick=%d alive — active_tasks=%d signal_buffer=%d "
                    "scans=%d predictions=%d councils=%d stale=%d",
                    self._stats["heartbeat_count"],
                    len(record["active_tasks"]),
                    record["signal_buffer"],
                    record["scans"],
                    record["predictions"],
                    record["councils"],
                    len(stale),
                )

                # Throttled INFO (every 10 ticks ≈ 10 minutes) — preserves
                # original line format so downstream parsers still match.
                if tick % info_interval_ticks == 0:
                    log.info(
                        "[SCHEDULER][HEARTBEAT] alive — active_tasks=%d signal_buffer=%d "
                        "scans=%d predictions=%d councils=%d",
                        len(record["active_tasks"]),
                        record["signal_buffer"],
                        record["scans"],
                        record["predictions"],
                        record["councils"],
                    )

                # Stale-loop escalation
                if stale:
                    log.error(
                        "[HEARTBEAT][WATCHDOG] %d stale loop(s): %s",
                        len(stale),
                        ", ".join(f"{s['loop']}({s['age_s']}s)" for s in stale),
                    )
                    try:
                        await self._heartbeat_push_alert(stale)
                    except Exception as perr:
                        log.warning("[HEARTBEAT] push alert failed: %s", perr)

                tick += 1
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("[HEARTBEAT] error: %s", e, exc_info=True)

            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise

    # ── W8-A2 D8: stall-dumper watchdog ──────────────────────────────────
    # If the heartbeat loop hasn't ticked in STALL_THRESHOLD_S, the event
    # loop is almost certainly frozen — most likely a blocking-IO call
    # inside an async coroutine (the issue #91 class of bugs). This loop
    # is the canary: it fires every WATCHDOG_TICK_S and, when stale,
    # snapshots `asyncio.all_tasks()` with `get_stack()` to a JSONL so we
    # can see exactly which coroutine is blocked. py-spy-grade diagnostics
    # without needing sudo on prod.
    _STALL_WATCHDOG_TICK_S = 30.0
    _STALL_THRESHOLD_S = 90.0
    # W10B-10: relaxed threshold when a whitelisted long-running tag is
    # currently active. YTC 150K-char transcripts + night-watch phases were
    # tripping the default 90s. 300s gives them headroom without disarming
    # the watchdog for the rest of the scheduler.
    _STALL_THRESHOLD_LONG_S = 300.0
    _STALL_DUMP_DEDUP_S = 300.0  # 5 min between dumps to avoid spam

    # ── W10B-10: long-running deadband API ────────────────────────────────
    def mark_long_running(self, tag: str) -> None:
        """Mark a whitelisted tag as actively running a long-await workload.

        While *any* tag in ``_long_running_tags`` has a positive active count,
        the stall watchdog uses ``_STALL_THRESHOLD_LONG_S`` (300s) instead of
        ``_STALL_THRESHOLD_S`` (90s). Tags outside the whitelist are ignored
        — callers can't silently disable the watchdog by marking arbitrary
        strings. Reference-counted so re-entry is safe.
        """
        if tag not in self._long_running_tags:
            return
        self._active_long_running[tag] = self._active_long_running.get(tag, 0) + 1

    def unmark_long_running(self, tag: str) -> None:
        """Counterpart to ``mark_long_running``. Safe to call when not marked."""
        if tag not in self._long_running_tags:
            return
        n = self._active_long_running.get(tag, 0) - 1
        if n <= 0:
            self._active_long_running.pop(tag, None)
        else:
            self._active_long_running[tag] = n

    def _any_long_running_active(self) -> bool:
        return any(v > 0 for v in self._active_long_running.values())

    @contextlib.asynccontextmanager
    async def long_running_ctx(self, tag: str):
        """Async context manager wrapper around mark/unmark.

        Use from inside whitelisted loops (YTC analyzer, night-watch phases)
        to bracket the long-await section::

            async with scheduler.long_running_ctx("ncl-ytc-dedicated"):
                await analyze_long_video(...)
        """
        self.mark_long_running(tag)
        try:
            yield
        finally:
            self.unmark_long_running(tag)

    async def _stall_watchdog_loop(self) -> None:
        """Detect frozen event loop and dump all task stacks."""
        # Wait for the first heartbeat tick before arming — otherwise we'd
        # dump immediately at startup when _last_heartbeat_mono is still 0.
        while self._running and self._last_heartbeat_mono == 0.0:
            try:
                await asyncio.sleep(self._STALL_WATCHDOG_TICK_S)
            except asyncio.CancelledError:
                raise
        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[STALL_WATCHDOG] emergency stop — halting")
                break
            try:
                now = time.monotonic()
                age = now - self._last_heartbeat_mono
                # W10B-10: if a whitelisted long-running tag is active,
                # raise effective threshold from 90s to 300s. Everything
                # else still trips at 90s.
                effective_threshold = (
                    self._STALL_THRESHOLD_LONG_S
                    if self._any_long_running_active()
                    else self._STALL_THRESHOLD_S
                )
                if age > effective_threshold and (
                    now - self._last_stall_dump_at > self._STALL_DUMP_DEDUP_S
                ):
                    self._last_stall_dump_at = now
                    await self._dump_stall_diagnostics(age, effective_threshold)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("[STALL_WATCHDOG] error: %s", e, exc_info=True)
            try:
                await asyncio.sleep(self._STALL_WATCHDOG_TICK_S)
            except asyncio.CancelledError:
                raise

    async def _dump_stall_diagnostics(self, age_s: float, threshold_s: float | None = None) -> None:
        """Snapshot all live tasks' stacks and ntfy. Best-effort, never raises."""
        # W10B-10: threshold may be the relaxed long-running value (300s) or
        # the default (90s). Fall back to the strict default if unspecified
        # so legacy callers still work.
        if threshold_s is None:
            threshold_s = self._STALL_THRESHOLD_S
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dump_path = self._stall_dump_dir / f"stall-{ts}.jsonl"
        n_tasks = 0
        try:
            with open(dump_path, "w", encoding="utf-8") as f:
                header = {
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "heartbeat_age_s": int(age_s),
                    "threshold_s": int(threshold_s),
                    "active_long_running": sorted(
                        t for t, n in self._active_long_running.items() if n > 0
                    ),
                    "kind": "stall_dump_header",
                }
                f.write(json.dumps(header, default=_json_safe) + "\n")
                for t in asyncio.all_tasks():
                    try:
                        stack_lines: list[str] = []
                        for frame in t.get_stack():
                            stack_lines.append(
                                f"{frame.f_code.co_filename}:{frame.f_lineno} "
                                f"in {frame.f_code.co_name}"
                            )
                        entry = {
                            "kind": "task",
                            "name": t.get_name(),
                            "done": t.done(),
                            "coro": repr(t.get_coro()) if hasattr(t, "get_coro") else "",
                            "stack": stack_lines,
                        }
                        f.write(json.dumps(entry, default=_json_safe) + "\n")
                        n_tasks += 1
                    except Exception as ie:
                        f.write(json.dumps({"kind": "task_error", "err": str(ie)}) + "\n")
            log.critical(
                "[STALL_WATCHDOG] heartbeat stale for %ds — dumped %d tasks to %s",
                int(age_s),
                n_tasks,
                dump_path,
            )
        except Exception as we:
            log.error("[STALL_WATCHDOG] dump write failed: %s", we)

        # Fire ntfy via central alert dispatcher
        try:
            enqueue_alert(
                title="Brain stall detected",
                body=(
                    f"Heartbeat stale for {int(age_s)}s "
                    f"(threshold {int(threshold_s)}s). "
                    f"{n_tasks} task stacks dumped to {dump_path.name}."
                ),
                priority="5",
                tags="brain,critical,skull",
                dedup_key="brain_stall_detected",
                source="stall_watchdog",
            )
        except Exception as ae:
            log.warning("[STALL_WATCHDOG] alert enqueue failed: %s", ae)

    def _get_watch_queries(self, platform: str) -> list[str]:
        """
        Get intelligence watch queries for a platform.

        Loads from config or uses defaults aligned with active mandates.
        """
        # Load custom queries from config file if available
        queries_file = Path(self.config.config_dir).expanduser() / "watch_queries.json"
        if queries_file.exists():
            try:
                with open(queries_file) as f:
                    queries = json.load(f)
                    return queries.get(platform, [])
            except Exception:
                pass

        # Default queries aligned with NARTIX mandate priorities
        defaults = {
            "x": [
                "AI automation business",
                "algorithmic trading crypto",
                "indie game development",
                "AI music production",
                "prediction markets Polymarket",
            ],
            "youtube": [
                "AI business automation 2026",
                "crypto trading strategies",
                "game development indie",
                "AI tools for developers",
            ],
            "reddit": [
                "artificial intelligence business",
                "cryptocurrency trading",
                "gamedev indie",
                "AI music generation",
            ],
        }
        return defaults.get(platform, [])

    async def _flag_for_council(self, trigger: str, data: dict, importance: float) -> None:
        """Flag a signal/prediction for council consideration.

        Uses file locking to prevent TOCTOU races with concurrent readers.
        """
        flag = {
            "trigger": trigger,
            "data": data,
            "importance": importance,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        flags_file = self.signals_dir / "council_flags.jsonl"
        try:
            line = json.dumps(flag, default=_json_safe) + "\n"

            def _locked_append() -> None:
                with open(flags_file, "a") as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    try:
                        f.write(line)
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            await asyncio.to_thread(_locked_append)
        except Exception as e:
            log.warning(f"Failed to write council flag: {e}")

    async def _get_council_flags(self) -> list[dict]:
        """Read pending council flags with file locking to avoid TOCTOU races."""
        flags_file = self.signals_dir / "council_flags.jsonl"
        flags = []
        try:
            fd = await asyncio.to_thread(lambda: open(flags_file, "r"))
            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                content = fd.read()
                fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
                for line in content.strip().split("\n"):
                    if line.strip():
                        flags.append(json.loads(line))
            finally:
                fd.close()
        except (FileNotFoundError, OSError):
            pass
        return flags

    async def _clear_council_flags(self) -> None:
        """Clear processed council flags atomically.

        Renames the file to a .processing sentinel before unlinking so that
        a concurrent writer appending to council_flags.jsonl at the same moment
        will not see a partially-deleted file. The rename is atomic on POSIX
        filesystems; the subsequent unlink is then safe to fail silently.
        """
        flags_file = self.signals_dir / "council_flags.jsonl"
        if flags_file.exists():
            processing = self.signals_dir / "council_flags.jsonl.processing"
            try:
                flags_file.rename(processing)
            except OSError as e:
                log.warning(f"[COUNCIL-AUTO] Failed to rename flags file for atomic clear: {e}")
                return
            try:
                processing.unlink()
            except OSError as e:
                log.warning(f"[COUNCIL-AUTO] Failed to unlink processing flags file: {e}")

    async def _log_autonomous_event(self, event_type: str, data: dict) -> None:
        """Log an autonomous event to the autonomous events file."""
        event = {
            "type": f"autonomous.{event_type}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        events_file = self.signals_dir / "events.ndjson"
        try:
            async with aiofiles.open(events_file, "a") as f:
                await f.write(json.dumps(event, default=_json_safe) + "\n")
        except Exception as e:
            log.warning(f"Failed to log autonomous event: {e}")

    def _http_get(self, url: str, timeout: int = 5) -> Optional[str]:
        """Synchronous HTTP GET (run via asyncio.to_thread)."""
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status < 400:
                    return resp.read().decode("utf-8")
        except Exception:
            return None
        return None

    # ═══════════════════════════════════════════════════════════════════
    # NEW AUTONOMOUS LOOPS (added 2026-05-21)
    # ═══════════════════════════════════════════════════════════════════

    async def _health_rollup_loop(self) -> None:
        """LOOP 13 — 60s aggregated component health → data/health/current.json.

        Aggregates scheduler / awarebot / portfolio / memory / cost /
        calendar / journal into one snapshot for the iOS Dashboard and
        external ops checks. Atomic-writes the JSON every minute.
        """
        health_dir = self.data_dir / "health"
        log.info("[HEALTH-ROLLUP] loop started (60s cadence → %s/current.json)", health_dir)

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[HEALTH-ROLLUP] Emergency stop active — halting loop")
                break
            try:
                rollup = await build_health_rollup(self, self.brain)
                try:
                    await asyncio.to_thread(write_rollup_atomic, rollup, health_dir)
                except Exception as werr:
                    log.warning("[HEALTH-ROLLUP] write failed: %s", werr)
                self._stats["last_health_rollup"] = rollup["timestamp"]
                self._stats["health_rollups_written"] = (
                    self._stats.get("health_rollups_written", 0) + 1
                )
                # Stash latest in memory for the /system/health/rollup route
                self._latest_health_rollup = rollup
                log.debug(
                    "[HEALTH-ROLLUP] tick — overall=%s warnings=%d errors=%d",
                    rollup.get("overall"),
                    len(rollup.get("warnings", [])),
                    len(rollup.get("errors", [])),
                )
            except asyncio.CancelledError:
                log.info("[HEALTH-ROLLUP] cancelled")
                raise
            except Exception as e:
                log.error("[HEALTH-ROLLUP] error: %s", e, exc_info=True)
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise

    async def _cost_rollover_loop(self) -> None:
        """LOOP 14 — UTC midnight cost ledger close + reset.

        Polls every 60s for a UTC date change. On rollover:
          - Append a ``cost_day_closed`` event to ``data/costs/cost_ledger.jsonl``
            with the closing per-source totals.
          - Reset in-memory daily counters (the tracker resets lazily on
            ``can_spend`` / ``record``; this makes the boundary explicit).
          - Log INFO with the day's total and top source.
        """
        # Defensive: initialize the "last seen" UTC date on first tick so we
        # don't fire on Brain startup right before/after midnight.
        last_seen_date: Optional[str] = None
        log.info("[COST-ROLLOVER] loop started (polls UTC date every 60s)")

        # Import lazily to avoid circular imports at module load.
        try:
            from ..cost_tracker import LEDGER_FILE, get_tracker
        except Exception as e:
            log.error("[COST-ROLLOVER] cost_tracker import failed: %s", e)
            return

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[COST-ROLLOVER] Emergency stop active — halting loop")
                break
            try:
                today = datetime.utcnow().date().isoformat()
                if last_seen_date is None:
                    last_seen_date = today
                elif today != last_seen_date:
                    log.info(
                        "[COST-ROLLOVER] UTC date rolled %s → %s — closing day",
                        last_seen_date,
                        today,
                    )
                    try:
                        tracker = await get_tracker()
                        # Snapshot the day we're closing BEFORE reset.
                        async with tracker._lock:
                            closing_totals = dict(tracker._daily_totals)
                            closing_counts = dict(tracker._daily_counts)
                            closing_date = tracker._current_date or last_seen_date

                        total_usd = round(sum(closing_totals.values()), 6)
                        top_source = (
                            max(closing_totals.items(), key=lambda kv: kv[1])
                            if closing_totals
                            else (None, 0.0)
                        )

                        # Append explicit close event to JSONL (audit trail).
                        close_event = {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "date": closing_date,
                            "event": "cost_day_closed",
                            "total_usd": total_usd,
                            "total_calls": sum(closing_counts.values()),
                            "by_source": {
                                src: {
                                    "spent_usd": round(amt, 6),
                                    "calls": closing_counts.get(src, 0),
                                }
                                for src, amt in closing_totals.items()
                            },
                            "top_source": top_source[0],
                            "top_source_usd": round(top_source[1], 6),
                        }
                        try:
                            LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)

                            def _append():
                                with open(LEDGER_FILE, "a") as f:
                                    f.write(json.dumps(close_event) + "\n")

                            await asyncio.to_thread(_append)
                        except Exception as wer:
                            log.warning("[COST-ROLLOVER] ledger flush failed: %s", wer)

                        # Explicit reset (cost_tracker also does this lazily).
                        async with tracker._lock:
                            tracker._daily_totals.clear()
                            tracker._daily_counts.clear()
                            tracker._warned_sources.clear()
                            tracker._current_date = today

                        log.info(
                            "[COST-ROLLOVER] %s closed: $%.4f across %d calls — top source: %s ($%.4f)",  # noqa: E501
                            closing_date,
                            total_usd,
                            sum(closing_counts.values()),
                            top_source[0] or "(none)",
                            top_source[1],
                        )
                        self._stats["last_cost_rollover"] = datetime.now(timezone.utc).isoformat()
                        self._stats["cost_rollovers_count"] = (
                            self._stats.get("cost_rollovers_count", 0) + 1
                        )
                    except Exception as re:
                        log.error("[COST-ROLLOVER] rollover failed: %s", re, exc_info=True)
                    last_seen_date = today
            except asyncio.CancelledError:
                log.info("[COST-ROLLOVER] cancelled")
                raise
            except Exception as e:
                log.error("[COST-ROLLOVER] tick error: %s", e, exc_info=True)
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise

    async def _cache_warmer_loop(self) -> None:
        """LOOP 15 — 5m cache warmer for cold-start latency mitigation.

        Pre-touches the calendar agent's compiled-events cache (7d, 30d),
        todos, sun state, and the WorkingContext current snapshot so the
        first iOS call after Brain restart isn't a 30s wait.
        """
        log.info("[CACHE-WARMER] loop started (300s cadence)")
        # Give the rest of init a head start so we don't fight cold imports.
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[CACHE-WARMER] Emergency stop active — halting loop")
                break
            try:
                # ── Calendar agent caches ──────────────────────────
                try:
                    from ..calendar.calendar_agent import get_calendar_agent

                    cal = get_calendar_agent()
                except Exception as e:
                    cal = None
                    log.debug("[CACHE-WARMER] calendar agent unavailable: %s", e)
                if cal is not None:
                    for window in (7, 30):
                        try:
                            await cal.compile_events("edmonton", window)
                        except Exception as e:
                            log.debug(
                                "[CACHE-WARMER] compile_events(edmonton,%d) failed: %s",
                                window,
                                e,
                            )
                    try:
                        await cal.get_todos("edmonton", 7)
                    except Exception as e:
                        log.debug("[CACHE-WARMER] get_todos failed: %s", e)
                    try:
                        await cal.get_sun_state("edmonton")
                    except Exception as e:
                        log.debug("[CACHE-WARMER] get_sun_state failed: %s", e)

                # ── Working context ────────────────────────────────
                if self._working_context is not None:
                    try:
                        # get_current() is a fast, in-memory accessor that keeps
                        # the daily snapshot warm.
                        self._working_context.get_current()
                        # Also pre-render context text so ChromaDB pages stay hot.
                        self._working_context.get_context_text(max_items=10)
                    except Exception as e:
                        log.debug("[CACHE-WARMER] working context warm failed: %s", e)

                self._stats["last_cache_warm"] = datetime.now(timezone.utc).isoformat()
                self._stats["cache_warms_count"] = self._stats.get("cache_warms_count", 0) + 1
                log.debug("[CACHE-WARMER] cycle complete")
            except asyncio.CancelledError:
                log.info("[CACHE-WARMER] cancelled")
                raise
            except Exception as e:
                log.error("[CACHE-WARMER] error: %s", e, exc_info=True)
            try:
                await asyncio.sleep(300)
            except asyncio.CancelledError:
                raise

    async def _alert_dispatch_loop(self) -> None:
        """LOOP 16 — drives the centralized AlertDispatcher.

        The dispatcher's own ``dispatch_loop()`` is an infinite worker
        that pops queued alerts, respects a global rate limit and
        per-dedup-key cooldown, and POSTs to ntfy. We wrap it here so
        the supervisor can restart on crash and the standard
        ``_running`` / ``EMERGENCY_STOP_EVENT`` semantics apply.
        """
        log.info("[ALERT-DISPATCH] loop starting — supervising AlertDispatcher.dispatch_loop()")
        dispatcher = get_alert_dispatcher()

        # Update tick timestamp every ~10s for the /autonomous/loops endpoint.
        async def _heartbeat_ticker():
            while True:
                self._stats["last_alert_dispatch_tick"] = datetime.now(timezone.utc).isoformat()
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    return

        ticker = asyncio.create_task(_heartbeat_ticker(), name="alert-dispatch-ticker")
        try:
            # Watch EMERGENCY_STOP — wrap dispatch in a stop-aware shield.
            dispatch_task = asyncio.create_task(
                dispatcher.dispatch_loop(), name="alert-dispatch-worker"
            )
            while self._running:
                if EMERGENCY_STOP_EVENT.is_set():
                    log.critical("[ALERT-DISPATCH] Emergency stop active — halting loop")
                    dispatch_task.cancel()
                    break
                if dispatch_task.done():
                    # If the worker died, let the supervisor restart THIS loop.
                    exc = dispatch_task.exception()
                    if exc:
                        log.error("[ALERT-DISPATCH] worker died: %s", exc)
                        raise exc
                    log.warning("[ALERT-DISPATCH] worker exited cleanly — re-spawning")
                    dispatch_task = asyncio.create_task(
                        dispatcher.dispatch_loop(), name="alert-dispatch-worker"
                    )
                try:
                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    dispatch_task.cancel()
                    raise
        finally:
            ticker.cancel()
            try:
                await asyncio.gather(ticker, return_exceptions=True)
            except Exception:
                pass

    async def _ytc_dedicated_loop(self) -> None:
        """LOOP 17 — dedicated YouTube Council cycle (split from Awarebot).

        Runs every 3600s (1h). Uses ``run_youtube_council`` from the
        councils runner (the same implementation Awarebot used to call)
        so we don't duplicate logic. Records cost to the ``ytc`` source
        which has its own $3/day cap in ``cost_tracker.DEFAULT_DAILY_BUDGETS``.
        """
        from ..cost_tracker import check_budget, record_cost

        log.info("[YTC-DEDICATED] loop started (3600s cadence)")
        # Initial delay so other Brain startup work completes first.
        try:
            await asyncio.sleep(300)  # 5 min
        except asyncio.CancelledError:
            raise

        ytc_interval = 3600  # 1 hour

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[YTC-DEDICATED] Emergency stop active — halting loop")
                break

            try:
                # Budget gate — YTC bills against `anthropic` (the actual
                # provider). Previously billed against `ytc` which had a
                # $0 cap = unlimited. W13 P1-A (2026-05-24) audit A8 fix.
                if not await check_budget("anthropic", 0.10):
                    log.warning("[YTC-DEDICATED] anthropic daily budget exhausted — skipping cycle")
                    try:
                        await asyncio.sleep(ytc_interval)
                        continue
                    except asyncio.CancelledError:
                        raise

                session_id = f"ytc-dedicated-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
                log.info(f"[YTC-DEDICATED] Starting per-video-only YTC run: {session_id}")

                # W11-1: hourly loop now does per-video only. Cross-video
                # rollup is produced by ``ncl-ytc-nightshift`` at 3am local.
                from ..councils.runner import run_youtube_per_video_only

                async with self.long_running_ctx("ncl-ytc-dedicated"):
                    report = await run_youtube_per_video_only(session_id)

                if report:
                    ncl_base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
                    # W11-1: per-video reports now land under
                    # intelligence-scan/council-reports/youtube/YYYY-MM-DD/
                    # so the nightshift loop can glob a single day's worth.
                    today_local = datetime.now().strftime("%Y-%m-%d")
                    json_dir = (
                        ncl_base / "intelligence-scan" / "council-reports" / "youtube" / today_local
                    )
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(
                        None, lambda: json_dir.mkdir(parents=True, exist_ok=True)
                    )

                    per_video = getattr(report, "_per_video_reports", [])
                    for vid_report in per_video:
                        vid_data = vid_report.to_dict()
                        vid_data.update(
                            {
                                "status": "complete",
                                "completed_at": datetime.now(timezone.utc).isoformat(),
                                "auto_triggered": True,
                                "report_type": "per_video",
                                "spawned_by": "ncl-ytc-dedicated",
                            }
                        )
                        vid_path = json_dir / f"{vid_report.session_id}.json"
                        # W13 followup: serialize OFF the event loop. The
                        # outer per-video loop fires 30-50× per hourly YTC
                        # cycle; each ~100KB indent=2 dump = 30-80ms sync
                        # CPU on the event loop. Cumulative blocking adds
                        # up across the tight loop and was a likely
                        # contributor to the 21:35 lockup pattern.
                        vid_json = await asyncio.to_thread(
                            json.dumps, vid_data, default=str, indent=2
                        )
                        async with aiofiles.open(vid_path, "w") as f:
                            await f.write(vid_json)

                    # Conservative per-video estimate; tighten later if usage data exposed.
                    est_cost = 0.05 * max(1, len(per_video))
                    try:
                        # W13 P1-A: bill YTC against `anthropic` (the
                        # actual provider) instead of the `ytc` key
                        # which had a $0 cap = unlimited spend.
                        await record_cost(
                            "anthropic",
                            est_cost,
                            "ytc_per_video",
                            detail=f"{len(per_video)} videos ({session_id})",
                        )
                    except Exception as ce:
                        log.warning("[YTC-DEDICATED] record_cost failed: %s", ce)

                    log.info(
                        f"[YTC-DEDICATED] cycle complete: {session_id} "
                        f"({len(per_video)} per-video reports, est ${est_cost:.4f}) — "
                        f"rollup deferred to nightshift"
                    )
                    self._stats["last_ytc_dedicated"] = datetime.now(timezone.utc).isoformat()
                    self._stats["ytc_dedicated_runs"] = self._stats.get("ytc_dedicated_runs", 0) + 1
                    self._stats["last_ytc_per_video_count"] = len(per_video)
                    # Also write to awarebot stats for the iOS UI which already
                    # reads aware_stats['last_ytc_at'].
                    if self.awarebot is not None:
                        try:
                            self.awarebot._stats["last_ytc_at"] = self._stats["last_ytc_dedicated"]
                            self.awarebot._stats["ytc_runs"] = (
                                self.awarebot._stats.get("ytc_runs", 0) + 1
                            )
                        except Exception:
                            pass
                else:
                    log.info(f"[YTC-DEDICATED] cycle produced no per-video reports: {session_id}")
            except asyncio.CancelledError:
                log.info("[YTC-DEDICATED] cancelled")
                raise
            except Exception as e:
                log.error(f"[YTC-DEDICATED] run failed: {e}", exc_info=True)

            try:
                await asyncio.sleep(ytc_interval)
            except asyncio.CancelledError:
                raise

    async def _ytc_nightshift_loop(self) -> None:
        """LOOP — YouTube Council nightshift rollup (3am LOCAL nightly).

        Wave 11 task W11-1. Fires once at 3:00 AM local time. Reads every
        per-video report written during the prior day under
        ``intelligence-scan/council-reports/youtube/<yesterday>/``,
        calls ``run_youtube_nightshift(yesterday_date)`` which runs the
        same ``synthesize_rollup()`` the legacy hourly loop used to call,
        and writes the resulting daily rollup as ``nightshift-brief.json``
        + ``nightshift-brief.md`` into that same date directory so it's
        ready for the morning operator.

        Cost gated on the ``ytc`` source budget (~$0.30 estimated). Heavy
        work is bracketed in ``long_running_ctx("ncl-night-watch")`` so the
        stall watchdog uses the relaxed (300s) threshold during synthesis.
        """
        from ..cost_tracker import check_budget, record_cost

        log.info("[YTC-NIGHTSHIFT] loop started — will fire daily at 3:00 AM local")

        # Startup grace so other Brain init work finishes before we even
        # think about computing the next 3am-local target.
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[YTC-NIGHTSHIFT] Emergency stop active — halting loop")
                break

            # ── Compute seconds until next 3am LOCAL ───────────────────
            try:
                now_local = datetime.now()  # naive, system local tz
                target = now_local.replace(hour=3, minute=0, second=0, microsecond=0)
                if now_local >= target:
                    target += timedelta(days=1)
                sleep_secs = (target - now_local).total_seconds()
                log.info(
                    "[YTC-NIGHTSHIFT] next run at %s (%.0fs)",
                    target.isoformat(),
                    sleep_secs,
                )
                await asyncio.sleep(sleep_secs)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("[YTC-NIGHTSHIFT] sleep-target compute failed: %s", e, exc_info=True)
                try:
                    await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    raise
                continue

            # ── Fire the rollup synthesis ─────────────────────────────
            try:
                # W13 P1-A: bill YTC nightshift against `anthropic` (the
                # actual provider). Previously billed against `ytc`
                # which had a $0 cap = unlimited spend.
                if not await check_budget("anthropic", 0.30):
                    log.warning(
                        "[YTC-NIGHTSHIFT] anthropic daily budget exhausted — skipping tonight's rollup"  # noqa: E501
                    )
                    continue

                yesterday_local = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
                session_id = (
                    f"ytc-nightshift-{yesterday_local}-"
                    f"{datetime.now(timezone.utc).strftime('%H%M%S')}"
                )
                log.info(
                    "[YTC-NIGHTSHIFT] starting rollup for %s as %s",
                    yesterday_local,
                    session_id,
                )

                from ..councils.runner import run_youtube_nightshift

                # Use night-watch deadband — nightshift synthesis is heavy
                # (Sonnet rollup + write) and may exceed the default 90s
                # stall threshold.
                async with self.long_running_ctx("ncl-night-watch"):
                    rollup = await run_youtube_nightshift(yesterday_local, session_id)

                if rollup is None:
                    log.info(
                        "[YTC-NIGHTSHIFT] no rollup produced for %s "
                        "(insufficient per-video reports or empty day)",
                        yesterday_local,
                    )
                    self._stats["last_ytc_nightshift_skipped"] = datetime.now(
                        timezone.utc
                    ).isoformat()
                    continue

                ncl_base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
                date_dir = (
                    ncl_base / "intelligence-scan" / "council-reports" / "youtube" / yesterday_local
                )
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, lambda: date_dir.mkdir(parents=True, exist_ok=True)
                )

                # Persist nightshift-brief.json
                brief_path = date_dir / "nightshift-brief.json"
                brief_data = rollup.to_dict()
                brief_data.update(
                    {
                        "session_id": session_id,
                        "status": "complete",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "auto_triggered": True,
                        "report_type": "nightshift_rollup",
                        "rolled_up_date": yesterday_local,
                        "spawned_by": "ncl-ytc-nightshift",
                    }
                )
                # W13 followup: serialize OFF the event loop — nightshift
                # rollup brief_data is the biggest YTC artifact (~500KB-1MB
                # with full rollup insights + per-video summaries), and
                # the 3am loop runs once but a sync dump here would block
                # everything else for 200-500ms.
                brief_json = await asyncio.to_thread(json.dumps, brief_data, default=str, indent=2)
                async with aiofiles.open(brief_path, "w") as f:
                    await f.write(brief_json)

                # Persist nightshift-brief.md (human-readable for morning op)
                md_lines: list[str] = []
                md_lines.append(f"# YouTube Council — Nightshift Brief ({yesterday_local})\n")
                md_lines.append(f"_Session: {session_id}_\n")
                md_lines.append(f"_Synthesized: {datetime.now(timezone.utc).isoformat()}_\n\n")
                md_lines.append(f"**Per-video reports rolled up:** {rollup.sources_processed}  \n")
                md_lines.append(
                    f"**Total content duration:** {rollup.total_duration_hours:.1f}h  \n"
                )
                md_lines.append(f"**Insight count:** {len(rollup.insights)}  \n\n")
                if rollup.summary:
                    md_lines.append("## Executive Summary\n\n")
                    md_lines.append(rollup.summary + "\n\n")
                if rollup.raw_analysis:
                    md_lines.append("## Full Analysis\n\n")
                    md_lines.append(rollup.raw_analysis + "\n\n")
                if rollup.insights:
                    md_lines.append("## Insights\n\n")
                    for i, ins in enumerate(rollup.insights, 1):
                        md_lines.append(
                            f"### {i}. [{ins.category.value}] {ins.title} "
                            f"(conf {ins.confidence:.0%})\n\n{ins.description}\n\n"
                        )
                md_path = date_dir / "nightshift-brief.md"
                async with aiofiles.open(md_path, "w") as f:
                    await f.write("".join(md_lines))

                # Record cost (~$0.30 estimated — single Sonnet rollup call)
                # W13 P1-A: bill against `anthropic` (the actual provider).
                try:
                    await record_cost(
                        "anthropic",
                        0.30,
                        "ytc_nightshift_rollup",
                        detail=f"nightshift rollup {yesterday_local} ({session_id})",
                    )
                except Exception as ce:
                    log.warning("[YTC-NIGHTSHIFT] record_cost failed: %s", ce)

                log.info(
                    "[YTC-NIGHTSHIFT] complete: %s — %d insights, %.1fh content, "
                    "ready for morning at %s",
                    yesterday_local,
                    len(rollup.insights),
                    rollup.total_duration_hours,
                    brief_path,
                )
                self._stats["last_ytc_nightshift"] = datetime.now(timezone.utc).isoformat()
                self._stats["ytc_nightshift_runs"] = self._stats.get("ytc_nightshift_runs", 0) + 1
                self._stats["last_ytc_nightshift_insights"] = len(rollup.insights)
                self._stats["last_ytc_nightshift_date"] = yesterday_local
            except asyncio.CancelledError:
                log.info("[YTC-NIGHTSHIFT] cancelled")
                raise
            except Exception as e:
                log.error("[YTC-NIGHTSHIFT] cycle failed: %s", e, exc_info=True)

    async def _afternoon_debrief_loop(self) -> None:
        """LOOP 20 (Wave 14X-Y Phase 2, 2026-05-29) — Afternoon Debrief at
        16:30 local daily. Reads today's outcomes + closes the loop with
        a single Opus synthesis. ~$0.08/run."""
        from ..cost_tracker import check_budget

        log.info("[AFTERNOON-DEBRIEF] loop started — will fire daily at 16:30 local")
        try:
            await asyncio.sleep(120)  # startup grace
        except asyncio.CancelledError:
            raise

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                break
            try:
                now_local = datetime.now()
                target = now_local.replace(hour=16, minute=30, second=0, microsecond=0)
                if now_local >= target:
                    target += timedelta(days=1)
                sleep_secs = (target - now_local).total_seconds()
                log.info(
                    "[AFTERNOON-DEBRIEF] next run at %s (%.0fs)",
                    target.isoformat(),
                    sleep_secs,
                )
                await asyncio.sleep(sleep_secs)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("[AFTERNOON-DEBRIEF] sleep compute failed: %s", e)
                try:
                    await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    raise
                continue

            try:
                if not await check_budget("anthropic", 0.10):
                    log.warning("[AFTERNOON-DEBRIEF] anthropic budget exhausted — skipping")
                    continue
                from ..intelligence.afternoon_debrief import build_debrief

                async with self.long_running_ctx("ncl-afternoon-debrief"):
                    debrief = await build_debrief()
                if debrief and debrief.get("synthesis"):
                    self._stats["last_afternoon_debrief"] = datetime.now(timezone.utc).isoformat()
                    log.info(
                        "[AFTERNOON-DEBRIEF] complete in %.1fs",
                        debrief.get("elapsed_s", 0),
                    )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("[AFTERNOON-DEBRIEF] cycle error: %s", e, exc_info=True)

    async def _cross_reference_loop(self) -> None:
        """LOOP 19 (Wave 14X-Y, 2026-05-29) — cross-reference promotion.

        Every 5 minutes, scans the AWAREBOT signal stream for ticker /
        theme / news+trends convergences. Writes promoted candidates to
        ``data/cross_reference/promotions.jsonl`` for TRADERAGENT (auto-
        trader) pickup. Pure pull-from-disk, no LLM cost.
        """
        log.info("[CROSS-REF] loop started (300s cadence)")
        try:
            await asyncio.sleep(60)  # initial delay
        except asyncio.CancelledError:
            raise

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[CROSS-REF] Emergency stop — halting")
                break
            try:
                from ..cross_reference import scan_and_promote

                new_promotions = await asyncio.to_thread(scan_and_promote, 4)
                if new_promotions:
                    self._stats["last_cross_ref_run"] = datetime.now(timezone.utc).isoformat()
                    self._stats["last_cross_ref_count"] = len(new_promotions)
                    log.info("[CROSS-REF] promoted %d candidates this cycle", len(new_promotions))
            except asyncio.CancelledError:
                log.info("[CROSS-REF] cancelled")
                raise
            except Exception as e:
                log.error("[CROSS-REF] cycle error: %s", e, exc_info=True)
            try:
                await asyncio.sleep(300)
            except asyncio.CancelledError:
                raise

    async def _bm25_rebuild_loop(self) -> None:
        """LOOP 18 — BM25 keyword index maintenance for Loop-11 fusion.

        Cadence: 1800s (30 min). Each tick:
          1. Lazily attach a ``BM25Index`` to the memory store (idempotent).
          2. If the index is missing or older than 1h → full ``build()``.
          3. Otherwise, scan ``units.jsonl`` for new ``unit_id`` values that
             aren't in the index and call ``update(new_ids)``. Incremental
             update falls back to full rebuild internally on failure.
          4. Log the resulting stats.

        Build is dispatched via ``asyncio.to_thread`` because BM25Okapi
        construction and full ``get_scores`` are pure-Python CPU work.
        """
        log.info("[BM25] rebuild loop started (1800s cadence)")

        memory_store = getattr(self.brain, "memory_store", None)
        if memory_store is None:
            log.warning("[BM25] no memory_store on brain — loop is a no-op")
            return

        # Attach exactly one index to the memory store (other code can read it
        # via ``brain.memory_store._bm25_index``).
        try:
            if not getattr(memory_store, "_bm25_index", None):
                memory_store._bm25_index = BM25Index(memory_store)
            bm25 = memory_store._bm25_index
        except Exception as e:
            log.error("[BM25] failed to construct BM25Index: %s — loop exiting", e)
            return

        REBUILD_AFTER_S = 60 * 60  # 1 hour  # noqa: N806

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[BM25] Emergency stop active — halting loop")
                break

            try:
                stats = bm25.stats() or {}
                last_built = stats.get("last_built")
                needs_full = False
                if not last_built or stats.get("docs", 0) == 0:
                    needs_full = True
                else:
                    try:
                        ts = datetime.fromisoformat(last_built.replace("Z", "+00:00"))
                        if (datetime.now(timezone.utc) - ts).total_seconds() > REBUILD_AFTER_S:
                            needs_full = True
                    except Exception:
                        needs_full = True

                if needs_full:
                    log.info("[BM25] full rebuild (last_built=%s)", last_built)
                    indexed = await asyncio.to_thread(bm25.build)
                    new_stats = bm25.stats() or {}
                    log.info(
                        "[BM25] index size: %d docs, vocab: %d, last_built: %s, took %.2fs",
                        new_stats.get("docs", indexed),
                        new_stats.get("vocabulary_size", 0),
                        new_stats.get("last_built"),
                        new_stats.get("build_seconds") or 0.0,
                    )
                    self._stats["last_bm25_build"] = new_stats.get("last_built")
                    self._stats["bm25_docs"] = new_stats.get("docs", indexed)
                    self._stats["bm25_vocab"] = new_stats.get("vocabulary_size", 0)
                else:
                    # Incremental — diff unit_ids on disk against the index.
                    new_ids: list[str] = []
                    indexed_ids = set(getattr(bm25, "_unit_pos", {}).keys())
                    try:

                        def _scan_new() -> list[str]:
                            out: list[str] = []
                            with open(memory_store.memory_file, "r") as f:
                                for line in f:
                                    line = line.strip()
                                    if not line:
                                        continue
                                    try:
                                        obj = json.loads(line)
                                    except json.JSONDecodeError:
                                        continue
                                    uid = obj.get("unit_id")
                                    if uid and uid not in indexed_ids:
                                        out.append(uid)
                            return out

                        new_ids = await asyncio.to_thread(_scan_new)
                    except FileNotFoundError:
                        new_ids = []
                    except Exception as scan_err:
                        log.warning("[BM25] new-id scan failed: %s", scan_err)

                    if new_ids:
                        added = await asyncio.to_thread(bm25.update, new_ids)
                        new_stats = bm25.stats() or {}
                        log.info(
                            "[BM25] incremental +%d → index size: %d docs, vocab: %d, last_built: %s",  # noqa: E501
                            added,
                            new_stats.get("docs", 0),
                            new_stats.get("vocabulary_size", 0),
                            new_stats.get("last_built"),
                        )
                        self._stats["last_bm25_build"] = new_stats.get("last_built")
                        self._stats["bm25_docs"] = new_stats.get("docs", 0)
                        self._stats["bm25_vocab"] = new_stats.get("vocabulary_size", 0)
                    else:
                        log.debug(
                            "[BM25] no new units (index has %d docs, last_built %s)",
                            stats.get("docs", 0),
                            last_built,
                        )
            except asyncio.CancelledError:
                log.info("[BM25] cancelled")
                raise
            except Exception as e:
                log.error("[BM25] tick failed: %s", e, exc_info=True)

            try:
                await asyncio.sleep(1800)
            except asyncio.CancelledError:
                raise

    # ─────────────────────────────────────────────────────────────────
    async def _city_events_loop(self) -> None:
        """LOOP 19 (2026-05-22) — per-city "fun finder" scanner.

        Cadence: 3600s (1 hour). Each tick:
          1. Iterate every registered city (CITIES).
          2. Call ``CityEventScanner.scan_city(...)`` (lookback=0, lookahead=30).
          3. Scanner auto-enqueues events into MemoryStore via async_writer
             with source "awarebot:city_events:{city_id}".
          4. Persist the per-city payload to ``data/calendar/city_events_cache.jsonl``
             so iOS can do an instant disk read on cold start.
        """
        log.info("[CITY-EVENTS] loop started (3600s cadence)")
        try:
            from ..calendar.city_scanner import get_city_scanner, write_cache_atomic
            from ..calendar.local_events import CITIES as _CITIES
        except Exception as e:
            log.error("[CITY-EVENTS] cannot import city_scanner: %s — loop exiting", e)
            return

        # Wire the async_writer (if available) so memory ingestion happens.
        # Prefer the singleton via get_async_writer() — falls back to self._async_writer.
        async_writer = getattr(self, "_async_writer", None)
        if async_writer is None:
            try:
                from ..memory.async_writer import get_async_writer

                async_writer = get_async_writer()
            except Exception:
                async_writer = None
        scanner = get_city_scanner(async_writer=async_writer)

        # Initial warm-up delay (give async_writer drainers a head start)
        try:
            await asyncio.sleep(120)
        except asyncio.CancelledError:
            raise

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[CITY-EVENTS] Emergency stop active — halting loop")
                break

            cycle_start = time.time()
            success_count = 0
            event_total = 0

            for city_id in list(_CITIES.keys()):
                if EMERGENCY_STOP_EVENT.is_set():
                    break
                try:
                    payload = await scanner.scan_city(
                        city_id,
                        lookback_days=0,
                        lookahead_days=30,
                        bypass_cache=True,
                    )
                    event_total += payload.get("stats", {}).get("total_events", 0)
                    # Atomic cache write per city payload
                    write_cache_atomic(payload)
                    success_count += 1
                    log.debug(
                        "[CITY-EVENTS] %s ok: %d events, sources=%s",
                        city_id,
                        payload.get("stats", {}).get("total_events", 0),
                        payload.get("sources_used", []),
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.warning("[CITY-EVENTS] %s failed: %s", city_id, e)

            elapsed = time.time() - cycle_start
            self._stats["last_city_events_run"] = datetime.now(timezone.utc).isoformat()
            self._stats["city_events_total"] = event_total
            self._stats["city_events_cities_ok"] = success_count
            log.info(
                "[CITY-EVENTS] cycle complete: %d/%d cities, %d events, %.1fs",
                success_count,
                len(_CITIES),
                event_total,
                elapsed,
            )

            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise

    async def _stocks_scan_loop(self) -> None:
        """LOOP 20 (2026-05-22 EOD) — autonomous stock scanner (GOAT + BRAVO).

        Cadence: 4 hours (14400s). Market-hours gated:
          * NYSE open M-F 09:30-16:00 ET (matches portfolio_manager._is_market_open).
          * Off-hours ticks log + sleep, no scan work performed.

        Each in-hours tick:
          1. Run GOAT + BRAVO scans in parallel on the full WATCHLIST_TICKERS list.
          2. Both scans go through the enriched pipeline — portfolio dedup,
             earnings filter (next 7d), liquidity gate, IVR gate, options-flow
             confirmation, dark-pool support refinement, JSONL append, memory
             enqueue (importance 70 GOAT / 55 BRAVO).
          3. Stats stamped on self._stats so /autonomous/loops can render last_run.

        Stat keys:
          last_stocks_scan, goat_hits_total, bravo_hits_total,
          last_stocks_scan_duration_s, last_stocks_scan_skipped_reason.
        """
        log.info("[STOCKS-SCAN] loop started (4h cadence, NYSE hours only)")
        try:
            from ..portfolio.portfolio_manager import _is_market_open
            from ..stocks.scanner import StockScanner
            from ..stocks.watchlist import WATCHLIST_TICKERS
        except Exception as e:
            log.error("[STOCKS-SCAN] import failed: %s — loop exiting", e)
            return

        async_writer = getattr(self, "_async_writer", None)
        if async_writer is None:
            try:
                from ..memory.async_writer import get_async_writer

                async_writer = get_async_writer()
            except Exception:
                async_writer = None

        scanner = StockScanner(async_writer=async_writer)

        # Try to wire portfolio manager (already running in lifespan)
        try:
            from ..portfolio.portfolio_routes import _portfolio_manager as _pm

            if _pm is not None:
                scanner.attach_portfolio_manager(_pm)
        except Exception:
            pass

        # Warm-up delay so Brain finishes booting
        try:
            await asyncio.sleep(120)
        except asyncio.CancelledError:
            raise

        STOCKS_SCAN_INTERVAL = 14400  # 4h  # noqa: N806
        IDLE_SLEEP = 600  # 10m poll when market closed  # noqa: N806

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[STOCKS-SCAN] Emergency stop active — halting loop")
                break

            if not _is_market_open():
                self._stats["last_stocks_scan_skipped_reason"] = "market_closed"
                try:
                    await asyncio.sleep(IDLE_SLEEP)
                except asyncio.CancelledError:
                    raise
                continue

            cycle_start = time.time()
            # Late-bind async_writer if it appeared after loop start
            if scanner.async_writer is None:
                aw2 = getattr(self, "_async_writer", None)
                if aw2 is not None:
                    scanner.attach_async_writer(aw2)
            try:
                goat_task = asyncio.create_task(
                    scanner.run_goat_scan_enriched(WATCHLIST_TICKERS),
                )
                bravo_task = asyncio.create_task(
                    scanner.run_bravo_scan_enriched(WATCHLIST_TICKERS),
                )
                (goat_results, goat_meta), (bravo_results, bravo_meta) = await asyncio.gather(
                    goat_task,
                    bravo_task,
                )
                goat_hits = len(goat_results)
                bravo_hits = len(bravo_results)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("[STOCKS-SCAN] cycle failed: %s", e)
                goat_hits = bravo_hits = 0

            elapsed = time.time() - cycle_start
            now_iso = datetime.now(timezone.utc).isoformat()
            self._stats["last_stocks_scan"] = now_iso
            self._stats["last_stocks_scan_duration_s"] = round(elapsed, 2)
            self._stats["goat_hits_total"] = self._stats.get("goat_hits_total", 0) + goat_hits
            self._stats["bravo_hits_total"] = self._stats.get("bravo_hits_total", 0) + bravo_hits
            self._stats["last_stocks_scan_goat_hits"] = goat_hits
            self._stats["last_stocks_scan_bravo_hits"] = bravo_hits
            self._stats.pop("last_stocks_scan_skipped_reason", None)
            log.info(
                "[STOCKS-SCAN] cycle complete: GOAT %d / BRAVO %d in %.1fs",
                goat_hits,
                bravo_hits,
                elapsed,
            )

            try:
                await asyncio.sleep(STOCKS_SCAN_INTERVAL)
            except asyncio.CancelledError:
                raise
