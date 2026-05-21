"""
NCL Autonomous Scheduler
========================

Background task scheduler that makes NCL a true autonomous second brain.
Runs continuous loops for:

1. Intelligence Scanning (Awarebot) — X/YouTube/Reddit monitoring
2. Future Prediction — Ensemble forecasting with convergence detection
3. Council Auto-Spawn — Triggers council deliberation on high-signal events
4. Memory Consolidation — Periodic merge and decay processing
5. AAC War Room Sync — Pulls market regime data from AAC forecasters
6. MWP Workspace Health — Monitors pipeline stage health

All intervals are configurable via ncl.yaml or environment variables.
"""

import asyncio
import fcntl
import json
import logging
import os
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
            "aac_syncs": 0,
            "high_signals_detected": 0,
            "started_at": None,
            "last_scan": None,
            "last_prediction": None,
            "last_council": None,
            "last_consolidation": None,
            "last_aac_sync": None,
            "intel_briefs_generated": 0,
            "intel_collections_run": 0,
            "intel_alerts_pushed": 0,
            "last_intel_brief": None,
            "last_intel_collection": None,
        }

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
            )
            log.info("  Awarebot agent: ACTIVE (unified intelligence pipeline)")
        except Exception as e:
            log.error(f"  Awarebot agent: FAILED to initialize: {e}")
            self.awarebot = None

        # Journal system
        try:
            self._journal_store = JournalStore(
                data_dir=str(self.data_dir),
                memory_store=self.brain.memory_store if self.brain else None,
                working_context=self._working_context,
            )
            self._reflection_engine = ReflectionEngine(self._journal_store)
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
            asyncio.create_task(self._aac_sync_loop(), name="ncl-aac-sync"),
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

        # Journal reflection task (needs _journal_store to exist)
        if self._journal_store and self._reflection_engine:
            self._tasks.append(
                asyncio.create_task(self._journal_reflection_loop(), name="ncl-journal-reflection")
            )

        # Night Watch — nightly 2am ET health audit
        self._tasks.append(
            asyncio.create_task(self._night_watch_loop(), name="ncl-night-watch")
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
            "ncl-aac-sync": self._aac_sync_loop,
            "ncl-workspace": self._workspace_health_loop,
            "ncl-mandate-purge": self._mandate_purge_loop,
            "ncl-feedback-synth": self._feedback_synthesis_loop,
            "ncl-working-ctx": self._working_context_loop,
            "ncl-night-watch": self._night_watch_loop,
            "ncl-journal-reflection": self._journal_reflection_loop,
        }
        # Awarebot agent is restarted via its own .run() method
        if self.awarebot:
            self._task_factories["ncl-awarebot-agent"] = self.awarebot.run

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
                        # Create a synthetic pump prompt for the council
                        session = await self.brain.council_engine.spawn_council(
                            prompt=council_prompt,
                            context={
                                "trigger": council_trigger,
                                "autonomous": True,
                                "signal_count": len(council_flags) if council_flags else 0,
                                "timestamp": now.isoformat(),
                            },
                        )

                        if session:
                            # Store council output in memory
                            await self.brain.memory_store.create_unit(
                                content=(
                                    f"Autonomous council ({council_trigger}): "
                                    f"{session.get('consensus', '')[:500]}"
                                ),
                                source=f"autonomous:council:{council_trigger}",
                                importance=90.0,
                                tags=["council", "autonomous", council_trigger],
                            )

                            # Clear processed flags
                            await self._clear_council_flags()

                            self._stats["councils_auto_spawned"] += 1
                            self._stats["last_council"] = now.isoformat()

                            log.info(f"[COUNCIL-AUTO] Session complete — "
                                     f"consensus={session.get('consensus_score', 0):.0f}%")

                            await self._log_autonomous_event("council_auto_spawned", {
                                "trigger": council_trigger,
                                "consensus_score": session.get("consensus_score", 0),
                                "mandates_proposed": len(session.get("mandates", [])),
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

    # ─── LOOP 5: AAC War Room Sync ─────────────────────────────

    async def _aac_sync_loop(self) -> None:
        """
        Pull market regime data from AAC forecasters.

        Queries AAC's health endpoint and market data APIs to sync:
        - Current market regime classification
        - Crypto regime signals (8 formulas)
        - Stock opportunity rankings
        - Prediction market positions
        - P&L and risk metrics

        Stores as memory units for council access.
        """
        await asyncio.sleep(120)  # Wait for services to stabilize

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[AAC-SYNC] Emergency stop active — halting loop")
                break
            try:
                aac_data = {}

                # Try AAC health endpoint.
                # json.loads() is called on the event loop after each to_thread()
                # HTTP call completes. These are small health/status responses
                # (typically <10 KB) so parsing on the event loop is acceptable;
                # wrapping in a second to_thread() would add overhead without
                # meaningful benefit.
                try:
                    aac_health = await asyncio.to_thread(
                        self._http_get, "http://localhost:8080/health"
                    )
                    if aac_health:
                        aac_data["health"] = json.loads(aac_health)
                except Exception:
                    pass

                # Try AAC War Room URL if configured
                war_room_url = self.config.aac_war_room_url
                if war_room_url:
                    try:
                        regime_data = await asyncio.to_thread(
                            self._http_get, f"{war_room_url}/regime"
                        )
                        if regime_data:
                            aac_data["market_regime"] = json.loads(regime_data)
                    except Exception:
                        pass

                    try:
                        positions_data = await asyncio.to_thread(
                            self._http_get, f"{war_room_url}/positions"
                        )
                        if positions_data:
                            aac_data["positions"] = json.loads(positions_data)
                    except Exception:
                        pass

                # Try NCC Master for execution status
                try:
                    ncc_health = await asyncio.to_thread(
                        self._http_get, "http://localhost:8765/health"
                    )
                    if ncc_health:
                        aac_data["ncc_status"] = json.loads(ncc_health)
                except Exception:
                    pass

                # Try BRS Dashboard for revenue metrics
                try:
                    brs_data = await asyncio.to_thread(
                        self._http_get, "http://localhost:8000/matrix/sitrep"
                    )
                    if brs_data:
                        aac_data["brs_sitrep"] = json.loads(brs_data)
                except Exception:
                    pass

                if aac_data:
                    # Store pillar sync data in memory
                    await self.brain.memory_store.create_unit(
                        content=(
                            f"Pillar sync: reached {list(aac_data.keys())} at "
                            f"{datetime.now(timezone.utc).isoformat()}"
                        ),
                        source="autonomous:aac_sync",
                        importance=40.0,
                        tags=["aac", "sync", "pillar_status", "autonomous"],
                    )

                    self._stats["aac_syncs"] += 1
                    self._stats["last_aac_sync"] = datetime.now(timezone.utc).isoformat()

                    log.info(f"[AAC-SYNC] Pillar sync complete — "
                             f"reached: {list(aac_data.keys())}")

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[AAC-SYNC] Sync error: {e}", exc_info=True)

            # Sync every 15 minutes
            await asyncio.sleep(900)

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
        """
        import pytz
        et = pytz.timezone("US/Eastern")

        log.info("[NIGHT-WATCH] Loop started — will fire at 2:00 AM ET nightly")

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

            # ── Run all checks ────────────────────────────────────────
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

            # ── Push notification via ntfy ─────────────────────────────
            try:
                await self._nw_push_notification(issues, critical, has_warnings)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[NIGHT-WATCH] Push notification failed: {e}", exc_info=True)

            await self._log_autonomous_event("night_watch", {
                "issues_count": len(issues),
                "critical": critical,
                "issues": issues[:20],
            })

            # LLM-powered analysis phase
            try:
                await self._night_watch_analyst(issues, len(issues) > 0, critical)
            except Exception as exc:
                log.error("[NIGHT-WATCH] Analyst phase failed: %s", exc)

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
                log.info(f"[NIGHT-WATCH] Push sent: {title} ({len(issues)} issues)")
        except Exception as e:
            log.error(f"[NIGHT-WATCH] ntfy push failed: {e}")

    # ─── NIGHT WATCH ANALYST: LLM-powered nightly analysis ─────────

    async def _night_watch_analyst(
        self, deterministic_issues: list[str], has_warnings: bool, critical: bool
    ) -> None:
        """
        LLM-powered analysis phase for Night Watch.

        Runs AFTER the deterministic health checks. Collects operational data
        from multiple subsystems, triages with Haiku, synthesizes with Sonnet,
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
        # 4 Haiku calls ~2000 tok in + ~500 tok out each = ~$0.014
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

        haiku_model = "claude-haiku-4-5-20251001"
        sonnet_model = "claude-sonnet-4-5-20241022"

        # Haiku cost rates: $0.80/1M input, $4.00/1M output
        # Sonnet cost rates: $3.00/1M input, $15.00/1M output

        haiku_outputs: dict[str, str] = {}
        total_llm_cost = 0.0

        async def _call_anthropic(
            model: str, prompt: str, max_tokens: int, label: str
        ) -> tuple[str, float]:
            """Make a single Anthropic API call, return (text, cost_usd)."""
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
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

                # Compute cost
                if model == haiku_model:
                    cost = (input_tokens * 0.80 + output_tokens * 4.00) / 1_000_000
                else:
                    cost = (input_tokens * 3.00 + output_tokens * 15.00) / 1_000_000

                log.info(
                    "[NIGHT-WATCH] LLM call '%s': %d in / %d out tokens, $%.4f",
                    label, input_tokens, output_tokens, cost,
                )
                return text, cost

        # ── Haiku triage calls ────────────────────────────────────────

        haiku_prompts = {
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

        for label, prompt in haiku_prompts.items():
            try:
                # Budget check before each call
                if not await tracker.can_spend("anthropic", 0.01):
                    log.warning("[NIGHT-WATCH] Budget hit mid-analysis — stopping Haiku calls")
                    break

                text, cost = await _call_anthropic(haiku_model, prompt, 1024, label)
                haiku_outputs[label] = text
                total_llm_cost += cost

                await tracker.record(
                    "anthropic", cost, "night_watch",
                    f"Night Watch Haiku triage: {label}",
                    {"model": haiku_model, "phase": "triage", "label": label},
                )
            except Exception as e:
                log.error("[NIGHT-WATCH] Haiku call '%s' failed: %s", label, e)
                haiku_outputs[label] = f"[Analysis failed: {type(e).__name__}: {e}]"

        # ── Sonnet synthesis call ─────────────────────────────────────
        synthesis_text = ""
        if haiku_outputs:
            try:
                if not await tracker.can_spend("anthropic", 0.03):
                    log.warning("[NIGHT-WATCH] Budget hit — skipping Sonnet synthesis")
                else:
                    subsystem_reports = "\n\n".join(
                        f"=== {label.upper()} ===\n{text}"
                        for label, text in haiku_outputs.items()
                    )

                    deterministic_summary = (
                        "\n".join(f"  - {i}" for i in deterministic_issues[:15])
                        if deterministic_issues else "None — all deterministic checks passed."
                    )

                    sonnet_prompt = (
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
                        sonnet_model, sonnet_prompt, 2048, "synthesis"
                    )
                    total_llm_cost += cost

                    await tracker.record(
                        "anthropic", cost, "night_watch",
                        "Night Watch Sonnet synthesis",
                        {"model": sonnet_model, "phase": "synthesis"},
                    )
            except Exception as e:
                log.error("[NIGHT-WATCH] Sonnet synthesis failed: %s", e)
                synthesis_text = ""

        # ── Fallback: if no synthesis, use deterministic results ──────
        if not synthesis_text:
            synthesis_text = (
                "STATUS: UNKNOWN\n\n"
                "LLM analysis was unavailable. Deterministic check results:\n"
                + ("\n".join(f"  - {i}" for i in deterministic_issues) if deterministic_issues
                   else "All deterministic checks passed.")
                + "\n\nHaiku triage outputs:\n"
                + "\n".join(f"  [{k}]: {v[:200]}" for k, v in haiku_outputs.items())
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
        try:
            # Truncate for ntfy (max ~4KB)
            push_body = synthesis_text
            if len(push_body) > 3800:
                push_body = push_body[:3800] + "\n\n... (truncated — full brief saved to disk)"

            push_body += f"\n\nLLM analysis cost: ${total_llm_cost:.4f}"

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
                log.info("[NIGHT-WATCH] Analyst brief pushed via ntfy: %s", nw_title)
        except Exception as e:
            log.error("[NIGHT-WATCH] Analyst ntfy push failed: %s", e)

        log.info(
            "[NIGHT-WATCH] Analyst phase complete — total LLM cost: $%.4f, "
            "haiku calls: %d, synthesis: %s",
            total_llm_cost, len(haiku_outputs),
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
        """Send an urgent ntfy alert when a task exhausts its restart budget."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                await client.post(
                    "https://ntfy.sh/ncl-natrix-intel-7x9k",
                    content=(
                        f"Task '{task_name}' has crashed 3 times and will not be restarted.\n\n"
                        f"Last error: {error}"
                    ).encode(),
                    headers={
                        "Title": "NCL Supervisor Alert",
                        "Priority": "5",
                        "Tags": "rotating_light",
                    },
                )
            log.info("[SUPERVISOR] ntfy alert sent for task '%s'", task_name)
        except Exception as e:
            log.warning("[SUPERVISOR] Failed to send ntfy alert: %s", e)

    # ─── Helpers ───────────────────────────────────────────────

    # ─── LOOP 9: Heartbeat ──────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """Log a heartbeat every 60 seconds so operators can verify the scheduler
        is alive without checking individual loop stats."""
        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[HEARTBEAT] Emergency stop active — halting loop")
                break
            try:
                active = [t.get_name() for t in self._tasks if not t.done()]
                log.info(
                    "[SCHEDULER][HEARTBEAT] alive — active_tasks=%d signal_buffer=%d "
                    "scans=%d predictions=%d councils=%d",
                    len(active),
                    len(self._signal_buffer),
                    self._stats["scans_completed"],
                    self._stats["predictions_run"],
                    self._stats["councils_auto_spawned"],
                )
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
