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

from ..ncl_brain.models import InsightSignal
from ..governance.emergency_stop import EMERGENCY_STOP_EVENT
from .signal_processor import SignalProcessor
from ..journal.store import JournalStore
from ..journal.reflection_engine import ReflectionEngine, ContextAwareTips
from ..awarebot.agent import Awarebot
from ..memory.working_context import DailyContextWindow
from ..memory.retrieval import BM25Index
from ..notifications import get_alert_dispatcher, enqueue_alert
from ..health.rollup import build_health_rollup, write_rollup_atomic

log = logging.getLogger("ncl.autonomous")


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
        log.info(f"  Scanner intervals: X={self.config.x_scan_interval}s, "
                 f"YT={self.config.youtube_scan_interval}s")
        log.info(f"  Prediction interval: {self.config.prediction_interval}s")
        log.info(f"  Memory consolidation: {self.config.memory_consolidation_interval}s")
        log.info(f"  Council trigger threshold: {self.council_trigger_threshold}")
        if self.intelligence_engine:
            log.info(f"  Intel brief interval: {self.config.intelligence_brief_interval}s")
            log.info(f"  Intel collection interval: {self.config.intelligence_collection_interval}s")
        log.info(f"  Working context: 6am assembly, noon refresh, 11pm EOD")
        log.info(f"  Journal reflection: 10pm ET daily")
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
                                    "system": system or "You are a journaling synthesis assistant. Return valid JSON only.",
                                    "messages": [{"role": "user", "content": prompt}],
                                },
                            )
                            resp.raise_for_status()
                            data = resp.json()
                            try:
                                from ..cost_tracker import record_cost
                                usage = data.get("usage", {}) or {}
                                cost = (usage.get("input_tokens", 0) * 0.80
                                        + usage.get("output_tokens", 0) * 4.00) / 1_000_000
                                if cost > 0:
                                    await record_cost("anthropic", cost, "journal_reflection")
                            except Exception:
                                pass
                            return data["content"][0]["text"]
                _llm_client = _AnthropicReflectionClient(_anth_key)
                log.info("  Journal reflection LLM: Claude 3.5 Haiku")
            else:
                log.warning("  Journal reflection LLM: NONE (template fallback) — set ANTHROPIC_API_KEY")
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
            asyncio.create_task(self._working_context_loop(), name="ncl-working-ctx"),
        ]

        # Awarebot runs its own event loop (replaces scanner, intel, brief, prediction loops)
        if self.awarebot:
            self._tasks.append(
                asyncio.create_task(self.awarebot.run(), name="ncl-awarebot-agent")
            )

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
        self._tasks.append(
            asyncio.create_task(self._night_watch_loop(), name="ncl-night-watch")
        )

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
        self._tasks.append(
            asyncio.create_task(self._cache_warmer_loop(), name="ncl-cache-warmer")
        )
        # Loop 4: centralized rate-limited ntfy dispatcher
        self._tasks.append(
            asyncio.create_task(self._alert_dispatch_loop(), name="ncl-alert-dispatch")
        )
        # Loop 5: dedicated YouTube Council — split from Awarebot, own budget
        self._tasks.append(
            asyncio.create_task(self._ytc_dedicated_loop(), name="ncl-ytc-dedicated")
        )
        # Loop 6: BM25 keyword index rebuild — backs FusedRetriever (Loop 11)
        self._tasks.append(
            asyncio.create_task(self._bm25_rebuild_loop(), name="ncl-bm25-rebuild")
        )
        # Loop 7 (2026-05-22): per-city "fun finder" scanner — 1h cadence
        self._tasks.append(
            asyncio.create_task(self._city_events_loop(), name="ncl-city-events")
        )

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
                        self._stats["last_async_writer_tick"] = datetime.now(timezone.utc).isoformat()
                        self._stats["async_writer_queue_size"] = s.get("queue_size", 0)
                        self._stats["async_writer_drained"] = s.get("drained_total", 0)
                        self._stats["async_writer_dlq_size"] = s.get("dlq_size", 0)
                    except Exception:
                        pass
            self._async_writer_supervisor = _async_writer_supervisor
            self._tasks.append(
                asyncio.create_task(_async_writer_supervisor(), name="ncl-async-writer")
            )
        except Exception as e:
            log.warning(f"[SCHEDULER] async-writer disabled: {e}")
            self._async_writer = None

        # Memory budget telemetry — per-tier token spend, 15m rollup + ntfy
        try:
            from ..memory.budget_tracker import run_budget_cycle
            async def _memory_budget_loop():
                while self._running and not EMERGENCY_STOP_EVENT.is_set():
                    try:
                        await run_budget_cycle(stats=self._stats)
                    except Exception as ex:
                        log.warning(f"[ncl-memory-budget] {ex}")
                    await asyncio.sleep(900)
            self._memory_budget_loop = _memory_budget_loop
            self._tasks.append(
                asyncio.create_task(_memory_budget_loop(), name="ncl-memory-budget")
            )
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
                    self.brain, interval=3600, threshold=50,
                    is_running=lambda: self._running,
                    emergency_stop=EMERGENCY_STOP_EVENT,
                    stats_dict=self._stats,
                )
            self._chroma_gc_wrapper = _chroma_gc_wrapper
            self._tasks.append(
                asyncio.create_task(_chroma_gc_wrapper(), name="ncl-chroma-gc")
            )
        except Exception as e:
            log.warning(f"[SCHEDULER] chroma-gc loop disabled: {e}")

        # Loop 5: conflict arbitration — adaptive cadence (5m burst / 10m
        # busy / 15m calm). Audit 2026-05-22 bumped per-cycle cap 5 -> 50
        # and added a quality filter (importance_divergence > 40 AND
        # >=3 shared entities) so we don't drown council in low-signal
        # contradictions.
        try:
            from ..memory.conflict_resolver import (
                ConflictResolver, run_conflict_arbitration_cycle,
                CADENCE_BURST_S, CADENCE_BUSY_S, CADENCE_CALM_S,
                BACKLOG_BURST, BACKLOG_BUSY,
            )
            self._conflict_resolver = ConflictResolver(
                self.brain.memory_store,
                knowledge_graph=getattr(self.brain, "knowledge_graph", None),
            )
            async def _conflict_arb_loop():
                cadence = CADENCE_CALM_S
                while self._running and not EMERGENCY_STOP_EVENT.is_set():
                    try:
                        summary = await run_conflict_arbitration_cycle(
                            self.brain, self._stats,
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
            self._tasks.append(
                asyncio.create_task(_conflict_arb_loop(), name="ncl-conflict-arb")
            )
        except Exception as e:
            log.warning(f"[SCHEDULER] conflict-arb loop disabled: {e}")

        # Loop 6: staleness detector (6h — re-verify high-importance facts)
        try:
            from ..memory.staleness_detector import StalenessDetector, staleness_detector_loop
            self._staleness_detector = StalenessDetector(
                self.brain.memory_store, awarebot=self.awarebot,
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
            from ..memory.narrative_threads import _narrative_thread_loop
            # Bind as bound method on this instance
            import types
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
        self._tasks.append(
            asyncio.create_task(self._dedup_scan_loop(), name="ncl-dedup-scan")
        )

        # Attach a done-callback to every task so a silent crash (unobserved
        # task exception) gets logged instead of disappearing.
        def _task_done(task: asyncio.Task) -> None:
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                log.error(
                    f"[SCHEDULER] task '{task.get_name()}' DIED: "
                    f"{type(exc).__name__}: {exc!r}",
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
            "ncl-bm25-rebuild": self._bm25_rebuild_loop,
            "ncl-city-events": self._city_events_loop,
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
                self._task_factories["ncl-staleness"] = lambda: staleness_detector_loop(self, self._staleness_detector)
            except Exception:
                pass
        if hasattr(self, "_narrative_thread_loop"):
            self._task_factories["ncl-narrative-threads"] = self._narrative_thread_loop
        # ncl-dedup-scan (replaces inline Night Watch M1)
        self._task_factories["ncl-dedup-scan"] = self._dedup_scan_loop
        # ncl-claude-md-refresh (24h refresh of system-doc memory units)
        if hasattr(self, "_claude_md_refresh_loop"):
            self._task_factories["ncl-claude-md-refresh"] = self._claude_md_refresh_loop
        # 2026-05-22 batch 2
        if getattr(self, "_async_writer", None) is not None and hasattr(self, "_async_writer_supervisor"):
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
        self._supervisor_task = asyncio.create_task(
            self._supervisor_loop(), name="ncl-supervisor"
        )

        await self._log_autonomous_event("scheduler_started", {
            "loops": [t.get_name() for t in self._tasks],
            "config": {
                "x_scan_interval": self.config.x_scan_interval,
                "youtube_scan_interval": self.config.youtube_scan_interval,
                "reddit_scan_interval": self.config.reddit_scan_interval,
                "prediction_interval": self.config.prediction_interval,
                "memory_consolidation_interval": self.config.memory_consolidation_interval,
                "council_trigger_threshold": self.council_trigger_threshold,
            },
        })

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
                        f"AUTONOMOUS COUNCIL — {len(council_flags)} high-priority signals detected. "
                        f"Themes: {', '.join(list(themes)[:10])}. "
                        f"Analyze these converging signals, assess implications for NARTIX operations, "
                        f"and recommend strategic actions or mandate adjustments."
                    )

                # Check 2: Scheduled strategic review
                elif (now - last_strategic_review).total_seconds() >= strategic_review_interval:
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
                        # spawn_council_session() is the high-level brain wrapper.
                        # It calls council_engine.spawn_session() + run_debate(),
                        # persists, and returns a CouncilSession Pydantic model.
                        # (Was calling non-existent council_engine.spawn_council —
                        # AttributeError raised on every spawn attempt before this fix.)
                        topic = f"autonomous:{council_trigger}"
                        session = await self.brain.spawn_council_session(
                            topic=topic,
                            prompt=council_prompt,
                            members=None,  # default full membership
                        )

                        if session:
                            consensus_text = (session.consensus or "")[:500]
                            agreement_pct = (
                                session.consensus_score.agreement_pct
                                if session.consensus_score else 0.0
                            )

                            # Store council output in memory
                            await self.brain.memory_store.create_unit(
                                content=(
                                    f"Autonomous council ({council_trigger}): "
                                    f"{consensus_text}"
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

                            await self._log_autonomous_event("council_auto_spawned", {
                                "trigger": council_trigger,
                                "session_id": session.session_id,
                                "consensus_score": agreement_pct,
                                "recommendations": len(session.recommendations or []),
                            })

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
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[MEMORY] Emergency stop active — halting loop")
                break
            try:
                log.info("[MEMORY] Starting consolidation cycle...")

                store = self.brain.memory_store
                stats_before = await store.stats()

                # Enhanced consolidation with reflection loop
                try:
                    if hasattr(self.brain.memory_store, 'consolidate_v2'):
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
                log.info(f"[MEMORY] Consolidation complete — "
                         f"before: {consolidation_result.get('total_before', 0)}, "
                         f"after: {consolidation_result.get('total_after', 0)}, "
                         f"pruned: {pruned}, merged: {merged}")

                await self._log_autonomous_event("memory_consolidation", {
                    "stats_before": stats_before,
                    "stats_after": stats_after,
                    "consolidation": consolidation_result,
                })

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
                    "mandate-generation", "research-pipeline",
                    "intelligence-scan", "memory-processing",
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

        from ..ncl_brain.models import MandateStatus
        from datetime import datetime as _dt, timezone as _tz

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
                            mid for mid, m in self.brain.mandates.items()
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
                    (p / sub).exists()
                    for sub in ("aac-reports", "brs-reports", "ncc-reports")
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
            log.exception(
                f"[FEEDBACK] init failed; loop dying: {type(e).__name__}: {e!r}"
            )
            return

        log.info("[FEEDBACK] loop entering scan cycle (interval=300s)")
        ticks = 0
        while self._running:
            ticks += 1
            try:
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
                log.exception(
                    f"[FEEDBACK] tick {ticks} error: {type(e).__name__}: {e!r}"
                )

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
        from ..ncl_brain.models import PillarType, MandateStatus

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
            proposals.append((
                pillar,
                7,
                f"RESOLVE: {blk[:80]}",
                f"Blocker reported by {pillar_str} (source mandate: {mid}). "
                f"Synthesis note {note.synthesis_id}. Resolve and report back.",
            ))

        for adj in note.suggested_adjustments:
            adj_clean = (adj or "").strip()
            if not adj_clean:
                continue
            # Default to NCC for adjustments without explicit pillar tagging;
            # NCC owns execution and can re-route if needed.
            proposals.append((
                PillarType.NCC,
                5,
                f"FEEDBACK: {adj_clean[:80]}",
                f"Pillar-suggested adjustment from synthesis {note.synthesis_id}: "
                f"{adj_clean}",
            ))

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
                            except Exception:
                                pass

                        # Gather working context
                        wc_data = None
                        if self._working_context:
                            try:
                                wc_data = self._working_context.get_current()
                            except Exception:
                                pass

                        # Generate reflection
                        reflection = await self._reflection_engine.generate_daily_reflection(
                            intel_brief=intel_brief_data,
                            working_context=wc_data,
                        )

                        self._stats["journal_reflections_generated"] = self._stats.get("journal_reflections_generated", 0) + 1
                        self._stats["last_journal_reflection"] = datetime.now(timezone.utc).isoformat()

                        # Push summary to iPhone
                        try:
                            from ..strike_point_orchestrator import notify_intelligence_brief
                            summary_text = (
                                f"Daily Reflection — {today}\n\n"
                                f"{reflection.summary}\n\n"
                            )
                            if reflection.patterns_noticed:
                                summary_text += "Patterns: " + ", ".join(reflection.patterns_noticed[:3]) + "\n"
                            if reflection.tomorrow_focus:
                                summary_text += "Tomorrow: " + ", ".join(reflection.tomorrow_focus[:3]) + "\n"

                            await notify_intelligence_brief({
                                "brief_type": "journal_reflection",
                                "executive_summary": summary_text,
                                "brief_id": reflection.reflection_id,
                            })
                            log.info(f"[JOURNAL] Reflection pushed to iPhone: {reflection.reflection_id}")
                        except ImportError:
                            log.debug("[JOURNAL] Push notification not available")
                        except Exception as e:
                            log.warning(f"[JOURNAL] Push failed: {e}")

                        await self._log_autonomous_event("journal_reflection", {
                            "entries_count": reflection.entries_count,
                            "patterns": len(reflection.patterns_noticed),
                            "research_topics": len(reflection.research_queue),
                            "date": str(today),
                        })

                        log.info(f"[JOURNAL] Reflection complete: {reflection.entries_count} entries → "
                                 f"{len(reflection.patterns_noticed)} patterns, "
                                 f"{len(reflection.research_queue)} research topics")

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
                        self._stats["working_ctx_assemblies"] = self._stats.get("working_ctx_assemblies", 0) + 1
                        self._stats["last_working_ctx"] = datetime.now(timezone.utc).isoformat()

                        await self._log_autonomous_event("working_context_assembled", {
                            "date": str(today),
                            "items": len(ctx.items),
                            "themes": ctx.themes[:10],
                            "stats": ctx.stats,
                        })
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
            try:
                result = await run_dedup_scan(
                    self.brain,
                    window_size=500,
                    max_merges=200,
                )

                now_iso = datetime.now(timezone.utc).isoformat()
                merged = int(result.get("merged", 0) or 0)
                self._stats["last_dedup_scan"] = now_iso
                self._stats["dedup_scan_runs"] = (
                    self._stats.get("dedup_scan_runs", 0) + 1
                )
                self._stats["dedup_scan_merged"] = (
                    self._stats.get("dedup_scan_merged", 0) + merged
                )
                self._stats["last_dedup_scan_candidates"] = int(
                    result.get("candidates_checked", 0) or 0
                )
                self._stats["last_dedup_scan_dupes_found"] = int(
                    result.get("dupes_found", 0) or 0
                )
                self._stats["last_dedup_scan_duration_s"] = float(
                    result.get("duration_s", 0.0) or 0.0
                )

                # Maintain 24h rolling merged total
                rolling_24h.append((now_iso, merged))
                cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                rolling_24h[:] = [
                    (ts, c) for ts, c in rolling_24h
                    if datetime.fromisoformat(ts) >= cutoff
                ]
                self._stats["last_dedup_scan_merged_24h"] = sum(
                    c for _, c in rolling_24h
                )

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
                    candidates.append(
                        datetime.fromtimestamp(newest_mtime, tz=timezone.utc)
                    )
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
        critical = any(
            "CRITICAL" in i or "CRASH" in i or "DEAD" in i
            for i in issues
        )
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

        await self._log_autonomous_event("night_watch", {
            "issues_count": len(issues),
            "critical": critical,
            "issues": issues[:20],
            "catchup": catchup,
        })

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
                    issues, len(issues) > 0, critical,
                    memory_report=memory_report,
                    intel_report=intel_report,
                    council_report=council_report,
                )
            except Exception as exc:
                log.error("[NIGHT-WATCH] Analyst phase failed: %s", exc)

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
            self._stats["night_watch_full_runs"] = (
                self._stats.get("night_watch_full_runs", 0) + 1
            )

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
        """
        Night Watch Phase 2 — Memory Maintenance Cycle.

        Runs 6 sequential maintenance tasks on the memory store:
          M1: Semantic duplicate detection (FREE)
          M2: Deep re-scoring of unscored units (Sonnet, ~$0.50)
          M3: Entity backfill for entity-less units (Sonnet, ~$0.30)
          M4: Stale fact detection via LLM (Sonnet + Gemini dual-model, ~$0.05)
          M5: Knowledge graph maintenance (FREE)
          M6: Entity normalization (Sonnet + Gemini consensus, ~$0.01)

        NEVER deletes memory units — all operations are additive or re-scoring.

        Returns:
            Dict with task results and overall stats.
        """
        import time
        import hashlib
        import re

        import httpx

        from ..cost_tracker import get_tracker
        from ..memory.importance_scorer import rule_based_score, llm_importance_score
        from ..memory.entity_extractor import fast_extract_entities, extract_entities_and_relationships
        from ..memory.reflection import MemoryReflector

        t0 = time.monotonic()
        report = {
            "duplicates_found": 0,
            "units_rescored": 0,
            "entities_extracted": 0,
            "stale_facts_found": 0,
            "kg_stats": {"nodes": 0, "edges": 0, "components": 0},
            "normalizations": 0,
            "total_cost_usd": 0.0,
            "duration_seconds": 0.0,
            "errors": [],
        }

        TASK_TIMEOUT = 30 * 60  # 30 minutes per task

        memory_store = getattr(self.brain, 'memory_store', None)
        if not memory_store:
            report["errors"].append("Memory store not available")
            report["duration_seconds"] = time.monotonic() - t0
            return report

        knowledge_graph = getattr(memory_store, '_knowledge_graph', None)
        if knowledge_graph is None:
            knowledge_graph = getattr(self.brain, 'knowledge_graph', None)

        tracker = await get_tracker()
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")

        log.info("[NIGHT-WATCH/MEMORY] Starting memory maintenance cycle")

        # ══════════════════════════════════════════════════════════════
        # Task M1: Semantic Duplicate Detection — OFFLOADED (2026-05-22)
        # ══════════════════════════════════════════════════════════════
        # M1's in-line implementation was wedging Night Watch:
        #   - scoped to ALL units (9.7K-strong) instead of the change frontier
        #   - counted every pair twice (both A→B and B→A queries fired)
        #   - last cycle reported 11,521 dupes among 9,710 units (i.e. each
        #     pair counted 2-3x) and timed out at 30 minutes
        # Now lives in its own loop: `ncl-dedup-scan` (6h, 500-newest window,
        # 200-merge cap). We just report the 24h rolling merge count here.
        try:
            merged_24h = int(self._stats.get("last_dedup_scan_merged_24h", 0) or 0)
            last_scan = self._stats.get("last_dedup_scan")
            last_candidates = int(self._stats.get("last_dedup_scan_candidates", 0) or 0)
            last_dupes = int(self._stats.get("last_dedup_scan_dupes_found", 0) or 0)
            report["duplicates_found"] = merged_24h  # backwards-compat key
            report["dedup_scan_merged_24h"] = merged_24h
            report["dedup_scan_last_run"] = last_scan
            report["dedup_scan_last_candidates"] = last_candidates
            report["dedup_scan_last_dupes"] = last_dupes
            log.info(
                "[NIGHT-WATCH/MEMORY] Task M1 (offloaded): dedicated ncl-dedup-scan "
                "loop merged %d units in last 24h (last cycle: %s, candidates=%d, "
                "pairs=%d)",
                merged_24h, last_scan or "never", last_candidates, last_dupes,
            )
        except Exception as e:
            log.error("[NIGHT-WATCH/MEMORY] Task M1 offload report failed: %s", e)
            report["errors"].append(f"M1: {e}")

        # ══════════════════════════════════════════════════════════════
        # Task M2: Deep Re-scoring (uses memory scorer - Sonnet, ~$1.80)
        # ══════════════════════════════════════════════════════════════
        try:
            task_t0 = time.monotonic()
            log.info("[NIGHT-WATCH/MEMORY] Task M2: Deep re-scoring of unscored units")

            if not api_key:
                log.info("[NIGHT-WATCH/MEMORY] M2 skipped — no ANTHROPIC_API_KEY")
            else:
                units = await memory_store._load_all_units()

                # Find units with no LLM importance score
                unscored = [u for u in units if u.llm_importance_score is None]
                # Limit to 200 per night
                unscored = unscored[:200]
                log.info("[NIGHT-WATCH/MEMORY] M2: %d unscored units found (capped at 200)", len(unscored))

                rescored_count = 0
                m2_cost = 0.0
                batch_size = 50
                units_by_id = {u.unit_id: u for u in units}

                for batch_start in range(0, len(unscored), batch_size):
                    if time.monotonic() - task_t0 > TASK_TIMEOUT:
                        log.warning("[NIGHT-WATCH/MEMORY] M2 timeout — aborting")
                        break

                    # Budget check before each batch
                    if not await tracker.can_spend("anthropic", 0.02):
                        log.warning("[NIGHT-WATCH/MEMORY] M2 budget exceeded — stopping")
                        break

                    batch = unscored[batch_start:batch_start + batch_size]
                    for unit in batch:
                        try:
                            llm_score = await llm_importance_score(
                                unit.content, unit.source,
                                unit.tags, timeout=10.0,
                            )
                            if llm_score is not None:
                                # Compute hybrid score: 70% LLM + 30% rule
                                rule_score = rule_based_score(unit.content, unit.source, unit.tags)
                                hybrid = (llm_score * 10 * 0.7) + (rule_score * 10 * 0.3)
                                hybrid = max(0.0, min(100.0, hybrid))

                                unit.llm_importance_score = llm_score
                                unit.importance = hybrid
                                units_by_id[unit.unit_id] = unit
                                rescored_count += 1

                                # Estimate per-call cost (Sonnet: $3.00/1M in, $15.00/1M out)
                                est_cost = 0.0016  # ~300 in + 50 out tokens typical
                                m2_cost += est_cost

                        except Exception as e:
                            log.debug("[NIGHT-WATCH/MEMORY] M2 scoring error: %s", e)
                            continue

                # Persist re-scored units
                if rescored_count > 0:
                    await memory_store._acquire_write()
                    try:
                        all_units = list(units_by_id.values())
                        await memory_store._rewrite_units(all_units)
                    finally:
                        memory_store._release_write()

                    # Record cost
                    await tracker.record(
                        "anthropic", m2_cost, "night_watch_memory",
                        f"deep re-scoring {rescored_count} units",
                    )
                    report["total_cost_usd"] += m2_cost

                report["units_rescored"] = rescored_count
                log.info(
                    "[NIGHT-WATCH/MEMORY] Task M2: re-scored %d units, cost $%.4f",
                    rescored_count, m2_cost,
                )

        except Exception as e:
            log.error("[NIGHT-WATCH/MEMORY] Task M2 failed: %s", e)
            report["errors"].append(f"M2: {e}")

        # ══════════════════════════════════════════════════════════════
        # Task M3: Entity Backfill (Sonnet, ~$1.20)
        # ══════════════════════════════════════════════════════════════
        try:
            task_t0 = time.monotonic()
            log.info("[NIGHT-WATCH/MEMORY] Task M3: Entity backfill")

            units = await memory_store._load_all_units()

            # Find units with importance >= 40 and no entities
            needs_entities = [
                u for u in units
                if u.importance >= 40.0 and not u.entities
            ]
            needs_entities = needs_entities[:100]  # Limit to 100 per night
            log.info("[NIGHT-WATCH/MEMORY] M3: %d entity-less units found (capped at 100)", len(needs_entities))

            entities_extracted = 0
            m3_cost = 0.0
            modified_ids: set[str] = set()

            for unit in needs_entities:
                if time.monotonic() - task_t0 > TASK_TIMEOUT:
                    log.warning("[NIGHT-WATCH/MEMORY] M3 timeout — aborting")
                    break

                try:
                    # Always do fast extraction (FREE)
                    use_llm = unit.importance >= 60.0 and bool(api_key)

                    if use_llm:
                        if not await tracker.can_spend("anthropic", 0.002):
                            use_llm = False  # Fall back to regex-only

                    extraction = await extract_entities_and_relationships(
                        unit.content, unit.source, use_llm=use_llm,
                    )

                    new_entities = extraction.get("entities", [])
                    new_relationships = extraction.get("relationships", [])

                    if new_entities:
                        unit.entities = new_entities
                        unit.relationships = new_relationships
                        entities_extracted += 1
                        modified_ids.add(unit.unit_id)

                        # Add to knowledge graph
                        if knowledge_graph:
                            await knowledge_graph.add_entities(new_entities, unit.unit_id)
                            if new_relationships:
                                await knowledge_graph.add_relationships(
                                    new_relationships, unit.unit_id
                                )

                        if use_llm:
                            est_cost = 0.001
                            m3_cost += est_cost

                except Exception as e:
                    log.debug("[NIGHT-WATCH/MEMORY] M3 extraction error for %s: %s", unit.unit_id[:8], e)
                    continue

            # Persist modified units
            if modified_ids:
                await memory_store._acquire_write()
                try:
                    all_units = await memory_store._load_all_units()
                    units_by_id = {u.unit_id: u for u in all_units}
                    # Update modified units in place
                    for unit in needs_entities:
                        if unit.unit_id in modified_ids:
                            units_by_id[unit.unit_id] = unit
                    await memory_store._rewrite_units(list(units_by_id.values()))
                finally:
                    memory_store._release_write()

                if m3_cost > 0:
                    await tracker.record(
                        "anthropic", m3_cost, "night_watch_memory",
                        f"entity backfill {entities_extracted} units",
                    )
                    report["total_cost_usd"] += m3_cost

            report["entities_extracted"] = entities_extracted
            log.info(
                "[NIGHT-WATCH/MEMORY] Task M3: extracted entities for %d units, cost $%.4f",
                entities_extracted, m3_cost,
            )

        except Exception as e:
            log.error("[NIGHT-WATCH/MEMORY] Task M3 failed: %s", e)
            report["errors"].append(f"M3: {e}")

        # ══════════════════════════════════════════════════════════════
        # Task M4: Stale Fact Detection (HAIKU + GEMINI, ~$0.02)
        # ══════════════════════════════════════════════════════════════
        try:
            task_t0 = time.monotonic()
            log.info("[NIGHT-WATCH/MEMORY] Task M4: Stale fact detection (dual-model)")

            google_api_key = os.environ.get("GOOGLE_API_KEY", "")

            if not api_key or not knowledge_graph:
                log.info("[NIGHT-WATCH/MEMORY] M4 skipped — no API key or knowledge graph")
            else:
                units = await memory_store._load_all_units()

                # Load semantic and decision type units
                fact_units = [
                    u for u in units
                    if getattr(u, 'memory_type', 'episodic') in ('semantic', 'decision')
                ]

                # Group by shared entities from the knowledge graph
                entity_to_units: dict[str, list] = {}
                for unit in fact_units:
                    for entity in unit.entities:
                        entity_to_units.setdefault(entity, []).append(unit)

                # Find clusters with 3+ units
                clusters: list[tuple[str, list]] = [
                    (entity, unit_list)
                    for entity, unit_list in entity_to_units.items()
                    if len(unit_list) >= 3
                ]
                clusters = clusters[:30]  # Limit to 30 clusters per night

                stale_facts_found = 0
                m4_cost = 0.0
                m4_haiku_finds = 0
                m4_gemini_finds = 0

                for entity, cluster_units in clusters:
                    if time.monotonic() - task_t0 > TASK_TIMEOUT:
                        log.warning("[NIGHT-WATCH/MEMORY] M4 timeout — aborting")
                        break

                    if not await tracker.can_spend("anthropic", 0.001):
                        log.warning("[NIGHT-WATCH/MEMORY] M4 budget exceeded — stopping")
                        break

                    # Build prompt with unit contents
                    unit_texts = []
                    for i, u in enumerate(cluster_units[:10]):  # Cap at 10 per cluster
                        unit_texts.append(
                            f"[{i+1}] (created {u.created_at.strftime('%Y-%m-%d')}, "
                            f"importance {u.importance:.0f}): {u.content[:300]}"
                        )

                    prompt = (
                        f"These memory units reference '{entity}'. "
                        "Identify any contradictions or outdated facts. "
                        "Respond with JSON: {{\"contradictions\": [{{\"units\": [i,j], "
                        "\"description\": \"...\"}}, ...], \"count\": N}}\n"
                        "If no contradictions, respond: {{\"contradictions\": [], \"count\": 0}}\n\n"
                        + "\n".join(unit_texts)
                    )

                    # --- Haiku call ---
                    async def _m4_haiku(p: str) -> list[dict]:
                        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                            resp = await client.post(
                                "https://api.anthropic.com/v1/messages",
                                headers={
                                    "x-api-key": api_key,
                                    "anthropic-version": "2023-06-01",
                                    "content-type": "application/json",
                                },
                                json={
                                    "model": "claude-sonnet-4",
                                    "max_tokens": 300,
                                    "messages": [{"role": "user", "content": p}],
                                },
                            )
                            if resp.status_code != 200:
                                return []
                            data = resp.json()
                            usage = data.get("usage", {})
                            input_t = usage.get("input_tokens", 0)
                            output_t = usage.get("output_tokens", 0)
                            cost = (input_t * 3.00 + output_t * 15.00) / 1_000_000
                            return [{"_cost": cost, "_source": "sonnet"}] + _m4_parse_contradictions(data["content"][0]["text"])

                    # --- Gemini call ---
                    async def _m4_gemini(p: str) -> list[dict]:
                        if not google_api_key:
                            return []
                        if not await tracker.can_spend("google", 0.001):
                            return []
                        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                            resp = await client.post(
                                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                                params={"key": google_api_key},
                                json={
                                    "contents": [{"parts": [{"text": p}]}],
                                    "generationConfig": {"maxOutputTokens": 300},
                                },
                            )
                            if resp.status_code != 200:
                                return []
                            data = resp.json()
                            candidates = data.get("candidates", [])
                            if not candidates:
                                return []
                            parts_list = candidates[0].get("content", {}).get("parts", [])
                            if not parts_list:
                                return []
                            text = parts_list[0].get("text", "")
                            usage_meta = data.get("usageMetadata", {})
                            input_t = usage_meta.get("promptTokenCount", 0)
                            output_t = usage_meta.get("candidatesTokenCount", 0)
                            cost = (input_t * 0.15 + output_t * 0.60) / 1_000_000
                            return [{"_cost": cost, "_source": "gemini"}] + _m4_parse_contradictions(text)

                    def _m4_parse_contradictions(text: str) -> list[dict]:
                        text = re.sub(r"```json\s*", "", text)
                        text = re.sub(r"```\s*", "", text)
                        try:
                            parsed = json.loads(text.strip())
                            return parsed.get("contradictions", [])
                        except (json.JSONDecodeError, ValueError):
                            return []

                    try:
                        # Run Haiku and Gemini in parallel
                        haiku_result, gemini_result = await asyncio.gather(
                            _m4_haiku(prompt), _m4_gemini(prompt),
                            return_exceptions=True,
                        )

                        # Process Haiku results
                        haiku_contradictions: list[dict] = []
                        haiku_cost = 0.0
                        if isinstance(haiku_result, list) and haiku_result:
                            meta = haiku_result[0]
                            if isinstance(meta, dict) and "_cost" in meta:
                                haiku_cost = meta["_cost"]
                                haiku_contradictions = haiku_result[1:]

                        # Process Gemini results
                        gemini_contradictions: list[dict] = []
                        gemini_cost = 0.0
                        if isinstance(gemini_result, list) and gemini_result:
                            meta = gemini_result[0]
                            if isinstance(meta, dict) and "_cost" in meta:
                                gemini_cost = meta["_cost"]
                                gemini_contradictions = gemini_result[1:]

                        # Combine: union of findings from either model
                        combined_descriptions: set[str] = set()
                        combined_count = 0
                        for c in haiku_contradictions:
                            desc = c.get("description", "")
                            if desc and desc not in combined_descriptions:
                                combined_descriptions.add(desc)
                                combined_count += 1
                        for c in gemini_contradictions:
                            desc = c.get("description", "")
                            if desc and desc not in combined_descriptions:
                                combined_descriptions.add(desc)
                                combined_count += 1

                        m4_haiku_finds += len(haiku_contradictions)
                        m4_gemini_finds += len(gemini_contradictions)
                        stale_facts_found += combined_count

                        # Track costs and record to tracker
                        if haiku_cost > 0:
                            await tracker.record(
                                "anthropic", haiku_cost, "night_watch_memory",
                                f"M4 stale fact detection (Haiku) entity='{entity}'",
                            )
                        if gemini_cost > 0:
                            await tracker.record(
                                "google", gemini_cost, "night_watch_memory",
                                f"M4 stale fact detection (Gemini) entity='{entity}'",
                            )
                        m4_cost += haiku_cost + gemini_cost

                        if combined_count > 0:
                            log.info(
                                "[NIGHT-WATCH/MEMORY] M4: entity '%s' — Haiku=%d, Gemini=%d, combined=%d contradictions",
                                entity, len(haiku_contradictions), len(gemini_contradictions), combined_count,
                            )

                    except Exception as e:
                        log.debug("[NIGHT-WATCH/MEMORY] M4 dual-model call error for '%s': %s", entity, e)
                        continue

                # Record costs per source (tracked inline per cluster, just add to report)
                if m4_cost > 0:
                    report["total_cost_usd"] += m4_cost

                report["stale_facts_found"] = stale_facts_found
                log.info(
                    "[NIGHT-WATCH/MEMORY] Task M4: Haiku found %d issues, Gemini found %d issues, "
                    "%d combined across %d clusters, cost $%.4f",
                    m4_haiku_finds, m4_gemini_finds, stale_facts_found, len(clusters), m4_cost,
                )

        except Exception as e:
            log.error("[NIGHT-WATCH/MEMORY] Task M4 failed: %s", e)
            report["errors"].append(f"M4: {e}")

        # ══════════════════════════════════════════════════════════════
        # Task M5: Knowledge Graph Maintenance (FREE)
        # ══════════════════════════════════════════════════════════════
        try:
            task_t0 = time.monotonic()
            log.info("[NIGHT-WATCH/MEMORY] Task M5: Knowledge graph maintenance")

            if not knowledge_graph:
                log.info("[NIGHT-WATCH/MEMORY] M5 skipped — no knowledge graph")
            else:
                # Prune stale nodes/edges (not seen in 90 days)
                prune_result = await knowledge_graph.prune_stale(90)
                log.info(
                    "[NIGHT-WATCH/MEMORY] M5 prune: %d nodes, %d edges removed",
                    prune_result.get("pruned_nodes", 0),
                    prune_result.get("pruned_edges", 0),
                )

                # Graph structure analysis using NetworkX
                if knowledge_graph._ensure_graph():
                    import networkx as nx
                    g = knowledge_graph._graph

                    total_nodes = g.number_of_nodes()
                    total_edges = g.number_of_edges()

                    # Weakly connected components
                    if total_nodes > 0:
                        components = list(nx.weakly_connected_components(g))
                        num_components = len(components)
                        largest_component = max(len(c) for c in components) if components else 0
                        isolated = sum(1 for n in g.nodes() if g.degree(n) == 0)
                    else:
                        num_components = 0
                        largest_component = 0
                        isolated = 0

                    report["kg_stats"] = {
                        "nodes": total_nodes,
                        "edges": total_edges,
                        "components": num_components,
                        "largest_component": largest_component,
                        "isolated_nodes": isolated,
                        "pruned_nodes": prune_result.get("pruned_nodes", 0),
                        "pruned_edges": prune_result.get("pruned_edges", 0),
                    }

                    # Find potential missing connections: entity pairs that
                    # share 3+ neighbors but have no direct edge
                    potential_links: list[str] = []
                    if total_nodes > 0 and total_nodes < 5000:
                        undirected = g.to_undirected()
                        nodes_list = list(g.nodes())
                        # Only check top entities by degree to limit compute
                        top_nodes = sorted(
                            nodes_list,
                            key=lambda n: g.degree(n),
                            reverse=True,
                        )[:100]

                        checked = set()
                        for n1 in top_nodes:
                            if time.monotonic() - task_t0 > TASK_TIMEOUT:
                                break
                            neighbors_1 = set(undirected.neighbors(n1))
                            for n2 in top_nodes:
                                if n1 >= n2 or (n1, n2) in checked:
                                    continue
                                checked.add((n1, n2))
                                if g.has_edge(n1, n2) or g.has_edge(n2, n1):
                                    continue
                                neighbors_2 = set(undirected.neighbors(n2))
                                shared = neighbors_1 & neighbors_2
                                if len(shared) >= 3:
                                    potential_links.append(
                                        f"{n1} <-> {n2} (share {len(shared)} neighbors)"
                                    )

                    if potential_links:
                        log.info(
                            "[NIGHT-WATCH/MEMORY] M5: %d potential missing connections found",
                            len(potential_links),
                        )
                        for pl in potential_links[:5]:
                            log.info("[NIGHT-WATCH/MEMORY] M5 potential link: %s", pl)

                    log.info(
                        "[NIGHT-WATCH/MEMORY] Task M5: nodes=%d, edges=%d, components=%d, "
                        "largest=%d, isolated=%d",
                        total_nodes, total_edges, num_components,
                        largest_component, isolated,
                    )

        except Exception as e:
            log.error("[NIGHT-WATCH/MEMORY] Task M5 failed: %s", e)
            report["errors"].append(f"M5: {e}")

        # ══════════════════════════════════════════════════════════════
        # Task M6: Entity Normalization (HAIKU, ~$0.001)
        # ══════════════════════════════════════════════════════════════
        try:
            task_t0 = time.monotonic()
            log.info("[NIGHT-WATCH/MEMORY] Task M6: Entity normalization")

            if not knowledge_graph or not knowledge_graph._ensure_graph():
                log.info("[NIGHT-WATCH/MEMORY] M6 skipped — no knowledge graph")
            else:
                # Get top entities
                top_entities = await knowledge_graph.get_top_entities(100)
                entity_names = [e["entity"] for e in top_entities]

                # Simple heuristic: find candidate pairs that may be the same entity
                candidate_pairs: list[tuple[str, str]] = []
                for i, name_a in enumerate(entity_names):
                    for name_b in entity_names[i + 1:]:
                        # Strip $ prefix for comparison
                        clean_a = name_a.lstrip("$").lower()
                        clean_b = name_b.lstrip("$").lower()

                        # Skip if identical after cleaning
                        if clean_a == clean_b and name_a != name_b:
                            candidate_pairs.append((name_a, name_b))
                            continue

                        # Check if one is a substring of the other (min length 3)
                        if len(clean_a) >= 3 and len(clean_b) >= 3:
                            if clean_a in clean_b or clean_b in clean_a:
                                candidate_pairs.append((name_a, name_b))
                                continue

                        # Common ticker-to-name mappings
                        ticker_map = {
                            "aapl": "apple", "goog": "google", "googl": "google",
                            "msft": "microsoft", "amzn": "amazon", "tsla": "tesla",
                            "meta": "facebook", "nvda": "nvidia", "nflx": "netflix",
                            "spy": "s&p 500", "qqq": "nasdaq",
                        }
                        if clean_a in ticker_map and ticker_map[clean_a] in clean_b:
                            candidate_pairs.append((name_a, name_b))
                        elif clean_b in ticker_map and ticker_map[clean_b] in clean_a:
                            candidate_pairs.append((name_a, name_b))

                normalizations = 0
                m6_cost = 0.0

                if candidate_pairs:
                    log.info(
                        "[NIGHT-WATCH/MEMORY] M6: %d candidate pairs found for normalization",
                        len(candidate_pairs),
                    )

                    # For unambiguous pairs (exact match after cleanup), add directly
                    unambiguous: list[tuple[str, str]] = []
                    ambiguous: list[tuple[str, str]] = []

                    for a, b in candidate_pairs:
                        clean_a = a.lstrip("$").lower().strip()
                        clean_b = b.lstrip("$").lower().strip()
                        if clean_a == clean_b:
                            unambiguous.append((a, b))
                        else:
                            ambiguous.append((a, b))

                    # Add SAME_AS edges for unambiguous pairs
                    for a, b in unambiguous:
                        await knowledge_graph.add_relationships(
                            [{"subject": a, "predicate": "SAME_AS", "object": b}]
                        )
                        normalizations += 1

                    # For ambiguous pairs, use Haiku AND Gemini — only confirm if BOTH agree
                    if ambiguous and api_key:
                        google_api_key_m6 = os.environ.get("GOOGLE_API_KEY", "")
                        if await tracker.can_spend("anthropic", 0.001):
                            pairs_text = "\n".join(
                                f"  {i+1}. \"{a}\" vs \"{b}\""
                                for i, (a, b) in enumerate(ambiguous[:30])
                            )
                            prompt = (
                                "These entity pairs may refer to the same real-world entity. "
                                "For each pair, respond YES if they are the same, NO if different.\n"
                                "Respond with JSON: {{\"results\": [true/false, ...]}}\n\n"
                                + pairs_text
                            )

                            def _m6_parse_results(text: str) -> list[bool]:
                                text = re.sub(r"```json\s*", "", text)
                                text = re.sub(r"```\s*", "", text)
                                try:
                                    parsed = json.loads(text.strip())
                                    return parsed.get("results", [])
                                except (json.JSONDecodeError, ValueError):
                                    return []

                            async def _m6_haiku(p: str) -> tuple[list[bool], float]:
                                async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                                    resp = await client.post(
                                        "https://api.anthropic.com/v1/messages",
                                        headers={
                                            "x-api-key": api_key,
                                            "anthropic-version": "2023-06-01",
                                            "content-type": "application/json",
                                        },
                                        json={
                                            "model": "claude-sonnet-4",
                                            "max_tokens": 200,
                                            "messages": [{"role": "user", "content": p}],
                                        },
                                    )
                                    if resp.status_code != 200:
                                        return [], 0.0
                                    data = resp.json()
                                    usage = data.get("usage", {})
                                    input_t = usage.get("input_tokens", 0)
                                    output_t = usage.get("output_tokens", 0)
                                    cost = (input_t * 3.00 + output_t * 15.00) / 1_000_000
                                    return _m6_parse_results(data["content"][0]["text"]), cost

                            async def _m6_gemini(p: str) -> tuple[list[bool], float]:
                                if not google_api_key_m6:
                                    return [], 0.0
                                if not await tracker.can_spend("google", 0.001):
                                    return [], 0.0
                                async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                                    resp = await client.post(
                                        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                                        params={"key": google_api_key_m6},
                                        json={
                                            "contents": [{"parts": [{"text": p}]}],
                                            "generationConfig": {"maxOutputTokens": 200},
                                        },
                                    )
                                    if resp.status_code != 200:
                                        return [], 0.0
                                    data = resp.json()
                                    candidates = data.get("candidates", [])
                                    if not candidates:
                                        return [], 0.0
                                    parts_list = candidates[0].get("content", {}).get("parts", [])
                                    if not parts_list:
                                        return [], 0.0
                                    text = parts_list[0].get("text", "")
                                    usage_meta = data.get("usageMetadata", {})
                                    input_t = usage_meta.get("promptTokenCount", 0)
                                    output_t = usage_meta.get("candidatesTokenCount", 0)
                                    cost = (input_t * 0.15 + output_t * 0.60) / 1_000_000
                                    return _m6_parse_results(text), cost

                            try:
                                haiku_res, gemini_res = await asyncio.gather(
                                    _m6_haiku(prompt), _m6_gemini(prompt),
                                    return_exceptions=True,
                                )

                                haiku_results: list[bool] = []
                                haiku_cost_m6 = 0.0
                                if isinstance(haiku_res, tuple):
                                    haiku_results, haiku_cost_m6 = haiku_res

                                gemini_results: list[bool] = []
                                gemini_cost_m6 = 0.0
                                if isinstance(gemini_res, tuple):
                                    gemini_results, gemini_cost_m6 = gemini_res

                                m6_cost += haiku_cost_m6 + gemini_cost_m6

                                # Consensus: only confirm if BOTH models agree
                                agreed = 0
                                disagreed = 0
                                for idx in range(min(len(ambiguous), len(haiku_results))):
                                    haiku_says = haiku_results[idx] if idx < len(haiku_results) else None
                                    gemini_says = gemini_results[idx] if idx < len(gemini_results) else None

                                    if haiku_says is True and gemini_says is True:
                                        # Both agree it's the same entity
                                        a, b = ambiguous[idx]
                                        await knowledge_graph.add_relationships(
                                            [{"subject": a, "predicate": "SAME_AS", "object": b}]
                                        )
                                        normalizations += 1
                                        agreed += 1
                                    elif haiku_says is True and gemini_says is not True:
                                        # Haiku-only (no Gemini or disagreement) — fall back to Haiku
                                        if gemini_says is None:
                                            a, b = ambiguous[idx]
                                            await knowledge_graph.add_relationships(
                                                [{"subject": a, "predicate": "SAME_AS", "object": b}]
                                            )
                                            normalizations += 1
                                        else:
                                            disagreed += 1
                                    elif haiku_says is not None and gemini_says is not None:
                                        if haiku_says != gemini_says:
                                            disagreed += 1

                                log.info(
                                    "[NIGHT-WATCH/MEMORY] M6: %d pairs agreed, %d disagreed",
                                    agreed, disagreed,
                                )

                            except Exception as e:
                                log.debug("[NIGHT-WATCH/MEMORY] M6 dual-model call error: %s", e)

                        if m6_cost > 0:
                            if haiku_cost_m6 > 0:
                                await tracker.record(
                                    "anthropic", haiku_cost_m6, "night_watch_memory",
                                    f"entity normalization (Haiku) {normalizations} pairs",
                                )
                            if gemini_cost_m6 > 0:
                                await tracker.record(
                                    "google", gemini_cost_m6, "night_watch_memory",
                                    f"entity normalization (Gemini) {normalizations} pairs",
                                )
                            report["total_cost_usd"] += m6_cost

                report["normalizations"] = normalizations
                log.info(
                    "[NIGHT-WATCH/MEMORY] Task M6: %d normalizations, cost $%.4f",
                    normalizations, m6_cost,
                )

        except Exception as e:
            log.error("[NIGHT-WATCH/MEMORY] Task M6 failed: %s", e)
            report["errors"].append(f"M6: {e}")

        # ══════════════════════════════════════════════════════════════
        # Final report
        # ══════════════════════════════════════════════════════════════
        report["duration_seconds"] = round(time.monotonic() - t0, 2)

        log.info(
            "[NIGHT-WATCH/MEMORY] Memory cycle complete — "
            "duplicates=%d, rescored=%d, entities=%d, stale=%d, "
            "normalizations=%d, cost=$%.4f, duration=%.1fs, errors=%d",
            report["duplicates_found"],
            report["units_rescored"],
            report["entities_extracted"],
            report["stale_facts_found"],
            report["normalizations"],
            report["total_cost_usd"],
            report["duration_seconds"],
            len(report["errors"]),
        )

        return report

    # ─── NIGHT WATCH INTEL CYCLE: Phase 3 intelligence correlation ──

    async def _night_watch_intel_cycle(self) -> dict:
        """
        Night Watch Phase 3 — Intelligence Correlation Cycle.

        Runs 6 analysis tasks on intelligence data:
          I1: Cross-source correlation mining (FREE)
          I2: Coverage blind spot detection (FREE + Sonnet + Gemini dual-model)
          I3: Signal score calibration (FREE)
          I4: Prediction calibration analysis (FREE + Sonnet + Gemini dual-model)
          I5: Council topic suggestion (Sonnet + Gemini dual-model, merged with priority)
          I6: Cost optimization analysis (Sonnet + Gemini consensus)

        Total cost target: ~$0.30/night (4 Sonnet + 4 Gemini calls).

        Returns:
            Dict with task results and overall stats.
        """
        import re
        import time

        import httpx

        from ..cost_tracker import get_tracker

        t0 = time.monotonic()
        report: dict = {
            "missed_correlations": 0,
            "blind_spots": [],
            "over_scored_signals": 0,
            "under_scored_signals": 0,
            "predictions_stale": 0,
            "per_model_accuracy": {},
            "council_suggestions": [],
            "cost_optimization": "",
            "total_cost_usd": 0.0,
            "duration_seconds": 0.0,
            "errors": [],
        }

        TASK_TIMEOUT = 10 * 60  # 10 minutes per task

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            report["errors"].append("No ANTHROPIC_API_KEY — skipping LLM intel tasks")
            log.warning("[NIGHT-WATCH/INTEL] No ANTHROPIC_API_KEY — LLM tasks will be skipped")

        tracker = await get_tracker()
        sonnet_model_intel = "claude-sonnet-4"
        api_headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        async def _call_sonnet_intel(prompt: str, label: str, max_tokens: int = 1024) -> tuple[str, float]:
            """Make a Sonnet call for intel analysis, return (text, cost_usd). Raises on failure."""
            if not api_key:
                raise RuntimeError("No API key")
            if not await tracker.can_spend("anthropic", 0.02):
                raise RuntimeError("Anthropic budget exceeded")
            async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=api_headers,
                    json={
                        "model": sonnet_model_intel,
                        "max_tokens": max_tokens,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                text = data["content"][0]["text"]
                usage = data.get("usage", {})
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                cost = (input_tokens * 3.00 + output_tokens * 15.00) / 1_000_000
                log.info(
                    "[NIGHT-WATCH/INTEL] Sonnet call '%s': %d in / %d out tokens, $%.4f",
                    label, input_tokens, output_tokens, cost,
                )
                await tracker.record(
                    "anthropic", cost, "night_watch_intel",
                    f"Night Watch Intel Sonnet: {label}",
                    {"model": sonnet_model_intel, "phase": "intel", "label": label},
                )
                return text, cost

        google_api_key_intel = os.environ.get("GOOGLE_API_KEY", "")

        async def _call_gemini(prompt: str, label: str, max_tokens: int = 1024) -> tuple[str, float]:
            """Make a Gemini 2.5 Flash call, return (text, cost_usd). Raises on failure."""
            if not google_api_key_intel:
                raise RuntimeError("No GOOGLE_API_KEY")
            if not await tracker.can_spend("google", 0.005):
                raise RuntimeError("Google budget exceeded")
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                resp = await client.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                    params={"key": google_api_key_intel},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"maxOutputTokens": max_tokens},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    raise ValueError(f"Gemini returned no candidates: {list(data.keys())}")
                parts_list = candidates[0].get("content", {}).get("parts", [])
                if not parts_list:
                    raise ValueError("Gemini candidate has no content parts")
                text = parts_list[0].get("text", "")
                usage_meta = data.get("usageMetadata", {})
                input_tokens = usage_meta.get("promptTokenCount", 0)
                output_tokens = usage_meta.get("candidatesTokenCount", 0)
                # Gemini 2.5 Flash: $0.15/1M input, $0.60/1M output
                cost = (input_tokens * 0.15 + output_tokens * 0.60) / 1_000_000
                log.info(
                    "[NIGHT-WATCH/INTEL] Gemini call '%s': %d in / %d out tokens, $%.6f",
                    label, input_tokens, output_tokens, cost,
                )
                await tracker.record(
                    "google", cost, "night_watch_intel",
                    f"Night Watch Intel Gemini: {label}",
                    {"model": "gemini-2.5-flash", "phase": "intel", "label": label},
                )
                return text, cost

        # Ensure output directory exists
        nw_dir = self.data_dir / "night-watch"
        nw_dir.mkdir(parents=True, exist_ok=True)

        # ══════════════════════════════════════════════════════════════
        # TASK I1: Cross-Source Correlation Mining (FREE)
        # ══════════════════════════════════════════════════════════════
        try:
            log.info("[NIGHT-WATCH/INTEL] Task I1: Cross-source correlation mining...")

            signals_file = self.data_dir / "intelligence" / "agent_signals.jsonl"
            cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            signals_by_source: dict[str, list[dict]] = defaultdict(list)

            if signals_file.exists():
                with open(signals_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            sig = json.loads(line)
                            ts = sig.get("timestamp", "")
                            if ts >= cutoff:
                                source = sig.get("source", "unknown")
                                signals_by_source[source].append(sig)
                        except json.JSONDecodeError:
                            continue

            # Tokenize each signal's content into keyword sets
            def _tokenize_signal(sig: dict) -> set[str]:
                text = f"{sig.get('title', '')} {sig.get('content', '')} {' '.join(sig.get('tags', []))}"
                tokens = set(t.lower() for t in re.findall(r'\b[a-zA-Z0-9]{4,}\b', text))
                # Filter out very common words
                stopwords = {"this", "that", "with", "from", "have", "been", "will", "they",
                             "their", "about", "would", "could", "should", "just", "more",
                             "some", "than", "into", "when", "what", "also", "other", "were"}
                return tokens - stopwords

            # Build per-source keyword sets grouped by broad topic clusters
            source_keywords: dict[str, dict[str, set]] = {}  # source -> {keyword -> signal_ids}
            for source, sigs in signals_by_source.items():
                kw_map: dict[str, set] = defaultdict(set)
                for sig in sigs:
                    tokens = _tokenize_signal(sig)
                    sid = sig.get("signal_id", "")
                    for token in tokens:
                        kw_map[token].add(sid)
                source_keywords[source] = dict(kw_map)

            # Find keywords appearing in 2+ different sources
            all_sources = list(source_keywords.keys())
            cross_source_keywords: dict[str, set[str]] = defaultdict(set)  # keyword -> sources
            for source, kw_map in source_keywords.items():
                for kw in kw_map:
                    cross_source_keywords[kw].add(source)

            # Filter to multi-source keywords with >= 2 sources
            multi_source_kw = {
                kw: sources for kw, sources in cross_source_keywords.items()
                if len(sources) >= 2
            }

            # Cluster related keywords by co-occurrence in the same signals
            # Simple approach: group keywords that share significant overlap in source coverage
            missed_clusters: list[dict] = []
            used_keywords: set[str] = set()

            for kw, sources in sorted(multi_source_kw.items(), key=lambda x: -len(x[1])):
                if kw in used_keywords:
                    continue
                # Find related keywords (appear in same sources)
                cluster = {kw}
                for other_kw, other_sources in multi_source_kw.items():
                    if other_kw not in used_keywords and other_sources == sources:
                        cluster.add(other_kw)
                    if len(cluster) >= 8:
                        break

                used_keywords.update(cluster)
                if len(cluster) >= 2:  # Only report clusters with multiple related keywords
                    missed_clusters.append({
                        "keywords": sorted(cluster)[:8],
                        "sources": sorted(sources),
                        "source_count": len(sources),
                    })

                if len(missed_clusters) >= 20:
                    break

            report["missed_correlations"] = len(missed_clusters)
            log.info("[NIGHT-WATCH/INTEL] Task I1: found %d missed correlation clusters across %d sources",
                     len(missed_clusters), len(all_sources))

        except asyncio.TimeoutError:
            report["errors"].append("I1: timeout")
            log.error("[NIGHT-WATCH/INTEL] Task I1 timed out")
        except Exception as e:
            report["errors"].append(f"I1: {e}")
            log.error("[NIGHT-WATCH/INTEL] Task I1 failed: %s", e, exc_info=True)

        # ══════════════════════════════════════════════════════════════
        # TASK I2: Coverage Blind Spot Detection (FREE + 1 Haiku)
        # ══════════════════════════════════════════════════════════════
        blind_spot_analysis = ""
        try:
            log.info("[NIGHT-WATCH/INTEL] Task I2: Coverage blind spot detection...")

            # Load watch queries
            watch_topics: list[str] = []
            wq_candidates = [
                self.data_dir.parent / "config" / "watch_queries.json",
                self.data_dir.parent / "runtime" / "autonomous" / "watch_queries.json",
                self.data_dir / "watch_queries.json",
            ]
            for wq_path in wq_candidates:
                if wq_path.exists():
                    try:
                        wq_data = json.loads(wq_path.read_text())
                        for key, val in wq_data.items():
                            if key.startswith("_"):
                                continue
                            if isinstance(val, list):
                                watch_topics.extend(val)
                        break
                    except Exception:
                        continue

            # If no watch config, try knowledge graph top entities
            if not watch_topics:
                memory_store = getattr(self.brain, 'memory_store', None)
                kg = getattr(memory_store, '_knowledge_graph', None) if memory_store else None
                if kg and hasattr(kg, 'get_top_entities'):
                    try:
                        top_ents = kg.get_top_entities(limit=20)
                        watch_topics = [e.get("name", "") for e in top_ents if e.get("name")]
                    except Exception:
                        pass

            # Deduplicate
            watch_topics = list(dict.fromkeys(watch_topics))

            # Check signals from last 48h for coverage
            cutoff_48h = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
            recent_signal_text = ""
            recent_count = 0
            if signals_file.exists():
                with open(signals_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            sig = json.loads(line)
                            if sig.get("timestamp", "") >= cutoff_48h:
                                recent_signal_text += f" {sig.get('title', '')} {sig.get('content', '')}"
                                recent_count += 1
                        except json.JSONDecodeError:
                            continue

            recent_lower = recent_signal_text.lower()
            blind_spots: list[str] = []
            covered_topics: list[str] = []
            for topic in watch_topics:
                # Check if any significant words from the topic appear in signals
                topic_words = [w.lower() for w in topic.split() if len(w) >= 4]
                if not topic_words:
                    continue
                matches = sum(1 for w in topic_words if w in recent_lower)
                coverage_ratio = matches / len(topic_words) if topic_words else 0
                if coverage_ratio < 0.3:
                    blind_spots.append(topic)
                else:
                    covered_topics.append(topic)

            report["blind_spots"] = blind_spots[:20]

            # Dual-model call for synthesis (Haiku + Gemini in parallel)
            if blind_spots and api_key:
                try:
                    prompt = (
                        "You are an intelligence analyst for an autonomous AI brain system. "
                        "The system watches specific topics and generates signals from X/Twitter, "
                        "YouTube, Reddit, Google Trends, news, and market data.\n\n"
                        f"WATCHED TOPICS ({len(watch_topics)} total):\n"
                        + "\n".join(f"- {t}" for t in watch_topics[:30]) + "\n\n"
                        f"TOPICS WITH NO COVERAGE in last 48h ({len(blind_spots)}):\n"
                        + "\n".join(f"- {t}" for t in blind_spots[:15]) + "\n\n"
                        f"TOPICS WITH COVERAGE ({len(covered_topics)}):\n"
                        + "\n".join(f"- {t}" for t in covered_topics[:10]) + "\n\n"
                        f"Total signals in last 48h: {recent_count}\n\n"
                        "Given these watched topics and coverage gaps, what intelligence might "
                        "we be missing? What risks emerge from the blind spots? "
                        "Return each blind spot as a bullet point starting with '- '."
                    )

                    # Run both models in parallel
                    haiku_task = asyncio.wait_for(
                        _call_sonnet_intel(prompt, "I2_blind_spots"), timeout=TASK_TIMEOUT
                    )
                    gemini_task = asyncio.wait_for(
                        _call_gemini(prompt, "I2_blind_spots"), timeout=TASK_TIMEOUT
                    )
                    haiku_res, gemini_res = await asyncio.gather(
                        haiku_task, gemini_task, return_exceptions=True,
                    )

                    haiku_text = ""
                    gemini_text = ""

                    if isinstance(haiku_res, tuple):
                        haiku_text, haiku_cost = haiku_res
                        report["total_cost_usd"] += haiku_cost
                    elif isinstance(haiku_res, Exception):
                        log.warning("[NIGHT-WATCH/INTEL] I2 Haiku failed: %s", haiku_res)

                    if isinstance(gemini_res, tuple):
                        gemini_text, gemini_cost = gemini_res
                        report["total_cost_usd"] += gemini_cost
                    elif isinstance(gemini_res, Exception):
                        log.warning("[NIGHT-WATCH/INTEL] I2 Gemini failed: %s", gemini_res)

                    # Merge blind spot bullet points (union, deduplicated)
                    def _extract_bullets(text: str) -> list[str]:
                        return [
                            line.strip().lstrip("- •*").strip()
                            for line in text.split("\n")
                            if line.strip().startswith(("-", "•", "*"))
                            and len(line.strip()) > 10
                        ]

                    haiku_bullets = _extract_bullets(haiku_text)
                    gemini_bullets = _extract_bullets(gemini_text)

                    # Identify high-confidence bullets (flagged by both)
                    haiku_kw = {b.lower()[:60] for b in haiku_bullets}
                    gemini_kw = {b.lower()[:60] for b in gemini_bullets}

                    merged_bullets: list[str] = []
                    high_confidence: list[str] = []

                    for b in haiku_bullets:
                        merged_bullets.append(b)
                        # Check if Gemini flagged something similar
                        b_words = set(b.lower().split())
                        for gb in gemini_bullets:
                            gb_words = set(gb.lower().split())
                            overlap = len(b_words & gb_words) / max(len(b_words | gb_words), 1)
                            if overlap > 0.4:
                                high_confidence.append(b)
                                break

                    for b in gemini_bullets:
                        # Only add if not already covered
                        b_words = set(b.lower().split())
                        already = False
                        for mb in merged_bullets:
                            mb_words = set(mb.lower().split())
                            overlap = len(b_words & mb_words) / max(len(b_words | mb_words), 1)
                            if overlap > 0.4:
                                already = True
                                break
                        if not already:
                            merged_bullets.append(b)

                    # Build combined analysis
                    combined_parts: list[str] = []
                    if high_confidence:
                        combined_parts.append(
                            "HIGH CONFIDENCE blind spots (flagged by both Haiku and Gemini):\n"
                            + "\n".join(f"- {b}" for b in high_confidence)
                        )
                    combined_parts.append(
                        "ALL identified blind spots (merged):\n"
                        + "\n".join(f"- {b}" for b in merged_bullets)
                    )
                    blind_spot_analysis = "\n\n".join(combined_parts)

                    log.info(
                        "[NIGHT-WATCH/INTEL] I2: Haiku found %d, Gemini found %d, "
                        "%d merged (%d high confidence)",
                        len(haiku_bullets), len(gemini_bullets),
                        len(merged_bullets), len(high_confidence),
                    )

                except Exception as e:
                    report["errors"].append(f"I2 dual-model: {e}")
                    log.error("[NIGHT-WATCH/INTEL] Task I2 dual-model failed: %s", e)

            log.info("[NIGHT-WATCH/INTEL] Task I2: %d blind spots out of %d watched topics",
                     len(blind_spots), len(watch_topics))

        except asyncio.TimeoutError:
            report["errors"].append("I2: timeout")
            log.error("[NIGHT-WATCH/INTEL] Task I2 timed out")
        except Exception as e:
            report["errors"].append(f"I2: {e}")
            log.error("[NIGHT-WATCH/INTEL] Task I2 failed: %s", e, exc_info=True)

        # ══════════════════════════════════════════════════════════════
        # TASK I3: Signal Score Calibration (FREE)
        # ══════════════════════════════════════════════════════════════
        try:
            log.info("[NIGHT-WATCH/INTEL] Task I3: Signal score calibration...")

            signals_file = self.data_dir / "intelligence" / "agent_signals.jsonl"
            cutoff_14d = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()

            high_signals: list[dict] = []  # scored HIGH/CRITICAL (composite > 0.7)
            low_signals: list[dict] = []   # scored LOW (composite < 0.3)

            if signals_file.exists():
                with open(signals_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            sig = json.loads(line)
                            if sig.get("timestamp", "") < cutoff_14d:
                                continue
                            score = sig.get("composite_score", 0)
                            level = sig.get("route_level", "")
                            if score >= 0.7 or level in ("HIGH", "CRITICAL"):
                                high_signals.append(sig)
                            elif score < 0.3 or level == "LOW":
                                low_signals.append(sig)
                        except json.JSONDecodeError:
                            continue

            # Check which high signals were actually referenced in memory/journal
            memory_store = getattr(self.brain, 'memory_store', None)
            memory_contents: set[str] = set()
            if memory_store:
                try:
                    # Get recent memory units to check for signal references
                    all_units = getattr(memory_store, '_units', [])
                    if hasattr(memory_store, 'get_all_units'):
                        try:
                            all_units = await memory_store.get_all_units()
                        except Exception:
                            pass
                    for unit in all_units:
                        content = ""
                        if isinstance(unit, dict):
                            content = unit.get("content", "")
                        elif hasattr(unit, "content"):
                            content = unit.content
                        if content:
                            memory_contents.add(content[:200].lower())
                except Exception:
                    pass

            # Check journal for references
            journal_store = getattr(self.brain, 'journal_store', None)
            journal_contents: set[str] = set()
            if journal_store:
                try:
                    recent_entries = await journal_store.get_entries(
                        date_from=(datetime.now(timezone.utc) - timedelta(days=14)).date(),
                        limit=100,
                    )
                    for entry in recent_entries:
                        journal_contents.add(entry.content[:200].lower())
                except Exception:
                    pass

            all_ref_text = " ".join(memory_contents) + " " + " ".join(journal_contents)
            all_ref_lower = all_ref_text.lower()

            # Over-scored: HIGH signals never referenced again
            over_scored = 0
            over_scored_examples: list[str] = []
            for sig in high_signals:
                title = sig.get("title", "")[:60]
                # Check if key words from the signal title appear in memory/journal
                key_words = [w.lower() for w in title.split() if len(w) >= 5]
                if key_words:
                    found = sum(1 for w in key_words if w in all_ref_lower)
                    if found == 0:
                        over_scored += 1
                        if len(over_scored_examples) < 5:
                            over_scored_examples.append(
                                f"{sig.get('source', '?')}: {title} (score={sig.get('composite_score', 0):.2f})"
                            )

            # Under-scored: LOW signals that ended up being reinforced/referenced
            under_scored = 0
            under_scored_examples: list[str] = []
            for sig in low_signals[:500]:  # Cap for performance
                title = sig.get("title", "")[:60]
                key_words = [w.lower() for w in title.split() if len(w) >= 5]
                if key_words:
                    found = sum(1 for w in key_words if w in all_ref_lower)
                    if found >= 2:  # Multiple key words referenced
                        under_scored += 1
                        if len(under_scored_examples) < 5:
                            under_scored_examples.append(
                                f"{sig.get('source', '?')}: {title} (score={sig.get('composite_score', 0):.2f})"
                            )

            report["over_scored_signals"] = over_scored
            report["under_scored_signals"] = under_scored

            over_rate = (over_scored / max(len(high_signals), 1)) * 100
            under_rate = (under_scored / max(min(len(low_signals), 500), 1)) * 100

            log.info(
                "[NIGHT-WATCH/INTEL] Task I3: %d HIGH signals checked, %d over-scored (%.1f%%), "
                "%d LOW signals checked, %d under-scored (%.1f%%)",
                len(high_signals), over_scored, over_rate,
                min(len(low_signals), 500), under_scored, under_rate,
            )

        except asyncio.TimeoutError:
            report["errors"].append("I3: timeout")
            log.error("[NIGHT-WATCH/INTEL] Task I3 timed out")
        except Exception as e:
            report["errors"].append(f"I3: {e}")
            log.error("[NIGHT-WATCH/INTEL] Task I3 failed: %s", e, exc_info=True)

        # ══════════════════════════════════════════════════════════════
        # TASK I4: Prediction Calibration Analysis (FREE + 1 Haiku)
        # ══════════════════════════════════════════════════════════════
        try:
            log.info("[NIGHT-WATCH/INTEL] Task I4: Prediction calibration analysis...")

            pred_dir = self.data_dir / "predictions"
            cutoff_30d = (datetime.now(timezone.utc) - timedelta(days=30))
            cutoff_14d_dt = datetime.now(timezone.utc) - timedelta(days=14)

            all_predictions: list[dict] = []
            if pred_dir.exists():
                for pf in sorted(pred_dir.glob("pred-*.json")):
                    try:
                        # Check file age
                        mtime = datetime.fromtimestamp(pf.stat().st_mtime, tz=timezone.utc)
                        if mtime < cutoff_30d:
                            continue
                        pdata = json.loads(pf.read_text())
                        pdata["_file"] = pf.name
                        pdata["_mtime"] = mtime.isoformat()
                        all_predictions.append(pdata)
                    except Exception:
                        continue

            # Read accuracy outcomes
            accuracy_outcomes: dict[str, dict] = {}  # prediction_id -> outcome
            acc_file = pred_dir / "accuracy.jsonl" if pred_dir.exists() else None
            if acc_file and acc_file.exists():
                try:
                    with open(acc_file, "r") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                outcome = json.loads(line)
                                pid = outcome.get("prediction_id", "")
                                if pid:
                                    accuracy_outcomes[pid] = outcome
                            except json.JSONDecodeError:
                                continue
                except Exception:
                    pass

            # Extract model info from consensus text and compute per-model stats
            model_predictions: dict[str, list[dict]] = defaultdict(list)  # model -> predictions
            stale_predictions: list[dict] = []

            for pred in all_predictions:
                consensus = pred.get("consensus", "")
                topic = pred.get("topic", "unknown")
                ts_str = pred.get("timestamp", pred.get("_mtime", ""))
                pred_id = pred.get("prediction_id", "")

                # Extract model names from consensus text
                models_found: list[str] = []
                # Pattern: "lead=MODEL@" or "[MODEL concurs@"
                for m in re.findall(r'lead=(\w+)@|(\w+)\s+concurs@|\[Single-model\]', consensus):
                    model_name = m[0] or m[1]
                    if model_name:
                        models_found.append(model_name.lower())
                if "[Single-model]" in consensus:
                    # Try to detect model from context
                    if "claude" in consensus.lower():
                        models_found.append("claude")
                    elif "qwen" in consensus.lower():
                        models_found.append("qwen")
                    elif "deepseek" in consensus.lower():
                        models_found.append("deepseek")

                if not models_found:
                    models_found = ["unknown"]

                # Check for outcome
                has_outcome = pred_id in accuracy_outcomes or pred.get("outcome")
                outcome_correct = None
                if pred_id in accuracy_outcomes:
                    outcome_correct = accuracy_outcomes[pred_id].get("correct")
                elif pred.get("outcome") in ("correct", "partial"):
                    outcome_correct = True
                elif pred.get("outcome") == "incorrect":
                    outcome_correct = False

                for model in models_found:
                    model_predictions[model].append({
                        "topic": topic,
                        "confidence": pred.get("confidence", 0),
                        "has_outcome": has_outcome,
                        "correct": outcome_correct,
                    })

                # Stale predictions: no outcome and older than 14 days
                if not has_outcome:
                    try:
                        pred_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else None
                        if pred_dt and pred_dt < cutoff_14d_dt:
                            stale_predictions.append({
                                "topic": topic,
                                "timestamp": ts_str,
                                "file": pred.get("_file", ""),
                            })
                    except Exception:
                        pass

            report["predictions_stale"] = len(stale_predictions)

            # Compute per-model accuracy
            per_model_accuracy: dict[str, str] = {}
            model_summary_lines: list[str] = []
            for model, preds in sorted(model_predictions.items()):
                total = len(preds)
                with_outcome = sum(1 for p in preds if p["has_outcome"])
                correct = sum(1 for p in preds if p["correct"] is True)
                if with_outcome > 0:
                    acc_pct = f"{correct}/{with_outcome} ({correct/with_outcome*100:.0f}%)"
                else:
                    acc_pct = f"0/{total} (no outcomes)"
                per_model_accuracy[model] = acc_pct
                model_summary_lines.append(
                    f"{model}: {total} predictions, accuracy={acc_pct}"
                )

            report["per_model_accuracy"] = per_model_accuracy

            # Dual-model call for model reliability assessment (Haiku + Gemini)
            if api_key and model_summary_lines:
                try:
                    stale_summary = ""
                    if stale_predictions:
                        stale_summary = (
                            f"\n\nUNRESOLVED PREDICTIONS (older than 14 days, no outcome recorded):\n"
                            + "\n".join(f"- {p['topic']} ({p.get('file', '')})" for p in stale_predictions[:10])
                        )

                    prompt = (
                        "You are a prediction system analyst. Review per-model accuracy data "
                        "for an AI ensemble forecasting system.\n\n"
                        "PER-MODEL STATS:\n"
                        + "\n".join(f"- {line}" for line in model_summary_lines) + "\n"
                        + stale_summary + "\n\n"
                        "Given these per-model accuracy rates and unresolved predictions, "
                        "which models are reliable on which topics? What calibration issues "
                        "exist? 3-5 bullet points."
                    )

                    # Run both models in parallel
                    haiku_task = asyncio.wait_for(
                        _call_sonnet_intel(prompt, "I4_prediction_calibration"), timeout=TASK_TIMEOUT
                    )
                    gemini_task = asyncio.wait_for(
                        _call_gemini(prompt, "I4_prediction_calibration"), timeout=TASK_TIMEOUT
                    )
                    haiku_res, gemini_res = await asyncio.gather(
                        haiku_task, gemini_task, return_exceptions=True,
                    )

                    haiku_text = ""
                    gemini_text = ""

                    if isinstance(haiku_res, tuple):
                        haiku_text, haiku_cost = haiku_res
                        report["total_cost_usd"] += haiku_cost
                    elif isinstance(haiku_res, Exception):
                        log.warning("[NIGHT-WATCH/INTEL] I4 Haiku failed: %s", haiku_res)

                    if isinstance(gemini_res, tuple):
                        gemini_text, gemini_cost = gemini_res
                        report["total_cost_usd"] += gemini_cost
                    elif isinstance(gemini_res, Exception):
                        log.warning("[NIGHT-WATCH/INTEL] I4 Gemini failed: %s", gemini_res)

                    # Combine assessments — note disagreements
                    combined_parts: list[str] = []
                    if haiku_text and gemini_text:
                        combined_parts.append(f"=== Haiku Assessment ===\n{haiku_text}")
                        combined_parts.append(f"=== Gemini Assessment ===\n{gemini_text}")
                        log.info(
                            "[NIGHT-WATCH/INTEL] I4: Got assessments from both Haiku and Gemini"
                        )
                    elif haiku_text:
                        combined_parts.append(haiku_text)
                    elif gemini_text:
                        combined_parts.append(gemini_text)

                    # Store combined calibration in report for Phase 5 synthesis
                    report["prediction_calibration_analysis"] = "\n\n".join(combined_parts)

                except Exception as e:
                    report["errors"].append(f"I4 dual-model: {e}")
                    log.error("[NIGHT-WATCH/INTEL] Task I4 dual-model failed: %s", e)

            log.info(
                "[NIGHT-WATCH/INTEL] Task I4: %d predictions, %d models, %d stale",
                len(all_predictions), len(model_predictions), len(stale_predictions),
            )

        except asyncio.TimeoutError:
            report["errors"].append("I4: timeout")
            log.error("[NIGHT-WATCH/INTEL] Task I4 timed out")
        except Exception as e:
            report["errors"].append(f"I4: {e}")
            log.error("[NIGHT-WATCH/INTEL] Task I4 failed: %s", e, exc_info=True)

        # ══════════════════════════════════════════════════════════════
        # TASK I5: Council Topic Suggestion (1 Haiku)
        # ══════════════════════════════════════════════════════════════
        try:
            log.info("[NIGHT-WATCH/INTEL] Task I5: Council topic suggestion...")

            suggestion_inputs: list[str] = []

            # Prediction failures
            for model, preds in model_predictions.items():
                for p in preds:
                    if p["correct"] is False:
                        suggestion_inputs.append(f"PREDICTION FAILURE ({model}): {p['topic']}")

            # Coverage blind spots from I2
            for bs in report.get("blind_spots", [])[:5]:
                suggestion_inputs.append(f"COVERAGE GAP: {bs}")

            # Journal research_queue items
            journal_store = getattr(self.brain, 'journal_store', None)
            if journal_store:
                try:
                    recent_reflections = await journal_store.get_recent_reflections(days=7)
                    for ref in recent_reflections:
                        for rq in getattr(ref, 'research_queue', []):
                            suggestion_inputs.append(f"RESEARCH QUEUE: {rq}")
                        for oq in getattr(ref, 'open_questions', []):
                            suggestion_inputs.append(f"OPEN QUESTION: {oq}")
                except Exception:
                    pass

            # High-importance signals not yet council-debated
            if signals_file.exists():
                cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
                high_undebated: list[str] = []
                with open(signals_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            sig = json.loads(line)
                            if sig.get("timestamp", "") >= cutoff_7d:
                                tags = sig.get("tags", [])
                                level = sig.get("route_level", "")
                                if level in ("HIGH", "CRITICAL") and "council_flagged" not in tags:
                                    title = sig.get("title", "")[:80]
                                    if title and len(high_undebated) < 10:
                                        high_undebated.append(title)
                        except json.JSONDecodeError:
                            continue
                for t in high_undebated[:5]:
                    suggestion_inputs.append(f"HIGH SIGNAL (no council): {t}")

            if api_key and suggestion_inputs:
                try:
                    prompt = (
                        "You are a strategic intelligence advisor for an autonomous AI brain system. "
                        "Based on the following intelligence gaps, prediction failures, research questions, "
                        "and high-importance signals, suggest the top 3 topics that would benefit from "
                        "a full council debate (multi-LLM deliberation with Claude, Grok, Gemini, GPT). "
                        "Explain why each topic matters.\n\n"
                        "INPUTS:\n"
                        + "\n".join(f"- {inp}" for inp in suggestion_inputs[:30]) + "\n\n"
                        "Format as:\n"
                        "1. TOPIC: [topic]\n   WHY: [reasoning]\n"
                        "2. TOPIC: [topic]\n   WHY: [reasoning]\n"
                        "3. TOPIC: [topic]\n   WHY: [reasoning]"
                    )

                    # Run both models in parallel
                    haiku_task = asyncio.wait_for(
                        _call_sonnet_intel(prompt, "I5_council_topics"), timeout=TASK_TIMEOUT
                    )
                    gemini_task = asyncio.wait_for(
                        _call_gemini(prompt, "I5_council_topics"), timeout=TASK_TIMEOUT
                    )
                    haiku_res, gemini_res = await asyncio.gather(
                        haiku_task, gemini_task, return_exceptions=True,
                    )

                    def _parse_topics(text: str) -> list[str]:
                        topics: list[str] = []
                        for line_text in text.split("\n"):
                            line_text = line_text.strip()
                            if line_text and re.match(r'^\d+\.?\s*TOPIC:', line_text, re.IGNORECASE):
                                topic_text = re.sub(r'^\d+\.?\s*TOPIC:\s*', '', line_text, flags=re.IGNORECASE).strip()
                                if topic_text:
                                    topics.append(topic_text)
                        if not topics:
                            for line_text in text.split("\n"):
                                line_text = line_text.strip()
                                if re.match(r'^\d+\.', line_text):
                                    topics.append(line_text)
                        return topics

                    haiku_topics: list[str] = []
                    gemini_topics: list[str] = []
                    haiku_full = ""
                    gemini_full = ""

                    if isinstance(haiku_res, tuple):
                        haiku_full, haiku_cost = haiku_res
                        report["total_cost_usd"] += haiku_cost
                        haiku_topics = _parse_topics(haiku_full)
                    elif isinstance(haiku_res, Exception):
                        log.warning("[NIGHT-WATCH/INTEL] I5 Haiku failed: %s", haiku_res)

                    if isinstance(gemini_res, tuple):
                        gemini_full, gemini_cost = gemini_res
                        report["total_cost_usd"] += gemini_cost
                        gemini_topics = _parse_topics(gemini_full)
                    elif isinstance(gemini_res, Exception):
                        log.warning("[NIGHT-WATCH/INTEL] I5 Gemini failed: %s", gemini_res)

                    # Merge: topics from both models get priority boost
                    haiku_kw_set = {t.lower()[:50] for t in haiku_topics}
                    gemini_kw_set = {t.lower()[:50] for t in gemini_topics}

                    priority_topics: list[str] = []  # Both models agree
                    other_topics: list[str] = []     # Only one model

                    seen_lower: set[str] = set()
                    for t in haiku_topics:
                        t_lower = t.lower()[:50]
                        t_words = set(t_lower.split())
                        # Check if Gemini has a similar topic
                        matched = False
                        for gt in gemini_topics:
                            gt_words = set(gt.lower()[:50].split())
                            overlap = len(t_words & gt_words) / max(len(t_words | gt_words), 1)
                            if overlap > 0.3:
                                matched = True
                                break
                        if matched:
                            priority_topics.append(t)
                        else:
                            other_topics.append(t)
                        seen_lower.add(t_lower)

                    for t in gemini_topics:
                        t_lower = t.lower()[:50]
                        if t_lower not in seen_lower:
                            other_topics.append(t)
                            seen_lower.add(t_lower)

                    # Priority topics first, then others
                    suggestions = priority_topics + other_topics
                    report["council_suggestions"] = suggestions[:5]

                    log.info(
                        "[NIGHT-WATCH/INTEL] I5: Haiku suggested %d, Gemini suggested %d, "
                        "%d priority (both agree), %d total merged",
                        len(haiku_topics), len(gemini_topics),
                        len(priority_topics), len(suggestions),
                    )

                    # Save to file for daytime council scheduling
                    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    topics_file = nw_dir / f"council-topics-{today_str}.json"
                    try:
                        topics_data = {
                            "date": today_str,
                            "generated_at": datetime.now(timezone.utc).isoformat(),
                            "suggestions": suggestions[:5],
                            "priority_topics": priority_topics,
                            "haiku_analysis": haiku_full,
                            "gemini_analysis": gemini_full,
                            "inputs_count": len(suggestion_inputs),
                        }
                        async with aiofiles.open(topics_file, "w") as f:
                            await f.write(json.dumps(topics_data, indent=2))
                        log.info("[NIGHT-WATCH/INTEL] Council topics saved to %s", topics_file)
                    except Exception as e:
                        log.error("[NIGHT-WATCH/INTEL] Failed to save council topics: %s", e)

                except Exception as e:
                    report["errors"].append(f"I5 dual-model: {e}")
                    log.error("[NIGHT-WATCH/INTEL] Task I5 dual-model failed: %s", e)
            else:
                log.info("[NIGHT-WATCH/INTEL] Task I5: no inputs or no API key — skipping")

            log.info("[NIGHT-WATCH/INTEL] Task I5: %d suggestion inputs, %d topics suggested",
                     len(suggestion_inputs), len(report.get("council_suggestions", [])))

        except asyncio.TimeoutError:
            report["errors"].append("I5: timeout")
            log.error("[NIGHT-WATCH/INTEL] Task I5 timed out")
        except Exception as e:
            report["errors"].append(f"I5: {e}")
            log.error("[NIGHT-WATCH/INTEL] Task I5 failed: %s", e, exc_info=True)

        # ══════════════════════════════════════════════════════════════
        # TASK I6: Cost Optimization Analysis (1 Haiku)
        # ══════════════════════════════════════════════════════════════
        try:
            log.info("[NIGHT-WATCH/INTEL] Task I6: Cost optimization analysis...")

            # Get 30-day spending history
            historical = await tracker.get_historical(30)
            today_ledger = await tracker.get_full_ledger(1)

            # Build per-source daily averages
            source_daily_totals: dict[str, list[float]] = defaultdict(list)
            daily_totals: list[float] = []
            for day_summary in historical:
                by_source = day_summary.get("by_source", {})
                day_total = day_summary.get("total_usd", 0)
                daily_totals.append(day_total)
                for source, sdata in by_source.items():
                    spent = sdata.get("spent_usd", 0)
                    if spent > 0:
                        source_daily_totals[source].append(spent)

            # Per-category breakdown from today's ledger
            category_totals: dict[str, float] = defaultdict(float)
            source_totals_today: dict[str, float] = defaultdict(float)
            for entry in today_ledger:
                cat = entry.get("category", "unknown")
                src = entry.get("source", "unknown")
                amt = entry.get("amount_usd", 0)
                category_totals[cat] += amt
                source_totals_today[src] += amt

            # Build analysis summary for Haiku
            cost_summary_lines: list[str] = []
            cost_summary_lines.append(f"30-day history: {len(historical)} days recorded")
            if daily_totals:
                avg_daily = sum(daily_totals) / len(daily_totals)
                max_daily = max(daily_totals)
                cost_summary_lines.append(f"Daily average: ${avg_daily:.4f}, max: ${max_daily:.4f}")

                # Trend: compare last 7 days vs prior 7 days
                if len(daily_totals) >= 14:
                    recent_avg = sum(daily_totals[-7:]) / 7
                    prior_avg = sum(daily_totals[-14:-7]) / 7
                    if prior_avg > 0:
                        change_pct = ((recent_avg - prior_avg) / prior_avg) * 100
                        trend = "INCREASING" if change_pct > 10 else "DECREASING" if change_pct < -10 else "STABLE"
                        cost_summary_lines.append(
                            f"Trend: {trend} ({change_pct:+.1f}% last 7d vs prior 7d)"
                        )

            cost_summary_lines.append(f"\nPer-source daily averages:")
            for source, amounts in sorted(source_daily_totals.items(), key=lambda x: -sum(x[1])):
                avg = sum(amounts) / max(len(amounts), 1)
                cost_summary_lines.append(f"  {source}: ${avg:.4f}/day (over {len(amounts)} days)")

            cost_summary_lines.append(f"\nToday's per-category spend:")
            for cat, amt in sorted(category_totals.items(), key=lambda x: -x[1]):
                cost_summary_lines.append(f"  {cat}: ${amt:.4f}")

            cost_summary_lines.append(f"\nToday's ledger entries: {len(today_ledger)}")
            cost_summary_lines.append(f"Today's total: ${sum(source_totals_today.values()):.4f}")

            if api_key:
                try:
                    prompt = (
                        "You are a cost optimization analyst for an autonomous AI brain system "
                        "that uses Claude, Grok, Gemini, GPT, and local Ollama models. "
                        "Analyze this 30-day cost data and identify optimization opportunities.\n\n"
                        "COST DATA:\n"
                        + "\n".join(cost_summary_lines) + "\n\n"
                        "Identify:\n"
                        "1. Categories where Sonnet could replace Opus (simpler tasks using expensive models)\n"
                        "2. Redundant calls (same data processed twice)\n"
                        "3. Times/patterns of highest spend\n"
                        "4. Project when daily budgets will be consistently exceeded\n\n"
                        "Give 3-5 specific, actionable recommendations. "
                        "Each recommendation as a bullet point starting with '- '."
                    )

                    # Run both models in parallel
                    haiku_task = asyncio.wait_for(
                        _call_sonnet_intel(prompt, "I6_cost_optimization"), timeout=TASK_TIMEOUT
                    )
                    gemini_task = asyncio.wait_for(
                        _call_gemini(prompt, "I6_cost_optimization"), timeout=TASK_TIMEOUT
                    )
                    haiku_res, gemini_res = await asyncio.gather(
                        haiku_task, gemini_task, return_exceptions=True,
                    )

                    haiku_text = ""
                    gemini_text = ""

                    if isinstance(haiku_res, tuple):
                        haiku_text, haiku_cost = haiku_res
                        report["total_cost_usd"] += haiku_cost
                    elif isinstance(haiku_res, Exception):
                        log.warning("[NIGHT-WATCH/INTEL] I6 Haiku failed: %s", haiku_res)

                    if isinstance(gemini_res, tuple):
                        gemini_text, gemini_cost = gemini_res
                        report["total_cost_usd"] += gemini_cost
                    elif isinstance(gemini_res, Exception):
                        log.warning("[NIGHT-WATCH/INTEL] I6 Gemini failed: %s", gemini_res)

                    # Conservative approach: only flag optimizations both models agree on
                    def _extract_recs(text: str) -> list[str]:
                        return [
                            line.strip().lstrip("- •*0123456789.").strip()
                            for line in text.split("\n")
                            if line.strip() and (
                                line.strip().startswith(("-", "•", "*"))
                                or re.match(r'^\d+\.', line.strip())
                            )
                            and len(line.strip()) > 15
                        ]

                    haiku_recs = _extract_recs(haiku_text)
                    gemini_recs = _extract_recs(gemini_text)

                    # Find recommendations both models agree on (word overlap > 30%)
                    agreed_recs: list[str] = []
                    haiku_only: list[str] = []

                    for hr in haiku_recs:
                        hr_words = set(hr.lower().split())
                        matched = False
                        for gr in gemini_recs:
                            gr_words = set(gr.lower().split())
                            overlap = len(hr_words & gr_words) / max(len(hr_words | gr_words), 1)
                            if overlap > 0.3:
                                matched = True
                                break
                        if matched:
                            agreed_recs.append(hr)
                        else:
                            haiku_only.append(hr)

                    # Build combined output — consensus first
                    combined_parts: list[str] = []
                    if agreed_recs:
                        combined_parts.append(
                            "CONSENSUS RECOMMENDATIONS (both Haiku and Gemini agree):\n"
                            + "\n".join(f"- {r}" for r in agreed_recs)
                        )
                    if haiku_only:
                        combined_parts.append(
                            "ADDITIONAL (Haiku-only, not confirmed by Gemini):\n"
                            + "\n".join(f"- {r}" for r in haiku_only[:3])
                        )

                    report["cost_optimization"] = "\n\n".join(combined_parts) if combined_parts else haiku_text or gemini_text

                    log.info(
                        "[NIGHT-WATCH/INTEL] I6: Haiku %d recs, Gemini %d recs, %d consensus",
                        len(haiku_recs), len(gemini_recs), len(agreed_recs),
                    )

                except Exception as e:
                    report["errors"].append(f"I6 dual-model: {e}")
                    log.error("[NIGHT-WATCH/INTEL] Task I6 dual-model failed: %s", e)
            else:
                report["cost_optimization"] = "No API key — skipped LLM analysis"

            log.info("[NIGHT-WATCH/INTEL] Task I6: analyzed %d days of cost history", len(historical))

        except asyncio.TimeoutError:
            report["errors"].append("I6: timeout")
            log.error("[NIGHT-WATCH/INTEL] Task I6 timed out")
        except Exception as e:
            report["errors"].append(f"I6: {e}")
            log.error("[NIGHT-WATCH/INTEL] Task I6 failed: %s", e, exc_info=True)

        # ══════════════════════════════════════════════════════════════
        # WRAP-UP
        # ══════════════════════════════════════════════════════════════

        report["duration_seconds"] = round(time.monotonic() - t0, 2)

        log.info(
            "[NIGHT-WATCH/INTEL] Intel cycle complete — "
            "correlations=%d, blind_spots=%d, over_scored=%d, under_scored=%d, "
            "stale_predictions=%d, council_suggestions=%d, "
            "cost=$%.4f, duration=%.1fs, errors=%d",
            report["missed_correlations"],
            len(report["blind_spots"]),
            report["over_scored_signals"],
            report["under_scored_signals"],
            report["predictions_stale"],
            len(report["council_suggestions"]),
            report["total_cost_usd"],
            report["duration_seconds"],
            len(report["errors"]),
        )

        return report

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
                    t.get_name() for t in self._tasks
                    if t.done() and t.get_name() != "ncl-night-watch"
                ]
                if dead_tasks:
                    issues.append(f"CRITICAL: DEAD scheduler tasks: {', '.join(dead_tasks)}")
            except Exception as e:
                issues.append(f"WARNING: Could not check scheduler tasks — {e}")

            # ── 3. Awarebot sub-tasks alive ────────────────────────────
            try:
                if self.awarebot and hasattr(self.awarebot, "_tasks"):
                    dead_ab = [
                        t.get_name() for t in self.awarebot._tasks if t.done()
                    ]
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
            free_gb = free_bytes / (1024 ** 3)
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
            from ..portfolio.portfolio_routes import _portfolio_manager
            from ..portfolio.paper_routes import _engine as _paper_engine

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

        journal_store = self._journal_store or getattr(self.brain, 'journal_store', None)
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
                if hasattr(r, 'highlights') and r.highlights:
                    summary_text = "; ".join(r.highlights[:3])
                elif hasattr(r, 'summary') and r.summary:
                    summary_text = r.summary[:200]
                elif hasattr(r, 'content') and r.content:
                    summary_text = r.content[:200]
                reflection_summaries.append({
                    "date": getattr(r, 'date', '?'),
                    "summary": summary_text,
                })
                # Extract research queue items
                if hasattr(r, 'research_queue') and r.research_queue:
                    data["research_queue"].extend(r.research_queue[:3])
                if hasattr(r, 'open_questions') and r.open_questions:
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
                if hasattr(e, 'title') and e.title
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
        self, memory_report: dict, intel_report: dict,
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
        COUNCIL_TIMEOUT = 300  # 5 minutes per council

        log.info("[NIGHT-WATCH/COUNCIL] Starting council cycle (4 mini-councils)")

        # ── Helper: 3-call debate pattern ────────────────────────────
        async def _run_mini_council(
            topic: str, prompt: str, label: str,
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
                    cost = (usage.get("input_tokens", 0) * 3.00 + usage.get("output_tokens", 0) * 15.00) / 1_000_000
                    total_cost += cost
                    await tracker.record(
                        "anthropic", cost, "night_watch_council",
                        f"NW council {label} -- Sonnet analysis",
                        {"model": "claude-sonnet-4", "council": label, "step": "analysis"},
                    )
                    log.info("[NIGHT-WATCH/COUNCIL] %s -- Sonnet analysis done ($%.4f)", label, cost)
            except Exception as e:
                log.error("[NIGHT-WATCH/COUNCIL] %s — Claude analysis failed: %s", label, e)
                return None, total_cost

            # Call 2: Grok rebuttal (skip if no xAI key)
            grok_text = ""
            if xai_key:
                try:
                    if not await tracker.can_spend("xai", 0.05):
                        log.warning("[NIGHT-WATCH/COUNCIL] xAI budget exceeded — skipping Grok rebuttal for %s", label)
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
                                "xai", grok_cost, "night_watch_council",
                                f"NW council {label} — Grok rebuttal",
                                {"model": "grok-3", "council": label, "step": "rebuttal"},
                            )
                            log.info("[NIGHT-WATCH/COUNCIL] %s — Grok rebuttal done ($%.4f)", label, grok_cost)
                except Exception as e:
                    log.error("[NIGHT-WATCH/COUNCIL] %s — Grok rebuttal failed: %s", label, e)
                    grok_text = "(Grok rebuttal unavailable)"

            # Call 3: Claude Opus synthesis (top-tier reasoning for council chair)
            try:
                if not await tracker.can_spend("anthropic", 0.20):
                    log.warning("[NIGHT-WATCH/COUNCIL] Budget exceeded -- returning analysis without synthesis for %s", label)
                    return claude_text, total_cost

                council_synthesis_prompt = (
                    f"You are the chair of the NCL Night Watch council. "
                    f"Synthesize these two perspectives on: {topic}\n\n"
                    f"=== ANALYST (Claude) ===\n{claude_text[:1200]}\n\n"
                    f"=== CONTRARIAN (Grok) ===\n{grok_text[:1200] if grok_text else '(No rebuttal available)'}\n\n"
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
                    cost = (usage.get("input_tokens", 0) * 15.00 + usage.get("output_tokens", 0) * 75.00) / 1_000_000
                    total_cost += cost
                    await tracker.record(
                        "anthropic", cost, "night_watch_council",
                        f"NW council {label} -- Opus synthesis",
                        {"model": "claude-opus-4-6", "council": label, "step": "synthesis"},
                    )
                    log.info("[NIGHT-WATCH/COUNCIL] %s -- Opus synthesis done ($%.4f, total=$%.4f)", label, cost, total_cost)
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
                mem_summary_lines.append(f"Duplicates found: {memory_report.get('duplicates_found', 0)}")
                mem_summary_lines.append(f"Units re-scored: {memory_report.get('units_rescored', 0)}")
                mem_summary_lines.append(f"Entities extracted: {memory_report.get('entities_extracted', 0)}")
                mem_summary_lines.append(f"Stale facts found: {memory_report.get('stale_facts_found', 0)}")
                kg = memory_report.get("kg_stats", {})
                mem_summary_lines.append(f"Knowledge graph: {kg.get('nodes', 0)} nodes, {kg.get('edges', 0)} edges, {kg.get('components', 0)} components")
                mem_summary_lines.append(f"Entity normalizations: {memory_report.get('normalizations', 0)}")
                mem_summary_lines.append(f"Cycle cost: ${memory_report.get('total_cost_usd', 0):.4f}")
                errors = memory_report.get("errors", [])
                if errors:
                    mem_summary_lines.append(f"Errors: {'; '.join(errors[:3])}")

            mem_prompt = (
                "You are an AI memory systems analyst on the NCL Night Watch council. "
                "Review tonight's memory maintenance findings for an autonomous AI brain.\n\n"
                f"MEMORY MAINTENANCE REPORT:\n" + "\n".join(mem_summary_lines) + "\n\n"
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
                intel_summary_lines.append(f"Missed correlations: {intel_report.get('missed_correlations', 0)}")
                blind_spots = intel_report.get("blind_spots", [])
                if blind_spots:
                    intel_summary_lines.append(f"Blind spots: {', '.join(blind_spots[:8])}")
                intel_summary_lines.append(f"Over-scored signals: {intel_report.get('over_scored_signals', 0)}")
                intel_summary_lines.append(f"Under-scored signals: {intel_report.get('under_scored_signals', 0)}")
                intel_summary_lines.append(f"Stale predictions: {intel_report.get('predictions_stale', 0)}")
                pma = intel_report.get("per_model_accuracy", {})
                if pma:
                    intel_summary_lines.append("Per-model accuracy: " + ", ".join(f"{m}={a}" for m, a in pma.items()))
                suggestions = intel_report.get("council_suggestions", [])
                if suggestions:
                    intel_summary_lines.append(f"Suggested topics: {'; '.join(suggestions[:3])}")
                cost_opt = intel_report.get("cost_optimization", "")
                if cost_opt:
                    intel_summary_lines.append(f"Cost optimization: {cost_opt[:150]}")

            intel_prompt = (
                "You are an intelligence analyst on the NCL Night Watch council. "
                "Review tonight's intelligence correlation findings for an autonomous AI brain.\n\n"
                f"INTELLIGENCE CORRELATION REPORT:\n" + "\n".join(intel_summary_lines) + "\n\n"
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
                port_summary_lines.append(f"Portfolio not available: {portfolio_data.get('error', 'not initialized')}")
            else:
                port_summary_lines.append(f"Total portfolio value: ${portfolio_data.get('total_value', 0):,.2f}")
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
                f"PORTFOLIO SNAPSHOT:\n" + "\n".join(port_summary_lines) + "\n\n"
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
                journal_summary_lines.append(f"Journal not available: {journal_data.get('error', 'not initialized')}")
            else:
                analytics = journal_data.get("analytics_summary", {})
                journal_summary_lines.append(f"Entries (30d): {analytics.get('total_entries', 0)}")
                journal_summary_lines.append(f"Words written: {analytics.get('total_words', 0):,}")
                journal_summary_lines.append(f"Current streak: {analytics.get('current_streak', 0)} days")
                journal_summary_lines.append(f"Avg importance: {analytics.get('avg_importance', 0):.1f}")
                top_tags = analytics.get("top_tags", {})
                if top_tags:
                    journal_summary_lines.append(f"Top tags: {', '.join(list(top_tags.keys())[:8])}")
                by_type = analytics.get("entries_by_type", {})
                if by_type:
                    journal_summary_lines.append(f"Entry types: {json.dumps(by_type)}")

                reflections = journal_data.get("weekly_patterns", [])
                if reflections:
                    journal_summary_lines.append("\nRecent reflections:")
                    for r in reflections[:3]:
                        journal_summary_lines.append(f"  [{r.get('date', '?')}]: {r.get('summary', 'N/A')[:150]}")

                rq = journal_data.get("research_queue", [])
                if rq:
                    journal_summary_lines.append(f"\nResearch queue: {'; '.join(str(q) for q in rq[:5])}")
                oq = journal_data.get("open_questions", [])
                if oq:
                    journal_summary_lines.append(f"Open questions: {'; '.join(str(q) for q in oq[:5])}")

                titles = journal_data.get("recent_entry_titles", [])
                if titles:
                    journal_summary_lines.append(f"\nRecent entries: {'; '.join(titles[:8])}")

            journal_prompt = (
                "You are a strategic thinking analyst on the NCL Night Watch council. "
                "Review this week's journal patterns, research queues, and decision history "
                "for an autonomous AI brain operator.\n\n"
                f"JOURNAL & STRATEGY DATA:\n" + "\n".join(journal_summary_lines) + "\n\n"
                "Questions to address:\n"
                "- What themes are emerging across recent journal entries?\n"
                "- Which research questions remain unresolved and should be prioritized?\n"
                "- Are there blind spots in the operator's thinking?\n"
                "- What should be tomorrow's focus areas based on patterns?\n"
                "- Is the journal practice itself healthy (streak, frequency, depth)?\n"
                "Be concise — 5-8 bullet points."
            )

            synthesis, cost = await asyncio.wait_for(
                _run_mini_council("Night Watch Journal & Strategy Review", journal_prompt, "journal"),
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
            report["councils_run"], report["total_cost_usd"], report["duration_seconds"],
        )

        await self._log_autonomous_event("night_watch_council", {
            "councils_run": report["councils_run"],
            "total_cost_usd": report["total_cost_usd"],
            "duration_seconds": report["duration_seconds"],
            "errors": report["errors"],
        })

        return report

    # ─── NIGHT WATCH ANALYST: LLM-powered nightly analysis ─────────

    async def _night_watch_analyst(
        self, deterministic_issues: list[str], has_warnings: bool, critical: bool,
        *, memory_report: dict | None = None, intel_report: dict | None = None,
        council_report: dict | None = None,
    ) -> None:
        """
        LLM-powered analysis phase for Night Watch.

        Runs AFTER the deterministic health checks. Collects operational data
        from multiple subsystems, triages with Sonnet, synthesizes with Opus,
        pushes a daily briefing via ntfy, and saves to disk.
        """
        import glob as glob_mod
        import httpx

        from ..cost_tracker import get_tracker

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            log.warning("[NIGHT-WATCH] No ANTHROPIC_API_KEY — skipping LLM analyst")
            return

        tracker = await get_tracker()

        # ── Budget guard: estimate max cost ──────────────────────────
        # 4 Sonnet calls ~2000 tok in + ~500 tok out each = ~$0.05
        # 1 Sonnet call ~4000 tok in + ~1000 tok out   = ~$0.027
        # Total estimate: ~$0.04
        estimated_total = 0.05  # conservative
        if not await tracker.can_spend("anthropic", estimated_total):
            log.warning("[NIGHT-WATCH] LLM analysis skipped — budget exceeded")
            return

        # ══════════════════════════════════════════════════════════════
        # DATA COLLECTION PHASE (all local, no LLM cost)
        # ══════════════════════════════════════════════════════════════

        collected: dict[str, str] = {}

        # ── 1. Cost ledger summary ────────────────────────────────────
        try:
            cost_lines: list[str] = []
            ledger_path = self.data_dir / "costs" / "cost_ledger.jsonl"
            if ledger_path.exists():
                source_totals: dict[str, float] = defaultdict(float)
                category_totals: dict[str, float] = defaultdict(float)
                all_entries: list[dict] = []
                with open(ledger_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            if entry.get("date") == today_str:
                                src = entry.get("source", "unknown")
                                cat = entry.get("category", "unknown")
                                amt = entry.get("amount_usd", 0.0)
                                source_totals[src] += amt
                                category_totals[cat] += amt
                                all_entries.append(entry)
                        except json.JSONDecodeError:
                            continue

                grand_total = sum(source_totals.values())
                cost_lines.append(f"Total spend today: ${grand_total:.4f}")
                cost_lines.append(f"Calls today: {len(all_entries)}")
                cost_lines.append("Per-source: " + ", ".join(
                    f"{s}=${v:.4f}" for s, v in sorted(
                        source_totals.items(), key=lambda x: -x[1]
                    )
                ))
                cost_lines.append("Per-category: " + ", ".join(
                    f"{c}=${v:.4f}" for c, v in sorted(
                        category_totals.items(), key=lambda x: -x[1]
                    )[:8]
                ))
                # Top 5 most expensive individual calls
                top5 = sorted(all_entries, key=lambda e: -e.get("amount_usd", 0))[:5]
                if top5:
                    cost_lines.append("Top 5 costliest calls:")
                    for e in top5:
                        cost_lines.append(
                            f"  ${e.get('amount_usd', 0):.4f} — "
                            f"{e.get('source', '?')}/{e.get('category', '?')}: "
                            f"{e.get('detail', '')[:80]}"
                        )
            else:
                cost_lines.append("No cost ledger found.")

            collected["costs"] = "\n".join(cost_lines)
        except Exception as e:
            collected["costs"] = f"Error reading cost data: {e}"

        # ── 2. Prediction accuracy ────────────────────────────────────
        try:
            pred_lines: list[str] = []
            pred_dir = self.data_dir / "predictions"
            if pred_dir.exists():
                pred_files = sorted(pred_dir.glob("pred-*.json"), reverse=True)[:20]
                total_preds = 0
                with_outcome = 0
                correct = 0
                topics: list[str] = []
                for pf in pred_files:
                    try:
                        pdata = json.loads(pf.read_text())
                        preds_list = pdata if isinstance(pdata, list) else pdata.get("predictions", [pdata])
                        for p in (preds_list if isinstance(preds_list, list) else [preds_list]):
                            total_preds += 1
                            topic = p.get("topic", p.get("title", ""))
                            if topic and len(topics) < 10:
                                topics.append(topic[:60])
                            outcome = p.get("outcome")
                            if outcome:
                                with_outcome += 1
                                if outcome in ("correct", "partial"):
                                    correct += 1
                    except Exception:
                        continue

                pred_lines.append(f"Recent prediction files: {len(pred_files)}")
                pred_lines.append(f"Total predictions parsed: {total_preds}")
                pred_lines.append(f"With recorded outcomes: {with_outcome}")
                if with_outcome > 0:
                    acc = correct / with_outcome * 100
                    pred_lines.append(f"Accuracy (correct+partial): {acc:.1f}%")
                if topics:
                    pred_lines.append(f"Recent topics: {'; '.join(topics[:5])}")

                # Check accuracy.jsonl
                acc_file = pred_dir / "accuracy.jsonl"
                if acc_file.exists():
                    acc_count = sum(1 for _ in open(acc_file))
                    pred_lines.append(f"Accuracy JSONL entries: {acc_count}")
            else:
                pred_lines.append("No predictions directory found.")

            collected["predictions"] = "\n".join(pred_lines)
        except Exception as e:
            collected["predictions"] = f"Error reading predictions: {e}"

        # ── 3. Council session summary ────────────────────────────────
        try:
            council_lines: list[str] = []
            councils_dir = self.data_dir / "councils"
            if councils_dir.exists():
                # Count report files from today
                report_files = list(councils_dir.glob("*.json"))
                today_reports: list[dict] = []
                for rf in report_files:
                    try:
                        if rf.stat().st_mtime > (
                            datetime.now(timezone.utc) - timedelta(hours=24)
                        ).timestamp():
                            rdata = json.loads(rf.read_text())
                            topic = rdata.get("topic", rdata.get("prompt", ""))[:80]
                            today_reports.append({"file": rf.name, "topic": topic})
                    except Exception:
                        continue

                council_lines.append(f"Council reports (last 24h): {len(today_reports)}")
                for cr in today_reports[:5]:
                    council_lines.append(f"  {cr['file']}: {cr['topic']}")

                # Also check council sessions file
                sessions_file = self.data_dir / "council_sessions.json"
                if sessions_file.exists():
                    try:
                        sdata = json.loads(sessions_file.read_text())
                        if isinstance(sdata, list):
                            council_lines.append(f"Total council sessions on record: {len(sdata)}")
                    except Exception:
                        pass
            else:
                council_lines.append("No councils directory found.")

            collected["councils"] = "\n".join(council_lines)
        except Exception as e:
            collected["councils"] = f"Error reading council data: {e}"

        # ── 4. Memory stats ───────────────────────────────────────────
        try:
            mem_lines: list[str] = []
            if self.brain and self.brain.memory_store:
                try:
                    stats = await self.brain.memory_store.stats()
                    if isinstance(stats, dict):
                        mem_lines.append(f"Memory units: {stats.get('total', 'unknown')}")
                        for k, v in stats.items():
                            if k != "total" and isinstance(v, (int, float)):
                                mem_lines.append(f"  {k}: {v}")
                    else:
                        mem_lines.append(f"Memory stats: {stats}")
                except Exception as e:
                    mem_lines.append(f"Memory store stats() failed: {e}")
            else:
                mem_lines.append("Memory store not available.")

            collected["memory"] = "\n".join(mem_lines)
        except Exception as e:
            collected["memory"] = f"Error reading memory stats: {e}"

        # ── 4b. Night Watch Memory Cycle report ──────────────────────
        if memory_report:
            try:
                mc_lines: list[str] = []
                if memory_report.get("error"):
                    mc_lines.append(f"Memory cycle error: {memory_report['error']}")
                else:
                    mc_lines.append(f"Duplicates found: {memory_report.get('duplicates_found', 0)}")
                    mc_lines.append(f"Units re-scored: {memory_report.get('units_rescored', 0)}")
                    mc_lines.append(f"Entities extracted: {memory_report.get('entities_extracted', 0)}")
                    mc_lines.append(f"Stale facts found: {memory_report.get('stale_facts_found', 0)}")
                    mc_lines.append(f"Normalizations: {memory_report.get('normalizations', 0)}")
                    kg = memory_report.get("kg_stats", {})
                    if kg:
                        mc_lines.append(f"KG nodes: {kg.get('nodes', 0)}, edges: {kg.get('edges', 0)}, components: {kg.get('components', 0)}")
                    mc_lines.append(f"Memory cycle cost: ${memory_report.get('total_cost_usd', 0):.4f}")
                    mc_lines.append(f"Memory cycle duration: {memory_report.get('duration_seconds', 0):.1f}s")
                    errors = memory_report.get("errors", [])
                    if errors:
                        mc_lines.append(f"Errors ({len(errors)}): " + "; ".join(errors[:5]))
                collected["memory_cycle"] = "\n".join(mc_lines)
            except Exception as e:
                collected["memory_cycle"] = f"Error formatting memory cycle report: {e}"

        # ── 4c. Night Watch Intel Cycle report ────────────────────────
        if intel_report:
            try:
                ic_lines: list[str] = []
                if intel_report.get("error"):
                    ic_lines.append(f"Intel cycle error: {intel_report['error']}")
                else:
                    ic_lines.append(f"Missed correlations: {intel_report.get('missed_correlations', 0)}")
                    blind_spots = intel_report.get("blind_spots", [])
                    if blind_spots:
                        ic_lines.append(f"Coverage blind spots ({len(blind_spots)}): {', '.join(blind_spots[:10])}")
                    ic_lines.append(f"Over-scored signals: {intel_report.get('over_scored_signals', 0)}")
                    ic_lines.append(f"Under-scored signals: {intel_report.get('under_scored_signals', 0)}")
                    ic_lines.append(f"Stale predictions: {intel_report.get('predictions_stale', 0)}")
                    pma = intel_report.get("per_model_accuracy", {})
                    if pma:
                        ic_lines.append("Per-model accuracy: " + ", ".join(
                            f"{m}={a}" for m, a in pma.items()
                        ))
                    suggestions = intel_report.get("council_suggestions", [])
                    if suggestions:
                        ic_lines.append(f"Council topic suggestions ({len(suggestions)}): {'; '.join(suggestions[:3])}")
                    cost_opt = intel_report.get("cost_optimization", "")
                    if cost_opt:
                        ic_lines.append(f"Cost optimization: {cost_opt[:200]}")
                    ic_lines.append(f"Intel cycle cost: ${intel_report.get('total_cost_usd', 0):.4f}")
                    ic_lines.append(f"Intel cycle duration: {intel_report.get('duration_seconds', 0):.1f}s")
                    errors = intel_report.get("errors", [])
                    if errors:
                        ic_lines.append(f"Errors ({len(errors)}): " + "; ".join(errors[:5]))
                collected["intel_cycle"] = "\n".join(ic_lines)
            except Exception as e:
                collected["intel_cycle"] = f"Error formatting intel cycle report: {e}"

        # ── 4d. Night Watch Council Cycle report ─────────────────────
        if council_report:
            try:
                cc_lines: list[str] = []
                if council_report.get("error"):
                    cc_lines.append(f"Council cycle error: {council_report['error']}")
                else:
                    cc_lines.append(f"Councils run: {council_report.get('councils_run', 0)}/4")
                    for domain in ("memory", "intel", "portfolio", "journal"):
                        synthesis = council_report.get(f"{domain}_council")
                        if synthesis:
                            # Truncate each council output for the analyst prompt
                            cc_lines.append(f"\n--- {domain.upper()} COUNCIL ---")
                            cc_lines.append(synthesis[:500])
                    cc_lines.append(f"\nCouncil cycle cost: ${council_report.get('total_cost_usd', 0):.4f}")
                    cc_lines.append(f"Council cycle duration: {council_report.get('duration_seconds', 0):.1f}s")
                    errors = council_report.get("errors", [])
                    if errors:
                        cc_lines.append(f"Errors ({len(errors)}): " + "; ".join(errors[:5]))
                collected["council_cycle"] = "\n".join(cc_lines)
            except Exception as e:
                collected["council_cycle"] = f"Error formatting council cycle report: {e}"

        # ── 5. Awarebot scan results ──────────────────────────────────
        try:
            aware_lines: list[str] = []
            intel_dir = self.data_dir / "intelligence"
            if intel_dir.exists():
                signals_file = intel_dir / "signals.jsonl"
                if signals_file.exists():
                    recent_signals = 0
                    tier_counts: dict[str, int] = defaultdict(int)
                    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
                    with open(signals_file, "r") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                sig = json.loads(line)
                                ts = sig.get("timestamp", "")
                                if ts >= cutoff:
                                    recent_signals += 1
                                    tier = sig.get("tier", sig.get("importance_tier", "unknown"))
                                    tier_counts[str(tier)] += 1
                            except json.JSONDecodeError:
                                continue
                    aware_lines.append(f"Signals (last 24h): {recent_signals}")
                    if tier_counts:
                        aware_lines.append("By tier: " + ", ".join(
                            f"{t}={c}" for t, c in sorted(tier_counts.items())
                        ))

                briefs_file = intel_dir / "briefs.jsonl"
                if briefs_file.exists():
                    brief_count = 0
                    with open(briefs_file, "r") as f:
                        for line in f:
                            if line.strip():
                                brief_count += 1
                    aware_lines.append(f"Total intel briefs on record: {brief_count}")

            if self.awarebot:
                ab_stats = self.awarebot.get_stats()
                if isinstance(ab_stats, dict):
                    aware_lines.append(f"Awarebot scans completed: {ab_stats.get('scans_completed', '?')}")
                    aware_lines.append(f"Awarebot predictions run: {ab_stats.get('predictions_run', '?')}")

            if not aware_lines:
                aware_lines.append("No intelligence data found.")

            collected["intelligence"] = "\n".join(aware_lines)
        except Exception as e:
            collected["intelligence"] = f"Error reading intelligence data: {e}"

        # ── 6. Log analysis ───────────────────────────────────────────
        try:
            log_lines: list[str] = []
            log_candidates = [
                Path.home() / "NCL" / "logs" / "brain-stderr.log",
                Path.home() / "dev" / "NCL" / "logs" / "brain-stderr.log",
                self.data_dir.parent / "logs" / "brain-stderr.log",
                self.data_dir.parent / "logs" / "ncl-brain-stderr.log",
            ]
            log_file = None
            for lf in log_candidates:
                if lf.exists():
                    log_file = lf
                    break

            if log_file:
                # Read last 200 lines
                all_lines_raw = log_file.read_text(errors="replace").splitlines()
                tail = all_lines_raw[-200:]
                error_count = 0
                warning_count = 0
                unique_errors: set[str] = set()
                for ll in tail:
                    if "ERROR" in ll:
                        error_count += 1
                        # Extract error message (after last colon or ERROR marker)
                        parts = ll.split("ERROR", 1)
                        err_msg = parts[1].strip()[:120] if len(parts) > 1 else ll[:120]
                        unique_errors.add(err_msg)
                    elif "WARNING" in ll:
                        warning_count += 1

                log_lines.append(f"Log file: {log_file.name}")
                log_lines.append(f"Last 200 lines: {error_count} ERRORs, {warning_count} WARNINGs")
                if unique_errors:
                    log_lines.append(f"Unique error patterns ({len(unique_errors)}):")
                    for ue in list(unique_errors)[:10]:
                        log_lines.append(f"  {ue[:120]}")
            else:
                log_lines.append("No brain log file found.")

            collected["logs"] = "\n".join(log_lines)
        except Exception as e:
            collected["logs"] = f"Error reading logs: {e}"

        # ══════════════════════════════════════════════════════════════
        # LLM ANALYSIS PHASE
        # ══════════════════════════════════════════════════════════════

        api_headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        sonnet_model = "claude-sonnet-4"
        opus_model = "claude-opus-4-6"

        # Sonnet cost rates: $3.00/1M input, $15.00/1M output
        # Opus cost rates: $15.00/1M input, $75.00/1M output

        triage_outputs: dict[str, str] = {}
        total_llm_cost = 0.0

        async def _call_anthropic(
            model: str, prompt: str, max_tokens: int, label: str
        ) -> tuple[str, float]:
            """Make a single Anthropic API call, return (text, cost_usd)."""
            timeout = 120.0 if model == opus_model else 60.0
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=api_headers,
                    json={
                        "model": model,
                        "max_tokens": max_tokens,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                text = data["content"][0]["text"]
                usage = data.get("usage", {})
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)

                # Compute cost per model
                if model == opus_model:
                    cost = (input_tokens * 15.00 + output_tokens * 75.00) / 1_000_000
                else:
                    # Sonnet-class rates (default)
                    cost = (input_tokens * 3.00 + output_tokens * 15.00) / 1_000_000

                log.info(
                    "[NIGHT-WATCH] LLM call '%s': %d in / %d out tokens, $%.4f",
                    label, input_tokens, output_tokens, cost,
                )
                return text, cost

        # ── Sonnet triage calls ───────────────────────────────────────

        triage_prompts = {
            "cost_analysis": (
                "You are an operations analyst for an autonomous AI brain system. "
                "Analyze this cost data from today. Flag anomalies, unusual spending "
                "patterns, projected budget issues, and sources burning money fastest. "
                "Be concise — 3-5 bullet points max.\n\n"
                f"COST DATA:\n{collected.get('costs', 'No data')}\n\n"
                f"DETERMINISTIC ISSUES FOUND:\n" +
                "\n".join(deterministic_issues[:10]) if deterministic_issues else "None"
            ),
            "prediction_review": (
                "You are a prediction system analyst. Review this prediction data "
                "for an AI forecasting system. Note any accuracy drift, coverage gaps, "
                "or model performance issues. 3-5 bullet points.\n\n"
                f"PREDICTION DATA:\n{collected.get('predictions', 'No data')}\n\n"
                f"COUNCIL DATA:\n{collected.get('councils', 'No data')}"
            ),
            "log_analysis": (
                "You are a systems reliability engineer. Analyze these log extracts "
                "from an AI brain service. Categorize errors by severity, identify "
                "root causes, flag any patterns that suggest impending failures. "
                "3-5 bullet points.\n\n"
                f"LOG DATA:\n{collected.get('logs', 'No data')}"
            ),
            "system_health": (
                "You are an infrastructure analyst. Review this operational data for "
                "an autonomous AI system. Assess memory health, intelligence pipeline "
                "throughput, and scanner performance. Note any degradation or anomalies. "
                "3-5 bullet points.\n\n"
                f"MEMORY:\n{collected.get('memory', 'No data')}\n\n"
                f"INTELLIGENCE:\n{collected.get('intelligence', 'No data')}"
            ),
        }

        for label, prompt in triage_prompts.items():
            try:
                # Budget check before each call
                if not await tracker.can_spend("anthropic", 0.03):
                    log.warning("[NIGHT-WATCH] Budget hit mid-analysis -- stopping Sonnet triage")
                    break

                text, cost = await _call_anthropic(sonnet_model, prompt, 1024, label)
                triage_outputs[label] = text
                total_llm_cost += cost

                await tracker.record(
                    "anthropic", cost, "night_watch",
                    f"Night Watch Sonnet triage: {label}",
                    {"model": sonnet_model, "phase": "triage", "label": label},
                )
            except Exception as e:
                log.error("[NIGHT-WATCH] Sonnet triage '%s' failed: %s", label, e)
                triage_outputs[label] = f"[Analysis failed: {type(e).__name__}: {e}]"

        # ── Opus synthesis call ───────────────────────────────────────
        synthesis_text = ""
        if triage_outputs:
            try:
                if not await tracker.can_spend("anthropic", 0.10):
                    log.warning("[NIGHT-WATCH] Budget hit -- skipping Opus synthesis")
                else:
                    subsystem_reports = "\n\n".join(
                        f"=== {label.upper()} ===\n{text}"
                        for label, text in triage_outputs.items()
                    )

                    deterministic_summary = (
                        "\n".join(f"  - {i}" for i in deterministic_issues[:15])
                        if deterministic_issues else "None — all deterministic checks passed."
                    )

                    synthesis_prompt = (
                        "You are the Night Watch analyst for NCL Brain, an autonomous AI "
                        "second brain system. Synthesize these subsystem triage reports into "
                        "a daily briefing for NATRIX (the human operator).\n\n"
                        "FORMAT YOUR RESPONSE EXACTLY AS:\n"
                        "STATUS: [GREEN/YELLOW/RED]\n\n"
                        "KEY FINDINGS:\n- [3-5 concise bullets about what matters most]\n\n"
                        "COST REPORT:\n- Today's spend, budget utilization, anomalies\n\n"
                        "SYSTEM HEALTH:\n- Component status, degraded services, pipeline throughput\n\n"
                        "RECOMMENDATIONS:\n- [2-3 actionable items for tomorrow]\n\n"
                        "Be concise and actionable. Focus on PATTERNS and CORRELATIONS "
                        "across subsystems, not just restating individual findings. "
                        "Highlight anything that could become a problem if ignored.\n\n"
                        f"DETERMINISTIC HEALTH CHECK ISSUES:\n{deterministic_summary}\n\n"
                        f"SUBSYSTEM TRIAGE REPORTS:\n{subsystem_reports}"
                    )

                    synthesis_text, cost = await _call_anthropic(
                        opus_model, synthesis_prompt, 2048, "synthesis"
                    )
                    total_llm_cost += cost

                    await tracker.record(
                        "anthropic", cost, "night_watch",
                        "Night Watch Opus synthesis",
                        {"model": opus_model, "phase": "synthesis"},
                    )
            except Exception as e:
                log.error("[NIGHT-WATCH] Opus synthesis failed: %s", e)
                synthesis_text = ""

        # ── Fallback: if no synthesis, use deterministic results ──────
        if not synthesis_text:
            synthesis_text = (
                "STATUS: UNKNOWN\n\n"
                "LLM analysis was unavailable. Deterministic check results:\n"
                + ("\n".join(f"  - {i}" for i in deterministic_issues) if deterministic_issues
                   else "All deterministic checks passed.")
                + "\n\nSonnet triage outputs:\n"
                + "\n".join(f"  [{k}]: {v[:200]}" for k, v in triage_outputs.items())
            )

        # ══════════════════════════════════════════════════════════════
        # OUTPUT PHASE
        # ══════════════════════════════════════════════════════════════

        # ── 1. Save to disk ───────────────────────────────────────────
        try:
            nw_dir = self.data_dir / "night-watch"
            nw_dir.mkdir(parents=True, exist_ok=True)
            brief_file = nw_dir / f"daily-{today_str}.md"

            brief_content = (
                f"# NCL Night Watch Daily Brief — {today_str}\n\n"
                f"Generated: {datetime.now(timezone.utc).isoformat()}\n"
                f"LLM cost: ${total_llm_cost:.4f}\n\n"
                f"---\n\n"
                f"{synthesis_text}\n\n"
                f"---\n\n"
                f"## Raw Data Collected\n\n"
            )
            for section, data in collected.items():
                brief_content += f"### {section.title()}\n```\n{data}\n```\n\n"

            async with aiofiles.open(brief_file, "w") as f:
                await f.write(brief_content)

            log.info("[NIGHT-WATCH] Daily brief saved to %s", brief_file)
        except Exception as e:
            log.error("[NIGHT-WATCH] Failed to save daily brief: %s", e)

        # ── 2. Determine status for push notification ─────────────────
        status_line = ""
        for line in synthesis_text.split("\n"):
            if line.strip().startswith("STATUS:"):
                status_line = line.strip().split(":", 1)[1].strip().upper()
                break

        if "RED" in status_line:
            nw_priority = "5"
            nw_tags = "brain,red_circle"
            nw_title = "NCL Night Watch Brief — RED"
        elif "YELLOW" in status_line:
            nw_priority = "4"
            nw_tags = "brain,yellow_circle"
            nw_title = "NCL Night Watch Brief — YELLOW"
        else:
            nw_priority = "3"
            nw_tags = "brain,green_circle"
            nw_title = "NCL Night Watch Daily Brief"

        # ── 3. Push via ntfy ──────────────────────────────────────────
        # Migrated 2026-05-21 to enqueue via central AlertDispatcher.
        try:
            push_body = synthesis_text
            if len(push_body) > 3800:
                push_body = push_body[:3800] + "\n\n... (truncated — full brief saved to disk)"
            push_body += f"\n\nLLM analysis cost: ${total_llm_cost:.4f}"

            try:
                enqueue_alert(
                    title=nw_title,
                    body=push_body,
                    priority=nw_priority,
                    tags=nw_tags,
                    dedup_key=f"night-watch-analyst:{datetime.now(timezone.utc).date().isoformat()}",
                    source="night_watch",
                )
                log.info("[NIGHT-WATCH] Analyst brief enqueued: %s", nw_title)
            except Exception as enq_err:
                log.warning("[NIGHT-WATCH] dispatcher unavailable, direct POST fallback: %s", enq_err)
                async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                    resp = await client.post(
                        "https://ntfy.sh/ncl-natrix-intel-7x9k",
                        content=push_body.encode("utf-8"),
                        headers={
                            "Content-Type": "text/plain; charset=utf-8",
                            "Title": nw_title.encode("ascii", "replace").decode("ascii"),
                            "Priority": nw_priority,
                            "Tags": nw_tags,
                        },
                    )
                    resp.raise_for_status()
                    log.info("[NIGHT-WATCH] Analyst brief pushed via ntfy (fallback): %s", nw_title)
        except Exception as e:
            log.error("[NIGHT-WATCH] Analyst ntfy push failed: %s", e)

        log.info(
            "[NIGHT-WATCH] Analyst phase complete — total LLM cost: $%.4f, "
            "triage calls: %d, synthesis: %s",
            total_llm_cost, len(triage_outputs),
            "yes" if "STATUS:" in synthesis_text else "fallback",
        )

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

        log.info("[SUPERVISOR] Supervisor loop started (check every %ds, max %d restarts/task)",
                 check_interval, max_restarts)

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
                    error_str = f"{type(exc).__name__}: {exc}" if exc else "completed unexpectedly"

                    log.warning(
                        "[SUPERVISOR] Task '%s' is dead: %s", name, error_str
                    )

                    factory = self._task_factories.get(name)
                    if not factory:
                        log.error(
                            "[SUPERVISOR] No factory for task '%s' — cannot restart", name
                        )
                        continue

                    if self._restart_counts[name] < max_restarts:
                        self._restart_counts[name] += 1
                        attempt = self._restart_counts[name]
                        log.warning(
                            "[SUPERVISOR] Restarting '%s' (attempt %d/%d) after 5s delay",
                            name, attempt, max_restarts,
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
                                    t.get_name(), type(e).__name__, e,
                                    exc_info=e,
                                )
                        new_task.add_done_callback(_task_done)

                        # Replace the dead task in the list
                        self._tasks = [
                            t for t in self._tasks if t is not task
                        ]
                        self._tasks.append(new_task)

                        log.info(
                            "[SUPERVISOR] Task '%s' restarted successfully (attempt %d/%d)",
                            name, attempt, max_restarts,
                        )
                        await self._log_autonomous_event("supervisor_restart", {
                            "task": name,
                            "attempt": attempt,
                            "max_restarts": max_restarts,
                            "error": error_str,
                        })
                    else:
                        log.error(
                            "[SUPERVISOR] Task '%s' has exhausted restart budget (%d/%d) "
                            "— permanently dead",
                            name, self._restart_counts[name], max_restarts,
                        )
                        await self._send_supervisor_alert(name, error_str)
                        await self._log_autonomous_event("supervisor_task_dead", {
                            "task": name,
                            "restarts_used": self._restart_counts[name],
                            "error": error_str,
                        })
                        # Remove the dead task from the list
                        self._tasks = [
                            t for t in self._tasks if t is not task
                        ]

                # ── Check Awarebot sub-tasks (only if its supervisor is dead) ─
                if (
                    self.awarebot
                    and hasattr(self.awarebot, "_tasks")
                    and self.awarebot._tasks
                ):
                    # The Awarebot agent's run() method IS the supervisor.
                    # Find the ncl-awarebot-agent task to check if it's alive.
                    awarebot_agent_alive = any(
                        t.get_name() == "ncl-awarebot-agent" and not t.done()
                        for t in self._tasks
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
                                if sub_exc else "completed unexpectedly"
                            )
                            log.warning(
                                "[SUPERVISOR] Awarebot sub-task '%s' dead (supervisor also dead): %s",
                                sub_name, sub_error,
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
            check_interval, alerts_path,
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
                        or f"{alert.get('timestamp','')}|{alert.get('type','')}|{alert.get('title','')}"
                    )
                    if not alert_id or alert_id in self._pushed_calendar_alerts:
                        continue

                    title = alert.get("title") or f"Calendar {severity.upper()} Alert"
                    body = alert.get("message") or alert.get("body") or json.dumps(alert, default=_json_safe)
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
                            severity, title,
                        )
                    except Exception as push_err:
                        log.warning(
                            "[CALENDAR-ALERTS] Failed to push alert '%s': %s",
                            alert_id, push_err,
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
        "last_scan":               (15 * 60,   "Awarebot scan"),
        "last_prediction":         (90 * 60,   "Prediction"),
        "last_consolidation":      (2 * 3600,  "Memory consolidation"),
        "last_intel_brief":        (6 * 3600,  "Intel brief"),
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
                            stale.append({
                                "loop": label,
                                "key": key,
                                "last_fire_at": None,
                                "age_s": int((now - s).total_seconds()),
                                "threshold_s": max_age,
                            })
                    except Exception:
                        pass
                continue
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age = (now - ts).total_seconds()
                if age > max_age:
                    stale.append({
                        "loop": label,
                        "key": key,
                        "last_fire_at": ts_str,
                        "age_s": int(age),
                        "threshold_s": max_age,
                    })
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
            fd = await asyncio.to_thread(
                lambda: open(flags_file, "r")
            )
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
            from ..cost_tracker import get_tracker, LEDGER_FILE
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
                        last_seen_date, today,
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
                            if closing_totals else (None, 0.0)
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
                            "[COST-ROLLOVER] %s closed: $%.4f across %d calls — top source: %s ($%.4f)",
                            closing_date, total_usd, sum(closing_counts.values()),
                            top_source[0] or "(none)", top_source[1],
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
                                window, e,
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
                self._stats["cache_warms_count"] = (
                    self._stats.get("cache_warms_count", 0) + 1
                )
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
                # Budget gate — block if YTC budget exhausted for the day.
                if not await check_budget("ytc", 0.10):
                    log.warning("[YTC-DEDICATED] ytc daily budget exhausted — skipping cycle")
                    try:
                        await asyncio.sleep(ytc_interval)
                        continue
                    except asyncio.CancelledError:
                        raise

                session_id = f"ytc-dedicated-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
                log.info(f"[YTC-DEDICATED] Starting YouTube Council run: {session_id}")

                from ..councils.runner import run_youtube_council
                report = await run_youtube_council(session_id)

                if report:
                    ncl_base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
                    json_dir = ncl_base / "intelligence-scan" / "youtube-reports"
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(
                        None, lambda: json_dir.mkdir(parents=True, exist_ok=True)
                    )

                    per_video = getattr(report, "_per_video_reports", [])
                    for vid_report in per_video:
                        vid_data = vid_report.to_dict()
                        vid_data.update({
                            "status": "complete",
                            "completed_at": datetime.now(timezone.utc).isoformat(),
                            "auto_triggered": True,
                            "report_type": "per_video",
                            "spawned_by": "ncl-ytc-dedicated",
                        })
                        vid_path = json_dir / f"{vid_report.session_id}.json"
                        async with aiofiles.open(vid_path, "w") as f:
                            await f.write(json.dumps(vid_data, default=str, indent=2))

                    out_path = json_dir / f"{session_id}.json"
                    report_data = report.to_dict()
                    report_data.update({
                        "session_id": session_id,
                        "status": "complete",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "auto_triggered": True,
                        "report_type": "rollup",
                        "per_video_count": len(per_video),
                        "spawned_by": "ncl-ytc-dedicated",
                    })
                    async with aiofiles.open(out_path, "w") as f:
                        await f.write(json.dumps(report_data, default=str, indent=2))

                    # Conservative per-video estimate; tighten later if usage data exposed.
                    est_cost = max(0.05, 0.05 * max(1, len(per_video)))
                    try:
                        await record_cost(
                            "ytc", est_cost, "ytc_per_video",
                            detail=f"{len(per_video)} videos + 1 rollup ({session_id})",
                        )
                    except Exception as ce:
                        log.warning("[YTC-DEDICATED] record_cost failed: %s", ce)

                    log.info(
                        f"[YTC-DEDICATED] run complete: {session_id} "
                        f"({len(per_video)} per-video + 1 rollup, est ${est_cost:.4f})"
                    )
                    self._stats["last_ytc_dedicated"] = datetime.now(timezone.utc).isoformat()
                    self._stats["ytc_dedicated_runs"] = (
                        self._stats.get("ytc_dedicated_runs", 0) + 1
                    )
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
                    log.info(f"[YTC-DEDICATED] run produced no report: {session_id}")
            except asyncio.CancelledError:
                log.info("[YTC-DEDICATED] cancelled")
                raise
            except Exception as e:
                log.error(f"[YTC-DEDICATED] run failed: {e}", exc_info=True)

            try:
                await asyncio.sleep(ytc_interval)
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

        REBUILD_AFTER_S = 60 * 60  # 1 hour

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
                            "[BM25] incremental +%d → index size: %d docs, vocab: %d, last_built: %s",
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
                            stats.get("docs", 0), last_built,
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
                success_count, len(_CITIES), event_total, elapsed,
            )

            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise
